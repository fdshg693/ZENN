---
title: "URLショートナーで学ぶシステム設計 — 一般解からAzure構成へ、要件と複雑度で\"正解\"はどう動くか"
status: plan
---

# 構成案：URLショートナーで学ぶシステム設計

「システム設計」シリーズ第一弾。本記事で確立する型（**一般解 → Azure構成 → 要件・複雑度での変化**）を以降の記事でも再利用する。

## メタ情報（publish 時 frontmatter 想定）

- title: URLショートナーで学ぶシステム設計 — 一般解からAzure構成へ、要件と複雑度で"正解"はどう動くか（各ファイルでサブタイトル調整）
- emoji: 🔗
- type: tech
- topics: `["systemdesign", "architecture", "azure", "cosmosdb", "frontdoor"]`（既存タグ `architecture` / `azure` を再利用。`systemdesign` をシリーズ共通の新タグとして導入）
- published: false（デフォルト）

## 想定読者・前提・問い

- 読者: Web/インフラ・Azure基礎（App Service, Functions, Cosmos DB, Front Door, Redis の名前と役割）が分かる人
- 問い: ①単純そうなURL短縮の本質的な難所はどこか ②ベンダー非依存での選択肢とトレードオフ ③Azureへの落とし込み ④要件・複雑度が増えると構成はどう進化するか
- 決定事項（ユーザー承認済み）: 採番は**バランス重視**（比較表＋トレードオフ、実装詳細はリンク委譲）／ Azure構成は**サーバーレス中心＋PaaS・コンテナ中心**の2軸を主役に

## ファイル分割（`zenn/publish/system_design/url_shortener/` 配下、各500行目安）

| # | ファイル | 役割 |
|---|---|---|
| 00 | `00_overview.md` | シリーズ趣旨・読み方・要件整理（機能/非機能、読み書き比、規模見積り） |
| 01 | `01_core_vendor_neutral.md` | 採番方式比較・ストレージ選定・キャッシュ・リダイレクト経路（ベンダー非依存） |
| 02 | `02_complexity_evolution.md` | パターン0→3の段階進化（各Mermaid） |
| 03 | `03_azure_mapping.md` | 各パターンのAzureマッピング（サーバーレス／PaaS・コンテナの2軸、各Mermaid） |
| 04 | `04_extensions_and_refs.md` | 解析・レート制限・有効期限・カスタムエイリアス＋まとめ＋厳選参考リンク |

各ファイル冒頭に「シリーズ内ナビ（前後リンク）」を置き、相互リンクする。

---

## 00_overview.md

**主張**: URL短縮は「小さく見えて、読み多め・低レイテンシ・採番という3つの設計の山場を含む良い教材」。本シリーズは“最適な複雑度”を要件から逆算する型を示す。

- セクション
  1. このシリーズで何を学ぶか（記事の型の宣言）
  2. お題：URLショートナーとは（短縮→保存→リダイレクトの3動作、Mermaidシーケンス図で最短経路）
  3. 機能要件 / 非機能要件の分離（作成・リダイレクト・任意でカスタムエイリアス/有効期限/解析 ｜ 低レイテンシ・高可用・スケール）
  4. 規模見積りの型（DAU・read/write比 ≈ 100:1、QPS・ストレージ・短縮コード長とBase62の表現空間 62^7 ≒ 3.5兆 の概算）
  5. 本記事の読み進め方（01→04）
- 根拠: `extract_general_design.json`（algomaster: read-heavy 100:1, NoSQL for KV, expiration hybrid, analytics decouple ／ hellointerview: 301 vs 302, hash vs counter, CDN）
- 参考リンク誘導: Hello Interview「Design Bitly」, AlgoMaster, systemdesign.one

## 01_core_vendor_neutral.md

**主張**: 中核設計はベンダーに依存しない。難所は「採番」「読み経路の最適化」「リダイレクトの意味論」。

- セクション
  1. 採番方式の比較（バランス重視）
     - ①ハッシュ＋Base62切り詰め（決定的・重複排除向き／衝突不可避→再ハッシュやsalt）
     - ②連番カウンタ＋Base62（一意保証・単純／中央ボトルネック・推測可能）
     - ③分散ID（Snowflake系：高スループット・k-sortable／実装複雑・クロックスキュー）
     - ④事前生成KGS（採番をホットパスから外す／鍵在庫の管理が必要）
     - 比較表（長所/短所/向くケース）＋「どれを選ぶかは規模で変わる」と02へ橋渡し
     - Mermaid: 採番方式の選択フローチャート
  2. ストレージ選定（KV中心アクセス → NoSQL/KVが素直、RDBは強整合や二次索引が要るとき）
  3. キャッシュ戦略（read-heavyの本丸：cache-asideパターン、ホットキー、TTL）
     - Mermaid: cache-aside の読み取りシーケンス（ヒット/ミス）
  4. リダイレクトの意味論（301=恒久・キャッシュされ解析が取れない vs 302=一時・毎回サーバ経由で解析可能）というトレードオフ
- 根拠: `extract_general_design.json`（algomaster比較表: Hashing/Global Counter/Distributed ID の pros/cons/best-for、cache-aside、NoSQL）, `extract_azure_serverless.json`（301/302 はhellointerview側）
- 参考リンク誘導: systemdesign.one（採番・容量見積りの数式）, AlgoMaster（ID生成の比較）

## 02_complexity_evolution.md

**主張**: 同じ要件でも規模で“正解”が変わる。過剰設計も過小設計も失敗。段階で考える。

- パターン（各Mermaid構成図）
  - パターン0（MVP）: 単一アプリ + 単一DB。連番採番。Mermaid。向くケース/限界（単一障害点・読みでDB直撃）
  - パターン1（read最適化）: + キャッシュ層（cache-aside）。Mermaid。向くケース/限界
  - パターン2（水平スケール）: ステートレスApp×LB + 読み書き分離 + DBレプリカ/パーティション + 分散ID or KGS。Mermaid。向くケース/限界
  - パターン3（グローバル分散）: エッジ/CDNでリダイレクト + マルチリージョンDB + 整合性の妥協（最終的整合）。Mermaid。向くケース/限界
- 「複雑度グラデーション」総括表（規模・グローバル性・運用負荷で各パターンを位置づけ）
- 根拠: `extract_general_design.json`（incremental build, separate read/write services, multi-region availability, graceful degradation）
- 参考リンク誘導: hellointerview「scale to 1B urls / 100M DAU」, systemdesign.one

## 03_azure_mapping.md

**主張**: 一般解の各箱はAzureサービスに素直に対応する。同じ要件でも「サーバーレス中心」と「PaaS/コンテナ中心」で異なる落とし方がある。

- セクション
  1. 対応表（一般概念 → Azure：アプリ＝Functions/App Service/Container Apps、KV＝Cosmos DB/Table Storage、キャッシュ＝Azure Cache for Redis、エッジ＝Front Door、解析＝Event Hubs）
  2. 構成A：サーバーレス中心（MS公式 AzUrlShortener / techcommunity 構成準拠）
     - Front Door + Static Web Apps(管理UI) + API Management + Functions(consumption) + Cosmos DB(serverless, /id パーティションキー=ハッシュ) + AD B2C
     - Functions の Cosmos 入出力バインディングで vanity=document id（Eran Stiller の要点）
     - Mermaid。長所（コスト従量・低運用）/注意（コールドスタート等）
  3. 構成B：PaaS/コンテナ中心
     - Front Door/App Gateway + App Service or Container Apps + Cosmos DB or Azure SQL + Azure Cache for Redis
     - Mermaid。長所（既存業務システムと地続き・常時稼働）/注意（スケール設定・コスト）
  4. グローバル化の勘所（Cosmos DB マルチリージョン書き込み・整合性レベルの選択）
     - 5つの整合性レベル、p99 <10ms 読み書き、99.999%可用性／Session が最も一般的／強整合×マルチ書き込みは不可、Bounded Staleness はマルチ書き込みでアンチパターン
     - Front Door はDDoS/WAF前段にも効く（運用上の付帯価値）
- 根拠: `extract_azure_serverless.json`（techcommunity: Functions consumption / Cosmos serverless zone-redundant / `/id` high-cardinality partition / APIM / SWA / AD B2C ｜ Eran Stiller: Cosmos bindings, <10ms p99, vanity=id）, `extract_azure_official.json`（Cosmos global distribution・consistency-levels, Front Door overview, Redis tiers/geo-replication）
- 参考リンク誘導: MS Learn「AzUrlShortener」, Cosmos DB グローバル配布/整合性レベル 公式Docs, Front Door overview, Azure Cache for Redis overview

## 04_extensions_and_refs.md

**主張**: 要件が一段増えるたびに設計は分岐する。代表的拡張の勘所と、深掘り用の良質リンク。

- セクション
  1. 解析（クリック計測）: ホットパスから外す。302で計測点を確保 → イベントを非同期集計（バッファリング/Event Hubs）。Mermaid（非同期解析パイプライン）
  2. レート制限 / 不正URL対策（作成APIの濫用防止、フィッシング対策の方針）
  3. 有効期限: passive（読取時チェック）+ active（バッチ/TTL）のハイブリッド、Cosmos TTL の活用
  4. カスタムエイリアス（vanity）: 一意制約・予約語・衝突時の扱い
  5. まとめ：要件→複雑度→構成の地図（本シリーズの型の再掲）
  6. 厳選参考リンク集（一般設計／Azure公式／OSS実装）
- 根拠: `extract_general_design.json`（expiration hybrid, analytics buffered counting, rate limiting）, `extract_azure_serverless.json`（APIM JWT 検証, 4 APIs）, `extract_azure_official.json`（Cosmos TTL は追加確認候補）
- 追加調査候補（執筆時に裏取り）: Cosmos DB TTL の公式仕様、APIM rate-limit ポリシーの公式Docs（断定する場合のみ）

---

## 参考URL一覧（収集済み）

一般設計
- Hello Interview: https://www.hellointerview.com/learn/system-design/problem-breakdowns/bitly
- AlgoMaster: https://algomaster.io/learn/system-design-interviews/design-url-shortener
- systemdesign.one: https://systemdesign.one/url-shortening-system-design

Azure
- MS Learn AzUrlShortener: https://learn.microsoft.com/en-us/shows/azure-friday/azurlshortener-an-open-source-budget-friendly-url-shortener
- Serverless URL Shortener (techcommunity): https://techcommunity.microsoft.com/blog/appsonazureblog/serverless-url-shortener/3754120
- Eran Stiller (Functions+Cosmos): https://eranstiller.com/build-a-custom-url-shortener-using-azure-functions-and-cosmos-db
- Cosmos DB global distribution: https://learn.microsoft.com/en-us/azure/cosmos-db/distribute-data-globally
- Cosmos DB consistency levels: https://learn.microsoft.com/en-us/azure/cosmos-db/consistency-levels
- Front Door overview: https://learn.microsoft.com/en-us/azure/frontdoor/front-door-overview
- Azure Cache for Redis overview: https://learn.microsoft.com/en-us/azure/azure-cache-for-redis/cache-overview

## 収集ファイル

- `temp/url_shortener/search_design_general.json`
- `temp/url_shortener/search_azure_mapping.json`
- `temp/url_shortener/extract_general_design.json`
- `temp/url_shortener/extract_azure_serverless.json`
- `temp/url_shortener/extract_azure_official.json`
