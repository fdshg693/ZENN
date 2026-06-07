---
title: "Copilot と Actions を知っている人のための GitHub Agentic Workflows 入門"
emoji: "🤖"
type: "tech"
topics: ["github", "githubactions", "copilot", "ai", "agent"]
published: false
---

## この記事について

GitHub Copilot は「対話的に書き手を助ける」ためのもの、GitHub Actions は「決まった手順を自動で回す」ためのもの。では、**「Issue の triage」「CI が壊れた原因の調査」「docs の継続メンテ」のように、毎日リポジトリで発生する主観的で継続的なタスクを、勝手に・安全に処理させたい**ときは何を書けばよいでしょうか。

そこを埋めるのが [**GitHub Agentic Workflows**(リポジトリ名: [`github/gh-aw`](https://github.com/github/gh-aw))](https://github.github.com/gh-aw/) です。GitHub Next と Microsoft Research が共同で開発し、2026 年 2 月に technical preview として [公式 Blog で発表](https://github.blog/ai-and-ml/automate-repository-tasks-with-github-agentic-workflows/) されました。**現時点では research demonstrator / technical preview** の位置付けで、仕様は変わりうることに注意してください。

この記事では Copilot と Actions を既に触っている人を前提に、次の 3 点を順に説明します。

1. **何ができるのか**(具体的なユースケース)
2. **なにがそれを可能にしているのか**(Markdown → Actions YAML コンパイル、MCP Gateway、Safe Outputs、Sandbox)
3. **どこが従来より便利になったのか**(素の Actions YAML / Copilot CLI を Actions 内で直叩きする構成との比較)

## 1. Actions と Copilot の「あいだ」にある空白

まず整理しておきたいのは、Agentic Workflows は **CI/CD を置き換えるものではない** ということです。公式 Blog でも明言されています。

> GitHub Agentic Workflows and Continuous AI are designed to augment existing CI/CD rather than replace it. They do not replace build, test, or release pipelines...
> — [Automate repository tasks with GitHub Agentic Workflows](https://github.blog/ai-and-ml/automate-repository-tasks-with-github-agentic-workflows/)

build / test / release のような**決定的に回したい**パイプラインはこれまで通り Actions YAML に任せます。一方で、

- 「今日の PR・Issue・Release をざっと読んで、維持者向けに daily status を issue に立てて」
- 「CI が赤いので、ログを読んで原因を推定して、関連 Issue にコメントして」
- 「docs/ と実装がずれていないかチェックして、直す提案 PR を出して」

のような、**判断・要約・調査を含む主観的で繰り返し発生するタスク**は、従来の YAML では「1行目でつまずく」タイプの仕事でした。これを GitHub は **Continuous AI** と呼び、その実装基盤として提供されているのが Agentic Workflows です。

## 2. 何ができるのか — ユースケースの輪郭

公式サイトのギャラリーと [`githubnext/agentics`](https://github.com/githubnext/agentics) のサンプル集から代表的なカテゴリを拾うと次のようになります。

- **Issue & PR Management**:自動 triage、ラベル付け、プロジェクト整理
- **Continuous Documentation**:docs の継続メンテと整合性チェック
- **Continuous Improvement**:日次の code simplification / refactor / style 改善
- **Metrics & Analytics**:日次レポート、活動トレンド、ワークフロー健全性
- **Quality & Testing**:CI failure の原因診断、テスト改善
- **Multi-Repository**:複数リポジトリをまたぐ feature sync
- **Command-Triggered**:Issue / PR コメントの `/plan` `/fix` などで起動

ポイントは「**team-visible な成果物(Issue / PR / Discussion / Comment)として結果が出る**」ことです。個人の手元で Copilot CLI を叩くのと違って、**リポジトリに audit 可能なログと成果物が残る**設計になっています。

## 3. なにがそれを可能にしているのか — アーキテクチャ 4 つの柱

ここが核心です。Agentic Workflows は「新しいランタイム」ではなく、**既存の GitHub Actions の上に薄く被せた層**として実装されています。柱は 4 つです。

### 3.1 Markdown → Actions YAML コンパイル

ワークフローの実体は `.github/workflows/*.md` — **YAML frontmatter 付きの Markdown ファイル 1 枚**です。これを [`gh aw` CLI extension](https://github.com/github/gh-aw) で `.lock.yml` という通常の Actions YAML にコンパイルします。

> Critically, agentic workflows are compiled to existing GitHub Actions workflows (YAML).
> — [GitHub Next: Agentic Workflows](https://githubnext.com/projects/agentic-workflows/)

ここが設計上の肝です。**実行時はただの Actions ワークフロー**なので、

- `on:` トリガー(schedule / issues / pull_request / workflow_dispatch / …)
- `permissions:` スコープ
- Secrets / Environments
- ログ、audit、re-run、cancel

がすべてそのまま効きます。新しい実行環境を覚え直す必要はありません。

### 3.2 Engine 抽象(Copilot / Claude / Codex の切替)

frontmatter の `engine:` で、ワークフロー本文を実行するコーディングエージェントを選べます。

- `engine: copilot`(GitHub Copilot CLI)
- `engine: claude`(Claude Code)
- `engine: codex`(OpenAI Codex)
- custom engine

設計原則として **「エージェント独立性」** が掲げられており、モデルやエージェントを入れ替えてもワークフローを書き直さなくてよいよう意図されています。

> Model and coding agent independence. An agentic workflow is largely independent of the underlying LLM and the coding agent. You shouldn't have to rewrite your workflows to move from Claude Code to Codex.
> — [GitHub Next: Agentic Workflows](https://githubnext.com/projects/agentic-workflows/)

### 3.3 Tools 宣言と MCP Gateway

エージェントに何をさせられるかは frontmatter の `tools:` で明示します。[Tools リファレンス](https://github.github.com/gh-aw/reference/tools/) より例を引用します。

```yaml
tools:
  edit:              # ワークスペースのファイル編集
  bash: true         # シェル実行
  github:            # GitHub API 操作
    toolsets: [repos, issues]
```

外部サービスとの接続は **MCP(Model Context Protocol)サーバ経由**で行います。重要なのは、MCP サーバ呼び出しがエージェントコンテナから直接出ていくのではなく、**MCP Gateway という trusted container を経由して集約される**点です。

> The MCP gateway runs in a separate trusted container, launches MCP servers, and has exclusive access to MCP authentication material.
> — [Under the hood: Security architecture of GitHub Agentic Workflows](https://github.blog/ai-and-ml/generative-ai/under-the-hood-security-architecture-of-github-agentic-workflows/)

つまり **MCP 認証情報はエージェントからは見えない**。エージェントが攻撃側に取り込まれても、Gateway 経由で許可された呼び出ししか出ていけない構造です。

### 3.4 Safe Outputs — 「依頼 → 審査 → 実行」の二段構え

ここが Agentic Workflows を**セキュリティ上ユニーク**にしている仕組みです。

デフォルトでエージェントジョブは **read-only**(`contents: read` など)で動きます。では Issue や PR をどう作るか? エージェントは GitHub に**直接は書き込めません**。代わりに、

1. エージェントは「こういう Issue を作って」「こういうコメントをつけて」という**意図**を、構造化アーティファクト(NDJSON)として出力する
2. エージェントジョブが終わったあと、**別ジョブ**(こちらだけが write 権限を持つ)がそのアーティファクトを読む
3. 別ジョブは frontmatter の `safe-outputs:` 宣言と照合し、**サニタイズ & 制約チェック**をしたうえで GitHub API を叩く

frontmatter はこんな形になります([公式ホームのサンプル](https://github.github.com/gh-aw/) より)。

```yaml
---
on:
  schedule: daily
permissions:
  contents: read
  issues: read
  pull-requests: read
safe-outputs:
  create-issue:
    title-prefix: "[team-status] "
    labels: [report, daily-status]
    close-older-issues: true
---
## Daily Issues Report
Create an upbeat daily status report for the team as a GitHub issue.
...
```

`safe-outputs.create-issue` のところがまさに **「agent が Issue を作りたがったとき、こういう制約で通してよい」という許可リスト**です。[Safe Outputs 仕様](https://github.github.com/gh-aw/reference/safe-outputs-specification/) には具体的な hard limit も定義されていて、例えば `create_issue` なら title 256 文字 / body 65536 文字まで、`add_comment` なら mentions は 10 件まで、といった**コンパイル時に埋め込まれる上限**が設定されています。

公式ホームの表現を借りると、

> The agent requests; a gated job decides.
> — [GitHub Agentic Workflows Home](https://github.github.com/gh-aw/)

**エージェントは「お願いする」だけで「実行する」のは別ジョブ**という責務分離です。

### 3.5 Sandbox と Egress 制御

4 つ目の柱は実行環境の隔離です。[Security Architecture Blog](https://github.blog/ai-and-ml/generative-ai/under-the-hood-security-architecture-of-github-agentic-workflows/) によれば、

- エージェントは **専用コンテナ**に隔離される
- そのコンテナの外向き通信は **firewall**(AWF: Agent Web Firewall)で制限。`network.allowed` で明示したドメインしか抜けられない
- **LLM API トークン**はエージェントコンテナに渡さず、別の API proxy 内に置き、エージェントの LLM 呼び出しはその proxy 経由にする

> ...we avoid exposing those tokens directly to the agent's container. Instead, we place LLM auth tokens in an isolated API proxy and configure agents to route model traffic through that proxy.

これは Prompt Injection / 間接的プロンプト汚染(XPIA)経由でエージェントが乗っ取られたときに、**流出しうる情報の範囲を物理的に狭める**ための設計です。

## 4. 最小サンプルを読む — daily report ワークフロー

前節のサンプルを改めて分解して読んでみます。

```yaml
---
on:
  schedule: daily
permissions:
  contents: read
  issues: read
  pull-requests: read
safe-outputs:
  create-issue:
    title-prefix: "[team-status] "
    labels: [report, daily-status]
    close-older-issues: true
---
## Daily Issues Report
Create an upbeat daily status report for the team as a GitHub issue.
## What to include
- Recent repository activity (issues, PRs, discussions, releases, code changes)
- Progress tracking, goal reminders and highlights
- Project status and recommendations
- Actionable next steps for maintainers
```

Copilot と Actions を知っている人向けに、各部の対応を整理すると次の通りです。

| 部分 | 役割 | 従来の等価物 |
|------|------|------|
| `on: schedule: daily` | 日次起動 | Actions の `on.schedule` (cron) |
| `permissions: ... read` | エージェントジョブの権限。書き込みなし | Actions の `permissions:` |
| `safe-outputs.create-issue` | 「Issue 作成だけを、この条件なら許す」宣言 | 従来なし(ここが gh-aw 固有) |
| `## Daily Issues Report` 以降 | エージェントへの自然言語の指示 | 従来なら `actions/github-script` + octokit で書いていた命令的コード |

コンパイル結果の `.lock.yml` では、エージェント実行ジョブと Safe Outputs 処理ジョブが分離され、後者にだけ `issues: write` が与えられた 2 ジョブ構成として吐き出されます(抜粋は [gh-aw repo](https://github.com/github/gh-aw) の README やサンプル workflow を参照)。

## 5. どこが従来より便利になったのか

ここが一番大事なパートです。「Copilot と Actions があるんだから、それ組み合わせれば良いのでは?」という疑問に、3 つの比較軸で答えます。

### 5.1 素の Actions YAML + GitHub API スクリプトとの比較

**従来のやり方**:`actions/github-script` や `octokit` を使って、

1. 昨日から今日までの PR / Issue を GitHub API で取得し
2. 件数や傾向を集計し
3. Markdown を組み立て
4. `octokit.issues.create()` する

という**命令的なコードを自前で書く**。対象が「件数集計」程度なら書けますが、「どれが重要か判断して」「言葉を柔らかく整えて」のような主観的要件が入ると途端に手に負えなくなります。

**Agentic Workflows**:Markdown に「何が欲しいか」を書くだけ。判断と文章化は LLM が埋める。しかも出力は `safe-outputs.create-issue` を通るので、**タイトル prefix や label の一貫性はコンパイル時に担保される**。

### 5.2 Copilot / Claude CLI を素の Actions YAML で直接叩くのとの比較

**従来のやり方**:Actions YAML の step で Claude Code や Copilot CLI を起動し、同じジョブの中で `gh issue create` まで走らせる。この方式だと、

- エージェントジョブに **write 権限をまとめて渡さざるを得ない**(task-specific 最小権限が設計しにくい)
- エージェントが回す tool の許可/不許可をコンパイル時に検査する仕組みがない
- Prompt Injection などでエージェントが暴走した場合、Issue だけでなく**任意の write 操作**を実行しうる

公式 Blog もこの点をはっきり指摘しています。

> ...running coding agent CLIs, such as Copilot or Claude, directly inside a standard GitHub Actions YAML workflow. This approach often grants these agents more permission than is required for a specific task. In contrast, GitHub Agentic Workflows run coding agents with read-only access by default and rely on safe outputs for GitHub operations...
> — [Automate repository tasks with GitHub Agentic Workflows](https://github.blog/ai-and-ml/automate-repository-tasks-with-github-agentic-workflows/)

**Agentic Workflows**:

- デフォルト **read-only**
- 書き込みは **safe-outputs で宣言したものだけ**、かつ**別ジョブで gated**
- MCP 呼び出しは **Gateway 経由**で認証情報をエージェントから隠す
- tool allow-listing と compile-time validation が効く

「意図(エージェント)」と「実行(gated job)」を分離しているので、**エージェント側がどんなに説得されても、宣言されていない操作は起きない**。このセキュリティモデルの差が、素の YAML で CLI を直接叩く方式との決定的な違いです。

### 5.3 Copilot CLI / Codex Automations を手元や SaaS UI で動かすのとの比較

`@pelikhan` らの [比較 Issue #13575](https://github.com/github/gh-aw/issues/13575) でも整理されている通り、個人の手元や外部 SaaS UI でコーディングエージェントを回すと、

- 成果物が **個人の環境に閉じる**(チームから見えない、版管理されない)
- 権限管理が GitHub の team / secrets / environment と切り離される
- audit が別システム

といった運用上の断絶が起こります。Agentic Workflows は Actions 上で走るため、

- **repo-centric**:ワークフロー定義も成果物もリポジトリに残る
- **team-visible**:Issue / PR / Discussion として全員が見える
- **version-controlled**:Markdown 自体がコミット対象
- 権限・secrets・audit は既存の GitHub の仕組みそのまま

Copilot / Codex の**コーディング能力**を、**リポジトリに閉じた運用ルール**のもとで使う — という住み分けになります。

## 6. 使いどころと、向かないケース

ここまで書いたとおり、Agentic Workflows は便利ですが**万能ではない**です。

**向くもの**:

- 判断・要約・文章化を含む、**主観的で繰り返し発生する**リポジトリ運用タスク
- Issue / PR / Discussion / コメントという **GitHub ネイティブな成果物**で価値が出るタスク
- 「人間がレビューする前提」の半自動化

**向かないもの**:

- build / test / release / deploy のような、**決定的で冪等に回したい**パイプライン → 引き続き素の Actions YAML
- ms オーダーのレイテンシ要件、厳密な SLA が要る処理
- コスト / 実行時間の予測が重要な処理(LLM コストが載るぶんブレる)

また、冒頭で触れた通り **technical preview / research demonstrator** というステータスです。仕様・フィールド名・デフォルト挙動は今後も変わりえますし、運用中も週次で破壊的変更を含むリリースが入っています([例: 2026-04-13 Weekly Update](https://github.github.com/gh-aw/blog/2026-04-13-weekly-update/))。本番クリティカルな経路に組み込む前に、preview 前提で試すのが安全です。

## 7. まとめ

Agentic Workflows は新しいランタイムではなく、**「Actions の配管」+「Copilot 系 agent の判断力」+「Safe Outputs という審査装置」を束ねた薄い層**だと捉えると見通しがよくなります。

- **何ができるか**:triage / 日次レポート / doc メンテ / CI 失敗調査などの、判断を含む継続タスク
- **なにが可能にしているか**:Markdown → Actions YAML コンパイル、Engine 抽象、MCP Gateway、Safe Outputs、Sandbox + 外向き firewall
- **どこが便利か**:素の YAML + octokit より表現力が高く、Actions 内で Copilot CLI を直叩きするより権限設計と監査が安全で、手元 / SaaS UI よりチーム・リポジトリ中心に情報が残る

Copilot と Actions の既存知識はそのまま活きます。手を動かすなら、[`githubnext/agentics`](https://github.com/githubnext/agentics) の sample workflow を 1 本 fork して、`gh aw` でコンパイルし、低リスクなトリガー(weekly の read-only レポート等)から試すのが入り口として素直です。

### 主な参照先

- [GitHub Agentic Workflows 公式ホーム](https://github.github.com/gh-aw/)
- [GitHub Next: Agentic Workflows プロジェクトページ](https://githubnext.com/projects/agentic-workflows/)
- [Automate repository tasks with GitHub Agentic Workflows(GitHub Blog, 2026-02-13)](https://github.blog/ai-and-ml/automate-repository-tasks-with-github-agentic-workflows/)
- [Under the hood: Security architecture of GitHub Agentic Workflows(GitHub Blog)](https://github.blog/ai-and-ml/generative-ai/under-the-hood-security-architecture-of-github-agentic-workflows/)
- [Safe Outputs MCP Gateway Specification](https://github.github.com/gh-aw/reference/safe-outputs-specification/)
- [Tools リファレンス](https://github.github.com/gh-aw/reference/tools/)
- [`github/gh-aw` リポジトリ](https://github.com/github/gh-aw)
- [`githubnext/agentics` サンプル集](https://github.com/githubnext/agentics)
