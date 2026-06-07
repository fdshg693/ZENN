---
title: "「閉域を作る」とは結局何をすることなのか — クラウドの構成・性質・落とし穴"
status: plan
---

> この記事の plan。構成・各セクションの主張・根拠 URL を記載する。publish と主張を一致させること。

## 対象読者
- 閉域・プライベートネットワークの概念は理解している(VPC/VNet、サブネット、プライベートIP、インターネットゲートウェイの役割が分かる)
- 細かいデバッグ(疎通が取れない原因の切り分け)までは未習熟な技術者
- AWS / Azure いずれかは触ったことがある

## 記事が答える問い
「閉域を作る」とは具体的に何を設定することなのか。なぜ "公開エンドポイントを消すだけ" では閉域にならないのか。閉域特有の性質(特にDNSと依存サービス)と、ハマりやすい落とし穴は何か。

## 比重
作り方・性質・注意点を均等(バランス型)。

## 扱う / 扱わない
- 扱う: クラウド内のプライベート接続、完全エアギャップ/外部通信遮断、閉域内の名前解決(DNS)。インフラ非依存の一般論を主軸に、例で AWS/Azure を対比。
- 扱わない: オンプレ-クラウド間専用線/VPNの設計詳細(到達手段として軽く触れる程度)、GUI手順書、パケットレベルの詳細トラブルシュート(切り分けの考え方までに留める)。

## タグ案
`["aws", "azure", "networking", "cloud", "security"]`

---

## 構成(セクション一覧と主張)

### 0. 導入:なぜ「閉域=公開エンドポイントを消すこと」ではないのか
- **主張**: 閉域は単一スイッチではなく、(1)ネットワーク境界 (2)プライベート接続 (3)外向き遮断 (4)名前解決 の4つの層を別々に設計して初めて成立する。どれか1つ抜けると「閉域のつもり」になる。
- この4層を記事全体の地図として提示する。

### 1. 閉域の構成要素を4層で整理する(性質の総論)
- **主張**: 「閉域」と一口に言っても、守りたいのは「入ってくる経路(ingress)」か「出ていく経路(egress)」かで設計が変わる。プライベートIP空間があるだけでは閉域ではない。
- 4層の対応表(一般概念 / AWS / Azure):
  - 境界 = VPC / VNet + サブネット
  - プライベート接続 = PrivateLink・VPCエンドポイント / Private Endpoint・Private Link
  - 外向き遮断 = ルートテーブル・SG/NACL / システムルート・NSG・NAT
  - 名前解決 = Route 53 Private Hosted Zone / Private DNS Zone
- 根拠: AWS PrivateLink concepts、Azure VNet Integration for network isolation

### 2. 作り方その1:クラウド内サービスへのプライベート接続
- **主張**: マネージドサービス(S3, DBなど)は既定で公開エンドポイント。これを「自VPC/VNet内のプライベートIP」に引き込むのが PrivateLink / Private Endpoint。トラフィックはクラウドのバックボーンに留まりインターネットを経由しない。
- AWS: インターフェイスエンドポイント(PrivateLink、ENIが生える)と ゲートウェイエンドポイント(S3/DynamoDB専用、ルートテーブル方式、追加料金なし)の違い。
- Azure: Private Endpoint は VNet内のNIC。サービスをVNetに「持ち込む」。
- **作り方の要点**: エンドポイントを作る→対象サブネットを指定→(AWSは)エンドポイントポリシーで絞る。
- 根拠: AWS concepts / gateway-endpoints / privatelink-access-aws-services、Azure private-endpoint-overview

### 3. 性質その1:プライベート接続しても公開の扉は閉まらない(最重要の落とし穴)
- **主張**: Private Endpoint / VPCエンドポイントを作っても、サービス側の公開エンドポイントは自動では塞がらない。閉域化には「プライベート経路を作る」と「公開経路を明示的に閉じる」の2手が必要。
- Azure: `publicNetworkAccess = Disabled`(例: Automation, Storage, ML registry)。設定しないと公開IP経由のパスが残る。
- AWS: 公開サービスエンドポイントは別途 IAM/リソースポリシー・SGで制御。VPCエンドポイントポリシーは「誰がそのエンドポイント経由で何を呼べるか」。
- 根拠: Azure private-endpoint-overview(「don't necessarily restrict public network access」)、Automation private-link-security(`publicNetworkAccess`)、Microsoft Q&A(Storage の defense-in-depth)

### 4. 作り方その2:完全エアギャップ(外向き通信の遮断)
- **主張**: 「外に出られない」を作るには、デフォルトのインターネット経路を消し、必要な依存先だけプライベートエンドポイントで開ける。"全部塞ぐ" と "必要分だけ開ける" はセット。
- 一般原則: デフォルトルート(0.0.0.0/0)が egress の鍵。
- Azure: サブネットの既定システムルート(0.0.0.0/0 → Internet、RFC1918 → None)。NSGの既定OutboundにはAllowInternetOutBound と DenyAllOutBound がある。UDRやNSGで遮断。**2026/3/31以降、新規VNetは private subnet 既定でデフォルトのアウトバウンドアクセスが提供されない**(最新の変更点)。
- AWS: プライベートサブネット = IGWへのルートを持たないサブネット。NATを置かなければ外に出られない。
- 根拠: Azure virtual-networks-udr-overview、network-security-groups-overview、nat-overview(2026/3/31の既定変更)、AWS gateway-endpoints(private subnetの定義)

### 5. 作り方その3:閉域の中でも依存サービスは生きているか
- **主張**: アプリ単体を閉域に置いても、そのアプリが使う「裏方サービス」への経路が無いと動かない。エアギャップで最も多い事故。
- 具体例: EKSプライベートクラスタは ECR・S3・CloudWatch Logs・STS・EKS・eks-auth 等への VPCエンドポイントが要る。
- **ハマりどころ**: STSはSDKが既定でグローバルエンドポイント(`sts.amazonaws.com`)を使うため、VPCエンドポイント経由にするにはリージョナルエンドポイント(`sts.region.amazonaws.com`)へSDK設定が必要。
- 一般化: 認証・ログ・アーティファクト取得・メタデータの4系統は閉域化時に見落としやすい。
- 根拠: AWS private-clusters(依存エンドポイント一覧、STSの注意)

### 6. 性質その2:閉域の名前解決(DNS)— 一番ハマる場所
- **主張**: 閉域では「アプリのコードを変えずに公開DNS名を内部IPへ向ける」ためにプライベートDNSが要る。DNSが解決できないと、ネットワークが正しくても通信は始まらない。
- AWS: インターフェイスエンドポイントの private DNS を有効化すると、AWS管理の隠れた private hosted zone が作られ、公開リージョナルDNS名がエンドポイントENIのプライベートIPに解決される。アプリ改修不要。
- Azure: Private DNS Zone(`privatelink.*`)をVNetにリンクして名前解決を上書き。Hosts ファイル(テスト用)や Azure Private Resolver も選択肢。
- **重要な性質**: DNS解決とアクセス制御は独立。公開の `privatelink...` ゾーンはインターネットからも解決可能(ハイブリッド移行のため)。名前が引けても、`Public network access = Disabled` ならサービスは接続を拒否する。「名前の存在」は列挙可能でも「アクセス」はできない。
- 根拠: AWS privatelink-access-aws-services(hidden private hosted zone)、Azure private-endpoint-dns(DNS resolution and access control are independent)

### 7. 注意点とデバッグの考え方(切り分けの順番)
- **主張**: 閉域で「つながらない」とき、闇雲に試すのではなく層の順で切り分ける。読者レベルに合わせ、コマンドの羅列ではなく「どこを疑うか」の地図を渡す。
- 切り分け順: (1)DNSは内部IPに解決されているか →(2)経路はあるか(ルートテーブル/UDR)→(3)SG/NSG/NACLで許可されているか →(4)エンドポイント/サービス側ポリシーで許可されているか →(5)サービス側で公開アクセスを切った結果の拒否ではないか。
- 可用性の注意: VPCエンドポイント/Private Endpointは複数AZ/サブネットに置かないと、AZ障害でそのサービスへ到達不能。
- コストの注意: インターフェイスエンドポイント/Private Endpointは時間課金+処理量課金が一般的(ゲートウェイエンドポイントは無料)。サービスごとに無数に作ると効く。
- 根拠: AWS privatelink-access-aws-services(複数AZ推奨、AZ障害時の挙動)、gateway-endpoints(料金)、Azure private-endpoint-overview(リージョン/サブスク制約・上限)

### 8. まとめ:閉域チェックリスト
- 4層(境界/プライベート接続/外向き遮断/名前解決)が全部埋まっているか。
- 公開エンドポイントを明示的に閉じたか。
- 依存サービス(認証・ログ・アーティファクト・メタデータ)への経路を用意したか。
- DNSが内部IPに解決されるか。
- 複数AZ冗長とコストを確認したか。

---

## 根拠ファイル
- `temp/closed_network/search_aws_overview.json`
- `temp/closed_network/search_azure_overview.json`
- `temp/closed_network/extract_aws_privatelink.json`
- `temp/closed_network/extract_azure_privatelink.json`
- `temp/closed_network/extract_aws_eks_private.json`
- `temp/closed_network/extract_azure_outbound.json`

## 主要根拠 URL
- AWS PrivateLink concepts: https://docs.aws.amazon.com/vpc/latest/privatelink/concepts.html
- AWS Access services through PrivateLink (private DNS): https://docs.aws.amazon.com/vpc/latest/privatelink/privatelink-access-aws-services.html
- AWS Gateway endpoints: https://docs.aws.amazon.com/vpc/latest/privatelink/gateway-endpoints.html
- AWS EKS private clusters: https://docs.aws.amazon.com/eks/latest/userguide/private-clusters.html
- Azure Private Endpoint overview: https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-overview
- Azure Private Endpoint DNS: https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-dns
- Azure VNet integration for network isolation: https://learn.microsoft.com/en-us/azure/virtual-network/vnet-integration-for-azure-services
- Azure Automation Private Link (publicNetworkAccess): https://learn.microsoft.com/en-us/azure/automation/how-to/private-link-security
- Azure UDR / system routes: https://learn.microsoft.com/en-us/azure/virtual-network/virtual-networks-udr-overview
- Azure NSG overview (default rules): https://learn.microsoft.com/en-us/azure/virtual-network/network-security-groups-overview
- Azure NAT Gateway (2026/3/31 private subnet既定): https://learn.microsoft.com/en-us/azure/nat-gateway/nat-overview

## 追加調査の余地(任意)
- AWS側の「公開アクセスを切る」具体例(S3 Block Public Access, RDS publicly accessible=false)を1つ補強するとAzureの`publicNetworkAccess`と対比しやすい。現時点の plan は既存抽出で書ける範囲。
