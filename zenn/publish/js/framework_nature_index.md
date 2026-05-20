---
title: "UIフレームワークを\"賭け\"として読む — React / Vue / Svelte / Solid の比較インデックス"
emoji: "🎲"
type: "tech"
topics: ["react", "vue", "svelte", "solidjs"]
published: false
---

## この記事について

React / Vue / Svelte / Solid を**同じ観点で捉え直す**4本の姉妹記事を公開しています。どれも以下の4点を順に整理する構成です。

1. ネイティブJSが詰んだ問題に対して、そのフレームワークが**何を共有し、何を別に賭けた**のか
2. 賭けと引き換えに、利用者が**新しく引き受けた制約**は何か
3. その性質から自然に導かれる**勝ち筋と地雷**
4. **向く/向かないユースケース**

本インデックス記事は、4本に共通する出発点と、横並びで比較したときに見える「賭けの違い」だけを取り出した概略マップです。各論は個別記事に譲ります。

---

## 共通の出発点 — 「状態空間の爆発」

4本とも同じ問題提起から始まります。命令的に書いていた頃のUIコードはこんな形でした。

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

相互作用が N 個あると、「ボタンが押せるはずなのに disabled のままだ」のような整合性違反のパターン数が概ね O(N²) 以上のオーダーで膨らみます。

**「状態 → ビュー」の写像を宣言的に書き、DOM 同期はフレームワークに任せる** — ここまでは4つとも共通方針です。違うのはその先で、**「どのレイヤーで、何を代償に解くか」** が分岐します。

---

## 4つの賭け — 一行サマリ

| フレームワーク | 賭けの一行 | 反応性の単位 | VDOMの扱い |
|---|---|---|---|
| **React** | 状態→ビューを**純関数**として書かせ、**ツリー全体を diff で整合性に戻す** | コンポーネント | あり(中心) |
| **Vue** | 値の変化を**値自身に監視させる**(reactive proxy)+ コンパイラが runtime を縮める | 値(ref / reactive) | あり(コンパイラに助けられた VDOM) |
| **Svelte** | フレームワークを**専用言語+コンパイラ**に寄せ、signals を**隠した実装詳細**にする | 値(裏で signal) | なし |
| **Solid** | コンポーネントは**一度だけ実行**し、signals と JSX を直接DOMに繋ぐ | 値(signal、表に出す) | なし |

「どちらが速いか」ではなく、**別の問題定義を選んでいる**という構造で読むことが、本シリーズを貫く視点です。

---

## 「持ち込んだ問題」の対応表

各記事で深掘りしている代償も、横並びで見ると同型の制約が出ていることが分かります。

| テーマ | React | Vue | Svelte | Solid |
|---|---|---|---|---|
| **反応性が抽象から漏れる箇所** | 参照同一性(`Object.is`)→ over-reactivity | `ref` の `.value` 税 / `reactive` 置換不能・destructure消失 | Proxy 境界が POJO・配列限定、クラスは `$state` フィールド | `props` の destructure / spread で反応性が切れる |
| **Effectの位置づけ** | `useEffect` は**外部世界との同期**専用、派生は render | `watch`/`watchEffect` は同期専用、派生は `computed` | `$effect` は同期専用、派生は `$derived`(side-effect 禁止) | `createEffect` は同期専用、派生は `createMemo` |
| **リスト identity の宣言** | `key` で subtree identity | `:key` で in-place patch を上書き | `{#each ... (key)}` | `<For>`(値) と `<Index>`(位置)の明示的二択 |
| **アプリ化のスコープ外注** | Next.js / React Router(意図的にスコープ外) | Vue Router / Pinia / Nuxt(段階的に連続) | SvelteKit(実質一択) | SolidStart(first-party) |

**4つすべてのフレームワークで、「派生は宣言的に / 同期だけ手続き的に」「リスト identity をユーザーが宣言する」というルールが同じ形で現れる** — これが横並びで読んだときに最も明確に浮かび上がる共通構造です。

---

## 各記事への導線

- **React版 — Reactを「UIランタイム」として捉え直す**
  Dan Abramov の "UI runtime"(UIランタイム)を軸に、ツリー位置 = state identity、`memo` は保証ではなく最適化、CRA sunset の意味、まで。

- **Vue版 — Vueを「コンパイラ付きリアクティブランタイム」として捉え直す**
  `ref` と `reactive` の二元性、Proxy identity hazard、`computed` / `watch` の役割分担、Progressive Framework の意味、まで。

- **Svelte版 — Svelteを「コンパイラ × ランタイム反応性」として捉え直す**
  `.svelte` / `.svelte.js` を方言として扱う設計、runes は関数ではなくコンパイラ指示子、`$state` の Proxy 境界、SvelteKit 寄せ、まで。

- **Solid版 — Solidを「消えるコンポーネント・残るリアクティビティ」として捉え直す**
  コンポーネントは一度だけ走る、tracking scope の境界、props destructure 禁止、`<For>` / `<Index>` の二択、まで。

---

## どこから読むと一番見通しが良いか

- **日々 React を書いている人**: React版 → Vue版 → Solid版 の順。Solid 版が「Reactと最も見た目が近いのに、最も違う賭け」を取っているため、対比が最も鮮明になります。
- **Vue / Nuxt が主戦場の人**: Vue版 → Svelte版 → React版。`reactive` の漏れと runes の指示子性、CRA sunset の意味、と上から構造を見ていけます。
- **signals 周りの最近の流れを追いたい人**: Solid版 → Svelte版 → Vue版(Vue 公式の Reactivity in Depth における signals の節)。Solid が「signalsを表に出す」、Svelte が「signalsを隠す」、Vue が「ref は signal と同じプリミティブだと公式に位置づける」と、3者で signals への態度がきれいに分かれます。

どの順番で読んでも、**「全員が同じ問題に対して別の賭けをしているだけ」** という構図に収束する構成にしています。
