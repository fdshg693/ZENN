---
title: "Key-Value 型 NoSQL 実戦ガイド — DynamoDB と Redis はなぜ全然違うのか"
emoji: "🔑"
type: "tech"
topics: ["dynamodb", "redis", "nosql", "keyvalue", "architecture"]
published: false
---

# はじめに — 「KV だからシンプル」という誤解

先行記事 [NoSQL をもう一度ちゃんと整理する](./nosql_overview.md) では、NoSQL を SQL との対比で整理し、4 タイプのうち Key-Value 型の代表として **DynamoDB** と **Redis** を並べて紹介しました。もう 1 本の続編 [Azure Cosmos DB 実戦ガイド](./cosmos_db_azure_guide.md) では Document 型 NoSQL を 1 プロダクトで深掘りしました。

本記事はその姉妹編として、**Key-Value 型を 2 プロダクト対比で深掘り** します。

よくある誤解は「DynamoDB と Redis は同じ KV だから、使い方も似ている」です。これは半分正しく、半分危険です。**キーに対して値を取る** という API 表面は確かに似ていますが、その下の設計思想は別物です。

- **DynamoDB**: 永続・水平スケール・AWS マネージド・サーバーレス志向の「分散 KV データベース」
- **Redis**: インメモリ・サブミリ秒・多データ構造・OSS 起源の「インメモリストア兼キャッシュ兼ミドルウェア」

この差を無視すると、「Redis で primary DB のつもりでデータを失う」「DynamoDB で Scan 連打して RU とコストを溶かす」「キャッシュ層のつもりで DynamoDB を叩いてレイテンシ要件を満たせない」といった失敗に刺さります。

本記事のスタンスは先行記事と同じく、**「できること」より「向いていないこと・壊れ方」を優先して書く** です。

# 両者の根本差異 — なぜ "同じ KV" で括ってはいけないか

まず、DynamoDB と Redis の設計軸を並べます。ここで意識すべきは、**どの軸も「どちらがエライ」ではなく「目的が違う」** 点です。

| 観点 | DynamoDB | Redis |
|---|---|---|
| 位置付け | 永続 KV データベース | インメモリストア(キャッシュ / ブローカー / DB) |
| レイテンシ | single-digit ms(DAX で μs) | sub-millisecond |
| ストレージ | ディスク前提 | メモリ前提 + 永続化オプション |
| データモデル | item(属性集合) + PK/SK | 7+ データ構造(String / List / Hash / Set / Sorted Set / Stream / JSON) |
| デプロイ | AWS マネージドのみ | OSS / Docker / Redis Cloud / Redis Enterprise / マネージド各種 |
| 課金 | pay-per-request または provisioned | OSS は無料、マネージドは usage-based |
| 向く用途 | サーバーレス、AWS 連携、スケーラブル KV | キャッシュ、リアルタイム処理、ランキング、セッション |

> 根拠: [Redis vs DynamoDB 比較](https://redis.io/tutorials/what-is-redis/)

直感的に言えば、**Redis は「速度のためならメモリを使い、耐久性は設定で買う」思想**、**DynamoDB は「耐久性とスケールのためなら数 ms のレイテンシを払う」思想** です。

この設計思想の差は、以降のセクションすべての判断に顔を出します。

# データモデル対比 — 単一値 KV と 多データ構造 KV

先行記事では KV 型を「キーと値」と紹介しましたが、DynamoDB と Redis の「値」の中身は大きく違います。

## DynamoDB の "値" は属性の集合 (item)

DynamoDB のデータ単位は **item** で、複数の **attribute**(属性)を持つ JSON ライクな構造です。

- **主キー** はシンプル(partition key のみ)または複合(partition key + sort key)
- partition key は string / numeric / binary のスカラー値で、内部のハッシュ関数で partition に振り分けられる
- sort key があると、同一 partition key 内で **sort key 順の B-tree** に格納される。等値だけでなく範囲検索・前方一致も可能
- 1 item の最大サイズは **400 KB**(attribute 名と値を含む)

> 根拠: [Choosing the Right DynamoDB Partition Key](https://aws.amazon.com/blogs/database/choosing-the-right-dynamodb-partition-key/), [Single-table vs multi-table design](https://aws.amazon.com/blogs/database/single-table-vs-multi-table-design-in-amazon-dynamodb/), [Service, account, and table quotas](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Constraints.html)

## Redis の "値" はデータ構造

Redis は「1 つのキーに何が入るか」で API が変わります。

| 型 | 用途 | 例 |
|---|---|---|
| **String** | 最大 512 MB。カウンター、トークン、キャッシュ値、セッション | `SET`, `GET`, `INCR` |
| **List** | 順序付き string。キュー、タイムライン | `LPUSH`, `RPOP`, `LRANGE` |
| **Hash** | フィールドと値のマップ | `HSET user:1 name alice age 30` |
| **Set** | 一意要素の無順序集合 | `SADD`, `SINTER`(積集合) |
| **Sorted Set** | スコア付き集合。リーダーボード、rate limit、優先度キュー | `ZADD`, `ZRANGEBYSCORE` |
| **Stream** | append-only log。イベントソーシング | `XADD`, `XREAD` |
| **JSON** | ネイティブ JSON。ネスト構造 | `JSON.SET`, `JSON.GET` |

> 根拠: [What is Redis](https://redis.io/tutorials/what-is-redis/)

**「ランキングを集計する」が `ZADD` + `ZRANGE` で済むのが Redis**、**「1 item を読み書きするのが線形・永続で済むのが DynamoDB」** と理解すると差が分かります。

## 同じ「注文」をどうモデルに落とすか

先行記事の注文データを、2 つの KV でモデルに落とすとこうなります。

**DynamoDB 版**(Single-Table Design、PK = `CustomerId`、SK = `ORDER#<orderId>` など):

```
PK            SK                       Attributes
CUST#123      PROFILE                  { name, email, ... }
CUST#123      ORDER#2026-04-18-001     { total, items: [...], orderedAt }
CUST#123      ORDER#2026-04-17-002     { total, items: [...], orderedAt }
```

- 顧客プロファイルと注文を同じ PK に寄せ、`Query` 1 回で全部取れる
- `SK BEGINS_WITH "ORDER#"` で注文だけ絞り込める

**Redis 版**(ユースケースごとに構造を変える):

```
HSET cust:123:profile name "Alice" email "alice@example.com"
ZADD cust:123:orders 1713427200 "order:2026-04-18-001"   # timestamp でソート
HSET order:2026-04-18-001 total 17480 orderedAt ...
EXPIRE cust:123:recent 3600                              # 直近注文キャッシュは 1h
```

- プロファイルは Hash、注文一覧は Sorted Set(時系列)、注文詳細は Hash
- TTL を使った "直近 1 時間キャッシュ" のような期限付きデータが自然に書ける

**この差が、両者を "同じ KV" と括れない最大の理由** です。

# DynamoDB の設計軸 — パーティションキー / Single-Table / GSI & LSI

DynamoDB の設計判断は、大きく 4 つの軸で決まります。

## パーティションキーと物理制約

DynamoDB の水平スケールは、partition key を内部ハッシュ関数に通して物理 partition に振り分けることで実現しています。**1 partition の上限** は以下のとおりです。

- 読み: **3,000 RCU/s**(= strongly consistent 3,000 reads/s、または eventually consistent 6,000 reads/s、ただし 4 KB まで)
- 書き: **1,000 WCU/s**(= 1 KB までの write が 1,000 回/s)
- サイズ: **10 GB**

item サイズが大きいと必要 RCU/WCU は線形に増えます。例えば 20 KB の item を strongly consistent で 1 回読むと **5 RCU 消費** で、1 partition で同時 600 ops/s が上限になります。

> 根拠: [Best practices for partition keys](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-partition-key-design.html), [Burst and adaptive capacity](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/burst-adaptive-capacity.html)

**Adaptive Capacity** は on-demand / provisioned 両方で効き、ホット partition の一時的な偏りはある程度吸収します。ただし「万能の治療薬」ではなく、**partition key の偏りが大きいとそもそも adaptive capacity が間に合いません**。

## パーティションキー選定のアンチパターンと Good パターン

**避けるべきキー**:

- 低 cardinality(`status`、`country`、boolean): 数種類しか値がないので数 partition にしか分散しない
- **RDB 出身の UID / sequence**: partition key として問い合わせに使われないのに、ただ一意性のためだけに設定されているケース。検索できない UID が PK になると GSI に頼ることになる
- **時刻そのまま**(`order_date` を日丸め): その日の全書き込みが 1 partition に集中する典型的ホットパーティション
- **特定値に偏る** `Product_SKU`: 人気商品の partition だけが熱くなる

**向くキー**:

- `customerId` / `userId` / `deviceId` / `orderId` / `sessionId` のような **high cardinality かつ均等分散** する属性
- 偏りがあるなら **複合キー** でハッシュサフィックスを加える(`customerId#shardNo`)

> 根拠: [Designing partition keys to distribute workload](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-partition-key-uniform-load.html), [Choosing the Right DynamoDB Partition Key](https://aws.amazon.com/blogs/database/choosing-the-right-dynamodb-partition-key/)

先行記事と同じく、**partition key は後から直せない** と考えるのが安全です。変更するにはテーブルを作り直してデータを全移行するしかありません。

## Single-Table Design — "エンティティ = テーブル" の呪縛を解く

RDBMS 出身者は「エンティティごとにテーブル」と考えがちですが、DynamoDB では **複数のエンティティを同じテーブルに寄せる** のが基本です。動機はシンプルで、

- **Query は 1 partition にしかルーティングされない**
- したがって、**一緒に読みたいものを同じ partition key に寄せる** と 1 Query で済む
- 逆に別テーブルに分けると、アプリ側で 2 回引いて join する羽目になる(N+1 API 化)

### 典型パターン

**1. Customer + Orders を同一 PK に**:

```
PK                SK
CUST#123          PROFILE
CUST#123          ORDER#001
CUST#123          ORDER#002
```

`CustomerEmailAddress` を PK に載せておけば、顧客情報と全注文が 1 Query で取れます。

**2. Adjacency list で many-to-many**:

例えば "レース" と "ランナー" の多対多関係を、両方とも同じテーブルに `race-1` / `racer-2` のように PK で共存させて管理する。

**3. GSI Overloading**:

DynamoDB の GSI はデフォルトで 1 テーブルあたり 20 本までですが、**同じ GSI を複数のアクセスパターンで使い回す** ことで、実質的に 20 を超える問い合わせ軸を持てます。

> 根拠: [Single-table vs multi-table design](https://aws.amazon.com/blogs/database/single-table-vs-multi-table-design-in-amazon-dynamodb/), [Creating a single-table design](https://aws.amazon.com/blogs/compute/creating-a-single-table-design-with-amazon-dynamodb/)

### いつ Multi-Table にするか

- **まったく関連しない** エンティティ(顧客と IoT メトリクスを同じテーブルに寄せる必要は無い)
- **ライフサイクルが違う**(例: 監査ログを別テーブルにして TTL で自動削除)
- **スケール特性が違う**(書き込み集中するテーブルと、薄く広く読むテーブル)

Single-Table Design は銀の弾丸ではありません。**「1 Query で取りたい関連エンティティがある」なら寄せる、それ以外は分ける** が現実解です。

## GSI と LSI — 何が違うか、いつ使うか

DynamoDB の二次インデックスは 2 種類あり、挙動が大きく違います。

| 観点 | GSI (Global Secondary Index) | LSI (Local Secondary Index) |
|---|---|---|
| スループット | **独立した RCU/WCU を持つ** | **ベーステーブルのキャパシティを共有** |
| partition key | ベースと異なる属性にできる | **ベースと同じ partition key 必須** |
| 作成タイミング | いつでも追加・削除可 | **テーブル作成時のみ** 定義可能 |
| 整合性 | 結果整合のみ(eventually consistent) | 強整合の読みも可能 |
| サイズ制約 | 独立 | LSI があると item collection が 10 GB で固定 |

### GSI の書き込み増幅に注意

item を `Put` / `Update` / `Delete` すると、そのテーブルの **すべての GSI にも書き込みが伝搬** します。

重要な罠: **GSI の WCU がベースより小さいと、GSI 側の throttle がベーステーブルの書き込みごと止めます**。本番で「なぜかベースが書けなくなった」事故の定番原因です。**GSI の WCU はベース以上に設定する** が鉄則です。

### LSI は "同じ partition key で違う sort key を使いたい時だけ"

LSI は強整合読みができる利点がありますが、

- テーブル作成時にしか定義できない
- LSI があると、その `partition key` 配下の item collection は 10 GB で固定(HPK 的な回避ができない)
- ベースのキャパシティを食う

という制約から、**Single-Table Design と GSI Overloading が普及した現代では、LSI の出番は減って** います。迷ったら GSI から考えるのが無難です。

> 根拠: [Using Global Secondary Indexes](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GSI.html), [Right-Sized Provisioning](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/CostOptimization_RightSizedProvisioning.html), [Service quotas (Constraints)](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Constraints.html)

### Scan は原則使わない

1 Query の最大結果サイズは **1 MB** で、それを超えると pagination が必要になります。

そして `Scan` は **テーブル全体を読む** API で、コストとレイテンシの両方が最悪です。本番で Scan を使うべきなのは「データ全件バッチ処理を明示的に意図するとき」だけで、**通常のアプリケーションロジックから Scan を叩くのはアンチパターン** と考えていいです。

## 課金モード — オンデマンド vs プロビジョンド

DynamoDB の課金は 2 つのモードから選べます。

| モード | 単位 | 向く用途 |
|---|---|---|
| **On-demand** | リクエスト単価(RRU / WRU) | スパイキー、初期トラフィック不明、serverless |
| **Provisioned** | 秒あたりキャパシティ(RCU / WCU) | 負荷が安定、コスト最適化したい本番 |

判断の目安:

- **80% 以上の使用率が常時** になる見込みで、予測可能なら Provisioned
- 80% 超を維持するテーブルは「under-provisioned」扱い(スロットルリスク)
- スパイキーなら On-demand、または Provisioned + Auto Scaling
- **切替は provisioned → on-demand が 24h 内に 4 回まで**、on-demand → provisioned はいつでも可

> 根拠: [Right-Sized Provisioning](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/CostOptimization_RightSizedProvisioning.html), [Constraints](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Constraints.html)

# DynamoDB 固有の武器 — Transactions / Streams / Global Tables / DAX

ここまでは基礎設計の話でした。DynamoDB には、「NoSQL でこれが欲しかった」機能が揃っています。

## TransactWriteItems / TransactGetItems — "NoSQL でも ACID"

先行記事の「多エンティティ ACID なら RDBMS」を、DynamoDB は範囲を区切って引き受けます。

- **1 トランザクションあたり最大 100 アクション、4 MB**
- 対象は `ConditionCheck` / `Put` / `Update` / `Delete` のいずれか(1 アクションにつき 1 つ)
- **同一 AWS アカウント・同一リージョン内** の複数テーブルを跨げる(**クロスアカウント・クロスリージョン不可**)
- 同一アイテムに複数アクションは不可
- `ClientRequestToken` で冪等性を保証(同一トークンでの再送は 1 回と同じ効果)

キャンセルされる典型ケース:

- 条件式が不成立
- プロビジョンドキャパシティ不足
- アイテムが 400 KB 超過、または LSI の item collection が 10 GB 超過
- 同一アイテムに 2 つ以上のアクションが含まれる
- 別アカウント・別リージョンを含む

コスト面の重要な注意: **トランザクション read は通常の 2 倍(2 RCU / 4 KB)、transaction write も 2 倍(2 WCU / 1 KB)** です。ACID はタダではありません。

> 根拠: [Service, account, and table quotas](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Constraints.html), [DynamoDB API Reference (PDF)](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/dynamodb-api.pdf)

## DynamoDB Streams — 24 時間の CDC

**Streams** はテーブルへの変更イベントを時系列で取れる CDC 機能です。先行記事で扱った **Outbox / Materialized View / Event Sourcing** の基盤として使えます。

- **保持期間: 24 時間**(超過分は自動 trim)
- Stream は shard で構成され、各レコードに sequence number
- Stream view types は 4 種類:
  - `KEYS_ONLY`: キーのみ
  - `NEW_IMAGE`: 更新後の item
  - `OLD_IMAGE`: 更新前の item
  - `NEW_AND_OLD_IMAGES`: 両方
- Lambda trigger は 1 秒に 4 回 polling する
- **1 つの Stream に Lambda は 2 つまで**(それ以上だと読み取り throttle リスク)

典型用途:

- 書き込み通知 → SNS / SQS / EventBridge へ publish
- 別テーブルへのプロジェクション(Materialized View パターン)
- OpenSearch / S3 への非同期同期
- 監査ログ

> 根拠: [Change data capture for DynamoDB Streams](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Streams.html), [Streams and Lambda triggers](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Streams.Lambda.html), [StreamSpecification](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_StreamSpecification.html)

**24 時間を過ぎたレコードは復元できない** 点は Cosmos DB の Change Feed(保持無制限)との大きな違いです。下流処理が 24h 詰まると取り逃します。バッチ復旧を考えるなら PITR や別系統のログが必要です。

## Global Tables — マルチリージョン active-active と LWW

**Global Tables** は DynamoDB のテーブルを複数リージョンに同期する機能で、**マルチアクティブ**(全レプリカが読み書き可能)が基本です。

- **既定は MREC (Multi-Region Eventual Consistency)**: 非同期レプリケーション、通常 1 秒以内で他レプリカに反映
- 競合解決は **Last Writer Wins (LWW)**: 内部タイムスタンプで最新の書き込みが勝つ
- **MRSC (Multi-Region Strong Consistency)** は same-account 構成でのみサポート
- **トランザクションはソースリージョン内のみ ACID**(クロスリージョンでは部分反映が観測されうる)
- ソーステーブルは新リージョン追加から **24h 経過まで削除不可**

### 実戦的な設計パターン

マルチリージョン active-active は強力ですが、同一 item を複数リージョンで頻繁に更新すると LWW で結果が読みにくくなります。**IAM で 1 リージョンのみ書き込みを許可する "region pinning"** が公式推奨の回避策です。

> 根拠: [Global Tables](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GlobalTables.html), [Global Tables V2 how it works](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/V2globaltables_HowItWorks.html), [V1 how it works](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/globaltables_HowItWorks.html)

## DAX — DynamoDB 専用の in-memory 層

DAX (DynamoDB Accelerator) は DynamoDB の前に置く in-memory cache で、**DynamoDB 単体で single-digit ms が、DAX 併用で microseconds に** なります。

- **item cache**: `GetItem` / `BatchGetItem` の結果をキャッシュ(GSI/LSI 非対応)
- **query cache**: `Query` / `Scan` の結果をキャッシュ(テーブル・GSI 両方対応)
- 1 クラスタは primary 1 + replica 0〜10 ノード、**1 AWS アカウントあたり合計 50 ノード上限**

Redis と何が違うかは後で整理しますが、**DAX は DynamoDB API と直結する "透過キャッシュ"、Redis は汎用 KV** という違いが最大のポイントです。

> 根拠: [DAX config considerations](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/dax-config-considerations.html)

# Redis の設計軸 — 多データ構造 / 永続化 / Cluster / TTL

ここから Redis 側に移ります。Redis は「速い KV」という紹介だけで済ませると、肝心の**設計レバー**が見えません。

## 多データ構造の "設計レバー"

Redis の強みは、**データ構造ごとに最適化された O(1) / O(log N) コマンド** を持っている点です。以下は代表的な "この構造じゃないと書けない" 実例です。

- **Leaderboard**: Sorted Set に `ZADD`、上位 N 件は `ZREVRANGE`。スコア更新が O(log N)
- **Rate limit**: Sorted Set に timestamp を score にして push、`ZREMRANGEBYSCORE` で古いのを掃除
- **Atomic counter**: String に `INCR`(atomic)
- **Distributed lock**: `SET key value NX PX 10000`(存在しなければ set + TTL 付き)
- **Unique visitor**: Set に `SADD`、`SCARD` で重複排除済みカウント
- **Pub/Sub / Stream**: Stream に `XADD` / consumer group で event-driven 処理

逆に、**全部 String + JSON 文字列に格納する** のは公式アンチパターン #10 です。全 read / update で blob 全体のシリアライズとアプリ側編集が必要になり、field 単位の atomic update ができません。ネストを使いたいなら `Hash` か `JSON` 型を使います。

> 根拠: [What is Redis](https://redis.io/tutorials/what-is-redis/), [Redis Anti-Patterns](https://redis.io/tutorials/redis-anti-patterns-every-developer-should-avoid/)

## 永続化 — RDB / AOF / Hybrid

**「in-memory = 揮発」は Redis に当てはまりません**。永続化は 3 モードあります。

| 方式 | 特徴 | 代表的な用途 |
|---|---|---|
| **RDB** | 定期スナップショット(`save N M` 設定、手動 `BGSAVE`)。`dump.rdb` にバイナリで保存 | 日次バックアップ、高速な再起動 |
| **AOF** | 各 write op をログ追記、再起動時に replay | より細かい耐久性 |
| **Hybrid** | RDB snapshot + AOF 追記(7.0+ では multi-part AOF に進化) | 公式推奨 |

AOF の fsync ポリシーは 3 段階です。

- `always`: 毎 write で fsync。最も耐久性が高いが最も遅い
- `everysec`(既定): 1 秒に 1 回 fsync。現実的な折衷
- `no`: OS 任せ。最も速いが最も危険

**クラッシュ時に 1 件たりとも失わない完全耐久性が必要なら、AOF + `appendfsync always` が唯一の構成** です。それ以外は「最悪 1 秒ぶん失う可能性」を受け入れる設定になります。

Redis 7.0 以降、AOF は base file(RDB or AOF フォーマット) + incremental file + manifest の **multi-part** 機構に進化しており、AOF rewrite のコストが下がっています。

> 根拠: [Redis persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/), [Durable Redis](https://redis.io/technology/durable-redis/), [Caching at Scale with Redis (PDF)](https://redis.io/wp-content/uploads/2021/12/caching-at-scale-with-redis-updated-2021-12-04.pdf)

## レプリケーションと Redis Cluster

Redis の HA / スケール手段は 2 系統あります。

- **master-replica**: 1 primary が write、複数 replica が read とコピー。**非同期レプリケーション** なので、書いた直後に primary が落ちるとロスしうる
- **Redis Cluster**: keyspace を **16,384 hash slot** に分割、各 slot をノード間に割り振り、**CRC16(key) % 16,384** で slot を決定
- **推奨最大ノード数は約 1,000** (理論上限 16,384)
- OSS Redis で HA を得るには **Redis Sentinel** を別途セットアップする必要がある

### Cluster の大きな制約: CROSSSLOT

Redis Cluster では、**1 つのコマンド / トランザクション / Lua スクリプトに含まれるキーは全て同一 slot にある必要があります**。異なる slot のキーを触ると:

```
(error) ERR CROSSSLOT Keys in request don't hash to the same slot
```

これが出ます。MULTI/EXEC で異なる slot のキーを触ると各コマンドで CROSSSLOT、最終的に `EXECABORT Transaction discarded because of previous errors.` になります。

### Hash Tag で同一 slot に寄せる

これを回避するのが **hash tag** 記法です。キーの中に `{...}` を置くと、**中身だけがハッシュ対象** になります。

```
user:{123}:profile
user:{123}:orders
user:{123}:cart
```

この 3 つは `{123}` だけが CRC16 されるので、必ず同一 slot に乗ります。MULTI/EXEC や Lua で一括操作できるようになります。`CLUSTER KEYSLOT key` でスロット番号を確認できます。

> 根拠: [Cluster specification](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/), [Scale with Redis Cluster](https://redis.io/docs/latest/operate/oss_and_stack/management/scaling/), [Clustering best practices with keys](https://redis.io/blog/redis-clustering-best-practices-with-keys/), [CLUSTER KEYSLOT](https://redis.io/docs/latest/commands/cluster-keyslot/)

Redis Enterprise では、一部 multi-hash-slot 操作 (`MGET` / `MSET` など) を OSS より緩く扱える実装があります。OSS の範囲では、**hash tag を前提に key 設計する** のが鉄則です。

## TTL と Eviction Policy

Redis をキャッシュとして使うときの**事実上の本体**が TTL と `maxmemory-policy` です。

`maxmemory` に到達すると `maxmemory-policy` に従って eviction が発動します。既定は `noeviction` で、**これだと書き込みコマンドがエラーを返します**。キャッシュ用途で `noeviction` のまま起動すると「なぜか SET が通らない」事故になります。

選べる policy は 8 種類:

| policy | 対象 | アルゴリズム |
|---|---|---|
| `noeviction` | — | evict しない、書き込みエラー |
| `allkeys-lru` | 全キー | 近似 LRU |
| `allkeys-lfu` | 全キー | 近似 LFU |
| `allkeys-random` | 全キー | ランダム |
| `volatile-lru` | expire 付きのみ | 近似 LRU |
| `volatile-lfu` | expire 付きのみ | 近似 LFU |
| `volatile-random` | expire 付きのみ | ランダム |
| `volatile-ttl` | expire 付きのみ | TTL が最短のものから |

実務の目安:

- **純粋なキャッシュ**: `allkeys-lru` または `allkeys-lfu`
- **「消えたら困るデータ」と「キャッシュ」を同一 Redis に同居**: `volatile-lru` + 消したくないデータには TTL を付けない
- **primary DB として使う** なら: `noeviction`(そして永続化を有効化)

LRU / LFU / TTL いずれも**近似ランダム化アルゴリズム**で、厳密な LRU / LFU ではありません。メモリ効率と精度のトレードオフです。

レプリカが接続された状態で `maxmemory` を設定する場合、**レプリカの出力バッファ用にやや低めに maxmemory を設定する** のが安全です。eviction で発生する DEL 複製でレプリカバッファが膨らみ、連鎖退避が起きるのを避けます。

> 根拠: [redis.conf (maxmemory-policy 列挙)](https://download.redis.io/redis-stable/redis.conf), [Anti-Patterns #5](https://redis.io/tutorials/redis-anti-patterns-every-developer-should-avoid/)

# Redis の "NoSQL らしくない" 側面 — Pipelining / MULTI / Lua

先行記事で NoSQL は「結果整合が前提」と整理しましたが、Redis には **RDBMS のトランザクションに似た機能** があります。ただし、挙動はかなり独特です。

## Pipelining — RTT 削減で 5 倍速

Redis は Request/Response プロトコルなので、素朴なクライアントは 1 コマンドごとに 1 RTT を消費します。

```
Client: INCR X
Server: 1
Client: INCR X
Server: 2
...
```

**Pipelining** はサーバの応答を待たず複数コマンドを送り、まとめて応答を読む機能です。公式ドキュメントのベンチマークでは `10_000.times { ping }` が:

- pipelining なし: **1.185 秒**
- pipelining あり: **0.250 秒**

と、**約 5 倍高速** になっています。`MULTI` とは別機能で、原子性は保証されず、単に RTT を削減します。

「Serial single operations (no pipelining)」は Redis 公式のアンチパターン #4 です。1 リクエストで 100 個のキーを読むとき、1 コマンド × 100 回にするか、`MGET` か Pipelining か、の判断は**レイテンシに直結** します。

> 根拠: [Redis pipelining](https://redis.io/docs/latest/develop/use/pipelining/)

## MULTI / EXEC — 原子実行、ただしロールバック無し

MULTI/EXEC は Redis のトランザクション機能で、**1 EXEC で囲まれたコマンド列は他クライアントから分離された状態で atomic に実行** されます。ただし、**RDBMS と根本的に違う** 点が 2 つあります。

### (1) ロールバック無し

MULTI 内でコマンド型エラー(例: 文字列キーに `INCR`)が起きても、**他のコマンドは実行され続けます**。

> Redis does not support rollbacks of transactions since supporting rollbacks would have a significant impact on the simplicity and performance of Redis.

`DISCARD` で実行前に破棄することはできますが、EXEC 後は戻せません。

### (2) CROSSSLOT

前述のとおり、Cluster では MULTI 内の全キーが同一 slot にある必要があります。

### WATCH で CAS

MULTI は元々 pessimistic lock ではなく、**WATCH** と組み合わせて楽観的同時実行制御(CAS)を作るのが公式推奨パターンです。

```
WATCH mykey
val = GET mykey
val = val + 1
MULTI
SET mykey $val
EXEC
```

他のクライアントが `mykey` を更新していたら `EXEC` は Null reply を返すので、アプリ側でリトライします。RDBMS の `UPDATE ... WHERE version = ?` と同じ発想です。

> 根拠: [Transactions](https://redis.io/docs/latest/develop/interact/transactions/)

## Lua / Functions — サーバサイドロジック

`EVAL` / `EVALSHA` で Lua スクリプトをサーバ側で実行できます。スクリプトは **atomic 実行**(他コマンドは割り込めない)で、複数コマンドをまとめるのに向きます。

replication 時、Lua 実行中の write コマンド列を Redis が MULTI/EXEC で包んで replica / AOF に送る挙動があり、**スクリプトは短時間で終わらせる** のが運用の鉄則です。`maxmemory` 付近で長い Lua を実行すると、途中で memory を超過して write が失敗するリスクもあります。

7.0+ では `Functions` という仕組みが加わり、Lua を永続化・バージョン管理された機能として扱えます。Cluster 下では Lua / Functions も `hash tag` 制約の対象です。

> 根拠: [EVAL intro](https://redis.io/docs/latest/develop/programmability/eval-intro/)

# 整合性と耐久性の寄せ方 — どこまで信じていいか

先行記事の「ACID / BASE」を、DynamoDB と Redis の具体的な選択肢に落として並べます。

## DynamoDB

- **単一 item の書き込みは常に ACID**
- **TransactWriteItems で最大 100 アクション / 4 MB まで ACID**(単一リージョン)
- **Global Tables は基本 MREC(結果整合 + LWW)**、MRSC で強整合(same-account のみ)
- **書き込みは最低 3 AZ に複製** されて初めて成功が返る(= 耐久性はマネージドが担保)
- Streams の保持は 24 時間

耐久性は "DB 側で信用できる" のが DynamoDB の設計思想です。

## Redis

- **単一コマンドは atomic**
- **MULTI/EXEC も atomic だが、ロールバック無し**
- **WATCH で CAS**
- **耐久性は AOF 設定次第**: `appendfsync always` で完全耐久、`everysec` で最悪 1 秒失う
- **Cluster は非同期レプリケーション**: primary failover 時に、書いた直後のデータが failover 先で欠ける可能性

Redis は「**自分で選んだ耐久性レベル**しか得られない」設計です。デフォルトで "DB のつもり" で使い始めると、事故が起きます。

## 直感的な整理

- **DynamoDB は "DB 側で信用できる耐久性"** を前提にしてよい
- **Redis は "アプリとインフラ側で耐久性を構築する"** もの
- 「Ephemeral Redis を primary DB として使う」は Redis 公式のアンチパターン #9。速さのためにキャッシュとして使い、永続データは別ストアに置くのが基本姿勢

> 根拠: [DynamoDB Constraints](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Constraints.html), [Redis Anti-Patterns](https://redis.io/tutorials/redis-anti-patterns-every-developer-should-avoid/), [Durable Redis](https://redis.io/technology/durable-redis/)

# 併用パターン — 実戦では組み合わせるのが普通

DynamoDB と Redis は競合するのではなく、**役割分担で両方効く** のが実戦です。先行記事の **Polyglot Persistence** をこの 2 プロダクトで具体化すると次のパターンになります。

## パターン A: RDBMS / DynamoDB + Redis cache-aside

最も普通の構成。**backing store は RDBMS または DynamoDB、Redis は読み取りキャッシュ**。

```
Client → (1) GET cache key → Redis
      ← cache miss
Client → (2) Read from DB → DynamoDB / PostgreSQL
      ← data
Client → (3) SET cache key TTL → Redis
```

- キャッシュミスで DB に抜け、結果をキャッシュに書く
- **thundering herd**(同じキーに大量リクエストが同時に来る)で DB が潰れないよう、lock やシングルフライトで制御
- TTL を必ず付ける(アンチパターン #5)

> 根拠: [Redis caching solutions](https://redis.io/solutions/caching/), [Cache optimization strategies](https://redis.io/blog/guide-to-cache-optimization-strategies/)

## パターン B: DynamoDB + DAX

DynamoDB と API を直結で統一したい、**microseconds レイテンシが欲しい、汎用性は不要** の場合の選択肢。

- Redis と違い、アプリコード上は DynamoDB SDK のまま(DAX クライアント経由)
- **item cache は `GetItem` 系のみ**。GSI / LSI クエリをキャッシュしたいなら query cache
- 50 ノード上限、Redis ほど柔軟なデータ構造は無い

「Redis を別運用するほどじゃないが、DynamoDB の single-digit ms では足りない」場面にはまります。

## パターン C: Redis で session / rate limit / leaderboard、永続データは別

Redis の**得意技(TTL / Sorted Set / 分散ロック)だけ** を使う構成。

- session store: `SET session:<id> ... EX 3600`
- rate limit: Sorted Set に timestamp で push + 古い要素削除
- leaderboard: `ZADD` + `ZREVRANGE`

永続が要る業務データ(顧客、注文、請求)は **RDBMS か DynamoDB** に置く。「Redis は消えていい前提」で運用する。

## パターン D: Read-through / Write-through / Write-behind

キャッシュと backing store の **書き込み経路** を変えるパターン。トレードオフが重要です。

| パターン | 書き込み経路 | 整合性 | 性能 |
|---|---|---|---|
| **Cache-aside**(A と同じ) | アプリ → DB + アプリ → cache(別々) | アプリ責任 | 一般的 |
| **Read-through** | cache miss 時にキャッシュが DB フェッチ | アプリ責任 | A とほぼ同等 |
| **Write-through** | アプリ → cache → DB(同期) | cache と DB が常に一致 | 書き込みレイテンシ増 |
| **Write-behind** | アプリ → cache(即返却) → 非同期で DB | cache と DB が一時乖離 | 書き込み最速、DB 反映遅延 |

Write-through は cache と DB の dual-write 問題(片方だけ成功するケース)があり、完全な整合性は得られません。Write-behind はさらに遅延を許容する代わりにバッファリングできます。**実戦では cache-aside が最多**、特殊要件があるときだけ read-through / write-through / write-behind に寄せるのが現実解です。

> 根拠: [Three ways to maintain cache consistency](https://redis.io/blog/three-ways-to-maintain-cache-consistency/), [Why your caching strategies might be holding you back](https://redis.io/blog/why-your-caching-strategies-might-be-holding-you-back-and-what-to-consider-next/)

# アンチパターン — 両者固有の "踏み抜き"

先行記事のアンチパターンに重ねて、**DynamoDB / Redis 固有** に絞って列挙します。

## DynamoDB 固有

1. **低 cardinality な PK**: `status`, `country`, boolean を PK にして数 partition しか使えない
2. **時刻そのまま PK**: `order_date` を PK にすると「今日」の partition にだけ書き込みが集中する
3. **UID / sequence を "PK として使わない PK" にする**: RDB 出身のクセで付けた UID が PK だが、検索には GSI 経由しか使えない
4. **GSI の WCU 不足でベースごとスロットル**: GSI の WCU 設計漏れは本番事故の定番
5. **Scan をアプリの通常パスで使う**: 全件スキャンは RU とレイテンシの両方が悪化する。バッチ以外では使わない
6. **Single-Table Design の教科書を "1 テーブル絶対" として適用**: 関連しないエンティティまで同居させてインデックス設計が破綻する
7. **Streams 下流が 24h 以上詰まる**: Streams の保持は 24 時間のみ、超過分は復旧不可
8. **Global Tables で同一 item をマルチリージョン同時更新**: LWW で結果が予測困難

## Redis 固有(Redis 公式の 10 アンチパターンから抜粋)

1. **#5 TTL 無しキャッシュ**: メモリ無制限増大と eviction storm
2. **#7 Hot key**: 99 ノードクラスタで 1 key に 100 万 req/s が集中 → 1 ノードに全部飛ぶ
3. **#8 `KEYS` コマンドを本番で使う**: Redis をブロックする O(N) full scan。本番では `SCAN` の iteration を使う
4. **#9 Ephemeral Redis を primary database として使う**: 再起動時のデータロス、永続化と HA 前提でないと primary は無理
5. **#10 JSON blob を String に格納**: field 単位 atomic update が不可能、全 read/update で blob 全体転送
6. **MULTI のロールバック無しを理解せず書く**: 文字列 key に `INCR` → 他コマンドは実行される
7. **Cluster で hash tag なしに multi-key 操作**: `CROSSSLOT` エラーで EXEC ごと破棄
8. **Pipelining をせず大量コマンドを serial に送る**: RTT で数倍の時間を浪費(アンチパターン #4)

> 根拠: [Redis Anti-Patterns](https://redis.io/tutorials/redis-anti-patterns-every-developer-should-avoid/), [Choosing the Right DynamoDB Partition Key](https://aws.amazon.com/blogs/database/choosing-the-right-dynamodb-partition-key/)

# 判断フロー — いつ DynamoDB、いつ Redis、いつ両方

先行記事の判断フローを、KV 型に特化して詳しく書き直します。上から順に最初に Yes になったところが答えです。**「両方」が答えの場面も多い** 点を忘れないでください。

1. **データが一時的 / キャッシュ / 揮発で OK**、または **多様なデータ構造が必要(リーダーボード、rate limit、セッション、分散ロック、pub/sub)** → **Redis**
2. **永続、high throughput、AWS ネイティブ、サーバーレス志向** → **DynamoDB**
3. **sub-millisecond レイテンシが必須** → **Redis**、または DynamoDB が既に採用済みなら **DynamoDB + DAX**
4. **グローバルで active-active に書きたい**:
   - LWW を受け入れられる → **DynamoDB Global Tables**
   - データ構造の CRDT マージが必要 → **Redis Enterprise Active-Active**
5. **複雑な atomic 操作を "データ構造側で" やりたい**(Sorted Set の rate limit、分散ロック、priority queue) → **Redis**
6. **multi-item ACID が要件の中核**:
   - 単一リージョン、100 アクション / 4 MB 以内 → **DynamoDB TransactWriteItems**
   - それ以上の複雑性 → **RDBMS**
7. **上記どれにも強く当てはまらない** → **RDBMS** を起点に、必要な領域だけ KV に切り出す

そして、**ほとんどのシステムは "片方だけ" では終わりません**。

- **DynamoDB / RDBMS を永続、Redis をキャッシュ兼ミドルウェア**
- **DynamoDB + DAX でキャッシュまで DynamoDB に閉じる**

この 2 つが主要な実戦パターンで、どちらが良いかは運用の複雑性(Redis を別運用できる体力)と機能要件(汎用データ構造が要るか)で決まります。

# まとめ

- **DynamoDB と Redis は同じ KV でも目的が違う**: 永続スケールアウト KV と、インメモリ多機能ストア
- **DynamoDB の 4 軸**: partition key(3,000 RU / 1,000 WU / 10 GB)、Single-Table、GSI & LSI、課金モード
- **DynamoDB 固有の武器**: TransactWriteItems(100 アクション / 4 MB)、Streams(24h CDC)、Global Tables(LWW)、DAX(μs レイテンシ)
- **Redis の 4 軸**: 多データ構造、永続化(RDB / AOF / hybrid)、Cluster(16,384 slot + hash tag)、TTL と 8 種 Eviction Policy
- **Redis の独自機能**: Pipelining(5 倍速)、MULTI/EXEC(ロールバック無し)、WATCH(CAS)、Lua / Functions
- **整合性と耐久性**: DynamoDB は DB 側で信用できる、Redis は自分で選ぶ
- **アンチパターン**: 低 cardinality PK / Scan / GSI スロットル / TTL 無し / Hot key / `KEYS` / Ephemeral as primary / CROSSSLOT
- **実戦は併用が普通**: cache-aside、DAX、session & rate limit、write-through / write-behind
- **迷ったら**: 揮発 + 多構造なら Redis、永続 + AWS なら DynamoDB、sub-ms 必須なら Redis or DAX、両方いるなら両方

「KV だからシンプル」ではなく、**どちらの KV かで設計軸が全く別** ということを頭に残せれば、この記事のゴールです。

# 参考資料

## DynamoDB

### パーティションキー / Single-Table

- [Best practices for designing partition keys](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-partition-key-design.html)
- [Designing partition keys to distribute workload](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-partition-key-uniform-load.html)
- [Choosing the Right DynamoDB Partition Key (AWS Blog)](https://aws.amazon.com/blogs/database/choosing-the-right-dynamodb-partition-key/)
- [Single-table vs multi-table design (AWS Blog)](https://aws.amazon.com/blogs/database/single-table-vs-multi-table-design-in-amazon-dynamodb/)
- [Creating a single-table design (AWS Compute Blog)](https://aws.amazon.com/blogs/compute/creating-a-single-table-design-with-amazon-dynamodb/)

### インデックス / キャパシティ

- [Using Global Secondary Indexes](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GSI.html)
- [Service, account, and table quotas](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Constraints.html)
- [Burst and adaptive capacity](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/burst-adaptive-capacity.html)
- [Right-Sized Provisioning](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/CostOptimization_RightSizedProvisioning.html)

### Streams / Global Tables / DAX

- [Change data capture for DynamoDB Streams](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Streams.html)
- [Streams and Lambda triggers](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Streams.Lambda.html)
- [StreamSpecification (API)](https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/API_StreamSpecification.html)
- [Global Tables](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/GlobalTables.html)
- [Global Tables V2 How it works](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/V2globaltables_HowItWorks.html)
- [Global Tables V1 How it works](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/globaltables_HowItWorks.html)
- [DAX config considerations](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/dax-config-considerations.html)

## Redis

### 全体 / データ構造

- [What is Redis?](https://redis.io/tutorials/what-is-redis/)
- [Redis Anti-Patterns](https://redis.io/tutorials/redis-anti-patterns-every-developer-should-avoid/)

### Cluster / Scaling

- [Redis Cluster Specification](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/)
- [Scale with Redis Cluster](https://redis.io/docs/latest/operate/oss_and_stack/management/scaling/)
- [CLUSTER KEYSLOT](https://redis.io/docs/latest/commands/cluster-keyslot/)
- [Redis Clustering best practices with keys](https://redis.io/blog/redis-clustering-best-practices-with-keys/)

### 永続化 / 設定

- [Redis persistence](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)
- [Durable Redis](https://redis.io/technology/durable-redis/)
- [redis.conf (maxmemory-policy 列挙)](https://download.redis.io/redis-stable/redis.conf)
- [Caching at Scale with Redis (PDF)](https://redis.io/wp-content/uploads/2021/12/caching-at-scale-with-redis-updated-2021-12-04.pdf)

### Pipelining / Transactions / Lua

- [Redis pipelining](https://redis.io/docs/latest/develop/use/pipelining/)
- [Transactions](https://redis.io/docs/latest/develop/interact/transactions/)
- [EVAL intro (Lua)](https://redis.io/docs/latest/develop/programmability/eval-intro/)

### キャッシュパターン

- [Redis caching solutions](https://redis.io/solutions/caching/)
- [Cache optimization strategies](https://redis.io/blog/guide-to-cache-optimization-strategies/)
- [Three ways to maintain cache consistency](https://redis.io/blog/three-ways-to-maintain-cache-consistency/)
- [Why your caching strategies might be holding you back](https://redis.io/blog/why-your-caching-strategies-might-be-holding-you-back-and-what-to-consider-next/)
