---
title: "Microsoft Purview 実践編 — Data Map × Unified Catalog で作るデータガバナンス基盤の設計"
emoji: "🏛️"
type: "tech"
topics: ["microsoftpurview", "azure", "datagovernance", "datacatalog", "microsoftfabric"]
published: false
---

## はじめに

[前回記事「データガバナンス入門 — なぜ今必要で、何を押さえるべきか」](./data_governance_basics) では、特定のツールに寄らない中立的な地図として、データガバナンスの **定義・目的・8 つの構成要素・DMBOK・運用モデル** を整理しました。

ただし本記事は Purview のハンズオンではありません。**各機能をボタン単位で説明する**のではなく、次の問いに答えることを狙っています。

- Microsoft Purview は結局、何と何の統合体なのか
- **Data Map と Unified Catalog の関係**は何か(新旧の区切り目はどこか)
- **Governance Domains と Collections** はどう使い分けるのか
- スキャン・用語集・データプロダクトの設計で先に決めるべきは何か
- 課金(pay-as-you-go / DGPU / Data Map CU)はどこで効くのか
- 非 Microsoft 環境(AWS/SaaS)でどこまで現実的か
- いつ Purview を選ばないべきか

想定読者は、前回の 8 構成要素マップを手元に置いて「で、Purview ならどこに何があるの?」を知りたい、データエンジニア / アーキテクト / データ PM の方です。

> ⚠️ **変動要素の注意**: Purview はここ数年で「Azure Purview」→「Microsoft Purview」→ 新 Unified Catalog と構造が大きく動いています。特に GA/プレビューの境目やリージョン展開は時期で変わります。本記事は 2025 年後半〜2026 年前半時点の公式ドキュメントを根拠にしていますが、採用判断時は必ず [What's new in Microsoft Purview](https://learn.microsoft.com/en-us/purview/whats-new) を直接確認してください[^whatsnew]。

---

## シナリオで見る全体像 — 「新規顧客の数字が 3 つ」をどう解くか

前回記事の冒頭で、こんなシナリオが出てきました。

> ある EC 企業の月曜朝の経営会議で、「先週の新規顧客数」が議題に。マーケは 12,400 人、CS は 9,850 人、財務は 11,200 人。3 つとも違う数字が出てきて、結論が次回持ち越しに。

この会社が Azure / M365 中心のスタック(ADLS Gen2 に生データ、Azure SQL Database にトランザクション、Azure Data Factory で日次 ETL、Microsoft Fabric の Lakehouse で中間層、Power BI でダッシュボード)を使っていると仮定して、**Purview を入れたあとに何がどう変わるか** を一枚絵にしてみます。後続章はこのシナリオに戻ってくる形で読み進めてください。

### 導入後のざっくり構成

```
 [ADLS Gen2]   [Azure SQL]        ←── 生データ / トランザクション
      │             │
      └──→ [Azure Data Factory] ──→ [Fabric Lakehouse] ──→ [Power BI]
                  │                       │                    │
                  ▼                       ▼                    ▼
   ┌───────────────────────────────────────────────────────────┐
   │     Microsoft Purview Data Map(登録 + スキャン)           │
   │   Classification:PII / Email / Credit Card 自動検出      │
   │   Lineage: ADF / Fabric / Power BI から自動取得          │
   └───────────────────────▲───────────────────────────────────┘
                           │ governed asset 化
   ┌───────────────────────┴───────────────────────────────────┐
   │  Microsoft Purview Unified Catalog                        │
   │  - Governance Domain: 「マーケティング」「CS」「財務」      │
   │  - Data Product: 「新規顧客 KPI(全社共通)」              │
   │  - Glossary Term: 「新規顧客」= 初回決済完了者             │
   │  - CDE: 「Customer ID」(テーブル横断の論理束)             │
   │  - Access Policy: PII を含むものは申請→承認フロー         │
   └───────────────────────────────────────────────────────────┘
```

### 月曜朝の会議はどう変わるか

Purview を導入した場合の「同じ会議」で起きることを並べると、次のようになります。

1. **用語集で定義が単一に**:Unified Catalog の Enterprise glossary に「新規顧客 = 月次で初回決済が完了したユニークな Customer ID」という定義が active term として登録されている。マーケ・CS・財務それぞれのレポートは、この term を参照していることが Purview 上で可視化されている。
2. **データプロダクトで「正」が 1 つに**:「新規顧客 KPI」という **Data Product** が Fabric Lakehouse のゴールデンテーブル上に定義されていて、Power BI の公式ダッシュボードはこれを参照。3 つのレポートのうち「どれを信じるべきか」が Unified Catalog の Data Product ページで明示されている。
3. **リネージで「数字の出所」が辿れる**:ダッシュボードの数字から **Power BI → Fabric Lakehouse → ADF pipeline → ADLS Gen2 の生ファイル** まで、**Purview が自動取得したリネージグラフ**をクリックでたどれる[^adfconnect][^lineagefabric]。データエンジニアに 1 週間かけて調査してもらう必要はない。
4. **PII は勝手に守られる**:ADLS Gen2 と Azure SQL のスキャン時に Classification が PII を検出し、Autolabeling policy で「Confidential - PII」ラベルが自動付与される[^sensitivity]。そのカラムを含むデータプロダクトは、アクセス要求→承認ワークフローが必須化される。
5. **オーナーが見える**:「新規顧客」用語のオーナーはマーケの Data Steward、データプロダクトのオーナーはデータ基盤チームのリード、と Unified Catalog 上で明示。揉めた時の意思決定者が 1 クリックで分かる。

前回記事で「ガバナンスがあると変わる 5 点」として抽象的に書いた項目が、そのまま **Purview の機能に 1:1 で対応している** のが分かるかと思います。以降の章は、この絵の各コンポーネントを分解して読んでいく流れです。

---

## Microsoft Purview の現在地 — 何と何の統合体なのか

### 製品群としての Purview

「Microsoft Purview」という名前は、単一製品ではなく **複数ソリューションを束ねるブランド** として使われています。大きく 2 系統に分かれます。

- **Data Governance 系**: Data Map、Unified Catalog(旧 Data Catalog)、Data Quality、Data Estate Health、Access Policies など — 本記事のスコープ
- **Risk & Compliance 系**: DLP、Information Protection(Sensitivity Labels の管理)、Insider Risk Management、eDiscovery、Audit など — 本記事では範囲外(ただし Sensitivity Labels は両者にまたがる)

Data Governance 側は、さらに **基盤(Data Map)** と **利用者層(Unified Catalog)** に分かれます。この層分けが理解できると、ライセンスもドキュメントも一気に読みやすくなります。

### 新旧 2 つのポータル体験

現在の Purview には **新旧 2 つの体験** が並走しています。

| 区分 | ポータル | カタログ体験 | 既定の課金 |
|---|---|---|---|
| 新 | Microsoft Purview portal | **Unified Catalog**(GA、段階展開中) | pay-as-you-go(governed assets + DGPU) |
| 旧 | Classic Microsoft Purview governance portal | **Classic Data Catalog** | Data Map Capacity Unit(CU)+ 追加メーター |

[Unified Catalog は複数リージョンで GA され、段階的にロールアウトが進んでいる状態](https://learn.microsoft.com/en-us/purview/unified-catalog) で、地域によってはまだ見えないことがあります[^uc]。また既存の Azure Purview(クラシック)顧客は、**新しい pay-as-you-go 課金への同意(consent)** を行うことで Unified Catalog に移行でき、同意しなければクラシック Data Catalog を継続利用できます[^billing]。

ここで重要なのは **Data Map 自体は新旧で共通** だという点です。スキャン機能・資産メタデータ・リネージ収集の土台は同じで、上に乗る利用者体験(カタログ)だけが新旧で差し替わります。

> 設計上の含意: アセットをスキャンして Data Map に入れた段階では「新旧どちらでも使える資産」になっています。カタログ側の体験は後から選択・移行できる、という構造です。

---

## アーキテクチャ全体図 — Data Map と Unified Catalog の関係

Purview の Data Governance 側は、ざっくり次のような 2 層構造です。

```
┌─────────────────────────────────────────────────────────┐
│ Unified Catalog(利用者層)                              │
│  - Governance Domains(組織的な器)                      │
│  - Data Products / CDE / Glossary Terms / OKRs          │
│  - Access Policies(セルフサービスアクセス要求)          │
│  - Data Quality / Data Estate Health                    │
└────────────────────────▲────────────────────────────────┘
                          │ ガバナンス概念として「紐づけ」
┌────────────────────────┴────────────────────────────────┐
│ Data Map(基盤)                                        │
│  - Data Sources の登録・スキャン(Integration Runtime)  │
│  - アセット / Schema / Classification / Lineage         │
│  - Collections(運用・アクセスの単位)                    │
│  - Sensitivity Labels の反映                            │
└─────────────────────────────────────────────────────────┘
```

公式の Plan ガイドも「**Data Map がアセットの地図を作り、Unified Catalog がそれをビジネス価値に紐づける**」という順で記述しています[^plan]。逆にいうと、Data Map に入っただけの資産は Unified Catalog の課金対象(governed asset)にはならず、ガバナンス概念(データプロダクトや CDE)に紐づけた瞬間に初めて governed asset としてカウントされる、という分かれ目があります[^billing]。

### 前回記事 8 ドメインとの対応表

前回整理した「データガバナンスの 8 構成要素」を Purview 側にマップすると次のようになります。

| 前回の 8 ドメイン | Purview 側の位置 |
|---|---|
| ① ポリシー・役割・組織 | Unified Catalog の **Domain Admin / Data Product Owner / Steward** ロール、Data Map の **Collection Admin** |
| ② データ品質管理 | Unified Catalog の **Data Quality**(ルール、スコアカード) |
| ③ メタデータ管理 | **Data Map**(スキャン結果、Schema、Classification) |
| ④ データカタログ | **Unified Catalog**(Discovery、Browse、Search) |
| ⑤ データリネージ | Data Map(自動収集)+ Unified Catalog(グラフ表示) |
| ⑥ MDM / 参照データ | 一部 **CDE(Critical Data Elements)** で論理統合。本格 MDM は別製品領域 |
| ⑦ アクセス制御・セキュリティ | **Unified Catalog Access Policies** + Microsoft Entra ID |
| ⑧ ライフサイクル管理 | 主に Risk & Compliance 側の Retention/Records(本記事は範囲外) |

「ガバナンス=単一ツール」ではなく「8 ドメインのどれを埋めるか」を先に決めてから Purview のどこを使うかを選ぶ、という前回記事の順番は、Purview を使う場合もそのまま通ります。

---

## Data Map — スキャン設計の勘所

Data Map は **データ資産のメタデータを最新に保つ地図** を提供する基盤です。データソースを **登録(Register)** し、**スキャン(Scan)** を回してメタデータを取り込みます[^datamap][^scanbp]。

### スケール単位としての Capacity Unit(クラシック課金時)

クラシック課金の場合、Data Map は **Capacity Unit(CU)** 単位で課金されます[^datamap][^datamapprice]。

- 1 CU = **25 Ops/sec のスループット + 10 GB のメタデータストレージ**
- 新規アカウントは常に 1 CU から開始し、需要に応じて **エラスティックスケール**(自動アップダウン)
- ストレージ超過だけでも次の CU に上がる(例: 25 Ops/sec のまま 15 GB なら 2 CU)
- 既定のエラスティック上限を超える場合はサポートチケットで上限引き上げ

> Unified Catalog に同意した顧客では、**Data Map のスキャン課金は発生しません**[^billing]。課金は後段で述べる Unified Catalog 側の 2 メーター(governed assets と DGPU)に一本化されます。

### スキャン設計の原則

公式の「Data Map scanning best practices」は、スキャン設計上の具体的な指針を明示しています[^scanbp]。

- **初回はフルスキャン、以降はインクリメンタル**。これは自動でそうなる挙動。
- スキャン頻度は **データソースの変更管理サイクルと揃える**(週次で構造が変わるなら週次スキャン)。
- **業務時間外にスケジュール** して、ソース側の負荷ピークを避ける。
- スキャンスコープは **granular に**。SQL Database なら schema/folder、Oracle/Hive/Teradata なら schema リストや pattern を明示。
- **親を部分的に選択** すると、その配下の将来アセットも自動で対象化される(仕様として押さえる)。
- **同一データソースを複数コレクションに重複登録できない**。これは「同じソースに矛盾するアクセス制御が付与されるリスク」を避けるための設計上の制約[^scanbp]。

### Resource Set と Advanced Resource Set

データレイクのような「大量の小ファイル群」を、**論理的に 1 つの資産に束ねる**仕組みが **Resource Set** です。Data Map はファイル名や配置パターンから自動でグルーピングします[^datamapprice]。

**Advanced Resource Set** を有効化すると、合計サイズ・パーティション数などの **集計値** が取得され、パターンルールの **カスタマイズ** も可能になります。ただしこの機能は **別メーター** で課金されます。未使用なら Resource Set アセット自体は Unified Catalog で見えるものの、集計プロパティは空になります。

### 統合ランタイム(Integration Runtime)の選択

データソースごとに、スキャンを実行する実行基盤を選びます[^ir]。

- **Azure Integration Runtime**: クラウド内リソースに公開ネットワーク経由。
- **Self-hosted Integration Runtime(SHIR)**: オンプレ・プライベートネットワーク・VPN 先のソース向け。
- **Managed VNet Integration Runtime**: プライベートエンドポイントで閉域から。
- **Multicloud Scanning Connector**: AWS などを対象にした別コネクタ経由。

**認証方式と IR の選択は、スキャンを作る前に必ず決めておく** こと、というのが Best practices の一貫した助言です[^scanbp]。

---

## Unified Catalog — 5 つのビジネス概念で「意味」を設計する

Unified Catalog の役割は、Data Map が収集した技術メタデータを **ビジネスの言葉に接続** することです。そのために次の **5 つのビジネス概念(business concepts)** が用意されています[^uc][^ucplan]。

### 1. Governance Domains

**組織の単位** で、ガバナンスのスコープを切ります。部門(マーケ、CS、財務)、地域(JP/EMEA)、事業(法人/個人)などが典型です。

- ドメインごとに **Domain Admin / Steward / Data Product Owner** を割り当てる
- ドメインは Unified Catalog 全体の中で **所有権・ポリシー・ラベルの適用先の束ね** として機能
- 「すべてのドメインが同じ成熟度である必要はない」ことを公式がはっきり述べている[^ucplan]。**成熟しているドメインから少数で始めて段階的に広げる**のが推奨

### 2. Data Products

データプロダクトは、**「ユースケースごとにまとめた資産のパッケージ」** です。テーブル、ファイル、Power BI レポート、Fabric アイテムなどを「新規顧客分析」「在庫可視化」のような利用目的単位で束ね、オーナー・説明・アクセス要求フローを付けて公開します[^uc]。

「データメッシュ」における **product thinking**(データをプロダクトとして扱う発想)の Purview 上の実装とも言えます。

### 3. Critical Data Elements(CDE、プレビュー)

CDE は、**論理的に同じ意味を持つが物理的には違う場所に散らばっている要素** を束ねる仕組みです。

> 例: テーブル A の `CustID` 列と、テーブル B の `customer_id` 列を、同じ `Customer ID` CDE にマップする。

CDE に **データ品質ルール** や **アクセスポリシー** を付けておけば、データ資産側の列にいちいち設定せずに、**データエステート全体で横断的に** 適用できます[^uc][^ucplan]。前回記事の「MDM」ドメインほど厳密ではありませんが、MDM に踏み込む前の第一歩として現実的です。

> 公式は「**ドメイン全体のカバレッジを完璧にしようとするな**。事業的に重要なデータ要素だけに絞る」と明言しています[^ucplan]。完璧主義はここでは逆効果。

### 4. Glossary Terms

用語集は Purview に **2 系統** あることに注意が必要です[^glossary]。

- **Classic business glossary**(旧)— Data Catalog/Data Map 側
- **Enterprise glossary(preview)** — Unified Catalog 側

Microsoft の Q&A 回答では、**Enterprise glossary を forward-looking な一次ソース** に位置づけ、classic は legacy として「既存ワークフローがある場合のみ利用、新規用語は作らない」方針が推奨されています[^glossary]。

Enterprise glossary の特徴は、用語を **active(有効化)** すると関連するアクセスポリシーが紐づいたアセットに伝播する、という動き方です。単なる辞書ではなく **「単一のポリシーアンカー」** として機能させられる点がポイント。

### 5. OKRs

データを **事業目標(Objectives and Key Results)** に直接結びつける概念です[^uc]。どの KPI がどのデータプロダクトに依存しているかを可視化し、ガバナンスの投資判断を「どのデータが価値に効くか」で優先順位付けできるようにします。

### 初期導入の現実的な順序

公式の Plan ガイドが示す手順は次の通りです[^ucplan]。

1. **既に強いスチュワードがいる**領域を選び、少数のドメインを作る
2. スチュワード・データプロダクトオーナーを割り当てる
3. Data Map 側で並行してスキャンを回しアセットを供給
4. ドメインを **draft のまま** いくつかデータプロダクトを揃える
5. **publish** して Global Catalog Reader 権限で最初のユーザーに解放
6. フィードバックを元に、次のドメイン or 既存データプロダクトを拡張

「**最初の数人の熱心なユーザーに届ける**→実用例で優先順位を決める」という順は、前回記事の「痛みが大きい領域から始めて段階的に広げる」とそのまま整合します。

---

## Governance Domains と Collections の使い分け

新アーキテクチャでは **Domains と Collections の 2 階層** でガバナンスが組まれます[^dc]。名前が似ていて混乱しやすい領域なので、公式の定義を素直に読むのが早道です。

### それぞれの役割

| 区分 | 性格 | 主目的 | 管理対象 |
|---|---|---|---|
| **Domain** | 戦略・ポリシー中心 | 部門/地域/事業の論理分離、デリゲーション、セキュリティ分離 | データソース、アセット、スキャン、接続、認証情報、ポリシーなどの**最上位の束** |
| **Collection** | 運用・アクセス中心 | Data Map 内でデータソース・スキャンを階層化 | データソース登録、スキャン定義、コレクション単位のアクセス |

公式は明確に「**Domains are more strategic and policy-centric, while collections are more operational and access-centric**」と表現しています[^dc]。

### 典型パターン(ヘルスケアの例)

公式ガイドに載っている例をそのまま引くと、Contoso Health のような組織なら次のような切り方になります[^dc]。

- **Domains**: `Hospitals` / `Clinics` / `Research` / `Administration`
- 各 Domain 配下の **Collections**: `Production`, `Non-production`, `Regional-JP`, `Regional-EMEA` のような運用軸

つまり **Domain は「誰の・何の責任範囲か」、Collection は「どこに・どうやって物を並べるか」**。この 2 軸を取り違えて **同じ切り口で二重に切る** と、即座に運用コストが跳ね上がります(典型的な落とし穴)。

### 階層設計の注意点

- 前提: **テナントレベルアカウント** を使っていること(Best practices はこの前提)[^dc]
- **深すぎる階層** は技術制約ではなく **運用オーバーヘッド**(権限、スキャン設定、責任分担の煩雑化)で破綻する、というのが公式 Q&A の回答[^dchierarchy]
- アップグレード時:クラシックアカウントのルートコレクションが、新体験では **「デフォルトドメイン」** に昇格する。既存権限はそのまま引き継がれる[^dcmanage]
- Domain admin / Collection admin の **分業** を先に決めておく。Domain admin はドメイン内のすべてを管理でき、Collection admin は権限が絞られる

### デフォルトドメインの扱い

すべての Data Map は **1 つのデフォルトドメイン** から始まります[^dcmanage]。最初は「本当に必要になるまで追加しない」くらいの慎重さで、まずデフォルトドメイン上で 1 ドメイン分の運用を作ってから分割するのが安全です。

---

## 分類(Classification)と機密度ラベル(Sensitivity Labels)

Purview の機密度管理は **2 層** で動きます[^sensitivity][^classification]。

- **Classification**: スキャン時にデータの型やパターン(メールアドレス、クレジットカード番号など)を検出し、自動でタグ付け
- **Sensitivity Labels**: Microsoft 365 / Information Protection と **共通** のラベルを、Data Map 上のアセットにも適用

Sensitivity Labels は、ラベルの **scope が「Files & other data assets」** になっているものが Data Map アセットに適用可能です[^sensitivity]。M365 側(Word/Excel など)で使っている「Confidential」などのラベルを、そのまま DB のテーブルや Data Lake のファイルにも適用できる、というのが統合のキモ。

### 適用フロー

1. Sensitivity Label を作成(または既存を利用)
2. アセットを Data Map に登録・スキャン
3. スキャン中に **Classification が自動検出** される
4. **Autolabeling policy** により、特定の Classification が見つかれば対応するラベルを **自動付与**[^sensitivity]

手動でラベル付けする運用もありますが、**大規模環境で破綻しないのは Autolabeling 前提** です。

### 対応データソースの広がり

2025 年の更新で Sensitivity Labels 適用可能なデータソースが大きく拡張されました[^whatsnew]。一部抜粋:

- Azure Cosmos DB for SQL API
- Azure Data Explorer
- Azure Database for MySQL / PostgreSQL
- Azure Databricks Unity Catalog
- Azure SQL Managed Instance
- Azure Synapse Analytics(Workspace)
- Snowflake
- SQL Server
- Amazon S3
- Microsoft Dataverse

非 Microsoft 系(Snowflake、Amazon S3)にも正式対応している点は、前回記事で「Purview は非 Microsoft 環境では弱い」と書いたイメージを **一定アップデート** すべきポイントです(ただしコネクタ全体の対応範囲は下で書きます)。

---

## リネージの設計 — 「全部見せる」と破綻する

### 自動取得できる範囲

Purview は次の領域について **自動でリネージを取得** します。

- **Azure Data Factory / Synapse Pipelines**(Copy / Data Flow)
- **Microsoft Fabric**(スキャン後、アイテム間の依存)[^lineagefabric]
- **Power BI**(ワークスペース内のデータセット・レポート・ダッシュボード)

それ以外は **Apache Atlas hooks / REST API** を介した **カスタムリネージ** として取り込む必要があります[^lineageclassic]。

### Fabric リネージの既知制約

Microsoft Fabric との連携は強力ですが、現時点で押さえておくべき制約がいくつかあります[^lineagefabric]。

- **Power BI 以外の Fabric アイテム**: 外部データソースを上流として表示することはまだ **非対応**
- **クロスワークスペースリネージ**(非 Power BI アイテム): 非対応
- **Notebook → Pipeline** のリネージ: 非対応
- **Lakehouse テーブル/ファイルのサブアイテムリネージ**: 未対応(サブアイテムメタデータはプレビュー提供)

つまり「Fabric を入れれば全部が自動で繋がる」わけではなく、**組織の境界(ワークスペース越え)や特定の組み合わせでは繋がらない** ことを前提に設計する必要があります。

### 設計原則:「全部見せる」をやめる

Microsoft の Q&A 回答で興味深いのは、**リネージを単純化する方向が推奨されている** ことです[^lineageqna]。

- Cloud Adoption Framework は「**データプロダクト** 間のリネージを中心に見せ、全ての技術オブジェクトを展開しない」ことを推奨
- Fabric 利用時は「**Fabric 層のみをスキャンする** オプション」を使い、上流システムが既にガバナンスされているなら上流ノードを省く
- 技術レベルの詳細リネージは **技術ユーザー向け** に留め、業務ユーザーには **データプロダクトレベルの簡略版** を見せる
- Power BI のワークスペースリネージビューは、業務ユーザー向けの見やすい可視化に使う
- Sensitivity Labels を一貫して付けることで、ユーザーがリネージ上の「重要ノード」を識別しやすくする

> 「リネージは技術的には全部見せられる」と「**全部見せたほうが分かりやすい**」は、直感とは逆です。リネージは **意思決定に使える粒度** で見せるのが設計の仕事です。

---

## Azure サービスとの連携パターン(具体例)

ここまでの概念を、**冒頭のシナリオで使われる Azure サービスごと** にどう配線するかを見ていきます。それぞれ「何を認証情報として渡すか」「どのロールを必要とするか」「自動 vs 手動の境界はどこか」が微妙に違うので、**導入時に先に設計しておくべき差分** として押さえてください。

### ADLS Gen2(データレイク)の登録・スキャン

EC 企業のシナリオでは、生データが ADLS Gen2 に溜まっています。Purview への接続は次の流れです[^adls][^adlsregister]。

1. **データソース登録**: Purview portal の Data Map → Data sources → Register → Azure Data Lake Storage Gen2 を選び、対象の Subscription / アカウント / 登録先 Collection を指定
2. **権限付与**: Purview の **System Assigned Managed Identity(MSI)** または User Assigned Managed Identity(UAMI)に、対象 ADLS Gen2 の **Storage Blob Data Reader** 相当のロールを Subscription / RG / Resource のいずれかのスコープで付与[^adlsregister]
3. **スキャン設定**: AutoResolve Integration Runtime を選び、Scan rule set(File types、Classification rule)を設定してスケジュール(初回フル、以降インクリメンタル)

> 落とし穴: MSI へのロール付与は **Subscription の Owner でないと付けられない**。Purview 管理者と Subscription Owner が分かれている組織では、**先に権限委譲のプロセスを決めておく** のが現実的。

### Azure Data Factory(ETL パイプライン)のリネージ連携

シナリオの「生データ → Lakehouse」の変換は ADF が担います。ADF と Purview をつなぐと、**Copy / Data Flow アクティビティからリネージが自動で Purview にプッシュ** されます[^adfconnect]。

- **配線**: ADF Studio の Manage → Microsoft Purview → **Connect to a Microsoft Purview account** から接続(ADF の Contributor/Owner 権限が必要)
- **認証**: ADF の **System Assigned Managed Identity** を使って Purview にリネージ情報をプッシュ
- **Purview 側のロール**: ADF の Managed Identity に、Purview の **ルートコレクション上で Data Curator ロール** を付与[^adfconnect]
- **Firewall 注意**: Purview アカウントがファイアウォール保護されている場合、**ADF のアクティビティを実行する IR も Purview に到達できる** 経路が必要

> 設計上の含意: ADF の Copy / Data Flow で表現される変換だけが自動リネージの対象。**Notebook 内の SQL や自作 Python の変換はここに載らない**(これは後述の Databricks や Atlas で補う)。

### Microsoft Fabric(Lakehouse / Power BI の新世代)

Fabric 内の Lakehouse / Warehouse / Dataflow、そして Power BI ワークスペースは、**Fabric テナント単位** で Purview に登録します[^fabricregister][^lineagefabric]。

- **登録**: Data Map → Sources → Fabric(Power BI)を追加。同一テナントなら既定のテナント ID、別テナントなら対象の Tenant ID を指定してクロステナント登録
- **認証**: Microsoft Entra **サービスプリンシパル** または **Delegated auth**。Fabric 側の **Tenant settings で「Service principals can access read-only API」を有効化** する管理者作業が必要
- **スキャン**: 個人ワークスペースを含めるか除外するかを指定。設定変更すると**次回はフルスキャン**になる点に注意
- **既知制約の再掲**: 非 Power BI Fabric アイテムの外部データソース上流、クロスワークスペースリネージ、Notebook → Pipeline は未対応(「リネージの設計」章参照)

### Power BI 単独のワークスペース

Fabric 経由で一括登録するのが本筋ですが、**Power BI のみを既存で使っている組織** もあります。その場合も同じ仕組み(サービスプリンシパル+読み取り API)で登録でき、レポート・データセット・ダッシュボードと、その上流のデータソースがリネージに載ります。

シナリオでは「Power BI ダッシュボードから遡って Fabric Lakehouse → ADF → ADLS Gen2 まで辿れる」と書きましたが、これは **ADF・Fabric・Power BI のそれぞれで Purview 連携が設定されている** ことで初めて成立します。どこか 1 か所が欠けると、そこでリネージが途切れる。

### Azure SQL Database / Synapse(dedicated SQL pool)

EC 企業のトランザクション DB は Azure SQL と仮定していました。Azure SQL Database、Azure SQL MI、Synapse(dedicated/serverless)はいずれも Data Map でスキャンでき、**2025 年の更新で Sensitivity Label 対応が大きく拡張** されました[^whatsnew]。

- 認証は SQL 認証 / Microsoft Entra Auth / Managed Identity のいずれか
- 閉域ネットワーク上にある場合は **Self-hosted IR** または **Managed VNet IR** を使う[^ir]
- Synapse 側のクエリリネージは **Synapse Pipelines(ADF 相当)** 経由のみ自動取得。SQL スクリプト直書きの変換は自動では載らない[^lineageqna]

### Azure Databricks / Unity Catalog

シナリオには入れていませんが、前回記事の「連携パターン」で触れた「ハイブリッド運用(中央カタログ × プラットフォーム内蔵)」の典型が Databricks です。

- Databricks **Unity Catalog のカタログ・スキーマ・テーブル**は Purview にスキャン登録可能[^whatsnew]
- Databricks 側のノートブック実行のリネージは、**Spark での変換を Purview が完全には自動取得しない**ため、Atlas hook / REST API 経由のカスタムリネージで補完するパターンが一般的[^lineageclassic]
- Unity Catalog 側のポリシー(row/column-level security)は Databricks 側のエンジンが実行、Purview 側は Sensitivity Label + Access Policy の「タグ」側を担当、という役割分担

### 連携時の共通ポイント

各サービス共通で効いてくる設計上のコツを整理しておきます。

- **認証の最小権限原則**: Purview MSI / サービスプリンシパルに過剰な権限を付けない。**必要なのは Read + メタデータ取得**で、書き込み権限は要らない
- **Integration Runtime を先に決める**: 閉域要件のあるデータソース(オンプレ、Private Endpoint)は **Self-hosted IR または Managed VNet IR** が必須。後から変更するとスキャン再設定が必要
- **スキャンのスケジュール分散**: 同じ時間帯にすべてのソースをスキャンすると、ソース側にも Purview 側にも負荷が集中する。**業務時間外かつソースごとにずらす** のが基本[^scanbp]
- **Domain / Collection の配線を先に決める**: データソース登録時に配置する Collection を間違えると、権限委譲とセキュリティ分離が崩れる。**スキャンを回す前に 2 軸設計を終えておく**

### シナリオに戻って — EC 企業の実配線を最初から最後まで

上記の各論を、**冒頭 EC 企業の実配線** として 1 本につなげて書いてみます。多少前章と重複しますが、**「どのサービスを、誰が、どう設定して、何を得るか」** を省略せずに書くことで、読後すぐに自社にマッピングできる粒度を目指します。

#### (0) 前提のデータ構造

仮の EC 企業 **Contoso EC** は、次のようなデータ資産を持っています。

- **ADLS Gen2**(`contosoeclake` アカウント): 3 ゾーン構成
  - `raw/` — 各システムからの日次ダンプ(Parquet / CSV)
    - `raw/crm/customers/yyyy=.../mm=.../dd=.../*.parquet`
    - `raw/shop/orders/yyyy=.../mm=.../dd=.../*.parquet`
    - `raw/marketing/events/yyyy=.../mm=.../dd=.../*.json`
  - `curated/` — Fabric Lakehouse が参照する中間層
  - `presentation/` — Power BI が直接読むゴールデンテーブル層
- **Azure SQL Database**(`contoso-ec-txdb`): オンライン EC のトランザクション DB
  - `dbo.Customer`(customer_id, email, phone, first_purchase_at, …)
  - `dbo.Orders`(order_id, customer_id, order_status, paid_at, …)
  - `dbo.Payment`(payment_id, order_id, card_last4, amount, …)
- **Azure Data Factory**(`adf-contoso-ec`)
  - `pl_daily_crm_ingest`: CRM → `raw/crm/customers/` の Copy
  - `pl_daily_tx_ingest`: Azure SQL `dbo.Orders` / `dbo.Payment` → `raw/shop/orders/` の Copy(差分抽出)
  - `pl_curated_build`: `raw/*` → `curated/*` の Mapping Data Flow
- **Microsoft Fabric**(テナント: `contoso.onmicrosoft.com`)
  - ワークスペース `ws-analytics-prod`
    - Lakehouse `lh_commerce`: `curated/*` を Shortcut 参照、派生テーブル `dim_customer`, `fact_order`, `fact_payment`
    - Notebook `nb_new_customer_kpi`: `dim_customer` + `fact_payment` から `kpi_new_customer_daily` テーブルを生成
  - ワークスペース `ws-bi-prod`
    - Power BI セマンティックモデル `sm_new_customer_kpi`(Lakehouse の `kpi_new_customer_daily` を Direct Lake)
    - Power BI レポート `rpt_weekly_exec`(月曜朝の会議で使う「公式」ダッシュボード)

前回の会議での議論対象である「先週の新規顧客数」は、厳密には **`kpi_new_customer_daily.new_customer_count` の週次集計** に対応する、という定義を **これから Purview 上で確定していく** のが以下の流れです。

#### (1) Purview アカウント作成とドメイン設計(Day 0)

- `pv-contoso-ec` という Purview アカウントを作成(テナントレベル・新ポータル体験)
- **Governance Domain** を 4 つ:
  - `Marketing`(オーナー: マーケ部門の Data Steward)
  - `CustomerSupport`(オーナー: CS 部門の Data Steward)
  - `Finance`(オーナー: 経理部門の Data Steward)
  - `Commerce-Shared`(オーナー: データ基盤チーム。**新規顧客 KPI のような全社横断指標の置き場所**)
- **Collection** は運用軸で別に切る:
  - ルート配下に `prod` / `nonprod` / `sandbox`
  - `prod` 配下に `data-lake` / `tx-db` / `etl` / `fabric`(データソース種別でさらに分ける)

設計の要点: **Domain(戦略)と Collection(運用)で軸が違う** のが、この時点で効いてきます。`Marketing` ドメインは複数の Collection にまたがった資産を「マーケの責任範囲」として束ねる役割。Collection は「ADLS の管理は誰、Azure SQL の管理は誰」という運用担当分けに使う。

#### (2) ADLS Gen2 の登録・スキャン(Day 1)

データ基盤チームが ADLS Gen2 を Data Map に登録します[^adls][^adlsregister]。

1. **ロール付与(Azure portal 側)**: `contosoeclake` ストレージアカウントの Access Control (IAM) で、Purview の System Assigned Managed Identity(`pv-contoso-ec`)に **Storage Blob Data Reader** を付与
2. **Network 確認**: ストレージ側にファイアウォール/Private Endpoint があれば、Purview の Managed VNet IR を使う設定に切り替え(シナリオでは Public とする)
3. **登録(Purview 側)**: Data Map → Data sources → Register → Azure Data Lake Storage Gen2。Subscription、アカウント名 `contosoeclake`、Collection は `prod/data-lake`
4. **スキャン作成**:
   - Scan rule set: 標準 + **PII classification(Email、Phone number、Credit Card)を ON**
   - Scope: まず `raw/` と `curated/` のみ(`presentation/` は Power BI から読むだけなので後回しでも可)
   - Integration Runtime: `AutoResolveIntegrationRuntime`
   - Schedule: 初回は手動、以降は **毎日深夜 02:00 の増分スキャン**(ソース側の EC バッチが 01:00 に完了するため)
5. **結果の確認**: 初回スキャン後、`raw/shop/orders/` 配下の Parquet 群が **Resource Set** として自動グルーピングされ、`dbo.Customer` 相当の列で **Email / Phone が PII として Classification 付与** される

> この時点で、ADLS 配下のファイル群にはまだ Sensitivity Label はついていません。次の「Autolabeling policy」で自動化します。

#### (3) Azure SQL Database の登録・スキャン(Day 1 並行)

同じく Data Map に Azure SQL を登録します。

1. **認証の準備**: Purview MSI を `contoso-ec-txdb` で Entra ID 認証として許可(`CREATE USER [pv-contoso-ec] FROM EXTERNAL PROVIDER; ALTER ROLE db_datareader ADD MEMBER [pv-contoso-ec];`)
2. **登録**: Azure SQL Database を Collection `prod/tx-db` に登録
3. **スキャン設定**: PII Classification を含む rule set を適用。毎日深夜 03:00 に増分スキャン
4. **結果**: `dbo.Customer.email` に Email Classification、`dbo.Payment.card_last4` に Credit Card 関連 Classification が付与

#### (4) Sensitivity Labels と Autolabeling policy(Day 2)

情報セキュリティ部門が持っている M365 Sensitivity Label(`Confidential - PII`, `Confidential - Financial`, `Internal`)を Purview でも活用します[^sensitivity]。

1. **ラベルのスコープ確認**: Purview compliance portal 側で、`Confidential - PII` の scope に **「Files & other data assets」** が含まれていることを確認(含まれていなければラベル定義を修正)
2. **Autolabeling policy 作成**:
   - 条件: Classification = `Email` OR `Phone` OR `Credit Card` を含む資産
   - アクション: `Confidential - PII` ラベルを自動付与
   - 対象 Collection: `prod/data-lake`, `prod/tx-db`
3. **再スキャンまたは手動実行**: 既存アセットに対してもポリシーを適用。`dbo.Customer` テーブル、`raw/crm/customers/*.parquet` に `Confidential - PII` が自動付与される

**ここが重要**: このラベルは M365 側の Word/Excel とも共通。仮に誰かが `dbo.Customer` から抽出した CSV を OneDrive に上げても、**同じ `Confidential - PII` ラベルが引き継がれる**(Information Protection 統合の効用)。

#### (5) Azure Data Factory からのリネージ自動取得(Day 3)

ADF 側の 3 本のパイプライン(`pl_daily_crm_ingest`, `pl_daily_tx_ingest`, `pl_curated_build`)を Purview に接続します[^adfconnect]。

1. **ADF の MSI 有効化**: `adf-contoso-ec` の Identity ブレードで System Assigned Managed Identity を有効化
2. **Purview 側のロール付与**: Purview の**ルートコレクション**で、ADF MSI に **Data Curator** ロールを割り当て
3. **ADF → Purview 接続**: ADF Studio → Manage → Microsoft Purview → `pv-contoso-ec` を Connect
4. **テストラン**: `pl_curated_build` を 1 回実行してみる
5. **結果**: Purview 側の `curated/dim_customer` や `curated/fact_order` の **Lineage タブに ADF の Copy / Mapping Data Flow が表示され**、`raw/*` からの流れが自動で可視化される

> 注意: `pl_daily_tx_ingest` の差分抽出クエリに入っている「Stored Procedure 呼び出し」部分は、ADF 側で Stored Procedure アクティビティが認識できる範囲しかリネージに載りません。Stored Procedure 内の SQL ロジックはブラックボックスになるため、**業務上重要ならリネージへの補足記述(説明 + カスタムリネージ)を入れる** のが現実的。

#### (6) Microsoft Fabric テナントの登録・スキャン(Day 4)

Fabric の Lakehouse と Power BI 資産を Purview に取り込みます[^fabricregister][^lineagefabric]。

1. **サービスプリンシパル作成**: Entra ID で `sp-purview-fabric-scan` を作成、シークレットを Purview 側の Credential として登録
2. **Fabric Tenant settings(Fabric 管理者)**:
   - 「Service principals can access read-only admin APIs」を **有効化**
   - 対象セキュリティグループに `sp-purview-fabric-scan` を含める
3. **データソース登録**: Purview Data Map → Register → Microsoft Fabric。Tenant ID は自テナント。Collection は `prod/fabric`
4. **スキャン設定**: 個人ワークスペースは除外。AutoResolve IR。週次で実行(Fabric は構造変化が頻繁でないため)
5. **結果**:
   - Lakehouse `lh_commerce` の `dim_customer`, `fact_order`, `fact_payment`, `kpi_new_customer_daily` テーブルが資産として登場
   - Notebook `nb_new_customer_kpi` も資産として可視化(ただし **Notebook → テーブルの自動リネージは現時点では非対応**[^lineagefabric])
   - Power BI の `sm_new_customer_kpi` → `rpt_weekly_exec` のリネージは自動取得

> Notebook からテーブルへのリネージは、**OpenLineage 出力の設定 + Atlas REST API でカスタム投入** するか、Data Product に紐づけて「ロジカルな矢印」として見せるパターンが現実的[^lineageclassic][^lineageqna]。

#### (7) ここまでで見えている「壊れているリネージ」

4 日かけて全ソースを登録しましたが、リネージグラフを眺めると **途切れている箇所** があります。

- ✅ `raw/*` → `curated/*`: ADF の Mapping Data Flow で自動
- ❌ `curated/*` → `lh_commerce.*`: Fabric Shortcut での参照は自動リネージに載りづらい(テーブルとしては認識される)
- ❌ `lh_commerce.dim_customer + fact_payment` → `kpi_new_customer_daily`: Notebook の中身が載らない
- ✅ `kpi_new_customer_daily` → `sm_new_customer_kpi` → `rpt_weekly_exec`: Fabric / Power BI の自動リネージで繋がる

現実のプロジェクトでは **全自動で完璧なリネージは得られない** のが普通です。ここで取る選択は次のどちらか。

- **A案**: Notebook のロジックを Data Flow または Fabric Pipeline に置き換えて自動リネージに乗せる(技術的コストあり)
- **B案**: Atlas REST API で Notebook のカスタムリネージを投入する(初期実装が必要、継続メンテが要る)
- **C案**: 「Data Product レベル」のリネージだけを公式見解にし、Notebook の詳細は技術者向けドキュメントに切り離す[^lineageqna]

Contoso EC は **C 案**を選び、業務ユーザーにはデータプロダクト起点のリネージだけ見せる方針にします。

#### (8) Unified Catalog でビジネス概念を作る(Week 2)

ここからがマーケ・CS・財務部門の出番です。技術配線が終わったので、**意味の設計** を Unified Catalog 上で進めます。

**(8-a) Enterprise glossary term**

- `Marketing` ドメイン配下に用語 **「新規顧客(New Customer)」** を作成
  - 定義: **「当月内に `dbo.Payment` で初回の決済完了(`status = Paid`)を記録した Customer ID のユニーク数」**
  - オーナー: マーケティング部門の Data Steward
  - active 化し、アクセスポリシー(PII 含むので申請→承認)を紐づけ[^glossary]
  - 関連用語: `アクティブ顧客`, `リピート顧客` を synonym として登録
- CS と財務の既存定義(初回サイト登録 / 初回問い合わせ)は、**別の用語** として `CustomerSupport` や `Finance` ドメインに登録する。**同じラベルを違う意味で使い続けない** ことを、用語集として明示する

**(8-b) Critical Data Element**

- `Commerce-Shared` ドメインに **CDE「Customer ID」** を作成
- マッピング:
  - `dbo.Customer.customer_id`(Azure SQL)
  - `raw/crm/customers/*.parquet` の `custid` 列
  - `lh_commerce.dim_customer.customer_id`(Fabric)
  - `kpi_new_customer_daily.customer_id`
- 紐づけるデータ品質ルール: 「NULL 不許可」「Azure SQL 側で UNIQUE」「フォーマット = 10 桁数値」
- CDE にアクセスポリシーを紐づけると、**Customer ID を含むどの資産にも同じアクセス方針** が効くようになる

**(8-c) Data Product**

- `Commerce-Shared` ドメインに **Data Product「新規顧客 KPI(全社共通)」** を作成
- 含めるアセット:
  - Fabric テーブル `kpi_new_customer_daily`
  - Power BI セマンティックモデル `sm_new_customer_kpi`
  - Power BI レポート `rpt_weekly_exec`
- メタデータ:
  - 説明: 「新規顧客の定義は Glossary 『新規顧客』を参照。会議で参照される公式な数字はこの Data Product のものを使用する」
  - オーナー: データ基盤チームのリード
  - ステュワード: マーケティングの Data Steward(定義責任者)
  - 更新頻度: 毎日 04:00 に更新
- **アクセスポリシー**: 閲覧は全社員に対して Self-service で開放(承認不要)、ただし PII 列を含む下流データへのアクセスは承認フロー必須
- status を `Draft` → `Published` に変更

この瞬間に **`kpi_new_customer_daily`、`sm_new_customer_kpi`、`rpt_weekly_exec` の 3 資産が governed asset になり、課金メーターに乗る**[^billing]。逆に言うと、Data Product に紐づけていない `raw/*` や `curated/*` は governed asset としてはカウントされていない。

#### (9) 月曜朝の会議(Week 3)

運用に乗ったあとの月曜朝の会議はこうなります。

- 参加者は Power BI で `rpt_weekly_exec` を開き、「先週の新規顧客:11,480 人」と表示される
- マーケの参加者が「でもうちの別ダッシュボードは 12,400 人になっている」と言い出す
- 議長が **Power BI の「このビジュアルの情報」→ Purview で開く** を選ぶ
- Unified Catalog が開き、Data Product 「新規顧客 KPI(全社共通)」のページが表示され、Glossary の「新規顧客」定義(= 初回決済完了者)が先頭に書いてある
- マーケのダッシュボードは「初回サイト登録」を数えていたことが分かる(こちらは `Marketing` ドメインの **別 Data Product「マーケティングファネル KPI」** として存在する、という位置づけ)
- 「今日からは『新規顧客』という言葉を使うときは、公式 Data Product の値に揃える」という合意だけで、会議は 5 分で次の議題に移る

> 40 分の答え合わせが、5 分の合意形成に変わる — 前回記事で抽象的に書いた「ガバナンスの実務的価値」は、この **Purview の具体機能の組み合わせ** で実装されます。

#### (10) 運用に入ってから効いてくること

- **PII 誤流出の防止**: 財務が「決済ログが欲しい」と `dbo.Payment` にアクセス要求を出すと、CDE「Customer ID」と Sensitivity Label `Confidential - PII` が紐づいているため、**自動で承認フロー** に入り、承認者(データ基盤リード)がログインするまでアクセスできない
- **監査対応**: 「この KPI の数字はどう計算されたか」を監査法人から問われたら、Data Product ページの Lineage タブを見せるだけで、ADLS → ADF → Fabric Lakehouse → Power BI の流れが視覚的に示せる
- **新しいデータプロダクトの追加コスト**: 次に「リピート購入率 KPI」を作る時、すでに CDE「Customer ID」と Glossary「新規顧客」が整備されているため、それらを再利用できる。**最初の Data Product より圧倒的に短時間** で出せる

#### (11) 配線の一覧サマリ

以上を 1 枚の表に圧縮すると次の通り。

| レイヤ | 実リソース | Purview 側の配線 | 権限/認証 | 効用 |
|---|---|---|---|---|
| ストレージ | `contosoeclake`(ADLS Gen2) | Data Map 登録、PII Classification、Autolabel | Purview MSI に Storage Blob Data Reader | ファイル群が Resource Set 化、PII ラベル自動付与 |
| トランザクション DB | `contoso-ec-txdb`(Azure SQL) | Data Map 登録、Classification | Purview MSI を DB user、db_datareader | PII カラムに `Confidential - PII` ラベル |
| ETL | `adf-contoso-ec`(ADF) | Purview Connection、自動リネージプッシュ | ADF MSI に Purview Data Curator | Copy / Data Flow のリネージが自動取得 |
| レイクハウス/BI | Fabric テナント | Fabric テナント登録スキャン | SP `sp-purview-fabric-scan`、Fabric Tenant settings | Lakehouse テーブル・Power BI 資産がリネージ付きで可視化 |
| 意味 | Glossary 「新規顧客」 | Enterprise glossary active term | Marketing Domain Admin / Steward | 定義の一元化、ポリシーアンカー |
| 意味 | CDE 「Customer ID」 | 4 資産をマッピング、データ品質ルール付与 | Commerce-Shared Domain Admin | 横断的なデータ品質・アクセス管理 |
| 意味 | Data Product 「新規顧客 KPI」 | Fabric テーブル + セマンティックモデル + レポートを束ね、Published | Data Product Owner(基盤リード) | 「正」の一本化、アクセスフロー、governed asset 化 |

**ここで強調したいのは、各行の「Purview 側の配線」は単独では大した機能ではない** ということです。登録してスキャンするだけなら、他のカタログツールでもできる。価値が出るのは **全行が一つのメタデータ空間で繋がったとき** — リネージが端から端までつながり、Glossary がレポートに紐づき、Sensitivity Label が DB からファイルまで伝播する状態になって、はじめて月曜朝の会議が 5 分で終わるような体験になります。

---

## 非 Microsoft データソース(AWS / マルチクラウド / SaaS)

Purview は **Multicloud Scanning Connector** という別 add-on の仕組みで、非 Microsoft 環境もスキャン対象にできます[^s3][^rds]。スキャン先はクラウド側で実行され、**メタデータと分類結果だけが Azure 側に戻ってくる** という動きです。

### Amazon S3 の対応範囲

Amazon S3 は GA で対応しています[^s3]。ただし実装レベルの制約があります。

- 対象の粒度: **バケットのルートのみ**。サブフォルダ単位(`s3://bucket/sub/`)での登録は **非対応**
- Multicloud Scanning Connector は **別 add-on**(契約上も別扱い)
- 認証は AWS の IAM を用いた信頼関係でセットアップ

### Amazon RDS(Public Preview)

Amazon RDS も対応していますが **Public Preview** 段階で、さらに **AWS リージョンが限定** されています[^rds]。US East/West、Canada、EU 各種、アジア太平洋、南米、中東のリージョンのみ、といった形で全 AWS リージョンではありません。

### 採用判断の指針

Multicloud コネクタまわりは時期で動きやすいので、実運用で採用する前に以下を必ず確認してください。

- 対象サービス・対象リージョンの **最新対応表**(公式 Learn の各 Register ページ)
- GA か Preview か(Preview は SLA と互換性の保証が弱い)
- サブアイテム粒度でのサポート有無(S3 はバケットのみ、など)
- データ classification / sensitivity label まで対応しているか

前回記事でも触れたように、**Purview を「マルチクラウド中央カタログ」として使う場合、コネクタのサポート範囲が現実的な天井になる** という点は変わりません。見えない資産には governance が掛けられないので、**カバレッジを事前確認すること自体がアーキテクチャ判断** です。

---

## 課金モデル — Pay-as-you-go / DGPU / Data Map CU

### Unified Catalog(新)の 2 メーター

Unified Catalog は pay-as-you-go 課金で、**2 つのメーター** で決まります[^billing]。

#### ① Governed assets

- **「ガバナンス概念(データプロダクト / CDE / Glossary term など)に紐づけられた、ユニークなデータ資産」数/日** で課金
- Data Map に入っているだけの資産は **governed asset にはならない**(= 課金対象外)
- ガバナンス概念に紐づけた瞬間にカウントが始まる

これは設計上 **非常に重要な性質** です。「全資産をとりあえずスキャンして取り込む」ことはコストを発生させず、「どの資産をビジネス概念に束ねるか」という **意思決定** が課金に直結する、という構造になります。

#### ② Data Governance Processing Units(DGPU)

- **データ品質ルール実行や Data Estate Health の処理** に対してかかるメーター
- 実行量(run 数 × スケール)で課金
- ガバナンスドメイン横断で DGPU 消費量を可視化する admin ビュー(usage monitoring)あり[^whatsnew]

### クラシック Data Map の CU 課金

Unified Catalog に同意せず classic で続ける場合、Data Map は次で課金されます[^datamapprice]。

- **Elastic Data Map(CU 課金)**: 1 CU = 25 Ops/sec + 10 GB
- **Automated scanning & classification**: スキャンの CPU 時間相当
- **Advanced Resource Set**: ファイル群論理化の拡張機能(別メーター)

### 同意モデルと設計判断

- **新規顧客で Unified Catalog を使う**場合 → pay-as-you-go を有効化
- **既存 Azure Purview 顧客**は同意するまで classic 課金で継続
- **同意すると Data Map のスキャン課金が消え**、Unified Catalog 側メーターに統合される
- いずれの場合も **Data Map 上のアセットは維持** される(体験を切り替えてもデータは消えない)[^billing]

> PoC 設計の勘所:「資産をとりあえず Data Map に入れる」はそこまで怖くない。**何を governed asset にするか(= Unified Catalog 側で結びつけるか)** が課金と価値の両方を動かす。

---

## 設計パターンと運用の落とし穴

前回記事で書いた「**連携パターン × 運用パターン**」を Purview 機能に落としたものを整理します。

### 運用モデル × Purview 機能のマッピング

| 運用モデル | Purview での実装 |
|---|---|
| **中央集権(Centralized)** | デフォルトドメイン 1 つ。中央チームが Domain/Collection Admin を独占。Classification/ラベル/ポリシーも中央で統制 |
| **ハイブリッド(現実解)** | 中央が **共通 Glossary / CDE / Sensitivity Label** を定義。ドメイン内は各部門 Domain Admin/Steward に委譲。Data Quality ルールは中央テンプレを配布 |
| **連邦(Data Mesh 寄り)** | ドメイン単位で独立した Data Product オーナーシップ。Enterprise glossary を **横串の共通語彙** に使い、CDE でドメイン間の意味の衝突を吸収 |

公式の Best practice でも「全ドメインを同じ成熟度にする必要はない」と明言されており[^ucplan]、ハイブリッド運用は単に現実的というだけでなく **推奨される運用形** です。

### 典型的な落とし穴

実装で踏みやすい落とし穴を、公式記述や Q&A から拾うとおおむね次の通りです。

- **Domain と Collection を同じ切り方で切る**:「戦略 vs 運用」の 2 軸をそれぞれ別に切らないと、階層が二重になって維持不能になる[^dc]。
- **Classic と Enterprise の両方の Glossary で新規用語を作る**: 新規は Enterprise glossary に寄せる方針を決めないと、二重管理が発生し、どちらが正しいか分からなくなる[^glossary]。
- **スチュワード任命だけで権限を渡さない**: Purview では Domain Admin / Data Product Owner / Collection Admin 等を明示的に割り当てないと、名ばかり化しやすい。
- **データプロダクトに紐づけずに大量スキャン**: Data Map 側のアセット数だけ増えて、Unified Catalog の価値(discoverability, governance) がほとんど出ない。governed asset にならないので Unified Catalog 課金も出ず、メリットも出ない、という「スキャンしただけ状態」。
- **リネージを全資産で取ろうとする**: Fabric 制約・Atlas 実装コスト・ユーザーの可読性のいずれかで破綻する。**データプロダクト間のリネージ** に絞る[^lineageqna]。
- **Advanced Resource Set の課金を忘れる**: 大量ファイル環境では集計値が欲しくなるが、別メーターとして効いてくる[^datamapprice]。

---

## Purview を選ばない(または限定利用する)ケース

前回記事の「連携パターン」で触れた通り、Purview を選ばない方が素直なケースも明確にあります。

- **データ資産のほとんどが Snowflake 単独 / Databricks 単独**で、外部への波及が少ない
  → Snowflake Horizon / Databricks Unity Catalog で完結する方が、メタデータ収集・ポリシー適用ともにネイティブで軽い
- **AWS/GCP ネイティブが中心**で、Azure/M365 はほぼ使わない
  → Multicloud Scanning Connector でアセット可視化はできるが、**ポリシー適用・リネージ深掘り** は Microsoft エコシステムほどシームレスではない。AWS 側なら Glue Data Catalog + Lake Formation、GCP 側なら Dataplex + BigQuery policies の方が適合する領域が多い
- **Risk & Compliance(DLP / Insider Risk)だけ使いたい**
  → Data Governance 側を入れずに単独採用可能。本記事のスコープ外だが、M365 中心の組織では現実解
- **小規模で 1 プラットフォーム完結**、ビジネス用語集の需要も低い
  → 重量な Unified Catalog まで入れる必要はない。小さめの OSS/ SaaS カタログで十分なケース

逆に、**Microsoft スタック中心で複数のデータソースを横断** していて、**M365 の Sensitivity Label をデータ側まで効かせたい** なら、Purview の優位性が最大化します。選定は「最強のもの」より「自分たちの痛みと既存スタックとの適合」です。

---

## まとめ

- Microsoft Purview は **Data Map(基盤)× Unified Catalog(利用者層)× Risk & Compliance** の束。本記事は前者 2 つに絞った
- 前回の **8 ドメイン** はほぼそのまま Purview にマップできる。ただし MDM / ライフサイクルは部分的
- 新アーキテクチャでは **Domains(戦略)× Collections(運用)** の 2 軸で切る。軸を取り違えると即座に運用コストが跳ねる
- Unified Catalog の **5 ビジネス概念(Domains / Data Products / CDE / Glossary / OKRs)** が「何に governed asset を紐づけるか」の起点
- 課金は **資産単体ではなく「ガバナンス概念に紐づいた資産」と「DGPU 処理量」** で決まる。PoC は「スキャンは怖くない、紐づけが価値と課金を動かす」という前提で組む
- **リネージは全部見せるな**。データプロダクト間に絞って、詳細は技術ユーザー向けに残す
- **Sensitivity Labels** は M365 と共通。Autolabeling を前提に設計するのが大規模運用の条件
- **非 Microsoft 環境** は Multicloud Scanning Connector 次第。採用前に必ず対応表・GA/Preview 状況を公式で確認
- **選定は「最強」より「痛みと既存スタック適合」**。前回記事の原則がそのまま効く

### 次に読むと良いもの

- [Plan for Microsoft Purview Unified Catalog with best practices](https://learn.microsoft.com/en-us/purview/unified-catalog-plan) — ドメイン設計から初期導入まで最も実務的
- [Microsoft Purview domains and collections architecture and best practices](https://learn.microsoft.com/en-us/purview/data-gov-best-practices-domains-collections) — 2 軸設計の一次資料
- [Data Map scanning best practices](https://learn.microsoft.com/en-us/purview/data-map-scanning-best-practices) — スキャン設計の細かな勘所
- [Billing in Microsoft Purview Data Governance](https://learn.microsoft.com/en-us/purview/data-governance-billing) — 新旧課金モデルの判断基準
- [What's new in Microsoft Purview](https://learn.microsoft.com/en-us/purview/whats-new) — GA/Preview とリージョン対応の差分チェック

次の記事では、本記事で深く踏み込まなかった **Data Quality(ルール設計・スコアリング)** や、**Access Policies と Entra の条件付きアクセス連動** あたりを、手を動かせる粒度で扱う予定です。

---

## 参考文献

[^whatsnew]: [What's new in Microsoft Purview - Microsoft Learn](https://learn.microsoft.com/en-us/purview/whats-new)
[^uc]: [Learn about Microsoft Purview Unified Catalog - Microsoft Learn](https://learn.microsoft.com/en-us/purview/unified-catalog)
[^ucplan]: [Plan for Microsoft Purview Unified Catalog with best practices - Microsoft Learn](https://learn.microsoft.com/en-us/purview/unified-catalog-plan)
[^plan]: [Plan your Microsoft Purview data governance solution - Microsoft Learn](https://learn.microsoft.com/en-us/purview/data-governance-plan)
[^billing]: [Billing in Microsoft Purview Data Governance - Microsoft Learn](https://learn.microsoft.com/en-us/purview/data-governance-billing)
[^datamap]: [Learn about Microsoft Purview Data Map - Microsoft Learn](https://learn.microsoft.com/en-us/purview/data-map)
[^datamapprice]: [Pricing guidelines for the Microsoft Purview Data Map - Microsoft Learn](https://learn.microsoft.com/en-us/purview/data-gov-classic-pricing-data-map)
[^scanbp]: [Data Map scanning best practices - Microsoft Purview](https://learn.microsoft.com/en-us/purview/data-map-scanning-best-practices)
[^ir]: [Choose the right integration runtime for your scan - Microsoft Learn](https://learn.microsoft.com/en-us/purview/data-map-integration-runtime-choose)
[^dc]: [Microsoft Purview domains and collections architecture and best practices - Microsoft Learn](https://learn.microsoft.com/en-us/purview/data-gov-best-practices-domains-collections)
[^dcmanage]: [Manage domains and collections in the Microsoft Purview Data Map - Microsoft Learn](https://learn.microsoft.com/en-us/purview/data-map-domains-collections-manage)
[^dchierarchy]: [Clarification on Collection and Sub Collections Hierarchy Limits - Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/5807587/clarification-on-collection-and-sub-collections-hi)
[^sensitivity]: [Apply sensitivity labels to assets in the Microsoft Purview Data Map - Microsoft Learn](https://learn.microsoft.com/en-us/purview/data-map-sensitivity-labels)
[^classification]: [Data classification in Microsoft Purview Data Map - Microsoft Learn](https://learn.microsoft.com/en-us/purview/data-map-classification)
[^lineagefabric]: [Lineage for Microsoft Fabric items in Microsoft Purview - Microsoft Learn](https://learn.microsoft.com/en-us/purview/data-map-lineage-fabric)
[^lineageclassic]: [Classic Data Catalog lineage in Microsoft Purview - Microsoft Learn](https://learn.microsoft.com/en-us/purview/data-gov-classic-lineage)
[^lineageqna]: [Request for Guidance: Simplifying Data Lineage Visualization - Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/5845759/request-for-guidance-simplifying-data-lineage-visu)
[^glossary]: [Clarification on glossary strategy and consolidation - Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/5835385/clarification-on-glossary-strategy-and-consolidati)
[^s3]: [Register and scan Amazon S3 buckets - Microsoft Learn](https://learn.microsoft.com/en-us/purview/register-scan-amazon-s3)
[^rds]: [Amazon RDS Multicloud Scanning Connector for Microsoft Purview (Public preview) - Microsoft Learn](https://learn.microsoft.com/en-us/purview/register-scan-amazon-rds)
[^adls]: [Set up a Microsoft Purview data governance sample (ADLS Gen2 walkthrough) - Microsoft Learn](https://learn.microsoft.com/en-us/purview/data-governance-setup-sample)
[^adlsregister]: [Connect to and manage Azure Data Lake Storage Gen2 in Microsoft Purview - Microsoft Learn](https://learn.microsoft.com/en-us/purview/register-scan-adls-gen2)
[^adfconnect]: [Connect Data Factory to Microsoft Purview - Microsoft Learn](https://learn.microsoft.com/en-us/azure/data-factory/connect-data-factory-to-azure-purview)
[^fabricregister]: [Connect to and manage a Microsoft Fabric tenant (cross-tenant) in Microsoft Purview - Microsoft Learn](https://learn.microsoft.com/en-us/purview/register-scan-fabric-tenant-cross-tenant)
