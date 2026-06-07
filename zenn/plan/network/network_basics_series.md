---
title: "クラウド閉域を理解するためのネットワーク基礎(シリーズ)"
status: plan
---

> 5 本のテーマ別シリーズの plan。各記事の構成・主張・根拠 URL を記載する。publish 群と主張を一致させること。
> 既存記事 `closed_network.md`(閉域を作る記事)の「前提知識」を、汎用ネットワーク原理から深く解説し、各所でクラウド構成要素(VPC/サブネット/SG/NACL/ルートテーブル/Private DNS)へ対応づける。

## シリーズ共通の方針

- **フレーミング**: 各記事とも ①汎用原理を深く → ②クラウド構成要素へ対応づけ(AWS/Azure) → ③`closed_network` の該当箇所へ接続 の 3 段構え。
- **レイヤ範囲**: 0 番で OSI 全層を俯瞰し地図を渡す。1〜4 番で L3/L4/DNS を特に厚く掘る。
- **対象読者**: `closed_network.md` は読み通せるが、「そもそも NAT とは? DNS 解決とは? CIDR の /24 は何を意味する?」を原理から固めたい技術者。VPC/SG/ルートテーブルを操作はできるが背後の汎用原理に自信がない層。
- **各記事の比重**: 原理(厚)+クラウド対応づけ(中)+落とし穴/向かない使い方(必ず入れる)。
- **タグ案(全記事共通寄せ)**: `["networking", "tcpip", "aws", "azure", "infrastructure"]`(`closed_network` の `aws`/`azure`/`networking` を再利用)。
- **各記事末**: 「次に読むべき `closed_network` のどこ」へ橋渡しする導線を置く。

## シリーズ全体の構成

| # | 仮タイトル | 中心の問い | 厚み | closed_network 接続点 |
|---|-----------|-----------|------|----------------------|
| 0 | パケットの一生 — OSI/TCP-IP モデルで地図を持つ | データは層をどう降りて昇るか/カプセル化 | 俯瞰 | 「層で分けて考える」発想の下地 |
| 1 | IP アドレス・CIDR・サブネット — 区画を切るとは | private/public・RFC1918・CIDR・サブネット計算 | 厚(L3) | ①境界/プライベート IP 空間 |
| 2 | ルーティングと NAT — パケットはなぜ着くか | ルートテーブル・最長一致・デフォルトルート・NAT | 厚(L3) | ③外向き遮断/NAT・IGW |
| 3 | ファイアウォールとアクセス制御 — ステートフルとは | TCP/UDP とポート・stateful/stateless・SG/NACL | 厚(L4) | SG/NACL/NSG の挙動差 |
| 4 | DNS の仕組み — 名前が引けるとつながるは別 | 再帰/権威・CNAME・解決フロー・プライベート DNS | 厚(L7だが閉域の要) | ④名前解決/解決とアクセスは独立 |

---

## 記事 0: パケットの一生 — OSI/TCP-IP モデルで全体地図を持つ
slug: `network_basics_0_osi`

### 解決する問題
「NAT は L3? ファイアウォールは何層? DNS は?」と層がごちゃつくと、閉域の切り分けで「どこを見ているか」を見失う。まず全層の地図を持たせ、以降 4 記事の座標系を与える。

### 構成と主張
- **0-1 なぜ層に分けるのか**: 通信は複数の独立した役割の積み重ね。層に分けると「どこが壊れているか」を局所化できる。`closed_network` の 4 層モデルもこの発想の応用。
- **0-2 OSI 7 層と TCP/IP モデル**: OSI=物理/データリンク/ネットワーク/トランスポート/セッション/プレゼン/アプリの 7 層。TCP/IP は 5 層(セッション/プレゼンをアプリに統合)。各層の代表例(L2=Ethernet/MAC, L3=IP, L4=TCP/UDP, L7=HTTP/DNS)。根拠: NetworkAcademy OSI, GeeksforGeeks OSI vs TCP/IP。
- **0-3 カプセル化とヘッダ**: 上位層データを各層がヘッダで包む。PDU 名: L4=セグメント, L3=パケット, L2=フレーム。受信側でデカプセル化。スイッチは L2、ルータは L2+L3 を見る。根拠: Study CCNA encapsulation, NetworkAcademy OSI。
- **0-4 この地図に閉域の各要素を置く**: サブネット/CIDR=L3、ルーティング/NAT=L3、SG/NACL=L3-L4、DNS=L7。本シリーズの各記事がどの層を扱うか俯瞰表で示す。
- **0-5 まとめ + 次へ**: 「層で切る」発想を持って記事 1(IP)へ。

### 根拠 URL
- https://www.networkacademy.io/ccna/network-fundamentals/understanding-the-osi-model
- https://study-ccna.com/encapsulation
- https://www.geeksforgeeks.org/computer-networks/difference-between-osi-model-and-tcp-ip-model

---

## 記事 1: IP アドレス・CIDR・サブネット — 区画を切るとは何か
slug: `network_basics_1_ip_subnet`

### 解決する問題
「プライベート IP=閉域」という誤解の起点。IP/CIDR/サブネットマスクを原理から理解し、VPC/VNet の CIDR 設計が何を決めているのかを腹落ちさせる。

### 構成と主張
- **1-1 IP アドレスとは**: 32bit を 8bit×4 で表記。ネットワーク部+ホスト部。
- **1-2 public と private**: グローバルに一意な public と、組織内で自由に使える private。RFC1918 の 3 レンジ(10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)。private はインターネットに直接出られず NAT が要る(→記事 2 への伏線)。リンクローカル 169.254.0.0/16、CGN 100.64.0.0/10 も軽く。根拠: pfSense addresses, Azure UDR(予約レンジ)。
- **1-3 CIDR とサブネットマスク**: `/n` はネットワーク部の bit 数。`/24`=256 アドレス、`/16`=65536。マスクとの対応、ネットワークアドレス/ブロードキャストアドレス、使用可能ホスト数の計算。最長一致(→記事 2)の布石として「より長い /n がより小さい区画」を強調。根拠: pfSense addresses。
- **1-4 サブネットに切る意味**: 大きな区画を小さく割り、ルーティング/制御の単位にする。
- **1-5 クラウド対応づけ**: AWS VPC=自分専用の IP 空間、サブネット=AZ 内の区画。VPC ルートテーブルの **local ルート**は VPC CIDR への到達を既定で持つ。Azure VNet/サブネットも同様。`closed_network` の「①境界」がこれ。根拠: AWS subnet-route-tables(local route), AWS VPC how-it-works。
- **1-6 落とし穴**: CIDR レンジの重複(VPC ピアリング/オンプレ接続で衝突)、過小な /27 で IP 枯渇、プライベート IP を割っただけでは閉じていない。
- **1-7 まとめ + 次へ**: 区画はできた。では区画間をどう運ぶか → 記事 2(ルーティング/NAT)。

### 根拠 URL
- https://docs.netgate.com/pfsense/en/latest/network/addresses.html
- https://www.flackbox.com/cisco-private-ip-addresses-rfc1918
- https://docs.aws.amazon.com/vpc/latest/userguide/subnet-route-tables.html
- https://learn.microsoft.com/en-us/azure/virtual-network/virtual-networks-udr-overview

---

## 記事 2: ルーティングと NAT — パケットはなぜ目的地に着くか
slug: `network_basics_2_routing_nat`

### 解決する問題
`closed_network` の「外向き遮断はデフォルトルートが鍵」「NAT を置かなければ外に出られない」を、ルーティングと NAT の原理から理解する。

### 構成と主張
- **2-1 ルーティングの基本**: ルータは宛先 IP を見てルートテーブルを引き、ネクストホップへ転送。各ホップで L2 ヘッダは付け替え、L3(IP)は保持。
- **2-2 最長プレフィックス一致**: 複数候補があれば最も長い `/n`(最も具体的)を選ぶ。例: `/18` と `/22` が重なる範囲は `/22` が勝つ。デフォルトルート `0.0.0.0/0` は prefix 長 0 = 最後の手段。根拠: GeeksforGeeks longest prefix。
- **2-3 デフォルトルートと「外向き」**: `0.0.0.0/0` のネクストホップが egress を決める。Azure システムルート: VNet CIDR→Virtual network、`0.0.0.0/0`→Internet、RFC1918→None(破棄)。UDR で上書き。AWS: プライベートサブネット=IGW へのルートを持たないサブネット。根拠: Azure UDR overview, AWS subnet-route-tables。
- **2-4 NAT とは**: なぜ要るか(private IP はそのまま外に出られない)。Static NAT(1:1)/Dynamic NAT(プール)/PAT=NAT オーバーロード(1 つの public IP+ポートで多数共有、最も一般的)。SNAT(送信元書き換え)と DNAT(宛先書き換え)。根拠: NetworkAcademy NAT, Alibaba SNAT/DNAT。
- **2-5 クラウド対応づけ**: AWS NAT Gateway(プライベートサブネットの `0.0.0.0/0`→NAT)、IGW、Azure NAT Gateway。Azure NAT Gateway の SNAT ポート(最大 16 IP×64,512 ポート、動的割り当て)。`closed_network` の「③外向き遮断」「NAT 経由でしか S3 に出られない」。根拠: Azure NAT overview。
- **2-6 落とし穴**: SNAT ポート枯渇(多数の外向きコネクション)、`0.0.0.0/0` を消した副作用で必要な経路まで死ぬ、NAT は「内→外」起点が前提で「外→内」は別物(→ファイアウォール/エンドポイントの話)。
- **2-7 まとめ + 次へ**: 経路はできた。誰を通し誰を止めるか → 記事 3(ファイアウォール)。

### 根拠 URL
- https://www.geeksforgeeks.org/computer-networks/longest-prefix-matching-in-routers
- https://www.networkacademy.io/ccna/network-services/network-address-translation-nat
- https://learn.microsoft.com/en-us/azure/nat-gateway/nat-overview
- https://learn.microsoft.com/en-us/azure/virtual-network/virtual-networks-udr-overview
- https://www.alibabacloud.com/blog/alibaba-cloud-nat-gateway-snat-and-dnat-architecture_603165

---

## 記事 3: ファイアウォールとアクセス制御 — ステートフルとは何か
slug: `network_basics_3_firewall`

### 解決する問題
`closed_network` の切り分けで頻出する「SG は許可したのに NACL で弾かれる」を、ステートフル/ステートレスの原理から理解する。SG と NACL の挙動差の根っこ。

### 構成と主張
- **3-1 TCP/UDP とポート**: L4 の役割。ポート番号でアプリを区別(HTTP=80, HTTPS=443, DNS=53)。TCP は 3-way handshake で接続を確立、UDP はコネクションレス。「コネクション」という状態がステートフルの前提。
- **3-2 ステートレス vs ステートフル**: ステートレスは 1 パケットだけ見て往路/復路を独立判定(復路の許可ルールが別に要る)。ステートフルはフロー(5 タプル: src IP/port, dst IP/port, protocol)を記憶し、許可した接続の戻りトラフィックを自動許可。根拠: AWS Network Firewall(stateless/stateful, flow), Azure NSG(stateful)。
- **3-3 クラウド対応づけ — ここが事故の源**: AWS セキュリティグループ=ステートフル(戻り自動許可、許可ルールのみ)。AWS ネットワーク ACL=ステートレス(往復別、許可/拒否、番号順)。Azure NSG=ステートフル、5 タプル評価、優先度は数字が小さいほど高い、既定ルール(AllowVNetInBound 65000 / AllowAzureLoadBalancerInBound 65001 / DenyAllInbound 65500)。根拠: Azure NSG overview, AWS Network Firewall。
- **3-4 多層になる理由**: SG(インスタンス単位)と NACL(サブネット単位)、NSG。多層防御だが、ステートレス層で復路を開け忘れる事故が起きる。`closed_network` の「SG/NSG で許可されているか」「エンドポイント用 ENI の SG 許可漏れ」。
- **3-5 落とし穴**: NACL で ephemeral port(戻り用高位ポート)を開け忘れる、優先度の数字の向きを誤る、SG は拒否ルールを書けない(許可の集合)ことの誤解。
- **3-6 まとめ + 次へ**: 経路と通行可否はできた。でも宛先の「名前」をどう IP に変えるか → 記事 4(DNS)。

### 根拠 URL
- https://learn.microsoft.com/en-us/azure/virtual-network/network-security-groups-overview
- https://docs.aws.amazon.com/network-firewall/latest/developerguide/what-is-aws-network-firewall.html

---

## 記事 4: DNS の仕組み — 名前が引けることとつながることは別
slug: `network_basics_4_dns`

### 解決する問題
`closed_network` で「閉域でつながらない体感的最多原因は DNS」「DNS 解決とアクセス制御は独立」とある。その核心を原理から理解する。シリーズの締め。

### 構成と主張
- **4-1 なぜ名前が要るか**: 人は名前、機械は IP。DNS は分散データベースで名前→IP を引く。
- **4-2 解決フロー**: スタブリゾルバ → 再帰リゾルバ(キャッシュ) → ルート → TLD → 権威サーバ。各役割。根拠: Cloudflare DNS server types。
- **4-3 レコードと CNAME チェーン**: A/AAAA, CNAME(別名)、CNAME が CNAME を指すチェーン、TTL とキャッシュ(短いほど切替速いが負荷増)。根拠: Cloudflare DNS server types, AWS re:Post CNAME。
- **4-4 クラウド/閉域対応づけ**: 公開 DNS 名(`s3...amazonaws.com`, `*.blob.core.windows.net`)を内部 IP に向ける必要。AWS Route53 プライベートホストゾーン、VPC リゾルバ(VPC+2)。Azure Private DNS Zone(`privatelink.*`)。split-horizon DNS(同名で VPC 内/外に別応答)。根拠: AWS hosted-zones-private, hosted-zone-private-considerations。
- **4-5 最重要 — 解決とアクセスは独立**: 公開 `privatelink` ゾーンはハイブリッド移行のためインターネットからも解決可能。名前が引けても `Public network access=Disabled` なら front door で拒否。逆に「経路はあるのにつながらない」=DNS が公開 IP を返している疑い。根拠: Azure private-endpoint-dns。
- **4-6 落とし穴**: プライベート DNS の設定漏れ(経路はあるのに公開 IP を引く)、TTL キャッシュで切替が即時反映されない、hosts ファイルでの暫定対応の罠。
- **4-7 シリーズまとめ**: 5 層(地図/IP/ルーティング・NAT/FW/DNS)が直列でそろって初めて通信が成立。これが `closed_network` の「つながらないときに疑う順番」の土台。閉域記事へ送り出す。

### 根拠 URL
- https://www.cloudflare.com/learning/dns/dns-server-types/
- https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/hosted-zones-private.html
- https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/hosted-zone-private-considerations.html
- https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-dns
- https://repost.aws/knowledge-center/route-53-resolve-cname-record-hosted-zone

---

## 根拠ファイル(temp/network_basics/)
- search_nat_ipaddr.json / search_dns_firewall.json / search_osi_model.json / search_nat_routing.json
- search_aws_routing_sg.json / search_azure_nsg_nat.json / search_dns_cloud.json
- extract_osi.json / extract_ip_cidr.json / extract_nat_routing.json / extract_firewall.json / extract_dns.json / extract_cloud_map.json

## 追加調査の余地(任意)
- 記事 3 の AWS 側「SG=ステートフル / NACL=ステートレス」を AWS VPC 公式(security-groups.html / network-acls.html)で 1 本直接引くと、AWS Network Firewall ドキュメントより SG/NACL に密着した引用にできる。現 plan は既存抽出で骨子は書けるが、publish 前に補強推奨。
- 記事 2 の AWS NAT Gateway 公式(vpc-nat-gateway.html)を 1 本足すと Azure NAT との対比が締まる。

## 公開設定
- 全記事 `published: false` で作成(ユーザー明示指示があるまで true にしない)。
