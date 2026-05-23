# 機能A: ソース画像の用意

> [実装詳細インデックス](./README.md) / [全体設計](../implementation-plan.md) / [PLAN.md](../../PLAN.md)（機能A の定義）

以降の全ブロックの**起点となる顔画像**を確定する機能。ルーティンの「入力」を作るだけで、API の AI 処理（タスク）は呼ばない。
ここを薄く・確実に作ることが、後続の機能B〜Eのデバッグを楽にする（「入力は正しいのに結果が変」の切り分けが効く）。

## 目的 / スコープ

- **提供する**: 2 経路で起点画像を指定できる。
  - ① **アップロード**: ローカルの顔写真を選び、File API 経由でタスクに渡せる状態にする。
  - ② **URL 指定**: 公開アクセス可能な画像 URL をそのまま `src_file_url` として使う（File API を経由しない近道）。
- **提供しない**: 撮影 UI、画像の自動リサイズ・整形・圧縮。**ファイル仕様を超えた場合はエラー表示で止める**（直さない）。
- **共有との関係（機能F）**: ソース画像は**共有 JSON に含めない**。取り込み側が自分の顔に差し替える前提なので、`SourceBlock` はエクスポート対象外（全体設計 [6-2](../implementation-plan.md#6-2-json-共有機能f)）。

## 担当ファイル

| ファイル | 役割 | レイヤ |
| --- | --- | --- |
| `components/SourcePanel.tsx` | 2 経路の選択 UI・プレビュー・入力検証メッセージ表示 | components |
| `domain/blocks.ts` | `SourceBlock` の型と既定値 | domain |
| `api/files.ts` | File API の 2 段階（発行 → PUT）を 1 関数に内包 | api |
| `api/types.ts` | File API のリクエスト/レスポンス型 | api |
| `state/appState.ts` | ソース選択を状態へ反映する action | state |

## データ（型）

ここで全体設計 [セクション4](../implementation-plan.md#4-ドメインモデル設計の核) の `SourceBlock` スケッチを**1点だけ精緻化**する。理由が重要なので明記する。

> **`file_id` は feature 単位で発行される**（`POST /file/makeup-vto` と `POST /file/skin-analysis` は別物）。
> したがって `SourceBlock` に `fileId` を 1 つ持たせると、最初に実行する機能が変わるたびに無効化される“漏れた”状態になる。
> **対策**: 編集時点では**ローカルの `File` 実体（とプレビュー用 URL）だけ**を保持し、`file_id` の発行は**実行時に「先頭タスクの feature」が確定してから**行う（必要なら feature ごとにキャッシュ）。

```ts
// domain/blocks.ts （機能A: 精緻化版）

/** 機能A: 起点となる顔画像。AIタスクは持たず「入力の指定」だけを表す。 */
interface SourceBlock extends BaseBlock {
  kind: 'source';
  source:
    // ① アップロード経路: 編集時は File 実体を保持。file_id は実行時に発行（feature依存のため）。
    | { type: 'upload'; file: File; previewUrl: string }
    // ② URL 経路: そのまま src_file_url に使える。File API 不要。
    | { type: 'url'; url: string };
}
```

```ts
// api/types.ts （File API の型 = 仕様の正本）

/** File API 開始リクエスト。寸法・サイズは送らず、メタのみ（実体は後段の PUT）。 */
interface FileCreateRequest {
  files: { content_type: string; file_name: string; file_size: number }[];
}

/** File API レスポンス。requests[].url が「実体を PUT する事前署名 URL」。 */
interface FileCreateResponse {
  result: { file_id: string; requests: { url: string; headers?: Record<string, string> }[] }[];
}
```

## 処理フロー

ソース指定は「いつ何が起きるか」を 2 フェーズに分けると追いやすい。

1. **編集フェーズ（SourcePanel 上の操作）** — API は呼ばない。
   - **upload**: ファイル選択 → クライアント側で**仕様の事前チェック**（拡張子 jpg/jpeg/png、`file.size < 10MB`）→ `URL.createObjectURL` でプレビュー → `SourceBlock.source = { type:'upload', file, previewUrl }` を state へ。
   - **url**: 文字列入力 → 形式の軽い検証（`https?://`）→ `SourceBlock.source = { type:'url', url }` を state へ。
2. **実行フェーズ（機能Cの実行時に解決）** — ここで初めて API に触れる。
   - `source.type === 'url'` → タスク body に **`src_file_url`** を渡す。File API は不要。
   - `source.type === 'upload'` → 先頭タスクの feature を引数に `files.ts` の `uploadFile(feature, file)` を呼び、**`file_id` を得てから** body に **`src_file_id`** を渡す。

```ts
// api/files.ts — File API の「2段階」を1関数に隠蔽（呼び側はミスれない）
//   ① POST /file/{feature} で file_id と署名URLを取得
//   ② その URL に File 実体を PUT（←これを忘れると後続タスクが 500/404）

async function uploadFile(feature: string, file: File): Promise<string> {
  // ① メタを送って file_id と PUT 先 URL を発行
  const res = await client.post<FileCreateResponse>(`/s2s/v2.0/file/${feature}`, {
    files: [{ content_type: file.type, file_name: file.name, file_size: file.size }],
  });
  const { file_id, requests } = res.result[0];

  // ② 実体を PUT。ここまでやって初めて「アップロード済み」になる。
  await fetch(requests[0].url, {
    method: 'PUT',
    headers: { 'Content-Type': file.type, ...(requests[0].headers ?? {}) },
    body: file,
  });

  return file_id; // ← 呼び側（実行フェーズ）が src_file_id として使う
}
```

## UI（`SourcePanel.tsx`）

- 経路をタブ/ラジオで切替（**アップロード ⇄ URL**）。同時指定は不可（どちらか一方が起点）。
- 選択後は**プレビュー画像**を必ず表示（`previewUrl` か URL 文字列）。「何を起点にするか」を目で確認できることが、後続の結果ズレ調査の起点になる。
- 仕様外入力（サイズ超過・非対応形式・空 URL）は**その場で読めるメッセージ**を出す（API に投げる前に弾く）。
- ロジックは持たない。検証ロジックは `domain` 側のヘルパに置き、コンポーネントは表示と dispatch のみ。

## つまりどころ

| 落とし穴 | 吸収する場所 |
| --- | --- |
| **File API の PUT 忘れ**（発行だけで未アップロード → タスクが 500/404） | `files.ts` の `uploadFile` が発行と PUT を 1 関数に内包。呼び側が分割呼び出ししない。 |
| **`file_id` の feature 依存**（最初に実行する機能が変わると無効） | 編集時は `File` 実体だけ保持し、`file_id` は実行時に feature を指定して発行（上記データ設計）。 |
| **ファイル仕様超過**（長辺 < 1920・顔幅 >= 100px・< 10MB・jpg/png） | サイズ/形式は `SourcePanel` で事前チェック。寸法・顔幅は API 側の `error_*` を `client.ts` が整形して表示（POC は自動リサイズしない）。 |
| **CORS（署名 URL への PUT / URL 画像の取得）** | API 呼び出しは `vite.config.ts` の dev proxy 経由（全体設計 [セクション7](../implementation-plan.md#7-つまりどころと対策先回りで潰す)）。署名 URL への PUT はオブジェクトストレージ直叩きになる点に留意し、詰まれば proxy 対象を見直す。 |
| **`error_no_face` / `error_multiple_people`** | 機能Aでは検知できない（顔解析は AI タスク側）。実行時に `client.ts` が整形したメッセージを `SourcePanel` 付近へ表示する導線だけ用意。 |

## 完了条件

- アップロード経路: ローカル画像を選ぶと**プレビューが出る**／仕様外ファイルは**実行前にエラー表示**で弾ける。
- URL 経路: 公開画像 URL を入れるとプレビューが出て、実行フェーズで `src_file_url` として渡る。
- いずれの経路でも、機能B（`feature-b-makeup.md` で記述予定）の単発実行に**そのまま入力として渡せる**状態になっている。
  → これが「機能A 完了」の観測可能な基準であり、全体設計 [セクション8](../implementation-plan.md#8-実装ステップ推奨ビルド順)のステップ3の前半に対応する。
