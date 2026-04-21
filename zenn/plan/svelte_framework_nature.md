---
title: "Svelteを「コンパイラ × ランタイム反応性」として捉え直す — 解く問題・持ち込む問題・付き合い方"
status: plan
---

## この記事の狙い

React版([react_framework_nature.md](../publish/react_framework_nature.md))、Vue版、Solid版の姉妹記事。Svelteを日常で書いている人が、文法の裏にある**フレームワーク全体の性質**を言語化できるようになることをゴールにする。

React/Vue/Solid との比較を常に意識するが、「Svelteのほうが良い/劣る」の比較記事ではなく、**別の問題定義に賭けた別のフレームワーク**として並べる。

## 想定読者

- Svelte 5(runes mode)を書けるが「なぜこう書くのか」を原理で説明できない人
- React/Vue/Solid 経験者で、Svelte の設計哲学を対比で把握したい人
- 同シリーズ(React / Vue / Solid 版)を読んだ人

## 記事が答える問い

1. ネイティブJSの「状態空間の爆発」に対して、SvelteはReact/Vue/Solidと何を共有し、何を別に賭けたのか
2. Svelte が「コンパイラ + signals ランタイム」として自分の制約として引き受けた代償は何か
3. その性質から自然に導かれる「勝ち筋」と「地雷」は何か
4. どのユースケースで Svelte が有利/不利になるのか

## 扱う範囲

- 扱う: Svelte 5(runes mode)、`$state`/`$derived`/`$effect`/`$props`、`.svelte`/`.svelte.js(ts)`、Proxy によるdeep reactivity、クラスと `$state` の関係、SvelteKit とのスコープ境界
- 扱わない: Svelte 3/4 の `$:` ラベルの詳細(比較用の最小言及のみ)、SvelteKit の具体チュートリアル、各UIライブラリ比較

## セクション構成と各セクションの主張

### 1. イントロ:日常の Svelte を「性質」で語り直す

- React/Vue/Solid 版と同じ導入骨格。文法の紹介ではなく、Svelte の**問題定義への賭け**を読み解く。
- 特に「Svelte 5 で `let` 宣言だけではリアクティブにならなくなった」「runes は import しないのに呼べる」「class 内で `$state` がフィールド定義になる」といった一見奇妙に見える仕様を、**フレームワークの賭け方**から導く。

### 2. 出発点は React/Vue/Solid と同じ — 「状態空間の爆発」

- ネイティブJSで命令的にUIを書くと、相互作用 N に対して整合性の面が O(N²) 以上に膨らむ
- 宣言的レンダリング + 自動DOM同期はReact/Vue/Solid/Svelteが**共有**している解
- 違いはここから。React は「状態→ビューを**純関数**にして diff で整合性に戻す」、Vue は「値の変化を値自身に監視させる + compiler-informed VDOM」、Solid は「コンポーネントは一度だけ実行し、反応性プリミティブとDOMを直接繋ぐ」、**Svelte は「フレームワーク自体をコンパイラに寄せ、反応性を言語(DSL)の一級市民にする」**
- 根拠: react.dev/learn/reacting-to-input-with-state, svelte.dev/blog/frameworks-without-the-framework, svelte.dev/blog/runes

### 3. Svelte の賭け — 「コンパイラ + 薄いランタイム signals」

- Svelte の原点:フレームワークを**実行時ライブラリではなくコンパイラ**として実装し、.svelte をビルド時に素のJSへ焼き落とす
- Svelte 5 以降は「コンパイル時リアクティビティ」から「runes を入口にしたランタイムの fine-grained reactivity(signalsベース)」に舵を切った
- ただし signals は**実装詳細**として隠し、ユーザーが触るのは runes API。SSR ではランタイムを更に削れる余地を残す
- Solid が signals を表舞台の主人公にしたのと対照的に、Svelte は**「signals を内部エンジンにし、runes という DSL の指示子でラップする」** という立ち位置

### 4. Svelte が新しく持ち込んだ4つの代償

#### 4.1 `.svelte` / `.svelte.js(ts)` は「JSの上に乗った専用言語」

- Svelte コンポーネントは仕様上「JS のスーパーセット」ではなく、**専用の言語**として compiler が処理する。結果として、エディタ/型/ビルドチェーンが .svelte を一等市民として扱う必要がある
- runes を `.js/.ts` で使うには拡張子を `.svelte.js` / `.svelte.ts` にする必要がある
- 対価:ツールチェーンの Svelte 特殊対応が必要。逆に React/Vue/Solid のように「標準 JS ファイル + JSX/テンプレート」の単純積み上げでは済まない
- 根拠: svelte.dev/docs/svelte/v5-migration-guide(universal reactivity / .svelte.js), svelte.dev/blog/frameworks-without-the-framework

#### 4.2 runes は「関数」ではなく「コンパイラ指示子」

- `$state` / `$derived` / `$effect` / `$props` は import しない。コンパイラが特別扱いするキーワードで、**宣言位置と使われ方**が意味を決める
- `let count = $state(0)` は「count を signal に置き換える」指示であって、ただの関数呼び出しではない
- だから「`$state(0)` を関数の戻り値として切り出す」「別モジュールに再エクスポートする」「動的に呼ぶ」といった操作は一般化できない
- 逆に `count` は `.value` を持たない素の数として読み書きできる(Solid/Vue ref との違い)
- 対価:runes は**構文上の位置を動かせない**。エディタ支援や lint 経由で制約が強制される
- 根拠: svelte.dev/blog/runes, svelte.dev/docs/svelte/v5-migration-guide

#### 4.3 `$state` は Proxy による deep reactivity — ただしクラスや非POJOには及ばない

- `$state({...})` / `$state([...])` はオブジェクト/配列を**再帰的に Proxy でラップ**し、ネストされた代入まで反応する
- 一方、`new Foo()` のようなクラスインスタンスや Map/Set などは `$state(...)` で単にラップしても deep reactivity は得られない。クラス側で `value = $state(...)` などとフィールドとして宣言する必要がある
- `let x = props.x` のようなローカル分解は「その瞬間の値をコピー」扱いで、反応性が切れる場合がある(Solid と似た罠)
- 対価:利用者は「どこが Proxy 越しで、どこが素のJSか」を意識せざるを得ず、反応性の境界を設計する義務が残る
- 根拠: svelte.dev/docs/svelte/v5-migration-guide, svelte.dev/blog/runes

#### 4.4 Svelte 単体では「アプリ」にならない — SvelteKit とのスコープ分離

- ルーティング、データ取得、SSR/SSG/CSR の切り替え、form actions、adapters によるデプロイ先切替は Svelte ではなく SvelteKit が担当する
- Rich Harris 自身が「コンポーネントフレームワークから始めると、事実上自前アプリフレームワークを組むことになる」と明言している
- 対価:SvelteKit は Vite 前提で、React 界の Next/Remix/TanStack Router のような選択肢の広さがない(=プラットフォーム選択の集約)
- 根拠: vercel.com/blog/the-future-of-svelte-an-interview-with-rich-harris, kit.svelte.dev

### 5. 原理から導かれる成功パターン

- **source of truth は `$state` に寄せ、派生は `$derived` で書く**(`$effect` で setState しない)
- **`$effect` は外部世界との同期専用**(React の useEffect と同じ原則)
- **`$state` は deep reactivity を前提に設計**(外から分解代入した local let は signal ではない)
- **クラスには `$state` フィールドを置く**(インスタンス自体を `$state()` でラップしない)
- **runes は構文上の位置に縛られる**ことを前提にヘルパを設計する(関数にラップして隠さない)
- **コンパイラに頼れるものは頼る**(キー管理、テンプレートの識別、イベントハンドラ最適化など)

### 6. 地雷になりやすいアンチパターン

- `$effect` で props から state を派生し、`$state` を書き換える(二度レンダー + バグ源)
- `let x = props.x` でローカルコピーし、あとで props が変わったのに x が古いまま(分解代入で反応性を失う)
- クラスを `$state()` でラップしてdeep reactiveにしようとする(効かない)
- runes を関数の中にラップして抽象化しようとする(構文位置の制約に引っかかる)
- Svelte が管理する DOM を `document.querySelector` で直接書き換え、再レンダー時に不整合を起こす
- `$:` ラベルに慣れた頭で Svelte 5 を書き、reactivity が効かないと混乱する

### 7. Svelteが向くユースケース、向かないユースケース

**Svelteが勝ちやすい領域**
- 小〜中規模の SPA / コンテンツサイト / ダッシュボード — compiled バンドルの小ささが効く
- SVG アニメーションやデータビジュアライゼーション(Rich Harris の出自が NYT データビズ)
- Edge / Cloudflare / モバイル PWA — ランタイムが薄いのでコールドスタート/帯域が厳しい環境で有利
- チームが「UI 言語として学習して良い」と腹を括れるプロダクト

**Svelteが負けやすい領域**
- 超大規模エンタープライズ SPA — エコシステムの深さと採用者数で React に及ばない
- 「標準 JS ツールチェーンだけで揃えたい」案件 — .svelte を一等市民にする追加コストが嫌われる
- React Native / 複数ホスト共通のUIロジック — Svelte は DOM 中心で、レンダラ可換性が React ほど広くない
- メタフレームワークの選択肢を多く持ちたい案件 — SvelteKit が事実上の単一選択肢

### 8. まとめ

- Svelte は「UI コードを、汎用 JS ライブラリではなく**専用言語とコンパイラ**で解く」という問題定義への賭け
- Svelte 5 で runes を導入し、compile-time reactivity から **runes を入口にしたランタイム fine-grained reactivity** に移行した
- 利用者は「言語拡張」「runes の構文制約」「Proxy 反応性の境界」「SvelteKit への依存」の4つを受け入れて、薄いランタイムと高い DX を手に入れている

## 根拠として読むべき主要URL

- https://svelte.dev/blog/runes
- https://svelte.dev/blog/frameworks-without-the-framework
- https://svelte.dev/docs/svelte/v5-migration-guide
- https://svelte.dev/docs/svelte/what-are-runes
- https://svelte.dev/docs/svelte/$state
- https://svelte.dev/docs/svelte/$derived
- https://svelte.dev/docs/svelte/$effect
- https://vercel.com/blog/the-future-of-svelte-an-interview-with-rich-harris
- https://github.com/sveltejs/svelte/discussions/10085(Tenets)

## 追加調査ポイント

- `$state` が Proxy でラップする範囲と、クラスの扱いの正確な仕様
- `$effect` のタイミング(effect が何のタイミングで走り、cleanup がいつ走るか)
- `$derived` が read-only で side effect を禁止している根拠
- `.svelte.js` / `.svelte.ts` の位置づけの公式な記述
- SvelteKit との責務分離(公式 Docs の "What is SvelteKit?" 相当ページ)
