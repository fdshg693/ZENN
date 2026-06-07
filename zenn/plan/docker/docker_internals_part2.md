---
title: "Dockerは使えるが中身は曖昧な人のためのDocker内部(後編) — ネットワークの本体とデバッグ実践"
status: plan
---

## 想定読者と前提

- 前編([Docker内部(前編)](./docker_internals_part1))で「コンテナ = namespace + cgroup + rootfs を runc が組み立て shim が見守るプロセス」という地図を共有済み
- 「`-p` を付けたのに繋がらない」「コンテナ間で名前解決できない」「どこでパケットが落ちているか分からない」で詰まる中級者
- 対象は Linux 上(または Docker Desktop 内の Linux VM)。Linux コンテナのみ

前提知識: 前編の namespace / nsenter の話。IP・ポート・NAT の概念名は聞いたことがあるレベル。

## この連載が答える問い(後編担当分)

1. コンテナはなぜ外と通信できるのか(network namespace + veth + docker0 bridge)
2. `-p 8080:80` は実際に何をしているのか(iptables/nftables の DNAT と MASQUERADE)
3. なぜ別ネットワークのコンテナとは通信できないのか(DOCKER-ISOLATION)
4. Compose のサービス名はなぜ名前解決できるのか(embedded DNS)
5. Docker Desktop(Mac/Windows)ではなぜ挙動が一段ややこしいのか
6. 繋がらない/名前解決できない時、ホスト側からどう切り分けるか(ip netns / tcpdump / inspect / ctr / crictl)

## 扱う / 扱わない

- **扱う**: network namespace と veth ペア、docker0 bridge、`-p` の DNAT + POSTROUTING MASQUERADE、DOCKER / DOCKER-USER / DOCKER-ISOLATION-STAGE-1/2 チェーン、embedded DNS と Compose のサービス解決、Docker Desktop の VM 経由構造、デバッグ実践(ip netns / nsenter --net / tcpdump / docker network inspect / ctr / crictl / docker events)
- **扱わない**: overlay / macvlan / ipvlan の詳細(触れる程度)、Swarm、Kubernetes の CNI、IPv6 の詳細

## セクション構成

### 1. この記事について — 前編からの接続

- 主張: 前編で「コンテナはプロセス」と分かった。では、その隔離されたプロセスがどうやって外の世界と話すのか。鍵は network namespace と、それを橋渡しする仕組み
- ネットワークのトラブルは「層が多い」ことが原因。本編はその層を 1 つずつ剥がす

### 2. コンテナネットワークの本体 — network namespace + veth + bridge

- 主張: コンテナは自分専用の network namespace(独立した NIC・ルーティング表・ポート空間)を持ち、ホストとは veth ペアという“仮想 LAN ケーブル”で繋がっている
- veth ペア: 2 つで 1 組の仮想インタフェース。片端がコンテナ内の `eth0`、もう片端がホスト側に出て `docker0` bridge に挿さる
- `docker0` は Linux ソフトウェアブリッジ。同じ bridge 上のコンテナ同士は L2 で直接通信できる
- 確認: `nsenter -t $PID --net ip addr` でコンテナ内 `eth0` を見る → ホスト側の対になる veth を特定
- 根拠: https://oneuptime.com/blog/post/2026-02-08-how-to-understand-docker-networking-internals-veth-pairs-bridges/view / https://blog.kubesimplify.com/docker-networking-demystified / https://docs.docker.com/engine/network/drivers/bridge / extract_veth_dnat.json / extract_docker_networking.json

### 3. `-p` の正体 — DNAT と MASQUERADE

- 主張: `-p 8080:80` は魔法ではなく iptables(または nftables)の数行のルール。これを読めば「公開したのに繋がらない」が一発で切り分けられる
- 受信側(外→コンテナ): nat テーブルの `DOCKER` チェーンに DNAT ルール。実物を提示 → `DNAT tcp -- !docker0 0.0.0.0/0 0.0.0.0/0 tcp dpt:8080 to:172.17.0.2:80`
- 送信側(コンテナ→外): `POSTROUTING` の `MASQUERADE all -- !docker0 172.17.0.0/16` でコンテナの送信元 IP をホスト IP に書き換え。これがコンテナがインターネットに出られる理由
- firewall-backend は iptables がデフォルト、nftables も選べる(bridge では機能同等)
- 確認: `iptables -t nat -L DOCKER -n -v --line-numbers`、`docker exec <c> ss -tlnp` でコンテナが実際に listen しているか
- 根拠: https://iximiuz.com/en/posts/docker-publish-container-ports / https://oneuptime.com/blog/post/2026-02-08-how-to-understand-docker-iptables-rules/view / https://docs.docker.com/engine/network/packet-filtering-firewalls / https://docs.docker.com/engine/network/drivers/bridge / extract_veth_dnat.json

### 4. ネットワーク隔離とユーザールール — DOCKER-ISOLATION / DOCKER-USER

- 主張: 「別の Compose プロジェクトのコンテナと通信できない」のは仕様。`DOCKER-ISOLATION-STAGE-1/2` が別 bridge 間の転送を遮断している
- 同一ユーザー定義ネットワーク内のコンテナは全ポートを互いに公開、別ネットワークへは `-p` 経由のみ、という既定ポリシーを整理
- `DOCKER-USER` チェーン: Docker のルールより先に評価されるユーザー用フック。自前のファイアウォール規則はここに入れる(Docker の自動ルールに上書きされない)
- firewalld 環境では `docker` ゾーンと `docker-forwarding` ポリシーが作られる、という補足
- 根拠: https://oneuptime.com/blog/post/2026-02-08-how-to-understand-docker-iptables-rules/view / https://docs.docker.com/engine/network/packet-filtering-firewalls / https://docs.docker.com/engine/network/drivers/bridge

### 5. 名前解決 — embedded DNS と Compose のサービス名

- 主張: `http://api:3000` のようにサービス名で繋がるのは、Docker が各ユーザー定義ネットワークに埋め込み DNS サーバを持っているから。デフォルト bridge ではこれが効かない、という差が事故のもと
- Compose は `docker compose up` で `<project>_default` という bridge ネットワークを作り、全サービスを接続。各サービスは自身の名前を内部 DNS に登録し、相互にサービス名で到達できる
- `host-gateway`(Linux ではホスト IP に解決)と `extra_hosts` の使い方
- 詰まり: デフォルト bridge(`docker run` 単発で `--network` 未指定)では名前解決が効かず IP 直打ちが必要 → ユーザー定義ネットワーク or Compose を使う
- 根拠: https://docs.docker.com/compose/how-tos/networking / https://docs.docker.com/engine/network/drivers/bridge / extract_docker_networking.json

### 6. Docker Desktop の差分 — なぜ Mac/Windows は一段ややこしいか

- 主張: Mac/Windows の Docker Desktop は裏で Linux VM を回している。だから「ホストのポート」と「コンテナのポート」の間に VM という層が増え、Linux ネイティブと挙動が変わる
- ポート公開の実際: ホスト側プロセス(`com.docker.backend`)がホストの :8080 を listen → VM 内へ転送 → VM 内でコンテナの内部 IP(例 `172.17.0.2:80`)へルーティング
- 外向き通信は VM の仮想アダプタ(例 `192.168.65.x`)経由で NAT
- `host.docker.internal` / `host-gateway` の扱いがプラットフォームで違う点に注意
- 根拠: https://docs.docker.com/desktop/features/networking / https://iximiuz.com/en/posts/docker-publish-container-ports

### 7. デバッグ実践 — ホスト側からネットワークを切り分ける

- 主張: 前編の `nsenter` に加え、`ip netns` / `tcpdump` / `docker network inspect` を使えば「どの層で落ちているか」を機械的に切り分けられる
- コンテナの network namespace に入る: `nsenter -t $PID --net <cmd>`(`ip addr` / `ip route` / `ss -tlnp`)
- パケットを見る: ホスト側 veth を特定して `tcpdump -i <veth> -n`、または namespace 内で `tcpdump`
- ルール/構成を見る: `docker network inspect <net>`(サブネット・接続コンテナ・IP)、`iptables -t nat -L DOCKER`
- 切り分けの型: (1)コンテナ内で listen しているか → (2)veth/bridge まで来ているか → (3)DNAT/FORWARD で落ちていないか → (4)名前解決の問題か、を順に潰す
- 根拠: https://oneuptime.com/blog/post/2026-02-09-nsenter-pod-namespaces-host/view / https://oneuptime.com/blog/post/2026-02-08-how-to-understand-docker-networking-internals-veth-pairs-bridges/view / https://serverfault.com/questions/1165677/can-i-masquerade-traffic-coming-over-a-veth-pair-without-a-bridge / extract_netns_tcpdump.json

### 8. 下層ツール — ctr / crictl / docker events / containerd ログ

- 主張: `docker` コマンドで見えない問題(ランタイムレベルの起動失敗・イベント)は、一段下の containerd 向けツールで見える
- `ctr`: containerd 標準 CLI。コンテナ/イメージ/namespace を直接操作(containerd の挙動学習・低レベル調査向け)
- `crictl`: CRI 互換のデバッグ CLI。`crictl ps -a` / `crictl inspect <id> | jq '.info.pid'` / `crictl logs --tail=50 --timestamps`。エンドポイントは `/etc/crictl.yaml` の `runtime-endpoint: unix:///run/containerd/containerd.sock`
- `docker events`(`--filter event=oom` など)でランタイムイベントをリアルタイム監視
- 注意: `ctr`/`crictl` は主に containerd ベース環境(Kubernetes ノード等)向け。素の Docker では用途が限定される点を明示
- 根拠: https://labs.iximiuz.com/courses/containerd-cli / https://oneuptime.com/blog/post/2026-02-09-crictl-debug-container-runtime/view / https://lippertmarkus.com/2022/01/22/containerd-ctr-windows / extract_debug_tools.json

### 9. 詰まりパターン別デバッグ集

- 主張: ここまでの知識を「症状 → 仮説 → 確認コマンド」の早見表に落とす
- 公開したのに繋がらない → DNAT ルール有無 / コンテナの listen / DOCKER-USER のブロック
- コンテナ間で名前解決できない → デフォルト bridge を使っていないか / ユーザー定義ネット or Compose か
- 外に出られない → MASQUERADE ルール / `ip route` / DNS(`/etc/resolv.conf`)
- 急に落ちる(OOM) → 前編の `memory.events` / `docker events --filter event=oom`(クロス参照)
- 書き込みが消える → 前編の OverlayFS upper 層 / ボリュームの有無(クロス参照)
- 根拠: 上記各セクションの再構成。新規出典なし

### 10. まとめ

- 連載全体の地図を 1 枚に再掲(プロセス層 → ランタイム層 → ネットワーク層)
- 「層を 1 枚ずつ剥がす」というデバッグ姿勢を結語に

## frontmatter 方針(publish 時)

- title 同上 / emoji: 🐳 / type: tech / topics: ["docker","container","linux","networking","containerd"] / published: false
