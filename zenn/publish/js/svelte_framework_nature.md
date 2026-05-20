---
title: "Svelteを「コンパイラ × ランタイム反応性」として捉え直す — 解く問題・持ち込む問題・付き合い方"
emoji: "🔥"
type: "tech"
topics: ["svelte", "frontend", "javascript", "architecture"]
published: false
---

## この記事について

Svelteは毎日書いている。`$state`も`$derived`も`$effect`も、Svelte 5へ移行してからはいつのまにか手が勝手に書ける。
それでも、同僚や後輩に「なぜSvelteなのか」「Svelteは何を解いて、何を代償にしているのか」と聞かれて、**30秒で自分の言葉で答えられるか**と言われると、意外と詰まる人は多いです。

この記事は、Svelteの文法を一切「使い方」としては説明しません。**フレームワーク全体の性質**として、

1. ネイティブJSが詰んだのはどこで、SvelteはReact/Vue/Solidと何を共有し、何を別に賭けたのか
2. 代わりにSvelteは何を自分の制約として引き受け、ユーザーに何を強いたのか
3. その性質から自然に導かれる「勝ち筋」と「地雷」は何か
4. どのユースケースでSvelteが有利/不利になるのか

を、公式 Docs と Rich Harris の発言を根拠に整理します。日常でSvelteを書いている人が、**原理のレベルで判断できる軸**を手に入れることがゴールです。同シリーズの [React版](./react_framework_nature.md) の姉妹記事として、突き合わせて読めるように構成を揃えています。

コード例は、原理を示すのに必要な最小限だけ添えます。関連しない部分は `...` で省略します。

---

## 1. ネイティブJSが詰んだのは「状態空間の爆発」

React版と同じ出発点から入ります。Reactが必要になる前、命令的に書かれていたUIコードは、ざっくり次のループでした。

```js
input.addEventListener('input', (e) => {
  state.query = e.target.value;
  if (state.query.length > 0) {
    clearButton.hidden = false;
  } else {
    clearButton.hidden = true;
  }
  // submitButton, counter, ... 影響箇所を全部手で同期する
});
```

相互作用が N 個あると「ボタンが押せるはずなのに disabled のままだ」のような整合性違反が発生しうる面が概ね O(N²) 以上に膨らみます。これが「状態空間の爆発」です。

宣言的レンダリング + 自動DOM同期で解こう、というアイデア自体は、React / Vue / Solid / Svelte が**全員共有**しています。違いはその先、**「どのレイヤーで、何を代償に解くか」** です。

- **React**: 状態→ビューを**純関数**にして、差分を Virtual DOM の diff で吸収する(UIランタイムとしての中央集権)
- **Vue**: 値の変化を値自身に監視させる(reactive proxy)+ compiler-informed VDOM
- **Solid**: コンポーネントは一度だけ実行し、**signals と JSX 式を直接DOMに繋ぐ**
- **Svelte**: **フレームワーク自体をコンパイラに寄せ**、反応性を `.svelte` という専用言語の一級市民にする

Svelte公式はこれをかなり強く打ち出しています:

> ...during your build process Svelte compiles them into tiny standalone JavaScript modules. By statically analysing the component template, we can make sure that the browser does as little work as possible.
> The Svelte implementation of TodoMVC weighs 3.6kb zipped. For comparison, React plus ReactDOM _without any app code_ weighs about 45kb zipped.
> ([svelte.dev / Frameworks without the framework](https://svelte.dev/blog/frameworks-without-the-framework))

ここで言われている「フレームワークは消え、残るのはほぼ vanilla JS」という設計方針が、Svelteの賭けを象徴しています。

---

## 2. Svelteの正体は「DSL + コンパイラ + 薄いランタイム」

Svelteを「React/Vue より軽い UIライブラリ」として捉えていると、かなり解像度が落ちます。より正確なモデルは、**JavaScript の上に乗った専用言語**と、それを解釈する**コンパイラ**、そして最小限に絞られた**ランタイム**の3層です。

公式ドキュメントの冒頭、"What are runes?" の書き出しは、この構造を正面から言語化しています:

> Runes are symbols that you use in `.svelte` and `.svelte.js` / `.svelte.ts` files to control the Svelte compiler. **If you think of Svelte as a language, runes are part of the syntax — they are keywords.**
> ([svelte.dev / What are runes?](https://svelte.dev/docs/svelte/what-are-runes))

つまりSvelteチームは明示的に、「Svelte は言語(language)である」というモデルを採っています。`.svelte` ファイルと `.svelte.js` / `.svelte.ts` ファイルは、普通のJSファイルではなく、**コンパイラが特別扱いする方言**です。

そして Svelte 5 以降、反応性の実装は compile-time reactivity から **signalsベースのランタイム** に舵を切りました。ただし立ち位置は Solid と逆で、signalsは**隠されています**:

> In Svelte 5, **signals are an under-the-hood implementation detail** rather than something you interact with directly. ... when compiling in server-side rendering mode we can ditch the signals altogether, since on the server they're nothing but overhead.
> ([svelte.dev / Introducing runes](https://svelte.dev/blog/runes))

ここから引ける性質は3つあります。

### 2.1 Svelte は「言語」として設計されている

React / Vue / Solid は「汎用 JS + 特別な使い方(JSX や テンプレート)」の積み上げでも、最低限の開発体験を得られます。Svelteは逆で、`.svelte` をコンパイラに通すことが**前提**です。後述する runes / `.svelte.js` / `$state` フィールドなどの制約は、すべてこの「Svelte は言語である」という前提から素直に出てきます。

### 2.2 コンパイラが中央、ランタイムは用途に応じて削られる

Svelteチームは、signalsをAPIとして露出させれば「関数呼び出しで値を取り出す書き味」に引きずられる、と判断しています。APIにしないことで、SSR時にはランタイムごと落とせるし、型推論の邪魔も起きない。**「言語機能にすれば、実装はいつでも差し替えられる」** という立場です。

### 2.3 反応性は runes で「宣言する」

利用者が触るのは signals ではなく、`$state` / `$derived` / `$effect` / `$props` という runes です。これらは見た目こそ関数ですが、公式が **"compiler instructions"** と明言している通り、コンパイラへの指示子であって、ただの関数呼び出しではありません:

> At the heart of Svelte 5 is the new runes API. **Runes are basically compiler instructions that inform Svelte about reactivity.** Syntactically, runes are functions starting with a dollar-sign.
> ([svelte.dev / Svelte 5 migration guide](https://svelte.dev/docs/svelte/v5-migration-guide))

この「関数の見た目をしたキーワード」という折衷は、Svelteがユーザーに課す制約の出発点です。

---

## 3. Svelteが「新しく持ち込んだ」4つの問題

コンパイラ中心・signalsは隠す・反応性は言語機能、という賭けは、**利用者側に新しい義務**を課します。Svelteを原理から理解するには、この代償を4つに分けて言語化しておくと扱いやすくなります。

### 3.1 `.svelte` / `.svelte.js` は「JS のスーパーセットではなく、方言」

Svelte 5 の移行ガイドは、runes を `.js` / `.ts` で使いたい場合の扱いを、次のように書いています(React版でいう「Build a React app from Scratch」に相当する、**スコープ境界の宣言**です):

> if the place where they are instantiated is under your control, you can also make use of runes inside `.js/.ts` files by adjusting their ending to include `.svelte`, i.e. `.svelte.js` or `.svelte.ts`, and then use `$state`:
> ([svelte.dev / Svelte 5 migration guide](https://svelte.dev/docs/svelte/v5-migration-guide))

普通の `.ts` ファイルでは runes は使えず、**拡張子ごと `.svelte.ts` に切り替える**必要があります。これは構文糖でも規約でもなく、「そのファイルを Svelte コンパイラが処理するか」を拡張子で宣言しているわけです。

結果として、エディタ(型)・リンタ・ビルドチェーン・テストランナーは全部 `.svelte` / `.svelte.js` / `.svelte.ts` を**一等市民**として扱う必要があります。React/Vue/Solid が「標準JS(+ JSX/SFC)」のままでおおむね済むのと比べると、Svelteは**ツールチェーンに特別対応を要求する**側に立ちます。

一方で、Svelte 4までの `$:` ラベルに溜まっていた「TypeScriptフレンドリーでない」「並び替えの曖昧さ」「スコープ外れ」といった罠は、この言語化路線で解消されています:

> ...it wasn't TypeScript-friendly (our editor tooling had to jump through some hoops to make it valid for TypeScript), which was a blocker for making Svelte's reactivity model truly universal.
> ([svelte.dev / Svelte 5 migration guide](https://svelte.dev/docs/svelte/v5-migration-guide))

**実務的な含意**:Svelteを入れるということは、「言語が1つ増える」選択です。エコシステム(Vite / vite-plugin-svelte / svelte-check / Prettier / ESLint)はこの前提で構築されています。

### 3.2 runes は「関数」ではなく「構文上の位置に縛られる指示子」

runes は import せずに書けますが、その対価として、**ただの関数として扱えない**という制約が付きます。公式ドキュメントは率直にこう書いています:

> Runes have a `$` prefix and look like functions ... **They differ from normal JavaScript functions in important ways**
> ([svelte.dev / What are runes?](https://svelte.dev/docs/svelte/what-are-runes))

たとえば `$state` は「変数宣言の初期化子」として現れることに意味があります:

```svelte
<script>
  let count = $state(0);          // OK: コンパイラが count を signal に置き換える
  const val = getState();         // NG相当: ただの関数呼び出し
</script>
```

その代わり、値を取り出すときは **`.value` や getter を通さず、素の変数として読み書きできる**のが、Solid/Vue ref との大きな違いです:

> Unlike other frameworks you may have encountered, there is no API for interacting with state — `count` is just a number, rather than an object or a function, and you can update it like you would update any other variable.
> ([svelte.dev / $state](https://svelte.dev/docs/svelte/$state))

この「`.value` 不要」は、**シグナルを関数として扱うと起きる型の狭窄(type narrowing)問題を回避するための設計判断**でもあります:

> For example, we avoid the type narrowing issues that arise when values are accessed by function call
> ([svelte.dev / Introducing runes](https://svelte.dev/blog/runes))

そして `$derived` はこの指示子性をさらに強く制約しています。`$derived(...)` の**式の中で副作用を起こすことはコンパイラが禁じます**:

> The expression inside `$derived(...)` should be free of side-effects. **Svelte will disallow state changes (e.g. `count++`) inside derived expressions.**
> ([svelte.dev / $derived](https://svelte.dev/docs/svelte/$derived))

`$effect` も同じ系譜で、**サーバーサイドレンダリング中には走らない**というランタイム契約が付いています:

> Effects ... only run in the browser, not during server-side rendering.
> ([svelte.dev / $effect](https://svelte.dev/docs/svelte/$effect))

**実務的な含意**:runes を「自前で使いやすくラップ」しようとすると、しばしばコンパイラの特別扱いの外に出てしまいます。React の `useMount` 禁止と似た構図で、**抽象化は言語機能の側に合わせる**のがSvelte流です。再利用したいなら runes を含む `.svelte.js` 関数として切り出し、呼び出し側でも構文位置を保って使います。

### 3.3 `$state` は Proxy による deep reactivity — ただし「POJO と 配列」だけ

`$state` の反応性の境界は、React/Vueとも違う独特のラインに引かれています。

まず、オブジェクトと配列は**再帰的に Proxy でラップ**され、ネストされた代入や `array.push(...)` まで追跡されます:

> If `$state` is used with an array or a simple object, the result is a **deeply reactive state proxy**. Proxies allow Svelte to run code when you read or write properties, including via methods like `array.push(...)`, triggering granular updates.
> ([svelte.dev / $state](https://svelte.dev/docs/svelte/$state))

ところが、この proxify は**オブジェクト/配列以外では止まります**:

> State is proxified recursively **until Svelte finds something other than an array or simple object** (like a class or an object created with `Object.create`).
> ([svelte.dev / $state](https://svelte.dev/docs/svelte/$state))

`new Foo()` のようなクラスインスタンスを `$state()` で包んでも deep reactivity は得られません。Svelte 5 移行ガイドが明示的に警告しているポイントです:

> In Svelte 5, reactivity is determined at runtime rather than compile time, so you should define `value` as a reactive `$state` field on the `Foo` class. **Wrapping `new Foo()` with `$state(...)` will have no effect — only vanilla objects and arrays are made deeply reactive.**
> ([svelte.dev / Svelte 5 migration guide](https://svelte.dev/docs/svelte/v5-migration-guide))

そのため、クラス設計のパターンは「フィールド定義そのものに runes を書く」形になります:

```svelte
<script>
  class Counter {
    count = $state(0);          // クラスフィールドとして宣言する
    double = $derived(this.count * 2);
  }
  const c = new Counter();
</script>
```

これは React / Vue の書き味からは一歩外れます。「データはクラスで閉じ込めたい」「ドメインモデルを POJO以外で表現したい」という要求がある場合、`$state` の **proxy境界** をまたぐか否かを、設計の最初で決めておく必要があります。

同じ境界は `$props` にも現れます。`$bindable` で宣言していない props のフォールバック値は**リアクティブプロキシ化されない**ため、fallbackが使われた場合に mutate しても反映されません:

> The fallback value of a prop not declared with `$bindable` is left untouched — **it is not turned into a reactive state proxy** — meaning mutations will not cause updates
> ([svelte.dev / $props](https://svelte.dev/docs/svelte/$props))

**実務的な含意**:Svelteは「反応性の境界 = Proxyで包めるか」というモデルです。React が参照同一性を、Vue が reactive proxy の到達可能性をユーザーに委ねているのと同じく、Svelteも**境界の設計責任**をユーザーに残しています。

### 3.4 `$effect` は「ライフサイクル」ではなく「外部世界との同期」

これは React の `useEffect` と並べて読むと驚くほど同じ結論になっています。公式ドキュメントの立ち位置は一貫しています:

> Effects are functions that run when state updates, and can be used for things like calling third-party libraries, drawing on `<canvas>` elements, or making network requests.
> ([svelte.dev / $effect](https://svelte.dev/docs/svelte/$effect))

つまり `$effect` の本来の用途は、**外部システム(サードパーティ、Canvas、ネットワーク)との同期**です。props から派生状態を作るため、ビジネスロジックを回すため、初期化を一回だけ行うため、といった用途は原則として本筋ではありません。Reactと同じ警告もはっきり書かれています:

> Generally speaking, you should not update state inside effects, as it will make code more convoluted and will often lead to never-ending update cycles. If you find yourself doing so, see when not to use `$effect` to learn about alternative approaches.
> ([svelte.dev / $effect](https://svelte.dev/docs/svelte/$effect))

そして派生は **`$effect` ではなく `$derived`** に寄せる、というのが Svelte 5の公式パターンです。`$derived` はコンパイラが side-effect を禁止しているぶん、この役割分担が構文レベルで保証されています。

**実務的な含意**:`$effect` を書き始める前に、「これは本当に外部世界との同期か、それとも `$derived` で表現できる派生か」を自問する。Reactでの `useMemo` / `useEffect` の使い分けと同じ問いが、Svelte側にもそのまま存在します。

### 3.5 Svelte単体では「アプリ」にならない

Reactが Create React App を sunset したのと同じように、Svelteも**「UIフレームワーク」のスコープを意図的に狭く保って**います。ルーティング、データ取得、SSR/SSG/SPAの切り替え、form actions、デプロイターゲット別の adapters — これらは全部 SvelteKit 側の責務です:

> Official adapters exist for a variety of platforms:
> `@sveltejs/adapter-cloudflare`, `@sveltejs/adapter-netlify`, `@sveltejs/adapter-node`, `@sveltejs/adapter-static`, `@sveltejs/adapter-vercel`
> ([svelte.dev / Adapters](https://svelte.dev/docs/kit/adapters))

Rich Harris 自身が Vercel のインタビューで、アプリフレームワーク層から出発することの意味を率直に語っています:

> If you, instead of starting at the component-framework level, start at the application-framework level—be that Next.js or Nuxt or SvelteKit—then immediately you've taken a huge chunk of maintenance off your plate. You can start building stuff much, much quicker with one of those frameworks.
> ([vercel.com / The future of Svelte — Rich Harris interview](https://vercel.com/blog/the-future-of-svelte-an-interview-with-rich-harris))

つまりSvelteは、「UIを言語とコンパイラで解く」**狭く深い問題**に特化していて、アプリケーションの残り半分(データ流・ルーティング・配信)は意図的にスコープ外です。Svelte を入れる = 事実上 SvelteKit を入れる、という構造は、React界で Next.js 系に寄ることが準デファクトになっている状況と似ていますが、**選択肢の集約度**は Svelte のほうが強い(実質 SvelteKit 一択)点は押さえておく必要があります。

---

## 4. 原理から導かれる成功パターン

ここまでの4つの代償を踏まえると、公式に散らばっている「推奨」が同じ方向を向いていることが見えてきます。全部、**Svelteの問題定義に沿って書く**ためのパターンです。

1. **source of truth は `$state` に寄せ、派生は `$derived` で書く**
   `$effect` の中で `$state` を書き換えて派生を作らない。`$derived` はコンパイラが side-effect を禁止してくれるので、データの流れが一方向に揃う。

2. **`$effect` は外部世界との同期専用に絞る**
   サードパーティライブラリ、Canvas、ネットワーク、DOMイベントの購読など。**「XになったらYのstateを更新する」の9割は、`$effect` ではなく `$derived` か、イベントハンドラの側**。

3. **Proxy境界をまたぐデータは最初に設計する**
   POJO/配列なら deep reactive、それ以外(クラス、Map/Set、`Object.create`)は `$state` フィールドで明示的に宣言する。「フレームワークの魔法が自動で追う」は POJO 限定と割り切る。

4. **runes を安易にラップしない**
   runes は構文上の位置に意味がある指示子。共通化したいときは、runes を含む関数を `.svelte.js` / `.svelte.ts` で書き、呼び出し側でも「宣言位置」を保って使う。

5. **読み書きは `.value` なしの素の変数で**
   Svelteの一番素直な書き味はここ。わざわざ getter / setter で包むと、シグナル化のメリット(型推論、素の代入の書き味)を潰すことになる。

6. **アプリ層は SvelteKit に寄せる**
   ルーティング / load function / form actions / adapter は自前で作らず、SvelteKit のパターンに乗る。Rich Harris 自身が **「application-framework level から始めた方が速い」** と明言している。

---

## 5. 地雷になりやすいアンチパターン

逆に、上記を裏返すと地雷が見えます。どれも表面上は動くが、**Svelteが保証してくれていた性質**を自分で壊しています。

- `$effect` で props から state を派生し、`$state` を書き換える(二度レンダー + ループの温床)
- `$derived` の式の中で state を書き換える(コンパイラに止められる。止められなくても壊れる)
- `new Foo()` を `$state()` で包んで deep reactivity を期待する(効かない。クラス側に `$state` フィールドを書くのが正解)
- props を destructure して `let x = props.x` のように**ローカル変数に取り出したまま使う**(その瞬間の値コピーになり、親の更新が反映されないケースがある)
- `.svelte.js` にせず普通の `.ts` ファイルで runes を書こうとする(コンパイラが処理しない)
- runes を関数にラップして「自作 Hook 風」に抽象化し、構文位置の制約を踏み抜く
- Svelteが管理する DOM を `document.querySelector` で直接書き換え、次回の反応性トリガーで不整合を起こす
- Svelte 4 の `$:` の直感で Svelte 5 を書き、reactivity が効かないと混乱する(言語仕様が変わっている)

これらが「なぜダメか」を**機能単位**ではなく**Svelteの原理単位(言語である/runes は指示子/Proxy境界/外部同期専用)**で説明できるのが、この記事の目指した地点です。

---

## 6. Svelteが向くユースケース、向かないユースケース

原理から、向き不向きの切り分けも素直に出ます。

**Svelteが勝ちやすい領域**

- 小〜中規模の SPA / ダッシュボード / コンテンツサイト — compiled バンドルの小ささが直接効く。公式が出している比較:
  > The Svelte implementation of TodoMVC weighs 3.6kb zipped. ... React plus ReactDOM without any app code weighs about 45kb zipped.
  > ([svelte.dev / Frameworks without the framework](https://svelte.dev/blog/frameworks-without-the-framework))
- SVGアニメーション・データビジュアライゼーション(Rich Harris の出自が NYT / Guardian のデータビズなこともあって、この領域の書き味が特に練られている)
- Edge / Cloudflare Workers / モバイル PWA — ランタイムが薄く、SSR時にさらに削れるので、コールドスタートと帯域が厳しい環境で有利
- チームとして「Svelteを UI 言語として学習して良い」と腹を括れるプロダクト

**Svelteが負けやすい/コストが過剰な領域**

- 超大規模エンタープライズ SPA — エコシステム(UIライブラリ、求人、採用者数)の厚みで React に届かない
- 「標準 JS ツールチェーンだけで完結したい」「社内の .ts 規約に吸収したい」案件 — `.svelte` / `.svelte.ts` を一等市民にする追加コストが嫌われる
- React Native 的に、**複数の宿主(Web / iOS / ネイティブ)で同じUIロジックを流用したい**ケース — Svelteは基本DOM向けで、React のようなレンダラ可換性の層が厚くない
- アプリフレームワークとして**複数の選択肢を比較しながら組み替えたい**案件 — React界(Next / Remix / TanStack Router / Astro)のような選択の幅は、SvelteKitが実質単一選択肢なので薄い

重要なのは、「Svelteが遅い/劣る」ではなく、**Svelteが解こうとしている問題(UIコードを専用言語とコンパイラで解く)と、そのユースケースが解いてほしい問題が違う**、という捉え方です。

---

## 7. まとめ

Svelteは「UI コードを、汎用 JS ライブラリではなく**専用言語(`.svelte` / `.svelte.js`)とコンパイラ**で解く」という、**特定の問題定義への賭け**をしたフレームワークです。

その賭けと引き換えに、利用者は4つの代償を受け入れています:

1. `.svelte` / `.svelte.js` / `.svelte.ts` は JS のスーパーセットではなく、コンパイラ特別扱いの方言
2. runes は関数ではなく、**構文上の位置に意味がある指示子**
3. `$state` の deep reactivity は **POJO / 配列限定**の Proxy 境界を持ち、クラスや非POJOはユーザーが明示する
4. UIの外側(ルーティング・データ・配信)は、**SvelteKit に寄せる**前提

この4つを腹に収めておくと、

- 日々書いているパターン(`$derived` で派生を書く、`$effect` は外部同期だけに絞る、クラスは `$state` フィールド、`.svelte.js` で runes を再利用する…)が**全部同じ原理の帰結**として見える
- 迷ったときに「Svelteはこの問題をどう定義したか?」に戻って判断できる
- React / Vue / Solid との比較も、「別の賭けをしている」という構造として読める(Reactは "UIランタイム"、Vueは "reactive proxy + compiler-informed VDOM"、Solidは "消えるコンポーネント + 表に出た signals"、Svelteは "言語 + コンパイラ + 隠した signals")

この視点だけでも、同僚に "なぜSvelteなの?" と聞かれたときの答えは、だいぶ変わっているはずです。

## 参考資料

- [What are runes? — Svelte Docs](https://svelte.dev/docs/svelte/what-are-runes)
- [$state — Svelte Docs](https://svelte.dev/docs/svelte/$state)
- [$derived — Svelte Docs](https://svelte.dev/docs/svelte/$derived)
- [$effect — Svelte Docs](https://svelte.dev/docs/svelte/$effect)
- [$props — Svelte Docs](https://svelte.dev/docs/svelte/$props)
- [Svelte 5 migration guide](https://svelte.dev/docs/svelte/v5-migration-guide)
- [Introducing runes — Svelte Blog](https://svelte.dev/blog/runes)
- [Frameworks without the framework — Svelte Blog](https://svelte.dev/blog/frameworks-without-the-framework)
- [Adapters — SvelteKit Docs](https://svelte.dev/docs/kit/adapters)
- [The future of Svelte, an interview with Rich Harris — Vercel](https://vercel.com/blog/the-future-of-svelte-an-interview-with-rich-harris)
- 姉妹記事: [Reactを「UIランタイム」として捉え直す](./react_framework_nature.md)
