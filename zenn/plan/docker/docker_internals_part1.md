---
title: "Dockerは使えるが中身は曖昧な人のためのDocker内部(前編) — コンテナの正体とランタイム構造"
status: plan
---

## 想定読者と前提

- `docker run` / `docker compose up` は日常的に使えるが、コンテナの中で実際に何が起きているかは説明できない
- 「コンテナはただのプロセス」と聞いたことはあるが、namespace / cgroup / runc が頭の中でつながっていない
- 障害時に `docker logs` と再起動以上の手が出ず、ホスト側からコンテナを覗く調査に踏み込めず詰まる
- 対象は Linux 上(または Docker Desktop 内の Linux VM)の Docker / Linux コンテナ。Windows コンテナは扱わない

前提知識: プロセス、ファイルシステム、PID、シグナルの概念名は聞いたことがあるレベル。C のソース読解は要求しない。

## この連載が答える問い(前編担当分)

1. 「コンテナ」とは結局カーネルの何の組み合わせなのか(namespace + cgroup + rootfs)
2. namespace の各種類は何を隠すのか。`clone`/`unshare`/`setns` とは
3. cgroup v2 によるリソース制限と、メモリ制限を付けても落ちない/急に落ちる OOM の挙動
4. イメージのレイヤと OverlayFS の copy-on-write は何をしているのか
5. `docker run` 一発で、dockerd / containerd / shim / runc の誰が何をやっているのか。なぜ `ps` で runc が見えないのか
6. ホスト側から「コンテナの中」をどう覗くか(`nsenter`)。PID 1・ゾンビ・`--init` とは

## 扱う / 扱わない

- **扱う**: namespace 8 種と隔離対象、cgroup v1/v2 と OOM、OverlayFS(overlay2)の CoW、ランタイム階層(dockerd→containerd→shim→runc)、プロセスツリーの読み方、`nsenter` でのコンテナ侵入、PID 1 とゾンビ問題
- **扱わない**: ネットワーク詳細(後編)、Kubernetes(既存記事に委譲)、Dockerfile 最適化、Windows コンテナ、seccomp/AppArmor の詳細

## セクション構成

### 1. この記事について — 「使える」と「中が見える」の間

- 主張: `docker run` は使えても、障害時に手が止まるのは「コンテナ = カーネル機能の組み合わせ」という地図がないから。本連載はその地図を引く
- 連載の位置づけ(前編=隔離とランタイム、後編=ネットワークとデバッグ実践)を提示
- 既存記事 [k8s_for_docker_users](../k8s/k8s_for_docker_users.md) はオーケストレーションの層、本稿はその下のコンテナ単体の内部、と棲み分けを明示

### 2. 基礎概念の軽い振り返り — イメージ・コンテナ・レイヤ

- 主張: イメージは「読み取り専用レイヤの積み重ね」、コンテナは「その上に書き込み可能レイヤを 1 枚載せて動かしたプロセス」。この一文を後続セクションの地図にする
- `docker run myimage` が作るもの: 新しい namespace 群 + 新しい cgroup + OverlayFS マウント(読み取り専用イメージ層 + 書き込み層)
- コンテナ内は「小さな OS」に見えるが、実体はホスト上の単なるプロセス、という核心を先出し
- 根拠: https://dev.to/ankitdevcode/inside-docker-linux-namespaces-cgroups-3h27 / extract_namespaces_man.json

### 3. コンテナの正体 = namespace + cgroup + rootfs

- 主張: コンテナという単一のカーネルオブジェクトは存在しない。「何が見えるか(namespace)」「どれだけ使えるか(cgroup)」「ルートに何があるか(rootfs)」の 3 つを組み合わせた“見立て”がコンテナ
- 3 要素の役割分担を表で整理(namespace=隔離 / cgroup=資源制御 / rootfs=ファイルの中身)
- namespace は所属プロセスが 0 になるとカーネルが破棄する、という寿命の話で「コンテナ ≒ プロセス」を補強
- 根拠: https://turcomat.org/index.php/turkbilmat/article/download/15258/10928/29324 / search_namespaces_cgroups.json

### 4. namespace — 何を隠しているのか

- 主張: namespace は「このプロセスにどの OS リソースを見せるか」を軸ごとに切り替える仕組み。種類ごとに隠す対象が違う
- 8 種を導入時期つきで一覧(Mount 2002 / UTS・IPC 2006 / PID 2008 / Network 2009 / User 2013 / Cgroup 2016 / Time 5.6)。各 `CLONE_NEW*` フラグと隠す対象を表に
- PID namespace の例: コンテナ内 `ps` は PID 1 から始まる独立番号。これが後段の PID 1 問題の伏線
- User namespace: コンテナの root(UID0)をホストの非特権 UID にマップできるが Docker はデフォルト無効、という実務上の注意
- Cgroup namespace: これがないとコンテナから `/sys/fs/cgroup` 越しに他コンテナの資源配分が見える、という具体例
- 操作する syscall は `clone()` / `unshare()` / `setns()` の 3 つ、と整理
- 根拠: https://man7.org/linux/man-pages/man7/namespaces.7.html / https://man7.org/linux/man-pages/man7/cgroup_namespaces.7.html / https://www.abhik.ai/concepts/linux/namespaces / extract_namespaces_man.json

### 5. cgroup によるリソース制限と OOM の見え方

- 主張: 「メモリ制限を付けたのに落ちない」「逆に何もしてないのに OOM Kill された」は、cgroup v2 のメモリゲートと OOM killer の挙動を知れば説明できる
- v1(コントローラ別階層)と v2(統一階層)の違い。確認法: `stat -fc %T /sys/fs/cgroup/` が `cgroup2fs` なら v2
- v2 のメモリ 3 段ゲート: `memory.low`(保護)/ `memory.high`(スロットリング、落ちずに遅くなる)/ `memory.max`(ハードリミット、超過で cgroup 内 OOM killer 起動)
- 落とし穴: マルチプロセスのコンテナで OOM killer が PID 1 以外の子を殺すとコンテナは生き続ける → 「制限したのに落ちない」の正体。`memory.oom.group=1` でグループ全体を殺せる(v2 の新機能、v1 にはない)
- Docker での設定: `docker run --memory 500m`。コンテナの cgroup は v2 で `/sys/fs/cgroup/system.slice/docker-<ID>.scope/` に作られる
- 確認法: `<scope>/memory.events` の `oom_kill` カウンタ、`docker events --filter event=oom`
- 根拠: https://docs.kernel.org/admin-guide/cgroup-v2.html / https://www.netdata.cloud/academy/diagnosing-linux-cgroups / https://oneuptime.com/blog/post/2026-02-08-how-to-understand-docker-container-cgroups-in-depth/view / https://labs.iximiuz.com/challenges/kill-container-on-child-process-oom-event-docker / extract_cgroup_oom.json

### 6. rootfs と OverlayFS — レイヤと copy-on-write

- 主張: 「ビルドが効かない」「書き込みが消える」「イメージが肥大化する」の多くは OverlayFS の lower/upper/merged と copy-on-write の理解で解ける
- overlay2 の 4 要素: `lowerdir`(読み取り専用イメージ層、複数可)/ `upperdir`(コンテナの書き込み層)/ `merged`(コンテナが見る統一ビュー)/ `workdir`(内部作業用)
- 同名ファイルは upper が lower を隠す。既存ファイルへの初回書き込みは `copy_up` で lower→upper にファイル全体をコピー(ファイル単位なので巨大ファイルの一部変更でも全体コピー)
- レイヤ共有の効能: 200MB ベースを 50 コンテナで共有しても 10GB にならない、各コンテナは差分のみ
- 実体の場所: `/var/lib/docker/overlay2/<id>/` の `lower`/`merged`/`upper`/`work`。`docker info` の `Storage Driver` で確認
- 注意(変動要素): 旧 `overlay`/`aufs` は v24.0 で削除済み。Docker Engine 29.0 以降の新規インストールは containerd image store(snapshotter)がデフォルトで classic graph driver と異なる
- 根拠: https://docs.docker.com/engine/storage/drivers/overlayfs-driver / https://docs.docker.com/engine/deprecated / https://docs.docker.com/engine/storage/containerd / extract_overlayfs.json

### 7. ランタイム構造 — dockerd → containerd → shim → runc

- 主張: `docker` コマンドは入口にすぎない。実際にコンテナを作るのは多段のプロセスで、これを知らないと「ログがどこに出るか」「runc がなぜ見えないか」が分からない
- 処理の流れ: docker CLI → dockerd(REST 受信)→ containerd(OCI bundle 作成)→ `containerd-shim-runc-v2` 経由で runc 起動 → runc がカーネルと対話して namespace/cgroup を設定しプロセスを起動 → **runc は起動後に終了** → shim が親になる
- なぜ shim が要るのか(3 つ): (1) runc を即終了させて長命ランタイムを持たない(daemonless)、(2) dockerd/containerd が死んでもコンテナの STDIO/fd を保持してコンテナを生かす、(3) 実際の親でなくても終了コードを上位へ報告
- プロセスツリーの実際(`ps fxa`): dockerd → containerd → containerd-shim → 実プロセス。runc は既に終了しているので `ps aux | grep runc` しても出ない、という“見えなさ”の説明
- OCI bundle = rootfs + config.json。`docker export ... | tar` と `runc spec` / `runc run` で手で再現できる、という腑落ちデモ
- 根拠: https://medium.com/@yeldos/docker-engine-architecture-under-the-hood-741512b340d5 / https://alexander.holbreich.org/docker-components-explained / https://github.com/containerd/containerd/blob/main/docs/runtime-v2.md / https://groups.google.com/g/docker-dev/c/zaZFlvIx1_k / search_docker_arch_overview.json

### 8. 前編のデバッグ実践 — プロセスツリー・nsenter・PID 1

- 主張: ここまでの地図があれば、ホスト側からコンテナの中を直接覗ける。これがデバッグの第一歩
- コンテナの PID を得る: `docker inspect --format '{{.State.Pid}}' <id>`
- そのプロセスの namespace に入る: `nsenter -t $PID -a /bin/sh`(全 namespace)、`-n` だけでネット名前空間に入る(後編で多用)。`unshare`/`nsenter` のフラグ表(-C/-i/-m/-n/-p/-u/-U)
- PID 1 問題: コンテナ内 PID 1 はカーネルがシグナルを特別扱いし、ハンドラ未登録だと SIGTERM が無視される → `docker stop` が SIGKILL まで待たされる。さらに PID 1 が子を reap しないとゾンビが溜まる
- 解決: `docker run --init`(Tini を注入、Docker 1.12 以降同梱、Dockerfile 変更不要)または `ENTRYPOINT ["/sbin/tini","--"]`
- 根拠: https://www.denibertovic.com/posts/containers-and-signal-handling-why-you-need-to-care-about-pid-1 / https://stackoverflow.com/questions/49162358/docker-init-zombies-why-does-it-matter / https://man7.org/conf/ndctechtown2019/Linux-namespaces-NDC-TechTown-2019-Kerrisk.pdf / extract_pid1_zombie.json / extract_debug_tools.json

### 9. 前編まとめと後編予告

- 「コンテナ = namespace + cgroup + rootfs を runc が組み立て、shim が見守るプロセス」を 1 枚に再掲
- 後編予告: このプロセスがどうやって外と通信するのか(veth / bridge / iptables)と、繋がらない/覗けないを潰すデバッグ実践

## frontmatter 方針(publish 時)

- title 同上 / emoji: 🐳 / type: tech / topics: ["docker","container","linux","containerd","lowlevel"] / published: false
