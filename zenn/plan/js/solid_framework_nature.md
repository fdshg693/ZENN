---
title: "Solidを「消えるコンポーネント・残るリアクティビティ」として捉え直す — 解く問題・持ち込む問題・付き合い方"
status: plan
---

## 想定読者と前提

- React / Vue のどちらかを日常的に書いている中〜上級フロントエンドエンジニア
- Solid を触ったことがある、あるいは存在は知っているが「なぜ Signals なのか」「React と何が違うのか」を自分の言葉で言えない人
- Svelte runes / Vue Vapor / signals-first ランタイムとの比較判断の土台が欲しい人

## この記事の立場

- 文法(JSX/`createSignal` API)には触れない
- 各 API の使い方ではなく「なぜその形になったか」「その形が何を強いているか」に寄る
- コード例は原理を示すのに必要なところだけ、差分以外は極力簡略化する
- 姉妹記事の React版・Vue版と**対で読める構造**に揃える

## 記事で答える問い

1. ネイティブJSの「状態空間の爆発」に対して、React/Vue と Solid は何を共有し、何を別に賭けたのか
2. Solid が「UIランタイム+コンパイラ」として自分の制約として引き受けた代償は何か
3. その性質から自然に導かれる「勝ち筋」と「地雷」は何か
4. どのユースケースで Solid が有利/不利になるのか

## セクション構成(plan)

### 1. イントロ:日常の Solid を「性質」で語り直す

- React/Vue版と同じ導入骨格を維持する。**問題設定の解像度**を一段上げることがゴール。
- 特に「Reactから来た人が必ず一度ハマる `props` の destructure 禁止」「`onMount` と `createEffect` の関係」「`<For>` と `<Index>`」を、表層の書き方ではなく**フレームワークの賭け方**から導く。

### 2. 出発点は React/Vue と同じ — 「状態空間の爆発」

- ネイティブ JSで命令的にUIを書くと、相互作用 N に対して整合性の面が O(N²) 以上に膨らむ
- 宣言的レンダリングと自動DOM同期はReact/Vue/Solidが**共有**している解
- 違いはここから先。React は「状態→ビューを**純関数**にして diff で整合性に戻す」、Vue は「**値の変化を値自身に監視させる**(reactive proxy)+ compiler-informed VDOM」、**Solid は「コンポーネントは一度だけ実行し、反応性プリミティブとDOMを直接繋げる」**
- 根拠: react.dev/learn/reacting-to-input-with-state, vuejs.org/guide/introduction, docs.solidjs.com/concepts/intro-to-reactivity

### 3. Solid の賭け — 「消えるコンポーネント・残るリアクティビティ」

- Ryan Carniato の "5 Ways SolidJS Differs" を軸に、Solid の3つの性質を整理する。

#### 3.1 コンポーネントは一度だけ実行される(vanishing components)

- コンポーネント関数は**1度しか走らない**。その後に残るのは JSX から生成されたDOMとリアクティブプリミティブだけ
- > "Components do not re-run, just the primitives and JSX expressions you use. ... components actually more or less disappear after the fact."
- 結果として「stale closure」「Hook Rules」「依存配列の整合性」という React 特有の負債は存在しない
- 対価:コンポーネント本体は「セットアップ関数」。`let x = props.x` のように値を捕まえると、それは**初期値の1回コピー**で、反応性は切れる
- 根拠: dev.to/ryansolid/5-ways-solidjs-differs-from-other-js-frameworks-1g63, docs.solidjs.com/concepts/intro-to-reactivity

#### 3.2 リアクティビティは「値」単位で、VDOMを通らない

- `createSignal` はゲッター/セッターのペア。ゲッターを**tracking scope**(`createEffect` / `createMemo` / JSX)の中で呼ぶと依存として登録される
- 値が変わると、**そのゲッターを読んでいたエフェクトだけ**が再実行される。コンポーネントツリーの再レンダーや仮想DOM差分は発生しない
- Solid は VDOM を持たない。コンパイラが JSX を「どのノードのどの属性をどの signal に繋げるか」という**具体的なDOM更新コード**に落とす
- Ryan の表現:「components -> hooks -> signals という分解のさらに先」
- 根拠: docs.solidjs.com/concepts/signals, docs.solidjs.com/advanced-concepts/fine-grained-reactivity, dev.to/ryansolid/thinking-granular-how-is-solidjs-so-performant-4g37, dev.to/playfulprogramming/thinking-locally-with-signals-3b7h

#### 3.3 コンパイラが props をレイジー評価する

- Solid のコンパイラは JSX の動的 props を**getter 付きオブジェクト**に変換する:`{ get value() { return props.value } }`
- これにより、`<B value={a()} />` と書いても `a()` の実行はコンポーネント B が最終的にその値を消費する場所まで**遅延**される
- 結果として反応性はツリーを跨いで保たれる(「pinpoint accuracy でコンポーネント境界を越えてDOM更新される」)
- 代償:**props を destructure するとその瞬間にレイジー評価の対象から外れ、反応性が切れる**
- 根拠: dev.to/ryansolid/5-ways-solidjs-differs-from-other-js-frameworks-1g63, docs.solidjs.com/concepts/components/props, www.solidjs.com/guides/rendering

### 4. Solid が「新しく持ち込んだ」4つの問題

React が「over-reactivity・Effectの同期プリミティブ化・ツリー位置としての state identity・単体ランタイムの限界」という4つの代償を利用者に押しつけたように、Solid も**別の4つ**を押しつけている。

#### 4.1 Reactive scope — tracking scope の境界が全てを決める

- Solid では「このコードは反応する / しない」が**tracking scope に入っているかどうか**だけで決まる
- tracking scope を作るのは `createEffect` / `createMemo` / JSX のみ(`createRenderEffect`, `createRoot` も同様)
- `onMount` は `createEffect(() => untrack(fn))` と等価:**明示的に tracking しない**
- コンポーネント関数本体は tracking scope **ではない** — ここで signal を読むと「初回のスナップショット」になる
- 結果として初心者は次のような間違いをする:
  ```jsx
  function Counter() {
    const [count, setCount] = createSignal(0);
    if (count() > 5) return <div>Big</div>;  // ❌ 一度しか評価されない
    return <div>{count()}</div>;              // ✅ JSX内なので tracking される
  }
  ```
- 解決手段は `<Show>` / `<Switch>` / JSX式(関数)で tracking scope を作り直すこと
- 根拠: docs.solidjs.com/concepts/effects, docs.solidjs.com/concepts/signals, docs.solidjs.com/reference/lifecycle/on-mount, docs.solidjs.com/reference/reactive-utilities/untrack

#### 4.2 Props の反応性は「props オブジェクトへのアクセス」でしか保たれない

- 公式は destructure を明確に禁じている:
  > "Unlike in some other frameworks, you cannot use object destructuring on the `props` of a component."
  > "destructuring props is not recommended as it can break reactivity."
- `props` は getter で包まれた lazily-evaluated オブジェクト。`const { name } = props` は初回だけ値を読んで終わり
- spread や `Object.assign`、任意の非 tracking 関数へ渡すのも同じ理由で壊れる
- これを埋めるために Solid は `mergeProps` / `splitProps` を用意している(Vue の `toRefs` と立ち位置が似ている)
- TypeScript から見ると `props` は普通のオブジェクトに見えるため、**型システムがこの制約を守ってくれない**
- 根拠: docs.solidjs.com/concepts/components/props, www.solidjs.com/tutorial/props_defaults, www.solidjs.com/tutorial/props_children, docs.solidjs.com/reference/reactive-utilities/split-props

#### 4.3 Effect は「ライフサイクル」ではなく「外部との同期プリミティブ」

- React/Vue 記事と**構造上の類似点**。公式は `createEffect` の中で signal をセットすることを明確に警告:
  > "Effects are primarily intended for handling side effects that do not write to the reactive system. It's best to avoid setting signals within effects, as this can lead to additional rendering or even infinite loops if not managed carefully. Instead, it is recommended to use createMemo to compute new values that rely on other reactive values."
- 派生は `createMemo`、外部との同期は `createEffect`、**初回だけ** / **untrack したい**なら `onMount`
- 「依存配列で reactivity を手動管理する」という React の税は不要(自動依存追跡)。代わりに「値を変数に捕まえると反応性が消える」というスコープの税がある
- Ryan の立場:「Signals を変数に代入できるようにしない理由」— データグラフを view の外に漏らさないためにあえて制限している
- 根拠: docs.solidjs.com/concepts/effects, docs.solidjs.com/reference/lifecycle/on-mount, dev.to/playfulprogramming/thinking-locally-with-signals-3b7h

#### 4.4 リスト identity — `<For>`(値で追跡)と `<Index>`(位置で追跡)の明示的二択

- React の `key` は subtree identity の宣言、Vue の `:key` は in-place patch を上書きする宣言。Solid では**この選択がコンポーネント名として分離**されている:
  - `<For>`: 値 identity で追跡。同じ item が別の位置に動いたらDOMノードは**再利用されて移動**される(keyed)
  - `<Index>`: 位置で追跡。同じ index の位置に別の値が入ったら子行の signal が更新される(indexed)
- Store 側では `reconcile` が同じ思想で「新旧データの差分を検出して必要な部分だけ更新する」
- 実務的な含意:「子が state を持つ」「DOM の持続が必要」なら `<For>`、「値そのものが更新される固定位置のフォーム」なら `<Index>` — 選択ミスは state 消失 or 過剰再生成を生む
- 根拠: docs.solidjs.com/reference/components/for, docs.solidjs.com/reference/components/index-component, docs.solidjs.com/reference/reactive-utilities/index-array, docs.solidjs.com/reference/store-utilities/reconcile

### 5. (補)Solid が「アプリ」になるまで — SolidStart の位置

- React が Create React App を sunset して「フレームワークを使え」と明示した対比として、Solid は SolidStart を first-party framework として提供
- SolidStart は Vite + Nitro + Solid Router で、SSR/SSG/CSR/Streaming/Server Functions を1本に統合
- 2022年から `"use server"` による Server Functions を先行導入、React Server Components の流れと**別系統だが同世代**の解
- エコシステムの厚みは React/Vue に及ばない。Solid を選ぶのは「ランタイムの性質を取りに行く」判断であり、エコシステム全体で判断する話になる
- 根拠: www.solidjs.com/blog/introducing-solidstart, www.solidjs.com/blog/solid-start-the-shape-frameworks-to-come, docs.solidjs.com/llms.txt

### 6. 原理から導かれる成功パターン

1. **派生は `createMemo` / 派生 signal、同期だけ `createEffect`**
   - 「Aが変わったらBを更新する」はほぼ全て `createMemo` で書ける。`createEffect` 内で setSignal する前に「これ `createMemo` では無理か?」を自問する。
2. **`props.x` を直接使え、destructure するな**
   - `const { x } = props` は反応性破壊。spread, `Object.assign` も同じ。必要なら `splitProps`、default 値なら `mergeProps`。
3. **`<Show>` / `<For>` / `<Index>` / `<Switch>` を使い、コンポーネント本体で `if` しない**
   - コンポーネント本体は setup。条件分岐・ループは JSX 側の tracking scope に置く。
4. **`<For>` と `<Index>` を意図的に選ぶ**
   - 「要素 identity が意味を持つか」で決める。state を持つ子・DOM 持続が必要なら `<For>`、固定位置の表示更新なら `<Index>`。
5. **Store と Signal の使い分けは「粒度」で決める**
   - 複数値の関係を持つなら store、独立した値なら signal。store は proxy で property アクセスごとに signal が立つので、巨大オブジェクトを全部入れても必要な部分だけが tracking される。
6. **`onMount` / `onCleanup` は「スコープライフサイクル」として捉える**
   - `onMount` は初回だけ untrack で走り、`onCleanup` は所有スコープが破棄されるときに走る。コンポーネント unmount と必ずしも 1:1 ではなく、「所有スコープ」の単位。
- 根拠: docs.solidjs.com/concepts/effects, docs.solidjs.com/concepts/derivations, docs.solidjs.com/concepts/stores, docs.solidjs.com/reference/lifecycle/on-mount, docs.solidjs.com/reference/lifecycle/on-cleanup

### 7. 地雷になりやすいアンチパターン

- `const { count } = props` / `props` を spread して他関数に渡す(反応性が切れる)
- コンポーネント本体で `const name = props.name` / `const c = count()` と変数に捕まえる(初回コピーで凍結)
- コンポーネント本体で `if` / `&&` / 三項演算子で早期 return(条件評価は一度だけ、以降変わらない)
- `createEffect` の中で `setSignal` して派生を同期する(`createMemo` で消える / 無限ループの温床)
- `<For>` と `<Index>` を何も考えずに選ぶ(子 state 消失 or 過剰再生成)
- signal を変数に代入してコンポーネントの外に持ち出す(Ryan 本人が「やってほしくない」と書いている。`isSignal` が存在しない理由)
- store の生オブジェクトを直接変更する(proxy 側を触らないと反応性が起きない)
- 根拠: docs.solidjs.com/concepts/components/props, docs.solidjs.com/concepts/effects, dev.to/playfulprogramming/thinking-locally-with-signals-3b7h

### 8. どこで Solid が勝ち、どこで負けるか

**勝ちやすい領域**

- 手動メモ化のレビューコストに疲れた React チームが、同じ JSX 系のまま別の賭けへ移行したいケース
- 高頻度更新(グラフ、チャート、ダッシュボード、ビジュアライザ、ゲーム的UI)で、コンポーネント再レンダーのコストが効くケース
- バンドルサイズを絞りたい(Solid のコアは小さい)
- Signals という最近の潮流(TC39 signals proposal, Svelte runes, Vue Vapor)を正面から取りに行く設計判断

**負けやすい/コスト過剰な領域**

- エコシステム優先のプロダクト(React Native、大量の React 製ライブラリ、Next.js の機能全部欲しい、など)
- チームに Solid の「reactive scope / props の扱い」を教える余裕がない場合 — Reactと見た目が似ているのが罠になる
- RSC と同等の「サーバーファースト UI モデル」に一本化したい場合 — SolidStart はサーバーファーストではあるが、React の RSC とは別系統の抽象
- コンテンツ中心・静的性が高く、そもそもランタイム自体を軽くしたい場合 — Astro や Qwik のアプローチが合う

- 重要なのは「Solid が速い / Reactが遅い」ではなく、**「コンポーネントを再実行するか / 反応性プリミティブだけ残すか」という問題定義そのものの選択**であるという捉え方。

### 9. まとめ

- Solid は「コンポーネントは一度しか走らず、残るのは反応性プリミティブとコンパイル済みDOM更新コードだけ」という**特定の問題定義への賭け**をしたUIランタイム+コンパイラ
- その賭けと引き換えに、利用者は4つの制約を受け入れている:
  1. tracking scope に入っているかどうかが反応性の唯一のルール
  2. `props` は destructure 不可(`splitProps` / `mergeProps` で埋める)
  3. Effect はライフサイクルではなく外部世界との同期プリミティブ、派生は `createMemo`
  4. リスト identity は `<For>`(値)と `<Index>`(位置)の明示的二択
- React版(UIランタイム)/ Vue版(Compiler-Informed Virtual DOM)と並べると、**同じ問題(状態空間の爆発)に対する3つの別の賭け方**として読める

## 使用した調査ファイル

- `temp/solid_framework_nature/search_solid_philosophy.json`
- `temp/solid_framework_nature/search_solid_carniato.json`
- `temp/solid_framework_nature/search_solid_tradeoffs.json`
- `temp/solid_framework_nature/search_solid_tracking.json`
- `temp/solid_framework_nature/search_solid_for_index.json`
- `temp/solid_framework_nature/search_solidstart.json`
- `temp/solid_framework_nature/extract_solid_core_docs.json`
- `temp/solid_framework_nature/extract_solid_effect_store.json`
- `temp/solid_framework_nature/extract_carniato_blogs.json`
