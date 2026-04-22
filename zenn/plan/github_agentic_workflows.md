---
title: "GitHub Agentic Workflows を Copilot と Actions を知っている人向けに解説する"
status: plan
---

## 対象読者と前提

- GitHub Copilot(コーディングエージェントとしての Copilot CLI / IDE 統合)を日常的に使っている
- GitHub Actions の YAML ワークフロー、`on:` トリガー、permissions、secrets、runner の基本を理解している
- 「結局 Agentic Workflows って Actions と何が違うの?Copilot を Actions で動かすのと何が違うの?」という疑問を持っている

## 記事で答える問い

1. **GitHub Agentic Workflows で何ができるのか**(具体例とユースケースの輪郭)
2. **なにがそれを可能にしているのか**(Markdown → Actions YAML コンパイル、MCP ツール、Safe Outputs、Sandbox)
3. **どこが従来より便利になったのか**(素の Actions YAML / 素の Copilot CLI を Actions で走らせる場合との比較)

## 扱う範囲 / 扱わない範囲

- 扱う: 概念、アーキテクチャの全体像、frontmatter の要点、Safe Outputs の仕組み、Sandbox / MCP Gateway、Copilot・Claude・Codex の切替、従来手法との比較
- 扱わない: `gh aw` CLI の全コマンド網羅、全 frontmatter フィールドの網羅、特定エンジンの API 料金比較、実運用でのデバッグ Tips

## 前提ステータス

- **Technical preview / research demonstrator** (GitHub Next × Microsoft Research、2026-02-13 に GitHub Blog で announce、現時点でも active に更新中)
- 本記事ではこの preview ステータスを必ず明記する

## 仮タイトル案

1. 「GitHub Agentic Workflows は Actions と何が違うのか — Markdown から Continuous AI を回す仕組み」
2. 「Copilot と Actions を知っている人のための GitHub Agentic Workflows 入門」
3. 「Markdown ワンファイルでリポジトリを自走させる — GitHub Agentic Workflows の仕組みと便利さ」

現状の第一候補: 2。

## セクション構成案

### 1. はじめに — Actions と Copilot の「あいだ」にある空白

- Actions は決まった手順を回す(CI/CD 向き・決定的)
- Copilot は対話的に書き手を助ける(単発・対話的)
- では「リポジトリの日常的な面倒ごとを、勝手に・継続的に・安全に処理させたい」ときに何を書くべきか?
- そこに埋まるのが GitHub Agentic Workflows(以下 gh-aw)
- 根拠: [automate-repository-tasks 公式 Blog](https://github.blog/ai-and-ml/automate-repository-tasks-with-github-agentic-workflows/), [gh-aw ホーム](https://github.github.com/gh-aw/)

### 2. 何ができるのか — ユースケースの輪郭

- Markdown 1 ファイルで、以下のような「主観的・継続的」タスクを自動化できる:
  - Issue / PR triage, labeling, project 整理
  - Continuous documentation(docs の継続メンテ)
  - 日次 code simplification / refactor
  - メトリクス・活動レポート
  - CI failure diagnosis(壊れたビルドの原因を agent に調べさせる)
  - multi-repo の feature sync
  - `/plan` `/fix` などの command-triggered workflow(コメントで起動)
- Continuous AI という位置付け:**CI/CD を置き換えるものではなく、CI/CD がやりづらかった「判断・要約・調査」を補完する層**
- 根拠: [gh-aw ホーム Gallery](https://github.github.com/gh-aw/), [githubnext/agentics README](https://github.com/githubnext/agentics), [automate-repository-tasks 公式 Blog](https://github.blog/ai-and-ml/automate-repository-tasks-with-github-agentic-workflows/)

### 3. なにがそれを可能にしているのか — アーキテクチャ 4 つの柱

#### 3.1 Markdown → Actions YAML コンパイル

- `.github/workflows/*.md` に frontmatter + 自然言語プロンプトを書く
- `gh aw` CLI extension で `.lock.yml` として GitHub Actions ワークフローに**コンパイル**
- 実行時は普通の Actions として動く → ログ、権限、環境、secrets、audit がそのまま効く
- 根拠: [githubnext/projects/agentic-workflows/](https://githubnext.com/projects/agentic-workflows/)「compiled to existing GitHub Actions workflows (YAML)」, [gh-aw ホーム](https://github.github.com/gh-aw/) サンプル frontmatter

#### 3.2 Engine 抽象(Copilot / Claude / Codex の切替)

- frontmatter の `engine:` で選択(`copilot` / `claude` / `codex` / custom)
- エージェント独立性が設計原則:LLM 変更でワークフローを書き直さなくていい
- 根拠: [githubnext/projects/agentic-workflows/](https://githubnext.com/projects/agentic-workflows/)「Model and coding agent independence」, [gh-aw ホーム](https://github.github.com/gh-aw/)

#### 3.3 MCP ツールと Tools 宣言

- `tools:` frontmatter で使える能力を明示:`edit`, `bash`, `github` (API 操作), `playwright`, `web-fetch`, 任意の MCP サーバ等
- MCP サーバ呼び出しは **MCP Gateway** 経由で一元化され、認証情報はエージェントの container に露出しない
- 根拠: [Tools リファレンス](https://github.github.com/gh-aw/reference/tools/), [Security Architecture Blog](https://github.blog/ai-and-ml/generative-ai/under-the-hood-security-architecture-of-github-agentic-workflows/)

#### 3.4 Safe Outputs — 「依頼 → 審査 → 実行」の二段構え

- デフォルトは **read-only**(`permissions: contents: read` 相当)
- エージェントは GitHub に直接書き込めない。代わりに「こういう issue を作って」といった**意図を NDJSON 構造化アーティファクト**として出力する
- 別ジョブ(scoped write 権限)がそれを読み、`safe-outputs:` frontmatter の制約(max件数、title-prefix、labels、本文長)に照らしてサニタイズ後に GitHub API を叩く
- 例: `create_issue` は title 256 文字 / body 65536 文字、add_comment は mentions 10 件までなどの hard limit
- 根拠: [gh-aw ホーム](https://github.github.com/gh-aw/) "Safe outputs with strong guardrails", [Safe Outputs 仕様](https://github.github.com/gh-aw/reference/safe-outputs-specification/), [Security Architecture Blog](https://github.blog/ai-and-ml/generative-ai/under-the-hood-security-architecture-of-github-agentic-workflows/)

#### 3.5 Sandbox と Egress 制御

- エージェントは dedicated container に隔離され、外向き通信は firewall で制限(AWF: agent web firewall)
- LLM API トークンは API proxy 内にあり、エージェントコンテナからは見えない
- `sandbox.agent: awf` と `network.allowed` ドメインリストで通信許可を明示
- 根拠: [Security Architecture Blog](https://github.blog/ai-and-ml/generative-ai/under-the-hood-security-architecture-of-github-agentic-workflows/), [gh-aw Discussion #25936](https://github.com/github/gh-aw/discussions/25936)

### 4. 最小サンプル — 日次レポート workflow を読む

- 公式ホームの "daily report" frontmatter + Markdown 本文を引用し、各フィールドが何を意味するか分解して解説
- `on: schedule: daily`、`permissions: contents/issues/pull-requests: read`、`safe-outputs.create-issue` の `title-prefix` `labels` `close-older-issues` を対応付けて読ませる
- 根拠: [gh-aw ホーム](https://github.github.com/gh-aw/) daily report frontmatter example

### 5. どこが従来より便利になったのか — 3 パターンとの比較

#### 5.1 「素の Actions YAML + GitHub API スクリプト」との比較

- 従来: `actions/github-script` + octokit で branch を比較、issue 本文を組み立てる、等の**命令的スクリプト**を自力で書く
- gh-aw: 「今日の活動をまとめて issue を 1 本立てて」を**自然言語で書く**だけ。判断の部分を LLM が埋める
- 根拠: [GitHub Next プロジェクトページ](https://githubnext.com/projects/agentic-workflows/)

#### 5.2 「Copilot / Claude CLI を素の Actions YAML 内で直接叩く」との比較

- 従来: YAML の step に `claude-code` などを呼び、`permissions: write-all` に近い権限を渡しがち
- gh-aw: デフォルト read-only + safe-outputs で **意図と実行を分離**、compile-time validation と tool allow-listing が効く
- 根拠: [automate-repository-tasks Blog](https://github.blog/ai-and-ml/automate-repository-tasks-with-github-agentic-workflows/) "One alternative approach..." 段落, [Security Architecture Blog](https://github.blog/ai-and-ml/generative-ai/under-the-hood-security-architecture-of-github-agentic-workflows/)

#### 5.3 「Copilot CLI / Codex Automations を手元や SaaS UI で動かす」との比較

- 従来: 個人環境で走る → 成果物は個人に閉じる、repo-centric ではない
- gh-aw: Actions 上で走るので、権限・secrets・logs・audit が**リポジトリ中心**にまとまる。team-visible / version-controlled
- 根拠: [gh-aw Issue #13575 Codex automations 比較](https://github.com/github/gh-aw/issues/13575)

### 6. 使いどころと向かないケース

- 向く: 主観的・継続的・判断を挟むタスク(triage, 要約, 傾向分析, doc 更新提案)
- 向かない: build / test / release など**決定的に回したいパイプライン**。これは素の Actions に任せる
- preview ステータスなので本番クリティカル運用には慎重に
- 根拠: [automate-repository-tasks Blog](https://github.blog/ai-and-ml/automate-repository-tasks-with-github-agentic-workflows/) "designed to augment existing CI/CD rather than replace it"

### 7. まとめ

- gh-aw は「Actions の配管」+「Copilot 系 agent の判断力」+「Safe Outputs という審査装置」を束ねた薄い層
- Copilot と Actions の知識はそのまま活きる
- まずは [`githubnext/agentics`](https://github.com/githubnext/agentics) の sample を fork して 1 本動かしてみるのが近道

## 根拠ファイル

- `temp/github_agentic_workflows/search_overview.json`
- `temp/github_agentic_workflows/extract_main.json`
- `temp/github_agentic_workflows/search_security.json`
- `temp/github_agentic_workflows/extract_frontmatter.json`
- `temp/github_agentic_workflows/search_blog.json`
- `temp/github_agentic_workflows/extract_blogs.json`

## topics 候補

`github`, `githubactions`, `copilot`, `ai`, `agent`
