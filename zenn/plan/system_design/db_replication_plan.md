---
title: "データベースレプリケーションで学ぶシステム設計 — 一般解からAzure構成へ、なぜ複製するのか・何が難所か"
status: plan
---

# 構成案：データベースレプリケーションで学ぶシステム設計

「システム設計」シリーズ **第二弾**。第一弾[URLショートナー](../url_shortener_plan.md)で確立した型（**一般解 → 複雑度の進化 → Azure構成**）をそのまま再利用する。

## メタ情報（publish 時 frontmatter 想定）

- title: 各ファイルで `データベースレプリケーションで学ぶシステム設計(NN) — サブタイトル` 形式
- emoji: ファイルごとに変える（00:🗄️ / 01:🧩 / 02:📈 / 03:☁️ / 04:🧭）
- type: tech
- topics: `["systemdesign", "architecture", "azure", "cosmosdb", "database"]`
  - `systemdesign`/`architecture`/`azure`/`cosmosdb` は第一弾で使用済みタグを再利用。`database` を新規追加（`frontdoor` は本題から外れるため落とす）
- published: false（デフォルト）

## 決定事項（ユーザー承認済み）

1. **重心＝両動機バランス**：「可用性/DR」と「読みスケール/整合性」を等しく扱う総合型
2. **Azure範囲＝SQL + Cosmos を主役**：Azure SQL Database（geo-replication / failover groups / 読み取りスケールアウト / ゾーン冗長HA）と Cosmos DB（マルチリージョン読み書き＋整合性5レベル＋衝突解決）を2本柱に。MySQL/PostgreSQL の read replica は軽く触れる
3. **隣接領域＝レプリケーション一本に集中**：シャーディング/パーティショニング、ストレージ冗長(GRS)、バックアップ詳細は 04 で「隣接テーマの地図」として軽く言及するに留める

## 想定読者・前提・問い

- 読者: Web/インフラ基礎と分散システムの素朴な概念（整合性・可用性）が分かる人。Azure の主要DB（Azure SQL Database, Cosmos DB）の名前と役割が分かる人
- 問い:
  - ① なぜ複製するのか（**可用性/DR** と **読みスケール/局所性** の2動機を混同せず整理）
  - ② トポロジ（単一リーダー/マルチリーダー/リーダーレス）と同期/非同期のトレードオフ
  - ③ レプリケーションの本質的難所＝**ラグと整合性**（read-your-writes / monotonic reads / consistent prefix / 衝突解決 / split-brain）
  - ④ フェイルオーバー設計（RPO/RTO、自動 vs 手動）
  - ⑤ それらが Azure(SQL/Cosmos) のどの機能に対応し、規模・要件で構成がどう動くか

## ファイル分割（`zenn/publish/system_design/db_replication/` 配下、各500行目安）

| # | ファイル | 役割 |
|---|---|---|
| 00 | `00_overview.md` | シリーズ趣旨・読み方／なぜ複製するか（2動機）／登場概念マップ |
| 01 | `01_core_vendor_neutral.md` | トポロジ3種・同期/非同期・ラグと整合性保証・フェイルオーバー意味論（ベンダー非依存） |
| 02 | `02_complexity_evolution.md` | パターン0→3の段階進化（各Mermaid） |
| 03 | `03_azure_mapping.md` | Azure SQL と Cosmos DB の2スタイル＋グローバル化（各Mermaid） |
| 04 | `04_extensions_and_refs.md` | 衝突解決深掘り・ラグ対策・隣接領域の地図＋まとめ＋厳選参考リンク |

各ファイル冒頭に「シリーズ内ナビ（前後リンク）」を置き相互リンク。

---

## 00_overview.md — お題と「なぜ複製するのか」

**主張**: レプリケーション＝「同じデータのコピーを複数ノードに保持し同期する」こと。**動機は2つあり、混同すると設計を誤る**。①可用性/DR（壊れても止めない）②読みスケール/局所性（速く読む・近くで読む）。利点の裏には必ず「コピー間の食い違い（整合性）」という代償がつく。

- 複製と非複製の最小比較（単一DBは何が困るか：SPOF・読み負荷集中・地理レイテンシ）
- 2つの動機を表で整理（動機→嬉しいこと→生まれる難所）
- 登場概念マップ（リーダー/フォロワー、同期/非同期、ラグ、整合性、フェイルオーバー、RPO/RTO）を mermaid で俯瞰
- シリーズの読み方（00→04 の flowchart）
- :::message で「レプリケーション ≠ バックアップ ≠ シャーディング」の線引き（隣接領域は04で地図のみ）

**Mermaid**: ①単一DBの困りごと→複製で解く図、②シリーズ読み進めフロー

**根拠**: `extract_general_topologies.json`（複製の利点と複雑性）, ByteByteGo「A Guide to Database Replication」（fault tolerance/scalability の動機, split-brain/stale read の代償）

---

## 01_core_vendor_neutral.md — ベンダー非依存の中核（最大の山場）

**主張**: クラウド非依存で決まる中核判断は4つ。「トポロジ」「同期/非同期」「ラグと整合性保証」「フェイルオーバー意味論」。

### 1. トポロジ3種
- **単一リーダー**（leader-follower）: 書きはリーダー集約、読みはフォロワー分散。強整合が素直・実装単純だが書きがSPOF/ボトルネック。例: PostgreSQL/MySQL/SQL Server
- **マルチリーダー**（active-active）: 複数リーダーが書きを受ける。書き可用性・地理局所性に強いが**書き衝突**が発生する
- **リーダーレス**（Dynamo系）: 任意ノードが読み書き、**クォーラム(W+R>N)** で整合を調整。高可用・SPOFなしだが結果整合＋衝突解決が複雑。例: DynamoDB/Cassandra/Riak
- 比較表（書き/読みスループット、レイテンシ、SPOF、整合性、複雑度、代表製品）

### 2. 同期 vs 非同期
- 同期: コミット前にレプリカ反映を待つ→データ損失ゼロだが**書きレイテンシ増・可用性低下**（レプリカ遅延が書きを止める）
- 非同期: すぐ返す→速いが**リーダー障害時に未伝播分を失う**
- 準同期（半分だけ同期）の実務的折衷

### 3. レプリケーションラグと整合性保証（本記事の核）
- 非同期の宿命＝ラグ。ラグが生む**3つのユーザー可視アノマリ**（DDIAの枠組み）:
  - **read-your-writes**（自分の書きが見えない）→ 解: 書き後一定時間はリーダーから読む / セッションのLSNトークンで追いついたレプリカへ
  - **monotonic reads**（時間が巻き戻る）→ 解: 同一ユーザーは同じレプリカに固定（sticky）
  - **consistent prefix reads**（因果が逆転、質問より先に回答が見える）→ 解: 因果関係ある書きは同じパーティションへ / 因果一貫性(ベクタークロック)
- 「整合性の強さ ⇔ レイテンシ/可用性」の連続体（強整合〜結果整合の間に session 系保証がある）

### 4. フェイルオーバー意味論
- 自動 vs 手動、**split-brain**（複数ノードが自分をリーダーと誤認→二重書き）、**RPO/RTO** の定義
- 非同期フェイルオーバーは RPO>0（未伝播分の損失）を受け入れること

**Mermaid**: ①トポロジ3種の図、②cache的でなくラグのシーケンス（writer→leader→follower遅延→stale read）、③トポロジ選択フロー

**根拠**: `extract_general_topologies.json`（leader/leaderless比較表・例・SPOF）, `extract_consistency_guarantees.json`（read-your-writes/monotonic/consistent prefix の定義と実装手法・DDIA由来・Bayou session guarantees）, ByteByteGo「How to Choose a Replication Strategy」（multi-leader衝突・用途）

---

## 02_complexity_evolution.md — 複雑度の進化（パターン0→3）

**主張**: 同じ「複製したい」でも、**動機と規模で正解が動く**。下から順に「次へ進む引き金」を引かれたときだけ右へ。

- **パターン0**: 単一DB（複製なし）。SPOF・読み負荷集中・地理レイテンシが引き金
- **パターン1**: 読みレプリカ追加（単一リーダー＋非同期フォロワー）。**読みスケール動機**の第一手。引き金＝ラグによる整合性問題、リージョン障害耐性なし
- **パターン2**: クロスリージョン geo-DR / フェイルオーバー（**可用性/DR動機**）。スタンバイ＋自動/手動フェイルオーバー、RPO/RTO設計。引き金＝書きを複数拠点で受けたい/グローバル低レイテンシ書き込み
- **パターン3**: マルチリーダー/グローバル分散。active-active、衝突解決、結果整合の受容
- 複雑度グラデーション総括表（規模・トポロジ・整合性・可用性・運用負荷）

**Mermaid**: 各パターン構成図4枚＋総括 flowchart

**根拠**: `extract_general_topologies.json`, `extract_consistency_guarantees.json`, 第一弾02の型を踏襲

---

## 03_azure_mapping.md — Azure構成例（SQL / Cosmos の2スタイル）

**主張**: 一般解の各箱はAzureに素直に対応。**「リレーショナルで段階的に複製を足す(Azure SQL)」と「最初からグローバル分散前提(Cosmos DB)」**で2スタイルある。

### 一般概念→Azure対応表

### 構成A：Azure SQL Database（単一リーダー型を段階的に強化）
- **ローカルHA（ゾーン冗長）**: プライマリ＋最大3つの同期セカンダリレプリカ、Always On類似、Service Fabricがフェイルオーバー。**RTO<30秒 / RPO=0**
- **読み取りスケールアウト**: Premium/Business Critical/Hyperscale で既定有効、読み取り専用レプリカへオフロード（**追加コストなしで+100%の計算能力**）= パターン1
- **Active geo-replication**: DB単位、別リージョンに**読み取り可能なgeo-secondary（最大4）**、非同期、手動/プログラム的フェイルオーバー = パターン2
- **Failover groups**: geo-replication上の宣言的抽象。**安定した接続リスナ(rw/ro)** で接続文字列を変えずに自動フェイルオーバー。**RTO<60秒 / RPO≈5秒**
- 注意: failover group のセカンダリは既定でHA無効→明示有効化。Hyperscaleは一部制約

### 構成B：Azure Cosmos DB（最初からマルチリージョン前提）
- **グローバル分散**: 複数リージョン読み、または**マルチリージョン書き込み(active-active)**。99.999%可用性、p99<10ms
- **整合性5レベル**: Strong / Bounded Staleness / Session / Consistent Prefix / Eventual。RPO対応表（Strong=0、Session/CP/Eventual<15分、Bounded=K&T〔マルチリージョン最小10万操作 or 300秒〕）
- **マルチリージョン書き込みでは強整合は選べない**／Bounded Staleness はマルチ書きでアンチパターン（01の理論と接続）
- **衝突解決**: LWW(既定、`_ts`タイムスタンプ) or カスタム（NoSQL APIのみ）。ハブリージョンがアービター = パターン3の具体
- レプリカラグの理論(01)が、整合性レベル選択という具体的UIになる、と接続

### 構成A vs B 選択表
- リレーショナル/トランザクション資産・段階導入→A、グローバル低レイテンシ・active-active前提→B

**Mermaid**: ①Azure SQL（HA+読みスケール+geo+failover group）図、②Cosmos マルチリージョン書き込み図

**根拠**: `extract_azure_sql.json`（HA構成・読みスケール・geo-replication・failover group）, `extract_azure_rpo_rto.json`（RTO/RPO数値）, `extract_cosmos.json`（グローバル分散・整合性レベル・RPO表・衝突解決）, [マルチリージョン対応サービス一覧](https://learn.microsoft.com/en-us/azure/reliability/regions-multiregion-support)

---

## 04_extensions_and_refs.md — 拡張トピックと厳選参考リンク

**主張**: 要件が一段増えると新しい難所が生まれる地図。隣接領域への導線も置く。

1. **衝突解決の深掘り**: LWW/バージョンベクトル/CRDT、アプリ側解決。マルチリーダー採用時の必須検討
2. **ラグ対策パターン実務**: read-your-writes をどう担保するか（sticky session, セッショントークン, 重要読みはリーダー/Strong）
3. **フェイルオーバー運用**: 自動の誤検知(false positive)対策、split-brainフェンシング、定期DR訓練
4. **隣接領域の地図**（一本に集中の宣言通り軽く）: シャーディング/パーティショニング（書きスケール）、ストレージ冗長(LRS/ZRS/GRS)、バックアップ＋PITR との役割分担
5. まとめ（要件→複雑度→構成の地図 flowchart）
6. 厳選参考リンク（一般: DDIA Ch5, ByteByteGo, openmetal / Azure公式: SQL geo-replication・failover groups・read scale-out・business continuity, Cosmos consistency-levels・conflict-resolution・global distribution）

**根拠**: 全 `extract_*.json`、各Azure公式Docs

---

## 不足情報・追加調査ポイント（必要なら執筆中に補完）

- MySQL/PostgreSQL read replica の具体数値は「軽く触れる」範囲なので深掘り不要（`regions-multiregion-support` で十分）
- DDIA は書籍のためURL引用は概念帰属のみ（一次ソースは公式Docs/技術ブログを使用）
