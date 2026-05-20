---
title: "Solidを「消えるコンポーネント・残るリアクティビティ」として捉え直す — 解く問題・持ち込む問題・付き合い方"
emoji: "🟦"
type: "tech"
topics: ["solidjs", "frontend", "javascript", "architecture"]
published: false
---

## この記事について

Solid を触ったことがあると、「なんか React っぽいけど、destructure できないやつ」「コンポーネントが一度しか走らないやつ」くらいの粗い印象に落ち着きがちです。
それでも、同僚や後輩に「なぜ Solid なのか」「Solid は何を解いて、何を代償にしているのか」と聞かれて、**30秒で自分の言葉で答えられるか**と言われると、意外と詰まります。

姉妹記事で Reactを「UIランタイム」、Vueを「コンパイラ付きリアクティブランタイム」として捉え直しました。この記事では同じ視点で Solid を見直します。文法は一切説明しません。**フレームワーク全体の性質**として、

1. ネイティブJSが詰んだ問題に対して、Solid は React/Vue と何を共有し、何を別に賭けたのか
2. Solid が自分の制約として引き受けた代償は何か
3. その性質から自然に導かれる「勝ち筋」と「地雷」は何か
4. どのユースケースで Solid が有利/不利になるのか

を、公式 Docs と Ryan Carniato(Solid 作者)の発信を根拠に整理します。日常で Solid を書いている人が、**原理のレベルで判断できる軸**を手に入れることがゴールです。

コード例は、原理を示すのに必要な最小限だけ添えます。関連しない部分は `...` で省略します。

---

## 1. 出発点は React / Vue と同じ — 「状態空間の爆発」

まず出発点を揃えます。命令的に書かれていたUIコードは、ざっくり次のループでした。

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

小さなフォームなら回りますが、相互作用が N 個あると整合性の面が O(N²) 以上に膨らむ。これは React / Vue 版記事で書いたとおりです。

Solid の公式も同じ問題認識から入ります:

> Reactivity powers the interactivity in Solid applications. This programming paradigm refers to a system's ability to respond to changes in data or state automatically. With Solid, reactivity is the basis of its design, ensuring applications stay up-to-date with their underlying data.
> ([docs.solidjs.com / Intro to reactivity](https://docs.solidjs.com/concepts/intro-to-reactivity))

つまり、**「状態 → ビュー」の写像を宣言的に書き、DOM 同期はフレームワークに任せる**。この方向までは React / Vue とまったく同じです。

違うのはここから先。

- React は「状態 → ビューを**純関数**として書かせ、**ツリー全体を diff で整合性に戻す**」
- Vue は「**値の変化を値自身に監視させる**(reactive proxy)+ **コンパイラが runtime を縮める** (Compiler-Informed VDOM)」
- **Solid は「コンポーネントは一度だけ実行し、反応性プリミティブとDOMを直接繋げる。VDOM は持たない」**

3つは**同じ問題に対する別の賭け方**です。

---

## 2. Solid の賭け — 「消えるコンポーネント・残るリアクティビティ」

Solid を「React風の signals ライブラリ」として捉えているとかなり解像度が落ちます。より正確なモデルは Ryan Carniato 自身が書いている **"vanishing components"** です。

ここから引ける性質は3つあります。

### 2.1 コンポーネントは一度だけ実行される

これが Solid の最大の分岐点です。Ryan は "5 Ways SolidJS Differs" でこう書いています:

> Components do not re-run, just the primitives and JSX expressions you use. This means no stale closures or Hook Rules for those of you coming from React. ... Solid has truly granular updates, unlike React, Vue, or Svelte. This means that components actually more or less disappear after the fact.
> ([dev.to / 5 Ways SolidJS Differs from Other JS Frameworks](https://dev.to/ryansolid/5-ways-solidjs-differs-from-other-js-frameworks-1g63))

公式ドキュメントも明示しています:

> Components, much like other functions, will only run once. This means that if a signal is accessed outside of the return statement, it will run on initialization, but any updates to the signal will not trigger an update.
> ([docs.solidjs.com / Intro to reactivity](https://docs.solidjs.com/concepts/intro-to-reactivity))

つまりコンポーネント関数は**セットアップ**です。1回走って、JSX から生成されたDOMとリアクティブプリミティブを構築し、自分は消える。残ったプリミティブが signal の変化に反応してDOMを直接更新する、というモデルです。

React 由来の「stale closure」「Hook Rules」「依存配列の整合性」という一連の負債は、この設計では**そもそも発生しない**。代わりに、「コンポーネント本体で値を変数に捕まえると、それは初回コピーで凍結される」という別の税を払うことになります。

### 2.2 リアクティビティは「値」単位で、VDOM を通らない

Solid の `createSignal` はゲッター/セッターのペアを返します。ゲッターを **tracking scope**(`createEffect` / `createMemo` / JSX)の中で呼ぶと、そのスコープが signal の subscriber として登録されます。値が変わると、**そのゲッターを読んでいたエフェクトだけ**が再実行されます。

公式はこれを "fine-grained reactivity" と呼び、React との差を次のように明示しています:

> In Solid, updates are made to the targeted attribute that needs to be changed, avoiding broader and, sometimes unnecessary, updates. In contrast, React would re-execute an entire component for a change in the single attribute, which can be less efficient.
> ([docs.solidjs.com / Fine-grained reactivity](https://docs.solidjs.com/advanced-concepts/fine-grained-reactivity))

重要なのは、**Solid には VDOM がない**ということです。Reactのように「新旧ツリーを diff する」層は存在しません。コンパイラが JSX を「どのノードのどの属性をどの signal に繋げるか」という具体的なDOM更新コードに落とす。

Vue が Compiler-Informed VDOM で「コンパイラが runtime の仕事を縮める」という中間解を取ったのに対し、Solid は「**そもそもVDOMを挟まない**」側に寄せた賭けです。

### 2.3 コンパイラが props をレイジー評価する

もう一つ重要な性質がこれです。Ryan はこう書いています:

> How do we achieve this? Simply lazy evaluating all dynamic props.
> ([dev.to / 5 Ways SolidJS Differs from Other JS Frameworks](https://dev.to/ryansolid/5-ways-solidjs-differs-from-other-js-frameworks-1g63))

Solid のコンパイラは、JSX の動的 props を **getter 付きオブジェクト**に変換します:

```js
// あなたが書くもの
<B value={a()} onClick={handler} />

// コンパイラが生成するもの(概念)
createComponent(B, {
  get value() { return a(); },
  get onClick() { return handler; },
});
```

こうしておくと、`a()` の実行は**値が最終的に消費される場所**(JSX式 or effect内)まで遅延されます。結果として、コンポーネント境界を越えても reactivity がつながったままになる。Ryan の言葉で言えば:

> What looks like some simple binding is actually producing reactive streams through your view code, enacting updates cross-component with pinpoint accuracy.

この設計には**強い副作用**があります。props を destructure するとその瞬間にレイジー評価の対象から外れ、反応性が切れる。これが次の 3.2 で整理する"Solid が新しく持ち込んだ問題"の一つです。

---

## 3. Solid が「新しく持ち込んだ」4つの問題

Reactの賭けが利用者に4つの義務(over-reactivity、Effect は同期プリミティブ、state identity はツリー位置、単体ランタイムの限界)を押しつけたように、Solid の賭けも代償を伴います。

### 3.1 Reactive scope — tracking scope の境界が反応性の全てを決める

Solid で「このコードは反応する / しない」は、**tracking scope の中にいるかどうか**だけで決まります。tracking scope を作るのは `createEffect` / `createMemo` / JSX のみです。

> A tracking scope can be created by `createEffect` or `createMemo`, which are other Solid primitives. Both functions subscribe to the signals accessed within them, establishing a dependency relationship.
> ([docs.solidjs.com / Signals](https://docs.solidjs.com/concepts/signals))

重要なのは、**コンポーネント関数本体は tracking scope ではない**ということ。だから、本体で signal を読むと「初回のスナップショット」になります。

Reactから来た人が一度は書く間違いはこれです:

```jsx
function Counter() {
  const [count, setCount] = createSignal(0);

  // ❌ 一度しか評価されない。以後 count が増えても再評価されない
  if (count() > 5) return <div>Big</div>;

  // ✅ JSX 内なので tracking scope 内、count の変化で再評価される
  return <div>{count()}</div>;
}
```

見た目は Reactと同じですが、挙動が根本的に違います。Reactは関数コンポーネントを毎回呼び直すので `if` は毎回評価される。Solid は1回しか呼ばないので `if` は1回しか評価されない。

解決手段は公式の制御フロー要素を使うこと:

```jsx
function Counter() {
  const [count, setCount] = createSignal(0);
  return (
    <Show when={count() > 5} fallback={<div>{count()}</div>}>
      <div>Big</div>
    </Show>
  );
}
```

`<Show>` は `when` を tracking scope で評価するので、`count()` の変化に追従します。

`onMount` も同じ流儀で定義されています。ドキュメントによれば、`onMount(fn)` は実質的に `createEffect(() => untrack(fn))` と等価:

> Non-tracking function executed once on mount.
> ([docs.solidjs.com / onMount](https://docs.solidjs.com/reference/lifecycle/on-mount))

つまり「初回マウント時に1回だけ走らせる、かつ中身は tracking しない」。`useEffect(() => {...}, [])` に似ていますが、**依存配列で reactivity を管理する**という React モデルとはまったく別物です。

**Reactとの対比**: React は参照同一性(`Object.is`)が抽象から漏れる。Solid は reactive scope が抽象から漏れる。どちらも runtime の制約がユーザーに降りてきている姿で、**どちらの漏れと付き合うかを選ぶ**ことになります。

### 3.2 Props の反応性は「props オブジェクトへのアクセス」でしか保たれない

これは Solid 固有の、そして最も事故の多い制約です。公式はここを明確に禁止しています:

> Unlike in some other frameworks, you cannot use object destructuring on the `props` of a component.
> ([www.solidjs.com / Guides: Rendering](https://www.solidjs.com/guides/rendering))

> With Solid, destructuring props is not recommended as it can break reactivity. Instead, you should access props directly from the `props` object, or wrap them in a function to ensure they are always up-to-date.
> ([docs.solidjs.com / Props](https://docs.solidjs.com/concepts/components/props))

次のコードは Reactなら何も考えずに書きますが、Solid では**反応性が死にます**:

```jsx
// ❌ destructure した瞬間にレイジー評価から外れ、反応性が切れる
const MyComponent = ({ name }) => <div>{name}</div>;

// ✅ props 経由でアクセスすれば getter が発火し、反応性が保たれる
const MyComponent = (props) => <div>{props.name}</div>;
```

公式チュートリアルの言葉はもっと強いです:

> Props objects are readonly and have reactive properties which are wrapped in Object getters. ... In general accessing properties on the props object outside of Solid's primitives or JSX can lose reactivity. This applies not just to destructuring, but also to spreads and functions like `Object.assign`.
> ([www.solidjs.com / Tutorial: Props Defaults](https://www.solidjs.com/tutorial/props_defaults))

つまり spread も、Object.assign も、任意の非 tracking 関数に props を渡すのも、すべて同じ理由で壊れます。

これを埋めるために Solid は `mergeProps` と `splitProps` を公式に提供しています:

- `mergeProps`: 複数の(潜在的に reactive な)オブジェクトをマージしつつ反応性を保つ。default props の設定に使う
- `splitProps`: キーのグループで props を分割しつつ、各グループ側の反応性を維持する

> `splitProps` separates props into groups without destructuring them into non-reactive locals.
> ([docs.solidjs.com / splitProps](https://docs.solidjs.com/reference/reactive-utilities/split-props))

立ち位置としては、Vueの `toRefs` / `toRef` と近い「抽象の漏れを塞ぐための公式補助」です。

**問題の厄介さ**: TypeScript から見ると `props` は普通のオブジェクトに見えます。だから `ESLint`/`tsc` はこの違反を型エラーとして検出してくれない。チームとしてこの規約を教育・lintルール化する必要があります。公式の eslint-plugin-solid はまさにこのためにあります。

### 3.3 `createEffect` は「ライフサイクル」ではなく「外部世界との同期プリミティブ」

ここは React / Vue 記事と**ほぼ同じ構造**の話で、原理は横並びです。公式の立場:

> Effects are primarily intended for handling side effects that do not write to the reactive system. It's best to avoid setting signals within effects, as this can lead to additional rendering or even infinite loops if not managed carefully. Instead, it is recommended to use createMemo to compute new values that rely on other reactive values.
> ([docs.solidjs.com / Effects](https://docs.solidjs.com/concepts/effects))

つまり、

- **派生値**(Aが変わったらBも変わる、のB)は `createMemo` で宣言する
- **外部世界への反映**(DOM、localStorage、3rd party ライブラリ、API 呼び出し)は `createEffect`
- **初回1回だけ、かつ tracking なし**で走らせたいものは `onMount`

Reactで「useEffect + setState で派生を作るな」、Vue で「watch で派生を作るな、computed を使え」と言われるのと全く同じ構造です。どれも**宣言的に派生するか、手続きで同期するか**をユーザーに分別させます。

細かい差分として、Solid は**依存配列を持ちません**。tracking scope 内で実際に読まれた signal が自動的に依存になります。Vue の `watchEffect` に近い挙動で、React の依存配列 lint はありません。代わりに「値を変数に捕まえると追跡されない」というスコープ側の制約で全体のバランスを取っています。

Ryan はこの設計方針を強く主張しています。Signal は view の外に持ち出すものではなく、view の宣言ツリーの中にとどめる:

> There is a reason why Solid doesn't have `isSignal` or Svelte Runes don't allow you to assign a Signal to a variable. We don't want you to worry about the data graph outside of your view.
> ([dev.to / Thinking Locally with Signals](https://dev.to/playfulprogramming/thinking-locally-with-signals-3b7h))

`isSignal` を**わざと用意しない**ことで、「コンポーネントに渡された値が signal かどうかで分岐する」というパターンを最初から禁じ手にしている、という話です。抽象をユーザーに漏らさないための設計判断。

### 3.4 リスト identity — `<For>`(値)と `<Index>`(位置)の明示的二択

Reactの `key` は subtree identity の宣言、Vue の `:key` は in-place patch を上書きする宣言。Solid ではこの選択が**コンポーネント名として分離**されています。

**`<For>`**: 値 identity で追跡

> `<For>` maps items by value identity. If the same item value appears at a new position, its rendered node can be moved instead of recreated.
> ([docs.solidjs.com / `<For>`](https://docs.solidjs.com/reference/components/for))

同じオブジェクトが配列の別の位置に動いたら、DOMノードは**再利用されて移動**される。子コンポーネントの state や入力中のフォームもそのまま保持される。Reactで `key={item.id}` とやっているのと同等の挙動。

**`<Index>`**: 位置で追跡

> `<Index>` renders a list by index. ... Items are mapped by index rather than by value identity. ... Reordering the source array changes which item each index points to instead of moving mapped entries by identity.
> ([docs.solidjs.com / `<Index>`](https://docs.solidjs.com/reference/components/index-component), [indexArray](https://docs.solidjs.com/reference/reactive-utilities/index-array))

同じ index の位置に別の値が入ったら、その行の signal が更新される。DOMノードは動かない。固定位置のフォームや、配列の順序が意味を持たないケースに向く。

**何が嬉しいのか**: Reactだと `key={index}` は「だいたいダメ、でも場合によっては正解」というぼんやりした落とし穴でした。Solid は**どちらの戦略を取っているか**がコンポーネント名で表明されます。選択ミスは型では防げませんが、レビューで見える。

Store 側では同じ思想の `reconcile` があります:

> `reconcile` creates a store modifier that reconciles existing state with a new value. ... Key used to match items during reconciliation.
> ([docs.solidjs.com / reconcile](https://docs.solidjs.com/reference/store-utilities/reconcile))

新旧データから差分を検出し、必要な部分だけ更新する。これも「identity をどう宣言するか」を API で明示させる側の設計です。

---

## 4. (補)Solid が「アプリ」になるまで — SolidStart の位置

Reactが Create React App を sunset して「フレームワークを使え」と明示した対比として、Solid はこの領域で**first-party な答え**を持っています。

> SolidStart is a first-party project starter/framework for SolidJS that punches above its weight and provides a first-class way to deploy your Solid apps.
> ([solidjs.com / Introducing SolidStart](https://www.solidjs.com/blog/introducing-solidstart))

SolidStart は Vite + Nitro + Solid Router の統合で、SSR / SSG / CSR / Streaming / Server Functions / Islands(experimental)をカバーします:

> Client Render Mode, Server Side Rendering, Static Site Generation, Out-of-Order-Streaming, Optimistic UI, Key Based Cache/Invalidation, Progressively Enhanced Forms, API Routes, Parallelized Nested Route Data Fetching, Single Flight Mutation, Islands(experimental), Suspense, Transitions.
> ([solidjs.com / SolidStart 1.0](https://www.solidjs.com/blog/solid-start-the-shape-frameworks-to-come))

特に注目すべきは Server Functions (`"use server"`)を2022年から先行導入している点。React Server Components と別系統ですが、**「サーバー側で走る関数をクライアントから RPC で呼べる」**という同世代の抽象です。

ただし、エコシステムの厚みは Reactや Vue には及びません。React Native 相当、Nuxt のモジュール生態系、Next.js の豊富な統合ライブラリ、そういうものは一桁以上少ない。**Solid を選ぶのは「ランタイムの性質を取りに行く」判断**であり、エコシステム全体で判断する話になります。

---

## 5. 原理から導かれる成功パターン

ここまでの4つの制約を踏まえると、公式ドキュメントに散らばっている「推奨」が全部同じ方向を向いていることが見えてきます。

1. **派生は `createMemo` / 派生 signal、同期だけ `createEffect`**
   「Aが変わったらBを更新する」のほぼ全ては `createMemo` で書ける。`createEffect` の中で `setSignal` する前に、「これ `createMemo` では無理か?」を先に自問する。

2. **`props.x` を直接使え、destructure するな**
   `const { x } = props` は反応性破壊。spread、`Object.assign`、非 tracking 関数への props 受け渡しも同じ。default 値は `mergeProps`、分割は `splitProps`。

3. **コンポーネント本体で `if` しない、JSX側の制御フローを使う**
   コンポーネント本体は setup 関数で1回きり。条件分岐は `<Show>` / `<Switch>`、ループは `<For>` / `<Index>` に置く。そうすれば tracking scope が JSX 側で立つ。

4. **`<For>` と `<Index>` を意図的に選ぶ**
   「要素 identity が意味を持つか」で決める。state を持つ子・DOM 持続が必要なら `<For>`、固定位置の表示更新なら `<Index>`。どちらでもいい場面は実際は少ない。

5. **Store と Signal の使い分けは「粒度」で決める**
   複数プロパティの関係を持つデータなら `createStore`、独立した値なら `createSignal`。store は property アクセスごとに signal が立つので、巨大なオブジェクトを全部入れても**実際にUIから読まれた部分だけ**が tracking されます。

   > When a store is created, it starts with the initial state but does not immediately set up signals to track changes. These signals are created lazily, meaning they are only formed when accessed within a tracking scope.
   > ([docs.solidjs.com / Stores](https://docs.solidjs.com/concepts/stores))

6. **`onMount` / `onCleanup` は「スコープライフサイクル」として捉える**
   `onMount` は初回だけ untrack で走る。`onCleanup` は**所有スコープ**が破棄されるときに走る。コンポーネント unmount と必ずしも 1:1 ではなく、`createRoot` / `createEffect` 内部からも呼べる。スコープの単位で考えるのが原理的に正しい。

---

## 6. 地雷になりやすいアンチパターン

逆に、上記を裏返すと地雷が見えます。どれも表面上は動きますが、**Solid が保証してくれていた性質**を自分で壊しています。

- `const { count } = props` / `...props` を他関数に spread する(反応性が切れる)
- コンポーネント本体で `const name = props.name` / `const c = count()` と変数に捕まえる(初回コピーで凍結)
- コンポーネント本体で `if` / 三項演算子で早期 return する(条件評価が1回で終わる。以後状態が変わっても変わらない)
- `createEffect` の中で `setSignal` して派生を同期する(`createMemo` で消える。最悪無限ループ)
- `<For>` と `<Index>` を何も考えずに選ぶ(子 state 消失 or 過剰再生成)
- signal を変数に代入して関数の外に持ち出す(Ryan 本人が「やってほしくない」と明言、`isSignal` が**存在しない**理由)
- store の生オブジェクトに対して `raw.x = 1` のように直接変更する(proxy 側を触らないと tracking が走らない)
- `createEffect` を「マウント時に1回だけ」用途で使う(依存する signal があれば再実行される。1回だけなら `onMount`)

これらが「なぜダメか」を**機能単位**ではなく**Solid の原理単位**で説明できるのが、この記事の目指した地点です。

---

## 7. Solid が向くユースケース、向かないユースケース

原理から、向き不向きの切り分けが素直に出ます。

**Solid が勝ちやすい領域**

- 手動メモ化のレビューコストに疲れた Reactチームが、**同じ JSX 系のまま**別の賭けへ移行したいケース — `useMemo` 警察から解放される
- 高頻度更新(グラフ、チャート、ダッシュボード、ビジュアライザ、ゲーム的UI)で、コンポーネント再レンダーのコストが効くケース — fine-grained な更新モデルが素直にハマる
- バンドルサイズを絞りたいケース — Solid のコアは小さい(Preact に近いレンジ)
- Signals という最近の潮流(TC39 Signals proposal、Svelte 5 runes、Vue Vapor)を正面から取りに行く設計判断をしたいチーム

**Solid が負けやすい/コスト過剰な領域**

- エコシステム優先のプロダクト — React Native 相当、大量の React製 UI ライブラリ、Next.js の豊富な統合を前提にする案件
- チームに「reactive scope / props の扱い」を教える余裕がない現場 — Reactと**見た目が似ているのが罠**になる。destructure 一発で反応性が死ぬ、という事故が頻発する
- React Server Components と同等の「サーバーファースト UI モデル」に一本化したいケース — SolidStart はサーバー機能を持つが、RSC とはモデルが別系統
- コンテンツ中心・静的性が高く、そもそもランタイム自体を捨てたいケース — Astro や Qwik (resumability) の方向が合う

重要なのは、「Solid が速い / Reactが遅い」という問いではなく、**「コンポーネントを再実行するか / 反応性プリミティブだけ残すか」「VDOM を挟むか / 挟まないか」**という**問題定義そのものの選択**である、という捉え方です。

---

## 8. まとめ

Solid は「コンポーネントは一度だけ走り、残るのは反応性プリミティブとコンパイル済みDOM更新コードだけ」という、**特定の問題定義への賭け**をした UI ランタイム+コンパイラです。

その賭けと引き換えに、利用者は4つの制約を受け入れています:

1. **tracking scope に入っているかどうか**が反応性の唯一のルール — コンポーネント本体はスコープ外
2. `props` は destructure 不可 — `splitProps` / `mergeProps` で公式に埋める
3. `createEffect` はライフサイクルではなく**外部世界との同期プリミティブ**、派生は `createMemo`
4. リスト identity は `<For>`(値)と `<Index>`(位置)の明示的二択

この4つを腹に収めておくと、

- 日々書いているパターン(destructure 禁止、`<Show>` で分岐、`createMemo` で派生、`onMount` で初期化、…)が**全部同じ原理の帰結**として見える
- 迷ったときに「Solid はこの問題をどう定義したか?」に戻って判断できる
- Reactや Vue、Svelte 5 runes、Vue Vapor、TC39 Signals との比較も「**別の賭けをしている**」という構造で読める

React / Vue と並べるとさらに見通しが良くなります。**同じ「状態空間の爆発」という問題**に対して、

- Reactは「状態→ビューを純関数として書かせ、diff で整合性に戻す」
- Vue は「値の変化を値自身に監視させ、コンパイラが runtime を縮める」
- Solid は「コンポーネントを一度しか走らせず、反応性プリミティブと DOM を直接繋げる」

という**3つの別の賭け方**がある。日々の書き方の違いは、全部ここから自然に導かれています。

## 参考資料

- [Intro to reactivity — Solid Docs](https://docs.solidjs.com/concepts/intro-to-reactivity)
- [Fine-grained reactivity — Solid Docs](https://docs.solidjs.com/advanced-concepts/fine-grained-reactivity)
- [Signals — Solid Docs](https://docs.solidjs.com/concepts/signals)
- [Effects — Solid Docs](https://docs.solidjs.com/concepts/effects)
- [Props — Solid Docs](https://docs.solidjs.com/concepts/components/props)
- [Stores — Solid Docs](https://docs.solidjs.com/concepts/stores)
- [`<For>` — Solid Docs](https://docs.solidjs.com/reference/components/for)
- [`<Index>` — Solid Docs](https://docs.solidjs.com/reference/components/index-component)
- [indexArray — Solid Docs](https://docs.solidjs.com/reference/reactive-utilities/index-array)
- [splitProps — Solid Docs](https://docs.solidjs.com/reference/reactive-utilities/split-props)
- [onMount — Solid Docs](https://docs.solidjs.com/reference/lifecycle/on-mount)
- [onCleanup — Solid Docs](https://docs.solidjs.com/reference/lifecycle/on-cleanup)
- [untrack — Solid Docs](https://docs.solidjs.com/reference/reactive-utilities/untrack)
- [reconcile — Solid Docs](https://docs.solidjs.com/reference/store-utilities/reconcile)
- [Guides: Rendering — SolidJS](https://www.solidjs.com/guides/rendering)
- [Tutorial: Props Defaults — SolidJS](https://www.solidjs.com/tutorial/props_defaults)
- [5 Ways SolidJS Differs from Other JS Frameworks — Ryan Carniato](https://dev.to/ryansolid/5-ways-solidjs-differs-from-other-js-frameworks-1g63)
- [Thinking Granular: How is SolidJS so Performant? — Ryan Carniato](https://dev.to/ryansolid/thinking-granular-how-is-solidjs-so-performant-4g37)
- [Thinking Locally with Signals — Ryan Carniato](https://dev.to/playfulprogramming/thinking-locally-with-signals-3b7h)
- [Introducing SolidStart — SolidJS Blog](https://www.solidjs.com/blog/introducing-solidstart)
- [SolidStart 1.0: The Shape of Frameworks to Come — SolidJS Blog](https://www.solidjs.com/blog/solid-start-the-shape-frameworks-to-come)
