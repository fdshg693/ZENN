# PLAN — 提供機能と利用 API

本デモが「何を提供するか」と「どの YouCam API を使うか」だけに集中したプラン。
**アプリ側の実装（UI/フレームワーク/状態管理など）には踏み込まない。** あくまで提供機能と利用 API の定義。

全体像・前提は [README.md](./README.md)、API 仕様の詳細は [docs/](./docs/) を参照。

---

## 0. 共通の土台（全機能に効く）

- すべての AI 機能は **非同期タスク**: `ファイルアップロード → タスク開始(task_id) → ポーリング → 結果URL`。
- 認証は **Bearer トークン1本**（ユーザーが入力した API キー）。サーバ `https://yce-api-01.makeupar.com`。
- ブロックの連結は **前タスクの結果を次の入力に渡すチェイン**で表現する。実機確認では makeup-vto は `dst_id` を返さず成功レスポンスは結果 url（公開 S3）なので、**結果 url を次タスクの `src_file_url` に渡す**のが基本。`dst_id`（出典は Skin Analysis ドキュメント・skin-analysis 固有の可能性）を返す機能ではそれも使える。
- 課金は **成功時のみ** units 消費。ポーリング中・失敗時は非消費。
- **見るべき docs**: [docs/api-basics.md](./docs/api-basics.md)（認証・ワークフロー・`dst_id`・レート制限・エラー・ファイル仕様）。

---

## 1. 提供機能と利便性の範囲

### 機能A: ソース画像の用意

- ユーザーの顔写真をアップロード、または公開画像 URL を指定して、以降のブロックの起点にする。
- **利便性の範囲**:
  - 提供する: File API でのアップロード、または `src_file_url` 直指定の2経路。
  - 提供しない: 撮影 UI の作り込み、画像の自動リサイズ・整形（仕様超過時はエラー表示まで）。
- **利用 API**: 各機能の File API（例 `POST /s2s/v2.0/file/makeup-vto`）。
- **見るべき docs**: [docs/api-basics.md](./docs/api-basics.md) の「共通ワークフロー」「入力ファイルの仕様」。

### 機能B: メイクブロックの実行（中核）

- 「ファンデ」「チーク」「リップ」等の化粧パーツを1ブロックとして指定し、顔に適用する。
- **利便性の範囲**:
  - 提供する: Makeup VTO の `effects` 各カテゴリ（skin_smooth / foundation / concealer / blush / bronzer / contour / highlighter / eyebrows / eye_shadow / eye_liner / eyelashes / lip_color / lip_liner）を指定して適用。色・質感・強度などのパラメータ指定。
  - 提供する: パターンが必要なカテゴリは、カタログ JSON の `label` を選択肢として提示。
  - 提供しない: 独自パターンの作成、API にない化粧表現。
- **利用 API**: `POST /s2s/v2.0/task/makeup-vto` → `GET /s2s/v2.0/task/makeup-vto/{task_id}`。
- **見るべき docs**: [docs/makeup-vto.md](./docs/makeup-vto.md)（effect カテゴリ一覧・必須項目・texture・パターンカタログ JSON・有効ペイロード例）。

### 機能C: ブロックの連結（ルーティンの実行）

- 複数ブロックを順に実行し、一連の手順（ルーティン）として結果を得る。
- **利便性の範囲（2方式のどちらか/両方を提供）**:
  - **一括方式**: 複数パーツを1つの `effects` 配列にまとめ、**1タスク**で適用（速い・安い・途中経過なし）。
  - **チェイン方式**: ブロックごとにタスクを分け、**前タスクの結果 url を次の `src_file_url`** に渡す（途中経過が見える・Makeup 以外の機能も挟める）。実機確認: makeup-vto は `dst_id` を返さないため url 受け渡しが基本。`dst_id` を返す機能ではそれも可。
  - 提供しない: 分岐・条件付き実行などの複雑なフロー（直列の手順のみ）。
- **利用 API**: 機能B/D/E のタスク API ＋ 前タスクの結果 url（`dst_id` を返す機能ではそれも）。
- **見るべき docs**: [docs/api-basics.md](./docs/api-basics.md) の「タスクのチェイン」、[docs/makeup-vto.md](./docs/makeup-vto.md) の「POC への示唆」。

### 機能D: 完成ルックブロック（補助）

- プロ作成の完成ルックを `template_id` 一発で適用する、手軽なブロック。
- **利便性の範囲**:
  - 提供する: テンプレート一覧の取得・選択と、選んだ look の適用。
  - 提供しない: テンプレートのカスタム作成。
- **利用 API**: `GET /s2s/v2.0/task/template/look-vto`（一覧）→ `POST /s2s/v2.0/task/look-vto` → `GET .../look-vto/{task_id}`。
- **見るべき docs**: [docs/feature-catalog.md](./docs/feature-catalog.md)（Look VTO の位置づけ）、リファレンス <https://docs.perfectcorp.com/reference/ai_look_vto>。

### 機能E: 肌診断ブロック（補助）

- ルーティンの起点（Before 診断）として、肌状態をスコア化して表示する。
- **利便性の範囲**:
  - 提供する: `dst_actions` を指定した診断と、`ui_score`/総合点/マスク画像の表示。SD/HD のどちらか一方に統一。
  - 提供しない: 医療的な診断・処方、SD と HD の混在（API 仕様上不可）。
- **利用 API**: `POST /s2s/v2.0/task/skin-analysis` → `GET .../skin-analysis/{task_id}`（v2.1 も可）。
- **見るべき docs**: [docs/skin-analysis.md](./docs/skin-analysis.md)（dst_actions・出力スコア構造・撮影条件）。

### 機能F: ルーティンの保存・共有（JSON）

- 組んだルーティンを JSON でエクスポート/インポートする。他人の JSON を取り込み、自分の顔で再生する。
- **利便性の範囲**:
  - 提供する: ルーティン定義（使用機能・各ブロックの設定・順序）の JSON 入出力。**ソース画像は共有対象に含めない**（取り込み側が自分の顔を指定）。
  - 提供しない: 共有リンク発行・アカウント・サーバ保存（import/export のみ）。
- **利用 API**: なし（クライアント内の JSON 操作）。ただし JSON の中身は機能B〜Eのリクエスト設定に対応させる。
- **見るべき docs**: [docs/makeup-vto.md](./docs/makeup-vto.md)（`effects` JSON がそのまま共有単位になる点）、[README.md](./README.md) の提供価値。

---

## 2. 利用 API 早見表

| 機能 | エンドポイント（タスク開始 → ポーリング） | 主な docs |
| --- | --- | --- |
| ファイル準備 | `POST /s2s/v2.0/file/{feature}` | [api-basics.md](./docs/api-basics.md) |
| メイク適用 | `POST /s2s/v2.0/task/makeup-vto` → `GET .../{task_id}` | [makeup-vto.md](./docs/makeup-vto.md) |
| 完成ルック | `GET /s2s/v2.0/task/template/look-vto` / `POST /s2s/v2.0/task/look-vto` → `GET .../{task_id}` | [feature-catalog.md](./docs/feature-catalog.md) |
| 肌診断 | `POST /s2s/v2.0/task/skin-analysis` → `GET .../{task_id}` | [skin-analysis.md](./docs/skin-analysis.md) |
| ブロック連結 | 上記タスク + 前タスクの結果 url を次の `src_file_url` へ（`dst_id` を返す機能ではそれも可） | [api-basics.md](./docs/api-basics.md) |

> パターンカタログ JSON（blush.json / eyeshadow.json / lipshape.json 等）は [makeup-vto.md](./docs/makeup-vto.md) にURL一覧。

---

## 3. 実装時に docs をどう見るか（参照フロー）

実装で迷ったら、この順で docs を引く:

1. **まず全体像** → [docs/README.md](./docs/README.md)（30秒サマリ・このPOCとAPIの対応）。
2. **どの機能を使う？** → [docs/feature-catalog.md](./docs/feature-catalog.md)（機能一覧と各リファレンスURL）。
3. **共通の叩き方（認証/アップロード/ポーリング/チェイン/エラー）** → [docs/api-basics.md](./docs/api-basics.md)。
4. **メイクのパラメータ詳細（カテゴリ・色・質感・パターン）** → [docs/makeup-vto.md](./docs/makeup-vto.md)。
5. **肌診断の項目・出力** → [docs/skin-analysis.md](./docs/skin-analysis.md)。
6. **docs に無い細部（リクエスト/レスポンスの全フィールド）** → 各 docs に貼った **公式リファレンスURL**（末尾に `.md` を付けると Markdown 版が取れる）か、API Playground で実挙動を確認。

> docs に載っていない最新仕様・エッジケースは、公式の Changelog（<https://docs.perfectcorp.com/release/changelog>）と各リファレンスの最新版を正本とする。

---

## 4. 未確定・実装前に確認すべき API 上の前提

機能ではなく「API の使い方」に関する未確認事項（[README.md](./README.md) スコープ外と重複するが、API 観点で再掲）:

- **ブラウザからの直叩き（CORS）**: 静的サイトから `yce-api-01.makeupar.com` を直接叩けるか。Playground は `xhr.withCredentials = true` を使う例あり。要検証。
- **チェインの実挙動**: 実機確認で makeup-vto は `dst_id` を返さない（→ 結果 url を `src_file_url` に渡すチェインで対応済みの方針）。残る未確認は ①結果 S3 url を `src_file_url` に渡してサーバ間取得が通るか、②skin-analysis / look-vto が `dst_id` を返すか、③機能をまたいだチェイン（例: skin-analysis → makeup-vto）がどこまで通るか。
- **units 消費単位**: ブロック数ぶん消費するのか、一括 `effects` なら1回かなど、課金粒度。
- これらは [docs/api-basics.md](./docs/api-basics.md) と API Playground / コンソールで確認する。
