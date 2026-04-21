---
title: "Reactを「UIランタイム」として捉え直す — 解く問題・持ち込む問題・付き合い方"
emoji: "⚛️"
type: "tech"
topics: ["react", "frontend", "javascript", "architecture"]
published: false
---

## この記事について

Reactは毎日書いている。`useState`も`useEffect`も`key`も`memo`も、いつのまにか手が勝手に書ける。
それでも、同僚や後輩に「なぜReactなのか」「Reactは何を解いて、何を代償にしているのか」と聞かれて、**30秒で自分の言葉で答えられるか**と言われると、意外と詰まる人は多いです。

この記事は、Reactの文法を一切説明しません。**フレームワーク全体の性質**として、

1. ネイティブJSが詰んだのはどこで、Reactはその問題をどう再定義したのか
2. 代わりにReactは何を自分の制約として引き受け、ユーザーに何を強いたのか
3. その性質から自然に導かれる「勝ち筋」と「地雷」は何か
4. どのユースケースでReactが有利/不利になるのか

を、Dan Abramov の "React as a UI runtime" や公式 Docs を根拠に整理します。日常でReactを書いている人が、**原理のレベルで判断できる軸**を手に入れることがゴールです。

コード例は、その原理を示すのに必要な最小限だけ添えます。関連しない部分は `...` で省略します。

---

## 1. ネイティブJSが詰んだのは「状態空間の爆発」

まず出発点を揃えます。Reactが必要になる前、命令的に書かれていたUIコードは、ざっくり次のループでした。

```js
input.addEventListener('input', (e) => {
  // 1. 入力イベントから、手元の状態を更新する
  state.query = e.target.value;
  // 2. その状態変化に応じて、DOMを手で同期させる
  if (state.query.length > 0) {
    clearButton.hidden = false;
  } else {
    clearButton.hidden = true;
  }
  // 3. 他に影響する箇所も全部、自分で洗い出して更新する
  //    submitButton, counter, ...
});
```

小さなフォームならこれで十分回ります。公式も同じことを言っています:

> Manipulating the UI imperatively works well enough for isolated examples, but it gets exponentially more difficult to manage in more complex systems.
> ([react.dev / Reacting to Input with State](https://react.dev/learn/reacting-to-input-with-state))

「指数的に難しくなる (exponentially more difficult)」と言い切っているのがポイントです。
ここで破綻しているのは単なる行数ではありません。**状態遷移の組み合わせ数**と、**DOMとの整合性を人間が維持するコスト**です。相互作用が N 個あると、「ボタンが押せるはずなのに disabled のままだ」のようなズレが発生しうる面が概ね O(N²) 以上に膨らみます。

Reactの最初の賭けは、この問題の形を書き換えたことにあります。

> In React, you don’t directly manipulate the UI ... Instead, you declare what you want to show, and React figures out how to update the UI.
> ([react.dev / Reacting to Input with State](https://react.dev/learn/reacting-to-input-with-state))

つまり、「状態 → ビュー」の**写像を一方向の純関数にする**。DOMとの同期という面倒な後半戦は、全部Reactというランタイムに押しつける。これがReactが取った基本姿勢です。

---

## 2. Reactは「DOMライブラリ」ではなく「UIランタイム」

このあたりで、Reactを「Virtual DOMのライブラリ」として捉えているとだいぶ解像度が落ちます。より正確なモデルは Dan Abramov の言う **UI runtime** です。

> React programs usually output a tree that may change over time. It might be a DOM tree, an iOS hierarchy, a tree of PDF primitives, or even of JSON objects. ... So what is React useful for? Very abstractly, it helps you write a program that predictably manipulates a complex host tree in response to external events like interactions, network responses, timers, and so on.
> ([overreacted.io / React as a UI Runtime](https://overreacted.io/react-as-a-ui-runtime/))

ここから引ける性質は3つあります。

### 2.1 宿主ツリーは交換可能

React自体は DOM に依存していません。DOM・iOS・PDF・JSON、どれでも「ツリー状の宿主」があればレンダラを差し替えて動きます。これが React Native, React Three Fiber, react-pdf, Ink(CLI)などの基盤です。
日常ではDOMしか見ませんが、**DOMでの挙動は"特定のレンダラ実装の詳細"にすぎない**、という意識を持つと、パフォーマンス議論の筋が通しやすくなります。

### 2.2 Reactは外部イベントに反応する「調整役」

Reactは coordinator として振る舞います。これは「疎結合な小さなモジュールの集合」として実装できない、とReactチーム自身が明言しています:

> React can’t be split into small simple loosely coupled modules because in order to do its job, something has to act as the coordinator. That’s what React is.
> ([overreacted.io / What Are the React Team Principles?](https://overreacted.io/what-are-the-react-team-principles/))

「複雑性はReact側が吸収する (Absorb the Complexity)」という原則もここと一対です。つまり、**Reactの中央集権性は副作用ではなく本質**です。軽量で疎結合なライブラリが欲しいならそもそも別の設計(例: signal 系)を選ぶことになります。

### 2.3 UIは「状態から辿れる」ことが保証される

設計原則ドキュメントにある明示的な表現:

> It is an explicit design goal that state is not “trapped” in closures and combinators, and is available to React directly. ... synchronous render() functions of props and state turn debugging from guesswork into a boring but finite procedure.
> ([legacy.reactjs.org / Design Principles](https://legacy.reactjs.org/docs/design-principles.html))

状態を closure に閉じ込めさせず、Reactが把握できる形で持たせる。render は `props + state` の同期純関数にする。引き換えに得られるのが **「どの画面も、その時点のprops/stateから必ず再現できる」** という保証です。
DevToolsでコンポーネントツリーを辿ってバグ原因の state にたどり着く、というあの体験は、この設計制約の直接の帰結です。

---

## 3. Reactが「新しく持ち込んだ」4つの問題

ここからが本題です。宿主ツリーを「状態の純関数」として扱うという賭けは、**利用者側に新しい義務**を押しつけています。フレームワークとしてのReactを理解するには、この代償を4つに分けて言語化しておくのが役に立ちます。

### 3.1 Over-reactivity — 参照同一性が抽象から漏れる

宿主ツリーの差分更新のためには、Reactは「前回と今回で何が変わったか」を判定する必要があります。ところがJSには、2つのオブジェクトの意味的等価性を安価に判定する手段がありません。Reactが使える唯一現実的な武器は **`Object.is` による浅い比較**です。

結果として、意味的に同じデータでも、参照が変われば「変わった」扱いになります。

```jsx
function Page() {
  const user = { name: 'Taylor', age: 42 };  // 毎レンダーで新しいオブジェクト
  return <Profile user={user} />;
}
```

`Profile` が `memo` されていても、`user` は毎回新しい参照なので再レンダーは止まりません。`useMemo` / `useCallback` が必要になるのはこのためです。

React公式はこの性質を率直に弱点として認めています:

> The catch is that React can sometimes be too reactive: it can re-render too much. For example, in JavaScript we don’t have cheap ways to compare if two objects or arrays are equivalent ... so creating a new object or array on each render may cause React to do more work than it strictly needs to. This means developers have to explicitly memoize components so as to not over-react to changes.
> ([react.dev / React Labs — March 2023](https://react.dev/blog/2023/03/22/react-labs-what-we-have-been-working-on-march-2023))

そして `memo` は保証ではなく最適化にすぎない、と明記されています:

> This memoized version of your component will usually not be re-rendered when its parent component is re-rendered as long as its props have not changed. But React may still re-render it: memoization is a performance optimization, not a guarantee.
> ([react.dev / memo](https://react.dev/reference/react/memo))

**実務的な含意**:props の "形" は Reactの等価性モデルを前提に設計されるべきものです。巨大オブジェクトやインラインで作られた配列/関数を雑にバラ撒くと、memoization は簡単に死にます。React Compiler がこれを自動化しようとしているのは、この問題を"言語として"解きにいく試みです。

### 3.2 Effectは「ライフサイクル」ではなく「同期プリミティブ」

ここは、既に書ける人でも原理に戻すと詰まる場所です。Reactの公式立場は一貫していて、**Effect は外部システムとの同期のためにある**、と位置づけています。

> You do need Effects to synchronize with external systems. ... If you can calculate something during render, you don’t need an Effect.
> ([react.dev / You Might Not Need an Effect](https://react.dev/learn/you-might-not-need-an-effect))

つまり、

- propsから派生データを作るため
- 入力に対してビジネスロジックを回すため
- 初期化を「1回だけ」やるため

のどれも、Effectの本来の用途ではありません。Reactが「UIは状態の純関数」というモデルを採っている以上、**renderで計算できるものはrenderで計算する**のが正解です。

Effect内で `setState` するのは、多くの場合ただの二度レンダーです:

> Setting state immediately inside an effect forces React to restart the entire render cycle. ... This creates an extra render pass that could have been avoided by transforming data directly during render or deriving state from props.
> ([react.dev / set-state-in-effect](https://react.dev/reference/eslint-plugin-react-hooks/lints/set-state-in-effect))

さらに、`useMount` や `useEffectOnce` のような「lifecycle 風カスタムフック」を作るのもReactのパラダイムに合わない、と公式は明言しています:

> Avoid creating and using custom “lifecycle” Hooks that act as alternatives and convenience wrappers for the useEffect API itself ...
> For example, this useMount Hook ... doesn’t “react” to roomId or serverUrl changes, but the linter won’t warn you about it because the linter only checks direct useEffect calls.
> ([react.dev / Reusing Logic with Custom Hooks](https://react.dev/learn/reusing-logic-with-custom-hooks))

ポイントは、依存配列の検査は useEffect の**直接の呼び出し**でしか効かないこと。`useMount` でラップされた瞬間、「reactivity」という Reactの中核メカニズムが見えなくなる、だから禁じ手扱いなのです。これは単なる好みではなく、**Reactの整合性モデルに直接響く**話です。

### 3.3 状態の identity は「ツリー位置」に固定される

Reactのstateは、JSXのタグに紐づいているのではありません。**ツリー上の位置(index + optional key)** に紐づいています。

> React preserves a component’s state for as long as it’s being rendered at its position in the UI tree. If it gets removed, or a different component gets rendered at the same position, React discards its state. ... State is not kept in JSX tags. It’s associated with the tree position in which you put that JSX.
> ([react.dev / Preserving and Resetting State](https://react.dev/learn/preserving-and-resetting-state))

これが意識に上がってないと、次のようなコードが直感に反して見えます。

```jsx
{showA ? <Counter /> : <Counter />}
```

「コンポーネントが切り替わっているのだから、stateはリセットされるだろう」と思うかもしれませんが、**同じ位置に同じ型**が置かれているので、Reactから見るとこれは同一のインスタンスで、stateは保持されます。
逆に、「別のエンティティを表示している」ことを表現したければ、`key` を変える必要があります。

```jsx
<Profile key={userId} />
```

これでReactはsubtreeを別物と認識し、**丸ごと作り直します**。公式ドキュメントはこれを propsからのstateリセットの**推奨手段**として位置づけています。`getDerivedStateFromProps` のような気持ちの悪い同期は、実はこの `key` 操作でだいたい消せます。

この性質は、reconciliation のアルゴリズム的制約から来ています。

> There are some generic solutions to this algorithmic problem of generating the minimum number of operations to transform one tree into another. However, the state of the art algorithms have a complexity in the order of O(n³) ...
> ([legacy.reactjs.org / Reconciliation](https://legacy.reactjs.org/docs/reconciliation.html))

真面目に木差分を解くと O(n³) なので、Reactは「型が同じなら同じ、違えば破棄・再生成」「リストはkeyで追跡」というヒューリスティックを置いて O(n) に抑えています。そのために、**利用者がkeyを安定・予測可能・一意に保つ義務**を負います。`Math.random()` や機械的なindexをkeyに使うと、並び替えや挿入でstateとDOMインスタンスが壊されます:

> Unstable keys (like those produced by Math.random()) will cause many component instances and DOM nodes to be unnecessarily recreated, which can cause performance degradation and lost state in child components.
> ([legacy.reactjs.org / Reconciliation](https://legacy.reactjs.org/docs/reconciliation.html))

`key` を「Reactを黙らせる warning 回避手段」だと思っている人が一定数いますが、実態はほぼ逆で、**key は subtree の identity をユーザーが宣言する唯一の公式プリミティブ**です。

### 3.4 React単体では「アプリ」にならない

最後に、2025年2月に公式が発表した Create React App の sunset は、このフレームワークの**本質的なスコープ**を示しています。

> Create React App does not include a specific code splitting solution. ... Create React App does not include a specific data fetching solution. ...
> ([react.dev / Sunsetting Create React App](https://react.dev/blog/2025/02/14/sunsetting-create-react-app))

ルーティング、データ取得、コード分割、レンダリング戦略(SSR/SSG/RSC)の選択は、React単体では解けません。そして「自分で足していくと事実上フレームワークを自作することになる」と公式ドキュメントは率直に書いています:

> Starting from scratch is an easy way to get started using React, but a major tradeoff to be aware of is that going this route is often the same as building your own adhoc framework.
> ([react.dev / Build a React app from Scratch](https://react.dev/learn/build-a-react-app-from-scratch))

つまりReactは、UIツリーの差分更新と状態管理という**狭く深い問題**に特化したランタイムであって、アプリケーションの残り半分(データ流・配送・遷移)は意図的にスコープ外です。Next.js や React Router を選ぶのは、このスコープ外を誰に任せるかの判断です。

---

## 4. 原理から導かれる成功パターン

ここまでの4つの制約を踏まえると、公式ドキュメントに散らばっている「推奨」が全部同じ方向を向いていることが見えてきます。全部、**Reactの問題定義に沿って書く**ためのパターンです。

1. **"source of truth" は1箇所にし、残りは render で派生する**
   選択中のアイテムを state に持たずに、`selectedId` だけ持って render で `items.find` する。Effect + setState での派生同期はほぼ全部これで消える。

2. **状態の identity は `key` で明示的に切る**
   「別のものを映している」を表現したいときは、getDerivedStateFromProps ではなく `key` を変える。これがReactネイティブな identity 宣言手段。

3. **render は純関数として守る**
   副作用は event handler か Effect に寄せる。render 中にグローバル可変状態を書き換えない。Strict Modeの二重呼び出しは、これを機械的に検出するためにある。

4. **Effect は外部世界との同期専用**
   外部サブスクリプション、サードパーティウィジェット、ブラウザAPIとの接続だけ。**「Xになったら Yの state を更新する」の9割はEffectではなくrender or event handler**。

5. **参照同一性を設計の一部として扱う**
   propsに毎レンダー新規オブジェクトを生やさない。依存配列にオブジェクト/関数を入れない。分解してプリミティブに直す、またはオブジェクトはEffectの中で作る:
   > Whenever possible, you should try to avoid objects and functions as your Effect’s dependencies. Instead, try moving them outside the component, inside the Effect, or extracting primitive values out of them.
   > ([react.dev / Removing Effect Dependencies](https://react.dev/learn/removing-effect-dependencies))

6. **状態は必要十分な"高さ"に置く**
   共有が必要な最小の祖先まで持ち上げて、それ以上は持ち上げない。フォームの一時状態やホバー状態をグローバルストアに乗せない。これはReactチーム自身が useMemo のドキュメントで書いている原則です(`react.dev/reference/react/useMemo` の "Prefer local state and don't lift state up any further than necessary")。

---

## 5. 地雷になりやすいアンチパターン

逆に、上記を裏返すと地雷が見えます。どれも表面上は動くが、**Reactが保証してくれていた性質**を自分で壊しています。

- Effectで props から state を派生し、`setState` で同期する(二度レンダー + バグ源)
- 「初回マウントだけ」用の `useMount` / `useEffectOnce` を自作する(reactivity の lint検査が効かなくなる)
- render の最中にグローバル可変変数やrefを書き換える(renderの純粋性と time-slicing を壊す)
- key に `Math.random()` や配列 index を機械的に使う(並び替え・挿入でstateとDOMが壊れる)
- `memo` を「とりあえず貼る」(props が毎回新規オブジェクトなら効かない。むしろ比較コストだけ残る)
- 巨大な object を context で流し、全 consumer を連鎖再レンダーさせる
- Reactが管理する DOM を、Reactの外から直接いじって world view とズラす(reconciliation後のDOM復元で必ずどこかで壊れる)

これらが「なぜダメか」を**機能単位**ではなく**Reactの原理単位**で説明できるのが、この記事の目指した地点です。

---

## 6. Reactが向くユースケース、向かないユースケース

原理から、向き不向きの切り分けも素直に出ます。

**Reactが勝ちやすい領域**

- 状態が多く、派生が深く、UIが「現在の状態のスナップショット」として説明できる領域
  — 管理画面、ダッシュボード、複雑フォーム、IDE的UI、SPAアプリ
- 同じUIロジックを複数の宿主(Web + Native、あるいはPDF/Canvas/CLI)に持ち込みたい領域(レンダラ可換性が効く)
- 長期保守が前提で、**「あとから入った人が state から画面を辿れる」保証**が価値を持つプロダクト

**Reactが負けやすい/コストが過剰な領域**

- コンテンツ中心で、状態遷移がほぼ静的なページ
  — hydration と参照同一性の注意コストに対してリターンが薄い。Astro 的なアプローチやサーバー側 HTML に倒す方が筋が良い
- 1フレーム精度のアニメーション・物理シミュレーション
  — renderサイクルを避けて DOM/Canvas を直接触るほうが、Reactの抽象と殴り合わずに済む(Reactの外に逃げるための `useSyncExternalStore` や ref の使い方はある)
- 極端に制約された配信環境で、ランタイム本体のサイズが予算に収まらないケース
  — Preact や signal 系、あるいは islands アーキテクチャのほうが合う

ここで重要なのは、「Reactが遅い/重い」ではなく、**Reactが解こうとしている問題と、そのユースケースが解いてほしい問題が違う**、という話だ、という捉え方です。

---

## 7. まとめ

Reactは「UIの複雑性を、状態 → ビューの純関数というモデルで飼い慣らす」という、**特定の問題定義への賭け**をしたUIランタイムです。

その賭けと引き換えに、利用者は4つの制約を受け入れています:

1. 参照同一性がReactの等価性モデルに漏れる(over-reactivity)
2. Effectはライフサイクルでなく、外部世界との同期プリミティブ
3. stateの identity はツリー位置(key)に固定される
4. アプリケーションとしての完成は、React単体では意図的にスコープ外

この4つを腹に収めておくと、

- 日々書いているパターン(`key`でリセット、`useMemo`で参照安定化、render中の派生計算、…)が**全部同じ原理の帰結**として見える
- 迷ったときに「Reactはこの問題をどう定義したか?」に戻って判断できる
- Svelte や Solid、signal 系、islands との比較も「別の賭けをしている」という構造として読める

この視点だけでも、同僚に "なぜReactなの?" と聞かれたときの答えは、だいぶ変わっているはずです。

## 参考資料

- [React as a UI Runtime — Dan Abramov](https://overreacted.io/react-as-a-ui-runtime/)
- [What Are the React Team Principles? — Dan Abramov](https://overreacted.io/what-are-the-react-team-principles/)
- [Design Principles — React (legacy docs)](https://legacy.reactjs.org/docs/design-principles.html)
- [Reconciliation — React (legacy docs)](https://legacy.reactjs.org/docs/reconciliation.html)
- [Reacting to Input with State — React](https://react.dev/learn/reacting-to-input-with-state)
- [You Might Not Need an Effect — React](https://react.dev/learn/you-might-not-need-an-effect)
- [Preserving and Resetting State — React](https://react.dev/learn/preserving-and-resetting-state)
- [Reusing Logic with Custom Hooks — React](https://react.dev/learn/reusing-logic-with-custom-hooks)
- [Removing Effect Dependencies — React](https://react.dev/learn/removing-effect-dependencies)
- [memo — React Reference](https://react.dev/reference/react/memo)
- [set-state-in-effect rule — React](https://react.dev/reference/eslint-plugin-react-hooks/lints/set-state-in-effect)
- [React Labs: What We've Been Working On (March 2023)](https://react.dev/blog/2023/03/22/react-labs-what-we-have-been-working-on-march-2023)
- [Sunsetting Create React App](https://react.dev/blog/2025/02/14/sunsetting-create-react-app)
- [Build a React app from Scratch](https://react.dev/learn/build-a-react-app-from-scratch)
