---
title: "Dify はどこに刺さるか — LLM アプリ基盤の使いどころと、別ツールに切り替える線引き"
emoji: "🧩"
type: "tech"
topics: ["dify", "llm", "ai", "rag", "agent"]
published: false
---

## この記事について

LLM アプリ基盤の選択肢が一気に増えた結果、「**Dify は良さそうだが、本番に使ってよいのか**」「**LangChain でコードを書くのと比べてどっちが速いのか**」「**n8n でも作れる気がするが、どこから別ツール扱いなのか**」が並走するようになった。

この記事は Dify の **チュートリアルではない**。Dify が「**何を解いているプロダクトなのか**」を機能ベースで切り出し、4 カテゴリの代替ツールと並べて、**採用 / 撤退ラインを言語化する**ことを目的とする。

想定読者:

- LLM アプリを業務で内製しようとしているエンジニア / テックリード
- LangChain・LangGraph・LangFlow・Flowise・n8n・Zapier・Azure AI Foundry・OpenAI Assistants・Microsoft Copilot Studio との比較で迷っている人
- 「とりあえず触ってみたが、本番採用して良いか判断軸がほしい」状態の人

扱わないもの:

- Dify の画面操作チュートリアル
- 個別 LLM のモデル比較
- RAG / Agent の理論解説

## 1. なぜ「Dify を選ぶか / 選ばないか」が難しいのか

Dify は **カテゴリ横断で機能を持っている**。LLM フレームワークでもあり、RAG エンジンでもあり、ノーコードビルダでもあり、ワークフロー基盤でもあり、LLMOps プラットフォームでもある。

機能表だけを眺めると「**全部できるじゃん**」に見えてしまう。だから「LangChain と比べて...」「n8n と比べて...」が同時に成立してしまい、議論がいつまで経っても収束しない。

この記事の方針は単純で、**Dify は何を解くために設計されたプロダクトか** をまず確定し、そのうえで「同じ問題を別の角度で解いているツール」と比較する。

## 2. Dify が解いている問題 — 「LLM アプリ基盤」の再定義

公式自身は Dify を「**プロダクションレディな agentic workflow 開発プラットフォーム**」と位置付けている([GitHub README](https://github.com/langgenius/dify))。実体としては以下を 1 つに束ねた統合基盤と捉えるのが分かりやすい。

- **LLM オーケストレーション**(プロンプト IDE / モデル切り替え / Workflow)
- **RAG パイプライン**(取り込み・分割・ベクター化・検索・Rerank)
- **Agent ランタイム**(Function Calling / ReAct + ビルトインツール)
- **配信レイヤ**(WebApp 公開 / API 公開 / 埋め込み)
- **LLMOps**(ログ / アノテーション / Observability 連携)

スタックは Python / Flask / PostgreSQL バックエンドに Next.js フロントエンド、コードベースは **13 万行超**、リリースは平均週 1 回([Features and Specifications](https://legacy-docs.dify.ai/getting-started/readme/features-and-specifications))。商用モデルは 48 時間以内に新規対応するとされている。

ざっくり比喩でいえば、「**LLM アプリの App Service**」のような存在で、**プロトタイプから本番まで 1 ツールで完結させる思想** がコアだ。これが「Dify が解いている問題」の輪郭になる。

## 3. 機能マップ — 7 つのカテゴリ

Dify の機能は表面的には膨大だが、以下 7 カテゴリに分けて整理すると判断しやすい。

### 3.1 モデル統合

- 商用モデル 10+ プロバイダ(OpenAI / Anthropic 他)
- MaaS 7(Hugging Face / Replicate / AWS Bedrock / NVIDIA / Groq / together.ai / OpenRouter)
- ローカル推論ランタイム 6(Ollama / OpenLLM / LocalAI / Xorbits / ChatGLM / NVIDIA TIS)
- OpenAI 互換 API モデルを「無制限」に追加可能

→ **モデル抽象層をプロダクト側で持ちたい場合の負担を Dify に肩代わりさせられる** のがここの価値。

### 3.2 アプリ種別

5 種のテンプレートが提供される。

- Text generation(単発生成)
- Chatbot(マルチターン会話)
- Agent(ツール使用 / 自律推論)
- Workflow(明示的なフロー)
- Chatflow(会話型 + フロー)

「アプリのガラ」が最初から用意されているので、ゼロから配信レイヤを書く必要がない。

### 3.3 Workflow

ビジュアル DSL で組み立て、live-edit デバッグが可能。標準ノードは以下。

- LLM
- Knowledge Retrieval(RAG)
- Question Classifier(分岐)
- IF/ELSE
- CODE(Python サンドボックス)
- Template(Jinja 風テンプレート)
- HTTP Request
- Tool

LangGraph や n8n と同じ「フロー型」だが、**LLM ノード前提に最適化されている** のが特徴。

### 3.4 RAG パイプライン

- インデクシング: キーワード / ベクター / LLM 補助の 3 系統
- 検索: ハイブリッド検索 / 多経路 retrieval / Rerank モデル
- ETL: TXT / Markdown / PDF / HTML / DOC / CSV を自動処理、Notion / Web ページ同期
- ベクター DB: 複数バックエンドに対応

「自分で LangChain + ベクター DB + Rerank を貼り合わせる」工程をワンセットで提供してくる、ここが Dify の最も実利的な機能だ。

### 3.5 Agent

- LLM Function Calling または ReAct ベース
- ビルトインツール 50+(Google Search / DALL·E / Stable Diffusion / WolframAlpha 等)
- カスタムツールの追加可

### 3.6 Observability / LLMOps

- LangSmith / Langfuse / Opik / Arize Phoenix への接続が **ワンクリック**([Dify × Langfuse / LangSmith](https://dify.ai/blog/dify-integrates-langsmith-langfuse))
- ログ・アノテーション・データセット管理を内蔵

→ Dify 単体で改善ループが閉じる。「とりあえず動いた後の運用」までを一貫して持てる。

### 3.7 Backend-as-a-Service

すべての機能に対応する API があり、Dify 自体を「裏側のサービス」として既存プロダクトに組み込める。フロント・配信を自社で持っている場合に効く。

## 4. Dify が刺さる場面

機能マップを踏まえると、Dify は以下の文脈で特に強い。

### 4.1 「AI が主役」のアプリ作り

Chatbot / RAG アシスタント / Agent のように、**プロダクトの中心に LLM がある** ケース。AI 以外のステップ(SaaS 連携、データパイプライン)は脇役で、対話やナレッジ検索が本体になっているもの。

### 4.2 プロトタイプ → そのまま本番

Dify 公式は「LangChain の学習に費やす時間で、Dify なら数十のアプリを動かせる」と主張している([Dify vs LangChain](https://dify.ai/blog/dify-vs-langchain))。これはマーケティング言ではあるが、**「画面で組み、API で公開し、ログを見て直す」が一直線で繋がっている** のは事実で、PoC からそのまま運用に入れる。

### 4.3 マルチモデル比較が日常的に必要

Prompt IDE で同じプロンプトを複数モデルに流せる。OpenAI / Claude / ローカル LLM の **同条件比較**をプロダクトの内部要件にしているチームには、これがそのまま開発環境になる。

### 4.4 規制業界の社内 AI

GDPR / HIPAA / SOC 2 などでデータを外に出せない要件があり、それでも RAG / Agent を業務に組み込みたい場合、**Self-hosted で同等機能が動く**ことが選定理由になる。

### 4.5 エンタープライズ機能(SSO / アクセス制御)が必要

LangChain や Flowise は OSS フレームワークなので、SSO・ロール管理は自前。Dify は **これを最初から内蔵** している([機能比較](https://github.com/Decentralised-AI/Dify-is-an-open-source-LLM-app-development-platform.))。社内導入の敷居が下がる。

### 4.6 開発者と非開発者が同じ画面でプロンプトを直したい

「プロンプトの書き換え」をエンジニア以外が触れる必要があるチームに向いている。Git PR 経由でなく、共同編集 UI で当てにいける。

## 5. Dify ではなく別ツールを検討すべき場面

ここが本記事の肝。**カテゴリ別に切り分ける** のが整理の鍵になる。

### 5.1 vs LangChain / LangGraph(コードファースト LLM フレームワーク)

| 観点 | Dify | LangChain | LangGraph |
| --- | --- | --- | --- |
| 開発スタイル | UI + DSL + API | Python コード | Python コード(状態機械) |
| 動的なフロー変更 | 限定的 | 自由 | 自由 |
| Git 完全管理 | DSL を export 可だが UI 中心 | 自然 | 自然 |
| 大規模本番事例 | 多数 | 多数 | Klarna / Uber / J.P. Morgan / LinkedIn |

**切り替え条件:**

- コードレベルで細かく制御したい(プロンプトの動的合成、複雑なリトライ、部分的なツール選択ロジック)
- Git・CI / CD・コードレビューを完全に通したい
- ステートフルなマルチエージェントを設計する(LangGraph は状態機械が一級概念)

**Dify を選ぶ理由:**

- 「足場(scaffolding)は欲しい、ロジックは書きたくない」場合
- LangChain でいう Chain / Tool 周辺の貼り合わせを **プロダクト側の関心事から外したい** 場合

### 5.2 vs Flowise / LangFlow(他の OSS ノーコード LLM)

機能比較表のエッセンスは以下([比較表ソース](https://github.com/Decentralised-AI/Dify-is-an-open-source-LLM-app-development-platform.))。

| 機能 | Dify | LangChain | Flowise | OpenAI Assistants |
| --- | --- | --- | --- | --- |
| RAG | ✅ | ✅ | ✅ | ✅ |
| Agent | ✅ | ✅ | ❌ | ✅ |
| Workflow | ✅ | ❌ | ✅ | ❌ |
| Observability | ✅ | ✅ | ❌ | ❌ |
| Enterprise(SSO 等) | ✅ | ❌ | ❌ | ❌ |
| Local Deployment | ✅ | ✅ | ✅ | ❌ |

**切り替え条件:**

- もっと軽量で良い、依存を増やしたくない
- LangChain ベースの薄い UI で十分(Flowise は LangChain のグラフ的 UI)
- 用途が RAG 単機能や単純なエージェントに収まる

**Dify を選ぶ理由:**

- Workflow + Agent + Enterprise + LLMOps をまとめて欲しい(Flowise / LangFlow ではここがピースで欠ける)

### 5.3 vs n8n / Zapier / Make(汎用ワークフロー自動化)

ここは「**LLM 中心か / 業務自動化中心か**」で分かれる。

| ツール | 統合数 | 強み | 弱み |
| --- | --- | --- | --- |
| Dify | LLM 系に特化 | LLM オーケストレーション・RAG・Agent をネイティブ提供 | SaaS 連携の網羅性は弱い |
| n8n | 400+ | OSS / Self-hosted / AI ノード追加 | 50+ ノードで UI が複雑化、undo なし、非開発者には学習が急 |
| Zapier | 7,000+ | フルマネージドの圧倒的な統合数 | LLM 連携は外部 API 経由、Self-hosted 不可 |
| Make | 中規模 | ビジュアル指向 | 無料枠の 5 分タイムアウトで重い処理に不向き |

(出典: [n8n vs Zapier - DataCamp](https://www.datacamp.com/blog/n8n-vs-zapier)、[browseract: n8n alternatives](https://www.browseract.com/blog/best-n8n-alternatives-zapier-make-dify-coze-compared))

**判断ルール(かなり実用的):**

- **「The AI is just one step」**(AI は処理の 1 ステップに過ぎない、本体は SaaS 連携)→ n8n / Zapier
- **「AI is the product」**(AI が成果物そのもの)→ Dify

「Slack に来た問い合わせを Salesforce に登録して GPT で要約してメール返信」のようなフローは、**LLM ステップは全体の 1/5 程度**。これは n8n の領分だ。一方、「社内ドキュメントに対して RAG で回答する Bot を作って Teams に流す」のような場合、業務連携ステップはほぼ無く LLM が中心になる。これは Dify の領分。

### 5.4 vs Azure AI Foundry / OpenAI Assistants / Microsoft Copilot Studio

クラウドベンダー側の LLM 基盤との比較は最も誤解されやすい。

#### Azure AI Foundry

- モデルカタログ 1,600+(GPT-4o / Llama 3 / Mistral / BYOM 等)
- コードファースト(SDK / CLI / VS Code)中心
- Azure RBAC / VNet 隔離推論 / Key Vault / 100+ コンプライアンス認証(HIPAA / GDPR / ISO)
- 出典: [SharePoint Europe: Foundry vs Copilot Studio](https://www.sharepointeurope.com/choosing-between-microsoft-copilot-studio-and-azure-ai-foundry-a-comprehensive-guide/)

**Foundry を選ぶ場面:** Azure に深くロックインしている / 厳しいネットワーク隔離が必要 / 大規模に Azure 上で組み込み開発する。

#### OpenAI Assistants API

- OpenAI モデル限定 / 単一会話アシスタント / Workflow なし / Observability なし / Local Deployment 不可

**Assistants を選ぶ場面:** OpenAI 縛りで全く問題なく、用途が単一の会話アシスタントだけ。

#### Microsoft Copilot Studio

- Power Platform 1,000+ コネクタ
- Teams / Outlook / Web / Mobile への配信
- Microsoft 365 DLP / Purview / Entra ID 統合
- 「**AI worker を作るのが Copilot Studio、AI infrastructure を作るのが Foundry**」と整理されている([Dynatech](https://dynatechconsultancy.com/blog/microsoft-copilot-vs-copilot-studio-vs-azure-ai-foundry))
- Copilot Studio から Foundry 登録モデルを HTTP / MCP で呼び出す併用パターンが推奨

**Copilot Studio を選ぶ場面:** Microsoft 365 / Teams / Outlook への深統合が主目的。社員が Teams 内で完結して触ることが要件。

#### Dify を選ぶ理由(対クラウドベンダー)

- ベンダーロックインを避けたい
- 複数モデル横断・OSS モデル併用が常態
- Self-hosted 可能性が要件
- Azure / Microsoft 365 を必須としない

なお、これらは二者択一とは限らない。**Foundry 上にモデルを置き、Dify をフロント基盤として被せる** といった併用も実務では十分あり得る。

## 6. SaaS 版 vs Self-hosted 版 — ライセンスの落とし穴

Dify には Cloud(SaaS)と Self-hosted の 2 系統があり、選択がそのまま **ライセンス上の判断** につながる。ここを軽く扱うと後でつまずく。

### 6.1 Dify Cloud の料金階層

[公式 Pricing](https://dify.ai/pricing) より概略。料金は変動するため詳細は公式参照。

- **Sandbox**: 無料、200 GPT-4 calls 付与
- **Professional**: $59 / workspace / 月、5,000 message credits、3 members、50 apps、500 docs、5GB
- **Team**: $159 / workspace / 月

「workspace 単位の課金」なので、複数チーム展開の試算では workspace 数が効く。

### 6.2 Self-hosted の選択肢

- Docker Compose、Helm、Terraform、AWS CDK のサンプルが公式提供
- エンタープライズ機能(SSO / アクセス制御)も含む
- データを外に出せない要件を満たす(GDPR / HIPAA / SOC 2 等)

### 6.3 ライセンスの注意点(必ず読む)

Dify は「**Dify Open Source License**」という Apache 2.0 をベースにした **追加条件付き** ライセンスを採用している([LICENSE 全文](https://github.com/langgenius/dify/blob/main/LICENSE))。重要な追加条件は 2 つ。

#### a. マルチテナント運用には商用ライセンスが必要

> Multi-tenant service: Unless explicitly authorized by Dify in writing, you may not use the Dify source code to operate a multi-tenant environment.

> Tenant Definition: Within the context of Dify, one tenant corresponds to one workspace.

つまり、**Dify をベースに「他社向け SaaS」として提供する** 構成(複数顧客がそれぞれ workspace を持つ形態)は、原則として **書面での商用ライセンス契約** が必要になる。社内 1 テナントで使う限りは問題ない。

#### b. LOGO・著作権表示の改変不可

> LOGO and copyright information: In the process of using Dify's frontend, you may not remove or modify the LOGO or copyright information in the Dify console or applications.

`web/` 配下(Docker の `web` イメージ)に対する制限。**Dify のフロントエンドを使う限り、ロゴと著作権は外せない**。完全自社ブランドで配信したい場合は、フロントエンドを使わず BaaS API 経由にするか、商用ライセンスでの相談になる。

### 6.4 実務上の判断

- **社内ツールとして 1 テナントで使う** → OSS のまま使える
- **顧客に AI 機能を提供するが、Dify はバックエンドだけ使う(自社フロント)** → フロントエンド条項は対象外、ただし「マルチテナント」に該当するかは要確認
- **Dify をそのまま顧客に SaaS 提供する** → 商用ライセンスが必要

ここは法務確認が要るので、**プロダクト戦略を立てる初期段階で確認しておくべき項目**だ。

## 7. まとめ — 採用判断フローチャート

ここまでの整理を 1 枚に圧縮する。

```
- AI が主役 / プロト → そのまま本番にしたい
  → Dify

- コードで完全制御 / 大規模ステートフル Agent
  → LangGraph(LangChain)

- AI は処理の 1 ステップ、本体は業務連携
  → n8n(Self-hosted)/ Zapier(マネージド)

- Microsoft 365 / Teams 統合が主目的
  → Microsoft Copilot Studio

- Azure 前提で本格開発、ネットワーク隔離が必須
  → Azure AI Foundry(必要なら Dify と併用)

- 単一 OpenAI モデルだけで足りる単純アシスタント
  → OpenAI Assistants API

- 軽量な OSS ノーコード LLM が欲しい
  → Flowise / LangFlow

- Dify をマルチテナント SaaS として再配布したい
  → Dify(商用ライセンス契約が必要)
```

Dify は「全部できる」ツールではなく、「**LLM がプロダクトの中心にいるアプリを、UI と API 両面から最短で作って運用に乗せる**」ことに最適化されたプロダクトだ。これに合致する場面では強烈に効くし、合致しない場面では別カテゴリのツールを選ぶ方がはるかに早い。

判断のポイントは結局のところ次の 3 問に集約される。

1. **AI はプロダクトの中心か、それとも 1 ステップか?**
2. **コードで完全に制御したいか、それとも UI と DSL で十分か?**
3. **どこで動かすのか(SaaS / Self-hosted / クラウドベンダー上)、そしてマルチテナント配布する予定はあるか?**

この 3 問に明確に答えられた段階で、選択肢はほぼ自動的に絞られる。

## 参考資料

- [GitHub: langgenius/dify](https://github.com/langgenius/dify) — 公式 README、機能一覧、機能比較表
- [Dify Features and Specifications](https://legacy-docs.dify.ai/getting-started/readme/features-and-specifications)
- [Dify Pricing](https://dify.ai/pricing)
- [Dify Open Source License(LICENSE 全文)](https://github.com/langgenius/dify/blob/main/LICENSE)
- [Dify × LangSmith / Langfuse 統合](https://dify.ai/blog/dify-integrates-langsmith-langfuse)
- [Dify vs LangChain(公式)](https://dify.ai/blog/dify-vs-langchain)
- [OpenAI Assistants API vs Dify(公式)](https://dify.ai/blog/openai-assistants-api-vs-dify-self-hosting-flexible-ai-solutions)
- [Choosing between Microsoft Copilot Studio and Azure AI Foundry](https://www.sharepointeurope.com/choosing-between-microsoft-copilot-studio-and-azure-ai-foundry-a-comprehensive-guide/)
- [Microsoft Copilot vs Copilot Studio vs Azure AI Foundry](https://dynatechconsultancy.com/blog/microsoft-copilot-vs-copilot-studio-vs-azure-ai-foundry)
- [n8n vs Zapier — DataCamp](https://www.datacamp.com/blog/n8n-vs-zapier)
- [Best n8n alternatives — Zapier, Make, Dify, Coze compared](https://www.browseract.com/blog/best-n8n-alternatives-zapier-make-dify-coze-compared)
