---
title: "WSLは『Linux』ではない — WSL1とWSL2が同じ問いに正反対に答えた話"
status: plan
---

## この plan の位置づけ

- 重心: **設計思想と対比を主役に**(ユーザー確認済み)
- 終盤の対比対象: **普通のVM / Hyper-V**(参照記事が V8 と対比したのと同じ役割)
- 目的: WSLを「使える」を超えて、**OSとは何か(=システムコールABI)・境界はどこにあり何のコストを生むか**という、エンジニアとして成長する視点を作る
- 分量目安: 約500行(参照 `zenn/publish/low_layer/python_bytecode_internals.md`)
- スタイル: 個別Tips寄せ集めではなく、**1つの設計判断から全現象を一本の筋で導く**(参照記事と同じ構造)

## 中心の主張(メンタルモデルの軸)

> 「LinuxをWindowsで動かす」という1つの問いに、WSL1(**NTカーネルにLinux ABIを実装する=逆Wine**)と WSL2(**本物のLinuxカーネルを軽量VMで動かす**)が正反対に答えた。
> WSL1は「カーネルの境界=システムコール」を翻訳した。WSL2は「カーネルごと別世界を立て、その世界とホストの間に通信境界を引いた」。
> 有名なハマり(/mnt/c が遅い、vmmem がメモリを返さない、.vhdx が縮まない、localhost、systemd 不在)は、すべて **WSL2 の「別世界 + 境界」という設計の帰結** として一本で説明できる。

---

## セクション構成

### 0. この記事について(導入)
- 「WSL使ってます」「/mnt/c は遅いから Linux 側に置けって言いますよね」を、**理由まで30秒で説明できるか**という問いかけ(参照記事の導入と同じ温度感)
- 答えられないとモヤる質問リスト:
  - WSLって結局VMなの? 違うの?
  - なんで /mnt/c は遅くて、~/ は速いの? どっち向きが遅いの?
  - WSL閉じたのに vmmem がメモリ食ってるのはなぜ?
  - 中のファイル消したのに ext4.vhdx が縮まないのはなぜ?
  - localhost で繋がるときと繋がらないときがあるのはなぜ?
- 対象読者: WSLを日常で使う中級者 / 仮想化・カーネル・syscall を身近な題材で言語化したい人
- 扱わない: インストール手順、ディストリ別小技、WSLg(GUI)詳細、設定の網羅リファレンス
- 根拠: `extract_core.json`(about/compare-versions/filesystems)

### 1. 「OSを動かす」とは何を提供することか — syscall ABI の話
- メンタルモデルの土台。アプリは「カーネルが公開する**システムコール**という窓口」越しにしか世界に触れない(open/read/fork/...)
- 「Linuxを動かす」=「Linuxのsyscall ABIを満たす何かを用意する」こと。**カーネルの実体が何かは問わない**
- ここで WSL1 と WSL2 の分岐を予告:
  - WSL1 = その窓口を **NTカーネル上に再実装** する(別実装で同じABIを満たす)
  - WSL2 = **本物のLinuxカーネルを別の箱で動かす**(本物にABIを満たさせる)
- 根拠: WSL architectural overview(syscall定義), announcing-wsl-2(syscall translation layer)
  - https://learn.microsoft.com/en-us/previous-versions/windows/desktop/cmdline/wsl-architectural-overview
  - https://devblogs.microsoft.com/commandline/announcing-wsl-2

### 2. WSL1 — NTカーネルにLinuxを「化けさせる」(逆Wine)
- pico process / pico provider の仕組み:
  - pico process = 通常のWindowsプロセスの構成要素を持たない「最小プロセス」+「これはpicoだ」というフラグ
  - syscallが出ると、NTのシステムサービスディスパッチャが「picoか?」を見て、`lxcore.sys` / `lxss.sys`(pico driver)に委譲
  - lxcore.sys は **Linuxカーネルのコードを一切含まない clean-room 実装**。可能な限りNTの機能にマッピングし、無理なものはドライバ内で実装
- `fork()` の例: Windowsに直接の等価物がない。lxcore.sys が初期処理 → NT内部APIでプロセス作成 → 追加データをコピー、で意味論を再現
- 強みと弱み(設計の代償):
  - 強み: VMなし → 起動が軽い、Windows FS とネイティブ統合、/mnt/c が速い(後で効く)
  - 弱み: syscall互換を**全部は実装しきれない**(Docker/FUSEなどが動かない)、性能とABI互換のチューニングがNTカーネル改造になり地獄
- これが「逆Wine」(WineがWin32 ABIをLinux上に実装するのと鏡像)という mental model
- 根拠: WSL architectural overview, "How does WSL 1 work?"(pico process解説), Wikipedia(pico process/clean room), dev.to(LXCore/LXSS)
  - `search_wsl1_pico.json`

### 3. WSL2 — 本物のカーネルを軽量VMで動かす、でも「VMっぽくない」
- なぜ作り直したか: NTカーネルでABIを全部再現するのは限界 → 「本物のLinuxカーネルを持ってくる」方が**互換性が一気に100%になる**(Docker/FUSEが動く)
- 「軽量ユーティリティVM」: Hyper-Vベースだが、起動が速く・省リソース・管理不要、を狙った特別なVM。従来VMとは別物として設計(終盤で対比)
- Microsoftが**Linuxカーネルそのものをshipする**(カスタムカーネル)
- ディストリは「VM内の隔離コンテナ」として動く。network namespace等は共有、PID/mount/user/cgroup namespace は各自(=複数ディストロが同じVMを共有)
- **ここで決定的に変わったこと**: WSL1では境界が「syscall(同じマシン内)」だったが、WSL2では境界が「**VMとホストの間**」になった。以降の全現象はこの一行から出る
- 根拠: announcing-wsl-2, about(共有/隔離の名前空間の記述), compare-versions
  - `extract_core.json`, `extract_config_net.json`

### 4. 現象1: なぜ /mnt/c は遅く、~/ は速いのか — 9P という境界
- WSL2のLinuxファイル(`~/`)は VM内の **ext4(.vhdx ファイル)** にある → ネイティブ速度
- Windowsファイル(`/mnt/c`)へのアクセスは、VMの外。Linuxカーネルが「これはローカルでない」と判断し、**9P (Plan 9) プロトコル**で仮想ネットワーク越しにWindows側の9Pサーバへ転送
- 遅さの正体: シリアライズ→仮想NW転送→デシリアライズ。特に**小さいファイルを大量に**(npm install, git status)叩くとレイテンシが積み上がる
- 逆方向(`\\wsl$` / `\\wsl.localhost` でWindowsからLinuxファイル)も境界越えだが、体感は前者ほどではない(根拠ブログの実測談)
- 実務結論: **プロジェクトは Linux FS(~/) に置く。/mnt/c に置かない。** これが「なぜ」まで言える
- WSL1ではこれが逆だった(DrvFsで /mnt/c が速く、Linux FSの一部操作が遅い)=境界の場所が違うから
- 根拠: filesystems(Linux FSに置け), WSL issue #4197(WSL1/WSL2の/mntベンチ逆転), Proxmフォーラム(9P3層の解説), pomeroyブログ(双方向の体感)
  - `extract_core.json`, `search_wsl_gotchas.json`

### 5. 現象2: なぜ vmmem はメモリを返さないのか / .vhdx が縮まないのか — 「箱」の宿命
- VMである以上、Linuxが使うメモリ・ディスクは**ホストから見ると1個の箱(vmmem プロセス / ext4.vhdx)**
- メモリ: WSL2のメモリは伸縮するが、**Linuxがキャッシュしたページは WSL shutdown まで Windows に返らない**(長時間セッション・大量ファイルアクセスで肥大)
  - 対策の道具: `.wslconfig` の `memory=`(上限)、`autoMemoryReclaim`(段階的キャッシュ解放)、最終手段 `wsl --shutdown`
- ディスク: Linux内でファイルを消しても `.vhdx` は**自動で縮まない**(成長一方)。sparse VHD / `wsl --manage --set-sparse` / `Optimize-VHD` の話
- 両方とも「Linux FSやメモリの実体がホスト管理のファイル/プロセスに閉じ込められている」という**同じ根**から来る、と束ねる
- 根拠: compare-versions(キャッシュ非解放の注記), wsl-config(memory/networkingMode), Q&A/issue #4699/#12103(.vhdx縮まない, sparse)
  - `extract_config_net.json`, `search_wsl_gotchas.json`, `search_interop_mem.json`

### 6. 現象3: localhost とネットワーク — NAT という境界、mirrored という回避
- デフォルトは **NAT**: WSL2 VM は別サブネットを持つ別ホスト。Windows→Linuxのサーバは localhost forwarding で繋がるが、IPは起動ごとに変わる/一部ケースで破綻
- `hostname -i`(VM自身) と `hostname -I`(外から見えるIP)の違い、なぜIP探しが要るのか
- `networkingMode=mirrored`(Win11 22H2+): Windowsのインターフェースを Linux に「鏡写し」。localhost(127.0.0.1)で双方向接続、IPv6、VPN互換改善。境界の引き方自体を変えるオプション
- mental model: 「localhostが繋がる/繋がらない」は気分ではなく、**NAT(別ホスト)か mirrored(同一視)か**で決まる
- 根拠: networking(NAT/mirrored/localhost/hostname -i vs -I), wsl-config(networkingMode値一覧)
  - `extract_config_net.json`

### 7. 現象4: 相互運用と systemd — 「同じマシンに見える」の正体
- interop: Linuxから `notepad.exe` が動くのは、WSLが Linuxカーネルの **binfmt_misc** にWindows実行ファイル(PE)用ハンドラを登録しているから。カーネルがPEを見ると実行をWSL interopブリッジに渡す → Windows側でプロセス起動
  - `WSLENV` で環境変数を橋渡しできる話も軽く
- systemd: 当初WSLのinitは独自で **systemdが無かった**(PID1がsystemdでない)→ snap等が動かない問題。今は `wsl.conf` の `[boot] systemd=true` で有効化(WSL 0.67.6+)
  - 「なぜ最初から無かったのか」= WSLは「VMを意識させない」設計で、独自initで起動を速く/軽くしていたから。systemd対応はその思想とのトレードオフを呑んだ追加
- 根拠: filesystems(interop節), systemd(有効化手順/バージョン/サービスはinstanceを生かし続けない), wsl-config(boot)
  - `extract_core.json`, `extract_config_net.json`

### 8. 立体化: 普通のVM / Hyper-V との対比(参照記事の V8 対比に相当)
- 従来VM: 完全に隔離、起動が遅い、固定リソース確保、ユーザーが構成管理、ホストとはネットワーク共有くらい
- WSL2(軽量ユーティリティVM)が振った設計:
  - 起動高速(オンデマンド)/ リソース動的(でも返さない宿命=5章)/ 管理不要 / ファイル・ネットワーク・プロセスをホストと**積極的に橋渡し**
- 「WSL2はVMなのにVMっぽくない」の正体 = **隔離(VMの安全/互換)と統合(WSL1の体験)を両取りしようとした結果**、橋(9P/NAT/interop)を大量に架けた。橋があるところに必ずコスト(遅延・メモリ・IP問題)が出る
- 結論の一文: **WSLの全現象は「隔離と統合のトレードオフを、境界をどこに引くかで解いた」一点に収束する**
- 根拠: announcing-wsl-2("NOT a traditional VM experience"の各論), about
  - `extract_core.json`

### 9. 実務への変換(チェックリスト)
- プロジェクトは `~/`(Linux FS)に置く。/mnt/c はWindowsツールと共有したい時だけ(4章)
- メモリ肥大は `.wslconfig` の `memory` / `autoMemoryReclaim`、困ったら `wsl --shutdown`(5章)
- ディスクが減らない時は sparse + `Optimize-VHD`(5章)
- localhost問題は NAT を疑い、必要なら `mirrored`(6章)
- Dockerやsnapを使うなら WSL2 + systemd(3,7章)
- WSL1がまだ有利な例外: /mnt/c への重い読み書きが主、VM不可環境 → 公式の「Exceptions for using WSL1」に沿って判断
- 根拠: compare-versions(WSL1例外), filesystems, wsl-config, networking

### 10. まとめ
- WSL1=逆Wine(syscall翻訳)、WSL2=本物カーネル+軽量VM、は「Linuxを動かす」への正反対の解
- WSL2の全ハマりは「VMという別世界 × ホストへの橋」から一本で導ける(9P=ファイルの橋, vmmem/.vhdx=箱の宿命, NAT/mirrored=NWの橋, binfmt_misc/interop=実行の橋)
- 持ち帰り: **OSはsyscall ABI、仮想化は境界の再配置、性能と互換は橋のコスト**。WSLを題材にこの3つが言語化できれば、Docker/コンテナ/他の仮想化も同じ地図で読める

---

## 参考(本文末尾に載せる候補)
- [What is WSL](https://learn.microsoft.com/en-us/windows/wsl/about)
- [Comparing WSL Versions](https://learn.microsoft.com/en-us/windows/wsl/compare-versions)
- [WSL architectural overview (WSL1)](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/cmdline/wsl-architectural-overview)
- [Announcing WSL 2](https://devblogs.microsoft.com/commandline/announcing-wsl-2)
- [Working across Windows and Linux file systems](https://learn.microsoft.com/en-us/windows/wsl/filesystems)
- [Accessing network applications with WSL](https://learn.microsoft.com/en-us/windows/wsl/networking)
- [Advanced settings configuration in WSL (.wslconfig / wsl.conf)](https://learn.microsoft.com/en-us/windows/wsl/wsl-config)
- [Use systemd to manage Linux services with WSL](https://learn.microsoft.com/en-us/windows/wsl/systemd)
- [WSL issue #4197 (/mnt perf)](https://github.com/microsoft/WSL/issues/4197) / [#4699 (.vhdx disk space)](https://github.com/microsoft/WSL/issues/4699)

## 想定タグ(publish時)
`["wsl", "linux", "windows", "lowlevel", "architecture"]`
（既存リポジトリの慣習: linux/os/lowlevel/architecture を再利用）
