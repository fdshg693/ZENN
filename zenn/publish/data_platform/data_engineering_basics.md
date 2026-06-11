---
title: "データエンジニアリング入門 — OLTPからレイクハウス、BIまで「データ基盤の地図」を一枚で"
emoji: "🗺️"
type: "tech"
topics: ["dataengineering", "etl", "datalake", "lakehouse", "microsoftfabric"]
published: false
---

## 1. はじめに — なぜ「データ基盤の地図」が必要か

Microsoft Fabric のような統合データプラットフォームは、データの取り込みから蓄積・変換・可視化までを一つの製品で提供してくれます。とても便利なのですが、いざ触ってみると「レイクハウス」「メダリオン」「セマンティックモデル」といった言葉が当たり前のように並び、**そもそもこの製品は何を解決したのか**が掴めないまま画面を眺めることになりがちです。これらの製品は、長年データエンジニアリングの世界で積み上げられてきた一般概念を前提に作られているからです。

この記事は、その前提概念を一枚の「地図」として渡すことを目的にしています。地図さえ頭に入っていれば、統合データプラットフォームの概観記事（たとえば[Microsoft Fabric とは何か](https://zenn.dev/)のような記事）を読んだときに「ああ、あの一般概念をこう製品化したのか」とすらすら腑に落ちるはずです。

- **想定読者**: アプリ開発・インフラ・クラウドの基礎はあるが、「データ分析基盤」の世界には馴染みが薄いエンジニア。
- **ゴール**: 読み終えたら、ベンダー製品の説明に出てくる用語の「元ネタ」が分かり、製品固有の解説記事が前提知識なしで読めるようになること。
- **扱う範囲**: データエンジニアという職種から、OLTP/OLAP の分離、ETL/ELT、置き場所(ウェアハウス/レイク/レイクハウス)、テーブルフォーマット、メダリオン、バッチ/ストリーミング、ガバナンス、BI、コスト構造まで。**扱わない範囲**: 個別ツールの操作手順や、特定ベンダーに依存した設定。ここではあくまでベンダー非依存の一般論に絞ります。

構成の方針として、この記事は**「データの一生」**をたどります。データは業務システムで**生まれ**、パイプラインで**運ばれ**、基盤に**溜まり**、変換で**磨かれ**、最後に分析や BI で**使われる**——この流れに沿って、各段階で「なぜそれが必要になったのか」を必ず添えながら概念を一つずつ置いていきます。地図は、行き先ではなく道筋を示すものだからです。

そして最後の章で、ここで描いた一般概念が Microsoft Fabric の具体的な機能名にどう対応するかを一覧にして、Fabric 記事へとお送りします。

---

## 2. データエンジニアという仕事 — 役割・需要・隣接職種との違い

データの一生を案内する前に、まずその一生を設計・運用する人、すなわち**データエンジニア**が何者かを押さえておきましょう。地図でいえば「誰が道を敷くのか」を知ることに当たります。

データエンジニアとは、ひとことで言えば**分析の土台を作る人**です。Microsoft Learn は、データエンジニアを「多様な構造化・非構造化データシステムから、データを統合・変換・集約し、分析ソリューションを構築するのに適した構造へと作り変える、組織の主役となる役割」と定義しています（[Get started with data engineering on Azure - Microsoft Learn](https://learn.microsoft.com/en-us/training/paths/get-started-data-engineering)）。パイプライン・蓄積・整形といった、分析が始まる**前**の地ならしを担当するわけです。

### 隣接職種との違い

「データを扱う仕事」はデータエンジニアだけではありません。よく混同される三職種を整理します。

| 役割 | 主な責務 | ひとことで言うと |
| --- | --- | --- |
| データエンジニア | データベースや大規模処理システムなどのアーキテクチャを開発・構築・テスト・維持し、生データを整える | 土台を作る人 |
| アナリティクスエンジニア | エンジニアが用意した複数のデータソースをまとめ、利用者が一貫した洞察に簡単・反復的にアクセスできる仕組みを作る | 土台と分析の橋渡しをする人 |
| データサイエンティスト | 整えられたデータを使って予測モデルを構築・訓練し、大規模にパターンや傾向を見つけ出す | 意味を取り出す人 |

要するに、**エンジニアが土台を作り、サイエンティストがその上で意味を取り出す**という補完関係です。DataCamp はこの分担を「データエンジニアは人間・機械・計測器の誤りを含む生データを扱い、その主な役割の一つはデータサイエンティストが分析できるようにデータをきれいにすることだ」と表現しています（[DataCamp](https://www.datacamp.com/blog/data-scientist-vs-data-engineer)）。AWS も「データエンジニアはデータサイエンティストがデータにアクセス・解釈できるようにするシステムを構築・維持し、データモデルの作成・パイプライン構築・ETL の監督に携わる」と整理しています（[What is Data Science? - AWS](https://aws.amazon.com/what-is/data-science)）。IBM はさらにアナリティクスエンジニアを加え、「データエンジニアがデータを生み、アナリティクスエンジニアがそれらを束ねてアクセスしやすい形にし、データサイエンティストが大規模に分析する」という三者の流れを示しています（[IBM](https://www.ibm.com/think/topics/data-engineer-data-vs-data-scientist-vs-analytics-engineer)）。

なお、職種の境界は組織によってかなり曖昧です。IBM も Syracuse 大学（iSchool）も「チームによって責務は重なり合う」と注意しており、役割名そのものより**「土台を作る／意味を取り出す」という軸**で捉えるのが実用的です（[Syracuse iSchool](https://ischool.syracuse.edu/data-engineer-vs-data-scientist)）。

### 需要について

需要も見ておきましょう。米国労働統計局（BLS）によると、**data science の雇用は 2023 年から 2033 年にかけて +34% 成長する**と予測されています（[Syracuse iSchool](https://ischool.syracuse.edu/data-engineer-vs-data-scientist)）。

ただし、ここは正確に読む必要があります。**この +34% は「data science」全体に対する数値であり、データエンジニア単独の統計ではありません**。データエンジニアリングはしばしば広義の data science の一部とみなされるため、この予測は関連職種を含めた分野全体の伸びを反映したものです。出典でも「データエンジニアリングは広義のデータサイエンス分野の一部とされることが多いため、この予測はデータエンジニアなど関連職種への需要の高まりも反映している」と注記されています。データエンジニアだけの増加率を表す公式統計として引用しないよう注意してください。

---

## 3. なぜ業務DBで分析してはいけないのか — OLTPとOLAPの分離

データエンジニアが「分析の土台を別に作る」と述べました。ではなぜ、わざわざ別の土台が必要なのでしょうか。業務システムの DB をそのまま分析に使えば済むようにも思えます。その素朴な疑問に答えるのが、本セクションの **OLTP と OLAP の分離**です。

業務システムが日々使うデータベースは **OLTP（Online Transaction Processing、オンライントランザクション処理）** と呼ばれ、注文処理・在庫更新・顧客情報管理といった**1 件ずつの読み書き（トランザクション）**を、応答性・一貫性・同時実行性を優先して高速・確実にさばくよう最適化されています（[Architecture strategies for optimizing data performance - Microsoft Learn](https://learn.microsoft.com/en-us/azure/well-architected/performance-efficiency/optimize-data-performance)）。

一方、分析は **OLAP（Online Analytical Processing、オンライン分析処理）** と呼ばれ、大量のデータをスキャンして集計し、レポートや傾向分析を行う処理です。両者は最適化の方向がちょうど逆を向いています。Microsoft Learn は OLTP データベースを「個々のレコード入力に最適化されており、**分析向けには設計されていない**ため、データの取り出しに時間と手間がかかる」と明言しています（[Online Analytical Processing - Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/data-guide/relational-data/online-analytical-processing)）。

ここに**分析基盤を別に立てる理由**があります。本番の OLTP に重い分析クエリ（大量スキャン・集計）をぶつけると、リソースを食い潰して肝心の業務トランザクションが遅くなったり止まったりしかねません。だから分析専用の OLAP システムを切り離す——これがデータエンジニアリングが存在する理由の一つです。Microsoft も「OLTP と OLAP のシステムを分離し、それぞれを固有のワークロードに合わせて最適化せよ」とアーキテクチャ戦略として推奨しています（[Microsoft Learn](https://learn.microsoft.com/en-us/azure/well-architected/performance-efficiency/optimize-data-performance)）。

### OLTP と OLAP の対比

| 観点 | OLTP（業務処理） | OLAP（分析処理） |
| --- | --- | --- |
| 目的 | リアルタイムのトランザクション処理 | 大量データの分析・意思決定支援 |
| データソース | 単一ソースのリアルタイム・トランザクションデータ | 複数ソースの履歴・集計データ |
| データモデル | 正規化／非正規化モデル | スタースキーマ・スノーフレークスキーマ等の分析モデル |
| 物理構造の傾向 | 行指向（少数レコードへの高速アクセス向き） | 列指向（スキャン・集計向き） |
| データ量 | 比較的小さい（GB 規模） | 大きい（TB〜PB 規模） |
| 更新 | 即時更新が中心 | 履歴を保持し、定期的にまとめて更新 |

（対比の根拠: [AWS: OLAP vs OLTP](https://aws.amazon.com/compare/the-difference-between-olap-and-oltp)、列指向／行指向と HTAP は [In-memory technologies - Azure SQL Database](https://learn.microsoft.com/en-us/azure/azure-sql/database/in-memory-oltp-overview?view=azuresql)）

### データの流れ（簡易図）

```
[クライアントアプリ]
   Webアプリ / APIアプリ
        |  トランザクション(1件ずつ)
        v
[OLTP] 業務DB（行指向・正規化・即時更新）
        |  定期的に抽出・移送
        v
[OLAP] 分析基盤（列指向・非正規化・履歴保持）
        |
        v
[分析・レポート / BI]
```

（この流れは [Online Analytical Processing - Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/data-guide/relational-data/online-analytical-processing) のアーキテクチャ図に基づく）

なお、行と列の両方の持ち方を同じデータに対して用意し、トランザクションと分析を同時にこなそうとする **HTAP（Hybrid Transaction/Analytical Processing）** という手法も存在します（[Microsoft Learn](https://learn.microsoft.com/en-us/azure/azure-sql/database/in-memory-oltp-overview?view=azuresql)）。本記事では「そういう選択肢もある」とだけ触れ、深入りはしません。基本はあくまで「OLTP と OLAP を分ける」と覚えておけば十分です。

---

## 4. データを運ぶ二つの流儀 — ETLとELT

OLTP と OLAP を分けると決めました。すると次の問題が立ち上がります——**業務 DB（OLTP）に生まれたデータを、どうやって分析基盤（OLAP）まで運び、分析できる形に整えるのか**。この「運び方」の流儀が、本セクションの **ETL** と **ELT** です。

### ETL: 変換してから入れる（従来型）

古くからの定石は **ETL（Extract → Transform → Load、抽出→変換→ロード）** でした。データソースから抽出（Extract）し、分析しやすい形に変換（Transform）してから、データウェアハウス（DWH）にロード（Load）する——つまり**「変換してから入れる」**順序です。SQL Server Integration Services（SSIS）などがその代表で、従来型のデータウェアハウスではこの ETL が好まれてきました（[Exploring the Modern Data Warehouse - Microsoft Learn](https://learn.microsoft.com/en-us/data-engineering/playbook/solutions/modern-data-warehouse)）。

### ELT: 入れてから変換する（現代型）

これに対し、現代のクラウド基盤で主流になったのが **ELT（Extract → Load → Transform、抽出→ロード→変換）** です。Databricks の説明によれば「ELT は抽出したデータをすぐにロードし、変換せずにそのまま置く。その後、必要に応じてデータの保管場所から直接、使える形へと変換する」流儀です（[ETL vs ELT - Databricks](https://www.databricks.com/discover/etl/vs-elt)）。つまり**「入れてから変換する」**——生のまま入れて、後で必要な分だけ磨くわけです。Modern Data Warehouse（MDW）では、この ELT で「まずデータレイクにそのまま取り込み、その後で変換する」のが定石とされています（[Microsoft Learn](https://learn.microsoft.com/en-us/data-engineering/playbook/solutions/modern-data-warehouse)）。

### なぜ ELT へ移ったのか

順序が入れ替わった背景には、クラウドがもたらした二つの変化があります。

- **ストレージが安く、スケールするようになった**: かつては容量が高価だったため「不要なデータは変換段階で削ぎ落としてから入れる」必要がありました。クラウドの安価でスケールするストレージはこの制約を外し、生のまま大量に溜め込むことを現実的にしました。Databricks も「ELT モデルは結果的なストレージ需要が本質的に読みづらく、クラウドを活用してこそ現実的になる」と指摘しています（[ETL vs ELT - Databricks](https://www.databricks.com/discover/etl/vs-elt)）。
- **多様なデータ型を後から活かせる**: ELT は構造化・非構造化データの両方を保存できるモダンなデータレイク型アーキテクチャと相性が良く、アナリストはより幅広い種類のデータを後から分析に取り込めます（[ETL vs ELT - Databricks](https://www.databricks.com/discover/etl/vs-elt)）。先に変換して捨ててしまうと、後から「あのデータも使いたかった」が利かないのです。

ETL が時代遅れというわけではありません。Databricks も「ETL モデルには依然として多くの利点があり、両者の類似点と相違点を理解する価値がある」と述べています（[ETL vs ELT - Databricks](https://www.databricks.com/discover/etl/vs-elt)）。ただ、**現代の分析基盤は基本的に ELT を前提に設計されている**——これが地図に書き込んでおくべきポイントです。

### 「取り込み→蓄積→変換→提供」という 4 段階フレーム

ETL／ELT の話を、もう一段抽象化しておきましょう。Microsoft の Modern Data Warehouse は、分析パイプラインを次の **4 段階**で捉えます。

1. **取り込み（Ingest）**: データソースからデータを取り込む。
2. **蓄積（Store）**: データレイクなどにそのまま溜める。
3. **変換（Transform）**: 分析しやすい形に整える。
4. **提供（Serve）**: エンドユーザーの可視化・分析に向けてデータを公開・消費可能にする。

出典では特に「Serve: データが消費のために公開される。エンドユーザーによる可視化と分析を可能にすることを含む」と説明されています（[Exploring the Modern Data Warehouse - Microsoft Learn](https://learn.microsoft.com/en-us/data-engineering/playbook/solutions/modern-data-warehouse)）。ELT とは、この 4 段階のうち「**蓄積を変換より先に置く**」やり方だ、と捉えると見通しが良くなります。

この「取り込み→蓄積→変換→提供」こそ、冒頭で予告した**データの一生（生まれ→運ばれ→溜まり→磨かれ→使われる）**そのものです。データがどこで生まれ（OLTP）、なぜ別の場所へ運ばれ（OLTP/OLAP 分離）、どう運ばれて溜まるのか（ELT）——ここまでで地図の骨格が引けました。次は、運ばれたデータが溜まる「置き場所」そのものを見ていきます。

---

## 5. データの置き場所の進化 — ウェアハウス → レイク → レイクハウス

前セクションまでで「ETL/ELTでデータを集めて変換する」流れを見てきました。では、集めたデータは**どこに置く**のでしょうか。その置き場所の設計思想は、扱うデータの種類と量の爆発に押されて、30年かけて大きく姿を変えてきました。本セクションでは「ウェアハウス → レイク → レイクハウス」という置き場所の進化を、それぞれ「なぜ次が必要になったか」とともにたどります。

### データウェアハウス — BIのために構造を先に決める

データウェアハウス(DWH)は、約30年にわたってビジネスインテリジェンス(BI)の意思決定を支えてきた、構造化データのための整然とした置き場所です。データはクレンジング・変換・統合され、**クエリと分析に最適化されたスキーマ**(よく使う集計まであらかじめ組み込んだ形)に整えてから格納されます。

ここで重要なのが **schema-on-write(書き込み時スキーマ)** という考え方です。データを書き込む前に「どんな構造で持つか」を確定させておくため、読むときには常にきれいな構造化データが手に入ります。BIレポートや分析の土台としては非常に高性能でスケーラブルです。

一方で弱点もあります。

- **高価で独自(proprietary)**: 多くのDWHは独自フォーマットに依存し、機械学習(ML)のサポートが限られがちです。
- **変化に弱い**: 頻繁には変わらないデータ向けに設計されており、近年の多様なデータ・ユースケースを捌ききれません。

（出典: [What is a data lakehouse? - Databricks](https://docs.databricks.com/aws/en/lakehouse) 、[Data Lakes vs Data Warehouses - Databricks](https://www.databricks.com/blog/data-lakes-vs-data-warehouses-what-your-organization-needs-know) ）

### データレイク — まず生のまま、安く全部ためる

データウェアハウスの「高価・独自・現代的ユースケースに対応できない」という限界への反応として登場したのが **データレイク** です。データレイクは、**大量のデータをネイティブな生(raw)フォーマットのまま**保持する中央の置き場所です。

階層的なフォルダ構造を持つDWHと違い、データレイクは**フラットな構造**と**オブジェクトストレージ**を使います。オブジェクトストレージは各データにメタデータタグと一意IDを付けて格納するため、安価かつ大規模にデータを保存できます。この「安いオブジェクトストレージ + オープンフォーマット」という組み合わせが、多様なアプリケーションからのデータ活用を可能にしました。

ここでの考え方が **schema-on-read(読み込み時スキーマ)** です。DWHのように事前にスキーマを課さず、データを「ありのまま(as is)」格納し、構造の解釈は読むときに行います。生データも、構造化されたテーブルも、変換途中の中間テーブルも、すべて同じレイクに並べて置けます。このため、データ探索・データサイエンス・MLとの相性が良いのが特徴です。

しかし、安さと柔軟性と引き換えに **信頼性が弱い** という重大な弱点を抱えます。データレイクは「ファイル(オブジェクト)の集まり」にすぎないため、

- トランザクション失敗による**隠れたデータ破損**が起こりやすい
- 結果整合性により**不整合なクエリ結果**が出る
- **テーブルのバージョン管理や監査ログといった基本的な管理機能が欠如**している

といった問題が一般的です。このため、多くの組織はデータレイクをデータサイエンスやMLには使う一方、未検証(unvalidated)な性質ゆえに**BIレポートには使わない**、という使い分けを強いられてきました。

（出典: [Introduction to Data Lakes - Databricks](https://www.databricks.com/discover/data-lakes) 、[Inside Lakehouse and Delta Lake - Databricks](https://www.databricks.com/blog/2020/09/10/diving-deep-into-the-inner-workings-of-the-lakehouse-and-delta-lake.html) ）

### データレイクハウス — 安いレイクの上に、ウェアハウスの信頼性を載せる

「BIにはDWH、MLにはレイク」と2つのシステムを使い分けるのは、データの重複を生み、アーキテクチャを複雑にします。この分断を埋めるべく登場したのが **レイクハウス(lakehouse)** です。

レイクハウスは、データレイクとデータウェアハウスの**良いとこ取り**をする新しいアーキテクチャです。その実現方法はシンプルかつ強力で、「**安価なクラウドオブジェクトストレージの上に、データウェアハウスと同等のデータ構造とデータ管理機能を、オープンフォーマットのまま直接実装する**」というものです。言い換えれば、「安くて信頼性の高いオブジェクトストレージが手に入った現代に、もう一度ウェアハウスを設計し直したらこうなる」という発想の産物です。

具体的には、データレイクの上に **トランザクショナルなストレージ層** を一枚追加します。これにより、

- レイクの**安さ・柔軟性・スケーラビリティ**
- ウェアハウスの**構造・性能・信頼性・ガバナンス**

が1つのプラットフォームに統合され、従来型のBI分析・データサイエンス・MLが**同じシステム上・同じオープンフォーマットで共存**できるようになります。レイクハウスは、Delta LakeやApache Icebergといったオープンなデータフォーマットの上で信頼性と性能を提供することで、従来のデータウェアハウスを**置き換える**ことすら可能とされています。

```
[ データの置き場所の進化 ]

  データウェアハウス            データレイク                レイクハウス
  (schema-on-write)          (schema-on-read)          (両者の統合)
 ┌──────────────┐         ┌──────────────┐         ┌──────────────┐
 │ 構造化データ  │         │ 生データを     │         │ レイクの安さ   │
 │ をBI向けに    │   →     │ 安く全部ためる │   →     │ + ウェアハウス │
 │ 整えて格納    │         │ MLに強い      │         │ の信頼性       │
 │              │         │              │         │              │
 │ 高価・独自    │         │ 信頼性が弱い   │         │ オブジェクト   │
 │ MLに弱い      │         │ 破損/不整合   │         │ ストレージ上に  │
 │              │         │ バージョン管理 │         │ 信頼性層を載せる│
 │              │         │ がない        │         │              │
 └──────────────┘         └──────────────┘         └──────────────┘
   BIのための整然          安いが信頼できない         安くて信頼できる
```

ここで一つ宿題が残ります。レイクハウスは「安いオブジェクトストレージの上に**信頼性**を載せる」と言いましたが、**ファイルの山にすぎないデータレイクに、どうやってACIDや履歴やバージョン管理という信頼性を後付けできるのでしょうか**。その答えが、次セクションで扱う**オープンテーブルフォーマット**です。

（出典: [Data Warehouse - Databricks](https://www.databricks.com/discover/data-warehouse) 、[What Is a Lakehouse? - Databricks](https://www.databricks.com/blog/2020/01/30/what-is-a-data-lakehouse.html) ）

---

## 6. テーブルフォーマットという土台 — Parquet・Delta・Iceberg と「オープン」の意味

前セクションの宿題は、「ファイル(オブジェクト)の山にすぎないデータレイクに、どうやってウェアハウス並みの信頼性を載せるのか」でした。その答えが、本セクションの主役 **オープンテーブルフォーマット** です。レイクハウスという建物を成立させた**土台**は、「ファイルの集まりに、テーブルとしての信頼性(ACID・履歴・スキーマ)を与える技術」だったのです。

### まずは土台の土台 — Parquet(列指向ファイルフォーマット)

オープンテーブルフォーマットを理解する前に、その下にあるファイルフォーマットを押さえます。代表が **Parquet** に代表される **列指向(columnar)フォーマット** です。

列指向フォーマットの利点は、同種の比較で語られるORCの説明がそのまま当てはまります。

- **列指向**: クエリエンジンが関係ない列を簡単に読み飛ばせる(行指向だとファイル全体を見る必要がある)。
- **スキーマを埋め込む**: スキーマとメタデータをファイルに持つため、エンジンが推論する必要がなく、エラーが減る。
- **強力な圧縮**: ストレージを効率化する。
- **データスキッピングの素地**: データを塊(stripe等)で持ち、塊ごとのメタデータでクエリ最適化(必要な塊だけ読む)ができる。

ただし、Parquetのような**ファイルフォーマット単体ではACIDトランザクションを提供しません**。ファイルが多数に散らばると、管理が遅く・難しくなり、破損リスクも上がります。

（出典: [Delta Lake vs. ORC - Delta Lake](https://delta.io/blog/delta-lake-vs-orc) ）

### オープンテーブルフォーマット — メタデータを分離して信頼性を与える

そこに乗るのが **オープンテーブルフォーマット** です。これは、ParquetやORCといった既存のファイルフォーマットの**上に構築される**、表形式データを格納するためのオープンソース技術です。

仕組みの核心は「**データとメタデータの分離保存**」です。表形式のデータはファイルに格納し、**そのデータや操作についてのメタデータを、別のファイル/ディレクトリに格納**します。この一元化されたメタデータが、次のような「テーブルらしい」機能を実現します。

- **信頼性のあるACIDトランザクション**: 書き込みが途中で失敗してもテーブルを破損させない。これはまさにデータレイクの弱点を解消するために開発された機能です。
- **タイムトラベル(time travel)**: 過去時点のスナップショットを参照したり、誤った更新をロールバックしたりできる。
- **高度なデータスキッピング**: 一元化されたメタデータディレクトリのおかげで、選択的クエリに対し関連データを素早く見つけられ、Parquet単体やCSVより速い。

主要なオープンテーブルフォーマットは **Delta Lake・Apache Hudi・Apache Iceberg** の3つです。

| 層 | 役割 | 例 |
|---|---|---|
| オープンテーブルフォーマット | ファイル群にACID・履歴・スキーマを与え、「テーブル」にする | Delta Lake / Apache Iceberg / Apache Hudi |
| ファイルフォーマット | 列指向・圧縮・データスキッピングの素地 | Parquet / ORC |
| ストレージ | 安価に大量保存する | クラウドオブジェクトストレージ |

### Delta Lake — Parquet + トランザクションログ

具体例として **Delta Lake** を見ると、その正体がよく分かります。Delta Lakeは、**Parquetデータファイルを、ファイルベースのトランザクションログで拡張した**ストレージ層です。つまり「Parquet + トランザクションログ = ACID」という構図です。

このトランザクションログ(ログ自体もParquetへコンパクトに圧縮され、クラウドオブジェクトストレージに格納されます)が「どのオブジェクトがこのテーブルの一部か」をACIDな形で管理します。これにより、複数オブジェクトの同時更新や一部の差し替えを、直列化可能(serializable)な形で安全に行えます。Delta Lakeのトランザクションログは**明確に定義されたオープンなプロトコル**を持ち、どんなシステムからでもログを読めるようになっています。

（出典: [Understanding Open Table Formats - Delta Lake](https://delta.io/blog/open-table-formats) 、[What is Delta Lake? - Databricks](https://docs.databricks.com/aws/en/delta) 、[Inside Lakehouse and Delta Lake - Databricks](https://www.databricks.com/blog/2020/09/10/diving-deep-into-the-inner-workings-of-the-lakehouse-and-delta-lake.html) ）

### 「オープン」の意味と、フォーマット間の差

ここで「オープン」という言葉の意味を押さえておきます。オープンとは、**特定ベンダーの独自フォーマットにロックインされず、複数のエンジンから読める**ということです。前述のとおりDelta Lakeのログプロトコルは公開されており、「どんなシステムでもログを読める」ように設計されています。これは、DWHが独自フォーマットに依存しがちだったこととの大きな違いです。

ただし注意点があります。Delta Lake・Iceberg・Hudiの**フォーマット間には差がありますが、その差は相互運用(interoperability)を支える技術の登場によって、重要性を失いつつあります**。たとえば **Delta Lake UniForm** や **Unity Catalog** といったプロジェクトが、オープンテーブルフォーマット間のギャップを埋めています。「どれか一つを選んだら他から読めなくなる」という固定的な見方は、もはや実態に合わなくなってきている、ということです。

この「Delta/Icebergの相互運用」という視点を持っておくと、後続の Microsoft Fabric 記事で出てくる **「Delta/Iceberg相互運用」や「OneLake Table APIs」** といった話が、「ああ、あのテーブルフォーマット間の橋渡しの話か」とすっと読めるようになります(ここでは深入りしません)。

（出典: [Understanding Open Table Formats - Delta Lake](https://delta.io/blog/open-table-formats) ）

---

## 7. データを磨く設計図 — メダリオン(Bronze/Silver/Gold)

前セクションで、レイクハウスに「信頼できるテーブル」を置けるようになりました。では、**そのテーブル群をどう並べれば、生データを業務で使える品質まで引き上げられる**のでしょうか。その定番の設計図が **メダリオンアーキテクチャ** です。

### Bronze → Silver → Gold の三層

メダリオンアーキテクチャは、レイクハウス内のデータを論理的に整理するためのデータ設計パターンです。狙いは、データが各層を流れるにつれて、その**構造と品質を段階的(incrementally and progressively)に高めていく**ことにあります。データを3段階で掃除・整理していくプロセス、とイメージすると分かりやすいです。

- **Bronze(生データ)**: ソースから取り込んだ生のデータを、ほぼそのまま格納する層。
- **Silver(クレンジング/結合済み)**: クレンジングや結合(エンリッチ)を施した、より整った層。データモデリング的には第3正規形(3NF)に近いモデルや、Data Vaultのような書き込み性能の高いモデルが使われます。
- **Gold(集計/業務用)**: 業務消費にすぐ使える、集計済み・キュレーション済みの層。プロジェクト固有の複雑な変換やビジネスルールは、主にSilver→Goldの間で適用されます。

層を上がるほど品質が高くなる、というのがポイントです。Fabricの公式ドキュメントでも、bronze(raw)・silver(enriched)・gold(curated)の3層として、まったく同じ枠組みが「**推奨される設計アプローチ**」として説明されています。

```
[ メダリオン: multi-hop でデータを磨く ]

  ソース        Bronze            Silver              Gold
  (OLTP等)  →  生のまま取り込む → クレンジング/結合 → 集計/業務用
                (raw)            (enriched)         (curated)

   低 ───────────── データ品質 ─────────────→ 高
                  ↑ ELT: まず生で入れ、層を上げるたびに変換 ↑
```

### ELT との関係 — "multi-hop"

メダリオンは、前のセクションで見た **ELT** と相性の良いパターンです。レイクハウスのデータエンジニアリングでは、通常 ETL ではなく **ELT** が採られます。すなわち、

- まず **Bronzeに生のまま取り込む**(取り込みの速さと俊敏さを優先)
- Silverへのロード時には、**最小限の「ちょうど十分な(just-enough)」変換とクレンジング**だけを行う
- プロジェクト固有の複雑な変換とビジネスルールは **Silver→Goldで一気に適用**

という流れです。このように**層から層へとデータが何段も飛び移っていく**ことから、メダリオンは別名 **"multi-hop"(マルチホップ)アーキテクチャ** とも呼ばれます。

### 絶対の規則ではない — 層は増減してよい

ここで強調しておきたいのは、**メダリオンは「リファレンスアーキテクチャ(参照設計)」であって、守らなければならない「規則」ではない**という点です。

Bronze/Silver/Goldの3層は、データをレイクハウスに整理するための優れた枠組みを提供しますが、必須の構造ではありません。モデリングの鍵は柔軟性を保つことにあり、**現実世界の複雑さに合わせて、必要なら層を追加したり、逆に削除したりしてよい**とされています。「3層でなければならない」と硬直的に捉える必要はない、ということです。

（出典: [What is Medallion Architecture? - Databricks](https://www.databricks.com/blog/what-is-medallion-architecture) 、[Implement Medallion Lakehouse Architecture in Fabric - Microsoft Learn](https://learn.microsoft.com/en-us/fabric/onelake/onelake-medallion-lakehouse-architecture) 、[Lakehouse Data Modeling - Databricks](https://www.databricks.com/blog/databricks-lakehouse-data-modeling-myths-truths-and-best-practices) ）

---

## 8. 速度の選択 — バッチとストリーミング

ここまで「どこに置き(レイクハウス)、何で信頼性を与え(テーブルフォーマット)、どう磨くか(メダリオン)」を見てきました。もう一つの論点は **速度** です。データを「いつ処理するか」には大きく二択があり、その選択が基盤の鮮度とコストを左右します。

### 二つの処理モデル

- **バッチ処理(batch)**: データを**溜めてからまとめて**処理する方式。大量のデータを塊(chunk)で扱い、スケジュールに基づいて(リアルタイムでなく)実行します。一度に複数の行・イベントを処理し、**高スループット**で大量データを動かすのに向きます。
- **ストリーム処理(streaming)**: データが**流れてきた端から**、到着した順に連続的に処理する方式。変化を継続的に捕捉し、データがシステムを流れる間に絶え間なく変換・集計・フィルタ・ロードを行います。

どちらが優れているという話ではなく、**要件(鮮度 vs コスト)で選ぶ**ものです。そして多くの現代的な基盤は、その両方を扱えます。

### どちらをいつ選ぶか

| 観点 | バッチ処理 | ストリーム処理 |
|---|---|---|
| 実行タイミング | スケジュール実行(間隔ごと) | 連続・到着次第 |
| レイテンシ | 高い(意図的な遅延を許容) | 低い(ミリ秒〜秒、サブ秒) |
| スループット | 高い(大量データ向き) | リアルタイム性重視 |
| 代表的な用途 | 日次/週次レポート、給与処理、履歴分析 | 不正検知、ライブダッシュボード、IoTセンサー、行動分析、パーソナライズ |
| データ源 | 期間ごとに集めた静的データセット | IoTデバイス・センサー・アプリ操作などイベント駆動の源 |

選び方の指針はシンプルです。**「即時の洞察」が要件なら(不正検知やライブ監視)ストリーミング**、**「時間に余裕がある」なら(レポート生成や給与処理)バッチ**。さらに、データの量と頻度も判断材料です。IoTセンサー出力のような高頻度ストリームはストリーム処理に、定期的に大量に集まるデータセットはバッチ処理に向きます。

それぞれにトレードオフがあります。バッチは**実行時のリソーススパイク**(溜めたデータを一気に処理するため)や、ingestから利用可能になるまでの**構造的な遅延**を抱えます。ストリームは低レイテンシを実現する代わりに、**システムリソースへの継続的な需要**(常に処理し続ける)を要します。

### マイクロバッチは「真のストリーミング」ではない

注意点として、**マイクロバッチ(micro-batch)** があります。バッチの実行間隔を短くし、より小さな塊で処理することを「マイクロバッチ」と呼ぶことがありますが、**これは真のリアルタイムストリーム処理ではありません**。間隔を細かくしても、本質は「溜めてから処理する」バッチであり、到着の瞬間に処理するストリーミングとは別物だ、という区別を押さえておきましょう。

### 土台(テーブルフォーマット)との接続

ここで、第6セクションのテーブルフォーマットの話と繋がります。Delta Lakeは **Structured Streaming との緊密な統合** のために開発されており、**同一データの1コピーを、バッチ操作とストリーミング操作の両方で使える**ようになっています(大規模な増分処理も可能)。

つまり、「バッチかストリーミングか」という速度の選択は、必ずしも別々のデータコピーや別システムを要求しません。**信頼できるテーブルフォーマットという土台があるからこそ、同じデータを溜めても流しても扱える**——置き場所・土台・磨き方・速度という4つの論点が、ここで一つに結びつきます。

（出典: [Batch vs Stream Processing - Streamkap](https://streamkap.com/blog/batch-processing-vs-real-time-stream-processing) 、[Batch processing vs. stream processing - Fivetran](https://www.fivetran.com/learn/batch-processing-vs-stream-processing) 、[Batch vs Stream - Rivery](https://rivery.io/blog/batch-vs-stream-processing-pros-and-cons-2) 、[What is Batch Processing? - AWS](https://aws.amazon.com/what-is/batch-processing) 、[What is Delta Lake? - Databricks](https://docs.databricks.com/aws/en/delta) ）

---

## 9. 信頼を支える仕組み — ガバナンス・カタログ・リネージ

前セクションまでで、生データから整形済みデータ、そしてレイク/レイクハウス/ウェアハウスまで「データが流れる先」を見てきました。ところがデータが増え、置き場所も増えていくと、今度は別の困りごとが現れます。「どこに何があるのか」「このデータは誰が使ってよいのか」「この数字はそもそもどこから来たのか」が、誰にも分からなくなるのです。本セクションは、この“見失い”を防ぐ仕組みを扱います。

### なぜガバナンスが必要になるのか

データの種類・量・利用者が増えるほど、データは「資産」であると同時に「管理対象」になります。**データガバナンス**とは、組織がデータ資産を管理するための原則・実践・ツールの総体を指します(Databricks)。誰がアクセスできるか、品質は保たれているか、規制に準拠しているか——こうした問いに継続的に答え続ける営みです。

ガバナンスを支える中核ツールが、次の2つです。

#### データカタログ — 資産の検索可能な目録

**データカタログ**は、組織のデータ資産に関するメタデータ(データについてのデータ)を蓄える中央リポジトリで、データソース・データセット・データベース・ファイルなどの**検索可能な目録(インベントリ)**として機能します(Atlan)。カタログが担う主な役割は次の通りです。

- **メタデータ管理**: データソース、データ型、所有者、アクセス権限、品質、リネージなどの情報を一元管理する。
- **データ発見(discovery)とインベントリ**: 「どこに何があるか」を探せるようにする。
- **分類と機微度判定**: 機微なデータを識別・タグ付けする。
- **アクセス制御**: 誰がどのデータを使えるかを管理する。

つまりカタログは、「データがどこにあるか分からない」問題に対する答えそのものです(Atlan)。

#### データリネージ — 出自と流れの追跡

**データリネージ**は、データが「どこから来て、どう変化し、どこで使われているか」を可視化する仕組みです(Databricks)。Microsoft Purview のドキュメントでは、リネージを「データの出自(origin)と、データ資産全体を時間とともに移動していくライフサイクル」と説明し、ソースから宛先まで——どう変換されたかを含めて——視覚的に示すものだとしています(Microsoft Purview)。たとえば「BLOBストレージにコピーされたデータが、変換を経て、最終的にPower BIダッシュボードに至るまで」を一本の経路として描けます(Microsoft Purview)。

リネージが効いてくる場面は、主に“後ろ向き(過去をたどる)”のシナリオです。

| 用途 | 何を助けるか |
| --- | --- |
| トラブルシュート / 根本原因の特定 | パイプライン中のエラーを素早く見つけ、デバッグする(Databricks / Purview) |
| 影響分析(impact analysis / 「what if」) | あるデータを変えると、下流のどこに波及するかを見る(Purview) |
| コンプライアンス / 監査 | 機微なデータを(列レベルまで)追跡し、監査レポートに使う(Databricks) |
| 品質・正確性の担保 | データの正確性と一貫性を検証する(Databricks) |

### カタログとリネージの関係

両者は別物ではなく、補完関係にあります。カタログの役割の一つにリネージが含まれており(Atlan)、Purview のドキュメントも「データカタログのゴールは、環境内のすべてのデータシステムが自然につながり、リネージを報告できる堅牢なフレームワークを作ること」と述べています(Microsoft Purview)。各システム(ETL/ELT、分析、可視化)が持つメタデータをカタログが集約することで、ソースからダッシュボードまでを横断する一枚の地図ができあがるわけです。

### ガバナンスは「基盤の一部」という現代的な位置づけ

ここで強調したいのは、ガバナンスがもはや**後付けのオプションではなく、データ基盤そのものの構成要素**として語られるようになった点です。Databricks はリネージを「データ管理・ガバナンス戦略の不可欠な柱(essential pillar)」と表現しています(Databricks)。

実装例としては、たとえば次のような統合ガバナンスの仕組みが挙げられます(いずれも本記事はベンダー非依存の一般論として触れるにとどめます)。

- **Databricks Unity Catalog**: データ・分析・AI資産を一元的にカタログ化し、きめ細かなアクセス権を定義、データアクセスを監査し、リネージを(列レベルまで)自動取得する統合ガバナンスソリューション(Databricks)。
- **Microsoft Purview**: ガバナンスドメインやデータ品質、リネージを備えたデータガバナンスのプラットフォーム。リネージによって品質問題の根本原因を特定しやすくする(Microsoft Purview)。

ポイントは特定の製品名ではなく、「**蓄積・変換・出口のすべての層を横断して、出自と権限とを継続的に把握する層**が、現代の基盤には標準で組み込まれる」という発想の転換です。

（出典: [What is Data Lineage? - Databricks](https://www.databricks.com/blog/what-is-data-lineage) 、[Data lineage in classic Microsoft Purview Data Catalog](https://learn.microsoft.com/en-us/purview/data-gov-classic-lineage) 、[Data governance with Microsoft Purview](https://learn.microsoft.com/en-us/purview/data-governance-overview) 、[Data lineage in Unity Catalog - Databricks](https://docs.databricks.com/aws/en/data-governance/unity-catalog/data-lineage) 、[Data Catalog and Data Governance - Atlan](https://atlan.com/data-catalog-and-data-governance) ）

---

## 10. 出口としてのBI — セマンティックモデルと import / DirectQuery、そして「コピー問題」

ガバナンスで「どこから来たか」を追えるようになっても、最終的にデータは人の意思決定に使われなければ意味がありません。その**出口**にあたるのがBI(Business Intelligence、Power BI など)です。本セクションは、BIがデータをどう読み込むかという一見地味な設定が、実は基盤全体の「データを何度コピーするか」という悩みに直結している、という話をします。

### セマンティックモデル — BIが読む論理モデル

BIツールはテーブルを直接見せるのではなく、**セマンティックモデル**という論理モデルを介してデータを扱います。これは指標(メジャー)やテーブル間の関係(リレーションシップ)を定義した「BIが読むための層」です。Power BI では、このセマンティックモデルが取り込み方式(ストレージモード)を**テーブル単位**で持ちます(Microsoft Learn)。

### import か DirectQuery か — 根本的なトレードオフ

ストレージモードには大きく2つの基本形があり、ここに本質的なトレードオフがあります(Microsoft Learn)。

- **import**: データをBI側のエンジン(Power BI の場合は VertiPaq という列指向インメモリエンジン)に**コピーして取り込む**。クエリは取り込んだコピーに対して走る。
- **DirectQuery**: データを取り込まず、モデルは構造を定義するメタデータだけを持つ。クエリのたびに、DAXをソースDB向けのネイティブクエリ(SQLなど)に翻訳して**ソースに都度問い合わせる**(Microsoft Learn)。

それぞれの性格を整理します。

| 観点 | import | DirectQuery |
| --- | --- | --- |
| データの持ち方 | エンジン内にコピー(VertiPaq) | コピーせずメタデータのみ |
| クエリ性能 | 速い(インメモリ処理) | 遅くなりやすい(ソースが分析向け負荷に最適化されていない) |
| データ鮮度 | 取り込み時点で固定 → 劣化しうる | ソースを都度参照 → 鮮度が高い |
| コピーの発生 | あり(二重持ち) | なし |

import は速い代わりに「コピーである以上、取り込んだ瞬間から古くなる」「同じデータを二重に持つ」という宿命を負います。DirectQuery は鮮度を保つ代わりに、分析向けに最適化されていないソースへ重いクエリを投げるため遅くなりがちです(Microsoft Learn)。**速さと鮮度はトレードオフ**になっているのです。

### composite / dual — 「いいとこ取り」の試み

このトレードオフを緩和するために、両方を混ぜる仕組みがあります。

- **composite(複合)モデル**: import と DirectQuery を1つのモデル内で混在させ、テーブルごとにストレージモードを設定する。インメモリの高性能と、ソースからの(ニアリアルタイムな)鮮度の両立を狙う(Microsoft Learn)。実務では、ディメンション(マスタ系)テーブルを import/Dual に、ファクト(明細系)テーブルを DirectQuery にする、といった使い分けがよく取られます(Microsoft Learn)。
- **dual(デュアル)モード**: あるテーブルを import と DirectQuery の両方として扱えるようにし、クエリごとにPower BI側が効率的な方を選ぶ。import と DirectQuery を混在させたときの「限定的なリレーションシップ」問題を避けるのに役立つ(Microsoft Learn)。

### 「コピー問題」— なぜコピーを減らすことに価値があるのか

ここで一段引いて全体を眺めると、import のストレージモードは「**基盤のどこかに、また一つコピーが増える**」ことを意味します。そして思い出してほしいのは、ここに至るまでの道のり——取り込み、変換(ETL/ELT)、レイク、ウェアハウス——でも、各段階ごとに物理的なコピーが積み上がってきたことです。従来の構成では、ETLのステップごとにデータの物理コピーが増え、それぞれを別々に保持・更新する必要がありました。

コピーが増えると、

- ストレージと処理のコストが膨らむ、
- どのコピーが正なのか(鮮度のズレ)が問題になる、
- リネージ(セクション9)で追うべき経路も複雑になる、

といった負担が連鎖します。だからこそ「**コピーを減らす**」こと自体が価値になります。

理想を言えば、BIが「コピーを取り込んだ import の速さ」を保ちながら、「コピーせずソースを直接読む鮮度」も得られれば、このトレードオフから抜け出せます。実際、レイクハウスに置いたデータをBIエンジンが**直接読む**ような方式(たとえば Direct Lake のようなアプローチ)は、まさにこの「コピーを減らしつつ速さと鮮度を両立する」方向の試みです。Direct Lake は import と同じ VertiPaq エンジンでDAXを処理する一方、ソースを都度翻訳する DirectQuery とは異なる経路を取ります(Microsoft Learn)。詳細は深入りせず、次セクションとまとめへの伏線としておきます。

（出典: [Semantic model modes - Power BI](https://learn.microsoft.com/en-us/power-bi/connect-data/service-dataset-modes-understand) 、[Table Storage Mode - Power BI](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-storage-mode) 、[Composite models - Power BI](https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-composite-models) 、[Direct Lake overview - Microsoft Fabric](https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-overview) ）

---

## 11. クラウドが変えたコスト構造 — ストレージとコンピュートの分離

ここまで、取り込み・変換・蓄積・ガバナンス・出口と「データの一生」をたどってきました。最後に、なぜ近年これらが**こういう形に落ち着いたのか**——その背後で全体を決めている一つの発想を取り上げます。それが「**安いストレージ(蓄積)と、必要なときだけ動かす計算(コンピュート)を分離する**」という考え方です。

### 従来DWH — ストレージと計算が一体だった

データウェアハウスは約30年にわたりBIの意思決定を支えてきましたが(Databricks)、その多くは**高価で、独自(プロプライエタリ)な**システムでした(Databricks)。古典的な構成では、ストレージと計算リソースが事実上一体で、容量を増やすにも計算を増やすにも、まとまったシステムとして拡張する必要がありました。結果として、たとえ使っていない時間帯でも設備を抱え続けるような、コストの重い前提があったわけです。データレイクは、まさにこうしたデータウェアハウスの限界——「高価でプロプライエタリ」——への応答として生まれた、と整理されています(Databricks)。

### クラウド — object storage が安く、計算は分離できる

転機になったのが、クラウドの **object storage(オブジェクトストレージ)** です。データレイクは、階層的に保存するウェアハウスと違い、フラットなアーキテクチャとオブジェクトストレージにデータを置きます。オブジェクトストレージはメタデータタグと一意な識別子とともにデータを保存するため、リージョンをまたいだ検索・取得がしやすく、性能も向上します(Databricks)。そして重要なのは、それが**安価(inexpensive)**だという点です。「安価なオブジェクトストレージとオープンフォーマットを活かすことで、データレイクは多くのアプリケーションがデータを利用できるようにした」とされます(Databricks)。

レイクハウスは、この発想をさらに推し進めたものです。Databricks はレイクハウスを「**低コストなクラウドストレージの上に、オープンフォーマットで、ウェアハウス相当のデータ構造・管理機能を直接実装する**新しいシステム設計」と定義し、「**安価で高信頼なストレージ(オブジェクトストア)が手に入った今、データウェアハウスを設計し直したらこうなる、というもの**」と表現しています(Databricks)。つまり「安いストレージに蓄え、計算は分離して必要なときに動かす」という構図こそが、レイクハウスを成立させている土台です。

### なぜこの分離がすべてを束ねるのか

ストレージとコンピュートの分離は、本記事で見てきた各章の前提を一本につなぎます。

```
        [ 安価・実質無限の object storage ]   ← 蓄積はここに集約(レイク/レイクハウス)
                     │
        ┌────────────┼─────────────┐
        ▼            ▼             ▼
   一時起動の計算   一時起動の計算   一時起動の計算   ← 必要なときだけ伸縮・起動
   (変換/ELT)     (BIクエリ)     (ML 等)
```

- **ELT が成立する理由**: まず安いストレージに「生のまま」ためておき(schema-on-read)、変換は後から必要なときに計算を当てればよい——ストレージが安いからこそ、先に変換して整える(ETL)必然性が薄れ、ELT/レイクが現実的な選択肢になりました(Databricks)。
- **レイク/レイクハウスが成立する理由**: 上記の通り、安価なオブジェクトストレージという土台があって初めて成り立つ設計です(Databricks)。
- **課金が「使った計算量」に寄る理由**: 蓄積(安いストレージ)と計算が分離されていれば、料金は主に「動かした計算」で測るのが自然になります。これが従量・容量課金や、計算を止める/再開する(ポーズ/再開)といった運用の前提になります。

なお、具体的な料金体系や数値は資料の範囲外のため、ここでは「**分離されているからこそ、計算を伸縮させたり一時停止したりでき、コストの測り方もそれに沿う**」という一般論にとどめておきます。

この「ストレージとコンピュートの分離」を補助線として持っておくと——安いストレージにためる(レイク/レイクハウス)、変換は後から計算を当てる(ELT)、出口ではコピーを減らして直読を狙う(セクション10)、そして横断的に出自を管理する(セクション9)——という、ここまでの各ピースが一枚の地図としてつながって見えてくるはずです。

---

## 12. まとめ:この地図で Microsoft Fabric 記事を読む

長い道のりでした。最後に、ここまで描いてきた**ベンダー非依存の一般概念**が、Microsoft Fabric という具体的な製品ではどんな名前で呼ばれているのかを対応表にして、Fabric 記事へと送り出します。重要なのは、**Fabric の各機能は新しい発明ではなく、本記事で見てきた「一般的な困りごと」への一つの解(answer)**だという視点です。この視点さえ持てば、Fabric 記事は「機能カタログ」ではなく「課題と解の対応表」として読めます。

### 概念 → Fabric 用語 対応表

| 本記事で学んだ一般概念 | Fabric での呼び名・対応する機能 |
| --- | --- |
| 分析基盤を OLTP と分けて立てる(3章) | 分析側は OneLake / Lakehouse / Warehouse、OLTP は Fabric SQL Database / Cosmos DB in Fabric |
| データレイク(安く全部ためる, 5章) | **OneLake**(テナントに1つ自動提供される論理データレイク) |
| レイクハウス(5章) | **Fabric Lakehouse** |
| オープンテーブルフォーマット / Delta・Iceberg 相互運用(6章) | OneLake 上の **Delta** 格納、**Iceberg 相互運用**、**OneLake Table APIs** |
| メダリオン Bronze/Silver/Gold(7章) | Lakehouse 内の **Medallion**(Fabric の推奨設計) |
| ETL/ELT パイプライン(4章) | **Data Factory**(Pipeline / Dataflow Gen2 / Mirroring) |
| データウェアハウス(OLAP, 5章) | **Fabric Warehouse**(T-SQL, OneLake 上の Delta 格納) |
| ストリーミング処理(8章) | **Real-Time Intelligence**(Eventstream / Eventhouse(KQL)) |
| OLTP データベース(3章) | **Fabric SQL Database** / **Cosmos DB in Fabric** |
| ガバナンス・カタログ・リネージ(9章) | **OneLake Catalog** + **Purview 統合** |
| BI の import/DirectQuery と「コピー問題」(10章) | **Direct Lake**(OneLake 上の Delta を BI が直読し、コピーを減らす) |
| ストレージとコンピュートの分離・従量課金(11章) | **Capacity(F SKU)** の **CU(Capacity Unit)プール**、ポーズ/再開 |

### この地図を持って読むと、Fabric の「嬉しさ」が見える

たとえば Fabric 記事には「Mirroring + Shortcut + Direct Lake によってデータコピーを最小化する」という説明が出てきます。本記事を読んだ後なら、これは——

- **コピー問題(10章)**: ETL ごとに物理コピーが積み上がる従来構成の悩み、を
- **ゼロコピー**: Shortcut(他ストレージを参照だけで使う)と Direct Lake(BI が Delta を直読)で解こうとしている、
- そしてそれを支えるのが **OneLake という単一のデータレイク(5章)** と **Delta というオープンテーブルフォーマット(6章)** だ、

という「課題 → 解」の物語として読めるはずです。同様に、「Capacity の CU プールを全ワークロードで共有する」という Fabric 独特の課金も、**ストレージとコンピュートの分離(11章)**を一歩進めて「計算を一つのプールに束ねた」ものだ、と位置づけられます。

データは、業務システムで**生まれ**、パイプラインで**運ばれ**(ETL/ELT)、レイクハウスに**溜まり**、メダリオンで**磨かれ**、BI で**使われる**——そして全体をガバナンスとコスト構造が支える。この「データの一生」の地図を手に、ぜひ Microsoft Fabric の概観記事へ進んでみてください。各機能が「どの一般問題を解いているか」として、すっと頭に入るはずです。

## 参考資料

- [Get started with data engineering on Azure - Microsoft Learn](https://learn.microsoft.com/en-us/training/paths/get-started-data-engineering)
- [Data Engineer vs Data Scientist vs Analytics Engineer - IBM](https://www.ibm.com/think/topics/data-engineer-data-vs-data-scientist-vs-analytics-engineer)
- [Data Scientist vs Data Engineer - DataCamp](https://www.datacamp.com/blog/data-scientist-vs-data-engineer)
- [What is Data Science? - AWS](https://aws.amazon.com/what-is/data-science)
- [Data Engineer vs. Data Scientist - Syracuse iSchool](https://ischool.syracuse.edu/data-engineer-vs-data-scientist)
- [What's the Difference Between OLAP and OLTP? - AWS](https://aws.amazon.com/compare/the-difference-between-olap-and-oltp)
- [Architecture strategies for optimizing data performance - Microsoft Learn](https://learn.microsoft.com/en-us/azure/well-architected/performance-efficiency/optimize-data-performance)
- [Online Analytical Processing - Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/data-guide/relational-data/online-analytical-processing)
- [ETL vs ELT - Databricks](https://www.databricks.com/discover/etl/vs-elt)
- [Exploring the Modern Data Warehouse - Microsoft Learn](https://learn.microsoft.com/en-us/data-engineering/playbook/solutions/modern-data-warehouse)
- [Data Warehouse - Databricks](https://www.databricks.com/discover/data-warehouse)
- [Introduction to Data Lakes - Databricks](https://www.databricks.com/discover/data-lakes)
- [What is a data lakehouse? - Databricks](https://docs.databricks.com/aws/en/lakehouse)
- [What Is a Lakehouse? - Databricks Blog](https://www.databricks.com/blog/2020/01/30/what-is-a-data-lakehouse.html)
- [Understanding Open Table Formats - Delta Lake](https://delta.io/blog/open-table-formats)
- [What is Delta Lake? - Databricks](https://docs.databricks.com/aws/en/delta)
- [What is Medallion Architecture? - Databricks](https://www.databricks.com/blog/what-is-medallion-architecture)
- [Implement Medallion Lakehouse Architecture in Fabric - Microsoft Learn](https://learn.microsoft.com/en-us/fabric/onelake/onelake-medallion-lakehouse-architecture)
- [Batch processing vs. stream processing - Fivetran](https://www.fivetran.com/learn/batch-processing-vs-stream-processing)
- [What is Batch Processing? - AWS](https://aws.amazon.com/what-is/batch-processing)
- [What is Data Lineage? - Databricks](https://www.databricks.com/blog/what-is-data-lineage)
- [Data governance with Microsoft Purview - Microsoft Learn](https://learn.microsoft.com/en-us/purview/data-governance-overview)
- [Semantic model modes in the Power BI service - Microsoft Learn](https://learn.microsoft.com/en-us/power-bi/connect-data/service-dataset-modes-understand)
- [Direct Lake overview - Microsoft Fabric](https://learn.microsoft.com/en-us/fabric/fundamentals/direct-lake-overview)
