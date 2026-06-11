---
title: "データエンジニアリング入門 — OLTPからレイクハウス、BIまで「データ基盤の地図」を一枚で"
status: plan
---

> 本記事は `articles/microsoft_fabric_overview.md`(Microsoft Fabric 概観記事)の **前段記事** として書く。
> Fabric 固有の準備に寄せず、データ基盤の一般概念を「地図」として提示し、巻末で各概念が Fabric のどこに対応するかを接続する。

## メタ情報(publish 時の想定)

- 想定 topics: `["dataengineering", "etl", "datalake", "lakehouse", "microsoftfabric"]`
- emoji 案: 🗺️(地図メタファ)
- type: tech / published: false
- 想定読者: アプリ開発・インフラ・クラウドの基礎はあるが「データ分析基盤」の世界が手薄なエンジニア(Fabric 記事の読者層と一致)
- トーン: ベンダー非依存の一般論 → 巻末で Fabric へ接続。各概念は「なぜそれが必要になったか」を必ず添える。

## 導入で解決する問題

Fabric 記事(や統合データプラットフォーム全般)は「データエンジニアリングの世界観」を前提に書かれている。OLTP/OLAP の分離、ETL/ELT、データレイク/ウェアハウス/レイクハウス、メダリオン、Direct Lake、ストレージとコンピュートの分離 — これらを知らないと、Fabric の「何が嬉しいのか」が読み取れない。本記事はその前提知識を、製品に依存しない「地図」として一枚で渡す。

## 全体ストーリー(なぜこの順か)

「データはどう生まれ、どう運ばれ、どこに溜まり、どう磨かれ、誰が使うのか」という **データの一生** をたどる順で並べる。各セクションは前の「困りごと」を次が解決する因果でつなぐ。最後にこの地図を Fabric 用語へマッピングして橋渡しする。

---

## セクション構成

### 1. はじめに — なぜ「データ基盤の地図」が必要か
- 主張: 統合データプラットフォーム(Fabric 等)は便利だが、前提概念を知らないと「何を解決した製品か」が分からない。本記事はその地図を渡す。
- 内容: 対象読者、ゴール(読み終えたら Fabric 記事がすらすら読める)、扱う/扱わない範囲。
- 根拠 URL: (導入のため特になし。Fabric 記事 `articles/microsoft_fabric_overview.md` を参照先として明記)

### 2. データエンジニアという仕事 — 役割・需要・隣接職種との違い
- 主張: データエンジニアは「分析の土台(パイプライン・蓄積・整形)」を作る人。データサイエンティスト/アナリストは「その土台の上で意味を取り出す」人。両者は補完関係で、需要は伸び続けている。
- 内容:
  - MS Learn の定義「構造化/非構造化データを統合・変換・集約し、分析に適した構造にする主役」を引用
  - データエンジニア vs データサイエンティスト vs アナリティクスエンジニア(IBM/AWS/DataCamp の整理)
  - 需要: BLS の data science 雇用見通し +34%(2023→2033)を「データ職全体の需要」の文脈で引用(※データエンジニア単独統計ではない点を明記)
- 根拠 URL:
  - https://learn.microsoft.com/en-us/training/paths/get-started-data-engineering
  - https://www.ibm.com/think/topics/data-engineer-data-vs-data-scientist-vs-analytics-engineer
  - https://aws.amazon.com/what-is/data-science
  - https://www.datacamp.com/blog/data-scientist-vs-data-engineer
  - https://ischool.syracuse.edu/data-engineer-vs-data-scientist (BLS 34%)

### 3. なぜ業務DBで分析してはいけないのか — OLTPとOLAPの分離
- 主張: 業務システムの DB(OLTP)は「1件ずつの読み書き」に最適化、分析(OLAP)は「大量スキャン・集計」に最適化。設計思想が逆なので、本番 OLTP に分析クエリをぶつけると業務が止まる。だから分析基盤を別に立てる。
- 内容:
  - OLTP=正規化・行指向・小容量・即時更新 / OLAP=非正規化(スタースキーマ)・列指向・大容量・履歴保持
  - 「業務 DB は分析向けに設計されていない」(MS Learn)
  - 列指向/HTAP に軽く触れる(深入りしない)
  - これがデータエンジニアリングの存在理由のひとつ、と接続
- 根拠 URL:
  - https://aws.amazon.com/compare/the-difference-between-olap-and-oltp
  - https://learn.microsoft.com/en-us/azure/well-architected/performance-efficiency/optimize-data-performance
  - https://learn.microsoft.com/en-us/azure/architecture/data-guide/relational-data/online-analytical-processing

### 4. データを運ぶ二つの流儀 — ETLとELT
- 主張: 昔は「変換してから入れる」ETL。クラウドの安いストレージと強力なエンジンが出てきて「入れてから変換する」ELT が主流に。Fabric/Databricks 等の現代基盤は ELT 前提。
- 内容:
  - ETL=Extract→Transform→Load(SSIS 等、従来 DWH 向き)
  - ELT=Extract→Load→Transform(生のまま入れて後で変換、データレイク向き)
  - なぜ ELT に移ったか(ストレージが安い・スケールする/多様なデータ型を後から活かせる)
  - 「取り込み(ingest)→蓄積→変換→提供(serve)」の4段階フレーム(MS Learn MDW)
- 根拠 URL:
  - https://www.databricks.com/discover/etl/vs-elt
  - https://learn.microsoft.com/en-us/data-engineering/playbook/solutions/modern-data-warehouse

### 5. データの置き場所の進化 — ウェアハウス → レイク → レイクハウス
- 主張: データウェアハウス(構造化・schema-on-write・BI 向き・高価/独自)→ データレイク(生データ・schema-on-read・安い・ML 向きだが信頼性が弱い)→ レイクハウス(両者の良いとこ取り、安い object storage の上にウェアハウスの信頼性を載せる)。
- 内容:
  - 3 つの定義と長所短所(Databricks の整理)
  - schema-on-write vs schema-on-read
  - データレイクの弱点(信頼性・整合性・破損)→ それを解決するのが次セクションのテーブルフォーマット、と伏線
  - 「レイクハウスは従来 DWH を置き換えうる」潮流
- 根拠 URL:
  - https://www.databricks.com/discover/data-warehouse
  - https://www.databricks.com/blog/data-lakes-vs-data-warehouses-what-your-organization-needs-know
  - https://docs.databricks.com/aws/en/lakehouse
  - https://www.databricks.com/discover/data-lakes

### 6. テーブルフォーマットという土台 — Parquet・Delta・Iceberg と「オープン」の意味
- 主張: レイクハウスを成立させたのは「ファイルの山にテーブルとしての信頼性(ACID・履歴・スキーマ)を与えるオープンテーブルフォーマット」。Parquet(列指向ファイル)の上に Delta Lake / Apache Iceberg / Hudi がトランザクションログを足す。
- 内容:
  - Parquet=列指向・圧縮・データスキッピングの土台
  - オープンテーブルフォーマット=データ+メタデータを分離して保存し、ACID・time travel・data skipping を実現(delta.io)
  - Delta Lake = Parquet + トランザクションログ
  - 「オープン」であることの意味=特定ベンダーにロックされず複数エンジンから読める。相互運用(UniForm 等)で差が縮小
  - Fabric 記事の「Delta/Iceberg 相互運用」「OneLake Table APIs」が読めるようになる、と軽く伏線
- 根拠 URL:
  - https://delta.io/blog/open-table-formats
  - https://docs.databricks.com/aws/en/delta
  - https://www.databricks.com/blog/2020/09/10/diving-deep-into-the-inner-workings-of-the-lakehouse-and-delta-lake.html

### 7. データを磨く設計図 — メダリオン(Bronze/Silver/Gold)
- 主張: レイクハウスにデータを置くとき、品質を段階的に上げる定番パターンがメダリオン。Bronze(生)→ Silver(クレンジング/結合)→ Gold(集計/業務用)。これは「推奨リファレンス」であって絶対の規則ではない。
- 内容:
  - 3 層の役割(Databricks/MS Learn)
  - ELT との関係(Bronze に生のまま入れ、層を上げるごとに変換)
  - "multi-hop" の考え方、層は増減してよい
  - Fabric の Lakehouse でも推奨設計、と接続
- 根拠 URL:
  - https://www.databricks.com/blog/what-is-medallion-architecture
  - https://learn.microsoft.com/en-us/fabric/onelake/onelake-medallion-lakehouse-architecture
  - https://www.databricks.com/blog/databricks-lakehouse-data-modeling-myths-truths-and-best-practices

### 8. 速度の選択 — バッチとストリーミング
- 主張: データの処理には「溜めてまとめて(バッチ)」と「流れてきた端から(ストリーミング)」の二択があり、要件(鮮度 vs コスト)で選ぶ。多くの基盤は両方を扱える。
- 内容:
  - バッチ=スケジュール実行・高スループット・遅延許容(日次レポート等)
  - ストリーミング=低レイテンシ(ミリ秒〜秒)・連続処理(不正検知・IoT・ライブダッシュボード)
  - マイクロバッチは「真のストリーミングではない」点
  - Delta が「同一データをバッチとストリーム両方で使える」例で土台と接続
- 根拠 URL:
  - https://aws.amazon.com/what-is/batch-processing
  - https://www.fivetran.com/learn/batch-processing-vs-stream-processing
  - https://www.bmc.com/blogs/batch-processing-stream-processing-real-time

### 9. 信頼を支える仕組み — ガバナンス・カタログ・リネージ
- 主張: データが増えると「どこに何があり、誰が使え、どこから来たか」が分からなくなる。これを管理するのがデータガバナンス。中核ツールがデータカタログ(資産の検索可能な目録)とデータリネージ(出自と流れの追跡)。
- 内容:
  - データカタログ=メタデータ管理・発見・分類・アクセス制御
  - リネージ=ソース→変換→ダッシュボードまでの経路を可視化(トラブルシュート・影響分析・コンプライアンス)
  - ガバナンスはオプションでなく基盤の一部、という現代的位置づけ(Purview/Unity Catalog の例)
  - Fabric の OneLake Catalog / Purview 統合が読めるようになる、と接続
- 根拠 URL:
  - https://www.databricks.com/blog/what-is-data-lineage
  - https://learn.microsoft.com/en-us/purview/data-gov-classic-lineage
  - https://learn.microsoft.com/en-us/purview/data-governance-overview

### 10. 出口としてのBI — セマンティックモデルと import / DirectQuery、そして「コピー問題」
- 主張: 分析基盤の出口は BI(Power BI 等)。BI はデータの取り込み方に「メモリにコピー(import:速いが鮮度劣化・二重持ち)」と「都度問い合わせ(DirectQuery:鮮度よいが遅い)」のトレードオフがあり、これが「データを何度コピーするか」という基盤全体の悩みに直結する。
- 内容:
  - セマンティックモデル=BI が読む論理モデル(指標・関係)
  - import モード(VertiPaq にコピー)vs DirectQuery(ソースに変換クエリ)vs composite/dual
  - トレードオフ=鮮度・性能・コピー回数
  - 「コピーを減らす」ことがなぜ価値か(従来構成は ETL ごとに物理コピーが積み上がる)→ Direct Lake のような直読の意義に伏線
- 根拠 URL:
  - https://learn.microsoft.com/en-us/power-bi/connect-data/service-dataset-modes-understand
  - https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-storage-mode
  - https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-overview

### 11. クラウドが変えたコスト構造 — ストレージとコンピュートの分離
- 主張: 現代データ基盤の設計を根本で決めているのは「安い object storage(蓄積)と、必要なときだけ動かす計算(コンピュート)を分離する」発想。だからレイク/レイクハウスが成立し、課金も「使った計算量」で測るモデルに寄る。
- 内容:
  - 従来 DWH=ストレージと計算が一体(高価・常時起動)
  - クラウド=object storage が安く無限、計算は分離して伸縮/一時起動
  - これが ELT・レイクハウス・従量/容量課金・ポーズ/再開の共通の前提
  - Fabric の Capacity(CU プール)課金が「なぜそういう形か」を読む補助線、と接続
- 根拠 URL:
  - https://www.databricks.com/discover/data-lakes (object storage / 安価ストレージ前提)
  - https://docs.databricks.com/aws/en/lakehouse (low cost cloud storage の上に DWH 機能)
  - (補強で `tav extract` を 1 本検討。必須ではない)

### 12. まとめ:この地図でFabric記事を読む — 概念 → Fabric 用語 対応表
- 主張: ここまでの一般概念は、Fabric では具体的な機能名に化けているだけ。対応表で接続し、Fabric 記事へ送り出す。
- 内容(対応表案):
  | 一般概念(本記事) | Fabric での呼び名・対応 |
  | --- | --- |
  | データレイク | OneLake(テナント1つの論理データレイク) |
  | レイクハウス | Fabric Lakehouse |
  | オープンテーブルフォーマット | Delta / Iceberg 相互運用、OneLake Table APIs |
  | メダリオン | Bronze/Silver/Gold(推奨設計) |
  | ETL/ELT パイプライン | Data Factory(Pipeline / Dataflow Gen2 / Mirroring) |
  | DWH(OLAP) | Fabric Warehouse |
  | ストリーミング | Real-Time Intelligence(Eventstream / Eventhouse) |
  | OLTP | Fabric SQL Database / Cosmos DB in Fabric |
  | ガバナンス/カタログ/リネージ | OneLake Catalog + Purview 統合 |
  | BI の import/DirectQuery とコピー問題 | Direct Lake(Delta 直読) |
  | ストレージとコンピュートの分離・従量 | Capacity(F SKU / CU プール) |
- 締め: 「この地図を持って `articles/microsoft_fabric_overview.md` を読むと、各機能が『どの一般問題を解いているか』として頭に入る」と誘導。
- 根拠 URL: 本文中の各リンク + Fabric 記事

---

## 不足情報・追加調査の判断
- セクション 11(ストレージ/コンピュート分離)は手持ちのレイク/レイクハウス資料で十分書けるが、断定を強めたい場合のみ `tav search-extract "separation of storage and compute cloud data warehouse"` を 1 本追加(任意)。
- それ以外のセクションは根拠 URL が揃っており、追加調査なしで執筆可能。
- 全ソースは `--topic data_engineering_basics`(`temp/web/data_engineering_basics/`)に蓄積済み。

## 執筆方針メモ
- 各セクション冒頭に「前セクションの困りごと → 本セクションが解く」の一文を置き、地図の連続性を出す。
- 図(ASCII)は「データの一生」全体図(2 では役割相関、5 では3アーキの進化、12 では対応表)に絞る。
- 断定の強さに注意: 需要統計は data science 全体の数値である点、メダリオンは規則でなく推奨である点、オープンフォーマットの差は縮小中である点を、それぞれ明示する([[feedback_doc_phrasing_skepticism]] の方針)。
