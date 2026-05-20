---
title: "AIチャットアプリで学ぶAzureコスト設計 — App Service / Cosmos DB / Azure OpenAI / 外部AI / 監視系の勘所"
emoji: "💸"
type: "tech"
topics: ["azure", "appservice", "cosmosdb", "azureopenai", "applicationinsights"]
published: false
---

## この記事について

「PoCで動かしたAIチャットアプリを本番に載せたら、**月額がPoCの10倍**になって上長への説明に困った」。そういう経験、もしくはそれを予防したくて料金表を見始めた段階、どちらの立場でもこの記事の対象です。

Azureの料金ページは網羅的ですが、**「自分のワークロードに対してどう設計判断するか」は料金表だけ見ても分からない**。そして、AIチャットアプリは特にこれが難しい。なぜなら、同じアプリの中に

- **固定費的に課金されるサービス**(App Service Plan)
- **使用量(トークン)で課金されるサービス**(Azure OpenAI、外部AI)
- **スキーマ設計次第で課金が変わるサービス**(Cosmos DB のRU)
- **データ量で課金されるサービス**(Application Insights / Log Analytics)
- **通信の方向と経路で課金されるサービス**(egress / Private Link)

が同時に走るからです。ツマミの種類が違うと、思考モデルも別々に持たないと最適化できません。

この記事では、以下の構成で**企業の本番AIチャットアプリをAzure上で運用する**エンジニア向けに、コストの「形」と「効くツマミ」を整理します。

- 対象アーキテクチャ: Azure App Service(Web App) + Azure Cosmos DB + Azure OpenAI + 外部AI API(例: Anthropic Claude / OpenAI.com / Gemini など) + Application Insights / Log Analytics
- 前提: 各サービスの基本(App Service Plan、RU、AOAIのデプロイ、App Insightsの存在)は理解している
- 扱わないこと: 具体的な単価の転記(変動するので必ず公式で確認してください)、FinOps組織論、Cost Management UIの操作手順

:::message
単価・レートは変動します。本記事が引用する**構造・境界値・比較式**は公式ドキュメントの引用ですが、実際の金額判断は必ず[Azure料金計算ツール](https://azure.microsoft.com/ja-jp/pricing/calculator/)と各サービスの公式料金ページで検算してください。
:::

## 0. 全体像: AIチャットアプリのコストは5層構造

まず、対象アーキテクチャを置き直しておきます。

```
[ユーザー]
   │
   ▼
[App Service] ─────── [Cosmos DB]          ← 会話メタ/履歴
   │   │
   │   ├─────────── [Azure OpenAI]          ← 社内AI
   │   └─────────── [外部AI API]            ← Claude / OpenAI.com 等
   │
   └─────────── [Application Insights / Log Analytics]
```

このアプリで発生するコストは、5つの層に分解できます。

| 層 | 代表サービス | 課金の形 | 主な制御軸 |
|---|---|---|---|
| 1. 固定確保 | App Service Plan | インスタンス時間 | SKU / autoscale |
| 2. 使用量 | Azure OpenAI / 外部AI | トークン | 入出力トークン数 / デプロイタイプ |
| 3. スキーマ依存 | Cosmos DB | RU + GB | スキーマ / インデックス / スループット型 |
| 4. データ量 | Log Analytics / App Insights | GB(ingestion) | サンプリング / ログプラン |
| 5. 経路 | egress / Private Link | GB / 時間 | リージョン選定 / ルーティング |

AIチャットアプリが「コストを読みにくい」と感じる理由は、**これら5層の支配要因がすべて違う**ところにあります。1層ずつ、実務のツマミと AIチャット文脈での判断に分けて見ていきます。

## 1. App Service: 「プラン単位課金」という常時確保コスト

### コストの形

App ServiceはApp Service Planの**インスタンス時間**で課金されます。秒単位でプロレートされますが、大枠は「`SKUの時間単価 × インスタンス数 × 稼働時間`」です[^appservice-wafr]。

[^appservice-wafr]: [Architecture Best Practices for Azure App Service — Well-Architected Framework](https://learn.microsoft.com/en-us/azure/well-architected/service-guides/app-service-web-apps)

ここで踏み外しやすいのが、**同一App Service Planに乗るすべてのアプリとすべてのデプロイスロットが同じVMを共有する**という設計です[^appservice-hosting]。「スロットを増やしても無料」ではなく、**スロットで動くプロセスが本番アプリと同じRAM・CPUを食い合う**というのが正確です。

[^appservice-hosting]: [Azure App Service Plans — Overview](https://learn.microsoft.com/en-us/azure/app-service/overview-hosting-plans)

:::message
PoC時代に「全プロジェクト共通でStandard 1枚」にしていたものを、本番で同じ流れで組むと、検証用アプリのWebJobsが本番の応答遅延を引き起こす、ということが普通に起きます。
:::

### 実務のツマミ

#### スケール方式: 2つあって選べない

App Serviceのスケールには2つのモードがあり、**1プランで併用できません**[^appservice-autoscale]。

- **Automatic scaling**: HTTPトラフィック駆動。アプリ単位に `always ready` と `prewarmed` と `maximum burst` を設定する
- **Autoscale**: メトリック(CPU/メモリ/キュー長/カスタム) やスケジュールで動く。**プラン全体**に適用

[^appservice-autoscale]: [How to Enable Automatic Scaling — Azure App Service](https://learn.microsoft.com/en-us/azure/app-service/manage-automatic-scaling)

Automatic scalingの課金の肝は、**idle状態でalways-readyだけが動いている間、prewarmedは課金されない**ことです。トラフィックが来てalways-readyがactiveになると即座にprewarmedが確保され、課金が始まります。スケールアウト時も常に次のprewarmedバッファを1台余分に確保しにいきます[^appservice-autoscale]。

さらに、**プランの `assigned instance count` は含まれる全アプリの `always ready` 値から計算されます**。例えばプラン内のアプリA=2、B=3、C=5なら、**プランには最低7台分が常時課金**されます。1アプリの設定を変えるとプラン全体の月額が動くということです。

#### SKU選定とリージョン依存

Premium V3には `P0V3`〜`P5mV3` まで複数SKUがありますが、**リージョンとデプロイユニットによっては一部SKUがそもそも選べません**[^appservice-pv3]。既存プランがPremium V3をサポートしていないデプロイユニットに載っていた場合、「SKUを上げる」ではなく「新リソースグループ＋新プランに再デプロイ」が必要になります。

[^appservice-pv3]: [Configure Premium V3 Tier — Azure App Service](https://learn.microsoft.com/en-us/azure/app-service/app-service-configure-premium-v3-tier)

これは**AOAIと同一リージョンに寄せた結果、App Service側のSKU選択肢が狭まる**、という形で地味に効いてきます。

### AIチャット文脈での判断

AIチャットアプリの負荷プロファイルには特徴があります。

- **リクエストあたりの処理時間が長い**(AOAI/外部AIの応答待ち)
- **CPU使用率は低いのにスレッド/接続が詰まる**
- 勤務時間帯に集中、深夜はほぼアイドル

これを素直にCPUメトリックのautoscaleに乗せると、「**CPUが低いままスケールアウトが起きない → 実際は応答待ちで詰まっている**」か、逆に「待ち時間がCPUに現れないためスケールインが早すぎて応答劣化」になります。

判断の方向性:

- メトリックは**同時接続数 / 応答時間 / カスタムメトリック(AOAI呼び出し中の件数)** を軸に組む
- **夜間のスケールインを積極的に**: アイドル時間が長いワークロードはautoscale向き。min/maxを明示して未使用VMを残さない[^appservice-wafr]
- **staging slotは最小構成に**: 同じVMで動くので、ステージ側のバックグラウンド処理やAlways OnがRAMを食う

## 2. Cosmos DB: RUとスキーマ設計の二本柱

### コストの形

Cosmos DBのコストは2軸です[^cosmos-plan]。

- **スループット(RU/s)**: Provisioned manual は予約したRU/sが時間単位で常時課金、Autoscaleはその時間中に到達した最大RU/s、Serverlessは消費したRU分
- **ストレージ(GB)**: データ本体＋インデックス

これに**バックアップ / 分析ストア / Availability Zones / マルチリージョン書き込み**が追加で乗ります。

[^cosmos-plan]: [Plan and Manage Costs — Azure Cosmos DB](https://learn.microsoft.com/en-us/azure/cosmos-db/plan-manage-costs)

### 実務のツマミ(スループット型の選び方)

Provisioned / Autoscale / Serverless の選択は、**ピーク時間率**が決定打になります。公式がはっきり境界値を出しています。

- **Autoscaleが得するライン**: ピークRU/sを**月全体の66%以下の時間しか使わない**ワークロード[^cosmos-autoscale]
- **Serverlessが得する例**: 常時500 RU/s必要なら Provisioned($29.20/月の試算例)、月250M RUのバーストでも Provisioned、月20M RU程度のスパイク利用なら Serverless($5.00の試算例) という比較が公式にあります[^cosmos-serverless]

[^cosmos-autoscale]: [Create Containers and Databases with Autoscale Throughput](https://learn.microsoft.com/en-us/azure/cosmos-db/provision-throughput-autoscale)
[^cosmos-serverless]: [Compare Provisioned Throughput and Serverless — Azure Cosmos DB](https://learn.microsoft.com/en-us/azure/cosmos-db/throughput-serverless)

**Serverlessの本番適用には大きな制約があります**。単一リージョンのみ、SLAではなくSLO(point-read < 10ms、write < 30ms)。**企業本番のチャットアプリでマルチリージョンや強いSLAが要件なら、Serverlessは外れる**と考えたほうが安全です[^cosmos-serverless]。

AIチャットの本番トラフィックは「平日9〜19時にピーク、夜間激減」という形になりやすく、ピーク時間率が66%以下に収まることが多い。**最初の本番は Autoscale が第一候補**になります。

### 実務のツマミ(スキーマ側でRUを食わせない)

スループット型を選ぶより先に、**RUを食わせる要素を理解する**ほうが重要です。RUは1回のオペレーションごとに算定され、読み込みと書き込みで別々に効いてきます。

公式が列挙しているRU消費ドライバ[^cosmos-ru]:

- **アイテムサイズ**: 大きいほど読み書きともRU増
- **アイテムのプロパティ数**: プロパティが多いほど書き込みRU増
- **インデックス対象のプロパティ数**: Cosmos DBは**デフォルトで全プロパティを自動インデックス**。書き込みのたびに全プロパティのインデックス更新が走る
- **クエリ複雑性**: 述語数、UDF、対象データセットサイズが読み込みRU増[^cosmos-optimize]

[^cosmos-ru]: [Request Units in Azure Cosmos DB](https://learn.microsoft.com/en-us/azure/cosmos-db/request-units)
[^cosmos-optimize]: [Optimize Request Cost — Azure Cosmos DB](https://learn.microsoft.com/en-us/azure/cosmos-db/optimize-cost-reads-writes)

### AIチャット文脈での判断

AIチャットのデータをそのままCosmos DBに詰め込むと、ほぼ確実にアンチパターンに踏みます。

**アンチパターン**: user message、assistant response、embedding、system prompt snapshot をすべて1ドキュメントに保存する

- メッセージ本体は**長文かつ書き込み偏重**(会話のたびに追記される) → 書き込みRUを食い続ける
- embeddingは**1次元あたりfloat**で数キロバイト規模 → さらにサイズを押し上げる
- 検索しない長文・embedding までデフォルトでインデックスされる → 書き込みRUを二重に食う

公式ドキュメントも「**検索対象でない大きなデータはCosmos DBに置くべきではなく、Blob Storageに本体を置いて参照だけ持つ**」というベストプラクティスを明示しています[^cosmos-optimize]。

判断の方向性:

- **本文はBlob Storage、Cosmos DBにはsession / turnの構造化メタと本文blob URLだけ**
- 全文検索が要らないなら**インデックスポリシーで長文messageやembeddingを除外** → 書き込みRU削減
- ピーク時間率が低い(夜間アイドル)企業本番は**Autoscale 一択に近い**
- 予期せぬ暴走を防ぐため、**アカウント全体のプロビジョンスループット上限**を設定する[^cosmos-plan]

## 3. Azure OpenAI: デプロイタイプが価格の「型」を決める

### コストの形

AOAIはトークン単位課金、というのは入口の話です。実務で先に決めるべきは**デプロイタイプ**で、これが価格の形を決めます[^aoai-types]。

[^aoai-types]: [Understanding deployment types in Microsoft Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/deployment-types)

| デプロイタイプ | 課金モデル | 特徴 |
|---|---|---|
| Standard / Global Standard / Data Zone Standard | pay-per-token | 使った分だけ、可変トラフィック向け |
| Provisioned Managed(PTU): Regional / Global / Data Zone | 容量予約(PTU-hour) | 一貫した低レイテンシ、高ボリューム向け |
| Batch(Global / Data Zone) | pay-per-token × **50%割引** | 24時間以内ターンアラウンドの大量処理向け |
| Developer | ホスティング料 $0 (プリエンプティブル) | 検証・開発向け、SLAなし |

**Batchの50%割引**は公式に明記されています[^aoai-types]。同期応答が要らない業務(ナレッジのバルク要約、夜間再処理)を切り出せるなら効きます。

### 実務のツマミ(PTUはどこから検討するか)

Provisioned Managed(PTU)は、**トラフィックが一貫していて高ボリュームで、かつレイテンシを保証したい**場合に向きます。逆に言うと、「バースト気味」「量が読めない」段階で入ると無駄な容量を抱えます。

構造上知っておくべき点:

- **PTUは model-independent quota**: 1つのPTUプールを複数モデルで共有できる(クォータ種別は Regional / Global / Data Zone 別)[^aoai-ptu]
- **クォータ ≠ 容量保証**: Foundryで先にデプロイして、その後Azureポータルで対応するreservationを購入する順序[^aoai-ptu]
- **最小デプロイ単位が重い**(gpt-4o の場合): Global & Data Zone Provisioned は最小 **15 PTU / 5 PTU増分**、Regional Provisioned は最小 **50 PTU / 50 PTU増分**[^aoai-ptu]
- **1 PTUあたりのInput TPM** はモデルごとに違う(例: gpt-4o = 2,500 input TPM/PTU、gpt-4o-mini = 37,000、o3-mini = 2,500、o1 = 230)[^aoai-ptu]

[^aoai-ptu]: [Provisioned throughput unit (PTU) costs and billing — Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/provisioned-throughput-onboarding)

この最小単位は、個人開発や小規模PoCには大きすぎます。**「PTU移行は数字で見えてから」**が現実解で、最初はStandard / Global Standardでpay-per-tokenで動かし、消費トークンの時系列が取れてからPTUに切り替えるかを判断します。

### 実務のツマミ(入出力トークンの非対称性)

トークン単価は**入力と出力で違い、出力のほうが高い**のが大半のモデルで共通です。PTU換算でも同様の非対称があり、たとえば Llama-3.3-70B-Instruct では**出力1トークンが入力4トークン相当**としてPTU利用量にカウントされます[^aoai-ptu]。

AIチャットアプリでは、会話履歴をすべて毎回プロンプトに入れる実装をすると「**入力トークンが会話長に比例して増える**」ので、入力側も無視できません。

- **システムプロンプトの共通化 / 圧縮**: 毎ターン同じ指示なら Prompt Caching で入力を削減
- **会話履歴の要約**: N ターンごとにサマリ化して履歴を再構成
- **ツール結果の選択的渡し**: RAGの全チャンクをそのまま渡すのでなく上位のみ

### 実務のツマミ(ファインチューニング)

ファインチューニング済みモデルをデプロイすると、**ホスティング料(時間課金)が pay-per-token とは別に発生**します[^aoai-ft]。

[^aoai-ft]: [Fine-tuning cost management — Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/fine-tuning-cost-management)

| デプロイ先 | ホスティング料 | SLA | 備考 |
|---|---|---|---|
| Standard | $1.70/hour | あり(Best effort) | pay-per-token別途 |
| Global Standard | あり(ホスト料) | あり(Best effort) | データ残留保証なし、Standardより高スループット |
| Regional Provisioned Throughput | PTU-hour課金 | あり(レイテンシ保証) | 予約レート |
| Developer | **$0/hour** | なし | プリエンプティブル(止められる) |

学習ジョブそのもののコストも: Global Standard trainingはRegional Standard trainingから **10〜30%割引**、Developer trainingはさらに **50%割引**(ただしプリエンプティブル、停止中は非課金、データ残留保証なし)[^aoai-ft]。

:::message alert
Developerはホスティング料がゼロで魅力的ですが、**SLAなし・プリエンプティブル**です。企業本番のユーザー向けAIチャットに直結させる先として選ぶ対象ではなく、評価・A/B テスト用途に限定するのが安全です。
:::

### AIチャット文脈での判断

- **最初はStandard / Global Standard**。pay-per-tokenで動かし、月次で**1会話あたり平均トークン数**を記録する
- **Batch対応できる業務を切り出す**(バッチ要約、ナレッジ再インデックス等)。50%割引が効く
- PTU移行は**「ピーク時間率が高く」「月間の消費PTUが最小デプロイ単位を十分に超える」**のが両方満たせてから
- データ残留要件(EUのみ等)があるなら **Data Zone Standard / Data Zone Provisioned** を検討

## 4. 外部AI API: 「Azureから外に出す」というegressコスト問題

企業で「Azure OpenAIだけでなく、Anthropic Claude / OpenAI.com / Gemini なども組み合わせて使う」ケースは珍しくありません。ここで見落としやすいのが、**外部AI APIの料金とは別に、Azure側でegress(下り) 課金が発生する**という点です。

### コストの形

Azureのbandwidth課金は、**発信元リージョン × 宛先(Internet / 同大陸別リージョン / 別大陸)** の組み合わせで単価が決まり、月の累積量で階段式に安くなります[^bandwidth]。

[^bandwidth]: [Pricing — Bandwidth | Microsoft Azure](https://azure.microsoft.com/en-us/pricing/details/bandwidth/)

構造を言葉でつかむと:

- **月100GBまで無料**(どのリージョン発でも共通)
- **Internet egress** は北米/欧州発が最も安く、アジア・南米発は1.5〜2倍の単価
- **Inter-Region(同大陸内)** は例えば北米内・欧州内で $0.02/GB、アジア内で $0.08/GB
- **Inter-Continental** は $0.05〜$0.16/GB
- ルーティング方式に **Standard** と **Microsoft Premium Global Network** があり、後者のほうが速くて安い(例: 北米/欧州発 Internet egress で $0.08/GB 〜)

(実単価は月次で変わる可能性があるので[公式]([https://azure.microsoft.com/en-us/pricing/details/bandwidth/](https://azure.microsoft.com/en-us/pricing/details/bandwidth/)) を必ず確認してください)

### Private Linkは「安くする手段」ではない

「内部通信にしてegressを減らす」ためにPrivate Endpointを張る、という発想は正しい場面もありますが、**Private Linkは別の課金が乗る**ことを理解したうえで選ぶ必要があります[^privatelink]。

[^privatelink]: [Azure Private Link pricing](https://azure.microsoft.com/en-us/pricing/details/private-link/)

- **Private Link Service 自体は無料**
- **Private Endpoint は時間課金**(per-hour)
- **Inbound / Outbound Data Processed は GB 課金**(0–1 PB、1–5 PB、5+ PB の階段式ディスカウント)
- **Private Link経由でも通常のData Transfer料金は別途発生する**(Private Linkプレミアムと Data Transfer は独立)

つまり、「Private Endpointにすれば egress がタダになる」という理解は誤りです。**egress削減ではなく、ネットワークセキュリティ・トラフィック制御のための手段**と考えるべきです。

### AIチャット文脈での判断

AIチャットの通信プロファイルには特徴があります。

- **ストリーミング応答**: SSEやチャンク配信で長文応答を返す → 下り帯域が出る
- **会話履歴を含めたリクエスト**: 入力側も決して小さくない
- **外部AI API呼び出し**: App Service → Internet → 外部AIベンダー、という経路は**必ずInternet egress扱い**

概算の例(数字は構造説明のための架空値):

- 月50万会話 × 1会話平均2KB入力 + 8KB出力 = 月 **約5GB** 規模ならegressは無料枠内
- ストリーミング長文応答が主体で月平均20KB → 月50万会話で **約10GB** → それでも100GB無料枠内
- 月500万会話規模で **約100GB** を超え始める

ここでの判断の方向性:

- **リージョン選定を「AOAIと同居」だけで決めない**: 外部AIを呼ぶ経路のegress単価も設計要素
- **Microsoft Premium Global Network ルーティング**が使える構成か確認する(AFDなど利用時)
- **AOAIを Private Endpoint化するのは意味があるが、外部AI呼び出しはどう張ってもegressに落ちる**
- 大規模なら `Network Watcher` やNSG Flow Logsで**実際の下り量を計測**してから判断(勘で見積もると桁を外します)

## 5. 監視・ログ(Application Insights / Log Analytics): 全部入れたら詰む

Azure Monitor(Application Insights / Log Analytics)の課金で最初に押さえるべき事実は、公式の以下の一文です。

> Logsは**ほとんどの顧客でAzure Monitor課金の最大構成要素**

[出典][^monitor-cost]。クエリ実行は基本無料ですが、**ingestion・retention・export**で課金されます。

[^monitor-cost]: [Azure Monitor cost and usage](https://learn.microsoft.com/en-us/azure/azure-monitor/fundamentals/cost-usage)

### コストの形

- **ingestion(取り込み量 GB)** が最大の変数
- **retention(保持期間)** の延長は追加課金
- **export(Event Hubs等への継続エクスポート)** も別課金
- Cost Managementでは**サービス名が4つに分散**している(Azure Monitor / Log Analytics / Insight and Analytics / Application Insights)ので、まとめて見ないと実態を掴めない[^monitor-cost]

コミット購入の形もあります。Dedicated Cluster に commitment tier を設定すると**クラスター単位で一括プリペイド**になり、pay-as-you-goよりGB単価が下がります。ただし**クラスターにはpay-as-you-goオプションがない**ため、契約の判断は慎重に[^monitor-cost-logs]。

[^monitor-cost-logs]: [Azure Monitor Logs cost calculations and options](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/cost-logs)

### 実務のツマミ(サンプリング)

Application InsightsのOpenTelemetry SDK側サンプリングには2モードあります[^otel-sampling]。

[^otel-sampling]: [Sampling in Azure Application Insights with OpenTelemetry](https://learn.microsoft.com/en-us/azure/azure-monitor/app/opentelemetry-sampling)

- **Fixed-rate**: 0〜1の比率。`0.1` で 10% 送信
- **Rate-limited**: 秒あたりの最大trace数。`5.0` で 5 traces/sec

重要な挙動として、**サンプリング対象外の trace に紐づくログも一緒に drop する設定がデフォルトON**です[^otel-sampling]。これは「trace重視のアプリ」では合理的ですが、AIチャットのように**「エラー時は詳細ログが欲しい、通常時はメトリックだけ」**のケースでは意図した動きにならないことがあるので、設定を明示的に理解しておく必要があります。

対して Azure Monitor 側の **ingestion sampling はフォールバック**と位置付けられています。取り込み時に drop するため、どの trace/span が残るか制御できず、**broken trace(親子関係が壊れたspan)が増える**のがデメリットです[^otel-sampling]。

サンプリングが効いているかは KQL で確認できます[^otel-sampling]。

```kusto
union requests,dependencies,pageViews,browserTimings,exceptions,traces
| where timestamp > ago(1d)
| summarize RetainedPercentage = 100/avg(itemCount) by bin(timestamp, 1h), itemType
```

`RetainedPercentage` が 100 未満のitemTypeはサンプリングされています。

### AIチャット文脈での判断

AIチャットは「**ログに入れたくなるもの**」が多すぎるアプリです。安易に全部入れるとingestionが青天井に伸びます。

**典型的なアンチパターン**:

- プロンプト本文と応答本文をそのままtraces に詰める → **トークン量 = ingestion GB**になる
- 1会話で「リクエスト → AOAI呼び出し → ツール呼び出し → DB書き込み」まで全span取得 → 1会話で数十span
- 例外が起きた時だけでなく毎回 `payload` を付ける

**設計の方向性**:

- **本文はログに入れない**。ログに入れるのは `token_count_in`, `token_count_out`, `model`, `latency_ms`, `decision_branch` など**メタだけ**
- 本文を監査要件で残したいなら、**別のセキュアストレージ**(Blob + 鍵管理)に保存し、ログからはそのURI/ハッシュ参照にする
- **エラー時のみ full payloadログ** をサンプリング除外で通す(SDK側でtail-based的な設計ができる場合)
- trace数が膨らむなら **Rate-limited sampling** で秒あたり上限をかける
- 監査目的で保存したいが通常クエリしないデータは **Basic Logs** テーブルに振り分け(安価だが検索・retentionに制約あり)
- **Dedicated Cluster の commitment tier** は、月次ingestion量が安定してから検討(pay-as-you-goから切り替えるのは不可逆ではないが、未消化を生むリスクがある)

## 6. 総合: AIチャットアプリのコスト設計を1枚で見る

ここまでを5層構造に戻し、**PoCから本番に上げる時に最初に手をつけるツマミ**の早見表にします。

| 層 | サービス | 最初に見るツマミ | AIチャットでの典型的な地雷 |
|---|---|---|---|
| 1. 固定確保 | App Service | SKU・autoscale min/max・staging slot | AOAI応答待ちでCPU低→スケールしない。staging常時稼働でプランVM圧迫 |
| 2. 使用量 | Azure OpenAI | デプロイタイプ(Std/Global/PTU/Batch) | 早すぎるPTU化。会話履歴全送信で入力トークンが肥大 |
| 2'. 使用量 | 外部AI API | 呼び出し頻度・入出力トークン量 | AOAIとの多重呼び出しで合計トークンが倍になる |
| 3. スキーマ依存 | Cosmos DB | Autoscale or Provisioned / インデックスポリシー | 本文・embeddingの生データ保存。全プロパティ自動インデックス |
| 4. データ量 | Log Analytics / App Insights | サンプリング・Basic Logs・retention | プロンプト/応答本文をログに流し込む。全spanを無選択で取得 |
| 5. 経路 | egress / Private Link | リージョン選定・ルーティング | 外部AIを遠いリージョンから呼ぶ。Private Endpointで「安くなる」と誤解 |

### PoC→本番移行のチェックリスト

- [ ] **App Service**: autoscale min/maxを明示。staging slotの常時プロセスを洗い出し
- [ ] **Cosmos DB**: Provisioned manualで固定上限にしていないか。Autoscaleへ移行。長文本文はBlobへ分離、インデックスポリシー見直し
- [ ] **Azure OpenAI**: Standard系で1会話あたり平均トークン量を計測。Batch化できる業務を切り出し。PTUは数字が出てから
- [ ] **外部AI**: 呼び出し先リージョンとルーティングを確認。月egress量を試算
- [ ] **監視**: 本文ログを除外。サンプリング(Fixed-rate or Rate-limited)を SDK側で設定。Basic Logs への振り分け

### コスト設計の思考順序

1. **アーキテクチャを5層に分解する**(使用量/固定/スキーマ/データ/経路)
2. **各層のツマミで「桁が変わるもの」だけ先に潰す**(微調整は最後)
3. **測れるようにしてから最適化する**(1会話あたりのトークン・RU・ingestion・egress を月次で追う)
4. **単価は最後に考える**(単価交渉やPTU/commitment tier移行は、使用量が見えてからでないと成立しない)

## 7. ユースケース別: 規模と監査要件で変わるプラン選定

5層構造と各ツマミを見てきましたが、「じゃあ自分のプロジェクトは何を選べばいいのか」は規模と監査要件で答えが変わります。ここでは4つの典型的なユースケースに落として、**各層で何を選ぶか / 何を外すか** を比較します。

:::message
以下の月額は**構造説明のための概算レンジ**で、リージョン・為替・割引契約で大きく変動します。必ず[Pricing Calculator](https://azure.microsoft.com/ja-jp/pricing/calculator/)で自分の条件で再計算してください。
:::

### ユースケースA: 個人/チーム検証PoC(〜数十ユーザー・数百会話/日)

**目的**: 実装検証・動作確認。SLAなし、監査要件なし、夜間はほぼアイドル。

| 層 | 選定 | 理由 |
|---|---|---|
| App Service | **B1〜B2**(Basic) or App Service Free/Shared | 常時1台、autoscale不要。停止可ならDev/Test SKU |
| Cosmos DB | **Serverless** | 単一リージョンで十分、スパイク利用で課金最小 |
| Azure OpenAI | **Standard / Global Standard** (pay-per-token) | 量が読めないのでPTUは不要 |
| 外部AI | 必要に応じ直接呼び出し | egress は無料枠100GBに収まる |
| 監視 | App Insights **Basic Logs** + Fixed-rate sampling 10% | ingestionを絞る |
| 経路 | Private Link なし、公衆インターネット | セキュリティ要件がないなら不要 |

**月額感**: $50〜$200 程度(トークン消費次第)。**ポイントは「固定費をほぼゼロにする」**ことで、App ServiceをB1/Free、Cosmos DBをServerless、AOAIをStandardに寄せれば**使っていない時間の課金が消える**。

**地雷**: PoC延長で本番に流用するとき、Cosmos DB ServerlessはマルチリージョンもSLAもないため**本番移行時に作り直し**になる。Serverlessは「PoCで使い切りを前提」として選ぶ。

### ユースケースB: 社内ツール(数百〜1,000ユーザー・数千会話/日)

**目的**: 社内業務効率化。SLAは "ベストエフォート"、監査要件は軽め(社内ログ保存数ヶ月)。勤務時間にピーク、夜間ほぼゼロ。

| 層 | 選定 | 理由 |
|---|---|---|
| App Service | **P1V3**(Premium V3 最小) + Autoscale 1〜3台 | ステージング用slot 1つ、夜間min=1 |
| Cosmos DB | **Autoscale** (最小400 RU/s〜) | ピーク時間率が66%以下。スキーマ分離で本文はBlob |
| Azure OpenAI | **Global Standard** + Batch(夜間バルク処理) | 同期はStandard、ナレッジ再インデックス等はBatchで50%OFF |
| 外部AI | 1ベンダー併用程度、呼び出しリージョンを近接化 | 月egress 数GB〜数十GB |
| 監視 | Rate-limited sampling 5 trace/s、Analytics Logs 30日保持 | 本文はログに入れない、メタのみ |
| 経路 | AOAIに Private Endpoint 1本、外部AIは公衆 | 社内統制で最低限の閉域化 |

**月額感**: $500〜$2,000 程度。**ポイントは「勤務時間外のアイドルを作る」**ことで、App Service autoscale min=1、Cosmos DB Autoscale、監視サンプリングの3点で夜間コストを削る。Batch対応できる業務(日次ナレッジ要約など)を切り出せれば AOAI コストも効率化できる。

**地雷**: 「なんとなく Premium V3 の P2/P3」で入ると固定費が倍に跳ねる。**P1V3から始めて足りなければ上げる**のが正解。Cosmos DBも「安全のため Provisioned manual 10000 RU/s固定」は夜間無駄なので Autoscale 1000〜10000 のほうが良い。

### ユースケースC: 顧客向け本番サービス(数千〜数万ユーザー・数万会話/日・SLA要件あり)

**目的**: 対外サービス、SLA 99.9%以上、ログ保管1年以上、可能ならマルチリージョン。

| 層 | 選定 | 理由 |
|---|---|---|
| App Service | **P2V3〜P3V3** + Autoscale 2〜10台、本番slot別プラン | staging が本番VMを食わないようプラン分離。ゾーン冗長 |
| Cosmos DB | **Autoscale** + マルチリージョン読み取り + 継続バックアップ | SLA必須、Serverlessは外れる |
| Azure OpenAI | **Global Standard** を軸、トラフィック安定後に **PTU(最小15〜50)** 検討 | 数字が見えてからPTU移行判断 |
| 外部AI | 2〜3ベンダー fallback 構成、リージョン近接 + PGN ルーティング | 月egress 数百GB規模を想定 |
| 監視 | Fixed-rate 20% + エラー時 full payload 抜け道、Analytics 90日 + Basic 2年 | 監査用は Basic Logs へ |
| 経路 | AOAI/Cosmos DB は Private Endpoint、AFD前段 | 通信制御・WAF要件 |

**月額感**: $3,000〜$15,000 程度。**ポイントは「SLAと可用性のために払う固定費」と「使用量の監視/抑制」の両立**。App Service はゾーン冗長で2台下限、Cosmos DB はマルチリージョン読み取りで Serverless を外す、AOAI は Standard で計測しながら PTU 移行の損益分岐を見る、という形になる。

**地雷**: 最初から PTU を買って「容量を余らせる」。**PTU は最小15 PTU(Global) / 50 PTU(Regional)** で、gpt-4o なら入力 TPM 2,500 × 15 = 37,500 TPM相当。この水準を月次で継続的に使い切れないならStandard継続のほうが安い。

### ユースケースD: 大規模SaaS / 金融・医療など強い監査要件(数万〜数十万ユーザー・SLA 99.95%+・厳格な監査)

**目的**: 対外SaaSまたは規制業種の基幹。データ残留要件、長期ログ保管、マルチリージョン能動/能動、セキュリティ監査対応。

| 層 | 選定 | 理由 |
|---|---|---|
| App Service | **P3V3〜P5mV3** + 複数リージョンに Active-Active、Traffic Manager/AFD | リージョン障害への耐性 |
| Cosmos DB | **Provisioned Autoscale** + マルチリージョン書き込み + 継続バックアップ + 分析ストア | SLA 99.999%、RPO要件 |
| Azure OpenAI | **Data Zone Provisioned (PTU)** + Batch、ファインチューニング時は Regional Provisioned | データ残留要件、安定レイテンシ |
| 外部AI | 代替経路として持つがメインはAOAI、全呼び出しを DLP/プロキシ経由 | データ持ち出し制御 |
| 監視 | **Dedicated Cluster + Commitment Tier**、Analytics 1年 + Basic/Archive 7年 | コスト効率と監査保管の両立 |
| 経路 | 全サービス Private Endpoint、ExpressRoute、NSG Flow Logs 常時有効 | 完全閉域 + 監査ログ |

**月額感**: $20,000〜$100,000+ 。**ポイントは「PTUと Commitment Tier で単価を下げる代わりに、予測精度に投資する」**こと。未消化でも損、不足でもSLA損というトレードオフなので、**月次の実績レポート → 四半期のコミット調整**というFinOpsループが回せて初めてこの規模が機能する。

**地雷**: 監査要件で「全プロンプト・全応答を永久保存」を素直に Application Insights に入れる。ingestion GB がトークン量と直結して月額が青天井になる。**監査保管は Blob + 鍵管理 + イミュータブルポリシー**が本筋で、Log Analytics は運用ログに限定する。

### 規模別の早見表

| 観点 | A: PoC | B: 社内 | C: 本番 | D: 大規模SaaS |
|---|---|---|---|---|
| App Service | B1 / Free | P1V3 | P2-P3V3 ZR | P3V3+ Multi-Region |
| Cosmos DB | Serverless | Autoscale単一 | Autoscale+Read複製 | Provisioned+Write複製 |
| AOAI | Standard | Global Standard+Batch | Global Standard→PTU | Data Zone PTU+FT |
| 監視 | Basic Logs | サンプリング+Analytics 30d | サンプリング+Basic振分+1y | Dedicated Cluster+7y |
| 経路 | 公衆 | AOAIのみPE | 主要はPE+AFD | 全PE+ExpressRoute |
| 月額感(概算) | $50〜$200 | $500〜$2k | $3k〜$15k | $20k〜$100k+ |
| 切り替え判定 | 本番化で全面見直し | 顧客向け化でC相当に | 監査/規制入ったらD相当に | — |

### 段階移行の原則

**A→B、B→C、C→D の昇格で毎回必ず「作り直し」になる層**があります。事前に知っておくと設計判断がぶれません。

- **Cosmos DB Serverless → Provisioned** は**アカウント作り直し**。A→Bの移行は計画的に
- **AOAI Standard → PTU** はエンドポイント変更あり、**クライアントコードの接続切替**が必要
- **Log Analytics pay-as-you-go → Dedicated Cluster** はワークスペース移行で**過去ログは持っていけない**ケースがある
- **Private Endpoint の追加/撤去** は DNS と接続先設定の全面見直しで、運用中のサービスに影響する

逆に、**影響が軽く昇格しやすい層**は:

- App Service SKU 変更(ダウンタイムはあるが不可逆ではない)
- Cosmos DB Autoscale 上限引き上げ(即時)
- App Insights サンプリング率変更(設定反映のみ)

**結論として、ユースケースが1段階上がる可能性があるなら、Cosmos DB のスループット型と AOAI のデプロイタイプは最初から「上の段階」を見越した選定にしておく**のがコスト以上に大事です。

## 8. まとめ

- Azureのコストは「単価 × 使用量」ではなく、まず**コストの形**を理解する
- AIチャットアプリは**トークン(AOAI/外部AI)** / **RU(Cosmos DB)** / **ingestion(Log Analytics)** という3種類の使用量が同時に走る珍しいアプリで、それぞれ別の思考モデルが要る
- さらに**App Serviceの固定確保コスト**と**egress/Private Linkの経路コスト**が上乗せされる5層構造
- 本記事はユースケース駆動の**思考の地図**を提供するもので、最終判断は必ず公式料金ページと[Pricing Calculator](https://azure.microsoft.com/ja-jp/pricing/calculator/)で検算してください

PoC段階では「動かすこと」が正義でも、本番はコストの形を見ないと2〜3ヶ月目に痛い目に遭います。**測って、5層に分解して、桁の変わるツマミから回す**。これが企業本番AIチャットアプリのコスト設計の骨格です。

## 参考資料

### Azure App Service

- [Azure App Service Plans — Overview](https://learn.microsoft.com/en-us/azure/app-service/overview-hosting-plans)
- [Architecture Best Practices for Azure App Service (Web Apps)](https://learn.microsoft.com/en-us/azure/well-architected/service-guides/app-service-web-apps)
- [How to Enable Automatic Scaling — Azure App Service](https://learn.microsoft.com/en-us/azure/app-service/manage-automatic-scaling)
- [Configure Premium V3 Tier — Azure App Service](https://learn.microsoft.com/en-us/azure/app-service/app-service-configure-premium-v3-tier)

### Azure Cosmos DB

- [Plan and Manage Costs — Azure Cosmos DB](https://learn.microsoft.com/en-us/azure/cosmos-db/plan-manage-costs)
- [Compare Provisioned Throughput and Serverless — Azure Cosmos DB](https://learn.microsoft.com/en-us/azure/cosmos-db/throughput-serverless)
- [Create Containers and Databases with Autoscale Throughput](https://learn.microsoft.com/en-us/azure/cosmos-db/provision-throughput-autoscale)
- [Request Units in Azure Cosmos DB](https://learn.microsoft.com/en-us/azure/cosmos-db/request-units)
- [Optimize Request Cost — Azure Cosmos DB](https://learn.microsoft.com/en-us/azure/cosmos-db/optimize-cost-reads-writes)

### Azure OpenAI / Foundry

- [Understanding deployment types in Microsoft Foundry Models](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/deployment-types)
- [Provisioned throughput unit (PTU) costs and billing](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/provisioned-throughput-onboarding)
- [Fine-tuning cost management — Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/fine-tuning-cost-management)

### Azure Monitor / Application Insights / Log Analytics

- [Azure Monitor cost and usage](https://learn.microsoft.com/en-us/azure/azure-monitor/fundamentals/cost-usage)
- [Azure Monitor Logs cost calculations and options](https://learn.microsoft.com/en-us/azure/azure-monitor/logs/cost-logs)
- [Sampling in Azure Application Insights with OpenTelemetry](https://learn.microsoft.com/en-us/azure/azure-monitor/app/opentelemetry-sampling)

### ネットワーク

- [Pricing — Bandwidth | Microsoft Azure](https://azure.microsoft.com/en-us/pricing/details/bandwidth/)
- [Azure Private Link pricing](https://azure.microsoft.com/en-us/pricing/details/private-link/)
- [Private Endpoint Overview](https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-overview)
