---
title: "JavaScriptはいつ、どの順で動き出すのか — script読込・イベント登録・バンドラの裏側"
emoji: "⏱️"
type: "tech"
topics: ["javascript", "html", "esmodules", "webpack", "vite"]
published: false
---

## この記事について

「`addEventListener`を書いたのに動かない」「`defer`と`async`、結局どっちを使えばいいか説明できない」「`import`がズラッと並んでいるけど、どのファイルから実行されているのかよく分からない」「バンドラは便利だけど、裏で何をしているのか曖昧」。

中級以上のフロントエンドエンジニアでも、**JSがブラウザに読み込まれてから実際にコードが動き出すまでの「時間軸」**を正確に言語化できる人は意外と少ないです。この記事では、以下の問いに順番に答えていきます。

1. JSファイルの中の`addEventListener`等は、**いつ**登録されるのか
2. 複数の`<script>`や`import`がある場合、**どんな順**で評価・実行されるのか
3. 動的`import()`と top-level `await`が絡むと順序はどう変わるか
4. それを自動化するバンドラは、**裏で何を解いているのか**

仕様一次情報 (MDN / HTML Standard / V8 / TC39) を根拠にしつつ、コード例は必要なところだけ最小限で示します。

---

## 1. 「イベントリスナーが動かない」の正体

最初によくある失敗例を置いておきます。

```html
<!-- head 内 -->
<script src="app.js"></script>

<!-- body 内 -->
<button id="btn">click</button>
```

```js
// app.js
document.querySelector("#btn").addEventListener("click", () => {
  console.log("hi");
});
```

これは `Cannot read properties of null (reading 'addEventListener')` で落ちます。理由は単純で、**`app.js`が実行された時点ではまだ`#btn`が存在しない**からです。

ここから見える単純な事実は一つだけです。

> **「イベントリスナーは、そのコードが実行された瞬間の DOM に対して登録される」**

つまり「イベントリスナー登録のタイミング問題」は、「その script がいつ実行されるか」という問題に書き換えられます。そして、この **「いつ実行されるか」** が `<script>` の属性次第で劇的に変わる、というのがこの記事の主題です。

---

## 2. classic script: パースをブロックするのが基本

属性なしの`<script src="…">`、あるいはインライン`<script>`は、**HTMLパーサを止める**のが基本動作です[^mdn-script]。

[^mdn-script]: [MDN `<script>` element](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/script): 「Scripts without `async`, `defer` or `type="module"` attributes, as well as inline scripts without the `type="module"` attribute, are fetched and executed immediately before the browser continues to parse the page.」

```text
[HTML parse] ---→ [<script>到達] ──fetch──→ [parse + evaluate + execute] ──→ [HTML parse 再開]
                                    （この間、後続のHTMLはパースされない）
```

この「**parser-blocking**」挙動が、`addEventListener` が動かない事故の根本原因です。`head` の classic script は、後続の DOM がまだ存在しない時点で実行されます。

この時点では `document.readyState === "loading"` です[^mdn-readystate]。歴史的に「`<script>`は`</body>`の直前に置きましょう」というプラクティスが広まったのは、単純にこの**同期実行**を DOM 生成完了後に遅らせたかったからです。

[^mdn-readystate]: [MDN Document: readyState](https://developer.mozilla.org/en-US/docs/Web/API/Document/readyState): 「loading — The document is still loading (that is, the HTML parser is still working).」

---

## 3. `async` と `defer`: 非同期ロードの2系統

属性なしの classic は辛いので、非同期にロードする2系統が用意されています。どちらも**フェッチは並行**ですが、**実行タイミングと順序**が違います[^mdn-script]。

| 属性 | フェッチ | 実行タイミング | 実行順序 | パースを止めるか |
|------|---------|---------------|---------|-----------------|
| なし | ブロッキング | 即時 | 記述順 | 止める |
| `async` | 並行 | 取得完了次第すぐ | **順不同** | 実行中のみ止める |
| `defer` | 並行 | **HTMLパース完了後** | **記述順** | 止めない |

図にするとこうなります。

```text
classic : [HTML-----][fetch+exec][HTML-----]
async   : [HTML------[exec]--------------]（取れた瞬間どこかで割り込む）
defer   : [HTML---------------------][exec1][exec2]…（記述順）
```

使い分けの実務的な原則はシンプルです。

- **`async`**: 他スクリプトや DOM に依存しない計測タグやアナリティクス。順不同で構わないもの
- **`defer`**: DOMが揃っている前提で動くアプリ本体。`defer`同士は**記述順に実行される**ことが保証されているので、依存順に並べて書ける[^mdn-script-defer]

[^mdn-script-defer]: [MDN `<script>` element](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/script): 「Scripts with the `defer` attribute will execute in the order in which they appear in the document.」

---

## 4. `type="module"`: デフォルトで`defer`相当、だけど別物

モジュールスクリプトは、属性なしでも **`defer`相当の挙動**をします。`defer`属性を付けても無視されます[^mdn-script-module]。

[^mdn-script-module]: [MDN `<script>` element](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/script): 「The `defer` attribute has no effect on module scripts — they defer by default.」

```html
<script type="module" src="main.js"></script>  <!-- defer 相当 -->
<script type="module" async src="analytics.js"></script>  <!-- 取れ次第、順不同 -->
<script nomodule src="legacy.js"></script>  <!-- モジュール対応ブラウザは無視 -->
```

ただし、`defer` との決定的な違いは、モジュールスクリプトは**中で静的importを辿り、依存グラフを解決する**という重い仕事が裏で走る点です。モジュール評価の3フェーズは以下のとおりです。

1. **Construction**: 参照されている全モジュールを fetch し、parse する
2. **Linking**: 各モジュールの `import`/`export` を束ねて、メモリ上の live binding を作る
3. **Evaluation**: 依存グラフを**深さ優先**で辿り、順に評価する

「1ファイルしか書いてないのに裏で何十ファイルも動いている」のがモジュールスクリプトの通常運転です。ESMという仕様そのものの整理は §6 で、複数ファイルの評価順は §7 で掘り下げます。

---

## 5. `DOMContentLoaded` と `readyState` の正確な定義

ここまでを一本のタイムラインに落とすと、**`DOMContentLoaded`(DCL)と`readyState`がいつ進むのか**を正確に言えます。MDNの定義はこうです[^mdn-dcl]。

[^mdn-dcl]: [MDN DOMContentLoaded event](https://developer.mozilla.org/en-US/docs/Web/API/Document/DOMContentLoaded_event): 「The `DOMContentLoaded` event fires when the HTML document has been completely parsed, and all deferred scripts (`<script defer src="…">` and `<script type="module">`) have downloaded and executed.」

```text
readyState : loading ───────────→ interactive ────────────→ complete
HTML parse : [==========================]
classic    :     [fetch+exec]
defer      :     [======fetch======]            [exec（順）]
module     :     [=fetch+link=]                 [exec]
async      :                  [任意の時点で割り込み [exec]]
                                              ↑           ↑
                                         DCL fires    load fires
```

要点を整理すると、

- `readyState === "loading"`: HTMLパーサがまだ動いている
- `readyState === "interactive"`: HTMLパース完了直後。**defer/module スクリプトはまだ実行される前**の状態も含む
- `DOMContentLoaded`: **HTMLパース完了 + defer/module 実行完了**で発火。**async は待たれない**
- `readyState === "complete"`: **async 含むすべてのサブリソース完了**。`load` イベント直前

見落とされがちな2点:

### 5.1 `readyState === "interactive"` 中の DCL listener は間に合う

defer/module スクリプト本体が実行されている間、`readyState` は `"interactive"` ですが、**そこから `DOMContentLoaded` listener を付けても発火する**[^mdn-dcl-note]。モジュールの先頭で listener を登録すれば、その後の DCL をちゃんとキャッチできます。

[^mdn-dcl-note]: [MDN DOMContentLoaded event](https://developer.mozilla.org/en-US/docs/Web/API/Document/DOMContentLoaded_event): 「during the execution of deferred and module scripts, `document.readyState` is `"interactive"` but it's still possible to attach `DOMContentLoaded` listeners and make them fire as usual.」

### 5.2 `async` や動的ロードで後から動く場合は `readyState` を見る

`async`や `await fetch(...)`経由など、**DCL が既に過ぎた後**に初期化ロジックを走らせるケースでは、DCL listener を付けても二度と呼ばれません。このケースでは `readyState` を先に見て分岐します。

```js
function whenReady(fn) {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", fn, { once: true });
  } else {
    fn();
  }
}
```

classic script(`async`/`defer`なし、HTML初期マークアップ内)の場合は、ドキュメントがその script の実行完了を待ってから DCL を発火させるので、こういう分岐は不要です。

---

## 6. ESMとは何か — 仕様としてのモジュール

ここから複数ファイルの話に入る前に、**「ESM(ECMAScript Modules)」という仕様**そのものを押さえておきます。§4で触れた`type="module"`は、このESMをブラウザに読み込むための入り口であって、ESMというモデル自体はブラウザにもNodeにも共通です。

### 6.1 なぜ標準化されたのか — 方言の歴史

ES2015以前、「JSでモジュールを書く」という目的に対して、**互換性のない方言**が環境ごとに乱立していました。

| 方式 | 主な環境 | 代表的な記法 |
|------|---------|-------------|
| CommonJS (CJS) | Node.js | `require()` / `module.exports` |
| AMD | RequireJS 等 | `define(deps, factory)` |
| UMD | ライブラリ配布 | CJS+AMD両対応のラッパ |
| IIFE / global | ブラウザ素朴 | `window.MyLib = ...` |

ES2015で `import`/`export` が**言語仕様**として決着し、現在は **ブラウザ・Node(v13.2+)・Deno・Bun すべてがネイティブ対応**しています。`type="module"`は「このスクリプトはESMとして解釈せよ」というブラウザ向けの宣言です。

### 6.2 ESMの特徴 — 5つの約束事

CommonJSや古い方式との違いは、この5点に集約できます。

1. **静的構造**: `import`/`export` は**文(statement)**であり、式ではない。条件分岐・関数内・変数パスでは書けない。結果として**実行前に依存グラフが確定する**[^mdn-import-static-overview]
2. **strict modeがデフォルト**: `"use strict"` 不要。`this` はトップレベルで `undefined`
3. **独立したスコープ**: モジュール内で `var` 宣言しても**グローバルを汚染しない**(classic scriptだと `window` に漏れる)
4. **シングルトン評価**: 同じURL/パスのモジュールは**1回だけ**評価される。何度importしても**同じインスタンス**が共有される
5. **Live binding**: importされた識別子は**値のコピーではなくエクスポート元変数への参照**。エクスポート側で値が変われば import 側も追従する(`const` exportは再代入されないが、`let` exportの変化は観測できる)

[^mdn-import-static-overview]: [MDN import statement](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Statements/import): 「`import` declarations are designed to be syntactically rigid … which allows modules to be statically analyzed and linked before getting evaluated. This is the key to making modules asynchronous by nature, powering features like top-level await.」

### 6.3 CommonJSとの決定的な違い — 同期 vs 非同期

Node.jsをCJSで書いてきた人にとって最大のつまずきは、「**CJSは同期、ESMは非同期**」という点です。

```js
// CommonJS(同期、実行時に解決)
const x = require("./x"); // この行でファイルを読んで即評価
if (flag) {
  const y = require("./y"); // 関数内・条件内でもOK
}

// ESM(静的、評価前に依存解決)
import { x } from "./x.js"; // top-levelのみ、文字列リテラル必須
// if (flag) import { y } from "./y.js";  // ← 構文エラー
```

CJSは `require()` の評価が**ファイル実行中**に起きるので、条件分岐もループも書き放題な代わりに、**静的解析とtree shakingがしにくい**。ESMは「呼ぶ前に依存グラフを決める」制約を言語レベルで課すことで、ブラウザ・バンドラ・ランタイムが**フェッチとリンクを事前に並列化できる**余地を手に入れました。top-level awaitが成立するのも、この「非同期であることが前提」の設計の帰結です。

「どうしても実行時に動的解決したい」場合は、§8の `import()` 式を使います。これは構文規則としては**関数呼び出しの形**なので、ESMの静的制約から解放されます。

### 6.4 ブラウザもNodeも同じ見方ができる

`type="module"` を付けたブラウザスクリプトも、`package.json` に `"type": "module"` を書いたNodeの `.mjs` も、**同じESMの評価ルール**で動きます。深さ優先評価、シングルトン、live binding、top-level await ——どれも環境共通の言語仕様です。

以降の§7〜§9で扱う「評価順」「動的import」「top-level await」は、このESMモデルの上で成り立っている話だと思って読み進めてください。

---

## 7. 複数ファイルの解決順 — モジュールグラフ

ここから「複数ファイルの読み込み順」の話です。重要な点: **モジュール評価順は、見た目の`<script>`順ではなく「依存グラフの形」で決まります**。

### 7.1 なぜ静的importは「文字列リテラル限定、top-levelのみ」なのか

`import`文には強い構文制約があります。変数でパスを書けない、`if`の中に書けない、関数内に書けない。これは**評価前に依存グラフを静的解析するため**です[^mdn-import-static]。

[^mdn-import-static]: [MDN import statement](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Statements/import): 「`import` declarations are designed to be syntactically rigid (for example, only string literal specifiers, only permitted at the top-level, all bindings must be identifiers), which allows modules to be statically analyzed and linked before getting evaluated.」

この「**評価前に静的解析できる**」性質のおかげで、ブラウザやバンドラはソースを実行せずに「この依存グラフはこれです」と先に決められます。

### 7.2 深さ優先評価

依存グラフが理想的にDAG(循環なし)であれば、**深さ優先**で評価されます[^mdn-cyclic]。

```text
main.js ──imports──> a.js ──imports──> util.js
              │
              └──imports──> b.js
```

評価順は `util.js` → `a.js` → `b.js` → `main.js`。葉(リーフ)が先です。`<script type="module" src="main.js">` を1行書いただけで、この順序が決定論的に回ります。

### 7.3 循環依存は「使われなければ」通る

循環はグラフ構造としてよくあります。ESM は「どちらかの import が**まだ初期化されていない状態で使われたとき**」に限って `ReferenceError` を投げる設計です[^mdn-cyclic]。

[^mdn-cyclic]: [MDN JavaScript modules](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules): 「The imported variable's value is only retrieved when the variable is actually used (hence allowing live bindings), and only if the variable remains uninitialized at that time will a `ReferenceError` be thrown.」

```js
// a.js
import { b } from "./b.js";
export const a = "A";
export function useB() { return b; }  // 参照は後、評価時点では呼ばない → OK

// b.js
import { a } from "./a.js";
export const b = `B depends on ${a}`;  // トップレベルで a を使う → a が未初期化なら ReferenceError
```

ここが `import` の「**live binding**」と言われる所以です。import された名前は値のコピーではなく、**元モジュールの変数への参照**です。だから「名前は bind 済みだが初期化はまだ」の状態があり得ます。

---

## 8. 動的 `import()` — 「遅延ロード」を手動で差し込む

静的 `import` に加えて、関数風の `import()` 式があります。こちらは**Promise を返す**非同期ロード[^mdn-dynamic-import]です。

[^mdn-dynamic-import]: [MDN import()](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Operators/import): 「The `import()` syntax, commonly called dynamic import, is a function-like expression that allows loading an ECMAScript module asynchronously and dynamically into a potentially non-module environment.」

```js
button.addEventListener("click", async () => {
  const { renderChart } = await import("./chart.js");
  renderChart();
});
```

静的 `import` との違いをまとめると、

- **非モジュール環境でも使える**(classic scriptの中でもOK)
- **パスを動的に組み立てられる**
- **呼ばれるまでロードされない**(初期バンドルから切り離せる)
- **Import Attributes**が第2引数で使える: `await import("./data.json", { with: { type: "json" } })`

MDN は「初期依存は静的形式を優先、動的 import は必要なときだけ」と明言しています[^mdn-dynamic-tree-shaking]。理由は、静的 import の方が静的解析と tree shaking の恩恵を受けやすいからです。

[^mdn-dynamic-tree-shaking]: [MDN import()](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Operators/import): 「Use dynamic import only when necessary. The static form is preferable for loading initial dependencies, and can benefit more readily from static analysis tools and tree shaking.」

動的 import を使うと、初期ロード時のグラフに入らない**別のサブグラフ**が、そのタイミングで改めて構築・評価されます。ルート分割、条件分岐による重いライブラリの後ロード、管理画面だけで使う機能の切り出しなどが典型的な用途です。

---

## 9. Top-level `await` — モジュールが「大きな非同期関数」になる

モジュールの**トップレベル**で `await` が使えます。これがタイミング論をもう一段複雑にします[^mdn-tla]。

[^mdn-tla]: [MDN JavaScript modules](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules): 「Top level await is a feature available within modules. … It allows modules to act as big asynchronous functions meaning code can be evaluated before use in parent modules, but without blocking sibling modules from loading.」

```js
// colors.js（モジュール）
const colors = fetch("/colors.json").then((r) => r.json());
export default await colors;
```

この `colors.js` を import する親モジュールは、`fetch` が resolve するまで**評価を待たされます**。ただし「親を待たせる」のであって、**兄弟モジュールの評価はブロックしない**のがポイントです[^v8-tla]。

[^v8-tla]: [V8: Top-level await](https://v8.dev/features/top-level-await): 「As siblings are able to execute, there is no definitive blocking. Top-level `await` occurs during the execution phase of the module graph. At this point all resources have already been fetched and linked. There is no risk of blocking fetching resources.」

言い換えると、

- **モジュール評価フェーズ**で発火する(fetch/link はもう終わっている)
- **ネットワーク取得を止めることはない**
- **親モジュールは awaited モジュールの完了を待つ**
- **兄弟モジュールの評価は並行して進む**

classic script や CommonJS では使えず、**モジュール専用**の機能です[^v8-tla]。

注意点として、**循環 + top-level await はデッドロックを作れます**[^v8-tla-deadlock]。`a.js` が `b.js` を待ち、`b.js` が `a.js` を待つ形を作ってしまうと永久に進みません。循環を書くときは top-level await を混ぜないのが無難です。

[^v8-tla-deadlock]: [V8: Top-level await](https://v8.dev/features/top-level-await): 「with top-level `await`, circular module dependencies could introduce a deadlock.」

---

## 10. タイミング全体図 — 1枚でまとめる

ここまでの話を1本の時間軸に置くと、こうなります。

```text
時刻 →

HTML parse   : [=================]
classic      :    [fetch+exec]                      （パースをブロック）
defer #1/#2  :    [=fetch=]    [=fetch=]
                                        [exec#1][exec#2]   （順序保証、DCL前）
module       :    [=fetch+link=]         [eval（深さ優先）]
 ├ TLA あり  :                           [eval... await... eval再開]
 └ 動的import:                                           [click等] [追加fetch+link+eval]
async        :              [=fetch=]          [exec]    （順不同、DCL後のこともある）

readyState   : loading ───────→ interactive ──→ complete
events       :                              DCL ↑         load ↑
```

**重要な対応関係:**

- `addEventListener` の登録が走るのは、**そのスクリプトの`exec`セル**の中
- DOMに依存するコードは、**DCL 以降**(= defer / module 実行完了後)に走らせる
- 動的 import や async での遅延ロードは、**DCL 後**になる可能性があるので `readyState` 分岐が要る
- top-level await を含むモジュールは、**自分の exec セルを長く引き伸ばす**(親も長くなる、兄弟は伸びない)

---

## 11. なぜバンドラが必要か — 解いている問題を言語化

ここまで「ブラウザ側だけ」の話でしたが、実務では`<script>`を手で並べるのは数ファイルが限界です。依存数が増えると、次の4点で破綻します。

### 11.1 手動scriptタグの順序管理が無理

クラシックスクリプト時代、`jquery.js` → `plugin.js` → `app.js` みたいに**人間が記述順を維持**する必要がありました。100ファイルになると絶望的です。ESM を使えば `import` で依存が明示されるので順序問題は消えますが、次の問題が残ります。

### 11.2 多数の小ファイル = 多数のHTTPリクエスト

未バンドルのESMは、**依存の深さだけネットワーク往復が発生**します。数千モジュールの本番ビルドでそのまま配ると、HTTP/2 でも初期表示が重くなります。Vite もこれを認識しており、「極端に大規模なコードベースでは未バンドルESMは遅くなりうる」と明記しています[^vite-why-bundle]。

[^vite-why-bundle]: [Vite: Why Vite](https://vitejs.dev/guide/why.html): 「exceptionally large codebases can experience slow page loads due to the high number of unbundled network requests」

### 11.3 不要コードの除去(tree shaking)

`lodash` から `debounce` だけ使っても、手で`<script>`を並べたら全体が乗ります。バンドラは静的import解析で「使われていないexport」を判定し、出力から除去できます。

### 11.4 開発時のフィードバック速度(HMR)

1ファイル変更のたびにブラウザをフルリロードするのは遅すぎる。バンドラ/devサーバは**変更差分だけを走る中のアプリに注入**します(Hot Module Replacement)。これも生のESMだけでは実現できません。

> 「バンドラ」は、ブラウザの script/module 機構が**解かない部分**(順序、最適化、互換、HMR)を引き受けるレイヤー、と捉えるのが一番スッキリします。

---

## 12. ツール分類 — 何が何の役割を担っているか

「バンドラ」と一口に言っても、**何をどこまで担うか**で性格が違います。現状のツール群は4カテゴリに整理できます。

### (A) クラシックバンドラ

**Webpack / Rollup / Parcel**。実装言語は JavaScript。機能は豊富で、プラグインエコシステムが巨大ですが、**大規模プロジェクトでは遅い**のが常にネックでした。

- **Rollup**: ライブラリ向きの ESM 出力が綺麗。Vite の本番ビルドの裏でも長く使われてきた[^rspack-vs-rollup]
- **Webpack**: 最も成熟、設定の柔軟性が高い、アプリ向け
- **Parcel**: ゼロコンフィグ志向、HTML/CSS もビルトイン

[^rspack-vs-rollup]: [Rspack Introduction](https://rspack.dev/guide/start/introduction): 「Rollup is more suitable for bundling libraries, while Rspack is more suitable for bundling applications.」

### (B) ネイティブコンパイラ/バンドラ

**esbuild(Go) / SWC(Rust)**。ソース → ASTの変換・最適化・出力を**ネイティブコード**で一気に行うことで、JS実装の数倍〜数十倍の速度を出します[^esbuild-why-fast]。

[^esbuild-why-fast]: [esbuild FAQ](https://esbuild.github.io/faq/): 「Most other bundlers are written in JavaScript, but a command-line application is a worst-case performance situation for a JIT-compiled language. … Every time you run your bundler, the JavaScript VM is seeing your bundler's code for the first time without any optimization hints.」

ただし esbuild は自前のHMRや細粒度のコード分割(`optimization.splitChunks`)を持たないなど、**機能面は classic より絞られている**[^rspack-vs-esbuild]。単体でアプリ全体を賄うより、**上位ツールから呼ばれるエンジン**として使われる場面が多いです(例: Vite が dev 時の依存プレバンドルに esbuild を使用)。

[^rspack-vs-esbuild]: [Rspack Introduction](https://rspack.dev/guide/start/introduction): 「esbuild's feature set is not as complete as webpack, for example missing HMR and optimization.splitChunks features.」

### (C) ネイティブ製ウェブバンドラ

**Rspack / Turbopack**。Rust製、本番向けアプリバンドラ。

- **Rspack**: webpack API互換を狙う「drop-in replacement」。既存webpack資産を活かして高速化したい現場向け[^rspack-compat]
- **Turbopack**: webpack互換を捨てて再設計。移行コストは高いが、アーキテクチャはモダン[^rspack-vs-turbopack]

[^rspack-compat]: [Rspack Introduction](https://rspack.dev/guide/start/introduction): 「Launched as a drop-in replacement for webpack, with more powerful features and exceptional productivity」

[^rspack-vs-turbopack]: [Rspack Introduction](https://rspack.dev/guide/start/introduction): 「Turbopack is implemented in Rust like Rspack, but Turbopack started over with a redesigned architecture and configuration. This brings some benefits, but presents a steeper migration cost for projects that rely on webpack and its extensive ecosystem.」

### (D) devサーバ指向

**Vite**。「dev と prod でやり方を分ける」発想が特徴です[^vite-split]。

- **dev時**: ネイティブESMをブラウザに**そのまま**配信し、編集されたファイルだけHMRで差し替える。全量バンドルしないので起動はほぼ瞬時
- **prod時**: Rollup(将来は Rolldown)でバンドル
- **依存プレバンドル**: 頻繁に変わらない`node_modules`は esbuild で事前にまとめておき、dev 時のリクエスト数を減らす

[^vite-split]: [Vite: Why Vite](https://vitejs.dev/guide/why.html): 「Dependencies (libraries that rarely change) are pre-bundled once using fast native tooling, so they're ready instantly. Source code (your application code that changes frequently) is served on-demand over native ESM.」

### 使い分けの現在地(大まかな目安)

| 目的 | 典型的な選択 |
|------|-------------|
| アプリの dev 体験最優先 | Vite |
| webpack 資産を活かしつつ高速化 | Rspack |
| ライブラリ配布 | Rollup(またはtsup等の薄いラッパー) |
| 低レベルの高速コンパイル/バンドル | esbuild / SWC(他ツールの内部エンジンとしても) |
| 既存の成熟した巨大設定 | Webpack |

ここは流動的です。今後の選択は「ツールの名前」ではなく「**ツールがA〜Dのどの役割を担っているか**」で見ると、新ツールが出てきても位置づけがすぐ分かります。

---

## 13. 実務ケース — 複数ページで共通するJSをどう扱うか

ここまで「1つのエントリがどう読み込まれるか」を掘ってきました。最後に、**複数ページを持つ実アプリで共通するJSをどう配るか**という現場の論点を整理します。バンドラが裏でやってくれていることの全体像が見えると、設定を書くときや遅いページを診断するときの指針になります。

### 13.1 典型ケース

中規模以上のウェブアプリには、だいたいこういう構造があります。

```text
ページ     使うもの
──────     ─────────────────────────────────────
/          React + UIライブラリ + 認証 + トップページ固有ロジック
/products  React + UIライブラリ + 認証 + 商品一覧ロジック
/cart      React + UIライブラリ + 認証 + カートロジック
```

横串で共通するもの(React / UIライブラリ / 認証処理)と、ページ固有のもの(各ビジネスロジック)が混在しています。これを**ネットワーク量・キャッシュヒット率・初期表示速度**の観点で最適に配るのが、ここでの問題です。

### 13.2 素朴にやると何が困るか

#### ❌ 手で`<script>`順を並べる(classic時代のやり方)

各ページの`<head>`に`jquery.js` → `ui.js` → `auth.js` → `page.js`と並べる方式。順序管理と**バージョンの一貫性**が人力になり、100ページになると破綻します。`defer`/`module`で緩和はできても、「どのページに何を置くか」の管理は残ります。

#### ❌ ページごとに独立バンドル

各ページで`import "react"`しているからと**ページ数ぶんバンドル**を作ると、**Reactが全バンドルにコピーされる**。1ページ目で読んだReactを2ページ目で使い回せず、転送量もブラウザキャッシュも非効率です。

#### ❌ 全部まとめて1個のバンドル

逆に全ページを1つのバンドルにまとめると、トップページに`/cart`のコードまで含まれて**初期ロードが重くなる**。

### 13.3 解決の骨格 — Code Splitting + Shared Chunk

バンドラの解は、ざっくり言えば**「共通部分を別チャンクに切り出し、各ページのHTMLから複数JSを読み込む」**です。

```text
dist/
  vendor.[hash].js   ← node_modules由来(React等、更新頻度低)
  common.[hash].js   ← アプリ共通コード(認証、レイアウト等)
  home.[hash].js     ← トップページ固有
  products.[hash].js ← 商品一覧固有
  cart.[hash].js     ← カート固有
```

各ページのHTMLは、必要なチャンクだけを `<script type="module" defer>` で列挙します。

```html
<!-- /products のHTML -->
<script type="module" src="/dist/vendor.9f3a.js"></script>
<script type="module" src="/dist/common.b41e.js"></script>
<script type="module" src="/dist/products.2d7c.js"></script>
```

共通チャンクは**ページ遷移しても再利用される**(ブラウザキャッシュヒット)ため、2ページ目以降の表示が速くなります。ESMがシングルトン評価(§6.2)なので、同じモジュールが重複ロードされても**同一インスタンスとして振る舞う**のも嬉しい点です。

### 13.4 ツール別の実装

| ツール | 共通チャンク分離の仕組み |
|--------|-------------------------|
| **Webpack / Rspack** | `optimization.splitChunks` — 既定で`node_modules`や複数entryから参照されるモジュールを自動分離[^rspack-splitchunks] |
| **Rollup / Vite** | `output.manualChunks` — 関数または辞書で「このモジュールはこのチャンクへ」と指定 |
| **Parcel** | ゼロコンフィグ。動的importを境界に自動分割 |
| **Next.js / Nuxt / SvelteKit** | フレームワーク側が分割戦略を内蔵(ページ単位・共有・ベンダで自動分離) |

[^rspack-splitchunks]: [Rspack Introduction](https://rspack.dev/guide/start/introduction): 「All of the existing bundling solutions also had various limitations when optimizing for a production environment, such as insufficiently fine-grained code splitting.」Rspackは細粒度のコード分割を設計目標に据えている。

設定例(Vite / Rollupの`manualChunks`):

```js
// vite.config.js
export default {
  build: {
    rollupOptions: {
      input: {
        home:     "src/home.html",
        products: "src/products.html",
        cart:     "src/cart.html",
      },
      output: {
        manualChunks: {
          react: ["react", "react-dom"],
          ui:    ["@mui/material", "@emotion/react"],
        },
      },
    },
  },
};
```

`input` に複数HTMLを登録するのがMPA(Multi-Page App)の作法、`manualChunks`でベンダをまとめるのが共通化の作法です。

### 13.5 SPAならルート単位に動的import

Single Page Applicationでは、ページ遷移も1つのバンドル内で起きるのでHTMLのエントリは1つです。それでも初期ロードを軽くしたいときは、**ルートごとに動的importで分離**します。

```js
// React Router + React.lazy
const Home = lazy(() => import("./pages/Home.jsx"));
const Cart = lazy(() => import("./pages/Cart.jsx"));

<Routes>
  <Route path="/" element={<Home />} />
  <Route path="/cart" element={<Cart />} />
</Routes>
```

§8で見た `import()` 式は、バンドラにとって**自然な分割境界**です。バンドラは`Home.jsx`と`Cart.jsx`をそれぞれ別チャンクに出力し、**ルート遷移時に初めてfetchする**動きが自動で得られます。Vue(`defineAsyncComponent`)、SvelteKit、Next.js、Nuxtなども同じメカニズムで動いています。

「重いライブラリだが一部の画面でしか使わない」(チャート、リッチエディタ、PDFプレビューなど)も、この動的importパターンが定石です。

### 13.6 キャッシュ戦略 — ファイル名にハッシュを入れる

「共通チャンクを切り出した」だけでは片手落ちで、**長期キャッシュを効かせる**配信設計が要ります。鍵はファイル名です。

- 内容ベースのハッシュを付与: `common.9f3a2b.js` のように
- HTMLから参照するURLも、ビルドごとに書き換える
- `Cache-Control: max-age=31536000, immutable` で1年キャッシュ可能
- 内容が変われば別ファイル名になるので**キャッシュ破棄の問題が起きない**

HTML自体は短寿命キャッシュ(もしくは都度検証)にして、中のスクリプト参照だけを更新する、というのが典型構成です。バンドラは**ハッシュ付きファイル名の生成**と、**HTMLへの参照差し替え**までまとめて面倒を見てくれます。`vendor`チャンクのように更新頻度の低いものと、`home`のように頻繁に変わるものを分けておくと、ユーザー側のキャッシュが最大限効きます。

### 13.7 判断フロー

実装レベルで「どう分けるか」と迷ったとき、以下の順に考えると整理しやすいです。

1. **`node_modules`は`vendor`チャンクに分離**(更新頻度が低く、長期キャッシュが効く)
2. **複数ページで共通するアプリコード**(認証、レイアウト、共通ユーティリティ)は`common`チャンクに分離
3. **ページ固有コード**はページ単位のentry(MPA)、またはルート分割の動的import(SPA)
4. **重いライブラリで一部画面でしか使わないもの**(チャート、エディタ等)は、その画面内でさらに動的import
5. **ファイル名にハッシュ**を入れて不可変キャッシュにする

この5ステップで、たいていの「複数ページ共通JSをどう配るか」問題は説明できます。**バンドラが自動でやってくれる部分(1,2)、設定で明示する部分(2,3)、コード側で表現する部分(4)** の三層構造になっている、と理解しておくと、ツールが変わっても応用が効きます。

---

## 14. まとめ — 押さえるべき7点

1. **「イベントリスナーが登録される瞬間」=「そのscriptが評価された瞬間」**。他は全部これに還元できる
2. **classic / async / defer / module** の4モードを区別できるようになれ。`defer`は記述順保証、`module`はデフォルト`defer`相当+依存グラフ解決
3. **`DOMContentLoaded` は defer / module を待つが async は待たない**。`readyState` の `loading` / `interactive` / `complete` と併せて把握する
4. **ESMは「静的構造・strict・スコープ分離・シングルトン・live binding」の5つを持つ言語仕様**。ブラウザとNodeで共通のモデル、CJSと違って評価前に依存グラフが決まる
5. **ESM の複数ファイル評価順は「記述順」ではなく「依存グラフの深さ優先」**。循環は live binding のおかげで、未初期化参照しない限り通る
6. **動的 `import()` は Promise**。初期グラフから切り離せる。**top-level `await` は親を待たせるが兄弟は待たせない**
7. **バンドラはブラウザ機構が解かない部分(順序・最適化・HMR・互換)を担うレイヤ**。複数ページ共通のJSは**vendor / common / ページ固有**のチャンクに分けてハッシュ付きで配るのが定石

このモデルが頭に入っていると、「なぜ動かない」「なぜこの順で走る」「なぜこのツールを選ぶ」「なぜこう分割する」がだいたい自分で説明できるようになります。

---

## 参考資料

- [MDN `<script>` element](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/script)
- [MDN DOMContentLoaded event](https://developer.mozilla.org/en-US/docs/Web/API/Document/DOMContentLoaded_event)
- [MDN Document: readyState](https://developer.mozilla.org/en-US/docs/Web/API/Document/readyState)
- [MDN JavaScript modules](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules)
- [MDN import statement](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Statements/import)
- [MDN import()](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Operators/import)
- [V8: Top-level await](https://v8.dev/features/top-level-await)
- [TC39 proposal-top-level-await](https://tc39.es/proposal-top-level-await/)
- [Vite: Why Vite](https://vitejs.dev/guide/why.html)
- [Rspack: Introduction](https://rspack.dev/guide/start/introduction)
- [esbuild FAQ](https://esbuild.github.io/faq/)
