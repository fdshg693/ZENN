---
title: "Linuxを地図に、OSを読む(前編) — アプリは『どこから先』をOSに任せているのか"
status: plan
---

## 想定読者と前提

- 普段は Python / Go / JavaScript / Rust / Java / C# などの **高級言語** で仕事をしているエンジニア
- `syscall` `fork` `epoll` `mmap` `/proc` などの単語は聞いたことがあるが、`strace` で何が起きているかを 30 秒で説明できない人を含む
- 学部の OS 演習で「kernel mode と user mode」「プロセスとスレッド」「仮想メモリ」あたりは触ったが、その後 5〜10 年触っていない人
- 連載中の前提: [アセンブラを書かない人のためのアセンブラ(前編)](./assembly_for_high_level_users_part1) で **ISA・呼出規約・ABI** を、[後編](./assembly_for_high_level_users_part2) で **コンパイラの代行作業** を扱った前提

前提知識: 関数、プロセス、ファイルディスクリプタ、仮想メモリ、共有ライブラリ の概念名だけは聞いたことがあるレベル。C のソース読解までは要求しない。

## この記事が答える問い

1. 「OS」と「カーネル」と「ユーザーランド」はどこで切れるのか
2. Linux カーネルが **本当にやっていること** は何で、**やっていないこと** は何か(GUI、音、フォント、パッケージ管理は OS の仕事ではない)
3. user mode と kernel mode の境界とは、何の境界か
4. `printf("hello")` を 1 行書いたとき、コードはどこまで自前で、どこから OS の責任になるか
5. システムコールと libc 関数はどう違うのか
6. アプリは OS のどの面に、どの程度依存しているのか(syscall, libc, VFS, ネット, スケジューラ, 仮想メモリ, IPC, 端末)

## 扱う / 扱わない

- **扱う**: Linux カーネルのサブシステム責務(プロセススケジューラ / メモリ管理 / VFS / ネットワークスタック)、user mode と kernel mode の境界、syscall ABI と libc wrapper の関係、`strace` で `printf` を分解、`/proc` `/sys` の役割、カーネルがやらないこと(GUI / オーディオ / パッケージング)とその担い手、高級言語ランタイムが薄める層
- **扱わない**: カーネル開発、デバドラ実装、SELinux / AppArmor の詳細、リアルタイム / 組込み OS、特定ファイルシステム実装の細部(ext4, btrfs, xfs)、Linux ディストロ比較、systemd 詳細

## セクション構成

### 1. なぜ今「OS の地図」を引き直すのか

- 連載前 2 本で ISA → 呼出規約 → コンパイラの代行作業まで降りた
- そこからもう一段上にある「カーネルとアプリの境界線」を扱うのが本稿
- 主張: 高級言語は ABI を抽象化したが、**OS の責務境界そのものは抽象化していない**。だから「ファイル名の大文字小文字」「`fork` の有無」「`epoll` か `IOCP` か」のような **OS の地肌が漏れる** 場面が消えない
- 根拠: 連載前作 + 一般論(別途引用なし)

### 2. 「OS」と「カーネル」と「ユーザーランド」を切り直す

- 多くの人が「OS = Linux」と言うとき、実は Linux **ディストリビューション**(カーネル + libc + coreutils + シェル + パッケージマネージャ + デスクトップ環境)を指している
- 厳密には「Linux」は **カーネルそのもの** の名前
- カーネルは「特権命令で動くコード」、ユーザーランドは「普通のプロセスとして動くコード」
- 主張: この記事で「OS の責務」と言ったら、原則 **カーネル + 最小ユーザーランド(libc, init)** を指す。デスクトップ環境やパッケージマネージャは含めない
- 根拠: `kernel.org` の admin-guide が Core-kernel subsystems として列挙する範囲(MM、VFS、namespaces、cgroup、scheduler、BPF など)
  - [The Linux Kernel documentation - Memory Management](https://docs.kernel.org/admin-guide/mm/index.html)
  - [Linux Kernel docs v5.14 ToC](https://www.kernel.org/doc/html/v5.14/)

### 3. user mode と kernel mode — そもそも何の境界か

- 主張: これは「権限の境界」であって「コードの大きさの境界」ではない。kernel mode のコードは互いに隔離されない単一アドレス空間に住んでいる
- Microsoft Learn の言い回しがそのまま使える: 「user mode のプロセスは private virtual address space と private handle table を持つ」「kernel mode のコードは a single virtual address space を共有する」
- 帰結: kernel mode コードがクラッシュすると OS 全体が落ちる(= BSOD / Linux panic)。user mode のアプリがクラッシュしても OS は落ちない
- 根拠:
  - [Microsoft Learn - User Mode and Kernel Mode](https://learn.microsoft.com/en-us/windows-hardware/drivers/gettingstarted/user-mode-and-kernel-mode)
  - 補強: Linux MM admin-guide の `/proc/sys/vm/` 公開モデル(カーネル内部状態が user mode から read-only に見える) [docs.kernel.org/admin-guide/mm](https://docs.kernel.org/admin-guide/mm/index.html)

### 4. Linux カーネルが本当にやっていること — 4 つの責務

公式 docs の ToC を機械的に並べると、4 つの大柱が見える。

1. **プロセス/スレッドのスケジューリング**: 限られた CPU に対する fair な配分
2. **メモリ管理 (MM)**: 仮想メモリ、デマンドページング、`mmap`、ページキャッシュ
3. **VFS (Virtual File System)**: ファイルシステムの抽象。`open` `read` `write` `stat` `chmod` の正体
4. **ネットワークスタック**: TCP/IP, ソケット API, NIC との橋渡し

- 主張: アプリが「OS に依存している」と言うとき、ほぼこの 4 つに対する依存に分解できる
- 根拠:
  - [kernel.org docs v5.14 — Filesystems / MM / BPF / USB / PCI / SCSI](https://www.kernel.org/doc/html/v5.14/)
  - [VFS overview](https://www.kernel.org/doc/html/v6.3/filesystems/vfs.html) — 「software layer in the kernel that provides the filesystem interface to userspace programs」
  - VFS の例: dcache が RAM 上にのみ存在しディスクには無い等の具体話
  - [MM admin-guide](https://docs.kernel.org/admin-guide/mm/index.html) — virtual memory、demand paging、mapping of files into process address space

### 5. Linux カーネルが「やらないこと」

公式 ToC に **入っていない** ものを並べると、「OS の仕事ではない」ことが分かる。

- **GUI**: X11 / Wayland はユーザーランドのサーバー
- **オーディオミキシング**: PulseAudio / PipeWire はユーザーランドのデーモン
- **フォントレンダリング**: FreeType / HarfBuzz はユーザーランドのライブラリ
- **パッケージ管理**: apt / dnf / pacman はユーザーランドのツール
- **ターミナルエミュレータ**: gnome-terminal, alacritty もユーザーランド
- 主張: macOS や Windows との **最も大きな思想差** はここにある。macOS / Windows は GUI とオーディオが OS の一部として束ねられている
- 根拠: kernel.org の ToC に GUI / audio / packaging が出てこないという **間接根拠**。直接根拠としては freedesktop.org / ALSA / PipeWire / Debian Policy 等が後編か補足脚注の対象

### 6. syscall とは何か — アプリとカーネルの fundamental interface

- man7 の言い回し: 「The system call is the fundamental interface between an application and the Linux kernel.」
- C コードの `open()` は syscall **そのもの** ではなく、glibc が提供する **wrapper function**
- wrapper がやることは 3 ステップ: ①引数と syscall 番号をレジスタに載せる、②カーネルへ trap、③戻り値をチェックして errno を立てる
- syscall は失敗時に「a negative error number」を返し、glibc が `errno` に絶対値を入れ、呼び出し元には `-1` を返す
- アーキごとに引数渡しのレジスタが違う: x86-64 は rdi/rsi/rdx/r10/r8/r9、arm64 は x0–x5(= アセンブラ前編の System V vs AAPCS64 の話の延長)
- 主張: アセンブラ編で見た「呼出規約」は **libc 内部** にもあり、libc → kernel への呼出にはさらにもう一段別の「syscall 呼出規約」が存在する
- 根拠:
  - [syscalls(2)](https://man7.org/linux/man-pages/man2/syscalls.2.html)
  - [intro(2)](https://man7.org/linux/man-pages/man2/intro.2.html)
  - [syscall(2)](https://man7.org/linux/man-pages/man2/syscall.2.html) — レジスタ一覧の表

### 7. `printf("hello\n")` を `strace` で分解する

- 高級言語ユーザーが一番つかみやすい題材
- 「文字列フォーマット」は libc(ユーザーランド)、「文字列を端末に出す」は `write(2)` syscall(カーネル)
- 主張: アプリは思っているより syscall を **直接** は叩いていない。間に libc / 言語ランタイム / バッファリングが入る
- 補強: 同じ題材で `python -c 'print("hello")'` を `strace` した時に何回 `write(2)` が呼ばれるか、`stdout` がパイプか TTY かで動作がどう変わるか
- 根拠: `strace` で観測する手元実験 + [syscalls(2)](https://man7.org/linux/man-pages/man2/syscalls.2.html)
- 注記: 同じ題材で stat(2) が 3 バージョン共存している話(`__NR_oldstat`, `__NR_stat`, `__NR_stat64`)を補足コラムに

### 8. アプリは OS のどの面に依存しているか — 7 つの依存軸

アプリが OS に依存する **面** を列挙して、それぞれ「どれくらい強く依存しているか」を概観する。

1. **syscall ABI**: 直接依存はまれ。Go ランタイムは Linux で直接叩く例外
2. **libc**: ほぼ全アプリが間接依存(musl と glibc の差異は実在)
3. **VFS の意味論**: パス、case sensitivity、`rename` の atomicity、`fsync` 等
4. **プロセスモデル**: `fork` `exec` 前提か、`CreateProcess` 前提か
5. **シグナル / IPC**: SIGTERM ハンドリング、パイプ、Unix domain socket
6. **ネット API**: BSD ソケットはほぼ業界標準
7. **時刻と乱数**: `CLOCK_MONOTONIC`, `getrandom(2)`

- 主張: 後編で OS 差を扱うときの **比較軸** がこの 7 つになる
- 根拠: 上記 syscall man-page 群 + VFS overview

### 9. 高級言語ランタイムは OS をどこまで薄めているか

- CPython の `os` モジュールが何をしているか
- Node.js の `libuv` が IOCP / epoll / kqueue をどう統一しているか
- Go の `runtime` が `epoll` を直接叩いている話(libc を介さない)
- JVM の `java.nio` がどう吸収するか
- 主張: ランタイムは **「ベストエフォートで」 OS 差を吸収する**。完全には吸収できない(後編で示す)
- 根拠: 一般論 + 各ランタイムの公式 docs(本文では脚注リンクで足す程度)
- 注記: ここは「軽く触れて後編に渡す」つなぎセクション

### 10. 前編まとめと、後編への接続

- 前編の結論: OS = カーネルが提供する **「4 つの責務 × 7 つの依存軸」のサーフェス**。アプリはこの面に乗っている
- 後編で扱う問い: 同じサーフェスを Linux / macOS / Windows が **どう違って提供しているか**、その差をアプリ開発者はどこで踏むか
- リンク予告: `Linux を地図に、OS を読む(後編)`

## 根拠 URL まとめ(前編で主に使うもの)

- [The Linux Kernel documentation - Memory Management](https://docs.kernel.org/admin-guide/mm/index.html)
- [Overview of the Linux Virtual File System](https://www.kernel.org/doc/html/v6.3/filesystems/vfs.html)
- [Linux Kernel docs v5.14 ToC](https://www.kernel.org/doc/html/v5.14/)
- [syscalls(2) - man7.org](https://man7.org/linux/man-pages/man2/syscalls.2.html)
- [intro(2) - man7.org](https://man7.org/linux/man-pages/man2/intro.2.html)
- [syscall(2) - man7.org](https://man7.org/linux/man-pages/man2/syscall.2.html)
- [Microsoft Learn - User Mode and Kernel Mode](https://learn.microsoft.com/en-us/windows-hardware/drivers/gettingstarted/user-mode-and-kernel-mode)

調査ファイル:
- `temp/os_from_linux_lens/extract_kernel_subsystems.json`
- `temp/os_from_linux_lens/extract_syscall_basics.json`
- `temp/os_from_linux_lens/extract_windows_wsl.json`(user mode / kernel mode 部分)
- `temp/os_from_linux_lens/facts.md`(Part 1 セクション)
