# 機能E: 肌診断ブロック（補助）

> [実装詳細インデックス](./README.md) / [全体設計](../implementation-plan.md) / [PLAN.md](../../PLAN.md)（機能E の定義） / [feature-b-makeup.md](./feature-b-makeup.md)（単発タスク実行の土台） / [feature-c-routine.md](./feature-c-routine.md)（チェイン実行の土台） / [feature-d-look.md](./feature-d-look.md)（複数種別を1チェインで回す骨格）

肌状態を AI でスコア化し、**ルーティンの起点（Before 診断）／仕上げ（After 診断）**として見せる補助ブロック。
これまでの機能B（makeup）・機能D（look）が「**画像 → 画像**（結果 url 1枚）」の**変換ブロック**だったのに対し、機能E は「**画像 → スコア＋マスク**」を返す**測定ブロック**である点が決定的に違う。
API の骨格（File → Task → Poll）は同じだが、**成功レスポンスが結果 url 1枚ではない**ため、機能B〜D が前提にしてきた「結果は `resultUrl` 1本」という型・状態・UI・チェイン受け渡しのすべてに、肌診断専用の分岐を1つずつ足すのが本機能の主な仕事になる。

機能Dが「`featureOf` による種別振り分けで複数 AI ブロックを1チェインで回す骨格」を確立済みなので、**機能E はその骨格に種別を1つ足す**形になる。ただし「出力が画像ではない」ぶん、機能D（look=makeup と同形）よりは触る面が広い。

## 公式仕様から確定した事実（このプランの前提）

[docs/skin-analysis.md](../skin-analysis.md) とリファレンス（<https://docs.perfectcorp.com/reference/ai_skin_analysis>）で skin-analysis の入出力を確認した。機能D との最大の差は **③成功レスポンスの形**。

1. **エンドポイントは feature 名 `skin-analysis`**: `POST /s2s/v2.0/task/skin-analysis` → `GET .../skin-analysis/{task_id}`。File API も `POST /s2s/v2.0/file/skin-analysis`。ラッパは機能B〜D と同じ **`data`**。**既存の `client` / `files.uploadFile` / ポーリングはそのまま使える**（v2.1 もパス違いだけ）。
2. **適用 body は `dst_actions` ＋ 起点画像**: `POST .../task/skin-analysis` に `{ src_file_url | src_file_id, dst_actions: string[], format: 'json', miniserver_args?: { enable_mask_overlay } }`。`effects`（機能B）でも `template_id`（機能D）でもない第3の body 形。
3. **成功レスポンスは「結果 url 1枚」ではない**（★ここが機能Eの核）。`data.results.output[]` に**項目ごとの** `type` / `ui_score` / `raw_score` / `mask_urls`、加えて総合点 `all.score`・推定肌年齢 `skin_age`。
   ```json
   { "status": 200, "data": { "task_status": "success",
     "results": { "output": [ { "type": "wrinkle", "ui_score": 60, "raw_score": 36.09, "mask_urls": ["https://…png"] } ],
                  "all": { "score": 75.76 }, "skin_age": 37 } } }
   ```
   → **既存 [api/task.ts](../../src/api/task.ts) の `extractResult` はそのままでは通らない**（`url` が無く `結果 URL が取得できませんでした` を投げる）。機能Eは **start→poll の中核（`pollTask`）を切り出して再利用しつつ、肌診断専用の取り出し（`extractSkin`）を別に持つ**。
4. **SD と HD は混在不可**（混ぜると `InvalidParameters`）。`dst_actions` は SD 系（`wrinkle`/`pore`/…）か HD 系（`hd_*`）の**どちらか一方に統一**。→ `SkinBlock.resolution: 'sd' | 'hd'` で一方に固定し、UI で混在不可能にする（全体設計 [7](../implementation-plan.md#7-つまりどころと対策先回りで潰す) の「SD/HD 混在エラー」対策）。
5. **タスクレベルのエラーは HTTP 200**（`data.task_status:"error"` + `data.error`）。肌診断は撮影条件がシビアで、makeup/look に無い**固有コード**が出る（`error_src_face_too_small`・`error_lighting_dark`・`error_src_face_out_of_bound` 等）→ [api/client.ts](../../src/api/client.ts) の `describeErrorCode` に**未登録なら追加**する。
6. **`dst_id` を返すかは未確認**（メモリ `youcam-api-response-shapes`: dst_id は skin-analysis 固有の見立て）。ただし本機能のチェインは**画像を変換しない**ため `dst_id` 受け渡しに依存しない（後述「測定タップ」）。返れば将来の拡張余地として記録に留める。
7. **結果保持 24時間 / ポーリング中は units 非消費 / 課金は success 時のみ**（機能B〜D と同じ）。

## 目的 / スコープ

- **提供する**:
  - **診断項目（`dst_actions`）の選択**: SD / HD のどちらかに固定し、その系統の項目をチェックボックスで選ばせる（混在は UI で不可能）。
  - **単発診断**: skin ブロック単体を起点画像（**upload / url 両経路**）で実行 → **項目別 `ui_score`・総合点・推定肌年齢**を表示（マスク画像があればサムネ表示）。
  - **ルーティンへの組み込み**: skin ブロックを機能C/D の**チェインに混在**させる。**Before 診断**（skin → makeup）と **After 診断**（makeup → skin）の双方。
- **提供しない**: 医療的な診断・処方（PLAN 通り）。SD と HD の混在（API 仕様上不可）。skin ブロックの **bundle 統合**（effects ではないため統合不可。機能D と同じ安全弁で chain に切替）。マスク PNG の高度な合成エディタ（重ね表示まで。自動リサイズ・整形はしない＝撮影条件は API の `error_*` に委ねる）。
- **機能B〜Dとの境界**: `client` / `files.uploadFile` / `resolveSource` / `runs`（blockId→RunStatus）/ `RunPanel` の単発実行シェル / `RoutinePanel` の方式トグル・実行起動 / `runRoutine`・`runChain` の骨格は**そのまま再利用**する。機能Eが足すのは「**出力が画像ではない**ことに伴う差分」——①start→poll 中核の切り出しと肌診断専用の取り出し、②画像 url 前提だった `RunOutput` / `RunStatus` の一般化、③測定タップとしてのチェイン挙動、④診断結果の表示 UI。

## 担当ファイル

| ファイル | 役割 | レイヤ | 新規/追記 |
| --- | --- | --- | --- |
| `api/task.ts` | **中核改修**: start→poll を `pollTask`（成功時の生 `data` を返す）に切り出し、`runTask`（=`pollTask`+`extractResult`）はその上に再構成（**makeup/look は無改変で通る**）。`RunOutput` 判別共用体を導入 | api | 追記 |
| `api/types.ts` | `SkinScore` / `SkinResult` / `SkinTaskRequest` / 肌診断ステータスの型を追記。SD・HD の `dst_actions` 定数 | api | 追記 |
| `api/skinAnalysis.ts` | feature 名 `skin-analysis`。`runSkin`（`pollTask`+`extractSkin`）。結果取り出し（`output[]` / `score_info` 形の揺れ吸収）はここ | api | 新規 |
| `domain/blocks.ts` | `SkinBlock` 型・`createSkinBlock`・`validateSkin`、SD/HD の `dst_actions` カタログ（ラベル付き）、`Block` / `AiBlock` union に追加 | domain | 追記 |
| `domain/routine.ts` | `featureOf`/`runBlock`/`validateBlock` に skin を足す。`runBlock` の戻りを `RunOutput` 化。**`runChain` を「作業画像は変換ブロックのみ進める／無ければ起点を当該 feature で解決」へ改修**（skin=測定タップ） | domain | 追記 |
| `state/appState.ts` | `ADD_SKIN` / `UPDATE_SKIN`、`RUN_SUCCESS` を `RunOutput` 一般化（`RunStatus.success` が画像 or 診断）。`selectAiBlocks` に skin を含める | state | 追記 |
| `components/editors/SkinEditor.tsx` | SD/HD トグル ＋ 当該系統の項目チェックで `UPDATE_SKIN`。表示と dispatch のみ（カタログは domain） | components | 新規 |
| `components/SkinResultView.tsx` | `SkinResult` を描画（総合点・肌年齢・項目別 `ui_score` バー・マスクサムネ）。純表示 | components | 新規 |
| `components/RunPanel.tsx` | success の描画を `output.kind` で分岐（`image`→既存 `<img>` / `skin`→`SkinResultView`）。検証・実行導線は種別非依存のまま | components | 追記 |
| `components/RoutinePanel.tsx` | `onStepSuccess` を `RunOutput` で受ける。注記（skin は bundle 不可で chain 化）。`selectAiBlocks` 化済みなので主たる改修なし | components | 追記 |
| `App.tsx` | `kind` で editor を出し分け（skin→`SkinEditor`）＋「＋ 肌診断を追加」ボタン（`ADD_SKIN`） | components | 追記 |

## データ（型）

機能D が「結果系の型を増やさない」で済んだのに対し、機能E は**出力が画像ではない**ので、結果系の型を新設する。鍵は「画像結果（makeup/look）」と「診断結果（skin）」を**判別共用体 `RunOutput`** で1つに束ね、`kind` で分岐させること（全体設計 [4](../implementation-plan.md#4-ドメインモデル設計の核) の方針＝`kind` を見れば型が確定）。

```ts
// api/task.ts （追記）— 実行結果を「画像」と「診断」の判別共用体に一般化する。
//   makeup/look は image、skin は skin。RunPanel / RunStatus / runChain がこの kind で分岐する。
export type RunOutput =
  | { kind: 'image'; resultUrl: string; dstId?: string } // 機能B/D: 変換ブロックの結果画像
  | { kind: 'skin'; skin: SkinResult };                  // 機能E: 測定ブロックの診断スコア

// 既存 TaskOutput（{ resultUrl, dstId? }）は runTask の戻りとして残し、
//   RunPanel/RoutinePanel 側で { kind:'image', ...out } に包んで RunOutput へ持ち上げる。
```

```ts
// api/types.ts （機能E: skin-analysis の型 = 仕様の正本）

/** 診断1項目ぶんのスコア。type は dst_actions の値（'wrinkle' / 'hd_pore' 等）。 */
export interface SkinScore {
  type: string;
  uiScore: number;       // ui_score（表示用に補正・高め）
  rawScore?: number;     // raw_score（1–100 実スコア）
  maskUrls?: string[];   // mask_urls（検出箇所の重ね合わせ PNG。任意）
}

/** 肌診断の結果（=画像 url ではなくスコア群）。これが機能E の「結果」。 */
export interface SkinResult {
  scores: SkinScore[];   // 項目別（results.output[] 由来）
  overall?: number;      // all.score（総合点）
  skinAge?: number;      // skin_age（推定肌年齢）
}

/** skin-analysis タスク開始リクエスト。src_* はどちらか一方。SD/HD は dst_actions で一系統に統一。 */
export interface SkinTaskRequest {
  src_file_id?: string;
  src_file_url?: string;
  dst_actions: string[];
  format?: 'json';
  miniserver_args?: { enable_mask_overlay?: boolean };
}

/** skin の成功ペイロード（results が output[] 形）。score_info 形（keyed map）の揺れは extractSkin で吸収。 */
export interface SkinStatusData {
  task_status: 'running' | 'success' | 'error';
  results?: {
    output?: { type: string; ui_score: number; raw_score?: number; mask_urls?: string[] }[];
    all?: { score?: number };
    skin_age?: number;
  };
  error?: string;
  error_message?: string;
}
```

```ts
// domain/blocks.ts （追記）— SkinBlock と dst_actions カタログ（SD/HD は別系統）。

/** 機能E: 肌診断。SD/HD はどちらか一方に統一（resolution で固定し UI で混在不可能に）。
 *  これが共有（機能F）の最小単位（resolution + dstActions の素直な JSON）。 */
export interface SkinBlock extends BaseBlock {
  kind: 'skin';
  resolution: 'sd' | 'hd';
  dstActions: string[]; // 選択中の診断項目（resolution の系統に属するもののみ）
}

// Block / AiBlock union を拡張（既存に追加）。
export type Block = SourceBlock | MakeupBlock | LookBlock | SkinBlock;
export type AiBlock = MakeupBlock | LookBlock | SkinBlock;

/** SD/HD 各系統の選択肢（value=dst_actions 値, label=表示名）。UI のチェックはここから生成。 */
export const SKIN_ACTIONS: Record<'sd' | 'hd', { value: string; label: string }[]> = {
  sd: [ { value: 'wrinkle', label: 'シワ' }, { value: 'pore', label: '毛穴' }, /* texture/acne/oiliness/... */ ],
  hd: [ { value: 'hd_wrinkle', label: 'シワ(HD)' }, { value: 'hd_pore', label: '毛穴(HD)' }, /* ... */ ],
};

/** 既定の skin ブロック（SD・基本4項目）。最初の「動いた」を取りやすい無難な初期値。 */
export function createSkinBlock(): SkinBlock {
  return { id: crypto.randomUUID(), kind: 'skin', title: '肌診断',
           resolution: 'sd', dstActions: ['wrinkle', 'pore', 'texture', 'acne'] };
}

/** skin ブロックの実行前検証（空・系統不一致を API に投げる前に弾く＝units と撮影リトライを無駄にしない）。 */
export function validateSkin(block: SkinBlock): string | null {
  if (block.dstActions.length === 0) return '診断する項目を1つ以上選んでください。';
  const allowed = new Set(SKIN_ACTIONS[block.resolution].map((a) => a.value));
  if (!block.dstActions.every((a) => allowed.has(a))) {
    return 'SD と HD の項目は混在できません。どちらか一方に統一してください。';
  }
  return null;
}
```

```ts
// state/appState.ts （追記）— RUN_SUCCESS を RunOutput で一般化（画像 or 診断）。
export type RunStatus =
  | { phase: 'idle' }
  | { phase: 'running' }
  | { phase: 'success'; output: RunOutput } // ← 旧 { url, dstId } を RunOutput に一般化
  | { phase: 'error'; message: string };

export type Action =
  // …既存（… ADD|UPDATE_LOOK / REMOVE_BLOCK / RUN_START|ERROR / SET_EXECUTION / RESET_RUNS）…
  | { type: 'ADD_SKIN' }
  | { type: 'UPDATE_SKIN'; id: string; resolution: 'sd' | 'hd'; dstActions: string[] }
  | { type: 'RUN_SUCCESS'; id: string; output: RunOutput }; // ← 旧 { url, dstId } を置換

// UPDATE_SKIN は UPDATE_MAKEUP / UPDATE_LOOK と同様、当該ブロックの run を idle に戻す（編集で結果が陳腐化するため）。
// selectAiBlocks は kind ∈ {makeup, look, skin} を取り出すよう拡張する。
```

> **`RUN_SUCCESS` の一般化は機能Eで一度だけ払うコスト**。`{ url, dstId }` を直に持っていた箇所（reducer・`RunPanel` の `<img src={run.url}>`・`RoutinePanel` の `onStepSuccess`）を `output: RunOutput` 経由に揃える。makeup/look は `{ kind:'image', ...TaskOutput }` に包むだけで、表示分岐が増えるのは success の描画のみ。

## 処理フロー

機能B〜D と同じ「編集」「実行」の2フェーズ。skin 固有なのは**実行時の取り出し**（url ではなくスコア）と、**チェインでの振る舞い（測定タップ）**の2点。

1. **編集フェーズ（`SkinEditor`）** — SD/HD トグル → 当該系統の項目チェック → `UPDATE_SKIN` で `{ resolution, dstActions }` を state へ。系統を切り替えたら選択は当該系統に作り直す（混在を作れない）。
2. **実行フェーズ** — 単発（`RunPanel`）でもルーティン（`runChain`）でも、skin ブロックは起点を `resolveSource('skin-analysis', source)`（先頭の場合）→ `runSkin(src, resolution, dstActions)` → `pollTask` が start→poll→生 `data` を返し、`extractSkin` が `SkinResult` に整形 → `{ kind:'skin', skin }` を `RUN_SUCCESS`。

```ts
// api/task.ts — 中核改修: start→poll を pollTask に切り出す。runTask はその上に再構成（makeup/look は無改変）。
//   ★ 肌診断は成功ペイロードが url ではないので、ポーリングだけ共通化し、取り出しは feature 側に委ねる。

/** start → poll し、success 時の生 data を返す（取り出しは呼び側）。error/timeout は従来どおり投げる。 */
export async function pollTask<T extends { task_status: string; error?: string; error_message?: string }>(
  feature: string, body: unknown,
  { intervalMs = 1500, timeoutMs = 120_000 }: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<T> {
  const start = await client.post<TaskStartResponse>(`/s2s/v2.0/task/${feature}`, body);
  const taskId = start.data.task_id;
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const st = await client.get<{ data: T }>(`/s2s/v2.0/task/${feature}/${taskId}`);
    const r = st.data;
    if (r.task_status === 'success') return r;
    if (r.task_status === 'error') {
      const message = describeErrorCode(r.error) ?? r.error_message ?? r.error ?? 'タスクが失敗しました。';
      throw new ApiError(message, r.error);
    }
    if (Date.now() > deadline) throw new ApiError('タスクがタイムアウトしました。');
    await delay(intervalMs);
  }
}

/** 機能B/D: 結果 url を返す従来の runTask は pollTask + extractResult に再構成（戻り値・挙動は不変）。 */
export async function runTask(feature: string, body: unknown, opts = {}): Promise<TaskOutput> {
  const r = await pollTask<TaskStatusResponse['data']>(feature, body, opts);
  const out = extractResult(r.results);
  if (!out) throw new ApiError('結果 URL が取得できませんでした。');
  return out;
}
```

```ts
// api/skinAnalysis.ts — 機能E: skin-analysis 固有の差分（取り出しを含む）。
import { pollTask } from './task';
import type { SkinResult, SkinStatusData } from './types';

/** 肌診断を1タスク実行し、SkinResult（スコア群）を返す。dst_actions は SD/HD 一系統に統一済み前提（validateSkin）。 */
export async function runSkin(
  src: { src_file_id: string } | { src_file_url: string },
  resolution: 'sd' | 'hd',
  dstActions: string[],
): Promise<SkinResult> {
  const data = await pollTask<SkinStatusData>('skin-analysis', { ...src, dst_actions: dstActions, format: 'json' });
  return extractSkin(data);
}

/** results の形の揺れ（output[] 形 / score_info の keyed map 形）を1か所で吸収する。 */
function extractSkin(data: SkinStatusData): SkinResult {
  const r = data.results ?? {};
  const scores = (r.output ?? []).map((o) => ({
    type: o.type, uiScore: o.ui_score, rawScore: o.raw_score, maskUrls: o.mask_urls,
  }));
  return { scores, overall: r.all?.score, skinAge: r.skin_age };
}
```

```ts
// domain/routine.ts — skin を足す（featureOf/runBlock/validateBlock）＋ runChain を測定タップ対応に改修。
export function featureOf(block: AiBlock): string {
  return block.kind === 'look' ? 'look-vto' : block.kind === 'skin' ? 'skin-analysis' : 'makeup-vto';
}

/** 1ブロックを実行し RunOutput を返す（画像 or 診断）。 */
export async function runBlock(block: AiBlock, src: SrcRef): Promise<RunOutput> {
  if (block.kind === 'skin') return { kind: 'skin', skin: await runSkin(src, block.resolution, block.dstActions) };
  const out = block.kind === 'look' ? await runLook(src, block.templateId) : await runMakeup(src, block.effects);
  return { kind: 'image', ...out };
}

export function validateBlock(block: AiBlock): string | null {
  return block.kind === 'skin' ? validateSkin(block)
       : block.kind === 'look' ? validateLook(block)
       : validateEffects(block.effects);
}

/** chain: ★ skin は測定タップ＝作業画像を進めない。
 *  入力は「直近の変換結果 url があればそれ／無ければ起点を“このブロックの feature”で解決」。 */
async function runChain(blocks: AiBlock[], source: SourceSelection, cb: RoutineProgress) {
  let workUrl: string | null = null; // 直近の変換（image）結果。skin では更新しない。
  for (const block of blocks) {
    cb.onStepStart(block.id);
    try {
      const src: SrcRef = workUrl
        ? { src_file_url: workUrl }                     // 前段の変換結果（feature 非依存の url）
        : await resolveSource(featureOf(block), source); // まだ変換が無い → 起点を当該 feature で解決
      const out = await runBlock(block, src);
      cb.onStepSuccess(block.id, out);
      if (out.kind === 'image') workUrl = out.resultUrl; // 変換ブロックのみ作業画像を進める
    } catch (e) {
      cb.onStepError(block.id, e instanceof Error ? e.message : String(e));
      return; // 直列なので以降は中断
    }
  }
}
```

> **`runChain` 改修は makeup/look 既存チェインと完全後方互換**。makeup/look は必ず `kind:'image'` なので毎ステップ `workUrl` を進める＝従来の「前結果 url を次へ」と同一。変わるのは「先頭解決を `i===0` 固定でなく `workUrl` 未確定時に行う」点だけで、これが**先頭 skin（upload）→ 次 makeup** で各々の feature の `file_id` を正しく発行する鍵になる（下記つまりどころ）。`runBundle` は makeup 専用のまま（安全弁が全 makeup のときしか呼ばない）。

## UI

- **`SkinEditor.tsx`（新規）**: SD/HD のトグル（ラジオ）＋ 選択中系統の項目チェックボックス（`SKIN_ACTIONS[resolution]` から生成）。チェック変更・系統切替で `UPDATE_SKIN` を dispatch（系統を変えたら選択は当該系統で作り直す＝混在不可）。**ロジックは持たず**表示と dispatch のみ（カタログ・検証は domain）。
- **`SkinResultView.tsx`（新規）**: `SkinResult` を描画。総合点 `overall`・推定肌年齢 `skinAge` を見出しに、項目別は `ui_score` の横バー（`SkinScore.type` のラベルは `SKIN_ACTIONS` の label を引く）。`maskUrls` があればサムネを `loading="lazy"` で並べる（重ね合わせは任意・POC は並置で十分）。純表示。
- **`RunPanel.tsx`（分岐追加）**: success の描画を `run.output.kind` で出し分ける——`image` は既存の `<img src={output.resultUrl}>`、`skin` は `<SkinResultView result={output.skin} />`。実行ボタン・前提チェック・`validateBlock` 経由の検証は**種別非依存のまま**（skin も「このブロックを実行」で同じ導線）。caption は skin のとき「診断結果（units を消費しました）」。
- **`RoutinePanel.tsx`（追記）**: `onStepSuccess(id, out)` を `RUN_SUCCESS` の `output` にそのまま渡す（`url`/`dstId` の分解をやめる）。注記に「肌診断は effects 統合できないため bundle でも chain 実行」を追記。`selectAiBlocks` 化済みのため running 判定・前提チェックは skin を含めて自動で効く。
- **`App.tsx`（追記）**: `kind` 分岐に skin→`SkinEditor` を足し、「＋ 肌診断を追加」（`ADD_SKIN`）ボタンを並べる。

## つまりどころ

| 落とし穴 | 吸収する場所 |
| --- | --- |
| **成功レスポンスが結果 url 1枚ではない**（output[] のスコア群） | `task.ts` を `pollTask`（生 data）＋取り出しに分離。skin は `extractSkin`、makeup/look は `extractResult`。`RunOutput` 判別共用体で「画像／診断」を1型に束ねる。 |
| **skin は画像を変換しない**（測定タップ。後続に渡す作業画像を作らない） | `runChain` は `out.kind==='image'` のときだけ `workUrl` を進める。skin ステップは作業画像を据え置き → **Before 診断**（skin→makeup は元画像に化粧）が成立。 |
| **`file_id` は feature スコープ**（先頭 skin が upload だと skin-analysis の file_id を発行。次 makeup には使えない） | `runChain` を「`workUrl` 未確定なら**そのブロックの feature** で起点を解決」へ。先頭 skin は skin-analysis で、次 makeup は makeup-vto で各々 `file_id` を発行（url 起点なら feature 非依存で二重アップロード無し）。 |
| **SD/HD 混在で `InvalidParameters`** | `SkinBlock.resolution` で一系統に固定。`SkinEditor` が当該系統の項目しか出さない＝混在不可能。`validateSkin` が裏当て（系統不一致・空を実行前に弾く）。 |
| **肌診断固有のエラーコード**（`error_src_face_too_small` / `error_lighting_dark` / `error_src_face_out_of_bound`） | HTTP 200 で返る → `pollTask` が `describeErrorCode` で整形。**未登録コードは [client.ts](../../src/api/client.ts) のカタログに追加**（読めるメッセージ＝撮り直しの指示に直結）。 |
| **`dst_id` 依存の誘惑**（docs に「dst_id で次の VTO に渡せる」） | 本機能のチェインは画像を**変換しない**＝測定タップなので dst_id 受け渡しに依存しない。返れば記録に留めるのみ（着手前に確認）。 |
| **results の形の揺れ**（`output[]` 形 / `score_info.json` の keyed map 形 / ZIP） | `extractSkin` が1か所で吸収（`output[]` を第一に、keyed map はフォールバック）。ZIP（`enable_mask_overlay`/`format` 次第）は POC では `format:'json'` 固定で回避。 |
| **マスク PNG が重い／多い**（項目数ぶん） | `SkinResultView` でサムネを `loading="lazy"`。重ね合成はせず並置（POC スコープ）。`enable_mask_overlay` は既定（送らない＝項目別）に倒す。 |
| **skin は bundle 統合できない** | 機能D と同じ安全弁: `ai.every(kind==='makeup')` のときだけ bundle、skin/look が混ざれば自動 chain（全体設計 [6-1](../implementation-plan.md#6-1-ルーティン実行機能c)）。skin が混ざると `every` が false になり自動で chain。 |
| **撮影条件がシビア**（顔幅 60% 超・正面・明るさ） | 自動補正はしない（PLAN スコープ外）。`error_*` を読めるメッセージで出して撮り直しを促す。`validateSourceFile`（形式・サイズ）は既存を流用。 |

## 完了条件

- **編集**: `SkinEditor` で SD/HD を選び、その系統の項目をチェックできる。SD と HD を**同時に選べない**（混在が UI 上不可能）。
- **単発診断**: skin ブロック単体を起点画像（**upload / url 両経路**）で実行 → **項目別 `ui_score`・総合点・推定肌年齢**が表示される（マスクがあればサムネも）。
- **チェイン（Before 診断）**: skin → makeup を `chain` で実行 → skin のスコアが出つつ、makeup は**元の顔**に適用される（skin が作業画像を進めない＝測定タップ）。
- **チェイン（After 診断）**: makeup → skin を `chain` で実行 → skin が**化粧後の結果 url**を測定してスコアを出す。
- **bundle 安全弁**: skin を含む並びで `bundle` を選んでも**自動的に chain** で実行される。
- **エラー導線**: SD/HD 混在・項目未選択は実行前に弾かれ、顔小さすぎ・暗い等は**読めるメッセージ**が出る。**units は success ステップぶんのみ**消費。
- **機能F への受け渡し**: `SkinBlock` が `{ kind:'skin', resolution, dstActions }` という **JSON 化可能な素直な形**に保たれている（共有の最小単位）。

## 着手前に確認したいこと（未検証 → 実装中に実機で潰す）

- [ ] **skin-analysis 成功レスポンスの実形**: `data.results.output[]` か、`score_info.json` の keyed map か、ZIP か（`extractSkin` の吸収範囲を確定）。
- [ ] **`dst_id` を返すか**・返すなら何の画像を指すか（メモリ `youcam-api-response-shapes` の見立ての検証。返っても POC は使わない）。
- [ ] **チェインの実挙動**: ①先頭 skin（upload）→ makeup で各 feature の file_id 発行＋元画像への化粧が成立するか、② makeup → skin で結果 S3 url をサーバ間取得して測定できるか（機能C/D の未確認項目と同根）。
- [ ] **追加すべきエラーコード**: `error_src_face_too_small` 等が `describeErrorCode` に無ければ文言を追加。
- [ ] **v2.0 と v2.1 のどちらを使うか**（v2.1 は入力解像度 1920→4096。POC は v2.0 既定で十分か）。
- [ ] **`enable_mask_overlay` / `format` の既定挙動**（マスクを `mask_urls` で受けられるか、ZIP 強制か）。
- [ ] **units の課金粒度**（1タスク=1消費か、`dst_actions` 数に比例か）。

## 再利用できる既存資産（機能B〜D で実装済み）

| 資産 | 場所 | 機能E での使い方 |
| --- | --- | --- |
| **start→poll の中核**（success/error/timeout・HTTP 200 エラー整形） | [api/task.ts](../../src/api/task.ts) | `pollTask` に切り出して **skin と makeup/look で共有**（取り出しだけ feature 側）。 |
| `client`（認証・整形・429 リトライ）/ `describeErrorCode` | [api/client.ts](../../src/api/client.ts) | 開始・ポーリングとも `client.get/post`。skin 固有コードはカタログに追加。 |
| `uploadFile(feature, file)` | [api/files.ts](../../src/api/files.ts) | upload 経路で `skin-analysis` の file_id を発行。 |
| `resolveSource(feature, source)` | [domain/blocks.ts](../../src/domain/blocks.ts) | chain 先頭/未変換時の起点解決を `featureOf` で `skin-analysis` にも対応。 |
| `runRoutine` / `RoutineProgress` / bundle・chain 戦略 / 安全弁 | [domain/routine.ts](../../src/domain/routine.ts) | skin を `featureOf`/`runBlock`/`validateBlock` に1つ足す。`runChain` を測定タップ対応へ（後方互換）。 |
| `runs`（blockId→RunStatus）・`RUN_*` / `SET_EXECUTION` / `RESET_RUNS` | [state/appState.ts](../../src/state/appState.ts) | `RUN_SUCCESS` を `RunOutput` 一般化。per-block 進捗・結果保持は同じキー空間。 |
| `RunPanel`（単発実行シェル・前提チェック・進捗） | [components/RunPanel.tsx](../../src/components/RunPanel.tsx) | 実行導線は種別非依存のまま。success の描画だけ `output.kind` で分岐。 |
| `RoutinePanel`（方式トグル・実行起動・running 判定） | [components/RoutinePanel.tsx](../../src/components/RoutinePanel.tsx) | `selectAiBlocks` 化済みで skin を自動で含む。`onStepSuccess` を `RunOutput` で受ける。 |
| `LookEditor` のグルーピング／カード選択 UI の作法 | [components/editors/LookEditor.tsx](../../src/components/editors/LookEditor.tsx) | `SkinEditor`（系統トグル＋チェック）・`SkinResultView`（バー＋サムネ）の見た目の下敷き。 |
