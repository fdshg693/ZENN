# 機能B: メイクブロックの実行（中核）

> [実装詳細インデックス](./README.md) / [全体設計](../implementation-plan.md) / [PLAN.md](../../PLAN.md)（機能B の定義） / [makeup-vto.md](../makeup-vto.md)（API 仕様）

POC の中核。1つの **makeup ブロック（= `effects` 集合）** を指定し、**makeup-vto を1タスク実行**して結果画像を得る機能。
ここで初めて「File → Task → Poll → Result」の AI 処理が動く。機能A（[feature-a-source.md](./feature-a-source.md)）が用意した起点画像を入力に、**単発のタスク実行**を成立させるところまでが本機能の範囲。
複数ブロックの連結（一括 / チェイン）は機能C、共有は機能F が担う。本機能はそれらの**土台となる「1ブロック=1タスク」**を確実に通す。

## 目的 / スコープ

- **提供する**:
  - makeup-vto の各 `category`（skin_smooth / foundation / concealer / blush / bronzer / contour / highlighter / eyebrows / eye_shadow / eye_liner / eyelashes / lip_color / lip_liner）を指定して `effects` を組む。
  - パターン必須カテゴリ（blush 等）は**カタログ JSON の `label` を選択肢**として提示し、多色は色数ぶんの `palettes` を入力させる。
  - 起点画像（機能A の `upload` / `url` どちらの経路でも）を入力に、**1タスクで適用 → 結果画像を表示**。
- **提供しない**: 複数ブロックの連結・実行戦略（機能C）、JSON 共有（機能F）、独自パターンの作成、API にないカテゴリ・表現。
- **機能Cとの境界**: 本機能は **`effects` 1配列を1タスク**で実行するところまで。`bundle`（複数ブロックの effects 統合）/ `chain`（結果 url 受け渡し）の戦略と `RunPanel` の多段進捗表示は機能C。
  → 本機能では成功時の **結果 url を state に保持**しておく（機能C のチェイン入力の受け渡し点）。**実機確認: makeup-vto は `dst_id` を返さない**ため、チェインは結果 url を次タスクの `src_file_url` に渡す方式になる（[feature-c-routine.md](./feature-c-routine.md) 参照）。`dst_id` は skin-analysis 固有の可能性が高く未確認なので、取れたら併せて保持する（`extractResult` が両対応）。
- **共有との関係（機能F）**: `MakeupBlock.effects` の JSON が**そのまま共有の最小単位**になる（全体設計 [6-2](../implementation-plan.md#6-2-json-共有機能f)）。本機能では型をシリアライズ可能な素直な形に保つ。

## 担当ファイル

| ファイル | 役割 | レイヤ | 新規/追記 |
| --- | --- | --- | --- |
| `api/types.ts` | makeup-vto の `effects` スキーマ（category 別判別共用体）とタスク req/res 型を追記 | api | 追記 |
| `api/task.ts` | 汎用タスク実行: `start → poll → { resultUrl, dstId }`（機能C/D/E も使う共通骨格） | api | 新規 |
| `api/makeupVto.ts` | feature 名 `makeup-vto` と body 形だけを定義し、実処理は `task.ts` に委譲 | api | 新規 |
| `api/catalog.ts` | パターンカタログ JSON を取得し `label` / `thumbnail` を選択肢化（カテゴリ別キャッシュ） | api | 新規 |
| `domain/blocks.ts` | `MakeupEffect` を再利用する `MakeupBlock` 型・既定値、`Block` union へ追加、`resolveSource` | domain | 追記 |
| `state/appState.ts` | ブロック追加/更新/削除と**単発実行結果**（running/success/error・url・dst_id）の action | state | 追記 |
| `components/editors/MakeupEditor.tsx` | category 選択・色/質感/強度・パターン選択の編集 UI | components | 新規 |
| `components/RunPanel.tsx` | **単発の実行ボタン＋進捗＋結果画像**（機能C で多段化する最小版） | components | 新規 |

## データ（型）

`effects` の入れ子 JSON が本機能の最大の複雑さ。**`category` で判別する共用体**にして、カテゴリごとの必須項目をコンパイル時に固定する（取り違えを潰す）。
`MakeupEffect` は **API の仕様＝`api/types.ts` に置き**、`domain` の `MakeupBlock` がそれを再利用する（全体設計 [セクション4](../implementation-plan.md#4-ドメインモデル設計の核) の方針どおり）。

```ts
// api/types.ts （機能B: makeup-vto の effects スキーマ = 仕様の正本）

/** 1色ぶんの塗り設定。texture により「追加で必須になる項目」がある（下記コメント）。 */
export interface MakeupPalette {
  color: string;            // "#RRGGBB"
  colorIntensity?: number;  // 0–100
  texture?: 'matte' | 'satin' | 'shimmer' | 'metallic' | 'gloss' | 'holographic' | 'sheer';
  shimmerColor?: string;    // texture==='shimmer' のとき必須
  shimmerDensity?: number;  //   〃（0–100）
  glowStrength?: number;    // texture==='satin'  のとき必須
  gloss?: number;           // lip_color の gloss 系で使用
}

/** パターン名 / シェイプ名 = カタログ JSON 内の `label` 値（例 "2colors1", "plump"）。 */
export interface PatternRef { name: string }

/** effect は category で判別。スキーマは大きく 3 系統（無パターン / パターン+palettes / lip_color）。 */
export type MakeupEffect =
  // ① 無パターン系（pattern 不要・フラットなパラメータ）
  | { category: 'skin_smooth'; skinSmoothStrength?: number; skinSmoothColorIntensity?: number }
  | { category: 'foundation'; color: string; colorIntensity?: number; glowIntensity?: number; coverageIntensity?: number }
  | { category: 'concealer'; color: string; colorIntensity?: number; colorUnderEyeIntensity?: number; coverageLevel?: number }
  // ② パターン + palettes 系（pattern.name 必須・多色は palettes を色数ぶん）
  | {
      category: 'blush' | 'bronzer' | 'contour' | 'highlighter'
              | 'eye_shadow' | 'eye_liner' | 'eyelashes' | 'lip_liner' | 'eyebrows';
      pattern: PatternRef;
      palettes: MakeupPalette[];
    }
  // ③ lip_color（shape + style + morphology）
  | {
      category: 'lip_color';
      shape: PatternRef;
      style?: { type: 'full' | 'ombre' | 'twoTone' };
      morphology?: { fullness?: number; wrinkless?: number };
      palettes: MakeupPalette[];
    };

/** makeup-vto タスク開始リクエスト。src_* はどちらか一方（機能A の選択を実行時に解決）。 */
export interface MakeupTaskRequest {
  src_file_id?: string;
  src_file_url?: string;
  version: string;          // "1.0"
  effects: MakeupEffect[];
}

/** タスク開始/ステータスの共通形（feature 横断）。実機確認: ラッパは `result` ではなく `data`。 */
export interface TaskStartResponse { status?: number; data: { task_id: string } }

/** 結果1件ぶん。url / download_url のどちらか、dst_id は同階層 or data[] 内にあり得る。 */
export interface TaskResultItem {
  url?: string;
  download_url?: string;
  dst_id?: string;                                 // makeup-vto では返らない（skin-analysis 固有の可能性）
  data?: { url?: string; dst_id?: string }[];
}
export interface TaskStatusResponse {
  status?: number;
  data: {
    task_status: 'running' | 'success' | 'error';
    results?: TaskResultItem | TaskResultItem[];   // success 時。makeup-vto は単体オブジェクト { url }
    error?: string;                                // ★ task_status:'error' は HTTP 200 で返る（task.ts が整形）
    error_message?: string;
  };
}
```

```ts
// domain/blocks.ts （追記）

import type { MakeupEffect } from '../api/types';

/** 機能B: makeup-vto の effects そのもの。これが共有（機能F）の最小単位。 */
export interface MakeupBlock extends BaseBlock {
  kind: 'makeup';
  effects: MakeupEffect[];
}

// Block union を拡張（既存の SourceBlock に追加）
export type Block = SourceBlock | MakeupBlock;

/** 新しい空の makeup ブロック（既定では skin_smooth を1つ入れておくと最初の疎通が楽）。 */
export function createMakeupBlock(): MakeupBlock {
  return { id: crypto.randomUUID(), kind: 'makeup', title: 'メイク', effects: [] };
}
```

## 処理フロー

機能A と同じく「編集」と「実行」の 2 フェーズで追う。実行フェーズで初めて API（File / Task）に触れる。

1. **編集フェーズ（`MakeupEditor`）** — API は呼ばない（パターンカタログ取得を除く）。
   - category を選ぶ → カテゴリ別のフォームを出す。パターン必須なら `catalog.ts` で `label` 一覧を取得して選択肢に。
   - 色・質感（texture）・強度を入力 → `MakeupEffect` を組み立てて `UPDATE_MAKEUP` で state に反映。
   - 多色パターン（`colorNum: 2/3…`）は **色数ぶんの `palettes`** を入力させる（不足は実行前に弾く）。
2. **実行フェーズ（`RunPanel` の実行ボタン）** — ここで `domain.resolveSource` → `api.makeupVto` → `task.ts` が動く。
   - 起点画像を解決: `source.type === 'url'` → `{ src_file_url }`。`upload` → **その時点で** `uploadFile('makeup-vto', file)` を呼び `{ src_file_id }`（`file_id` は feature 単位発行のため実行時に確定。機能A の設計どおり）。
   - body を組んで `makeup-vto` タスクを開始 → ポーリング → `{ resultUrl, dstId? }`（makeup-vto は `dstId` 無し）。
   - 結果を `RUN_SUCCESS`（url ＋ あれば dst_id）で state に反映。失敗は **HTTP 200 + `data.task_status:'error'`** を `task.ts` が `describeErrorCode` で整形 → `RUN_ERROR` で表示。

```ts
// api/task.ts — 汎用タスク実行（全 AI 機能の共通骨格。各機能は feature 名と body だけ渡す）
//   実機確認を反映: ラッパは `data`、results は単体/配列の揺れ、task エラーは HTTP 200。

import { client, ApiError, describeErrorCode } from './client';
import type { TaskResultItem, TaskStartResponse, TaskStatusResponse } from './types';

export interface TaskOutput { resultUrl: string; dstId?: string }

const delay = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** results の入れ子の揺れ（単体/配列・url/download_url・dst_id は同階層 or data[]）を1か所で吸収。 */
function extractResult(results: TaskResultItem | TaskResultItem[] | undefined): TaskOutput | null {
  const item = Array.isArray(results) ? results[0] : results;
  if (!item) return null;
  const url = item.url ?? item.download_url ?? item.data?.[0]?.url;
  const dstId = item.dst_id ?? item.data?.[0]?.dst_id; // makeup-vto では undefined
  return url ? { resultUrl: url, dstId } : null;
}

/** start → poll（緩い間隔＋全体タイムアウト）→ 結果。units は success 時のみ消費。 */
export async function runTask(
  feature: string,
  body: unknown,
  { intervalMs = 1500, timeoutMs = 120_000 }: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<TaskOutput> {
  const start = await client.post<TaskStartResponse>(`/s2s/v2.0/task/${feature}`, body);
  const taskId = start.data.task_id;

  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const st = await client.get<TaskStatusResponse>(`/s2s/v2.0/task/${feature}/${taskId}`);
    const r = st.data;
    if (r.task_status === 'success') {
      const out = extractResult(r.results);
      if (!out) throw new ApiError('結果 URL が取得できませんでした。');
      return out;
    }
    if (r.task_status === 'error') {
      // タスクレベルのエラーは HTTP 200 で返る（client.ts の整形を通らない）→ ここで読めるメッセージに変換。
      const message = describeErrorCode(r.error) ?? r.error_message ?? r.error ?? 'タスクが失敗しました。';
      throw new ApiError(message, r.error);
    }
    if (Date.now() > deadline) throw new ApiError('タスクがタイムアウトしました。');
    await delay(intervalMs);
  }
}
```

```ts
// api/makeupVto.ts — makeup-vto 固有の差分だけ（実処理は task.ts に委譲）
import { runTask, type TaskOutput } from './task';
import type { MakeupEffect } from './types';

export function runMakeup(
  src: { src_file_id: string } | { src_file_url: string },
  effects: MakeupEffect[],
): Promise<TaskOutput> {
  return runTask('makeup-vto', { ...src, version: '1.0', effects });
}
```

```ts
// domain/blocks.ts — 起点画像の選択を実行用の body 断片に解決（機能C もこれを再利用）
import { uploadFile } from '../api/files';

export async function resolveSource(
  feature: string,
  source: SourceSelection,
): Promise<{ src_file_id: string } | { src_file_url: string }> {
  if (source.type === 'url') return { src_file_url: source.url };
  const fileId = await uploadFile(feature, source.file); // 実行時に発行（feature 依存）
  return { src_file_id: fileId };
}
```

## UI

- **`MakeupEditor.tsx`**: category セレクト → カテゴリ別フォーム。`texture` 選択に応じて**追加必須欄を出し分け**（shimmer→shimmerColor/Density、satin→glowStrength）。パターン必須カテゴリは `catalog.ts` の `label`（＋ `thumbnail`）から選び、`colorNum` ぶんの色入力を強制。**ロジックは持たず**、`MakeupEffect` を組んで dispatch するだけ。検証は `domain` のヘルパに置く。
  - ビルド順: まず **無パターン（skin_smooth / foundation）** だけで疎通を取り、その後パターン必須カテゴリを `catalog.ts` 経由で拡充（全体設計 [セクション8](../implementation-plan.md#8-実装ステップ推奨ビルド順) ステップ3→7）。
- **`RunPanel.tsx`**: 「このブロックを実行」ボタン → `running` 中はスピナー、`success` で結果画像、`error` で整形済みメッセージ。**単発**の最小版で、機能C が複数ステップの進捗表示へ拡張する。
- `App.tsx` に `MakeupEditor` と `RunPanel` を追加し、機能A の `SourcePanel` の下に並べる。

## つまりどころ

| 落とし穴 | 吸収する場所 |
| --- | --- |
| **`effects` 入れ子スキーマの取り違え**（category ごとに必須項目が違う） | `api/types.ts` の `category` 判別共用体で型固定。`MakeupEditor` は型に沿ってフォームを出す。 |
| **パターン必須カテゴリ**（blush 等は `pattern.name` 必須） | `catalog.ts` がカタログ JSON の `label` を選択肢化。未選択のまま実行できない UI に。 |
| **多色と palettes 数の不一致**（`colorNum:2` なのに palettes 1個 → API エラー） | `MakeupEditor` が `colorNum` ぶんの色入力を強制。`domain` 側で実行前に検証して弾く。 |
| **texture 依存の必須項目漏れ**（shimmer/satin で追加欄が要る） | `MakeupEditor` が texture 選択で必須欄を出し分け、未入力は実行前に弾く。 |
| **`file_id` の feature 依存**（最初に実行する機能で発行先が変わる） | `resolveSource('makeup-vto', …)` が**実行時に**発行（機能A の設計を実体化）。編集時は `File` 実体のみ保持。 |
| **ポーリング**（実行時間が不定） | `task.ts` の共通ループ（緩い間隔＋全体タイムアウト）。機能ごとに再実装しない。 |
| **units 消費**（成功時のみ） | 失敗・タイムアウト・ポーリング中は非消費。`client.ts` がエラーを整形して投げるので原因判別が速い。 |
| **顔系エラー**（`error_no_face` / `error_large_face_angle` 等） | 実機確認: **HTTP 200 + `data.task_status:'error'`** で返るため client.ts の整形を通らない → `task.ts` が `describeErrorCode` で整形し `RunPanel` に表示（機能A が導線だけ用意した部分の実体化）。 |
| **CORS（カタログ JSON / 結果画像）** | API は dev proxy 経由。`plugins-media.makeupar.com` のカタログ JSON はホストが別なので、CORS で詰まれば `vite.config.ts` の proxy 対象に追加（全体設計 [セクション7](../implementation-plan.md#7-つまりどころと対策先回りで潰す)）。 |
| **レスポンスの入れ子の揺れ** | 実機確認で **ラッパは `data`（`result` ではない）／makeup-vto の `results` は単体オブジェクト `{ url }`** と確定。`task.ts` の `extractResult` が単体/配列・`url`/`download_url`・`dst_id` の揺れを吸収し、型（`TaskStatusResponse`）を正本として固定。 |

## 完了条件

- **無パターン疎通**: `skin_smooth` ＋ `foundation` だけの makeup ブロックを作り、機能A の起点画像（**upload / url 両経路**）で makeup-vto を**1タスク実行 → 結果画像が表示**される。
  → これが全体設計 [セクション8](../implementation-plan.md#8-実装ステップ推奨ビルド順) のステップ2（API 疎通の山）＋ステップ3後半に対応する、本機能の最小の「動いた」基準。
- **パターン適用**: パターン必須カテゴリ（例 `blush`）で `catalog.ts` の `label` を選び、`colorNum` ぶんの `palettes` を入れて適用できる。
- **エラー導線**: 失敗時（顔なし・角度過大等）に**読めるメッセージ**が出て、**units が消費されない**。
- **機能C への受け渡し**: 成功時に **結果 url を state に保持**し、**次タスクの `src_file_url` に渡せる状態**になっている（実機確認: makeup-vto は `dst_id` を返さないため url が受け渡し点。[feature-c-routine.md](./feature-c-routine.md) のチェインの起点）。`dst_id` を返す機能では `extractResult` がそれも拾う。
