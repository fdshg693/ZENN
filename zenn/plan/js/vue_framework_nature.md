---
title: "Vueを「コンパイラ付きリアクティブランタイム」として捉え直す"
status: plan
---

## この記事の狙い

React版記事([react_framework_nature.md](../publish/react_framework_nature.md))の姉妹記事。Vueを日常で書いている人が、文法の裏にある**フレームワーク全体の性質**を言語化できるようになることをゴールにする。

Reactとの対比を常に意識して書く。ただし「Vueの方が良い/劣る」の比較記事ではなく、**別の問題定義に賭けた別のランタイム**として並べる。

## 想定読者

- Vue 3 を書けるが「なぜこう書くのか」を原理で説明できない人
- React 経験者で Vue の設計哲学を Reactの語彙との対比で把握したい人
- Vue と React の選定判断軸を手に入れたい人

## 記事が答える問い

1. ネイティブJSが詰んだ問題に対して、VueはReactと何を共有し、何を別に賭けたのか
2. Vue が自分の制約として引き受けた代償は何か
3. その性質から自然に導かれる「勝ち筋」と「地雷」は何か
4. どのユースケースでVueが有利/不利になるのか

## 扱う範囲

- 扱う: Vue 3(Composition API と `<script setup>`)、反応性システム、テンプレート/コンパイラ、watch/watchEffect/computed、v-for key、エコシステムのスコープ
- 扱わない: Vue 2 と Options API の詳細、Nuxt 固有の話、各UIライブラリ比較、Pinia の使い方チュートリアル

## セクション構成と各セクションの主張

### 1. 出発点 — ネイティブJSが詰んだのは「状態空間の爆発」

- React版と同じ出発点を置く。命令的DOM操作の組み合わせ爆発を説明。
- ここで Vue は React と**同じ問題認識**から出発したと明示する。
- 根拠: Vue Introduction の "Declarative Rendering / Reactivity" 説明
  - https://vuejs.org/guide/introduction
  - https://vuejs.org/guide/essentials/reactivity-fundamentals

### 2. VueとReactは「別の賭け」をした

- Reactは「状態→ビューの純関数」に賭けた。Vueは「値の変化を**値自身に監視させる**」=細粒度リアクティビティに賭けた、と主張する。
- React は Virtual DOM を diff することで整合性を出す。Vue はリアクティビティ・システムが**何が変わったか**を知っているので、再レンダリング範囲が最初から決まっている。
- Vue は **Compiler-Informed Virtual DOM** = コンパイラがテンプレートを静的解析して実行時の diff 対象を縮める、という公式立場。
- 根拠:
  - https://vuejs.org/guide/extras/rendering-mechanism (Compiler-Informed Virtual DOM)
  - https://vuejs.org/guide/extras/reactivity-in-depth (Runtime vs. Compile-time Reactivity, signalsと同じreactivity primitive)
  - https://vuejs.org/ トップ ("Truly reactive, compiler-optimized rendering system that rarely requires manual optimization")

### 3. Vueは「コンパイラ + 細粒度リアクティブランタイム」

React記事の §2 "Reactは UI runtime" に対応するVueの本質定義。3つの性質を出す。

#### 3.1 リアクティビティは Proxy ベースで、runtime に寄っている

- Vue 3 の reactivity は Proxy による。ref は getter/setter。
- React と違い、Virtual DOM diff でなく依存追跡で「誰が再レンダーすべきか」を直接知る。
- 根拠: https://vuejs.org/guide/extras/reactivity-in-depth

#### 3.2 コンパイラが運命を決める

- 多くのフレームワーク(含むReact)はコンパイラと runtime が疎結合。Vue は両方を自分で握っている。
- コンパイラが静的解析して「動くノードだけ flatten して runtime に渡す」ことで、diff コストをアプリ規模に対して線形以下にする。
- 代償: テンプレートという DSL を使う前提。JSX のような「ただのJS」ではない。
- 根拠: https://vuejs.org/guide/extras/rendering-mechanism

#### 3.3 "Progressive Framework" — 徐々に導入できる

- スクリプトタグで貼るだけの使い方から SSR までの連続性。
- React の「ランタイム + 自分で組み立てる」設計に対し、Vue はエコシステム(Router/Pinia)の公式性が高い。
- 根拠:
  - https://vuejs.org/guide/introduction (Progressive Framework)
  - https://blog.vuejs.org/posts/vue-3-one-piece (Taking the "Progressive Framework" Concept Further)

### 4. Vueが「新しく持ち込んだ」4つの問題

React版§3と対応させる。Vueの代償を4つに言語化する。

#### 4.1 ref と reactive — プリミティブの二元性と `.value` 負債

- Vue 3 の反応性プリミティブは2つ: `ref()` と `reactive()`。歴史的・技術的な理由で分かれている(ref は `.value` で包む、reactive は Proxy なので深い)。
- `reactive()` の限界:
  - プリミティブ値を保持できない
  - オブジェクト全体を置き換えできない(参照を保つ必要がある)
  - 分割代入すると反応性を失う
- 根拠:
  - https://vuejs.org/guide/essentials/reactivity-fundamentals (Limitations of reactive())
  - https://vuejs.org/api/reactivity-utilities (toRefs, toRef)
  - https://vuejs.org/guide/extras/reactivity-transform.html (".value is easy to miss")

**Reactとの対比**: React は「参照同一性」が抽象から漏れる。Vue は「反応性の連結」が抽象から漏れる。どちらも runtime の制約がユーザーに降りてきている。

#### 4.2 Proxy identity — 生オブジェクトと proxy は別物

- `reactive(raw) !== raw`。ネストされたオブジェクトも取り出すと proxy が返る。
- `markRaw` / `shallowReactive` / `shallowRef` を知らないと、3rd party ライブラリや大きな不変データを渡したとき identity hazard に遭う。
- 根拠:
  - https://vuejs.org/guide/essentials/reactivity-fundamentals (Reactive Proxy vs. Original)
  - https://vuejs.org/api/reactivity-advanced (markRaw, shallowReactive — "identity hazards")

#### 4.3 watch / watchEffect は「ライフサイクル」ではなく「同期プリミティブ」

- React の Effect と同じ罠。派生値は `computed` で、外部世界との同期だけ `watch`/`watchEffect`。
- `watch` は明示依存、`watchEffect` は自動追跡。どちらも「外部世界への反映」が用途。
- propsから派生データを作るため `watch` + ref を使うのはほぼ常にアンチパターン ==> `computed`で足りる。
- 根拠:
  - https://vuejs.org/guide/essentials/watchers (watch vs watchEffect)
  - https://vuejs.org/api/reactivity-core (computed, watch, watchEffect)
  - https://vuejs.org/glossary/ (reactive effect 定義)

**Reactとの対比**: Reactは「render中に計算できるならEffect不要」。Vueは「`computed`で書けるなら`watch`不要」。同じ原理。

#### 4.4 list identity — v-for の key はRと同じ

- v-for はデフォルトで in-place patch。コンポーネント状態や form input を含む場合は `:key` 必須。
- key は「reuse/reorder の hint」。index をkeyに使うと並べ替えで壊れる、はReactと同じ。
- Reactの`key`での subtree リセットに対応するのが Vue の `:key="foo"` を要素に付けての強制再生成。
- 根拠:
  - https://vuejs.org/guide/essentials/list (Maintaining State with key)
  - https://vuejs.org/api/built-in-special-attributes (key special attribute)
  - https://v3-migration.vuejs.org/breaking-changes/key-attribute

#### 4.5 (補) 「アプリ」としての完成は Vue も単体では出ない — が、Reactよりは埋まっている

- Router、状態管理、SSR は公式/準公式(Vue Router, Pinia, Nuxt)。
- React の Create React App sunset に相当する切断は Vue にはない。これは Progressive Framework 宣言の裏返し。
- 根拠:
  - https://vuejs.org/guide/introduction (Progressive Framework 使われ方一覧)

### 5. 原理から導かれる成功パターン

各ルールに「なぜか」を添える。

1. **派生は `computed`、同期は `watch`** — Effect版と同じ原理
2. **composable は `ref` を返し、`reactive` を返すな** — 分割代入しても反応性を失わないため
3. **状態はできるだけ `ref` に寄せ、どうしても必要なときだけ `reactive`** — `.value` は負債だが、`reactive` の置換不能/destructure 消失の方が事故が大きい
4. **`:key` はvi-forで常に付ける** — 動かしたくなるケースの多くは index に逃げると壊れる
5. **3rd party オブジェクトは `markRaw` / `shallowRef`** — identity hazard を避ける
6. **Template を書く前提に立つ** — render function で書く旨味はコンパイラ最適化を捨てる代わりに JS 力を得ること。普段は逆

### 6. 地雷になりやすいアンチパターン

- `watch` で props から派生 state を作って `ref.value = ...` で同期する(二度更新 + computed で消える)
- composable の戻り値を `reactive({...})` で返し、呼び出し側で `{ x, y } = useX()` と分割代入(反応性が切れる)
- 巨大 3rd party インスタンスを `ref` に入れて deep reactive 化(コスト爆発)
- v-for の key に index や `Math.random()`
- Vue が管理する DOM を jQuery 系で直接触る(Reactと同じ)
- Options API と Composition API を同一コンポーネントで混在させつつ、`this` 依存コードを setup 側に持ち込む

### 7. Vueが向くユースケース、向かないユースケース

**Vueが勝ちやすい**
- progressive に導入したい既存のサーバレンダリング主体サイト
- テンプレートで書ける程度の動的性で、手動メモ化にコストを使いたくないアプリ
- 設計が収束していて、公式エコシステム(Router/Pinia)に乗りたいチーム
- コンパイラ最適化が効く中規模 SPA

**Vueが負けやすい/コストが過剰**
- JSX の柔軟性が必要な、コンポーネント生成ロジックが極端に動的なケース(render function に降りるならRの方が素直)
- 巨大オブジェクトを reactive に渡して扱うような、reactivity の identity が事故になるドメイン
- React RSC のような最新のサーバー境界設計を取り込みたいケース(Nuxt 3 に近い概念はあるが、RSC とは別モデル)
- signal-first の超軽量ランタイムが絶対条件のケース(Solid/Preact signalsの方が筋)

**重要な論点**: 「React と Vue のどちらが速い」ではなく、**runtime diff を前提にするか、反応性を前提にするか**という問題定義の違い。

### 8. まとめ

- Vue は「値の変化を値自身に知らせる」細粒度リアクティビティと「コンパイラが runtime を助ける」アーキテクチャに賭けた。
- 代償として、ref/reactive の二元性、Proxy identity、`.value` 負債、テンプレート DSL を受け入れている。
- Reactと比べて「暗黙に効率よく動く」代わりに、**どこが反応してどこが切れたかを追う抽象**が増えた。
- Reactの `useMemo`, `memo` を日常的に書く負担がない代わりに、`toRefs`, `markRaw`, `shallowRef` を知っている必要がある。
- 「別の賭けをしたランタイム」として並べて理解すると、選定判断もアンチパターンの根っこも見える。

## 参考URL(本文執筆時にインライン引用する想定)

- https://vuejs.org/guide/introduction
- https://vuejs.org/guide/essentials/reactivity-fundamentals
- https://vuejs.org/guide/extras/reactivity-in-depth
- https://vuejs.org/guide/extras/rendering-mechanism
- https://vuejs.org/guide/essentials/watchers
- https://vuejs.org/guide/essentials/list
- https://vuejs.org/guide/reusability/composables
- https://vuejs.org/api/reactivity-core
- https://vuejs.org/api/reactivity-advanced
- https://vuejs.org/api/reactivity-utilities
- https://vuejs.org/api/built-in-special-attributes
- https://vuejs.org/glossary/
- https://blog.vuejs.org/posts/vue-3-one-piece
- https://v3-migration.vuejs.org/breaking-changes/key-attribute

## 調査ファイル

- [temp/vue_framework_nature/search_vue_design_philosophy.json](../../temp/vue_framework_nature/search_vue_design_philosophy.json)
- [temp/vue_framework_nature/search_vue_reactivity_caveats.json](../../temp/vue_framework_nature/search_vue_reactivity_caveats.json)
- [temp/vue_framework_nature/search_vue_effects.json](../../temp/vue_framework_nature/search_vue_effects.json)
- [temp/vue_framework_nature/search_vue_key.json](../../temp/vue_framework_nature/search_vue_key.json)
- [temp/vue_framework_nature/search_vue_compiler.json](../../temp/vue_framework_nature/search_vue_compiler.json)
- [temp/vue_framework_nature/search_vue_destructure.json](../../temp/vue_framework_nature/search_vue_destructure.json)
