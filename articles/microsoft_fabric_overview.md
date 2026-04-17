---
title: "Microsoft Fabric とは何か — 7つのワークロードと OneLake、Capacity の関係を Azure 視点で理解する"
emoji: "🧵"
type: "tech"
topics: ["microsoftfabric", "azure", "onelake", "powerbi", "synapse"]
published: true
---

## はじめに: なぜ Azure エンジニアにとって Fabric は分かりにくいのか

Microsoft Fabric は「SaaS 型の統合データ分析プラットフォーム」と紹介されることが多いですが、Azure の IaaS/PaaS を普段触っているエンジニアからすると、

- SaaS なのに Azure サブスクリプション側で「Microsoft.Fabric/capacities」というリソースを作る
- Power BI の延長のようなUIだが、中身には Synapse 相当の分析機能が丸ごと入っている
- Synapse / ADLS Gen2 / ADF / Power BI Premium などがどう置き換わるのか分かりづらい

といった「どこに分類していいか分からない」違和感があります。

本記事は、Fabric の構造を **「プラットフォーム層」+「ワークロード層」** の 2 層モデルに整理し、OneLake・Capacity・Workspace を Azure 側の概念にマッピングしながら、全体像を一気に掴むことを目的とします。個別ワークロードのハンズオンには踏み込まず、設計判断に必要な「地図」を提供します。

:::message
本記事は 2026 年 4 月時点の公式ドキュメント・Fabric Blog を根拠にしています。Fabric は変化の早いサービスなので、実際の採用判断時は必ず最新の [Microsoft Learn](https://learn.microsoft.com/en-us/fabric/) を確認してください。
:::

---

## Fabric のレイヤ構造: プラットフォーム層 + ワークロード層

Fabric の全体像は、次の 2 層に分けて理解すると一気に見通しが良くなります。

```
┌──────────────────────────────────────────────────────────┐
│  ワークロード層 (Experiences)                              │
│  Data Factory / Data Engineering / Data Warehouse /       │
│  Real-Time Intelligence / Data Science / Databases /      │
│  Power BI / (Fabric IQ - Preview)                         │
├──────────────────────────────────────────────────────────┤
│  プラットフォーム層 (Fabric Platform)                       │
│  OneLake / OneLake Catalog / Copilot / Purview 統合 /     │
│  認証・監視・監査 (Entra ID ベース)                          │
└──────────────────────────────────────────────────────────┘
            上には Capacity (F SKU) があり CU を消費
```

公式ドキュメントでも、下部の「Fabric platform layer」が OneLake・Copilot・ガバナンス基盤を提供し、その上に専門ワークロードが載る構成として説明されています ([What is Microsoft Fabric](https://learn.microsoft.com/en-us/fabric/fundamentals/microsoft-fabric-overview))。

Azure エンジニアにとっての要点は次の 3 つです。

1. **インフラ管理は不要**: Spark クラスタも SQL エンドポイントも自分でプロビジョニングしない。
2. **データは原則 OneLake に入る**: ワークロード間のコピーが最小化される。
3. **計算リソースは Capacity の CU (Capacity Unit) プール**: ワークロードを跨いで共有される。

---

## OneLake: 全ワークロード共通の論理データレイク

OneLake は Fabric の心臓です。「One Drive for Data」と紹介されることもあり、**テナントごとに 1 つ、自動で提供される論理データレイク**です。

### Azure との関係

OneLake は **Azure Data Lake Storage Gen2 の上に構築** されており、OneLake API は ADLS Gen2 / Blob Storage API のサブセットと互換性があります ([Unify data sources with OneLake shortcuts](https://learn.microsoft.com/en-us/fabric/onelake/onelake-shortcuts))。つまり、既存の Azure SDK や `abfss://` 相当のアクセスパターンを持つツールでも、プロトコルレベルで接続できる設計になっています。

### 格納フォーマットは Delta (Parquet) が中心、さらに Iceberg と相互運用

Fabric のうち、**Lakehouse や Warehouse を中心とする分析テーブル** は、Delta Lake 形式 (Parquet ベース) で OneLake に保存されます。Data Warehouse でさえ、ストレージ層は「Log Structured Tables implemented using the open Delta table format」であると明記されています ([Architecture of Fabric Data Warehouse](https://learn.microsoft.com/en-us/fabric/data-warehouse/architecture))。一方で Real-Time Intelligence の KQL データのように、ワークロードごとにアクセスモデルやエンジンは異なるため、「Fabric の全データが同一の実行形式で保存される」とまでは言えません。

さらに 2025 年以降、Apache Iceberg との **メタデータ仮想化** が導入され、Iceberg テーブルを Delta Lake として、あるいは Delta Lake を Iceberg として読み書きできます。2026 年 2 月には **OneLake Table APIs** (Iceberg REST Catalog / Delta Lake API) が GA となっており、Fabric 外のエンジン (Snowflake、Trino 等) からも統一的にアクセスできます。

### Files と Tables — 2 種類のフォルダ

Lakehouse は `Files` と `Tables` という 2 つのトップレベルフォルダを持ちます。

| 場所 | 用途 | 典型例 |
| --- | --- | --- |
| `Tables/` | 構造化データ。Delta 形式のテーブルとして自動認識され、SQL/Spark で即クエリ可能 | ETL 済みの Silver/Gold 層 |
| `Files/` | 任意形式のファイル。テーブル登録なし | Bronze 層の生ログ、JSON など |

`Tables/` 配下はトップレベルにしかショートカットを張れない、スペースを含む名前の Delta は認識されない、などの細かい制約がある点に注意が必要です ([OneLake shortcuts](https://learn.microsoft.com/en-us/fabric/onelake/onelake-shortcuts))。

### Shortcut: ゼロコピーで他ストレージを参照する

Shortcut は OneLake 内のシンボリックリンクのような仕組みで、次のソースを「コピーなしで」Fabric 内のフォルダやテーブルとして扱えます。

- **Internal**: 他の OneLake 上のデータ (別ワークスペース、別 Lakehouse など)
- **External**: ADLS Gen2、Amazon S3、Google Cloud Storage、Dataverse、SharePoint、OneDrive など

Shortcut を `Tables/` の直下に置き、ターゲットが Delta 形式であれば、Fabric は自動でメタデータを同期し、通常のテーブルと同じように SQL / Spark / Direct Lake から読めます。

:::message alert
Shortcut 経由でアクセスする際、Internal sources は「**呼び出しユーザーの ID**」で認可されます。ただし Power BI の Direct Lake over SQL または T-SQL の Delegated identity モードでは、呼び出しユーザーではなく **アイテム所有者の ID** でアクセスされるので、権限設計時に注意が必要です ([OneLake shortcuts](https://learn.microsoft.com/en-us/fabric/onelake/onelake-shortcuts))。
:::

### Direct Lake: Power BI がセマンティックモデルを経由せず Delta を直接読む

従来の Power BI は、データソースからメモリに「インポート」するか、DirectQuery で都度クエリする形でした。Fabric では **Direct Lake モード** が加わり、OneLake 上の Delta ファイルを Analysis Services が直接読み込みます。インポートの鮮度とコピー不要性を両立できる点が、Fabric が Power BI とデータ基盤を一体化できた最大の理由のひとつです。

---

## 7つのワークロードを俯瞰する

Fabric の各ワークロードは、Azure に既存のサービスに概ね対応します。

| ワークロード | ひとこと | Azure での類似サービス |
| --- | --- | --- |
| **Data Factory** | パイプライン + Dataflow Gen2 + Mirroring による ETL/ELT | Azure Data Factory |
| **Data Engineering (Lakehouse)** | Spark Notebook + Delta Lake 中心の開発 | Synapse Spark / Azure Databricks |
| **Data Warehouse** | T-SQL ベースの MPP エンジン (自動スケール) | Synapse Dedicated SQL Pool |
| **Real-Time Intelligence** | Eventstream + Eventhouse (KQL) でストリーム処理 | Event Hubs + Azure Data Explorer |
| **Data Science** | MLflow + Spark ベースのノートブック | Azure Machine Learning |
| **Databases (SQL / Cosmos)** | Fabric 内 OLTP DB (2025 GA) | Azure SQL Database / Cosmos DB |
| **Power BI** | BI レポーティング (Direct Lake で高速化) | Power BI Premium |

以下、Azure 視点で重要な特徴だけ簡単に見ます。

### Data Factory in Fabric

170 以上のコネクタをサポートし、Pipeline / Dataflow Gen2 / Copy Job / Mirroring / dbt job などの形で ELT と ETL の両方を扱えます ([What is Data Factory (Fabric)](https://learn.microsoft.com/en-us/fabric/data-factory/data-factory-overview))。従来の Azure Data Factory とは別実装で、Azure ADF の Self-hosted Integration Runtime ではなく、Power BI 系統の **On-premises Data Gateway (OPDG)** を使う点が大きな違いです ([Differences between Data Factory in Fabric and Azure](https://learn.microsoft.com/en-us/fabric/data-factory/compare-fabric-data-factory-and-azure-data-factory))。

### Data Warehouse

T-SQL 互換の MPP 型 DWH ですが、ストレージは OneLake 上の Delta 形式で、メタデータとトランザクションは ACID 準拠に保たれます。`SELECT` と `NON-SELECT` で計算プールが分離されているため、ETL が BI クエリを阻害しにくい設計です ([Architecture of Fabric Data Warehouse](https://learn.microsoft.com/en-us/fabric/data-warehouse/architecture))。

### Real-Time Intelligence

Eventstream でストリームを取り込み、Eventhouse (KQL DB) に時系列データを格納します。ADX のエンジンをそのまま SaaS 化した位置づけで、IoT、アプリテレメトリ、LLM の会話ログ、エージェント監視などに向きます ([What Is Real-Time Intelligence](https://learn.microsoft.com/en-us/fabric/real-time-intelligence/overview))。

### Databases in Fabric (2025 GA)

Fabric 内に SQL Database / Cosmos DB が GA になりました。**OLTP データと分析データを同じプラットフォーム上に置ける** 点がポイントで、OLTP テーブルが自動で OneLake にミラーリングされ、ETL なしで分析側から読めます。従来なら「Azure SQL + ADF + ADLS + Synapse + Power BI」だった構成が Fabric 単体で完結します。

---

## Capacity (F SKU) と Workspace、テナント: 課金と論理構成

Fabric で最も Azure エンジニアが引っかかるのは、この **課金と論理構成の階層** です。

### 4 層の階層

```
Tenant (Entra ID テナント = Azure AD)
  ├─ Capacity (F SKU) ← Azure サブスクリプション配下の Azure リソース
  │    └─ Workspace (旧 License Mode = Workspace Type で種類が決まる)
  │         └─ Item (Lakehouse、Warehouse、Notebook、Report など)
```

- **Tenant**: Entra ID のテナントと 1:1。OneLake もここで 1 つ。
- **Capacity**: 計算リソースの単位。Azure Portal から `Microsoft.Fabric/capacities` として作成する Azure リソース。
- **Workspace**: アイテムを束ねる論理コンテナ。どの Capacity に載るかを選択できる。
- **Item**: Lakehouse、Warehouse、Notebook、Report 等の実体。

### F SKU は Azure サブスクリプションで課金される

F SKU は **Azure Portal から作成する Azure リソース** で、課金も Azure サブスクリプションを通じて行われます ([Buy a Microsoft Fabric subscription](https://learn.microsoft.com/en-us/fabric/enterprise/buy-subscription))。具体的には、

- **秒単位課金** (最小 1 分)
- **ポーズ/再開** 可能 (`Microsoft.Fabric/capacities/suspend/action`, `resume/action`)
- **Azure Reservations** で割引可能
- Azure Portal からサイズを上げ下げ可能

従来の Synapse Dedicated SQL Pool (DWU) や ADF (アクティビティ単位) のように個別に課金されるのではなく、**すべてのワークロードの計算リソースが単一の CU プールから消費される** のが Fabric 流です。SKU は F2 から F2048 まであり、例えば F64 以上では Workspace の Viewer ロールを持つ Free ユーザーが Power BI コンテンツを閲覧できるなど、機能単位での SKU 依存が存在します。

### Workspace Type (旧 License Mode)

License mode は現在 **Workspace Type** という名称になっており、この設定によって Workspace が利用できる Capacity 種別と、作成できる Item の範囲が決まります ([Understand Microsoft Fabric Licenses](https://learn.microsoft.com/en-us/fabric/enterprise/licenses))。

- **Fabric Capacity (F SKU)** に載る Workspace → Lakehouse、Warehouse、Notebook など非 Power BI のアイテムも作成可
- **Power BI Premium (P SKU)** に載る Workspace → Fabric 管理者が Fabric を有効化していれば、Fabric アイテムも利用可
- **Pro / PPU (shared pool)** 上の Workspace → Power BI アイテムのみ。PPU は Fabric キャパシティではない点に注意

:::message
PPU (Premium Per User) を持っていても、それだけでは Fabric の Lakehouse や Warehouse は作れません。F SKU もしくは Trial Capacity が必要です。
:::

### サイジングと Noisy Neighbor

CU は **ワークロード横断で消費される共有プール** なので、大規模 ETL が走ると Power BI レポートも遅くなる、というようなことが起こります。公式の Capacity Planning Guide でも、"noisy neighbors" の分離策として **用途別に Capacity を複数切る** 設計が推奨されています ([Capacity Planning Guide](https://learn.microsoft.com/en-us/fabric/enterprise/capacity-planning-plan-deployment))。小規模な開発用 Capacity を一時的に `resume` してテストし、終わったら `pause` する運用も基本形です。

---

## Synapse / ADLS Gen2 / Databricks との違い

Fabric は Synapse の後継ポジションですが、**課金モデルとデータ格納モデルが根本的に違う** ため、単純な置き換えではありません。

### Synapse Analytics との違い

| 観点 | Azure Synapse Analytics | Microsoft Fabric |
| --- | --- | --- |
| 課金モデル | 従量 (DWU、ADF アクティビティ、ストレージが別) | Capacity ベース (F SKU、プール) |
| ETL ツール | ADF または Synapse Pipelines | Fabric Pipelines (別実装) |
| ストレージ | ADLS Gen2 / Dedicated SQL Pool を個別管理 | OneLake に統合 |
| Power BI 連携 | Power BI Premium と別途連携 | Native、Direct Lake |
| 接続統合 | Synapse Link | Mirroring に置き換わった |

公式のマイグレーションガイドでは、Dedicated SQL Pool → Fabric Warehouse について、**インデックスは Fabric が自動管理するため移行しない**、T-SQL の一部は書き換えが必要、データ型マッピングの差分がある、などが列挙されています ([Migration from Synapse dedicated SQL pool to Fabric Warehouse](https://learn.microsoft.com/en-us/fabric/data-warehouse/migration-synapse-dedicated-sql-pool-warehouse))。

### ADLS Gen2 との関係

OneLake は ADLS Gen2 上に構築され、ADLS Gen2 / Blob API のサブセット互換を持ちます。既存 ADLS Gen2 のデータはコピーせず、**Shortcut で OneLake 側から参照するだけ** で Fabric のワークロードから使えます。これが Fabric 採用時の移行負荷を下げる重要なポイントです。

### Databricks との棲み分け

Databricks は引き続き、コード中心の大規模 ETL や PySpark/Scala ベースの ML ワークロード、マルチクラウド運用で強みがあります。Fabric は「Microsoft エコシステム + Power BI + SaaS 運用」を中核に据える組織に向き、**どちらを選ぶかは組織の技術ポートフォリオとガバナンス方針次第** です。

---

## 2025〜2026 年の主要トレンド

Fabric は 2023 年末に一般提供された後、アップデートの頻度が非常に高いサービスです。2026 年 4 月時点で押さえておきたい主要な GA / Preview を列挙します。

| 時期 | 機能 | 種別 |
| --- | --- | --- |
| 2025 年 | Copilot in Fabric 全世界展開 | GA |
| 2025 年 | Fabric SQL database / Cosmos DB in Fabric | GA |
| 2025 年 12 月 | Lakehouse schemas | GA |
| 2025 年 (Ignite) | Fabric IQ (業務エンティティ用のセマンティック層) | Preview |
| 2026 年 1 月 | Fabric Identities (Workspace Identity 上限 10,000 へ) | GA |
| 2026 年 2 月 | OneLake Table APIs (Iceberg REST / Delta Lake) | GA |
| 2026 年 3 月 | Built-in SQL DB mirroring to OneLake 管理 API | Preview |
| 2026 年 3 月 | Dynamic Data Masking (DDM) | GA |

出典: [What's New in Microsoft Fabric](https://learn.microsoft.com/en-us/fabric/fundamentals/whats-new)、[Fabric November 2025 Feature Summary](https://blog.fabric.microsoft.com/en-us/blog/fabric-november-2025-feature-summary/)

トレンドとしては、

- **OLTP と分析の統合** (Fabric Databases GA、Mirroring 拡張)
- **オープン規格のさらなる採用** (Iceberg 相互運用、OneLake Table APIs)
- **Copilot の各ワークロードへの浸透** (SQL、Real-Time、Dataflow Gen2 の Explainer など)
- **エンタープライズ・ガバナンス強化** (OneLake security for Mirrored DBs、Fabric Identities、DDM)

という 4 軸で整理できます。

---

## Fabric を使わない場合と使う場合の比較 — 何が嬉しいのか

前セクションまでで「Fabric は Synapse + ADF + Power BI Premium の統合後継」と述べましたが、具体的に**何をしなくて済むのか**を整理したほうが価値が見えやすいので、同一要件を「Fabric 不採用」と「Fabric 採用」で対比します。

### 要件例: 売上データの日次集計を Power BI ダッシュボードで見る

源泉データは業務 SQL DB、補助データは SaaS (CSV 出力) と想定します。

#### Fabric を使わない場合 (従来型 Azure 構成)

| ステップ | 使うサービス | 必要作業 |
| --- | --- | --- |
| 1. ストレージ用意 | ADLS Gen2 | ストレージアカウント作成、コンテナ設計、ACL/RBAC |
| 2. DB からの取り込み | Azure Data Factory + SHIR | Linked Service、Dataset、IR、パイプライン設計 |
| 3. 変換 | Azure Databricks or Synapse Spark | クラスタ設計、ノートブック、Delta 保存、スケジュール |
| 4. DWH 層 | Synapse Dedicated SQL Pool | プロビジョニング、DWU サイジング、分散キー設計 |
| 5. BI | Power BI Pro / Premium | Gateway 設定、インポートモデル or DirectQuery |
| 6. ガバナンス | Purview (別料金・別設定) | スキャン登録、Classification、Lineage 設定 |
| 7. 認証/監視 | 各サービスで個別 | サービスごとに RBAC、診断ログ、メトリクス |

**何が辛いか:**

- 課金ラインが 5 つ以上に分かれる (ADF 実行時間、DWU、Storage、Databricks クラスタ、Power BI Premium)
- ETL→DWH→Power BI で **データのコピーが 3 回程度発生** する
- それぞれのサービスに個別の RBAC と診断ログがあり、ガバナンスが分散
- 新しいデータソースを追加するたびに、ADF / Spark / DWH の 3 箇所で配線変更が必要

#### Fabric を使う場合

| ステップ | 使うサービス (Fabric 内) | 必要作業 |
| --- | --- | --- |
| 1. ストレージ用意 | OneLake (自動) | Workspace 作成のみ、ストレージは自動プロビジョニング |
| 2. DB からの取り込み | Mirroring or Copy Job | ウィザードで DB 選択、Mirroring なら ETL 不要 |
| 3. 変換 | Notebook or Dataflow Gen2 | Medallion 構成で Bronze/Silver/Gold を Lakehouse 内に |
| 4. DWH 層 | Fabric Warehouse (必要なら) | T-SQL で参照、自動スケール、インデックス自動管理 |
| 5. BI | Power BI (Direct Lake) | OneLake の Gold テーブルをコピーなしで参照 |
| 6. ガバナンス | OneLake Catalog + Purview 統合 | Fabric 内で完結、テナント横断の Lineage |
| 7. 認証/監視 | Entra ID + Capacity Metrics App | 一元管理 |

出典: [What is Microsoft Fabric](https://learn.microsoft.com/en-us/fabric/fundamentals/microsoft-fabric-overview)、[Analytics End-to-End with Microsoft Fabric (Azure Architecture Center)](https://learn.microsoft.com/en-us/azure/architecture/example-scenario/dataplate2e/data-platform-end-to-end)

### 比較表: 違いの本質

| 観点 | 従来型 Azure 構成 | Microsoft Fabric |
| --- | --- | --- |
| プロビジョニング | サービスごとに個別作成 | Workspace 作成のみ |
| ストレージ | ADLS Gen2 を別リソースで管理 | OneLake 自動提供 |
| データコピー | ETL ごとに物理コピー | Shortcut + Mirroring + Direct Lake でゼロコピー中心 |
| 課金モデル | サービス別の従量/時間課金が混在 | Capacity (F SKU) の CU プールに一元化、秒単位 |
| ガバナンス | Purview を別途配線 | OneLake Catalog + Purview が標準装備 |
| BI 連携 | Gateway / インポート / DirectQuery の設計判断 | Direct Lake で Delta ファイル直読 |
| SKU ポーズ | 個別に対応 (Synapse DW のみ可) | Azure Portal から Capacity 単位で ポーズ/再開 |
| 開発者体験 | ツール横断、認証も個別 | Fabric ポータル 1 つ、Entra ID で統一 |

### Fabric を採用することで得られるメリット (まとめ)

1. **データコピーの最小化**: Mirroring + Shortcut + Direct Lake により、OneLake に置いた Delta が全ワークロードから直接読める
2. **課金の単純化**: Capacity 1 つで全ワークロードの CU を共有、予測可能
3. **ガバナンス一元化**: OneLake Catalog + Purview 統合でテナント全体のデータ資産を横串で管理
4. **開発スピード向上**: サービス間の配線・認証・Gateway 設計が不要、POC を Trial Capacity で即開始可能
5. **Power BI との距離がゼロ**: 分析基盤と BI の間でのデータ受け渡しがほぼ発生しない

逆に言うと、「データコピーが必然ではない、BI は Power BI、ガバナンスは Microsoft で揃えたい」という前提が崩れる場合 (例: Snowflake 中心、Tableau 中心) は、Fabric の旨味が相対的に薄れます。

---

## 向いているケース / 向かないケース

### 向いているケース

- **Microsoft エコシステム中心**: M365、Dynamics 365、Power BI を軸に業務を回している組織
- **SaaS で運用負荷を最小化したい**: Spark クラスタや SQL Pool を自分で運用したくない
- **ETL なしで業務データを BI に繋ぎたい**: Mirroring + Direct Lake で「鮮度の高いレポート」を低運用コストで実現できる
- **エンドツーエンド分析の POC**: Trial Capacity で短期間に Lakehouse〜Power BI まで一気通貫で試せる

### 向かないケース / 注意が必要なケース

- **細かい計算リソース分離が必要**: 全ワークロードが Capacity の CU プールを共有するため、厳格な SLA 分離には向かない。複数 Capacity に分ける設計が必要
- **Python / OSS ML スタック中心の組織**: Databricks + Azure ML の方が依然として成熟
- **既存 Synapse / ADF の大規模資産を短期移行**: T-SQL 書き換え、SHIR → OPDG の切り替え、連携パターンの変更など移行コストは小さくない
- **本番採用でプレビュー機能に依存**: Fabric IQ や一部の新機能は Preview。SLA や機能制限を要確認

### F SKU サイジングの落とし穴

- SKU の選定は **Fabric SKU Estimator** + 実測の Fabric Capacity Metrics App で継続的に調整する前提
- Noisy Neighbor 対策として、**用途別に小さい Capacity を複数切る** か、priority workload 用の standby Capacity を `pause` 状態で用意して緊急時に `resume` する運用が実務的
- 本番開始後、CU スロットリングが発生したら即バックログ化するため、モニタリング必須

---

## Fabric 利用の具体シナリオ

Fabric の価値を具体的に見るため、公式ドキュメント ([Analytics End-to-End with Microsoft Fabric](https://learn.microsoft.com/en-us/azure/architecture/example-scenario/dataplate2e/data-platform-end-to-end)、[Lakehouse end-to-end scenario](https://learn.microsoft.com/en-us/fabric/data-engineering/tutorial-lakehouse-introduction)、[Introducing the end-to-end scenarios in Microsoft Fabric](https://blog.fabric.microsoft.com/en-US/blog/introducing-the-end-to-end-scenarios-in-microsoft-fabric/)) で扱われている代表的な 3 パターンを紹介します。

### シナリオ A: 小売企業の売上分析 (Lakehouse + Medallion + Power BI)

**背景:** 架空の小売企業 "Wide World Importers" が複数店舗・EC・在庫管理システムの売上データを統合して日次ダッシュボード化したい。公式の Lakehouse チュートリアルと同じ題材です。

**構成イメージ:**

```
[店舗 POS DB] ─┐
[EC 注文 DB]  ─┼─→ Data Factory (Pipeline / Mirroring)
[CSV エクスポート] ─┘              │
                                    ▼
                         OneLake / Lakehouse
                         ├─ Bronze (生データ、Files)
                         ├─ Silver (クレンジング済み Delta)  ← Spark Notebook
                         └─ Gold (集計済み Delta)           ← SQL/Spark
                                    │
                                    ▼
                        Power BI (Direct Lake モード)
                                    │
                                    ▼
                            経営ダッシュボード
```

**Fabric ならではのポイント:**

- Medallion の各層が **1 つの Lakehouse 内に** 収まり、別サービスの設定を跨がない
- Gold 層の Delta テーブルを **Power BI が Direct Lake で直接** 読むので、「Gold を Power BI インポートモデルに取り込む」工程が不要
- 追加で SQL 分析が必要になれば、同じ Lakehouse に SQL analytics endpoint から T-SQL で接続できる (コピー不要)
- スケジュール実行は Data Factory Pipeline で一元管理

### シナリオ B: IoT デバイスのリアルタイム監視 (Real-Time Intelligence + KQL + アラート)

**背景:** 製造業で数千台のセンサーから秒間数万件のテレメトリを収集し、異常値検知・Power BI でのライブ可視化・メール/Teams 通知を実現したい。

**構成イメージ:**

```
[IoT デバイス] ─→ Azure IoT Hub / Event Hubs
                         │
                         ▼
                    Eventstream (Fabric)
                         │
                         ▼
                    Eventhouse (KQL DB) ← OneLake と自動同期
                         │  (KQL クエリ)
            ┌────────────┼────────────┐
            ▼            ▼            ▼
     Real-Time      Activator      Power BI
     Dashboard      (アラート)       (Direct Lake)
                   → Teams通知 / Power Automate
```

**Fabric ならではのポイント:**

- Eventhouse はストリームデータを時系列で自動組織化するため、ADX を個別運用する必要がなくなる
- **"One logical copy"** — KQL DB に入ったデータは自動で OneLake にも反映され、Lakehouse や DWH からも同じデータを参照できる ([Real-Time Intelligence Overview](https://learn.microsoft.com/en-us/fabric/real-time-intelligence/overview))
- Activator でアラート条件を KQL で記述でき、Power Automate / Teams 連携もネイティブ
- バッチ分析用の履歴データと、ストリーム分析用のホットデータを**同じストレージ上で共有**できる

### シナリオ C: OLTP 業務データと分析の一体運用 (Fabric Databases + Mirroring + Power BI)

**背景:** SaaS アプリを新規開発、業務 OLTP データベースが必要。同時に経営ダッシュボードも提供したい。従来なら Azure SQL + ADF + ADLS + Synapse + Power BI の 5 サービス構成。

**構成イメージ:**

```
        [SaaSアプリ]
              │ CRUD
              ▼
     Fabric SQL database (OLTP, 2025 GA)
              │ ← 自動 Mirroring (built-in, zero-ETL)
              ▼
          OneLake (Delta 形式)
              │
    ┌─────────┴──────────┐
    ▼                    ▼
 Lakehouse            Power BI
 (Spark で分析)       (Direct Lake)
                          │
                          ▼
                     経営ダッシュボード
```

**Fabric ならではのポイント:**

- Fabric SQL database は秒単位でプロビジョニングされ、OneLake への **ビルトインミラーリング** でデータが即分析側に届く (2026/03 Preview で選択的なテーブル指定も可能)
- 従来 ADF でのバッチ ETL を書いていた部分が **ゼロコード** で完結
- OLTP テーブルのスキーマ変更が分析側に自動反映される
- Cosmos DB in Fabric (2025 GA) を使えば、同じ仕組みを半構造化/地理分散の OLTP にも適用できる
- 2026/03 GA の Dynamic Data Masking (DDM) によって、同じデータベースで機微情報をマスクしたまま分析側に見せられる

---

### どれを選ぶ?

| ユースケース | 推奨シナリオ |
| --- | --- |
| 複数ソースを統合した BI ダッシュボード | A (Lakehouse + Medallion) |
| ストリーム/ログの即時監視と異常検知 | B (Real-Time Intelligence) |
| 業務アプリを新規開発しつつ分析も提供 | C (Fabric Databases + Mirroring) |
| 上記の複合 | 同一 Workspace 内で組み合わせ可 |

Fabric の肝は **「これらのシナリオを同じ OneLake / Capacity / ガバナンス基盤の上で組み合わせられる」** 点にあります。例えばシナリオ B の Eventhouse の結果を、シナリオ A の Gold テーブルと JOIN して Power BI に出す、といった横断利用が追加コストなしで可能です。

---

## まとめ

Fabric を Azure 視点で端的にまとめると、次の 3 つに集約されます。

1. **Fabric = SaaS 基盤 + OneLake + 7 ワークロード + Capacity 課金**
   - プラットフォーム層が OneLake・ガバナンス・Copilot を提供し、その上に 7 種類のワークロードが載る
2. **OneLake が中心で、Delta/Iceberg 相互運用 + Shortcut で「ゼロコピー」を実現**
   - ADLS Gen2 のサブセット互換なので、既存データ資産は Shortcut で繋げる
3. **Capacity = Azure リソース、Workspace = 論理コンテナ、Item = サービスインスタンス**
   - F SKU は Azure サブスクリプションで秒単位課金、ポーズ/再開可能、Reservations で割引

Fabric を「Synapse + Power BI Premium + ADF の統合後継」と捉えつつ、**課金単位とストレージの統一こそが本質の変化** だと理解しておくと、以降の設計議論が格段にスムーズになります。具体的なワークロード選定やマイグレーション計画を立てる際は、本記事で挙げた公式 Docs の各ページが起点になります。

## 参考資料

- [What is Microsoft Fabric - Microsoft Learn](https://learn.microsoft.com/en-us/fabric/fundamentals/microsoft-fabric-overview)
- [OneLake documentation](https://learn.microsoft.com/en-us/fabric/onelake/)
- [OneLake shortcuts](https://learn.microsoft.com/en-us/fabric/onelake/onelake-shortcuts)
- [Use Iceberg tables with OneLake](https://learn.microsoft.com/en-us/fabric/onelake/onelake-iceberg-tables)
- [Architecture of Fabric Data Warehouse](https://learn.microsoft.com/en-us/fabric/data-warehouse/architecture)
- [What Is Real-Time Intelligence](https://learn.microsoft.com/en-us/fabric/real-time-intelligence/overview)
- [Data Science in Microsoft Fabric](https://learn.microsoft.com/en-us/fabric/data-science/data-science-overview)
- [What is Data Factory (Fabric)](https://learn.microsoft.com/en-us/fabric/data-factory/data-factory-overview)
- [Differences between Data Factory in Fabric and Azure](https://learn.microsoft.com/en-us/fabric/data-factory/compare-fabric-data-factory-and-azure-data-factory)
- [Migration from Synapse dedicated SQL pool to Fabric Warehouse](https://learn.microsoft.com/en-us/fabric/data-warehouse/migration-synapse-dedicated-sql-pool-warehouse)
- [Understand Microsoft Fabric Licenses](https://learn.microsoft.com/en-us/fabric/enterprise/licenses)
- [Buy a Microsoft Fabric subscription](https://learn.microsoft.com/en-us/fabric/enterprise/buy-subscription)
- [Manage your Fabric capacity](https://learn.microsoft.com/en-us/fabric/admin/capacity-settings)
- [Microsoft Fabric Capacity Planning Guide](https://learn.microsoft.com/en-us/fabric/enterprise/capacity-planning-plan-deployment)
- [What's New in Microsoft Fabric](https://learn.microsoft.com/en-us/fabric/fundamentals/whats-new)
- [Fabric November 2025 Feature Summary](https://blog.fabric.microsoft.com/en-us/blog/fabric-november-2025-feature-summary/)
- [Analytics End-to-End with Microsoft Fabric (Azure Architecture Center)](https://learn.microsoft.com/en-us/azure/architecture/example-scenario/dataplate2e/data-platform-end-to-end)
- [Lakehouse end-to-end scenario](https://learn.microsoft.com/en-us/fabric/data-engineering/tutorial-lakehouse-introduction)
- [Introducing the end-to-end scenarios in Microsoft Fabric](https://blog.fabric.microsoft.com/en-US/blog/introducing-the-end-to-end-scenarios-in-microsoft-fabric/)
