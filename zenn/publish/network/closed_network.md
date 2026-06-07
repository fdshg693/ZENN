---
title: "「閉域を作る」とは結局何をすることなのか — クラウドの構成・性質・落とし穴"
emoji: "🔒"
type: "tech"
topics: ["aws", "azure", "networking", "cloud", "security"]
published: false
---

## はじめに

「このシステムは閉域で動かしたい」——よくある要件です。VPC やプライベートサブネット、プライベート IP の役割はだいたい分かっている。でもいざ作ってみると、

- プライベートエンドポイントを作ったのに、なぜか公開 URL でも普通にアクセスできてしまう
- 外に出られない設定にしたら、アプリ自体が起動しなくなった
- ネットワーク的には正しいはずなのに「名前解決できません」で止まる

といったところでハマります。

この記事は、**閉域の概念は理解しているが、つながらないときの細かい切り分けまでは自信がない**技術者を対象に、「閉域を作る」とは具体的に何を設定することなのかを整理します。特定のクラウドに依存しない一般論を主軸にしつつ、具体例は AWS と Azure で対比します。

最初に結論を一つ。**閉域は単一のスイッチではありません。** 「閉域モード ON」というボタンはどこにもなく、いくつかの独立した層をそれぞれ設計して、初めて「閉じている」状態になります。逆に言えば、どれか 1 層が抜けていると「閉域のつもり」で穴が空いている、という事故が起きます。

:::message
この記事では、オンプレミスとクラウドを専用線(AWS Direct Connect / Azure ExpressRoute)や VPN でつなぐハイブリッド閉域の設計詳細は扱いません。あくまで「クラウド内で閉じた環境をどう作るか」と、その性質・注意点に絞ります。
:::

## 閉域を構成する 4 つの層

まず全体の地図を示します。「閉域」と言うとき、実際には次の 4 つを別々に考える必要があります。

| 層 | 何を決めるか | AWS の例 | Azure の例 |
|----|------------|---------|-----------|
| ① 境界 | プライベートな IP 空間と区画 | VPC / サブネット | VNet / サブネット |
| ② プライベート接続 | マネージドサービスを自網に引き込む | PrivateLink / VPC エンドポイント | Private Endpoint / Private Link |
| ③ 外向き遮断 | インターネットへ出さない | ルートテーブル / セキュリティグループ / NACL | システムルート / NSG / NAT |
| ④ 名前解決 | 公開 DNS 名を内部 IP へ向ける | Route 53 Private Hosted Zone | Private DNS Zone |

ここで大事なのは、守りたいのが**「入ってくる経路(ingress)」なのか「出ていく経路(egress)」なのか**で、注力する層が変わるということです。

- 「外部からマネージドサービスを叩かれたくない」→ ②プライベート接続 と、後述する「公開エンドポイントを閉じる」が中心
- 「中のサーバーを勝手に外部へ通信させたくない(データ持ち出し対策)」→ ③外向き遮断 が中心

そして、**プライベート IP 空間があるだけでは閉域ではありません。** プライベートサブネットに置いた VM でも、経路と DNS が公開側を向いていれば普通にインターネットへ出ますし、マネージドサービスの公開エンドポイントへもアクセスできます。「プライベート IP = 閉域」という誤解が、最初のつまずきポイントです。

以下、この 4 層を「作り方」「性質」「注意点」の順に往復しながら見ていきます。

## 作り方①:クラウド内サービスへのプライベート接続

最初の山場が「マネージドサービスへのプライベート接続」です。

S3 のようなオブジェクトストレージや、マネージド DB などの PaaS は、**既定では公開エンドポイント(インターネットから到達可能な DNS 名 + 公開 IP)を持ちます。** あなたの VPC/VNet の中にあるように見えても、通信は一度「サービスの公開窓口」を経由するのが既定の姿です。

これを「自分のネットワーク内のプライベート IP」に引き込む仕組みが、AWS の **PrivateLink / VPC エンドポイント**、Azure の **Private Endpoint / Private Link** です。

### AWS:インターフェイスエンドポイントとゲートウェイエンドポイント

AWS には 2 種類あり、性質がかなり違うので最初に押さえておくと混乱しません。

- **インターフェイスエンドポイント(PrivateLink)**: 指定したサブネットに「エンドポイントネットワークインターフェイス(ENI)」が作られ、そこにプライベート IP が割り当てられます。対象サービスへの通信は、この ENI を入口として AWS のネットワーク内に留まり、インターネットゲートウェイも NAT も使いません。多くのサービス(Bedrock、CloudWatch、STS など)がこの方式です。
- **ゲートウェイエンドポイント**: S3 と DynamoDB 専用の特殊な方式で、PrivateLink は使いません。ENI を生やすのではなく、**ルートテーブルにそのサービス宛の経路を追加する**形で動きます。追加料金がかからないのが大きな特徴です。

> Gateway VPC endpoints provide reliable connectivity to Amazon S3 and DynamoDB without requiring an internet gateway or a NAT device for your VPC. ... There is no additional charge for using gateway endpoints.
> （[Gateway endpoints](https://docs.aws.amazon.com/vpc/latest/privatelink/gateway-endpoints.html)）

なお、ゲートウェイエンドポイントが無ければ、プライベートサブネットの VM は NAT 経由でしか S3 に到達できません。NAT を通っても「トラフィックは AWS ネットワークを出ない」ものの、経路としては公開エンドポイント宛になります。ゲートウェイエンドポイントは、これをルーティングだけで閉域化できる点が便利です。

### Azure:Private Endpoint はサービスを VNet に「持ち込む」

Azure の Private Endpoint は、**VNet 内に作られる特別なネットワークインターフェイス**です。VNet のアドレス空間からプライベート IP が 1 つ割り当てられ、そのサービス(Storage、SQL、App Service など)への接続が Private Link を通じて確立されます。

> A private endpoint is a network interface that uses a private IP address from your virtual network. ... By enabling a private endpoint, you're bringing the service into your virtual network.
> （[What is a private endpoint?](https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-overview)）

「サービスを自分の VNet の中に持ち込む」というイメージが Azure 側の理解の鍵です。

### 作り方の共通の流れ

クラウドは違っても、手順の骨格は共通です。

1. 対象サービスに対するエンドポイント(IF/GW エンドポイント、または Private Endpoint)を作る
2. どのサブネットに置くかを指定する(冗長性のため後述のとおり複数 AZ に)
3. アクセス制御を絞る(AWS ならエンドポイントポリシー、Azure ならサブスクリプション/サービス側の制御)

ここまでで「プライベートに到達する経路」はできました。ただし——ここからが最初の大きな落とし穴です。

## 性質①:プライベート接続しても、公開の扉は閉まらない

**プライベートエンドポイントを作っただけでは、そのサービスの公開エンドポイントは塞がれません。**

これは直感に反するので、強調しておきます。Private Endpoint / VPC エンドポイントが行うのは「プライベートな到達経路を**追加**する」ことであって、「既存の公開経路を**閉じる**」ことではありません。

Azure の公式ドキュメントは明言しています。

> Private endpoints provide a privately accessible IP address for the Azure service, but don't necessarily restrict public network access to it.
> （[What is a private endpoint?](https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-overview)）

つまり、閉域化には **2 手** が必要です。

1. プライベート経路を作る(Private Endpoint / VPC エンドポイント)
2. 公開経路を明示的に閉じる

### Azure:`publicNetworkAccess = Disabled`

Azure の多くのサービスには、公開ネットワークアクセスを切るスイッチがあります。たとえば Automation アカウントでは `publicNetworkAccess` を無効化すると、公開エンドポイント経由の接続はすべて 401 で拒否され、Private Endpoint 経由だけが許可されます。

> When the Public Network Access setting is set to `$false`, only connections via private endpoints are allowed and all connections via public endpoints are denied with an unauthorized error message and HTTP status of 401.
> （[Use Azure Private Link with Azure Automation](https://learn.microsoft.com/en-us/azure/automation/how-to/private-link-security)）

Storage アカウントなどでも考え方は同じで、推奨は **「Private Endpoint で経路を作る」+「ファイアウォール/公開アクセスで公開側を閉じる」** の多層防御です。Private Endpoint を作っただけでファイアウォール設定を変えていないと、公開パスは開いたまま残ります。

### AWS:公開エンドポイントの制御は別レイヤー

AWS では「公開エンドポイントを 1 フラグで殺す」よりも、サービスごとの制御を組み合わせます。たとえば S3 なら Block Public Access とバケットポリシー、RDS なら `publicly accessible = false`、といった具合です。

混同しやすいのが **VPC エンドポイントポリシー** です。これは「**誰がそのエンドポイント経由で何を呼べるか**」を決める IAM リソースポリシーであり、既定では全許可です。

> The default VPC endpoint policy allows all actions by all principals on all resources over the VPC endpoint.
> （[AWS PrivateLink concepts](https://docs.aws.amazon.com/vpc/latest/privatelink/concepts.html)）

エンドポイントポリシーは「プライベート経路の通行許可」を絞るもので、「サービスの公開窓口を閉じる」ものではない、という役割の違いを意識してください。

:::message alert
「Private Endpoint を作ったから安心」は危険です。公開エンドポイントを明示的に閉じたか、必ず別途確認してください。閉域化の事故の多くはここです。
:::

## 作り方②:完全エアギャップ(外向き通信の遮断)

次は egress、つまり「中から外へ出さない」設計です。データ持ち出し対策や、コンプライアンス要件でよく出てきます。

ここでの一般原則はシンプルです。**デフォルトルート(`0.0.0.0/0`)が egress の鍵を握る。** そして「全部塞ぐ」と「必要分だけ開ける」は必ずセットになります。塞いだだけだと、後述するように依存サービスごと死にます。

### Azure:システムルートと NSG の既定を理解する

Azure では、サブネットを作ると自動で「システムルート」が引かれます。重要なのは次の 2 種類です。

| 宛先 | ネクストホップ |
|------|--------------|
| `0.0.0.0/0` | Internet |
| `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` ほか | None(=破棄) |

> When a subnet is created, Azure creates a default route to the 0.0.0.0/0 address prefix, with the Internet next hop type. If you don't override this route, Azure routes all traffic destined to IP addresses not included in the address prefix of any other route to the internet.
> （[Azure virtual network traffic routing](https://learn.microsoft.com/en-us/azure/virtual-network/virtual-networks-udr-overview)）

つまり既定では「VNet 内とプライベート空間以外は全部インターネットへ」です。これを閉じるには、ユーザー定義ルート(UDR)で `0.0.0.0/0` をファイアウォールや「None」へ向けるか、NSG のアウトバウンドで拒否します。NSG には既定で `AllowInternetOutBound`(優先度 65001)と `DenyAllOutBound`(優先度 65500)があり、より高い優先度の拒否ルールで上書きする形になります。

なお押さえておくべき**最近の変更点**があります。

> As of March 31, 2026, new virtual networks default to using private subnets. Default outbound access isn't provided by default. Use an explicit form of outbound connectivity instead, like Azure NAT Gateway.
> （[What is Azure NAT Gateway?](https://learn.microsoft.com/en-us/azure/nat-gateway/nat-overview)）

2026 年 3 月 31 日以降に作る新規 VNet は、既定でアウトバウンドの暗黙的なインターネットアクセスが提供されません。外に出したい場合は NAT Gateway などを明示的に付ける必要があります。閉域を作る側にとってはむしろ安全寄りの既定ですが、「以前は出られたのに出られない」という挙動差を生むので注意してください。

### AWS:プライベートサブネットの定義そのもの

AWS では話がもう少しストレートです。**プライベートサブネットとは「インターネットゲートウェイ(IGW)へのルートを持たないサブネット」** のことです。

> Instances in a private subnet can't send traffic to Amazon S3 or DynamoDB, because by definition private subnets do not have routes to an internet gateway.
> （[Gateway endpoints](https://docs.aws.amazon.com/vpc/latest/privatelink/gateway-endpoints.html)）

外に出すには、パブリックサブネットに NAT ゲートウェイを置いて、プライベートサブネットの `0.0.0.0/0` をその NAT へ向けます。逆に言えば、**NAT を置かなければそのサブネットは外へ出られません。** エアギャップを作るなら「NAT を付けない」が出発点で、そのうえで必要な AWS サービスにだけ VPC エンドポイントで穴を開けていきます。

## 作り方③:閉域の中でも、依存サービスは生きているか

ここが、エアギャップで最も事故が多いところです。

**アプリ本体を閉域に置いても、そのアプリが裏で使っている「依存サービス」への経路が無いと動きません。** 外向き通信を塞いだ瞬間にアプリが起動しなくなる、というのはたいていこれです。

象徴的なのが Kubernetes(AWS EKS)のプライベートクラスタです。外向きインターネットアクセスが無い構成では、クラスタが使う各 AWS サービスに対して VPC エンドポイントを用意しなければなりません。

公式が挙げている、よく使われる依存先の例:

- コンテナイメージ取得:ECR(`ecr.api` / `ecr.dkr`)、S3
- ログ:CloudWatch Logs（`logs`）
- 認証:STS（`sts`）
- クラスタ制御:EKS（`eks`）、EKS Auth（`eks-auth`）

特にハマりやすいのが **STS(認証)** です。

> Most AWS v1 SDKs use the global AWS STS endpoint by default (`sts.amazonaws.com`), which doesn't use the AWS STS VPC endpoint. To use the AWS STS VPC endpoint, you might need to configure your SDK to use the regional AWS STS endpoint (`sts.region-code.amazonaws.com`).
> （[Deploy private clusters with limited internet access](https://docs.aws.amazon.com/eks/latest/userguide/private-clusters.html)）

SDK が既定でグローバルエンドポイント `sts.amazonaws.com` を見にいくため、VPC エンドポイントを作っただけでは経路に乗りません。SDK 側をリージョナルエンドポイント `sts.region.amazonaws.com` に切り替える設定が要る——「エンドポイントは作ったのに使われていない」典型例です。

これを一般化すると、閉域化で見落としやすいのは次の 4 系統です。

1. **認証**(トークン発行・ID 連携)
2. **ログ・監視**(ログ送信先、メトリクス)
3. **アーティファクト取得**(コンテナイメージ、パッケージ、OS アップデート)
4. **メタデータ・制御**(コントロールプレーン、構成取得)

Azure 側でも同じ構図です。たとえば Windows VM を private subnet に置くと、Windows Update やライセンス認証(Key Management Service)のような外向き通信が、明示的なアウトバウンド経路なしには成立しません(前掲の NAT Gateway ドキュメントが言及しています)。

:::message
閉域を作るときは「アプリが何に依存しているか」の棚卸しが本体です。ネットワークを塞ぐ作業より、**依存先を列挙して 1 つずつ経路を用意する**作業のほうが時間がかかります。
:::

## 性質②:閉域の名前解決(DNS)— 一番ハマる場所

経路を全部用意しても、まだ通信は始まりません。残るのが **DNS** です。そして経験上、閉域で「つながらない」の体感的に最多の原因がここです。

問題はこうです。アプリは `myaccount.blob.core.windows.net` や `s3.ap-northeast-1.amazonaws.com` のような**公開 DNS 名**でサービスを呼びます。プライベートエンドポイントを作ってプライベート IP を用意しても、その公開名が**依然として公開 IP に解決されてしまう**と、せっかくのプライベート経路は使われません。

そこで、**アプリのコードを変えずに、公開 DNS 名を内部 IP へ向ける**仕組みが要ります。

### AWS:プライベート DNS を有効化すると裏でゾーンが作られる

インターフェイスエンドポイントで「プライベート DNS」を有効にすると、AWS が**隠れた管理用プライベートホストゾーン**を作り、サービスの公開リージョナル DNS 名をエンドポイント ENI のプライベート IP に解決させます。

> If you enable private DNS for your interface VPC endpoint ... we create a hidden, AWS-managed private hosted zone for you. ... if you have existing applications that send requests to the AWS service using a public Regional endpoint, those requests now go through the endpoint network interfaces, without requiring that you make any changes to those applications.
> （[Access AWS services through AWS PrivateLink](https://docs.aws.amazon.com/vpc/latest/privatelink/privatelink-access-aws-services.html)）

アプリ改修不要で公開名がプライベート IP に解決される——これがプライベート DNS の役割です。逆に、これを有効にし忘れると「経路はあるのに公開 IP を引いてしまう」状態になります。

### Azure:Private DNS Zone を VNet にリンクする

Azure では `privatelink.*`(例:`privatelink.blob.core.windows.net`)という Private DNS Zone を作り、VNet にリンクすることで名前解決を上書きします。選択肢としては Private DNS Zone のほか、テスト用の hosts ファイル、複数 VNet/オンプレ混在なら Azure Private Resolver もあります。

### 最重要の性質:DNS 解決とアクセス制御は別物

ここで、閉域の理解で一番ねじれやすいポイントを正面から書きます。**DNS で名前が引けること**と、**そのサービスにアクセスできること**は、まったく独立しています。

> DNS resolution and access control are independent. The CNAME chain in the public `privatelink...` zone is deliberately resolvable from anywhere on the internet so that hybrid and gradual-migration scenarios continue to work without breaking existing clients. A successful public DNS lookup confirms only that a resource with that exact name exists ... When a resource has Public network access set to Disabled ... the service rejects the connection at the front door regardless of DNS resolution. Resource existence is enumerable; resource access is not.
> （[Azure Private Endpoint DNS](https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-dns)）

要点を 2 方向から押さえてください。

- **「名前が引けた = つながる」ではない。** 公開 `privatelink` ゾーンは、ハイブリッド移行のためインターネットからも解決可能です。名前が引けても、公開アクセスを無効化してあればサービス側が接続を拒否します(リソースの**存在**は列挙できても、**アクセス**はできない)。
- 逆に **「経路はあるのにつながらない = DNS が公開 IP を返している」可能性が高い。** プライベート DNS の設定漏れを真っ先に疑うべき、ということです。

## 注意点とデバッグの考え方

最後に、つながらないときの**切り分けの順番**と、設計上の注意点をまとめます。読者の多くは「コマンドを並べられても、どこから疑えばいいか分からない」状態だと思うので、ここでは具体的なコマンドより**疑う順番の地図**を渡します。

### つながらないときに疑う順番

閉域の通信は複数の層が直列でそろって初めて成立します。下から順に潰すのが定石です。

1. **DNS は内部 IP に解決されているか**
   `nslookup` 等で対象の公開名を引き、返ってくるのがプライベート IP か公開 IP か。公開 IP が返るならプライベート DNS の設定漏れ。
2. **経路はあるか**
   ルートテーブル / UDR に、対象宛(またはエンドポイント宛)の経路があるか。`0.0.0.0/0` を塞いだ副作用で必要な経路まで消えていないか。
3. **ファイアウォールで許可されているか**
   AWS なら セキュリティグループ / ネットワーク ACL、Azure なら NSG。エンドポイント用 ENI のセキュリティグループが、呼び出し元サブネットからの通信を許可しているか(EKS の例のように、エンドポイントの SG 許可漏れは頻出です)。
4. **エンドポイント/サービス側ポリシーで許可されているか**
   VPC エンドポイントポリシー、IAM、Azure のサービス側アクセス制御。
5. **公開アクセスを切った結果の「正しい拒否」ではないか**
   前述のとおり、`publicNetworkAccess = Disabled` の状態で公開経路から来た通信は意図どおり拒否されます。これは故障ではありません。

この順で見ると、「DNS は正しい、経路もある、でも SG で弾かれていた」のように、原因が 1 つの層に局在していることが多いと分かります。

### 設計上の注意点

**可用性:複数 AZ に置く。** インターフェイスエンドポイント / Private Endpoint は、置いたサブネット(= AZ)でしか入口が無いものがあります。AWS の例では、単一 AZ にしかエンドポイントを置いていないと、その AZ が障害を起こした際に他 AZ のリソースからそのサービスへ到達できなくなります。

> if Availability Zone 1 is impaired, the resources in Availability Zone 2 lose access to Amazon CloudWatch.
> （[Access AWS services through AWS PrivateLink](https://docs.aws.amazon.com/vpc/latest/privatelink/privatelink-access-aws-services.html)）

本番では「最低 2 つの AZ にエンドポイントを配置し、プライベート DNS 名を有効化する」ことが推奨されています。

**コスト:エンドポイントは無料ではない。** インターフェイスエンドポイントや Azure Private Endpoint は、一般に時間課金 + 処理データ量課金がかかります(対して AWS のゲートウェイエンドポイントは追加料金なし)。「閉域化のためにサービスごとにエンドポイントを大量に作る」と、地味に効いてきます。正確な料金は各クラウドの料金ページで必ず確認してください。

**制約:配置のルール。** Azure の Private Endpoint は VNet と同じリージョン・サブスクリプションに作る必要があり、サブスクリプションあたりの作成数にも上限があります。AWS のエンドポイントにもサービスごとの対応有無があります。設計時に「そのサービスがプライベート接続に対応しているか」を最初に確認するのが安全です。

## まとめ:閉域チェックリスト

「閉域を作る」とは、結局この 5 点を埋める作業です。

- [ ] **4 層がそろっているか**(境界 / プライベート接続 / 外向き遮断 / 名前解決)
- [ ] **公開エンドポイントを明示的に閉じたか**(`publicNetworkAccess` / Block Public Access 等)——プライベート接続を作っただけでは閉じない
- [ ] **依存サービスへの経路を用意したか**(認証・ログ・アーティファクト・メタデータの 4 系統)
- [ ] **DNS が内部 IP に解決されるか**(プライベート DNS / Private DNS Zone)
- [ ] **複数 AZ 冗長とコストを確認したか**

最初に書いたとおり、閉域に「ON ボタン」はありません。プライベート IP を割り当てた時点で安心せず、「入口は塞いだか」「出口は塞いだか」「依存先は生きているか」「名前は内部を向いているか」を、層ごとに確かめていく——それが「閉域を作る」の実態です。

## 参考リンク

- [AWS PrivateLink concepts](https://docs.aws.amazon.com/vpc/latest/privatelink/concepts.html)
- [Access AWS services through AWS PrivateLink](https://docs.aws.amazon.com/vpc/latest/privatelink/privatelink-access-aws-services.html)
- [AWS Gateway endpoints](https://docs.aws.amazon.com/vpc/latest/privatelink/gateway-endpoints.html)
- [Deploy private clusters with limited internet access (Amazon EKS)](https://docs.aws.amazon.com/eks/latest/userguide/private-clusters.html)
- [What is a private endpoint? (Azure)](https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-overview)
- [Azure Private Endpoint private DNS zone values](https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-dns)
- [Integrate Azure services with virtual networks for network isolation](https://learn.microsoft.com/en-us/azure/virtual-network/vnet-integration-for-azure-services)
- [Use Azure Private Link with Azure Automation](https://learn.microsoft.com/en-us/azure/automation/how-to/private-link-security)
- [Azure virtual network traffic routing](https://learn.microsoft.com/en-us/azure/virtual-network/virtual-networks-udr-overview)
- [Azure network security groups overview](https://learn.microsoft.com/en-us/azure/virtual-network/network-security-groups-overview)
- [What is Azure NAT Gateway?](https://learn.microsoft.com/en-us/azure/nat-gateway/nat-overview)
