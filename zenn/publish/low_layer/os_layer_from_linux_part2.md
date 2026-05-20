---
title: "Linuxを地図に、OSを読む(後編) — Linux / macOS / Windows、アプリ視点で『同じ』と『違う』はどこか"
emoji: "🗺️"
type: "tech"
topics: ["linux", "os", "posix", "architecture", "lowlevel"]
published: false
---

## この記事について

前編 [Linuxを地図に、OSを読む(前編)](./os_layer_from_linux_part1) で、Linux を題材に「OS の責務」と「アプリの OS 依存軸」を整理しました。要約:

- **カーネルの責務 4 つ**: スケジューラ / MM / VFS / ネット
- **アプリの依存軸 7 つ**: syscall ABI / libc / VFS 意味論 / プロセスモデル / シグナル・IPC / ネット API / 時刻乱数

後編は、その格子に **横軸として Linux / macOS / Windows** を入れて、「どのマスで色が割れるか」を実際に見ていきます。先に結論を書いておくと:

> 差が **大きい** のは、プロセスモデル、ファイルパス意味論、ネイティブ非同期 I/O。
> 差が **小さい** のは、BSD ソケット、UTF-8、POSIX subset の API。
> WSL2 / コンテナ は「差を埋める」のではなく、**Linux カーネルを別 OS の上で動かす** ことで差を **回避** している。

ここに至るまでに、POSIX が何を約束しているか / していないか、Windows NT と XNU の構造、`fork` 問題、io_uring vs IOCP vs kqueue の設計差、を通ります。

対象読者は前編と同じ ─ 業務で高級言語を書くエンジニアで、3 OS のうち 2 つ以上で開発した経験があり、「ローカルでは動くが本番で動かない」を 1 度以上踏んだ人。

---

## 1. 前編からの接続 — 4 × 7 の格子を 3 OS で塗る

前編の最後で出した格子をもう一度:

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

この依存軸 7 つを縦に並べ、Linux / macOS / Windows を横に取って、「どこで色が割れるか」を先に出してしまいます。

| 依存軸 | Linux | macOS | Windows | 色の割れ |
|---|---|---|---|---|
| ① syscall ABI | 安定・公開 | 不安定・libSystem 必須 | 公開されているのは Win32 のみ(NT は非公開) | **大** |
| ② libc | glibc / musl 等 | libSystem(統合済み) | UCRT / MSVCRT | 中 |
| ③ VFS 意味論 | case-sensitive / `/` | case-insensitive 既定 / `/` | case-insensitive 既定 / `\` | **大** |
| ④ プロセスモデル | `fork` + `exec` | `fork` + `exec`(ただし制約あり) | `CreateProcess` 一発 | **大** |
| ⑤ シグナル/IPC | POSIX 完備 | POSIX 完備 + Mach IPC | NT 流(Event, NamedPipe) | **大** |
| ⑥ ネット API | BSD ソケット | BSD ソケット | Winsock(BSD ベース) | 小 |
| ⑦ 時刻/乱数 | `clock_gettime`, `getrandom` | `clock_gettime`, `arc4random` | `QueryPerformanceCounter`, `BCryptGenRandom` | 小〜中 |

このうち、本稿で深掘りするのは色が **大** の軸 ─ ①③④⑤、それに「ネイティブ非同期 I/O」(これは ⑥ ネット API に分類できなくて格子の外、と気付くのが後の楽しみどころです)です。

---

## 2. POSIX があるのに、なぜ移植性は難しいのか

「移植性」と聞くと多くの人が POSIX を思い浮かべます。POSIX の最新版は **POSIX.1-2024**(= Open Group Base Specifications Issue 8、= IEEE Std 1003.1-2024)。Open Group のサイトで本文が読めます。

スコープを公式から引用:

> POSIX.1-2024 defines a standard operating system interface and environment, including a command interpreter (or "shell"), and common utility programs to support applications portability at the source code level.
>
> ─ [The Open Group Base Specifications Issue 8 - Introduction](https://pubs.opengroup.org/onlinepubs/9799919799/basedefs/V1_chap01.html)

ここに 2 つの重要な制限が書かれています。

**(a) 「**source code level** の移植性」**。バイナリ互換ではない。同じ C ソースが両方の OS で **コンパイル** できる、というレベル。

**(b) ただし、POSIX 自身が「準拠 ≠ 完全移植」と明言している**:

> Some of the utilities in the Shell and Utilities volume of POSIX.1-2024 and functions in the System Interfaces volume … describe functionality that might not be fully portable to systems meeting the requirements for POSIX conformance.

そして決定打が「**unspecified**」という用語の存在です。POSIX 文書には「この挙動は unspecified」とされた箇所が大量にあり、それは「実装ごとに違ってよい」「アプリは依存するな」を意味します。

具体例(本文外で確認できる範囲):

- `printf` の浮動小数フォーマットの丸め方向
- パイプの容量上限(`PIPE_BUF` の最小値だけ規定、最大は実装依存)
- `readdir` の返却順序
- `signal()` のセマンティクス(`sigaction` を使え、と注意書きされている)

つまり、「Mac は Unix だから Linux と同じ」「`bash` があれば動く」は **POSIX 自身が否定している命題** です。`#!/bin/sh` で書いたシェルスクリプトが macOS と Alpine で動かないのは、書いた人の落ち度というより POSIX の設計に組み込まれた **余白** に過ぎません。

---

## 3. カーネル設計の見取り図 — Linux vs Windows NT vs macOS XNU

3 OS のカーネルが「どんな部品で組み立てられているか」を、同じ語彙で並べてみます。

### 3.1 Linux

モノリシック構造。**ローダブルカーネルモジュール (LKM)** で拡張する。`kernel.org` の ToC には次が並びます:

> Filesystems / Memory Management / BPF / USB / PCI / SCSI / Block layer / Networking / Scheduler / ...
> ─ [Linux Kernel docs](https://www.kernel.org/doc/html/v5.14/)

設計の特徴:

- すべてのドライバ・ファイルシステム・ネットスタックが **同じカーネル空間** に住んでいる(= 前編で扱った kernel mode の一枚アドレス空間)
- 「すべてはファイル」哲学を VFS で実装
- API の安定性は **syscall は壊さない、内部 API は壊す** のスタンス

### 3.2 Windows NT

公式の Kernel-Mode Driver Architecture Design Guide によると、Windows のカーネルは **「managers」の集合体** として設計されています:

> Object Manager / Memory Manager / Process and Thread Manager / I/O Manager / Plug and Play Manager / Power Manager / Configuration Manager / Kernel Transaction Manager / Security Reference Monitor / Kernel-Mode Kernel Library
>
> ─ [Microsoft Learn - Kernel-Mode Driver Architecture](https://learn.microsoft.com/en-us/windows-hardware/drivers/kernel/)

このうち最も特徴的なのが **Object Manager** です。Microsoft Learn の表現を借りると、ファイル、デバイス、同期プリミティブ、レジストリキー、すべてが **統一されたオブジェクト** として扱われます。

Sysinternals の Russinovich は、これを Unix の VFS と対比して説明しています:

> The Windows NT Object Manager namespace … is a namespace not unlike the Virtual File System (VFS) namespace present on UNIX implementations.
>
> ─ [Sysinternals Newsletter Vol. 2, No. 2](https://learn.microsoft.com/en-us/sysinternals/resources/archive/v02n02)

つまり、Linux の「すべてはファイル」と、Windows NT の「すべてはオブジェクト」は、**同じ問題に対する別の答え** です。

そしてもう一つ、Windows には **「subsystem」** という概念があります。PE フォーマットの `IMAGE_SUBSYSTEM` 定数を見ると、Windows がかつて複数の OS パーソナリティを支援していた痕跡が残っています:

| 定数 | 値 |
|---|---|
| NATIVE | 1 |
| WINDOWS_GUI | 2 |
| WINDOWS_CUI | 3 |
| OS2_CUI | 5 |
| **POSIX_CUI** | 7 |
| NATIVE_WINDOWS | 8 |
| WINDOWS_CE_GUI | 9 |
| EFI_APPLICATION | 10 |
| EFI_BOOT_SERVICE_DRIVER | 11 |

出典: [PE Format - Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)

`POSIX_CUI = 7` ─ かつて Windows には **POSIX subsystem** があり、Unix バイナリを直接動かす設計を持っていました(Interix / SUA、後に廃止)。今は Win32 が実質的に唯一の現役 subsystem ですが、**PE ヘッダの仕様には残っている**。これは「Windows NT が最初から複数 OS パーソナリティを支援する構造で設計された」ことの機械的証拠です。

### 3.3 macOS XNU

Apple Developer の Kernel Architecture Overview から直接引用:

> OS X kernel environment includes the Mach kernel, BSD, the I/O Kit, file systems, and networking components. These are often referred to collectively as the kernel.
>
> ─ [Apple Developer - Kernel Architecture Overview](https://developer.apple.com/library/archive/documentation/Darwin/Conceptual/KernelProgramming/Architecture/Architecture.html)

つまり XNU は **ハイブリッド** で、3 層に分けて理解できます。

- **Mach 層(下)**: メモリ管理、IPC、SMP スケジューラ、リアルタイム、仮想メモリ、pagers、モジュラアーキテクチャ ─ ここが「低レベル OS 機能」
- **BSD 層(中)**: 「OS personality APIs」。POSIX に近い API はこのレイヤで提供される。FreeBSD をベースにしている
- **I/O Kit 層**: ドライバフレームワーク(C++ ベース)

Apple の言い回しで興味深いのは、BSD 層を **「OS personality」** と呼んでいること。これは「下に別の OS パーソナリティ(Mach 由来の API、別の POSIX 風 API、もしくは Windows 風 API すら)を載せ替えられる」という設計思想です。実際そういう商用パーソナリティが載ったことは無いですが、設計のアフォーダンスとしては Windows NT に近い ─ **「上に subsystem を載せる」** 構造を持っています。

### 3.4 3 OS の構造比較

| 観点 | Linux | macOS (XNU) | Windows NT |
|---|---|---|---|
| カーネル様式 | モノリシック | ハイブリッド(Mach + BSD) | ハイブリッド(NT Executive + Kernel) |
| 抽象の単位 | ファイル(VFS) | ファイル(BSD)+ Mach port | オブジェクト(Object Manager) |
| 拡張機構 | LKM(`.ko`) | Kext(廃止予定)→ System Extensions / DriverKit | カーネルドライバ(`.sys`) |
| 「上に subsystem」 | 基本なし | BSD 層が事実上の personality | 設計レベルでサポート(現役は Win32) |
| ABI 安定性 | syscall は壊さない | libSystem 経由必須・直 syscall は非推奨 | Win32 は安定・NT 内部は非公開 |

ここで一つ気付くこと:**macOS と Windows は「下に低レベルカーネル、上にパーソナリティ」という同じ構造アイデア** を持っているのに、文化が完全に違う。Mach IPC は Windows の LPC/ALPC と類縁ですが、上に乗っているパーソナリティ(BSD POSIX vs Win32)で世界の見え方が全く違う。

---

## 4. 差が「大きい」領域(1) — プロセスモデル: `fork` 問題

ここから差が大きい領域の各論に入ります。

POSIX は `fork(2)` を定義しています。挙動はシンプル ─ **現在のプロセスを丸ごと複製** し、親子両方が直後の行から実行を続ける。子プロセスでだけ何かしたい場合は、`exec()` を続けて呼んで全く別のプログラムに化けるか、`if (pid == 0)` で分岐する。Unix の伝統的な並列 / 子プロセス生成パターンです。

**Windows は `fork` を持っていません。** これは「実装していないだけ」ではなく **設計として持っていない**。Windows のプロセス生成は `CreateProcess` で、これは「現在のプロセスを複製する」のではなく「指定された実行ファイルから新しいプロセスを **起動** する」。両者は意味論が全く違います。

`fork` を Windows で素直にエミュレートできない理由:

- `fork` は **CoW(Copy-on-Write)** でアドレス空間を複製するが、Windows の Memory Manager はそれを基本前提にしていない
- Windows のプロセスは多数のハンドル(オブジェクト参照)を持ち、それらを単純複製できない(セキュリティ、参照カウント)
- COM オブジェクト、GUI ハンドル、デバイスコンテキストなどはプロセス間で共有できない設計

**macOS はもっと厄介** です。`fork` 自体は実装されていますが、Apple は実質的に「Cocoa / Core Foundation を初期化したプロセスでの fork は安全ではない」立場を取っています。**理由は、フレームワークが Mach port や GCD のディスパッチキューを内部で持っていて、それらが fork 後の子プロセスで一貫した状態を保てない** から。

これがアプリ側に **直接** 染み出します。代表例:

**Python の `multiprocessing`**:

```python
import multiprocessing as mp
mp.set_start_method("fork")       # Linux でデフォルト
mp.set_start_method("spawn")      # Windows でデフォルト
mp.set_start_method("forkserver") # 安全寄りの選択肢
```

- `fork`: 速い、状態を引き継げる、しかし macOS / threading との相性が悪い
- `spawn`: Python インタプリタを別プロセスとして起動し直す。安全だが遅く、状態は引き継げない
- `forkserver`: 仲介プロセスを 1 個立てておき、そこから `fork` する

**Python 3.8 から macOS のデフォルトは `spawn` に変更されました**。`fork` のままだと SIGSEGV や謎のデッドロックを引いていたから ─ それが Apple の前述スタンスの影響です。

つまり、Python の `multiprocessing` ドキュメントを読むと「macOS と Windows の挙動が違います」と書いてあるのは、Python の作りの問題ではなく **OS の根本設計差** が浮き出ているわけです。

---

## 5. 差が「大きい」領域(2) — ファイルパスとケース感度

ここは事故の宝庫です。

### 5.1 Windows のパス規則

Microsoft Learn の「Naming Files, Paths, and Namespaces」が一次資料です:

- ファイル名に使えない文字: `< > : " / \ | ? *`、NUL(0)、ASCII 1〜31
- パス区切りは `\`(UNC は `\\server\share\path`)
- 予約名: `CON`, `PRN`, `AUX`, `NUL`, `COM1`〜`COM9`, `LPT1`〜`LPT9`(拡張子を付けても予約)

そしてケース感度について、明示的な警告:

> Do not assume case sensitivity. For example, consider the names OSCAR, Oscar, and oscar to be the same, even though some file systems (such as a POSIX-compliant file system) may consider them as different.
>
> ─ [Naming Files, Paths, and Namespaces](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file)

「`POSIX-compliant file system` may consider them as different」と、**POSIX ファイルシステムは違う扱いをすると Microsoft が明記している**。これは大事です。

NTFS 自体は POSIX semantics for case sensitivity を **サポートしているが、デフォルトではない**。ドライブレターも case-insensitive(`D:\` と `d:\` は同じ)。

### 5.2 macOS のパス規則

macOS のデフォルト APFS は **case-insensitive かつ case-preserving**。`Foo.txt` と `foo.txt` は同じファイルとして扱われるが、最初に作った時の大文字小文字は保持される。

これが macOS で開発したリポジトリを Linux にデプロイした時の **王道事故** を生みます:

```
# macOS で作業
$ touch FooBar.js
$ git add FooBar.js
$ git commit -m "rename"
$ mv FooBar.js foobar.js  # macOS では「リネーム」したつもり
$ git add foobar.js
$ git commit -m "lowercase"
# git は「同じファイル」と認識し、case 変更だけが記録される
# Linux で pull すると…大文字版が消えなかったり、二重存在したり
```

Git には `core.ignoreCase` という設定がありますが、これは「設定する側が OS 差を知っている」前提です。

### 5.3 .NET と長いパス

`MAX_PATH` 問題は **.NET Framework 固有の問題** であり、.NET 5+ では暗黙に解消されています:

> .NET Core and .NET 5+ handles long paths implicitly and doesn't perform a MAX_PATH check.
>
> ─ [File path formats on Windows systems - .NET](https://learn.microsoft.com/en-us/dotnet/standard/io/file-path-formats)

`\\?\` プレフィックスは、暗黙の API 呼出経路でのみ MAX_PATH チェックをスキップさせる仕組みでした。`GetFullPathName` に明示的に渡した場合は正規化されるので、`\\?\` は API の通る道に乗せる時の **おまじない** だった。

### 5.4 WSL のケース感度設定

Microsoft Learn の WSL Case Sensitivity ページから:

- WSL では **ディレクトリごとに** case sensitivity を設定できる
- WSL2 では子ディレクトリが親の設定を **継承する**(WSL1 では継承しない)
- ドライブマウント時の挙動は `/etc/wsl.conf` で各ディストロごとに設定

つまり、「Windows 上の `C:\Users\me\projects\` に `Foo.txt` と `foo.txt` を共存させたい」は、WSL2 経由なら設定で実現できます。これは後述する WSL2 の「Linux カーネルそのものを動かす」設計の副産物です。

### 5.5 改行コードと文字符号化

ついでに触れておくと:

- Linux / macOS: `\n`
- Windows: `\r\n`(歴史的に CP/M 由来)
- 旧 macOS(MacOS 9 まで): `\r` ─ Mac OS X 以降は `\n`

Git の `core.autocrlf` はこの差をリポジトリ階層で吸収しようとする仕組みです。

文字符号化は **UTF-8 が事実上の業界標準**。Windows API は内部で UTF-16(WCHAR)を保持しているので、`*A` 系 API(`CreateFileA`)と `*W` 系 API(`CreateFileW`)が二重に存在しますが、Windows 10 1903 以降は UTF-8 をプロセスのデフォルトコードページにできます。

### 5.6 結論

3 OS の VFS 意味論差は、**ファイルシステムを抽象化する側(つまり高級言語の `os` / `fs` モジュール)が POSIX に寄せている** ため、表面上は揃って見えます。が、ケース感度・ファイル名・パス区切り・改行・原子的 rename ─ いずれも漏れ口になります。

「テスト環境では動いた」事故の **過半は VFS 意味論の差** が原因です。

---

## 6. 差が「大きい」領域(3) — ネイティブ非同期 I/O 三国志

ここが 3 OS の哲学差が一番くっきり出るところです。前編の「依存軸」7 つには入れませんでしたが、**入れるとしたら何軸?** という問いがそのまま答えになります ─ どこにも収まらない、OS 固有領域です。

### 6.1 Linux: io_uring(2019〜)

man 7 `io_uring` の冒頭:

> io_uring is a Linux-specific API for asynchronous I/O.
> It gets its name from ring buffers which are shared between user space and kernel space.
> Rather than just communicate between kernel and user space with system calls, ring buffers are used as the main mode of communication. … avoiding the overhead of copying buffers between them, where possible.
>
> ─ [io_uring(7) - man7.org](https://man7.org/linux/man-pages/man7/io_uring.7.html)

設計の肝:

- **共有 ring buffer が通信の主モード**。syscall ではない
- Submission Queue Entry(`struct io_uring_sqe`) と Completion Queue Entry(`struct io_uring_cqe`) を ring に積み下ろしする
- カーネル ≥ 5.4 では SQ と CQ を **1 回の `mmap` でジョイントマップ** できる
- 公開 syscall は `io_uring_setup(2)`(キュー作成)と `io_uring_enter(2)`(submit/wait)の **たった 2 つ**
- glibc には wrapper がまだ無く、自前で `syscall()` で呼ぶか、`liburing` を使う
- ring の操作は `memory_order_release` / `memory_order_acquire` の atomic が必要

これがなぜ革命的か。従来の Linux の async I/O は `epoll`(readiness-based、「読める / 書ける」になったら通知される)で、実際の `read()` `write()` は syscall として別途呼ぶ必要がありました。io_uring は **read / write も含めて非同期に投入** でき、しかも syscall 回数を劇的に減らせます。

### 6.2 Windows: IOCP(Windows NT 時代から)

Microsoft Learn の I/O Completion Ports ページから:

> I/O completion ports provide an efficient threading model for processing multiple asynchronous I/O requests on a multiprocessor system.
> When a process creates an I/O completion port, the system creates an associated queue object for threads whose sole purpose is to service these requests.
> … the best maximum value to specify for the concurrency value of an I/O completion port. … a minimum of twice as many threads in the thread pool as there are processors on the system.
>
> ─ [I/O Completion Ports - Win32](https://learn.microsoft.com/en-us/windows/win32/fileio/i-o-completion-ports)

設計の肝:

- **completion-based** モデル。I/O を投入したら、完了したときに「completion packet」が completion port に届く
- スレッドプールが `GetQueuedCompletionStatus` で待ち、来た packet を取って処理する
- packet の取り出しは **FIFO**(届いた順)、スレッドの解放は **LIFO**(直近で待ち始めたものから)。これは「キャッシュが温かい同じスレッドを優先」する設計
- 推奨スレッド数は **プロセッサ数の最低 2 倍**
- 落とし穴: 非同期ハンドルで `WriteFile` が `TRUE` を返しても、completion port にも別途 packet が送られる。**両方で同じリソース解放を書くと double-free**。「Synchronous and Asynchronous I/O」ページに警告あり

### 6.3 macOS / BSD: kqueue(1990 年代〜)

Apple のマニュアルページ:

> kqueue() creates a new kernel event queue and returns a descriptor.
> The queue is not inherited by a child created with fork(2).
>
> ─ [kqueue(2) - Apple Manual Pages](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/kqueue.2.html)

設計の肝:

- **readiness-based** モデル(epoll に近い)。fd が「読める / 書ける」になったら通知
- ただし監視対象は fd だけではない: **シグナル、タイマー、プロセス、vnode(ファイルシステム変化)、ユーザーイベント**
- 登録と取り出しを **同じ `kevent()` syscall** で一度にできる(epoll は `epoll_ctl` と `epoll_wait` が別)
- 「複数イベントが連続発生すると、フィルタが集約して 1 個の `struct kevent` にまとめる」 ─ 過剰なウェイクアップを避ける設計

### 6.4 3 API の構造比較

| 観点 | io_uring (Linux) | IOCP (Windows) | kqueue (macOS/BSD) |
|---|---|---|---|
| モデル | submission + completion ring | completion-based | readiness-based(イベント駆動) |
| 通信路 | 共有 ring buffer | completion packet | kernel event queue |
| 監視対象 | I/O 操作全般 | I/O 操作全般 | fd / signal / timer / process / vnode |
| syscall 回数 | 極小(ring 操作はゼロ) | 1 イベントごとに 1 | 1 イベントごとに 1(集約可) |
| 登場時期 | 2019(Linux 5.1) | Windows NT 〜 | 1990 年代(FreeBSD 由来) |

それぞれの **設計世代** が異なります。kqueue → IOCP → io_uring の順で新しく、新しいほど「syscall を減らす」「カーネルとユーザーで状態を共有する」方向に進んでいます。

これを **どう吸収するか** が、ランタイム実装者の腕の見せどころです。

- **Node.js / libuv**: epoll / IOCP / kqueue を一つの event loop API に統一(io_uring 対応は段階的)
- **Tokio**(Rust): io_uring / IOCP / kqueue を選べる(`tokio-uring` などのクレート)
- **Go の `netpoll`**: Linux で epoll、macOS で kqueue、Windows で IOCP を直接統合(libc を経由せずに)
- **CPython の `asyncio`**: `selectors` モジュールで `select` / `poll` / `epoll` / `kqueue` を吸収。Windows は `ProactorEventLoop`(IOCP ベース)を別に用意

「`asyncio` が Windows と Linux で挙動が違う」と感じるとき、その正体は **このレイヤの差** です。

---

## 7. 差が「小さい」領域 — BSD ソケット、UTF-8、POSIX subset

差ばかり挙げると「全部違うのか…」と絶望しますが、**差が小さい領域もちゃんとある** ことを書いておきます。

### 7.1 BSD ソケット

`socket()` `bind()` `listen()` `accept()` `connect()` `send()` `recv()` `close()` のセットは、3 OS で **関数名がほぼ同じ** で動きます。Windows の Winsock も BSD ソケットを踏襲しています(`WSAStartup` で初期化が必要、`closesocket` で閉じる、エラー報告が `WSAGetLastError` といった微差はある)。

逆に言うと、「ネットワーキングは移植性が高い」のは BSD ソケットがほぼ唯一の生き残った標準だからで、これは **歴史的偶然** に近い結果です。

### 7.2 UTF-8

テキストデータの相互運用は UTF-8 が事実上の業界標準。Web は UTF-8、JSON は UTF-8、Linux と macOS のファイルシステムは UTF-8 ベース。Windows は内部 UTF-16 が残るレイヤがありますが、Windows 10 1903 以降は UTF-8 を選択できます。

### 7.3 POSIX subset

POSIX の System Interfaces 巻に含まれる **基本 API**(`open` / `read` / `write` / `close` / `stat` / `pipe` / `dup` / `select` / 一部の `fcntl` ...)は、Linux と macOS でほぼ同じに使えます。Windows でも `_open` `_read` 等の互換 API があり、POSIX subset の上で書いた C コードは 3 OS で **コンパイル** くらいは通る。

「**差が小さい領域**」では、ランタイムが薄いラッパを置くだけで OS 差を吸収できます。Python の `socket` モジュール、Node.js の `net`、Go の `net` ─ いずれもこれです。

---

## 8. 高級言語ランタイムはどこを吸収し、どこを吸収できないか

依存軸 7 つに対する、5 ランタイムの吸収度合いを表にすると:

| 軸 | CPython | Node.js (libuv) | Go runtime | JVM | Rust std |
|---|---|---|---|---|---|
| ① syscall ABI | 隠す | 隠す | **直接叩く**(Linux) | 隠す | 隠す |
| ② libc | 依存 | 依存(prebuilt は OS 別) | 依存しない(Linux) | JNI 経由で依存 | 依存(`libc` クレート別) |
| ③ VFS 意味論 | **漏らす**(`os.path`) | 部分吸収(`path` モジュール) | 部分吸収 | `java.nio.Path` で吸収 | **漏らす**(`std::path`) |
| ④ プロセスモデル | **漏らす**(`os.fork` が無い) | 部分吸収(`child_process`) | `os/exec` で抽象化 | `ProcessBuilder` で抽象化 | `std::process` で抽象化 |
| ⑤ シグナル/IPC | **大きく漏らす** | event loop 経由で部分吸収 | `os/signal` で抽象化 | `Signal` クラスで部分吸収 | `signal-hook` クレート別 |
| ⑥ ネット API | 統一(BSD ソケット) | 統一(libuv) | 統一(`net`) | `java.net` で統一 | `std::net` で統一 |
| ⑦ 時刻/乱数 | 統一(`time`, `secrets`) | 統一 | 統一(`time`, `crypto/rand`) | 統一 | 統一 |
| native async I/O | `selectors` + Windows 別 event loop | event loop で統一 | runtime 内で吸収 | NIO で吸収 | async crate(Tokio 等) |

ここから読み取れる原則:

1. **ネット API、時刻、乱数 は全ランタイムが吸収できる**(下が揃っているから)
2. **プロセスモデルと VFS 意味論 は、明示的に「漏らす」設計のランタイムがある**(CPython、Rust std)
3. **native async I/O は、event loop / scheduler を持つランタイムだけが吸収する**(Node.js、Go、Tokio)

**「全部を吸収する」ランタイムは存在しません。** これはランタイム実装者の怠慢ではなく、「漏らした方が、その軸を本当に使いたい人が困らない」という工学的判断です。

CPython が `os.fork` を Windows で `AttributeError` にするのは、「fork は POSIX 概念です」と明示的に通知している ─ そこで「Windows でも `fork` ぽいことを偽装」してしまうと、本気で `fork` の意味論に依存しているコード(CoW でメモリ節約、子プロセスでファイルディスクリプタを継承)が壊れます。

---

## 9. WSL2 / コンテナ / Rosetta — 移植性地図の書き換え

ここまでに整理した「3 OS の差」は、過去 5 年で大きく **無効化** されつつあります。理由は、「差を埋める」ではなく「**差を回避する**」アプローチが主流になったから。

### 9.1 WSL2

Microsoft Learn の WSL について:

> WSL 2 uses virtualization technology to run a Linux kernel inside of a lightweight utility virtual machine (VM).
> WSL 2 is the default distro type when installing a Linux distribution.
> Linux distributions run as isolated containers inside of the WSL 2 managed VM.
>
> ─ [What is WSL](https://learn.microsoft.com/en-us/windows/wsl/about)

注目すべきは **「a Linux kernel」**。WSL1 は Windows カーネル上で Linux syscall を翻訳する **emulation layer** でしたが、WSL2 は **本物の Linux カーネル** を Hyper-V のサブセット(Virtual Machine Platform)で動かしています。

> The newest version of WSL uses a subset of Hyper-V architecture to enable its virtualization. This subset is provided as an optional component named "Virtual Machine Platform".
>
> ─ [WSL FAQ](https://learn.microsoft.com/en-us/windows/wsl/faq)

VM 内では:

- 各ディストロは **コンテナとして隔離** される
- **共有**: network namespace、device tree(`/dev/pts` を除く)、CPU、Kernel、Memory、Swap、`/init` バイナリ
- **独立**: PID namespace、Mount namespace、User namespace、Cgroup namespace、`init` プロセス
- ホストとは **別の IP アドレス** を持つ

つまり WSL2 は、「Windows が Linux アプリを動かしている」のではなく、「**Windows の上に動く Linux カーネルが Linux アプリを動かしている**」。だから syscall は **完全互換** です ─ そりゃそうです、本物の Linux なんですから。

### 9.2 コンテナ(Docker / Podman)

Linux 上のコンテナは、**namespaces + cgroups の組合せ** で実装されています。これは Linux カーネルの機能(`unshare(2)`、`clone(2)` の各フラグ、`/sys/fs/cgroup`)です。

ここで重要なのは、**Mac / Windows の Docker Desktop は中で Linux VM を走らせている** こと。WSL2 と同じく、Linux カーネルが必要だから本物の Linux カーネルを VM で動かす、という割り切り。

これにより、開発者の体感としては「Mac / Windows でも `docker run -it ubuntu` で Linux 環境が立ち上がる」── ただし正確には **どちらも Linux カーネルが直接走っている** ので、差を埋めているわけではない。差を **回避** している。

### 9.3 Rosetta 2

Apple Silicon に伴って登場した Rosetta 2 は、**x86_64 → ARM64 の ISA 翻訳**。OS 差ではなく **アーキテクチャ差** を埋めます。

アセンブラ前編で扱った「同じ C コードが x86_64 と AArch64 で違うアセンブリになる」問題に対するアップル流の答えです。OS の責務軸(本稿の話)には触れていないので、本稿の文脈では「**移植性の別の側面**」だけ補足しておく程度で十分です。

### 9.4 結論

「最近 Mac でも Windows でも開発が楽になった」と感じるのは、**OS 差が縮まったから** ではなく、「**Linux カーネルそのものをどこでも持ち運べるようになったから**」です。

これは大変重要な認識転換で、つまり:

- WSL2 で動いている Python アプリは **Linux のアプリ** であって Windows のアプリではない
- Docker Desktop for Mac で動いている Postgres は **Linux のアプリ** であって macOS のアプリではない

**「Linux カーネルが各所に運ばれてきた」** という見方が現実に近い。後編冒頭で書いた結論「差を埋めるのではなく差を回避する」はこれです。

---

## 10. アプリ開発者が押さえるべき OS 差の「優先順位」

3 OS で配布・運用するアプリを書く立場で、**何に注意の予算を割くか** を提案します。

1. **最優先**: VFS 意味論
   - パス区切り、ケース感度、改行、`rename` の atomicity、`fsync` の保証
   - ここをサボると Git とテストとデプロイの全部に飛び火する
2. **次点**: プロセスモデル、シグナル、async I/O
   - `multiprocessing` の `start_method`、SIGTERM の作法、event loop の選択
3. **中位**: 権限モデル(POSIX 権限 vs ACL)、シェル、行末
4. **下位**: ネット API、BSD ソケット、UTF-8(揃っているので楽できる)
5. **「ほぼ気にしなくて良い」領域**: コンテナや WSL2 の **内側に閉じる限り**(ただし、外との境界 ─ ファイル共有、ネットワーク、開発時の IDE 統合 ─ で噴き出す)

「OS 差を全部抽象化しろ」は、**ランタイム実装者でも諦めているライン** があるので無理です。漏れる場所を予測して、**その場所だけ抽象化を入れる** のが現実的な戦略です。

具体的には:

- パスは `pathlib.Path` / `path.PathBuf` を使う(文字列連結しない)
- プロセス生成は `multiprocessing` の `start_method` を明示する
- ファイルシステムは「ケース感度に依存しない」ようにテストする
- async I/O は信頼できるランタイム(`asyncio` / `tokio` / Node.js)に乗る ─ 自前で `epoll` / `IOCP` を書かない

---

## 11. 連載まとめ

連載 4 本で「アプリの足場」を下から地図化しました。

```
┌─────────────────────────────────────────────────────┐
│  本連載で扱った地層(上から)                       │
├─────────────────────────────────────────────────────┤
│  ⑥ OS 差とアプリへの影響(本記事 後編)            │
│  ⑤ OS とアプリの境界(本記事 前編)                │
│  ④ Python C 拡張 — Python から C への橋(別記事)  │
│  ③ コンパイラの代行作業(アセンブラ後編)          │
│  ② ISA、レジスタ、呼出規約(アセンブラ前編)       │
│  ① CPU 命令そのもの(連載外)                      │
└─────────────────────────────────────────────────────┘
```

各層を一つずつ降りていくと、「高級言語の上で完結する世界」が **借り物の地面の上に立っている** ことが見えてきます。借り物先は、

- ハードウェア(CPU / メモリ)
- カーネル(syscall / VFS / スケジューラ)
- libc / 言語ランタイム / 標準ライブラリ
- OS の文化的選択(`fork` か `CreateProcess` か、ケース感度の有無)

このどれかが変わると、アプリの挙動も変わる。**「環境依存」と呼ばれているものの大半は、この地層のどれかの色が違うこと** に起因しています。

次回テーマ予告: コンテナの仕組み(namespaces / cgroups の詳細)、もしくは Apple Silicon 時代の ABI 変動。

---

## 参考

- [Open Group Base Specifications Issue 8 - Introduction](https://pubs.opengroup.org/onlinepubs/9799919799/basedefs/V1_chap01.html) — POSIX.1-2024
- [Microsoft Learn - Kernel-Mode Driver Architecture](https://learn.microsoft.com/en-us/windows-hardware/drivers/kernel/)
- [Microsoft Learn - PE Format (IMAGE_SUBSYSTEM)](https://learn.microsoft.com/en-us/windows/win32/debug/pe-format)
- [Microsoft Learn - Sysinternals Newsletter Vol. 2, No. 2](https://learn.microsoft.com/en-us/sysinternals/resources/archive/v02n02)
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

連載:

- [アセンブラを書かない人のためのアセンブラ — 高級言語が抽象化した 3 つの問題(前編)](./assembly_for_high_level_users_part1)
- [アセンブラを書かない人のためのアセンブラ(後編)](./assembly_for_high_level_users_part2)
- [Python C 拡張の地図](./python_c_extensions_internals)
- [Linuxを地図に、OSを読む(前編)](./os_layer_from_linux_part1)
- Linuxを地図に、OSを読む(後編) — 本記事
