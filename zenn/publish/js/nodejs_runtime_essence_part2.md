---
title: "Node.js のイベントループとスレッドモデルを直視する — 性能・可用性・難解バグの根 (第2部)"
emoji: "🟢"
type: "tech"
topics: ["nodejs", "javascript", "performance", "architecture", "libuv"]
published: false
---

## この記事について

[第1部](./nodejs_runtime_essence_part1)では、Node.js を「V8 + libuv + bindings + 標準モジュール」という合体構造として捉え直し、ブラウザの JS と何を共有していて何が別物なのかを整理した。

第2部はその内側に踏み込む。題材は次の 3 つ:

- **libuv のイベントループ**(6 フェーズの実体、microtask との関係、`process.nextTick` の位置)
- **Node のスレッドモデル**(libuv Worker Pool と `worker_threads`、どこに「非同期」が実装されているか)
- **V8 のヒープ**(OOM と GC スパイクが「どういう形」で出るか)

これら 3 つは、Node の **性能(スループット・p99)・可用性(DoS 耐性・落ち方)・難解バグ(再現しないハング、順序逆転、OOM)の根** になる。「やるべきプラクティス集」ではなく「なぜそれが必要になるのか」を、libuv と V8 から逆算して説明する。

対象読者は第1部と同じ:Node を日常的に使う中級〜上級エンジニアで、`async`/`await` の見た目には慣れているが、**どの非同期がどこで動いているか** を即答できないレベル。

## 0. 出発点: 「非同期」は一枚岩ではない

Node の「非同期」を**最低でも 4 種類**に分けられないと、この章以降の話は地に足が付かない。

| 種類 | どこで動く | 何が乗るか |
|------|-----------|------------|
| 1. microtask | V8 / メインスレッド | `Promise.then`, `queueMicrotask`, `await` の再開 |
| 2. `process.nextTick` キュー | Node / メインスレッド | `process.nextTick(fn)` |
| 3. libuv フェーズ | メインスレッド(libuv が回す) | timer, I/O コールバック, `setImmediate`, close |
| 4. libuv Worker Pool | **別 OS スレッド** | `fs` の Promise/cb 版, `dns.lookup`, `crypto.pbkdf2` 系, `zlib`, C++ アドオンタスク |

加えて `worker_threads` を使うと、

- 5. **別 Isolate + 別 event loop** が立ち上がり、上の 1〜4 をそのまま持つ

という構造が増える。

中級者が詰まる難解バグの多くは「1 つのコードを書いたら、その**どこ**で実行されたのか」が見えていないことから来る。これを地図にできれば、ほとんどの「再現しないハング」「順序が環境で変わる」「片方が遅い」は構造的に説明できる。

## 1. libuv のイベントループ: 6 フェーズの実体

Node のイベントループは libuv の `uv_loop_t` だ。**Node が公開している** フェーズは 6 つ。

```
   ┌───────────────────────────┐
┌─►│           timers          │ ◀── setTimeout / setInterval の発火
│  └───────────────┬───────────┘
│  ┌───────────────┴───────────┐
│  │     pending callbacks     │ ◀── 前反復で延期された I/O cb (例: TCP ECONNREFUSED)
│  └───────────────┬───────────┘
│  ┌───────────────┴───────────┐
│  │       idle, prepare       │ ◀── 内部利用 (Node ユーザーには公開されない)
│  └───────────────┬───────────┘
│  ┌───────────────┴───────────┐  ┌───────────────┐
│  │           poll            │◀─┤   incoming:   │
│  │                           │  │ connections,  │
│  │                           │  │  data, etc.   │
│  └───────────────┬───────────┘  └───────────────┘
│  ┌───────────────┴───────────┐
│  │           check           │ ◀── setImmediate の発火
│  └───────────────┬───────────┘
│  ┌───────────────┴───────────┐
└──┤      close callbacks      │ ◀── socket.on('close', ...) など
   └───────────────────────────┘
```

各フェーズの定義は公式に明記されている:

> ### pending callbacks
>
> This phase executes callbacks for some system operations such as types of TCP errors. For example if a TCP socket receives `ECONNREFUSED` ... This will be queued to execute in the pending callbacks phase.
>
> ### check
>
> This phase allows the event loop to execute callbacks immediately after the poll phase has completed. ... `setImmediate()` is actually a special timer that runs in a separate phase of the event loop.
>
> — https://nodejs.org/learn/asynchronous-work/event-loop-timers-and-nexttick

`idle, prepare` フェーズは libuv の内部用で、Node の JS からは触れない。libuv メンテナの bnoordhuis 本人がこう述べている:

> Idle: the event loop normally blocks waiting for I/O or a timer to expire ... uv_idle_start() makes it not block. ... Prepare: called before libuv polls for I/O; check handles are called afterwards. ... AFAIK, [Node] doesn't expose them.
>
> — https://github.com/libuv/libuv/discussions/4462

### 1.1 libuv の I/O backend と「ループは 1 スレッドに 1 つ」

libuv は OS のイベント通知機構を抽象化している:

- Linux: `epoll`
- macOS / BSD: `kqueue`
- SunOS: event ports
- Windows: IOCP

> — https://docs.libuv.org/en/v1.x/design.html

そして `uv_loop_t` は**スレッドにバインド**される。複数の event loop を別スレッドで動かすことは可能だが、**ループ自体はスレッドセーフではない**(原則)。これが「Node は基本シングルスレッドの非同期」と言われる構造的理由だ。

### 1.2 公式の反復シーケンスから読み取れること

libuv 公式 design overview のループ反復シーケンス(抜粋)を読むと、ループ 1 周は次のように進む:

1. ループの "now" を初期化
2. `UV_RUN_DEFAULT` なら due timer を実行
3. ループが生きているか判定(active handles / requests / closing handles のいずれかがあれば alive)
4. **pending callbacks** を呼ぶ(前反復で延期された I/O 完了コールバック)
5. ... (poll など中間ステップ)
9. **check** ハンドルのコールバックを呼ぶ(I/O ブロック直後)
10. **close** コールバックを呼ぶ
11. ループの "now" を更新
12. **due timer** を再度実行

> — https://docs.libuv.org/en/v1.x/design.html

ここで読み取るべき要点は 2 つ:

- **「now」はループ反復中に更新されない**。だから、コールバック処理中に経過時間が積まれて「もう発火すべき」になったタイマーがあっても、**そのループ反復中には動かない**(=次反復に持ち越し)。これがタイマー精度の理論上限を決めている。
- **poll フェーズには starvation 対策のハード上限がある**:

> To prevent the poll phase from starving the event loop, libuv (the C library that implements the Node.js event loop and all of the asynchronous behaviors of the platform) also has a hard maximum (system dependent) before it stops polling for more events.
>
> — https://nodejs.org/learn/asynchronous-work/event-loop-timers-and-nexttick

「I/O が大量に詰まっても他フェーズが完全に止まることはない」のはこのおかげだ。

### 1.3 libuv 1.45 (Node 20) のタイマー実行順変更

公式が地味だが重要な変更点として書いている:

> Starting with libuv 1.45.0 (Node.js 20), the event loop behavior changed to run timers only after the poll phase, instead of both before and after as in earlier versions. This change can affect the timing of `setImmediate()` callbacks and how they interact with timers in certain scenarios.
>
> — https://nodejs.org/learn/asynchronous-work/event-loop-timers-and-nexttick

つまり Node 18 以下と Node 20 以降で、**タイマーと `setImmediate` の競合状況が変わる**。「Node 18 では再現しない順序逆転が Node 20 でだけ出る」というバグはこの変更に当たっている可能性がある。

## 2. microtask と `process.nextTick` の位置: 公開フェーズの「外側」

ここが多くの中級者がつまずく場所だ。

`process.nextTick` は**フェーズの外**にある。公式が次のように明示している:

> `process.nextTick()` is not technically part of the event loop. Instead, the `nextTickQueue` will be processed after the current operation is completed, regardless of the current phase of the event loop.
>
> — https://nodejs.org/learn/asynchronous-work/event-loop-timers-and-nexttick

つまり「現在の operation 完了直後」(= C/C++ ハンドラから JS への遷移単位の境界)で nextTick キューが flush される。各 libuv フェーズの境界、I/O コールバックの直後、`Promise` の解決直後 ── そのすべての隙間で nextTick が走る。

microtask キュー(`Promise.then` / `queueMicrotask`)も、同じく「フェーズの間で flush される」が、**nextTick の後** に処理される(CJS の場合)。

### 2.1 優先順位の正確な絵

```
  [ libuv フェーズ完了 ]
       │
       ├──► nextTick キューを全部 flush
       │       │
       │       ├──► その間に積まれた nextTick も全部 flush
       │       │
       │     (空になるまで)
       │
       ├──► microtask キューを全部 flush
       │       │
       │       ├──► その間に積まれた microtask も全部 flush
       │       │
       │     (空になるまで)
       │
   [ 次の libuv フェーズへ ]
```

### 2.2 ESM と CJS で優先順位が逆転する話

これは第1部でも触れたが、第2部でも重要なので再確認しておく。

> However, due to the implementation of ECMAScript Modules, ... `queueMicrotask()` callbacks are always executed before `process.nextTick()` callbacks within ES modules. This is because ES modules are loaded as part of a microtask queue and therefore the entire script is already inside a microtask queue when `process.nextTick()` is called.
>
> — https://nodejs.org/api/process.html

つまり ESM のトップレベルで `process.nextTick` と `queueMicrotask` を両方呼ぶと、**microtask のほうが先に走る**。「Node CJS で動くテストを `.mjs` に移植したら順序が変わってテストが落ちる」── このケースの根はここだ。

### 2.3 再帰 `process.nextTick` による I/O starvation

`process.nextTick` キューはフェーズ間で **空になるまで** flush される。だから内部で再度 nextTick を積むと、ループは次フェーズに進めない。これを延々繰り返すと **I/O コールバックの順番が永遠に来ない**(=poll フェーズに到達できない)。

公式は「**API は常に非同期であるべき** という設計哲学のためにこの仕組みが残っている」と説明したうえで、ユーザーランドの第一候補としては `queueMicrotask` を推奨している。

> In most userland use cases, `queueMicrotask()` provides a portable and reliable way of deferring execution that works across multiple JavaScript platform environments and should be favored over `process.nextTick()`.
>
> — https://nodejs.org/api/process.html

「自分は再帰 nextTick なんて書かない」と思っていても、**ライブラリの内部実装で nextTick が再帰されているケース**があり、そうしたライブラリを高頻度で叩くと意外なところで I/O が遅くなる ── これは典型的な「再現しない p99 スパイク」のシナリオだ。

## 3. `setImmediate` vs `setTimeout(fn, 0)`: 順序の理論と現実

第1部で結論だけ書いた部分を、構造から説明し直す。

### 3.1 I/O サイクル内では `setImmediate` が必ず先

> When called within an I/O cycle, the immediate callback is always executed first.
>
> — https://nodejs.org/learn/asynchronous-work/event-loop-timers-and-nexttick

なぜか:

- I/O コールバックは **poll フェーズ内**で実行される
- そこで `setImmediate` を積むと、**直後の check フェーズ**で発火する
- 同じところで `setTimeout(fn, 0)` を積むと、**次反復の timers フェーズ**まで持ち越し
- poll → check → close → 次の timers の順なので、必ず `setImmediate` が先

### 3.2 メインモジュール直下では非決定的

メインモジュールが評価される時点ではまだ I/O サイクルに入っておらず、`setImmediate` と `setTimeout(fn, 0)` のどちらが先に発火するかは、

- 初回ループ突入までに `setTimeout` の "now" が来てしまうか
- 「now」の更新タイミングと OS のスケジューラ揺れ

に依存する。だから**プロセス負荷で順序が揺れる**。

```bash
$ node -e "setTimeout(() => console.log('T'), 0); setImmediate(() => console.log('I'));"
# 実行ごとに T → I だったり I → T だったりする
```

この事実が公式で明示されていることを知っておくと、「同じコードがローカルと CI で順序が違う」というバグレポートの 9 割は数秒で説明できる。

## 4. libuv の Worker Pool: 「非同期 I/O」の実は別スレッドで動いている部分

Node の公式は「**2 種類のスレッド**」という整理を提示している:

> Node.js has two types of threads: one Event Loop and `k` Workers. The Event Loop is responsible for JavaScript callbacks and non-blocking I/O, and a Worker executes tasks corresponding to C++ code that completes an asynchronous request, including blocking I/O and CPU-intensive work.
>
> — https://nodejs.org/learn/asynchronous-work/dont-block-the-event-loop

つまり「Node は **シングルスレッド** だ」というのは厳密には正しくない。**メインの JS スレッドが 1 本、加えて libuv が管理する Worker スレッドが k 本(デフォルト 4)** いる。

### 4.1 何が Worker Pool に乗るか

公式の網羅リスト:

- **I/O 系**
  - DNS: `dns.lookup()`, `dns.lookupService()`
  - File System: `fs.FSWatcher()` と明示同期 API を除く **全 fs API**
- **CPU 系**
  - Crypto: `crypto.pbkdf2()`, `crypto.scrypt()`, `crypto.randomBytes()`, `crypto.randomFill()`, `crypto.generateKeyPair()`
  - Zlib: 明示同期を除く **全 zlib API**

> — https://nodejs.org/learn/asynchronous-work/dont-block-the-event-loop

加えて、**C++ アドオン**は `uv_queue_work()` 経由で同じ Worker Pool に追加タスクを積めるので、`sharp`(画像処理)、`bcrypt`、`argon2`、`@node-rs/*`(Rust 製ネイティブモジュール)、データベースドライバの一部がここに乗る。

ここで重要なのは:

1. **`net` / HTTP は Worker Pool を使わない**(epoll/kqueue/IOCP で直接非同期)
2. **`dns.lookup` は Worker Pool 経由、`dns.resolve*` は async I/O**

(2) は地味だが効く。`fetch` / `http.request` は内部で `dns.lookup` を呼ぶ実装が多いので、**DNS 解決遅延が libuv Worker Pool を埋める** ことがある。p99 のスパイクが「DNS が原因なのに Worker Pool 全体に波及する」典型パターンだ。

### 4.2 `UV_THREADPOOL_SIZE`: デフォルトと上限

libuv 公式が明記している:

> The default size of the threadpool is 4, but it can be changed at startup time by setting the `UV_THREADPOOL_SIZE` environment variable to any value (the absolute maximum is 1024).
>
> — https://docs.libuv.org/en/v1.x/threadpool.html

ポイント:

- **デフォルト 4**(物理 CPU 数と無関係)
- **絶対上限 1024**(libuv 1.30.0 で 128 → 1024 に拡大、Node 12.6.0 で反映)
- **プロセス起動時の環境変数**で設定する(libuv ドキュメントの建前)
- threadpool は libuv 1.45.0 で **スレッドスタック 8MB 固定** に変更
- threadpool は **グローバル**、複数 event loop で共有される

```bash
UV_THREADPOOL_SIZE=16 node server.js
```

### 4.3 なぜ調整するか: 一見無関係な API が互いを引きずる現実

Node v12 系の CLI ドキュメントが、調整の動機を一文で書いている:

> Because the threadpool has a fixed size, if for whatever reason one of these APIs takes a long time, the performance of other (seemingly unrelated) APIs that run in the threadpool will experience degraded performance. In order to mitigate this issue, ... set the `UV_THREADPOOL_SIZE` environment variable to a value greater than 4.
>
> — https://nodejs.org/download/release/v12.5.0/docs/api/cli.html

これがおそらく **Node のパフォーマンスチューニングで最も重要な構造的事実** だ。具体的に何が起きるかと言うと:

- `bcrypt.hash()` を 4 並列で呼ぶと、**`fs.readFile` も `dns.lookup` も `crypto.pbkdf2` も全部待たされる**
- Worker は 4 本しかない、全部 bcrypt で塞がっているから

これは Node の「非同期 = ノンブロッキング」という素朴な信仰を裏切る部分だ。**Worker Pool に乗る非同期は、別 OS スレッドで動いているが、本数が限られているため互いに競合する**。並列性の暗黙の上限が `UV_THREADPOOL_SIZE` で決まっている、ということを知っているかどうかで p99 の見え方は変わる。

### 4.4 公式の同期 API 地雷リスト

> Many Node.js core APIs offer synchronous as well as asynchronous versions ... Some of these synchronous APIs are listed below:
>
> - Encryption: `crypto.randomBytes` (synchronous version), `crypto.randomFillSync`, `crypto.pbkdf2Sync`
> - Compression: `zlib.inflateSync`, `zlib.deflateSync`
> - File System: ... avoid the synchronous file system APIs. For example, if the file you access is in a distributed file system like NFS, access times can vary widely.
> - Child Process: `child_process.spawnSync`, `child_process.execSync`, `child_process.execFileSync`
>
> — https://nodejs.org/learn/asynchronous-work/dont-block-the-event-loop

これらは**メインの JS スレッド上で同期的に動く**ので、呼んでいる間サーバ全体が止まる。書き慣れていないモジュールから呼んでいたら、p99 を見たときに突然刺さる類いの地雷だ。

## 5. `worker_threads`: 並列実行のもう 1 つの形

`node:worker_threads` は Stability: Stable で、用途も公式が明言している。

> Workers (threads) are useful for performing CPU-intensive JavaScript operations. They do not help much with I/O-intensive work. The Node.js built-in asynchronous I/O operations are more efficient than Workers can be.
>
> — https://nodejs.org/api/worker_threads.html

つまり:

- **CPU 集約型** には効く
- **I/O 集約型** には**効かない**(組み込みの非同期 I/O のほうが速い)

「リクエストごとに Worker を作って I/O を投げる」設計が遅くなる理由は構造から出ている。Worker 間通信のコスト + I/O は元々ノンブロッキング、という事実だ。

### 5.1 構造: 独立した Isolate と event loop

各 `Worker` は **独立した V8 Isolate** と **独立した `uv_loop_t`** を持つ。これは Node の C++ コード上で見ても、Isolate も event loop も Worker ごとに別物だ。

> Currently, every `Environment` class is associated with: `Isolate`, `Context`, ...
>
> — https://github.com/libuv/ci-tmp-libuv-node/blob/master/src/README.md

帰結:

- **メモリは共有されない**(同じプロセスでも別ヒープ)
- 値の受け渡しは `postMessage`(構造化クローン)、`transferList`(所有権移譲)、`SharedArrayBuffer`(明示共有メモリ)のいずれか
- ヒープスナップショットは Isolate 固有 ── メインから取った snapshot に Worker のヒープは映らない、逆も同じ

> A heap snapshot is specific to a single V8 isolate. When using worker threads, a heap snapshot generated from the main thread will not contain any information about the workers, and vice versa.
>
> — https://nodejs.org/api/v8.html

これは **本番でメモリリーク調査をするときに必ずぶつかる事実** で、Worker を使っているアプリの heap dump は「メイン + 各 Worker」を個別に取らないと全体像が見えない。

### 5.2 メッセージングと診断

Worker は次の API を持つ:

- `worker.postMessage(value, [transferList])` / `worker.postMessageToThread(threadId, ...)`
- `worker.cpuUsage()`
- `worker.getHeapSnapshot([options])`
- `worker.getHeapStatistics()`
- `worker.performance.eventLoopUtilization()`
- `worker.startCpuProfile()` / `worker.startHeapProfile()`
- `worker.threadId`, `worker.threadName`
- `worker.ref()` / `worker.unref()`
- `worker.terminate()`
- `worker.resourceLimits`

> — https://nodejs.org/api/worker_threads.html

`eventLoopUtilization()` は本番運用で特に強力で、「メインスレッドのループがどれだけ忙しいか」を計測できる(中央値 0.0〜1.0、1.0 が完全飽和)。Worker のループでも同じく取れるので、メイン詰まりかWorker 詰まりかの切り分けが定量化できる。

## 6. なぜ "1 リクエストが重いだけで全体が詰まる" のか

ここまでの構造を踏まえると、Node の可用性の本質がはっきりする。

> If a thread is taking a long time to execute a callback (Event Loop) or a task (Worker), we call it "blocked". While a thread is blocked working on behalf of one client, it cannot handle requests from any other clients.
>
> — https://nodejs.org/learn/asynchronous-work/dont-block-the-event-loop

### 6.1 経験則

公式が言い切っている:

> Node.js is fast when the work associated with each client at any given time is "small".
>
> — https://nodejs.org/learn/asynchronous-work/dont-block-the-event-loop

「**各クライアントの仕事を常に小さく保つ**」。これが Node の性能設計の根幹で、フレームワークやライブラリの上に立つあらゆるベストプラクティスはここに収束する。

### 6.2 ミティゲーション: Partitioning と Offloading

公式が示す 2 つの戦略:

- **Partitioning**: 重い同期処理を `setImmediate` で分割し、他のリクエストにループを譲る
- **Offloading**: 重い計算を Worker Pool / `worker_threads` / 別プロセスに逃がす

```js
// Partitioning の例: 重い配列処理をチャンク化
function processChunk(arr, i, done) {
  if (i >= arr.length) return done();
  // 1回分の重い処理
  doExpensive(arr[i]);
  // 次のチャンクを次のループ反復に
  setImmediate(() => processChunk(arr, i + 1, done));
}
```

Offloading のトレードオフは、Worker 間の **シリアライズコスト** だ。`postMessage` で大きなデータを毎リクエスト送ると、シリアライズで取り戻すべきマルチコア利得を食い潰す。これを避けるために、

- 計算結果だけ送って入力は ID で参照する
- `SharedArrayBuffer` で生のメモリを共有する
- `transferList` で MessagePort を移譲する

といった工夫を入れる。公式も「シリアライズコストはマルチコア利用で相殺される」と書いているが、相殺できないケースは普通にあるので、**実測する** ことが前提だ。

### 6.3 DoS の構造

「悪意ある入力で重い処理を強要されるとサーバが詰まる」というのは、Node では**抽象論ではなく構造的に成立する** ことを公式が認めている。

> If it is possible that for certain input one of your threads might block, a malicious client could submit this "evil input", make your threads block, and keep them from working on other clients. This would be a Denial of Service attack.
>
> — https://nodejs.org/learn/asynchronous-work/dont-block-the-event-loop

ReDoS(壊滅的バックトラックを誘発する正規表現)、JSON DOS(ネスト深い JSON で同期パースを長時間化)、大きなアップロードでの同期解凍 ── どれも 1 リクエストの重さを全体のダウンに変換する。第1部で書いた「**ブラウザでは 1 タブの問題が Node ではプロセス全体の問題になる**」というのは、ここを念頭に置いた話だった。

## 7. V8 ヒープ: OOM と GC スパイクの根

最後に、Node プロセスの「メモリの形」を決めている V8 ヒープを見る。

### 7.1 世代別ヒープと GC アルゴリズム

V8 は **世代仮説(generational hypothesis)** を採る。

> V8's memory management is based on the generational hypothesis, the idea that most objects die young. Therefore, it separates the heap into generations to optimize garbage collection.
>
> — https://nodejs.org/learn/diagnostics/memory/understanding-and-tuning-memory

ヒープは大きく分けて 2 領域:

- **New Space**(若い世代):新規・短命オブジェクトの割り当て先。**小さく**、頻繁に GC される。
- **Old Space**(古い世代):長命オブジェクトが昇格してくる場所。**大きく**、GC は高コスト。

GC アルゴリズムも対応して 2 種類:

- **Scavenge**:New Space 対象。半空間コピーで生存オブジェクトを別領域に移す。2 回の Scavenge を生き残ったオブジェクトは Old Space に**昇格(promote)** される。
- **Mark-Sweep**:Old Space 対象。生存オブジェクトをマーク → 未マークを sweep。

> v8 will promote objects, not garbage collected after two Scavenge operations to the old space.
>
> — https://nodejs.org/learn/diagnostics/memory/using-gc-traces

「短命なものは Scavenge で安く回収、長命なものは Old Space で高くたまにまとめて」という発想だ。

### 7.2 ヒープサイズを決めるフラグ

実運用で覚えておく価値があるのは次の数本:

- `--max-old-space-size=4096` ── Old Space 上限を 4 GB に。例えば `node --max-old-space-size=4096 app.js`
- `--max-semi-space-size=64` ── New Space(の半空間)サイズ。**増やすと minor GC の頻度が下がる** が、Scavenge 自体のコストは上がる。
- `--trace-gc` ── GC ログを stderr に出す。本番でも比較的低コスト
- `--expose-gc` ── `global.gc()` で手動 GC を呼べるようになる。**自動 GC は止まらない**、補助のみ

> — https://nodejs.org/learn/diagnostics/memory/understanding-and-tuning-memory

`--trace-gc` の出力フォーマットは公式に解説がある:

```
[13973:0x110008000]  44 ms: Scavenge 2.4 (3.2) -> 2.0 (4.2) MB, 0.5 / 0.0 ms (...)
```

それぞれの意味:

| トークン | 意味 |
|---------|------|
| `13973` | プロセス PID |
| `0x110008000` | Isolate(JS ヒープインスタンス) |
| `44 ms` | プロセス開始からの経過時間 |
| `Scavenge` | GC のタイプ / フェーズ |
| `2.4 (3.2)` | GC 前の Heap used (MB) / Total heap (MB) |
| `2.0 (4.2)` | GC 後の Heap used (MB) / Total heap (MB) |
| `0.5 / 0.0 ms` | GC 滞在時間 |

> — https://nodejs.org/learn/diagnostics/memory/using-gc-traces

Old Space の Mark-Sweep が **10ms オーダーでイベントループを止める** ことがあるので、p99 スパイクの原因究明では `--trace-gc` を最初に試す価値がある。

### 7.3 ヒープスナップショットの罠

メモリリーク調査の定石はヒープスナップショットだが、本番で雑に取ると痛い。

> Creating a heap snapshot requires memory about twice the size of the heap at the time the snapshot is created. This results in the risk of OOM killers terminating the process.
>
> Generating a snapshot is a synchronous operation which blocks the event loop for a duration depending on the heap size.
>
> — https://nodejs.org/api/v8.html

つまり:

- **ヒープサイズの 2 倍のメモリを瞬間的に要求する** → OOM killer に殺される
- **同期処理** → その間サーバが完全停止する

「本番でヒープが膨らんでいるときに snapshot を取ったら、サーバが落ちた」というのは構造的に起きる事故だ。ヒープが大きいインスタンスでは、別プロセスにフェイルオーバさせた上で取るか、`v8.writeHeapSnapshot()` を低トラフィック時間帯に取るのが現実的な運用になる。

### 7.4 Isolate 単位という事実

> A heap snapshot is specific to a single V8 isolate. When using worker threads, a heap snapshot generated from the main thread will not contain any information about the workers, and vice versa.
>
> — https://nodejs.org/api/v8.html

繰り返しになるが、Worker を使っているアプリの heap dump は **メイン + 各 Worker 個別に** 取らないと全体像が見えない。Worker でリークしていてもメインの snapshot だけ見ていると気付けない。

### 7.5 V8 Heap Sandbox

V8 は、ヒープ corruption をプロセスの他領域に**波及させない隔離**を進めている。

> The basic idea behind the sandbox is to isolate V8's (heap) memory such that any memory corruption there cannot "spread" to other parts of the process' memory.
>
> — https://v8.dev/blog/sandbox

Node 運用者にとっての示唆は単純で:**最新の V8 を使うこと = セキュリティ対策**だ。古い Node を本番で長く走らせると、累積する V8 の修正を取り込めない。これは性能ではなく可用性の話だ。

## 8. 難解バグの読み解き方: 根からの逆引き

ここまでの構造を踏まえて、典型的な「再現しないバグ」「不可解な p99 スパイク」「落ちないはずなのに落ちた」を、根から逆引きできるようにする。

| 事象 | 怪しい根 | 確認するもの |
|------|---------|--------------|
| イベントループ遅延が出る | どの phase が詰まったか | `perf_hooks.monitorEventLoopDelay`、`eventLoopUtilization()`、`--trace-gc` |
| `unhandledRejection` でプロセスが落ちる | 回復不能状態のシグナル | `process.on('unhandledRejection', ...)` で観測、根本は Promise の握りつぶし |
| `setImmediate` と `setTimeout(fn, 0)` の順序が環境で変わる | I/O サイクル内 / 外の違い、libuv 1.45 の挙動変更 | コードがどこから呼ばれているか、Node のバージョン |
| `fs` のレイテンシが `dns.lookup` を巻き込む | 共有 Worker Pool の本質 | `UV_THREADPOOL_SIZE`、`bcrypt` 等のネイティブモジュールの使用箇所 |
| `dns.lookup` だけ p99 が悪い | threadpool 経由である事実 | `dns.resolve*` への切り替え、外部 DNS リゾルバの使用 |
| `worker_threads` を増やしても I/O が速くならない | 公式の通り I/O では効かない | 計算の Worker 化に絞る、入力をシリアライズしない設計 |
| heap snapshot を本番で取ると落ちる | メモリ 2x の特性 | 取得タイミング、フェイルオーバ、ヒープサイズの実測 |
| タイマー精度が前と違う | libuv 1.45 / Node 20 の挙動変更 | Node のメジャーバージョン |
| Old Space の GC でリクエストが詰まる | Mark-Sweep の停止時間 | `--trace-gc`、`--max-old-space-size` の調整、リークの除去 |
| graceful shutdown が完了しない | keep-alive、未完了の Worker、close 待ち | `server.close()` のコールバック、`AbortSignal`、`server.closeIdleConnections()` |
| `Buffer` を多く使うインスタンスでメモリが膨らむ | `Buffer` は V8 ヒープ外 | RSS とヒープサイズの差を観測 |

「現象 → 構造のどこに帰着するか」を 1 度通すと、Node の難解バグは「特殊な経験で解くもの」ではなくなる。むしろ「**libuv のフェーズか、Worker Pool か、Isolate か、ヒープか、のどれか**」しか答えがない、と言ってもよい。

## 9. まとめ: Node を理解するということ

第2部のメッセージ:

- **「Node はシングルスレッドのイベントループ」では情報量が足りない**。実際には libuv の 6 フェーズ + 2 種類の優先キュー(nextTick / microtask) + 共有 Worker Pool(別 OS スレッド)+ `worker_threads`(別 Isolate)が常に動いている。
- **「非同期」という言葉が指す実体は最低 5 種類**ある(microtask / nextTick / libuv フェーズ / Worker Pool / `worker_threads`)。どこで実行されているかで、ブロックの伝播・優先順位・観測の仕方がすべて変わる。
- **性能・可用性・難解バグは、構造のどこか 1 点に帰着する**。libuv のどのフェーズか、`UV_THREADPOOL_SIZE` の上限か、Isolate 境界か、V8 のヒープのどの世代か。あてずっぽうの最適化ではなく、構造から逆引きできる問題群だ。
- **公式ドキュメントが最強の参考書**。"Don't Block the Event Loop"、libuv design overview、`worker_threads`、`v8` モジュールのページは、頭の中に地図として残しておく価値がある。

第1部と合わせて、Node.js を「サーバで動く JavaScript」ではなく「**V8 + libuv + bindings + 標準モジュールが構成する独自のホスト環境**」として、構造から読み解けるようになっていれば、この記事の役目は果たせている。

ここから先は、各論(graceful shutdown、`AbortSignal`、`async_hooks`、`AsyncLocalStorage`、`perf_hooks`、Node の起動シーケンス、permissions モデル、permission policy、`--experimental-strip-types`、ESM ローダーフック)を、この地図のどこに置けるかを当てはめながら学んでいくフェーズになる。地図さえあれば、迷う頻度は確実に減る。

## 参考リンク

- Node.js 公式: [The Event Loop, Timers, and `process.nextTick()`](https://nodejs.org/learn/asynchronous-work/event-loop-timers-and-nexttick)
- Node.js 公式: [Don't Block the Event Loop (or the Worker Pool)](https://nodejs.org/learn/asynchronous-work/dont-block-the-event-loop)
- Node.js 公式: [Overview of Blocking vs Non-Blocking](https://nodejs.org/learn/asynchronous-work/overview-of-blocking-vs-non-blocking)
- Node.js 公式: [Understanding `process.nextTick()`](https://nodejs.org/api/process.html)
- Node.js 公式: [Understanding setImmediate()](https://nodejs.org/learn/asynchronous-work/understanding-setimmediate)
- Node.js 公式: [Worker threads](https://nodejs.org/api/worker_threads.html)
- Node.js 公式: [V8](https://nodejs.org/api/v8.html)
- Node.js 公式: [Understanding and Tuning Memory](https://nodejs.org/learn/diagnostics/memory/understanding-and-tuning-memory)
- Node.js 公式: [Tracing garbage collection](https://nodejs.org/learn/diagnostics/memory/using-gc-traces)
- libuv 公式: [Design overview](https://docs.libuv.org/en/v1.x/design.html)
- libuv 公式: [Thread pool work scheduling](https://docs.libuv.org/en/v1.x/threadpool.html)
- V8 公式: [The V8 Sandbox](https://v8.dev/blog/sandbox)
