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

API Gateway には RESTful API を作る口が 2 つあります。

> REST APIs and HTTP APIs are both RESTful API products. REST APIs support more features than HTTP APIs, while HTTP APIs are designed with minimal features so that they can be offered at a lower price.
> — [Choose between REST APIs and HTTP APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-vs-rest.html)

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

> HTTP APIs are optimized for building APIs that proxy to AWS Lambda functions or HTTP backends, making them ideal for serverless workloads. HTTP APIs are a cheaper and faster alternative to REST APIs, but they do not currently support API management functionality.
> — [API Gateway FAQs](https://aws.amazon.com/api-gateway/faqs/)

**迷ったら HTTP API を起点にし、必要機能が増えてきたら REST API に切り替える**、で十分です。移行の手戻りが嫌なら最初から REST API を選んでも機能面で困ることはありません。

## 3. Lambda 統合の 4 パターンと payload format

API 種別を決めたら、Lambda との統合方法を決めます。

### パターン

- REST API
  - **Lambda proxy 統合**: HTTP リクエスト丸ごとを event オブジェクトとして Lambda に渡す。最も簡単で、ほぼこれを選ぶ。
  - **Lambda 非 proxy(カスタム)統合**: マッピングテンプレート(VTL)でリクエスト/レスポンスを変換。既存 Lambda のシグネチャを API 側で吸収したい場合など、限定的に使う。
- HTTP API
  - **Lambda proxy 統合のみ**。非 proxy は存在しない。

> In Lambda proxy integration, the required setup is simple. Set the integration's HTTP method to POST, the integration endpoint URI to the ARN of the Lambda function invocation action of a specific Lambda function, and grant API Gateway permission to call the Lambda function on your behalf. In Lambda non-proxy integration, in addition to the proxy integration setup steps, you also specify how the incoming request data is mapped to the integration request and how the resulting integration response data is mapped to the method response.
> — [Lambda integrations for REST APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-integrations.html)

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

JWT authorizer を使うと、検証済みの claims が Lambda 統合の event で読めます。

> After validating the JWT, API Gateway passes the claims in the token to the API route's integration. Backend resources, such as Lambda functions, can access the JWT claims. For example, if the JWT includes an identity claim `emailID`, it's available to a Lambda integration in `$event.requestContext.authorizer.jwt.claims.emailID`.
> — [Control access to HTTP APIs with JWT authorizers](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html)

「Cognito を使いたい」「OIDC IdP を使いたい」という要件がほとんどのケースでは、HTTP API + JWT authorizer が手数最小になります。

## 5. 設計で踏みやすい制約

次の値は**設計前に**把握しておきます。いずれも公式 Docs 由来。

### タイムアウト

- **REST API 統合タイムアウト**: `50 ms 〜 29 s`(Regional / Edge-optimized / Private すべて同じ)。Regional と Private については**引き上げ申請可能**。ただし、
  > You can raise the integration timeout to greater than 29 seconds, but this might require a reduction in your Region-level throttle quota for your account.
  > — [REST API quotas](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-execution-service-limits-table.html)
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

## 6. エラーハンドリングと観測性

### Lambda エラーの扱い

API Gateway が Lambda 統合でエラーを返すときの挙動([公式](https://docs.aws.amazon.com/lambda/latest/dg/services-apigateway-errors.html)):

> API Gateway treats all invocation and function errors as internal errors. If the Lambda API rejects the invocation request, API Gateway returns a 500 error code. If the function runs but returns an error, or returns a response in the wrong format, API Gateway returns a 502.

まとめると:

| 状況 | クライアントへの応答 |
|---|---|
| Lambda 呼び出し自体が失敗(権限不足、スロットリング、関数が見つからない等) | `500 Internal Server Error` |
| Lambda は動いたが例外 / 不正フォーマットを返した | `502 Bad Gateway` |

さらに重要:

> API Gateway does not retry any Lambda invocations. If Lambda returns an error, API Gateway returns an error response to the client.
> — [Handling Lambda errors with an API Gateway API](https://docs.aws.amazon.com/lambda/latest/dg/services-apigateway-errors.html)

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

## 7. まとめ: コードを書く前に決める 4 つのこと

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
