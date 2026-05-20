---
title: "Node.js を「JS ランタイム」として捉え直す — ブラウザJSと共通なもの、別物なもの (第1部)"
emoji: "🟩"
type: "tech"
topics: ["nodejs", "javascript", "architecture", "v8", "libuv"]
published: false
---

## この記事について

Node.js は毎日書いている。`async/await`も`fs.readFile`も`process.env`も、手は勝手に動く。

それでも、後輩や同僚から「**Node.js って結局なに?ブラウザの JS と何が違うの?**」と聞かれて、構造として短く答えられるかと言うと、案外詰まる人が多い。「サーバで動く JavaScript」では足りないし、「シングルスレッドのイベントループ」では半分しか言えていない。

この記事はその「構造」を言語化する。文法もテクニックもフレームワークも扱わない。代わりに、

- Node.js は何でできているのか
- ブラウザの JavaScript と**何を共有していて、何が別物なのか**
- 「同じ JavaScript」と思って書くと、なぜ落ちるのか

を、公式ドキュメントの根拠付きで整理する。Node の **イベントループ・スレッドモデル・V8 ヒープ** にさらに深く踏み込む話は[第2部](./nodejs_runtime_essence_part2)で扱う。第1部は、その前提となる「**Node という JS ランタイムの輪郭**」を引く回だと思って読んでほしい。

対象読者は、Node.js を業務で日常的に使っていて、

- `fs.readFile` も `crypto.pbkdf2` も非同期で書ける
- けれど両者の「非同期」がプロセス内のどこで実装されているかは即答できない
- ブラウザ JS にも触ったことがあり、何となく違いを感じている

くらいの中級〜上級エンジニアを想定している。

## 0. 合言葉: 「言語は同じ、ランタイムは別物」

ブラウザの JS と Node の JS は、同じ **ECMAScript** を実装している。`class`、`Promise`、`Map`、`Symbol.asyncIterator`、これらの意味は変わらない。

しかし、**ECMAScript は言語の仕様だけ** を定義する。「Window がある」「`document` がある」「ファイルが読める」「`process.exit()` がある」── これらは ECMAScript の外側、**ホスト環境(host environment)** が決める領分だ。

MDN の「JavaScript execution model」はこれを明示している。

> The JavaScript engine implements the ECMAScript (JavaScript) language, providing the core functionality. ... in order to interact with the outside world, ... we need additional environment-specific mechanisms provided by the host environment. For example, the HTML DOM is the host environment when JavaScript is executed in a web browser. Node.js is another host environment that allows JavaScript to be run on the server side.
>
> — https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Execution_model

つまり**ブラウザと Node は同列のホスト環境**で、どちらが本家でどちらが亜種という関係ではない。エンジン(V8)は共有しても、その外側にあるホストはまったく別物だ。この記事は、その「外側」を解剖する。

## 1. Node.js の正体: 4 つの部品の合体構造

「Node.js とは何か」を構造で答えるには、最低でも 4 層を区別する必要がある。

```
   ┌─────────────────────────────────────────┐
   │  あなたの JavaScript / TypeScript        │
   ├─────────────────────────────────────────┤
   │  Node core JS ライブラリ (node:http など)│
   ├─────────────────────────────────────────┤
   │  C++ bindings (V8 と libuv の橋渡し)     │
   ├──────────────────┬──────────────────────┤
   │  V8 (JS エンジン) │  libuv (非同期 I/O)   │
   └──────────────────┴──────────────────────┘
                    OS (epoll / kqueue / IOCP)
```

それぞれが何者かを押さえる。

### V8: 言語の心臓

V8 は Google が作った ECMAScript エンジンで、JS のパース・最適化(Ignition / TurboFan / Maglev など)・実行・GC を担う。**ブラウザ(Chrome / Edge)と Node が共有する部品はここ**だ。

V8 が提供する語彙のうち、Node の挙動を理解するうえで重要なのは次の 3 つ:

- **Isolate**: 「自身のヒープを持つ VM インスタンス」。Isolate が違えばヒープも GC もまったく独立する。
- **Context**: 「分離された実行環境」。同じ Isolate 内でも Context が違えばグローバルが別。
- **HandleScope / Handle**: JS オブジェクトのヒープ位置への参照。GC がオブジェクトを移動すると Handle も追従する。

> An isolate is a VM instance with its own heap. ... A context is an execution environment that allows separate, unrelated, JavaScript code to run in a single instance of V8.
>
> — https://v8.dev/docs/embed

なぜこれが効いてくるか: Node の `worker_threads` は **isolate ごと独立** に作られる。だから `worker_threads` 越しの値は基本 **コピー**(または `transferList` での所有権移譲、`SharedArrayBuffer` での明示共有)であって、参照を渡せない。これは「言語の癖」ではなく「V8 の構造」から来ている。

### libuv: 非同期 I/O の心臓

libuv は、もともと Node のために書かれた **クロスプラットフォーム非同期 I/O ライブラリ**。`fs`、`net`、`dgram`、`tls`、`dns.lookup`、タイマー、Worker Pool、シグナル ── これらの裏側はすべて libuv だ。

> libuv is cross-platform support library which was originally written for Node.js. It's designed around the event-driven asynchronous I/O model.
>
> — https://docs.libuv.org/en/v1.x/design.html

libuv は OS の差を吸収する: Linux なら `epoll`、macOS/BSD なら `kqueue`、SunOS なら `event ports`、Windows なら `IOCP`。Node の「非同期がどこのプラットフォームでも同じ顔をしている」秘密はここにある。

libuv のイベントループは `uv_loop_t` という C 構造体で表現されており、**1 スレッドに 1 つ** が原則だ。これは Node のメインスレッドだけでなく、Worker や補助スレッドにも当てはまる。

### C++ bindings: 接続層

V8 と libuv は別の C++ ライブラリで、そのままでは話が通じない。Node core が C++ で書いた **bindings** がこの間に挟まり、V8 Isolate と libuv ループを結び付け、JS から見える形に変換する。

Node の C++ 内部表現として、`Environment` というクラスが「1 つの Node インスタンス」を表す。`Environment` は `Isolate`(V8 側)と `Context`(V8 側)と event loop(libuv 側)を束ねていて、Worker を作るたびにこの `Environment` が新規に作られる。

> Currently, every `Environment` class is associated with: `Isolate`, `Context`, ... The current event loop can be accessed using `env->event_loop()`.
>
> — https://github.com/libuv/ci-tmp-libuv-node/blob/master/src/README.md

「Node に Isolate が複数ある」「event loop が複数ある」── この事実が、後で `worker_threads` の章で効いてくる。

### Node core JS ライブラリ: `node:` プレフィックス

`node:http`、`node:fs`、`node:crypto`、`node:worker_threads`、`node:v8`、`node:async_hooks` ── これらは Node core が JS と C++ で書いた標準ライブラリだ。`node:` プレフィックスを付けると npm パッケージとの衝突を避けられる。

ここまでが Node.js の **構造的正体** で、上位 4 層のどこに自分のコードが置かれているかを意識すると、性能や障害の地図が一気に読みやすくなる。

## 2. ブラウザと **共有しているもの**

ここまでで「ブラウザと Node が共有するのは V8 まで」だと分かる。共有部分のうち、日常のコードに直接効くのは次のあたり。

### ECMAScript の言語仕様

`Promise`、`async`/`await`、`class`、`Map`/`Set`、`Symbol`、`AsyncIterator`、`structuredClone`、`Object.hasOwn` ── これらの**意味論**は同じだ。Node 18 と Chrome 110 で動く `class` は同じ class、`Promise.then` の解決順序の規則も同じ。

ブラウザは古い環境への配慮で transpile することがあるが、Node では「どの Node バージョンで動くか」を自分で固定できるので、Babel/polyfill を入れないで素のモダン JS を書ける ── これが ECMAScript 共有による実利の最大点だ。

> ... unless you are building an open source application that anyone can deploy anywhere, you know which version of Node.js you will run the application on. Compared to the browser environment, where you don't get the luxury to choose what browser your visitors will use, this is very convenient.
>
> — https://nodejs.org/learn/getting-started/differences-between-nodejs-and-the-browser

### microtask の意味論

`Promise.then` のハンドラや `queueMicrotask` のコールバックが「**現在のマイクロタスクチェックポイントで一気に flush される**」というルールは、ブラウザと Node の双方で共通だ。

ただし、後で出てくる `process.nextTick` は **Node 固有のもう一段別のキュー** で、microtask と混同してはいけない。これは「同じ意味論」ではなく「Node 側が**追加した**もう 1 つの優先キュー」だ。

### 「決してブロックしない」という建前

MDN の execution model はこう言っている。

> JavaScript's execution model has a key consequence: the language is never blocking.
>
> — https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Execution_model

これも Node とブラウザの**共通の建前**だ。違いは、Node の場合「サーバが複数クライアントを束ねている」ので、**建前を破る代償が桁違いに大きい** こと(第2部で詳述)。

### Isolate / Context / Handle の語彙

ブラウザでも各タブやワーカーは別 Isolate / Context として動く。Node の `worker_threads` もまったく同じ構造だ。「**V8 から見ると、ブラウザのタブと Node のワーカースレッドは同じ概念**」と覚えておくと、`postMessage` や `transferList` の意味がスッと入る。

## 3. ブラウザに **あって Node にないもの**

ここからが「同じ JS」と言っていられない領域だ。

### DOM・`window`・`document`

これは見えやすい違い。Node には DOM が無く、`window`、`document`、`HTMLElement`、`MutationObserver`、`requestAnimationFrame`、`getComputedStyle` などはすべて存在しない。

> A Node.js application runs in a single process, ... another huge difference is that in Node.js you control the environment. ... Node.js apps bring with them a huge advantage: ... a single language.
>
> — https://nodejs.org/learn/getting-started/differences-between-nodejs-and-the-browser

MDN も明示している:

> Node.js offers additional APIs for supporting functionality that is useful in browserless environments ... but does not support JavaScript APIs for working with the browser and DOM.
>
> — https://developer.mozilla.org/en-US/docs/Learn_web_development/Extensions/Server-side/Express_Nodejs

### Web Platform API

`localStorage` / `sessionStorage`、Cookie API(`document.cookie`)、`Notification`、`Geolocation`、`Permissions`、`Service Worker`、Same-Origin Policy 由来の `CORS` 機構 ── これらは「**ブラウザがホストとして提供している API**」であって、Node は持っていない。

Node が **`fetch` を持っているのに `localStorage` は持っていない** のは、「ブラウザ互換ぽいけど全部入りではない」というかなり微妙なバランス感覚だ(`fetch` の経緯は後述する)。

### 隠れた前提: タブ単位の隔離

ブラウザは、タブ/オリジン単位で実行コンテキストを隔離する。あるサイトのコードが別サイトのストレージや DOM に触れないのは、ブラウザがホストとしてそう作っているからだ。

Node はこれをしない。**1 プロセスに 1 つのグローバル**、**1 つのモジュールキャッシュ**、**1 つの環境変数**、**1 つのファイルディスクリプタ集合**。複数の "リクエスト" が同じプロセスを共有する、というのが Node のサーバモデルの本質で、これがイベントループ・Worker Pool の議論(第2部)に直結する。

帰結として:

- **SSRF**: ブラウザは「自分の origin と違う API」を勝手に叩けないが、Node は何でも叩ける ── サーバ側で URL を fetch する設計には、検証なしに叩けてしまう構造的リスクが常に乗る。
- **prototype pollution**: ブラウザでも問題だが、Node ではプロセス全体のグローバル `Object.prototype` を 1 つしか持たないため、影響範囲が広い。

「ブラウザ側で勝手に止めてくれていたもの」が、Node では**自分の責任**になる。これは「JS なんだから同じだろう」と思って Node を書くと一番危ない部分だ。

## 4. Node に **あってブラウザにないもの**

逆方向。Node は OS のホストとして、ブラウザに無い API を山ほど持っている。

### `process` / `Buffer` / OS API

- `process`: `argv`、`env`、`cwd`、`pid`、`platform`、`versions`、`stdin`/`stdout`/`stderr`、シグナルハンドラ(`process.on('SIGTERM', ...)`)、終了コード(`process.exit(code)`)。ブラウザにはどれも無い。
- `Buffer`: **V8 ヒープ外**のバイナリ表現。`TypedArray`(`Uint8Array`)とは互換だが、Node 専用の便利 API(`Buffer.alloc`、`Buffer.from`、`hex`/`base64` エンコード)を持つ。V8 ヒープ外という性質は、**大きなバッファを持っていても V8 のヒープスナップショットには映らない**(=メモリ使用量が見えにくい)という形で運用に効いてくる。
- `fs` / `net` / `dgram` / `tls` / `dns` / `child_process` / `cluster`: OS をそのまま扱う API。

このうち `fs` は地味に重要で、**Promise/コールバック版の `fs` は内部で libuv の Worker Pool を使っている**(第2部の話)。

> The promise APIs use the underlying Node.js threadpool to perform file system operations off the event loop thread. These operations are not synchronized or threadsafe.
>
> — https://nodejs.org/api/fs.html

「同じファイルへの並行変更には注意」と公式が書いているのは、**libuv の Worker Pool は別 OS スレッドで動く** から(=データ競合が起きうる)。これは「JavaScript は同時並行で動かない」という素朴な直感を **真っ向から裏切る**。

### CommonJS と `node_modules`

ES Modules(`import`/`export`)はブラウザ側でも標準だが、CommonJS(`require()` / `module.exports`)は **Node 固有の世界** だ。`node_modules` を親ディレクトリに向かって遡る解決アルゴリズムも、`package.json` の `exports` フィールドによる条件付き解決(`"node"`, `"import"`, `"require"`, `"default"` など)もすべて Node のもの。

> The Node.js implementation of `exports` deliberately does not provide the kinds of customization (such as named exports from CJS imports, optional file extensions, JSON modules, etc.) that transpiler-based environments do.
>
> — https://nodejs.org/en/blog/release/v12.17.0

このため「ブラウザで動いていた transpile 前提のコードを `node` でそのまま動かそうとすると壊れる」── これは Node の ESM がブラウザ ESM 互換に振り切った帰結だ。

### マルチコア利用の手段

- `child_process.fork()` で別プロセス起動
- `cluster` で同一スクリプトを複数プロセスに分散
- `worker_threads` で同一プロセス内に別 Isolate + 別 event loop

これらは全部 Node 固有。ブラウザの Web Worker と概念は近いが、API も能力も別物。`worker_threads` の細部は第2部で。

### ネイティブアドオン

C/C++ で書いたモジュールを `.node` ファイルとしてロードできる。V8 と libuv の API に直接アクセスできるので、画像処理・暗号・データベースドライバ・LLM 推論など、CPU 重い領域ではこれが性能の出口になる。**ブラウザでこれに相当するのは WebAssembly だけ**で、ネイティブアドオンほどの自由度はない。

## 5. **似ているが意味が違う** もの ── 地雷ゾーン

ここが第1部の核心だ。「ブラウザでも Node でも同じ名前の API」が、実は挙動・コスト・順序保証で違っている、というケースを並べる。

### 5.1 `setTimeout` の "0ms" は別物

ブラウザの `setTimeout(fn, 0)` は HTML 仕様に基づく clamp が入る(ネストが 5 段以上だと最小 4ms に丸められる、など)。Node の `setTimeout` は libuv の `uv_timer_t` 経由で、libuv のループ反復に依存して発火する。

Node 公式は「`setTimeout()` は ms 単位の最小しきい値経過後に script を実行するようスケジュールする」とだけ言い、I/O サイクル外での `setTimeout(fn, 0)` と `setImmediate()` の順序は **非決定的** だと明記している。

> If we run this script from within an I/O cycle ... `setImmediate` will always be executed before any timers if scheduled within an I/O cycle, independently of how many timers are present.
>
> — https://nodejs.org/learn/asynchronous-work/event-loop-timers-and-nexttick

「`setTimeout(fn, 0)` を書けば次の tick で動く」という素朴な期待は、Node では**コンテキスト依存**になる。順序の細かい話は第2部。

### 5.2 `setImmediate` は Node 固有

`setImmediate` は **ブラウザ標準にはない**(かつて IE に独自実装があったが、それと Node のものは別)。「現在の poll フェーズ完了後に 1 回走る特殊タイマー」という意味で、Node のイベントループ構造を前提にした API だ。

```js
// I/O コールバック内では順序が保証される
fs.readFile('/etc/hosts', () => {
  setTimeout(() => console.log('timeout'), 0);
  setImmediate(() => console.log('immediate'));
  // 出力は常に: immediate → timeout
});

// メインモジュール直下では順序は環境依存
setTimeout(() => console.log('timeout'), 0);
setImmediate(() => console.log('immediate'));
// 出力順は呼び出しごと/負荷で変わりうる
```

> When called within an I/O cycle, the immediate callback is always executed first.
>
> — https://nodejs.org/learn/asynchronous-work/event-loop-timers-and-nexttick

「**コンテキスト次第で順序が変わる**」という事実が公式で明示されていることを知っておくのは大きい。プロダクションのバグレポート「ローカルでは順序が逆になる」の答えはほぼ毎回ここだ。

### 5.3 microtask の優先順位は **CJS と ESM で違う**

ここは最も多くの中級者が驚く部分だ。

Node の microtask 周りには 2 つのキューがある:

- **`process.nextTick` キュー**(Node 独自・最優先)
- **microtask キュー**(`Promise.then` / `queueMicrotask` / `await` の再開、ECMAScript 標準)

各 libuv フェーズの間、また同期コードの末尾で、Node は「nextTick キューを空にする → microtask キューを空にする → 次のフェーズへ」を繰り返す。**CJS では `process.nextTick` のほうが必ず先に走る**。

ところが ESM ではこれが反転する。

> However, due to the implementation of ECMAScript Modules, ... `queueMicrotask()` callbacks are always executed before `process.nextTick()` callbacks within ES modules. This is because ES modules are loaded as part of a microtask queue and therefore the entire script is already inside a microtask queue when `process.nextTick()` is called.
>
> — https://nodejs.org/api/process.html

つまり同じコードを `.cjs` と `.mjs` で書くと出力順が変わる:

```js
// CJS: nextTick → microtask → setTimeout
// ESM: microtask → nextTick → setTimeout
Promise.resolve().then(() => console.log('microtask'));
process.nextTick(() => console.log('nextTick'));
setTimeout(() => console.log('timeout'), 0);
```

これは「ECMAScript 仕様としての microtask は `Promise` 用キュー一つ」だが、Node が **その上に `process.nextTick` をもう一段乗せた** ことの帰結だ。さらに ESM が microtask キューの一部として評価される、という HTML 起源の仕様が絡んで、CJS と ESM で見える順序が逆になる。

公式は ECMAScript 互換のために `queueMicrotask` をユーザーランドの第一候補として推奨している:

> In most userland use cases, `queueMicrotask()` provides a portable and reliable way of deferring execution that works across multiple JavaScript platform environments and should be favored over `process.nextTick()`.
>
> — https://nodejs.org/api/process.html

`process.nextTick` は強力だが、**再帰的に呼ぶと I/O を starve させる** という有名な落とし穴があるので(これも第2部)、新規コードでは `queueMicrotask` を選ぶのが基本だ。

### 5.4 `fetch` は **同じに見えて別物**(undici 由来)

Node v18 で `fetch` がデフォルトで組み込まれ、v21.0.0 で stable になった。実装は Node のために 0 から書かれた HTTP/1.1 クライアントである **undici** だ。

> Node.js includes a fetch implementation since v18, which is the same implementation as ours, and it's powered by us.
>
> — https://undici.nodejs.org/

確認は `process.versions.undici` で取れる。

```js
console.log(process.versions.undici);
// 例: '6.19.2'
```

ブラウザ互換実装と謳われており、`Headers` / `Request` / `Response` / `FormData` も globals に居る。それでも完全同一ではない、という点が地雷だ:

- **`file://` URL は未実装**で、`TypeError` + `cause: Error: not implemented... yet...` を返す。これは WHATWG fetch spec が `file:` URL の挙動を「読者への課題」と表現していることに従った挙動だ。
  - 根拠: https://github.com/nodejs/undici/issues/2751
- エラーが `DOMException` や `TypeError` でラップされるため、タイムアウト・接続失敗・パースエラーの細かい原因切り分けには **undici の `fetch` / `request` を直接使ったほうが情報量が多い**、と undici メンテナが言及している。
  - 根拠: https://github.com/nodejs/undici/discussions/3253
- 接続プールやキープアライブの挙動は **dispatcher** が決める。`undici.setGlobalDispatcher()` でプロセス全体の挙動を差し替えられる。これはブラウザの fetch では概念ごと存在しない。

「ブラウザの `fetch` と同じだ」と思って Node に持ってくると、プロキシ環境変数の効き方、TLS 設定、コネクション再利用、デバッグ可能性、いずれも違うので注意する必要がある。

### 5.5 モジュールシステムの「同じ `import`」も別物

ESM 構文(`import`)はブラウザと Node の双方で使えるが、Node の ESM は **拡張子省略やディレクトリ index 解決をデフォルトでサポートしない**(Web 互換に振った)。

> The Node.js implementation of Node.js ECMAScript modules ... do not provide ... named exports from CJS imports, optional file extensions, JSON modules ...
>
> — https://nodejs.org/en/blog/release/v12.17.0

`package.json` の `exports` フィールドによる条件付き解決(`"node"`, `"import"`, `"require"`, `"browser"`, `"default"`, `"node-addons"` など)も Node 固有の世界。`"import"` と `"require"` を同居させると **dual package hazard**(同じパッケージが CJS 版と ESM 版で別インスタンスとしてロードされ、内部状態が分裂する事故)を招く、と公式が警告している。

> When both `"import"` and `"require"` conditions are used, special caution is required to avoid hazards of dual CommonJS/ES module packages.
>
> — https://nodejs.org/api/packages.html

ブラウザ側はここまで複雑な解決機構を持っていない(基本は URL 解決だけ)。**「同じ ESM」と思っていると、実は Node の ESM だけが特殊な解決ルールに支配されている** ── これが「文字列 `import` の見た目に騙されない」べき所だ。

### 5.6 グローバル汚染の影響範囲

ブラウザではタブ単位でグローバルが分離されている。`window.foo = 1` してもよそのタブには関係ない。

Node は **1 プロセスに 1 つの `globalThis`** で、同じプロセス内の全モジュール・全リクエストがそれを共有する。`global.foo = 1` をどこかのモジュールでやると、別の HTTP リクエストの処理でも `foo` が見える。

これは `Object.prototype` への汚染にも当てはまる。1 つのモジュールが `Object.prototype.toJSON = ...` を書くと、**プロセス内のあらゆる JSON シリアライズが影響を受ける**。「Node はプロセス境界 = 隔離境界」ということを忘れて、ブラウザのタブ感覚でグローバルをいじると痛い目に遭う。

## 6. ホスト環境差から来る運用・セキュリティの違い

ここまでの差は、運用面で次の形で現れる。

### 環境を制御できる利点

ブラウザは「どのバージョンのどのブラウザで動くか分からない」が、Node は「自分が CI とコンテナで固定した Node バージョンで動く」。Babel/polyfill が不要なのはこの恩恵で、`process.versions.node` を見ればフラットに分岐できる。

### 1 プロセスに同居する代償

ブラウザは 1 タブが死んでも別タブは生きる(Chrome のプロセスモデルがそれを保証する)。Node は **1 プロセス内の重い 1 リクエストが、同居する全リクエストを巻き込む**:

- イベントループをブロックする callback が走ると、その間サーバ全体が止まる
- libuv の Worker Pool が CPU 重いタスクで埋まると、`fs` も DNS lookup も詰まる(共有 threadpool だから)
- 悪意ある入力でこの状況を意図的に作る攻撃が成立 ── これが Node 公式が **「Don't Block the Event Loop」を最も力を入れて啓蒙している** 理由だ。

> If it is possible that for certain input one of your threads might block, a malicious client could submit this "evil input", make your threads block, and keep them from working on other clients. This would be a Denial of Service attack.
>
> — https://nodejs.org/learn/asynchronous-work/dont-block-the-event-loop

ブラウザでは「単に重いページが落ちるだけ」だが、Node では **可用性そのものに直結する**。同じ言語で書いていても、構造的なリスクの大きさはまったく別物だ。

### V8 Heap Sandbox

V8 自体のセキュリティモデルも、Node 運用者は知っておくと良い。V8 はヒープ corruption をプロセスの他領域に波及させない隔離設計を進めている。

> The basic idea behind the sandbox is to isolate V8's (heap) memory such that any memory corruption there cannot "spread" to other parts of the process' memory.
>
> — https://v8.dev/blog/sandbox

Node はこの V8 を組み込んでいる以上、最新 V8 への追従(Node のメジャーアップデート)が**そのままセキュリティ対策の追従**になる。古い Node を本番で長く走らせることが構造的にリスキー、という結論はここから来る。

## 7. まとめ: Node と「同じ JavaScript」の距離

第1部のメッセージはシンプルだ。

- **言語は同じ**。ECMAScript の意味論はブラウザと Node で揃っている。
- **ホスト環境は別物**。V8 までしか共有しておらず、libuv・`process`・`Buffer`・`fs`・CommonJS・ネイティブアドオン・Worker Pool は Node 固有。
- **同じ名前の API でも、意味が違う場合がある**。`setTimeout`、`setImmediate`、`process.nextTick` vs microtask、`fetch`(undici 由来)、ESM の解決規則、グローバル汚染の影響範囲 ── すべて「ブラウザの感覚で書く」と裏切られる箇所だ。
- **構造的リスクの大きさが違う**。ブラウザでは 1 タブの問題、Node では 1 プロセス全体の問題になる。

ここまで押さえると、よく言われる「Node はシングルスレッドのイベントループ」というフレーズの**情報量の薄さ** が見えてくる。実際には:

- V8 が 1 つの Isolate を持っていて
- libuv が 1 つの event loop を持っていて
- その裏に libuv の Worker Pool が **別 OS スレッド** として存在して
- 場合によっては `worker_threads` で **追加の Isolate + event loop** を立ち上げている

これが Node のリアルな構造だ。

[第2部](./nodejs_runtime_essence_part2) では、この構造の中で:

- libuv のイベントループは具体的にどの**フェーズ**を回しているのか
- 「非同期」と書いてある API が、**実際にどこで実行されているか**
- なぜ 1 リクエストの重さが全体を詰まらせるのか、その回避策の**トレードオフ**は何か
- V8 のヒープモデルが OOM と p99 スパイクの**形** をどう決めているか

を、性能・可用性・難解バグの根本要因として深掘りする。第1部で引いた「Node というランタイムの輪郭」を、内側に向かって解剖していく回だ。

## 参考リンク

- Node.js 公式: [Differences between Node.js and the Browser](https://nodejs.org/learn/getting-started/differences-between-nodejs-and-the-browser)
- Node.js 公式: [About Node.js](https://nodejs.org/en/about)
- Node.js 公式: [Process — `process.nextTick()` vs `queueMicrotask()`](https://nodejs.org/api/process.html)
- Node.js 公式: [The Event Loop, Timers, and `process.nextTick()`](https://nodejs.org/learn/asynchronous-work/event-loop-timers-and-nexttick)
- Node.js 公式: [Don't Block the Event Loop (or the Worker Pool)](https://nodejs.org/learn/asynchronous-work/dont-block-the-event-loop)
- Node.js 公式: [Globals — `fetch`](https://nodejs.org/api/globals.html)
- Node.js 公式: [Packages — `exports` field, dual package hazard](https://nodejs.org/api/packages.html)
- libuv 公式: [Design overview](https://docs.libuv.org/en/v1.x/design.html)
- V8 公式: [Getting started with embedding V8](https://v8.dev/docs/embed)
- V8 公式: [The V8 Sandbox](https://v8.dev/blog/sandbox)
- undici 公式: [Documentation](https://undici.nodejs.org/)
- MDN: [JavaScript execution model](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Execution_model)
