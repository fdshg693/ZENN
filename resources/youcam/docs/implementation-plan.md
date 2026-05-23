# 実装案 — 化粧ルーティン共有 POC

[PLAN.md](../PLAN.md)（提供機能と利用 API）を、**動くアプリの設計**に落とし込んだもの。
PLAN が「何を・どの API で」なら、本書は「**どう作るか**」を担当する。

設計方針は [README.md](../README.md) のスコープに従う:
**サーバを持たない静的サイト / ユーザーが自分の API キーを入力 / 描画品質や運用堅牢性は対象外**。
そのうえで本案では **「デバッグしやすさ・コード理解のしやすさ」を最優先**にし、
レイヤ分割・型による仕様の明文化・適切な粒度のコメントを徹底する。

---

## 1. 技術選定

| 項目 | 選定 | 理由（=つまりどころを減らす / デバッグしやすい） |
| --- | --- | --- |
| 言語 | **TypeScript** | API の入れ子 JSON（`effects` / `palettes` / `dst_actions`）を**型で明文化**できる。仕様がコードに乗るので理解・デバッグが速い。 |
| ビルド/開発 | **Vite** | 設定ほぼ不要・HMR が速い。**`server.proxy` で CORS 問題を開発時に回避**できる（後述のつまりどころ対策に直結）。 |
| UI | **React** | 「ルーティン = ブロックの並び」をコンポーネントとリストへ素直に1:1対応できる。状態が追いやすい。 |
| 状態管理 | **React `useReducer` + Context** のみ | 外部ライブラリ無し。状態遷移を1ファイルに集約でき、ブロック追加/並べ替え/実行の流れを1か所で追える。 |
| スタイル | **素の CSS Modules** | 凝らない（README のスコープ外）。最低限の可読性だけ確保。 |

> いずれも「枯れていて落とし穴が少ない」構成。新規ライブラリ学習コストや独自設定をほぼ持ち込まない。

---

## 2. 全体アーキテクチャ（レイヤ）

依存は**上から下への一方向のみ**。下位レイヤは UI を知らない＝単体で追える・テストできる。

```
┌─────────────────────────────────────────────┐
│  components/   React UI（見た目とユーザー操作だけ）   │
├─────────────────────────────────────────────┤
│  state/        アプリ状態（ルーティン・APIキー・結果）  │
├─────────────────────────────────────────────┤
│  domain/       ビジネスロジック（フレームワーク非依存）   │
│                ブロック定義 / 実行戦略 / JSON入出力     │
├─────────────────────────────────────────────┤
│  api/          YouCam API クライアント（純粋な fetch 層）│
│                認証・アップロード・ポーリング・型        │
└─────────────────────────────────────────────┘
```

**狙い**: 「API がおかしい」のか「ロジックがおかしい」のか「UI がおかしい」のかを、レイヤ境界で切り分けられる。
不具合時にどのファイルを見ればよいかが構成から自明になる。

---

## 3. ディレクトリ / ファイル構成

各ファイルに**単一の責務**を持たせる。括弧内はそのファイルが答える問い。

```
youcam/
├─ index.html                 # エントリ HTML
├─ vite.config.ts             # ★ dev proxy 設定（CORS 回避）をここに集約
├─ package.json
├─ tsconfig.json
└─ src/
   ├─ main.tsx                # React マウントのみ
   ├─ App.tsx                 # 画面全体のレイアウト・各パネルの配置
   │
   ├─ api/                    # 「YouCam API をどう叩くか」だけを知る層
   │  ├─ types.ts             #   API のリクエスト/レスポンスの型（仕様の正本）
   │  ├─ client.ts            #   fetch ラッパ: 認証ヘッダ・baseURL・エラー整形・429バックオフ
   │  ├─ files.ts             #   File API: file_id 発行 → 署名URLへ PUT 実アップロード
   │  ├─ task.ts              #   汎用タスク: 開始 → ポーリング → 結果(url ＋ 機能により dst_id) を返す
   │  ├─ makeupVto.ts         #   機能B: makeup-vto の開始/結果取得
   │  ├─ lookVto.ts           #   機能D: テンプレ一覧取得 + look-vto 適用
   │  ├─ skinAnalysis.ts      #   機能E: skin-analysis（dst_actions / スコア出力）
   │  └─ catalog.ts           #   パターンカタログ JSON 取得（blush.json 等の label 一覧）
   │
   ├─ domain/                 # 「ルーティンとは何か・どう実行するか」を知る層（UI非依存）
   │  ├─ blocks.ts            #   ブロックの型（source/makeup/look/skin の判別共用体）と既定値
   │  ├─ routine.ts           #   ルーティン実行: 一括方式 / チェイン方式 の戦略（機能C）
   │  └─ routineFile.ts       #   機能F: ルーティンの JSON 入出力（顔画像は除外）+ 妥当性検証
   │
   ├─ state/                  # アプリの「いまの状態」
   │  ├─ appState.ts          #   状態の型・初期値・reducer（追加/削除/並べ替え/実行結果反映）
   │  └─ AppContext.tsx       #   Context + Provider（状態とdispatchを配布）
   │
   └─ components/             # 見た目とユーザー操作（ロジックは持たない）
      ├─ ApiKeyPanel.tsx      #   API キー入力（フロント露出の注意書きも表示）
      ├─ SourcePanel.tsx      #   機能A: 顔写真アップロード or 画像URL指定
      ├─ BlockList.tsx        #   ブロック一覧・並べ替え・追加/削除
      ├─ editors/             #   ブロック種別ごとの編集 UI
      │  ├─ MakeupEditor.tsx  #     機能B: effects カテゴリ・色・質感・パターン選択
      │  ├─ LookEditor.tsx    #     機能D: テンプレ選択
      │  └─ SkinEditor.tsx    #     機能E: dst_actions 選択
      ├─ RunPanel.tsx         #   実行ボタン・進捗（running/success/error）・結果画像表示
      └─ ImportExport.tsx     #   機能F: JSON のエクスポート/インポート UI
```

---

## 4. ドメインモデル（設計の核）

PLAN の各機能を「ブロックの種別」として**判別共用体（discriminated union）**で表す。
`kind` を見れば型が確定するので、編集UI・実行・JSON化のすべてで分岐が安全になる。

```ts
// domain/blocks.ts （抜粋・設計イメージ）

/** ブロック共通の素性。id は実行順・並べ替えの管理キー */
interface BaseBlock {
  id: string;
  kind: BlockKind;
  title: string; // ユーザーが付けられる表示名（例「ベースメイク」）
}

/** 機能A: 起点となる顔画像。共有 JSON には含めない（取り込み側が差し替え） */
interface SourceBlock extends BaseBlock {
  kind: 'source';
  source: { type: 'upload'; fileId?: string } | { type: 'url'; url: string };
}

/** 機能B: makeup-vto の effects そのもの。これが共有の最小単位 */
interface MakeupBlock extends BaseBlock {
  kind: 'makeup';
  effects: MakeupEffect[]; // api/types.ts の型を再利用
}

/** 機能D: 完成ルックを template_id 一発適用 */
interface LookBlock extends BaseBlock {
  kind: 'look';
  templateId: string;
}

/** 機能E: 肌診断。SD/HD はどちらか一方に統一（混在は API エラー） */
interface SkinBlock extends BaseBlock {
  kind: 'skin';
  resolution: 'sd' | 'hd';
  dstActions: string[];
}

type Block = SourceBlock | MakeupBlock | LookBlock | SkinBlock;

/** ルーティン = 起点画像 + 並んだブロック + 実行方式 */
interface Routine {
  blocks: Block[];
  execution: 'bundle' | 'chain'; // 機能C
}
```

---

## 5. API クライアント層の設計（`api/`）

PLAN「0. 共通の土台」をそのままコード化する。**全機能が `File → Task → Poll → Result` の同じ骨格**なので、骨格を `task.ts` に1つ持ち、各機能はパラメータ差分だけを足す。

- **`client.ts`** — 全リクエストの単一窓口。
  - `Authorization: Bearer <key>` 付与、baseURL 連結。
  - レスポンスのエラーコード（`InvalidApiKey` / `CreditInsufficiency` / `error_no_face` 等）を**読めるメッセージ**に整形して投げる（デバッグ直結）。
  - `429` は指数バックオフで自動リトライ（PLAN のレート制限対策）。
- **`files.ts`** — File API の **2段階**を1関数に隠蔽。
  - ① `POST /file/{feature}` で `file_id` と署名 URL を取得 → ② その URL へ実体を **PUT**。
  - 「File API を呼んだだけではアップロードされない」落とし穴をここで吸収する。
- **`task.ts`** — 汎用の非同期タスク実行。
  - `start(feature, body)` → `task_id` → `poll()` が `success`/`error` まで待つ。
  - 戻り値は `{ resultUrl, dstId? }`。**チェイン（機能C）の土台は前タスクの結果 url を次の `src_file_url` に渡すこと**（実機確認: makeup-vto は `dst_id` を返さず、成功レスポンスは `data.results.url`。`dst_id` は skin-analysis 固有の可能性が高く未確認 → 返す機能ではそれも使える）。
  - レスポンスのラッパは **`result` ではなく `data`**（全レスポンス共通・実機確認）。`results` の内側（単体 / 配列、`url` / `download_url`）の揺れは `extractResult` で1か所吸収。
  - **タスクレベルのエラーは HTTP 200**（本文 `data.task_status:"error"` + `data.error`）で返るため client.ts の整形を通らない → task.ts が `describeErrorCode` で読めるメッセージへ変換する。
  - ポーリングは緩い間隔＋全体タイムアウト付き（24時間ウィンドウ内で柔軟に）。

各機能ファイル（`makeupVto.ts` 等）は「どの feature 名・どの body 形か」だけを定義し、実処理は `task.ts` に委譲する。

---

## 6. 主要フロー

### 6-1. ルーティン実行（機能C）

`domain/routine.ts` が2つの戦略を持つ:

- **一括方式 (`bundle`)**: 連続する **makeup ブロックの `effects` を1配列に統合** → makeup-vto を**1タスク**で実行（速い・安い）。
  - ※ 診断/Look は effects に統合できないため、それらを挟む並びでは自動的に chain に切り替える（設計上の安全弁）。
- **チェイン方式 (`chain`)**: ブロックごとに1タスク。前タスクの **結果 url を次タスクの `src_file_url`** に渡す（実機確認: makeup-vto は `dst_id` を返さないため。結果 url は公開 S3・`X-Amz-Expires=7200`＝約2時間有効）。途中経過を表示でき、makeup 以外も挟める。`dst_id` を返す機能（skin-analysis の可能性・未確認）ではそれを使ってもよいよう、入力解決は「`dst_id` があればそれ／無ければ結果 url」と吸収する。

両戦略とも、各ステップの `{status, resultUrl}` を state に逐次反映 → `RunPanel` が進捗と中間/最終画像を描画。

### 6-2. JSON 共有（機能F）

`domain/routineFile.ts`:

- **export**: `Routine` から **SourceBlock を除外**（または `source` を空に）して JSON 化。残りは API ペイロードと対応する設定そのもの。
- **import**: JSON を読み、型・enum（カテゴリ名 / dst_actions の SD・HD 混在チェック）を**検証してから** state へ。壊れた JSON は読めるエラーで弾く。
- → 「他人のルーティンを取り込み、自分の顔だけ差し替えて再生」が成立する。

---

## 7. つまりどころと対策（先回りで潰す）

| つまりどころ（docs で既出） | 対策（どのファイルで吸収するか） |
| --- | --- |
| **CORS**（静的サイトから API 直叩き可否が未検証） | `vite.config.ts` の `server.proxy` で `/api` を `yce-api-01.makeupar.com` に転送。`client.ts` の baseURL を `/api` にすれば**開発時は CORS を完全回避**。本番ホスティングで詰まる場合の唯一の逃げ道もここに集約。 |
| **File API の2段階**（PUT 忘れで 500/404） | `files.ts` が発行と PUT を1関数に内包。呼び側はミスれない。 |
| **レート制限 429** | `client.ts` で指数バックオフ＋リトライ。 |
| **ポーリング**（実行時間が不定） | `task.ts` に緩い間隔＋タイムアウト付きの共通ループ。各機能で再実装しない。 |
| **API キーのフロント露出** | 設計前提として許容（本人キーを本人が使う）。`ApiKeyPanel` に注意書き。保存は localStorage（任意）で、コードコメントにもリスクを明記。 |
| **パターン必須カテゴリ**（blush 等は `pattern.name` 必須・多色は palettes 複数） | `catalog.ts` がカタログ JSON を取得し `label` を選択肢化。`MakeupEditor` は色数ぶんの palettes 入力を強制し、不整合を UI で防ぐ。 |
| **SD/HD 混在エラー** | `SkinBlock.resolution` で一方に固定し、UI で混在不可能にする。 |

---

## 8. 実装ステップ（推奨ビルド順）

各段階で「動く・確認できる」状態を保ちながら積み上げる。

1. **足場**: Vite + React + TS 雛形、`vite.config.ts` の proxy、`api/types.ts` の骨格。
2. **API 疎通**: `client.ts` / `files.ts` / `task.ts` を作り、**makeup-vto を1パーツだけ**手で実行 → 結果画像が出ることを確認（最初の山＝API が通るか）。
3. **機能A+B**: `SourcePanel` と `MakeupEditor`（まずパターン不要カテゴリ: skin_smooth / foundation）を実装。
4. **機能C（一括）**: 複数 effects を1タスクで実行。`RunPanel` に結果表示。
5. **機能F**: JSON の export/import。ここで「共有」の中核価値が動く。
6. **機能C（チェイン）**: 結果 url チェイン（前ステップの url → 次の `src_file_url`）を追加（途中経過表示）。`dst_id` には依存しない。
7. **補助（機能D/E）**: Look VTO・Skin Analysis を追加。パターン必須カテゴリ（blush/lip 等）も `catalog.ts` 経由で拡充。

> 2 が最大の不確実性（CORS / 認証 / アップロード）。**ここを最初に通す**ことで以降の手戻りを防ぐ。

---

## 9. 動作確認の方法

- **API 疎通**: ステップ2の単発実行を「真の動作確認」とする（テストではなく実画像で確認）。
- **ロジック**: `domain/`（実行戦略・JSON入出力）は UI 非依存なので、必要なら最小の単体テスト（Vitest）を後付け可能。まずは手動確認で十分（POC スコープ）。
- **デバッグ動線**: 不具合は「画面 → state → domain → api」の順に1レイヤずつ切り分け。`client.ts` がエラーを整形済みなので、API 起因かどうかは最初に判別できる。

---

## 10. 機能別 実装詳細

セクション 1〜9 が「全体の設計」なら、ここから先は **機能ごとの作り方**を 1 つずつ確定させる。
本書（全体設計）の肥大化を避けるため、各機能の詳細は **[`implementation/`](./implementation/) サブフォルダに 1 機能 = 1 ファイル**で分割している。

- **入口・記述テンプレート・進捗**: [implementation/README.md](./implementation/README.md)
- **機能A: ソース画像の用意**: [implementation/feature-a-source.md](./implementation/feature-a-source.md)
- **機能B: メイクブロックの実行（中核）**: [implementation/feature-b-makeup.md](./implementation/feature-b-makeup.md)
- 機能C〜F: 順次追加（README のインデックス参照）。

> 全体設計（本書）は「レイヤと方針の正本」、`implementation/` 配下は「各機能の手順の正本」という役割分担。
> 迷ったらまず本書のセクション 1〜9 を読み、作る段になって該当機能のファイルを開く。
