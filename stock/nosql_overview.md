---
title: "NoSQL をもう一度ちゃんと整理する — SQL との対比で理解する使い所とアンチパターン"
emoji: "🗄"
type: "tech"
topics: ["nosql", "sql", "database", "rdbms", "architecture"]
published: true
---

# はじめに — 「とりあえず NoSQL」の危うさ

「スケールしそう」「JSON そのまま入る」「速い」というふわっとしたイメージで NoSQL が選ばれる場面は多いです。ところが運用に入ると、ホットパーティションで詰まる、クエリがうまく書けない、データ修正に数日かかる、といった形で跳ね返ってきます。

本記事は、特定ベンダーの紹介ではなく **NoSQL 全般を SQL(RDBMS)との対比で整理** し、さらに **モデリング例・パーティションキー設計・整合性の寄せ方・併用パターン・選定観点** まで踏み込むことで、「整理記事」ではなく **設計判断に使える記事** にすることを目指します。

扱う軸は次のとおりです。

- NoSQL とは何か(非リレーショナルの本質)
- SQL との違い(6 軸比較)
- 4 タイプ(Key-Value / Document / Wide-Column / Graph)
- **具体モデリング例: 注文データを SQL と Document でどう持つか**
- **NoSQL で最初に壊れる設計: パーティションキー**
- 有効シナリオとアンチパターン
- **NoSQL で整合性をどう寄せるか(Saga / Outbox / 冪等性)**
- **二者択一ではない併用パターン**
- 製品選定の観点と判断フロー

主張を先に書きます。**NoSQL は "SQL の上位互換" ではなく、トレードオフの違う別の選択肢です**。この前提が崩れると、設計判断の多くが歪みます。

# NoSQL とは何か(非リレーショナルの本質)

NoSQL は "Not Only SQL" の略で、**リレーショナルモデル(行と列の固定スキーマ、外部キー、JOIN、ACID)をあえて捨てる代わりに別の何かを取る** データベースの総称です。得るものは主に 3 つ。

- **柔軟なスキーマ**: 事前定義なし、ドキュメントごとに属性が違ってもよい
- **水平スケール**: ノード追加でスループットと容量を伸ばす
- **分散環境下の可用性**: 一部ノード障害でも読み書きを続けられる

このトレードオフは CAP 定理(Consistency / Availability / Partition tolerance のうち、ネットワーク分断下で同時に成立するのは 2 つまで)でも語られます。歴史的には RDBMS = CP 寄り、NoSQL = AP 寄りと整理されがちですが、**現代の NoSQL は設定で強整合性も選べる** ものが多く、「NoSQL = 結果整合のみ」は単純化しすぎです。

整合性モデルの略語は押さえておきます。

- **ACID**(RDBMS で一般的): Atomicity / Consistency / Isolation / Durability。一連の操作が**まとめて成功するか、まとめて失敗する**ことを保証する
- **BASE**(多くの NoSQL の既定): Basically Available / Soft state / Eventually consistent。**可用性とスケールを優先し、結果整合でよい**という考え方

銀行の振込のように「途中で止まると困る」仕事は ACID 向き、アクセスログのように「最終的に揃っていれば十分」な仕事は BASE で十分、というのが基本の感覚です。

# SQL との比較(6 軸)

| 軸 | SQL (RDBMS) | NoSQL |
|---|---|---|
| データモデル | 行と列のテーブル | Key-Value / Document / Wide-Column / Graph |
| スキーマ | 事前定義、厳格 | 動的 / 柔軟 / スキーマレス |
| 整合性 | ACID(強整合) | BASE が基本、設定次第で強整合も |
| スケーリング | 基本は垂直(Scale Up) | 基本は水平(Scale Out) |
| クエリ | 標準 SQL、複雑な JOIN / 集計 | 製品ごとに独自、JOIN は苦手または非対応 |
| 関係性 | 外部キー + 正規化 | デノーマライズ + 埋め込み |

重要な 3 軸を掘り下げます。

## スキーマ: 柔軟さの代償は「アプリ側でスキーマを守る責務」

RDBMS ではスキーマ違反は DB が蹴ります。NoSQL では通ってしまいます。**DB が面倒を見ていた型や必須項目のチェックを、アプリ側のバリデーション層で負う** ことになります。短期的には楽ですが、チームが増えてコードベースが広がると一貫性の担保が難しくなります。

## 整合性とスケール: 両立はタダではない

RDBMS の水平スケールは読み取り専用レプリカなら比較的楽ですが、読み書きの水平スケールはシャーディングなど特別な工夫が必要です。NoSQL は**最初から水平スケールを想定**しており、ノードを足すほど線形に伸ばしやすい設計です。ただしその代償として、分散ノードをまたぐ強整合トランザクションは高コスト、または制限つきです。

## JOIN と関係性: 多 JOIN を移植してはいけない

RDBMS の強みは JOIN を伴う複雑クエリです。NoSQL ではこれをそのまま移植せず、**一緒に使うものを一緒に保存する**(デノーマライズ / 埋め込み)方向に倒します。関連データをアプリ側で都度寄せ集めると、RDBMS なら 1 本の SQL になる処理が N+1 API 呼び出しに化けます。

# NoSQL の 4 タイプと向き不向き

NoSQL はひとくくりに語れません。**「NoSQL を選ぶ」ではなく「どのタイプを選ぶ」** が本当の問いです。

## Key-Value ストア

- **代表例**: Redis、DynamoDB、Memcached
- **得意**: キー 1 発の超高速 lookup、キャッシュ、セッション、設定値
- **苦手**: 範囲検索、属性フィルタ、集計

「このキーに対する値をくれ」が 9 割の世界で輝きます。「年齢 16〜24 で好物がワッフルで、直近 24 時間にログインしたユーザーを全員くれ」と言われると詰みます。

## Document(ドキュメント)

- **代表例**: MongoDB、CouchDB、Cosmos DB(NoSQL API)
- **得意**: 半構造化データ、アプリのオブジェクトをそのまま保存、アジャイルに属性が増える領域
- **苦手**: 多テーブル JOIN、強い関係整合性

ドメインオブジェクトを JSON 的に保存し、**"一緒に読むもの"を 1 ドキュメントに凝集** する設計に向きます。

## Wide-Column(列指向 / Column-Family)

- **代表例**: Cassandra、HBase、Bigtable
- **得意**: 書き込みスループット、時系列、巨大ログ
- **苦手**: アドホックな絞り込み、JOIN、トランザクション

「書き込みが毎秒数万〜数十万で、クエリパターンは決まっている」領域が主戦場です。

> :bulb: **「列指向」という語の注意**
> 同じ「列指向」という訳語で呼ばれる分析特化のカラムナー DB(BigQuery、Redshift、ClickHouse など)とは別物です。NoSQL の Wide-Column は **行キーごとに列ファミリを持つ分散 KV 寄りの構造** で、OLTP 的な書き込みを得意とします。分析特化のカラムナー DB は **列単位で列値を連続格納し、OLAP の集計スキャンを高速化** するのが目的で、設計思想も用途も異なります。

## Graph

- **代表例**: Neo4j、Neptune、Cosmos DB(Gremlin API)
- **得意**: 関係の深さを辿る探索(SNS の友達の友達、推薦、不正検知、権限グラフ)
- **苦手**: 大量のバルクスキャン、ヘビーな集計

「データそのものより関係に価値がある」ケース向けです。RDBMS で再帰 JOIN を大量に書き始めたら、Graph DB 検討のサインです。

## 比較表

| 特性 | Key-Value | Document | Wide-Column | Graph |
|---|---|---|---|---|
| データモデル | キーと値 | JSON 風ドキュメント | 行キー + 列ファミリ | ノードと辺 |
| 得意 | キー直取り | 半構造化の凝集 | 書き込み・時系列 | 関係の探索 |
| スキーマ | 事実上なし | 柔軟 | 半構造化 | スキーマレス |
| 代表例 | Redis / DynamoDB | MongoDB / Cosmos DB | Cassandra / HBase | Neo4j / Neptune |

# 具体モデリング例: 注文データを SQL と Document でどう持つか

抽象論だけでは掴みにくいので、「EC サイトの注文」という定番の題材で RDBMS と Document をモデリング比較します。

## RDBMS のモデル(正規化)

```
customers(id, name, email)
products(id, name, price, stock)
orders(id, customer_id, ordered_at, total)
order_items(id, order_id, product_id, qty, unit_price)
```

- 注文一覧画面は JOIN 1 本で組み立てられる
- 商品マスタ更新(価格変更、名称変更)は `products` の 1 行を直すだけ
- 在庫の整合性、外部キー制約は DB が守る

## Document のモデル(埋め込み)

```json
{
  "_id": "order_001",
  "orderedAt": "2026-04-18T10:00:00Z",
  "customer": {
    "customerId": "cust_123",
    "name": "Alice",
    "email": "alice@example.com"
  },
  "items": [
    {
      "productId": "prod_001",
      "name": "Mechanical Keyboard",
      "unitPrice": 14900,
      "qty": 1
    },
    {
      "productId": "prod_002",
      "name": "USB-C Cable",
      "unitPrice": 1290,
      "qty": 2
    }
  ],
  "total": 17480
}
```

- 注文詳細画面は**このドキュメント 1 本を読むだけ**で完結
- `items[].name` や `unitPrice` は **注文時点のスナップショット**。後から商品マスタの価格が変わっても注文側は動かない(そもそも履歴として動いてはいけない)
- `productId` / `customerId` は参照として残す。商品の詳細が必要なら別 collection を引く

## どこまで埋め込み、どこから分けるか

判断軸は 3 つ。

| 軸 | 埋め込み | 参照(分ける) |
|---|---|---|
| 件数 | 有界(1 注文あたり高々数十件) | 無限成長(1 商品に紐づく全注文、1 投稿の全コメント) |
| 変化頻度 | ほぼ不変(スナップショット的) | 頻繁に独立で更新される |
| 読み方 | ほぼ一緒に読む | 単独で検索・更新する |

この記事の注文例では、`items` は注文あたり件数が有界で、しかも「注文時点のスナップショット」として残したいため埋め込み。一方で `customer` は **「現在のメール」も欲しい場面がある** ならフルに埋め込まず、`customerId` + 最小スナップショットに留めるのが無難です。

## よくある失敗

- **商品を丸ごと埋め込む**: 商品マスタ更新のたびに全注文を書き換える羽目になる
- **配送ステータス履歴を 1 注文に無限追記**: ドキュメントサイズ上限(MongoDB は 16MB など)に近づいてインデックスが劣化する。上限を超えたら書き込み失敗
- **何でも分けてしまう**: RDBMS のクセで全部参照にすると、Document のメリット(読み取り 1 発、ローカルな原子更新)を失う

# シナリオで学ぶ: NoSQL が有効なパターン

4 タイプそれぞれに典型シナリオを 1 本。

## A: セッション / ユーザー設定を爆速で取得したい

- **要件**: ユーザー ID から設定値を毎リクエスト取得、ミリ秒未満、書き込みは稀、数千万ユーザー
- **SQL**: 可能だが、RDBMS をキャッシュ代わりに酷使。接続プールも逼迫しがち
- **NoSQL**: **Key-Value** が最適

## B: EC サイトの商品カタログ(属性が商品ごとにバラバラ)

- **要件**: 家電、衣類、食品が同じサイトに並ぶ。属性がカテゴリで全然違う
- **SQL**: EAV(Entity-Attribute-Value)にねじ込むとクエリが汚くなる
- **NoSQL**: **Document**。商品ごとに属性セットが違う JSON を入れる

## C: IoT / アプリログの時系列大量書き込み

- **要件**: 数十万デバイスから毎秒メトリクス、読みは「デバイス X の直近 N 時間」中心
- **SQL**: 書き込みがボトルネック、パーティショニング運用が重い
- **NoSQL**: **Wide-Column**。デバイス ID + タイムスタンプをキーに

## D: フォロー関係の「友達の友達」/ 不正検知

- **要件**: 関係を数ホップ辿る。例: 3 ホップ以内に共通の送金相手がいるか
- **SQL**: 再帰 CTE や多段 JOIN。ホップ数が増えるほど壊れる
- **NoSQL**: **Graph**。グラフトラバーサルで書ける

# NoSQL で最初に壊れる設計: パーティションキーとアクセスパターン

NoSQL で本当に事故るのはここです。**章 1 つ使って深掘りする価値がある** ポイントです。

## なぜパーティションキーが最重要か

NoSQL の水平スケールは「キーで分散する」ことが前提です。キーを間違えるとノードが均等に使われず、特定ノードだけが過負荷になります。そして厄介なことに、**パーティションキーは事実上変更不可**です。後から変えるにはデータ全再配置、もしくはテーブル作り直しが必要になります。

物理的な制約もあります。たとえば DynamoDB は 1 パーティションあたり 10GB / 読み 3000RU / 書き 1000WU、Cosmos DB は論理パーティションあたり 20GB が上限です。「無限に書ける」わけではありません。

## 悪いキー

- **`isActive`(boolean, 低 cardinality)**: 2 パーティションにしか分かれない。事実上スケールしない
- **`country`(偏りが大きい)**: 日本ユーザーが大半のサービスで日本パーティションに集中
- **`created_at`(時刻そのまま)**: **今日**のパーティションに書き込みが集中する典型的ホットパーティション。過去パーティションは書き込まれずコールドになり、プロビジョンスループットも無駄
- **`status` / `type` / `category`**: 取りうる値が数個しかなく、低 cardinality。特定の値に偏ると不均衡

## 少しマシなキー

- **`customerId` / `userId`**: cardinality が高く、均等分散しやすい
- ただし**ヘビーユーザーが数人**いると、その人のパーティションだけ熱くなる問題は残る
- マルチテナント SaaS で `tenantId` にすると、**特定テナントが大きすぎる** と 20GB 上限に刺さる

## よくある妥協案(複合キー / ハッシュサフィックス)

完璧なキーは普通ない、と前提した上で。

- **`userId#yyyyMM`**: ユーザー単位で時間で切る。サイズを抑えつつ、ユーザー単位の読みを維持
- **`tenantId#userId`**: テナントで分散しつつ、テナント内は user で分ける
- **`customerId#shardNo` (0〜N-1 のランダム)**: 書き込みを N シャードに撒く(write sharding)。代わりに**読み取りは N 倍のファンアウト** になる
- **`createdAt_bucket + randomSuffix`**: 時系列でもホットを避けたい場合

どれも「完璧」ではなく、**書きと読みの間でどのトレードオフを取るか** という話です。

## 原則

- 最初に **アクセスパターン**(どう読み、どう書くか)を洗い出す
- その上で **均等分散するキー** を選ぶ
- **書き読みの両方**を想定する(片方だけ最適化すると、もう片方が破綻する)
- 必要なら**複合キー**で時間やテナントを織り込む
- 本番投入前に **キー分布の偏り** を実データで確認する

パーティションキーは「後で直せばいい」ものではありません。**最初の設計で決まる** と思ったほうが安全です。

# シナリオで学ぶ: NoSQL のアンチパターン

経験上ハマりやすいものを 6 つ挙げます。

## アンチパターン 1: 銀行口座の振込のような多エンティティトランザクション

「A から引き、B に足す」を**同時に成立させるか、同時に失敗させるか**しか許されない処理は、ACID の atomicity と consistency の典型で、RDBMS が得意な領域です。NoSQL でも multi-document ACID を持つ製品はありますが、「できる」と「得意」は違います。

## アンチパターン 2: 多表 JOIN 前提のレポート / ダッシュボード

「顧客 × 注文 × 明細 × 商品」を JOIN して集計するレポートは SQL の独壇場です。NoSQL に移すと **アプリ側で JOIN を書き直す** ことになり、往復回数が増えてレイテンシもコストも悪化します。分析用途なら、DWH や分析 DB を横に置くほうが筋が通ります(アンチパターン 6 とも関連)。

## アンチパターン 3: スキーマレスを盾にした雑ドキュメント設計

「スキーマを持たなくていい」ではなく「**スキーマを DB に守らせない**」にすぎません。

- **Unbounded arrays**: 1 ドキュメント内に無制限に伸びる配列(投稿に対する全コメント埋め込みなど)。ドキュメントサイズ上限やインデックス性能に刺さる
- **Bloated documents**: ドキュメントが肥大化し、関係ないフィールドも毎回読み出す羽目に

## アンチパターン 4: ホットパーティション(章 7 の復習)

パーティションキーを `country` や生の `created_at` にして、特定ノードだけが熱くなる失敗。章 7 のとおり、**キー設計を真面目にやる** 以外に根本対処はありません。

## アンチパターン 5: クエリパターンを決めずに設計を始める

RDBMS は後から WHERE やインデックスを足せば何とかなることが多いですが、NoSQL は**アクセスパターン駆動設計**が原則です。「どう問い合わせるか」が決まっていないなら、**NoSQL は早計です**(ここは危険と言い換えても同じ意味)。

## アンチパターン 6: 運用 DB と分析 DB を兼ねようとする

よくある失敗。運用トラフィックを捌いている NoSQL 本体に、社内レポートやダッシュボードのクエリをそのままぶつける。結果として、オンライン処理のレイテンシが悪化し、プロビジョンスループットも食い潰します。

**対処**: 分析用途は素直に DWH / 分析 DB / 読み取り専用レプリカに分離する。CDC(Change Data Capture)やストリーミングで別系統へ流すのが定番です。「1 つの DB で全部」を目指さない。

# NoSQL で整合性をどう寄せるか

「強整合が要るなら RDBMS」で終わらせず、NoSQL 寄りの世界で整合性をどう扱うかを軽く触れておきます。**単なる比較記事から設計記事に上げる** ための肝です。

## 冪等性(Idempotency)

同じリクエストを 2 回処理しても結果が同じになる設計。分散環境ではネットワーク的にリトライが発生するのが前提なので、**冪等性は前提スキル** です。

実装例:

- リクエスト ID(clientRequestId)を保持し、すでに処理済みなら前回結果を返す
- 「追加」ではなく「set」「upsert」ベースで書く
- カウンタのインクリメントは「既にインクリメント済みか」を記録する

## リトライと DLQ(Dead Letter Queue)

結果整合は「いつか揃う」前提。揃わないイベントをどう扱うかも設計に含めます。

- 一定回数までリトライ
- 超えたら DLQ に退避して人が見る / 自動リトライする
- タイムアウトは短めに、リトライは冪等前提で

## Saga パターン

多サービス / 多エンティティにまたがる処理を、**ローカルトランザクションと補償トランザクションの連鎖** で実現するパターン。2PC(2 相コミット)を避けたい分散システムで広く使われます。

- **オーケストレーション型**: 中央のコーディネータが各ステップを順に呼ぶ。監視しやすいが、コーディネータがボトルネック
- **コレオグラフィ型**: 各サービスがイベントを発行して反応する。スケールするが、全体の流れが見えづらい

例: 注文確定で「在庫確保 → 決済 → 出荷予約」と進め、決済で失敗したら**補償**として「在庫を戻す」を実行する。

## Outbox パターン

「DB 書き込みとメッセージ送信を同時に成立させる」という dual-write 問題への定番解です。

1. 業務データの更新と**同じトランザクション**で `outbox` テーブルにイベントを書く
2. 別プロセス(ポーラーや CDC)が `outbox` を読んでメッセージブローカに配信
3. 配信済みフラグを立てる

これにより、**DB 書き込みは成功したがメッセージが飛ばなかった**(逆もまた然り)という不整合を防げます。

## まとめ

NoSQL を選ぶなら、「ACID 一発で済ませる」ではなく **「結果整合を前提に、冪等性とイベント連携で揃える」思考** に切り替える必要があります。逆に、この思考を組織がまだ持っていない段階で NoSQL に飛びつくと、アンチパターンに一直線です。

# 実務では二者択一ではない: RDBMS と NoSQL の併用パターン

現実のシステムは「どちらか」ではなく「組み合わせ」です。このように役割ごとに適切なストアを選ぶ発想を **Polyglot Persistence(ポリグロット永続化)** と呼びます。

## パターン A: 本体 RDBMS + キャッシュに Key-Value

最も普通の構成。RDBMS の前に Redis 等を置き、読み取りの大半をキャッシュで返す。TTL やキー設計の手間はあるが、効果が大きい。

## パターン B: 本体 RDBMS + 検索は全文検索エンジン

キーワード検索、日本語の形態素解析、ファセット検索などは RDBMS の LIKE では限界がある。OpenSearch / Elasticsearch 相当に非同期で流す。**検索インデックスは結果整合でよい** ケースが多い。

## パターン C: トランザクションは RDBMS、イベント / ログは Wide-Column

監査ログや操作ログ、イベントストリームは書き込み量が桁違い。これらは Wide-Column 系に逃がし、RDBMS は**ビジネスの整合性が要る部分** に集中させる。

## パターン D: マスタは RDBMS、プロファイル / 設定は Document

ユーザープロファイルや設定は「人によって属性がバラバラ」「頻繁に増減する」性質があり Document 向き。請求や契約情報は RDBMS。

## パターン E: 運用と分析を分離

運用 DB(RDBMS でも NoSQL でも)から、CDC やストリーミングで DWH / 分析 DB に流す。ダッシュボードや重集計はそちらで。**運用の性能を守る** ための基本形。

## 注意点

- **データの二重管理** は必ず発生する。どちらが master of record かを決める
- **整合性の責任** を Saga / Outbox / CDC のどれで取るかを明示する
- **運用対象が増える**。運用負荷と恩恵を天秤にかける

# 製品選定の観点

「4 タイプのどれか」だけで終わらせず、実務の選定では次の軸も必ず見るべきです。

| 観点 | 見るべきこと |
|---|---|
| トランザクション範囲 | 単一キーのみ / パーティション内 / パーティションまたぎ / マルチドキュメント。要件に合うか |
| セカンダリインデックス | 有無、**強整合 or 結果整合**、インデックスあたりの課金、更新時の書き込み増幅 |
| 整合性レベル | 強整合 / 有界陳腐化 / セッション / 結果整合 など、選べる粒度 |
| TTL | 自動失効が使えるか。ログやセッションで効く |
| バックアップ / PITR | Point-in-Time Restore の粒度と保持期間 |
| リージョン冗長 | マルチリージョン書き込みの可否、**コンフリクト解決の挙動**(LWW / カスタム) |
| 課金モデル | プロビジョンド / オンデマンド、ストレージ、RU / WCU などの単位、読み書きの非対称性 |
| 運用負荷 | マネージド度、オートスケールの滑らかさ、監視の自動連携 |
| エコシステム | ドライバ、言語サポート、マイグレーションツール、運用ツール |
| パーティション上限 | サイズ上限(例: DynamoDB 10GB / Cosmos DB 20GB)、スループット上限 |

プロダクト選定は **タイプ選定で 5 割、これらの運用観点で残り 5 割** が決まると思っていいです。

# 判断フロー / チェックリスト

迷ったら上から順に。最初に Yes になったところが答えです。

1. クエリパターンがまだ固まっていない → **RDBMS で始める**(プロトタイプ含む。早計に NoSQL に飛びつくと後悔しやすい)
2. 多エンティティにまたがる強整合なトランザクションが中核要件 → **RDBMS**
3. キー 1 発の高速アクセスが 9 割以上 → **Key-Value**
4. スキーマが頻繁に揺れる、または要素ごとに属性がバラバラ → **Document**
5. 書き込みスループット優先で、時系列 / ログ的データ → **Wide-Column**
6. データの価値が「関係」そのもの → **Graph**
7. どれにも強く当てはまらない → **RDBMS**(NoSQL を選ぶ積極的理由がない)

そして大事なこととして、**単体ではなく複数組み合わせ**(Polyglot Persistence)の選択肢も常に残してください。実務では多くがハイブリッドです。

# まとめ

- NoSQL は SQL の上位互換ではなく、**トレードオフの違う別の選択肢**
- 4 タイプは得意領域が違う。**「NoSQL を選ぶ」ではなく「どのタイプを選ぶ」**
- 注文データのような題材では、**埋め込みと参照の境界** を判断軸(有界性 / 変化頻度 / 読み方)で決める
- **パーティションキーは最初の設計で決まる**。後からの修正は極めて重い
- 整合性は「諦める」ではなく、**冪等性 / Saga / Outbox で寄せる**
- 現実は二者択一ではなく**適材適所の併用**(Polyglot Persistence)
- 製品選定は **タイプ + 運用観点** の両輪
- 迷ったら RDBMS から始め、根拠のある領域だけ NoSQL に切り出すのが安全
- 「何を問い合わせるか」が決まっていない段階で NoSQL を選ぶのは **早計 / 危険**

# 参考資料

## 全体・比較

- [AWS — Relational vs Nonrelational Databases](https://aws.amazon.com/compare/the-difference-between-relational-and-non-relational-databases/)
- [MongoDB — Relational Vs. Non-Relational Databases](https://www.mongodb.com/resources/compare/relational-vs-non-relational-databases)
- [GeeksforGeeks — Types of NoSQL Databases](https://www.geeksforgeeks.org/dbms/types-of-nosql-databases/)
- [insightsoftware — Relational vs. Non-Relational Databases](https://insightsoftware.com/blog/whats-the-difference-relational-vs-non-relational-databases/)
- [InterSystems — NoSQL Databases Explained](https://www.intersystems.com/resources/nosql-databases-explained-advantages-types-and-use-cases/)
- [ByteHouse — SQL and NoSQL Databases](https://bytehouse.cloud/blog/sql-and-nosql-databases)
- [Rivery — Relational vs NoSQL](https://rivery.io/data-learning-center/relational-vs-nosql-databases/)
- [Stack Overflow — Column Family vs Key-Value vs Document vs Graph](https://stackoverflow.com/questions/21949093/when-should-i-use-a-column-family-nosql-solution-vs-key-value-document-store-g)

## モデリング(注文・埋め込み vs 参照)

- [Mingo — Embedding vs Referencing in MongoDB](https://mingo.io/blog/mongodb-embedding-vs-referencing)
- [MongoDB Docs — Model Embedded One-to-Many](https://www.mongodb.com/docs/manual/tutorial/model-embedded-one-to-many-relationships-between-documents/)
- [OneUptime — Embedding vs Referencing](https://oneuptime.com/blog/post/2025-12-15-how-to-choose-between-embedding-and-referencing-in-mongodb/view)
- [GeeksforGeeks — Embedded vs Referenced](https://www.geeksforgeeks.org/mongodb/embedded-vs-referenced-documents-in-mongodb/)

## パーティションキー / アンチパターン

- [DynamoDB — Best practices for partition keys](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/bp-partition-key-design.html)
- [Azure Cosmos DB — Partitioning and horizontal scaling](https://learn.microsoft.com/en-us/azure/cosmos-db/partitioning)
- [OneUptime — Effective Partition Key Strategy in Cosmos DB](https://oneuptime.com/blog/post/2026-02-16-how-to-design-an-effective-partition-key-strategy-in-azure-cosmos-db/view)
- [Medium — Partitioning in NoSQL databases](https://medium.com/@sudhakan/partitioning-in-nosql-databases-4adeb61a44a0)
- [ScyllaDB — NoSQL Data Modeling Mistakes](https://www.scylladb.com/2023/09/11/nosql-data-modeling-mistakes-that-hurt-performance/)
- [MongoDB Docs — Schema Design Anti-Patterns](https://www.mongodb.com/docs/v8.0/data-modeling/design-antipatterns/)

## 整合性・Saga・Outbox

- [InfoQ — Saga Orchestration for Microservices Using the Outbox Pattern](https://www.infoq.com/articles/saga-orchestration-outbox/)
- [IJFMR — A Review of the Saga Pattern](https://www.ijfmr.com/papers/2025/4/54377.pdf)
- [dev.to — Mastering the Saga Pattern](https://dev.to/amitjkamble/mastering-the-saga-pattern-achieving-data-consistency-in-microservices-52c1)
- [RavenDB — ACID Transactions in NoSQL](https://ravendb.net/articles/acid-transactions-in-nosql-ravendb-vs-mongodb)
