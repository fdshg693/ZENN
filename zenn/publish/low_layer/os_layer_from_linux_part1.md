---
title: "Linuxを地図に、OSを読む(前編) — アプリは『どこから先』をOSに任せているのか"
emoji: "🐧"
type: "tech"
topics: ["linux", "os", "kernel", "lowlevel", "architecture"]
published: false
---

## この記事について

普段は Python / Go / JavaScript / Rust / Java / C# で仕事をしている。OS のことは「使う」けれど「読む」ことはない。それでもこういう質問はよく飛んできて、30 秒で答えられない人が多いはずです。

- 「Linux って OS ですよね? それと Ubuntu の違いって何ですか?」
- 「カーネルが落ちるとなぜ OS ごと落ちて、Chrome が落ちても OS は落ちないんですか?」
- 「`printf` って syscall なんですか? それとも libc の関数ですか?」
- 「Go は libc を使わないって聞きました。じゃあ何を使ってるんですか?」
- 「`fork` って Windows には無いんですよね? じゃあ Windows のプロセスってどう作るんですか?」

最後の問いだけは、後編に回します。前編は、**カーネルが何をやっていて、何をやっていないか** を Linux を題材に整理し、そのうえで「アプリは OS のどの面に依存しているか」を 7 つの軸に分解します。

連載中の位置づけ:

- [アセンブラを書かない人のためのアセンブラ(前編)](./assembly_for_high_level_users_part1) で ISA・呼出規約・ABI まで降りた
- [後編](./assembly_for_high_level_users_part2) で「コンパイラの代行作業」を扱った
- **本稿は、その上にある「カーネルとアプリの境界線」の地図** を引きます

対象は Linux カーネル 6.x 系を主軸、libc は glibc を主軸にしますが、議論はバージョンに強くは依存しません。

---

## 1. なぜ今「OS の地図」を引き直すのか

アセンブラ編で、`return a + b;` の 1 行が CPU 命令とレジスタとスタックフレームと呼出規約に分解されるところまで降りました。「コンパイラがどれだけのことを代行しているか」も見ました。

ただ、あれは **「言語処理系とハードウェア」の話** で、まだ「OS」が出てきていない。コンパイラが吐いた `.o` を実行ファイルにして、それをカーネルがメモリに乗せて CPU に走らせる ─ そこに **もう 1 段、抽象化を貸している層** がいて、それが OS(カーネル)です。

そして高級言語は、ABI を抽象化したわりに **OS の責務境界そのものは抽象化していない**。だから今でも、

- 「ファイル名の大文字小文字を区別したい」
- 「`fork` で並列化したいけど Windows で動かない」
- 「`epoll` か `IOCP` か `kqueue` か、ライブラリが対応していない」

のような **OS の地肌が漏れる** 場面が消えない。これが、5 年経っても 10 年経っても「OS 差」が問題であり続ける構造的理由です。

本稿の狙いは、その「漏れる場所」がどこなのかを **格子状にマッピングする** ことです。

---

## 2. 「OS」と「カーネル」と「ユーザーランド」を切り直す

多くの人が「OS は Linux です」と言うとき、実は **「Linux ディストリビューション」** の話をしています。Ubuntu、Debian、Fedora、Arch、Alpine。これらは厳密には別物です。

```
Linux ディストリビューション = カーネル(Linux)
                             + libc(glibc / musl)
                             + coreutils(ls, cat, rm)
                             + シェル(bash, zsh)
                             + パッケージマネージャ(apt, dnf)
                             + デスクトップ環境(GNOME, KDE)
                             + ...
```

このうち、**「Linux」という単語が指しているのは一番上だけ** です。`kernel.org` で配布されているのもこれだけ。残りはすべて別プロジェクトの寄せ集めです。

この記事で「OS の責務」と書いたら、原則 **カーネル + 最小限のユーザーランド(libc と init くらい)** を指します。GUI もパッケージ管理も、ここには含めません。理由は後ろのセクション 5 で示します。

そして、もう一つ重要な区分が **「user mode」と「kernel mode」** です。これは権限の境界です。同じ CPU でも、user mode で走るコードと kernel mode で走るコードでは、できることが違う。次のセクションで掘ります。

---

## 3. user mode と kernel mode — そもそも何の境界か

ここは、Microsoft Learn の言い回しが端的なので引用します ─ 概念自体は OS によらない普遍的なものです。

> A processor in a computer that runs Windows operates in two different modes: user mode and kernel mode. The processor switches between these modes depending on the type of code it's executing.
>
> Applications operate in user mode. Core operating system components function in kernel mode.
>
> ─ [Microsoft Learn: User Mode and Kernel Mode](https://learn.microsoft.com/en-us/windows-hardware/drivers/gettingstarted/user-mode-and-kernel-mode)

ポイントは 2 つあります。

**(1) user mode のプロセスは互いに隔離されている。** 同じドキュメントから:

> When you start a user-mode application, Windows creates a process for the application. The process provides the application with a private virtual address space and a private handle table. Because an application's virtual address space is private, one application can't alter data that belongs to another application.

つまり Chrome が落ちても Firefox が落ちないし、どちらが落ちても OS は落ちない。これは **アドレス空間の独立** で保証されています。

**(2) kernel mode のコードは隔離されない。**

> All code that runs in kernel mode shares a single virtual address space. This means that a kernel-mode driver isn't isolated from other drivers and the operating system itself. If a kernel-mode driver accidentally writes to the wrong virtual address, data that belongs to the operating system or another driver could be compromised. **If a kernel-mode driver crashes, it causes the entire operating system to crash.**

「カーネルが落ちると OS ごと落ちる」のは、性能の都合ではなく **構造上の必然** です。kernel mode の住人(カーネル本体、ローダブルモジュール、ドライバ)は **同じ家** で暮らしているので、誰か一人が床を抜くと全員落ちる。

Linux なら kernel panic、Windows なら BSOD、macOS なら kernel panic。**名前は違っても起きていることは同じ** です。

そして、user mode と kernel mode の **行き来をする唯一の方法** が、次に説明する syscall です。

---

## 4. Linux カーネルが本当にやっていること — 4 つの責務

`kernel.org` の公式ドキュメントを開くと、Core-kernel subsystems として並んでいるものは、ほぼ次の 4 つに集約できます。

### 4.1 プロセス/スレッドのスケジューリング

CPU の数は有限。動きたいプロセスは無数にある。誰にどれだけ CPU を渡すか決めるのがスケジューラです。

Linux のスケジューラは、長らく CFS(Completely Fair Scheduler)を採用してきました。Linux 6.6 で **EEVDF**(Earliest Eligible Virtual Deadline First)へ置き換わっています。詳細は本稿の範囲外ですが、「Linux はスケジューラを大きく書き換えても上層から見えにくい」事実だけ覚えておくと良い ─ それは、スケジューラの責務が **抽象の裏側に閉じている** からです。

アプリ側は基本「`sched_yield` も `nice` も明示的には呼ばない」。ランタイムに任せています。

### 4.2 メモリ管理 (MM)

`kernel.org` の MM サブシステム説明:

> Linux memory management subsystem is responsible, as the name implies, for managing the memory in the system. This includes implementation of virtual memory and demand paging, memory allocation both for kernel internal structures and user space programs, mapping of files into processes address space and many other cool things.
>
> ─ [Memory Management - The Linux Kernel documentation](https://docs.kernel.org/admin-guide/mm/index.html)

主役は次の 4 つです。

- **仮想メモリ**: アプリは「自分専用の 64bit アドレス空間」を持っているように見える(実体は物理メモリの一部に動的にマップされている)
- **デマンドページング**: ページは触られた瞬間に物理メモリに読み込まれる(`mmap` の正体)
- **`mmap`**: ファイルやデバイスをメモリのように読み書きできる
- **ページキャッシュ**: 読み書きしたファイルは透過的に RAM にキャッシュされる

このうち **「アプリが意識せずに使っている」のがページキャッシュ** で、これがあるから fread が「2 回目は速い」。MM チューニングの大半は `/proc/sys/vm/` 配下から触れます(同 admin-guide が明示)。

### 4.3 VFS (Virtual File System)

`kernel.org` の言い回しは正確で美しい:

> VFS is the software layer in the kernel that provides the filesystem interface to userspace programs. It also provides an abstraction within the kernel which allows different filesystem implementations to coexist.
>
> ─ [Overview of the Linux Virtual File System](https://www.kernel.org/doc/html/v6.3/filesystems/vfs.html)

VFS は「ファイルシステムの **インターフェース** を提供する」層です。`open(2)`, `read(2)`, `write(2)`, `stat(2)`, `chmod(2)` の正体はここ。ext4 でも btrfs でも xfs でも、`open()` の呼び出し方は同じ ─ それを保証しているのが VFS です。

VFS が内部で使う dcache(dentry cache、パス文字列 → dentry の高速ルックアップ用キャッシュ)は **RAM 上のみに存在し、ディスクには保存されない**。ここは VFS docs に明記されています。

そして特筆すべきは、Linux における **「すべてはファイル」** の哲学が VFS で実装されていること。`/dev/sda`(ブロックデバイス)、`/proc/self/status`(プロセス情報)、`/sys/class/net/eth0/`(ネットワーク設定)、すべて `open()` `read()` で読める。

### 4.4 ネットワークスタック

TCP/IP、UDP、ソケット API、NIC との橋渡し。BSD ソケット API がカーネル内で実装されており、`socket(2)` `bind(2)` `listen(2)` `accept(2)` がそれぞれ syscall です。

ここは後編で「BSD ソケットは事実上の業界標準」として再登場します。

---

**この 4 つだけ覚えてください。** 「アプリが OS に依存している」という曖昧な主張は、ほぼこの 4 つに対する依存に分解できます。

---

## 5. Linux カーネルが「やらないこと」

公式 ToC に **入っていない** ものを並べると、カーネルの守備範囲がクッキリ見えます。

| やらないこと | 実際の担い手(Linux) |
|---|---|
| GUI(ウィンドウシステム) | X11 / Wayland(ユーザーランドのサーバー) |
| オーディオミキシング | PulseAudio / PipeWire(ユーザーランドのデーモン) |
| フォントレンダリング | FreeType / HarfBuzz(ユーザーランドのライブラリ) |
| パッケージ管理 | apt / dnf / pacman(ユーザーランドのツール) |
| ターミナルエミュレータ | gnome-terminal / alacritty(ユーザーランドのアプリ) |
| ログイン画面 | gdm / sddm / lightdm(ユーザーランドのデーモン) |
| シェル | bash / zsh / fish(ユーザーランドのアプリ) |

Linux ディストリビューションを起動して「画面が映る」までに、**Linux カーネル自体は画面を一度も描画していません**。フレームバッファの抽象は提供しているが、ピクセルを並べるのは Wayland コンポジタの仕事。

これは macOS / Windows との **最も大きな思想差** です。macOS では Quartz Compositor、Windows では DWM が **OS の一部として** 束ねられている。彼らは「ユーザーランドに後から接ぐ」ではなく、最初から OS のレイヤーに組み込まれている。

この差が後編で「コンテナで Linux アプリは持ち運べるが、Mac/Windows アプリは持ち運びにくい」議論につながります。Linux の GUI スタックは **取り外し可能** だから、コンテナで「画面なし」が成立する。

---

## 6. syscall とは何か — アプリとカーネルの fundamental interface

ここから user mode と kernel mode をつなぐ橋の話に入ります。

`man syscalls` の冒頭文:

> The system call is the fundamental interface between an application and the Linux kernel.
>
> ─ [syscalls(2) - man7.org](https://man7.org/linux/man-pages/man2/syscalls.2.html)

「**the** fundamental interface」と定冠詞付きで書いてあります。これ以外に正規ルートは無い、という強い宣言です。

ただし注意。`man intro 2` がもう一段補足してくれます:

> System calls are generally not invoked directly, but rather via wrapper functions in glibc (or perhaps some other library).
>
> ─ [intro(2) - man7.org](https://man7.org/linux/man-pages/man2/intro.2.html)

私たちが C で書く `open()` `read()` `write()` は、**syscall そのものではなく** glibc(または musl など)が提供する **wrapper function** です。

wrapper がやることは 3 ステップ:

1. 引数と syscall 番号を所定のレジスタに載せる
2. CPU を kernel mode に切り替える(trap 命令、x86_64 では `syscall` 命令)
3. 戻ってきた値をチェックし、負ならその絶対値を `errno` に入れ、呼び出し元には `-1` を返す

ここで重要なのは、レジスタの **割り当てがアーキごとに違う** こと。`syscall(2)` の man page に表があります(一部抜粋):

| Arch | syscall 番号 | 引数1〜6 |
|---|---|---|
| x86-64 | rax | rdi, rsi, rdx, r10, r8, r9 |
| i386 | eax | ebx, ecx, edx, esi, edi, ebp |
| arm64 | x8 | x0, x1, x2, x3, x4, x5 |
| riscv | a7 | a0, a1, a2, a3, a4, a5 |

アセンブラ前編で「呼出規約」を扱いました。あれは **関数呼び出しの規約** でした。ここでもう一段、**syscall 呼出規約** という別レイヤがあります。glibc は両方の規約を変換するブリッジコードを持っている。

そしてもう一つ ─ 同じ機能でも syscall が **複数バージョン共存** することがあります。man page に書いてある実例:

> `stat` の syscall は実は 3 つある: `__NR_oldstat`(sys_stat)、`__NR_stat`(sys_newstat)、`__NR_stat64`。

これは Linux カーネルが ABI 互換性を **シビアに維持している** 証拠でもあります。古いバイナリでも動くように、古い syscall は今もそのまま残してある。

---

## 7. `printf("hello\n")` を `strace` で分解する

ここまでを高級言語ユーザーの肌感に落とすために、`strace` を使います。`strace` はプロセスの syscall を全部覗ける Linux ツールです。

```bash
$ cat > hello.c <<'EOF'
#include <stdio.h>
int main(void) { printf("hello\n"); return 0; }
EOF
$ gcc -O0 hello.c -o hello
$ strace -e trace=write,openat,brk,execve,exit_group ./hello
```

出力(抜粋・整形):

```
execve("./hello", ["./hello"], ...) = 0
brk(NULL)                            = 0x...
openat(AT_FDCWD, "/etc/ld.so.cache", ...) = 3
openat(AT_FDCWD, "/lib/x86_64-linux-gnu/libc.so.6", ...) = 3
...
write(1, "hello\n", 6)               = 6
exit_group(0)
```

読み取れることは多いです:

- `printf("hello\n")` の中で **実際にカーネルに到達したのは `write(1, "hello\n", 6)` 1 回だけ**
- 文字列フォーマット("%d を埋める" のような)はすべて **glibc の中で完結** している(ユーザーランドの処理)
- 起動時に `execve` で実行ファイルが exec され、`/etc/ld.so.cache` と `libc.so.6` を `openat` で開いて動的リンクしている
- `brk` は heap を伸ばす syscall

ここで Python に置き換えてみます:

```bash
$ strace -e trace=write -c python3 -c 'print("hello")' 2>&1 | tail
```

`-c` は要約モード。`write` が **何十回も** 呼ばれているはず。Python インタプリタは起動時に多数の `.pyc` を読み込み、起動メッセージや終了処理でいくつもの `write` を発生させます。

ここで気づくべきは:

- **アプリは思っているより syscall を直接は叩いていない**。間に libc / 言語ランタイム / バッファリングが入る
- 逆に、起動時には **大量の syscall** が走っている(動的リンカ、`.pyc` ロード、共有ライブラリ探索)
- パイプ vs TTY の違いで `write` の **回数とサイズが変わる**(stdio が TTY 判定でバッファリング戦略を変える)

`strace -c` と `time` を組み合わせると、**「自分のスクリプトのどこが OS 側で詰まっているか」** が即座にわかります。これは高級言語ユーザーに最も実利のあるツールの一つです。

---

## 8. アプリは OS のどの面に依存しているか — 7 つの依存軸

カーネルの責務を 4 つに整理しました。今度はアプリ側から見て、「OS のどの **面** にどう依存しているか」を軸に分解します。

### 軸 1: syscall ABI

直接依存しているアプリはまれです。例外は Go ─ Go の標準ライブラリは Linux で libc を介さず、syscall を直接呼びます。これは「Go の実行ファイルが完全静的リンクで配れる」理由でもあります。

代償もあります。Linux の syscall ABI は安定していますが、**カーネルの新機能を Go から使うには runtime 側の更新が要る**。`io_uring` 対応がランタイムによってまちまちな理由はここ。

### 軸 2: libc(または相当ライブラリ)

ほぼ全アプリが間接依存しています。問題は、**libc は 1 つではない**:

- **glibc**: ほとんどの Linux ディストロのデフォルト
- **musl**: Alpine Linux のデフォルト。小さい、静的リンクしやすい
- **bionic**: Android のデフォルト
- **Windows MSVCRT / UCRT**: Windows
- **Apple libSystem**: macOS

「Docker で Alpine ベースイメージを使ったら Python が動かなかった」事故の正体はだいたい glibc vs musl の差です。`numpy` の wheel は CPython × glibc を前提に配布されていることが多い ─ `manylinux` という規格はこの差を吸収する仕組みです。

### 軸 3: VFS の意味論

ここが **後編の主役** になります。

- パス区切り文字(`/` vs `\`)
- ケース感度(`Foo.txt` と `foo.txt` を同じと見るか別と見るか)
- `rename` が atomic か
- `fsync` の保証粒度
- ハードリンク / シンボリックリンクの扱い
- 拡張属性 / ACL

POSIX が定めていない領域が多く、OS どころか **同じ OS 上の別ファイルシステム** でも挙動が違います。

### 軸 4: プロセスモデル

`fork` / `exec` を使うか、`CreateProcess` 系を使うか。これも後編の主役です。Python の `multiprocessing` が macOS と Linux と Windows で挙動が違う根本原因。

### 軸 5: シグナル / IPC

SIGTERM、SIGINT、パイプ、Unix domain socket、共有メモリ、メッセージキュー。POSIX の System Interfaces 巻でかなり広く規定されていますが、Windows は別世界(イベント、Named Pipe、Mailslot)です。

### 軸 6: ネット API

BSD ソケット API は事実上の業界標準。Windows の Winsock も同じ関数名で揃えています。**「差が小さい領域」の代表選手** です。

### 軸 7: 時刻と乱数

`clock_gettime(CLOCK_MONOTONIC)` と `getrandom(2)` は POSIX には完全には入っていないが、3 OS とも相当 API を持っています。意外と揃っている領域。

---

**前編で押さえてほしい全体像** は次の格子です。

```
            責務(カーネル側)             依存軸(アプリ側)
            ───────────────────────       ──────────────────────
            ① プロセス/スレッド           ① syscall ABI
            ② メモリ管理                  ② libc
            ③ VFS                         ③ VFS 意味論
            ④ ネットワーク                ④ プロセスモデル
                                          ⑤ シグナル/IPC
                                          ⑥ ネット API
                                          ⑦ 時刻/乱数
```

後編では、この格子を **横軸に Linux / macOS / Windows** を取って、「どのマスで色が割れるか」を見ます。

---

## 9. 高級言語ランタイムは OS をどこまで薄めているか

軽くだけ触れて、後編に渡します。

- **CPython の `os` モジュール**: ほぼ syscall の薄いラッパ。「OS 差は隠さない」設計。`os.fork` は Windows で `AttributeError`、`os.path` のセパレータは `/` だったり `\` だったり
- **Node.js の libuv**: epoll / IOCP / kqueue を統一 event loop に寄せる。`fs.readFile` のレベルでは差はほぼ見えない
- **Go の runtime**: Linux では libc を介さず syscall を直接。`epoll` / `kqueue` / `IOCP` を runtime が直接統合し、goroutine スケジューラと結合
- **JVM の java.nio**: `Path` がプラットフォーム差を吸う。`Files.move` の atomicity 保証は OS により異なる
- **Rust の `std`**: `std::fs` `std::net` は薄いラッパ寄り。async は Tokio / async-std が io_uring / IOCP / kqueue を選択

共通項として:

> ランタイムは **ベストエフォートで** OS 差を吸収する。
> 完全には吸収できないし、**そもそも吸収しないと決めている軸もある**。

吸収しないと決めているのは、たとえば「`fork` の有無」。これは隠せないし隠してはいけない、というのが多くのランタイムの立場です。

---

## 10. 前編まとめと、後編への接続

前編で確立した語彙:

1. **「Linux」はカーネルの名前**。Ubuntu などは「カーネル + ユーザーランド」の組合せ
2. **user mode と kernel mode** は権限の境界。kernel mode は単一アドレス空間で隔離が無い
3. **カーネルの責務は 4 つ**: スケジューラ / MM / VFS / ネット
4. **カーネルがやらないこと**: GUI / オーディオ / フォント / パッケージ管理 / シェル(ユーザーランドが担う)
5. **syscall はアプリとカーネルの fundamental interface**。私たちが呼ぶのは大抵 libc wrapper
6. **アプリの OS 依存は 7 軸に分解できる**(syscall / libc / VFS / プロセス / IPC / ネット / 時刻乱数)

そして後編の問い:

- POSIX があるのに、なぜ「移植性」は今でも難しいのか
- Linux / macOS / Windows でカーネル設計の **どこが違って、どこが同じ** か
- 差が大きい領域(プロセスモデル、パス、async I/O = io_uring vs IOCP vs kqueue)
- 差が小さい領域(BSD ソケット、UTF-8、POSIX subset)
- WSL2 / コンテナ / Rosetta は移植性の地図をどう書き換えたか

→ [Linuxを地図に、OSを読む(後編) — Linux / macOS / Windows、アプリ視点で『同じ』と『違う』はどこか](./os_layer_from_linux_part2)

---

## 参考

- [The Linux Kernel documentation - Memory Management](https://docs.kernel.org/admin-guide/mm/index.html)
- [Overview of the Linux Virtual File System](https://www.kernel.org/doc/html/v6.3/filesystems/vfs.html)
- [Linux Kernel docs v5.14 ToC](https://www.kernel.org/doc/html/v5.14/)
- [syscalls(2) - man7.org](https://man7.org/linux/man-pages/man2/syscalls.2.html)
- [intro(2) - man7.org](https://man7.org/linux/man-pages/man2/intro.2.html)
- [syscall(2) - man7.org](https://man7.org/linux/man-pages/man2/syscall.2.html)
- [Microsoft Learn - User Mode and Kernel Mode](https://learn.microsoft.com/en-us/windows-hardware/drivers/gettingstarted/user-mode-and-kernel-mode)

連載:

- [アセンブラを書かない人のためのアセンブラ — 高級言語が抽象化した 3 つの問題(前編)](./assembly_for_high_level_users_part1)
- [アセンブラを書かない人のためのアセンブラ(後編)](./assembly_for_high_level_users_part2)
- [Python C 拡張の地図](./python_c_extensions_internals)
- Linuxを地図に、OSを読む(前編) — 本記事
- [Linuxを地図に、OSを読む(後編)](./os_layer_from_linux_part2)
