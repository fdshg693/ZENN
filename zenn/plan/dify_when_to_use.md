---
title: "Dify はどこに刺さるか — LLM アプリ基盤の使いどころと、別ツールに切り替える線引き"
status: plan
---

## 記事メタ

- 仮タイトル: 「Dify はどこに刺さるか — LLM アプリ基盤の使いどころと、別ツールに切り替える線引き」
- emoji: 🧩
- topics: `["dify", "llm", "ai", "rag", "agent"]`
- 想定読者: LLM アプリを内製しようとしているエンジニア / テックリード。LangChain・LangGraph・LangFlow・Flowise・n8n・Zapier・Azure AI Foundry・OpenAI Assistants・Microsoft Copilot Studio との比較で迷っている人。
- 解決する問題: 「Dify って結局どこに使うべき?どこからは別ツール?」を判断軸ベースで言語化する。チュートリアル記事ではなく、採用 / 非採用の判断記事。

## 導入で示す問い

- LLM アプリ基盤の選択肢は急増しており、「Dify は良さそうだが本番にも使えるのか」「LangChain でコード書くのと比べてどっちが良いのか」「n8n でも作れるよね?」が常に並走する。
- 本記事は **Dify が解いている問題** と **解いていない問題** を機能ベースで分解し、4 カテゴリの代替ツールと比較して **採用 / 撤退ライン** を示す。

## セクション構成と各セクションの主張

### 1. はじめに — なぜ「Dify を選ぶか / 選ばないか」が難しいのか

- 主張: Dify はカテゴリ横断で機能を持っているため、表面比較だと「全部できる」に見えてしまう。判断には「どの問題を解いているか」を切り出す必要がある。
- 根拠 URL:
  - https://github.com/langgenius/dify
  - https://dify.ai/blog/dify-open-source

### 2. Dify が解いている問題 — 「LLM アプリ基盤」の再定義

- 主張: Dify は **LLM オーケストレーション + RAG + Agent + 配信(WebApp/API) + LLMOps** を 1 プロダクトに統合した「LLM アプリの App Service 的存在」。プロトタイプから本番までを 1 ツールでカバーする思想。
- スタック: Python/Flask/PostgreSQL バックエンド、Next.js フロントエンド、コードベース 13 万行超、平均週 1 回リリース。
- 根拠 URL:
  - https://legacy-docs.dify.ai/getting-started/readme/features-and-specifications
  - https://github.com/langgenius/dify

### 3. 機能マップ — 7 つの機能カテゴリ

ここは「どの機能が、どんな問題を解くために存在するか」を図解。

1. **モデル統合**: 商用 10+(OpenAI, Anthropic 他、新モデルは 48 時間以内に対応)、MaaS 7(HuggingFace, Replicate, Bedrock, NVIDIA, Groq, together.ai, OpenRouter)、ローカル推論 6(Ollama, OpenLLM, LocalAI, Xorbits, ChatGLM, NVIDIA TIS)。
2. **アプリ種別**: Text generation / Chatbot / Agent / Workflow / Chatflow の 5 種。
3. **Workflow**: ビジュアル DSL、live-edit デバッグ、ノード(LLM, Knowledge Retrieval, Question Classifier, IF/ELSE, CODE, Template, HTTP Request, Tool)。
4. **RAG パイプライン**: キーワード/ベクター/LLM 補助インデクシング、ハイブリッド検索、Rerank、TXT/MD/PDF/HTML/DOC/CSV の自動 ETL、Notion/Web 同期。
5. **Agent**: Function Calling / ReAct ベース、ビルトインツール 50+(Google Search, DALL·E, SD, WolframAlpha 等)。
6. **Observability / LLMOps**: Opik, Langfuse, Arize Phoenix, LangSmith をワンクリック接続(運用後の改善ループ)。
7. **Backend-as-a-Service**: 全機能に API、自社プロダクトへの組込み前提。
- 根拠 URL:
  - https://legacy-docs.dify.ai/getting-started/readme/features-and-specifications
  - https://github.com/langgenius/dify
  - https://dify.ai/blog/dify-integrates-langsmith-langfuse

### 4. Dify が刺さる場面(具体ユースケース)

- **AI が主役のアプリ作り**: Chatbot / RAG アシスタント / Agent。AI 以外の要素が薄いケース。
- **超短期プロトタイピング → そのまま本番**: 公式が「LangChain の学習時間で Dify なら数十のアプリが動く」と主張するスピード重視。
- **マルチモデル比較**: Prompt IDE で同一プロンプトを複数モデルへ流して評価。
- **規制業界の社内 AI**: GDPR / HIPAA / SOC 2 など、データを外に出せない要件 → Self-hosted。
- **エンタープライズ機能が必要**: SSO / Access Control が必要(LangChain / Flowise には無い)。
- **チームでのプロンプト共同編集**: 開発者と非開発者が同じ画面でプロンプトを更新したい。
- 根拠 URL:
  - https://github.com/langgenius/dify
  - https://github.com/Decentralised-AI/Dify-is-an-open-source-LLM-app-development-platform.
  - https://dify.ai/blog/openai-assistants-api-vs-dify-self-hosting-flexible-ai-solutions

### 5. 別ツールを検討すべき場面 — 4 カテゴリで線引き

#### 5.1 vs LangChain / LangGraph(コードファースト LLM フレームワーク)

- 切替条件: コード上で細かく制御したい / Git 完全管理したい / 動的にエージェント設計を変えたい / 大規模本番(LangGraph は Klarna・Uber・JPM・LinkedIn 採用)。
- Dify 選択理由: 「足場は欲しい、ロジックは書きたくない」。
- 根拠 URL:
  - https://dify.ai/blog/dify-vs-langchain
  - https://github.com/itsual/Agentic---Gen-AI

#### 5.2 vs Flowise / LangFlow(他の OSS ノーコード LLM)

- 切替条件: より軽量・シンプルで良い / LangChain ベースの薄い UI が欲しい / RAG 単機能で十分。
- Dify 選択理由: Workflow + Agent + Enterprise 機能 + LLMOps を統合したい(Flowise は Workflow 弱い、Agent なし)。
- 根拠 URL:
  - https://github.com/Decentralised-AI/Dify-is-an-open-source-LLM-app-development-platform.(機能比較表)
  - https://github.com/itsual/Agentic---Gen-AI

#### 5.3 vs n8n / Zapier / Make(汎用ワークフロー自動化)

- 切替条件: AI は 1 ステップに過ぎず、SaaS 連携が主役。n8n は 400+、Zapier は 7,000+ 統合。
- Dify 選択理由: LLM オーケストレーション・RAG・Agent がネイティブ機能で必要。
- 線引き: 「The AI is just one step」なら n8n、「AI is the product」なら Dify。
- 根拠 URL:
  - https://www.linkedin.com/posts/nechyporenko_ai-llm-aiengineering-activity-7414685487501733888-BXdS
  - https://www.browseract.com/blog/best-n8n-alternatives-zapier-make-dify-coze-compared
  - https://www.datacamp.com/blog/n8n-vs-zapier

#### 5.4 vs Azure AI Foundry / OpenAI Assistants / Microsoft Copilot Studio

- 切替条件:
  - **Foundry**: Azure に強くロックイン / モデルカタログ 1,600+ / VNet 隔離・RBAC / コードファースト SDK が必要。
  - **OpenAI Assistants**: OpenAI モデルしか使わない / シンプルな単一会話アシスタント。
  - **Copilot Studio**: Microsoft 365 / Teams / Outlook / Power Platform への深統合が主目的。
- Dify 選択理由: ベンダーロックインを避け、複数モデル横断、Self-hosted 可能、より柔軟な Workflow / RAG が必要。
- 注意: Copilot Studio と Foundry は併用パターンが推奨されており、二者択一ではない。
- 根拠 URL:
  - https://github.com/Decentralised-AI/Dify-is-an-open-source-LLM-app-development-platform.
  - https://www.sharepointeurope.com/choosing-between-microsoft-copilot-studio-and-azure-ai-foundry-a-comprehensive-guide/
  - https://dynatechconsultancy.com/blog/microsoft-copilot-vs-copilot-studio-vs-azure-ai-foundry
  - https://dify.ai/blog/openai-assistants-api-vs-dify-self-hosting-flexible-ai-solutions

### 6. SaaS vs Self-hosted — ライセンスと運用の現実

- **SaaS(Dify Cloud)**: Sandbox(無料、200 GPT-4 calls)/ Professional($59/workspace/月、5,000 messages・3 members・50 apps・500 docs・5GB)/ Team($159/workspace/月)。
- **Self-hosted**: Docker Compose / Helm / Terraform / AWS CDK のサンプル提供、エンタープライズ機能込み。
- **ライセンスの注意点(重要)**: Dify Open Source License = Apache 2.0 をベースに **追加条件**:
  - **マルチテナント運用には商用ライセンス必須**(1 テナント = 1 workspace の定義)。SaaS 風に他社へ提供する場合は別途契約。
  - **コンソール/アプリの LOGO・著作権表示の改変不可**(`web/` 配下、Docker の web イメージ)。フロントエンドを使わない用途は対象外。
- 根拠 URL:
  - https://dify.ai/pricing
  - https://github.com/langgenius/dify/blob/main/LICENSE
  - https://github.com/langgenius/dify

### 7. まとめ — 採用判断フローチャート

- 「AI が主役 / プロト→本番を 1 ツールで / マルチモデル試行」→ Dify
- 「コードで完全制御 / 大規模ステートフル Agent」→ LangGraph
- 「業務自動化主体で AI は 1 ノード」→ n8n
- 「Microsoft 365 / Teams 統合主体」→ Copilot Studio
- 「Azure 上で本格的に作り込む」→ Azure AI Foundry(Dify と併用も可)
- 「マルチテナント SaaS として提供したい」→ Dify は商用ライセンス必須、要検討

## 各セクションが参照する `temp/dify_article/` 内ファイル

- `search_dify_overview.json` — 機能概要・Observability 統合
- `extract_dify_core.json` — README、Features and Specifications、Pricing
- `search_extract_dify_vs_frameworks.json` — LangChain / LangGraph / Flowise / LangFlow
- `search_extract_dify_vs_ipaas.json` — n8n / Zapier / Make
- `search_extract_dify_vs_cloud.json` — Foundry / Assistants / Copilot Studio
- `extract_dify_license.json` — Open Source License の追加条件全文

## 不足情報・残課題

- Self-hosted の Community 版でどのエンタープライズ機能が含まれ、Premium / Enterprise 版で何が追加されるかの公式境界 → 必要なら本文段階で `extract_url_content.py` で公式エンタープライズページを当てる。
- ノード上限・同時実行・レイテンシなどの定量上限 → 公式 Docs に明記がなければ「公式参照」で逃がす。
- Dify v1.x 系のプラグイン仕様(Marketplace 動向)→ 本文中で軽く触れる程度。
