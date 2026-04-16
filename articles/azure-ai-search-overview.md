---
title: "Azure AI Search 全体像ガイド ― どこにデータが置かれ、どう絞り込めるのか"
emoji: "🔍"
type: "tech"
topics: ["azure", "azureaisearch", "rag", "search"]
published: true
---

## この記事について

Azure AI Search（旧 Azure Cognitive Search）は「とりあえずベクトル検索できる DB」くらいの雑な説明で済ませてしまうと、いざ本番設計のときに痛い目を見るサービスです。特に次の 3 点は曖昧なまま進めると手戻りや事故に直結します。

- **データはどこに保存されるのか？** 元データのコピーは取られるのか？
- **データの追加・更新・削除はどう行うのか？** 何が自動で、何は自分でやる必要があるのか？
- **検索範囲をどこまで柔軟に絞り込めるのか？** アクセス制御はどうする？

この記事では Azure AI Search の全体像と他の Azure サービスとの関係性を押さえつつ、上記 3 点を公式 Docs ベースで明確に整理します。

:::message
想定読者は「Azure 上で検索や RAG を構築しようとしているエンジニアで、ベクトル検索の概念はすでに分かっている人」です。ベクトル検索の理論には踏み込みません。
:::

---

## 1. Azure AI Search とは何か（立ち位置と主要コンポーネント）

Azure AI Search は、フルマネージドのクラウド型検索サービスです。クラシックな全文検索から、現在主流の **RAG（Retrieval-Augmented Generation）** や **agentic retrieval** まで、検索を軸とした幅広いシナリオを 1 つのサービスで賄えるよう設計されています[^1]。

### 主要コンポーネント（これだけ覚えればよい）

| 名称 | 役割 |
| --- | --- |
| **Search service** | 契約単位。SKU（Tier）とリージョンを選んで作成する |
| **Index** | 検索対象の実体。JSON ドキュメント集合 + スキーマ。サービス内の内部ストレージに格納される |
| **Document** | Index 内の 1 レコード。内部的には JSON |
| **Data source** | Indexer が参照する外部データ接続（Blob/Cosmos DB/SharePoint など）の定義 |
| **Indexer** | Data source から Index へデータを引き込むクローラー（pull model）。skillset を駆動する |
| **Skillset** | indexing 中の AI 処理（chunk 分割、埋め込み生成、OCR、翻訳など）を束ねたもの |
| **Knowledge source / Knowledge base** | Agentic retrieval の管理オブジェクト。**Knowledge source** は Blob・SharePoint など個別データソースの抽象化で、**Knowledge base** は複数 source をまとめるコンテナ。権限制御と複数ソース横断検索の単位（2025-11-01-preview で導入・再設計） |

### 2 つのオペレーションフェーズ

Azure AI Search の動きはシンプルで、**Indexing（書き込み）** と **Querying（読み出し）** の 2 フェーズだけです[^1]。

- **Indexing**: JSON ドキュメントを index に投入する。テキストは転置インデックスに、ベクトルはベクトルインデックスに内部的に格納される。
- **Querying**: クライアントが検索リクエストを送り、結果を受け取る。

:::message
**Azure AI Search はあくまで「JSON ドキュメントを受け付ける検索エンジン」です**。元のファイル（PDF/Word/画像など）をそのまま受け付けるわけではありません。Indexer や skillset がその変換を担います。
:::

---

## 2. 他の Azure サービスとの関係マップ

Azure AI Search は単体で閉じたサービスではなく、Azure の他サービスと組み合わせて使うことを前提に設計されています[^2][^3]。主要な連携先を整理します。

### データソース系（何を「検索する」か）

Indexer で pull できる主なデータソース:

- **Azure Blob Storage / Azure Data Lake Storage Gen2**
- **Azure Cosmos DB**（NoSQL / MongoDB プレビュー / Gremlin プレビュー。Cassandra は非対応）
- **Microsoft OneLake**
- **Microsoft SharePoint in Microsoft 365**（プレビュー）
- **Azure SQL Database / Azure MySQL**（MySQL はプレビュー）
- **Logic Apps connectors（プレビュー）**: 上記以外の広いコネクタ群を経由してデータ取得

### AI 系（何で「賢くする」か）

- **Azure OpenAI**: 埋め込みモデルをベクトル生成に、LLM を agentic retrieval のクエリ分解に使う
- **Azure AI Foundry**: Foundry IQ のナレッジレイヤーとして Azure AI Search を利用[^4]
- **ビルトイン Skill**: OCR、翻訳、エンティティ抽出など。Skillset に組み込む
- **Custom Skill**: 自前の Azure Function などを Skill として差し込める

### セキュリティ系（どう「守る」か）

- **Microsoft Entra ID**: 認証（API キー不要のキーレス運用）、ACL メタデータ継承
- **Azure Private Link / Private Endpoint**: Inbound/Outbound の両方向でプライベートアクセス
- **Azure Key Vault**: CMK（Customer-Managed Keys）の鍵管理

一枚絵で言えば、Azure AI Search は **「外部ソースから引き込む → サービス内部のインデックスに保持 → クエリで返す」** を軸に、AI 系（埋め込み・LLM）とセキュリティ系（Entra/Private Link/Key Vault）が左右から支える構造です。

---

## 3. 【要注意①】データはどこに保存されるのか

もっとも混乱しやすいポイントです。結論から言えば次のとおりです。

:::message alert
**インデックスの実体は「Azure AI Search サービス内部のストレージ」に格納されます。元データ（Blob 等）はそのまま元の場所にも残るので、インデックス対象のコンテンツは原則として二重持ちになります。**
:::

### 何がサービス内部に置かれるのか

Microsoft 公式の記述では、Azure AI Search は次のものを内部ストレージに保持し、すべて暗号化します[^5]。

- **インデックス（index）**
- **synonym map**
- **indexer / data source / skillset の定義**
- **一時ディスク上のデータ**

つまり、転置インデックス・ベクトルインデックス・検索可能フィールドの実値のコピーがサービス側に存在します。元データソース（Blob の PDF や Cosmos DB のドキュメントなど）は **Azure AI Search 側に取り込まれた後も、当然そのまま元の場所に残り続けます**。片方を消せば自動で連動するような関係ではありません。

### 暗号化は自動、ただし CMK は性能影響あり

| 層 | 暗号化 | 備考 |
| --- | --- | --- |
| 保存時（data at rest） | AES-256、Microsoft-managed、FIPS 140-2 準拠 | 全 Tier・全リージョンで自動。設定不要[^5] |
| 通信時（data in transit） | TLS 1.2 以上 | 内部サービス間通信も含む |
| CMK（任意） | Azure Key Vault で管理する鍵で二重暗号化 | インデックスと synonym map が対象 |
| 一時ディスクの CMK | 2021-05-13 以降作成のサービスのみ対応 | |

:::message alert
**CMK を有効化するとインデックスサイズが増え、クエリ性能が 30〜60% 劣化する**と公式に明記されています[^6]。例えば平時 50ms 程度だったクエリが 70〜80ms 台に伸びるイメージで、レイテンシに敏感な用途ではレプリカ追加や上位 Tier への変更が前提になります。コンプライアンス要件が本当にあるインデックスだけに限定するのが鉄則です。
:::

### Tier ごとのストレージ上限（抜粋）

| Tier | 概要 | 特徴 |
| --- | --- | --- |
| **Free** | 他テナントと共有、50 MB | SLA なし、長期未使用で削除される可能性あり |
| **Basic** | 専用リソース | 3 レプリカで SLA を満たせる小規模本番向け |
| **Standard S1 / S2 / S3** | 専用マシン、ストレージ・処理性能が段階的に増加 | 汎用本番 |
| **S3 HD** | マルチテナント型で小さいインデックス多数向け | 多 index シナリオ用 |
| **Storage Optimized L1 / L2** | TB 単価が安い | 大きい・更新少なめのインデックス向け。クエリレイテンシは高め[^7] |

:::message
**2025-02 以降、Basic と Standard（S1/S2/S3）間で Tier の上げ下げがプレビュー機能として提供**されています。以前は再作成が必須だったため、初期 Tier 選定のリスクはだいぶ下がりましたが、**プレビューなので本番適用前に最新の GA 状況を必ず確認**してください。L シリーズとの往復などはこの機能の対象外です[^8]。
:::

### データ所在（Data residency）

データは作成時に選んだリージョンに保持されます。検索エンドポイント・メタデータ・インデックス内容のすべてがそのリージョンに留まり、リージョン外に出ることはありません[^5]。

---

## 4. 【要注意②】データをどうやって追加・更新・削除するのか

「とりあえず Blob に PDF を置いたら勝手に反映されるんでしょ？」は半分正解、半分危険です。正確には次の 2 つのモデルを **明示的に選ぶ** 必要があります[^3]。

### 2 つのインジェストモデル

| モデル | 仕組み | 向いているケース |
| --- | --- | --- |
| **Push モデル** | クライアントから SDK / REST で `upload` / `merge` / `mergeOrUpload` / `delete` アクションをまとめて送る（`IndexDocumentsBatch`）[^9] | 5 分未満の鮮度要件、イベント駆動で即時反映したい場合、アプリ側で同期ロジックを完全に制御したい場合、および Indexer 非対応データソースを扱う場合 |
| **Pull モデル（Indexer）** | Azure AI Search 側の indexer が data source をクロールして取り込む[^3] | 対応データソースがあり、定期スケジュール更新で鮮度が足りるケース |

Push モデルでは、検索クライアント（.NET の `SearchClient` など）から 1 バッチで upload / merge / delete を混在させて送れます。`mergeOrUpload` は「存在すれば部分更新、なければ新規作成」の UPSERT 的な挙動です。

### Indexer のスケジュール

- **On-demand** または **スケジュール実行**
- スケジュールの最小間隔は **5 分**。これより短いフレッシュネスが必要なら Push モデルが必須[^3]
- 1 indexer = **1 data source → 1 index**（他の組み合わせは不可）
- ただし **「複数 indexer から同一 index へ書き込む」はできる**。複数ソースから 1 つの index を作るときはこの構成

:::message alert
**Indexer はバックグラウンド実行ができず、検索サービスの前景ワーカーとして走ります**。大規模な indexer が動いている間はクエリの CPU・メモリが奪われ、本番では検索レスポンスが悪化したり 503 スロットリングが増えたりします。複数 indexer を同時刻に走らせない、オフピークにスケジュールする、あるいはレプリカ数を増やして余裕を持たせる、といった設計が必要です。
:::

### 変更検知と削除検知（ここが落とし穴）

データソース側でデータが変わったとき、Indexer がそれをどう追いつけるかは、データソースごとに挙動が違います。

:::message alert
Azure Storage（Blob/ADLS Gen2）の場合、**変更検知はタイムスタンプを使って自動**で走ります。しかし **削除検知は自動ではありません**。素直に運用すると、元データから消した文書が検索インデックスに残り続ける「ゴースト」になります[^10]。
:::

推奨される対策は **Soft delete（論理削除）戦略**です。

1. Blob 側で「ネイティブ Blob soft delete」を有効化し、Indexer の data source 側に「Track deletions / Native blob soft delete」を設定する
2. アプリ側で削除は **直接の物理削除ではなく、まず論理削除フラグを立てる**
3. Indexer が soft delete を検知して検索ドキュメントを消した後で、物理削除する

:::message
**タイミングウィンドウに注意**。論理削除フラグを立ててから Indexer が次回走るまでの間（最短でも 5 分、スケジュール間隔次第ではそれ以上）、削除済みデータが検索結果に残ります。即時反映が必要なら Push モデルで `delete` アクションを送るか、クエリ側で `is_deleted eq false` のようなフィルタを必ず付ける運用を併用してください。
:::

### Skillset で AI 処理をパイプラインに組み込む

Indexer に skillset を紐付けると、取り込み途中で次のような AI 処理を走らせられます[^2]。

- **Integrated vectorization**: テキストを chunk 分割し、埋め込みモデル（Azure OpenAI 等）を呼んでベクトルを自動生成
- **OCR**: Blob 内の画像から文字を抽出
- **言語検出・翻訳・エンティティ抽出**
- **カスタム Skill**: Azure Function などを呼び出す

「Azure Blob 上の PDF をそのまま検索対象にできる」のは、この skillset + indexer の組み合わせによるものです。

---

## 5. 【要注意③】検索範囲をどこまで柔軟に絞り込めるか

検索の柔軟性はアプリの体験を決める最重要ポイントです。Azure AI Search には絞り込みの手段が何段階もありますが、**設計時点で決めておかないと後から詰む**項目がいくつかあります。

### 5.1 すべての出発点：フィールド属性

インデックスは「どのフィールドをどう使えるようにするか」をフィールド属性で宣言します[^11]。

| 属性 | 意味 |
| --- | --- |
| `searchable` | 全文検索（トークン化される）の対象にする |
| `filterable` | `$filter` で絞り込みに使える |
| `sortable` | ソートキーに使える |
| `facetable` | ファセットナビゲーションに使える |
| `retrievable` | 検索レスポンスに含められる |
| `key` | ドキュメントの主キー（1 フィールドのみ） |

:::message alert
**フィールド属性は原則「後から変更できません」**。例えば `filterable: false` で作ったフィールドを後からフィルタ可能にするには、新しい index を作り直して全ドキュメントを再投入する必要があります[^11]。大規模インデックスでは再ビルドに数時間〜数日かかり、その間の検索トラフィックをどう捌くか（エイリアスでのカナリア切替、読み取り専用レプリカ、二重書き込み期間の設計）まで含めて計画が必要です。フィルタやファセットで使う可能性のあるフィールドは最初から該当属性を立てておきましょう。
:::

また、`Edm.String` で `filterable` / `sortable` / `facetable` のいずれかを有効にする場合、**1 フィールドの値は 32 KB 以下**という制約があります。長文には使えません。

### 5.2 フィルタ（OData `$filter`）

OData 構文で厳密な絞り込みができます。値の等価比較・範囲・`and` / `or` / `not` / 文字列関数・コレクション関数・地理空間関数まで対応します[^12]。

**サイズの注意点**[^13]:

- **GET リクエスト**: URL が 8 KB を超えられない。普通の用途ではこれで足りるが、フィルタが巨大化しがちなセキュリティトリムなどでは足りないことがある
- **POST リクエスト**: 約 16 MB まで許容。大きなフィルタは POST で送る

### 5.3 ファセット（Faceted navigation）

EC サイトのサイドバーにあるような「カテゴリで絞る・ブランドで絞る」の UI を作るための機能です。`facetable: true` を立てたフィールドに対して `facets` パラメータを渡すと、**現在の検索結果に含まれるカテゴリと件数**が返ってきます[^14]。

実装上の注意:

- ファセットで使うフィールドは **`filterable` も一緒に立てておくべき**（ファセット選択後のフィルタクエリに使うため）
- ファセットは「現在のクエリ結果」から動的に作られる。静的なファセット一覧が欲しい場合は別クエリで取得する
- プレビュー API では階層ファセット、ファセットフィルタ、ファセット集計にも対応

### 5.4 スコアリングやランキング（絞り込みではなく「重み付け」）

「絞り込む」のではなく「重要なものを上に」したい場合は次の機能があります[^2]。

- **スコアリングプロファイル**: 新しいドキュメントほど優先、など
- **シノニムマップ**: 「クルマ」で「自動車」もヒットさせる
- **セマンティックランカー**: 機械学習で意味的に近いものを上位に
- **ハイライト / オートコンプリート / サジェスト**

### 5.5 アクセス制御（ドキュメントレベル）

RAG で特に重要です。**ユーザごとに見える文書を変える**には以下のいずれかを取ります。

#### パターン A: ネイティブ ACL 連携（2025 時点で SharePoint / Azure Storage 対応）

Indexer が元のデータストアの ACL / RBAC メタデータを index に取り込み、クエリ時にユーザトークンを使って自動でトリミングするパターンです[^15]。Azure Storage のデータは Microsoft Entra ID のパーミッションメタデータを継承できます。

#### パターン B: セキュリティフィルタ（Security trimming）

ネイティブ ACL に対応していないデータソースでは、**自前でフィールド設計する必要があります**[^16]。

手順の概要:

1. 各ドキュメントに「閲覧許可する group_id の配列」のような **filterable なフィールド**を用意
2. 取り込み時にその値をセット
3. 検索時に `search.in(group_ids, 'g1,g2,g3')` のようなフィルタをクエリに付ける

```json
// 例: 特定グループに紐付く文書だけを返すフィルタ
{
  "search": "*",
  "filter": "group_ids/any(g: search.in(g, 'group_id1,group_id2'))"
}
```

:::message alert
**権限変更の反映はアプリ側の責任**です。ユーザを Entra ID グループに追加・削除しても、インデックスの `group_ids` フィールドは自動では更新されません。権限変更の頻度に応じて Indexer スケジュールを短縮する・Push で個別に同期する、などを決めておく必要があります。また、1 ドキュメントの許可グループが大量になるケースでは `Collection(Edm.String)` でも 32 KB の壁に当たるため、**グループの「ハッシュ」だけを持って実体は外部に持つ**・**継承構造を正規化してグループ数を減らす**といった設計変更を迫られます。
:::

:::message
**Azure AI Search はインデックス内のドキュメントに対してユーザ単位のアクセス権を「ネイティブに持たせる」機能は持ちません**（ネイティブ ACL 対応データソース経由の場合を除く）。アプリケーション側でユーザの group メンバーシップを取得してフィルタに渡す責任があります[^17]。
:::

#### パターン C: Agentic retrieval の knowledge-source 権限

2025-11 preview の agentic retrieval では **Knowledge source 単位のアクセス制御（複数 source をまとめる Knowledge base 親オブジェクトで一元管理）** と、SharePoint 権限・Entra ID メタデータの継承がサポートされます[^4][^15]。将来的にはこちらが本命になりそうです。

---

## 6. ベクトル検索・ハイブリッド検索・Agentic Retrieval（簡易）

ベクトル検索の概念は知っている前提で、Azure AI Search 上での取り扱いだけを簡単にまとめます。

- **ベクトルフィールドの定義**: `Collection(Edm.Single)` 型のフィールドを作り、`vectorSearchConfiguration` や vector profile を紐付ける[^11]。
- **Integrated vectorization**: indexing 時に Azure OpenAI の埋め込みモデルで自動ベクトル化できる。クエリ時にも vectorizer を使って自然文をそのまま投げられる[^2]。
- **ハイブリッド検索**: BM25 によるキーワード検索とベクトル類似検索の結果を統合する。精度と再現率のバランスを取る標準手法。
- **セマンティックランカー**: ハイブリッド結果を機械学習モデルで再ランキング。2025-11 以降、Free Tier でも一部リージョンで利用可能に[^8]。
- **Agentic retrieval（2025-11-01-preview）**: LLM がチャット履歴から情報ニーズを分解 → 複数のサブクエリを並列実行 → 構造化レスポンスを返す[^4]。複数の Knowledge source を束ねた **Knowledge base** オブジェクト単位で検索・権限制御する。

より深く学ぶには以下を参照してください。

- [ベクトル検索の概要](https://learn.microsoft.com/en-us/azure/search/vector-search-overview)
- [Agentic retrieval の概要](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview)
- [Vector store としての Azure AI Search](https://learn.microsoft.com/en-us/azure/search/vector-store)

---

## 7. 実践例：社内ドキュメント RAG を組む

ここまでの設計ポイントを組み合わせると、実際の RAG システムにどう落ちるかを「社内ドキュメント RAG」シナリオで示します。**AI Search 側の設計に焦点を当て、Azure OpenAI の呼び出しや UI 層は最小限の言及に留めます**。

シナリオとして、次のような「社内ドキュメント検索アシスタント」を想定します。

- **会社規模**: 従業員 3,000 名、10 部署程度（人事 / 法務 / エンジニアリング / 営業 …）の中堅企業
- **データ**: Blob Storage に格納された社内規程・技術ドキュメント（PDF / Word）が数万件
- **アクセス制御**: Entra ID のセキュリティグループ（例: `grp-hr`, `grp-eng`, `grp-all-employees`）で閲覧範囲を決定。人事規程は人事部＋全社員、開発ガイドラインは開発部のみ、など
- **ユーザ体験**: 社員が Teams のチャットボットに「テレワーク申請の手順は？」のように自然文で質問すると、自分が閲覧権限を持つ文書だけを根拠に RAG で回答が返る

以下、この前提で **Azure AI Search 側の設計だけ** を扱います。

### 7.1 アーキテクチャ全体像

| コンポーネント | 役割 |
| --- | --- |
| **Azure Blob Storage** | PDF / Word などの原本を格納。各 Blob のメタデータに「閲覧可能な Entra ID グループ ID の配列」と「所管部署」を事前に付与しておく |
| **Azure AI Search（Indexer + Skillset）** | Blob を pull、chunk 分割、Integrated vectorization で埋め込み生成、ACL メタデータを index に投入 |
| **Azure AI Search（Index）** | 本文 chunk・ベクトル・メタデータ・`entra_groups` を格納 |
| **Azure OpenAI** | `text-embedding-3-large` を埋め込みに、`gpt-4o` を回答生成に使用（詳細は省略） |
| **アプリ層** | Entra ID からユーザの group ID 一覧を取得してクエリにフィルタ付与（詳細は省略） |

#### 普段の利用フロー

1. **ドキュメント運用者（管理部門など）**: 原本 PDF を Blob にアップロードし、Blob のカスタムメタデータに `entra_groups=grp-hr,grp-all-employees`、`department=人事` のように閲覧可能グループと所管部署を付与する
2. **Indexer（15 分ごと自動実行）**: 新規・更新された Blob を検知 → chunk 分割 → 埋め込み生成 → index に投入
3. **エンドユーザ（一般社員）**: Teams の社内ボットに「テレワーク申請は誰に出す？」と日本語で質問
4. **アプリ層**: Entra ID からユーザ所属グループ一覧（例: `grp-hr`, `grp-all-employees`）を取得 →「質問文＋ユーザのグループリスト」を Azure AI Search に送信
5. **Azure AI Search**: ユーザのグループでセキュリティトリミングした上で、ハイブリッド検索（BM25 + ベクトル）＋ セマンティックランカーで上位 8 chunk を返す
6. **アプリ層**: 上位 chunk を `gpt-4o` にコンテキストとして渡し、自然文の回答を生成してユーザに返す

ここで **Azure AI Search が直接責任を持つのは 5 番だけ** です。「誰が何のグループに所属しているか」「取得した chunk をどうプロンプトに入れるか」はアプリ層の仕事という責任分界が、このシナリオの要になります。

**他にありうるユースケース例**（同じインデックスを別 UI で使い回す場合）:

- 管理部門の社員が Web ポータルのサイドバーで「部署＝法務 かつ 更新日が過去 1 年以内」のファセット絞り込みから文書を探す（→ `department` のファセット、`updated_at` のソート／フィルタを活用）
- 監査担当が「最近更新された人事規程」一覧を `department eq '人事'` + `updated_at desc` でブラウズする
- モバイルの FAQ ボットが、特定部署用のサブセットだけを検索するために `department` フィルタを固定して投げる

### 7.2 インデックススキーマ

まず、このシナリオで index に持たせたい情報を整理します。

- **chunk 本文＋ベクトル**（RAG の主役）
- **原本を特定するキー**（回答に「出典リンク」を付けるため）
- **所管部署**（例: 人事 / 法務 / エンジニアリング）— UI サイドバーでの絞り込みに使う
- **更新日**（古い規程を除外、ソートに使う）
- **閲覧可能な Entra ID グループの配列**（セキュリティトリミング）
- **soft delete フラグ**（4 章の論理削除運用との整合）

これを踏まえたスキーマ例です。コメントで各キーの意図を補足しています。

```jsonc
{
  "name": "internal-docs",
  "fields": [
    // --- 識別 ---
    { "name": "id",        "type": "Edm.String", "key": true, "retrievable": true },
    // 原本 Blob（親）と chunk（子）を紐付けるキー。indexProjections が自動でセット
    { "name": "parent_id", "type": "Edm.String", "filterable": true, "retrievable": true },

    // --- 表示・検索対象 ---
    { "name": "title", "type": "Edm.String", "searchable": true, "retrievable": true },
    // 1 chunk 分の本文。BM25 の全文検索対象
    { "name": "chunk", "type": "Edm.String", "searchable": true, "retrievable": true },
    // ベクトル検索用。text-embedding-3-large の次元数 3072 に合わせる
    {
      "name": "chunk_vector",
      "type": "Collection(Edm.Single)",
      "searchable": true,
      "retrievable": false,              // 返す必要なし。レスポンス肥大化を防ぐ
      "dimensions": 3072,
      "vectorSearchProfile": "hnsw-profile"
    },

    // --- 絞り込み・ソート用メタデータ ---
    // 「人事の規程だけ見たい」「部署ごとの件数をサイドバーに出したい」用
    { "name": "department",  "type": "Edm.String",           "filterable": true, "facetable": true, "retrievable": true },
    { "name": "updated_at",  "type": "Edm.DateTimeOffset",   "filterable": true, "sortable": true,  "retrievable": true },
    { "name": "source_path", "type": "Edm.String",           "retrievable": true },

    // --- アクセス制御・削除管理 ---
    // セキュリティトリミング用。閲覧を許可する Entra ID グループ ID の配列
    { "name": "entra_groups", "type": "Collection(Edm.String)", "filterable": true, "retrievable": false },
    // 論理削除フラグ。クエリ側で常に `is_deleted eq false` を付ける
    { "name": "is_deleted",   "type": "Edm.Boolean",            "filterable": true }
  ],

  // ベクトル検索の設定ブロック。
  // algorithms で ANN アルゴリズム（HNSW）を宣言し、
  // profiles でそれに名前を付け、chunk_vector の vectorSearchProfile から参照する
  "vectorSearch": {
    "algorithms": [{ "name": "hnsw-algo",    "kind": "hnsw" }],
    "profiles":   [{ "name": "hnsw-profile", "algorithm": "hnsw-algo" }]
  },

  // セマンティックランカー用の設定。
  // どのフィールドを「タイトル／本文」として重み付けするかをここで指示する
  "semantic": {
    "configurations": [{
      "name": "default-semantic",
      "prioritizedFields": {
        "titleField":    { "fieldName": "title" },
        "contentFields": [{ "fieldName": "chunk" }]
      }
    }]
  }
  // 実際には analyzers / scoringProfiles / suggesters などがここに続くが、本質から外れるので省略
}
```

**なぜこのフィールド構成なのか**

| フィールド | 役割・前提 |
| --- | --- |
| `department` | 7.1 のユースケースで「人事の規程だけ」「法務の文書だけ」と絞り込みたい要件があるため。UI でのファセットナビ（サイドバー）にも使うので `filterable` + `facetable` をセットで立てる |
| `entra_groups` | セキュリティトリミング（5.5 パターン B）用。Blob のカスタムメタデータに事前付与した値を Indexer が取り込む |
| `is_deleted` | 4 章で触れた soft delete 運用のため。原本削除から Indexer 反映までのゴーストを、クエリ側フィルタで打ち消す |
| `updated_at` | 「最新版の規程だけ見たい」「更新日降順で並べたい」用。`filterable + sortable` 両対応 |
| `parent_id` | 1 Blob を複数 chunk に分割するので、chunk 側から原本 Blob を一意に指すキーが必要。回答にリンクを付けるときに使う |

**`vectorSearch` / `semantic` ブロックの読み方**

- `vectorSearch.algorithms`: ベクトル近似近傍探索のアルゴリズム定義（本例は HNSW）。`profiles` で設定に名前を付け、各ベクトルフィールドの `vectorSearchProfile` から参照する 2 段構造
- `semantic.configurations`: セマンティックランカーへの指示書。クエリ時に `queryType: "semantic"` + `semanticConfiguration: "default-semantic"` で呼び出され、`prioritizedFields` で指定したフィールドをタイトル／本文として扱って再ランキングする

**設計上の注意点**

- `chunk_vector` は `retrievable: false` が定石。数千次元の配列をレスポンスに含めるとペイロードが一気に膨らむ
- `entra_groups` も `retrievable: false`。権限メタデータをユーザに返さない
- 埋め込みモデルを変える（次元が変わる）と index の再ビルドが必須。最初から 3072 次元で固定しておくと後の総入れ替えを避けやすい

### 7.3 Indexer + Skillset（Integrated vectorization）

Skillset は「**chunk 分割 → Azure OpenAI で埋め込み生成 → chunk 単位で index に投入**」を 1 本のパイプラインで構成します。各ステップが何をしているかをコメントで示します。

```jsonc
{
  "name": "internal-docs-skillset",
  "skills": [
    // ステップ1: 長い PDF/Word を 2000 文字ごとに分割。chunk 境界で意味が切れないよう 500 文字オーバーラップ
    {
      "@odata.type": "#Microsoft.Skills.Text.SplitSkill",
      "context": "/document",
      "textSplitMode": "pages",
      "maximumPageLength": 2000,
      "pageOverlapLength": 500,
      "inputs":  [{ "name": "text",      "source": "/document/content" }],
      "outputs": [{ "name": "textItems", "targetName": "pages" }]
    },
    // ステップ2: 分割した各 chunk を Azure OpenAI に投げて埋め込み生成（Integrated vectorization）
    {
      "@odata.type": "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill",
      "context": "/document/pages/*",                 // 「各 chunk に対して」実行
      "resourceUri":  "https://<your-aoai>.openai.azure.com",
      "deploymentId": "text-embedding-3-large",
      "modelName":    "text-embedding-3-large",
      "inputs":  [{ "name": "text",      "source": "/document/pages/*" }],
      "outputs": [{ "name": "embedding", "targetName": "vector" }]
    }
    // 他に OCR・エンティティ抽出・翻訳などの skill を追加することも可能（ここでは省略）
  ],

  // ステップ3: chunk 単位で index に投入。1 Blob → 複数 chunk ドキュメントに展開するルール
  "indexProjections": {
    "selectors": [{
      "targetIndexName":    "internal-docs",
      "parentKeyFieldName": "parent_id",            // 原本 Blob のキーをここに自動セット
      "sourceContext":      "/document/pages/*",    // chunk ごとに 1 ドキュメント生成
      "mappings": [
        { "sourceFieldName": "/document/pages/*",               "targetFieldName": "chunk" },
        { "sourceFieldName": "/document/pages/*/vector",        "targetFieldName": "chunk_vector" },
        { "sourceFieldName": "/document/metadata_storage_name", "targetFieldName": "title" },
        { "sourceFieldName": "/document/metadata_storage_path", "targetFieldName": "source_path" },
        // Blob のカスタムメタデータから ACL 情報・部署タグを引き継ぐ
        { "sourceFieldName": "/document/entra_groups", "targetFieldName": "entra_groups" },
        { "sourceFieldName": "/document/department",   "targetFieldName": "department" }
      ]
    }]
  }
}
```

**skillset の 3 ステップ構造まとめ**

- `SplitSkill`: 1 つの長文を chunk に分割（RAG 精度を左右する最重要ステップ）
- `AzureOpenAIEmbeddingSkill`: 各 chunk を埋め込みベクトル化。indexing 中に Azure OpenAI を呼ぶため、ドキュメント量に応じて embedding API のコストが発生
- `indexProjections`: 「1 Blob = 1 インデックスドキュメント」ではなく「1 chunk = 1 インデックスドキュメント」に展開する指示書。`parentKeyFieldName` で親子関係を維持する

Indexer 側はスケジュールと取り込み範囲だけを定義します。

```jsonc
{
  "name": "internal-docs-indexer",
  "dataSourceName":  "internal-docs-blob",    // data source 定義で Blob 接続と soft-delete 検知を設定（別定義。ここでは省略）
  "targetIndexName": "internal-docs",
  "skillsetName":    "internal-docs-skillset",
  "schedule": { "interval": "PT15M" },        // 15 分ごとに差分取り込み。最小は 5 分
  "parameters": {
    "configuration": {
      "dataToExtract": "contentAndMetadata", // 本文＋カスタムメタデータ（entra_groups など）を抽出
      "parsingMode":   "default"             // PDF / Office 文書などを自動解析
    }
  }
  // fieldMappings / outputFieldMappings などは indexProjections に委ねているので省略
}
```

**設計のポイント**

- **chunk サイズ（2000 / 500）はあくまで出発点**。社内規程のように節区切りが明確な文書と、議事録のように流れるテキストでは最適値が違う。セマンティックランカーの上位 N を抜いて評価するループを必ず回す
- **埋め込みモデルの選択は index 再ビルドに直結**。`dimensions` が違うと互換性なし。最初から 3-large 3072 次元で固定しておくと、後の次元変更による総入れ替えを回避しやすい
- **`entra_groups` は Blob のカスタムメタデータに載せて Indexer に取り込む**。Azure Storage のネイティブ ACL を使うならパターン A（5.5）に切り替えることも検討

### 7.4 ハイブリッド検索クエリ（security trimming 込み）

ユーザが「テレワーク規程の申請手順」とチャットボットに聞いた場面を想定します。アプリ層はこのユーザが `grp-hr` と `grp-all-employees` に所属していることを Entra ID から取得済みで、それを以下のように `POST /indexes/internal-docs/docs/search` に投げます。

```jsonc
{
  // BM25（全文検索）側のクエリ文字列
  "search": "テレワーク規程の申請手順",

  // ベクトル検索側のクエリ。"kind": "text" は
  // 「このテキストを vectorizer で自動ベクトル化してから検索」の意味
  // （7.2 の vectorSearchProfile に vectorizer を紐付けておけば利用可能）
  "vectorQueries": [
    {
      "kind":   "text",
      "text":   "テレワーク規程の申請手順",
      "fields": "chunk_vector",
      "k":      50   // ベクトル側で上位 50 件を取り、BM25 結果と RRF で統合
    }
  ],

  // OData フィルタ：soft delete 除外 + ユーザが所属するグループのどれかを持つ文書のみ
  "filter": "is_deleted eq false and entra_groups/any(g: search.in(g, 'grp-hr,grp-all-employees'))",

  // セマンティックランカーを有効化（7.2 で定義した設定を参照）
  "queryType":             "semantic",
  "semanticConfiguration": "default-semantic",

  "select": "id,parent_id,title,chunk,source_path,updated_at", // 返却フィールドの明示（ベクトル・ACL は含めない）
  "top":    8
}
```

- **キーワード検索とベクトル検索のハイブリッド**: `search` と `vectorQueries` を両方指定すると、Azure AI Search 側で RRF（Reciprocal Rank Fusion）で統合される
- **security trimming**: `entra_groups` に対する `search.in(...)` が肝。ユーザが所属する全グループを投げ込む
- **soft delete**: `is_deleted eq false` で論理削除済みを必ず除外
- **POST を使う理由**: GET だと URL 8 KB 制限に当たりやすい。グループ数が多い組織では最初から POST 運用を前提にする

検索結果の上位 N chunk を Azure OpenAI の `gpt-4o` にコンテキストとして渡して回答生成する、というのが以降の流れですが、ここは一般的な RAG のプロンプト設計なので割愛します。

### 7.5 このシナリオ特有の落とし穴

1. **権限変更の反映遅延**。ユーザを Entra ID グループに追加しても、Indexer が次に走るまで `entra_groups` が更新されません（Blob のメタデータを書き換える運用にしている場合）。社内規程などでセンシティブ情報が含まれる場合は、**スケジュールを短く（5〜15 分）しつつ、アプリ側で「最新の group メンバーシップ」を毎クエリで取る**二段構えにします。
2. **削除反映のウィンドウ**。原本を消した瞬間に検索から消える仕様ではありません。4 章の soft delete 運用と、クエリ側の `is_deleted eq false` を **両方** 入れておくのが安全策です。
3. **Integrated vectorization のコスト**。埋め込みはドキュメント追加・更新のたびに Azure OpenAI が呼ばれます。「月間ドキュメント数 × 平均 chunk 数 × 埋め込み単価」で先に試算しておかないと、PoC の規模でも請求額に驚きます。更新が少ないドキュメントには、定期再 index を走らせない設計を。
4. **chunk 境界で意味が切れる**。`pageOverlapLength` を十分取る、または再ランキングでセマンティック的に近い chunk を救う設計が必要。評価用クエリセットを最初に作ってから運用に入るのがおすすめです。
5. **監査ログは Azure AI Search 側だけでは不足**。「誰が何を検索して何を見たか」はアプリ層で別途ロギングする必要があります。コンプライアンス要件がある場合は検索コール単位で記録する設計を最初から入れましょう。

---

## 8. Tier・リージョン・プレビュー機能の取り扱い

### Tier 選定のざっくり指針

| ユースケース | 推奨 |
| --- | --- |
| 手元のチュートリアル・検証 | Free（ただし 50 MB 制約、長期未使用で削除されうる） |
| 小規模本番（SLA 必要） | Basic（3 レプリカ） |
| 一般的な本番ワークロード | S1〜S3 |
| 多数の小さいインデックス（マルチテナント） | S3 HD |
| 巨大・低更新頻度のインデックス | L1 / L2（レイテンシは高め）[^7] |

### Tier 変更ができるようになった

以前は作成後の Tier 変更が不可で、再作成するしかありませんでした。2025-02 のプレビュー以降、Basic と Standard（S1/S2/S3）間の **アップグレード／ダウングレードがポータルおよび `Update Service (2025-02-01-preview)` で可能** になっています[^8]。初期選定のプレッシャーはかなり下がっていますが、**まだプレビュー** なので本番適用前に現時点の GA 状況を確認してください。L シリーズとの往復は依然対象外です。

### Free Tier での機能解放（2025-11）

2025-11 に **セマンティックランカーと agentic retrieval が Free Tier でも一部リージョン**で利用可能になりました（クエリ量に上限あり）[^8]。検証コストが下がったので、RAG の最初の検証に使いやすくなっています。

### プレビュー機能の扱い

次は現時点でプレビュー提供の代表例です。本番投入前に GA 状況を確認してください。

- Logic Apps connectors（広範なデータソース連携）
- Knowledge base / Knowledge source（agentic retrieval の中核）
- SharePoint in Microsoft 365 indexer
- Service upgrade / pricing tier change
- 2025-11-01-preview REST API

---

## 9. まとめ：導入前チェックリスト

設計時に曖昧にしないでおきたいポイントを一覧にまとめます。

- [ ] **Tier とリージョン**を決めた（ストレージ上限・SLA・CMK 要否を確認）
- [ ] **元データの所在**を整理した（インデックスは内部ストレージにコピーされる前提でコスト・コンプライアンス設計）
- [ ] **Push / Pull を選択**した（5 分未満の鮮度が要るか、対応データソースか）
- [ ] **Indexer スケジュール** と **削除検知戦略**（soft delete）を決めた
- [ ] **Indexer の前景実行による性能影響**を見込んだレプリカ設計・スケジュール時間帯を決めた
- [ ] **フィールド属性**（searchable / filterable / sortable / facetable / retrievable）を事前設計した
- [ ] **フィルタが巨大化**する見込みなら POST での呼び出しを前提にした
- [ ] **アクセス制御方式**（ネイティブ ACL / security trimming / agentic retrieval）を決めた
- [ ] **ベクトル化の責任分界**（Push 時に事前ベクトル化するか、Integrated vectorization に任せるか）を決めた。PII を含むドキュメントの場合は **Azure OpenAI への送信経路・権限・データ保持ポリシー** まで確認した
- [ ] プレビュー機能を使う場合、**GA 予定と API バージョン互換性**を確認した

Azure AI Search は「検索 DB」と呼ぶには守備範囲が広く、また 2025 年は agentic retrieval を中心に大きく進化しているサービスです。上記のポイントを押さえておけば、「とりあえず動いたけど本番設計で詰んだ」という事故はだいぶ避けられるはずです。

---

## 参考リンク

- [Introduction to Azure AI Search](https://learn.microsoft.com/en-us/azure/search/search-what-is-azure-search)
- [Features and Capabilities](https://learn.microsoft.com/en-us/azure/search/search-features-list)
- [Indexer overview](https://learn.microsoft.com/en-us/azure/search/search-indexer-overview)
- [Create an index](https://learn.microsoft.com/en-us/azure/search/search-how-to-create-search-index)
- [Create a query](https://learn.microsoft.com/en-us/azure/search/search-query-create)
- [Filters in Azure AI Search](https://learn.microsoft.com/en-us/azure/search/search-filters)
- [Add faceted navigation](https://learn.microsoft.com/en-us/azure/search/search-faceted-navigation)
- [Security filters (trimming)](https://learn.microsoft.com/en-us/azure/search/search-security-trimming-for-azure-search)
- [Built-in data protection](https://learn.microsoft.com/en-us/azure/search/search-security-built-in)
- [Security best practices](https://learn.microsoft.com/en-us/azure/search/search-security-best-practices)
- [Choose a service tier](https://learn.microsoft.com/en-us/azure/search/search-sku-tier)
- [Service limits](https://learn.microsoft.com/en-us/azure/search/search-limits-quotas-capacity)
- [What's new](https://learn.microsoft.com/en-us/azure/search/whats-new)
- [Agentic retrieval overview](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview)
- [Retrieval Augmented Generation (RAG) overview](https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview)

[^1]: [Introduction to Azure AI Search - Microsoft Learn](https://learn.microsoft.com/en-us/azure/search/search-what-is-azure-search)
[^2]: [Features and Capabilities - Azure AI Search](https://learn.microsoft.com/en-us/azure/search/search-features-list)
[^3]: [Indexer overview - Azure AI Search](https://learn.microsoft.com/en-us/azure/search/search-indexer-overview)
[^4]: [Agentic retrieval - Azure AI Search](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview)
[^5]: [Built-in data protection - Azure AI Search](https://learn.microsoft.com/en-us/azure/search/search-security-built-in)
[^6]: [Security best practices - Azure AI Search](https://learn.microsoft.com/en-us/azure/search/search-security-best-practices)
[^7]: [Choose a service tier - Azure AI Search](https://learn.microsoft.com/en-us/azure/search/search-sku-tier)
[^8]: [What's new in Azure AI Search](https://learn.microsoft.com/en-us/azure/search/whats-new)
[^9]: [SearchClient Class - .NET API](https://learn.microsoft.com/en-us/dotnet/api/azure.search.documents.searchclient?view=azure-dotnet)
[^10]: [Azure AI Search updating documents in Blob storage - MS Q&A](https://learn.microsoft.com/en-us/answers/questions/1847699/azure-ai-search-updating-documents-in-blob-storage)
[^11]: [Create an index - Azure AI Search](https://learn.microsoft.com/en-us/azure/search/search-how-to-create-search-index)
[^12]: [Filters in Azure AI Search](https://learn.microsoft.com/en-us/azure/search/search-filters)
[^13]: [Create a query - Azure AI Search](https://learn.microsoft.com/en-us/azure/search/search-query-create)
[^14]: [Add faceted navigation - Azure AI Search](https://learn.microsoft.com/en-us/azure/search/search-faceted-navigation)
[^15]: [Retrieval Augmented Generation (RAG) overview](https://learn.microsoft.com/en-us/azure/search/retrieval-augmented-generation-overview)
[^16]: [Security filters for trimming results - Azure AI Search](https://learn.microsoft.com/en-us/azure/search/search-security-trimming-for-azure-search)
[^17]: [Document security in Chat with your data](https://learn.microsoft.com/en-us/azure/developer/python/get-started-app-chat-document-security-trim)
