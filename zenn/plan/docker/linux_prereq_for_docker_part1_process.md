---
title: "Docker内部記事を読むためのLinux前提知識(プロセス・ファイル編) — プロセス・シグナル・マウントの地図"
status: plan
---

## この plan の位置づけ

- 既存記事 [docker_internals_part1](../../publish/docker/docker_internals_part1.md)(前編)が暗黙に要求する Linux 前提知識を埋めるコンパニオン記事の構成案
- 後編 [docker_internals_part2](../../publish/docker/docker_internals_part2.md) 向けのネットワーク前提は別 plan [linux_prereq_for_docker_part2_network](./linux_prereq_for_docker_part2_network.md) が担当
- スタイル方針(ユーザー承認済み): 各セクション冒頭に「なぜこれを知ると元記事が読めるか」のメンタルモデルを 2〜3 文 → 詳細・用語・コマンドは箇条書き/表で畳む。各セクション末に「→ 元記事のこの記述に効く」橋渡しを置く

## 想定読者と前提

- `docker run` / `docker compose up` は日常的に使えるが、元記事前編に出てくる「プロセス」「シグナル」「マウント」「rootfs」が語としては分かっても中身を説明できない
- 元記事の前提(「プロセス・PID・シグナルを聞いたことがあるレベル」)より **一段下** から始める。語の初出は必ず一文で定義する
- 対象は Linux(または Docker Desktop 内の Linux VM)。C のソース読解は要求しない

## この記事が答える問い

1. 「コンテナはホストのカーネル上の 1 プロセス」と言われてピンとくるための、カーネル/ユーザー空間とシステムコールの最小知識は何か
2. プロセス・PID・親子関係・プロセスツリーをどう読むか(`ps fxa` が読めるように)
3. シグナルとは何か。なぜ `docker stop` は SIGTERM → 10 秒 → SIGKILL なのか
4. PID 1 はなぜ特別か。ゾンビ・孤児・init/Tini とは
5. ファイルシステム・マウント・rootfs・copy-on-write とは
6. UID/GID・root・特権はコンテナのセキュリティとどう繋がるか

## 扱う / 扱わない

- **扱う**: カーネル空間とユーザー空間、システムコール、VM とコンテナの違い、プロセス/PID/fork-exec/プロセスツリー、デーモン、シグナルとハンドラ、PID 1 の特別扱い・reap・ゾンビ・孤児・init、ファイルシステム/マウント/rootfs、copy-on-write、UID/GID/root/特権、調査コマンドの読み方(`ps` `ss` `stat` `/proc` `/sys` `$(...)`)
- **扱わない**: namespace / cgroup / OverlayFS / runc の詳細(= 元記事本体なのでリンクで委譲)、ネットワーク(コンパニオン後編)、シェルスクリプト全般、C プログラミング

## セクション構成

### 1. この記事について — 元記事の「前提」を先に埋める

- 主張: 元記事前編は良い地図だが、その地図を読むにも「プロセスとは」「シグナルとは」という下地が要る。本稿はその下地だけを最短で配る
- 元記事前編へのリンクと、対応関係(本稿の各章が前編のどの記述に効くか)を冒頭で予告
- 根拠: [docker_internals_part1](../../publish/docker/docker_internals_part1.md)

### 2. カーネルとユーザー空間 — 「システムコール」とは何か

- メンタルモデル: OS は「カーネル(特権で動く中核)」と「ユーザー空間(アプリ)」の二層。アプリがハードやプロセス生成など特権操作をしたいとき、境界を越える唯一の窓口が **システムコール**
- 箇条書き: ユーザー空間/カーネル空間の違い / システムコールの例(プロセス生成・ファイル操作・ネットワーク)/ `clone()`・`unshare()`・`setns()` はプロセスと namespace を操る syscall
- VM との対比: VM は「別のカーネルごと」動かす。コンテナは **ホストの同じカーネル**を共有し、見え方だけを変える。だから「別カーネルが動いているわけではない」
- → 元記事「ホストのカーネルの上で動くただ 1 つのプロセス」「clone/unshare/setns」「仮想マシンのように別のカーネルが動いているわけではない」に効く
- 根拠: https://www.cs.bu.edu/fac/richwest/cs591_w1/notes/linux_process_mgt.PDF / search_process_syscall.json

### 3. プロセスとは — PID・親子・プロセスツリー

- メンタルモデル: プロセス=実行中のプログラム 1 個。Linux では新しいプロセスは必ず既存プロセスの「子」として生まれる。だから全プロセスは 1 本の木になる
- 箇条書き: プロセスと PID / fork(自分の複製を作る)→ exec(中身を別プログラムに置き換える)の 2 段モデル / PPID(親 PID)/ プロセスツリーと `ps fxa` の読み方(インデントが親子)/ デーモン=常駐するバックグラウンドプロセス(dockerd/containerd がこれ)
- 図: `bash → vim` のような小さなツリー例で「親→子」の見方を示す
- → 元記事「`ps fxa` で dockerd → containerd → shim → 実プロセス」「runc がツリーに現れない」を読むための下地
- 根拠: https://www.abhik.ai/concepts/linux/process-management / https://man7.org/linux/man-pages/man1/top.1.html / search_process_syscall.json

### 4. シグナル — プロセスへの「短い通知」

- メンタルモデル: シグナルは OS やプロセスが別プロセスへ送る番号付きの短い通知。「止まって」「死んで」などをプロセス境界越しに伝える仕組み
- 箇条書き: 代表的シグナル(SIGTERM=お願いベースの終了 / SIGKILL=問答無用の強制終了・捕捉不可 / SIGINT=Ctrl-C / SIGCHLD=子の状態変化通知)/ シグナルハンドラ=受信時の処理を登録できる / ハンドラ未登録時の「デフォルト動作」 / SIGKILL と SIGSTOP だけは捕捉・無視できない
- 表: シグナル名 | 既定動作 | 捕捉可否 | 用途
- → 元記事「`docker stop` が送る SIGTERM」「タイムアウト後に SIGKILL で強制終了」を読むための下地
- 根拠: https://man7.org/linux/man-pages/man7/signal.7.html(本格調査で本文裏取り予定)/ search_signals_pid1.json

### 5. PID 1・ゾンビ・init — 親が子を「看取る」仕組み

- メンタルモデル: 子プロセスが死ぬと、親が `waitpid()` で「看取って(reap して)」初めて完全に消える。看取られない死体が **ゾンビ**。そして PID 1 はこの木の根なので、カーネルから特別扱いされる
- 箇条書き:
  - reap = 親が死んだ子の終了情報を回収し、資源を解放すること
  - ゾンビ = 死んだが reap されていないプロセス。1 個なら無害、溜まると PID を食い潰す
  - 孤児 = 親が先に死んだ子。カーネルが PID 1 へ再ペアレント(里親に出す)する
  - PID 1 の特別扱い: カーネルが PID 1 にだけ `SIGNAL_UNKILLABLE` フラグを立て、ハンドラ未登録のシグナルは **デフォルト動作で配送しない**(だから SIGTERM を黙殺できる)。ただしハンドラを登録すれば受け取れる
  - init とは: 本来 PID 1 に座る、シグナル転送とゾンビ刈り取りに専念する小さなプロセス。コンテナでは Tini がこの役
- → 元記事「PID 1 にはシグナルがデフォルトで配送されない」「ゾンビを reap する責務」「`docker run --init`(Tini)」に直結
- 根拠: https://unix.stackexchange.com/questions/776687/how-is-pid-1-made-special-and-unkillable(SIGNAL_UNKILLABLE)/ https://www.denibertovic.com/posts/containers-and-signal-handling-why-you-need-to-care-about-pid-1 / https://stackoverflow.com/questions/49162358/docker-init-zombies-why-does-it-matter / search_signals_pid1.json

### 6. ファイルシステムとマウント — `/`・マウントポイント・rootfs

- メンタルモデル: Linux のファイルは 1 本のツリー(根は `/`)。別のディスクやイメージを、このツリーの任意の場所に「接ぎ木」するのが **マウント**。コンテナが見る `/` の中身=rootfs も、この接ぎ木で作られる
- 箇条書き: ファイルシステム/ディレクトリツリー / マウントとマウントポイント(「ここに別の中身を見せる」)/ ルート `/` / rootfs=ルートに見えるファイル一式 / 読み取り専用 vs 書き込み可能 / `/proc`・`/sys` は実ファイルでなくカーネルの情報を見せる特別な FS
- → 元記事「rootfs」「OverlayFS の merged がコンテナの `/`」「mount namespace」を読むための下地
- 根拠: https://man7.org/linux/man-pages/man8/mount.8.html / https://man7.org/linux/man-pages/man7/path_resolution.7.html(本格調査で裏取り予定)/ search_fs_perms.json

### 7. copy-on-write — 「コピーは書き込むまで遅延する」

- メンタルモデル: 同じ中身を複数が共有している間はコピーしない。誰かが書き換えようとした瞬間に、その分だけ複製する。これが copy-on-write(CoW)。fork のメモリ共有も OverlayFS の層も同じ発想
- 箇条書き: なぜ CoW が速い/省メモリか / fork 時のメモリ CoW / OverlayFS の `copy_up`(下層の読み取り専用ファイルを書く時だけ上層へコピー)/ ファイル単位コピーの含意(巨大ファイルの 1 バイト変更でも全体コピー)
- → 元記事「初回書き込みで `copy_up`」「ファイル単位なので巨大ファイルの一部変更でも全体コピー」に直結
- 根拠: https://www.abhik.ai/concepts/linux/process-management(fork CoW)/ search_process_syscall.json

### 8. ユーザーと権限 — UID/GID・root・特権

- メンタルモデル: Linux は「誰が(UID/GID)」で権限を判定する。UID 0=root=ほぼ何でもできる特権ユーザー。コンテナの中の root が、ホストの root と同じ番号なら、それは実質ホストの全権を持つ
- 箇条書き: UID/GID / root(UID 0)と一般ユーザー / 特権操作と `sudo` / なぜ「コンテナ内 root = ホスト root」が既定だと危険か(User namespace 未使用時)/ capabilities という「root 権限の細分化」が存在すること(深入りはしない)
- → 元記事「コンテナ内 root ≠ ホスト root にできる(User namespace)」「Docker はデフォルトで User namespace を有効にしない」に効く
- 根拠: https://man7.org/linux/man-pages/man7/capabilities.7.html / https://man7.org/linux/man-pages/man7/credentials.7.html(本格調査で裏取り予定)/ search_process_syscall.json

### 9. 調査の道具箱 — 元記事のコマンドを読む早見表

- メンタルモデル: 元記事のデバッグコマンドは、ここまでの概念に 1 対 1 で対応している。道具と「何を見るための道具か」を対応づけておけば、コマンド列に怯まなくなる
- 表: コマンド | 何を見る | 対応概念
  - `ps` / `ps fxa` … プロセス一覧/ツリー(§3)
  - `ss -tlnp` … listen 中のポート(後編の下地)
  - `stat -fc %T` … ファイルシステム種別(§6)
  - `cat /proc/...` `/sys/fs/cgroup` … カーネルが見せる情報(§6)
  - `/var/lib/docker/...` … Docker の実体パス
  - `$(...)` … コマンド置換(`PID=$(docker inspect ...)` の読み方)
- → 元記事のコマンド列全般が「何を確認しているか」で読めるようになる
- 根拠: https://man7.org/linux/man-pages/man8/ss.8.html / search_dns_tools.json

### 10. まとめと後編(ネットワーク編)への橋渡し

- 1 枚に畳む: 「コンテナ = ホストのカーネル上の 1 プロセスに、見え方(後述の namespace)とファイル(rootfs)を被せたもの」。本稿はその「プロセス」と「ファイル」の下地
- 後編予告: 同じ 1 プロセスが外と通信する仕組み(IP・ルーティング・NAT・iptables・DNS)の前提を、コンパニオン後編で配る
- リンク: [linux_prereq_for_docker_part2_network](./linux_prereq_for_docker_part2_network.md) / [docker_internals_part1](../../publish/docker/docker_internals_part1.md)

## frontmatter 方針(publish 時)

- title 同上 / emoji: 🐧 / type: tech / topics: ["linux","docker","container","process","beginners"] / published: false
- topics は既存 docker 記事の `linux` `docker` `container` を再利用しつつ、本稿の主題に合わせて `process` `beginners` を追加
