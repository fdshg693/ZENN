---
title: "AIチャットアプリの通信を推測する — Azure × Next.js 構成で「境界ごとの通信」を設計時に読む方法"
emoji: "📡"
type: "tech"
topics: ["azure", "nextjs", "appservice", "azureopenai", "network"]
published: false
---

## この記事について

「本番リリース後に SSE が定期的に切れる」「Private Endpoint を張ったのに egress 課金が下がらない」「Application Insights のコストが見積の 5 倍」。**通信は障害になってから観測したのでは遅い**。設計時点でアーキ図から「どこに、どんな通信が、どれくらい流れるか」を**推測**できれば、これらの多くは未然に防げます。

この記事では、

- どんなアプリにも当てられる「**通信を推測する 5 軸フレームワーク**」を提示し
- それを **Azure × Next.js × AIチャット** という典型構成に**例題として当てて**、各境界の通信を1本ずつ読み解いていきます

対象読者は、アーキ図を渡されたとき「どこにどんな通信が流れるか」を実装前に頭の中で**推測できるようになりたい**インフラ寄りエンジニアです。HTTP / TCP の基本(リクエスト・レスポンス、Keep-Alive、ヘッダ)は理解している前提で進めます。

:::message
本記事は通信の**メンタルモデル**が主題です。コスト単価の網羅は別記事 [AIチャットアプリで学ぶAzureコスト設計](https://zenn.dev/) に委譲しています(同リポジトリ内 `azure_cost_ai_chat_app.md`)。両者を組み合わせると、設計判断の左脳と右脳になります。
:::

## 0. なぜ「観測する前に推測する」のか

通信を観測する手段(App Insights、AFD のログ、Network Watcher)は揃っています。それでも設計段階で**推測**が要るのは、観測では取り返しがつかない場面が3つあるからです。

1. **SKU と前段の選定**: 後述する Front Door の SSE 非対応のように、**前段の選定ミスはあとから差し替えられない**。設計時に「ここを通る通信は SSE になる」と推測できないと、本番でハマる。
2. **コスト見積**: PoC 時点で egress 量・telemetry 量を桁で誤ると、本番で月額が想定の 3〜10 倍になる。**実装してから測る**では遅い場面がある。
3. **障害切り分け**: 本番障害時に「ここは内部通信のはず」「ここは長命接続のはず」というモデルがないと、ログを見ても何が異常か判定できない。

この記事は、その「推測の語彙」を提供します。Azure × Next.js × AIチャットは**例題**であって、5軸自体はどんなスタックでも当てられます。

## 1. 通信を推測する 5 軸フレームワーク

どんなアプリでも、通信は以下の 5 軸で記述できます。アーキ図の**各矢印**にこの 5 軸を書き込めるようになるのが目標です。

| 軸 | 問い | 例 |
|---|---|---|
| **方向** | 誰が誰に対して開始する通信か。ingress / egress / 内部 / 制御プレーン | ブラウザ → App Service は ingress、App Service → 外部AI は egress |
| **頻度** | セッション / ユーザー / リクエスト あたり何回か。定常か突発か | チャット送信1回ごと vs ページロード1回ごと vs 1秒間隔のヘルスチェック |
| **サイズ** | 1リクエスト / 1レスポンスの平均バイト数 | JSON 数KB vs JS バンドル 数百KB vs SSE で数十KB を分割送信 |
| **持続時間** | コネクションが何秒開きっぱなしか | REST 数百ms vs SSE 数十秒 vs WebSocket 数分以上 |
| **境界** | どのネットワーク境界を何回またぐか | ブラウザ → AFD → App Service → PE → Cosmos DB |

各軸が「コスト・障害・SLA」のどこに効くかを押さえておきます。

- **方向**は**egress 課金**と**セキュリティ境界(WAF / NSG)**に効く。「どっちが開始するか」を間違えると、Private Endpoint の張り方を間違える。
- **頻度**は**スループット設計**と**接続プール / コネクション数上限**に効く。「ユーザー1人 = 1リクエスト」と思った通信が、prefetch で 10 倍になっていることがある。
- **サイズ**は**egress 量**と**レイテンシ(TTFB / TTLB)**に効く。`raw_content` で 1MB の telemetry を送っていた、というのはよくある話。
- **持続時間**は**前段プロキシのタイムアウト / バッファリング**に直結する。SSE と REST はここがまったく違う。
- **境界**は**料金 / 経路 / DNS 解決 / 障害ドメイン**を決める。「同じリージョンだから内部通信」という思い込みが破綻する場面を後で見ます。

この 5 軸を**全部の矢印に当てる**のが、この記事の唯一の主張です。あとはこれを Azure × Next.js × AIチャットで実演するだけ。

## 2. 例題のアーキテクチャ

以後の章のために、典型的な Azure × Next.js × AIチャットアプリを 1 枚に固定しておきます。

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

矢印 ① 〜 ⑥ を、以後の章で1本ずつ拡大していきます。各章は「**5 軸での記述 → 落とし穴 → 推測のチェックリスト**」の順で統一します。

## 3. ① ブラウザ ↔ Front Door ↔ App Service: Next.js が実は流している通信

Next.js App Router 構成で**最も誤算を生む**のは、ユーザー操作と直接結びつかない通信、つまり **RSC payload** と **prefetch** です。SPA 感覚で「ページごとに 1 リクエスト」と数えると、実態の 5〜10 倍を見落とします。

### 3.1 初回ページロード

5 軸での記述:

- **方向**: ブラウザ → AFD → App Service(ingress)
- **頻度**: ユーザー1人につき 1 回(ただし都度更新)
- **サイズ**: HTML(streaming) + CSS + クライアント JS バンドル + bootstrap script。client component の量に依存し、数百 KB 〜数 MB
- **持続時間**: 短命だが **chunked transfer encoding** で複数チャンクが断続的に届く
- **境界**: 静的アセットは AFD でキャッシュされ、HTML はオリジンを通る → **2 種類を分けて推測**

App Router の HTML は、伝統的な SSR と違って「全部組み立ててから返す」のではなく、`<Suspense>` 境界ごとに**独立したチャンク**として `Transfer-Encoding: chunked` で流れます。Next.js 公式によれば、各 Suspense 境界はそれぞれ独立にストリームされ、互いをブロックしません[^streaming]。これは後述する SSE と同じ「**長めに開いている HTTP レスポンス**」という性質を持ちます。

[^streaming]: [Next.js: Streaming](https://nextjs.org/docs/app/guides/streaming) — "Each `<Suspense>` boundary is an independent streaming point. Components inside different boundaries resolve and stream in independently."

### 3.2 クライアント側ナビゲーション(`<Link>` クリック)

5 軸での記述:

- **方向**: ブラウザ → App Service(ingress)
- **頻度**: ユーザーのナビゲーションごと
- **サイズ**: ページ差分相当の **RSC payload**(数 KB 〜数十 KB)。HTML ではない
- **持続時間**: 短命
- **境界**: AFD オリジン経由

クリック時は HTML ではなく RSC payload(`?_rsc=...` クエリ付き)を取りに行きます。**HTML より小さい**のがメリットですが、後述の prefetch と組み合わせると総量で増えるため油断できません。

### 3.3 Prefetch — 「見えない常時通信」

これが最大の落とし穴です。`<Link>` がビューポートに入ると、Next.js は**自動で** prefetch を発火します[^prefetch]。

[^prefetch]: [Next.js: Linking and Navigating](https://nextjs.org/docs/app/getting-started/linking-and-navigating) — "Prefetched when the link is hovered or enters the viewport."

5 軸での記述:

- **方向**: ブラウザ → App Service(ingress、ユーザー操作なしで発生)
- **頻度**: 表示中の `<Link>` の数だけ。**サイドメニューに 50 リンクあれば 50 prefetch**
- **サイズ**: 軽量 prefetch(loading.tsx の static shell のみ)〜完全 prefetch(数 KB 〜数十 KB)
- **持続時間**: 短命
- **境界**: AFD オリジン経由

「一覧ページを表示しただけで数十リクエスト・数 MB が流れた」という現象はここから来ます。**長いリストや常時表示のサイドメニュー**で `<Link>` を使う設計にしたら、prefetch を意図的に切る(`prefetch={false}`)ことを検討してください。

### 3.4 Server Actions

5 軸での記述:

- **方向**: ブラウザ → App Service(ingress、POST)
- **頻度**: フォーム送信 / mutation ごと
- **サイズ**: リクエストは form data か JSON、レスポンスは**RSC payload**(再描画用の差分)
- **持続時間**: 短命
- **境界**: AFD オリジン経由

Server Actions は、mutation と再描画を**1 ラウンドトリップ**で済ませる仕組みです[^rsc]。REST + 再フェッチのパターンに比べて境界をまたぐ往復が減るので、AIチャットの「メッセージ送信 → 履歴一覧の再描画」のような操作で素直に効きます。

[^rsc]: [Vercel: Understanding RSC](https://vercel.com/blog/understanding-react-server-components) — "Server Actions in Next.js mean you can both mutate the cache and update the React tree in the same roundtrip request to the server."

### 3.5 推測のチェックリスト(① 矢印)

- [ ] ページごとに「初回ロード」「ナビゲーション」「prefetch」「Server Actions」「streaming」の**どれが**何回起きるか書き出したか
- [ ] サイドメニューや一覧ページの `<Link>` で、無自覚な prefetch を発生させていないか
- [ ] AFD のキャッシュ対象(静的アセット)とオリジン直行(HTML / RSC payload)を分けて見積もったか

## 4. ②③ App Service ↔ AOAI: 内部通信のはずが「外」を回るケース

「同じ Azure リージョン内の Azure OpenAI を呼んでいるから内部通信になっているはず」。これは**典型的な誤推測**です。**Private Endpoint を張っただけでは VNet を経由しません**。原因は App Service の VNet Integration の方向性にあります。

### 4.1 押さえるべき2つの公式仕様

公式ドキュメントは明確にこう書いています[^vnetint]。

> Virtual network integration affects only outbound traffic from your app. To control inbound traffic to your app, use the access restrictions feature or private endpoints.

[^vnetint]: [App Service VNet Integration overview](https://learn.microsoft.com/en-us/azure/app-service/overview-vnet-integration)

- **App Service の VNet Integration は outbound 専用**。アプリは VNet 内に「いる」のではなく、VNet にトンネルで outbound だけ流す。
- **App Service の Private Endpoint は inbound 専用**。VNet 内の他のリソースから App Service に**入ってくる**通信を private 化する。

つまり「App Service → AOAI を内部経路で流す」には、**outbound 側の設定(VNet Integration + ルーティング設定 + Private DNS)**を別途整える必要があります。

### 4.2 さらに `outboundVnetRouting` 設定を見る

VNet Integration を有効にしても、デフォルトでは**RFC1918 のローカル IP 宛だけ** VNet に流れます。AOAI Private Endpoint は VNet 内のプライベート IP に解決されるはずですが、**DNS 設定や routing 設定が抜けていると Public IP に解決されてしまい、結局 default route で外を回ります**。

公式は `outboundVnetRouting.applicationTraffic=true`(旧 `WEBSITE_VNET_ROUTE_ALL=1` と同義)で**アプリトラフィックを VNet 経由にする**設定を案内しています[^routing]。さらに `outboundVnetRouting.allTraffic=true` にすれば、コンテナイメージの pull やマネージド ID トークン取得などの**configuration traffic** まで VNet 経由になります。

[^routing]: [Configure VNet integration routing](https://learn.microsoft.com/en-us/azure/app-service/configure-vnet-integration-routing)

### 4.3 さらにシビアな制約: Linux App Service

Microsoft Q&A には、**Linux App Service + VNet Integration では AOAI の Private Endpoint への outbound が安定しない**という事例があります[^linuxase]。アーキ的な制約とされ、回避策として **App Service Environment v3**(VNet 内に App Service が「いる」)か、**Public エンドポイント + Managed Identity + ネットワーク制限**が推奨されています。

[^linuxase]: [App Service (Linux) with VNet integration cannot reach Azure OpenAI private endpoint](https://learn.microsoft.com/en-us/answers/questions/5789113/) — "VNet Integration is outbound-only and does not place the app inside the VNet"

### 4.4 5 軸での記述(③ 矢印: App Service → AOAI)

- **方向**: 内部(VNet)を**意図** / 設定不備時は default route で外回り
- **頻度**: チャット送信1回につき 1〜N 回(N はエージェントループや RAG の検索ステップ数)
- **サイズ**: リクエストは「トークン × 約 4 byte」が目安、レスポンスはストリーミングなら**長時間かけて累計**
- **持続時間**: stream 有効時は**数秒〜数十秒**(モデル応答時間に直結)
- **境界**: 期待: App Service → VNet → PE → AOAI / 実際: App Service → Internet → AOAI Public のことがある

### 4.5 推測のチェックリスト(③ 矢印)

- [ ] App Service 側で VNet Integration が有効か
- [ ] `outboundVnetRouting.applicationTraffic`(または `WEBSITE_VNET_ROUTE_ALL=1`)が設定されているか
- [ ] AOAI 用の Private DNS Zone が VNet にリンクされているか
- [ ] Linux App Service なら、ASE v3 移行 or Public + MI のどちらの設計を選んだか
- [ ] NSG / UDR が outbound を意図せずブロック / リダイレクトしていないか

## 5. ④ App Service → 外部AI: 「ストリーミング × egress」の二重課題

外部AI(Anthropic / OpenAI.com / Gemini など)を呼ぶ通信は、**「Internet egress 課金」と「長命 SSE 接続」が同時に**発生する特殊な性質を持ちます。両者を独立に推測すると見誤ります。

### 5.1 5 軸での記述(④ 矢印)

- **方向**: egress(Internet)
- **頻度**: チャット送信1回につき 1 回(マルチエージェント / fallback 構成なら N 回)
- **サイズ**: stream 有効時は **SSE のヘッダオーバーヘッド + delta JSON 群**。`data: {"choices":[{"delta":{"content":"..."}, ...}]}\n\n` という構造なので、本文 1 トークンに対しメタデータが繰り返し乗り、累計で本文の **1.2〜1.5 倍**になりうる[^sseguide]
- **持続時間**: stream 有効時は数秒〜数十秒
- **境界**: App Service → (VNet Integration の routing 次第) → Internet → 外部AI ベンダー

[^sseguide]: [The Complete Guide to Streaming LLM Responses](https://dev.to/pockit_tools/the-complete-guide-to-streaming-llm-responses-in-web-applications-from-sse-to-real-time-ui-3534) — SSE のフレーム形式と OpenAI/Anthropic の実装解説

### 5.2 落とし穴

- **Private Endpoint で外部AI 呼び出しを「内部化」はできない**。ベンダーが Azure 上に PE を出しているわけではないので、PE は egress 削減策にならない。
- **リージョン選定を「AOAI 同居」だけで決めると外部AI 経路が遠回りになる**。例えば AOAI を East US 2 に置いた都合で App Service も East US 2 にしたが、外部AI ベンダーの近接リージョンが Tokyo にあると、egress 経路と単価の両方で不利になる。
- **SSE の途中切断**(後述の 6 章)は、外部AI への呼び出しでも同じ問題を起こす。ベンダー側が `keep-alive` を頻繁に送ってくれるとは限らない。

### 5.3 推測のチェックリスト(④ 矢印)

- [ ] 1 メッセージあたり外部AI を何回呼ぶか(fallback / マルチエージェント込みで)
- [ ] stream 有効時の SSE 累計サイズを「本文 × 1.2〜1.5」で見積もったか
- [ ] App Service のリージョンと外部AI ベンダーの近接性を確認したか
- [ ] App Service → Internet 経路に対するタイムアウト(クライアント側 / VNet NAT / Firewall)を把握したか

## 6. SSE と中間プロキシ — Azure 特有の最大の地雷

ここが本記事の**核**です。AIチャットの応答は SSE で流すのが標準ですが、**Azure の前段プロキシ選定を間違えると SSE は根本的に通りません**。

### 6.1 SSE が中間プロキシに要求するもの

バックエンドが返すべき HTTP ヘッダは公式ドキュメントが明示しています[^appgwsse]。

```
Content-Type: text/event-stream
Connection: keep-alive
Transfer-Encoding: chunked
Cache-Control: no-cache
```

加えて、Nginx 系プロキシのバッファリングを抑止する `X-Accel-Buffering: no` を付けるのが定石です。

[^appgwsse]: [Using Server-sent events with Application Gateway](https://learn.microsoft.com/en-us/azure/application-gateway/use-server-sent-events) — 必要な response ヘッダ一式と AppGW 側の設定要件

### 6.2 Azure 前段プロキシの SSE 対応マップ

| 前段 | SSE 対応 | 注意点 |
|---|---|---|
| **Azure Front Door (Standard / Premium / Classic)** | **非対応**[^afdsse] | origin response timeout のデフォルトは 30 秒、最大でも 240 秒[^afdtimeout]。長命 SSE は通せない |
| **Application Gateway v1** | 対応 | ただし**2026-04-28 retire 予定**(コメント情報、要正式確認) |
| **Application Gateway v2** | 対応(要設定) | Response Buffer を**無効化** + Backend Setting の **Request timeout をイベント間アイドル時間より長く**[^appgwsse] |
| **App Service 直接公開** | 対応 | 最もシンプル。WAF / グローバル分散が要らないならこれが正解 |

[^afdsse]: Microsoft Q&A の AppGW SSE スレッドで、Front Door が SSE をサポートしないことが Microsoft 担当者により言及されている。[Azure Application Gateway support for server-sent events](https://learn.microsoft.com/en-us/answers/questions/1409780/azure-application-gateway-support-for-server-sent)
[^afdtimeout]: [Troubleshoot Azure Front Door common issues](https://learn.microsoft.com/en-us/troubleshoot/azure/front-door/troubleshoot-issues) — "The default timeout is 30 seconds. ... You can increase the default timeout to up to 4 minutes (240 seconds)."

つまり「とりあえず AFD を前段にしておけば速くて安全」という設計は、**AIチャット用途では成立しません**。前段選定は「SSE を通すか」を起点に決めるべきです。

### 6.3 5 軸での記述(ブラウザ ↔ App Service の SSE)

- **方向**: server から push(ただし HTTP レスポンス内)
- **頻度**: チャット送信1回につき 1 接続
- **サイズ**: 1チャンク数バイト〜数百バイト、累計は応答長 × 1.2〜1.5 倍
- **持続時間**: **数秒〜数十秒**(モデル応答時間に直結)
- **境界**: ブラウザ → 中間プロキシ → App Service。**中間プロキシ層がボトルネック**

### 6.4 設計ルートの比較

| 構成 | 長所 | 短所 | 向くケース |
|---|---|---|---|
| AFD + App Service(SSE 経路だけ別) | グローバル配信 + WAF | SSE エンドポイントだけ AFD をバイパスする経路設計が必要 | グローバルユーザー / 静的アセットを CDN 配信したい |
| AppGW v2 + App Service | リージョン内 WAF + SSE 対応 | グローバル分散はない | 国内向け、閉域要件、SSE 必須 |
| App Service 直接公開 | 最小構成、SSE そのまま通る | WAF / 分散がない | PoC、社内向け、外部 WAF を別途持っている |
| SignalR Service / WebSocket に切り替え | AFD の前段でも通せる(WebSocket は AFD 対応) | サーバ実装と SDK 選定の変更が必要 | グローバル + WAF + リアルタイム配信を全部欲しい |

### 6.5 推測のチェックリスト(SSE)

- [ ] 前段に AFD を置く前提なら、SSE 経路の代替(直接公開 / SignalR / WebSocket)を決めたか
- [ ] AppGW v2 を使うなら Response Buffer 無効化と Request timeout の見直しをしたか
- [ ] バックエンドが SSE 4 ヘッダ(`text/event-stream` / `keep-alive` / `chunked` / `no-cache`)を**必ず**返しているか
- [ ] AppGW v1 を使っているなら、retire 予定までの v2 移行計画があるか

## 7. ⑤⑥ 裏方の通信 — Cosmos DB と Application Insights

ユーザー操作と直接結びつかない「裏方通信」は**推測から漏れがち**です。実際にはユーザー操作 1 回が、裏で 5〜30 個の telemetry や複数回の DB アクセスを生みます。「アプリの通信」と「監視 / DB の通信」は別レイヤーで描き分けると推測精度が上がります。

### 7.1 Cosmos DB(⑤ 矢印)

- **方向**: App Service → Cosmos DB(同一リージョン内、または PE 経由)。マルチリージョン書き込みなら**クロスリージョン replication 通信**も裏で常時走る
- **頻度**: メッセージ 1 件につき 履歴の読み出し + 書き込み で 2〜N 回
- **サイズ**: 1 ドキュメント数 KB(チャット履歴を 1 ドキュメントに丸ごと持たせると、**送信のたびに肥大化したドキュメントを丸ごと書き直す**形になる)
- **持続時間**: 短命だが TLS handshake コストはある → 接続プールが効く
- **境界**: VNet + Private Endpoint or Public。PE経由なら**Inbound Data Processed 課金**が乗る

設計上の落とし穴として、「会話まるごと 1 ドキュメント」スキーマだと、書き込み 1 回ごとに**そのドキュメントの全サイズが request unit と転送量に効く**点があります。メッセージを別ドキュメントに分けるか、append-only にするかで通信プロファイルが変わります。

### 7.2 Application Insights / Log Analytics(⑥ 矢印)

- **方向**: App Service → AI ingest endpoint(常に egress)。AMPLS を使えば PE 経由
- **頻度**: **毎リクエストごとに request 1 件 + dependencies 数件 + traces 数〜数十件 + metrics**
- **サイズ**: 1 telemetry あたり数百 byte 〜数 KB。`customDimensions` が太ると一気に膨らむ
- **持続時間**: バッチ送信なので個別は短命
- **境界**: Public ingest が一般的

最大の地雷は、**チャット本文を `traces` や `customDimensions` に丸ごと載せてしまう**ことです。ユーザー入力 + AI 応答(数 KB)× チャット数 が telemetry として全量 ingest され、月次データ量が桁で跳ねます。

軽減策は 2 系統あります[^aisampling][^aiingest]。

- **SDK サンプリング(OpenTelemetry)**: 設計時点で**送る前に絞る**。標準メトリクスは preaggregation されるので精度を保ちやすい
- **Ingestion サンプリング**: Azure Monitor の ingest 側で間引く。**最終手段**で、broken trace のリスクが高まる

[^aisampling]: [Sampling in Azure Application Insights with OpenTelemetry](https://learn.microsoft.com/en-us/azure/azure-monitor/app/opentelemetry-sampling) — SDK 側 vs ingestion 側の役割分担
[^aiingest]: [Troubleshoot High Data Ingestion in Application Insights](https://learn.microsoft.com/en-us/troubleshoot/azure/azure-monitor/app-insights/telemetry/troubleshoot-high-data-ingestion) — `traces` / `dependencies` / `customMetrics` ごとの削減手段

### 7.3 推測のチェックリスト(⑤⑥ 矢印)

- [ ] チャット履歴のスキーマ(1 会話 = 1 ドキュメント or 1 メッセージ = 1 ドキュメント)を決めたか
- [ ] Cosmos DB をマルチリージョンにする場合、replication 通信のコストと方向を見積もったか
- [ ] チャット本文を `customDimensions` / `traces` に**乗せない**ルールを設けたか
- [ ] App Insights のサンプリングを SDK 側で設計したか、ingestion 側に頼っていないか

## 8. 全体の通信量を俯瞰する — ユースケース別にどこがどう変わるか

3〜7 章では 6 本の矢印を **1 本ずつ** 拡大してきました。ただ実務で本当に効く問いは、「全部で**合計どれくらい**流れるのか」「**どのユースケース**で**どの矢印が**重心になるのか」です。この章ではそれを俯瞰します。

### 8.1 「1 メッセージあたり」の通信量を分解する

ユーザーがチャットで 1 メッセージ送信したときに**6 境界すべてで**発生する通信を、1 枚の表にまとめます。これが**最小の予算単位**です。

| 境界 | 方向 | 1 メッセージあたりの典型値 | サイズが伸びる条件 |
|---|---|---|---|
| ① ブラウザ → App Service(送信) | ingress | 数 KB (JSON) | 添付ファイル、長文プロンプト、会話履歴の全体送信 |
| ③ App Service → AOAI / 外部AI | egress / VNet | 数 KB(トークン × 約 4 byte) | コンテキスト肥大、RAG で検索結果を prompt に挿入 |
| ④ AOAI / 外部AI → App Service(SSE) | ingress(VNet or Internet) | 応答本文 × 1.2〜1.5 | 長文応答、tool call の JSON が繰り返し乗る |
| ① App Service → ブラウザ(SSE) | egress(下り) | 応答本文 × 1.2〜1.5 | 上流 SSE と同量がそのまま流れる |
| ⑤ App Service ↔ Cosmos DB | 内部 or PE | 読み + 書きで数 KB × 2 | 履歴スキーマ(1 会話 = 1 ドキュメント だと肥大) |
| ⑥ App Service → App Insights | egress | 数 KB × (req 1 + dep N + trace M) | `customDimensions` 設計、チャット本文を載せる運用 |

**合計の相場感**: 1 メッセージで**数十 KB 〜 数百 KB**が**6 境界にまたがって**流れます。「チャット 1 往復 = AOAI への 1 リクエスト」ではありません。

### 8.2 通信量どうしの「連鎖関係」

ここが本章の核です。**1 つの変数を動かすと複数の矢印が同時に伸びる**ので、矢印を独立に最適化してもうまくいきません。主要な連鎖を挙げます。

| 動かす変数 | 連鎖して伸びる矢印 | 理由 |
|---|---|---|
| **プロンプト長 ↑**(会話履歴 / システムプロンプト) | ③ AOAI ingress、⑥ App Insights dependency | 毎回 prompt 全体を送る。`dependency` に prompt 本体が載る運用だと telemetry も同量増える |
| **応答長 ↑** | ④ AOAI→App Service SSE、① App Service→ブラウザ SSE、⑥ trace、**SSE 持続時間** | 応答が長いほど SSE 接続が長時間開く → **同時接続数が上がる** → App Service のメモリ・インスタンス数に効く |
| **Streaming ON** | UX 改善(TTFB ↓) | だが SSE 持続時間 ↑。**同時接続の並列度**が設計の主変数になる |
| **RAG チャンク数 ↑** | ③ AOAI prompt、⑤ Cosmos / Vector reads、事前の埋め込み egress | 検索結果を prompt に挿入するため、**③ と ⑤ が同時に伸びる**。Cosmos の RU も跳ねる |
| **Tool / Agent ループ回数 N** | ③ AOAI RTT × N、⑥ telemetry × N、⑤ DB reads × N | 1 ユーザー操作で**すべての矢印が N 倍**になる。最も怖いスケーラー |
| **同時アクティブユーザー ↑** | ①(SSE 同時接続)、⑤ Cosmos 接続プール、⑥ ingestion | SSE は**持続接続**なのでコネクション数で詰まる。REST と直観が違う |
| **Sampling rate ↑** | ⑥ 送信量 ↓ / トレース解像度 ↓ | App Insights の送信量は減るが、**dependency グラフが欠ける**副作用 |

覚えておくべきは 2 つです。

- **応答長 ↑ は「データ量」と「時間」の両方を増やす**。同時接続数設計まで波及する
- **RAG / Agent は複数の矢印を同時に N 倍にする**。単独の矢印を見て最適化しても効かない

### 8.3 ユースケース別の「重心」シフト

同じアーキでもユースケースによって**重くなる矢印が変わります**。設計判断は「自分のアプリの重心」を特定することから始まります。

| ユースケース | 重心となる矢印 | 実務上の注意 |
|---|---|---|
| **シンプル QA**(短い質問 / 短い応答) | 分布に大きな偏りなし | 標準的な見積で足りる。PoC はここから |
| **長文コンテキスト要約**(PDF 丸投げ系) | ③ AOAI ingress が肥大 | トークン単価で効く。転送量は中程度。**prompt caching** を検討 |
| **RAG + ベクター検索** | ③ AOAI + ⑤ Cosmos / Vector DB | **Cosmos RU が跳ねる**。読み取り整合性レベル、パーティション設計で通信量が桁変わる |
| **Tool-calling / Agent ループ** | ③④ が × N、⑥ も × N | **監視側が一番早く悲鳴を上げる**。trace / dependency の総量で App Insights 課金が跳ねる |
| **ファイル添付(PDF・画像要約)** | ① 入力 ingress が大、Blob Storage 経由の場合は⑤ も | Blob に直接アップロードさせて App Service を経由させない設計で ① を軽くできる |
| **ダッシュボード系 UI**(社内ツール的) | **① prefetch が爆発** | チャット本体より UI 起因の通信が多いケースも。3.3 節の対策必須 |
| **グローバルマルチリージョン配信** | **Cosmos クロスリージョン replication**、AFD経由の HTML 配信 | 書き込み整合性モデルの選定が通信量を決める |

### 8.4 「重心」から設計を逆算する

重心が分かると、設計判断の多くが**一意に絞れます**。

- **Agent ループが重心** → App Insights の SDK サンプリングを最初から設計する / tool 呼び出しを `dependency` ではなく `customEvent` で記録する / Cosmos の読み取り整合性を緩める
- **長文応答が重心** → SSE 必須 → 前段は AFD ではなく AppGW v2 か直接公開 → AppGW v2 の Request timeout をモデル最大応答時間に合わせる
- **prefetch が重心** → 一覧ページで `prefetch={false}` を徹底 / 軽量 prefetch(loading.tsx のみ)に留める
- **RAG が重心** → Cosmos のパーティションキーと RU、Vector インデックス側の通信量をまず見る / App Insights の `dependencies` の件数も跳ねるので同時に設計する
- **マルチリージョン配信が重心** → Cosmos の整合性モデルと書き込みリージョン設計が通信量の支配要因

つまり、**「通信の 5 軸 × 矢印別」の分析は、ユースケースの重心を当てるためのツールでもある**ということです。重心が決まれば、SKU・前段・サンプリング・スキーマが芋づる式に決まります。

## 9. 推測の答え合わせ — 「予測 → 観測 → 修正」のループ

推測は**仮説**です。本番リリース前後で必ず観測と突き合わせ、ズレた箇所はモデルを更新します。

### 9.1 観測手段の対応表

| 推測対象 | 観測手段 |
|---|---|
| ブラウザ ↔ App Service の通信内訳 | ブラウザ DevTools の Network、AFD の Logs / Metrics |
| App Service の外部呼び出し(AOAI / 外部AI / Cosmos DB) | App Insights の dependencies(自動収集) |
| Private Endpoint 経由のトラフィック | NSG flow logs / Network Watcher Connection Monitor |
| VNet 統合 outbound の実経路 | App Service 内から `nslookup` / `tcping`、Diagnostic Settings の AppServicePlatformLogs |
| Egress 量の総量 | Cost Management の "Bandwidth" カテゴリ |

### 9.2 「思ったのと違う」典型例とその真因

- **AOAI の Private Endpoint を張ったのに egress 課金が減らない** → VNet Integration の routing 設定 (`outboundVnetRouting.applicationTraffic`) または Private DNS Zone リンクが抜けている。`nslookup` で AOAI のホスト名がパブリック IP に解決されていないか確認する。
- **SSE が定期的に切れる** → 前段に AFD を経由している、または AppGW v2 の Request timeout がイベント間アイドル時間より短い、または Response Buffer が有効。
- **App Insights のコストが想定の 5 倍** → チャット本文を `customDimensions` / `traces` に載せている可能性が高い。`AppTraces` テーブルを `_BilledSize` で集計して、肥大している logger カテゴリを特定する。
- **prefetch で予想外の負荷** → 一覧ページの `<Link>` が大量にあり、ユーザーが画面表示しただけで数十リクエストが流れている。AFD のログで `?_rsc=` 付きリクエストの数を見れば即わかる。

## 10. まとめ

本記事の核を 5 つに集約します。

1. **アーキ図の各矢印に「方向 / 頻度 / サイズ / 持続時間 / 境界」の 5 軸を書き込め**。これだけで見落としと誤認の大半が消える。
2. **Next.js App Router は目に見えない通信(RSC / prefetch / Server Actions / streaming HTML)が常時流れる**。SPA 感覚での見積は実態の 5〜10 倍を見落とす。
3. **Azure 特有の地雷は「SSE × Front Door 非対応」と「VNet Integration が outbound only」の 2 つに集約される**。前段選定と PE 設計はここを起点に決める。
4. **裏方の通信(DB / 監視)は別レイヤーで描く**。サンプリングと項目選定で月次コストが桁で変わる。
5. **ユースケース(単純 QA / 長文要約 / RAG / Agent / ファイル添付 / ダッシュボード UI / マルチリージョン)で重心が変わる**。1 つの変数を動かすと複数の矢印が連鎖して伸びるので、**重心特定 → 芋づる式設計**が最短ルート。

そして最後に、推測は仮説です。リリース前後で**観測と突き合わせて推測モデルを更新する**ループを必ず回してください。「設計書通りだった矢印」と「設計書と違った矢印」を仕分けるだけで、次のプロジェクトの推測精度が上がります。

:::message
コスト単価そのものに踏み込みたい方は、同リポジトリ内の [AIチャットアプリで学ぶAzureコスト設計 (`azure_cost_ai_chat_app.md`)](https://zenn.dev/) をあわせて参照してください。本記事の「通信プロファイルの推測」と、コスト記事の「料金構造の理解」を組み合わせると、本番設計の判断が一段速くなります。
:::
