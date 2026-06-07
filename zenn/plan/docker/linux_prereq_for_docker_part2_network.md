---
title: "Docker内部記事を読むためのLinux前提知識(ネットワーク編) — IP・ルーティング・NAT・iptablesの地図"
status: plan
---

## この plan の位置づけ

- 既存記事 [docker_internals_part2](../../publish/docker/docker_internals_part2.md)(後編)が暗黙に要求するネットワーク前提知識を埋めるコンパニオン記事の構成案
- プロセス/ファイル系の前提は別 plan [linux_prereq_for_docker_part1_process](./linux_prereq_for_docker_part1_process.md) が担当
- スタイル方針(ユーザー承認済み): 各セクション冒頭にメンタルモデル 2〜3 文 → 詳細は箇条書き/表。各セクション末に「→ 元記事のこの記述に効く」橋渡し

## 想定読者と前提

- Docker は使えるが、後編に出てくる `172.17.0.0/16`、`iptables -t nat -L DOCKER`、DNAT/MASQUERADE のルール表を見ると手が止まる
- 「IP アドレス」「ポート」という語は知っているが、ルーティング・NAT・iptables の仕組みは説明できない、というレベルを想定(元記事より一段下)
- 対象は Linux(または Docker Desktop 内の Linux VM)。IPv6 は深入りしない

## この記事が答える問い

1. IP アドレス・NIC・ポート・listen とは何か
2. スイッチ/ブリッジ(L2)とルーター(L3)は何が違うのか
3. ルーティングテーブルとデフォルトゲートウェイはどう読むか
4. `172.17.0.0/16` の `/16` は何を意味するのか(CIDR)
5. NAT とは何か。DNAT/SNAT/MASQUERADE はどう違うのか
6. iptables のテーブル・チェーン・ターゲットをどう読むか
7. 名前解決(DNS / resolv.conf / hosts)はどう動くか

## 扱う / 扱わない

- **扱う**: NIC/インタフェース、IP アドレス(プライベート IP 含む)、ポートと listen、TCP の最小、L2/L3・スイッチ・ブリッジ、ルーティングとデフォルトゲートウェイ、サブネット/CIDR、NAT(DNAT/SNAT/MASQUERADE)、iptables/netfilter(テーブル・チェーン・ターゲット・ユーザー定義チェーン・`ip_forward`)、nftables との関係、DNS と名前解決、調査ツール(`ip` `ss` `tcpdump`)
- **扱わない**: veth / docker0 / DOCKER-ISOLATION / DOCKER-USER / embedded DNS の Docker 固有実装(= 元記事本体なのでリンクで委譲)、ルーティングプロトコル(BGP 等)、IPv6 詳細、L7/ロードバランサ

## セクション構成

### 1. この記事について — 元記事(後編)の「前提」を先に埋める

- 主張: 後編はネットワークを層で剥がす良い記事だが、その層(IP・ルーティング・NAT・iptables)自体に下地が要る。本稿はその下地だけを配る
- 元記事後編へのリンクと、本稿各章がどの記述に効くかを予告
- 根拠: [docker_internals_part2](../../publish/docker/docker_internals_part2.md)

### 2. ネットワークの最小単位 — NIC・IPアドレス・ポート

- メンタルモデル: 通信の宛先は「どのマシンか(IP アドレス)」と「そのマシンの中のどのアプリか(ポート)」の 2 段で決まる。NIC はマシンの通信口
- 箇条書き: NIC/ネットワークインタフェース(`eth0`=実体的な口、`lo`=自分自身宛のループバック)/ IP アドレス(IPv4 の 32bit 表記)/ プライベート IP(`10.*` `172.16-31.*` `192.168.*`、外から直接届かない)/ ポート(0-65535)/ listen=アプリが特定ポートで接続を待つ状態 / TCP=順序保証つきの接続型通信
- → 元記事「コンテナ内で `ip addr` を打つと `eth0` と `lo` しか見えない」「`172.17.0.2:80`」「`ss -tlnp` で listen 確認」に効く
- 根拠: https://man7.org/linux/man-pages/man7/tcp.7.html / https://man7.org/linux/man-pages/man8/ss.8.html / https://www.redhat.com/en/blog/sysadmin-essentials-networking-basics / search_net_basics.json / search_dns_tools.json

### 3. L2とL3 — スイッチ・ブリッジとルーター

- メンタルモデル: ネットワークは層で動く。同じ LAN の中で「隣の機械へ」運ぶのが L2(スイッチ/ブリッジ、MAC アドレスで配る)。別ネットワークへ「中継して」運ぶのが L3(ルーター、IP アドレスで配る)
- 箇条書き: L2(イーサネット/MAC アドレス/スイッチ)/ ブリッジ=ソフトウェアの仮想スイッチ / L3(IP/ルーター)/ 「同じブリッジに挿さった機械同士は直接、別ネットワークへはルーター経由」
- → 元記事「`docker0` は Linux のソフトウェアブリッジ(仮想スイッチ)」「同じブリッジに挿さったコンテナ同士は L2 で直接通信」に効く
- 根拠: https://docs.kernel.org/networking/index.html / https://www.redhat.com/en/blog/sysadmin-essentials-networking-basics / search_net_basics.json

### 4. ルーティングとデフォルトゲートウェイ

- メンタルモデル: 各マシンは「この宛先ならこの口から、あの宛先ならあの口から」という地図(ルーティングテーブル)を持つ。地図に載っていない宛先は全部「とりあえずここへ投げる」出口=デフォルトゲートウェイへ送る
- 箇条書き: ルーティングテーブルの読み方(宛先/ゲートウェイ/インタフェース)/ デフォルトゲートウェイ(`0.0.0.0/0` のルート)/ `ip route` の出力例
- → 元記事「ルーティング(デフォルトゲートウェイは docker0)」「`nsenter -t $PID --net ip route`」に効く
- 根拠: https://www.redhat.com/en/blog/sysadmin-essentials-networking-basics / https://man7.org/linux/man-pages/man8/ip-route.8.html(本格調査で裏取り予定)/ search_net_basics.json

### 5. サブネットとCIDR表記 — `172.17.0.0/16`の読み方

- メンタルモデル: IP アドレスは「ネットワーク部」と「ホスト部」に分かれる。`/16` は「先頭 16bit がネットワーク部」という意味で、同じネットワーク部を持つアドレスの集合=サブネット
- 箇条書き: CIDR 表記(`/n`)/ サブネットマスク / `172.17.0.0/16` が表す範囲(172.17.0.0〜172.17.255.255)/ なぜ Docker は 172.17.0.0/16 のようなプライベート範囲を使うか
- → 元記事「Docker サブネット(`172.17.0.0/16`)」「MASQUERADE all !docker0 172.17.0.0/16」を読むための下地
- 根拠: https://man7.org/linux/man-pages/man8/ss.8.html(CIDR 記法の言及)/ https://www.redhat.com/en/blog/sysadmin-essentials-networking-basics / search_net_basics.json

### 6. NAT — DNAT・SNAT・MASQUERADE

- メンタルモデル: NAT は通り過ぎるパケットの IP/ポートを書き換える仕組み。「外から来た宛先を内側へ向け直す」のが DNAT、「内から出る送信元を自分のアドレスに見せかける」のが SNAT。MASQUERADE は出口 IP を自動で使う SNAT の一種
- 箇条書き: NAT とは / プライベート IP しか持たない機械がなぜ外に出られるか / DNAT=宛先書き換え(ポート公開の正体)/ SNAT/MASQUERADE=送信元書き換え(外向き通信の正体)/ MASQUERADE と SNAT の違い(出口 IP 固定か自動か)
- → 元記事「`-p` の正体 = DNAT と MASQUERADE」「ホストの :8080 を 172.17.0.2:80 に DNAT」「送信元をホスト IP に書き換える MASQUERADE」に直結
- 根拠: https://github.com/thekubeworld/iptables / https://www.geeksforgeeks.org/linux-unix/using-masquerading-with-iptables-for-network-address-translation-nat / search_iptables_nat.json

### 7. iptables/netfilter — テーブル・チェーン・ターゲットの読み方

- メンタルモデル: Linux カーネルにはパケットの通り道に「関所(netfilter フック)」がある。iptables はそこに置くルールの管理ツール。ルールは「テーブル(何の目的か)→ チェーン(どの関所か)→ ターゲット(どう処理するか)」の 3 段で読む
- 箇条書き:
  - テーブル: `filter`(通す/落とす)、`nat`(書き換える)
  - 組み込みチェーン: PREROUTING(入口・ルーティング前)/ INPUT(自分宛)/ FORWARD(通過)/ OUTPUT(自分発)/ POSTROUTING(出口・ルーティング後)。DNAT は PREROUTING、SNAT/MASQUERADE は POSTROUTING
  - ターゲット: ACCEPT(通す)/ DROP(捨てる)/ RETURN(呼び出し元へ戻る)/ DNAT/MASQUERADE(書き換え)
  - ユーザー定義チェーン(Docker の `DOCKER` / `DOCKER-USER` がこれ)
  - `ip_forward`(`/proc/sys/net/ipv4/ip_forward`)= ホストをルーターとして振る舞わせる必須スイッチ
  - ルール 1 行の読み方を、元記事の DNAT ルール例で逐語解説
- nftables との関係: iptables の後継。Docker は既定 iptables、`firewall-backend` で nftables も選べる、と一言
- → 元記事「nat テーブルの `DOCKER` チェーン」「DNAT/MASQUERADE ルールの読み方」「DOCKER-ISOLATION / DOCKER-USER」「iptables vs nftables」に直結
- 根拠: https://ipset.netfilter.org/iptables.man.html / https://ipset.netfilter.org/iptables-extensions.man.html / https://man7.org/linux/man-pages/man8/iptables-extensions.8.html / https://github.com/thekubeworld/iptables / search_iptables_nat.json

### 8. DNSと名前解決 — `/etc/resolv.conf`・`/etc/hosts`

- メンタルモデル: 名前(`api`, `example.com`)を IP に変換するのが名前解決。Linux は「まず `/etc/hosts` などローカル、なければ DNS サーバへ問い合わせ」という順で解決する。問い合わせ先 DNS は `/etc/resolv.conf` に書いてある
- 箇条書き: 名前解決の流れ(hosts → DNS)/ `/etc/hosts`(静的な名前→IP 対応)/ `/etc/resolv.conf`(`nameserver` 行が問い合わせ先 DNS)/ nsswitch.conf が解決順を決める / `nslookup` / `dig` で手動確認
- → 元記事「embedded DNS と Compose のサービス名」「コンテナ内で `/etc/resolv.conf`・`nslookup`・`dig`」「`/etc/hosts` 編集」に効く
- 根拠: https://man7.org/linux/man-pages/man5/resolv.conf.5.html / search_dns_tools.json

### 9. 調査の道具箱 — `ip` / `ss` / `tcpdump`

- メンタルモデル: 元記事のネットワークデバッグは、3 つの道具に集約される。各々が「どの層を見る道具か」を対応づけておけば、切り分けの型がそのまま使える
- 表: ツール | 何を見る | 対応概念
  - `ip addr` / `ip route` … インタフェースと IP / ルーティング(§2,§4)
  - `ss -tlnp` … listen 中のポートとプロセス(§2)
  - `tcpdump -i <if>` … 指定インタフェースを通るパケットそのもの(§3 のどこまで届くか)
- パケットキャプチャの考え方(「どの口を通るパケットが見えるか」)を一言
- → 元記事「デバッグ実践」の `nsenter ... ip addr/route/ss`、`tcpdump -i veth/eth0` の各コマンドが読めるようになる
- 根拠: https://man7.org/linux/man-pages/man8/ss.8.html / https://man7.org/linux/man-pages/man8/tcpdump.8.html(本格調査で裏取り予定)/ search_dns_tools.json

### 10. まとめ — 層で読むネットワーク

- 1 枚に畳む: パケットは「IP+ポートで宛先決定 → ルーティングで経路決定 → NAT で書き換え → iptables の関所を通過」という層を流れる。元記事の veth/bridge/iptables は、この層の上に Docker 固有の配線を足したもの
- リンク: [linux_prereq_for_docker_part1_process](./linux_prereq_for_docker_part1_process.md) / [docker_internals_part2](../../publish/docker/docker_internals_part2.md)

## frontmatter 方針(publish 時)

- title 同上 / emoji: 🌐 / type: tech / topics: ["linux","docker","networking","iptables","beginners"] / published: false
- topics は元記事後編の `linux` `docker` `networking` を再利用し、本稿主題の `iptables` `beginners` を追加
