---
title: "Node.js のイベントループとスレッドモデルを直視する — 性能・可用性・難解バグの根 (第2部)"
status: plan
---

## 想定読者と前提

- 第1部「Node.js を JS ランタイムとして捉え直す」を読んだ前提
- Node.js を業務で使い、`async/await` も `setImmediate` も `process.nextTick` も書いたことはあるが、**どの非同期がどこで実行されているか** を体系的に説明できないレベル
- p99 スパイク / イベントループ詰まり / OOM / graceful shutdown 失敗を「経験」で扱ってきた人

## この記事(第2部)の立場

- 文法や API テクニックではなく、**プロセス内部の同時実行構造** を扱う
- 性能(スループット・p99)・可用性(DoS 耐性・落ち方)・難解バグ(再現しないハング・順序逆転・OOM)の**根** を、libuv と V8 から説明する
- 「やるべきプラクティス」ではなく「なぜそうなるのか」を中心に

## 第2部で答える問い

- libuv のイベントループは具体的に何をしているのか(6フェーズ + microtask)
- 「非同期」と書かれた API が、実際にどこで実行されているのか(JS スレッド / libuv スレッドプール / `worker_threads` / カーネル)
- なぜ "1リクエストが重いだけで全リクエストが詰まる" のか、その回避は何のトレードオフか
- V8 のヒープモデルが、OOM や p99 スパイクの「形」をどう決めているか

## 構成

### 1. はじめに: 「非同期」は一枚岩ではない

- Node の「非同期」には少なくとも 4 種類ある
  1. V8 の microtask(`Promise.then`, `queueMicrotask`)
  2. `process.nextTick` キュー(Node 独自、microtask とは別キュー)
  3. libuv のフェーズに乗るタイマー / I/O / immediate / close
  4. libuv の Worker Pool(別 OS スレッドで C++ が動く)
  5. `worker_threads`(別 isolate / 別 event loop)
- どこで動いているかで「ブロックの伝播」「優先順位」「観測の仕方」がすべて変わる

### 2. libuv のイベントループは 6 フェーズ + α

セクション概要:
- フェーズの公式図と意味を一つずつ
- timers / pending callbacks / idle, prepare / poll / check / close
- I/O backend: Linux=epoll, OSX/BSD=kqueue, SunOS=event ports, Windows=IOCP
- 公式ループ反復シーケンス(now 初期化 → due timers → pending callbacks → ... → check → close → now 更新 → due timers)
- 「now は反復中に更新されない」帰結:処理中に due になったタイマーは次反復まで動かない
- poll フェーズの "ハード上限" による starvation 防止
- Node が公開していないフェーズ(`idle`, `prepare`)の存在

根拠:
- https://nodejs.org/learn/asynchronous-work/event-loop-timers-and-nexttick
- https://docs.libuv.org/en/v1.x/design.html
- https://github.com/libuv/libuv/discussions/4462

### 3. microtask と `process.nextTick` の優先順位

- `process.nextTick` は「技術的にはイベントループの一部ではない」公式記述
- nextTick キュー → microtask キュー(Promise / queueMicrotask) → 次フェーズへ
- CJS と ESM で「最初の評価が microtask queue に乗っているか」が違うため、ESM では `queueMicrotask` が `process.nextTick` より先に走る
- 再帰的 `process.nextTick` による I/O starvation
- 公式が `queueMicrotask` を「ユーザーランドの第一候補」と明記している事実

根拠:
- https://nodejs.org/api/process.html
- https://nodejs.org/learn/asynchronous-work/event-loop-timers-and-nexttick
- https://nodejs.org/learn/asynchronous-work/understanding-setimmediate

### 4. `setImmediate` vs `setTimeout(fn, 0)`: 順序が決まる場合と決まらない場合

- I/O サイクル内(`fs.readFile` のコールバック内など)では `setImmediate` が**常に**先
  - 根拠で「順序が保証される」と明記されている
- メインモジュール直下では順序は**非決定的**(プロセス負荷で揺れる)
- libuv 1.45 / Node 20 で「タイマーは poll 後のみ実行」に変更されたことの意味

根拠:
- https://nodejs.org/learn/asynchronous-work/event-loop-timers-and-nexttick
- https://nodejs.org/learn/asynchronous-work/understanding-setimmediate

### 5. libuv の Worker Pool: 「非同期」の片方の正体

- Node 公式が定義する 2 種類のスレッド:「1 Event Loop + k Workers」
- Worker Pool に乗るのは:
  - I/O: `fs`(同期 API と FSWatcher を除く)、DNS の `dns.lookup()` / `dns.lookupService()`
  - CPU: `crypto.pbkdf2`, `crypto.scrypt`, `crypto.randomBytes`, `crypto.randomFill`, `crypto.generateKeyPair`, `zlib`(同期版除く)
  - C++ アドオンが投入するタスク
- `UV_THREADPOOL_SIZE`:
  - **デフォルト 4**(libuv 公式)
  - 上限 1024(libuv 1.30.0 で 128 → 1024 に拡大)
  - 起動時の環境変数で設定が前提
  - libuv 1.45.0 でスレッドスタックが 8MB 固定に
- なぜ調整が必要か:長時間の Worker タスクが「一見無関係な他の Worker API」のレイテンシを引きずる
- DNS の落とし穴:Node の `dns.lookup` は **threadpool 経由**(`dns.resolve*` は async I/O)

根拠:
- https://nodejs.org/learn/asynchronous-work/dont-block-the-event-loop
- https://docs.libuv.org/en/v1.x/threadpool.html
- https://nodejs.org/api/fs.html

### 6. `worker_threads`: 別物の並列実行

- `node:worker_threads` は Stability: Stable
- 公式が明言:**CPU 集約型に有効、I/O 集約型では効果薄**(組み込み非同期 I/O のほうが効率的)
- 各 worker は独立した V8 Isolate + 独立した `uv_loop_t`
- 通信は `postMessage` / `MessageChannel` / `MessagePort`、`transferList` で MessagePort を移譲
- `worker.postMessageToThread()` の親子関係外通信、`ERR_WORKER_MESSAGING_FAILED` / `ERR_WORKER_MESSAGING_ERRORED` のエラー種別
- 診断: `worker.cpuUsage()`, `worker.getHeapSnapshot()`, `worker.getHeapStatistics()`, `worker.performance.eventLoopUtilization()`
- ヒープスナップショットは「single isolate に固有」── main thread から worker は見えない、逆も同じ

根拠:
- https://nodejs.org/api/worker_threads.html
- https://nodejs.org/api/v8.html

### 7. なぜ "1リクエストが重いだけで全リクエストが詰まる" のか

- Event Loop も Worker Pool も「1 度 1 活動」しかできない
- スループットの経験則:「各クライアントの仕事は常に小さく」
- 同期 API の代表例 = 地雷:`crypto.randomBytesSync`, `pbkdf2Sync`, `zlib.*Sync`, fs 同期 API(特に NFS 上)、`child_process.*Sync`
- DoS 観点:悪意ある入力で意図的に正規表現や JSON パースを重くさせる攻撃面(ReDoS、JSON DOS など)が成立する
- ミティゲーション:
  - Partitioning(`setImmediate` で chunk 化)
  - Offloading(Worker Pool / Computation Worker Pool / `worker_threads` への分離)
  - シリアライズコストとマルチコア利得のトレードオフ

根拠:
- https://nodejs.org/learn/asynchronous-work/dont-block-the-event-loop
- https://nodejs.org/learn/asynchronous-work/overview-of-blocking-vs-non-blocking

### 8. V8 ヒープ: OOM と GC スパイクの根

- 世代仮説(generational hypothesis)とヒープ分割: New Space / Old Space
- Scavenge(若いオブジェクト用、高頻度・小コスト):2 回生き残ると Old Space に昇格
- Mark-Sweep(Old Space 用、高コスト)
- フラグ:
  - `--max-old-space-size=4096` で Old Space 上限を 4GB に
  - `--max-semi-space-size` で New Space サイズを調整(minor GC 頻度に効く)
  - `--trace-gc` / `v8.setFlagsFromString('--trace-gc')` で GC ログ
  - `--expose-gc` + `global.gc()` は補助、自動 GC は止まらない
- ヒープスナップショットの罠:
  - 単一 isolate に固有(worker は別)
  - 取得時に「ヒープ実サイズの約 2 倍」のメモリを要する → OOM killer の引き金
  - 同期処理でヒープサイズに比例した時間ループをブロック
- V8 Heap Sandbox:ヒープ corruption をプロセス他領域に波及させない隔離設計

根拠:
- https://nodejs.org/learn/diagnostics/memory/understanding-and-tuning-memory
- https://nodejs.org/learn/diagnostics/memory/using-gc-traces
- https://nodejs.org/api/v8.html
- https://v8.dev/blog/sandbox

### 9. 難解バグの読み解き方(根からの逆引き)

事象 → 根の対応関係を整理する章:

- **イベントループ遅延が出る** → どの phase か?(timer? poll? check?)Worker Pool 飽和か?GC 停止か?
- **`unhandledRejection` / `uncaughtException` でプロセスが落ちる** → プロセス境界の話、回復不能な状態のシグナル
- **`setImmediate` と `setTimeout(fn, 0)` の順序が環境で変わる** → I/O コンテキスト内 / 外の違い
- **`fs` 経由のレイテンシが他 API を巻き込む** → 共有 threadpool の本質的特性
- **`dns.lookup` だけ p99 が悪い** → threadpool 経由であり、`dns.resolve*` への切り替え検討
- **`worker_threads` を増やしても I/O が速くならない** → 公式の通り I/O では効かない
- **heap snapshot を本番で取ると落ちる** → メモリ 2x の特性
- **タイマー精度が前と違う** → libuv 1.45 / Node 20 の挙動変更
- **graceful shutdown が完了しない** → keep-alive 接続、未完了の Worker タスク、close フェーズで待つもの

根拠:
- https://nodejs.org/learn/asynchronous-work/event-loop-timers-and-nexttick
- https://nodejs.org/learn/asynchronous-work/dont-block-the-event-loop
- https://nodejs.org/api/worker_threads.html
- https://nodejs.org/learn/diagnostics/memory/understanding-and-tuning-memory

### 10. まとめ

- Node.js を理解するとは、「JS が乗っているランタイムの構造」を理解すること
- 性能・可用性・難解バグはすべて、libuv のフェーズ・スレッド・V8 ヒープのどこかから出てくる
- 「同じ非同期」「同じ Promise」と思って書くと、Worker Pool の飽和や GC の特性、isolate 境界などで足元をすくわれる
- 困ったとき帰る場所:公式 "Don't Block the Event Loop"、libuv design overview、`v8` モジュール、`worker_threads` ドキュメント

## 根拠ファイル(調査結果)

- `temp/nodejs_fundamentals/facts_nodejs_fundamentals.md`
- `temp/nodejs_fundamentals/extract_eventloop_phases.json`
- `temp/nodejs_fundamentals/extract_blocking.json`
- `temp/nodejs_fundamentals/extract_worker_threads.json`
- `temp/nodejs_fundamentals/extract_v8_memory.json`
- `temp/nodejs_fundamentals/extract_uv_threadpool_size.json`
- `temp/nodejs_fundamentals/extract_setimmediate_settimeout.json`
- `temp/nodejs_fundamentals/extract_nexttick_microtask.json`

## 不足/留意

- 「graceful shutdown」「`SIGTERM` ハンドリング」「`AbortSignal` の正確なフックポイント」は公式情報の細部まで本調査では押さえきれていないため、本文では一般論+公式ドキュメント参照に留める
- 「JSON DOS の具体手口」は本文では概念紹介に留め、攻撃手法の詳細には踏み込まない
- 「Scavenge / Mark-Sweep の並行・インクリメンタル性」は公式 Docs の引用範囲外のため、Orinoco 等への参照リンクに留める
