---
title: "Node.js を「JS ランタイム」として捉え直す — ブラウザJSと共通なもの、別物なもの (第1部)"
status: plan
---

## 想定読者と前提

- Node.js を業務で日常的に使う中級〜上級エンジニア
- 「`fs.readFile` は非同期、`crypto.pbkdf2` も非同期」と書けるが、両者の "非同期" がプロセス内のどこで実装されているかを即答できないレベル
- パフォーマンス事故・p99 スパイク・不可解なバグを "なんとなく" で乗り切ってきた人
- フロントエンドのブラウザ JS も触ったことがあり、「同じ JavaScript なのに何が違うのか」を構造として知りたい人

## この記事(第1部)の立場

- 文法・API リファレンス・フレームワーク・テクニックは扱わない
- 「Node.js とは何か」を**構造として**言語化する
- ブラウザの JS と Node の JS が「同じ言語」と思って書くと裏切られる箇所を、根拠付きで切り分ける
- 第2部(イベントループとスレッドモデル)の前提として、まず "ランタイム" の輪郭を共有する

## 第1部で答える問い

- Node.js は何でできているのか(V8 / libuv / bindings / 標準モジュールの合体構造)
- ブラウザの JS エンジン部分とは何を共有し、何を共有していないのか
- 「同じ JavaScript」と思って書くと、なぜ落ちるのか(意味が違う API・存在しない概念)

## 構成

### 1. はじめに: 「Node.js は JavaScript」では足りない

- ブラウザ JS と Node の JS は同じ ECMAScript を実装しているが、それらは**別のホスト環境**である
- MDN の execution model も「JavaScript engine + host environment」という枠組みで両者を並列に説明している
  - 根拠: https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Execution_model
- この記事の合言葉:「言語は同じ、ランタイムは別物」

### 2. Node.js の正体: V8 + libuv + bindings + 標準モジュール

- V8: JS の実行エンジン本体(ECMAScript 実装、Isolate / Context / HandleScope の語彙)
  - 根拠: https://v8.dev/docs/embed
- libuv: クロスプラットフォームの非同期 I/O ライブラリ。元々 Node のために書かれた
  - 根拠: https://docs.libuv.org/en/v1.x/design.html
- C++ bindings: V8 と libuv を JS から触れる形に橋渡しする層。`Environment` クラスが Node インスタンスを表現し、Isolate / Context / event loop を束ねる
  - 根拠: https://github.com/libuv/ci-tmp-libuv-node/blob/master/src/README.md
- 標準モジュール(`node:` プレフィックス): `node:http`, `node:fs`, `node:crypto`, `node:worker_threads`, `node:v8` など
- 図示: 「JS コード → V8 → bindings → libuv / OS」の縦の階層
- ここを構造として把握しているかどうかで、性能・運用の理解度が変わる

### 3. ブラウザと **共有しているもの** (V8 / ECMAScript / Promise・microtask)

- ECMAScript の言語仕様そのもの(構文・型・Promise・iterator・class など)
- V8 が提供する語彙: Isolate(自身のヒープを持つ VM インスタンス)、Context(分離された実行環境)、HandleScope(handle のコンテナ)
  - 根拠: https://v8.dev/docs/embed
- microtask の意味論(`Promise.then` / `queueMicrotask`)
- 「JS 実行は決してブロックしない」という建前(I/O は events / callbacks で扱う)
  - 根拠: https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Execution_model
- 「Node.js もイベントループはユーザから隠蔽されている」点が共通
  - 根拠: https://nodejs.org/en/about

### 4. ブラウザに **あって Node にないもの**

- `window`, `document`, DOM API 全般
  - 根拠: https://nodejs.org/learn/getting-started/differences-between-nodejs-and-the-browser
  - 根拠: https://developer.mozilla.org/en-US/docs/Learn_web_development/Extensions/Server-side/Express_Nodejs
- Web Platform API(`localStorage`, Cookie API, Same-Origin Policy 由来のセキュリティモデル など)
- ブラウザ拡張のサンドボックス(タブ単位の origin 隔離)
- 帰結: SSRF や prototype pollution など、Node では「ブラウザ側で勝手に止めてくれていたもの」が自分の責任になる

### 5. Node に **あってブラウザにないもの**

- `process`(env, argv, cwd, signal, exit code)
- `Buffer`(V8 ヒープ外のバイナリ表現)
- `fs`, `net`, `dgram`, `tls`, `child_process`, `cluster` などの OS API
- C++ ネイティブアドオン
- CommonJS(`require()`)と node_modules ルックアップ
  - 根拠: https://nodejs.org/learn/getting-started/differences-between-nodejs-and-the-browser
- libuv の Worker Pool(`fs` などはこれを使ってイベントループ外で動く)
  - 根拠: https://nodejs.org/api/fs.html
- マルチコア利用の手段: `child_process.fork()`, `cluster`, `worker_threads`

### 6. **似ているが意味が違う** もの(地雷ゾーン)

- `setTimeout`: ブラウザは HTML 仕様の clamp(ネスト 5 回以降は最小 4ms)、Node は libuv ベース・`uv_timer_t` 起点で挙動が異なる
- `setImmediate` は Node 固有(ブラウザにはない別物)。`setImmediate()` は poll フェーズ後の特殊タイマー
  - 根拠: https://nodejs.org/learn/asynchronous-work/event-loop-timers-and-nexttick
- microtask の優先順位:
  - CJS では `process.nextTick` キューが先、その後 `Promise.then` / `queueMicrotask` の microtask キュー
  - ESM では「ESM ロード自体が microtask 処理の一部」のため、`queueMicrotask` のほうが先に走る
  - 根拠: https://nodejs.org/api/process.html
  - 根拠: https://nodejs.org/learn/asynchronous-work/understanding-setimmediate
- `fetch`: Node v18 以降組み込み(undici 由来)。v21.0.0 で stable。ブラウザ互換実装だが完全同一ではない
  - 例: `file://` は未実装、エラー型が `DOMException`/`TypeError` でラップされ undici 直接呼び出しより粒度が粗い
  - 根拠: https://nodejs.org/api/globals.html
  - 根拠: https://undici.nodejs.org/
  - 根拠: https://github.com/nodejs/undici/issues/2751
- モジュールシステム:
  - CJS と ESM の二重ローダー、`exports` の条件分岐、dual package hazard
  - 根拠: https://nodejs.org/api/packages.html
  - 根拠: https://nodejs.org/api/esm.html
- グローバル汚染の影響範囲: ブラウザはタブ単位、Node はプロセス単位(=同居コードすべてに波及)

### 7. ホスト環境差から来る運用・セキュリティの違い

- 環境を制御できる強み: デプロイ先 Node バージョンを把握できるので Babel/polyfill 不要
  - 根拠: https://nodejs.org/learn/getting-started/differences-between-nodejs-and-the-browser
- 同時に背負うリスク:
  - 1 プロセスが多クライアントを束ねるため、1 リクエストの重さが全リクエストを巻き込む
  - 悪意ある入力でイベントループ / Worker Pool をブロックさせる DoS が成立しうる
  - 根拠: https://nodejs.org/learn/asynchronous-work/dont-block-the-event-loop
- V8 Heap Sandbox は V8 ヒープ corruption をプロセスの他領域に波及させない設計
  - 根拠: https://v8.dev/blog/sandbox

### 8. まとめと第2部への接続

- Node.js を「サーバで動く JavaScript」と一言で言うのは、構造を見ないと危険
- 言語は同じ、ホスト環境は別物 → API の見た目が同じでも挙動・コスト・失敗の仕方が違う
- 第2部では、ここで触れた「libuv のイベントループ」「Worker Pool」「V8 ヒープ」を、性能・可用性・難解バグの根本要因として深掘りする

## 根拠ファイル(調査結果)

- `temp/nodejs_fundamentals/facts_nodejs_fundamentals.md`
- `temp/nodejs_fundamentals/extract_node_vs_browser.json`
- `temp/nodejs_fundamentals/extract_nexttick_microtask.json`
- `temp/nodejs_fundamentals/extract_node_fetch_undici.json`
- `temp/nodejs_fundamentals/extract_cjs_esm.json`

## 不足/留意

- 「`setTimeout(fn, 0)` の最小遅延(HTML 仕様 4ms 等)」「`node_modules` 探索の完全な擬似コード」「ESM 名前空間オブジェクトの不変性」などは公式の引用が薄いため、本文では「文脈依存・実装依存」と表現するに留める
