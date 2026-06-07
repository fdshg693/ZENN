---
title: "DNS の仕組み — 「名前が引けること」と「つながること」はまったく別物"
emoji: "🔎"
type: "tech"
topics: ["networking", "tcpip", "aws", "azure", "infrastructure"]
published: false
---

> 「クラウド閉域を理解するためのネットワーク基礎」シリーズの記事 4(最終回)です。
> 記事 1〜3 で IP・ルーティング・ファイアウォールという L3/L4 の土台を作りました。最後は **L7** の DNS です。閉域で「つながらない」の体感的最多原因がここにあり、かつ「名前が引けること」と「アクセスできること」が独立しているという、最もねじれやすい性質を掘ります。

## この記事が解く核心

閉域記事には、太字でこう書かれていました。

> **DNS で名前が引けること**と、**そのサービスにアクセスできること**は、まったく独立しています。

そして「経路はあるのにつながらない=DNS が公開 IP を返している可能性が高い」とも。この 2 つを原理から理解するのが本記事のゴールです。まず「DNS とは何が起きているのか」から始めます。

## なぜ名前が要るのか

人は `s3.ap-northeast-1.amazonaws.com` のような **名前**を覚えますが、ネットワーク(L3)が配送に使うのは **IP アドレス**です(記事 1・2)。この橋渡しをするのが **DNS(Domain Name System)** で、世界中に分散したデータベースから「名前 → IP」を引きます。

重要なのは、**アプリは名前でサービスを呼ぶ**という点です。アプリのコードは `https://myaccount.blob.core.windows.net/...` のように名前で書かれています。だから閉域化では「アプリを改修せずに、この名前を内部 IP に向ける」ことが要になります(後述)。

## 解決フロー — 誰が誰に聞くのか

`www.example.com` を引くとき、裏で起きていることを追います([Cloudflare: DNS server types](https://www.cloudflare.com/learning/dns/dns-server-types/))。

登場人物は 4 種類です。

1. **再帰リゾルバ(Recursive Resolver)**: クライアントの代理で「答えを探し回る」役。ISP やクラウドが提供。キャッシュを持つ。
2. **ルートネームサーバ**: 「`.com` の担当はこっち」と TLD サーバの場所を教える。
3. **TLD ネームサーバ**: `.com` や `.org` 担当。「`example.com` の権威サーバはこっち」と教える。
4. **権威ネームサーバ(Authoritative)**: `example.com` の **本当のレコードを保持**し、最終的な IP を答える。

```
クライアント
   │ www.example.com の IP は?
   ▼
[再帰リゾルバ] ──①──▶ [ルート]      「.com はあっち」
      │      ◀────────
      │      ──②──▶ [TLD .com]   「example.com の権威はあっち」
      │      ◀────────
      │      ──③──▶ [権威]        「A レコードは 93.184.216.34」
      │      ◀────────
      ▼
クライアントに 93.184.216.34 を返す(そしてキャッシュ)
```

再帰リゾルバが「ルート → TLD → 権威」と順にたどって答えを集め、クライアントに返します。クライアント自身は再帰リゾルバに 1 回聞くだけです。

## レコードと CNAME チェーン

権威サーバが持つ「名前→値」の対応が **レコード**です。代表的なもの:

- **A / AAAA レコード**: 名前 → IPv4 / IPv6 アドレス(最終的な答え)。
- **CNAME レコード**: 名前 → **別の名前**(別名・エイリアス)。

CNAME は「この名前は、実はあちらの名前の別名です」と転送します。CNAME が指す先がさらに CNAME だと、リゾルバは **CNAME チェーン**をたどって、最後に A レコードへ行き着くまで解決を続けます([Cloudflare: DNS server types](https://www.cloudflare.com/learning/dns/dns-server-types/))。クラウドのプライベートエンドポイントでは、この CNAME チェーンが鍵になります(後述)。

### TTL とキャッシュ

各レコードには **TTL(Time To Live)** が付いており、再帰リゾルバは TTL の秒数だけ答えをキャッシュします。TTL の間は、同じ名前への問い合わせに **再探索せずキャッシュから即答**します([AWS re:Post: CNAME resolution](https://repost.aws/knowledge-center/route-53-resolve-cname-record-hosted-zone))。

- TTL が長い → 負荷もレイテンシも小さいが、**切り替えの反映が遅い**。
- TTL が短い → 切り替えは速いが、問い合わせが増える。

このキャッシュ挙動が、後述の「設定を直したのに古い IP を引き続ける」落とし穴を生みます。

## クラウド/閉域への対応づけ

ここで閉域の話に接続します。問題はこうでした。

アプリは `myaccount.blob.core.windows.net` や `s3.ap-northeast-1.amazonaws.com` という **公開 DNS 名**でサービスを呼ぶ。プライベートエンドポイントを作って内部 IP を用意しても、その公開名が **依然として公開 IP に解決されてしまう**と、せっかくのプライベート経路(記事 2)は使われません。

そこで、**公開 DNS 名を内部 IP へ向け直す**仕組みが要ります。

### split-horizon DNS — 同じ名前に違う答え

鍵になるのが **split-horizon DNS**(分割ホライズン)です。**同じドメイン名に対して、問い合わせ元によって違う答えを返す**仕組みです。

AWS の **Route 53 プライベートホストゾーン**がこれを実現します。同じ名前について、VPC 内からはプライベートホストゾーンの IP(内部 IP)を、インターネットからはパブリックホストゾーンの IP を返せます([AWS: Working with private hosted zones](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/hosted-zones-private.html))。VPC 内のリゾルバ(VPC+2 のアドレス)が、自動でこのプライベートゾーンを参照します。

Azure では **Private DNS Zone**(`privatelink.blob.core.windows.net` のようなゾーン)を作って VNet にリンクし、名前解決を上書きします。

閉域記事の AWS 側「インターフェイスエンドポイントの private DNS を有効化すると、AWS 管理の隠れた private hosted zone が作られ、公開リージョナル DNS 名がエンドポイント ENI のプライベート IP に解決される」も、まさにこの split-horizon の応用です。**アプリを改修せずに名前の向き先だけを内部へ差し替える**——これが閉域の DNS 設計の本質です。これが閉域記事の **「④名前解決」** にあたります。

## 最重要 — 「解決」と「アクセス」は独立している

ここがシリーズで最もねじれやすく、かつ最も重要なポイントです。閉域記事が引いていた Azure の公式表現を、もう一度正面から見ます。

> DNS resolution and access control are independent. The CNAME chain in the public `privatelink...` zone is deliberately resolvable from anywhere on the internet so that hybrid and gradual-migration scenarios continue to work without breaking existing clients. ... When a resource has Public network access set to Disabled ... the service rejects the connection at the front door regardless of DNS resolution. Resource existence is enumerable; resource access is not.
> （[Azure Private Endpoint DNS](https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-dns)）

要点を 2 方向から押さえます。

### ①「名前が引けた = つながる」ではない

公開の `privatelink...` ゾーンは、ハイブリッド移行のために **インターネットからもわざと解決できるようになっています**。だから「名前が引けた」のは「その名前のリソースが存在する」ことを示すだけで、アクセスできることは保証しません。公開アクセスを無効化(記事の `Public network access = Disabled`)してあれば、**DNS で名前が引けても、サービス側が front door で接続を拒否**します。

DNS(L7 の名前解決)と、サービス側のアクセス制御は、**別々の関門**です。記事 3 で見た「経路があっても通行制御は別」と同じ構図が、DNS とアクセス制御の間にもあります。

### ②「経路はあるのにつながらない = DNS が公開 IP を返している」を疑う

逆向きも重要です。プライベートエンドポイントを作り、経路(記事 2)もファイアウォール(記事 3)も正しいのに通信が始まらない——このとき、**DNS がまだ公開 IP を返している**可能性が高い。プライベート DNS(プライベートホストゾーン / Private DNS Zone)の設定漏れを真っ先に疑うべき、ということです。

この 2 方向が、閉域記事の切り分け順「(1)DNS は内部 IP に解決されているか」を最初に置く理由です。

## 落とし穴

- **プライベート DNS の設定漏れ**: 経路はあるのに公開 IP を引いてしまう。閉域で「つながらない」の体感的最多原因。`nslookup` で返る IP が内部か公開かをまず確認する。
- **TTL キャッシュで切り替えが即時反映されない**: プライベート DNS に直した直後でも、リゾルバやクライアントが TTL の間は古い公開 IP をキャッシュし続ける。TTL ぶん待つか、キャッシュをクリアする。
- **hosts ファイルでの暫定対応の罠**: テスト目的で hosts に直書きすると、その 1 台だけ通って「直った」と錯覚する。恒久対応はプライベート DNS ゾーン側で行う。
- **「名前が引けたから OK」という早合点**: 前述のとおり、解決成功はアクセス可否を意味しない。公開アクセスを切ってあれば、引けてもサービスが拒否する。

## シリーズのまとめ — 5 つの層が直列でそろって初めて通信は成立する

このシリーズで掘ってきた要素を並べると、閉域記事の「つながらないときに疑う順番」がそのまま立ち上がります。

| 記事 | 層 | 問い | つながらない原因の例 |
|------|----|------|-------------------|
| 0 | 全体 | どの層を見ているか | 切り分けの座標系が無い |
| 1 | L3 | IP/区画は正しいか | CIDR 重複、プライベート IP=閉域の誤解 |
| 2 | L3 | 経路はあるか | デフォルトルートを潰して依存先まで遮断 |
| 3 | L4 | 通行は許可されているか | NACL の戻り許可漏れ |
| 4 | L7 | 名前は内部 IP に解決されるか | プライベート DNS の設定漏れ |

通信は、これらの層が **直列でそろって初めて**成立します。どれか 1 層が欠けると「つながらない」。だからこそ、閉域でハマったときは闇雲に試すのではなく、**層の順に下から潰していく**のが定石です。

1. **DNS** は内部 IP に解決されているか(記事 4)
2. **経路**はあるか(記事 2)
3. **ファイアウォール**で許可されているか(記事 3)
4. **エンドポイント/サービス側ポリシー**で許可されているか
5. 公開アクセスを切った結果の **「正しい拒否」** ではないか(記事 4)

これが、閉域記事「『閉域を作る』とは結局何をすることなのか」を読み解くための土台です。本シリーズで原理を固めたうえで、ぜひあの記事の「4 層」「依存サービスの棚卸し」「切り分けの地図」を読み返してみてください。設計と事故の一つひとつが、層のどこで何が起きているのかとして見えてくるはずです。

## 参考リンク

- [DNS server types (Cloudflare Learning Center)](https://www.cloudflare.com/learning/dns/dns-server-types/)
- [Working with private hosted zones (AWS Route 53)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/hosted-zones-private.html)
- [Considerations - private hosted zones (AWS Route 53)](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/hosted-zone-private-considerations.html)
- [Resolve Route 53 CNAME records (AWS re:Post)](https://repost.aws/knowledge-center/route-53-resolve-cname-record-hosted-zone)
- [Azure Private Endpoint DNS](https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-dns)
