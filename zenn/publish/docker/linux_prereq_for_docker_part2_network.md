---
title: "Docker内部記事を読むためのLinux前提知識(ネットワーク編) — IP・ルーティング・NAT・iptablesの地図"
emoji: "🌐"
type: "tech"
topics: ["linux", "docker", "networking", "iptables", "beginners"]
published: false
---

## この記事について — 元記事(後編)の「前提」を先に埋める

「[Dockerは使えるが中身は曖昧な人のためのDocker内部(後編)](./docker_internals_part2)」は、コンテナのネットワークを veth → bridge → iptables → NIC と層で剥がして見せてくれます。ただ、その層**そのもの**に下地が要ります。

- `172.17.0.0/16` の `/16` は何を意味するのか
- `iptables -t nat -L DOCKER` の `DNAT`・`MASQUERADE` のルールが読めるか
- なぜ「公開しないと外から繋がらない」のに「コンテナは外に出ていける」のか

この記事は、**後編を読むためだけに必要な Linux ネットワークの下地**を最短で配ります。ネットワーク全般を教える記事ではありません。狙いは、後編のどの一文・どのルール表も「知らない言葉で詰まらない」状態にすることです。

プロセス・ファイル系の下地(プロセス、シグナル、rootfs など)は、前編のコンパニオン「[プロセス・ファイル編](./linux_prereq_for_docker_part1_process)」で配っています。本稿はその続きで、ネットワークだけに集中します。

各セクション末尾に **「→ 元記事のこの記述に効く」** の橋渡しを置きます。対象は Linux(または Docker Desktop 内の Linux VM)上の Docker。IPv6 には深入りしません。

配る下地は次の通りです。

1. NIC・IPアドレス・ポート
2. L2/L3、スイッチ・ブリッジ・ルーター
3. ルーティングとデフォルトゲートウェイ
4. サブネットとCIDR(`/16` の読み方)
5. NAT(DNAT・SNAT・MASQUERADE)
6. iptables/netfilter(テーブル・チェーン・ターゲット)
7. DNSと名前解決

---

## ネットワークの最小単位 — NIC・IPアドレス・ポート

通信の宛先は、**2 段階**で決まります。「どのマシンへ届けるか」と「そのマシンの中のどのアプリへ渡すか」です。前者が IP アドレス、後者がポートです。

- **NIC(Network Interface Card)/ ネットワークインタフェース**: マシンの「通信口」。Linux では名前で見える
  - `eth0` — 実体的な通信口(外と繋がる口)
  - `lo`(ループバック)— 自分自身宛ての特別な口(`127.0.0.1`)。外には出ない
- **IP アドレス**: マシンを指す番号。IPv4 は `172.17.0.2` のような 32bit の値
- **プライベート IP**: 組織内/ホスト内だけで使う、外から直接は届かないアドレス範囲(`10.*` / `172.16〜31.*` / `192.168.*`)。コンテナの IP はここに入る
- **ポート**: 1 つのマシンの中で「どのアプリか」を表す番号(0〜65535)。例: HTTP は 80、HTTPS は 443
- **listen(リッスン)**: アプリが特定ポートで接続を待ち受けている状態。「ポートは開いているのにアプリが listen していない」と当然繋がらない
- **TCP**: 順序保証と再送のある、接続型の通信方式。Web も DB もたいてい TCP

> `172.17.0.2:80` という表記は「IP アドレス `172.17.0.2` のマシンの、ポート `80`」を 1 つにまとめた書き方です。
> 出典: [tcp(7) — man7.org](https://man7.org/linux/man-pages/man7/tcp.7.html) / [ss(8) — man7.org](https://man7.org/linux/man-pages/man8/ss.8.html)

**→ 元記事のこの記述に効く**: 「コンテナの中で `ip addr` を打つと `eth0` と `lo` しか見えない」「`172.17.0.2:80`」「`ss -tlnp` で実際に listen しているか確認」

---

## L2とL3 — スイッチ・ブリッジとルーター

ネットワークは**層**で動きます。後編を読むうえで効くのは、隣接する 2 層の役割分担です。

- **L2(データリンク層)**: 同じ LAN の中で「すぐ隣の機械へ」運ぶ層。住所には **MAC アドレス**(機器固有の番号)を使う。これを捌く装置が **スイッチ**
- **L3(ネットワーク層)**: 別のネットワークへ「中継して」運ぶ層。住所には **IP アドレス**を使う。これを捌く装置が **ルーター**

一言でいうと、**「同じ LAN 内の配達 = L2/スイッチ、LAN をまたぐ配達 = L3/ルーター」**です。

ここで後編の鍵語が分かります。

- **ブリッジ**: ソフトウェアで作った仮想スイッチ。物理スイッチと同じく、**同じブリッジに挿さった機械同士を L2 で直接つなぐ**
- 後編の **`docker0`** は、まさにこの「ホスト上の仮想スイッチ(ブリッジ)」です。同じ `docker0` に挿さったコンテナ同士が直接通信できるのは、L2 で同じスイッチにいるからです

> 出典: [Learn the networking basics every sysadmin needs to know (Red Hat)](https://www.redhat.com/en/blog/sysadmin-essentials-networking-basics) / [Networking — The Linux Kernel documentation](https://docs.kernel.org/networking/index.html)

**→ 元記事のこの記述に効く**: 「`docker0` は Linux のソフトウェアブリッジ(仮想スイッチ)」「同じブリッジに挿さったコンテナ同士は、L2 レベルで直接通信できる」

---

## ルーティングとデフォルトゲートウェイ

「LAN をまたぐ配達は L3」と言いました。では各マシンは、宛先ごとに**どの口から出せばいいか**をどう知るのか。答えは、各マシンが持つ**ルーティングテーブル(経路表)**です。

ルーティングテーブルは「この宛先ネットワークなら、この口(インタフェース)から、必要ならこのゲートウェイ経由で」という地図です。`ip route` で見えます。

```text
default via 172.17.0.1 dev eth0      ← どれにも当てはまらない宛先は全部ここへ
172.17.0.0/16 dev eth0               ← このサブネット宛は eth0 から直接
```

ポイントは **デフォルトゲートウェイ** です。

- ルーティングテーブルに**具体的に載っていない宛先**(例えばインターネット上のサーバ)は、すべて「とりあえずここへ投げる」出口へ送られる。それがデフォルトゲートウェイ(`default` / `0.0.0.0/0` の行)
- コンテナの場合、このデフォルトゲートウェイが `docker0`(のホスト側 IP)になっている。だからコンテナの外向き通信は、まず `docker0` に集まる

> 出典: [Learn the networking basics every sysadmin needs to know (Red Hat)](https://www.redhat.com/en/blog/sysadmin-essentials-networking-basics) / [ip-route(8) — man7.org](https://man7.org/linux/man-pages/man8/ip-route.8.html)

**→ 元記事のこの記述に効く**: 「ルーティング(デフォルトゲートウェイは docker0)」「`nsenter -t $PID --net ip route`」

---

## サブネットとCIDR表記 — `172.17.0.0/16`の読み方

後編に何度も出る `172.17.0.0/16`。この `/16` の意味が分かれば、ルール表が一気に読めます。

IP アドレスは、**「ネットワーク部」と「ホスト部」**に分かれています。`/n`(CIDR 表記)は「**先頭 n ビットがネットワーク部**」という宣言です。

- `172.17.0.0/16` = 先頭 16 ビット(`172.17`)がネットワーク部。残りの 16 ビットが各マシンの番号
- したがって、この範囲は **`172.17.0.0` 〜 `172.17.255.255`**(約 6.5 万個のアドレス)を表す
- 「同じネットワーク部を持つアドレスの集合」を **サブネット**と呼ぶ

つまり後編の「Docker サブネット(`172.17.0.0/16`)発のパケット」は、「`172.17.x.y` という Docker のコンテナ群から出たパケット」という意味になります。Docker がこういうプライベート IP 範囲を使うのは、コンテナに外から直接は届かない内部用アドレスを割り当てるためです。

> 補足: `/16` のように 8 の倍数だと分かりやすいですが、`/24` なら先頭 24bit(= `192.168.1.0/24` は `192.168.1.0〜255` の 256 個)というように、任意のビット境界を表せるのが CIDR の柔軟さです。
> 出典: [ss(8) — man7.org](https://man7.org/linux/man-pages/man8/ss.8.html)(CIDR 記法の説明)/ [Red Hat: networking basics](https://www.redhat.com/en/blog/sysadmin-essentials-networking-basics)

**→ 元記事のこの記述に効く**: 「Docker サブネット(`172.17.0.0/16`)」「`MASQUERADE all !docker0 172.17.0.0/16 0.0.0.0/0`」

---

## NAT — DNAT・SNAT・MASQUERADE

ここが後編の `-p` の正体を理解する核心です。**NAT(Network Address Translation)** とは、通り過ぎるパケットの **IP アドレスやポートを書き換える**仕組みです。

なぜ必要か。コンテナはプライベート IP しか持たないので、そのままでは外から届かないし、外にも出られません。そこで境界で住所を書き換えて辻褄を合わせます。書き換える対象によって名前が変わります。

| 種類 | 何を書き換える | 用途 | 方向 |
|------|----------------|------|------|
| **DNAT** | 宛先(Destination) | 外から来たパケットを内側のコンテナへ向け直す = **ポート公開** | 外 → 内 |
| **SNAT** | 送信元(Source) | 内から出るパケットの送信元を、出口のアドレスに見せかける | 内 → 外 |
| **MASQUERADE** | 送信元(Source) | SNAT の一種。**出口インタフェースの IP を自動で使う** | 内 → 外 |

2 つの方向を押さえてください。

- **受信(外 → コンテナ)= DNAT**: ホストの `:8080` に来たパケットの宛先を、コンテナの `172.17.0.2:80` に書き換える。これが `-p 8080:80` の実体
- **送信(コンテナ → 外)= MASQUERADE**: プライベート IP のコンテナが外に出るとき、送信元をホストの IP に書き換える。だからインターネットに到達できるし、戻りも届く

**SNAT と MASQUERADE の違い**は、書き換える送信元 IP を**固定で指定するか(SNAT)、出口インタフェースの IP を自動で使うか(MASQUERADE)**です。IP が動的に変わりうる環境では MASQUERADE が便利なので、Docker はこちらを使います。

> 出典: [iptables / netfilter notes (GitHub: thekubeworld)](https://github.com/thekubeworld/iptables) / [Using Masquerading with Iptables for NAT (GeeksforGeeks)](https://www.geeksforgeeks.org/linux-unix/using-masquerading-with-iptables-for-network-address-translation-nat)

**→ 元記事のこの記述に効く**: 「`-p` の正体 — DNAT と MASQUERADE」「ホストの `:8080` をコンテナの `IP:80` に DNAT」「送信元 IP をホストの IP に書き換える MASQUERADE」

---

## iptables/netfilter — テーブル・チェーン・ターゲットの読み方

後編のルール表(`Chain DOCKER ...`)を読むには、iptables の文法を知る必要があります。難しく見えますが、**3 段で読む**だけです。

メンタルモデル: Linux カーネルには、パケットが通る道筋の要所に **「関所」(netfilter フック)** があります。`iptables` は、その関所に置くルールを管理するツールです。ルールは「**テーブル(何の目的か)→ チェーン(どの関所か)→ ターゲット(どう処理するか)**」の順に読みます。

### ① テーブル — 何のためのルールか

- **`filter`**: パケットを通すか落とすか(ファイアウォール)
- **`nat`**: アドレス/ポートを書き換える(前セクションの NAT)

後編の DNAT/MASQUERADE ルールは、すべて `nat` テーブル(`iptables -t nat`)にあります。

### ② チェーン — どの関所か

パケットの通り道に応じて、組み込みチェーンが決まっています。

| チェーン | いつ通るか | NAT での役割 |
|----------|------------|--------------|
| **PREROUTING** | 入ってきた直後(経路判断の前) | **DNAT**(宛先書き換え)はここ |
| **INPUT** | 自分(ホスト)宛てと判明した後 | — |
| **FORWARD** | 自分宛てでなく、通過させるとき | 通過パケットの許可/遮断 |
| **OUTPUT** | 自分(ホスト)が送り出すとき | — |
| **POSTROUTING** | 出ていく直前(経路判断の後) | **SNAT / MASQUERADE**(送信元書き換え)はここ |

「DNAT は入口の PREROUTING、MASQUERADE は出口の POSTROUTING」と覚えると、後編のルールがどのチェーンにあるか腑に落ちます。

### ③ ターゲット — マッチしたらどう処理するか

ルールは「条件(マッチ)」と「ターゲット(処理)」の組です。条件に合えばターゲットが実行されます。

- **ACCEPT**: 通す
- **DROP**: 黙って捨てる
- **RETURN**: このチェーンの探索をやめ、呼び出し元へ戻る
- **DNAT / MASQUERADE**: 前セクションの書き換え

### ④ ユーザー定義チェーン

組み込みチェーンに加え、**自分で名前を付けたチェーン**を作って、そこへ処理を飛ばせます。後編の `DOCKER`・`DOCKER-ISOLATION-STAGE-1`・`DOCKER-USER` は、すべて Docker が作ったユーザー定義チェーンです。

### ⑤ ルール 1 行を読んでみる

後編の DNAT ルールを逐語で読むと、文法がそのまま分かります。

```text
DNAT  tcp  !docker0  0.0.0.0/0  0.0.0.0/0  tcp dpt:8080 to:172.17.0.2:80
```

- `DNAT` … ターゲット(宛先を書き換える)
- `tcp` … プロトコルが TCP のものにマッチ
- `!docker0` … 入力インタフェースが docker0 **以外**(外から来た)
- `dpt:8080` … 宛先ポート(destination port)が 8080
- `to:172.17.0.2:80` … 宛先を `172.17.0.2:80` に書き換える

`-p 8080:80` の `8080` が `dpt:8080`、`80` が `to:...:80` に対応していると分かります。

### ⑥ もう一つの前提: `ip_forward`

ホストが「自分宛てでないパケットを通過(FORWARD)させる」には、`ip_forward` という設定が ON でなければなりません(`/proc/sys/net/ipv4/ip_forward` が `1`)。これはホストを**ルーターとして振る舞わせるスイッチ**で、Docker は自動で有効化します。コンテナの通信がホストを通り抜けられる前提条件です。

> なお Docker のファイアウォールバックエンドは既定で **iptables** ですが、後継の **nftables** も選べます。iptables は本稿の「テーブル/チェーン/ターゲット」モデルの代表格で、考え方は nftables にもほぼ引き継がれています。
> 出典: [Man page of IPTABLES (netfilter.org)](https://ipset.netfilter.org/iptables.man.html) / [iptables-extensions(8) — man7.org](https://man7.org/linux/man-pages/man8/iptables-extensions.8.html) / [iptables / netfilter notes (GitHub: thekubeworld)](https://github.com/thekubeworld/iptables)

**→ 元記事のこの記述に効く**: 「nat テーブルの `DOCKER` チェーン」「DNAT/MASQUERADE ルールの読み方」「`DOCKER-ISOLATION` / `DOCKER-USER`」「ファイアウォールバックエンドは iptables / nftables」

---

## DNSと名前解決 — `/etc/resolv.conf`・`/etc/hosts`

最後は名前解決です。後編の「Compose のサービス名 `http://api:3000` で繋がる」を理解する下地になります。

メンタルモデル: 人間は `api` や `example.com` という**名前**で相手を指しますが、通信には **IP アドレス**が要ります。この名前 → IP の変換が **名前解決**です。

Linux はおおむね次の順で解決します。

1. **ローカルの静的対応を見る**: `/etc/hosts` に「名前 → IP」が書いてあればそれを使う
2. **DNS サーバに問い合わせる**: なければ、`/etc/resolv.conf` に書かれた DNS サーバ(`nameserver` 行)へ問い合わせる

押さえる用語:

- **`/etc/hosts`**: 手動で書く静的な「名前 → IP」対応表
- **`/etc/resolv.conf`**: 問い合わせ先の DNS サーバ(`nameserver <IP>`)を書くファイル
- **nsswitch.conf**: 「hosts を先に見るか DNS を先に見るか」など解決順を決める設定
- **`nslookup` / `dig`**: 名前解決を手動で試すコマンド

後編で出てくる Docker の「埋め込み DNS」は、この仕組みの上に乗っています。コンテナの `/etc/resolv.conf` が Docker の内部 DNS を指すように設定され、そこがサービス名 → コンテナ IP を解決します。だから「名前解決がおかしい」ときは、まずコンテナ内の `/etc/resolv.conf` と `nslookup` を見るのが定石になります。

> 出典: [resolv.conf(5) — man7.org](https://man7.org/linux/man-pages/man5/resolv.conf.5.html)

**→ 元記事のこの記述に効く**: 「embedded DNS と Compose のサービス名」「コンテナ内で `/etc/resolv.conf`・`nslookup`・`dig`」「`/etc/hosts` 編集」

---

## 調査の道具箱 — `ip` / `ss` / `tcpdump`

後編のネットワークデバッグは、3 つの道具に集約されます。「どの層を見る道具か」を対応づけておけば、切り分けの型がそのまま使えます。

| ツール | 何を見る | 対応概念 |
|--------|----------|----------|
| `ip addr` | インタフェースと IP アドレス | NIC・IP(本稿§最小単位) |
| `ip route` | ルーティングテーブル | ルーティング(本稿§ルーティング) |
| `ss -tlnp` | listen 中のポートとプロセス | ポート・listen(本稿§最小単位) |
| `tcpdump -i <if>` | 指定インタフェースを通るパケットそのもの | L2/L3 のどこまで届くか(本稿§L2/L3) |

`tcpdump` だけ補足します。これは「指定した通信口(インタフェース)を**実際に通っているパケット**を覗き見る」道具です。後編が「ホスト側 veth に `tcpdump` を仕掛けて、パケットがコンテナまで届いているか確認する」と言うのは、「**この口までパケットが来ているか**」を物理的に確かめる、という意味です。

> 出典: [ss(8) — man7.org](https://man7.org/linux/man-pages/man8/ss.8.html) / [tcpdump(8) — man7.org](https://man7.org/linux/man-pages/man8/tcpdump.8.html)

**→ 元記事のこの記述に効く**: 後編「デバッグ実践」の `nsenter ... ip addr/route/ss`、`tcpdump -i veth/eth0` の各コマンド

---

## まとめ — 層で読むネットワーク

後編を読むための下地を 1 枚に畳むと、パケットの一生はこう流れます。

> **宛先は IP + ポートで決まり → ルーティングで経路(出口)が決まり → 関所(iptables/netfilter)で NAT による書き換えや通過可否の判定を受けて → 外へ出ていく。** 戻りのパケットは逆をたどる。

後編に出てくる veth・`docker0`・`DOCKER` チェーン・埋め込み DNS は、この普遍的な流れの上に **Docker 固有の配線**を足したものにすぎません。だから後編が「症状を見て層を言い当てれば、確認コマンドは自ずと決まる」と言うとき、その「層」とは、本稿で配った IP・ルーティング・NAT・iptables・DNS のことです。

- 本編が下地になる元記事: [Dockerは使えるが中身は曖昧な人のためのDocker内部(後編)](./docker_internals_part2)
- プロセス・ファイル系の下地: [前提知識(プロセス・ファイル編)](./linux_prereq_for_docker_part1_process)
