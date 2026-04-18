---
title: "Azure Cosmos DB 実戦ガイド — Document型 NoSQL を Azure でどう設計するか"
emoji: "🪐"
type: "tech"
topics: ["cosmosdb", "azure", "nosql", "document", "architecture"]
published: true
---

# はじめに — 「NoSQL を整理した」次の一歩

先行記事 [NoSQL をもう一度ちゃんと整理する](https://zenn.dev/) では、NoSQL を SQL との対比で整理しました。本記事はその続編として、Azure 上で NoSQL を実際に選ぶ段階に入ったときに必ず候補に挙がる **Azure Cosmos DB** に焦点を当てます。

よくある誤解は「Cosmos DB = 速いマネージド MongoDB / Document DB」です。これは半分正しく、半分危険です。実際には、Cosmos DB の設計判断は次の **4 軸** で決まります。

- **API 選択**(NoSQL / MongoDB / Cassandra / Gremlin / Table / PostgreSQL)
- **RU (Request Unit) モデル**(Provisioned / Autoscale / Serverless)
- **一貫性レベル**(5 段階)
- **パーティションキー**(論理 20GB / 10,000 RU/s の壁)

この 4 軸のどれを外しても、**RU 爆発 / ホットパーティション / 書き込み失敗 / コスト暴発** のいずれかに刺さります。本記事では、この 4 軸を深掘りしたうえで、Change Feed、Synapse Link、Vector 検索といった Azure ネイティブの構成パターンと、Event Sourcing / CQRS / Transactional Outbox / Materialized View といった設計パターンの勘所まで扱います。

本記事のスタンスは先行記事と同じく、**「できること」より「向いていないこと・壊れ方」を優先して書く** です。

# Cosmos DB の全体像 — 1 つのエンジン、複数の API

Cosmos DB は Microsoft が「Unified AI Database」と位置付けるマネージド分散 DB で、単一のエンジン上に **6 つの API** が載る構造になっています。

| API | データモデル | 主な用途 | 選ぶ場面 |
|---|---|---|---|
| **NoSQL (SQL)** | Document (JSON) | グリーンフィールド Document | SQL ライクなクエリが書ければよい、最新機能がまず載る |
| **MongoDB RU** | Document | MongoDB 資産の移行、RU モデルと相性よし | wire protocol 互換で既存ドライバをそのまま |
| **MongoDB vCore** | Document | MongoDB 完全互換、vCore 課金 | MongoDB のクエリ機能を可能な限り維持したい |
| **Cassandra** | Wide-Column | 時系列・大量書き込み | 既存 Cassandra ワークロードの移行 |
| **PostgreSQL** | Relational | 分散 RDBMS | Postgres 互換 + 水平スケールが要る |
| **Table** | Key-Value (+属性) | Azure Table Storage の高機能版 | Azure Table の既存資産をグローバル化 |
| **Gremlin** | Graph | 関係の探索 | SNS / 推薦 / 権限グラフ |

本記事は NoSQL API(Document 型)を中心に扱います。

基礎的な約束事として押さえておくと良いのは次の 2 つです。

- **可用性 SLA 99.999%**(複数リージョン構成時)
- **読み書きレイテンシ p99 < 10ms** をグローバルで保証

この数字は「マルチリージョンを正しく組めば」達成される値であり、シングルリージョン + Strong 一貫性のような構成ではこの限りではありません。

> 根拠: [Cosmos DB Overview](https://learn.microsoft.com/en-us/azure/cosmos-db/overview), [Choose an API](https://learn.microsoft.com/en-us/azure/cosmos-db/choose-api), [Distribute Data Globally](https://learn.microsoft.com/en-us/azure/cosmos-db/distribute-data-globally)

# リソース階層とスループットの持ち方 — パーティションキーの前に決めること

Cosmos DB の設計はパーティションキーから語られがちですが、その前に **リソース階層** と **スループットの持ち方** を決める必要があります。この上位の視点を抜かすと、「コンテナを無闇に増やす」「Database 共有 RU を使わずコストが跳ねる」という失敗に繋がります。

## 4 階層のリソース構造

```
Account
  └── Database
        └── Container
              └── Item (JSON)
```

- **Account**: リージョン、API、バックアップポリシーなどアカウント全体の設定境界。Azure のリソース 1 つに対応。
- **Database**: Container をまとめる論理グループ。**スループットを共有できる単位**。
- **Container**: **パーティションキー / インデックスポリシー / 一貫性 / TTL / Stored Procedure の境界**。後述のとおり RDBMS のテーブルとは同一視しないほうが安全です。
- **Item**: 個々の JSON ドキュメント。

## Container は "テーブル" ではない

RDBMS 出身だと「エンティティごとに container」と考えがちですが、Cosmos DB の container は **スループット・索引・パーティションキーをまとめて決める "箱"** です。container をまたいだ JOIN もトランザクションもありません。**一緒に読み書きするデータは、異なるエンティティでも同じ container に寄せる** のが基本姿勢です(後述の Event Sourcing や CQRS でもこの発想が効きます)。

## スループットは Database 共有 RU か Container 専有 RU か

| モード | 特徴 | 向く構成 |
|---|---|---|
| **Database 共有 RU** | 配下の複数 container でプール共有。**最大 25 コンテナまで** | 小さな container が多い、テナント別 container など |
| **Container 専有 RU** | container ごとに独立した RU/s | パフォーマンス予測性・分離性が要る本番 container |
| **Hybrid** | 同じ Database 内で共有 + 一部の container だけ専有 | 主要 container は専有、補助は共有、という現実解 |

**コスト面では、小さな container が多い構成ほど Database 共有 RU が効きます**。container 専有だと最低 400 RU/s × container 数 の基礎コストが発生しますが、Database 共有ならプール内で融通できます。

一方、**本番の主要ワークロード** は基本的に container 専有にします。共有だと隣の container の暴走に引きずられるためです。

## マルチテナントのリソースモデル

公式ドキュメントが示す典型の 2 モデルです。

- **Partition key per tenant**: 1 container の中で `tenantId` を partition key にし、全テナントを同居させる。**小〜中規模の B2C** で定番。コストが線形に伸び、テナント追加が軽い
- **Database account per tenant**: テナントごとに account / database を分ける。**大テナント、厳格な分離、カスタム SLA** が要る場合。管理コストは増える

「1 container にテナントを詰める」のは初期は楽ですが、大きなテナントが 20GB / 10,000 RU/s の論理パーティション上限に刺さると機能停止します。後述の階層パーティションキーと組み合わせて設計します。

> 根拠: [Set Throughput on Database and Container](https://learn.microsoft.com/en-us/azure/cosmos-db/set-throughput), [Optimize Cost with Throughput](https://learn.microsoft.com/en-us/azure/cosmos-db/optimize-cost-throughput), [Serverless multi-tenant models](https://learn.microsoft.com/en-us/azure/cosmos-db/serverless)

# Document 型 NoSQL を深掘る — Cosmos DB で見る本質

先行記事では Document 型を「JSON を保存し、"一緒に読むもの"をまとめる」と紹介しました。ここではもう一歩踏み込み、Cosmos DB を題材に **Document 型 NoSQL の強みと痛点** を具体化します。

## JSON モデルとハードリミット

Cosmos DB NoSQL API の 1 item は JSON です。ネストや属性数に明示的な上限はありませんが、**UTF-8 エンコード後のサイズで最大 2MB** という厳格なハードリミットがあります(MongoDB API のみ 16MB)。

この 2MB は「気にしなくていい」レベルではありません。次のような設計は簡単に上限に刺さります。

- 投稿に対する全コメントを埋め込む
- センサーデータの全履歴を 1 デバイスに蓄積する
- ユーザーの全アクティビティログを 1 ドキュメントに追記する

埋め込みの罠は先行記事で触れましたが、Cosmos DB ではこれが**書き込み失敗としてアプリに跳ね返る**点が厳しいです。上限に近づいた時点で RU コストとレプリケーション負荷も悪化します。

他のハードリミットも覚えておきます。

- **パーティションキー値の長さ: 2,048 バイト**(大きなパーティションキーが無効の場合は 101 バイト)
- **ID 値の長さ: 1,023 バイト**

> 根拠: [concepts-limits](https://learn.microsoft.com/en-us/azure/cosmos-db/concepts-limits)

## Cosmos DB の "キー" を整理する

「キー」という言葉は Cosmos DB の中でも複数の意味で使われます。パーティションキーを深掘る前に整理します。

| キー | 役割 | 一意性の範囲 | 後から変更 |
|---|---|---|---|
| **`id`** | アプリが付ける識別子。必須プロパティ | **同一論理パーティション内で一意** | 不可(= 再作成) |
| **Partition Key** | 論理パーティションを決める。`/userId` のようにパス指定 | container 全体の物理配置を決める | 実質不可(container 再作成) |
| **Unique Keys** | `email` などに一意制約を張る任意機能 | **同一論理パーティション内** | container 作成時のみ指定可能 |
| **`_etag`** | 楽観的同時実行制御(OCC)用 | item ごと、更新で変わる | システム管理 |
| **`_ts`** | 最終更新の Unix 時刻(秒) | item ごと | システム管理 |
| **`_rid` / `_self`** | 内部用リソース ID。アプリ依存禁止 | — | システム管理 |

特に混乱しやすい 2 点を明示します。

- **item の物理的な一意性は `(partitionKey, id)` の組** です。`id` だけでは container 全体では一意性を保証しません。別パーティションなら同じ `id` を持てます
- **Unique Keys も同一論理パーティション内が対象**です。「container 全体で email を一意に」という制約は張れません。グローバルな一意性が要るなら、アプリ側でユニークチェック用の別 item(id = email)を先に書く、といった工夫が必要です

`_etag` を使った楽観的同時実行制御は、RDBMS の `UPDATE ... WHERE version = ?` と同じ発想です。`If-Match: <_etag>` ヘッダ付きで更新し、他者が先に更新していれば **HTTP 412 Precondition Failed** が返ります。「気付かずに上書きした」事故を防ぐ標準パターンです。

> 根拠: [FAQ (ETag / OCC)](https://learn.microsoft.com/en-us/azure/cosmos-db/faq), [Model Partition Example](https://learn.microsoft.com/en-us/azure/cosmos-db/nosql/model-partition-example)

## パーティションキーとは何か

パーティションキーは Cosmos DB 設計の中核なので、ここで概念を明示します。

- **論理パーティション = 同一パーティションキー値を持つ item の集合**。物理的にも 1 台のノードに寄ります
- **役割は 3 つ**:
  - **水平スケール**: ノードを足すとパーティションを振り直して分散する
  - **トランザクション境界**: **同一論理パーティション内でのみ** transactional batch や stored procedure の原子性が保証される
  - **クエリ効率**: WHERE にパーティションキーが含まれると、1 物理パーティションへの問い合わせで済む
- **RDBMS のプライマリキーとは目的が違う**: RDBMS のキーは「一意制約 + 索引」が主目的、Cosmos のパーティションキーは **物理配置の決定** が主目的
- **事実上変更不可**: 変えるには container を再作成してデータ移行する

この性質から、**アクセスパターン(何を WHERE 句に載せて読み、どこで原子更新を欲しがるか)が決まっていない段階ではパーティションキーを決められません**。先行記事のとおり、NoSQL でアクセスパターン駆動設計が必須な最大の理由はここにあります。

物理的な上限は後の章で扱いますが、キー単位で **20GB / 10,000 RU/s** の壁がある、という事実だけ先に押さえておきます。

## ポイントリードと WHERE クエリ — 見た目が同じでも RU は違う

Cosmos DB では、同じ item を取るのに **2 つの経路** があります。ここを誤解すると、同じ処理なのに RU が数倍違う、という事態になります。

### 経路 1: ポイントリード

SDK の **専用 API** に `id` と `partitionKey` を渡して取ります。クエリエンジンを通らず、ルーティング層で直接 item に到達します。

```csharp
// .NET SDK (NoSQL API)
ItemResponse<Order> res = await container.ReadItemAsync<Order>(
    id: "order_001",
    partitionKey: new PartitionKey("cust_123")
);
```

```python
# Python SDK
item = container.read_item(item="order_001", partition_key="cust_123")
```

REST では `GET /dbs/{db}/colls/{c}/docs/{id}` にパーティションキーヘッダを付ける素朴な形です。

### 経路 2: WHERE 句で id を指定するクエリ

同じ item を取る見た目のコードでも、`QueryItems` / `query_items` 経由はクエリエンジン通過扱いで、**ポイントリードとしては認識されない** ことを Cosmos DB 公式が明記しています。

```sql
SELECT * FROM c WHERE c.id = "order_001"
```

### RU の違い(公式コミュニティの実測値)

| 操作 | 小さな item | 大きな item |
|---|---|---|
| **Point read** | **1.05 RU** | **4.76 RU** |
| `SELECT * FROM c WHERE c.id = 'x'` | 2.85 RU | 3.88 RU |
| `SELECT * FROM c`(スキャン) | 3.21 RU | 3.21 RU |

小さな item では **ポイントリードが 1.05 RU、同等の WHERE クエリは 2.85 RU**。約 **2.7 倍** の差です。公式も「クエリ最小課金」という下限コストがあり、ポイントリードより安くはならないと説明しています。

### 設計原則

- **`id` が意味のあるドメイン値(注文ID、ユーザーID、エンティティID)になるように設計する**
- **取れるものは SDK のポイントリード API で取る**。`SELECT ... WHERE c.id = ...` を書かない
- API 設計上、クライアントから `id` + `partitionKey` を引き出せる URL 設計(例: `/orders/{customerId}/{orderId}`)を取る

Cosmos DB を「速い」と感じるか「高い」と感じるかの 8 割は、ここを正しく実装しているかで決まります。

> 根拠: [Optimize Cost for Reads and Writes](https://learn.microsoft.com/en-us/azure/cosmos-db/optimize-cost-reads-writes), [Q&A: Point read vs query RU](https://learn.microsoft.com/en-us/answers/questions/1193016/point-read-has-higher-rus-than-equivalent-query)

## 自動インデックス — 何もしなくても WHERE / ORDER BY が動く理由

Cosmos DB は既定で **全プロパティを索引** します。`CREATE INDEX` を書かなくても WHERE / ORDER BY が動くのはこのためです。ここでは、なぜ索引で速くなるのか、具体的に何が起きているのかを軽く踏み込みます。

### インデックスが無ければどうなるか

例として、container に 10 万件の注文 item があるとします。

```sql
SELECT * FROM c WHERE c.status = "PAID"
```

インデックスが無い状態だと、この問い合わせは **10 万件を全部読んで `status` を比較** する必要があります。これが全件スキャンで、RU もレイテンシも件数に比例して悪化します。

### Cosmos DB の自動インデックスが何をしているか

Cosmos DB は **パスごとの inverted index**(逆索引)を自動で作ります。ざっくり言うと、

- `/status = "PAID"` → [item_001, item_042, item_087, ...]
- `/status = "CANCELLED"` → [item_003, item_050, ...]
- `/price = 1290` → [item_002, ...]

という「値 → item の参照リスト」を各パスに対して保持しています。したがって `WHERE c.status = "PAID"` は、**該当する item だけを直接引ける** ことになり、RU が(全件数ではなく)該当件数に比例します。

### 自動インデックスが効く典型クエリ

- **等値フィルタ**: `WHERE c.status = "PAID"`
- **範囲フィルタ**: `WHERE c.price > 1000 AND c.price <= 5000`
- **配列要素**: `WHERE ARRAY_CONTAINS(c.tags, "sale")`
- **ネストしたプロパティ**: `WHERE c.customer.country = "JP"`(パス `/customer/country` も自動索引される)

### 代償

- **書き込み時に全索引を更新** するため、書き込み RU は索引の数に応じて増える
- **ストレージも索引分だけ増える**(典型的には item サイズの +20〜40% 程度)
- 大ドキュメント × 全プロパティ索引は痛い

「使わないパスは `excludedPaths` で落とす」「検索用途のない大フィールドは索引から外す」が運用の定番です。書き込み特化ワークロードでは `indexingMode: "none"` で索引をほぼ切り、ポイントリードだけで回す選択肢もあります。

> 根拠: [Indexing Policies](https://learn.microsoft.com/en-us/azure/cosmos-db/index-policy), [Sample Indexing Policies](https://learn.microsoft.com/en-us/cosmos-db/sample-indexing-policies)

## クエリモデルと Composite Index — 多プロパティで自動索引だけでは足りない理由

NoSQL API のクエリは **SQL ライク** です。

```sql
SELECT c.id, c.customer.name
FROM c
WHERE c.status = "PAID" AND c.orderedAt >= "2026-04-01"
ORDER BY c.orderedAt DESC
```

RDBMS との最大の違いは、**JOIN は同一ドキュメント内の配列を開くためにしか使えない** ことです。ドキュメント間 JOIN は存在せず、必要ならアプリで 2 回引きます。ここでも「一緒に読むものは一緒に保存する」原則が効きます。

### パーティションキーの有無でクエリ形態が変わる

| WHERE に PK | 問い合わせ先 | コスト感 |
|---|---|---|
| 含む | 1 論理パーティション | 最安 |
| 含まない | **全物理パーティションにファンアウト(Cross-Partition Query)** | 高い |

公式のモデリング例では、Cross-Partition Query が **1 本で 2,063 RU** 消費する事例が出ています。ダッシュボードから繰り返し叩かれると RU を食い尽くします。

### なぜ Composite Index が必要か

自動インデックスが張っているのは **単一パスの inverted index** です。このため、

- **複数プロパティをまたぐ ORDER BY** (`ORDER BY c.status, c.orderedAt`)
- **等値 + 範囲の組み合わせ** (`WHERE c.status = "PAID" AND c.orderedAt > ...`)

のようなクエリでは、自動索引だけだと「片側で絞ってから残りをスキャンして並べ替える」ことになり、**クエリエンジンが大量の中間結果を持つ羽目になります**。

**Composite Index** は、「この複数プロパティの組み合わせで並んだ索引」を明示的に作ることで、この中間ステップを消します。

### 効果と具体例

公式ドキュメントの例では、**同じクエリが 44.28 RU → 8.86 RU(約 5 倍削減)** に下がっています。運用でよく叩かれるクエリほど効果が大きい領域です。

Composite Index の定義例(indexingPolicy の一部):

```json
"compositeIndexes": [
  [
    { "path": "/status", "order": "ascending" },
    { "path": "/orderedAt", "order": "descending" }
  ]
]
```

### 設計ルールと落とし穴

- **等値フィルタを先、範囲 / ORDER BY を後** に置く。RDBMS の複合索引と同じ勘所
- **ORDER BY が 2 列以上なら Composite は事実上必須**
- **並び順(ASC/DESC)も一致が必要**。混在の ORDER BY を使うなら別 Composite を張る
- Composite を増やすほど **書き込み RU と索引ストレージも増える**。乱発しない
- **クエリの実行計画に相当するものとして `indexingMetrics` がある**。運用前に重いクエリに対して有効化し、「Composite を足せばどれだけ下がるか」を確認する習慣を持つ

> 根拠: [Indexing Policies](https://learn.microsoft.com/en-us/azure/cosmos-db/index-policy), [Sample Indexing Policies](https://learn.microsoft.com/en-us/cosmos-db/sample-indexing-policies), [Troubleshoot Query Performance](https://learn.microsoft.com/en-us/azure/cosmos-db/troubleshoot-query-performance)

## Document 型の本質的な強みと痛点

先行記事を少し拡張して、Cosmos DB 前提で言語化するとこうなります。

**強み**

- **自動索引で開発速度が出る**。インデックス設計の "事前の正解" を強要されない
- **JSON + 柔軟スキーマ**がドメインオブジェクトと直結する
- **パーティション内トランザクション**(transactional batch / stored procedure)でローカルな原子性を持てる

**痛点**

- **2MB 上限**: 無限配列を許すと書き込みが落ちる
- **RU という独自の計量単位**: SQL 的な感覚で書くと一発で爆発する
- **クロスドキュメント JOIN が無い**: RDBMS からの移植は "問い合わせを書き直す"
- **自動索引のまま巨大ドキュメント**: RU とストレージを食い続ける

Document 型 NoSQL は「スキーマレス」ではなく **「DB がスキーマを守らないモデル」** です。これをチームが受け入れていない段階で採用すると、先行記事のアンチパターン集に一直線になります。

# RU (Request Unit) モデルと課金 3 モード

Cosmos DB 独自の概念である **Request Unit (RU)** を理解しないと、コスト感覚も性能感覚も噛み合いません。

## 1 RU は何か

公式の定義を平易に言うと、

> **1 RU = 1KB のドキュメントを point read(ID + パーティションキー指定)で 1 回取得するためのリソース量**

point read は最もコスパが良い操作で、RU/s が安定します。一方、クエリ(`SELECT ... WHERE`)、書き込み(insert / replace / upsert)はこれより多くの RU を消費します。

また、**Strong / Bounded Staleness の読み取りは Session 以下の約 2 倍 RU** を食います。一貫性レベルの選択は、そのまま RU 消費に跳ね返る設計上の決定です。

RU コストは**毎レスポンスの `x-ms-request-charge` ヘッダ**で観測できます。運用では「このクエリが何 RU か」を常に見る文化が必要です。

> 根拠: [request-units](https://learn.microsoft.com/en-us/azure/cosmos-db/request-units)

## 課金 3 モードの使い分け

| モード | 単価 | 最小 | 向く用途 | 向かない用途 |
|---|---|---|---|---|
| **Provisioned (Standard)** | 100 RU/s あたり $0.008/h | 400 RU/s | 負荷が安定し、使用率が高い本番 | スパイキー、低頻度 |
| **Autoscale** | Standard の **1.5 倍レート** | 最大の 10% が下限 | 日中帯に集中するワークロード | 24 時間同じ負荷 |
| **Serverless** | **100 万 RU あたり $0.25** | なし(従量) | dev / 検証、スパイキー、軽量 API | 高スループット、大容量 |

判断の目安はシンプルです。

- **使用率 < 66% で日中しか使わない → Autoscale**
- **使用率 >= 66% で安定 → Standard**
- **スパイキー / 低頻度 → Serverless**(ただし**最大 20,000 RU/s、ストレージ 1TB 程度**の上限に注意)

また、Cosmos DB には **Free Tier** があり、アカウント単位で **1000 RU/s + 25GB が永続的に無料** です。開発環境や小規模アプリで強力です。

> 根拠: [throughput-serverless](https://learn.microsoft.com/en-us/azure/cosmos-db/throughput-serverless), [how-to-choose-offer](https://learn.microsoft.com/en-us/azure/cosmos-db/how-to-choose-offer), [autoscale-faq](https://learn.microsoft.com/en-us/azure/cosmos-db/autoscale-faq), [free-tier](https://learn.microsoft.com/en-us/azure/cosmos-db/free-tier)

# 一貫性レベル 5 段階の使い分け

Cosmos DB は **5 段階** の一貫性レベルを提供し、アカウント単位で既定を決め、リクエスト単位で下げることもできます。

強 → 弱 の順に次のとおりです。

1. **Strong**: 線形化可能(linearizable)。読みは最新の確定書き込みを必ず返す
2. **Bounded Staleness**: K 件 / T 秒以内の遅延を許す、それ以外は Strong 相当
3. **Session**(既定): 同一セッション内で monotonic reads / read-your-writes を保証
4. **Consistent Prefix**: 書き込み順序が崩れない(逆順では見えない)だけを保証
5. **Eventual**: いつか揃う。順序の保証すらない

## 実務での選び方

- **既定の Session で大多数は足りる**。Web / モバイル / API でユーザーが「自分の書いたものを自分で読む」のはセッションで解決する
- **Strong / Bounded Staleness は "リッチなクライアント間の即時一貫性" が要件の時だけ**。読み RU が 2 倍、レイテンシも悪化
- **Strong は マルチリージョン書き込みと両立できない**。グローバル書き込みを取るなら自動的に候補外
- **Consistent Prefix / Eventual は "分散カウンタ的な用途" などで意図的に選ぶ**

つまり、**"強い一貫性が欲しい" と雰囲気で Strong を選ぶと、RU とグローバル展開の両方で損をする** 設計になりがちです。既定の Session を起点に、具体的な失敗シナリオで必要になった時だけ上げるのが無難です。

> 根拠: [consistency-levels](https://learn.microsoft.com/en-us/azure/cosmos-db/consistency-levels)

# パーティションキー設計 Cosmos DB 編 — 物理制約と階層パーティションキー

パーティションキーの概念は前章で扱いました。ここでは **Cosmos DB 固有の物理的上限** と、**階層パーティションキー (HPK)** で上限を回避する実務パターンに絞って深掘ります。

## 物理的な上限

| リソース | 上限 |
|---|---|
| 論理パーティション(1 キー値分) | **20 GB** / **10,000 RU/s** |
| 物理パーティション(裏側) | **50 GB** / **10,000 RU/s** |
| コンテナ全体の論理パーティション数 | 無制限 |

ここで重要な事実が 2 つあります。

- **1 つの論理パーティション(= 同一パーティションキー値)は、1 つの物理パーティションにしか乗らない**。したがって、どれだけスケールアウトしても、**1 論理パーティションが出せるスループットは最大 10,000 RU/s**。
- **論理パーティションは 20GB で頭打ち**。ここを超えると、そのキー値への書き込みはエラーになる。

つまり、**「1 人のユーザーでも 20GB / 10,000 RU/s を超えない」か「超えない設計に分割する」か** の二択になります。

> 根拠: [partitioning-overview](https://learn.microsoft.com/en-us/azure/cosmos-db/partitioning-overview), [partitioning](https://learn.microsoft.com/en-us/azure/cosmos-db/partitioning)

## 階層パーティションキー (Hierarchical Partition Keys)

この 20GB の壁に直接効くのが **階層パーティションキー (HPK)** です。最大 **3 階層** のキーを定義でき、**上位キーで分散しつつ下位キーで細分化** できます。

典型例はマルチテナント SaaS です。

- `/TenantId` だけにする → 大きなテナントが 20GB 超で詰まる
- `/UserId` だけにする → テナント単位の集計がクロスパーティションになる
- `/TenantId/UserId/SessionId`(HPK) → **テナントで分散、ユーザーで分割、セッションで更に細分** という良いとこ取り

条件は、**第 1 階層のキーが高 cardinality で、ほぼ全てのクエリの WHERE 句に含まれていること** です。これを満たせないなら HPK は効きません(クロスパーティションクエリ化する)。

> 根拠: [hierarchical-partition-keys](https://learn.microsoft.com/en-us/azure/cosmos-db/hierarchical-partition-keys)

## モデリング例: EC サイトの注文 — Cosmos DB 版

先行記事の「注文ドキュメント」を Cosmos DB 前提で置き直します。公式ドキュメントでは e コマースの例でパーティションキーを `/CartId` に置き、カート単位の読みと更新を最速化するモデリングが示されています。

- **パーティションキー = `CartId`**: カート詳細画面は point read 1 発
- **ユーザー横断で "あるユーザーの全カート" を引く**のは意図的にレアパスに回す
- **注文確定** は transactional batch で同一パーティション内原子更新

クロスパーティションクエリが避けられない例(ユーザー単位の全注文履歴)では、**別 container を Change Feed で同期** して `/UserId` で分散させる、という **Materialized View** の出番になります(後述)。

> 根拠: [model-partition-example](https://learn.microsoft.com/en-us/azure/cosmos-db/nosql/model-partition-example)

# Azure 前提の定番構成パターン

Cosmos DB を Azure の他サービスと繋いだ時に、初めて設計がきれいに閉じるパターンを 4 つ紹介します。

## Change Feed + Azure Functions

**Change Feed** は、コンテナに対する全書き込みを時系列で読める機能です。**常時オン、追加料金なし**、有効化も不要です。モードが 2 種類あります。

- **Latest version**(既定): 各 item の最新版だけが流れる
- **All versions and deletes**(プレビュー): 中間更新と TTL 削除も拾える

Functions の **Cosmos DB Trigger** を使うと、数行で「書き込みに反応してイベント駆動で処理を走らせる」が組めます。

典型用途:

- 書き込み通知 → Service Bus / Event Hub へ publish
- 集計・プロジェクションの更新
- 別 container の denormalized ビュー更新
- 外部システムへの同期

> 根拠: [change-feed](https://learn.microsoft.com/en-us/azure/cosmos-db/change-feed), [Functions Cosmos DB trigger](https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-cosmosdb-v2-trigger), [change-feed-design-patterns](https://learn.microsoft.com/en-us/azure/cosmos-db/change-feed-design-patterns)

## Transactional Outbox on Cosmos DB

先行記事で触れた **Outbox パターン** は、Cosmos DB + Change Feed との相性が非常に良いです。

手順:

1. 業務データ更新と outbox イベントを **同一論理パーティション** で **transactional batch** として書く(原子的)
2. Change Feed を読むワーカー(Functions など)が outbox を拾って Service Bus / Event Hub に publish
3. publish 済みフラグ、または TTL で掃除

これで、**「DB 書けたのにメッセージが飛ばなかった」** という dual-write 問題を、外部 outbox テーブルや CDC ツールを足さずに Cosmos DB の機能だけで解消できます。

> 根拠: [transactional outbox pattern for cosmos](https://learn.microsoft.com/en-us/azure/architecture/databases/guide/transactional-out-box-cosmos)

## Synapse Link / HTAP — "運用と分析を兼ねない" への Azure 解

先行記事のアンチパターン「運用 DB と分析 DB を兼ねる」を、Cosmos DB は **Synapse Link** で正面から解きます。

- コンテナに Synapse Link を有効化すると、裏側に **列指向の analytical store** が自動複製される
- 運用トラフィックの RU には影響しない(別リソースへの非同期複製)
- Synapse / Fabric / Spark から **near real-time で分析クエリを発行** できる

「運用 container に BI ツールから重いクエリを直接投げる」運用をしている現場は、まず Synapse Link に逃がすのが定石です。

> 根拠: [synapse-link](https://learn.microsoft.com/en-us/azure/cosmos-db/synapse-link), [configure synapse link](https://learn.microsoft.com/en-us/azure/cosmos-db/configure-synapse-link)

## Vector 検索 / RAG — "ベクトル DB を別立てしない" 構成

生成 AI 時代に Cosmos DB が強いのは、**運用データとベクトル(エンベディング)を同じコンテナに置ける** 点です。

- NoSQL API で **Vector Index (DiskANN)** を定義できる
- 1 item 内に「業務データ + `vector` プロパティ」を持たせる
- **kNN / ANN を Cosmos DB 単体で実行**、別ベクトル DB に複製不要

RAG の定番スタックでは「Postgres / Cosmos で業務データ」+「Pinecone / Qdrant / AI Search でベクトル」と 2 ストア構成になりがちですが、Cosmos DB に寄せれば **整合性の境界を 1 つ減らせる** のが実務的なメリットです。

Azure AI Search との住み分けは次のとおりです。

- **Cosmos DB Vector**: 運用データ + エンベディング、**RAG の一次ストア**として 1 本で済ませたい
- **Azure AI Search**: 全文検索 / ファセット / セマンティックランキングに特化、**検索エンジンとしての完成度**

> 根拠: [vector-search-overview](https://learn.microsoft.com/en-us/azure/cosmos-db/gen-ai/vector-search-overview), [RAG](https://learn.microsoft.com/en-us/azure/cosmos-db/gen-ai/rag), [vector-database](https://learn.microsoft.com/en-us/azure/cosmos-db/vector-database)

# 設計パターン集

Cosmos DB でよく組まれる設計パターンを、**どう組むか + いつ選ぶか** の観点でまとめます。

## Event Sourcing

**状態を直接保存せず、ドメインイベントの append-only ログを保存する** パターン。Cosmos DB は次の理由で相性が良いです。

- 論理パーティション内で **transactional batch によるイベント追記**
- **Change Feed がそのままイベントバス** になる
- 水平スケールと高可用性をそのまま享受できる

注意点として、Change Feed は **at least once** 配信です。プロジェクションや下流連携は **必ず冪等** に設計します。また、古いイベントを毎回リプレイするとコストが嵩むため、**スナップショット** と **プロジェクションの永続化** を併用します。

> 根拠: [event-sourcing sample](https://learn.microsoft.com/en-us/samples/azure-samples/cosmos-db-design-patterns/event-sourcing/)

## CQRS + Materialized View

**書きモデルと読みモデルを分離** し、Change Feed で非同期に読みモデルを組み上げるパターン。

- 書き: 正規化された container(例: `/CartId` で分散)
- 読み: クエリパターンごとに別 container(例: `/UserId` で分散、ユーザー単位の履歴)
- 同期: Functions の Cosmos DB Trigger

「クロスパーティションクエリを消す一般解」として覚えておくと応用が利きます。読みモデルは**結果整合**で問題ない場面が多く、Session 一貫性の既定のままで回せます。

> 根拠: [change-feed-design-patterns](https://learn.microsoft.com/en-us/azure/cosmos-db/change-feed-design-patterns)

## Reference Data Replication

「マスタデータを JOIN で引きたい」要望を、**各論理パーティションに最小スナップショットを埋め込む** ことで解消するパターン。

- 商品マスタ名・価格を各注文に snapshot として埋め込む(先行記事の注文モデルと同じ)
- マスタが変わったら Change Feed で**必要な範囲だけ**バックフィル

「全注文を書き直す」のは避けたいので、**"履歴はスナップショット、最新が必要なら別取得"** という方針を明確に持つことが重要です。

## Time-series bucketing

先行記事のホットパーティション回避策を Cosmos DB 的に書くとこうなります。

- キー: `deviceId#yyyyMMdd` / `deviceId#yyyyMM`
- 1 バケット = 1 論理パーティションの読みやすさを維持しつつ、時間で分割
- 古いバケットは TTL で自動削除

単純に `createdAt` を使うと「今日のパーティションに全書き込みが集中 → ホット」、`deviceId` だけだとヘビーデバイスが 20GB に刺さる、の両方を避ける定番構成です。

## Distributed Counter / Write Sharding

単一カウンタ(グローバル閲覧数など)を 1 ドキュメントで持つと、そのパーティションが 10,000 RU/s の上限に当たります。

- キー末尾にランダムサフィックスを付けた N 個のシャードに書き込みを分散
- 読み取り時に N シャードを合算

**書き込みを N 倍分散する代わりに、読み取りは N 倍のファンアウト** という、先行記事と同じトレードオフが Cosmos DB 前提でも繰り返し出てきます。

> 根拠: [cosmos-db-design-patterns (GitHub)](https://github.com/Azure-Samples/cosmos-db-design-patterns), [minimize-coordination](https://learn.microsoft.com/en-us/azure/architecture/guide/design-principles/minimize-coordination)

# グローバル分散と競合解決

Cosmos DB の強みはグローバル分散です。モードは 2 つ。

- **Single-region write + multi-region read**(既定): 1 リージョンで書き、全リージョンで読む。整合性は選びやすい
- **Multi-region writes**: 全リージョンで書け、全リージョンで読める。**Strong 一貫性は選べない**

マルチリージョン書き込みでは競合が発生しうるため、解決ポリシーが必要です。

- **Last-Write-Wins (LWW)**(既定): `_ts` が大きい方を採用。削除は insert/replace より優先
- **カスタム解決**: ストアドプロシージャで業務ルールに基づく解決
- **Conflict Feed**: 解決しきれない競合をアプリが後から拾う

「マルチリージョン書き込みで同一ドキュメントを秒間レベルで更新し続ける」設計は、LWW では衝突が多発して挙動が読みにくくなります。**頻繁に更新するデータは単一リージョン書き込みに寄せる**、もしくは **新しい item を作って不変化する**(Event Sourcing 寄せ)のが実務解です。

> 根拠: [distribute-data-globally](https://learn.microsoft.com/en-us/azure/cosmos-db/distribute-data-globally), [conflict-resolution-policies](https://learn.microsoft.com/en-us/azure/cosmos-db/conflict-resolution-policies), [how-to-manage-conflicts](https://learn.microsoft.com/en-us/azure/cosmos-db/how-to-manage-conflicts), [reliability-cosmos-db-nosql](https://learn.microsoft.com/en-us/azure/reliability/reliability-cosmos-db-nosql)

# Cosmos DB 固有のアンチパターン

先行記事のアンチパターンに重ねて、**Cosmos DB だからこそ刺さる** ものに絞ります。

## クロスパーティションクエリの多発

パーティションキーを WHERE に含まないクエリは、全パーティションにファンアウトします。**小さめのコンテナでも数百 RU、公式例では 1 クエリで 2063 RU** 程度まで伸びることがあります。ダッシュボードで何度も叩かれると RU を食い尽くします。

対処:

- クエリパターンを洗い出して **パーティションキーを決め直す**
- クロスパーティション前提のクエリは **Materialized View** に逃がす

## Composite Index の張り忘れ

複数プロパティ ORDER BY / フィルタのクエリで Composite Index が無いと、5〜10 倍の RU を食うことが普通にあります。**`indexingMetrics` を有効にして、運用前に重いクエリを洗う** 習慣を付けます。

## 全プロパティ索引のまま巨大ドキュメント

既定の自動索引は楽ですが、大きい item × 多プロパティで運用し続けると、書き込み RU とストレージが肥大化します。**クエリで使わない大フィールドは `excludedPaths`**、極端ワークロードでは `indexingMode: "none"` を検討。

## 2MB に近い item を作る

無限追記配列(コメント、履歴、ログ)は、**2MB 到達前から RU / レプリケーション性能が悪化** し、到達すると書き込み失敗に切り替わります。**分割設計(親 + 子コンテナ)** を早めに入れるのが安全です。

## マルチリージョン書き込みで同一ドキュメントを頻繁に更新

LWW 衝突が多発し、「どのリージョンで書いた結果が残るか」が読みにくくなります。**update 連打をやめて、新 item 発行(append-only)に寄せる**、もしくは**単一リージョン書き込みへ戻す**のが実務解。

## 運用コンテナに重い分析クエリ

BI ダッシュボードからの重集計、長時間 scan を運用 container に直接投げない。**Synapse Link / Fabric** に逃がす。

> 根拠: [troubleshoot-query-performance](https://learn.microsoft.com/en-us/azure/cosmos-db/troubleshoot-query-performance), [concepts-limits](https://learn.microsoft.com/en-us/azure/cosmos-db/concepts-limits), [reliability-cosmos-db-nosql](https://learn.microsoft.com/en-us/azure/reliability/reliability-cosmos-db-nosql)

# 判断フロー — いつ Cosmos DB を選ぶか、いつ避けるか

先行記事の判断フローを Cosmos DB 特化で書き直します。上から順に、最初に Yes になったところが答えです。

1. **JOIN / 複雑集計 / 厳密 ACID が中核** → Azure Database for PostgreSQL / Azure SQL Database
2. **OLAP / DWH が中心** → Fabric / Synapse(運用ストアと併用なら Cosmos + Synapse Link)
3. **既存 MongoDB 資産を可能な限り温存** → Cosmos DB for **MongoDB vCore**
4. **MongoDB 互換性がいるが RU モデルで回したい** → Cosmos DB for **MongoDB RU**
5. **既存 Cassandra / Table / Gremlin 資産がある** → それぞれの Cosmos DB API
6. **JSON + Azure + グローバル低レイテンシ + 最新機能(Vector / HPK / Synapse Link)** → **Cosmos DB NoSQL**
7. **検索が主要ユースケース(全文 / ファセット / セマンティック)** → Azure AI Search(Cosmos と併用も)
8. **上記のどれにも強く当てはまらない** → **Cosmos DB を選ぶ積極的理由がない**。RDBMS から始める

Cosmos DB が明確に勝つのは **「グローバル分散」「Azure 連携」「Vector + 運用の同居」「Change Feed ベースのイベント駆動」** が効くケースです。これらを使わない構成では、コスト面でも運用面でも Cosmos DB を選ぶ積極的理由は弱くなります。

# まとめ

- Cosmos DB は「速い Document DB」ではなく、**API / RU / 一貫性 / パーティションキー** の 4 軸で設計するプロダクト
- Document 型 NoSQL の強みは **JSON + 自動索引 + パーティション内原子更新**、痛点は **2MB 制約 / RU 爆発 / クロスドキュメント JOIN 無し**
- RU は **`x-ms-request-charge` を常に見る**。課金モードは 3 つ、使用率 66% が Autoscale と Standard の分水嶺
- 一貫性は **Session を既定に、具体的な要件が出た時だけ上げる**。Strong はマルチリージョン書き込みと両立しない
- パーティションキーは **20GB / 10,000 RU/s** の壁と **階層パーティションキー** を前提に決める
- Azure 前提なら **Change Feed + Functions**、**Transactional Outbox**、**Synapse Link**、**Vector / RAG** が定番
- 設計パターンは **Event Sourcing / CQRS / Materialized View / Reference Data / Time-series / Write Sharding** を押さえる
- 固有アンチパターンは **クロスパーティションクエリ / Composite Index 漏れ / 巨大 item / マルチリージョン同一更新 / 運用と分析の同居**
- Cosmos DB を選ぶ積極的理由が **Azure 連携 / グローバル / Vector / イベント駆動** にあるか、最初に確認する

# 参考資料

## 全体・API 選択

- [Cosmos DB Overview — Microsoft Learn](https://learn.microsoft.com/en-us/azure/cosmos-db/overview)
- [Choose an API — Microsoft Learn](https://learn.microsoft.com/en-us/azure/cosmos-db/choose-api)
- [Common Use Cases and Scenarios](https://learn.microsoft.com/en-us/azure/cosmos-db/use-cases)
- [Understand Data Models — Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/data-guide/technology-choices/understand-data-store-models)

## Document モデル / インデックス

- [Service Limits](https://learn.microsoft.com/en-us/azure/cosmos-db/concepts-limits)
- [Indexing Policies](https://learn.microsoft.com/en-us/azure/cosmos-db/index-policy)
- [Sample Indexing Policies](https://learn.microsoft.com/en-us/cosmos-db/sample-indexing-policies)
- [Troubleshoot Query Performance](https://learn.microsoft.com/en-us/azure/cosmos-db/troubleshoot-query-performance)

## RU / 課金 / 一貫性

- [Request Units in Azure Cosmos DB](https://learn.microsoft.com/en-us/azure/cosmos-db/request-units)
- [Consistency Levels](https://learn.microsoft.com/en-us/azure/cosmos-db/consistency-levels)
- [How to Choose Between Standard and Autoscale Throughput](https://learn.microsoft.com/en-us/azure/cosmos-db/how-to-choose-offer)
- [Autoscale FAQ](https://learn.microsoft.com/en-us/azure/cosmos-db/autoscale-faq)
- [Serverless in Azure Cosmos DB](https://learn.microsoft.com/en-us/azure/cosmos-db/throughput-serverless)
- [Free Tier](https://learn.microsoft.com/en-us/azure/cosmos-db/free-tier)

## パーティショニング

- [Partitioning Overview](https://learn.microsoft.com/en-us/azure/cosmos-db/partitioning-overview)
- [Partition Limits](https://learn.microsoft.com/en-us/azure/cosmos-db/partitioning)
- [Hierarchical Partition Keys](https://learn.microsoft.com/en-us/azure/cosmos-db/hierarchical-partition-keys)
- [Model Partition Example](https://learn.microsoft.com/en-us/azure/cosmos-db/nosql/model-partition-example)

## Azure 連携

- [Change Feed in Azure Cosmos DB](https://learn.microsoft.com/en-us/azure/cosmos-db/change-feed)
- [Change Feed Design Patterns](https://learn.microsoft.com/en-us/azure/cosmos-db/change-feed-design-patterns)
- [Azure Functions Cosmos DB Trigger](https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-cosmosdb-v2-trigger)
- [Transactional Outbox Pattern for Cosmos DB](https://learn.microsoft.com/en-us/azure/architecture/databases/guide/transactional-out-box-cosmos)
- [Azure Synapse Link for Azure Cosmos DB](https://learn.microsoft.com/en-us/azure/cosmos-db/synapse-link)
- [Configure Synapse Link](https://learn.microsoft.com/en-us/azure/cosmos-db/configure-synapse-link)
- [Vector Search Overview](https://learn.microsoft.com/en-us/azure/cosmos-db/gen-ai/vector-search-overview)
- [Retrieval-Augmented Generation (RAG)](https://learn.microsoft.com/en-us/azure/cosmos-db/gen-ai/rag)
- [Cosmos DB as Vector Database](https://learn.microsoft.com/en-us/azure/cosmos-db/vector-database)

## グローバル分散 / 競合

- [Distribute Data Globally](https://learn.microsoft.com/en-us/azure/cosmos-db/distribute-data-globally)
- [Conflict Resolution Policies](https://learn.microsoft.com/en-us/azure/cosmos-db/conflict-resolution-policies)
- [How to Manage Conflicts](https://learn.microsoft.com/en-us/azure/cosmos-db/how-to-manage-conflicts)
- [Reliability in Azure Cosmos DB for NoSQL](https://learn.microsoft.com/en-us/azure/reliability/reliability-cosmos-db-nosql)

## 設計パターン

- [Azure Cosmos DB Design Patterns (GitHub)](https://github.com/Azure-Samples/cosmos-db-design-patterns)
- [Event Sourcing Pattern Sample](https://learn.microsoft.com/en-us/samples/azure-samples/cosmos-db-design-patterns/event-sourcing/)
- [Minimize Coordination — Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/guide/design-principles/minimize-coordination)
