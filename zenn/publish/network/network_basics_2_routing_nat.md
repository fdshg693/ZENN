---
title: "ルーティングと NAT — パケットはなぜ目的地に着き、なぜプライベート IP で外に出られるのか"
emoji: "🧭"
type: "tech"
topics: ["networking", "tcpip", "aws", "azure", "infrastructure"]
published: false
---

> 「クラウド閉域を理解するためのネットワーク基礎」シリーズの記事 2 です。
> 記事 1 で区画(サブネット/CIDR)を切りました。この記事では、区画から区画へ、そして外の世界へ **パケットがどう運ばれるか(ルーティング)** と、プライベート IP のまま外に出るための **NAT** を、L3 の原理から掘ります。

## この記事が解く疑問

閉域記事には、egress(外向き)の遮断についてこう書かれていました。

> デフォルトルート(`0.0.0.0/0`)が egress の鍵を握る。
> NAT を置かなければそのサブネットは外へ出られない。

この 2 文を「なんとなく」ではなく原理で理解するのが本記事のゴールです。鍵は **ルーティング(どこへ送るか)** と **NAT(送信元/宛先 IP を書き換える)** の 2 つです。

## ルーティングの基本 — ルートテーブルを引く

ルータ(クラウドではサブネットに紐づくルーティング機能)がやっていることは、突き詰めると 1 つです。

> 届いたパケットの **宛先 IP** を見て、**ルートテーブル**を引き、対応する **ネクストホップ**へ転送する。

ルートテーブルは「この宛先レンジへはここへ送れ」という対応表です。例えば:

| 宛先(CIDR) | ネクストホップ |
|--------------|--------------|
| `10.0.0.0/16` | local(自分の VPC 内) |
| `0.0.0.0/0` | インターネットゲートウェイ |

宛先が `10.0.5.20` なら 1 行目に従って VPC 内で配送、`93.184.216.34`(VPC 外)なら 2 行目に従って外へ、という具合です。

このとき、各ホップで **L2 ヘッダ(MAC)は次の機器向けに付け替えられますが、L3 ヘッダの宛先 IP は最終目的地のまま保持されます**(記事 0 のカプセル化を思い出してください)。ルータは「最終的な宛先 IP」を見て「次にどの機器へ渡すか」を繰り返し判断し、バケツリレーで目的地まで運びます。

## 最長プレフィックス一致 — より具体的な経路が勝つ

ルートテーブルに、宛先が **重なる**複数の行があったらどうなるか。

```
宛先 192.24.0.0/18  → ルータ A
宛先 192.24.12.0/22 → ルータ B
```

`192.24.13.5` 宛のパケットは、どちらの行にもマッチします(`/18` の範囲にも `/22` の範囲にも含まれる)。このとき選ばれるのは **より長いプレフィックス、つまり `/22`(ルータ B)** です。これを **最長プレフィックス一致(Longest Prefix Match)** と呼びます([GeeksforGeeks: Longest Prefix Matching](https://www.geeksforgeeks.org/computer-networks/longest-prefix-matching-in-routers))。

なぜ「長いほうが勝つ」のか。記事 1 でやったように、**`/n` が長いほど区画は狭く、より具体的**だからです。「日本宛」と「東京都宛」の指示が両方あれば、東京都宛の荷物は当然「東京都宛」の指示に従うべき——直感どおりです。

そして、この規則の対極にあるのが次の行です。

```
宛先 0.0.0.0/0 → ???
```

`/0` は **プレフィックス長ゼロ = どんな宛先にもマッチするが、最も具体性が低い**経路です。だから「他のどの行にもマッチしなかったとき」だけ選ばれます。これが **デフォルトルート(最後の手段)** です。

## デフォルトルートが「外向き」を決める

ここで閉域記事の「`0.0.0.0/0` が egress の鍵」がつながります。VPC 内宛(`10.0.0.0/16` など)のパケットは local ルートで処理されますが、**それ以外すべて(=インターネット宛を含む)** の行き先は、`0.0.0.0/0` のネクストホップが決めます。

### AWS の場合

AWS では話がストレートです。**プライベートサブネットとは「インターネットゲートウェイ(IGW)への `0.0.0.0/0` ルートを持たないサブネット」** のことです。

- ルートテーブルに `0.0.0.0/0 → IGW` があれば → パブリックサブネット(外に出られる)
- その行が無ければ → プライベートサブネット(外に出られない)

つまり「外に出さない」は、**デフォルトルートを IGW に向けない**ことで実現します。閉域記事が「NAT を置かなければ外へ出られない」と言うのは、この延長です(NAT は後述)。

### Azure の場合

Azure はサブネットを作ると **システムルート**が自動で引かれます。重要なのは次の対応です([Azure: traffic routing](https://learn.microsoft.com/en-us/azure/virtual-network/virtual-networks-udr-overview))。

| 宛先 | ネクストホップ | 意味 |
|------|--------------|------|
| VNet のアドレス空間 | Virtual network | VNet 内配送(AWS の local 相当) |
| `0.0.0.0/0` | Internet | 既定では外へ出る |
| `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` | None | 破棄 |

既定では `0.0.0.0/0 → Internet` なので「黙っていると外に出られる」状態です。これを閉じるには、**ユーザー定義ルート(UDR)** で `0.0.0.0/0` をファイアウォールや `None`(破棄)へ向け直して、システムルートを上書きします。

:::message
RFC 1918 の 3 レンジが既定で `None`(破棄)になっている点に注目してください。これは「VNet に含めていないプライベートレンジ宛のパケットは、勝手にインターネットへ漏らさず捨てる」という安全側の既定です。記事 1 で見た「プライベート IP はインターネットでルーティングされない」が、クラウドのシステムルートにも反映されています。
:::

## NAT — プライベート IP のまま外に出る仕組み

ここで素朴な疑問が湧きます。プライベート IP(`10.0.5.20` など)はインターネットでルーティングされないのに、なぜプライベートサブネットの VM はインターネット上のサーバーと通信できるのか?

答えが **NAT(Network Address Translation)** です。NAT は、パケットが境界を通るときに **IP アドレス(やポート)を書き換える**仕組みです。

### NAT の種類

NAT にはいくつか方式があります([NetworkAcademy.IO: NAT](https://www.networkacademy.io/ccna/network-services/network-address-translation-nat))。

- **Static NAT**: プライベート IP ↔ パブリック IP を **1 対 1 で固定**マッピング。常に外部公開したいサーバーなどに使う。
- **Dynamic NAT**: 複数のプライベート IP に、パブリック IP の **プール**から一時的に 1 対 1 で割り当てる。使い終われば別のホストに再利用される。
- **PAT(Port Address Translation / NAT オーバーロード)**: **1 つのパブリック IP** を、**ポート番号で区別して**多数のホストで共有する。最も一般的な方式で、家庭のルーターもクラウドの NAT Gateway も基本これ。

PAT の動きをイメージで書くと:

```
内部 10.0.5.20:51000 ──┐
内部 10.0.5.21:49000 ──┼─→ 203.0.113.5:(別々のポート) → インターネット
内部 10.0.5.22:52000 ──┘
       (多数のプライベートIPを、1つのパブリックIP+ポートの違いで多重化)
```

戻りパケットは、ポート番号を手がかりに「どの内部ホスト宛か」を判別して逆変換されます。

### SNAT と DNAT

書き換える対象で呼び分けることもあります([Alibaba Cloud: SNAT and DNAT](https://www.alibabacloud.com/blog/alibaba-cloud-nat-gateway-snat-and-dnat-architecture_603165))。

- **SNAT(Source NAT)**: **送信元** IP/ポートを書き換える。**内→外**の通信(プライベートホストがインターネットへ出る)で使う。
- **DNAT(Destination NAT)**: **宛先** IP/ポートを書き換える。**外→内**の通信(公開 IP:443 を内部の VM:8443 へ転送する等)で使う。

閉域で問題になる「外向き(egress)」は、主に **SNAT** の世界です。

## クラウドへの対応づけ

| 汎用概念 | AWS | Azure |
|---------|-----|-------|
| 外向き NAT | NAT Gateway | NAT Gateway |
| 外との境界 | インターネットゲートウェイ(IGW) | (システムルートの Internet) |
| 外向き経路の制御 | ルートテーブル | システムルート + UDR |

AWS の **NAT Gateway** は、まさに「プライベートサブネットの VM が外部サービスへ接続できるが、外部からは接続を開始できない」ための部品です。

> You can use a NAT gateway so that instances in a private subnet can connect to services outside your VPC but external services can't initiate a connection with those instances.
> （[NAT gateways (AWS VPC)](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-gateway.html)）

使い方は「パブリックサブネットに NAT Gateway を置き、プライベートサブネットの `0.0.0.0/0` をその NAT へ向ける」。逆に言えば、**NAT を置かなければプライベートサブネットは外へ出られない**——これが閉域記事の一文の中身です。

Azure の **NAT Gateway** も SNAT を担います。スケールに関わる具体的な数字として、1 つの NAT Gateway は最大 16 個のパブリック IP を持ち、**IP あたり 64,512 個の SNAT ポート**を提供します。さらに **動的ポート割り当て**に対応し、サブネット内の複数インスタンスで SNAT ポートプールを動的に共有するため、一部 VM のポート枯渇リスクを抑えられます([Azure: What is Azure NAT Gateway?](https://learn.microsoft.com/en-us/azure/nat-gateway/nat-overview))。

これらは閉域記事の **「③外向き遮断」** と「NAT 経由でしか S3 に到達できない」の背景そのものです。

## 落とし穴

- **SNAT ポート枯渇**: PAT は「1 つのパブリック IP + ポート」で多重化するため、同時に大量の外向きコネクションを張るとポートを使い切る。バッチで数千の外部 API 呼び出しを並列に投げる、といったワークロードで顕在化する。NAT Gateway の IP を増やす/コネクションを束ねるなどで緩和する。
- **`0.0.0.0/0` を消した副作用**: 「外に出さない」ために UDR で `0.0.0.0/0` を潰すと、**必要な依存先(更新サーバー・認証・ログ)への経路まで一緒に死ぬ**。閉域記事の「外向きを塞いだらアプリが起動しなくなった」の主因。塞ぐのと「必要分だけプライベート経路で開ける」はセット。
- **NAT は内→外が前提**: NAT Gateway は「外から内への接続開始」を通さない。外部に公開したいなら DNAT/ロードバランサ/エンドポイントなど別の仕組みが要る。「NAT があるから外からも来られる」は誤解。

## まとめ

- ルータは **宛先 IP → ルートテーブル → ネクストホップ**でパケットを中継する。
- 候補が重なれば **最長プレフィックス一致**(より具体的な `/n` が勝つ)。`0.0.0.0/0` は最後の手段=**デフォルトルート**で、その向き先が **egress を決める**。
- **NAT** はプライベート IP のまま外に出るための書き換え。**SNAT=内→外**、**DNAT=外→内**。PAT(1 IP をポートで多重化)が最も一般的。
- AWS は「IGW へのルートが無い=プライベートサブネット」、Azure は「システムルートを UDR で上書き」。外向き NAT は両クラウドとも NAT Gateway。

経路はできました。でも、経路があるからといって **何でも通してよいわけではありません**。「誰を通し、誰を止めるか」を決めるのがファイアウォールです。次の記事 3 では、TCP/UDP とポート、そして閉域の切り分けで頻出する **「セキュリティグループは許可したのに NACL で弾かれる」** の正体——ステートフルとステートレスの違いを掘ります。

## 参考リンク

- [Longest Prefix Matching in Routers (GeeksforGeeks)](https://www.geeksforgeeks.org/computer-networks/longest-prefix-matching-in-routers)
- [Network Address Translation (NAT) (NetworkAcademy.IO)](https://www.networkacademy.io/ccna/network-services/network-address-translation-nat)
- [NAT gateways (AWS VPC)](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-gateway.html)
- [What is Azure NAT Gateway?](https://learn.microsoft.com/en-us/azure/nat-gateway/nat-overview)
- [Azure virtual network traffic routing](https://learn.microsoft.com/en-us/azure/virtual-network/virtual-networks-udr-overview)
- [Alibaba Cloud NAT Gateway: SNAT and DNAT Architecture](https://www.alibabacloud.com/blog/alibaba-cloud-nat-gateway-snat-and-dnat-architecture_603165)
