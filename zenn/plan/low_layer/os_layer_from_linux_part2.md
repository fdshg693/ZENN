---
title: "Linuxを地図に、OSを読む(後編) — Linux / macOS / Windows、アプリ視点で『同じ』と『違う』はどこか"
status: plan
---

## 想定読者と前提

- 前編 [Linuxを地図に、OSを読む(前編)](./os_layer_from_linux_part1) を読んだ前提。OS の責務(スケジューラ / MM / VFS / ネット)、user/kernel mode の境界、syscall と libc の関係 を共通言語として使う
- 普段は Python / Go / JavaScript / Rust / Java / C# などの高級言語で仕事をしているエンジニア
- Linux / macOS / Windows のうち少なくとも 2 つで開発・本番運用の経験があり、「ローカルでは動くが本番で動かない」「他人の Mac で同じコードがリポジトリから動かない」事故を 1 度以上踏んだことがある人

## この記事が答える問い

1. POSIX があるのに、なぜ「移植性」は今でも難しいのか
2. Linux / macOS(XNU) / Windows(NT) でカーネル設計の **どこが違って、どこが同じ** か
3. 差が **大きい** 領域はどこか(プロセスモデル、ファイルパス、改行コード、権限、ネイティブ非同期 I/O = io_uring vs IOCP vs kqueue)
4. 差が **小さい** 領域はどこか(BSD ソケット、UTF-8、POSIX の subset、コンテナ越しで見たとき)
5. 高級言語ランタイム(CPython、Node.js、Go、JVM)はその差をどう吸収しているか、何を吸収していないか
6. WSL2 / コンテナ / Rosetta は「移植性の地図」をどう書き換えたか

## 扱う / 扱わない

- **扱う**: POSIX.1-2024(Issue 8)のスコープと限界、Windows NT カーネルの managers 構造、macOS XNU(Mach + BSD + I/O Kit)、native async I/O 3 種(io_uring / IOCP / kqueue)の設計差、ファイルパスとケース感度、`fork` 問題、コンテナ(namespaces + cgroups)が薄める層、WSL2 が真の Linux カーネルを VM で走らせていること、ランタイム吸収層の限界
- **扱わない**: 各 OS の歴史的経緯の詳細、特定ファイルシステムの内部実装、Hyper-V / KVM の内部、Mach IPC のメッセージ形式、Apple Silicon の Rosetta 2 内部、Android、Linux 以外の Unix(Solaris, AIX)、商用 RTOS

## セクション構成

### 1. 前編からの接続 — 4 つの責務 × 7 つの依存軸を 3 OS で並べる

- 前編で出した「OS の責務 4 つ(スケジューラ / MM / VFS / ネット)」と「アプリ依存軸 7 つ(syscall / libc / VFS 意味論 / プロセスモデル / IPC / ネット / 時刻乱数)」を縦軸に置く
- 横軸に Linux / macOS / Windows を取ると、**どこで色が割れるか** が見える
- 主張: 「OS 差」は曖昧な総論ではなく、**この格子のどのマスで色が割れるか** という具体問題に分解できる
- 根拠: 前編

### 2. POSIX があるのに、なぜ移植性は難しいのか

- POSIX.1-2024 = Open Group Base Specifications Issue 8 = IEEE Std 1003.1-2024 の正体
- POSIX は「**ソースコードレベル** の移植性」を狙った標準。バイナリ互換ではない
- POSIX 自身が「POSIX 準拠 ≠ 完全移植」を明示している
- 値や挙動が「unspecified」とされる箇所が多数残されている(=実装ごとの差を許容している)
- 主張: 「Mac は Unix だから Linux と同じ」「`bash` があれば動く」は、POSIX 自身の文書が **否定している** 命題
- 根拠:
  - [Open Group Base Specifications Issue 8 - Introduction](https://pubs.opengroup.org/onlinepubs/9799919799/basedefs/V1_chap01.html) — Issue 8 = IEEE Std 1003.1-2024 の正式名称、ソースコード移植性の主旨、shall/should/may/can の用語定義、unspecified の存在

### 3. カーネル設計の見取り図 — Linux vs Windows NT vs macOS XNU

3 OS のカーネル構造を **同じ語彙** で並べる。

- **Linux**: モノリシック、サブシステム単位の module(MM, VFS, net, scheduler, BPF, USB, PCI, SCSI ...)、ローダブルカーネルモジュールで拡張
- **Windows NT**: kernel-mode は「managers」の集合(Object Manager, Memory Manager, Process and Thread Manager, I/O Manager, Plug and Play Manager, Power Manager, Configuration Manager, Kernel Transaction Manager, Security Reference Monitor)。Object Manager がファイル/デバイス/同期/レジストリキーを **統一オブジェクト** として扱う
- **macOS XNU**: 「Mach kernel + BSD + I/O Kit + ファイルシステム + ネットワーク」のハイブリッド。Mach が低レベル(IPC、VM、scheduler)、BSD が「OS personality APIs」(POSIX 互換 API のレイヤ)、I/O Kit がドライバフレームワーク
- 主張: 同じ「OS の 4 責務」を全 OS が提供しているが、**境界の引き方** が違う。特に Windows の Object Manager の発想は Unix 系の「all is a file」と対をなす設計
- 根拠:
  - [Microsoft Learn - Kernel-Mode Driver Architecture](https://learn.microsoft.com/en-us/windows-hardware/drivers/kernel/) — managers の列挙
  - [Apple Developer - Kernel Architecture Overview](https://developer.apple.com/library/archive/documentation/Darwin/Conceptual/KernelProgramming/Architecture/Architecture.html) — Mach の役割「untyped IPC, RPC, SMP scheduler, real-time, VM, pagers, modular」、BSD の役割「OS personality APIs」
  - PE フォーマットの IMAGE_SUBSYSTEM 定数: NATIVE / WINDOWS_GUI / WINDOWS_CUI / **OS2_CUI / POSIX_CUI** / EFI_APPLICATION 等が今でも定義されているという歴史的根拠 [PE Format](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)
  - Sysinternals「Object Manager 名前空間は a namespace not unlike the Virtual File System (VFS) namespace present on UNIX implementations」 [Sysinternals Newsletter Vol. 2, No. 2](https://learn.microsoft.com/en-us/sysinternals/resources/archive/v02n02)

### 4. 差が「大きい」領域(1) — プロセスモデル: `fork` 問題

- POSIX は `fork(2)` を持つ。Windows は持たない(`CreateProcess` は全く別の意味論)
- macOS は `fork` を持つが、Apple は「Cocoa/CF を初期化したプロセスでの fork は Apple フレームワークが対応していない」スタンス(macOS 上で Python multiprocessing が壊れがちな根本原因)
- 主張: 「`fork` の有無」はランタイム実装に **直接** 染み出す。Python の multiprocessing が `fork` / `spawn` / `forkserver` を切り替える理由はここ
- 根拠:
  - PEP 703 / Python docs の `multiprocessing` セクション(別途引用 — 本文時に検索可能)
  - 前編で扱った user mode / kernel mode 境界(プロセスの分離)
  - Windows: `CreateProcess` は別 API、`fork` 相当は無い(Microsoft Learn 一般論)
- 注記: ここは公式直接引用が手薄。本文段階で `multiprocessing` の Python docs を引いて補強する

### 5. 差が「大きい」領域(2) — ファイルパスとケース感度

- Windows でファイル名に使えない文字: `< > : " / \ | ? *`、NUL(0)、ASCII 1〜31
- パス区切りはバックスラッシュ(UNC は `\\server\share`)
- 「Do not assume case sensitivity. consider OSCAR, Oscar, oscar to be the same, even though some file systems (such as a POSIX-compliant file system) may consider them as different.」
- NTFS は POSIX semantics for case sensitivity を **サポートするがデフォルトではない**
- ドライブレターも case-insensitive(`D:\` と `d:\` は同じ)
- `MAX_PATH` 問題は .NET Framework 固有。.NET 5+ は長いパスを暗黙にハンドル
- `\\?\` プレフィックスはパス正規化を skip し MAX_PATH を回避する(暗黙経路に限る)
- WSL は per-directory case sensitivity を設定可能。WSL2 では子ディレクトリが継承するが WSL1 では継承しない
- macOS のデフォルト APFS は case-insensitive(ただし case-preserving)、HFS+ も同様。`git` リポジトリのケース違いファイルでハマる王道パターン
- 主張: 「テスト環境では動いた」事故の **過半は VFS 意味論の差** が原因
- 根拠:
  - [Naming Files, Paths, and Namespaces](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)
  - [File path formats on Windows systems - .NET](https://learn.microsoft.com/en-us/dotnet/standard/io/file-path-formats)
  - [WSL Case Sensitivity](https://learn.microsoft.com/en-us/windows/wsl/case-sensitivity)

### 6. 差が「大きい」領域(3) — ネイティブ非同期 I/O 三国志

3 OS の **native async I/O** は設計思想が異なる。これを並べると 3 OS の哲学差が一番くっきり出る。

- **Linux: io_uring** — ユーザー空間とカーネル空間で共有される **ring buffer** が通信の主モード(syscall ではない)。kernel ≥ 5.4 では SQ/CQ を 1 mmap でジョイントマップ。`io_uring_setup(2)` と `io_uring_enter(2)` の 2 syscall のみ。glibc wrapper はまだ無く `syscall()` ラップが man page で例示される
- **Windows: IOCP (I/O Completion Ports)** — **completion-based** モデル。スレッドプールが `GetQueuedCompletionStatus` で待ち、I/O 完了 packet が FIFO で配信される。スレッド解放は LIFO、推奨スレッド数はプロセッサ数の最低 2 倍
- **macOS/BSD: kqueue** — **readiness-based** モデル(epoll に近いが、fd 以外も watch できる: signal, timer, process, vnode...)。`kqueue()` で fd を取り `kevent()` で登録/取り出し。fork で継承されない
- 主張: 「非同期 I/O」と一言で言うが、**readiness vs completion** で API の形が根本的に違う。Node.js (`libuv`)、Tokio、Go の `netpoll` がやっているのはこの差の吸収
- 根拠:
  - [io_uring(7) - man7.org](https://man7.org/linux/man-pages/man7/io_uring.7.html)
  - [I/O Completion Ports - Win32](https://learn.microsoft.com/en-us/windows/win32/fileio/i-o-completion-ports)
  - [Synchronous and Asynchronous I/O - Win32](https://learn.microsoft.com/en-us/windows/win32/fileio/synchronous-and-asynchronous-i-o)
  - [kqueue(2) - Apple Manual Pages](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/kqueue.2.html)

### 7. 差が「小さい」領域 — BSD ソケット、UTF-8、POSIX subset

- BSD ソケット API は事実上の業界標準。Windows の Winsock も `socket() / bind() / listen() / accept()` を踏襲(関数名同じ、若干引数違い)
- UTF-8 はテキスト相互運用のデファクト。ただし Windows API の歴史的事情で UTF-16 が残るレイヤがある
- POSIX **subset** (open/read/write/close/stat/fork/exec/pipe ...) は Linux と macOS でほぼ同じに使える。`ifdef` で書き分け不要な範囲が広い
- 主張: 「差が小さい領域」では、**抽象を 1 枚噛ます** だけで OS 差を吸収できる。これが「ネット系の Python ライブラリは大体 3 OS で動く」の理由
- 根拠:
  - BSD ソケット: 一般論
  - [POSIX Base Specifications](https://pubs.opengroup.org/onlinepubs/9799919799/basedefs/V1_chap01.html) — System Interfaces 巻が POSIX subset の正本

### 8. 高級言語ランタイムはどこを吸収し、どこを吸収できないか

各ランタイムが何を吸収しているか、具体に並べる。

- **CPython**: `os` モジュールはほぼ syscall の薄いラッパ。OS 差は **漏らす** 設計。`os.fork` は Windows で無い、`os.path` のセパレータは OS 依存
- **Node.js / libuv**: epoll / IOCP / kqueue を統一 event loop に寄せる。`fs.readFile` レベルでは差はほぼ見えない。シェル相互運用は漏れる
- **Go の `net` / `runtime`**: Linux では libc を介さず syscall を直接呼ぶ。`epoll` / `kqueue` / `IOCP` を runtime が直接統合
- **JVM**: `java.nio` (NIO.2) で吸収。`Path` がプラットフォーム差を吸う。`Files.move` の atomicity 保証は OS により異なる
- **Rust**: `std::fs` `std::net` は CPython と同じく薄いラッパ寄り。async ランタイムは Tokio / async-std が io_uring / IOCP / kqueue を選択
- 主張: ランタイムが吸収するのは **「責務 × 軸」の格子の一部のマスのみ**。吸収していないマスがアプリ開発者に漏れる
- 根拠: 各ランタイムの公式 docs(本文時にリンク)+ 前編

### 9. WSL2 / コンテナ / Rosetta — 移植性地図の書き換え

- **WSL2** は「Hyper-V のサブセット (Virtual Machine Platform) を使った軽量 utility VM の中で **本物の Linux カーネル** を動かす」。WSL1 の syscall 翻訳 layer とは設計が違う。フル syscall 互換
- WSL2 の各ディストロは VM 内で **コンテナとして隔離** される(ネットワーク・カーネル・メモリは共有、PID/Mount/User/Cgroup namespace は分離)
- WSL2 ディストロはホスト Windows と **別の IP アドレス** を持つ
- **コンテナ** (Docker/Podman) は Linux 上では namespaces + cgroups の組合せ。Mac / Windows の Docker Desktop は **実際には軽量 Linux VM 内** で動いている
- **Rosetta 2** は ISA レベル(x86_64 → ARM64)の翻訳で、**OS 差は埋めない**
- 主張: WSL2 と Docker Desktop の登場で「Mac / Windows でも Linux アプリが普通に動く」は **本当に Linux カーネルを動かしているから動く** のであって、移植性が向上したわけではない
- 根拠:
  - [What is WSL](https://learn.microsoft.com/en-us/windows/wsl/about) — utility VM、フル syscall 互換、コンテナ隔離、共有/独立 namespace の明示
  - [WSL FAQ](https://learn.microsoft.com/en-us/windows/wsl/faq) — Virtual Machine Platform、Hyper-V サブセット、別 IP、nested virtualization

### 10. 結論 — アプリ開発者が押さえるべき OS 差の「優先順位」

3 OS で開発・配布するときに、注意の優先順位を提案する。

1. **最優先**: VFS 意味論(パス、ケース感度、改行、`fsync`、`rename` の atomicity)
2. **次点**: プロセスモデル(`fork` / `spawn`)、シグナル(SIGTERM の作法)、async I/O モデル
3. **中位**: 権限モデル(POSIX 権限 vs ACL)、シェル(PowerShell vs bash)、行末文字
4. **下位**: ネット API、BSD ソケット、UTF-8
5. **「ほぼ気にしなくて良い」**: コンテナや WSL2 の中に閉じる限り(ただし外との境界で噴き出す)

- 主張: OS 差を「全部抽象化しろ」は無理。**漏れる場所を予測** して、その場所だけ抽象化を入れるのが現実解
- 根拠: 本記事全体

### 11. 連載まとめ

- アセンブラ編 → C 拡張編 → OS 編(前 / 後)で、「アプリの足場」を下から ISA → ABI → カーネル責務 → OS 差まで地図化したことになる
- 次回テーマ予告: コンテナ詳細、または ARM64 / Apple Silicon 時代の ABI 変動

## 根拠 URL まとめ(後編で主に使うもの)

- [Open Group Base Specifications Issue 8 - Introduction](https://pubs.opengroup.org/onlinepubs/9799919799/basedefs/V1_chap01.html)
- [Microsoft Learn - Kernel-Mode Driver Architecture](https://learn.microsoft.com/en-us/windows-hardware/drivers/kernel/)
- [Microsoft Learn - PE Format (IMAGE_SUBSYSTEM)](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)
- [Apple Developer - Kernel Architecture Overview](https://developer.apple.com/library/archive/documentation/Darwin/Conceptual/KernelProgramming/Architecture/Architecture.html)
- [io_uring(7) - man7.org](https://man7.org/linux/man-pages/man7/io_uring.7.html)
- [I/O Completion Ports - Win32](https://learn.microsoft.com/en-us/windows/win32/fileio/i-o-completion-ports)
- [Synchronous and Asynchronous I/O - Win32](https://learn.microsoft.com/en-us/windows/win32/fileio/synchronous-and-asynchronous-i-o)
- [kqueue(2) - Apple Manual Pages](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/kqueue.2.html)
- [Naming Files, Paths, and Namespaces](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)
- [File path formats on Windows systems - .NET](https://learn.microsoft.com/en-us/dotnet/standard/io/file-path-formats)
- [WSL Case Sensitivity](https://learn.microsoft.com/en-us/windows/wsl/case-sensitivity)
- [What is WSL](https://learn.microsoft.com/en-us/windows/wsl/about)
- [WSL FAQ](https://learn.microsoft.com/en-us/windows/wsl/faq)

調査ファイル:
- `temp/os_from_linux_lens/extract_async_io_apis.json`
- `temp/os_from_linux_lens/extract_windows_wsl.json`
- `temp/os_from_linux_lens/extract_path_semantics.json`
- `temp/os_from_linux_lens/extract_macos_posix.json`
- `temp/os_from_linux_lens/facts.md`(Part 2 セクション)
