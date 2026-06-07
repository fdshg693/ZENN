---
title: "Dockerは使えるが中身は曖昧な人のためのDocker内部(後編) — ネットワークの本体とデバッグ実践"
emoji: "🐳"
type: "tech"
topics: ["docker", "container", "linux", "networking", "containerd"]
published: false
---

## この記事について — 前編からの接続

[前編](./docker_internals_part1)では「コンテナ = namespace + cgroup + rootfs を runc が組み立て、shim が見守る、ホスト上の 1 プロセス」という地図を引きました。

後編のテーマは、その**隔離されたプロセスがどうやって外の世界と通信するのか**です。コンテナは自分専用の network namespace に閉じ込められているのに、なぜブラウザから繋がり、なぜインターネットに出ていけるのか。そして、繋がらないときにどこを見ればいいのか。

冒頭で答える問いを並べます。

- `-p 8080:80` は実際に何をしているのか
- なぜ別の Compose プロジェクトのコンテナとは通信できないのか
- Compose のサービス名(`http://api:3000`)はなぜ名前解決できるのか
- Mac/Windows の Docker Desktop だと、なぜ挙動が一段ややこしくなるのか
- 繋がらないとき、ホスト側からどう切り分けるのか

ネットワークのトラブルが厄介なのは、**層が多い**からです。コンテナ → veth → bridge → iptables → ホストの NIC、と関所がいくつもある。本編は、この層を 1 つずつ剥がしていきます。対象は前編同様 **Linux 上の Docker / Linux コンテナ**です。

---

## コンテナネットワークの本体 — network namespace + veth + bridge

前編で触れたとおり、コンテナは自分専用の **network namespace** を持ちます。これは「独立した NIC・ルーティングテーブル・ポート空間」を意味します。コンテナの中で `ip addr` を打つと `eth0` と `lo` しか見えないのは、ホストの NIC が namespace の外に隠されているからです。

では、その隔離された namespace はどうやってホストと繋がるのか。鍵は **veth ペア**です。

veth(virtual ethernet)ペアは、**2 つで 1 組の仮想インタフェース**で、片方に入ったパケットがもう片方から出てくる「仮想的な LAN ケーブル」です。Docker はコンテナを作るとき、

- 片端を**コンテナの network namespace に入れて `eth0` にする**
- もう片端を**ホスト側に残し、`docker0` ブリッジに挿す**

`docker0` は Linux のソフトウェアブリッジ(仮想スイッチ)です。同じブリッジに挿さったコンテナ同士は、L2 レベルで直接通信できます。

```text
[コンテナ A]                      [コンテナ B]
  eth0 ─┐                          ┌─ eth0
        │(veth ペア)        (veth ペア)│
        └─ vethXXXX ─┐    ┌─ vethYYYY ─┘
                     │    │
                  [ docker0 bridge ]  ← ホスト上の仮想スイッチ
                          │
                     ホストの NIC
```

実際に、コンテナ内の `eth0` とホスト側の veth が対になっていることを確認できます(前編の `nsenter` を使います)。

```bash
PID=$(docker inspect --format '{{.State.Pid}}' <container-id>)

# コンテナの network namespace 内のインタフェースを見る
sudo nsenter -t $PID --net ip addr
#   eth0 が見える。これが veth ペアの片端
```

> 出典: [Docker Networking Internals: veth pairs, bridges (OneUptime)](https://oneuptime.com/blog/post/2026-02-08-how-to-understand-docker-networking-internals-veth-pairs-bridges/view) / [Docker Networking Demystified (kubesimplify)](https://blog.kubesimplify.com/docker-networking-demystified) / [Bridge network driver — docs.docker.com](https://docs.docker.com/engine/network/drivers/bridge)

---

## `-p` の正体 — DNAT と MASQUERADE

`docker run -p 8080:80 nginx` は魔法ではありません。実体は **iptables(または nftables)の数行のルール**です。これを読めるようになると、「公開したのに繋がらない」が一発で切り分けられます。

ポート公開には方向が 2 つあります。

### 受信側(外 → コンテナ): DNAT

ホストの `:8080` に来たパケットを、コンテナの `IP:80` に書き換えて転送します。nat テーブルの `DOCKER` チェーンに、こういうルールが入ります。

```bash
sudo iptables -t nat -L DOCKER -n -v --line-numbers
```

```text
Chain DOCKER (2 references)
num  target  prot  in       source       destination
1    RETURN  all   docker0  0.0.0.0/0    0.0.0.0/0
2    DNAT    tcp   !docker0 0.0.0.0/0    0.0.0.0/0   tcp dpt:8080 to:172.17.0.2:80
```

2 番目のルールが本体です。「`docker0` 以外から入ってきた、宛先ポート 8080(`dpt:8080`)の TCP を、`172.17.0.2:80` に DNAT(宛先書き換え)する」と読みます。`-p 8080:80` の `8080` が `dpt:8080`、`80` が `to:...:80` に対応しています。

### 送信側(コンテナ → 外): MASQUERADE

逆に、コンテナがインターネットに出ていくときは、送信元 IP をホストの IP に書き換えます。`POSTROUTING` チェーンを見ます。

```bash
sudo iptables -t nat -L POSTROUTING -n -v
```

```text
Chain POSTROUTING (policy ACCEPT)
target      prot  out       source         destination
MASQUERADE  all   !docker0  172.17.0.0/16  0.0.0.0/0
```

「Docker サブネット(`172.17.0.0/16`)発で、`docker0` 以外のインタフェースから出ていくパケットの送信元を、ホストのアドレスに書き換える」。これが、プライベート IP しか持たないコンテナがインターネットに到達できる理由です。

### 確認の型

公開系のトラブルは、この 2 点を機械的に確認すると速いです。

```bash
# DNAT ルールが本当に存在するか
sudo iptables -t nat -L DOCKER -n | grep 8080

# コンテナが実際にそのポートを listen しているか(ルールは合っててもアプリが listen してないと繋がらない)
docker exec <container> ss -tlnp
```

なお Docker のファイアウォールバックエンドはデフォルトで **iptables** ですが、**nftables** も選べます(`firewall-backend` デーモンオプション)。bridge ネットワークでは両者の機能は同等です。

> 出典: [What Actually Happens When You Publish a Container Port (iximiuz)](https://iximiuz.com/en/posts/docker-publish-container-ports) / [Understand Docker iptables Rules (OneUptime)](https://oneuptime.com/blog/post/2026-02-08-how-to-understand-docker-iptables-rules/view) / [Packet filtering and firewalls — docs.docker.com](https://docs.docker.com/engine/network/packet-filtering-firewalls)

---

## ネットワーク隔離とユーザールール — DOCKER-ISOLATION / DOCKER-USER

「別の Compose プロジェクトで立てたコンテナと通信できない」のは、バグではなく**仕様**です。Docker は bridge ネットワークごとに隔離をかけます。

その実体が `DOCKER-ISOLATION-STAGE-1` と `DOCKER-ISOLATION-STAGE-2` という 2 段のチェーンです。これらが、**異なる Docker ネットワーク(別 bridge)間のパケット転送を遮断**します。デフォルトの挙動を整理すると、

- **同じユーザー定義ネットワーク内**のコンテナ同士は、(公開設定なしでも)互いに全ポートへ到達できる
- **別ネットワーク**のコンテナや非 Docker ホストからは、`-p`(公開ポート)経由でしか到達できない

もう 1 つ、知っておくと便利なのが `DOCKER-USER` チェーンです。これは **Docker が自動生成するルールよりも先に評価される、ユーザー用のフック**です。自前のファイアウォール規則を入れたいときはここに書きます。Docker チェーンに直接書くと自動再生成で消えますが、`DOCKER-USER` の内容は Docker に上書きされません。「公開したのに繋がらない」ときは、`DOCKER-USER` に遮断ルールが残っていないかも確認ポイントです。

```bash
sudo iptables -L DOCKER-USER -n -v
```

> 出典: [Understand Docker iptables Rules (OneUptime)](https://oneuptime.com/blog/post/2026-02-08-how-to-understand-docker-iptables-rules/view) / [Packet filtering and firewalls — docs.docker.com](https://docs.docker.com/engine/network/packet-filtering-firewalls)

---

## 名前解決 — embedded DNS と Compose のサービス名

Compose で `http://api:3000` のようにサービス名で繋がるのは、**Docker が各ユーザー定義ネットワークに埋め込み DNS サーバを持っている**からです。ここには重要な落とし穴があります。

`docker compose up` を実行すると、Docker は `<project-name>_default` という名前の bridge ネットワークを作り、全サービスのコンテナをそこに接続します。各サービスは**自分の名前を内部 DNS に登録**するので、コンテナは IP を知らなくても**サービス名で相互に到達**できます。手動の `/etc/hosts` 編集も IP 指定も不要です。

```yaml
services:
  web:
    # web から `http://api:3000` で api コンテナに届く
  api:
```

落とし穴はここです。**この名前解決が効くのはユーザー定義ネットワーク(Compose が作るものを含む)だけ**で、**デフォルト bridge(`docker run` で `--network` を指定しなかった場合)では効きません**。「`docker run` で 2 つコンテナを立てて、名前で繋ごうとしたら解決できなかった」というハマりは、たいていこれです。解決策は、ユーザー定義ネットワークを作る(`docker network create` して `--network` で繋ぐ)か、Compose を使うことです。

`extra_hosts` でカスタムホスト名を足したり、`host-gateway`(Linux ではホスト IP に解決される特別な値)でコンテナからホストのサービスに繋いだりもできます。

> 出典: [Networking in Compose — docs.docker.com](https://docs.docker.com/compose/how-tos/networking) / [Bridge network driver — docs.docker.com](https://docs.docker.com/engine/network/drivers/bridge)

---

## Docker Desktop の差分 — なぜ Mac/Windows は一段ややこしいか

ここまでは「Linux 上の Docker」の話でした。Mac/Windows の **Docker Desktop は、裏で Linux VM を回しています**。Docker のコア機能(namespace / cgroup / iptables)はすべて Linux カーネルの機能なので、Linux 以外では VM の中で動かすしかないからです。

この結果、ホストとコンテナの間に **VM という層が 1 枚増えます**。そのため挙動が Linux ネイティブと変わります。

- **ポート公開**: `docker run -p 80:80 nginx` のとき、ホスト側のプロセス(`com.docker.backend`)がホストの :80 を listen し、接続を VM 内へ転送、VM 内でコンテナの内部 IP(例 `172.17.0.2:80`)へルーティングする
- **外向き通信**: コンテナ → VM 内の `docker0` → VM の仮想アダプタ(例 `192.168.65.x`)経由で NAT されて外に出る
- `host.docker.internal` / `host-gateway` の解決のされ方も Linux と異なる

実務上の含意は、「Linux のブログで見た `iptables` ルールがホスト側にそのまま見えない」「`docker0` がホストの `ip addr` に出てこない」といった現象です。これらは**実体が VM の中にある**ためで、調査するなら VM 内に入る(あるいは `--net host` の特権コンテナを VM のネットワーク namespace で動かす)必要があります。

> 出典: [Docker Desktop networking — docs.docker.com](https://docs.docker.com/desktop/features/networking) / [What Actually Happens When You Publish a Container Port (iximiuz)](https://iximiuz.com/en/posts/docker-publish-container-ports)

---

## デバッグ実践 — ホスト側からネットワークを切り分ける

前編の `nsenter` に、`ip netns` / `tcpdump` / `docker network inspect` を足すと、「どの層で落ちているか」を機械的に切り分けられます。

### コンテナの network namespace を覗く

```bash
PID=$(docker inspect --format '{{.State.Pid}}' <container-id>)

sudo nsenter -t $PID --net ip addr     # NIC と IP
sudo nsenter -t $PID --net ip route    # ルーティング(デフォルトゲートウェイは docker0)
sudo nsenter -t $PID --net ss -tlnp    # 実際に listen しているポート
```

### パケットを直接見る

ホスト側の veth インタフェース(コンテナの `eth0` の対)を特定して、そこに `tcpdump` を仕掛けると、コンテナ境界を通るパケットが見えます。

```bash
# ホスト側 veth で観測(パケットがそもそもコンテナまで届いているか)
sudo tcpdump -i <vethXXXX> -n

# あるいはコンテナの namespace に入って観測
sudo nsenter -t $PID --net tcpdump -i eth0 -n
```

### ネットワーク構成を見る

```bash
docker network inspect <network>
#   サブネット、接続中のコンテナ、各コンテナの IP が分かる
```

### 切り分けの型

繋がらないときは、外から内へ向かって順に潰すのが定石です。

1. **コンテナはそのポートで listen しているか** → `ss -tlnp`(アプリの問題切り分け)
2. **パケットは veth / bridge まで届いているか** → `tcpdump -i veth`
3. **DNAT / FORWARD で落ちていないか** → `iptables -t nat -L DOCKER`、`DOCKER-USER`
4. **名前解決の問題か** → コンテナ内で `/etc/resolv.conf`・`nslookup`・`dig`、ユーザー定義ネットワークか確認

> 出典: [nsenter pod namespaces (OneUptime)](https://oneuptime.com/blog/post/2026-02-09-nsenter-pod-namespaces-host/view) / [Docker Networking Internals (OneUptime)](https://oneuptime.com/blog/post/2026-02-08-how-to-understand-docker-networking-internals-veth-pairs-bridges/view) / [veth masquerade (ServerFault)](https://serverfault.com/questions/1165677/can-i-masquerade-traffic-coming-over-a-veth-pair-without-a-bridge)

---

## 下層ツール — ctr / crictl / docker events

`docker` コマンドで見えない問題——ランタイムレベルの起動失敗やイベント——は、一段下の containerd 向けツールで見えることがあります。

- **`ctr`**: containerd の標準 CLI。コンテナ・イメージ・namespace を直接操作できる。containerd の挙動そのものを調べたいときに使う
- **`crictl`**: CRI(Container Runtime Interface)互換のデバッグ CLI。Kubernetes ノードのように containerd を CRI 経由で使う環境で、コンテナ起動失敗・イメージ pull 問題・ランタイム設定を調べる

```bash
# crictl の例(エンドポイントは /etc/crictl.yaml で指定)
crictl ps -a
crictl inspect <id> | jq '.info.pid'        # PID を取り出して nsenter に渡せる
crictl logs --tail=50 --timestamps <id>
```

`crictl` のエンドポイントは `/etc/crictl.yaml` の `runtime-endpoint: unix:///run/containerd/containerd.sock` などで設定します。

ランタイムのイベントは `docker events` でリアルタイムに追えます。

```bash
docker events --filter event=oom      # OOM(前編の cgroup とクロス)
docker events                          # コンテナの作成・起動・停止・破棄など全イベント
```

:::message
`ctr` / `crictl` は主に **containerd ベースの環境(Kubernetes ノードなど)** 向けのツールです。素の Docker デスクトップ環境では用途が限られます。「Docker の下に containerd がいる」ことを実感する道具として知っておくと、Kubernetes ノードの調査に出くわしたときに役立ちます。
:::

> 出典: [containerd CLI (iximiuz labs)](https://labs.iximiuz.com/courses/containerd-cli) / [crictl debug (OneUptime)](https://oneuptime.com/blog/post/2026-02-09-crictl-debug-container-runtime/view)

---

## 詰まりパターン別デバッグ集

ここまでの知識を「症状 → 仮説 → 確認コマンド」の早見表に畳みます。前編の内容ともクロスさせています。

| 症状 | まず疑う | 確認コマンド |
|------|----------|--------------|
| `-p` したのに繋がらない | DNAT ルール / アプリが listen していない / `DOCKER-USER` のブロック | `iptables -t nat -L DOCKER -n`、`docker exec c ss -tlnp`、`iptables -L DOCKER-USER -n -v` |
| コンテナ間で名前解決できない | デフォルト bridge を使っている(名前解決が効かない) | ユーザー定義ネットワーク or Compose を使う。`docker network inspect` |
| 外(インターネット)に出られない | MASQUERADE / ルーティング / DNS | `iptables -t nat -L POSTROUTING`、`nsenter -t $PID --net ip route`、コンテナ内 `/etc/resolv.conf` |
| 急に落ちる(OOM) | cgroup のメモリ上限 | `memory.events` の `oom_kill`、`docker events --filter event=oom`(→ [前編](./docker_internals_part1)) |
| 制限したのに落ちない | 子プロセスだけ OOM kill されて PID 1 が生存 | `memory.oom.group`(→ [前編](./docker_internals_part1)) |
| 書き込みが消える/イメージが太る | OverlayFS の upper 層・ボリュームの有無 | `docker info` の Storage Driver、`/var/lib/docker/overlay2/<id>/`(→ [前編](./docker_internals_part1)) |
| Mac/Win で iptables が見えない | 実体が Docker Desktop の VM 内 | VM 内に入る / `--net host` 特権コンテナで確認 |

---

## まとめ

連載全体を 1 枚に畳むと、Docker は 3 つの層で理解できます。

1. **プロセス層**(前編): コンテナ = namespace + cgroup + rootfs を被せたホスト上の 1 プロセス
2. **ランタイム層**(前編): dockerd → containerd → shim → runc がそれを組み立てる
3. **ネットワーク層**(後編): network namespace を veth でブリッジに繋ぎ、iptables の DNAT / MASQUERADE で外と橋渡しする

デバッグで詰まるのは、たいてい「どの層を見ているか分からなくなる」ときです。逆に言えば、**症状を見て「これはネットワーク層の DNAT の話だ」「これはプロセス層の cgroup の話だ」と層を言い当てられれば、確認すべきコマンドは自ずと決まります**。

層を 1 枚ずつ剥がす——これが、Docker を「使える」から「中が見える」に変える唯一の近道です。
