# YouCam API 調査メモ（POC 用）

> 目的: 本リポジトリの POC（化粧ルーティンをブロックで繋いでドライラン・共有する静的サイト）に必要そうな
> YouCam API（Perfect Corp.）の機能と特性を、**おおまかな全体像** として把握するためのメモ。
> 詳細は各セクションの「公式ドキュメント」リンクから辿れるようにしてある。完全網羅はしていない。

調査日: 2026-05-23 / API バージョン: v1.11.1（公式 Introduction より）

## ドキュメント一覧

| ファイル | 内容 |
| --- | --- |
| この README | 全体像・共通の仕組み・POC との対応づけ |
| [api-basics.md](./api-basics.md) | 認証・共通ワークフロー（File→Task→Poll）・サーバ・レート制限・Webhook・エラー |
| [feature-catalog.md](./feature-catalog.md) | 利用可能な AI 機能の一覧（カテゴリ別）と各リファレンス URL |
| [makeup-vto.md](./makeup-vto.md) | Makeup VTO の effect スキーマ（化粧の各パーツ）・パターンカタログ。**POC の中核** |
| [skin-analysis.md](./skin-analysis.md) | Skin Analysis（肌診断）の入出力・スコア構造 |

## 公式の入り口

- 開発者ドキュメント（メイン）: <https://docs.perfectcorp.com/develop/introduction>
  - **どのページも末尾に `.md` を付けると Markdown 版が取れる**（LLM/調査向け。例: `.../develop/introduction.md`）
  - 「Open in ChatGPT / Open in Claude」リンクもページ上部にある
- 概要ドキュメント（別ホスト）: <https://yce.perfectcorp.com/document/index.html>
- API コンソール（アカウント・APIキー・課金・Webhook 管理・Playground）: <https://yce.makeupar.com/>
  - APIキー: <https://yce.makeupar.com/api-console/en/api-keys/>
  - API Playground: <https://docs.perfectcorp.com/develop/api_playground>
- リリースノート / Changelog: <https://docs.perfectcorp.com/release/changelog>
- 問い合わせ先: YouCamOnlineEditor_API@perfectcorp.com

## 30秒で分かる全体像

- **標準的な REST API**。サーバは `https://yce-api-01.makeupar.com`。
- 認証は **Bearer トークン**（APIキー1本）。`Authorization: Bearer YOUR_API_KEY`。
- ほぼ全機能が **非同期タスク**: ①ファイルアップロード → ②タスク開始（`task_id` が返る）→ ③ステータスをポーリング（or Webhook）→ ④結果画像 URL を取得。
- 課金は「units（クレジット）」消費。**成功時のみ消費**、エラー時やポーリング中は消費されない。
- 結果は **24時間** 保持。
- 公式 **MCP サーバ** があり、Claude/Cursor/VS Code から直接 API を叩ける（後述）。

## この POC との対応づけ

README の構想（複数操作をブロックで繋いで実行・JSON で共有）と API 特性の対応:

- **「ブロックを繋いで連続実行」**
  → 各タスク成功時のレスポンスに `dst_id` が含まれ、**結果画像を再アップロードせず次の AI タスクの入力にできる**（タスクのチェイン）。
  ルーティン＝タスクのチェイン、と素直にマッピングできる。詳細は [api-basics.md](./api-basics.md) の「タスクのチェイン」。
- **「化粧ルーティンのドライラン」**
  → [makeup-vto.md](./makeup-vto.md) の `effects` 配列がまさに「化粧の手順・パーツの集合」。1リクエストで複数パーツ（ファンデ→チーク→リップ…）をまとめて適用できる。
- **「他人のルーティンを共有して自分の顔で試す」**
  → ルーティンを「`effects` JSON ＋ 使用機能 ＋ template_id 等」として保存すれば、ソース画像（自分の顔）だけ差し替えて再実行できる。**共有形式 ≒ API ペイロードの JSON** にできるので、README が想定する「シンプルな JSON インポート/エクスポート」と相性が良い。
- **「キュレーション済みの完成ルック」** を使いたい場合
  → Makeup VTO（自分で各パーツ指定）の他に **Look VTO**（プロ作成の完成ルックを `template_id` 一発適用）がある。POC では「自由ブロック＝Makeup VTO」「お手軽プリセット＝Look VTO」と使い分け可能。

## POC で特に効きそうな API（優先度メモ）

1. **AI Makeup Virtual Try-On** — ルーティンの中核。各化粧パーツを細かく指定。 → [makeup-vto.md](./makeup-vto.md)
2. **AI Look Virtual Try-On** — 完成ルックをテンプレ一発適用。手軽な共有用。 → リファレンス: <https://docs.perfectcorp.com/reference/ai_look_vto>
3. **AI Skin Analysis** — 肌診断。ルーティンの「Before/診断」ブロックに。 → [skin-analysis.md](./skin-analysis.md)
4. その他（ヘアカラー・ネイル・アクセサリ等）はインパクト次第で追加。 → [feature-catalog.md](./feature-catalog.md)

## 注意・未確認事項（深掘りが必要になったら見るところ）

- **units（課金）の具体的な単価・無料枠** は未確認。API コンソールの課金画面と公式の料金ページで要確認。
- **CORS**: 本 POC は「サーバを立てずブラウザから直接 API」を想定しているが、ブラウザから `yce-api-01.makeupar.com` を直接叩けるか（CORS 許可・APIキーのフロント露出リスク）は未検証。Playground は `xhr.withCredentials = true` を使う例が出ている。要 PoC 検証。
- **APIキーのフロントエンド露出**: 静的サイトで APIキーをユーザーが入力する設計のため、キーがブラウザに乗る点はセキュリティ上の前提として明記しておくこと（本人のキーを本人が使う分には許容、という整理）。
- 各機能ごとに対応バージョン（v1.0 / v2.0 / v2.1 等）があるので、実装時はリファレンスの最新版を確認。
