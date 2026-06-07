---
title: "「7層のどこで守るか」— Web公開システムの多層防御を層の地図で設計する"
emoji: "🛡️"
type: "tech"
topics: ["networking", "security", "aws", "azure", "infrastructure"]
published: false
---

## はじめに — 公開した瞬間、全層が攻撃面になる

別シリーズで「OSI/TCP-IP モデルで通信の地図を持つ」「閉域を作るとは何をすることか」を書きました。あちらの主題は **「つながる／閉じる」=接続性**でした。「DNS は引けているか → 経路はあるか → ファイアウォールは通しているか」と、**どこが壊れているかを層で局所化する**話です。

この記事は、**同じ 7 層の地図を、別の軸で読み替えます**。システムを公開した瞬間、地図は「切り分けのための座標系」から「**攻撃面の地図**」に変わります。問いはこうです。

> どの層に、何が露出し、どの部品で、どこまで止められるのか。

前提として、OSI/TCP-IP の層構造・カプセル化・「機器ごとに見る層が違う（スイッチは L2、ルータは L3、ファイアウォールは L3/L4）」は理解済みとします。ここで再説明はしません。本記事が紙幅を割くのは、**各層の防御部品の「守備範囲」と「限界（=次の層に残る穴）」**、そして**本番でそれをどう選ぶか**の判断軸です。

最初に結論を一つ。**防御は単一の壁ではありません。** 「セキュリティ ON」というボタンはなく、層ごとに別の部品が別の脅威を止め、1 つが破られても次が止める——これが **多層防御(defense in depth)** です。逆に言えば、ある層だけ固めても、別の層の穴からあっさり落ちます。

### この記事で歩く参照構成

具体例として、ありふれた「公開 Web システム」を 1 枚用意します。これを**上の層から下へ縦に歩き**ます。

```
[Internet]   ← ここから下、全部が攻撃面
   │
[L3/L4 ボリューム吸収]   クラウド標準保護 / CDN・エッジ網
   │
[CDN・エッジ + WAF(L7) + TLS終端]   CloudFront / Front Door + WAF
   │
[ロードバランサ]   L4: NLB  /  L7: ALB
   │
[セキュリティグループ・NSG]   L3/L4 のマイクロ境界
   │
[アプリ]   L7 ロジック・認証・入力検証
   │
[DB / 内部サービス]   最深部・最小権限
```

各層について「**何が露出するか → どの部品が守るか → その部品では守れないこと**」の 3 点で見ていきます。最後の「守れないこと」が、なぜ次の層が要るのかの答えになります。

## 1. 攻撃面の二分法 — 「体力を奪う層」と「論理を突く層」

防御部品を層に並べる前に、**攻撃側を 2 系統に分ける**と地図が一気に整理できます。クラウド事業者の公式ドキュメントも、この二分法で防御を説明しています。

AWS Shield のドキュメントは、DDoS を 2 つに大別します([How AWS Shield works](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-overview.html))。

- **インフラ層攻撃(L3/L4)** — ネットワーク層・トランスポート層を狙う。帯域を飽和させる、あるいは接続状態を枯渇させる。代表例が **TCP SYN flood**：サーバやロードバランサ、ファイアウォールの接続状態テーブルを食い潰す。
- **アプリ層攻撃(L7)** — アプリにとって**正規に見えるリクエスト**を大量に投げる。例：Web リクエスト flood(HTTP flood)。

この 2 つは性質がまったく違います。

| | インフラ層(L3/L4) | アプリ層(L6/L7) |
|---|---|---|
| 攻撃の性質 | **量で殴る**（帯域・接続枯渇） | **正規の皮をかぶって殴る/論理を突く** |
| 例 | SYN flood, UDP リフレクション | HTTP flood, SQLi, XSS |
| 見分け方 | パケット数・ビットレートが異常 | リクエスト 1 本ずつは正常に見える |
| 止める場所 | 入口（ネットワーク/エッジ） | アプリの手前（WAF）とアプリ自身 |

ここが多層防御の出発点です。**L3/L4 をいくら吸収しても、正規に見える L7 リクエストは素通り**します。逆に、WAF で L7 を固めても、その手前で帯域が飽和すれば WAF に到達する前に落ちます。だから「片方だけ」では守れない。

しかも近年、DDoS のトレンドは **L3/L4 から L7(HTTP/S) へ移動**しています。AWS は「歴史的にネットワーク層(L3/L4)が DDoS の主戦場だったが、ここ数年でアプリ層(L7)、主に HTTP/S に焦点が移った」と述べ、そのために WAF が DDoS 防御の前面に出てきたと説明しています([AWS WAF application layer DDoS protection](https://aws.amazon.com/blogs/networking-and-content-delivery/introducing-the-aws-waf-application-layer-ddos-protection))。米 CISA らの DDoS ガイドも、プロトコルベース攻撃は L3/L4、アプリケーションベース攻撃は L7、と同じ線で整理しています([CISA DDoS guidance](https://www.cisa.gov/))。

この「**量(L3/L4)** と **論理(L7)**」の二分を頭に置いて、上から降りていきます。

## 2. L3 — 入口でボリュームを吸収する（届かせない防御）

L3 の防御目的は、突き詰めると **1 つだけ**です。

> **大容量を自分の前で吸収し、origin に届かせない。**

ここは設計思想が他の層と違います。SYN flood や UDP リフレクションのような**ボリュメトリック攻撃は、自前のサーバを増強しても勝てません**。攻撃側の総帯域が、あなたの回線容量を超えればそれで終わりだからです。したがって L3 防御の原則は、**自前で受けず、容量を持つ側（クラウド/CDN のグローバルネットワーク）に外出しして吸収させる**ことになります。

### クラウド標準保護は「基礎」、有償は「可視化と対応」

主要クラウドは、L3/L4 の自動保護を**標準で（多くは無料で）**提供しています。

- **AWS**: **Shield Standard** が全 AWS リソースに自動適用され、L3/L4 のボリュメトリック/プロトコル攻撃を無料で防御します。より高い可視化、コスト保護（攻撃でスケールした分の課金補償）、24/7 の専任対応(DRT)が要るなら **Shield Advanced**（有償）([How AWS Shield works](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-overview.html))。
- **Azure**: Azure 上の全サイトに**既定でインフラレベルの DDoS 保護**が効きます。さらに強化したい公開 IP には **Azure DDoS Protection** を有効化して、L3/L4 のボリューメトリック攻撃を保護します([Azure application DDoS protection](https://learn.microsoft.com/en-us/azure/web-application-firewall/shared/application-ddos-protection))。

ポイントは、**標準保護はあくまで「基礎」**だということ。無料で効いてはいますが、攻撃の可視化・アラート・課金補償・専任サポートといった**運用面**が欲しければ有償プランを選ぶ、という判断になります。

### さらに巨大な攻撃には「外部の容量」を借りる

想定攻撃が桁違いに大きい場合、**CDN/専業 DDoS のグローバルバックボーンで吸収する**選択肢があります。たとえば Cloudflare の Magic Transit は、自分の **IP プレフィックスごと**を相手のネットワークに通して L3 で保護する方式で、自社の大容量網で吸収します([Magic Transit](https://developers.cloudflare.com/magic-transit/get-started))。CDN を前段に置くだけでも、エッジで攻撃トラフィックを散らして origin に届きにくくする効果があります。

### L3 の判断軸

```
想定する攻撃規模  ×  止まったときの損害(可用性要件)  ×  自社の運用対応力
```

この 3 つで「標準保護のままでよいか／有償か／外部 CDN まで足すか」を決めます。スタートアップの社内ツールに Shield Advanced は過剰ですが、止まれば即売上に響く決済系なら、可視化と課金補償の価値は高い。

:::message
**この層では守れないこと**：L3/L4 のボリュームを完全に吸収しても、**正規に見える L7 リクエスト（HTTP flood、SQLi）はそのまま通過**します。だから次の層が要ります。
:::

## 3. L4 — 接続をさばく場所と、TLS をどこで終端するか

L4 の主役は**ロードバランサ(LB)**。ここでの本番設計の肝は、独立に見えて実は連動する **2 つの判断**です。

1. **L4 の LB(NLB) を使うか、L7 の LB(ALB) を使うか**
2. **TLS をどこで終端するか**

### NLB(L4) と ALB(L7) は「見る層」が違う

AWS を例に対比します（Azure は NLB↔Load Balancer、ALB↔Application Gateway/Front Door が対応）。

| | NLB（L4） | ALB（L7） |
|---|---|---|
| 見る層 | TCP/UDP・ポート | HTTP ヘッダ・パス・ホスト |
| 固定 IP | **可**（静的 IP / Elastic IP） | 不可（DNS 名） |
| TLS | 終端も可・**パススルーも可** | **必ず終端**（パススルー不可） |
| コンテンツ振り分け | 不可 | 可（パス/ホストでルーティング） |
| WAF 連携 | 直接は不可 | **可**（前提機能） |
| SG | **非対応**（ターゲット側で制御） | 対応 |
| mTLS | — | 対応 |

出典：NLB の TLS 終端対応([AWS NLB TLS termination](https://aws.amazon.com/blogs/news/new-tls-termination-for-network-load-balancers))、ALB の相互 TLS([ALB mutual authentication](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/mutual-authentication.html))、および各 LB の特性([research notes](https://info.nextmode.co.jp/blog/aws-nlb-alb-ec2-architecture))。

選び方は **要件が層を決める**形になります。

- **WAF とコンテンツルーティングが要る** → L7 LB(ALB) ＋ WAF
- **固定 IP・超低レイテンシ・TCP 透過が要る** → L4 LB(NLB)
- **固定 IP も欲しいが L7 機能も欲しい** → Global Accelerator(静的 IP) ＋ ALB のような組み合わせ
- NLB は SG を持たないので、その場合の通信制御は**ターゲット（バックエンド）側の SG**で行う、という運用差にも注意。

### TLS 終端の位置が、WAF が効く範囲を決める

ここが L4 設計で一番見落とされる点です。**TLS を終端した場所より手前は暗号、奥は平文**になります。そして——

> **WAF や L7 検査は、平文が見える場所でしか効きません。**

HTTPS のまま中身を見ずに通す(パススルー)構成では、WAF は SQLi も XSS も検出できません。だから実務の定番は、

```
クライアント ──HTTPS──▶ [エッジ/L7 LB で TLS 終端] ──▶ [平文を WAF が検査] ──(必要なら再暗号化)──▶ origin
```

という縦深になります。「エッジ or L7 LB で終端して WAF を効かせ、origin への区間は改めて暗号化する」。**TLS をどこで切るかは、暗号化の話であると同時に「WAF をどこに置けるか」の話**でもあるわけです。ALB が TLS パススルーを許さないのは、ALB がそもそも「中身を見て振り分ける/WAF と連携する」L7 部品だからです。

:::message
**この層では守れないこと**：LB は「誰と接続するか・どこへ振り分けるか」までしか見ません。**リクエスト本文の正当性（このパラメータは SQL インジェクションか？）は判定しない**。それは次の L7 の仕事です。
:::

## 4. L7 — アプリ層の防御線（WAF・レート制限・認証）

ここが「正規の皮をかぶった攻撃」を捌く最重要層です。L7 の防御は単一ではなく、**役割の違う 3 枚を重ねます**。

1. **WAF** — 既知の攻撃パターン（OWASP Top 10 など）を遮断
2. **レート制限** — 量（HTTP flood、ブルートフォース）を抑える
3. **アプリ自身の入力検証・認証/認可** — 業務ロジックの穴を塞ぐ

### WAF の守備範囲と、二重構成

WAF は **OWASP Top 10**（SQLi、XSS など Web アプリの代表的リスク）に対するマネージドルールを第一防御線として提供します([OWASP Top 10](https://owasp.org/www-project-top-ten/))。実務では、

- **エッジ WAF を第一防御線**にしつつ（CloudFront + AWS WAF、Azure Front Door + WAF）、
- **origin 側にも WAF / アプリ検証を重ねる**二重構成

にして、エッジをすり抜けたものを内側でもう一度止めます。Azure は L7 DDoS（HTTP flood、キャッシュバイパス、ボット）対策として **Front Door Premium または Application Gateway WAF v2 SKU** の利用を推奨しています([Azure application DDoS protection](https://learn.microsoft.com/en-us/azure/web-application-firewall/shared/application-ddos-protection))。GCP の Cloud Armor は Adaptive Protection で異常を学習し自動でルールを提案します。

### WAF は「いきなり遮断」しない — COUNT → BLOCK

WAF 運用の鉄則は、**最初から BLOCK にしない**ことです。誤検知で正規ユーザーを締め出すリスクがあるため、

```
COUNT(観測のみ) ──▶ ログ/メトリクスでチューニング ──▶ BLOCK(遮断)
```

と段階移行します。まず COUNT モードで「このルールは何を捕まえるか」を観測し、誤検知を潰してから遮断に切り替える。これは AWS WAF でも推奨される標準的な進め方です。

### レート制限 — L7 DDoS の主対策

HTTP flood のような「正規リクエストの氾濫」は、シグネチャでは止まりません。ここで効くのが**レート制限**です。スライディングウィンドウで「同一 IP から一定時間に N 回」を超えたら遮断します。

AWS WAF のレートベースルールは **5 分間のウィンドウ**で IP ごとのリクエストを数え、2024 年のアップデートで**最小閾値が 5 分あたり 10 リクエストまで**下げられるようになりました（より厳しい制限が可能に）([AWS WAF lower rate limits](https://aws.amazon.com/about-aws/whats-new/2024/08/aws-waf-rate-based-rules-lower-rate-limits))。ログイン API のような「正規でも高頻度はおかしい」エンドポイントに効きます。

加えて、**CDN のキャッシュ**は L7 防御の隠れた主力です。エッジでキャッシュ可能なレスポンスを返してしまえば、急増トラフィックをエッジで吸収し、origin に到達させずに済みます([Azure application DDoS protection](https://learn.microsoft.com/en-us/azure/web-application-firewall/shared/application-ddos-protection))。

### 認証・認可は WAF では守れない

最後に重要な線引き。**WAF はパターンと量に強いが、業務ロジックの欠陥は守れません。** 「他人の ID を指定すると他人のデータが見える(IDOR)」「権限のないユーザーが管理 API を叩ける」といった**認可の穴は、アプリ自身でしか塞げない**。WAF を入れたから安全、ではないのです。

:::message
**この層で守れないこと**：WAF はシグネチャと頻度に強い一方、**正規ユーザーが正規の手順で行う権限昇格や認可バイパス**は判定できません。そこはアプリのロジックの責務です。
:::

## 5. L1/L2 と最深部 — クラウドが抽象化する層と、内側の最小権限

### L1/L2 はクラウド事業者の担当（責任共有モデル）

物理層(L1)・データリンク層(L2)——ケーブル、データセンターの物理セキュリティ、スイッチ——は、クラウドでは**責任共有モデル**のもとで**事業者側が引き受けます**。利用者がケーブルや物理スイッチを直接守ることはなく、だから本記事も L3 以上を厚く扱ってきました。ここは「自分の責任範囲ではない層」として頭の隅に置けば十分です。

### 外周だけでは足りない — 内側ほど最小権限

ただし、外周（エッジ・LB・WAF）を固めれば安心、ではありません。多層防御の発想は **「1 層破られても被害を局所化する」** ことなので、**内側ほど締める**のが要点です。

- **DB を公開しない** — DB は LB やアプリのサブネットからのみ到達可能にする。
- **セキュリティグループでマイクロ境界** — 「アプリ → DB は 5432 のみ」のように、内部通信(east-west)も最小限に絞る。
- **内側も信用しない** — 「内部ネットワークだから素通し」をやめ、内部区間も暗号化・認証する（ゼロトラスト的な発想）。

こうしておくと、仮に WAF をすり抜けてアプリが 1 台侵害されても、そこから DB へ、他サービスへ、と**横移動(lateral movement)するのを内側の境界が止めます**。外周突破＝全滅、にしないための層です。

:::message
ゼロトラスト(ZTNA)の具体的な実装手順は本記事の範囲を超えるため、ここでは「内側も最小権限・相互認証」という原則の紹介に留めます。
:::

## 6. まとめ — 層ごとの「守備担当表」と設計チェックリスト

最後に 1 枚に畳みます。新しい構成を見たら、この表を上から当てて**穴を探せる**状態がゴールでした。

| 層 | 露出する脅威 | 守る部品(AWS / Azure) | この層で守れないこと |
|---|---|---|---|
| L3 | ボリュメトリック DDoS（帯域枯渇） | Shield Standard/Advanced / Azure DDoS Protection・CDN | 正規に見える L7 リクエスト |
| L4 | SYN flood、接続枯渇 | NLB/ALB、TLS 終端、SG | リクエスト本文の正当性 |
| L7 | HTTP flood、SQLi/XSS、ボット | WAF + レート制限(CloudFront/Front Door) | 認可・業務ロジックの穴 |
| アプリ | 権限昇格、IDOR | アプリの認証/認可・入力検証 | （アプリ自身が最終防衛線） |
| 内側 | 横移動、DB 直撃 | SG マイクロ境界・最小権限・内部暗号化 | — |

### 設計チェックリスト

- [ ] **L3**: クラウド標準の DDoS 保護は効いているか。可視化・課金補償が要るなら有償/外部 CDN を検討したか。
- [ ] **L4**: 固定 IP・L7 可視化の要否で LB(NLB/ALB)を選べているか。
- [ ] **L4↔L7**: **TLS 終端の位置と WAF の位置が整合**しているか（平文が見える所に WAF があるか）。
- [ ] **L7**: WAF は COUNT で観測してから BLOCK に移したか。高頻度エンドポイントにレート制限を入れたか。
- [ ] **アプリ**: 認可は WAF 任せにせずアプリで検証しているか。
- [ ] **内側**: DB は公開していないか。east-west も最小権限か。
- [ ] **運用**: WAF メトリクス（BlockedRequests の急増など）でアラートを上げ、ログを集中管理して継続チューニングしているか([AWS WAF metrics](https://docs.aws.amazon.com/waf/latest/developerguide/waf-metrics.html))。

接続性の地図では「DNS → 経路 → FW」と層を**下に潰して**障害を切り分けました。防御の地図では、攻撃を**入口から内側へ**と層ごとに止め、1 層破られても次が受ける。**同じ 7 層の地図を、読む向きを変えて 2 度使う**——これが、本番システムを「どの層をどう守るか」でイメージできるようになる、ということです。

## 参考リンク

- [How AWS Shield and Shield Advanced work (AWS)](https://docs.aws.amazon.com/waf/latest/developerguide/ddos-overview.html)
- [Introducing application layer (L7) DDoS protections for AWS WAF and Shield Advanced (AWS)](https://aws.amazon.com/blogs/networking-and-content-delivery/introducing-the-aws-waf-application-layer-ddos-protection)
- [Application (Layer 7) DDoS protection (Azure)](https://learn.microsoft.com/en-us/azure/web-application-firewall/shared/application-ddos-protection)
- [TLS termination for Network Load Balancers (AWS)](https://aws.amazon.com/blogs/news/new-tls-termination-for-network-load-balancers)
- [Mutual authentication with ALB (AWS)](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/mutual-authentication.html)
- [AWS WAF rate-based rules — lower rate limits (AWS)](https://aws.amazon.com/about-aws/whats-new/2024/08/aws-waf-rate-based-rules-lower-rate-limits)
- [AWS WAF metrics (AWS)](https://docs.aws.amazon.com/waf/latest/developerguide/waf-metrics.html)
- [Magic Transit (Cloudflare)](https://developers.cloudflare.com/magic-transit/get-started)
- [OWASP Top Ten](https://owasp.org/www-project-top-ten/)
