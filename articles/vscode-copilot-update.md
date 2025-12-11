---
title: "VSCode 1.107 GitHub Copilot最新アップデート徹底解説"
emoji: "🤖"
type: "tech"
topics: ["ai", "githubcopilot", "vscode"]
published: true
---
# VSCode 1.107 GitHub Copilot最新アップデート徹底解説

VSCode November 2025 Insiders（v1.107）では、GitHub Copilotのエージェント機能が大幅に強化されました。本記事では、特に注目すべき3つの実験的機能について詳しく解説します。

> **参考**: [VSCode Release Notes v1.107](https://code.visualstudio.com/updates/v1_107)

---

## 1. サブエージェントとしてのエージェント実行（実験的機能）

### サブエージェントの概念

サブエージェント（Context-Isolated Subagents）は、メインのチャットセッション内から呼び出せる**コンテキスト分離された自律エージェント**です。メインセッションとは独立したコンテキストウィンドウを持ち、複雑なマルチステップタスク（リサーチ、分析など）に適しています。

> **参考**: [Chat Sessions - Context-isolated subagents](https://code.visualstudio.com/docs/copilot/chat/chat-sessions#_contextisolated-subagents)

```
┌────────────────────────────────────────────────────┐
│ メインチャットセッション                            │
│ ┌────────────────────────────────────────────────┐ │
│ │ User: 認証方式のベストプラクティスを調べて、    │ │
│ │       実装計画を立てて                          │ │
│ └────────────────────────────────────────────────┘ │
│                     ↓                              │
│ ┌────────────────────────────────────────────────┐ │
│ │ サブエージェント起動                            │ │
│ │ - 独立したコンテキストウィンドウ                │ │
│ │ - 読み取り専用ツールでリサーチ実行              │ │
│ │ - 完了後、最終結果のみメインに返却              │ │
│ └────────────────────────────────────────────────┘ │
│                     ↓                              │
│ ┌────────────────────────────────────────────────┐ │
│ │ メインセッションで計画策定を継続                │ │
│ │ （サブエージェントの調査結果を活用）            │ │
│ └────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────┘
```

### 特徴

| 特性 | 詳細 |
|------|------|
| コンテキスト分離 | メインセッションのコンテキストを消費しない |
| 自律実行 | ユーザーフィードバックなしで完了まで実行 |
| 結果の返却 | 最終結果のみがメインセッションに返される |
| ツールアクセス | デフォルトではメインセッションと同じツールを継承<br/>**カスタムエージェントと組み合わせることで独立したツールセットを指定可能** |
| モデル | デフォルトではメインセッションと同じAIモデルを使用<br/>**カスタムエージェントと組み合わせることで独立したモデルを指定可能** |

> **実験的機能による拡張**: 設定 `chat.customAgentInSubagent.enabled` を有効にすると、サブエージェントで別のカスタムエージェントを指定できます。カスタムエージェントには独自の`tools:`および`model:`プロパティを定義できるため、**サブエージェントごとに専門化されたツールセットと最適なAIモデルを割り当てられます**。（筆者が実際に確認済み）
>
> **参考リンク**:
> - [公式ドキュメント: Context-isolated subagents](https://code.visualstudio.com/docs/copilot/chat/chat-sessions#_contextisolated-subagents)
> - [GitHub Issue #275855: モデル指定機能のリクエスト](https://github.com/microsoft/vscode/issues/275855) - コミュニティから「サブエージェントごとに異なるモデルを明示的に指定したい」という要望が寄せられています
> - [カスタムエージェントでのモデル指定](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/coding-agent/create-custom-agents)

### 使い方

1. `runSubagent`ツールをTool Pickerで有効化
2. プロンプトでサブエージェントの実行を指示

```markdown
<!-- 例1: リサーチタスク -->
サブエージェントを使って、Webアプリケーションの認証方式について調査してください。
調査結果をまとめてください。

<!-- 例2: #runSubagent を明示的に参照 -->
#runSubagent を使って、ユーザーのタスクを読み取り専用ツールで包括的に調査し、
80%の確信度に達したら計画立案に必要なコンテキストを返してください。
```

### カスタムエージェントとの組み合わせ（実験的）

設定 `chat.customAgentInSubagent.enabled` を有効にすると、サブエージェントで**別のカスタムエージェントを指定**できます。

```markdown
<!-- researchエージェントをサブエージェントとして実行 -->
research agentをサブエージェントとして実行し、
このプロジェクトに最適な認証方式を調査してください。

<!-- planエージェントで計画を作成し、ファイルに保存 -->
plan agentをサブエージェントで使用して、myfeatureの実装計画を作成し、
plans/myfeature.plan.md に保存してください。
```

### サブエージェント vs 通常のエージェント

| 観点 | サブエージェント | 通常のエージェント |
|------|-----------------|-------------------|
| 実行場所 | メインセッション内 | 独立セッション |
| コンテキスト | 分離（効率的） | 共有または完全独立 |
| ユーザー介入 | なし（自律） | 適宜フィードバック可能 |
| 結果の受け渡し | 最終結果のみ | 全履歴参照可能 |
| 適したタスク | 調査、分析、サブタスク | メインの開発タスク |

---

## なぜサブエージェントが重要か：ツール過多問題の解決

### ツールが多すぎるとエージェントは賢くならない

GitHub Copilotチームの研究によると、**エージェントに渡すツールが多すぎると、パフォーマンスが低下する**ことが明らかになっています。

> **参考**: [How we're making GitHub Copilot smarter with fewer tools - GitHub Blog](https://github.blog/ai-and-ml/github-copilot/how-were-making-github-copilot-smarter-with-fewer-tools/)

VSCodeのGitHub Copilot Chatは、MCPを通じて数百のツールにアクセスできます。しかし、ツールが増えるほど以下の問題が発生します：

| 問題 | 詳細 |
|------|------|
| **応答遅延** | ツール選択の推論に時間がかかり、平均400ms以上の遅延が発生 |
| **性能低下** | SWE-Lancerベンチマークで2〜5%の解決率低下 |
| **不適切なツール使用** | 明示的な指示を無視したり、不要なツールを呼び出す |
| **APIリミット超過** | 一部のモデルでは、ツール数がAPIの制限を超えることも |

実際、VSCodeでは以下のようなスピナーを見たことがあるかもしれません：

```
🔄 Optimizing tool selection...
```

これは、モデルが多すぎるツールの中から推論しようとしている状態です。

### GitHubの解決策：ツールセットの削減
（上記のGithubのブログ時点での情報となります。今回のアップデートを受けて、再度変更が行われました。）

GitHubチームは、デフォルトの40個の組み込みツールを**13個のコアツール**に削減しました。残りのツールは「仮想ツールグループ」としてまとめ、必要な時だけ展開する方式を採用しています。

```
コアツールセット（常時利用可能）: 13個
├── リポジトリ構造解析
├── ファイル読み書き
├── コンテキスト検索
└── ターミナル操作

仮想ツールグループ（必要時に展開）:
├── Jupyter Notebook Tools
├── Web Interaction Tools
├── VS Code Workspace Tools
└── Testing Tools
```

この結果：
- **TTFT（Time To First Token）**: 平均190ms短縮
- **TTLT（Time To Last Token）**: 平均400ms短縮

### サブエージェントによる新しいアプローチ

サブエージェント機能の登場により、**ツール過多問題に対する新しいアーキテクチャ**が可能になりました。

#### 従来のアプローチ（単一エージェント + 多数のツール）

```
┌─────────────────────────────────────────┐
│ メインエージェント                       │
│ ┌─────────────────────────────────────┐ │
│ │ ツール: 40+ 個                       │ │
│ │ - ファイル操作                       │ │
│ │ - Git操作                            │ │
│ │ - Web検索                            │ │
│ │ - データベース                        │ │
│ │ - テスト実行                          │ │
│ │ - ...その他多数                       │ │
│ └─────────────────────────────────────┘ │
│ → ツール選択に時間がかかる               │
│ → 間違ったツールを選びがち               │
└─────────────────────────────────────────┘
```

#### 新しいアプローチ（オーケストレーター + 専門サブエージェント）

```
┌─────────────────────────────────────────────────────┐
│ メインエージェント（オーケストレーター）             │
│ ┌─────────────────────────────────────────────────┐ │
│ │ ツール: runSubagent のみ                         │ │
│ │ モデル: Claude Sonnet 4.5（高度な推論）         │ │
│ └─────────────────────────────────────────────────┘ │
│                        ↓                            │
│    ┌───────────┬───────────┬───────────┐           │
│    ↓           ↓           ↓           ↓           │
│ ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐            │
│ │研究  │  │実装  │  │テスト│  │Git   │            │
│ │Agent │  │Agent │  │Agent │  │Agent │            │
│ ├──────┤  ├──────┤  ├──────┤  ├──────┤            │
│ │Web検索│  │ファイル│  │テスト│  │Git  │            │
│ │fetch │  │編集   │  │実行  │  │操作 │            │
│ ├──────┤  ├──────┤  ├──────┤  ├──────┤            │
│ │Sonnet │  │Sonnet │  │Haiku │  │Haiku│            │
│ │4.5   │  │4.5   │  │4.5   │  │4.5  │            │
│ └──────┘  └──────┘  └──────┘  └──────┘            │
│                                                     │
│ → 各エージェントは必要最小限のツールのみ保持         │
│ → 高精度なツール呼び出しが可能                       │
│ → タスクに最適なモデルを選択可能                     │
│   （高度な推論が必要な研究・実装にはSonnet、       │
│    単純な定型作業にはHaikuを割り当て）             │
└─────────────────────────────────────────────────────┘
```

#### 具体的な実装例

```markdown
<!-- カスタムエージェント: research-agent.agent.md -->
---
name: research-agent
description: Web検索と情報分析を専門とする調査エージェント
tools:
  - web_search
  - web_fetch
model: Claude Sonnet 4.5 (copilot)  # 高度な分析能力が必要
---

# Research Agent

あなたは情報調査と分析の専門家です。
Web検索を駆使して、技術的なトピックについて包括的な調査を行います。
...
```

```markdown
<!-- カスタムエージェント: test-agent.agent.md -->
---
name: test-agent
description: テストコード生成・実行の専門エージェント
tools:
  - codebase
  - runTerminal
model: Claude Haiku 4.5 (copilot)  # 定型的なタスクには軽量モデルで十分対処可能、比較的高速な処理が期待できる
---

# Test Agent

あなたはテスト自動化の専門家です。
既存のコードベースを分析し、適切なユニットテストを生成します。
...
```

```markdown
<!-- カスタムエージェント: orchestrator.agent.md -->
---
name: orchestrator
description: タスクを分析し、適切な専門エージェントに委譲するオーケストレーター
tools:
  - runSubagent
model: Claude Sonnet 4.5 (copilot)  # 高度なタスク分解・判断が必要
---

# Orchestrator Agent

あなたはタスク分析と委譲の専門家です。
ユーザーのリクエストを分析し、以下の専門エージェントに適切に委譲してください：

- research-agent: 調査・情報収集タスク（Web検索が必要な場合）
- implementation-agent: コード実装タスク
- test-agent: テスト作成・実行タスク（定型作業）
- git-agent: バージョン管理タスク

自分では直接コードを書いたりファイルを操作したりしないでください。
必ず専門エージェントに委譲してください。

各エージェントは独立したツールセットとモデルを持ち、
タスクの性質に応じて最適化されています。
```

> **利用可能なモデル**:
> - `Claude Sonnet 4.5 (copilot)` - バランスの取れた高性能モデル
> - `Claude Haiku 4.5 (copilot)` - 高速・軽量モデル
> - `Claude Opus 4.5 (Preview) (copilot)` - 最高性能モデル（プレビュー）

このアーキテクチャにより：
- **各エージェントのツール数を最小限に抑制**できる
- **ツール選択の精度が向上**する
- **応答速度が改善**される
- **タスクの専門性に応じた最適なツールセット**を構成できる
- **コスト効率の最適化**: 高度な推論が必要なタスクにはSonnet、定型作業にはHaikuを使い分けることで、トークン消費を最適化
- **パフォーマンスの向上**: タスクの複雑さに応じたモデル選択により、不要な処理時間を削減

---

## 2. Git Worktreesによるバックグラウンドエージェントの分離

### 背景と課題

バックグラウンドエージェント（Copilot CLI、OpenAI Codexなど）は、ユーザーがエディタで作業している間に自律的にタスクを実行します。しかし、従来はエージェントの変更が直接ワークスペースに適用されるため、以下の問題がありました：

- ユーザーが編集中のファイルとコンフリクトする可能性
- 複数のバックグラウンドエージェントを同時実行できない
- エージェントの変更を安全にレビュー・ロールバックしにくい

> **参考**: [Background Agents in VS Code](https://code.visualstudio.com/docs/copilot/agents/background-agents)

### Git Worktreeによる解決

Git Worktreeは、同じリポジトリから複数の作業ツリーを作成するGitの機能です。v1.107では、バックグラウンドエージェントセッションごとに独立したWorktreeを自動作成することで、完全な分離を実現しました。

> **参考**: [Branches & Worktrees - VS Code Source Control](https://code.visualstudio.com/docs/sourcecontrol/branches-worktrees)

#### 仕組み

```
メインワークスペース: /project/main
├── src/
├── package.json
└── ...

バックグラウンドエージェント用Worktree: /project/.worktrees/session-abc123
├── src/           # エージェントはここで変更を行う
├── package.json
└── ...
```

エージェントが作成・変更するファイルはすべてWorktreeフォルダ内に隔離されるため、メインワークスペースには一切影響しません。

#### 使い方

1. Chat viewから「New Background Agent」を選択
2. **Isolation mode**で「**Worktree**」を選択（デフォルトは「Workspace」）
3. プロンプトを入力してエージェントセッションを開始

```
┌─────────────────────────────────────┐
│  Isolation mode: [Worktree ▼]       │
│  ┌─────────────────────────────────┐│
│  │ Worktree  ← 分離モード          ││
│  │ Workspace ← 直接適用            ││
│  └─────────────────────────────────┘│
└─────────────────────────────────────┘
```

#### メリット

| 観点 | Worktreeモード | Workspaceモード |
|------|----------------|-----------------|
| 安全性 | 高（完全分離） | 低（直接変更） |
| 並列実行 | 可能 | コンフリクトリスク |
| レビュー | 差分で確認可能 | 即時反映 |
| ロールバック | Worktree削除で完了 | Git revertが必要 |

#### 変更のマージ

エージェントがタスクを完了したら、以下の方法で変更をメインブランチに取り込めます：

1. **Apply Changes**ボタン：Worktreeの変更を直接メインブランチに適用
2. **Git操作**：通常のブランチマージと同様に、cherry-pickやmergeで取り込み
3. **Source Control view**：Repositoriesビューで Worktreeを確認し、差分をレビュー

---

## 3. カスタムエージェントとバックグラウンドエージェントの連携（実験的機能）

### カスタムエージェントとは

カスタムエージェントは、特定の役割やタスクに特化したAIアシスタントを定義する機能です。Markdownファイルで以下を指定できます：

- ペルソナ（例：DBAスペシャリスト、フロントエンド開発者）
- 利用可能なツール
- 使用する言語モデル
- 適用する指示・ガイドライン

> **参考**: [Custom Agents - VS Code Copilot Customization](https://code.visualstudio.com/docs/copilot/customization/custom-agents)

### バックグラウンドエージェントでの活用

従来、カスタムエージェントはローカルチャットセッションでのみ使用可能でした。v1.107の実験的機能により、**バックグラウンドエージェントでもカスタムエージェントを指定**できるようになりました。

> **参考**: [Use custom agents with background agents](https://code.visualstudio.com/docs/copilot/agents/background-agents#_use-custom-agents-with-background-agents-experimental)

#### 設定方法

1. 設定で機能を有効化：
   ```json
   {
     "github.copilot.chat.cli.customAgents.enabled": true
   }
   ```

2. ワークスペースにカスタムエージェントを作成：
   ```markdown
   <!-- .github/agents/code-reviewer.agent.md -->
   ---
   name: code-reviewer
   description: セキュリティとパフォーマンスに注力したコードレビュー専門家
   tools:
     - codebase
     - textSearch
   ---
   
   # Code Reviewer Agent
   
   あなたはセキュリティとパフォーマンスの専門家です。
   コードレビュー時は以下の観点を重視してください：
   - SQLインジェクション、XSSなどの脆弱性
   - N+1問題などのパフォーマンス課題
   - 適切なエラーハンドリング
   ```

3. バックグラウンドエージェントセッション作成時に選択：
   ![画像1](/images/1.png)

### ユースケース例

| カスタムエージェント | バックグラウンドタスク |
|---------------------|----------------------|
| コードレビュアー | PR全体のセキュリティ監査 |
| テストエンジニア | 新機能に対するテストケース生成 |
| ドキュメンター | APIドキュメントの自動生成 |
| リファクタリング専門家 | レガシーコードのモダン化 |

### Git Worktreeとの組み合わせ

カスタムエージェント + Worktree分離を組み合わせることで、**「誰が（どのペルソナで）」「何を」「どこで（分離環境で）」**実行するかを完全に制御できます。

```
┌─────────────────────────────────────────────────────┐
│ バックグラウンドエージェントセッション               │
│                                                     │
│ Agent:     [code-reviewer]  ← カスタムエージェント  │
│ Isolation: [Worktree]       ← 分離モード            │
│ Task:      "PRのセキュリティレビューを実施"          │
│                                                     │
│ → 専門的なレビューを                                │
│ → 安全な分離環境で                                  │
│ → バックグラウンドで自律実行                        │
└─────────────────────────────────────────────────────┘
```

---

## 環境間のツール互換性に関する注意

カスタムエージェントは、以下の3種類の環境で動作します：

- **VS Code（GitHub Copilot Chat）**: ローカルのIDE内でリアルタイムに対話
- **GitHub.com（Copilot coding agent）**: クラウド上でバックグラウンド実行
- **GitHub Copilot CLI**: ターミナルからのコマンドライン実行

同じエージェント定義ファイル（`.agent.md`）を複数環境で共有できますが、**環境ごとにサポートされる設定やツールは異なります**。特にツールの互換性には大きな差異があり、VS Code固有のツールはクラウド環境やCLIでは利用できません。認識されないツールやプロパティは自動的に無視される設計になっています。

このため、同じエージェントを使っていても、**実行環境によって動作が異なる**場合があります。たとえば、VS Codeで期待通りに動作するエージェントが、GitHub.comでは一部の機能が無効化された状態で実行されることがあります。

カスタムエージェント機能は現在も急速に発展しており、各環境でサポートされるプロパティやツールは今後変更される可能性があります。最新の仕様については、以下の公式ドキュメントを参照してください：

> **参考リンク**:
> - [Custom agents configuration - GitHub Docs](https://docs.github.com/en/copilot/reference/custom-agents-configuration) - 設定プロパティとツールのリファレンス
> - [About custom agents - GitHub Docs](https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-custom-agents) - カスタムエージェントの概念と使い方
> - [Custom agents in VS Code](https://code.visualstudio.com/docs/copilot/customization/custom-agents) - VS Code固有の機能と設定
> - [Custom agents for GitHub Copilot - GitHub Changelog](https://github.blog/changelog/2025-10-28-custom-agents-for-github-copilot/) - 機能発表と最新アップデート
> - [awesome-copilot](https://github.com/github/awesome-copilot) - コミュニティによるカスタムエージェントのサンプル集

---

---

## 📋 **免責事項**

> **重要**: 本記事はClaudeとの対話で作成されており、以下の点での誤りが含まれている可能性があります：
> 
> - 設定名・プロパティの正確性（`chat.customAgentInSubagent.enabled` など）
> - カスタムエージェント実装例での構文
> - GitHub Issue番号や参考リンクの存在確認
> - 実験的機能の詳細仕様
> 
> **必ず以下の公式リソースで最新情報を確認してください：**
> - [VSCode Release Notes v1.107](https://code.visualstudio.com/updates/v1_107)
> - [Custom agents configuration - GitHub Docs](https://docs.github.com/en/copilot/reference/custom-agents-configuration)
> - [VS Code Copilot Documentation](https://code.visualstudio.com/docs/copilot)

---

## まとめ

VSCode v1.107のGitHub Copilotアップデートは、**エージェントの自律性**と**開発者の制御性**の両立を目指した進化です。

| 機能 | 価値 |
|------|------|
| サブエージェント | 効率的なコンテキスト管理・ツール過多問題の解決<br/>**タスクごとに最適なツールとモデルを割り当て可能** |
| Git Worktrees分離 | 安全な並列エージェント実行 |
| カスタムエージェント連携 | 専門化されたバックグラウンドタスク |

特に、**サブエージェントによるオーケストレーションパターン**は、ツール過多問題を根本的に解決する可能性を持っています。各専門エージェントに必要最小限のツールだけを持たせることで、GitHubチームの研究が示すように、より高精度で高速なエージェント実行が期待できます。

さらに、**カスタムエージェントと組み合わせることで、サブエージェントごとに独立したモデルを指定**できるため、以下のような高度な最適化が可能です：

- **コスト効率**: 高度な推論タスクにはSonnet、定型作業にはHaikuを使い分け
- **レスポンス速度**: タスクの複雑さに応じた適切なモデル選択
- **専門性の向上**: 各ドメインに最適なモデルとツールの組み合わせ

これらの機能はすべて**実験的（Experimental）**であり、今後のフィードバックに基づいて改善される予定です。Insidersビルドで積極的に試して、GitHubリポジトリにフィードバックを送りましょう。

---

## 参考リンク

- [VSCode Release Notes v1.107](https://code.visualstudio.com/updates/v1_107)
- [Chat Sessions - Context-isolated subagents](https://code.visualstudio.com/docs/copilot/chat/chat-sessions#_contextisolated-subagents)
- [Background Agents in VS Code](https://code.visualstudio.com/docs/copilot/agents/background-agents)
- [Custom Agents Documentation](https://code.visualstudio.com/docs/copilot/customization/custom-agents)
- [Customization Overview](https://code.visualstudio.com/docs/copilot/customization/overview)
- [How we're making GitHub Copilot smarter with fewer tools - GitHub Blog](https://github.blog/ai-and-ml/github-copilot/how-were-making-github-copilot-smarter-with-fewer-tools/)
