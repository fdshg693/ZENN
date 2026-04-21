---
title: "VSCodeリリースノートで追うGitHub Copilot進化史 (v1.86 → v1.116)"
emoji: "🕰"
type: "tech"
topics: ["vscode", "githubcopilot", "ai", "llm"]
published: false
---

## はじめに

GitHub Copilot は 2024 年から 2026 年にかけて、**「補完を出すアシスタント」から「VSCode に標準同梱されるエージェント基盤」**へと姿を変えました。しかし、普段使いしていると「Agent Mode っていつからあったっけ」「Copilot Edits と Agent は何が違うんだっけ」と、機能の来歴が分からなくなります。

公式ドキュメントは基本的に「現時点で使える機能」を前提に書かれていて、時系列の進化はほとんど追えません。そこで本記事では、VSCode のリリースノート **v1.86 (2024 年 1 月) から v1.116 (2026 年 4 月)** の 31 バージョンから Copilot 関連の記載だけを抽出し、1 本の年表に圧縮します。

興味深い副産物として、**リリースノートに占める Copilot 関連の比率そのものが進化を物語ります**。2024 年前半は「Contributions to extensions」の 1 項目だった Copilot は、2026 年には VSCode 本体リリースの主題になり、v1.116 でついにビルトイン化されました。

対象読者:

- Copilot を日常的に使っているが、どの機能がいつ入ったか把握していない人
- Inline Chat / Chat / Edits / Agent Mode / MCP の関係を時系列で整理したい人

扱わないこと: 料金プランの詳細、GitHub.com 側の機能、他 IDE 版 Copilot、ロードマップ。

:::message
各バージョンの記述は、[公式リリースノート](https://code.visualstudio.com/updates)から Copilot 関連箇所のみを選別したものです。全機能の網羅を目的とした資料ではありません。
:::

## 1. 2024 年前半 (v1.86〜v1.91) — Inline Chat 定着期

> **概要**: 主戦場は「エディタ内 Inline Chat」。コンテキスト投入 (`#file`, `#codebase`)、命名補助、ターミナル連携が順に揃い、基盤としての形が固まった半年。

### v1.86 (2024/01)

- `#file` コンテキスト変数が追加され、`#` を押して任意のファイルを chat に同梱できるように
- AI Fixes 用の **Light bulb (sparkle)**。選択範囲やカーソル位置から「Modify with Copilot / Generate with Copilot」を直接呼び出せる
- `editor.inlineSuggest.fontFamily` で補完のフォントを変更可能に

[v1.86 リリースノート](https://code.visualstudio.com/updates/v1_86)

### v1.87 (2024/02)

- **Rename suggestions** の段階的ロールアウト開始。シンボルをリネームすると Copilot が候補を提示
- Inline chat accessibility view、マイクアイコンの常時表示 (VS Code Speech 拡張連携)
- 音声入力で「at workspace」「slash fix」等の agent / slash 指定を認識
- pre-release で **`#codebase` 変数** を導入 (ワークスペース全体を context に)

[v1.87 リリースノート](https://code.visualstudio.com/updates/v1_87)

### v1.88 (2024/03)

- Inline Chat を **floating control に刷新**。最初は小さく、応答後に展開される軽量 UI に
- `@workspace /new` が context と履歴を扱い、「TypeScript にして」「Bootstrap も追加」のような追従指示が通るように
- **`@terminal /explain`** スラッシュコマンド (`@terminal` 単体は「修正案」、`/explain` を付けると「解説」)
- **Terminal Inline Chat のプレビュー** 開始
- コミットメッセージ生成に、直近 10 件の repo コミット + 10 件の自分のコミットを context として追加

[v1.88 リリースノート](https://code.visualstudio.com/updates/v1_88)

### v1.89 (2024/04)

- **Terminal Inline Chat がデフォルト機能に**。ターミナルにフォーカスを置いて `Ctrl+I` で起動、`@terminal` 経由で shell の内容を理解
- Rename サジェストにスパークル (✨) アイコンを追加
- **Content Exclusions** に対応 (Enterprise 向けのファイル除外制御)

[v1.89 リリースノート](https://code.visualstudio.com/updates/v1_89)

### v1.90 (2024/05)

- Inline Chat の会話を **Chat view に移動** できるように
- Rename サジェストの自動トリガー (`github.copilot.renameSuggestions.triggerAutomatically`)
- **📎 アイコンによる context 添付** (ワークスペースシンボルなど)
- **Copilot Enterprise で Bing Web 検索 + enterprise knowledge bases**。`@github What is the latest LTS of Node.js? #web` のような問いが可能に

[v1.90 リリースノート](https://code.visualstudio.com/updates/v1_90)

### v1.91 (2024/06)

- Compact Inline Chat と、ターミナル初期ヒント
- **Chat API / Language Model API が Stable 化**。外部拡張が Copilot の chat 機構に参加可能に

[v1.91 リリースノート](https://code.visualstudio.com/updates/v1_91)

この段階では、リリースノート全体のうち Copilot 記述は「Contributions to extensions > GitHub Copilot」の小節にまとまっており、全体の 1〜2 割程度です。まだ「VSCode の一機能」という位置付けが明確でした。

## 2. 2024 年後半 (v1.92〜v1.96) — GPT-4o / Custom Instructions / Copilot Edits 誕生

> **概要**: モデルが GPT-4o に上がり、カスタム指示で挙動を制御できるようになる。**v1.95 で Copilot Edits (プレビュー)**、**v1.96 で Copilot Free プラン**が登場し、利用者層と使い方が一気に拡大。

### v1.92 (2024/07)

- **Copilot Chat を GPT-4-Turbo → GPT-4o に引き上げ**。コード生成・説明の速度と精度が向上
- `@vscode /runCommand` で VS Code コマンドを自然言語で検索・実行
- Public code matching を chat に追加

[v1.92 リリースノート](https://code.visualstudio.com/updates/v1_92)

### v1.93 (2024/08)

- **Custom instructions (実験)** — `github.copilot.chat.experimental.codeGeneration.instructions` で、すべてのコード生成に固定指示を付与
- 自動 chat participant 検出 (実験) — `@workspace` を明示せずに自然言語で適切な participant にルーティング
- Quick Chat での context 追加、テスト生成の改善

[v1.93 リリースノート](https://code.visualstudio.com/updates/v1_93)

### v1.94 (2024/09)

- **モデル切替ピッカー**が chat に登場 (OpenAI o1 の early access 連動)
- **Inline Chat も GPT-4o に**
- Temporal Context (実験) — 最近開いた・編集したファイルを自動で chat context に
- Custom instructions のファイル取込、Chat view の UI リフレッシュ、Semantic search プレビュー

[v1.94 リリースノート](https://code.visualstudio.com/updates/v1_94)

### v1.95 (2024/10)

- 自動 participant 検出を正式機能に昇格
- **Copilot Edits (プレビュー) が登場** — Chat の会話フローと Inline の即時反映を合わせ、**ワーキングセットを指定した複数ファイル編集**を実現
- Experimental / Preview タグで機能段階を明示する運用に

[v1.95 リリースノート](https://code.visualstudio.com/updates/v1_95)

### v1.96 (2024/11)

- **GitHub Copilot Free プランを公開** — GitHub アカウントさえあれば毎月一定の補完・チャット枠が無料で使える。このリリースの前後で新規利用者が激増
- Copilot Edits を継続強化、Chat → Edits へのコードブロック引き継ぎ
- **`copilot-debug` ターミナルコマンド**でデバッグセッションを起動
- Chat / Edits に **シンボル・フォルダ** を context 追加
- コミットメッセージ生成にも custom instructions を対応 (`github.copilot.chat.commitMessageGeneration.instructions`)

[v1.96 リリースノート](https://code.visualstudio.com/updates/v1_96)

半年で「モデルを選べる」「指示を外部化できる」「複数ファイルを編集できる」「無料で試せる」が揃いました。Copilot Edits の誕生は、次の Agent Mode への布石でもあります。

## 3. 2025 年前半 (v1.97〜v1.102) — Agent Mode 登場と MCP の GA

> **概要**: 「Edit」から「Agent」への転換期。v1.97 で **Agent Mode (実験)** が産声を上げ、NES・Vision・Fetch・Thinking など「エージェントに必要な周辺ツール」が一気に揃う。v1.102 で **Copilot Chat が OSS 化**、**MCP が GA**。

### v1.97 (2025/01)

- **Copilot Edits が GA**
- **Next Edit Suggestions (プレビュー)** — 次にしそうな編集を Copilot が予測し、Tab で受け入れ
- **Agent Mode (実験) が初登場**。ワークスペースを自動探索し、ファイル編集・エラー確認・ターミナル実行 (許可制) までエンドツーエンドに実行

[v1.97 リリースノート](https://code.visualstudio.com/updates/v1_97)

### v1.98 (2025/02)

- **Custom instructions を GA** — `.github/copilot-instructions.md` が標準の置き場所に
- Agent Mode がプレビュー昇格、ノートブック向け Copilot Edits、**Copilot Vision (画像添付)**
- Copilot Edits のファイル数制限 (10) とクライアント側レート制限 (10 分 14 回) を撤廃

[v1.98 リリースノート](https://code.visualstudio.com/updates/v1_98)

### v1.99 (2025/03)

- **Prompt files (`.prompt.md`) / User Prompts** — 再利用可能な prompt を file として管理、同期も可能
- **Thinking tool (実験)** — ツール呼び出し間でモデルに「考える時間」を与え、複雑タスクの精度を上げる (Anthropic の研究に着想)
- **`#fetch` tool** — 公開 Web ページを prompt に取り込む

[v1.99 リリースノート](https://code.visualstudio.com/updates/v1_99)

### v1.100 (2025/04)

- NES がデフォルトで有効化
- **Agent Mode に auto-fix**。編集で新たに発生したエラーをエージェント自身が検出し、追加編集を提案 (`github.copilot.chat.agent.autoFix`)
- Agent Mode 中の手動編集 / undo 対応の改善、Conversation Summary と Prompt Caching
- MCP で **Image / Streamable HTTP** に対応

[v1.100 リリースノート](https://code.visualstudio.com/updates/v1_100)

### v1.101 (2025/05)

- NES 受け入れフローを改善 — Tab 連打で次候補に進める
- **Custom chat modes (プレビュー)** — 組み込みの Ask / Edit / Agent に加え、独自モードを作成可能
- MCP が **prompts / resources / sampling / 認証 / 開発モード / 拡張からの公開** をサポート
- **Tool sets** — ツールをグループ化して管理

[v1.101 リリースノート](https://code.visualstudio.com/updates/v1_101)

### v1.102 (2025/06)

- **Copilot Chat 拡張を MIT で OSS 化** ([microsoft/vscode-copilot-chat](https://github.com/microsoft/vscode-copilot-chat))
- **MCP が GA** — MCP ビュー、ギャラリー、Settings Sync 統合、プロファイル対応
- **Copilot coding agent にタスク委譲** — VSCode からバックグラウンドでタスクを GitHub 側に預けられる
- `Chat: Generate Instructions` コマンド — agent がコードベースを解析して `.github/copilot-instructions.md` の雛形を生成
- ターミナルコマンドの自動承認、過去の chat リクエストの編集・再送信

[v1.102 リリースノート](https://code.visualstudio.com/updates/v1_102)

この半年で、Copilot の裏側 (Chat 拡張の実装) が OSS になり、外側の仕組み (MCP) が GA を迎えました。「Copilot は閉じた拡張」から「開かれたエージェント基盤」への移行点です。

## 4. 2025 年後半 (v1.103〜v1.110) — モデル選択肢の拡張と Agent HQ

> **概要**: 「1 つの Copilot が複数エージェントを束ねる」時代へ。モデルは GPT-5 系 / Claude 系が並び、Copilot 拡張と Copilot Chat 拡張が統合され、**Agent HQ** で local / background / cloud のオーケストレーションが可能に。MCP も marketplace・GitHub 公式 MCP Server・Apps・メモリ・プラグインへと広がる。

### v1.103 (2025/07)

- **GPT-5 mini** が全 Copilot プランに展開
- **Chat checkpoints** — 会話と編集状態の「どこかの時点」に戻せる
- ターミナル系ツールを core (microsoft/vscode) 側に移管してハング問題を解消
- **Virtual Tools** — tool 数が 128 を超えるとき自動グルーピング (`github.copilot.chat.virtualTools.threshold`)
- ターミナル auto-approve の粒度強化

[v1.103 リリースノート](https://code.visualstudio.com/updates/v1_103)

### v1.104 (2025/08)

- ノートブック向け NES の強化 (`github.copilot.chat.notebook.enhancedNextEditSuggestions.enabled`) を中心とした細かい品質向上の集積回

[v1.104 リリースノート](https://code.visualstudio.com/updates/v1_104)

### v1.105 (2025/09)

- **Plan & Handoff** — 複雑タスクの計画立案と他エージェントへの引き継ぎ
- **AI によるマージコンフリクト解決**
- **GPT-5-Codex / Claude Sonnet 4.5** を chat モデルピッカーに追加
- **MCP Marketplace (プレビュー)**

[v1.105 リリースノート](https://code.visualstudio.com/updates/v1_105)

### v1.106 (2025/10)

- Copilot coding agent 連携を GitHub PR 拡張から Copilot Chat 拡張へ移管
- **Copilot CLI 統合** — chat エディタや統合ターミナルから CLI セッションを起動・再開
- **GitHub Copilot 拡張 + GitHub Copilot Chat 拡張の統合**。以後 Chat 拡張が inline suggestions も提供し、GitHub Copilot 拡張は **2026 年初頭までに非推奨**化 (`chat.extensionUnification.enabled` で一時的に戻せる)
- **Language Models エディタ** (Insiders) — すべてのモデルを provider / capability / visibility で検索・管理

[v1.106 リリースノート](https://code.visualstudio.com/updates/v1_106)

### v1.107 (2025/11)

- **GitHub MCP Server** を組み込み有効化 (`github.copilot.chat.githubMcpServer.enabled`)。既存の GitHub 認証を流用し、Issue / PR 情報にそのままアクセス
- **Agent HQ** — Copilot と custom agents を束ねる中心ビュー
- **Background agents** が isolated workspace で並列実行可能に
- **Multi-agent orchestration** — local / background / cloud にタスクを振り分け

[v1.107 リリースノート](https://code.visualstudio.com/updates/v1_107)

### v1.108 (2025/12)

- **Agent Skills (実験)** — 命令・スクリプト・リソースのフォルダを「スキル」として動的にロード。ドメイン固有の能力を渡せる
- MCP の出力を Accessible View から除外しノイズ低減

[v1.108 リリースノート](https://code.visualstudio.com/updates/v1_108)

### v1.109 (2026/01)

- **組織レベルの custom instructions** 自動適用 (`github.copilot.chat.organizationInstructions.enabled`)
- カスタムエージェントファイルの配置場所設定 (`chat.agentFilesLocations`)
- **Anthropic モデル向け context editing (実験)** — 古いツール結果や thinking token をクリアし、長い会話のコンテキストを保つ
- **MCP Apps** — MCP サーバーがリッチな UI をクライアント側に表示可能
- **Copilot Memory tool** — チャットが Copilot Memory を読み書きできる (`github.copilot.chat.copilotMemory.enabled`)

[v1.109 リリースノート](https://code.visualstudio.com/updates/v1_109)

### v1.110 (2026/02)

- **Agent plugins** — skills / commands / agents / MCP servers / hooks を 1 パッケージで配布。Extensions view の `@agentPlugins` で検索・インストール
- **Agentic browser tools** — エージェントがブラウザを操作して、自分の変更を実際に動かして検証できる
- **Session memory** — 会話ターンを超えて計画や方針を保持
- 会話から直接カスタマイズ生成する `/create-prompt` `/create-instruction` `/create-skill` `/create-agent` `/create-hook`

[v1.110 リリースノート](https://code.visualstudio.com/updates/v1_110)

この時期には、リリースノートの「highlights」の半分以上が Copilot / Chat / Agent / MCP 関連で占められるようになります。

## 5. 2026 年 (v1.111〜v1.116) — 週次リリースとビルトイン化

> **概要**: VSCode が **月次から週次リリース** に切り替わり、リリースノートは agent 関連で埋め尽くされる。v1.116 で **Copilot Chat が VSCode のビルトイン拡張** となり、「インストール不要で AI が使える VSCode」が標準に。

### v1.111 (2026/03/09) — 初の weekly stable release

- VSCode の初の **weekly stable release**
- AI CLI ターミナルプロファイル (Copilot CLI など) をプロファイルドロップダウン先頭のグループに集約
- **`#debugEventsSnapshot`** — Agent Debug panel のイベントを chat の context として添付できる

[v1.111 リリースノート](https://code.visualstudio.com/updates/v1_111)

### v1.112 (2026/03/18)

- **Agent Debug Logs の export / import** — セッションの挙動ログを共有・オフライン分析できる
- Copilot CLI にタスク委譲する前に、未コミット変更をプレビュー・取捨選択できる
- Copilot CLI のターミナル出力で **ファイルリンクがクリック可能に**

[v1.112 リリースノート](https://code.visualstudio.com/updates/v1_112)

### v1.113 (2026/03/25)

- **Session forking** — Copilot CLI / Claude エージェントで、会話の任意の時点をコピーして分岐
- Agent Debug Log パネルを Copilot CLI / Claude セッションでも利用可能に

[v1.113 リリースノート](https://code.visualstudio.com/updates/v1_113)

### v1.114 (2026/04/01)

- **`/troubleshoot`** — 過去チャットの debug logs を解析し、「なぜ custom instructions が無視されたか」「なぜ応答が遅いか」を診断
- Copy chat response、チャット添付の動画プレビュー
- Claude エージェントを Group Policy で無効化可能に (`Claude3PIntegration`)

[v1.114 リリースノート](https://code.visualstudio.com/updates/v1_114)

### v1.115 (2026/04/08)

- **VS Code Agents companion app** — エージェントネイティブ専用 UI が VSCode Insiders に同梱で配布。複数 repo を並列にエージェント実行、セッション切替、差分レビュー、PR 作成まで 1 アプリで完結
- 統合ブラウザを agent が扱うための改善
- background terminal の通知で agent が出力変化を検知できる (`chat.tools.terminal.backgroundNotifications`)

[v1.115 リリースノート](https://code.visualstudio.com/updates/v1_115)

### v1.116 (2026/04/15) — ついにビルトイン化

- **GitHub Copilot Chat が VSCode のビルトイン拡張に**。新規ユーザーは拡張をインストールしなくても、chat / inline suggestions / agents が最初から使える
- Agent Debug Logs で **過去セッション** を閲覧可能に (`github.copilot.chat.agentDebugLog.fileLogging.enabled`)
- Copilot CLI の **thinking effort** 設定で応答品質とレイテンシをチューニング
- **JS/TS Chat Features 拡張** (ビルトイン) — TypeScript プロジェクトのセットアップに特化したスキルを提供

[v1.116 リリースノート](https://code.visualstudio.com/updates/v1_116)

2024 年 1 月時点で「1 拡張機能への追加機能」でしかなかった Copilot は、2 年 3 ヶ月かけて VSCode 本体と一体化しました。

## 6. まとめ — 5 局面で眺める Copilot 進化

| 時期 | バージョン | キーワード | 一言まとめ |
|------|------|------|------|
| 2024 H1 | v1.86〜v1.91 | Inline Chat / `#file` / Terminal Inline | エディタ内でチャットできる段階 |
| 2024 H2 | v1.92〜v1.96 | GPT-4o / Custom Instructions / **Copilot Edits** / Free | モデルと指示を選べる、複数ファイルを編集できる段階 |
| 2025 H1 | v1.97〜v1.102 | NES / **Agent Mode** / Vision / Prompt files / **MCP GA** / OSS 化 | エージェント化と外部連携の基盤が整う段階 |
| 2025 H2 | v1.103〜v1.110 | GPT-5 / Claude / **Agent HQ** / Agent Skills / Plugins / Memory | 複数エージェントをオーケストレーションする段階 |
| 2026 | v1.111〜v1.116 | 週次リリース / Agents app / **ビルトイン化** | VSCode 本体の主役に昇格する段階 |

### 自分のワークフローを位置づける

今 Copilot をどこまで使えているかは、この 5 局面のどれかで測れます:

- **Inline Chat 止まり** (2024 H1 相当): 補完とチャットは使うが、コンテキストは都度張り付け
- **Chat 常用** (2024 H2 相当): `#file` や custom instructions を活用している
- **Edits 活用** (2025 H1 相当): 複数ファイル編集を 1 プロンプトで依頼している
- **Agent 委譲** (2025 H2 相当): ターミナル実行や連続編集をエージェントに任せ、ログで追っている
- **MCP / Plugins で拡張** (2026 相当): 自作 MCP サーバや Agent Plugin を組み込んで環境を育てている

ドキュメントを読んで「この機能の呼び方が 2 種類ある」「古い記事と記述が違う」と感じることが増えたら、この年表を思い出してください。多くの場合、それは進化の地層が見えているだけです。

## 参照

- [Visual Studio Code Updates](https://code.visualstudio.com/updates)
- 本記事で参照したリリースノート 31 本 (v1.86 〜 v1.116) はすべて `https://code.visualstudio.com/updates/v1_XX` の形式です
