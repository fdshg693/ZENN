---
title: "Reactを「UIランタイム」として捉え直す — 解く問題・持ち込む問題・付き合い方"
status: plan
---

## 想定読者と前提

- Reactを日常的に書いているが、「なぜこれが選ばれたのか」「何を代償にしているのか」を自分の言葉で言えない中〜上級フロントエンドエンジニア
- `useEffect`・`key`・`memo`の書き方は分かるが、**フレームワーク全体の思想**として言語化できるようになりたい人
- Svelte・Vue・Solid 等との比較判断の土台が欲しい人

## この記事の立場

- 文法 (JSX / Hooks の API) には触れない
- 各APIの「使い方」ではなく「なぜその形になったか」「その形が何を強いているか」に寄る
- コード例は必要なところだけ、差分以外は極力簡略化する

## 記事で答える問い

1. ネイティブJSが指数的に破綻するのは具体的にどの次元で、Reactはその問題をどう再定義したのか
2. Reactが「UIランタイム」になった結果、利用者側に押し付けられた新しい制約は何か
3. その性質を踏まえた成功パターン/アンチパターンは何か
4. Reactが向く/向かないユースケースはどう切り分けられるか

## セクション構成(plan)

### 1. イントロ:日常のReactを「性質」で語り直す

- 読者は明日からReactを書き続ける。この記事のゴールは「書き方の上手さ」でなく、**問題設定の解像度**を一段上げること。
- 扱うのは3層:(a) Reactが選んだ問題定義、(b) その定義の代償、(c) 代償の上で勝つためのパターン。

### 2. ネイティブJSが解けなかった問題 — 状態空間の爆発

- 命令的UIの基本ループ:「イベント → 状態の手動遷移 → DOM の手動同期」
- 公式の指摘:命令的アプローチは単体では動くが、「指数的に管理が難しくなる」(`react.dev/learn/reacting-to-input-with-state`)
- 複雑性の正体は**状態遷移の組み合わせ数**と**DOM更新との整合性維持**。相互作用 N に対してバグが出る面は O(N²) 以上
- Reactが再定義したのは「UI を状態の関数にする」こと。状態 → ビューの写像を一方向にし、DOMとの同期はランタイムに移譲する
- 根拠: react.dev/learn/reacting-to-input-with-state, legacy.reactjs.org/docs/design-principles

### 3. Reactの賭け — 「UIランタイム」というアーキテクチャ

- Dan Abramov "React as a UI runtime" の主張を起点にする
- Reactは「DOMライブラリ」ではなく、**汎用のUIランタイム**:宿主ツリー (host tree) に対して、外部イベント(入力・ネットワーク・タイマ)に反応して予測可能に変更を加える層
- 宿主が DOM でも iOS でも PDF でも JSON でも同じモデルが成立する(レンダラ可換)
- 重要なのは Reactが押しつけている**制約**:
  - render は純関数、同じ入力なら同じ出力 (`react.dev/learn/render-and-commit`)
  - 状態は closure に閉じ込めず、Reactが把握できる形で保持する
- この制約と引き換えに、Reactは「UIを現在の props と state から traceable にする」保証を返す(debuggingが「退屈だが有限」)
- 根拠: overreacted.io/react-as-a-ui-runtime, legacy.reactjs.org/docs/design-principles

### 4. 中央集権ランタイムの帰結 — Reactが吸収し、利用者が従う

- Reactチーム原則の"Absorb the Complexity"を引く
- 「Reactは疎結合な小モジュールに分解できない。誰かが coordinator として振る舞う必要があり、それがReactの仕事」
- 帰結1: 新機能は既存機能すべてと矛盾なく動く必要がある → React本体のコア変更は重く、慎重
- 帰結2: 利用者は「Reactの外で状態を動かす」と即座に予測性が壊れる(外部可変状態を render で読む、refで同期を回避する、等)
- 帰結3: ランタイムを通らない最適化(直接 DOM 触る、setState を回避して ref 更新で済ませる)は**その瞬間だけ**速く、長期ではデバッグ困難を生む
- 根拠: overreacted.io/what-are-the-react-team-principles

### 5. Reactが新しく持ち込んだ4つの問題

#### 5.1 over-reactivity — 参照同一性が漏れる抽象

- 公式の自認:「Reactは時に過剰に reactive になり、再レンダーしすぎる」(React Labs 2023/03)
- 原因:JS には「2つのオブジェクトが意味的に等しいか」を安価に判定する手段がない → Reactは `Object.is` による浅い比較しか使えない
- 結果:props や依存配列に新規オブジェクト/関数を渡すと、毎回「変わった」とみなされる
- `memo` は最適化であって保証ではない(`react.dev/reference/react/memo`)
- 実質、利用者は「Reactの等価性モデル」を理解した上でプロップス形状を設計する義務を負う
- 根拠: react.dev/blog/2023/03/22/react-labs-what-we-have-been-working-on-march-2023, react.dev/reference/react/memo, react.dev/reference/react/useMemo

#### 5.2 Effect は「ライフサイクル」ではなく「同期プリミティブ」

- 公式の立場:Effectは**外部システムとの同期**のためにあり、ライフサイクルフックではない
- `useMount` / `useEffectOnce` 等の「lifecycle 風カスタムフック」はReactパラダイムに合わない(依存配列検査が効かず、reactivityが壊れる)
- Effect内で `setState` するのは追加レンダーを強制し、多くの場合そもそも不要
- "You Might Not Need an Effect" が列挙するアンチパターン:レンダリング用データ変換、propsからの派生、イベント用処理、連鎖Effect、初期化一回芸
- 根拠: react.dev/learn/you-might-not-need-an-effect, react.dev/reference/eslint-plugin-react-hooks/lints/set-state-in-effect, react.dev/learn/reusing-logic-with-custom-hooks

#### 5.3 状態の identity は「ツリー位置」に固定される

- Reactは「同じ位置にレンダーされる同じ型のコンポーネント」の state を保存する(`react.dev/learn/preserving-and-resetting-state`)
- state は JSXタグに紐づいているのではない、**ツリー位置(index + key)** に紐づいている
- これにより `key` は「リストの識別子」以上の意味を持つ:**subtreeの identity 宣言**であり、state リセットの公式プリミティブ
- reconciliation は O(n³) の木差分を避けるためのヒューリスティック(`legacy.reactjs.org/docs/reconciliation`):
  - 型が変われば subtree は破棄・再生成
  - key が安定であることに依存
  - Math.random() 等の不安定keyは state 破壊とパフォーマンス劣化を生む
- 根拠: react.dev/learn/preserving-and-resetting-state, legacy.reactjs.org/docs/reconciliation, legacy.reactjs.org/docs/faq-internals

#### 5.4 Reactだけでは解けない領域 — 単体ランタイムの限界

- 2025年2月、React公式は Create React App を sunset し、フレームワーク利用を推奨
- 理由:ルーティング・データ取得・コード分割・レンダリング戦略選択は React単体では解けない(解こうとすると事実上「自分のフレームワークを書くこと」になる)
- React Server Components を含めた「ビルド時・サーバー・クライアントを1本のツリーで混ぜる」設計は、ランタイムが露出するだけでは実現できない
- 利用者の意思決定:React単体でやるか、フレームワーク(Next.js, React Router等)に乗るかは、この限界点から逆算する
- 根拠: react.dev/blog/2025/02/14/sunsetting-create-react-app, react.dev/learn/build-a-react-app-from-scratch

### 6. 性質から導かれる成功パターン

1. **状態は「source of truth」を1箇所に、残りは render で派生**
   - 派生を Effect + setState で書かない。render 関数内で計算する。
2. **状態の identity は `key` で明示的に切る**
   - 「別のエンティティを表示している」なら別 key を与えて subtree をリセットする。getDerivedStateFromProps 的な同期を書かない。
3. **renderは純関数として守る** — 副作用はイベントハンドラかEffectに寄せ、中間でグローバルを書き換えない
4. **Effectは「外部世界との同期」用途にだけ使う** — UI の lifecycle を表現する手段ではない
5. **参照同一性を設計の一部として扱う** — propsに新規オブジェクトを毎回作らない、依存配列にオブジェクト/関数を入れない、必要ならプリミティブに分解する
6. **状態は"必要十分な高さ"に置く** — lift state up は「共有が必要な最小の先祖」まで。グローバル state にトランジェントなものを置かない
- 根拠: react.dev/learn/you-might-not-need-an-effect, react.dev/learn/choosing-the-state-structure, react.dev/reference/react/useMemo

### 7. アンチパターン

- Effectで props から state を派生し、`setState` で同期する
- 「初期化だけ1回」用の `useMount` / `useEffectOnce` を自作する
- render 中にグローバル可変状態を読み書きする
- key に Math.random() や index を機械的に使う(並び替えで state が壊れる)
- memo を「何にでも貼れば速い」と考える(浅い比較に props を整形していないと効かない)
- 参照同一性を考慮せず、巨大 context に巨大オブジェクトを流す
- Reactの外で DOM を直接書き換えてランタイムの world view と食い違わせる
- 根拠: react.dev/learn/you-might-not-need-an-effect, legacy.reactjs.org/docs/reconciliation, react.dev/reference/eslint-plugin-react-hooks/lints/set-state-in-effect

### 8. どこでReactが勝ち、どこで負けるか

**勝ちやすい領域**

- 状態が多く、派生が深く、UIが状態のスナップショットとして説明できる SPA / ダッシュボード / 管理画面 / 複雑フォーム
- 同じ UI ロジックを Web + Native + 別宿主 (PDF, Canvas, CLI)に持ち込みたいケース(レンダラ可換性が効く)

**負けやすい/コスト過剰な領域**

- コンテンツ主体・状態がほぼ静的なページ(仮想DOM・Hydration・参照同一性の注意コストに対してリターンが薄い)
- 1フレーム精度の物理シミュレーションやシビアなアニメーション(renderサイクルを避けて直接 DOM/Canvas を触る方が素直)
- 極端に制約されたランタイム(小さなウィジェット、ごく小さな埋め込み)で、React本体のサイズが割に合わないケース
- 根拠: react.dev/blog/2025/02/14/sunsetting-create-react-app, overreacted.io/react-as-a-ui-runtime, legacy.reactjs.org/docs/design-principles

### 9. まとめ

- Reactは「UIの複雑性を状態→ビューの純関数にすることで飼い慣らす」という**特定の賭け**をしたUIランタイム
- その賭けの対価として、利用者は「参照同一性」「ツリー位置としての state identity」「Effectは同期プリミティブである」という制約を受け入れている
- この構造を踏まえると、日々書いているパターンが「Reactの原理から導かれる自然な帰結」として読めるようになり、逆に迷ったときは「Reactはこの問題をどう定義したか?」に戻れば判断できる

## 使用した調査ファイル

- `temp/react_framework_nature/search_react_philosophy.json`
- `temp/react_framework_nature/search_react_tradeoffs.json`
- `temp/react_framework_nature/extract_react_runtime.json`
- `temp/react_framework_nature/search_extract_effect_model.json`
- `temp/react_framework_nature/search_extract_no_effect.json`
- `temp/react_framework_nature/search_extract_state_identity.json`
- `temp/react_framework_nature/search_extract_over_render.json`
