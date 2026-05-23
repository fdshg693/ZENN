# 機能F: ルーティンの保存・共有（JSON）

> [実装詳細インデックス](./README.md) / [全体設計](../implementation-plan.md)（[6-2 JSON 共有](../implementation-plan.md#6-2-json-共有機能f)） / [PLAN.md](../../PLAN.md)（機能F の定義） / [feature-b-makeup.md](./feature-b-makeup.md)（effects＝共有の最小単位） / [feature-c-routine.md](./feature-c-routine.md)（実行方式 execution の共有） / [feature-d-look.md](./feature-d-look.md)・[feature-e-skin.md](./feature-e-skin.md)（look/skin ブロックの素直な JSON）

組んだルーティンを **JSON でエクスポート／インポート**し、他人の JSON を取り込んで**自分の顔で再生**できるようにする機能。
本 POC の中核価値（「ルーティンを共有する」）が成立する最後のピース。

機能B〜E は実装のたびに「**この型は機能F の共有の最小単位**だから JSON 化できる素直な形を保つ」という制約を守ってきた（[blocks.ts](../../src/domain/blocks.ts) の各ブロック型コメント参照）。
機能F は**その地ならしを回収するだけ**で、新しい API も新しいドメインモデルもほぼ要らない。機能F 固有の仕事は次の2点に集約される。

1. **API を一切使わない**（PLAN「利用 API: なし」）。すべてクライアント内の JSON 直列化／復元。これまでの機能（File→Task→Poll の非同期）と性質が根本的に違う。
2. **入力が「外部から来た信頼できない JSON」**。TypeScript の型は**コンパイル時**にしか効かないため、import では**実行時のバリデーション**（構造・enum・SD/HD 混在）を自前で持つ必要がある。これが本機能の主な実装量。

## 設計の前提（機能A〜E で確定済み）

機能F は新しい外部仕様を持ち込まない。前提はすべて既存コードと過去の設計判断に閉じている。

1. **AI ブロックの型はすべて JSON シリアライズ可能**（[blocks.ts](../../src/domain/blocks.ts)）。`MakeupBlock.effects` / `LookBlock.templateId` / `SkinBlock.{resolution,dstActions}` は API ペイロードに対応する素直な値だけを持ち、関数・`File`・DOM 参照を含まない。`AiBlock = MakeupBlock | LookBlock | SkinBlock` が**そのまま共有単位**になる。
2. **`SourceBlock` だけが共有不可**。`SourceSelection` は `{ type:'upload'; file: File; previewUrl }`（`File` と blob URL を持つ＝シリアライズ不可）か `{ type:'url'; url }`。**顔画像は共有対象に含めない**（PLAN: 取り込み側が自分の顔を指定）ので、export は source を**まるごと除外**し、import は**取り込み側の既存 source を温存**する。
3. **結果 url は共有しない**。結果（`runs`）は揮発する公開 S3 url（`X-Amz-Expires=7200`＝約2時間・[feature-c-routine.md](./feature-c-routine.md) 事実4）。そもそも `runs` は `Routine` の外（[appState.ts](../../src/state/appState.ts) の `AppState.runs`）にあるので、ルーティンを直列化する限り**自然と混入しない**。
4. **`execution`（bundle / chain）はルーティンの一部**（機能C）。手順だけでなく「どう実行するか」も共有対象に含める（[Routine](../../src/state/appState.ts) は `{ blocks, execution }`）。
5. **`template_id` は PerfectCorp のグローバルカタログ値**（[feature-d-look.md](./feature-d-look.md)）なので**ユーザー間で可搬**。ただし取り込み側のローカルマニフェスト（`public/look-templates/index.json`・349件）は全カタログの部分集合なので、**未収載 id を import しても落とさない**よう扱う（後述つまりどころ）。

## 目的 / スコープ

- **提供する**:
  - **エクスポート**: 現在のルーティン（**AI ブロックの並び＋各設定＋ `execution`**）を JSON 文字列化し、ファイルダウンロード（`routine.json`）／クリップボードコピーで取り出す。**source（顔画像）と結果 url は含めない**。
  - **インポート**: JSON（ファイル選択 or 貼り付け）を読み、**構造・enum を検証してから** state へ反映。取り込み側の **source は温存**し、AI ブロックと `execution` だけを差し替える＝「他人のルーティン＋自分の顔」が成立。
  - **壊れた / 別物の JSON を読めるエラーで弾く**（どのブロックの何が不正かを示す）。クラッシュさせない。
- **提供しない**: 共有リンク発行・アカウント・サーバ保存（**import/export のみ**・PLAN 通り）。顔画像の同梱（仕様として除外）。結果画像の同梱（揮発するため）。複数ルーティンのライブラリ管理・履歴（単一ルーティンの入出力のみ）。後方互換のための旧バージョン JSON 変換（`version` 不一致は読めるエラーで弾くまで。POC スコープ）。
- **機能A〜Eとの境界**: ブロックの型・既定値・**意味的な検証**（`validateEffects` / `validateLook` / `validateSkin`）・カタログ（`ALL_CATEGORIES` / `SKIN_ACTIONS`）は機能B〜E が持つものを**そのまま再利用**する。機能F が足すのは ①直列化（source 除外）、②**外部 JSON の構造バリデーション**（実行時の型ガード）、③state への一括読込（`LOAD_ROUTINE`）、④入出力 UI の4つだけ。実行（API 呼び出し）には一切関与しない。

## 担当ファイル

| ファイル | 役割 | レイヤ | 新規/追記 |
| --- | --- | --- | --- |
| `domain/routineFile.ts` | **機能Fの中核**: `serializeRoutine`（source 除外で JSON 化）／`parseRoutine`（外部 JSON の構造・enum 検証 → `AiBlock[]`＋`execution`）。UI 非依存・API 非依存 | domain | 新規 |
| `state/appState.ts` | `LOAD_ROUTINE`（**source を温存しつつ** AI ブロックと execution を差し替え・`runs` も一掃）を追加 | state | 追記 |
| `components/ImportExport.tsx` | エクスポート（ダウンロード／コピー）とインポート（ファイル選択／貼り付け）の UI。`routineFile` を呼び、結果を dispatch、エラーを表示 | components | 新規 |
| `App.tsx` | `ImportExport` を `RoutinePanel` の近く（ブロック一覧と実行の間 or 末尾）に配置 | components | 追記 |
| `domain/blocks.ts` | `ALL_CATEGORIES` / `SKIN_ACTIONS` / `validate*` を**検証に再利用**（必要なら `crypto.randomUUID` で import 時に id 再発行） | domain | 再利用 |

> `api/` 層は**一切触らない**。機能F はネットワークを発生させない初めての機能。

## データ（型）

共有 JSON の**スキーマそのもの**を1つの型に固定する（＝仕様の正本）。`AiBlock` は既に JSON 化可能なので、共有形は「`AiBlock[]` ＋ `execution` ＋ 識別用メタ」を包むだけで足りる。

```ts
// domain/routineFile.ts — 共有 JSON のスキーマ（＝仕様の正本）。
//   AiBlock（makeup|look|skin）はそのまま直列化できる（blocks.ts の設計）。
//   source（顔画像）と runs（結果 url）は意図的に含めない。
import type { AiBlock } from './blocks';

/** これがファイルとして書き出され、他人が取り込む単位。 */
export interface SharedRoutine {
  app: 'youcam-routine-share'; // 別アプリの JSON を取り違えないための識別子（マジック）
  version: 1;                  // スキーマ版。将来変えたら import 側で弾く / 変換する分岐点
  execution: 'bundle' | 'chain'; // 機能C: 実行方式も共有対象
  blocks: AiBlock[];           // makeup / look / skin の並び（source は含めない）
}

/** parse の結果。成功なら state に流せる素材、失敗なら読めるエラー。例外を投げず Result で返す。 */
export type ParseResult =
  | { ok: true; execution: 'bundle' | 'chain'; blocks: AiBlock[] }
  | { ok: false; error: string };
```

```ts
// state/appState.ts （追記）— ルーティンの一括読込。source は温存し AI ブロックだけ差し替える。
export type Action =
  // …既存（SET_SOURCE / ADD|UPDATE_* / REMOVE_BLOCK / RUN_* / SET_EXECUTION / RESET_RUNS）…
  | { type: 'LOAD_ROUTINE'; blocks: AiBlock[]; execution: 'bundle' | 'chain' };
```

> **新しい永続型はほぼ増えない**。`SharedRoutine` は `AiBlock` の薄いラッパ、`LOAD_ROUTINE` は既存 `Routine` を組み替える1 action。機能E が払った「ブロック型を JSON 可能に保つ」コストの配当をここで受け取る。

## 処理フロー

機能F は「実行」フェーズを持たない（API を呼ばない）。**直列化**と**復元**の2方向だけ。

### export（直列化）

1. `selectAiBlocks(state)` で AI ブロック（source 除外済み）を並び順で取得。
2. `serializeRoutine(blocks, execution)` が `SharedRoutine` を組み、`JSON.stringify(_, null, 2)` で整形文字列化。
3. UI が Blob → `<a download="routine.json">` でダウンロード、またはクリップボードへコピー。

```ts
// domain/routineFile.ts — export 側。source / runs を含めないことが要点。
export function serializeRoutine(blocks: AiBlock[], execution: 'bundle' | 'chain'): string {
  const shared: SharedRoutine = { app: 'youcam-routine-share', version: 1, execution, blocks };
  return JSON.stringify(shared, null, 2); // AiBlock は素直な値のみ＝そのまま安全に直列化できる
}
```

### import（復元 ＝ 機能F の本体）

外部 JSON は信頼できないので、**state に入れる前に**段階的に検証する。各段で落ちたら `{ ok:false, error }` を返し、UI が文言を出す。

1. **JSON パース**: `JSON.parse`（失敗＝壊れた JSON → 「JSON として読めません」）。
2. **封筒の検証**: オブジェクトか／`app==='youcam-routine-share'` か／`version===1` か／`execution ∈ {bundle,chain}` か／`blocks` が配列か。`version` 不一致は「対応していない形式（version N）」で弾く（将来の変換分岐点）。
3. **各ブロックの構造・enum 検証**（`kind` で分岐）:
   - `makeup`: `effects` が配列で、各 effect の `category ∈ ALL_CATEGORIES`。`palettes` / `pattern` 等の形は **`validateEffects` に委ねて意味検証も同時に拾う**（色形式・パターン未選択など）。
   - `look`: `templateId` が文字列（空でも構造的には可。`validateLook` は「未選択」を拾うが import 段では**警告に留め**、未収載 id は LookEditor 再選択へ）。
   - `skin`: `resolution ∈ {sd,hd}`／`dstActions` が string 配列で、**`validateSkin` で SD/HD 混在・空を弾く**。
   - 未知 `kind` は「未知のブロック種別: X」で弾く。
4. **id の再発行（任意・推奨）**: 取り込んだ各ブロックの `id` を `crypto.randomUUID()` で振り直す（他セッションの id と衝突させない・`runs` キーを確実に新規にする）。
5. 成功なら `{ ok:true, blocks, execution }`。UI が `LOAD_ROUTINE` を dispatch。

```ts
// domain/routineFile.ts — import 側（構造の型ガード）。意味検証は既存 validate* に委譲する。
import { ALL_CATEGORIES, validateEffects, validateSkin, type AiBlock } from './blocks';

export function parseRoutine(text: string): ParseResult {
  let raw: unknown;
  try { raw = JSON.parse(text); }
  catch { return { ok: false, error: 'JSON として読めませんでした。ファイルの中身を確認してください。' }; }

  if (!isObject(raw)) return { ok: false, error: 'ルーティン JSON の形式ではありません。' };
  if (raw.app !== 'youcam-routine-share') return { ok: false, error: 'このアプリのルーティン JSON ではありません。' };
  if (raw.version !== 1) return { ok: false, error: `対応していないバージョン（version ${String(raw.version)}）です。` };
  if (raw.execution !== 'bundle' && raw.execution !== 'chain') return { ok: false, error: 'execution は bundle / chain のいずれかです。' };
  if (!Array.isArray(raw.blocks)) return { ok: false, error: 'blocks が配列ではありません。' };

  const blocks: AiBlock[] = [];
  for (let i = 0; i < raw.blocks.length; i++) {
    const b = raw.blocks[i];
    const where = `ブロック${i + 1}`;
    if (!isObject(b) || typeof b.title !== 'string') return { ok: false, error: `${where}の形式が不正です。` };
    switch (b.kind) {
      case 'makeup': {
        if (!Array.isArray(b.effects)) return { ok: false, error: `${where}（メイク）の effects が配列ではありません。` };
        if (!b.effects.every((e) => isObject(e) && (ALL_CATEGORIES as readonly string[]).includes(e.category as string)))
          return { ok: false, error: `${where}（メイク）に未知のカテゴリが含まれます。` };
        const m = validateEffects(b.effects as never); // 色形式・パターン未選択など意味検証も流用
        if (m) return { ok: false, error: `${where}（メイク）: ${m}` };
        blocks.push({ id: crypto.randomUUID(), kind: 'makeup', title: b.title, effects: b.effects as never });
        break;
      }
      case 'look': {
        if (typeof b.templateId !== 'string') return { ok: false, error: `${where}（完成ルック）の templateId が不正です。` };
        // 未選択・未収載 id は弾かない（取り込み後に LookEditor で選び直せる）。
        blocks.push({ id: crypto.randomUUID(), kind: 'look', title: b.title, templateId: b.templateId });
        break;
      }
      case 'skin': {
        if (b.resolution !== 'sd' && b.resolution !== 'hd') return { ok: false, error: `${where}（肌診断）の resolution が不正です。` };
        if (!Array.isArray(b.dstActions) || !b.dstActions.every((a) => typeof a === 'string'))
          return { ok: false, error: `${where}（肌診断）の dstActions が不正です。` };
        const skin = { id: crypto.randomUUID(), kind: 'skin' as const, title: b.title, resolution: b.resolution, dstActions: b.dstActions };
        const s = validateSkin(skin); // SD/HD 混在・空を弾く（機能E の検証を再利用）
        if (s) return { ok: false, error: `${where}（肌診断）: ${s}` };
        blocks.push(skin);
        break;
      }
      default:
        return { ok: false, error: `${where}: 未知のブロック種別「${String(b.kind)}」です。` };
    }
  }
  return { ok: true, execution: raw.execution, blocks };
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}
```

```ts
// state/appState.ts （追記）— source を温存し AI ブロックだけ差し替える。runs も一掃する。
case 'LOAD_ROUTINE': {
  // 取り込み側の起点（顔写真）はそのまま。無ければ新規 source を1つ用意する。
  const source =
    state.routine.blocks.find((b): b is SourceBlock => b.kind === 'source') ?? createSourceBlock();
  return {
    ...state,
    routine: { blocks: [source, ...action.blocks], execution: action.execution },
    runs: {}, // 取り込んだブロックは未実行。古い結果（前ルーティンの url）を残さない。
  };
}
```

## UI

- **`ImportExport.tsx`（新規）**: 2区画のパネル。
  - **エクスポート**: 「JSON をダウンロード」（`serializeRoutine` → Blob → `routine.json`）と「コピー」（`navigator.clipboard.writeText`）。AI ブロックが0件なら無効化し「共有するブロックがありません」。**source・結果は含まれない旨**を注記（共有しても顔写真は渡らない＝安心材料）。
  - **インポート**: `<input type="file" accept="application/json,.json">` と貼り付け用 `<textarea>` の2経路。取り込み実行で `parseRoutine` → `ok` なら `LOAD_ROUTINE` を dispatch（成功トースト「N ブロックを取り込みました。起点画像はご自身のものを指定してください」）、`!ok` なら `error` をそのまま表示。
  - **置き換え確認**: import は現在のルーティンを差し替える破壊的操作。既存 AI ブロックがある場合は確認（「現在のブロックは置き換えられます」）。
- **`App.tsx`（追記）**: `ImportExport` を配置（共有は「ルーティンを組む → 出す／入れる」の文脈なので **`RoutinePanel` の直前**か末尾）。import 後は既存の各 `MakeupEditor` / `LookEditor` / `SkinEditor` がそのまま新ブロックを描画し、`SourcePanel` で自分の顔を指定 → `RoutinePanel` で実行、という既存導線にそのまま乗る（**機能F 専用の実行 UI は不要**）。

## つまりどころ

| 落とし穴 | 吸収する場所 |
| --- | --- |
| **顔画像を共有してしまう**（プライバシー・PLAN 違反） | `serializeRoutine` が `selectAiBlocks`（source 除外済み）だけを直列化。import は `LOAD_ROUTINE` で**取り込み側の source を温存**＝他人の顔は決して入らない／出ない。 |
| **結果 url を共有してしまう**（揮発する S3・約2時間） | `runs` は `Routine` の外（`AppState`）にあるため直列化対象に入らない。`LOAD_ROUTINE` は `runs:{}` で一掃。共有単位はブロック**定義**のみ（[feature-c 完了条件](./feature-c-routine.md#完了条件)の受け渡し契約どおり）。 |
| **外部 JSON は型が効かない**（TS はコンパイル時のみ。`as` で通すと壊れた値が state に侵入） | `parseRoutine` が**実行時の型ガード**（`isObject`・`kind` 分岐・enum 照合）を1か所に持つ。state に入れる前に必ず通す。`api/` のエラー整形に相当する「外部入力の番人」を domain 側に置く。 |
| **enum ドリフト**（未知 category / 未知 kind / SD・HD 混在） | `ALL_CATEGORIES` 照合＋`validateEffects`／`validateSkin` を**再利用**（機能B/E の正本を二重定義しない）。混在・未選択は読めるメッセージで弾く。 |
| **`template_id` が取り込み側の手元マニフェストに無い**（ローカルは全カタログの部分集合） | import では **look を弾かない**（templateId を保持）。`LookEditor` 側で「一覧に無い→未選択扱い・選び直し」を促す（実行前の `validateLook` が最終的に未選択を弾く）。 |
| **id 衝突 / 古い runs の取り違え** | import 時に `crypto.randomUUID()` で全ブロックの `id` を再発行。`LOAD_ROUTINE` が `runs:{}` を張り直すので、新 id に古い結果がぶら下がらない。 |
| **破壊的な置き換え**（import は現ルーティンを上書き） | UI で確認を挟む。`LOAD_ROUTINE` は source 温存なので、誤爆しても顔写真設定は消えない。 |
| **バージョン非互換**（将来スキーマを変えたとき） | `app` マジック＋`version` を封筒に持たせ、`parseRoutine` が不一致を**読めるエラーで弾く**（黙って誤パースしない）。変換が要るようになったらここが分岐点。 |
| **クリップボード API がブロックされる**（権限/HTTP） | コピーは best-effort。失敗時はダウンロード経路へ誘導（`<a download>` は権限不要）。 |

## 完了条件

- **エクスポート**: makeup / look / skin を混在させたルーティンを `routine.json` として書き出せる。中身を開くと **source（顔画像）も結果 url も含まれず**、`{ app, version, execution, blocks }` だけがある。
- **インポート（同一セッション）**: 書き出した JSON を読み込むと、**ブロックの並び・各設定・`execution` が復元**される。`SourcePanel` の自分の顔指定はそのまま残る。
- **インポート（別の顔で再生）**: 他人の JSON を取り込み → **自分の顔を指定**して `RoutinePanel` で実行 → 自分の顔に同じルーティンが適用される（＝本 POC の中核価値の実証）。
- **ラウンドトリップ**: export → import で**論理的に同一**のルーティンになる（`id` の差を除く）。
- **エラー導線**: 壊れた JSON・別アプリの JSON・未知 category / kind・SD/HD 混在・version 不一致は、**どこが不正かを示す読めるメッセージ**で弾かれ、アプリは落ちない。state は不正値で汚れない。

## 着手前に確認したいこと（実装中に潰す）

- [ ] **export の取り出し方式**（ファイルダウンロードのみで足りるか、クリップボードコピー／貼り付け textarea も要るか）。POC は**ダウンロード＋コピー＋貼り付け**の三点で十分か。
- [ ] **import の意味検証の強さ**: 構造は必ず弾く方針で確定。**意味検証（パターン未選択・色形式・未収載 template_id）は import で弾くか、取り込み後の実行前 `validate*` に委ねるか**（本書の既定: makeup/skin は import で弾く＝早期に気づける、look の未選択/未収載は実行前に委ねる）。この線引きの最終確認。
- [ ] **id 再発行の是非**: 再発行（衝突回避・推奨）か、共有元の id を保持（差分比較しやすい）か。
- [ ] **`version` の前方互換ポリシー**: 将来 version 2 を出したとき、version 1 を**変換して読む**か**弾く**か（POC は弾くで十分か）。
- [ ] **`title` の扱い**: 共有に含める（既定）か、取り込み側で付け直すか。空 title の補完規則。

## 再利用できる既存資産（機能A〜E で実装済み）

| 資産 | 場所 | 機能F での使い方 |
| --- | --- | --- |
| `AiBlock`（makeup|look|skin の判別共用体）／各ブロック型 | [domain/blocks.ts](../../src/domain/blocks.ts) | **そのまま共有単位**。`SharedRoutine.blocks` の要素型。各機能が「JSON 化可能に保つ」と決めてきた配当を回収。 |
| `ALL_CATEGORIES` / `SKIN_ACTIONS` | [domain/blocks.ts](../../src/domain/blocks.ts) | import の enum 照合（未知 category／dst_actions 系統）。 |
| `validateEffects` / `validateLook` / `validateSkin` | [domain/blocks.ts](../../src/domain/blocks.ts) | import の**意味検証を委譲**（色形式・パターン／テンプレ未選択・SD/HD 混在）。正本を二重定義しない。 |
| `Routine`（`{ blocks, execution }`）／`runs` が外にある構造 | [state/appState.ts](../../src/state/appState.ts) | export は `Routine` を直列化、`runs` は構造上自然に除外。`LOAD_ROUTINE` が `Routine` を組み替え。 |
| `selectAiBlocks` / `selectSource` / `createSourceBlock` | [state/appState.ts](../../src/state/appState.ts) | export は AI ブロックのみ取得、import は source を温存（無ければ新規）。 |
| `MakeupEditor` / `LookEditor` / `SkinEditor` / `RunPanel` / `RoutinePanel` | [components/](../../src/components/) | import 後の編集・実行は**既存導線にそのまま乗る**（機能F 専用の実行 UI は作らない）。 |
| `SourcePanel`（自分の顔の指定） | [components/SourcePanel.tsx](../../src/components/SourcePanel.tsx) | 「取り込み → 自分の顔を指定 → 実行」の自分の顔を担う既存パネル。 |
