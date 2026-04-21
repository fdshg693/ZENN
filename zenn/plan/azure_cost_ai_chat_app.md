---
title: "AIチャットアプリで学ぶAzureコスト設計 — App Service / Cosmos DB / Azure OpenAI / 外部AI / 監視系の勘所"
status: plan
---

## 記事メタ情報

- 対象読者: Azureの基本(App Service Plan、Cosmos DBのRU、AOAIのデプロイ、Application Insightsの存在)は押さえている中級エンジニア。企業の本番AIチャットアプリをAzure上で設計・運用する立場の人。
- 前提スタック: Azure App Service(Web App) + Azure Cosmos DB + Azure OpenAI + 外部AI API(例: Anthropic / OpenAI.com / Gemini) + Azure Monitor(Application Insights / Log Analytics)
- 読後に答えられるようにする問い:
  - AIチャットアプリで**最初にコストが跳ねる場所**はどこか
  - 各サービスで**「この軸を間違えると月額が桁で変わる」**ツマミはどれか
  - **PoC→本番移行**でどの設定を見直すべきか
- 扱わないこと: 単価の網羅転記、FinOps組織論、Cost Management UIの操作手順、Reserved/Savings Planの具体割引率(変動するため公式への誘導のみ)

## 想定トーン

- 料金表を読む前の「思考の地図」を提供する記事
- 数値は公式に書かれた一次情報(比較式・ガイドライン・境界値)のみ引用し、単価そのものは必ず公式へ誘導
- 各サービス章は「コストの形 → 実務で効くツマミ → AIチャット文脈での判断」の3段構成で統一

## セクション構成

### 0. はじめに: なぜAIチャットアプリのコストは読みにくいのか

- 想定アーキ図(App Service ← Cosmos DB / AOAI / 外部AI / App Insights)
- コストが読みにくい3要因:
  - **トークン課金**(AOAI/外部AI): 使用量が人間の会話に比例してスケールする
  - **RU課金**(Cosmos DB): 1クエリのコストがスキーマとインデックスに依存する
  - **ingestion課金**(Log Analytics): チャット履歴をログに落とすと二重課金になる
- この記事の歩き方: 各サービスを「コストの形」「実務のツマミ」「AIチャット観点の判断」で語る
- 根拠: 各章の公式URL総当たりだが、App Service Plan/RU/AOAI deployment types の存在は各ファイル冒頭で確認済み

### 1. App Service: プラン単位課金という「常時確保コスト」

**主張**: App Serviceは「インスタンス時間」で常時課金されるので、使用量課金のAOAI/Cosmos DBと思考モデルが違う。本番では**SKU選定と自動スケール戦略**が月額の8割を決める。

- コストの形:
  - プラン単位で秒単位プロレート課金。SKUとスケールアウト台数で決まる(`well-architected/service-guides/app-service-web-apps`)
  - **同一プランに相乗りするすべてのアプリ・スロットが同じVMを共有**(`overview-hosting-plans`)
  - つまり「スロットを増やしても無料じゃない」「相乗りアプリのログ出力が本番アプリのCPUを食う」
- 実務のツマミ:
  - Automatic scaling(HTTP駆動、per-app) vs Autoscale(メトリック/スケジュール、プラン全体)は**1プラン1方式**。同時併用不可(`manage-automatic-scaling`)
  - Automatic scaling特有の課金挙動: **always-readyだけが動いている間はprewarmedは課金されない**、トラフィックが来た瞬間prewarmedが確保される
  - **プランのassigned instance count = 含まれる全アプリのalways-ready値の合計**(例: 2+3+5 = 7 台)。1アプリのalways-readyを変えるとプラン全体の課金が動く
  - autoscaleのmin/max・scale-in閾値を決めずに使うとアンダー利用VMが残る(`well-architected`)
- AIチャット文脈での判断:
  - **「AIが遅いから待たされる」→ WebアプリのCPUはほぼ使ってないのにスケールアウト発火**、のパターンを避ける(AOAI呼び出し時間ベースのカスタムメトリックや応答待ち数でスケールするか、単に同時接続上限をアプリ側で制御)
  - Premium V3/V4 はリージョン/デプロイユニット依存で選べないSKUがある。**リージョン選定を「AOAIと同一リージョン」でやるとApp Service側のSKU選択肢が制約される**ことがある(`app-service-configure-premium-v3-tier`)
  - slot戦略: 本番+staging 1枚でプランVMを共有、slotのAlways Onとバックグラウンド処理でステージング側が本番のRAMを食う構造になりやすい

参考URL:
- https://learn.microsoft.com/en-us/azure/app-service/overview-hosting-plans
- https://learn.microsoft.com/en-us/azure/well-architected/service-guides/app-service-web-apps
- https://learn.microsoft.com/en-us/azure/app-service/manage-automatic-scaling
- https://learn.microsoft.com/en-us/azure/app-service/app-service-configure-premium-v3-tier

根拠ファイル: `temp/web/extract_appservice_cost.json`

### 2. Cosmos DB: RUの話は「スループット」と「スキーマ設計」の2本柱

**主張**: Cosmos DBはProvisioned/Autoscale/Serverlessの選択と、**RUを食わせるスキーマ**の両方で月額が決まる。AIチャットのログ保存という「書き込み偏重・読み込み少・テキストがデカい」典型ユースケースでハマりやすい地雷を示す。

- コストの形:
  - 課金は「スループット(RU)」+「ストレージ(GB)」が主軸、バックアップ/分析ストア/マルチリージョン/AZは追加課金(`plan-manage-costs`)
  - Provisioned manual = 予約したRU/sが常時課金、Autoscale = その時間の最大到達RU/s、Serverless = 消費RU分(`throughput-serverless`)
- Provisioned vs Serverless vs Autoscale:
  - 公式比較ケース: 常時500 RU/s必要なら**Provisioned安**、月250M RU消費のバーストなら**Provisioned安**、月20M RUだけのスパイク利用なら**Serverless安**(`throughput-serverless` の具体例)
  - **Autoscaleが得する境界: 月のうちピークRUを66%以下の時間しか使わない**(`provision-throughput-autoscale`)
  - Serverlessの制約: 単一リージョン、SLAではなくSLO(point-read <10ms, write <30ms) — マルチリージョン要件がある本番チャットでは使えない(`throughput-serverless`)
- RUを食わせる要素(スキーマ側):
  - アイテムサイズ、プロパティ数、**インデックス対象プロパティ数**が書き込みRUを押し上げる(`request-units`)
  - クエリ複雑性(述語数、UDF、対象データセットサイズ)が読み込みRUを押し上げる(`optimize-cost-reads-writes`)
  - **アンチパターン**: 検索しない大きなバイナリ/長文テキストをCosmosに入れる。推奨は「Blob Storageに本体を置き、Cosmosには参照と検索用メタのみ」(`optimize-cost-reads-writes`)
- AIチャット文脈での判断:
  - メッセージ本体(長文・非検索)は、書き込み頻度と文字数の掛け算でRUを食い続ける → 「本文はBlob、Cosmosにはsession/turnの構造化メタだけ」の分離を検討
  - 全文検索が要らないならインデックスポリシーで**embeddingや長文messageをインデックス除外** → 書き込みRU削減
  - 本番の常時トラフィック + 夜間急減 → **Autoscale 一択に近い(ピーク時間率が低い)**

参考URL:
- https://learn.microsoft.com/en-us/azure/cosmos-db/plan-manage-costs
- https://learn.microsoft.com/en-us/azure/cosmos-db/throughput-serverless
- https://learn.microsoft.com/en-us/azure/cosmos-db/provision-throughput-autoscale
- https://learn.microsoft.com/en-us/azure/cosmos-db/request-units
- https://learn.microsoft.com/en-us/azure/cosmos-db/optimize-cost-reads-writes

根拠ファイル: `temp/web/extract_cosmosdb_cost.json`

### 3. Azure OpenAI: デプロイタイプが価格の「型」を決める

**主張**: AOAIは「トークン単価」より先に**デプロイタイプ(Standard / Global Standard / Data Zone / Provisioned / Batch / Developer)**が価格の形を決める。型を間違えると後からツマミで調整しきれない。

- コストの形:
  - Standard系 = pay-per-token、Provisioned系(PTU) = 容量予約で固定、Batch = 24h以内ターンアラウンドで**50%割引**(`deployment-types`)
  - PTUは**model-independent quota**で複数モデルでプールを共有、クォータ=容量保証ではないのでFoundryでデプロイ→ポータルでreservation購入の順(`provisioned-throughput-onboarding`)
- 選定軸(公式ガイド):
  - 可変バースト → Standard / Global Standard
  - 一貫した高ボリューム → Provisioned
  - 時間非敏感の大規模バッチ → Batch(50%割引)
  - データ残留先がEU要件 → Data Zone
  - 単一リージョン縛り → Regional Standard / Regional Provisioned
- 本番AIチャット観点:
  - **対話トラフィックは平準化しにくい**(勤務時間集中、時差)→ 最初はStandard、負荷が読めてきたらPTUへ
  - PTUの最小単位(例: gpt-4o Global 15 PTU / 5増分、Regional 50 PTU / 50増分)(`provisioned-throughput-onboarding`)が**小規模には重すぎる**
  - **入出力の非対称性**: 長文出力モデル(o系、推論系)は出力トークンが高い。Llama-3.3-70BはPTU換算で**出力1トークン=入力4トークン扱い**(`provisioned-throughput-onboarding`)
  - プロンプトキャッシュ・システムプロンプトの共通化でinputトークン削減が直接効く
  - ファインチューニング: **Standardのホスティング料$1.70/hour** + per-tokenがかかる(Developerは$0/hourだがSLAなしでプリエンプティブル)(`fine-tuning-cost-management`)
  - 学習ジョブ: Global Standard trainingはRegionalから10〜30%割引、Developerはさらに50%割引(ただしデータ残留保証なし)

参考URL:
- https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/deployment-types
- https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/provisioned-throughput-onboarding
- https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/fine-tuning-cost-management

根拠ファイル: `temp/web/extract_aoai_cost.json`

### 4. 外部AI API: Azureから外に出すという「egressコスト」問題

**主張**: Anthropic / OpenAI.com / Gemini などをApp Serviceから呼ぶと、**AI API料金のほかに Azure側のegress課金**が乗る。Private Endpoint化するとegressは減るが逆にPrivate Link単価が乗るケースもある。

- コストの形:
  - Internet egressはGB単価の階段式。北米/欧州発は月100GBまで無料、以降10TBまで**$0.087/GB**(標準ルーティング)、Premium Global Networkルーティングなら**$0.08/GB**〜(`bandwidth pricing`)
  - アジア/南米発は同GBでも単価が1.5〜2倍(`bandwidth`)
  - Private Link Service自体は無料だが、**Private Endpointは時間課金+GB処理料金**、しかもPrivate Link経由でも**通常のData Transfer料金は別途発生**(`private-link pricing`)
- AIチャット文脈での判断:
  - ストリーミングで長文回答を返すと**入力と出力の両方向で帯域が出る** → 月N万会話×平均トークン数×UTF-8バイト数の概算でegress量を見積もる
  - 外部AIはAzureから見ると**Internet egress**扱い → リージョンによって同じ呼び出しでも単価が変わる
  - 「Azure内に閉じる」目的でAOAIをPrivate Endpoint化するのは意味があるが、**外部AIを呼ぶ経路はどう転んでもegressに当たる**
  - ルーティングオプション(Microsoft Global vs Internet)と**リージョン選定の組み合わせ**がegress月額を大きく動かす

参考URL:
- https://azure.microsoft.com/en-us/pricing/details/bandwidth/
- https://azure.microsoft.com/en-us/pricing/details/private-link/
- https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-overview

根拠ファイル: `temp/web/extract_networking_cost.json`

### 5. 監視・ログ(App Insights / Log Analytics): "全部ログに入れたら"で詰む

**主張**: チャットアプリは会話ログ・リクエスト・依存関係・例外で**ログ量が膨大になる**。Azure Monitor系は「多くの顧客で最大コスト」と公式が明言している。**サンプリングとBasic Logs**でコントロールしないと月額が青天井になる。

- コストの形:
  - Logs(Log Analytics + 旧App Insights)のingestion、retention、exportが主課金。クエリは基本無料(`cost-usage`)
  - **Cost Managementではサービス名が4つに分散**(Azure Monitor / Log Analytics / Insight and Analytics / Application Insights)、まとめて見ないと実態が掴めない(`cost-usage`)
  - Dedicated Cluster commitment tierで**cluster単位の一括プリペイド**が可能、ただしpay-as-you-goオプションはクラスターにない(`cost-logs`)
  - Basic/Auxiliary Logsとretentionはクラスター所属でも**常にワークスペース単位**で課金(`cost-logs`)
- OpenTelemetry サンプリング:
  - Fixed-rate(0〜1): `0.1`=10%送信、Rate-limited: `5.0`=5 trace/sec(`opentelemetry-sampling`)
  - **サンプリング外れのtraceに紐づくログもdropする設定がデフォルトON**(`opentelemetry-sampling`)
  - Ingestion samplingはフォールバック — 取り込み時dropのため**broken traceが増える** → できれば SDK側 sampling 推奨(`opentelemetry-sampling`)
  - 検証クエリ: `summarize RetainedPercentage = 100/avg(itemCount) by bin(timestamp, 1h), itemType`(`opentelemetry-sampling`)
- AIチャット文脈での判断:
  - **プロンプトと応答をそのままログに流すな**(トークン量=そのままingestion GB)。ログには metadata(token count / latency / model / decision) のみ、本文はセキュアストレージへ
  - エラー時だけ full payload ログ → サンプリング除外ルールを組む
  - 会話トレースを全部取ると**1会話=複数span**でtrace数が跳ねる → Rate-limited が現実的
  - **Basic Logs**: 安価だが検索機能とretentionが制限される → 「監査目的で保存はしたいが通常クエリしない」系を切り分けて置く

参考URL:
- https://learn.microsoft.com/en-us/azure/azure-monitor/fundamentals/cost-usage
- https://learn.microsoft.com/en-us/azure/azure-monitor/logs/cost-logs
- https://learn.microsoft.com/en-us/azure/azure-monitor/app/opentelemetry-sampling

根拠ファイル: `temp/web/extract_monitoring_cost.json`

### 6. 総合: AIチャットアプリのコスト設計を1枚で見る

**主張**: サービスごとのコストの形を重ねると、AIチャットアプリは**「固定費(App Service) + 使用量(AOAI/外部AI) + スキーマ依存量(Cosmos DB) + ログ量(Monitor) + egress」**という5層構造になる。各層で効くツマミが違うので、優先順位を持って回す。

- 5層の再整理と、それぞれで最初に見るべきツマミの早見表
- PoC→本番の移行チェックリスト:
  - App Service: autoscale上下限・assigned instance countの確認
  - Cosmos DB: Autoscale移行 / インデックス整理 / 長文Blob分離
  - AOAI: Standard継続かPTU検討か(ピーク時間率と予測可能性で判断)
  - 外部AI: リージョン選定とルーティング
  - 監視: サンプリング導入・本文ログ除外・Basic Logs振り分け
- 最後に: 単価は公式へ誘導(変動するので記事に書かない)

参考URL: 各章の主要URLを再掲

### 7. まとめ

- 「コスト=単価×使用量」ではなく「コストの形」を先に理解する
- AIチャットアプリは**トークン・RU・ingestion**という3つの"消費単位"が同時に走るアプリ
- 本記事はユースケース駆動の思考枠組みを提供するもので、最終判断は必ず公式料金表とPricing Calculatorで検算

## 本文で使わない(入れない)もの

- 具体単価の転記(日付と共に陳腐化する)
- FinOpsの組織論
- Azure Cost ManagementのUI操作手順
- Reserved Instance / Savings Plan の割引率の具体値

## Frontmatter(publish側で使う予定)

```yaml
---
title: "AIチャットアプリで学ぶAzureコスト設計 — App Service / Cosmos DB / Azure OpenAI / 外部AI / 監視系の勘所"
emoji: "💸"
type: "tech"
topics: ["azure", "appservice", "cosmosdb", "azureopenai", "applicationinsights"]
published: false
---
```
