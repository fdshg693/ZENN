---
title: "API Gateway + Lambda で API を作る前に — REST/HTTP API の選び方と中級者が踏む設計の地雷"
emoji: "🛣"
type: "tech"
topics: ["aws", "lambda", "apigateway", "serverless"]
published: false
---

## この記事の対象

- AWS Lambda を単体で動かした経験はある
- 「API Gateway + Lambda で API を作れ」と言われて、**REST API / HTTP API のどちらを選ぶか、どう統合するか、どこまで耐えられるか**の判断材料が欲しい

言語ランタイムには踏み込みません。API Gateway 側の設計判断だけを整理します。AWS 公式 Docs をベースに、各セクションに根拠 URL を添えます。

## 1. なぜ API Gateway + Lambda の設計で手戻りが起きるのか

Lambda 単体は動かせても、API Gateway 側は選択肢が多く、**先に決めないと後から変更しづらい**設定が並んでいます。

- API 種別: REST API / HTTP API(/ WebSocket API)
- 統合種別: Lambda proxy / Lambda 非 proxy / HTTP / VPC link / Mock
- 認可方式: IAM / Cognito / Lambda authorizer / JWT authorizer(HTTP のみ)
- 制約: 統合タイムアウト、ペイロードサイズ、スロットリング

「とりあえず REST API で proxy 統合、認可は後で」と決め打ちで進めると、ほぼ確実にどこかで手戻ります。本稿ではこの順番で**コードを書く前に決めておくべき**論点を整理します。

参考: [Amazon API Gateway FAQs](https://aws.amazon.com/api-gateway/faqs/)

## 2. REST API と HTTP API — 最初の分岐

API Gateway には RESTful API を作る口が 2 つあります。公式ドキュメントの表現を要約すると、**REST API と HTTP API はどちらも RESTful API を作るための製品だが、REST API は機能が豊富で、HTTP API は機能を絞って安価・低レイテンシに振ったもの** という位置付けです([Choose between REST APIs and HTTP APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-vs-rest.html))。

### 決定木

1. **以下のいずれかが必要** → REST API
   - API キー / 使用プラン(クライアント単位スロットリング・課金単位管理)
   - リクエスト検証(JSON Schema によるバリデーション)
   - AWS WAF 連携
   - Private API endpoint(VPC エンドポイントからのみアクセス)
   - Edge-optimized endpoint(CloudFront 経由の配信)
   - リソースポリシー(IP / VPC / アカウント制限)
2. **上記がどれも要らない** → HTTP API
   - より安価、低レイテンシ、JWT authorizer ネイティブ、CORS ネイティブ設定、自動デプロイ

### 主な機能差

| カテゴリ | REST API | HTTP API |
|---|---|---|
| エンドポイント | Edge-optimized / Regional / Private | Regional のみ |
| 認可 | IAM / Resource policy / Cognito / Lambda | IAM / Cognito(JWT 経由)/ Lambda / JWT |
| API キー・使用プラン | あり | なし |
| リクエスト検証 | あり | なし |
| AWS WAF | あり | なし |
| CORS | 手動設定 | ビルトイン |
| 自動デプロイ | なし | あり |
| 相互 TLS | あり | あり |

出典: [Choose between REST APIs and HTTP APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-vs-rest.html)

公式 FAQ も「HTTP API は Lambda や HTTP バックエンドにプロキシする用途に最適化されており、サーバーレスワークロード向け。REST API より安価で速いが、API 管理機能(使用プラン等)は現状サポートされない」と書いています([API Gateway FAQs](https://aws.amazon.com/api-gateway/faqs/))。

**迷ったら HTTP API を起点にし、必要機能が増えてきたら REST API に切り替える**、で十分です。移行の手戻りが嫌なら最初から REST API を選んでも機能面で困ることはありません。

## 3. Lambda 統合の 4 パターンと payload format

API 種別を決めたら、Lambda との統合方法を決めます。

### パターン

- REST API
  - **Lambda proxy 統合**: HTTP リクエスト丸ごとを event オブジェクトとして Lambda に渡す。最も簡単で、ほぼこれを選ぶ。
  - **Lambda 非 proxy(カスタム)統合**: マッピングテンプレート(VTL)でリクエスト/レスポンスを変換。既存 Lambda のシグネチャを API 側で吸収したい場合など、限定的に使う。
- HTTP API
  - **Lambda proxy 統合のみ**。非 proxy は存在しない。

公式ドキュメントの要約: **proxy 統合は「Lambda の ARN を指して呼び出し権限を渡すだけ」でセットアップが済む**。非 proxy 統合はそれに加えて、**リクエスト/レスポンスのマッピング(VTL)を自分で書く必要がある** という違いです([Lambda integrations for REST APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-integrations.html))。

### HTTP API の payload format: 1.0 と 2.0

HTTP API の Lambda proxy 統合では `payloadFormatVersion` を選びます。支援値は `1.0` / `2.0`。

- コンソールで作成すると最新(= 2.0)が既定
- **AWS CLI / CloudFormation / SDK で作成する場合は `payloadFormatVersion` を明示必須**

v2.0 の主な違い([公式](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-lambda.html)):

- `multiValueHeaders` / `multiValueQueryStringParameters` を持たない。重複ヘッダ・クエリはカンマ連結されて `headers` / `queryStringParameters` に入る
- `cookies` フィールドが追加(レスポンス側では各 cookie が `set-cookie` ヘッダになる)
- `rawPath` を持つ(ただしカスタムドメイン API マッピングのパスは反映されないので、そこに依存するなら v1.0)
- レスポンスで `statusCode` を省略しても、API Gateway が valid JSON を見て 200 / content-type `application/json` を推論する

**新規は v2.0 を基本**、カスタムドメインのマッピングを path 解釈に使う特殊事情があるときだけ v1.0、で問題ありません。

### REST API 非 proxy 統合をあえて使うケース

- 古い Lambda(event フォーマットがすでに固定)を API 化したい
- レスポンスヘッダや body を API Gateway 側で強制変換したい
- `200 OK` 以外のステータスへのマッピングを API Gateway で集中管理したい

新規開発で積極的に選ぶ理由は薄いです。迷ったら proxy 統合で Lambda 側にロジックを寄せるほうが、テストしやすく責務も明確です。

## 4. 認可の選び方

API Gateway の認可は API 種別で使える選択肢が違います([公式比較表](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-vs-rest.html))。

| 認可 | REST API | HTTP API |
|---|---|---|
| IAM | ○ | ○ |
| Resource policies | ○ | × |
| Amazon Cognito(ユーザープールオーソライザ) | ○ | ○(JWT 経由) |
| Lambda authorizer | ○ | ○ |
| JWT authorizer | ×(Lambda authorizer で代替) | ○ |

### 使い分け

- **クライアントも AWS 内(別アカウント / EC2 / Lambda など)**: IAM 署名で済ませる。鍵管理も不要。
- **既存 IdP(Cognito / Auth0 / Okta / Azure AD など)が発行する JWT を検証したいだけ**: HTTP API + JWT authorizer が最短。コードなしで issuer と audience を指定するだけ。
- **Cognito ユーザープールを IdP として使う**:
  - REST API なら Cognito オーソライザを直接選べる
  - HTTP API なら JWT authorizer 経由で使う(Cognito の `IssuerUrl` を JWT 設定で指定)
- **独自ロジック(API キー独自検証、独自ヘッダ、動的ポリシー)**: Lambda authorizer。REST / HTTP 共通で使えるが、**HTTP API の Lambda authorizer 応答は 10 秒タイムアウト、結果サイズは 8 KB まで**(後述)。

JWT authorizer を使うと、検証済みの claims が Lambda 統合の event で読めます。公式ドキュメントによれば、**API Gateway が JWT を検証した後、トークン内の claims を統合先(Lambda など)に渡す**仕組みで、たとえば `emailID` という claim は Lambda 側から `$event.requestContext.authorizer.jwt.claims.emailID` で参照できます([Control access to HTTP APIs with JWT authorizers](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html))。

「Cognito を使いたい」「OIDC IdP を使いたい」という要件がほとんどのケースでは、HTTP API + JWT authorizer が手数最小になります。

## 5. 設計で踏みやすい制約

次の値は**設計前に**把握しておきます。いずれも公式 Docs 由来。

### タイムアウト

- **REST API 統合タイムアウト**: `50 ms 〜 29 s`(Regional / Edge-optimized / Private すべて同じ)。Regional と Private については**引き上げ申請可能**。ただし公式ドキュメントは、**29 秒を超える引き上げと引き換えに、そのアカウントの Region レベルスロットリング枠を削られる可能性がある**と注記しています([REST API quotas](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-execution-service-limits-table.html))。
- **HTTP API 統合タイムアウト**: **最大 30 秒、引き上げ不可**([HTTP API quotas](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-quotas.html))
- **Lambda 関数側のタイムアウト**: 最大 15 分。これが API Gateway 側の上限を超えていても、API Gateway が先に切ってしまう

30 秒以上かかる処理を同期 API で返そうとしている時点で設計を疑い、非同期化 (SQS / Step Functions / 202 Accepted + ステータス API) を検討します。

### ペイロードとヘッダ

- **ペイロード上限**: REST / HTTP とも `10 MB`
- **全ヘッダの合計サイズ(名前+値+区切り)**: REST API `10240 Bytes`(private API は `8000 Bytes`)
- **Lambda authorizer 結果サイズ**: `8 KB`
- **HTTP API の Lambda authorizer 応答タイムアウト**: `10000 ms`

出典: [REST API quotas](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-execution-service-limits-table.html), [HTTP API quotas](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-quotas.html), [Amazon API Gateway endpoints and quotas](https://docs.aws.amazon.com/general/latest/gr/apigateway.html)

ファイルアップロードを Lambda に通す設計は、10 MB 上限と 29/30 秒の組み合わせですぐ破綻します。S3 pre-signed URL を発行して**クライアント直 PUT**、アップロード完了イベントを別の Lambda で処理、が定石です。

### スロットリング

- **アカウント単位(Region ごと)** に RPS とバースト上限があり、**アカウント内の全 API で共有**される。
- 超えるとクライアントに `429 Too Many Requests` が返る。
- REST API では使用プランで API 単位・ステージ単位・API キー単位の制限をさらに設定できる。
- HTTP API では使用プラン機能そのものがないので、アカウント上限 + ルートレベルスロットリングで対処。

出典: [Throttle requests to your REST APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-request-throttling.html)

「**アカウント内の他の API が原因で自分の API が 429 を返す**」という事故が起きるので、スロットリング上限は Region 共通リソースとして扱うこと。

## 6. API Gateway と Lambda の責務分割 — 機能が被るところはどう切り分けるか

API Gateway と Lambda は、リクエスト検証・認可・スロットリング・CORS・レスポンス整形・キャッシュ・ロギングで機能が重複します。「両方でやる」は原則 NG、「どちらか一方に寄せる」が AWS の一貫した方針です。

全体の原則は、**API Gateway は「Lambda に届く前に弾けるもの」に責務を寄せ、Lambda は「ビジネスロジックと行レベルの認可」に集中する**。この線を引くだけで設計判断のほとんどが決まります([Well-Architected: Serverless API access control](https://aws.amazon.com/blogs/compute/building-well-architected-serverless-applications-controlling-serverless-api-access-part-3/))。

### 6.1 リクエスト検証

- **REST API**: 必須パラメータ・Content-Type・JSON Schema の一次検証は **API Gateway の request validator** に寄せる。不正リクエストは Lambda を起動する前に弾けるのでコスト・DDoS 耐性ともに有利。
- **HTTP API**: **request validator 機能がない**。Lambda 側で [Powertools Validator / Parser](https://docs.powertools.aws.dev/lambda/typescript/latest/features/parser/) で JSON Schema 検証をかける。
- **Lambda 側では常に**: ビジネスルール検証(在庫あるか、この userId がこの order を触れるか など)を担当。
- **トラップ**: REST API で APIGW 側に検証を入れつつ Lambda でも同じ検証を書くと、**エラー応答の形式が 2 種類混在**してフロント実装が破綻する。同じ検証は 1 箇所。

### 6.2 認証・認可

- **トークン検証(署名・exp・iss・aud)は APIGW の authorizer に完全オフロード**。REST API なら Cognito authorizer か Lambda authorizer、HTTP API なら JWT authorizer。
- **Lambda 側で再チェックすべき**のは以下だけ:
  1. **行レベル権限**: `userId == ownerId` のように **データに依存する判定**
  2. **細粒度スコープ**: `scope: orders:write` のような claim を読むのは APIGW 通過後
  3. **リプレイ対策**: jti を DynamoDB と突き合わせる場合
- トークン**署名検証を Lambda で重ねてやる必要はない**(APIGW が通した時点で検証済み)。
- **トラップ**: authorizer のキャッシュ(Lambda authorizer は最大 1 時間)が効いていると、ユーザ失効直後も一定時間アクセスできてしまう。センシティブな操作を持つルートは `authorizerResultTtlInSeconds=0` にする。

### 6.3 レート制限・スロットリング

3 層で役割が違うので併用が前提です。

| 層 | ツール | 責務 |
|---|---|---|
| 外縁 | AWS WAF rate-based rule | 攻撃性トラフィックの遮断 |
| API Gateway | アカウント/ステージ/ルート/使用プラン単位のスロットル | 正常系の RPS・バースト保護、クライアントに `429` を返す |
| Lambda | reserved concurrency | 下流 DB(RDS/Aurora)を守る最終防波堤 |

**Lambda reserved concurrency だけで絞ると、APIGW から見ると 5xx で返るのでクライアントは「API が壊れた」と誤解**します。レート制限は APIGW を先に効かせるのが原則([Rate limiting strategies, AWS Architecture blog](https://aws.amazon.com/blogs/architecture/rate-limiting-strategies-for-serverless-applications/))。

### 6.4 CORS

**片方だけに寄せる**のが鉄則。両方で `Access-Control-Allow-Origin` を返すとヘッダが二重化され、ブラウザ側で CORS エラーになります(Chrome の "Multiple values in Access-Control-Allow-Origin" は大抵これ)。

- **HTTP API**: APIGW の組み込み CORS 設定を使う。OPTIONS preflight を Lambda を起動せずに返せるのでコスト削減・コールドスタート回避にも効く。Lambda は CORS ヘッダを返さない。
- **REST API + Lambda proxy 統合**: **Lambda 側で CORS ヘッダを返す**(公式推奨)。APIGW コンソールの "Enable CORS" を併用しない。
- **REST API + 非 proxy 統合**: 統合レスポンスのマッピングで APIGW 側が返す。

### 6.5 レスポンス整形・エラーシェイピング

- **モダンな基本**: Lambda proxy 統合 + Lambda が JSON を組み立てる。
- **VTL マッピングテンプレートを使うべきとき**:
  - **AWS サービス直接統合**(DynamoDB や SQS を Lambda を挟まず直接呼ぶ)
  - レガシー互換で既存ペイロード形式に合わせる必要があるとき
- **Gateway Response は APIGW 側でしか整形できない**: authorizer 失敗、スロットリング(429)、ペイロード超過(413)など、**Lambda に到達していないエラー**は APIGW の Gateway Response で共通フォーマットに揃える。ここを怠ると、正常系は整ったエラー形式、APIGW 側エラーは AWS デフォルト形式、という不揃いな API になる。
- **トラップ**: proxy 統合で Lambda が `statusCode` / `headers` / `body` の契約を守らないと APIGW は即 502。また VTL と Lambda の両方で body を書き換え始めると原因追跡が事実上不能になる。

### 6.6 キャッシュ

| キャッシュ層 | 向いている対象 |
|---|---|
| **APIGW レスポンスキャッシュ**(REST API のみ、ステージ単位) | GET の冪等レスポンス。**Lambda を起動せずにヒット応答を返せる**ので、コスト・レイテンシとも最強。HTTP API には無い |
| Lambda グローバルスコープ | 小さな計算結果・設定値の memoize。**同一ウォームコンテナ内だけ**有効 |
| ElastiCache (Valkey/Redis) | 複数関数で共有、TTL・サイズが大きいもの |

**APIGW キャッシュのトラップ**: キャッシュキーに `Authorization` ヘッダや `userId` クエリを含め忘れると、**他人の結果が別ユーザに返る**重大事故になります。認可を含むレスポンスは、キー設計を先に固めてからキャッシュを有効化する。

### 6.7 ロギング・トレーシング

- **APIGW アクセスログ**: `$context.requestId` / `$context.xrayTraceId` / `$context.integrationLatency` / `$context.authorizer.*` を構造化 JSON で出す。
- **Lambda 側**: Powertools Logger で structured logging。APIGW の `requestId` を相関キーにする。
- **X-Ray active tracing を APIGW と Lambda の両方で有効化**して 1 本のトレースに繋ぐ。
- **APIGW 側にしか残らない情報**: **Lambda に到達しなかった**リクエストのログ(authorizer で弾いた、スロットルで 429、形式エラーで 400)。Lambda 側からは原理的に見えないので必須。
- **トラップ**: APIGW の execution logging を `INFO` にすると**リクエストボディ全体が CloudWatch に流れる**(PII/シークレット漏洩)。本番は `ERROR` が推奨。詳細は X-Ray + アプリログで補う。

### 責務分割の一行まとめ

| 機能 | どこでやる |
|---|---|
| スキーマ/必須パラメータ検証 | REST=APIGW / HTTP=Lambda(Powertools) |
| トークン署名検証 | APIGW authorizer |
| 行レベル認可 | Lambda |
| レート制限 | WAF → APIGW → Lambda(reserved concurrency)の 3 層 |
| CORS | REST=Lambda / HTTP=APIGW(片方に寄せる) |
| 正常系レスポンス整形 | Lambda(proxy) |
| APIGW 手前エラーの整形 | APIGW Gateway Response |
| GET の冪等レスポンスキャッシュ | APIGW(REST のみ) |
| トレーシング | APIGW + Lambda 両方で X-Ray 有効化 |

## 7. サーバーレス関数の罠を AWS ではどう解決するか

[別記事「サーバーレス関数の実践ガイド」](/articles/serverless_functions_practical_guide.md)で扱った、サーバーレス関数に共通する落とし穴(Cold Start、ステートレス/マルチインスタンス、DB 接続爆発、FD 上限、冪等性、`/tmp` ephemeral storage)を、API Gateway + Lambda 構成ではどの AWS 製品で解決するかの対応表です。

| 元記事の問題 | AWS での解決手段 |
|---|---|
| **Cold Start が気になる** | Lambda Provisioned Concurrency / SnapStart(Java)/ Lambda Power Tuning でメモリ最適化。APIGW + Lambda 経路では、APIGW のレスポンスキャッシュで Lambda 起動自体を回避するのが最も効く |
| **同時実行が増えると DB 接続が爆発** | **RDS Proxy** を Lambda と RDS/Aurora の間に挟む。Aurora Serverless v2 / DSQL のサーバーレス DB なら HTTP ベースの [Data API](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/data-api.html) で接続プール不要 |
| **ステートレス/マルチインスタンスなのに状態を持ちたい** | セッション/一時状態は **DynamoDB**(TTL 付き)、ElastiCache、S3、Step Functions の実行コンテキストに外出し |
| **in-memory キャッシュがインスタンス間で効かない** | 読み取りレスポンス自体を **APIGW レスポンスキャッシュ**、共有キャッシュは **ElastiCache for Valkey/Redis**、または DynamoDB Accelerator (DAX) |
| **FD 1,024 本(や同様の)上限で接続が枯渇** | AWS SDK v3 の Keep-Alive を明示設定 + Lambda reserved concurrency で同時実行数を絞る。DB は RDS Proxy で接続多重化 |
| **29/30 秒以上かかる処理を同期で返せない** | **202 Accepted + SQS / Step Functions** パターン。Step Functions Standard は最長 1 年、Express は 5 分・10 万 TPS |
| **`/tmp` は揮発で信用できない** | 永続ファイルは **S3**、共有ファイルシステムが要るなら **EFS for Lambda**、スナップショット前提の一時計算なら `/tmp` を許容 |
| **冪等性を担保したい(SQS の at-least-once)** | [Powertools Idempotency](https://docs.powertools.aws.dev/lambda/typescript/latest/features/idempotency/) + DynamoDB を idempotency store に |
| **関数バンドルが肥大化して Cold Start が悪化** | Lambda レイヤーに共通依存を切り出し、ML モデルなどは S3 から起動時にロード、もしくは **Lambda コンテナイメージ**(最大 10GB) |
| **Edge で動かしたいが Edge Runtime の制約が辛い** | 認証・リダイレクト・A/B テストは **Lambda@Edge** か **CloudFront Functions**。重いロジックは Regional Lambda に残す |
| **クライアントに Lambda を通さず直に S3 へアップロードさせたい** | **S3 pre-signed URL** を Lambda が発行、クライアント直 PUT、S3 イベントで後続 Lambda を起動(10MB 制約の回避策) |

「サーバーレス関数の制約は消えないが、**制約ごとに専用の AWS マネージドサービスが用意されている**」という見方をすると、アーキテクチャ選定がだいぶシンプルになります。

## 8. ユースケース別構成 — 他 AWS 製品との組み合わせ

ここまでの設計判断を、よくあるユースケースに落とし込みます。どれも「APIGW + Lambda だけでは破綻するが、**他の AWS 製品を足すと素直に解ける**」という共通構造を持ちます。

### A. ファイルアップロード(S3 Pre-signed URL)

```
[Client]─PUT(直接)─▶[S3]─Event──▶[Lambda: 処理]
   │
   └─GET /upload-url─▶[APIGW]─▶[Lambda: URL 発行]
```

- **具体例**:
  - **医療画像共有 SaaS**: 放射線科医が数百 MB の DICOM 画像をブラウザからアップロード。`POST /studies` で Lambda が `study_id` を発行 + pre-signed URL を返し、ブラウザが S3 へ直 PUT。アップロード完了を S3 Event で受けた後続 Lambda が Rekognition でメタデータ抽出 → DynamoDB に保存。同期 API なら 29 秒で切れるが、この構成なら 1GB でも問題なし。
  - **動画投稿アプリ(TikTok 型)**: クライアントが `/videos/upload-url` を叩いて pre-signed POST を取得 → S3 に直接アップロード → S3 Event → Lambda が **MediaConvert** を起動してトランスコード → 完了イベントで DynamoDB の `status: processing → ready` に更新。
  - **経費精算アプリのレシート添付**: iOS アプリが撮影画像(5〜10MB)を pre-signed URL で S3 へ、Textract でレシート OCR → 金額・日付を自動入力。
- **構成要素**: APIGW + Lambda(URL 発行)+ S3 + S3 Event Notifications + Lambda(後続処理)。必要に応じて CloudFront / S3 Transfer Acceleration / MediaConvert / Textract / Rekognition。
- **解決する問題**: APIGW の **ペイロード 10MB 制限** を回避し、Lambda を転送経路から外す。クライアントは S3 に直接 PUT するため転送中の Lambda 実行時間課金もゼロ。
- **主な落とし穴**:
  - 単発 PutObject は最大 5GB、超えるなら multipart upload(最大 5TB)
  - Pre-signed URL の `expiresIn` は短く(5〜15 分目安)、オブジェクトキーは UUID で推測・上書き防止
  - URL 発行 Lambda の IAM ロールは `s3:PutObject` を特定プレフィックス(例: `uploads/{userId}/`)に限定
  - Content-Type / Content-Length-Range を pre-signed POST の条件に含めないと、**任意サイズ・任意 MIME** をアップロードされる
- 参考: [Patterns for building an API to upload files to Amazon S3](https://aws.amazon.com/blogs/compute/patterns-for-building-an-api-to-upload-files-to-amazon-s3/) / [Securing Amazon S3 presigned URLs](https://aws.amazon.com/blogs/compute/securing-amazon-s3-presigned-urls-for-serverless-applications/)

### B. 非同期ロングランニングジョブ(202 Accepted + Step Functions)

```
POST /jobs ─▶[APIGW]─▶[Lambda: 受付]─┬─▶[Step Functions / SQS]─▶[Worker Lambda]
                                     └─▶[DynamoDB: job status]
GET /jobs/{id} ─▶[APIGW]─▶[Lambda: status]─▶[DynamoDB]
```

- **具体例**:
  - **PDF レポート生成 SaaS**: BI ダッシュボードで「月次レポート出力」ボタン → `POST /reports` で Lambda が `job_id` を 202 で即返す → Step Functions が「DB 集計 → グラフレンダリング(数分)→ PDF 生成 → S3 保存 → SES でメール送信」を順次実行。ユーザーは `GET /reports/{job_id}` で状態を poll、完了したら S3 の pre-signed URL を取得。
  - **機械学習推論ジョブ**: 画像 100 枚を一括判定したい EC サイトの出品画像 NG 判定。`POST /moderation-jobs` で受付 → SQS にメッセージ投入 → SageMaker エンドポイントを呼ぶワーカー Lambda が並列処理 → 結果を DynamoDB に書き戻し、完了時 SNS でフロントへ通知。
  - **動画のサムネイル一括生成**: 動画投稿後 `POST /videos/{id}/thumbnails` → Step Functions Express が「フレーム抽出 → リサイズ × 3 解像度 → S3 Put → DynamoDB 更新」を 5 分以内にこなす。
  - **帳票の外部 API バッチ照会**: 1 リクエストで 1000 件の法人番号を与信 API(外部、1 req あたり 2 秒)で照合。Step Functions の Map state で並列度 50 に制御し、トータル 40 秒 → バックグラウンドで完結。
- **構成要素**: APIGW + Lambda(受付)+ Step Functions or SQS + ワーカー Lambda + DynamoDB(進捗・結果)+ SNS/SES(完了通知)+ S3(成果物)。
- **解決する問題**: APIGW 統合タイムアウト **29 秒** と Lambda 15 分上限を超える処理に対応。受付は即 Job ID を返し、結果は polling or WebSocket で通知。
- **Step Functions の選択**:
  - **Standard**: 最長 1 年実行、25,000 イベント上限。業務ワークフロー(承認フロー、月次処理)向き
  - **Express**: 最長 5 分、10 万 TPS。サムネイル生成のような高頻度・短時間向き
- **落とし穴**: 冪等性キー(Job ID)必須、ペイロード 256KB 超は S3 クレームチェック、SQS は DLQ を必ず設計、polling 間隔はクライアント側で指数バックオフ
- 参考: [Continue long-running workflows using Step Functions](https://docs.aws.amazon.com/step-functions/latest/dg/tutorial-continue-new.html) / [Building an API poller with Step Functions and Lambda](https://aws.amazon.com/blogs/compute/building-an-api-poller-with-aws-step-functions-and-aws-lambda/)

### C. Cognito 認証付き CRUD(HTTP API + JWT authorizer + DynamoDB)

```
[Client]─Bearer <id_token>─▶[APIGW HTTP API + JWT authorizer]─▶[Lambda]─▶[DynamoDB]
                                       │
                                       └─ Cognito User Pool (issuer)
```

- **具体例**:
  - **タスク管理 SaaS(Todoist 型)**: React ネイティブアプリが Cognito でサインイン → ID token を取得 → `GET /tasks` `POST /tasks` `PATCH /tasks/{id}` を Bearer 付きで呼ぶ。Lambda は `claims.sub`(ユーザー ID)を partition key に DynamoDB を Query し、**他人のタスクは原理的に取得不可**。Lambda authorizer を書かずに完結。
  - **社内向け勤怠打刻 API**: 社員が iOS アプリから `POST /timesheets/punch-in` を叩くと、Lambda は `claims["cognito:groups"]` を見て管理者なら代理打刻可、一般社員なら自分のみ、と行レベル認可。DynamoDB に `userId#date` で保存。
  - **家計簿アプリ(マルチデバイス同期)**: ユーザーが Web とスマホから同じ Cognito アカウントでログイン → 同じ `sub` に紐づく取引記録を DynamoDB 単一テーブル設計(`PK: USER#<sub>`, `SK: TXN#<date>#<id>`)で管理。APIGW レベルで JWT 検証、Lambda はビジネスロジックのみ。
- **構成要素**: APIGW HTTP API + Cognito User Pool + JWT authorizer + Lambda + DynamoDB(単一テーブル設計)+ 必要に応じて Cognito Identity Pool(S3 直接アクセス用の一時クレデンシャル発行)。
- **解決する問題**: 認証処理を APIGW にオフロードし、Lambda は `requestContext.authorizer.jwt.claims.sub` を使って行レベル認可とデータ操作に集中。Lambda authorizer 自作不要。
- **落とし穴**:
  - ID token と access token で `aud` claim の有無が違う。`aud` を検査対象にすると access token で拒否される
  - authorizer のキャッシュ有効時、ユーザ失効が最大 1 時間反映されない
  - APIGW は変更後のデプロイを忘れがち(`aws apigatewayv2 create-deployment`)
  - **DynamoDB Query の KeyConditionExpression に `sub` を含めないと他人のデータが取れる** — IAM だけでは防げず、アプリ側責務
- 参考: [Control access to REST APIs using Cognito user pools](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-integrate-with-cognito.html) / [Build a CRUD HTTP API with Lambda and DynamoDB](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-dynamo-db.html)

### D. Webhook レシーバー(EventBridge ファンアウト)

```
[SaaS]─POST /webhook─▶[APIGW]─▶[Lambda: 署名検証]─▶[EventBridge]─┬─▶[Lambda A]
                                                                 ├─▶[SQS → Lambda B]
                                                                 └─▶[Step Functions]
```

- **具体例**:
  - **EC サイトの Stripe 決済 Webhook**: `payment_intent.succeeded` を Stripe が POST → Lambda が `Stripe-Signature` ヘッダを HMAC で検証 → EventBridge に publish → (1) 注文 DB 更新 Lambda、(2) SES で領収書メール送信、(3) Slack で売上通知、(4) Analytics 用に Kinesis Firehose へ、と 4 方向ファンアウト。Stripe は 10 秒でタイムアウトし失敗なら最大 3 日間リトライするので、**検証だけして即 202** が必須。
  - **GitHub Webhook → CI 連携**: `push` イベントを受け、`repository.full_name` に応じた EventBridge ルールで該当プロジェクトのビルド Step Functions を起動。特定ブランチだけ E2E テストを回す、などをパターンマッチで選り分け。
  - **Shopify の注文通知を社内基幹へ同期**: 注文作成 Webhook を APIGW で受け、SQS バッファ経由で基幹システムの HTTP API に転送。売上急増時のスパイクを SQS で吸収し、基幹側の RPS 上限を超えないようにワーカー側で reserved concurrency 制御。
  - **SaaS の外部通知用 Webhook サーバー(自社 → 顧客)とは逆向き**: 顧客 SaaS からの着信専用として、**Lambda Function URL + IAM 署名** も選択肢。細かい制御は APIGW、シンプルな着信は Function URL。
- **構成要素**: APIGW + Lambda(HMAC 署名検証)+ EventBridge(パターンルーティング)or SNS(多数コンシューマファンアウト)+ SQS/Lambda/Step Functions。シークレットは **Secrets Manager** または Parameter Store。
- **解決する問題**: 外部 SaaS の Webhook を疎結合な内部イベントに変換。送信元の短いタイムアウト(5〜10秒)に合わせて、検証後は即 202 を返して下流を非同期化。SQS バッファで送信元のリトライ嵐も吸収。
- **落とし穴**:
  - HMAC 比較は **`hmac.compare_digest` のような定数時間比較**にする(タイミング攻撃対策)
  - EventBridge は 1 エントリ 256KB 上限、超えるなら S3 クレームチェック
  - Secrets を Lambda 環境変数に平文で置かない
  - **at-least-once なので冪等化必須** — Stripe の `event.id` や GitHub の `X-GitHub-Delivery` を DynamoDB idempotency store で dedup
- 参考: [Sending and receiving webhooks on AWS](https://aws.amazon.com/blogs/compute/sending-and-receiving-webhooks-on-aws-innovate-with-event-notifications/) / [Creating a webhook endpoint using a Lambda function URL](https://docs.aws.amazon.com/lambda/latest/dg/urls-webhook-tutorial.html)

### E. WebSocket リアルタイム(チャット/通知)

```
[Client]──WS──▶[APIGW WebSocket API]─┬─▶[Lambda $connect]──▶[DynamoDB: connectionId]
                                     ├─▶[Lambda sendmessage]─▶[DDB Query]
                                     │                        ─▶[postToConnection API]
                                     └─▶[Lambda $disconnect]──▶[DynamoDB delete]
```

- **具体例**:
  - **社内チャットアプリ(Slack ライクな MVP)**: `$connect` で `Authorization` クエリの JWT を検証 → `connectionId` を DynamoDB に `roomId#userId` で保存。誰かが `sendmessage` ルートに送信 → 同じルームの全 connectionId を Query → `postToConnection` で一斉配信。メッセージ履歴は別テーブルに書き込み、再接続時に最新 N 件を REST API で取得。
  - **株価リアルタイム配信**: バックエンドの価格更新 Lambda(Kinesis から駆動)が EventBridge 経由で push Lambda を起動 → 該当銘柄を購読している connectionId に `postToConnection` で配信。ブラウザチャートが即時更新。
  - **オンラインオークションの入札中継**: 入札 `POST /bids` を REST API で受け、DynamoDB Stream → Lambda → WebSocket に接続中の全ユーザーへ「現在価格 X 円」を push。REST と WebSocket を役割分担(書き込みは REST、通知は WS)。
  - **配車アプリのドライバー位置通知**: ドライバーアプリが 5 秒ごとに `POST /location` → DynamoDB → Stream → 乗客側の WebSocket へ push。乗客側はポーリング不要で地図上のマーカーが滑らかに動く。
- **構成要素**: APIGW WebSocket API + Lambda(`$connect` / `$disconnect` / `sendmessage` / `$default`)+ DynamoDB(connectionId 保持、TTL あり)+ **API Gateway Management API**(サーバーからの push)+ 必要に応じて DynamoDB Streams / EventBridge(書き込みトリガーの push)。
- **解決する問題**: ポーリング不要の双方向通信を、接続状態を DynamoDB に外出しすることでステートレス Lambda のまま実現。
- **落とし穴**:
  - **アイドルタイムアウト 10 分、接続上限 2 時間** — クライアント側再接続ロジック必須
  - `$disconnect` は保証されないケースがあるので TTL で孤児 connectionId を自動掃除
  - ルーム ID をパーティションキーに Query 設計(Scan にしない)
  - `postToConnection` 前に SDK の endpoint を `https://{apiId}.execute-api.{region}.amazonaws.com/{stage}` に明示設定
  - 切断済み connectionId に送ると `GoneException` — catch して DynamoDB から削除
- 参考: [Tutorial: Create a WebSocket chat app](https://docs.aws.amazon.com/apigateway/latest/developerguide/websocket-api-chat-app.html) / [Announcing WebSocket APIs in API Gateway](https://aws.amazon.com/blogs/compute/announcing-websocket-apis-in-amazon-api-gateway/)

### F. 公開 API の多層防御(CloudFront + WAF + APIGW キャッシュ + Usage Plan)

```
[Client]─▶[CloudFront]─▶[WAF]─▶[APIGW REST API (cache + usage plan)]─▶[Lambda]
```

- **具体例**:
  - **天気情報の公開 API(マネタイズ想定)**: 無料プラン 100 req/日、スタンダード 10,000 req/日、エンタープライズ無制限、を API Key + Usage Plan で実装。レスポンス本体(市区町村 × 時刻)は 10 分間ほぼ不変なので、APIGW キャッシュを 600 秒で設定し Lambda 呼び出しを 95% 以上削減。WAF の Managed Rules で典型的な攻撃を遮断、rate-based rule で同一 IP の急増を自動ブロック。
  - **為替レート API / 株価スナップショット API**: `GET /rates/USDJPY` のような GET だけで完結するデータ系。キャッシュキーに `Authorization` を含めない(全ユーザー同一レスポンス)ことでヒット率最大化。地域配信は CloudFront の edge で完結。
  - **物流追跡の公開参照 API**: 荷物番号を引数に配送状況を返す B2B API。取引先ごとに API Key を発行、Usage Plan で契約別の quota を制御、超過時は `429`。WAF で特定国からのアクセスを Geo block。
  - **ゲームのランキング取得 API**: 人気タイトルでリリース日にスパイクが予想 → CloudFront + APIGW キャッシュ 30 秒で Lambda 実行数を平準化。WAF rate-based rule で不正 bot を弾く。
- **構成要素**: CloudFront + AWS WAF(マネージドルール + rate-based)+ APIGW REST API(レスポンスキャッシュ + API Key + Usage Plan)+ Lambda。必要に応じて Route 53 Health Check / Shield Advanced。
- **解決する問題**: WAF で DDoS / SQLi / XSS を外縁で遮断、APIGW キャッシュで Lambda/DB への負荷削減、Usage Plan でテナント別の RPS・クォータを付与。CloudFront で SigV4 をオリジンリクエストに付与すれば「APIGW 直叩き」を遮断可能。
- **落とし穴**:
  - **WAF は authorizer より先に評価される** — ホワイトリスト設計が authorizer を迂回する場合がある
  - APIGW キャッシュは **時間課金**(サイズ 0.5GB〜237GB)、サイズ変更中は短時間サービス影響あり
  - **API Key は識別・スロットリング用途であって認証ではない** — 認証は Cognito/Lambda authorizer で別途
  - Edge-optimized エンドポイントは AWS 管理の CloudFront が前段にいるので、自前 CloudFront を付けるなら **Regional** を選ぶ
  - キャッシュキーに `userId` 相当を含め忘れるとユーザー A のレスポンスが B に返る(A. の典型事故)
- 参考: [Use AWS WAF to protect REST APIs in API Gateway](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-control-access-aws-waf.html) / [Protect APIs with API Gateway and perimeter protection services](https://aws.amazon.com/blogs/security/protect-apis-with-amazon-api-gateway-and-perimeter-protection-services/)

## 9. エラーハンドリングと観測性

### Lambda エラーの扱い

API Gateway が Lambda 統合でエラーを返すときの挙動([公式](https://docs.aws.amazon.com/lambda/latest/dg/services-apigateway-errors.html)):

公式ドキュメントは「**API Gateway は呼び出しエラーも関数エラーも内部エラー扱いにする。Lambda の呼び出し自体が失敗すれば 500、Lambda は動いたがエラー/不正フォーマットを返したら 502**」と整理しています。

まとめると:

| 状況 | クライアントへの応答 |
|---|---|
| Lambda 呼び出し自体が失敗(権限不足、スロットリング、関数が見つからない等) | `500 Internal Server Error` |
| Lambda は動いたが例外 / 不正フォーマットを返した | `502 Bad Gateway` |

さらに重要な点として、公式は「**API Gateway は Lambda 呼び出しを一切リトライしない。Lambda がエラーを返せば、そのままクライアントにエラー応答が返る**」と明言しています([Handling Lambda errors with an API Gateway API](https://docs.aws.amazon.com/lambda/latest/dg/services-apigateway-errors.html))。

**同期呼び出しの再試行は API Gateway 側ではしない**。クライアントに任せるか、そもそも失敗してもよい設計にします。

意味のある 4xx をクライアントに返したい場合、Lambda 関数は次のどちらかで返します。

1. proxy 統合でステータスコードを明示(v1.0 なら `statusCode` 必須、v2.0 も明示したほうが事故が減る)
2. REST API 非 proxy 統合なら、カスタムエラー形式 + `X-Amzn-ErrorType` ヘッダで API Gateway の Integration Response 設定とマッピング([公式](https://docs.aws.amazon.com/apigateway/latest/developerguide/handle-errors-in-lambda-integration.html))

### ログの 2 種類

API Gateway の CloudWatch ログは**実行ログ**と**アクセスログ**で役割が違います([公式](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-logging.html))。

- **Execution logging(実行ログ)**: API Gateway が自動で CloudWatch に吐く、リクエスト/レスポンス/マッピング処理/オーソライザ処理などの詳細。デバッグ用。認可ヘッダや API キー値は自動で redact される。
- **Access logging(アクセスログ)**: 1 リクエスト 1 行のサマリ。`$context.*` 変数を使って自分で書式を定義する。SRE / 運用用。

HTTP API のアクセスログでは、次の変数が特に有用です。

- `$context.integration.status` — Lambda proxy 統合なら Lambda 関数が返したステータス
- `$context.integrationStatus` — AWS Lambda 自体が返したステータス(関数のステータスではない)
- `$context.integrationLatency` — 統合呼び出しにかかった ms
- `$context.integrationErrorMessage` — 統合エラーのメッセージ
- `$context.requestId` — API Gateway がリクエストに割り当てた ID(トレース用)

出典: [Customize HTTP API access logs](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-logging-variables.html)

「502 が Lambda 関数内部のエラーなのか、API Gateway が関数応答を解釈できなかったのか」は `integration.status` と `integrationStatus` を分けて見ないと切り分けられません。X-Ray を有効化し、API Gateway ノードと Lambda ノードで追うのが確実です。

## 10. まとめ: コードを書く前に決める 4 つのこと

1. **REST API か HTTP API か**
   - 決定要因: API キー / 使用プラン / リクエスト検証 / WAF / Private / Edge-optimized / リソースポリシーが必要か
   - 迷ったら HTTP API
2. **Lambda 統合の形式**
   - 基本は proxy 統合
   - HTTP API なら payload format `2.0`(CLI/CFN 作成時は明示必須)
   - REST API の非 proxy 統合は「マッピングで吸収したい特別な理由」がある時だけ
3. **認可方式**
   - 既存 IdP の JWT を検証するだけ → HTTP API + JWT authorizer
   - AWS 内部呼び出し → IAM
   - 独自ロジック → Lambda authorizer(HTTP API は 10 秒 / 8 KB 制約)
4. **上限に収まるか**
   - 同期で 29/30 秒以内に返せるか(返せないなら非同期設計)
   - ペイロード 10 MB 以内か(超えるなら S3 pre-signed URL)
   - アカウント単位スロットリングを他 API と共有していて大丈夫か

この 4 点さえ先に決まっていれば、あとは Lambda の中身の話になります。逆にここが曖昧なまま proxy 統合で動かし始めると、認可方式の差し替えや REST/HTTP 移行で必ず手戻ります。

---

## 参考リンク(まとめ)

- [Choose between REST APIs and HTTP APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-vs-rest.html)
- [Lambda integrations for REST APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-integrations.html)
- [Create AWS Lambda proxy integrations for HTTP APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-lambda.html)
- [Control access to HTTP APIs with JWT authorizers](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html)
- [Control access to REST APIs using Amazon Cognito user pools](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-integrate-with-cognito.html)
- [Quotas for REST APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-execution-service-limits-table.html)
- [Quotas for HTTP APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-quotas.html)
- [Amazon API Gateway endpoints and quotas](https://docs.aws.amazon.com/general/latest/gr/apigateway.html)
- [Throttle requests to your REST APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-request-throttling.html)
- [Handling Lambda errors with an API Gateway API](https://docs.aws.amazon.com/lambda/latest/dg/services-apigateway-errors.html)
- [Handle Lambda errors in API Gateway](https://docs.aws.amazon.com/apigateway/latest/developerguide/handle-errors-in-lambda-integration.html)
- [Set up CloudWatch logging for REST APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-logging.html)
- [Customize HTTP API access logs](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-logging-variables.html)

### 責務分割 / ユースケース

- [Building Well-Architected Serverless Applications: Controlling serverless API access](https://aws.amazon.com/blogs/compute/building-well-architected-serverless-applications-controlling-serverless-api-access-part-3/)
- [Rate limiting strategies for serverless applications](https://aws.amazon.com/blogs/architecture/rate-limiting-strategies-for-serverless-applications/)
- [Enable CORS for an HTTP API](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-cors.html)
- [Enable CORS for a REST API resource](https://docs.aws.amazon.com/apigateway/latest/developerguide/how-to-cors.html)
- [Patterns for building an API to upload files to Amazon S3](https://aws.amazon.com/blogs/compute/patterns-for-building-an-api-to-upload-files-to-amazon-s3/)
- [Securing Amazon S3 presigned URLs for serverless applications](https://aws.amazon.com/blogs/compute/securing-amazon-s3-presigned-urls-for-serverless-applications/)
- [Building an API poller with AWS Step Functions and AWS Lambda](https://aws.amazon.com/blogs/compute/building-an-api-poller-with-aws-step-functions-and-aws-lambda/)
- [Tutorial: Build a CRUD HTTP API with Lambda and DynamoDB](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-dynamo-db.html)
- [Sending and receiving webhooks on AWS](https://aws.amazon.com/blogs/compute/sending-and-receiving-webhooks-on-aws-innovate-with-event-notifications/)
- [Tutorial: Create a WebSocket chat app](https://docs.aws.amazon.com/apigateway/latest/developerguide/websocket-api-chat-app.html)
- [Use AWS WAF to protect your REST APIs in API Gateway](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-control-access-aws-waf.html)
- [Protect APIs with Amazon API Gateway and perimeter protection services](https://aws.amazon.com/blogs/security/protect-apis-with-amazon-api-gateway-and-perimeter-protection-services/)
- [AWS Lambda Powertools (TypeScript)](https://docs.powertools.aws.dev/lambda/typescript/latest/)
