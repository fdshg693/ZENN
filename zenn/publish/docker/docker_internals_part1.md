---
title: "Dockerは使えるが中身は曖昧な人のためのDocker内部(前編) — コンテナの正体とランタイム構造"
emoji: "🐳"
type: "tech"
topics: ["docker", "container", "linux", "containerd", "lowlevel"]
published: false
---

## この記事について — 「使える」と「中が見える」の間

`docker run` も `docker compose up` も、毎日のように使っている。`Dockerfile` も書けるし、イメージを pull して動かすところまでは何の問題もない。

でも、いざ障害になると手が止まる。

- メモリ制限を付けたのにコンテナが落ちない。逆に、何も変えていないのに突然 OOM Kill された
- `docker stop` がやけに遅い。10 秒くらい待たされてから落ちる
- `-p 8080:80` を付けたのにブラウザから繋がらない
- `docker logs` を見ても何も出ていない。コンテナの「中」を覗きたいのに入り方が分からない

こうした場面で手が止まるのは、スキルが足りないからではありません。**「コンテナとは結局カーネルの何の組み合わせなのか」という地図がない**からです。`docker` コマンドは非常によくできた抽象化で、普段はその下の仕組みを意識せずに済みます。だからこそ、抽象が漏れる障害時に、急に地面が見えなくなる。

この連載は、その地図を引きます。狙うのは「自分でコンテナランタイムを実装できる」ことではなく、**障害時に「いま自分はどの層を見ているのか」を言える**ようになることです。

連載は前後編に分かれます。

- **前編(本稿)**: コンテナの正体(namespace / cgroup / rootfs)と、それを組み立てるランタイム構造(dockerd → containerd → shim → runc)。そして、ホスト側からコンテナの中を覗く第一歩
- **後編**: コンテナがどうやって外と通信するのか(veth / bridge / iptables)と、「繋がらない・覗けない」を潰すネットワークデバッグの実践

対象は **Linux 上の Docker(または Docker Desktop 内の Linux VM で動く Linux コンテナ)** です。Windows コンテナは扱いません。前提知識は、プロセス・ファイルシステム・PID・シグナルといった単語を聞いたことがあるレベルで十分です。

なお、Docker の「上」の層、つまり複数ホストにまたがるオーケストレーションについては、別記事「[Docker は何となく使える人のための Kubernetes 入門](../k8s/k8s_for_docker_users)」で扱っています。本稿はその下の、**コンテナ単体の内部**を見ていきます。

---

## 基礎概念の軽い振り返り — イメージ・コンテナ・レイヤ

深い話に入る前に、土台になる 3 語を一文ずつで固め直します。ここを後続セクションの地図にします。

- **イメージ**は、読み取り専用レイヤを積み重ねたもの。`Dockerfile` の各命令(`RUN`, `COPY` など)が、おおむね 1 枚のレイヤを足していく
- **コンテナ**は、そのイメージの上に**書き込み可能なレイヤを 1 枚だけ載せて動かしたプロセス**
- **レイヤ**は、ファイルシステムの差分。下のレイヤを共有しながら、上に変更だけを重ねる

`docker run myimage` を実行したとき、Docker が作るものを具体的に並べると次の 3 つです。

1. 新しい **namespace** 群(プロセス ID・ネットワーク・ファイルシステムの見え方などを隔離する)
2. 新しい **cgroup**(CPU やメモリの使用量を制限する)
3. **OverlayFS** のマウント(読み取り専用のイメージ層 + 書き込み可能な層を合成する)

コンテナの中に入ると、独立した `/` があり、自分専用の `ps` があり、自分だけの IP を持っているように見えます。**小さな OS のように見える**。しかし実体は、ホストのカーネルの上で動く**ただ 1 つのプロセス**(とその子)にすぎません。仮想マシンのように別のカーネルが動いているわけではない。この一点が、以降のすべての話の出発点です。

> 出典: [Inside Docker: Linux Namespaces, cgroups (DEV)](https://dev.to/ankitdevcode/inside-docker-linux-namespaces-cgroups-3h27)

---

## コンテナの正体 = namespace + cgroup + rootfs

ここで、おそらく一番大事な事実を言い切ります。

> **「コンテナ」という単一のカーネルオブジェクトは存在しない。**

Linux カーネルに `struct container` のようなものはありません。コンテナとは、独立した 3 つの仕組みを組み合わせて作り出した**“見立て”**です。

| 要素 | 担当 | ひとことで |
|------|------|------------|
| **namespace** | 隔離 | このプロセスに**何が見えるか** |
| **cgroup** | 資源制御 | このプロセスが**どれだけ使えるか** |
| **rootfs** | ファイル | ルート(`/`)に**何が入っているか** |

この 3 つを 1 つのプロセスに被せると、そのプロセスは「自分専用の世界」にいると錯覚します。`docker` はこの被せ方を全自動でやってくれる道具、と捉えると見通しがよくなります。

「コンテナ ≒ プロセス」を裏付ける事実がもう 1 つあります。**namespace は、所属するプロセスが 1 つ以上ある限り存続し、0 になるとカーネルが破棄します**。コンテナの中の最後のプロセスが死ねば、その namespace 自体が消える。コンテナの寿命が「中のプロセスの寿命」とほぼ一致するのは、これが理由です。

> 出典: [Linux Namespaces and cgroups as OS Primitives (TURCOMAT, PDF)](https://turcomat.org/index.php/turkbilmat/article/download/15258/10928/29324)

以降、この 3 要素を 1 つずつ掘ります。

---

## namespace — 何を隠しているのか

namespace は「このプロセスに、どの OS リソースを見せるか」を**軸ごとに切り替える**カーネル機能です。「ネットワークだけ隔離する」「PID 空間だけ隔離する」といった部分的な隔離が、軸ごとに独立してできます。

2024 年時点で、namespace は 8 種類あります。`man 7 namespaces` に載っている対応表を、導入されたカーネルバージョンとともに整理します。

| namespace | フラグ | 隠すもの | 導入 |
|-----------|--------|----------|------|
| Mount | `CLONE_NEWNS` | マウントポイント(ファイルシステムの見え方) | 2.4.19 (2002) |
| UTS | `CLONE_NEWUTS` | ホスト名・NIS ドメイン名 | 2.6.19 (2006) |
| IPC | `CLONE_NEWIPC` | System V IPC・POSIX メッセージキュー | 2.6.19 (2006) |
| PID | `CLONE_NEWPID` | プロセス ID 空間 | 2.6.24 (2008) |
| Network | `CLONE_NEWNET` | NIC・ルーティング・ポート | 〜2.6.29 (2009) |
| User | `CLONE_NEWUSER` | UID / GID のマッピング | 3.8 (2013) |
| Cgroup | `CLONE_NEWCGROUP` | cgroup の root ディレクトリ | 4.6 (2016) |
| Time | `CLONE_NEWTIME` | boot / monotonic クロック | 5.6 (2020) |

> 出典: [namespaces(7) — man7.org](https://man7.org/linux/man-pages/man7/namespaces.7.html) / [Linux namespaces (Kerrisk, NDC TechTown 2019, PDF)](https://man7.org/conf/ndctechtown2019/Linux-namespaces-NDC-TechTown-2019-Kerrisk.pdf)

実務で引っかかりやすいものを 4 つ補足します。

**PID namespace** — コンテナの中で `ps` を打つと、PID 1 から始まる独立した番号が見えます。コンテナ内の最初のプロセスは必ず PID 1。これが後述する「PID 1 問題」の伏線になります。ホスト側から見れば同じプロセスは別の(大きい)PID を持っていて、**同じプロセスが 2 つの PID 名前空間で別の番号を持つ**わけです。

**User namespace** — コンテナ内の root(UID 0)を、ホスト側の非特権 UID(例: 100000)にマップできます。これが効いていれば「コンテナ内 root ≠ ホスト root」になり、セキュリティ上強力です。ただし **Docker はデフォルトでは User namespace を有効にしません**。「コンテナの root はホストの root と同じ」が既定だと覚えておくと、権限まわりの事故を避けられます(Podman の rootless モードはこの仕組みに依存します)。

**Cgroup namespace** — これが無いと、コンテナの中から `/sys/fs/cgroup` を読んで**ホストや他コンテナの資源配分(誰がどれだけメモリを持っているか)が丸見え**になります。Cgroup namespace は、コンテナ自身の cgroup パスを `/`(root)に見せることで、これを隠します。

> 出典: [Linux Namespaces (abhik.ai)](https://www.abhik.ai/concepts/linux/namespaces) / [cgroup_namespaces(7)](https://man7.org/linux/man-pages/man7/cgroup_namespaces.7.html)

namespace を操作するシステムコールは、突き詰めると 3 つです。

- `clone()` — 新しい namespace を持った新プロセスを作る
- `unshare()` — 呼び出したプロセス自身を、いまの namespace から分離して新しいものを作る
- `setns()` — すでに存在する namespace に参加する

最後の `setns()` が、後で出てくる `nsenter`(コンテナの中に入るコマンド)の正体です。`docker exec` も内部的にはこの仲間です。

---

## cgroup によるリソース制限と OOM の見え方

冒頭に挙げた「メモリ制限を付けたのに落ちない」「何もしてないのに OOM Kill された」は、**cgroup のメモリゲートと OOM killer の挙動**を知ると説明がつきます。

cgroup には v1 と v2 があり、最近の多くのディストリは **v2** がデフォルトです。違いはざっくり、

- **v1**: コントローラ(cpu / memory / blkio …)ごとに別々の階層を持つ
- **v2**: 単一の統一階層(unified hierarchy)にまとめる

自分の環境がどちらかは、次で確認できます。

```bash
stat -fc %T /sys/fs/cgroup/
# cgroup2fs → v2 / tmpfs → v1
```

> 出典: [Diagnosing Linux cgroups (Netdata)](https://www.netdata.cloud/academy/diagnosing-linux-cgroups) / [Docker container cgroups in depth (OneUptime)](https://oneuptime.com/blog/post/2026-02-08-how-to-understand-docker-container-cgroups-in-depth/view)

### メモリには「3 段のゲート」がある

cgroup v2 のメモリ制御は、単一の上限ではなく 3 段構えです。ここが「落ちる/落ちない」の分かれ目です。

- `memory.low` — ベストエフォートの保護ライン。ここまでは極力回収されない
- `memory.high` — スロットリング閾値。**超えても OOM killer は起動しない**。代わりに強い回収圧力がかかり、プロセスが「遅くなる」
- `memory.max` — ハードリミット。ここに達して回収しきれないと、**その cgroup の中で OOM killer が起動**する

つまり「メモリを食っているのに OOM Kill されず、ただ遅くなる」状態は、`memory.high` でスロットリングされている可能性がある。逆に `memory.max` を超えれば OOM killer が動きます。

> 出典: [Control Group v2 — kernel.org](https://docs.kernel.org/admin-guide/cgroup-v2.html)

### 「制限したのに落ちない」の正体

ここが一番ハマるポイントです。**OOM killer が殺すのは cgroup 全体ではなく、原則として中の 1 プロセス**です。マルチプロセスのコンテナ(たとえば親プロセスが複数のワーカーを抱えている)で、OOM killer が **PID 1 以外の子プロセスを殺した**場合、PID 1 は生き残り、**コンテナは動き続けます**。「メモリ制限したのに、コンテナごと落ちてくれない」のはこれが原因です。

cgroup v2 には、これに対する仕組み `memory.oom.group` があります。`1` を書き込むと、OOM 時に**プロセスグループ全体(=コンテナまるごと)**を終了させられます。これは v2 で追加された機能で、v1 にはありません。

> 出典: [Kill container on child process OOM (iximiuz labs)](https://labs.iximiuz.com/challenges/kill-container-on-child-process-oom-event-docker) / [runtime-spec issue #1005](https://github.com/opencontainers/runtime-spec/issues/1005)

### Docker での設定と確認

メモリ制限は `docker run --memory 500m` のように指定します。コンテナの cgroup は、v2 環境では次のような場所に作られます。

```bash
/sys/fs/cgroup/system.slice/docker-<CONTAINER_ID>.scope/
```

OOM が起きたかどうかは、次のいずれかで確認できます。

```bash
# その cgroup の OOM カウンタを見る
cat /sys/fs/cgroup/system.slice/docker-<ID>.scope/memory.events
#   → oom_kill の値が増えていれば OOM killer が動いた

# リアルタイムに OOM イベントを監視する
docker events --filter event=oom
```

> 出典: [Docker container cgroups in depth (OneUptime)](https://oneuptime.com/blog/post/2026-02-08-how-to-understand-docker-container-cgroups-in-depth/view)

---

## rootfs と OverlayFS — レイヤと copy-on-write

「ビルドのキャッシュが効かない」「コンテナに書いたファイルが再起動で消える」「イメージがやたら肥大化する」——この種の悩みは、**OverlayFS の lower / upper / merged と copy-on-write** を理解すると整理できます。

現在の標準ストレージドライバ `overlay2` は、4 つのディレクトリでコンテナのファイルシステムを作ります。

- `lowerdir` — 読み取り専用のイメージ層(複数可)
- `upperdir` — コンテナの書き込み層(このコンテナの変更だけが入る)
- `merged` — コンテナが実際に見る統一ビュー(これがコンテナの `/`)
- `workdir` — OverlayFS が内部的に使う作業領域

動きの要点は次の通りです。

- **同名ファイルは upper が lower を隠す**。イメージ層とコンテナ層に同じパスのファイルがあれば、コンテナ層(upper)が優先される
- **既存ファイルへの初回書き込みで `copy_up` が起きる**。lower にあるファイルを変更しようとすると、まず upper にファイルを丸ごとコピーしてから書く
- **`copy_up` はファイル単位**。OverlayFS はブロック単位ではなくファイル単位で動くため、巨大なファイルの 1 バイトを書き換えるだけでも**ファイル全体がコピー**される。大きなファイルへの初回書き込みが妙に遅いのはこのため

レイヤ共有の効能も具体的です。200MB のベースイメージを 50 個のコンテナで使っても、ディスクは 10GB にはなりません。lower は共有され、各コンテナは自分の差分(upper)だけを持つからです。

実体は次の場所にあります。

```bash
ls /var/lib/docker/overlay2/<id>/
#   lower  merged  upper  work

docker info | grep "Storage Driver"
#   Storage Driver: overlay2
```

> 出典: [overlay2 storage driver — docs.docker.com](https://docs.docker.com/engine/storage/drivers/overlayfs-driver)

:::message
**変動要素に注意**
古い `overlay` / `aufs` ドライバは Docker v24.0 で削除済みで、いまは `overlay2` が標準です。さらに **Docker Engine 29.0 以降の新規インストールでは、containerd image store(snapshotter)がデフォルト**になり、従来の classic graph driver(overlay2)とは構成が変わります。`/var/lib/docker/overlay2/` の見え方は環境のバージョンと設定に依存するので、自分の環境では `docker info` で実際のドライバを確認してください。
> 出典: [Docker deprecated features](https://docs.docker.com/engine/deprecated) / [containerd image store](https://docs.docker.com/engine/storage/containerd)
:::

ここまでで「コンテナ = namespace + cgroup + rootfs」の 3 要素が揃いました。次は、**この 3 つを誰が組み立てているのか**です。

---

## ランタイム構造 — dockerd → containerd → shim → runc

`docker run` と打ったとき、実際にコンテナを作っているのは `docker` コマンドではありません。複数のプロセスがバトンを渡していきます。この多段構造を知らないと、「ログがどこに出るのか」「なぜ `ps` で `runc` が見えないのか」が永遠に謎のままになります。

流れはこうです。

1. **docker CLI** が、REST API のペイロードを `dockerd` に POST する
2. **dockerd**(Docker デーモン)が受け取り、`containerd` にコンテナ起動を依頼する
3. **containerd** が、Docker イメージから **OCI bundle**(rootfs + `config.json`)を組み立てる
4. containerd が **`containerd-shim-runc-v2`**(shim)を起動し、shim 経由で **runc** を呼ぶ
5. **runc** がカーネルと対話して namespace / cgroup を設定し、コンテナのプロセスを起動する
6. **runc は、コンテナを起動し終えると終了する**
7. **shim** が、残されたコンテナプロセスの親になって見守り続ける

> 出典: [Docker Engine Architecture Under the Hood (Medium)](https://medium.com/@yeldos/docker-engine-architecture-under-the-hood-741512b340d5) / [containerd runtime-v2 docs](https://github.com/containerd/containerd/blob/main/docs/runtime-v2.md)

### なぜ shim が必要なのか

「runc が起動して終わるなら、間に shim を挟まず containerd が直接コンテナの親になればいいのでは?」と思うはずです。shim が存在する理由は 3 つあります。

1. **runc を即終了させて、長命なランタイムプロセスを残さない**。コンテナ 1 個につき重い runc を常駐させずに済む(daemonless containers)
2. **dockerd や containerd が死んでも、コンテナを生かし続ける**。shim がコンテナの STDIO や file descriptor を保持しているので、上位デーモンを再起動してもコンテナのパイプ/TTY が閉じない。もし shim が無ければ、親側のパイプが閉じてコンテナが落ちてしまう
3. **コンテナの終了コードを上位ツールに報告する**。shim は実際の親プロセスとして `wait` し、終了ステータスを containerd / dockerd に伝える

> 出典: [Docker components explained (Holbreich)](https://alexander.holbreich.org/docker-components-explained) / [Use of containerd-shim (docker-dev)](https://groups.google.com/g/docker-dev/c/zaZFlvIx1_k)

### プロセスツリーを実際に見る

この構造は `ps fxa` で目で見えます。

```text
dockerd
 └─ containerd
     └─ containerd-shim-runc-v2
         └─ <コンテナの実プロセス、例: nginx や sleep 30>
```

ここで重要なのは、**runc がツリーに現れない**ことです。runc はコンテナを組み立て終えた瞬間に終了しているので、コンテナが動いている間に `ps aux | grep runc` しても何も出ません。「runc が見当たらないのは異常では?」と一瞬焦りますが、これが正常な姿です。

> 出典: [Docker Engine Architecture Under the Hood (Medium)](https://medium.com/@yeldos/docker-engine-architecture-under-the-hood-741512b340d5)

### 手で再現してみると腑に落ちる

OCI bundle は「rootfs + config.json」だけです。Docker なしでも、runc 単体でコンテナを起動できます。

```bash
# 1. busybox の rootfs を取り出す
mkdir -p ~/mycontainer/rootfs && cd ~/mycontainer
docker export $(docker create busybox) | tar -C rootfs -xf -

# 2. 雛形の config.json を生成する
runc spec

# 3. 起動する
runc run mycontainerid
```

これだけでコンテナが立ち上がります。`docker` という分厚い抽象を剥がすと、最下層は「rootfs を用意して runc に渡すだけ」だと体感できます。

> 出典: [Docker Engine Architecture Under the Hood (Medium)](https://medium.com/@yeldos/docker-engine-architecture-under-the-hood-741512b340d5)

---

## 前編のデバッグ実践 — プロセスツリー・nsenter・PID 1

ここまでの地図があれば、ホスト側からコンテナの中を直接覗けます。これがデバッグの第一歩です。

### コンテナの中に入る(docker exec が使えないときも)

まずコンテナのホスト側 PID を取ります。

```bash
PID=$(docker inspect --format '{{.State.Pid}}' <container-id>)
```

この PID のプロセスが入っている namespace に `nsenter` で入り込めます。

```bash
# 全 namespace に入る(コンテナにシェルが無くてもホストの sh で入れる)
sudo nsenter -t $PID -a /bin/sh

# ネットワーク namespace だけに入る(後編で多用)
sudo nsenter -t $PID -n ip addr
```

`docker exec` はコンテナ内にそのバイナリ(`sh` など)が必要ですが、`nsenter` は**ホスト側のバイナリ**を持ち込んで対象 namespace で実行できます。だから「シェルすら入っていない極小イメージ」のデバッグでも使えます。これが `setns()` の威力です。

`nsenter` / `unshare` の namespace 別フラグも押さえておくと便利です。

| フラグ | namespace |
|--------|-----------|
| `-C` | cgroup |
| `-i` | IPC |
| `-m` | mount |
| `-n` | network |
| `-p` | PID |
| `-u` | UTS |
| `-U` | user |

> 出典: [nsenter pod namespaces (OneUptime)](https://oneuptime.com/blog/post/2026-02-09-nsenter-pod-namespaces-host/view) / [Linux namespaces (Kerrisk, PDF)](https://man7.org/conf/ndctechtown2019/Linux-namespaces-NDC-TechTown-2019-Kerrisk.pdf)

### PID 1 問題 — `docker stop` が遅い・ゾンビが溜まる

冒頭の「`docker stop` がやけに遅い」に答えます。原因は **PID 1 のシグナルの特別扱い**です。

Linux カーネルは PID 1 を他のプロセスと別扱いします。具体的には、**PID 1 にはシグナルハンドラを明示的に登録しない限り、`SIGTERM` のようなシグナルがデフォルト動作で配送されません**。多くのアプリはハンドラを登録していないので、`docker stop` が送る `SIGTERM` を**PID 1 のアプリが黙って無視**します。Docker は反応がないので待ち、タイムアウト後に `SIGKILL` で強制終了する。これが「10 秒待たされてから落ちる」の正体です。

もう 1 つ、PID 1 には**死んだ子プロセスを `waitpid()` で刈り取る(reap する)責務**があります。アプリが PID 1 として動いていてこれをやらないと、子プロセスが**ゾンビ**として溜まります。ゾンビが 1 個なら無害ですが、増えるとカーネルの PID 上限を食いつぶし、それ以上プロセスを作れなくなります。

解決策はシンプルで、**ちゃんとした init を PID 1 に置く**ことです。

```bash
# Docker 同梱の Tini を PID 1 として注入する(Dockerfile の変更不要)
docker run --init myimage
```

`--init` を付けると、Docker が同梱する **Tini** が PID 1 になります。Tini がやるのは 2 つだけ——**シグナルをアプリに正しく転送する**ことと、**ゾンビを刈り取る**こと。`docker run --init` は Docker 1.12(2016 年)以降で使え、明示オプションなのでデフォルトでは適用されません。Dockerfile 側で `ENTRYPOINT ["/sbin/tini", "--"]` として組み込む手もあります。

> 出典: [Containers and signal handling: PID 1 (Bertovic)](https://www.denibertovic.com/posts/containers-and-signal-handling-why-you-need-to-care-about-pid-1) / [docker --init zombies (StackOverflow)](https://stackoverflow.com/questions/49162358/docker-init-zombies-why-does-it-matter)

---

## 前編まとめと後編予告

前編の地図を 1 枚に畳むと、こうなります。

> **コンテナとは、namespace(見える範囲)・cgroup(使える量)・rootfs(ファイルの中身)の 3 つを runc が組み立て、shim が見守る、ホスト上の 1 プロセスである。**

この一文に、本稿で出てきたデバッグの勘所が全部ぶら下がっています。

- 落ちない/急に落ちる → cgroup(`memory.events`、`memory.oom.group`)
- 書き込みが消える/イメージが太る → rootfs(OverlayFS の upper 層と `copy_up`)
- runc が `ps` で見えない → ランタイム構造(runc は起動後に終了し shim が親)
- `docker stop` が遅い・ゾンビが溜まる → PID 1 問題(`--init`)
- コンテナの中を覗きたい → `nsenter -t $PID`

後編では、この「1 プロセス」がどうやって外の世界と通信するのかを見ます。`-p 8080:80` を付けたのに繋がらない、コンテナ間で名前解決できない——こうしたネットワークの詰まりを、veth・bridge・iptables の層に分解して 1 枚ずつ剥がしていきます。
