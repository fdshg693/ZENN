---
title: "ファイアウォールとアクセス制御 — 「ステートフル」とは何か、なぜ SG と NACL で挙動が違うのか"
emoji: "🚦"
type: "tech"
topics: ["networking", "tcpip", "aws", "azure", "infrastructure"]
published: false
---

> 「クラウド閉域を理解するためのネットワーク基礎」シリーズの記事 3 です。
> 記事 2 で「経路(ルーティング)」を引きました。経路があっても、すべてを通してよいわけではありません。この記事は **L4(トランスポート層)** まで降りて、「誰を通し誰を止めるか」を決めるファイアウォールと、閉域の切り分けで最頻出の **「SG は許可したのに NACL で弾かれた」** の正体を掘ります。

## この記事が解く事故

閉域でつながらないとき、切り分けの定番にこの 1 行があります。

> エンドポイント用 ENI のセキュリティグループが、呼び出し元サブネットからの通信を許可しているか。

セキュリティグループ(SG)は許可したのに、ネットワーク ACL(NACL)の戻り側を開け忘れて弾かれる——これは非常によくある事故です。なぜ SG では起きないことが NACL では起きるのか。その根っこにあるのが **ステートフル / ステートレス**という性質の違いです。順を追って掘ります。

## まず L4 — TCP/UDP とポート

ファイアウォールが「IP だけでなくポートで制御できる」のは、L4 の情報を見ているからです(記事 0)。

L4 の主役は 2 つのプロトコルです。

- **TCP**: 通信を始める前に **3 ウェイハンドシェイク**(SYN → SYN/ACK → ACK)で「接続(コネクション)」を確立する。順序保証・再送ありの信頼性重視。HTTP/HTTPS や DB など。
- **UDP**: 接続を確立せず、いきなり送る **コネクションレス**。軽量・高速。DNS クエリや一部の動画/音声など。

そして **ポート番号**が「どのアプリ宛か」を区別します。

| ポート | プロトコル | 用途 |
|--------|-----------|------|
| 80 | TCP | HTTP |
| 443 | TCP | HTTPS |
| 53 | UDP/TCP | DNS |
| 22 | TCP | SSH |
| 3389 | TCP | RDP |

ここで押さえたいのが **「コネクション」という状態(ステート)** の存在です。TCP は「いま誰と誰が、どのポート同士で接続中か」という状態を持ちます。この状態を **ファイアウォールが覚えているかどうか**が、次に説明するステートフル/ステートレスの分かれ目です。

## ステートレス vs ステートフル

通信は必ず **往路と復路**のペアになります。あなたが Web サーバーに `あなた:51000 → サーバー:443` でリクエストを送れば、応答は `サーバー:443 → あなた:51000` で戻ってきます。

ファイアウォールがこの「往路と復路」をどう扱うかで、2 種類に分かれます。

### ステートレス

**1 パケットだけを見て、往路と復路を独立に判定**します。過去に何を通したかを覚えていません。

そのため、**往路を許可しても、復路は別途明示的に許可しないと通りません。**

```
往路 あなた:51000 → サーバー:443    ← 「443 への inbound 許可」ルールが要る
復路 サーバー:443 → あなた:51000    ← 「51000 への戻り許可」ルールも別に要る!
```

この復路用ポート(51000 のような、クライアントが一時的に使う高位ポート)を **エフェメラルポート(ephemeral port)** と呼びます。ステートレスなファイアウォールでは、**エフェメラルポート範囲の戻り許可を開け忘れる**のが定番の事故です。

### ステートフル

**通信のフロー(接続)を記憶**します。フローは典型的には **5 タプル**(送信元 IP、送信元ポート、宛先 IP、宛先ポート、プロトコル)で識別されます。

いったん往路を許可したら、**その応答(復路)は自動的に許可**されます。復路用のルールを書く必要がありません。

```
往路 あなた:51000 → サーバー:443    ← 「443 への許可」だけ書けばよい
復路 サーバー:443 → あなた:51000    ← 自動で許可される(覚えているから)
```

AWS Network Firewall のドキュメントは、この違いを「ステートレスは個々のパケットを単独で検査、ステートフルはトラフィックフローの文脈で検査する」と説明しています([AWS Network Firewall](https://docs.aws.amazon.com/network-firewall/latest/developerguide/what-is-aws-network-firewall.html))。

## クラウドへの対応づけ — ここが事故の源

クラウドの代表的なアクセス制御部品を、この軸で並べると一気に腑に落ちます。

| 部品 | クラウド | 適用単位 | ステート | 拒否ルール |
|------|---------|---------|---------|-----------|
| セキュリティグループ(SG) | AWS | インスタンス(ENI) | **ステートフル** | 書けない(許可のみ) |
| ネットワーク ACL(NACL) | AWS | サブネット | **ステートレス** | 書ける(allow/deny) |
| ネットワークセキュリティグループ(NSG) | Azure | サブネット / NIC | **ステートフル** | 書ける(allow/deny) |

### AWS セキュリティグループ(ステートフル)

AWS の SG は明確にステートフルです。公式の表現が分かりやすい。

> Security groups are stateful. For example, if you send a request from an instance, the response traffic for that request is allowed to reach the instance regardless of the inbound security group rules.
> （[Security groups (AWS VPC)](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-security-groups.html)）

しかも SG は **許可ルールしか書けません**(拒否ルールという概念がなく、「許可の集合」で表現する)。インスタンスから出した通信の戻りは inbound ルールに関係なく通るので、戻りを意識する必要がありません。

### AWS ネットワーク ACL(ステートレス)

対照的に NACL はサブネット単位で、**ステートレス**です。

> NACLs are stateless, which means that information about previously sent or received traffic is not saved. If, for example, you create a NACL rule to allow specific inbound traffic to a subnet, responses to that traffic are not automatically allowed.
> （[Network ACLs (AWS VPC)](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-network-acls.html)）

さらに NACL は番号付きルールを **小さい番号から順に評価し、最初にマッチしたルールで確定**します。ルール番号は 1〜32766 を取り、allow と deny の両方を書けます([Network ACLs](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-network-acls.html))。

> Each rule has a number from 1 to 32766. We evaluate the rules in order, starting with the lowest numbered rule ... If the traffic matches a rule, the rule is applied and we do not evaluate any additional rules.

つまり **「SG(ステートフル)で往路を許可 → 通った。でも NACL(ステートレス)でエフェメラルポートの戻りを許可し忘れ → 復路が弾かれる」** という、SG だけ見ていると気づけない事故が起きます。これが冒頭の「SG は許可したのに弾かれた」の正体です。

### Azure NSG(ステートフル)

Azure の NSG は **ステートフル**で、5 タプルでフローを評価し、許可した接続の戻りトラフィックを自動許可します。ルールは **優先度(数字が小さいほど高い)** で評価され、既定ルールが用意されています([Azure NSG overview](https://learn.microsoft.com/en-us/azure/virtual-network/network-security-groups-overview))。

代表的な既定インバウンドルール:

| 優先度 | 名前 | 動作 |
|--------|------|------|
| 65000 | AllowVNetInBound | VNet 内通信を許可 |
| 65001 | AllowAzureLoadBalancerInBound | Azure LB からの通信を許可 |
| 65500 | DenyAllInbound | その他すべて拒否 |

優先度は数字が小さいほど強いので、カスタムルール(100〜65499)で既定の拒否(65500)を上書きします。閉域記事に出てきた「NSG の既定 Outbound に `AllowInternetOutBound`(65001)と `DenyAllOutBound`(65500)がある」も同じ仕組みです。

## なぜ多層になっているのか

「SG があるのに、なぜ NACL も NSG もあるのか」——多層防御(defense in depth)のためです。

- **SG / NSG(インスタンス〜NIC 単位)**: ワークロードに密着した細かい制御。
- **NACL / NSG(サブネット単位)**: 区画全体に対する粗い網。SG の設定ミスを 1 枚外側で受け止める。

層が増えるほど安全になりますが、**ステートレスな層(NACL)が混じると、復路の許可漏れという事故の口が増えます**。閉域記事の切り分け順「(3)SG/NSG/NACL で許可されているか」で SG だけでなく NACL まで見るべきなのは、この性質差が理由です。

## 落とし穴

- **NACL のエフェメラルポート開け忘れ**: ステートレスゆえに復路用の高位ポート範囲を outbound/inbound で許可し忘れると、往路は通るのに応答が返らない。
- **優先度の数字の向きの誤解**: Azure NSG も AWS NACL も「数字が小さい=先に評価され強い」。大きい番号に書いた許可が、小さい番号の拒否に負ける。
- **SG は拒否を書けないことの誤解**: SG は許可の集合。「特定 IP だけ拒否」は SG では表現できず、NACL(deny ルール)や別の仕組みが要る。
- **SG が見ないトラフィックがある**: AWS の SG は DNS・DHCP・インスタンスメタデータ・Windows ライセンス認証・タイム同期など一部の通信をフィルタしない([Security groups](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-security-groups.html))。「SG で全部止めたつもり」が抜けることがある。

## まとめ

- ファイアウォールは IP(L3)に加え **ポート(L4)** を見る。TCP は接続(状態)を確立、UDP はコネクションレス。
- **ステートレス**=1 パケットを独立判定、復路を別途許可しないと通らない。**ステートフル**=フロー(5 タプル)を記憶し、戻りを自動許可。
- **AWS SG=ステートフル(許可のみ)**、**AWS NACL=ステートレス(番号順 allow/deny)**、**Azure NSG=ステートフル(優先度順)**。
- 「SG は許可したのに弾かれた」は、**ステートレスな NACL で復路を開け忘れた**のが定番の正体。

経路と通行可否が揃いました。残るは最後の関門——アプリは IP ではなく **名前**(`s3.amazonaws.com` のような)でサービスを呼びます。その名前を IP に変えるのが DNS で、閉域で「つながらない」の体感的最多原因がここです。次の記事 4 で、DNS の仕組みと「名前が引けることとつながることは別」という最重要の性質を掘り、シリーズを締めます。

## 参考リンク

- [Security groups (AWS VPC)](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-security-groups.html)
- [Network ACLs (AWS VPC)](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-network-acls.html)
- [What is AWS Network Firewall?](https://docs.aws.amazon.com/network-firewall/latest/developerguide/what-is-aws-network-firewall.html)
- [Azure network security groups overview](https://learn.microsoft.com/en-us/azure/virtual-network/network-security-groups-overview)
