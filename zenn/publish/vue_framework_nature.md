---
title: "Vueを「コンパイラ付きリアクティブランタイム」として捉え直す — 解く問題・持ち込む問題・付き合い方"
emoji: "💚"
type: "tech"
topics: ["vue", "frontend", "javascript", "architecture"]
published: false
---

## この記事について

Vueは毎日書いている。`ref`も`reactive`も`computed`も`watch`も、`<script setup>`のパターンも手が勝手に書ける。
それでも、同僚や後輩に「なぜVueなのか」「Vueは何を解いて、何を代償にしているのか」と聞かれて、**30秒で自分の言葉で答えられるか**と言われると、意外と詰まる人は多いはずです。

姉妹記事で Reactを「UIランタイム」として捉え直しました。この記事では同じ視点でVueを見直します。文法は一切説明しません。**フレームワーク全体の性質**として、

1. ネイティブJSが詰んだ問題に対して、VueはReactと何を共有し、何を別に賭けたのか
2. Vue が自分の制約として引き受けた代償は何か
3. その性質から自然に導かれる「勝ち筋」と「地雷」は何か
4. どのユースケースでVueが有利/不利になるのか

を、公式 Docs と Vue チームの発信を根拠に整理します。日常でVueを書いている人が、**原理のレベルで判断できる軸**を手に入れることがゴールです。

コード例は、原理を示すのに必要な最小限だけ添えます。関連しない部分は `...` で省略します。

---

## 1. 出発点はReactと同じ — 「状態空間の爆発」

まず出発点を揃えます。Reactが必要になる前、命令的に書かれていたUIコードは、ざっくり次のループでした。

```js
input.addEventListener('input', (e) => {
  state.query = e.target.value;
  if (state.query.length > 0) {
    clearButton.hidden = false;
  } else {
    clearButton.hidden = true;
  }
  // 他に影響する箇所も全部、自分で洗い出して更新する
});
```

小さなフォームなら回りますが、相互作用が N 個あると整合性の面が O(N²) 以上に膨らむ。これはR版記事で書いたとおりです。

Vue公式も同じ問題認識から入ります:

> Declarative Rendering: Vue extends standard HTML with a template syntax that allows us to declaratively describe HTML output based on JavaScript state.
> Reactivity: Vue automatically tracks JavaScript state changes and efficiently updates the DOM when changes happen.
> ([vuejs.org / Introduction](https://vuejs.org/guide/introduction))

つまり、**「状態 → ビュー」の写像を宣言的に書き、DOM同期はフレームワークに任せる**。この方向までは React とまったく同じです。

違うのはここから先。Reactは「状態→ビューを**純関数**として書かせ、**ツリー全体を diff で整合性に戻す**」に賭けました。Vue は「**値の変化を値自身に監視させる**=細粒度リアクティビティと、**コンパイラが runtime を助ける**」という、**別の賭け**をしています。

---

## 2. Vueは「DOMライブラリ」ではなく「コンパイラ付きリアクティブランタイム」

Vueを「テンプレート言語を持つReact風のもの」として捉えているとかなり解像度が落ちます。より正確なモデルは **compiler-informed reactive runtime** です。公式はこれを明示しています:

> In Vue, the framework controls both the compiler and the runtime. This allows us to implement many compile-time optimizations that only a tightly-coupled renderer can take advantage of. ... We call this hybrid approach **Compiler-Informed Virtual DOM**.
> ([vuejs.org / Rendering Mechanism](https://vuejs.org/guide/extras/rendering-mechanism))

ここから引ける性質は3つあります。

### 2.1 リアクティビティは「値」単位で成立している

Vue の反応性システムは `Proxy` と getter/setter による依存追跡です:

> Vue 2 used getter / setters exclusively due to browser support limitations. In Vue 3, Proxies are used for reactive objects and getter / setters are used for refs.
> ([vuejs.org / Reactivity in Depth](https://vuejs.org/guide/extras/reactivity-in-depth))

重要なのは、Vue のランタイムは **「どの値が変わったとき、誰が再実行すべきか」を直接知っている** ということです。Reactはコンポーネントツリーを再実行して Virtual DOM を diff することで整合性を出すモデルですが、Vue ではそもそも「再実行が必要な reactive effect」だけが走ります。同じ "virtual DOM" という言葉でも、やっている仕事が違います。

公式はこの反応性プリミティブを最近の signals と同列に位置づけています:

> Fundamentally, signals are the same kind of reactivity primitive as Vue refs. It's a value container that provides dependency tracking on access, and side-effect triggering on mutation.
> ([vuejs.org / Reactivity in Depth](https://vuejs.org/guide/extras/reactivity-in-depth))

### 2.2 コンパイラが runtime を縮める

多くのフレームワーク(含むReact)は、コンパイラと runtime が疎結合です。Reactのコードは基本的に素のJSで、Babel/TSC は型や JSX を落とす以上のことはしない。一方 Vue では、テンプレートコンパイラが静的解析をかけて、runtime の仕事を前もって縮めます:

> The compiler can statically analyze the template and leave hints in the generated code so that the runtime can take shortcuts whenever possible.
> ([vuejs.org / Rendering Mechanism](https://vuejs.org/guide/extras/rendering-mechanism))

具体的には、静的ノードのホイスト、動的ノードのフラット化、バインディング種別のヒント埋め込みなど。結果として Vue 3 は Vue 2 比で **up to 55% faster initial render, up to 133% faster updates** と公式がアナウンスしています:

> Vue 3 has demonstrated significant performance improvements over Vue 2 in terms of bundle size (up to 41% lighter with tree-shaking), initial render (up to 55% faster), updates (up to 133% faster), and memory usage (up to 54% less).
> ([blog.vuejs.org / Announcing Vue 3.0](https://blog.vuejs.org/posts/vue-3-one-piece))

トップページの次の一文は、この賭けを端的に表しています:

> Truly reactive, compiler-optimized rendering system that **rarely requires manual optimization**.
> ([vuejs.org](https://vuejs.org/))

Reactの `useMemo` / `useCallback` / `memo` を読者に強いる姿勢と真っ向から対照的です。「自動でよしなに」を runtime の設計で押し切るのがVueのスタンスです。

### 2.3 Progressive Framework — 徐々に導入できる

Vueは「使い方のレイヤー」を明示的に段階化している珍しいフレームワークです:

> Depending on your use case, Vue can be used in different ways:
> - Enhancing static HTML without a build step
> - Embedding as Web Components on any page
> - Single-Page Application (SPA)
> - Fullstack / Server-Side Rendering (SSR)
> - Jamstack / Static Site Generation (SSG)
> - Targeting desktop, mobile, WebGL, and even the terminal
> ([vuejs.org / Introduction](https://vuejs.org/guide/introduction))

Reactが「UIランタイムだけを提供し、アプリ化は外部(Next.js 等)に任せる」という**狭く深い**切り方をしているのと対照的に、Vueはルーティング(Vue Router)、状態管理(Pinia)、フルスタック(Nuxt)まで公式/準公式の直線的な連続体として提供しています。

---

## 3. Vueが「新しく持ち込んだ」4つの問題

Reactの賭けが利用者に4つの新しい義務を押しつけたように、Vueの賭けも代償を伴います。

### 3.1 反応性プリミティブの二元性 — `ref` と `reactive`

Vue 3 の反応性プリミティブは2つあり、技術的な理由で分かれています。

- `ref()`: 任意の値を `.value` で包む。プリミティブもOK。
- `reactive()`: オブジェクトを Proxy でラップする。`.value` は不要だが、制約がある。

`reactive()` の限界は公式が明示しています:

> The `reactive()` API has a few limitations:
> 1. **Limited value types**: it only works for object types ... It cannot hold primitive types such as `string`, `number` or `boolean`.
> 2. **Cannot replace entire object**: since Vue's reactivity tracking works over property access, we must always keep the same reference to the reactive object. This means we can't easily "replace" a reactive object because the reactivity connection to the first reference is lost.
> ([vuejs.org / Reactivity Fundamentals](https://vuejs.org/guide/essentials/reactivity-fundamentals))

つまり、

```js
let state = reactive({ count: 0 });
state = reactive({ count: 1 }); // 反応性は切れる
```

ができません。Proxy を通じた property access で依存追跡しているので、「proxyそのものの置き換え」は追跡の外側です。

加えて分割代入で反応性が切れます:

```js
const { count } = reactive({ count: 0 });
// count はただの number。以後 count++ しても再レンダーされない
```

これを埋めるために、Vue は `toRefs` / `toRef` / `toValue` という補助 API を用意しています:

> `toRefs` is useful when returning a reactive object from a composable function so that the consuming component can destructure/spread the returned object without losing reactivity.
> ([vuejs.org / Reactivity API: Utilities](https://vuejs.org/api/reactivity-utilities))

公式ドキュメント自身が「composableは`reactive`ではなく`ref`で返すのを推奨」と書いています:

> You have probably noticed that we have been exclusively using `ref()` instead of `reactive()` in composables. The recommended convention is for composables to always return a plain, non-reactive object containing multiple refs. This allows it to be destructured in components while retaining reactivity.
> ([vuejs.org / Composables](https://vuejs.org/guide/reusability/composables))

一方 `ref` 側の税金は `.value`:

> It's easy to lose reactivity when destructuring reactive objects, while it can be cumbersome to use `.value` everywhere when using refs. Also, `.value` is easy to miss if not using a type system.
> ([vuejs.org / Reactivity Transform](https://vuejs.org/guide/extras/reactivity-transform.html))

**Reactとの対比**: React は「参照同一性」(`Object.is`) が抽象から漏れました。Vue は「反応性の連結」が抽象から漏れています。どちらも runtime の制約がユーザーに降りてきている姿で、片方を選ぶことは**どちらの漏れと付き合うかを選ぶこと**です。

### 3.2 Proxy identity — 生オブジェクトと proxy は別物

もう一つの識別性問題が、Proxy と元オブジェクトの不一致です。

```js
const raw = {};
const proxy = reactive(raw);
console.log(proxy === raw); // false
```

> Only the proxy is reactive - mutating the original object will not trigger updates. Therefore, the best practice when working with Vue's reactivity system is to exclusively use the proxied versions of your state.
> ([vuejs.org / Reactivity Fundamentals](https://vuejs.org/guide/essentials/reactivity-fundamentals))

ネストされたオブジェクトを取り出すと、取り出した時点で proxy になります:

```js
const proxy = reactive({ nested: {} });
const raw = {};
proxy.nested = raw;
console.log(proxy.nested === raw); // false
```

これを踏まえずに 3rd party ライブラリのインスタンスや巨大な不変データを `reactive` に入れると、**identity hazard** と呼ばれる問題に遭います。公式は `markRaw` / `shallowReactive` / `shallowRef` を用意して明示的にオプトアウトさせます:

> Some values simply should not be made reactive, for example a complex 3rd party class instance, or a Vue component object. Skipping proxy conversion can provide performance improvements when rendering large lists with immutable data sources. They are considered advanced because the raw opt-out is only at the root level, so if you set a nested, non-marked raw object into a reactive object and then access it again, you get the proxied version back. **This can lead to identity hazards** — i.e. performing an operation that relies on object identity but using both the raw and the proxied version of the same object.
> ([vuejs.org / Reactivity API: Advanced](https://vuejs.org/api/reactivity-advanced))

**実務的な含意**: Vue で「reactive に何を入れるか」は単なるスタイルではなく設計判断です。**「観測可能にすべきでないもの」を誤って reactive に入れると、identity 依存のロジックが壊れる**。これはReactの「毎レンダー新規オブジェクトを生やすと memo が効かない」と同じ性質の、runtime 由来の制約です。

### 3.3 `watch` / `watchEffect` は「ライフサイクル」ではなく「同期プリミティブ」

ここはReactの Effect とほぼ同じ罠があります。公式の立場は一貫していて、**派生は `computed`、外部との同期は `watch`/`watchEffect`** と役割を切っています。

用語集で Vue は reactive effect を明確に定義しています:

> A reactive effect is part of Vue's reactivity system. It refers to the process of tracking the dependencies of a function and re-running that function when the values of those dependencies change. `watchEffect()` is the most direct way to create an effect. Various other parts of Vue use effects internally. e.g. component rendering updates, `computed()` and `watch()`.
> ([vuejs.org / Glossary](https://vuejs.org/glossary/))

つまり、**コンポーネントの再レンダーも `computed` も `watch` もすべて同じ reactive effect メカニズムの上にある**ということです。このうち `computed` は「派生値を宣言する」、`watch` は「ソースが変わったら副作用を走らせる」、`watchEffect` は「依存を自動追跡して副作用を走らせる」。

具体的にどれを使うべきかは公式が例示しています:

```js
// NG: watchを使って派生値を同期する
watch(A0, (v) => { A2.value = v + A1.value });

// OK: computed で派生値を宣言する
const A2 = computed(() => A0.value + A1.value);
```

> Using a reactive effect to mutate a ref isn't the most interesting use case - in fact, using a computed property makes it more declarative.
> ([vuejs.org / Reactivity in Depth](https://vuejs.org/guide/extras/reactivity-in-depth))

これはReactで「useEffect + setState で派生を作るな」と言われているのと同じ話です。**「計算できるもの」は `computed` で宣言する。「外部世界への反映(DOM、API、localStorage、3rd party)」だけ `watch`/`watchEffect`** — これが原則です。

`watch` と `watchEffect` の差も、依存追跡の明示性だけです:

> `watch` only tracks the explicitly watched source. ... `watchEffect`, on the other hand, combines dependency tracking and side effect into one phase. It automatically tracks every reactive property accessed during its synchronous execution. This is more convenient and typically results in terser code, but makes its reactive dependencies less explicit.
> ([vuejs.org / Watchers](https://vuejs.org/guide/essentials/watchers))

`watchEffect` には副作用と依存追跡の境界が暗黙になる代わりに、Reactの依存配列の手動管理が要らないという利点があります。ただし、非同期 `watchEffect` では `await` 以前のアクセスだけが追跡される、というトラップが残ります:

> `watchEffect` only tracks dependencies during its synchronous execution. When using it with an async callback, only properties accessed before the first `await` tick will be tracked.
> ([vuejs.org / Watchers](https://vuejs.org/guide/essentials/watchers))

**Reactとの対比**: Reactは「render中に計算できるならEffect不要」。Vueは「`computed`で書けるなら`watch`不要」。原理は同じです。どちらも **宣言的に派生するか、手続きで同期するか** をユーザーに分別させます。

### 3.4 リスト identity は `v-for` + `key` に固定される

これは React と構造がほぼ同じです。公式は `v-for` のデフォルト挙動を "in-place patch" と呼んでいます:

> When Vue is updating a list of elements rendered with `v-for`, by default it uses an "in-place patch" strategy. If the order of the data items has changed, instead of moving the DOM elements to match the order of the items, Vue will patch each element in-place and make sure it reflects what should be rendered at that particular index. **This default mode is efficient, but only suitable when your list render output does not rely on child component state or temporary DOM state** (e.g. form input values).
> ([vuejs.org / List Rendering](https://vuejs.org/guide/essentials/list))

つまり、Vue の default は「同じ index を使い回して上書き」。リスト内の子コンポーネントが state を持つ、あるいは `<input>` の value を持つなら、`:key` を必ず付けないと**並び替えで状態がズレます**。

`key` の役割は Vue 側も明確:

> Without keys, Vue uses an algorithm that minimizes element movement and tries to patch/reuse elements of the same type in-place as much as possible. With keys, it will reorder elements based on the order change of keys, and elements with keys that are no longer present will always be removed / destroyed. ... It can also be used to **force replacement of an element/component instead of reusing it**.
> ([vuejs.org / Built-in Special Attributes](https://vuejs.org/api/built-in-special-attributes))

Reactで `<Profile key={userId} />` と書くと subtree を丸ごと作り直すのと、まったく同じ機能が Vue にもあります。「別のエンティティを表示している」ことを宣言する公式プリミティブ、という位置付けも同一です。

index を key に使うなという教訓もそのまま適用されます。スタイルガイドも一貫:

> Always use `key` with `v-for`. `key` with `v-for` is always required on components, in order to maintain internal component state down the subtree.
> ([vuejs.org / Style Guide (v2, 内容はv3も同じ)](https://vuejs.org/v2/style-guide/))

### 3.5 (補) "アプリ" としての完成 — Vueは Reactよりは埋まっている

Reactが Create React App を sunset して「React単体でアプリにしないでくれ、フレームワークを使ってくれ」と明示したのに対し、Vue は Progressive Framework として**スクリプトタグで貼る最小ケースから Nuxt による SSR/SSG まで**を自分のスコープと宣言しています。

> Vue had a simple mission from its humble beginning: to be an approachable framework that anyone can quickly learn. As our user base grew, the framework also grew in scope to adapt to the increasing demands. Over time, it evolved into what we call a "Progressive Framework": a framework that can be learned and adopted incrementally, while providing continued support as the user tackles more and more demanding scenarios.
> ([blog.vuejs.org / Announcing Vue 3.0](https://blog.vuejs.org/posts/vue-3-one-piece))

- ルーティング: Vue Router(公式)
- 状態管理: Pinia(公式推奨)
- SSR/SSG/フルスタック: Nuxt(事実上の公式)

Reactの「好きなフレームワークと組み合わせてくれ」に対し、**Vueは「段階的に自分が伸びる」を選んでいる**。どちらが良いかではなく、**自前で組み合わせる自由度の代償としての統合の薄さ**(React) か、**統合された連続性の代償としての分岐の少なさ**(Vue)か、の選択です。

---

## 4. 原理から導かれる成功パターン

ここまでの4つの制約を踏まえると、公式ドキュメントに散らばっている「推奨」が全部同じ方向を向いていることが見えてきます。

1. **派生は `computed`、同期だけ `watch`/`watchEffect`**
   「Aが変わったらBを更新する」のほぼ全ては `computed` で書ける。`watch` で派生を書こうとするたびに、「これ `computed` じゃ無理か?」を先に自問する。

2. **composable は `ref` を返せ、`reactive` を返すな**
   呼び出し側の `{ a, b } = useX()` は Vue の世界ではデフォルト書法。`reactive` で返すと反応性が切れる。どうしても `reactive` を返したいなら `toRefs(state)` で包む。

3. **状態はできるだけ `ref` に寄せ、どうしても必要なときだけ `reactive`**
   `.value` は負債だが、`reactive` の「置換不能 / destructure で消失 / identity hazard」の方が事故として大きい。チームコーディング規約としては `ref` 優先がまず無難。

4. **`v-for` には `:key` を常に付ける**
   ドキュメントは「リストレンダーが子コンポーネントstateや DOM state を持つときだけ」と書いているが、現実には**最初はstateを持っていなくても後から持つ**ようになる。スタイルガイドの "always use key with v-for" に従うのが安全。

5. **3rd party オブジェクトは `markRaw` / `shallowRef` / `shallowReactive` でオプトアウト**
   巨大インスタンスや proxy化済みオブジェクトを素の `ref` / `reactive` に入れるのは、コストと identity hazard の両方を呼ぶ。観測対象にしないと決める覚悟をAPIで表現する。

6. **Template を書く前提に立つ**
   render function や JSX も使えるが、**コンパイラ最適化を捨てる代償** と釣り合うかを意識する。普段はテンプレート、動的生成ロジックが本当に必要なときだけ render function に降りる。

---

## 5. 地雷になりやすいアンチパターン

逆に、上記を裏返すと地雷が見えます。どれも表面上は動きますが、**Vueが保証してくれていた性質**を自分で壊しています。

- `watch` で props から派生 state を作り、`ref.value = ...` で同期する(二度更新 + `computed` で消える)
- composable の戻り値を `reactive({...})` で返し、呼び出し側で `{ x, y } = useX()` と分割代入する(反応性が切れる)
- 巨大な 3rd party インスタンスを `ref` / `reactive` にそのまま入れる(Proxy 変換コストと identity hazard を両方呼ぶ)
- `v-for` の `:key` に index や `Math.random()` を使う(並び替えで子コンポーネント state と DOM state が壊れる)
- Vue が管理している DOM を jQuery 等で直接操作し、Vue の描画後に齟齬を起こす(Reactと同じ)
- Options API と Composition API を同一コンポーネントで混在させ、`this` 依存のコードを setup 側に引きずり込む
- `reactive` を「置き換え」で更新したくなるたびに新しい `reactive` を作る(参照が切れるので反応性連結が失われる)

これらが「なぜダメか」を**機能単位**ではなく**Vueの原理単位**で説明できるのが、この記事の目指した地点です。

---

## 6. Vueが向くユースケース、向かないユースケース

原理から、向き不向きの切り分けが素直に出ます。

**Vueが勝ちやすい領域**

- 既存のサーバーレンダリング主体サイトに、部分的にインタラクションを足していきたい領域
  — Progressive Framework 宣言の**そのままのターゲット**。Reactだと SSR/hydration の詰まりが早く来る
- 「手動メモ化にコストを払いたくない」中規模SPA
  — コンパイラ最適化 + 細粒度reactivity が素直に効く。`useMemo` をレビューで指摘し合う文化から抜けられる
- 公式エコシステム(Vue Router / Pinia / Nuxt)に素直に乗りたいチーム
  — 分岐点が少ない代わりに、規約も揃いやすい
- テンプレートでも十分書ける程度のUI動的性

**Vueが負けやすい/コストが過剰な領域**

- コンポーネント生成ロジックが極端に動的で、**JSの柔軟性そのもの**がUI構造に漏れるケース
  — テンプレートが窮屈で render function / JSX に降りたくなる。Reactの方が素直
- 巨大な不変データ構造を日常的に扱い、identity 依存の最適化が必要なドメイン
  — `reactive` の Proxy 変換を避けるために `markRaw` / `shallowRef` を連発する羽目になる。ReactのImmutable的書き方の方が設計と噛み合う
- 最新のサーバー境界設計(React Server Components 等)を取り込みたいケース
  — Nuxt 3 にサーバー境界はあるが、RSC とはモデルが違う。選定はエコシステム全体で考える話になる
- signals-first の超軽量ランタイムが絶対条件
  — Vue 本体もランタイムを持つ。Preact / Solid の方が筋が通る

**ここで重要なのは**、「Vueが遅い/Reactが遅い」という問いではなく、**「runtime diff を前提にするか、反応性を前提にするか」「コンパイラ最適化をどれくらい当てにするか」**という問題定義の違いである、という捉え方です。

---

## 7. まとめ

Vueは「状態変化を値自身に監視させる細粒度リアクティビティ」と「コンパイラが runtime を縮める Compiler-Informed Virtual DOM」という、**特定の問題定義への賭け**をした UI フレームワークです。

その賭けと引き換えに、利用者は4つの制約を受け入れています:

1. 反応性プリミティブの二元性 — `ref` の `.value` 税、`reactive` の置換不能/destructure消失
2. Proxy identity — `reactive(raw) !== raw`、3rd party と組むときは `markRaw` / `shallowRef` で覚悟を表明
3. `watch` / `watchEffect` は**ライフサイクルではなく外部世界との同期プリミティブ**、派生は `computed`
4. リストの identity は `v-for` + `:key` に固定される(Reactと同じ制約)

この4つを腹に収めておくと、

- 日々書いているパターン(`toRefs`で分解安全に、`computed`で派生、`markRaw`で逃がす、…)が**全部同じ原理の帰結**として見える
- 迷ったときに「Vueはこの問題をどう定義したか?」に戻って判断できる
- React / Svelte / Solid / signals 系との比較も「**別の賭けをしている**」という構造で読める

Reactを対で理解しておくとさらに見通しが良くなります。Reactは「状態→ビューを純関数として書かせ、diff で整合性に戻す」、Vueは「値の変化を値自身に監視させ、コンパイラが runtime を縮める」。この二つは**どちらが正解かを問えない別の問題設定**で、日々の書き方の違いは全部そこから自然に導かれています。

## 参考資料

- [Introduction — Vue.js](https://vuejs.org/guide/introduction)
- [Reactivity Fundamentals — Vue.js](https://vuejs.org/guide/essentials/reactivity-fundamentals)
- [Reactivity in Depth — Vue.js](https://vuejs.org/guide/extras/reactivity-in-depth)
- [Rendering Mechanism — Vue.js](https://vuejs.org/guide/extras/rendering-mechanism)
- [Watchers — Vue.js](https://vuejs.org/guide/essentials/watchers)
- [List Rendering — Vue.js](https://vuejs.org/guide/essentials/list)
- [Composables — Vue.js](https://vuejs.org/guide/reusability/composables)
- [Reactivity API: Core — Vue.js](https://vuejs.org/api/reactivity-core)
- [Reactivity API: Advanced — Vue.js](https://vuejs.org/api/reactivity-advanced)
- [Reactivity API: Utilities — Vue.js](https://vuejs.org/api/reactivity-utilities)
- [Built-in Special Attributes — Vue.js](https://vuejs.org/api/built-in-special-attributes)
- [Glossary — Vue.js](https://vuejs.org/glossary/)
- [Announcing Vue 3.0 "One Piece" — The Vue Point](https://blog.vuejs.org/posts/vue-3-one-piece)
- [Reactivity Transform — Vue.js](https://vuejs.org/guide/extras/reactivity-transform.html)
- [key Attribute — Vue 3 Migration Guide](https://v3-migration.vuejs.org/breaking-changes/key-attribute)
