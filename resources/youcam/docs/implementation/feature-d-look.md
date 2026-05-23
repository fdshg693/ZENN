# 機能D: 完成ルックブロック（補助）

> [実装詳細インデックス](./README.md) / [全体設計](../implementation-plan.md) / [PLAN.md](../../PLAN.md)（機能D の定義） / [feature-b-makeup.md](./feature-b-makeup.md)（単発タスク実行の土台） / [feature-c-routine.md](./feature-c-routine.md)（チェイン実行の土台）

プロが作成した**完成ルックを `template_id` 一発で適用する**手軽なブロック。
個別パーツを積む機能B（makeup-vto）に対し、機能D は「テンプレートを選ぶだけ」で1枚のルックを当てる**補助ブロック**。
API の骨格は機能B/C とまったく同じ「File → Task → Poll → Result」で、look-vto 固有の差分は **①テンプレ一覧の取得（別エンドポイント）と②適用 body が `effects` ではなく `template_id`** の2点だけ。
そのため本機能の主な仕事は、新しい API を足すことより**既存のオーケストレーション（機能C）を「makeup 専用」から「makeup ＋ look の汎用」へ広げる**ことにある。

## 公式仕様から確定した事実（このプランの前提）

リファレンス（<https://docs.perfectcorp.com/reference/ai_look_vto>）で look-vto の入出力を確認した。**makeup-vto と同形**である点が機能D の設計を軽くする（メモリ: `youcam-api-response-shapes`）。

1. **テンプレ一覧は別エンドポイント**: `GET /s2s/v2.0/task/template/look-vto`。クエリ `page_size` / `starting_token`（ページング）。レスポンスは
   ```json
   { "status": 200, "data": { "templates": [ { "id": "…", "thumb": "https://…", "title": "…", "category_name": "…" } ], "next_token": "…" } }
   ```
   ラッパは機能B/C と同じく **`data`**（`result` ではない）。一覧取得は **units 非消費**のはず（適用時のみ消費。要確認）。
2. **適用 body は `template_id` ＋ 起点画像**: `POST /s2s/v2.0/task/look-vto` に `{ src_file_url | src_file_id, template_id }`。**`version` フィールドはリファレンスに無い**（makeup-vto は `"1.0"` を送っていた）→ 機能D では**送らない**方針とし、`InvalidParameters` が出たら付ける（下記「着手前に確認したいこと」）。
3. **成功レスポンスは makeup-vto と同形**: `data.results` が単体オブジェクト `{ url }`、**`dst_id` は返らない**。
   ```json
   { "status": 200, "data": { "results": { "url": "https://…s3…/….jpg?X-Amz-Expires=7200&…" }, "task_status": "success" } }
   ```
   → **既存の [api/task.ts](../../src/api/task.ts) の `runTask` / `extractResult` がそのまま通る**（新規の取り出し処理は不要）。チェインの受け渡しも機能C と同じ「結果 url を次の `src_file_url`」。
4. **タスクレベルのエラーは HTTP 200**（`data.task_status:"error"` + `data.error`）。`error_no_face` 等は [api/task.ts](../../src/api/task.ts) の `describeErrorCode` が整形済み。look-vto も顔写真が要るため同じ顔系エラーが起こり得る。

## 目的 / スコープ

- **提供する**:
  - **テンプレート一覧の取得・選択**: `GET .../template/look-vto` で `templates[]`（`id` / `title` / `thumb`）を取得し、サムネイル付きで選ばせる。
  - **選んだ look の適用**: `template_id` ＋ 起点画像で look-vto を**1タスク実行 → 結果画像**を表示（機能B の単発実行と同じ導線）。
  - **ルーティンへの組み込み**: look ブロックを機能C の**チェインに混在**させて実行（makeup→look / look→makeup の直列）。
- **提供しない**: テンプレートのカスタム作成・編集（PLAN 通り）。look ブロックの **bundle 統合**（`effects` ではないため統合不可。後述の安全弁で chain に切替）。`dst_id` 受け渡し（look-vto も返さない）。
- **機能B/Cとの境界**: 機能B/C が用意した **`runTask`（汎用タスク）/ `runs`（blockId→RunStatus）/ チェイン受け渡し（結果 url）/ `RunPanel` の進捗表示**をそのまま再利用する。機能D が足すのは「look-vto 固有の差分（一覧取得・`template_id` body）」と「**オーケストレータを makeup 専用から汎用へ広げる**」こと。
- **機能Eとの関係**: 本機能で「複数の AI ブロック種別を1本のチェインで回す」骨格（`featureOf` による振り分け）を確立する。機能E（skin）はこの骨格に種別を1つ足すだけになる。

## 担当ファイル

| ファイル | 役割 | レイヤ | 新規/追記 |
| --- | --- | --- | --- |
| `api/types.ts` | `LookTemplate` / 一覧レスポンス / look タスク req の型を追記 | api | 追記 |
| `api/lookVto.ts` | feature 名 `look-vto`。`runLook`（適用）と `listLookTemplates`（一覧・ページング）。実処理は `task.ts` に委譲 | api | 新規 |
| `domain/blocks.ts` | `LookBlock` 型・`createLookBlock`・`validateLook`、`Block` union に追加 | domain | 追記 |
| `domain/routine.ts` | **本機能の中核改修**: 実行対象を `makeup` 専用 → `makeup`+`look` の汎用へ。種別ごとの `featureOf` / `runBlock` 振り分け、look 混在時の bundle→chain 安全弁 | domain | 追記 |
| `state/appState.ts` | `ADD_LOOK` / `UPDATE_LOOK` と、削除を種別非依存の `REMOVE_BLOCK` に汎用化。`selectAiBlocks` 追加 | state | 追記 |
| `components/editors/LookEditor.tsx` | テンプレ一覧（サムネ）から選び `UPDATE_LOOK` する編集 UI | components | 新規 |
| `components/RunPanel.tsx` | block 種別で feature / 実行関数 / 検証を振り分ける汎用化（単発実行ボタン） | components | 追記 |
| `components/RoutinePanel.tsx` | 実行可否・running 判定を `selectMakeupBlocks` → `selectAiBlocks` に拡張 | components | 追記 |
| `App.tsx` | `kind` で editor を出し分け（look→`LookEditor`）＋「完成ルックを追加」ボタン | components | 追記 |

## データ（型）

look-vto は makeup-vto と同形なので、**結果系の型・取り出しは増やさない**（`TaskOutput` / `extractResult` をそのまま使う）。増えるのは「一覧取得の型」「look の req 型」「`LookBlock`」と、状態を動かす action だけ。

```ts
// api/types.ts （機能D: look-vto の型 = 仕様の正本）

/** テンプレ一覧の1件。リファレンス: data.templates[]。id を template_id に渡す。 */
export interface LookTemplate {
  id: string;            // ← look-vto の template_id に渡す値
  title: string;         // 表示名
  thumb?: string;        // サムネイル URL（一覧 UI で表示）
  category_name?: string;
}

/** テンプレ一覧レスポンス。ラッパは data（機能B/C と共通）。next_token でページング。 */
export interface LookTemplateListResponse {
  status?: number;
  data: { templates: LookTemplate[]; next_token?: string | number | null };
}

/** look-vto タスク開始リクエスト。src_* はどちらか一方。version はリファレンス未記載のため送らない。 */
export interface LookTaskRequest {
  src_file_id?: string;
  src_file_url?: string;
  template_id: string;
}
```

```ts
// domain/blocks.ts （追記）

/** 機能D: 完成ルックを template_id 一発適用。これが共有（機能F）の最小単位（id 文字列1つ）。 */
export interface LookBlock extends BaseBlock {
  kind: 'look';
  templateId: string; // LookTemplate.id
}

// Block union を拡張（既存に追加）。
export type Block = SourceBlock | MakeupBlock | LookBlock;

/** 新しい空の look ブロック（テンプレ未選択から始め、UI が一覧から選ばせる）。 */
export function createLookBlock(): LookBlock {
  return { id: crypto.randomUUID(), kind: 'look', title: '完成ルック', templateId: '' };
}

/** look ブロックの実行前検証（テンプレ未選択を API に投げる前に弾く）。 */
export function validateLook(block: LookBlock): string | null {
  return block.templateId ? null : '完成ルックのテンプレートを選んでください。';
}
```

```ts
// state/appState.ts （追記）— 既存 RUN_* / SET_EXECUTION / RESET_RUNS はそのまま使う。
export type Action =
  // …既存（SET_API_KEY / SET_SOURCE / ADD|UPDATE|REMOVE_MAKEUP / RUN_* / SET_EXECUTION / RESET_RUNS）…
  | { type: 'ADD_LOOK' }                                  // look ブロックを末尾に追加
  | { type: 'UPDATE_LOOK'; id: string; templateId: string } // テンプレ選択を反映（編集で run を idle に戻す）
  | { type: 'REMOVE_BLOCK'; id: string };                 // 種別非依存の削除（REMOVE_MAKEUP を一般化）

// reducer 追記イメージ（UPDATE_LOOK は UPDATE_MAKEUP と同じく当該ブロックの run を idle へ戻す）。
case 'ADD_LOOK': {
  const blocks = [...state.routine.blocks, createLookBlock()];
  return { ...state, routine: { ...state.routine, blocks } };
}
case 'UPDATE_LOOK': {
  const blocks = state.routine.blocks.map((b) =>
    b.id === action.id && b.kind === 'look' ? { ...b, templateId: action.templateId } : b,
  );
  const runs = { ...state.runs, [action.id]: { phase: 'idle' } as RunStatus };
  return { ...state, routine: { ...state.routine, blocks }, runs };
}
```

> **削除の一般化**: 既存 `REMOVE_MAKEUP` は `b.id !== action.id` で**種別に依存せず**フィルタしている。機能Dでは look も削除するため、名前と意図を合わせて `REMOVE_BLOCK` に一般化する（呼び出し側の MakeupEditor / LookEditor / App をまとめて差し替える小さな改修）。

```ts
// state/appState.ts — セレクタ追記。makeup だけでなく look も実行対象に含める。
import type { LookBlock } from '../domain/blocks';
export type AiBlock = MakeupBlock | LookBlock;

/** 実行対象の AI ブロック（makeup + look）を並び順で取り出す。source は起点なので除外。 */
export function selectAiBlocks(state: AppState): AiBlock[] {
  return state.routine.blocks.filter((b): b is AiBlock => b.kind === 'makeup' || b.kind === 'look');
}
```

## 処理フロー

機能B/C と同じく「編集」と「実行」の2フェーズ。look 固有の API 呼び出しは**編集時のテンプレ一覧取得**と**実行時の look-vto 適用**の2か所だけ。

1. **編集フェーズ（`LookEditor`）** — `listLookTemplates()` で一覧を取得（カテゴリ別キャッシュ）→ サムネ付きで選択 → `UPDATE_LOOK` で `templateId` を state へ。
2. **実行フェーズ** — 単発（`RunPanel`）でもルーティン（`RoutinePanel`→`runRoutine`）でも、look ブロックは `resolveSource('look-vto', source)`（先頭の場合）→ `runLook(src, templateId)` → `task.ts` が start→poll→`{ resultUrl }` を返す。`dst_id` は無いので chain は結果 url を次へ渡す（機能C と同じ）。

```ts
// api/lookVto.ts — 機能D: look-vto 固有の差分だけ（実処理は task.ts に委譲）。
//   makeup-vto と同形の成功レスポンス（data.results.url・dst_id 無し）なので runTask をそのまま使う。
//   一覧取得（template/look-vto）は units 非消費のはず。ページングは next_token を辿る。

import { client } from './client';
import { runTask, type TaskOutput } from './task';
import type { LookTemplate, LookTemplateListResponse } from './types';

/** 完成ルックを1タスク適用する。version はリファレンス未記載のため送らない（要確認）。 */
export function runLook(
  src: { src_file_id: string } | { src_file_url: string },
  templateId: string,
): Promise<TaskOutput> {
  return runTask('look-vto', { ...src, template_id: templateId });
}

// テンプレ一覧はモジュールキャッシュ（同じ一覧を何度も取りに行かない。catalog.ts と同方針）。
let templateCache: LookTemplate[] | null = null;

/** 完成ルックのテンプレ一覧を取得する（next_token を辿って全件）。一覧は /api proxy 配下なので追加 proxy は不要。 */
export async function listLookTemplates(pageSize = 50): Promise<LookTemplate[]> {
  if (templateCache) return templateCache;

  const all: LookTemplate[] = [];
  let token: string | undefined;
  do {
    const qs = new URLSearchParams({ page_size: String(pageSize) });
    if (token) qs.set('starting_token', token);
    const res = await client.get<LookTemplateListResponse>(`/s2s/v2.0/task/template/look-vto?${qs}`);
    all.push(...(res.data.templates ?? []));
    token = res.data.next_token != null ? String(res.data.next_token) : undefined;
  } while (token);

  templateCache = all;
  return all;
}
```

```ts
// domain/routine.ts — 機能D での中核改修: 実行対象を makeup 専用 → makeup+look の汎用へ。
//   足すのは「種別ごとの feature 名」と「種別ごとの実行関数」の2つの振り分けだけ。
//   bundle は effects 統合専用なので look が混ざれば chain に切替（全体設計 6-1 の安全弁）。

import {
  resolveSource, validateEffects, validateLook,
  type Block, type MakeupBlock, type LookBlock, type SourceSelection,
} from './blocks';
import { runMakeup } from '../api/makeupVto';
import { runLook } from '../api/lookVto';
import type { TaskOutput } from '../api/task';

type AiBlock = MakeupBlock | LookBlock;
type SrcRef = { src_file_id: string } | { src_file_url: string };

/** ブロック種別 → feature 名（File API / Task のエンドポイント・セグメント）。 */
function featureOf(block: AiBlock): string {
  return block.kind === 'look' ? 'look-vto' : 'makeup-vto';
}

/** 1ブロックを実行（種別ごとに API を振り分ける）。chain/bundle 双方から使う。 */
function runBlock(block: AiBlock, src: SrcRef): Promise<TaskOutput> {
  return block.kind === 'look' ? runLook(src, block.templateId) : runMakeup(src, block.effects);
}

/** 1ブロックの実行前検証（種別ごと）。 */
function validateBlock(block: AiBlock): string | null {
  return block.kind === 'look' ? validateLook(block) : validateEffects(block.effects);
}

/** 実行対象（makeup + look）を並び順で取り出す。source は起点なので除外。 */
function aiBlocksOf(blocks: Block[]): AiBlock[] {
  return blocks.filter((b): b is AiBlock => b.kind === 'makeup' || b.kind === 'look');
}

export async function runRoutine(
  blocks: Block[],
  source: SourceSelection,
  execution: 'bundle' | 'chain',
  cb: RoutineProgress,
): Promise<void> {
  const ai = aiBlocksOf(blocks);
  if (ai.length === 0) return;

  for (const b of ai) {
    const invalid = validateBlock(b);
    if (invalid) return cb.onStepError(b.id, invalid);
  }

  // look は effects に統合できない。bundle 指定でも look が混ざれば自動的に chain へ（安全弁）。
  const bundlable = execution === 'bundle' && ai.every((b) => b.kind === 'makeup');
  if (bundlable) await runBundle(ai as MakeupBlock[], source, cb);
  else await runChain(ai, source, cb);
}

/** chain: ブロックごとに1タスク。先頭は起点を「先頭ブロックの feature」で解決、2段目以降は前結果 url。 */
async function runChain(blocks: AiBlock[], source: SourceSelection, cb: RoutineProgress) {
  let src: SrcRef | null = null;
  for (let i = 0; i < blocks.length; i++) {
    const block = blocks[i];
    cb.onStepStart(block.id);
    try {
      // ★ 先頭の起点は「先頭ブロックの feature」で発行する（look が先頭なら look-vto で file_id）。
      if (i === 0) src = await resolveSource(featureOf(block), source);
      const out = await runBlock(block, src!);
      cb.onStepSuccess(block.id, out);
      src = { src_file_url: out.resultUrl }; // 次段へは結果 url（look も makeup も src_file_url を受ける）
    } catch (e) {
      cb.onStepError(block.id, e instanceof Error ? e.message : String(e));
      return; // 直列なので以降は中断
    }
  }
}
```

> **`runBundle` は makeup 専用のまま**でよい（安全弁が「全 makeup のとき」しか呼ばないことを保証する）。既存実装の `FEATURE = 'makeup-vto'` 固定もそのまま。変わるのは `runChain` が**先頭ブロックの feature で起点を解決する**点（`makeup-vto` 固定をやめる）と、種別振り分け（`featureOf` / `runBlock`）が入る点。

## UI

- **`LookEditor.tsx`（新規）**: `useEffect` で `listLookTemplates()` を呼び、読み込み中／失敗を `MakeupEditor` の `PatternPicker` と同じ作法で表示。取得後は**サムネイル付きの選択 UI**（`thumb` 画像＋`title`、`category_name` でグルーピングしてもよい）。選択で `UPDATE_LOOK` を dispatch。**ロジックは持たず**、表示と dispatch のみ。
- **`RunPanel.tsx`（汎用化）**: 現状は `MakeupBlock` 固定で `resolveSource('makeup-vto', …)` / `runMakeup` をハードコードしている。これを **block 種別で振り分け**る：feature は `featureOf`、実行関数は `runBlock`、検証は `validateBlock`（domain から再利用）。look ブロックでも「このブロックを実行」→ 進捗 → 結果画像の導線がそのまま動く。
- **`RoutinePanel.tsx`（追記）**: `selectMakeupBlocks` を `selectAiBlocks` に差し替える（running 判定・「ブロックを1つ以上追加」の前提チェック）。方式トグル・実行起動・コールバックの仕組みは無改修。
- **`App.tsx`（追記）**: `selectAiBlocks` を並び順で回し、`block.kind` で `MakeupEditor` / `LookEditor` を出し分け、各ブロックに `RunPanel` を添える。「＋ メイクブロックを追加」の隣に「＋ 完成ルックを追加」（`ADD_LOOK`）を置く。

## つまりどころ

| 落とし穴 | 吸収する場所 |
| --- | --- |
| **look は bundle 統合できない**（`effects` ではなく `template_id`） | `routine.ts` の安全弁: `ai.every(kind==='makeup')` のときだけ bundle、それ以外（look 混在）は自動 chain（全体設計 6-1）。 |
| **チェインの起点 feature が makeup 固定だった**（先頭が look だと file_id を makeup-vto で発行してしまう） | `runChain` が `resolveSource(featureOf(blocks[0]), source)` で**先頭ブロックの feature**で発行する。url 経路は feature 非依存なので影響なし。 |
| **`version` フィールドの要否が未確認**（makeup は `"1.0"`、look はリファレンス未記載） | `runLook` は送らない。`InvalidParameters` が出たら `version:'1.0'` を付けて再試行（着手前に確認）。 |
| **テンプレ一覧のページング**（`next_token` の型・終端） | `listLookTemplates` が `next_token != null` の間ループ。型の揺れに備え `String(token)` で正規化。1ページで足りる POC でも全件取れる形に。 |
| **一覧取得の units 消費**（取得だけで消費すると無駄） | 一覧は `template/look-vto`（適用とは別）で**非消費のはず**。実機で確認（着手前に確認）。キャッシュで多重取得も防ぐ。 |
| **look-vto も顔写真が必要**（顔系エラー） | makeup と同じ `error_no_face` 等が HTTP 200 で返る → `task.ts` の `describeErrorCode` が整形済み。新規対応不要。 |
| **テンプレ未選択のまま実行** | `validateLook` が実行前に弾く（`RunPanel` / `runRoutine` 両方で `validateBlock` 経由）。units を無駄に消費しない。 |
| **結果系の二重実装** | look-vto は makeup-vto と同形（`data.results.url`・`dst_id` 無し）。**`extractResult` / `TaskOutput` を再利用**し、look 専用の取り出しは作らない。 |
| **一覧の CORS** | `template/look-vto` は API 本体（`yce-api-01`）配下なので**既存の `/api` proxy で足りる**（catalog.ts の `/catalog` のような別ホスト追加は不要）。 |

## 完了条件

- **テンプレ一覧**: `LookEditor` を開くと look テンプレが**サムネ付きで一覧表示**され、1つ選べる（`templateId` が state に入る）。
- **単発適用**: look ブロック単体を、起点画像（**upload / url 両経路**）で実行 → **完成ルックの結果画像が表示**される。
- **チェイン混在**: makeup ブロックと look ブロックを並べ、方式 `chain` で**直列実行**でき、前ステップの結果 url が次の `src_file_url` に渡って中間→最終画像が逐次表示される（makeup→look / look→makeup の双方）。
- **bundle 安全弁**: look を含む並びで方式 `bundle` を選んでも**自動的に chain で実行**される（look が effects 統合をすり抜けない）。
- **エラー導線**: テンプレ未選択は実行前に弾かれ、顔なし等は読めるメッセージが出て **units は成功ステップぶんのみ消費**。
- **機能F への受け渡し**: `LookBlock` が `{ kind:'look', templateId }` という **JSON 化可能な素直な形**（共有の最小単位）に保たれている。

## 着手前に確認したいこと（未検証 → 実装中に実機で潰す）

- [ ] **look-vto の body に `version` が要るか**（要れば `runLook` に `version:'1.0'` を足す）。
- [ ] **一覧 `template/look-vto` のページング挙動**（`next_token` の実際の型・終端条件、`page_size` の上限）。
- [ ] **一覧取得が units 非消費か**（消費するならキャッシュ＋取得タイミングを見直す）。
- [ ] **チェインで makeup→look / look→makeup が通るか**（前段の結果 S3 url を `src_file_url` に渡してサーバ間取得が成立するか。機能C の未確認項目と同根）。
- [ ] **look 適用の units 課金粒度**（template 1適用=1消費か）。

## 再利用できる既存資産（機能B/C で実装済み）

| 資産 | 場所 | 機能D での使い方 |
| --- | --- | --- |
| `runTask` / `extractResult`（start→poll→結果・揺れ吸収） | [api/task.ts](../../src/api/task.ts) | look-vto も同形（`data.results.url`・dst_id 無し）なので**無改修で再利用**。`runLook` が委譲。 |
| `client`（認証・整形・429 リトライ）/ `describeErrorCode` | [api/client.ts](../../src/api/client.ts) | 一覧取得・適用とも `client.get/post`。顔系エラーの整形も共通。 |
| `uploadFile(feature, file)` | [api/files.ts](../../src/api/files.ts) | look 先頭・upload 経路で `look-vto` の file_id を発行。 |
| `resolveSource(feature, source)` | [domain/blocks.ts](../../src/domain/blocks.ts) | chain 先頭の起点解決を **feature 引数で `look-vto`** にも対応（`featureOf` で決定）。 |
| `runRoutine` / `RoutineProgress` / bundle・chain 戦略 | [domain/routine.ts](../../src/domain/routine.ts) | makeup 専用から **makeup+look 汎用**へ広げる（`featureOf` / `runBlock` 追加）。骨格は流用。 |
| `runs`（blockId→RunStatus）・`RUN_*` / `SET_EXECUTION` / `RESET_RUNS` | [state/appState.ts](../../src/state/appState.ts) | 多段進捗・中間/最終画像の保持。look も同じキー空間で per-block 表示。 |
| `RunPanel`（単発進捗・結果画像） | [components/RunPanel.tsx](../../src/components/RunPanel.tsx) | 種別振り分けで look も同 UI。 |
| `RoutinePanel`（方式トグル・実行起動） | [components/RoutinePanel.tsx](../../src/components/RoutinePanel.tsx) | `selectAiBlocks` 化のみで look 込み実行に対応。 |
