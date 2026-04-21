---
title: "JavaScriptはいつ、どの順で動き出すのか — script読込・イベント登録・バンドラの裏側"
status: plan
---

## 想定読者と前提

- JSは書けるが「ブラウザがscriptをどう処理しているか」の内部モデルを持っていない中級フロントエンド/Webエンジニア
- `defer`, `async`, `type="module"`, `DOMContentLoaded`の違いをなんとなく使っている人
- バンドラを「黒箱」として使っており、なぜ必要で何をしているか言語化したい人

## この記事が答える問い

1. JSファイルが読み込まれ、`addEventListener`等が実際に登録されるのはいつか。classic / `defer` / `async` / `type="module"` でどう変わるか
2. 複数の`<script>`タグや`import`文がある場合、どんな順序で評価・実行されるか
3. 動的 `import()` と top-level await が入ると順序はどう変わるか
4. これらの「読み込み順・依存解決」を自動化するバンドラは、裏で何をしているのか

## 扱う / 扱わない

- **扱う**: script処理モデル、`DOMContentLoaded`/`readyState`、ESMモジュールグラフ評価、循環依存、動的import、top-level await、バンドラのカテゴリ分け
- **扱わない**: Node.js側のCJS/ESM解決、具体的なバンドラ設定、パフォーマンスチューニング、Core Web Vitals

---

## セクション構成

### 1. 「イベントリスナーが動かない」の正体

**主張**: `addEventListener`が登録されるのは「そのscriptが実行された瞬間」。ただし**scriptが実行される瞬間**こそが複雑なので、本記事全体で解きほぐす。

内容:
- 3行コード例: `document.querySelector('#btn').addEventListener(...)` が失敗するよくあるパターン
- 「イベントリスナーの登録」=「そのコードが実行された時点でのDOMに対して登録される」という単純な真実
- 実行タイミング問題 = script処理タイミング問題

根拠:
- 体験的な導入のため、根拠URL不要(後続セクションで裏を取る)

### 2. classic script: parser-blockingが基本

**主張**: 属性なし`<script>`はHTMLパースを止めて、fetch → 評価 → 実行を完了してからパース再開する。このため「DOMがまだ存在しない」事故が起きる。

内容:
- `<script src="...">` が何をしているか: fetch/parse/evaluate/executeを1つの同期処理としてHTMLパーサが待つ
- インラインscriptも同じく同期
- `body`末尾に置くパターンが生まれた理由
- `document.readyState`はこの間 `"loading"`

根拠:
- [MDN `<script>` element](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/script)
- [MDN readyState](https://developer.mozilla.org/en-US/docs/Web/API/Document/readyState)
- `temp/web/extract_js_script_timing.json`

### 3. `async` と `defer`: 非同期ロードの2系統

**主張**: `async`と`defer`は「非同期に取ってくる」点は同じだが、**実行タイミング**と**実行順序**がまるで違う。

内容:
- `async`: 取得が終わり次第すぐ実行。**順序保証なし**。パースを瞬間的に止める
- `defer`: 取得は並行、**実行はパース完了後、ドキュメント順**
- 比較図(mermaidまたはASCII)
- `async`が向くのは「単独で動き依存がないもの」、`defer`が向くのは「DOM依存/順序依存」

根拠:
- [MDN `<script>` element](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/script)
- `temp/web/extract_js_script_timing.json`

### 4. `type="module"`: デフォルトで`defer`相当、でも別物

**主張**: モジュールスクリプトは標準で遅延評価される(defer相当)が、**依存グラフを辿る**という別の重い処理が裏で走る。

内容:
- `type="module"`は`defer`属性なしでもパースを止めない
- `defer`属性を付けても効果なし(モジュールは元から遅延評価)
- `async` + `module` は「取れ次第実行、順序なし」
- `nomodule`は後方互換のためのフォールバック指示
- **モジュールスクリプトの中身は「依存解決」「リンク」「評価」の3フェーズ**
- ここで初めて複数ファイルの依存グラフが登場する

根拠:
- [MDN `<script>` element](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/script)
- [MDN JavaScript modules](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules)
- `temp/web/extract_js_script_timing.json`, `temp/web/extract_js_esm.json`

### 5. `DOMContentLoaded` と `readyState` の正確な定義

**主張**: `DOMContentLoaded`は「HTMLパース完了 + **deferred/module**スクリプト実行完了」時点。`async`スクリプトは待たれない。`readyState`の遷移と合わせて1枚の図にまとめる。

内容:
- `readyState`: `loading` → `interactive` → `complete`
- `interactive` になるのは「HTMLパース完了直後 / **defer/module実行前**」
- `DOMContentLoaded` は defer/module 実行完了後に発火
- **`document.readyState === "interactive"`の間にDCL listenerを付けることはまだ可能**という重要事実
- `async`やfetch等で遅延登録する場合は、DCLが既に発火している可能性があるので `readyState` を確認して分岐する
- `load`イベントは画像など全サブリソース完了後

根拠:
- [MDN DOMContentLoaded](https://developer.mozilla.org/en-US/docs/Web/API/Document/DOMContentLoaded_event)
- [MDN readyState](https://developer.mozilla.org/en-US/docs/Web/API/Document/readyState)
- `temp/web/extract_js_script_timing.json`

### 6. 複数ファイルの解決順 — モジュールグラフ

**主張**: 静的`import`があるモジュールは、ブラウザが**依存グラフを構築してから深さ優先で評価**する。実行順は「見た目の`<script>`順」ではなくグラフ形状で決まる。

内容:
- 静的importが**文字列リテラル限定、top-levelのみ**なのは「評価前に静的解析できるようにする」ため
- 評価3フェーズ: Construction(fetch+parse) → Linking → Evaluation
- 深さ優先評価で「葉から先に評価される」
- 循環依存 = どちらかの変数が未初期化で使われると`ReferenceError`。**使われなければ通る**(live binding)
- 小さなコード例: `a.js`と`b.js`の循環で`ReferenceError`が出る条件

根拠:
- [MDN JavaScript modules](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules)
- [MDN import statement](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Statements/import)
- `temp/web/extract_js_esm.json`

### 7. 動的 `import()` — 「遅延ロード」を手動で差し込む

**主張**: `import()`は**非モジュール環境でも使えるPromise**。初期ロードのグラフから切り離され、呼ばれた瞬間に新しい依存サブグラフが走り始める。

内容:
- 構文: 関数風の`import()`、`Promise<Module>`を返す
- 用途: 条件付きロード、動的パスのロード、非モジュール環境からESMを使う、ルート分割
- 引数は動的に決めてよい(静的importと違う)
- Import Attributes(`{ with: { type: "json" } }`)
- **初期ロード時は静的importを優先、動的importは必要最小限に**(tree shaking / 静的解析との兼ね合い)
- 10並列ロードの短い例

根拠:
- [MDN import()](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Operators/import)
- `temp/web/extract_js_esm.json`

### 8. Top-level `await` — モジュールがPromiseになる

**主張**: top-level awaitはモジュール評価フェーズで発火する。兄弟モジュールの評価はブロックしないが、**その awaited モジュールを import している親モジュール**は待たされる。

内容:
- モジュールのみで使える(classic scriptや`eval`では不可)
- 「fetch/linkは既に終わっているので、ネットワーク取得のブロックは発生しない」
- 親モジュールは待つが兄弟は待たない = モジュールが「大きな非同期関数」として振る舞う
- 小さな例: `export default await fetch(...)` パターン
- **循環 + top-level await = デッドロックの可能性**
- 表面的には `<script type="module">` のロードが「遅く見える」原因になる

根拠:
- [V8: Top-level await](https://v8.dev/features/top-level-await)
- [TC39 proposal-top-level-await](https://tc39.es/proposal-top-level-await/)
- [MDN JavaScript modules](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules)
- `temp/web/search_js_tla.json`

### 9. 「タイミング全体図」1ページまとめ

**主張**: ここまでの知見を1枚のタイムラインに統合する。

内容:
- 横軸: HTMLパース開始 → パース完了 → interactive → DCL → load
- 縦レーン: classic / async / defer / module / dynamic import / top-level await
- 各レーンに実行タイミングとevent listener登録可能になる瞬間をマーク
- 「このscriptタグ、あのscriptタグ、このimport、これがどう並ぶか」の絵

根拠:
- セクション2〜8の整理

### 10. なぜバンドラが必要か — 解いている問題を言語化

**主張**: バンドラが解決しているのは「手で書いた`<script>`順序依存」「無数のHTTPリクエスト」「古いブラウザ互換」「依存解決の複雑さ」。ESMがあっても消えない。

内容:
- 手動scriptタグ並べの破綻: 依存数が増えると順序管理が無理
- 多数の小ファイルでのネットワークオーバーヘッド(多HTTP往復)
- tree shaking(不要コード除去)、コード分割(遅延ロード単位の自動生成)、HMR(開発時差分適用)
- これらは「ブラウザのモジュール機構」だけでは得られない

根拠:
- [Vite: Why Vite](https://vitejs.dev/guide/why.html)
- [Rspack: Introduction](https://rspack.dev/guide/start/introduction)
- `temp/web/extract_js_bundlers.json`

### 11. ツール分類 — 何が何の役割を担っているか

**主張**: 「バンドラ」と一口に言っても役割が違う。3カテゴリに分けると現在地が見える。

内容:
- **(A) クラシックバンドラ**: Webpack / Rollup / Parcel — JSで実装、機能豊富だが遅い。Rollupはライブラリ向きESM出力、Webpackはアプリ向きの成熟エコシステム
- **(B) ネイティブコンパイラ/バンドラ**: esbuild(Go) / SWC(Rust) — 桁違いに速いが、機能はclassicより限定的。Go/Rustで実装されることで、JIT起動コストやJS自体の表現の非効率を回避
- **(C) ネイティブ製ウェブバンドラ**: Rspack(Rust、webpack API互換) / Turbopack(Rust、独自設計)
- **(D) devサーバ指向**: Vite — dev時は**未バンドルESMをオンデマンド配信**、prodはRolldown/Rollupでバンドル。2モードを使い分ける発想
- 現時点の実務の位置づけ(ライブラリ=Rollup、アプリ=Vite or Rspack/Webpack、低レベルツール=esbuild/SWC)を短く

根拠:
- [Vite: Why Vite](https://vitejs.dev/guide/why.html)
- [esbuild FAQ](https://esbuild.github.io/faq/)
- [Rspack: Introduction](https://rspack.dev/guide/start/introduction)
- `temp/web/extract_js_bundlers.json`, `temp/web/search_js_bundlers.json`

### 12. まとめ — 何を押さえれば「裏側」を理解したと言えるか

**主張**: 記事全体の要点を6〜8項目で言語化。タイミング/順序/ツール、どれもまず「ブラウザのscript処理モデル」が基礎になる。

内容:
- 「event listener登録タイミング=そのscriptが評価された瞬間」
- classic/async/defer/moduleの4モードの意味
- DOMContentLoaded は defer/module を待つが async は待たない
- ESMは静的解析→深さ優先評価、循環は live binding が救う
- 動的 import は Promise、top-level await は親を待たせるが兄弟は待たない
- バンドラは「順序」「最適化」「互換」を一括で解決するレイヤ。ツール選択は役割の違いで決める

---

## 参考URL一覧

### 仕様 / MDN

- [MDN `<script>`](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/script)
- [MDN DOMContentLoaded](https://developer.mozilla.org/en-US/docs/Web/API/Document/DOMContentLoaded_event)
- [MDN readyState](https://developer.mozilla.org/en-US/docs/Web/API/Document/readyState)
- [MDN JavaScript modules](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules)
- [MDN import statement](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Statements/import)
- [MDN import()](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Operators/import)
- [MDN await](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Operators/await)
- [HTML Standard](https://html.spec.whatwg.org/)

### Top-level await

- [V8: Top-level await](https://v8.dev/features/top-level-await)
- [TC39 proposal-top-level-await](https://tc39.es/proposal-top-level-await/)

### バンドラ

- [Vite: Why Vite](https://vitejs.dev/guide/why.html)
- [Rspack: Introduction](https://rspack.dev/guide/start/introduction)
- [esbuild FAQ](https://esbuild.github.io/faq/)

### 調査ファイル

- `temp/web/search_js_script_loading.json`
- `temp/web/search_js_bundlers.json`
- `temp/web/extract_js_script_timing.json`
- `temp/web/extract_js_esm.json`
- `temp/web/extract_js_bundlers.json`
- `temp/web/search_js_tla.json`
