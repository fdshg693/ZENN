---
title: "Copilot Studioで何ができて何ができないのか — Azure AI Foundry / Agent Builderとの比較で整理する"
emoji: "🤖"
type: "tech"
topics: ["copilotstudio", "microsoft365", "azureaifoundry", "ai", "agent"]
published: false
---

## この記事の目的

AI / LLM / Agent の基本(RAG、tool calling、orchestration など)は理解している人向けに、**Microsoft Copilot Studio が「どこに住んでいる」ツールで、何が得意で何が苦手なのか**を、類似ツールとの比較で整理します。

ボタン操作やチュートリアルは扱いません。「自分のユースケースに Copilot Studio を採用すべきかどうか」を判断するための観点だけを残します。

なお、Microsoft 365 Copilot アプリ内の **Agent Builder** についても前提知識として扱い、詳細な解説はしません。

---

## 1. まず「Microsoft の Agent 構築ツールが多すぎる」問題を整理する

Microsoft エコシステムで「Agent を作る」経路は、現時点で主に 5 つあります。

1. **SharePoint agents**:1 つのドキュメントライブラリにスコープされる最も簡易な選択肢
2. **Agent Builder**(Microsoft 365 Copilot アプリ内):軽量な Agent を Copilot の中で直接作る。通称 "Copilot Studio Light"
3. **Copilot Studio**:Power Platform 上のフルローコード Agent 構築 SaaS。旧 Power Virtual Agents の後継
4. **Declarative Agents(Microsoft 365 Agents Toolkit 経由)**:M365 Copilot 拡張のプロコードパス
5. **Azure AI Foundry Agent Service**:Azure 上のコードファーストな Agent 基盤

これらは機能が重なって見えますが、**「誰が作り、誰が使い、どこまで自分で制御するか」で明確に住み分けされています**。本記事はこの中の **Copilot Studio** の座標を確定させるのが目的です。

---

## 2. Copilot Studio の正体(3 行で)

- **Power Platform 上の SaaS**。Power Virtual Agents (PVA) はそのまま Copilot Studio に吸収されており、PVA で作ったものは Copilot Studio で引き続き動く。
- **ローコード / グラフィカル UI による Agent と Agent flow の構築ツール**。内部データストアは Dataverse。
- **generative orchestration** に対応(instruction と tool description を元に LLM がツール選択・RAG を実行)。裏では Azure OpenAI を使用。

これ以上の「Agent とは何か」の説明は省きます(読者は前提知識ありのはずです)。

---

## 3. Copilot Studio の全体機能俯瞰

類似ツールと比較する前に、まず **Copilot Studio 単体で何ができるのか** を機能カテゴリ別に一望しておきます。個別のボタン操作は省き、「何が提供されているか」に絞ります。

### 3.1 Agent のオーサリング方式

- **自然言語で作る**:「こういう Agent を作って」と日本語で説明すれば初期テンプレートが生成される(Copilot 支援のオーサリング)
- **グラフィカルな dialog designer**:トピック単位で対話フローを GUI で組む。メッセージ / 質問 / 条件分岐 / 変数 / Adaptive Cards が標準ノードとして揃う
- **Agent instructions**:システムプロンプト相当の自由記述(最大 8,000 文字)
- **Trigger phrases と topics**:「こう聞かれたらこのフローへ」のルーティングを人が書く(1,000 topics / agent、200 phrases / topic)
- **Agent flow**:対話なしでバックグラウンド実行する Agent(スケジュール実行 / イベント起動のワークフロー)

### 3.2 オーケストレーションモード(Copilot Studio 独自の二面性)

この違いが Copilot Studio の設計で最も重要です。

| モード | 動き方 | 使う場面 |
|---|---|---|
| **Classic orchestration** | トピックと対話フローを人が設計。trigger phrase にマッチしたトピックが起動 | 応答を厳密に統制したい、旧 PVA から移行した資産 |
| **Generative orchestration** | LLM が instruction / tool description / knowledge description を読み、自律的にツールを選ぶ | 想定外の質問にも柔軟に対応させたい、Agentic な挙動が欲しい |

**同じ Copilot Studio でも、モードによって使える機能と制約が大きく変わります**。例えば「公開 Web の knowledge を 25 サイト登録する」「Web Search をオンにする」のは generative モード限定、「カスタムデータを直接 knowledge に置く」のは classic モード限定、といった具合です。

### 3.3 Knowledge sources(グラウンディング情報源)

Agent に「何を根拠に答えるか」を与える口。以下を組み合わせて使えます。

- **SharePoint URL**(generative: 25 URL まで、classic: 4 URL まで)
- **Dataverse テーブル**(2 ソース × 各 15 テーブルまで)
- **アップロードファイル**(PDF / Word / PowerPoint など、1 ファイル 512 MB まで、合計 500 ファイル。アップロード済みの数は 25 ソース制限にカウントされない)
- **公開 Web サイト**(generative: 25 サイト、内部的には Bing 経由)
- **Web Search**(generative 時に有効化。Bing で広くリアルタイム検索)
- **Azure OpenAI Service 接続**(最大 5 個。"On your data" の資産を接続可能)
- **Bing Custom Search Custom Configuration ID**(最大 2)
- **カスタムデータソース**(最大 3、classic モードのみ)

知識ソースは **Dataverse の中に独立したサイロとして保持されます**(M365 semantic index とは別経路)。この性質は後述の比較で効いてきます。

### 3.4 Actions / Tools(Agent の「手」)

Agent が知識参照だけでなく「実行」もできるようにする仕組み。**ここが Copilot Studio 最大の差別化ポイント**です。

- **Power Platform コネクタ(1,000+)**:Microsoft 365、Dynamics 365、Salesforce、ServiceNow、SAP、Jira、Zendesk、GitHub、Slack、Box、Google Workspace などが既製で揃う
- **プレミアムコネクタ / カスタムコネクタ**:REST API を独自にラップした connector を持ち込み可能
- **Power Automate フロー**:既存の業務フローをそのまま tool として呼べる
- **HTTP request**:連携用の REST エンドポイントを直接叩く
- **AI Tools**:プロンプトそのものやモデル呼び出しを再利用可能な tool として定義
- **Bot Framework Skills**(最大 100 / agent):Azure Bot Framework で作った Skill を組み込める
- **Agent-to-agent**:別の Copilot Studio agent を下位 agent として呼ぶ multi-agent 構成

**既に Power Platform / Power Automate に業務連携資産があるなら、コードを書かずそのまま Agent の手足になる**のが強みです。

### 3.5 Channels(公開先チャネル)

作成した Agent を以下にほぼ同じ定義のまま publish できます。

- **Microsoft 365 Copilot**(M365 Copilot アプリ内に Agent として登場)
- **Microsoft Teams**
- **Web チャット**(JavaScript スニペットで自社サイトに埋め込み)
- **カスタムサイト(匿名 / 認証あり)**
- **Slack / Facebook Messenger**
- **Azure Bot Service 経由の任意チャネル**(独自アプリ、LINE、電話系など)
- **Telephony**(一部プランで音声通話対応)

マルチチャネル対応は **設定ベース**なので、1 つの Agent を Teams と Web に同時に出すような構成が自然にできます。

### 3.6 Governance / Security / ALM(運用面)

エンタープライズ採用時に効く、「抽象化されているが手抜きはしていない」レイヤー。

- **Entra ID(旧 Azure AD)による SSO**:Agent 利用者の認証と、SharePoint 等の knowledge への permission 透過
- **Data Loss Prevention (DLP)**:Power Platform のデータポリシーで、使えるコネクタ / 送信先を admin が絞れる
- **Purview 統合**:監査ログ、DLP、機密ラベル連携
- **Power Platform 管理センター**:Agent 単位の利用状況、失敗トレース、発行先の管理
- **Environment 分離 + Solution による ALM**:開発 / テスト / 本番環境を分け、Solution でパッケージングして移送
- **Tenant 単位のガバナンスポリシー**:「このテナントでは generative AI 機能を止める」「US 外にデータを出さない」などを admin が強制可能
- **Agent runtime protection status**:プロンプトインジェクション等の攻撃に対する保護状態を Agent ごとに可視化

### 3.7 アナリティクスと観測性

- Power Platform 管理センターでの **会話ログ / 失敗分析 / ROI 分析**
- **Viva Insights** 連携(Agent 利用の生産性インパクト)
- Application Insights と連携したテレメトリ出力

### 3.8 Microsoft 365 / Power Platform 連携

- **Dataverse** を backing store として利用(Agent の状態、構造化データ、ナレッジの一部もここに入る)
- **Microsoft 365 Copilot 連携**:Agent を M365 Copilot に publish すれば、Microsoft 365 Copilot ライセンス保有者は追加課金なしで利用可能
- **Agent Builder との相互運用**:Agent Builder(Copilot Studio Light)で作った Agent を Copilot Studio にコピーしてアップグレード

---

### ここまでを一言で

Copilot Studio は **「LLM に M365 / Power Platform の全業務連携と既存のガバナンスをまとめて渡す」** ためのツールだと捉えると理解が早いです。モデルやインフラの自由度は薄い代わりに、**既にエンタープライズが持っている資産(connector、SSO、DLP、Dataverse、SharePoint の権限)をそのまま Agent の文脈に載せる** 部分に全振りしています。

---

## 4. 類似ツールとの住み分け(本記事の本丸)

横軸は「誰が作り、誰に届け、どれくらい自分で握るか」です。

| ツール | 立ち位置 | 主な対象者 | 自由度 | 公開先 |
|---|---|---|---|---|
| **Agent Builder**(M365 Copilot 内) | Copilot アプリに組み込まれた超軽量 Agent ビルダー | 情報ワーカー個人 / 小チーム | 低 | M365 Copilot 内のみ |
| **Copilot Studio** | Power Platform 上のローコード Agent 構築 SaaS | 業務担当者〜開発者 | 中(抽象化されている) | M365 Copilot / Teams / Web / 他 |
| **Declarative Agents**(ATK) | JSON / YAML で書く M365 Copilot 拡張。**Sydney オーケストレータ**上で動く | 開発者 | 中〜高 | M365 Copilot |
| **Azure AI Foundry Agent Service** | Azure 上のコードファースト Agent 基盤 | 開発者中心 | 最高(モデル / prompt / tool / ネットワーク / 監視まで全部自前) | 任意 |

比較で特に効くポイントを 3 つだけ。

### 4.1 Copilot Studio vs Agent Builder
対象オーディエンスの広さが違います。**Agent Builder は「自分と小チームのための Q&A Agent」向け**、**Copilot Studio は「部門・全社・社外にも届く Agent」向け**。マルチステップワークフローや LoB システム連携が必要なら Copilot Studio 側になります。**Agent Builder で作った Agent は Copilot Studio にコピーしてアップグレードできる**ので、軽く試してから育てる経路は確保されています。

### 4.2 Copilot Studio vs Declarative Agents
見落とされがちですが、**知識の置き場所のアーキテクチャが根本的に違います**。

- Copilot Studio の知識は **Dataverse の独立サイロ**。その Agent からしか参照されない。
- Declarative Agents の知識は **Microsoft 365 の semantic index**(M365 Copilot が使うのと同じ)に載る。

つまり「M365 Copilot 全体と同じ世界観で知識を共有したい」なら Declarative Agents が筋が良いです。また、M365 Copilot 側の新機能は **Sydney オーケストレータに先着**し、Copilot Studio(Samba オーケストレータ)には数ヶ月遅れで来る傾向があります。

### 4.3 Copilot Studio vs Azure AI Foundry Agent Service
**「速くて抽象化されている」** vs **「遅いが全部自分で握れる」** のトレードオフ。Foundry は Model catalog、prompt orchestration graph、評価ダッシュボード、SDK / CLI、VNET / Private Endpoint、LLMOps までフルで開けます。Copilot Studio はこれらを意図的に隠しています。

現場でよく見る構成は **ハイブリッド**:Copilot Studio がフロント(Teams / M365 の UI、ガバナンス、connectors)、Foundry がバックエンド(複雑な reasoning、評価、機密データ制御)。

---

## 5. Copilot Studio だからこそ解決できる具体シナリオ

抽象論だけだと判断しづらいので、**Copilot Studio を選ぶと明確にコスパが合う**代表シナリオを 4 つ挙げます。共通点は「**M365 / Power Platform エコシステムに既に業務プロセスと認可が乗っている**」ことです。

### シナリオ A:社内 IT ヘルプデスクの一次対応

**課題**
- SharePoint のナレッジ記事、Intune / Entra の状態、既存の社内 IT チケットシステムがバラバラで、情報ワーカーが都度 Teams で人力ヘルプデスクに聞いてくる。
- 人力ヘルプデスクは同じ質問の繰り返しで疲弊、SLA も守れない。

**なぜ Copilot Studio が効くか**
- SharePoint のナレッジサイトをそのまま knowledge source に指定 → Entra SSO の権限が効くので「見えるべき人にだけ見える」状態を自前で作り込まずに済む。
- チケットシステムが Power Platform コネクタにあれば、**「答える」だけでなく「代わりにチケットを切る / ステータスを見る」Action** をそのまま繋げる。
- Teams に公開すれば、ユーザは新しい UI を覚えなくてよい。
- 失敗時は人力エスカレーション(Agent から Teams のチームへルーティング)も conventional なフローで実装可能。

**他ツールだとどうなるか**
- Azure AI Foundry なら同じことはできるが、SSO・DLP・監査ログ・Teams チャネル公開を全部組み立てる必要がある。「とりあえず 1 ヶ月で PoC」には重い。
- Agent Builder だと、複数ステップのチケット作成 Action や LoB 連携の部分で壁にぶつかる。

### シナリオ B:営業部門の提案書ドラフト生成

**課題**
- 営業担当が過去の提案書・価格表・事例集を SharePoint から探すのに時間を取られる。
- ドラフトを作っても Dynamics 365 / CRM 側のお客様情報と手で合わせる必要がある。

**なぜ Copilot Studio が効くか**
- SharePoint の提案書アーカイブを knowledge source として登録し、generative orchestration に任せれば、質問に応じて関連文書を引きながら回答できる。
- Dynamics 365 コネクタで顧客データを Action として読み込み、**「この顧客向けのドラフトを」** のような指示を Agent に解釈させられる。
- 営業担当は Teams / M365 Copilot から使えるので、ツールの切り替えコストが小さい。

**他ツールだとどうなるか**
- Declarative Agents でも CRM 連携はできるが、**カスタム connector の開発とデプロイが開発者の仕事**になる。Copilot Studio なら Power Platform 側の既存 connector 資産を流用できる。

### シナリオ C:HR / 総務ポリシー Q&A の全社展開

**課題**
- 就業規則・経費規程・福利厚生の FAQ が年々増え、HR 部門の問い合わせ対応工数が増加。
- 機密情報なので、**誰が何を見られるか**の制御を厳密にしたい。

**なぜ Copilot Studio が効くか**
- SharePoint サイトの閲覧権限がそのまま Agent 側の可視性境界になる(Entra ID 認証経由)。
- **Purview の DLP、Power Platform 管理センターのデータポリシー**で、「この Agent からは機密ラベル付き文書を引かない」「このコネクタは使わせない」を admin 側で強制できる。
- 監査ログが Purview に統合されているので、「誰が何を聞いたか」を HR / コンプラが後から追える。

**他ツールだとどうなるか**
- Foundry で同等のガバナンスを敷こうとすると、識別基盤 / ポリシーエンジン / 監査パイプラインを自分で組む必要があり、HR 部門主導のプロジェクトでは重すぎる。

### シナリオ D:現場スタッフ向けの業務ワークフロー自動化

**課題**
- 店舗スタッフや現場作業員が、「シフト交代申請」「備品発注」「インシデント報告」など、社内フォームを毎回探して埋める必要がある。
- フォームの場所を覚えきれず、結果的に電話やメールで事務方に流れ込む。

**なぜ Copilot Studio が効くか**
- Power Automate の既存フローを Action として繋げば、**自然言語 1 行で申請プロセスがキックされる**。
- スマホの Teams から使えるので、現場スタッフに新しいアプリを配らなくて済む。
- ビジネス側(情報システム部門ではない担当)が Agent を育てていけるので、IT 部門のボトルネックになりにくい。

**他ツールだとどうなるか**
- LangChain / Foundry で作ると、**個々のフォーム呼び出しを全部 API として実装する**ことになる。社内フォームが既に Power Apps / Power Automate で組まれている環境だと、二重投資。

---

### 逆に、以下のシナリオは Copilot Studio に向きません

- **モデルそのものを評価・fine-tune したい**(例:ドメイン特化の SLM を載せる)→ Azure AI Foundry
- **最新の M365 Copilot 機能(Researcher、Analyst 相当)と同じオーケストレーションを使いたい**→ Declarative Agents
- **VNET / Private Endpoint で完全に閉域化したい**→ Azure AI Foundry
- **個人の生産性を Copilot の UI の中だけで底上げしたい**→ Agent Builder か Declarative Agents

---

## 6. Copilot Studio で「できないこと / 注意が必要なこと」

選定時に効く制約を、カテゴリごとに整理します。数値は公式 Docs の [Quotas and limits](https://learn.microsoft.com/en-us/microsoft-copilot-studio/requirements-quotas) 準拠(変動しうるので本番採用前に必ず最新を確認してください)。

### 6.1 仕様上のハードリミット
- Agent instruction は **8,000 文字まで**
- **100 skills / agent、1,000 topics / agent、200 trigger phrases / topic**
- Connector payload は **5 MB**、ファイル 1 つ 512 MB、合計 500 ファイル
- Azure OpenAI 接続は **最大 5**、カスタムデータソースは **最大 3**

instruction 8,000 文字の上限は、プロンプトエンジニアリングを長大にしている人にとって現実的な制約になります。

### 6.2 Generative orchestration 特有の制約
- 知識ソースが **25 を超えると、内部の GPT が description ベースでフィルタする** → **description の書き方が性能に直結**
- **カスタムデータや Bing Custom Search は generative orchestration の直接ソースにできない**(トピック内の generative answers node に embed する必要あり)
- Classic モードだと公開 URL / SharePoint URL **各 4 個まで**と極端に少ないため、広く使うなら generative 一択
- **公開 Web は generative モードでも 25 サイト、SharePoint も 25 URL まで**

「ナレッジを何十サイトも指定したら勝手にやってくれる」と期待すると裏切られます。

### 6.3 知識取り込みの落とし穴
- **Confidential / Highly Confidential ラベル付き文書**、パスワード保護 PDF は **インデックスされない**。UI 上は「Ready」と表示されても応答しない挙動。
- **SharePoint のドキュメントライブラリ単位の取り込みは非対応**。個別ファイル / フォルダ単位のみ。
- XLSX 等の構造化ファイルを置いても **Agent はコード実行しない**ので、分析系の質問は苦手。データ分析をやりたいなら別途 Foundry か Python 側に寄せる。
- **引用(citation)は他の tool / action の input として再利用できない**。「一次回答の出典をそのまま次ステップに渡す」パイプラインは組めない。

### 6.4 アーキテクチャ上の暗黙的な縛り
- 知識は **Dataverse 内の独立サイロ**。M365 の semantic index には乗らない(テナント graph grounding を明示的に有効化しない限り)。横断検索や M365 Copilot 全体での再利用には不向き。
- モデル・prompt・インフラの細かな調整は **基本的に不可能**。抽象化されている代わりに自由度を手放している。
- **新機能は Declarative Agents(Sydney オーケストレータ)側に先に入ることが多い**。Copilot Studio(Samba オーケストレータ)は数ヶ月遅れになる構造。最先端の機能を追いたいチームにはフィットしない。

### 6.5 運用・セキュリティで見落としがちな点
- 設定によっては **無認証で Agent を公開できてしまう**。過去に、研究者がインターネット上の無認証 Copilot Studio Agent をスキャンし、Salesforce の連絡先情報を対話経由でダンプするデモが公開されています。→ **Power Platform 管理センター側のガバナンスポリシーで publish 先を縛るのは必須**。
- Microsoft 公式に **医療機器用途 / 緊急通報用途は対象外** と明記されています。

---

## 7. ライセンスとコストの考え方

数式の詳細は Microsoft のページに譲りますが、構造だけ押さえます。

- **Copilot Credits** 方式:テナントワイドの 25,000 credits パック単位で購入、アクション / 応答ごとに消費。
- **Pay-as-you-go** 方式:Azure サブスクリプションに紐付けて使った分だけ課金。
- **M365 Copilot ライセンス保有者が M365 Copilot に publish された Agent を使う場合、追加課金は発生しない**(重要)。

Azure AI Foundry は **Azure 側の従量課金**(モデル利用 + インフラ)で完全に別体系。高トラフィック / 高トークンのケースで比較する場合、**Copilot Credits 単位の消費モデルと Azure のトークン単位のコストは、そもそも次元が違う**ことを念頭に置く必要があります。

---

## 8. 選定ガイド:いつ Copilot Studio を選び、いつ外すか

### Copilot Studio が刺さるケース
- **M365 / Teams / SharePoint / Dynamics などエコシステム内で完結する Agent** を速く出したい
- **ビジネス担当や市民開発者にも保守を任せたい**
- 既存の **Power Platform コネクタ資産** を活かしたい
- **エンタープライズガバナンス(DLP / Purview / 監査)を手早く担保したい**

### Copilot Studio から外すべきケース
- **モデル選択・fine-tune・評価・監視・閉域化を自分で握る必要がある** → Azure AI Foundry
- **個人 / 小チーム向けの軽量 Q&A で十分** → Agent Builder
- **M365 Copilot の semantic index / Graph と深く統合したい、最新機能を早く取りたい** → Declarative Agents(ATK)
- **強い規制環境で、誰が何をどこに publish できるかを開発者側で厳密にコードで制御したい** → Declarative Agents(ATK)寄り

---

## 9. まとめ

- Copilot Studio は万能の Agent プラットフォームではなく、**「Power Platform 上で M365 エコシステムと密結合した Agent を、ガバナンスを効かせつつ速く作る」ための専用レーン**。
- モデル制御・最先端機能・完全な閉域化・M365 semantic index 統合 は **構造的に他のツールに譲っている**。これは欠点ではなく設計思想。
- 選定は、**「モデル制御がどれだけ必要か」「誰が作り誰に届けるか」「M365 の中だけで閉じるか」** の 3 軸で判断すると最短で答えが出る。

「Copilot Studio で PoC を速く出して、プロダクション要件が硬くなったらバックエンドを Foundry に移す」というハイブリッド構成は、実務上も理にかなった選択肢です。

---

## 参考資料(公式中心)

- [Copilot Studio overview — Microsoft Learn](https://learn.microsoft.com/en-us/microsoft-copilot-studio/fundamentals-what-is-copilot-studio)
- [Quotas and limits for Copilot Studio — Microsoft Learn](https://learn.microsoft.com/en-us/microsoft-copilot-studio/requirements-quotas)
- [Knowledge sources summary — Microsoft Copilot Studio](https://learn.microsoft.com/en-us/microsoft-copilot-studio/knowledge-copilot-studio)
- [Security and governance — Microsoft Copilot Studio](https://learn.microsoft.com/en-us/microsoft-copilot-studio/security-and-governance)
- [Choose between Agent Builder in Microsoft 365 Copilot and Copilot Studio — Microsoft Learn](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/copilot-studio-experience)
- [Declarative agents for Microsoft 365 Copilot — Microsoft Learn](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/overview-declarative-agent)
- [Navigating AI Solutions: Microsoft Copilot Studio vs. Azure AI Foundry — Microsoft Community Hub](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/navigating-ai-solutions-microsoft-copilot-studio-vs-azure-ai-foundry/4411678)
- [Microsoft Copilot Studio vs. Microsoft Foundry: Building AI Agents and Apps — Microsoft Community Hub](https://techcommunity.microsoft.com/blog/microsoft-security-blog/microsoft-copilot-studio-vs-microsoft-foundry-building-ai-agents-and-apps/4483160)
- [Microsoft 365 Copilot Pricing — Copilot Studio](https://www.microsoft.com/en-us/microsoft-365-copilot/pricing/copilot-studio)
