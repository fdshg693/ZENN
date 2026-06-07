---
title: "WSLは『Linux』ではない — WSL1とWSL2が同じ問いに正反対に答えた話"
emoji: "🐧"
type: "tech"
topics: ["wsl", "linux", "windows", "lowlevel", "architecture"]
published: false
---

## この記事について

WSL を毎日使っている。`wsl` と打てば Ubuntu が立ち上がるし、VS Code も繋がる。「プロジェクトファイルは `/mnt/c` じゃなくて Linux 側(`~/`)に置け」という助言も、なんとなく従っている。

それでも、同僚や後輩から以下のように聞かれて、**30 秒で自分の言葉で答えられるか** と言われると、中級者でも詰まる人は多いはずです。

- 「WSL って結局 VM なんですか? 違うんですか?」
- 「なんで `/mnt/c` は遅くて、`~/` は速いんですか? どっち向きが遅いんですか?」
- 「WSL のターミナル閉じたのに、`vmmem` がメモリ食ってるのなんでですか?」
- 「Linux の中でファイル消したのに、`ext4.vhdx` が縮まないのは?」
- 「`localhost` で繋がるときと繋がらないときがあるのは何でですか?」

この記事は、これらに **「なぜ」まで答えられるメンタルモデル** を作ることを目的にしています。WSL の使い方(インストールやコマンド)ではなく、**「WSL という実行系がどういう設計判断をしているのか」** を読み解く話です。

そして、この記事のいちばんの狙いは WSL そのものではありません。WSL を題材にすると、**「OS とは何か」「仮想化とは何をしているのか」「性能と互換性はどこでトレードオフされるのか」** という、エンジニアとして一段成長するための見方が、驚くほどきれいに手に入ります。

対象は以下のような人:

- WSL を日常的に使うが、内部モデルを言語化できていない中級者
- 「`/mnt/c` は遅い」を **理由まで** 説明できるようになりたい人
- 仮想化・カーネル・システムコールという概念を、身近な題材で腹落ちさせたい人

扱わないこと: インストール手順、ディストリ別の小技、WSLg(GUI)の詳細、設定オプションの網羅リファレンス。

---

## 1. 「OS を動かす」とは、結局何を提供することか

最初に、この記事全体の土台になる 1 つの見方を入れておきます。

**アプリケーションは、カーネルが公開する「システムコール」という窓口越しにしか、世界に触れられません。**

ファイルを開くのも(`open`)、読むのも(`read`)、メモリをもらうのも(`mmap`)、プロセスを作るのも(`fork`)、すべて「カーネルにお願いする」形でしか実現できない。ユーザー空間のプログラムは、CPU・メモリ・ディスク・ネットワークに **直接** は触れず、必ずこの窓口を通します。

ここから、ひとつ強い言い換えができます。

> 「Linux を動かす」とは、突き詰めれば **「Linux のシステムコール ABI を満たす"何か"を用意する」** ことであって、その"何か"の実体が本物の Linux カーネルである必要は、原理的にはない。

[Microsoft の WSL アーキテクチャ解説](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/cmdline/wsl-architectural-overview) は、この点を素っ気なくこう説明しています。

> A syscall is a service provided by the kernel that can be called from user mode. Both the Linux kernel and Windows NT kernel expose syscalls to user mode, but they have different semantics and for the most part are not directly compatible.

Linux カーネルは `fork` / `open` / `kill` など数百のシステムコールを持ち、Windows NT カーネルは `NtCreateProcess` / `NtOpenFile` / `NtTerminateProcess` など別の数百を持つ。**両者は別物で、互換性はない。**

WSL が解いたのは、この一文に集約される問題です。「Linux バイナリが投げてくる Linux のシステムコールを、Windows のマシンの上でどう成立させるか」。

そして WSL1 と WSL2 は、この問いに **正反対** の答えを出しました。

- **WSL1** は、その窓口を **NT カーネルの上に再実装** した。別実装で同じ ABI を満たす方式。
- **WSL2** は、**本物の Linux カーネルを別の箱で動かし**、本物に ABI を満たさせる方式。

この分岐を理解することが、この記事の本体です。順に見ていきます。

---

## 2. WSL1 — NT カーネルに Linux を「化けさせる」(逆 Wine)

WSL1(2016 年)の発想は、いま振り返ると驚くほど大胆です。**VM を一切使わず、Windows NT カーネル自身に Linux のシステムコールを実装させた。**

### pico process と pico provider

仕組みの中心は「pico process」と「pico provider」という 2 つの概念です。

通常の Windows プロセスは、たくさんの「Windows プロセスらしい部品」(各種オブジェクト、初期 DLL など)を持って生まれます。これに対して **pico process は、それらを持たない最小限のプロセス** です。中身は空っぽで、そこに Linux の ELF バイナリがマップされる。そして「これは pico process だ」というフラグだけが立っている。

問題はシステムコールが投げられた瞬間です。Linux バイナリが `read` を呼ぶと、その要求は通常どおり NT カーネルに届きます。ここで NT カーネルのシステムサービスディスパッチャは、まず **「呼び出し元は pico process か?」** を確認します。pico process なら、要求を通常の NT の処理ではなく **pico provider** ── すなわちカーネルモードドライバ `lxcore.sys` / `lxss.sys` ── に委譲します。

この `lxcore.sys` の性質が肝心です。[公式解説](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/cmdline/wsl-architectural-overview) はこう書いています。

> The drivers do not contain code from the Linux kernel but instead a clean room implementation of Linux-compatible kernel interfaces. (...) Where possible, lxcore.sys translates the Linux syscall to the equivalent Windows functionality to do the heavy lifting. Where there is no reasonable mapping from Linux to Windows the kernel mode driver must service the request.

つまり `lxcore.sys` は、**Linux カーネルのコードを 1 行も含まない、Linux 互換インターフェースのクリーンルーム実装** です。可能なものは NT カーネルの機能に翻訳して丸投げし、対応物がないものはドライバ自身が実装する。

### `fork()` という象徴的な例

Linux の `fork`(自分のコピーを作る)には、Windows に直接の等価物がありません。同じ公式解説が、ここで何が起きるかを説明しています。

> When a fork system call is made on the Windows Subsystem for Linux, lxcore.sys does some initial work to prepare for copying the process, calls internal Windows NT kernel APIs to create the process with the correct semantics, and completes copying additional data for the new process.

`lxcore.sys` が下準備をし、NT カーネルの内部 API を叩いてプロセスを作り、Linux のセマンティクスになるよう追加データをコピーする ── つまり **「NT のプリミティブを使って Linux の意味論を組み立て直している」**。これが WSL1 の正体です。

### これは「逆 Wine」である

ここで強力なアナロジーが効きます。Wine は「Windows の Win32 API を Linux の上に実装して、Windows の `.exe` を Linux で動かす」ものでした。WSL1 はその **鏡像** です。「Linux の syscall ABI を Windows の上に実装して、Linux バイナリを Windows で動かす」。

WSL1 を「逆 Wine」として捉えると、その強みと弱みが両方きれいに見えます。

**強み(設計の果実):**

- VM がない。だから起動が一瞬で、リソットも軽い。
- Windows のファイルシステムとネイティブに統合される。後で重要になりますが、**WSL1 では `/mnt/c` へのアクセスが速い**。
- Windows プロセスと同じ土俵にいる。

**弱み(設計の代償):**

- **システムコール互換を全部は実装しきれない。** Linux には数百のシステムコールがあり、それぞれに細かい意味論がある。これを NT カーネルの上で完全再現するのは、現実には不可能に近い。結果として **Docker や FUSE のような、深いカーネル機能に依存するソフトが動かない**。
- 互換性と性能を上げようとすると、作業が「NT カーネルそのものを Linux に寄せて改造する」になり、エンジニアリングとして地獄だった。[Wikipedia の経緯](https://en.wikipedia.org/wiki/Windows_Subsystem_for_Linux) にも、まさにこの行き詰まりが記録されています。

「ABI を別実装で満たす」というアプローチは、上品ではあるけれど、**満たしきれない ABI が必ず残る**。この壁が、WSL2 の方針転換を生みます。

---

## 3. WSL2 — 本物のカーネルを軽量 VM で動かす、でも「VM っぽくない」

WSL2(2019 年発表)の答えは、WSL1 と正反対です。**Linux のシステムコールを再実装するのをやめ、本物の Linux カーネルを持ってきた。**

[Announcing WSL 2](https://devblogs.microsoft.com/commandline/announcing-wsl-2) はこう宣言しています。

> In WSL 1 we created a translation layer that interprets many of these system calls and allows them to work on the Windows NT kernel. However, it's challenging to implement all of these system calls (...). Now that WSL 2 includes its own Linux kernel it has full system call compatibility. (...) Some exciting examples are the Linux version of Docker, as well as FUSE!

「全部は実装しきれない」(WSL1 の弱み)に対して、「じゃあ本物を積めば互換性は一瞬で 100% になる」というのが WSL2 の発想です。実際、WSL1 で動かなかった Docker や FUSE がそのまま動くようになりました。Microsoft は **Linux カーネルそのものを Windows と一緒に配布する** という、数年前なら考えられなかった選択をしています。

### ただし「普通の VM」ではない

ここで多くの人がつまずきます。「本物のカーネル = VM」と聞くと、重くて遅いものを想像する。しかし WSL2 はそう作られていません。同じ記事が、わざわざ釘を刺しています。

> WSL 2 uses the latest and greatest in virtualization technology to run its Linux kernel inside of a lightweight utility virtual machine (VM). However, WSL 2 will NOT be a traditional VM experience. (...) It will still give the remarkable benefits of WSL 1: High levels of integration between Windows and Linux, extremely fast boot times, small resource footprint, and best of all will require no VM configuration or management.

Hyper-V をベースにしつつ、**起動が速く・省リソースで・構成管理不要** な「軽量ユーティリティ VM」。WSL1 の体験(統合・速さ)を維持したまま、中身だけ本物のカーネルに差し替えた、というのが狙いです。

[What is WSL](https://learn.microsoft.com/en-us/windows/wsl/about) によると、ディストリビューションはこの VM の中の「隔離されたコンテナ」として動きます。複数のディストロは、ネットワーク名前空間や CPU/カーネル/メモリを共有しつつ、PID・mount・user・cgroup の名前空間はそれぞれ持つ ── つまり **1 つの VM を複数ディストロで共有** しています。

### この記事でいちばん大事な一行

WSL1 と WSL2 のいちばん本質的な違いは、互換性でも性能でもありません。**境界の場所** です。

- **WSL1 の境界は「システムコール」だった。** Linux アプリと Windows カーネルは同じマシン・同じアドレス空間の地続きで、syscall という細い線で接していた。
- **WSL2 の境界は「VM とホストの間」に移った。** Linux は別世界(VM)に引っ越し、その世界とホスト Windows の間には、ネットワーク的な隔壁ができた。

これから出てくる「WSL の不可解な現象」は、ほぼ全部この一行 ── **境界が VM とホストの間に移った** ── から導けます。逆に言うと、この一行を握っていれば、現象を 1 個 1 個暗記する必要はありません。順に確かめていきます。

---

## 4. 現象①: なぜ `/mnt/c` は遅く、`~/` は速いのか — 9P という橋

WSL2 でいちばん有名なハマりが、ファイルシステムの性能です。[公式ドキュメント](https://learn.microsoft.com/en-us/windows/wsl/filesystems) は、理由を説明する前にまず結論を言い切ります。

> Use the Linux file system root directory: `/home/<user name>/Project`
> Not the Windows file system root directory: `/mnt/c/Users/<user name>/Project` (...) your performance speed will improve if you store them directly on the `\\wsl$` drive.

なぜこうなるのか。3 章の「境界」で説明できます。

- **`~/`(Linux ファイル)は、VM の中の ext4 ファイルシステム** にあります(その実体は後述の `.vhdx`)。Linux カーネルから見れば完全にローカルのディスクなので、**ネイティブ速度** が出る。
- **`/mnt/c`(Windows ファイル)は、VM の外** にあります。Linux カーネルは「これはローカルなファイルではない」と判断し、要求を **9P(Plan 9)プロトコル** に変換して、仮想ネットワーク越しに Windows 側の 9P サーバへ転送します。

この「9P 越しの転送」が遅さの正体です。あるフォーラムの[分かりやすい分解](https://forum.proxmox.com/threads/wsl2-broken-down.171914)を借りると、`/mnt/c` への 1 回の `write()` は、

1. VM 内 Linux カーネルが「ローカルでない」と判断し、
2. 要求を 9P リクエストにシリアライズして仮想ネットワークで送り、
3. Windows 側で受け取りデシリアライズして実 I/O、

という多段を毎回くぐります。1 回ぶんの追加レイテンシは小さくても、**小さなファイルを大量に** 触る操作 ── `npm install`、`git status`、ビルド ── では、このレイテンシが何千回も積み上がって体感に直撃します。

### 向きによって違う、WSL1 との逆転

ここで面白いのが「どっち向きが遅いか」です。

- **Linux から Windows ファイル(`/mnt/c`)** … 9P 越し。重い。
- **Windows から Linux ファイル(`\\wsl$` や `\\wsl.localhost`)** … これも境界越えですが、実測では前者ほど致命的でないという報告が多い([参考](https://pomeroy.me/2023/12/how-i-fixed-wsl-2-filesystem-performance-issues))。

さらに、**WSL1 ではこの関係が逆でした。** WSL1 は VM を持たず Windows FS とネイティブに統合されていたので `/mnt/c` が速く、むしろ Linux 側の一部操作が遅かった。実際、[WSL の issue #4197](https://github.com/microsoft/WSL/issues/4197) には「`/mnt` では WSL1 の方が WSL2 より速いが、`/` では WSL2 の方が速い」というベンチマークが残っています。

これは矛盾ではありません。**境界の場所が違うから、遅い場所が違う** だけです。WSL1 は syscall が境界なので Windows FS と地続き。WSL2 は VM が境界なので Windows FS が「ネットワークの向こう」になる。

**実務結論:** プロジェクトファイルは `~/`(Linux FS)に置く。`/mnt/c` は Windows ツールと共有したいときだけ使う。これを「なぜ」まで説明できるのが、この章のゴールです。

---

## 5. 現象②: なぜ `vmmem` はメモリを返さず、`.vhdx` は縮まないのか — 箱の宿命

次は「閉じたのにメモリを食う」「消したのにディスクが減らない」という、2 大不気味現象です。これも同じ根 ── **WSL2 は VM なので、Linux のメモリもディスクも、ホストから見ると 1 個の"箱"に閉じ込められている** ── から両方説明できます。

### メモリ: `vmmem` がキャッシュを抱え込む

WSL2 のメモリ使用量は、ホスト側では `vmmem`(新しめの Windows では `Vmmem` や `wslservice`)という 1 プロセスとして見えます。WSL2 のメモリは使うほど伸び、プロセスがメモリを解放すれば縮みます ── が、ここに 1 つ罠があります。[Comparing WSL Versions](https://learn.microsoft.com/en-us/windows/wsl/compare-versions) の WSL1 を選ぶべき例外の説明にこうあります。

> WSL 2's memory usage grows and shrinks as you use it. When a process frees memory this is automatically returned to Windows. However, as of right now WSL 2 does not yet release cached pages in memory back to Windows until the WSL instance is shut down.

Linux カーネルは、空きメモリを「ページキャッシュ」として積極的に使います(これ自体は正しい挙動)。問題は、**そのキャッシュが WSL を shutdown するまで Windows に返らない** こと。長時間セッションや大量ファイルアクセスのあと、`vmmem` がメモリを抱えたまま見える、というのはこのためです。これは「Linux のメモリ管理の都合」と「VM という箱の都合」が噛み合った結果で、バグではなく構造です。

対処の道具立て(`C:\Users\<you>\.wslconfig` で設定):

- `memory=4GB` … VM に渡すメモリの **上限** を切る。
- `autoMemoryReclaim` … 使われていないキャッシュを段階的に Windows へ返す挙動を有効化する。
- 最終手段 `wsl --shutdown` … VM ごと落とせば、当然すべて返る。

### ディスク: `.vhdx` は成長一方

Linux 側のファイルシステムの実体は、ホスト上の **`ext4.vhdx` という 1 個の仮想ディスクファイル** です。ここに「箱の宿命」が出ます。**Linux の中でファイルを削除しても、`.vhdx` は自動では縮みません。** 一度大きくなったら、空き領域があってもそのサイズを保ち続ける。

[WSL issue #4699](https://github.com/microsoft/WSL/issues/4699) には、「`/tmp` で大きな一時ファイルを処理したら `.vhdx` が肥大し、ファイルを消しても 250GB のまま戻らない」という典型例が報告されています。対処は、

- `.wslconfig` の `[experimental] sparseVhd=true` や `wsl --manage <distro> --set-sparse true` で sparse VHD を有効にする、
- それでも縮まなければ、`wsl --shutdown` のうえ `Optimize-VHD`(Windows Pro 以上)や `diskpart` の `compact vdisk` で手動圧縮する、

といった手順になります([参考 issue #12103](https://github.com/microsoft/WSL/issues/12103))。

メモリも `.vhdx` も、「Linux が管理しているつもりのリソースの実体が、ホスト側の 1 個のファイル/プロセスに閉じ込められている」という **まったく同じ構造** から来ている、と束ねて理解するのがこの章の要点です。

---

## 6. 現象③: `localhost` とネットワーク — NAT という境界、mirrored という回避

「Windows のブラウザから WSL のサーバに `localhost:3000` で繋がる ── ときと、繋がらないときがある」。これも境界の話です。

### デフォルトは NAT = WSL2 は「別ホスト」

[ネットワークの公式ドキュメント](https://learn.microsoft.com/en-us/windows/wsl/networking) によると、WSL2 は既定で **NAT(ネットワークアドレス変換)** ベースの構成を取ります。これはつまり、**WSL2 VM は独自のサブネットを持つ"別のホスト"** だということです。家の中に、ルータ(NAT)を挟んでもう 1 台 PC があるイメージ。

このため、いくつかの不便が生まれます。

- WSL の IP アドレスは VM 起動ごとに変わりうる。
- 「外から見た WSL の IP」を知るには小細工が要る。公式ドキュメントは `hostname -i`(VM 自身から見たローカルアドレス)と `hostname -I`(他のマシンから見えるアドレス)を区別せよ、と注意しています。
- Windows → Linux のサーバアクセスは `localhost` フォワーディングで救済されることが多いものの、構成によっては破綻する。

「`localhost` が繋がったり繋がらなかったり」は気分ではなく、**WSL が"別ホスト"であることに NAT の橋がどこまで対応できているか** で決まる、というのが正しい捉え方です。

### mirrored mode = 境界の引き方そのものを変える

Windows 11 22H2 以降では、`.wslconfig` に `networkingMode=mirrored` を指定できます。同ドキュメントの説明:

> Enabling this changes WSL to an entirely new networking architecture which has the goal of 'mirroring' the network interfaces that you have on Windows into Linux (...)
> Connect to Windows servers from within Linux using the localhost address `127.0.0.1`.

mirrored モードは、Windows のネットワークインターフェースを Linux 側に「鏡写し」にします。これにより、`localhost`(127.0.0.1)で双方向に繋がり、IPv6 が使え、VPN との互換性も改善する。NAT が「別ホストを橋でつなぐ」発想だったのに対し、mirrored は「**そもそも同一視してしまう**」発想です。`networkingMode` には他に `none` / `nat` / `bridged`(非推奨)/ `virtioproxy` があり([wsl-config](https://learn.microsoft.com/en-us/windows/wsl/wsl-config))、これらは全部「VM とホストのネットワーク境界をどう引くか」の選択肢だと読めます。

---

## 7. 現象④: 相互運用と systemd — 「同じマシンに見える」の正体

WSL の魔法のような体験 ── Linux のシェルから `notepad.exe` が起動し、Windows の PATH も通っている ── も、境界に架けられた「橋」の一種です。

### interop: Linux カーネルが `.exe` を実行できる理由

Linux のシェルで `explorer.exe .` と打つと Windows のエクスプローラが開きます。これは魔法ではなく、Linux カーネルの **binfmt_misc** という仕組みを使っています。binfmt_misc は「特定のフォーマットの実行ファイルを見つけたら、登録されたハンドラに実行を委ねる」カーネル機能です。WSL は起動時に、Windows の実行ファイル(PE フォーマット)用のハンドラを binfmt_misc に登録しています(`/proc/sys/fs/binfmt_misc/WSLInterop` で確認できます)。

だから、Linux カーネルが PE バイナリの実行要求を受けると、それを WSL の interop ブリッジに渡し、ブリッジが Windows 側で本物のプロセスを起動する。[ファイルシステムのドキュメント](https://learn.microsoft.com/en-us/windows/wsl/filesystems) には、この相互運用に加えて、`WSLENV` 環境変数を使って Windows と Linux の間で環境変数を橋渡しする方法も書かれています。これも「実行の橋」の一部です。

### systemd: なぜ最初は無かったのか

WSL には長らく **systemd がありませんでした。** PID 1(init プロセス)が systemd ではなく WSL 独自の init だったため、systemd 前提のサービスや `snap` が動かない、という不便がありました。

これは手抜きではなく、3 章で見た「VM を意識させない」思想の表れです。独自の軽量 init にすることで、起動を速く・フットプリントを小さく保っていた。systemd は重く、起動も遅くなりうるからです。

その後、Microsoft は Canonical と協力して systemd 対応を入れました。[公式手順](https://learn.microsoft.com/en-us/windows/wsl/systemd) によると、WSL 0.67.6 以降で、ディストロ内の `/etc/wsl.conf` に次を書くだけで有効化できます。

```ini
[boot]
systemd=true
```

ただし同ドキュメントは、**systemd サービスが WSL インスタンスを生かし続けるわけではない**(従来どおり、使い終われば VM は落ちる)と釘を刺しています。これは「速さ・軽さ」という元の思想を守りつつ、systemd というエコシステム互換を後付けで呑み込んだ ── まさに **思想とのトレードオフを引き受けた追加** として読めます。

---

## 8. 立体化: 「普通の VM」と何が違うのか

ここまでの現象を、もう一段高いところから見ます。WSL2 は「普通の VM」とどう違うのか。これを言語化すると、設計判断の全体像が一望できます。

### 従来の VM(VirtualBox や素の Hyper-V 上のゲスト)

- ホストから **完全に隔離** される。これが安全性と互換性の源。
- 起動が遅い(ゲスト OS をフルブートする)。
- リソースを **固定的に確保** する(「メモリ 4GB を割り当て」)。
- ユーザーが構成を管理する(仮想ディスク、ネットワークアダプタ、共有フォルダ…)。
- ホストとの接点は「ネットワーク共有」くらいで、基本は孤立した別マシン。

### WSL2(軽量ユーティリティ VM)が振った設計

3 章で引用したとおり、WSL2 は「NOT a traditional VM experience」を明言しています。具体的には:

- **起動高速**(オンデマンドで立ち上がり、使い終われば落ちる)。
- **リソース動的**(使った分だけ伸びる)。ただし 5 章で見たとおり、**返すのは苦手** という宿命つき。
- **管理不要**(仮想ディスクもネットワークも自動構成)。
- そして決定的に ── **ファイル・ネットワーク・プロセスを、ホストと積極的に橋渡しする。**

### 「VM なのに VM っぽくない」の正体

ここで全部が繋がります。WSL2 は、

- **隔離**(本物のカーネル = VM がもたらす完全な互換性と安全性)と、
- **統合**(WSL1 がもたらした、Windows と地続きの快適な体験)

の **両取り** を狙いました。普通の VM は隔離を取って統合を捨て、WSL1 は統合を取って互換性を捨てた。WSL2 はそのどちらも諦めなかった。

その代償が、ここまで見てきた「橋」の数々です。

| 橋 | 何をつなぐか | 出てくるコスト(=現象) |
|---|---|---|
| 9P プロトコル | Linux ⇄ Windows のファイル | `/mnt/c` が遅い(4 章) |
| vmmem / `.vhdx` | Linux のメモリ・ディスクの実体 | メモリ・ディスクが返らない(5 章) |
| NAT / mirrored | Linux ⇄ Windows のネットワーク | localhost 問題(6 章) |
| binfmt_misc / interop | Linux ⇄ Windows のプロセス実行 | (恩恵側。だが境界越えのオーバーヘッドはある) |

**橋を架けたところには、必ず通行コストが出る。** 遅延、メモリ、IP の不一致 ── WSL2 の「不可解な現象」は、例外なくどれかの橋のコストです。

結論を一文にすると、こうなります。

> **WSL の全現象は、「隔離と統合のトレードオフを、境界をどこに引くか・どんな橋を架けるかで解いた」という一点に収束する。**

---

## 9. 実務への変換

ここまでのメンタルモデルを、日々の判断に落とします。どれも「なぜそうするか」が、もう自分の言葉で言えるはずです。

- **プロジェクトは `~/`(Linux FS)に置く。** `/mnt/c` に置くと 9P の橋を毎回渡る(4 章)。Windows ツールと共有したいときだけ `/mnt/c` か `\\wsl$` を使う。
- **メモリが返らないと感じたら** `.wslconfig` で `memory` 上限と `autoMemoryReclaim` を設定。困ったら `wsl --shutdown`(5 章)。
- **ディスク(`.vhdx`)が減らないなら** sparse VHD を有効化し、必要なら `Optimize-VHD` で手動圧縮(5 章)。
- **`localhost` で繋がらないときは** まず NAT を疑う。Win11 22H2+ なら `networkingMode=mirrored` を検討(6 章)。
- **Docker や snap を使うなら** WSL2 + systemd 前提(3・7 章)。WSL1 ではそもそも動かない。
- **WSL1 がまだ有利な例外もある。** [公式の「Exceptions for using WSL 1」](https://learn.microsoft.com/en-us/windows/wsl/compare-versions) は、`/mnt/c` への重い読み書きが主なワークロードや、VM を立てられない環境を挙げています。境界が syscall にある WSL1 なら、Windows FS と地続きで速いからです。

「とりあえず全部 WSL2」ではなく、**自分のワークロードがどの橋を何回渡るか** で選べるようになる、というのがこの章のねらいです。

---

## 10. まとめ

- **「OS を動かす」とは、システムコール ABI を満たすこと。** カーネルの実体が何かは、原理的には問わない。これが WSL を読む土台。
- **WSL1 は逆 Wine。** NT カーネル上に Linux の syscall をクリーンルーム実装した(pico process / `lxcore.sys`)。上品だが、ABI を満たしきれず Docker/FUSE が動かなかった。
- **WSL2 は方針転換。** 本物の Linux カーネルを軽量 VM で動かし、互換性を一気に 100% にした。代わりに **境界が「syscall」から「VM とホストの間」へ移った。**
- **WSL2 の不可解な現象は、すべてこの境界に架けた橋のコスト** として一本で導ける ── 9P(ファイル)、vmmem/`.vhdx`(箱の宿命)、NAT/mirrored(ネットワーク)、binfmt_misc(実行)。
- **WSL2 は「隔離」と「統合」の両取りを狙った VM。** だから「VM なのに VM っぽくない」。橋を架けたところに必ずコストが出る、という一点に全部が収束する。

中級者として WSL の内部を理解すると、持ち帰れるものは WSL の Tips ではありません。**「OS は syscall ABI」「仮想化は境界の再配置」「性能と互換は橋のコスト」** という 3 つの見方です。この 3 つが言語化できれば、Docker のコンテナも、クラウドの軽量 VM も、次に出会う仮想化技術も、同じ地図の上で読めるようになります。次に `vmmem` がメモリを抱えているのを見たとき、それが不具合ではなく **設計判断のアイコン** に見えてくれば、この記事は役目を果たしたことになります。

---

## 参考

- [What is Windows Subsystem for Linux | Microsoft Learn](https://learn.microsoft.com/en-us/windows/wsl/about)
- [Comparing WSL Versions | Microsoft Learn](https://learn.microsoft.com/en-us/windows/wsl/compare-versions)
- [WSL architectural overview (WSL1) | Microsoft Learn](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/cmdline/wsl-architectural-overview)
- [Announcing WSL 2 | Windows Command Line](https://devblogs.microsoft.com/commandline/announcing-wsl-2)
- [Working across Windows and Linux file systems | Microsoft Learn](https://learn.microsoft.com/en-us/windows/wsl/filesystems)
- [Accessing network applications with WSL | Microsoft Learn](https://learn.microsoft.com/en-us/windows/wsl/networking)
- [Advanced settings configuration in WSL (.wslconfig / wsl.conf) | Microsoft Learn](https://learn.microsoft.com/en-us/windows/wsl/wsl-config)
- [Use systemd to manage Linux services with WSL | Microsoft Learn](https://learn.microsoft.com/en-us/windows/wsl/systemd)
- [filesystem performance is much slower than wsl1 in /mnt · Issue #4197](https://github.com/microsoft/WSL/issues/4197)
- [WSL 2 should automatically release disk space back to the host OS · Issue #4699](https://github.com/microsoft/WSL/issues/4699)
