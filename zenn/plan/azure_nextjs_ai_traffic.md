---
title: "AIチャットアプリの通信を推測する — Azure × Next.js 構成で「境界ごとの通信」を設計時に読む方法"
status: plan
---

## 想定読者と前提

- アーキ図を渡されたとき「どこにどんな通信が流れるか」を**実装前に頭の中で推測**できるようになりたいインフラ寄りエンジニア
- AIチャットアプリの構築・運用に携わるが、SSE / RSC / VNet統合の通信特性を**体系的に**は把握できていない人
- HTTP / TCP の基本(リクエスト・レスポンス、ヘッダ、Keep-Alive)は理解している中級

## この記事が答える問い

1. アーキ図から、各境界でどんな通信(方向 / 頻度 / サイズ / 持続時間)が発生するかを、どう推測するか
2. Next.js App Router 特有の「目に見えにくい通信」(RSC payload、prefetch、Server Actions)は**どこで**何バイト発生するか
3. AIチャット特有の SSE 通信が、Azure の各前段(Front Door / Application Gateway / VNet 統合)で**詰まる/化ける**理由は何か
4. App Service の VNet Integration / Private Endpoint で、**どの方向の通信が VNet に乗り、どれが乗らないか**

## 扱う / 扱わない

- **扱う**: 通信を推測する5軸フレームワーク、Next.js App Router 通信モデル、AIチャット SSE、Azure 構成要素間の境界別通信、SSE と中間プロキシの相性、VNet 統合の方向性
- **扱わない**: 単価の網羅(既存の `azure_cost_ai_chat_app.md` に委譲)、L4/L7 パケット解析、TCP/QUIC レイヤーの最適化、具体的な Next.js 実装コード

## 既存記事との差別化

- 既存 [`zenn/publish/azure_cost_ai_chat_app.md`](../publish/azure_cost_ai_chat_app.md) は**コスト**主題。本記事は**通信のメンタルモデル**主題で、コストは結果論。
- Next.js App Router の通信(RSC payload / prefetch / Server Actions / streaming)を厚めに扱う点と、SSE の Azure 中間プロキシ問題を独立した章で扱う点が新規。

## 想定トーン

- 「何を見れば推測できるか」を最初に与え、Azure × Next.js × AIチャットを**例題**として5軸を当てて見せる構成
- 数値は公式ドキュメントの一次情報のみ引用(タイムアウト値、SKU 制約、ヘッダ要件)
- 推測 → 検証 → 修正のループを最後に示す

---

## セクション構成

### 0. はじめに: なぜ「観測する前に推測する」のか

**主張**: 通信は障害が起きてから観測するのでは遅い。設計時点でアーキ図から**通信プロファイル**を推測できれば、SKU・タイムアウト・前段選定のミスを防げる。本記事は「推測の語彙」を提供する。

- 推測が必要な3場面: SKU 選定 / 前段(AFD / AppGW)選定 / 障害切り分け
- 「観測 → 後付け対応」では遅い具体例(本番でSSEが切れた、egress 課金が予想の3倍)
- この記事は「Azure × Next.js × AIチャット」を**例題**として、フレームワークを実地に当てて見せる

### 1. 通信を推測する5軸フレームワーク

**主張**: どんなアプリでも通信は「方向 / 頻度 / サイズ / 持続時間 / 境界」の5軸で記述できる。アーキ図の各矢印にこの5軸を書き込めば、見落としと誤認が劇的に減る。

| 軸 | 問い | 例 |
|---|---|---|
| **方向** | 誰が誰に対して開始する通信か。ingress / egress / 内部 / 制御プレーン | ブラウザ → App Service は ingress、App Service → 外部AI は egress |
| **頻度** | セッションあたり何回か、ユーザー1人あたり何回か、定常か突発か | チャット送信1回ごと vs ページロード1回ごと vs 1秒間隔のヘルスチェック |
| **サイズ** | 1リクエストの平均バイト数、1レスポンスの平均バイト数 | JSON 数KB vs JS バンドル 数百KB vs SSE で数十KB を分割送信 |
| **持続時間** | コネクションが何秒開きっぱなしか。短命 / 長命 / 持続接続 | REST API 数百ms vs SSE 数十秒 vs WebSocket 数分以上 |
| **境界** | どのネットワーク境界を何回またぐか。CDN / L7 LB / VNet / リージョン / インターネット | ブラウザ → AFD → App Service → Private Endpoint → Cosmos DB |

各軸の意味と、なぜその軸が「コスト・障害・SLA」に効くのかを 1 段落ずつ解説。

- 根拠: 一般的な分散システム設計の知識ベース + 後の章の Azure / Next.js 具体例で裏付け

### 2. 例題のアーキテクチャ — Azure × Next.js × AIチャット

**主張**: 5軸を当てるための具体例として、典型構成を1枚の図で固定する。以後の章はこの図の各矢印を1本ずつ拡大していく。

```
[ユーザー (ブラウザ)]
      │ ① HTML / JS bundle / RSC payload / SSE
      ▼
[Azure Front Door] ─── (静的アセットキャッシュ)
      │ ② オリジン HTTP(S)
      ▼
[App Service: Next.js App Router]
      │ ③ AOAI 呼び出し (内部 or PE経由)
      ├──────────► [Azure OpenAI]
      │ ④ 外部AI 呼び出し (Internet egress)
      ├──────────► [外部AI API: Anthropic / OpenAI.com / Gemini]
      │ ⑤ DB アクセス (内部 or PE経由)
      ├──────────► [Cosmos DB]
      │ ⑥ テレメトリ送信 (egress)
      └──────────► [Application Insights / Log Analytics]
```

各矢印に番号を振り、後段の章でそれぞれを 5 軸で記述する。

- 根拠: 既存記事 `azure_cost_ai_chat_app.md` の構成と整合させつつ、Front Door を前段に追加(本記事の SSE 章で重要になるため)

### 3. ① ブラウザ ↔ Front Door ↔ App Service: Next.js が流す通信

**主張**: Next.js App Router 構成では、ユーザーから見えない RSC payload と prefetch が「無視できない通信量」として常時流れている。SPA の感覚で見積もると過小評価する。

- **初回ページロード**:
  - HTML(streaming HTML, chunked transfer encoding) + CSS + クライアント JS バンドル + bootstrap script
  - サイズ: 数百 KB 〜数 MB(client component の量に依存)
  - 持続時間: 短命(数百 ms 〜数秒)だが**chunked のため複数チャンクで断続的に届く**
  - 境界: AFD でキャッシュされる静的アセットと、オリジンを通る HTML を分けて推測する
- **クライアント側ナビゲーション**:
  - `<Link>` クリック → `?_rsc=...` クエリ付きで RSC payload を取得(HTML ではない)
  - サイズ: ページの差分相当、数 KB 〜数十 KB
  - 頻度: ユーザー1人あたりナビゲーションごと
- **prefetch**:
  - `<Link>` がビューポートに入った時点で **自動** prefetch が走る
  - 軽量 prefetch(loading.tsx の static shell) と完全 prefetch がある
  - 落とし穴: **長いリスト・サイドメニューの全リンク** が prefetch 対象になり、一覧表示しただけで 数十リクエスト/数 MB が流れる
- **Server Actions**:
  - フォーム送信 / mutation 用。`POST` で multipart/form-data または JSON、レスポンスは RSC payload(再描画用の差分)
  - 1ラウンドトリップで mutation + 再描画ができるので、単純な REST より境界をまたぐ往復が減る
- **Streaming UI**:
  - `<Suspense>` 境界ごとに独立したチャンクが Transfer-Encoding: chunked で流れる
  - 1ページのレスポンスが**数百 ms〜数秒にわたり開きっぱなし** → 後述の SSE と同じ性質を持つ「半永続 HTTP」

参考:
- [Next.js Streaming Guide](https://nextjs.org/docs/app/guides/streaming) — `<Suspense>` ごとのチャンク、static shell + 動的部分の分離
- [Linking and Navigating](https://nextjs.org/docs/app/getting-started/linking-and-navigating) — `<Link>` の自動 prefetch 動作
- [Vercel: Understanding RSC](https://vercel.com/blog/understanding-react-server-components) — Server Actions で「mutation + 再描画 + クライアントキャッシュ整合」が1ラウンドトリップ

### 4. ②③ App Service ↔ AOAI: 内部通信のはずが「外」を回るケース

**主張**: 「同じ Azure リージョンの AOAI を呼んでいるから内部通信」という思い込みは危険。Private Endpoint を張っても、App Service からの outbound は**実は VNet を経由していない**ことがある。これを見抜くには「VNet Integration の方向性」を理解する必要がある。

- **App Service VNet Integration は outbound 専用**(公式記述: "Virtual network integration affects only outbound traffic from your app")
- **App Service の Private Endpoint は inbound 専用**(public-facing にせず VNet 内からアクセスさせるため)
- ここから派生する重要な事実:
  - App Service → AOAI を Private Endpoint 経由にしたい場合、**App Service 側で VNet Integration を有効化** + **AOAI 側に Private Endpoint** + **Private DNS Zone でのリゾルブ** が必要
  - VNet Integration を有効にしただけでは、App Service は VNet 内に「いる」わけではなく、トンネルで outbound だけ流す形
  - `outboundVnetRouting.applicationTraffic=true`(旧 `WEBSITE_VNET_ROUTE_ALL=1`)を設定しないと、アプリトラフィックは default route を通る = **AOAI Private Endpoint へのリクエストが Public IP に解決されて失敗する** ケース
  - Linux App Service + VNet Integration では、AOAI Private Endpoint への outbound が**アーキ的制約で安定しない**事例があり、ASE v3 か Public + Managed Identity が推奨される
- 5軸での記述例:
  - 方向: 内部(VNet)を意図 / 実際は default route で外回りになっていることがある
  - 頻度: チャット送信1回につき 1〜N 回(N は agent ループの回数)
  - サイズ: リクエストはトークン × 〜4byte、レスポンスはストリーミングなら**長時間かけて累計**
  - 持続時間: stream 有効時は**数秒〜数十秒の長命接続**
  - 境界: 期待通りなら App Service → VNet → PE → AOAI、実際は App Service → Internet → AOAI Public のケースあり
- 推測のチェックリスト: VNet Integration 有効? / outboundVnetRouting 設定? / Private DNS Zone 紐付け? / NSG / UDR の影響?

参考:
- [App Service VNet Integration overview](https://learn.microsoft.com/en-us/azure/app-service/overview-vnet-integration) — outbound only, traffic flow definition
- [Configure VNet integration routing](https://learn.microsoft.com/en-us/azure/app-service/configure-vnet-integration-routing) — `outboundVnetRouting.applicationTraffic` / `allTraffic` の差
- [Linux App Service + AOAI Private Endpoint Q&A](https://learn.microsoft.com/en-us/answers/questions/5789113/) — アーキ的制約、ASE v3 / Public + MI 推奨

### 5. ④ App Service → 外部AI: 「ストリーミング × egress」の二重課題

**主張**: 外部AI(Anthropic / OpenAI.com / Gemini)を呼ぶ通信は、**「Internet egress 課金」と「長命 SSE 接続」が同時に発生**するという特殊な性質を持つ。両者を独立に推測すると見誤る。

- 5軸での記述:
  - 方向: egress(Internet)
  - 頻度: チャット送信1回につき 1 回(マルチエージェントなら N 回)
  - サイズ: stream の場合、SSE のヘッダオーバーヘッド + delta JSON 群。**累計で response 本文 + メタデータ** で本文の 1.2〜1.5 倍になりうる
  - 持続時間: stream の場合 数秒〜数十秒
  - 境界: App Service → (VNet Integration の routing 次第) → Internet → 外部AI ベンダー
- 落とし穴:
  - **Private Endpoint で外部AI 呼び出しを「内部化」はできない**(ベンダー側に PE を出していないため)。これは egress 削減策にならない
  - リージョン選定を AOAI 同居だけで決めると、外部AI ベンダーの近接リージョンから遠い場所に App Service がいることになり、**egress 単価が高いリージョン発**になる
  - SSE の途中切断(後述の 6 章)は、外部AI への呼び出しでも同じ問題を起こす

参考:
- 既存ログ [`extract_networking_cost-log.json`](../../.claude/skills/use-tavily/src/logs/extract_networking_cost-log.json) — Internet egress / Premium Global Network ルーティング
- [The Complete Guide to Streaming LLM Responses](https://dev.to/pockit_tools/the-complete-guide-to-streaming-llm-responses-in-web-applications-from-sse-to-real-time-ui-3534) — SSE プロトコル形式、X-Accel-Buffering

### 6. SSE と中間プロキシ — Azure 特有の最大の地雷

**主張**: AIチャットの応答は SSE で流すのが標準だが、**Azure Front Door は SSE をサポートしていない**。Application Gateway は v2 で対応するが**バッファ無効化と request timeout 設定**が必須。前段選定はこの事実を起点に決まる。

- SSE の HTTP 性質:
  - `Content-Type: text/event-stream`
  - `Connection: keep-alive`
  - `Transfer-Encoding: chunked`
  - `Cache-Control: no-cache`
  - `X-Accel-Buffering: no`(中間プロキシのバッファリング抑止)
- Azure 前段の対応状況:
  - **Front Door: SSE 非対応**(Microsoft Q&A で複数の Microsoft 担当が回答)
  - Application Gateway v1: SSE 対応(ただし**2026-04-28 retire 予定**)
  - **Application Gateway v2: SSE 対応**だが要設定
    - Response Buffer を**無効化**
    - Backend Setting の Request timeout を**イベント間アイドル時間より長く**
    - バックエンドが上記 SSE ヘッダ群を送ること
  - AFD Standard/Premium の origin response timeout はデフォルト 30 秒(最大 240 秒)。長い AI 応答では足りない
- 5軸での記述(ブラウザ ↔ App Service の SSE):
  - 方向: server push(HTTP レスポンス内)
  - 頻度: チャット送信1回につき 1 接続
  - サイズ: 1チャンク数バイト〜数百バイト、累計は応答長 × 1.2〜1.5 倍
  - 持続時間: **数秒〜数十秒(モデル応答時間に直結)**
  - 境界: ブラウザ → 中間プロキシ → App Service。**中間プロキシ層がボトルネック**
- 推測のチェックリスト:
  - 前段に AFD があるなら SSE は通せない → SignalR / WebSocket / 長ポーリングへの設計変更検討
  - AppGW v1 を使っているなら 2026 年中に v2 移行 + 設定確認
  - AppGW v2 でも default のまま使うとバッファされて UX が「最後にドサッと表示」になる

参考:
- [Using Server-sent events with Application Gateway](https://learn.microsoft.com/en-us/azure/application-gateway/use-server-sent-events) — Response Buffer 無効化、Request timeout、必要ヘッダ
- [Application Gateway SSE 対応 Q&A](https://learn.microsoft.com/en-us/answers/questions/1409780/azure-application-gateway-support-for-server-sent) — AFD は SSE 非対応、AppGW v1 は 2026-04-28 retire、v2 対応
- [Front Door 503 troubleshooting](https://learn.microsoft.com/en-us/troubleshoot/azure/front-door/troubleshoot-issues) — origin response timeout デフォルト 30s、最大 240s

### 7. ⑤⑥ 裏方の通信 — Cosmos DB と Application Insights

**主張**: ユーザー操作と直接結びつかない裏方通信は推測から漏れがち。実際には**ユーザー操作1回が裏で 5〜30 個の telemetry を生む**。「アプリの通信」と「監視の通信」を別レイヤーで描くと推測精度が上がる。

- **Cosmos DB**:
  - 方向: App Service → Cosmos DB(リージョン内) / マルチリージョンならクロスリージョン replication 通信もある
  - 頻度: チャット履歴の 読み出し + 書き込み で 2〜N 回 / メッセージ
  - サイズ: 1ドキュメント数 KB(チャット履歴は会話まるごとを 1 ドキュメントにすると肥大化)
  - 持続時間: 短命だが TLS handshake コストあり → 接続プールが効く
  - 境界: VNet + Private Endpoint or Public、PE経由なら Inbound Data Processed 課金
- **Application Insights / Log Analytics**:
  - 方向: App Service → AI ingest endpoint(常に egress)
  - 頻度: **request / dependency / trace / metric を毎リクエストごとに送出**。内訳は requests 1 件、dependencies 数件、traces 数〜数十件
  - サイズ: 1 telemetry あたり数百 byte 〜 数 KB(traces / customDimensions が太ると一気に膨らむ)
  - 持続時間: バッチ送信なので個別は短命
  - 境界: 多くは Public ingest。Azure Monitor Private Link Scope (AMPLS) を使えば PE 経由
- 落とし穴:
  - **チャット本文を traces / customDimensions に乗せる**と、ユーザー入力 + AI応答(数 KB) × チャット数 が telemetry として全量 ingest され、**月次データ量が桁で跳ねる**
  - Sampling は ingestion sampling と SDK サンプリング(OTel)で意味が違う。前者は精度を犠牲にしつつ「最終手段」、後者は「設計時点で絞る」
  - ヘルスチェックや Always On のキープアライブも request telemetry として記録される

参考:
- [Troubleshoot High Data Ingestion in App Insights](https://learn.microsoft.com/en-us/troubleshoot/azure/azure-monitor/app-insights/telemetry/troubleshoot-high-data-ingestion) — traces / dependencies / customMetrics の削減手段
- [OpenTelemetry sampling](https://learn.microsoft.com/en-us/azure/azure-monitor/app/opentelemetry-sampling) — SDK 側サンプリング vs ingestion サンプリングの違い

### 8. 全体の通信量を俯瞰する — ユースケース別にどこがどう変わるか

**主張**: 3〜7 章で各矢印を個別に見てきたが、**実務で効く問いは「合計どれくらい流れるか」と「どのユースケースでどの矢印が重くなるか」**。ここで俯瞰表とユースケース別の重心シフトを提示し、個別の矢印を「連鎖」として捉え直す。

- **8.1 「1メッセージあたり」の通信量を分解する**: 6 矢印の典型値を一つの表に並べ、境界別の内訳でユーザー操作 1 回の「通信コスト」を総量で語れるようにする
  - 表: 各境界の 1 メッセージあたり典型値 / サイズが伸びる条件
  - 「1 メッセージ = 数十 KB 〜 数百 KB、6 境界にまたがる」という相場感を与える
- **8.2 通信量どうしの連鎖関係**: ある変数を動かすと**複数の矢印が同時に伸びる**関係を明示
  - プロンプト長 ↑ → AOAI ingress ↑ + telemetry ↑
  - 応答長 ↑ → AOAI/外部AI egress ↑ + ブラウザ SSE ↑ + App Insights trace ↑ + **SSE 持続時間 ↑(= 同時接続数 ↑)**
  - Streaming 有効 → UX ↑ / 同時接続必要数 ↑ / App Service インスタンス必要数 ↑
  - RAG チャンク数 ↑ → 埋め込み egress ↑ + Vector / Cosmos reads ↑ + AOAI prompt tokens ↑
  - Agent ループ N → AOAI RTT × N + telemetry × N + DB reads × N
  - Sampling rate ↑ → App Insights 送信量 ↓ / トレース解像度 ↓
- **8.3 ユースケース別の重心シフト**: 5〜6 個のユースケースで「どの矢印が重心になるか」の対応表
  - シンプル QA、長文要約、RAG + ベクター検索、Tool-calling / Agent、ファイル添付、ダッシュボード系 UI
- **8.4 「重心」から設計を逆算する**: 重心が分かると SKU 選定 / 前段選定 / サンプリング設計が一意に絞れる、という実務ループ

- 根拠: 本記事の 3〜7 章で集めた一次情報の再構成がメイン。新規の外部 URL 追加はなし。ただし SSE の持続時間 ↑ → 同時接続数 ↑ の議論は、AppGW の request timeout / AFD の origin response timeout の制約が下敷き

### 9. 推測の答え合わせ — 「予測 → 観測 → 修正」のループ

**主張**: 推測は仮説。リリース前後で必ず観測と突き合わせ、ズレた箇所は推測モデルを更新する。

- 観測手段の対応表:
  - **ブラウザ ↔ App Service**: ブラウザ DevTools の Network、AFD の Logs / Metrics
  - **App Service 内部 / 外部呼び出し**: App Insights の dependencies(自動収集される)
  - **Private Endpoint 経由のトラフィック**: NSG flow logs / Network Watcher Connection Monitor
  - **VNet 統合 outbound**: Diagnostic Settings の AppServicePlatformLogs、`tcping` / `nslookup` での確認
  - **Egress 量の総量**: Cost Management の "Bandwidth" カテゴリ
- 「思ったのと違う」典型例:
  - AOAI Private Endpoint を張ったのに egress 課金が減らない → VNet Integration / DNS の設定漏れ
  - SSE が定期的に切れる → AFD を経由している、または AppGW の Request timeout が短い
  - App Insights のコストが想定の 5 倍 → チャット本文を customDimensions に乗せていた

### 10. まとめ

**本記事の核**:
- アーキ図の各矢印に **方向 / 頻度 / サイズ / 持続時間 / 境界** の5軸を書き込め
- Next.js App Router は **目に見えない通信(RSC / prefetch / Server Actions / streaming HTML)** が常時流れる
- Azure 特有の地雷は **SSE × Front Door 非対応** と **VNet Integration が outbound only** の2つに集約される
- 監視の通信は「アプリの通信」とは別レイヤー。サンプリングと項目選定で桁が変わる
- **ユースケース(単純 QA / RAG / Agent / ファイル添付 / ダッシュボード UI)で重心が変わる**。1つの変数を動かすと複数の矢印が連鎖して伸びる
- 推測は仮説。リリース前後で観測と突き合わせて更新する

---

## 不足情報 / 追加調査メモ

- 必要に応じて、AppGW v2 の SSE retire スケジュール詳細(2026-04-28 という情報は Q&A コメント由来。正式 retire アナウンスを引いておくと強い) → 本文公開前に v2 公式 retire announcement を引きたい
- AFD が SSE 非対応である件は MS Q&A でのコメント根拠。AFD Standard/Premium 公式 docs での明示があれば引きたい(現時点では origin response timeout の 30s デフォルトを根拠に「長命接続が許容されない」点を補強)
