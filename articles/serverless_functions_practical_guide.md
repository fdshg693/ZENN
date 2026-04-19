---
title: サーバーレス関数の実践ガイド — 特徴・制約・マルチインスタンスの罠を正しく設計する
emoji: ⚡
type: tech
topics: [serverless, nextjs, vercel, typescript, architecture]
published: true
---

## はじめに — なぜ「動いているけど怖い」のか

Next.js を Vercel にデプロイすると、`app/api/hello/route.ts` にハンドラを書くだけで API が動きます。AWS Lambda でも Azure Functions でも、基本は同じ体験です。

ところがローカルでは見えなかったバグが、本番で突然顔を出します。

- あるエンドポイントが最初の 1 リクエストだけ妙に遅い
- `Map` に貯めたキャッシュが、なぜか一部のリクエストでしか効かない
- 同時リクエストが増えた途端に `too many clients already` が噴き出す
- Edge Runtime に切り替えたら `fs.readFileSync is not a function` で落ちた

これらは「実装ミス」ではなく、**サーバーレス関数の実行モデルを前提にしていない設計**から出てくる症状です。本記事では、ベンダーに依存しない一般論を軸に、実際に書くコードでどう設計を変えるべきかを整理します。

具体例は Next.js on Vercel を中心に示しますが、AWS Lambda / Azure Functions / Cloud Run Functions でも考え方はほぼ共通です。

---

## サーバーレス関数の本質 — 何を手に入れて何を手放すのか

サーバーレス関数は次の 3 つを提供します。

1. **イベント駆動** — HTTP リクエスト、キュー、スケジュール等のイベントで起動
2. **マネージドな実行環境** — OS・ランタイム・スケーリングは事業者が面倒を見る
3. **従量課金** — 実行時間や CPU 時間でのみ課金([Azure Functions overview, Microsoft Learn](https://learn.microsoft.com/en-us/archive/msdn-magazine/2019/august/azure-affairs-of-state-serverless-and-stateless-code-execution-with-azure-functions))

この 3 点を手に入れる代償として、次の 3 つの制約を受け入れます。

1. **ステートレス** — 呼び出し間でプロセスメモリに状態を保持できない
2. **短命インスタンス** — 実行環境は予告なく終了しうる
3. **実行時間上限** — 無限ループも、長時間バッチも許されない

この自動スケールとステートレス性は表裏一体です。AWS の Well-Architected Framework も、水平スケール可能にするにはワークロードをステートレスに設計する必要があると明記しています([Mitigate stateful interaction failures, AWS](https://docs.aws.amazon.com/wellarchitected/latest/framework/rel_mitigate_interaction_failure_stateless.html))。どのインスタンスがどのリクエストを処理してもよい、という性質が、裏返しとして「インスタンスに状態を持ってはいけない」を強制します。

> **一言でいうと**: サーバーレス関数はインフラ運用コストを下げる代わりに、「状態」と「長寿命プロセス」を諦める契約です。この契約を破ると、最初はたまたま動き、あとでこっそり壊れます。

---

## 実行モデル — Cold Start・Warm Start・インスタンスライフサイクル

### インスタンスは使い捨てではなく「再利用される一時容器」

サーバーレス関数のよくある誤解は「毎リクエストで新しいプロセスが立ち上がる」です。これは半分正解で半分間違いです。

AWS Lambda の公式ドキュメントは「実行環境(execution environment)は関数呼び出し後もしばらく維持され、次の呼び出しに備える」と明記しています。ただし、ランタイムのセキュリティ更新やメンテナンスのため、**数時間ごとに必ず終了させられる**とも書いています([Lambda runtime environment, AWS](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtime-environment.html))。

つまり実行環境は、

- リクエストがしばらく来ないと終了する(アイドルタイムアウト)
- デプロイで差し替わると終了する
- 事業者の都合で定期的に終了する

という **「数分から数時間のライフタイムしかない一時容器」** です。「一度立ち上がったらサーバーのように動き続ける」と仮定してはいけません。

### Cold Start で何が起きているか

実行環境が存在しない状態で最初のリクエストが来ると、次の処理が順に走ります([Conquering Cold Starts, dev.to](https://dev.to/vaib/conquering-cold-starts-strategies-for-high-performance-serverless-applications-59eg))。

1. ランタイム(Node.js, Python 等)のロード
2. 関数のコードと依存関係のダウンロード・ロード
3. **ハンドラ外のコード**(import 時評価、モジュールスコープ)の実行
4. ハンドラ本体の実行

このうち 1〜3 が Cold Start、4 だけが Warm Start です。言語・ランタイム別の傾向としては Go と Python が速く、JVM 系が遅くなりがちです([OneUptime, Fix Cold Start Issues](https://oneuptime.com/blog/post/2026-01-24-fix-cold-start-serverless-issues/view))。

`console.log` でモジュールスコープに置いた `console.time` が "1 回目だけ表示される" のはこのためです。

```typescript
// app/api/hello/route.ts
console.time('module-init');
import { OpenAI } from 'openai';
const client = new OpenAI(); // ← ここもモジュール評価時(Cold Start)に一度だけ走る
console.timeEnd('module-init');

export async function GET() {
  // ハンドラはリクエストごとに呼ばれる(Warm Start ではここだけ)
  return Response.json({ ok: true });
}
```

### 呼び出されない関数は「さらに寒い」

Vercel Functions には、呼び出されない関数を archive する挙動があり、アンアーカイブ時には通常の Cold Start に **少なくとも 1 秒追加**されると明記されています([Vercel Functions Runtimes](https://vercel.com/docs/functions/runtimes))。他のベンダーでも内部的には類似の挙動があります。

つまり「滅多に呼ばれないエンドポイント」ほど、呼ばれたときのレイテンシは悪化します。

### シャットダウンにはタイムアウトがある

Lambda の場合、インスタンス終了時に投げられる Shutdown イベントに応答できる時間は、**拡張機能なし: 0ms、内部拡張あり: 500ms、外部拡張あり: 2,000ms** で、これを超えると `SIGKILL` で強制終了されます([Lambda runtime environment, AWS](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtime-environment.html))。

「終了時にきれいに flush する」といった手癖は、サーバーレスでは成立しにくいと覚えておきます。

---

## リソース制約の「見えない壁」

サーバーレス関数には、ドキュメントに埋もれていて見落としがちな上限がいくつもあります。設計前に必ず確認します。

### 実行時間

具体例として Vercel Functions の制限を見ると、

- Node.js / Python: デフォルト 300 秒、最大 800 秒(Pro/Enterprise)
- Edge Runtime: **25 秒以内にレスポンス送信を開始**する必要があり、以降ストリーミングで最大 300 秒まで継続可能

([Vercel Functions Limits](https://vercel.com/docs/functions/limitations) / [Edge Runtime](https://vercel.com/docs/functions/runtimes/edge))

「25 秒以内に最初のバイトを返す」制約は特に重要です。LLM にリクエストを投げて待つような処理は、ストリーミング応答で早めに最初のバイトを返さないと、25 秒を超えた瞬間にタイムアウトします。

### メモリと CPU

Vercel Functions は Hobby で 2 GB / 1 vCPU 固定、Pro/Enterprise で最大 4 GB / 2 vCPU まで設定可能です([Vercel Functions Limits](https://vercel.com/docs/functions/limitations))。多くのサーバーレス環境で CPU はメモリにリニアに連動します。**「遅いから CPU を増やしたい → 実質メモリを増やす」**という操作になるので、性能チューニングではメモリ設定を動かします。AWS は [Lambda Power Tuning](https://dev.to/vaib/conquering-cold-starts-strategies-for-high-performance-serverless-applications-59eg) で最適値を探ることを推奨しています。

### ファイルディスクリプタ

見落とされがちですが強力な制約です。Vercel Functions では、**同時実行すべてで共有して 1,024 本**の FD 上限があり、ランタイム自身の消費も含むため実際は厳密にそれ以下になります([Vercel Functions Limits](https://vercel.com/docs/functions/limitations))。

FD は以下で消費されます。

- 開いているファイル
- TCP ソケット、HTTP コネクション
- DB コネクション
- ファイルシステム操作

同時 100 リクエスト × 1 リクエストあたり 5 つの外部接続 = 500 FD、という計算は軽く超えます。「接続は使ったら必ず閉じる」「プーリングする」は努力目標ではなく、**上限を守るための必須要件**です。

### バンドルサイズ

- Node.js 関数: 非圧縮 **250 MB**(AWS 由来の上限)
- Python 関数: 非圧縮 500 MB
- Edge Runtime: gzip 後 **1 MB(Hobby) / 2 MB(Pro) / 4 MB(Enterprise)**

([Vercel Functions Limits](https://vercel.com/docs/functions/limitations) / [Edge Runtime](https://vercel.com/docs/functions/runtimes/edge))

通常の Node.js 関数でも `node_modules` を全部詰めると簡単に肥大化します。ML モデル(数百 MB)はバンドルに入れず、S3/Blob などからストリームで読み込む方針になります。

### ephemeral storage (`/tmp`)

AWS Lambda は `/tmp` を最大 **10,240 MB** まで設定可能です([Lambda configuration-ephemeral-storage, AWS](https://docs.aws.amazon.com/lambda/latest/dg/configuration-ephemeral-storage.html))。ただしこれは「同じ実行環境にだけ存在する一時領域」であって、**別インスタンスから見えないし、終了時に消えます**。キャッシュとしての利用は「運が良ければ残っている」程度の信頼度しかない、という扱いにします。

---

## ステートレス × マルチインスタンスの罠

### 「同じ関数 = 同じプロセス」ではない

次の 2 つのリクエストは、たいていの場合 **別のインスタンス** に振られます。

```
Request A  ─▶ Instance #1 (メモリ空間 A)
Request B  ─▶ Instance #2 (メモリ空間 B)
```

つまり、モジュールスコープに置いた `Map` や `LRUCache` は、**そのインスタンスにヒットしたリクエストに対してだけ効く**「偶然のキャッシュ」にしかなりません。

```typescript
// ❌ これは分散キャッシュにはならない
const sessionCache = new Map<string, Session>();

export async function GET(req: Request) {
  const sid = getCookie(req, 'sid');
  const cached = sessionCache.get(sid); // Instance #1 でセットしても #2 では miss
  // ...
}
```

さらに厄介なのは、「運良く同じインスタンスに当たると動いてしまう」ためローカルや低トラフィック環境では気付きにくいことです。同時実行が増えた瞬間、複数インスタンスに散らばり、整合性が破綻します。

### インスタンスはいつ消えてもよい

前章で見たとおり、インスタンスは数分から数時間で終了します。つまりモジュールスコープに貯めたデータは、

- 別インスタンスからは見えない
- 再デプロイで消える
- アイドルタイムアウトで消える
- 事業者の都合で消える

このため、「**あってもなくても動く**」扱いにできるキャッシュ以外は、in-memory に置いてはいけません。

### 許容される in-memory 利用

逆に、次のような用途はモジュールスコープを積極的に使うべきです。

- **起動時にしか変わらない設定値**(環境変数を parse した結果など)
- **1 リクエスト内で memoize したい計算結果**
- **SDK クライアントや DB プール**(Cold Start 1 回分のコストを複数リクエストで償却するため)

「プロセス内でずっと使い回す」のは OK、「**プロセスをまたいで共有される前提**」は NG、と線を引きます。

---

## データベース接続 — サーバーレス最大級のハマりどころ

### なぜ接続が爆発するか

同時実行 N の関数が各自 DB にコネクションを張ると、単純に N 本の接続が DB に飛びます。PostgreSQL の `max_connections` はデフォルト数百本、Aurora Serverless v2 でも ACU に応じて 3,000〜4,000 程度です([Aurora Serverless v2 setting capacity, AWS](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2.setting-capacity.html))。

サーバーレスの同時実行は容易に数百〜数千に達するので、そのまま接続を張ると:

```
FATAL: sorry, too many clients already
```

というエラーが噴き出します([Aurora MySQL troubleshooting DB connections](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/mysql-troubleshooting-dbconn.html))。

新規接続のコストも無視できません。TLS/SSL ハンドシェイク・認証・機能ネゴシエーションで CPU を食い、同時接続数に比例してメモリも消費します([RDS Proxy howitworks, AWS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy.howitworks.html))。

### 解決策 A: コネクションプールを関数の外側に置く

古典的な解決策は、関数と DB の**間に**コネクションプール役を挟むことです。

- **Amazon RDS Proxy**: フルマネージド、transaction-level の multiplexing([RDS Proxy, AWS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy.html))
- **PgBouncer**: OSS の PostgreSQL 用 pooler。代表的な設定値は `default_pool_size=20`, `max_client_conn=100`, `server_lifetime=3600秒`, `server_idle_timeout=600秒`([PgBouncer parameters, PlanetScale docs](https://planetscale.com/docs/postgres/connecting/pgbouncer))

関数側からは通常の接続文字列で繋ぐだけで済み、プロキシが実際の DB への接続を再利用してくれます。即時処理できない接続要求はキューイング/スロットリングされ、上限超過時は load shedding で拒否されます([RDS Proxy howitworks, AWS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy.howitworks.html))。

### 解決策 B: HTTP/WebSocket ベースのサーバーレスドライバー

最近のマネージド DB は、サーバーレス関数から直接叩ける HTTP ベースのドライバーを提供します。代表例が Neon の `@neondatabase/serverless` で、PlanetScale Postgres なども互換です([Neon serverless driver, PlanetScale docs](https://planetscale.com/docs/postgres/connecting/neon-serverless-driver))。

```typescript
// Next.js Route Handler (Node.js runtime / Edge runtime どちらでも動く)
import { neon } from '@neondatabase/serverless';

const sql = neon(process.env.DATABASE_URL!);

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const postId = searchParams.get('id');

  const rows = await sql`SELECT * FROM posts WHERE id = ${postId}`;
  return Response.json(rows);
}
```

Neon ドライバーは HTTP モードと WebSocket モードを使い分けます。

| 用途 | モード |
| --- | --- |
| 単発クエリ | HTTP |
| 非対話トランザクション(クエリのバッチ) | HTTP |
| 対話トランザクション(BEGIN 〜 COMMIT を跨ぐ) | WebSocket |
| セッション機能 | WebSocket |
| `node-postgres` 互換 | WebSocket |

([PlanetScale docs, Neon driver](https://planetscale.com/docs/postgres/connecting/neon-serverless-driver))

HTTP モードは毎リクエストがステートレスな HTTP コールなので、サーバーレスの特性と相性が良好です。対話トランザクションが必要なら WebSocket を使いますが、「1 リクエスト = 1 トランザクション」を徹底できるなら HTTP で十分です。

### どちらを選ぶか

- DB が RDS / Aurora / 通常の PostgreSQL → **RDS Proxy / PgBouncer**
- DB が Neon / PlanetScale 等のサーバーレス DB、または Edge Runtime から直接叩きたい → **サーバーレスドライバー**
- ORM(Prisma, Drizzle 等)を使う場合は、それぞれのドライバーアダプタ対応を確認する

---

## エッジ配信 / Edge Runtime の特性と制約

「エッジ配信」とは、コードをユーザー最寄りのデータセンターで実行して物理距離分の RTT を削る手法です。Vercel の場合、従来のサーバーレス関数(MicroVM 上の Node.js)ではなく、**Chrome の V8 エンジン上で直接 JavaScript を走らせる Edge Runtime** を使うことで、MicroVM 起動のオーバーヘッドを削り、Cold Start をミリ秒オーダーにしています([Vercel Edge Functions, blog](https://vercel.com/blog/edge-functions-generally-available))。

### 使えない/使えるもの

Edge Runtime は Node.js のフルセットではなく、**ブラウザ API + Node.js API のサブセット**を提供します。Vercel 公式ドキュメントが明記している制約:

- ファイルシステムの読み書き不可(`fs` モジュール不可)
- `require` 直接呼び出し不可 — `import` を使う
- **ES Modules 必須**。フレームワークを使わない場合、`package.json` に `"type": "module"` を追加するか拡張子を `.mjs` に変更
- `node_modules` は使えるが、ES Modules 実装かつ native Node.js API を使わないもののみ
- `eval` / `new Function()` / `WebAssembly.compile` / `WebAssembly.instantiate`(buffer ベース)は**セキュリティ上の理由で禁止**

([Edge Runtime unsupported APIs, Vercel](https://vercel.com/docs/functions/runtimes/edge))

使えるもの:

- `fetch`, `Request`, `Response`, `Headers`
- Web Streams API
- `process.env`(環境変数アクセス)
- `crypto`(Web Crypto API)

古くから使われている Node.js 専用ライブラリ(たとえば `fs` を使う PDF 生成ライブラリや、native アドオンを含む画像処理)は動きません。Edge Runtime は「書き直し前提で選ぶ」環境です。

### データとの距離問題

エッジは関数を地理分散しますが、**データは分散していない**のが普通です。たとえばユーザーがヨーロッパ、関数がヨーロッパ、DB が米国東部にあるケースでは、関数 → DB の往復レイテンシが往復で数十〜数百 ms 追加され、結局エッジのメリットが打ち消されます。

Vercel 自身が「regional execution of Edge Functions」を導入し、関数をデータ近くに寄せる機能を提供していることからも分かるように、**「とにかくエッジに置く」は正解ではない**というのが現場の結論です([Regional execution for ultra-low latency, Vercel blog](https://vercel.com/blog/regional-execution-for-ultra-low-latency-rendering-at-the-edge))。

### Vercel は Edge Functions を非推奨化している

補足として、Vercel のスタンドアロン Edge Functions は現在非推奨扱いで、Node.js runtime の Vercel Functions(Fluid compute / Active CPU 課金)への移行が推奨されています([Edge Functions deprecated, Vercel](https://vercel.com/docs/functions/runtimes/edge/edge-functions.rsc))。Next.js の Middleware の edge runtime は引き続きサポート対象です。

これを一般化すると、「エッジで動かす」は **目的(低レイテンシ応答・地理的近接処理)を満たす手段の一つに過ぎず、常に正しい選択ではない** ということです。ミドルウェア的な前処理(認証・A/B テスト・リダイレクト)や、キャッシュしやすい軽い API だけをエッジに置き、ビジネスロジックは Node.js runtime に留める、という切り分けが現実的です。

Next.js での切り替え自体は 1 行です。

```typescript
// app/api/geo/route.ts
export const runtime = 'edge'; // デフォルトは 'nodejs'

export function GET(request: Request) {
  return new Response(`I am an Edge Function!`);
}
```

([Edge Runtime, Vercel](https://vercel.com/docs/functions/runtimes/edge))

---

## 実践設計パターン

ここまでの制約を踏まえると、「やるべき設計」はほぼ次の形に収束します。

### 1. ハンドラ**外**で初期化する

SDK クライアント、DB プール、設定の parse 結果はモジュールスコープに置き、**Cold Start 1 回分のコストを Warm Start 全体で償却**します。AWS 公式も「SDK クライアントと DB 接続はハンドラ外で初期化する」ことを明示的に推奨しています([Conquering Cold Starts, dev.to](https://dev.to/vaib/conquering-cold-starts-strategies-for-high-performance-serverless-applications-59eg))。

```typescript
// ✅ モジュールスコープ = Cold Start 時に 1 回だけ
import { OpenAI } from 'openai';
import { neon } from '@neondatabase/serverless';

const openai = new OpenAI();
const sql = neon(process.env.DATABASE_URL!);

export async function POST(req: Request) {
  const { prompt } = await req.json();
  // 毎リクエストはここだけ
  const completion = await openai.chat.completions.create({ /* ... */ });
  await sql`INSERT INTO logs(prompt) VALUES(${prompt})`;
  return Response.json(completion);
}
```

### 2. Keep-Alive を明示的に有効化する

サーバーレス関数は短命ですが、1 インスタンス内では HTTP 接続を再利用したほうが良い。Node.js 18+ の undici(グローバル `fetch`)はデフォルト Keep-Alive ですが、AWS SDK v3 などでは明示設定が推奨されます([OneUptime, Cold Start](https://oneuptime.com/blog/post/2026-01-24-fix-cold-start-serverless-issues/view))。

```typescript
import https from 'https';
import { NodeHttpHandler } from '@aws-sdk/node-http-handler';
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';

const httpHandler = new NodeHttpHandler({
  httpsAgent: new https.Agent({ keepAlive: true, maxSockets: 50 }),
});
const dynamo = new DynamoDBClient({ requestHandler: httpHandler });
```

### 3. Lazy loading で初期化を軽くする

Cold Start で評価されるモジュールスコープは小さく保ちます。重い依存はハンドラ内で必要になったタイミングで動的 import します。

```typescript
export async function POST(req: Request) {
  if ((await req.json()).action === 'generate-pdf') {
    const { generatePdf } = await import('./heavy/pdf'); // 必要時だけロード
    return generatePdf();
  }
  return Response.json({ ok: true });
}
```

### 4. 関数を小さく保つ

Single Responsibility Principle に従って 1 関数 1 責務にすると、デプロイバンドルが小さくなり Cold Start が速くなります([Reducing cold start, Medium](https://hervekhg.medium.com/reducing-cold-start-in-serverless-functions-5-essential-tips-3d9522707e97))。Next.js on Vercel は、動的コードを可能な限り少ない Vercel Functions にまとめて Cold Start を減らす戦略なので、これは「フレームワーク側に任せる」判断もできます([Vercel Runtimes](https://vercel.com/docs/functions/runtimes))。

### 5. 状態を外部化する

in-memory に置けないものを、用途に応じて適切な外部ストアに置きます。

| 状態 | 置き場所の例 |
| --- | --- |
| セッション | Redis / Upstash / KV、または JWT を Cookie に格納 |
| ユーザー設定 | RDB / KV |
| 一時ジョブ状態 | DynamoDB / Cosmos DB |
| 連鎖ワークフロー | イベントペイロード自体に状態を埋め込む |
| 大きなファイル | S3 / Azure Blob(必要なら `/tmp` に一時 DL) |

AWS の解説でも「外部ストレージパターン」「Storage-First パターン」として体系化されています([Resilient serverless state management, awsforengineers](https://awsforengineers.com/blog/5-patterns-for-resilient-serverless-state-management/))。

### 6. 冪等性を前提にする

サーバーレスのイベントソース(SQS, Pub/Sub など)は at-least-once が基本なので、**同じイベントが 2 回届いても結果が同じ**になるよう設計します。典型的にはイベントに `idempotency_key` を持たせ、DynamoDB や Redis に「処理済みマーカー」を conditional write で入れる方式です。

### 7. Cold Start 対策は「本当に必要か」を先に問う

Keep-warm cron や Provisioned Concurrency は効果的ですが、**常時起動ぶんのコスト**が戻ってきます。低トラフィックなエンドポイントでは、そもそも Cold Start を許容する設計(ヘルスチェック除外、非同期化、ユーザーに進捗表示)のほうが適切なこともあります。

### 8. リソースをクローズする

ファイル・HTTP・DB 接続は使い終わったら閉じる。前述の FD 1,024 本制約を守るためです。

```typescript
export async function GET() {
  const file = await fs.open('/tmp/data.bin', 'r');
  try {
    // ...
  } finally {
    await file.close(); // try/finally でクローズ漏れを防ぐ
  }
}
```

---

## 本番前チェックリスト

デプロイ前に最低限見直したい 10 項目です。

1. ☐ **実行時間とメモリの上限を採用プランで把握している**(Vercel Edge の 25 秒制約、ストリーミング要件を含む)
2. ☐ **モジュールスコープでの初期化**になっており、ハンドラ内で毎回クライアントを new していない
3. ☐ **in-memory キャッシュは「あってもなくても正しく動く」扱い**にしている(整合性を in-memory に依存していない)
4. ☐ **DB 接続はプロキシ(RDS Proxy / PgBouncer)またはサーバーレスドライバー経由**になっている
5. ☐ **ファイル・HTTP・DB の接続をクローズするコード**が揃っている(try/finally、`using` 構文、Keep-Alive 設定)
6. ☐ **Cold Start の最悪値を計測**している(ログ/メトリクスで識別できる)
7. ☐ **冪等性**を担保している(再試行されても壊れない)
8. ☐ Edge Runtime を使うなら、**禁止 API(fs, eval, new Function, 動的 require 等)に依存していない**
9. ☐ **`/tmp` 等 ephemeral storage への依存**が「消えても正しく動く」範囲に収まっている
10. ☐ **可観測性**: Cold Start か Warm か、インスタンス ID、メモリ/時間使用量を追えるログ・メトリクスが出ている

---

## おわりに

サーバーレス関数は「インフラを忘れてコードだけ書ける魔法」と紹介されがちですが、実態は **「制約を前提に作られた分散システムの 1 ノード」** です。

- インスタンスは短命で、いつ消えてもよい
- 同じ関数でも、別のリクエストは別プロセスで走る
- メモリ・FD・時間の上限は、設計を強制する

この契約をコードに織り込めば、サーバー運用より**むしろ**安定します。ステートレスと単一責務を強制されるおかげで、スケールアウトも障害復旧も自動で成立するからです。

逆に、従来のサーバーの延長で書こうとすると、たまたま動くが本番で崩れるコードが生まれます。本記事のチェックリストは、その「たまたま」を無くすための地味な手癖集だと思ってもらえれば幸いです。

---

## 参考資料

- [Azure Functions and stateless code execution, Microsoft Learn](https://learn.microsoft.com/en-us/archive/msdn-magazine/2019/august/azure-affairs-of-state-serverless-and-stateless-code-execution-with-azure-functions)
- [Lambda runtime environment, AWS](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtime-environment.html)
- [Lambda configuration-ephemeral-storage, AWS](https://docs.aws.amazon.com/lambda/latest/dg/configuration-ephemeral-storage.html)
- [Mitigate stateful interaction failures, AWS Well-Architected](https://docs.aws.amazon.com/wellarchitected/latest/framework/rel_mitigate_interaction_failure_stateless.html)
- [RDS Proxy, AWS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy.html)
- [RDS Proxy how it works, AWS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy.howitworks.html)
- [Aurora Serverless v2 setting capacity, AWS](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/aurora-serverless-v2.setting-capacity.html)
- [Vercel Functions Limits](https://vercel.com/docs/functions/limitations)
- [Vercel Functions Runtimes](https://vercel.com/docs/functions/runtimes)
- [Vercel Edge Runtime](https://vercel.com/docs/functions/runtimes/edge)
- [Vercel Edge Functions generally available](https://vercel.com/blog/edge-functions-generally-available)
- [Regional execution for ultra-low latency, Vercel](https://vercel.com/blog/regional-execution-for-ultra-low-latency-rendering-at-the-edge)
- [Neon serverless driver, PlanetScale docs](https://planetscale.com/docs/postgres/connecting/neon-serverless-driver)
- [PgBouncer, PlanetScale docs](https://planetscale.com/docs/postgres/connecting/pgbouncer)
- [Conquering Cold Starts, dev.to](https://dev.to/vaib/conquering-cold-starts-strategies-for-high-performance-serverless-applications-59eg)
- [Fix Cold Start Serverless Issues, OneUptime](https://oneuptime.com/blog/post/2026-01-24-fix-cold-start-serverless-issues/view)
- [Resilient serverless state management, awsforengineers](https://awsforengineers.com/blog/5-patterns-for-resilient-serverless-state-management/)
