# 機能C: ブロックの連結（ルーティンの実行）

> [実装詳細インデックス](./README.md) / [全体設計](../implementation-plan.md) / [PLAN.md](../../PLAN.md)（機能C の定義） / [feature-b-makeup.md](./feature-b-makeup.md)（前提となる単発実行）

複数ブロックを順に実行し、一連の手順（ルーティン）として結果を得る機能。機能B の「1ブロック=1タスク」を土台に、
**一括方式（bundle）／チェイン方式（chain）** の2戦略でブロック列を実行する（全体設計 [6-1](../implementation-plan.md#6-1-ルーティン実行機能c)）。
オーケストレーションは `domain/routine.ts` に集約し、各ステップの進捗は機能B が用意した `runs`（blockId→RunStatus）へ逐次反映する。

## 機能B から判明した事実（このプランの前提）

機能B の疎通で API の実レスポンスを確認した結果、プラン（および全体設計）の当初前提と食い違う点が判明した。
機能C はこれらを織り込んで設計する（メモリ: `youcam-api-response-shapes`）。

1. **レスポンスのラッパは `result` ではなく `data`**（全レスポンス共通）。File API: `data.files[]`、Task 開始: `data.task_id`、ポーリング: `data.task_status`、成功: `data.results`。すでに [api/types.ts](../../src/api/types.ts) / [api/task.ts](../../src/api/task.ts) で吸収済み。
2. **makeup-vto は `dst_id` を返さない。** 成功時 `data.results` は単体オブジェクト `{ url }` のみ。
   ```json
   { "status": 200, "data": { "error": null, "results": { "url": "https://…s3…/….jpg?X-Amz-Expires=7200&…" }, "task_status": "success" } }
   ```
   → **チェインを「`dst_id` 受け渡し」で組む前提が makeup では崩れる。** `dst_id` は Skin Analysis（機能E）固有の可能性が高いが**未確認**。
3. **タスクレベルのエラーは HTTP 200 で返る**（本文 `data.task_status:"error"` + `data.error`、例 `"error_no_face"`）。HTTP は ok なので [api/client.ts](../../src/api/client.ts) の整形を通らず、[api/task.ts](../../src/api/task.ts) が `describeErrorCode` で読めるメッセージへ変換済み。機能C の多段実行でも各ステップで同じ整形済みメッセージがそのまま使える。
4. **結果 url は公開 S3・`X-Amz-Expires=7200`（約2時間有効）の揮発する一時 URL。**

## 目的 / スコープ

- **提供する**:
  - **一括方式（bundle）**: 連続する makeup ブロックの `effects` を**1配列に統合 → 1タスク**で適用（速い・安い・途中経過なし）。
  - **チェイン方式（chain）**: ブロックごとに1タスク。**前ステップの結果 url を次タスクの `src_file_url`** に渡す（途中経過が見える・makeup 以外も挟める）。実機確認（事実2）より、チェインの受け渡しは `dst_id` ではなく結果 url が基本。
  - **ルーティン全体の実行**と、各ステップの `{status, resultUrl}` の**逐次表示**。
- **提供しない**: 分岐・条件付き・ループなどの複雑なフロー（**直列の手順のみ**）、`dst_id` 受け渡しへの依存（makeup では返らない）、結果 url の共有 JSON への同梱（揮発するため。機能F は `effects` 設定のみ共有）。
- **機能Bとの境界**: 機能B は `effects` 1配列を1タスクで実行するところまで。機能C は**複数ブロックのオーケストレーション**（実行戦略の選択 + ステップ間の入力受け渡し + 多段進捗）を担う。各ステップのタスク実行自体は機能B の `runMakeup`／`runTask` にそのまま委譲する。
- **機能D/Eとの関係**: 本 POC では機能C を makeup のみで先に通す（全体設計 [ステップ4・6](../implementation-plan.md#8-実装ステップ推奨ビルド順)）。Look/Skin が列に挟まる並びは bundle 統合できないため chain へ切り替える（下記つまりどころ。実装は機能D/E 着手時）。

## 担当ファイル

| ファイル | 役割 | レイヤ | 新規/追記 |
| --- | --- | --- | --- |
| `domain/routine.ts` | **機能Cの中核**: bundle（effects 統合）/ chain（url 受け渡し）の実行戦略。進捗はコールバックで通知し reducer に非依存 | domain | 新規 |
| `state/appState.ts` | `SET_EXECUTION`（方式の切替）・`RESET_RUNS`（実行前の結果クリア）を追加。**`RUN_START/SUCCESS/ERROR` は機能B のものを再利用** | state | 追記 |
| `components/RoutinePanel.tsx` | 方式トグル + 「ルーティンを実行」ボタン + 全体進捗。`runRoutine` を駆動し、各ステップで既存の `RUN_*` を dispatch | components | 新規 |
| `components/RunPanel.tsx` | 各ブロックの `{status, resultUrl}` 表示。機能Cでは**多段進捗の1ステップ表示としてそのまま再利用**（改修ほぼ不要） | components | 再利用 |
| `App.tsx` | `RoutinePanel` をブロック一覧の下に配置 | components | 追記 |
| `domain/blocks.ts` | `resolveSource`（起点解決）・`validateEffects`（実行前検証）を再利用 | domain | 再利用 |

## データ（型）

機能C は永続的な新規型をほとんど増やさない。`Routine.execution`（`'bundle' | 'chain'`）と `runs`（blockId→`RunStatus`）は機能B 実装時に [state/appState.ts](../../src/state/appState.ts) へ既に置いてある。機能Cが足すのは **進捗通知のコールバック型**と、状態を動かす2つの **action** だけ。

```ts
// domain/routine.ts — 進捗を state へ橋渡しするコールバック（domain は reducer/Context を知らない）。
//   オーケストレータは各ステップでこれを呼び、UI 側が中身で RUN_* を dispatch する。
import type { TaskOutput } from '../api/task';

export interface RoutineProgress {
  onStepStart(blockId: string): void;
  onStepSuccess(blockId: string, out: TaskOutput): void; // out.resultUrl が中間/最終画像
  onStepError(blockId: string, message: string): void;    // task.ts が整形済みのメッセージ
}
```

```ts
// state/appState.ts — 追記する action（既存 RUN_* はそのまま使う）。
export type Action =
  // …既存（SET_API_KEY / SET_SOURCE / ADD|UPDATE|REMOVE_MAKEUP / RUN_START|SUCCESS|ERROR）…
  | { type: 'SET_EXECUTION'; execution: 'bundle' | 'chain' } // 方式トグル
  | { type: 'RESET_RUNS' };                                  // ルーティン実行前に古い結果を一掃

// reducer に追記
case 'SET_EXECUTION':
  return { ...state, routine: { ...state.routine, execution: action.execution } };
case 'RESET_RUNS':
  return { ...state, runs: {} };
```

## 処理フロー

機能B と同じく「編集」と「実行」の2フェーズ。編集（ブロックの追加・並び・effects）は機能A/B の責務のまま。機能Cは**実行フェーズのオーケストレーション**を担う。

1. **方式の選択（`RoutinePanel`）** — `bundle` / `chain` を `SET_EXECUTION` で切り替える。
2. **ルーティン実行** — `RESET_RUNS` で古い結果を一掃 → `runRoutine(blocks, source, execution, cb)` を起動。`cb` の各メソッドが `RUN_*` を dispatch するので、各ブロックの `RunPanel` がそのまま進捗・画像を描画する。
   - **bundle**: 全 makeup ブロックの `effects` を1配列に統合 → 起点を1回だけ `resolveSource` → makeup-vto を**1タスク**。1タスクなので統合した全ブロックを同時に running にし、成功時は**同じ最終 url** を各ブロックへ反映する。
   - **chain**: 先頭ステップは機能A の起点を `resolveSource` で解決。2段目以降は**前ステップの結果 url を `src_file_url`** に渡す。途中のステップが失敗したら**以降は実行しない**（直列の手順なので残りは idle のまま）。

```ts
// domain/routine.ts — ルーティン実行のオーケストレーション（機能C）。
//   bundle: 連続 makeup の effects を1配列へ統合し makeup-vto を1タスク実行（速い・安い）。
//   chain : ブロックごとに1タスク。前ステップの結果 url を次の src_file_url に渡す（途中経過が見える）。
//   実機確認: makeup-vto は dst_id を返さないため、受け渡しは結果 url（公開 S3・約2時間有効）が基本。
//   各ステップのタスク実行は機能B の runMakeup に委譲し、本ファイルは「順序と入力の受け渡し」だけを持つ。

import { resolveSource, validateEffects, type Block, type MakeupBlock, type SourceSelection } from './blocks';
import { runMakeup } from '../api/makeupVto';
import type { TaskOutput } from '../api/task';
import type { MakeupEffect } from '../api/types';

const FEATURE = 'makeup-vto';

export interface RoutineProgress {
  onStepStart(blockId: string): void;
  onStepSuccess(blockId: string, out: TaskOutput): void;
  onStepError(blockId: string, message: string): void;
}

/** ルーティンから AI ブロック（現状 makeup のみ）を実行順に取り出す。source は起点なので除外。 */
function makeupBlocksOf(blocks: Block[]): MakeupBlock[] {
  return blocks.filter((b): b is MakeupBlock => b.kind === 'makeup');
}

/** チェインの中間入力を解決する。
 *  実機確認: makeup-vto は dst_id を返さないので結果 url を src_file_url に渡す。
 *  dst_id を返す機能（skin-analysis の可能性・未確認）に備え「dstId があればそれ／無ければ url」と吸収する形にしておく。 */
function chainInput(prev: TaskOutput): { src_file_url: string } {
  // ※ dst_id を src_file_id 相当として渡せるかは未確認（本書「着手前に確認したいこと」）。
  //    現状は makeup→makeup のみなので url 経路で確定。
  return { src_file_url: prev.resultUrl };
}

/**
 * ルーティンを実行する。execution に応じて bundle / chain を選ぶ。
 *   - source: 起点画像（機能A）。先頭ステップの src を resolveSource で解決。
 *   - cb: 各ステップの進捗（RUN_*）を逐次通知。chain のステップ失敗は以降を中断する。
 */
export async function runRoutine(
  blocks: Block[],
  source: SourceSelection,
  execution: 'bundle' | 'chain',
  cb: RoutineProgress,
): Promise<void> {
  const makeups = makeupBlocksOf(blocks);
  if (makeups.length === 0) return;

  // 実行前に全ブロックを検証（API に投げる前に弾く＝units を無駄に消費しない）。
  for (const b of makeups) {
    const invalid = validateEffects(b.effects);
    if (invalid) return cb.onStepError(b.id, invalid);
  }

  if (execution === 'bundle') await runBundle(makeups, source, cb);
  else await runChain(makeups, source, cb);
}

/** bundle: 全 makeup の effects を1配列へ統合 → 1タスク。
 *  1タスクなので統合した全ブロックを同時 running にし、同じ結果 url で success にする。 */
async function runBundle(makeups: MakeupBlock[], source: SourceSelection, cb: RoutineProgress) {
  const effects: MakeupEffect[] = makeups.flatMap((b) => b.effects);
  makeups.forEach((b) => cb.onStepStart(b.id));
  try {
    const src = await resolveSource(FEATURE, source); // 起点は1回だけ解決（file_id の二重発行を防ぐ）
    const out = await runMakeup(src, effects);
    makeups.forEach((b) => cb.onStepSuccess(b.id, out)); // 同じ最終画像を各ブロックに反映
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    makeups.forEach((b) => cb.onStepError(b.id, message));
  }
}

/** chain: ブロックごとに1タスク。前ステップの結果 url を次の src_file_url に渡す。
 *  途中失敗は以降のステップを実行しない（残りは idle のまま）。 */
async function runChain(makeups: MakeupBlock[], source: SourceSelection, cb: RoutineProgress) {
  let src: { src_file_id: string } | { src_file_url: string } | null = null;
  for (let i = 0; i < makeups.length; i++) {
    const block = makeups[i];
    cb.onStepStart(block.id);
    try {
      // 先頭は機能A の起点、2段目以降は前ステップの結果（chainInput）。
      if (i === 0) src = await resolveSource(FEATURE, source);
      const out = await runMakeup(src!, block.effects);
      cb.onStepSuccess(block.id, out);
      src = chainInput(out);
    } catch (e) {
      cb.onStepError(block.id, e instanceof Error ? e.message : String(e));
      return; // 直列の手順なので以降は中断
    }
  }
}
```

## UI

- **`RoutinePanel.tsx`（新規）**: 実行方式のトグル（`bundle` / `chain` のラジオ → `SET_EXECUTION`）と「ルーティンを実行」ボタン。クリックで `RESET_RUNS` → `runRoutine` を起動し、`RoutineProgress` の各メソッドで `RUN_*` を dispatch する。全体の実行中表示は `runs` に `running` が1つでもあるかで導出（個別のフラグは持たない）。前提チェック（API キー・起点画像の有無）は機能B の `RunPanel` と同じ導線を踏襲。
- **`RunPanel.tsx`（再利用）**: ブロックごとの `{status, resultUrl}` 表示はそのまま機能Cの「1ステップ表示」になる。`runs` が blockId キーなので、オーケストレータが per-block の `RUN_*` を dispatch するだけで、既存の per-block 表示が**多段進捗としてそのまま機能する**（改修ほぼ不要）。単発実行ボタンは1ブロックのデバッグ用に残す。
- **`App.tsx`**: `RoutinePanel` をブロック一覧の下に配置する。

## つまりどころ

| 落とし穴 | 吸収する場所 |
| --- | --- |
| **チェインを `dst_id` 受け渡しで組めない**（makeup-vto は `dst_id` を返さない・事実2） | `routine.ts` の `chainInput` が**結果 url を `src_file_url`** に渡す。`dst_id` を返す機能に備え「dstId があれば／無ければ url」と吸収する形を1か所に集約。 |
| **bundle の進捗表現**（1タスクで複数ブロックを統合） | 統合した全ブロックを同時 running にし、成功時は**同じ最終 url** を各ブロックへ反映。`runs` が blockId キーなので per-block 表示と矛盾しない。 |
| **chain 途中の失敗**（直列なので以降は無意味） | `runChain` がエラー時に `return`。残りのブロックは idle のまま。失敗ステップには `task.ts` 整形済みの読めるメッセージが出る。 |
| **起点 file_id の二重発行**（upload 経路は実行時に発行） | `resolveSource(FEATURE, source)` を**先頭で1回だけ**呼ぶ（bundle は1回、chain は i===0 のみ）。2段目以降は前ステップの結果 url を使うので File API を再度叩かない。 |
| **bundle に makeup 以外が挟まる**（Look/Skin は effects 統合不可・機能D/E） | 列の途中に非 makeup AI ブロックがあれば**自動的に chain へ切り替える**安全弁（全体設計 6-1）。本 POC は makeup のみなので単一 bundle。実装は機能D/E 着手時。 |
| **結果 url の2時間期限**（`X-Amz-Expires=7200`） | チェイン途中で長時間空くケースは POC では無視。**共有 JSON（機能F）には結果 url を含めない**（揮発するため `effects` 設定だけを共有）。 |
| **編集による結果の陳腐化** | `UPDATE_MAKEUP` が当該ブロックの run を `idle` に戻す（機能B 実装済み）。再実行で最新 effects が走る。 |

## 完了条件

- **bundle**: 複数の makeup ブロックを並べ、方式 `bundle` で**1タスク実行 → 1枚の結果画像**が得られる（起点画像は upload / url 両経路）。
- **chain**: 2つ以上の makeup ブロックを方式 `chain` で**直列実行**し、前ステップの結果 url が次ステップの `src_file_url` に渡って、**中間画像 → 最終画像が逐次表示**される。
- **エラー導線**: chain の途中ステップが失敗（顔なし等）したら**以降が止まり**、失敗ステップに読めるメッセージが出る。**units は成功したステップぶんのみ消費**。
- **方式トグル**: `bundle` / `chain` の切替が実行結果に反映される（同じブロック列で挙動が変わる）。
- **機能F への受け渡し**: ルーティン定義（ブロックの並び・各 `effects`・`execution`）が JSON 化可能な素直な形で保たれている（結果 url は含めない）。

## 着手前に確認したいこと（未検証 → 実装中に実機で潰す）

- [ ] **チェインで結果 S3 url を `src_file_url` に渡してタスクが通るか**（サーバ間取得なので CORS は不要のはず。`chainInput` の前提）。
- [ ] **skin-analysis / look-vto が `dst_id` を返すか**（返るなら `chainInput` を url/dst_id 両対応にする価値が出る。機能E で確認）。
- [ ] **bundle で effects を多数まとめたときの上限・挙動**（パーツ数や相反カテゴリの組合せ）。
- [ ] **units の課金粒度**（bundle の1タスク=1消費か、effects 数に依存するか）。

## 再利用できる既存資産（機能B で実装済み）

| 資産 | 場所 | 機能C での使い方 |
| --- | --- | --- |
| `runTask`（start→poll→結果） | [api/task.ts](../../src/api/task.ts) | 各ステップのタスク実行の骨格。`runMakeup` 経由でそのまま委譲。 |
| `extractResult`（results の揺れ吸収） | [api/task.ts](../../src/api/task.ts) | url/dst_id の取り出しを集約済み。`chainInput` の入力解決もこの結果（`TaskOutput`）を基準に。 |
| `runMakeup` | [api/makeupVto.ts](../../src/api/makeupVto.ts) | bundle / chain とも makeup ステップはこれを呼ぶ。 |
| `resolveSource(feature, source)` | [domain/blocks.ts](../../src/domain/blocks.ts) | 先頭ステップの起点画像解決。chain の2段目以降は前ステップ url を `src_file_url` に。 |
| `validateEffects` | [domain/blocks.ts](../../src/domain/blocks.ts) | `runRoutine` の実行前検証で各 makeup ブロックを一括チェック。 |
| `runs`（blockId→RunStatus）・`RUN_*` action | [state/appState.ts](../../src/state/appState.ts) | 多段進捗・中間/最終画像の保持先。`execution: 'bundle'|'chain'` も既存。 |
