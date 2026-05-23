# API の基本（認証・共通ワークフロー・運用）

POC を組む上で、ほぼ全ての機能に共通する仕組み。個別機能は [feature-catalog.md](./feature-catalog.md) 参照。

公式:
- Introduction: <https://docs.perfectcorp.com/develop/introduction>
- Quick Start Guide: <https://docs.perfectcorp.com/develop/quick_start_guide>
- API Server: <https://docs.perfectcorp.com/develop/api_server>

## サーバ / 認証

- **ベース URL**: `https://yce-api-01.makeupar.com`
- パスは `/s2s/v2.0/...`（機能・バージョンにより v2.0 / v2.1 など）
- **認証**: Bearer トークン（APIキー1本）。`Bearer` と キーの間に半角スペースが必要。
  ```
  Authorization: Bearer YOUR_API_KEY
  Content-Type: application/json
  ```
- APIキーの発行・管理: <https://yce.makeupar.com/api-console/en/api-keys/>
- 認証エラーコード: `InvalidApiKey` / `InactiveApiKey` / `ExpiredApiKey`（401）

## 共通ワークフロー（File → Task → Poll → Result）

ほぼ全ての AI 機能が **非同期タスク** として動く。Quick Start: <https://docs.perfectcorp.com/develop/quick_start_guide.md>

1. **ファイル準備（File API）**
   - 例: `POST /s2s/v2.0/file/{feature}`（`{feature}` は `makeup-vto`, `skin-analysis` 等）
   - リクエストに `content_type` / `file_name` / `file_size` を渡す
   - レスポンスで **`file_id`** と **アップロード先の事前署名 URL（`requests[].url`, PUT）** が返る
   - **重要**: File API を呼ぶだけではアップロードされない。返ってきた URL に対し **別途 PUT で実体をアップロード** する必要がある。
     （未アップロードのまま AI タスクを呼ぶと 500 `unknown_internal_error` / 404 になる）
   - **代替**: 公開アクセス可能な画像 URL を持っているなら、File API を飛ばして直接タスクに `src_file_url` を渡せる
2. **タスク開始**
   - 例: `POST /s2s/v2.0/task/{feature}`
   - ボディに `src_file_id` か `src_file_url`、加えて機能ごとの設定（makeup なら `effects`、skin なら `dst_actions` 等）
   - レスポンスで **`task_id`** が返る（24時間有効）
3. **ステータス確認（ポーリング）**
   - 例: `GET /s2s/v2.0/task/{feature}/{task_id}`
   - `data.task_status` が `running`（処理中）→ `success` / `error` になるまで繰り返す
   - **ポーリング中は units を消費しない**。実行時間は保証されないので必ずポーリングが必要
   - 短間隔でなくてよい。24時間のウィンドウ内なら柔軟な間隔で OK
4. **結果取得**
   - `success` 時、`data.results.url`（または `download_url`）に結果画像 URL（公開 S3・`X-Amz-Expires=7200`＝約2時間有効）
   - 加えて **`dst_id`** が返る機能では、これを次のタスクの入力にできる（再アップロード不要 → 下記チェイン）
   - ⚠️ **実機確認**: dst_id は全機能共通ではない。**makeup-vto は `dst_id` を返さず**、成功レスポンスは `data.results`（単体 `{ url }`）のみ。dst_id の出典は下記のとおり Skin Analysis ドキュメントで、**skin-analysis 固有の可能性が高い**（look-vto は未確認）。
   - ⚠️ **実機確認**: タスクレベルのエラー（`error_no_face` 等）は **HTTP 200** で `data.task_status:"error"` + `data.error` として返る（HTTP エラーにはならない）。

ポーリングのサンプル実装（Look VTO の例、JS）は公式リファレンスにそのまま動く形で載っている:
<https://docs.perfectcorp.com/reference/ai_look_vto>

## タスクのチェイン（★ POC のブロック連結に直結）

チェインには2通りの繋ぎ方がある。**実機確認の結果、機能によってどちらが使えるかが異なる**:

- **結果 url を次の `src_file_url` に渡す**（汎用・makeup-vto で確認済みの方法）。
  - makeup-vto は `dst_id` を返さないため、成功レスポンスの結果 url（公開 S3・約2時間有効）を次タスクの `src_file_url` に渡してチェインする。
  - サーバ間取得なので CORS は不要のはず（要実機確認）。url は揮発するため長時間空くチェインには不向き。
- **`dst_id` を次の AI タスクのソースとして渡す**（dst_id を返す機能のみ）。
  - これなら結果画像をダウンロード／再アップロードせずに繋げられる。**ただし出典は下記のとおり Skin Analysis ドキュメントで、skin-analysis 固有の可能性が高い**（makeup-vto では返らないことを確認済み。look-vto は未確認）。
- → どちらでも「肌診断 → ファンデ → チーク → リップ …」のような **ルーティン（ブロックの連鎖）** を表現できる。実装は「`dst_id` があればそれ／無ければ結果 url を `src_file_url`」と吸収しておくと両対応になる。
- 出典（dst_id）: Skin Analysis ドキュメント内「a dst_id that allow you to chain another AI task without re-upload the result image」
  <https://docs.perfectcorp.com/reference/ai_skin_analysis.md>

## 課金（units）

- 各 AI タスクは **units（クレジット）** を消費する。
- **成功時のみ消費**。クエリエラー・エンジンエラー・ポーリング中・タスク失敗時は消費されない。
- 消費時は **有効期限が近い units から優先消費**（同日付なら取得が古い順）。
- `CreditInsufficiency`（400）= units 不足。
- 単価・無料枠・サブスクは API コンソールの課金画面で確認（本メモでは数値を持たない）: <https://yce.makeupar.com/api-console/en/api-keys/>

## レート制限

出典: <https://docs.perfectcorp.com/develop/rate_limit.md>

- **IP アドレス単位**: 300秒あたり最大 250 リクエスト、5 QPS
- **アクセストークン単位**: 300秒あたり最大 250 リクエスト、5 QPS
- 両条件を満たす必要があり、超過すると `429 Too Many Requests`
- → バックオフ＋リトライを実装すること

## Webhook（ポーリングの代替）

出典: <https://docs.perfectcorp.com/develop/webhook>

- タスク完了（`success`/`error`）を **HTTPS エンドポイントに POST 通知** できる。ポーリング不要にできる。
- [Standard Webhooks 仕様](https://github.com/standard-webhooks/standard-webhooks) 準拠。署名検証は **HMAC-SHA256**（secret は `whsec_` プレフィックス＋base64）。
- ヘッダ: `webhook-id`（冪等性キー）/ `webhook-timestamp` / `webhook-signature`
- ボディ `data`: `task_id`, `task_status`
- コンソールで最大 **10 エンドポイント** 登録可。管理画面: <https://yce.makeupar.com/api-console/en/webhook/>
- **POC では静的サイト＝受信サーバが無いので、基本はポーリングを使う想定**（Webhook は将来の発展用メモ）。

## 入力ファイルの仕様

機能ごとに上限が異なるので各リファレンスの "File Specs & Errors" を要確認。代表例:

| 機能 | 寸法 | サイズ | 形式 |
| --- | --- | --- | --- |
| Makeup VTO | 長辺 < 1920, 顔幅 >= 100px | < 10MB | jpg/jpeg/png |
| Look VTO | 長辺 < 1920, 顔幅 >= 100px | < 10MB | jpg/jpeg/png |
| Skin Analysis (SD) | 長辺 <= 4096, 短辺 >= 480 | < 10MB | jpg/jpeg/png |
| Skin Analysis (HD) | 長辺 <= 4096, 短辺 >= 1080 | < 10MB | jpg/jpeg/png |

- 全体の対応フォーマット/寸法: <https://docs.perfectcorp.com/develop/supported_formats>
- ファイル保持期間: <https://docs.perfectcorp.com/develop/file_retention_period>（タスク結果は 24時間）

## エラーコード

- 共通エラーコード一覧: <https://docs.perfectcorp.com/develop/error_codes>
  - 代表例: `error_no_face`(顔なし), `error_multiple_people`(複数人), `error_nsfw_content_detected`, `exceed_max_filesize`, `error_large_face_angle`, `unknown_internal_error`
- HTTP/タスク系: `InvalidTaskId`(404), `InvalidApiKey`(401), `TaskTimeout`(500, 保持期間切れ), `CreditInsufficiency`/`InvalidParameters`/`BadRequest`(400)
- 顔系の典型: `error_face_position_invalid`, `error_face_position_too_small`, `error_face_angle_invalid`（正面は ±10°以内 等）
- デバッグガイド: <https://docs.perfectcorp.com/develop/debugging_guide>
- FAQ: <https://docs.perfectcorp.com/develop/faq>

## MCP サーバ（参考 / 開発効率化）

- 公式 MCP サーバがあり、MCP 互換クライアント（Cursor / VS Code Copilot / Claude for Desktop）から
  APIキーを設定するだけで全 YouCam AI 機能（skin analysis, VTO, hair, fashion 等）を呼べる。
- 認証・リクエスト整形・非同期ポーリングをクライアント側が抽象化してくれる。
- 出典: <https://docs.perfectcorp.com/develop/mcp>
- POC 実装そのものには不要だが、API 挙動の素振り・検証に便利。
