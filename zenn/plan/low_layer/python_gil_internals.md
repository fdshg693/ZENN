---
title: "GIL とは何だったのか — Python の GIL を「ランタイム全域ロック」という一般現象として読む"
status: plan
---

## 位置づけ(シリーズ第3弾)

- 第1弾 `python_bytecode_internals.md`: バイトコード / `__pycache__` / VM 評価ループ(`ceval`)
- 第2弾 `python_c_extensions_internals.md`: C 拡張 / 参照カウント / `Py_BEGIN_ALLOW_THREADS` / free-threaded build を C 拡張側から
- 本作: GIL を**正面から主題化**し、「Python 固有のクセ」ではなく **「共有可変状態を1個のロックで囲む」という、言語・OS・データベースに繰り返し現れる一般的な工学パターン**として読み解く

第2弾で GIL は「C 拡張が守る規律」「no-GIL の動機」として断片的に登場済み。本作はその GIL を中心に据え直し、Ruby GVL / Linux BKL と並べることで「全域ロック→段階的解体」という普遍的な歴史の中に Python を置く。

## 重心と分量

- **Python 7 : 他システム 3**。GIL の正体・解放・free-threading を厚く、他言語/OS/コンテナは「同じパターンの実例」として簡潔な対比に。
- free-threading は **1章**(なぜ外しにくかったか + 3.13t→3.14 の現状 + BKL 解体との類比)。C 拡張側の書き方詳細は第2弾に委ね、参照に留める。

## 想定読者と前提

- 第1弾・第2弾を**大まかに**理解している中上級 Python 開発者(refcount・`ceval`・`Py_BEGIN_ALLOW_THREADS` は再説明しすぎない)
- 「GIL があるから Python のスレッドは無意味」を漠然と信じているが、**いつ効いて・いつ効かないか・なぜ存在するか**を自分の言葉で言えない人
- Ruby / Node / Go / JVM の並行モデルや、コンテナの CPU 制限と GIL の関係を横断的に整理したい人

## この記事が答える問い

1. GIL は「Python の欠陥」なのか、ある条件下で合理的な工学判断なのか
2. GIL は具体的に**何を**1個のロックで守っているのか(refcount・組み込み型の内部状態)
3. GIL は**いつ解放される**のか(I/O・C 拡張・switch interval)、なぜ「100バイトコードごと」から「5ms ごと」に変わったのか
4. なぜ Ruby も同じ選択(GVL)をし、Linux カーネルも同じ道(BKL)を辿り、同じように解体されつつあるのか
5. なぜ GIL を外すのは難しかったのか(refcount の per-object lock 化・biased refcounting・QSBR・critical sections)
6. コンテナ(cgroup CPU 制限)・`multiprocessing`・C 拡張のスレッドと GIL はどう噛み合うのか
7. 3.13/3.14 の free-threaded build で、この「全域ロックの解体」は Python でどこまで進んだか

## 扱う / 扱わない

- **扱う**: GIL の正体と役割、解放メカニズム、switch interval、Ruby GVL / Node 単一スレッド / Go・JVM の対比、OS の BKL 史との類比、コンテナ CPU 制限との相互作用、free-threading の現状(PEP 703/779/803)
- **扱わない**: free-threaded build 向け C 拡張の書き方詳細(第2弾でカバー、参照に留める)、`asyncio` のイベントループ実装詳細、PyPy/Jython 等の各実装の網羅、GC アルゴリズム内部

## セクション構成

### 0. この記事について
- シリーズの接続。第2弾で散らばっていた GIL を主題に格上げする宣言。
- 一文の主張: **「GIL は Python の特異な欠陥ではなく、『共有可変状態 + 実装の簡潔さ』を選んだランタイムが必ず通る道の、Python における現れ方」**。

### 1. 「GIL があるから遅い」の解像度を上げる
- まず誤解の整理: GIL は「Python が遅い」原因ではなく「**マルチコアで CPU バウンドな Python コードが並列化しない**」原因。I/O バウンドや C 拡張内ループは別。
- 主張: 問題は「並列(parallel)」であって「並行(concurrent)」ではない。スレッド自体は動く。
- 一般定義の導入: GIL は「1プロセスにつき1個、基本操作(メモリ確保・参照カウント)を同時に1ネイティブスレッドだけ実行させる相互排他ロック」(Wikipedia の一般定義)。**CPython と Ruby MRI が代表例**と最初に明示し、「一般現象」フレームを張る。
- 根拠: en.wikipedia.org/wiki/Global_interpreter_lock, docs.python.org/3/glossary.html
- 根拠ファイル: extract_general_giantlock.json, extract_python_official_gil.json

### 2. GIL は何を守っているのか — refcount と組み込み型の不可分性
- 第2弾の参照カウントを 1 段引き上げる: 全オブジェクトが `ob_refcnt` を持ち、`Py_INCREF/DECREF` が動く。これを複数スレッドが**ロックなしで**触ると、refcount が壊れ(リーク or use-after-free)、`list` の `ob_size` と実要素数がずれてクラッシュする。
- 主張: GIL は「Python コードのデータ競合」ではなく「**インタプリタ内部状態の競合**」を防ぐためにある。`dict` などの組み込み型が暗黙にスレッド安全なのは GIL の副産物(glossary の表現)。
- ここで「全域ロック」の本質を一般化: **共有可変状態が大量にあり、細粒度ロックを全部に付けるのは高コスト → 1個の粗いロックで丸ごと囲う**、という判断。これは GIL に限らない。
- 根拠: peps.python.org/pep-0703(ob_size と refcount 破損の具体記述), docs.python.org/3/glossary.html
- 根拠ファイル: extract_pep703_mechanism.json, search_gil_python_official.json

### 3. GIL はいつ解放されるのか — switch interval と「協調的な手放し」
- 解放される3つの場面: ① I/O 時(glossary: 「GIL is always released when doing I/O」)② `time.sleep` 等 ③ C 拡張が `Py_BEGIN_ALLOW_THREADS` を打ったとき(第2弾を参照)。
- switch interval: 待機スレッドはフラグを立て、保持スレッドが eval ループの区切りでフラグを見て手放す。デフォルト **0.005 秒(5ms)**、`sys.setswitchinterval()` で変更可。スケジューリングの最終決定は **OS スケジューラ**(インタプリタ独自スケジューラではない)。
- 歴史: Python **3.2(2009)** の「new GIL」(Antoine Pitrou)で、旧 `sys.setcheckinterval()`(**100バイトコード命令ごと**、現在は非推奨/削除)から**時間ベース**へ。なぜ変えたか=CPU バウンドスレッドが GIL を占有し続ける問題への対処。
- 主張: GIL は「ハードウェアが強制する壁」ではなく「**協調的に手放す約束**」で回っている。だから手放さない C ループは並列化しないし(第2弾の `ALLOW_THREADS`)、手放しすぎると切替コストで遅くなる。
- 根拠: docs.python.org/3/library/sys.html(getswitchinterval 3.2 追加), docs.python.org/3/glossary.html。100→時間ベースの歴史は二次情報(stackoverflow/blog)で補強しつつ API は公式で裏取り。
- 根拠ファイル: extract_python_official_gil.json, search_extract_switchinterval.json

### 4. 同じ現象を別の名前で — Ruby GVL / Node 単一スレッド / Go・JVM
- **Ruby MRI の GVL**: 存在理由が GIL と**同型**(C 内部の race 防止 / GC 簡素化 / C 拡張作者をスレッド安全の地獄から守る)。I/O 時に解放。JRuby/TruffleRuby は別ランタイムなので GVL なし。→「Python だけの病ではない」決定的な証拠。
- **Node.js / V8**: 逆の解き方。**共有可変状態を最初から作らない**(単一スレッド + イベントループ)。ロックで守る代わりに、守るべき共有を消した。worker_threads は別 isolate。
- **Go / JVM**: 最初から細粒度ロック + 真の並列スレッド。「最初に難しい方を払った」側。Python/Ruby は「後で払う」側。
- 主張: 設計空間は「①全域ロックで囲う(Python/Ruby)②共有を消す(Node)③最初から細粒度化する(Go/JVM)」の3択。GIL はこのトレードオフの**1つの座標**にすぎない。
- 根拠: workingwithruby.com/wwrt/gil, en.wikipedia.org/wiki/Global_interpreter_lock
- 根拠ファイル: extract_ruby_gvl.json, search_gil_general_phenomenon.json

### 5. OS カーネルにも GIL があった — Big Kernel Lock(BKL)の生と死
- **BKL**: Linux が SMP(マルチプロセッサ)対応を始めたとき、カーネル全体を1個の巨大ロックで囲った。「kernel 空間に入る時取得、出る時解放」。**fine-grained 化への移行を簡単にするための過渡的な足場**として導入。← GIL の動機と完全に同じ。
- 解体: coarse → fine への長い旅。**Linux 2.6.39(2011)で完全削除**(Arnd Bergmann)。「Ding Dong, the Big Kernel Lock is Dead」。FreeBSD も Giant lock を SMPng プロジェクトで段階分解。
- 主張: 「とりあえず1個の粗いロックで正しく動かし、後で必要な部分だけ細粒度化する」は**正攻法のエンジニアリング順序**。GIL も BKL も「間違い」ではなく「正しい第一歩」。違いは、カーネルは解体しきり、Python は今まさに解体中、という**時間軸の差**だけ。
- 根拠: en.wikipedia.org/wiki/Giant_lock ほか(BKL 削除年・カーネルバージョン)
- 根拠ファイル: search_extract_bkl_history.json, extract_general_giantlock.json
- 注: 削除バージョン(2.6.39 / 2011)と「過渡的足場」という性格付けは複数ソースで裏取り済み。導入カーネル版数は断定せず「SMP 対応初期」と表現。

### 6. コンテナと GIL — CPU 制限が二重に効く場所
- 前提: GIL があるので CPU バウンドは `multiprocessing`(プロセス分離=各プロセスが自分の GIL を持つ、Wikipedia の一般論)か C 拡張の `ALLOW_THREADS` で稼ぐ。
- ここでコンテナの罠: `os.cpu_count()` は**ホストの論理CPU数**を返しがちで、cgroup の CPU quota を見ない。プロセスプール幅やスレッド数をこれで決めると**oversubscription**(コア数以上のワーカ)になる。
- 3.13 の回答: **`os.process_cpu_count()`**(3.13 追加)= 呼び出しプロセスが実際に使える論理CPU数(affinity 反映)。`os.sched_getaffinity()`、環境変数 **`PYTHON_CPU_COUNT`** / `-X cpu_count` でアプリ無改変に上書き可能。
- C 拡張との合わせ技の罠: NumPy/OpenBLAS が内部で `ALLOW_THREADS` して**自前スレッド**を張る。`multiprocessing` のプロセス数 × BLAS のスレッド数で、コンテナの CPU quota を簡単に超える(古典的 oversubscription)。
- 主張: GIL は「1プロセス内の並列を1個に絞る」ので、現実のスケールは**プロセス数 × コンテナが許す CPU**で決まる。その『コンテナが許す CPU』を正しく数える API が 3.13 でようやく揃った。
- 根拠: docs.python.org/3/library/os.html(process_cpu_count, sched_getaffinity), docs.python.org/3/whatsnew/3.13.html(PYTHON_CPU_COUNT)
- 根拠ファイル: extract_os_cpucount.json

### 7. 全域ロックの解体 — free-threading は Python でどこまで来たか(1章)
- なぜ難しかったか: refcount が**全オブジェクトの全アクセスに乗っている**。素朴にアトミック化すると単一スレッドでも激遅。PEP 703 はここを **biased reference counting + immortal objects(3.12)+ deferred refcount** で回避し、各 list/dict/set に **per-object lock**、lockless 読み取りに **QSBR**、デッドロック回避に **critical sections**、アロケータに **mimalloc** を採用。
- 現状(PEP 779 の3フェーズ): **Phase I = 3.13** で experimental(`python3.13t`)、**Phase II = 3.14** で officially supported(ただし optional)、Phase III(default 化)は将来。単一スレッド性能ペナルティは PEP 703 計測で **Skylake 6% / Zen3 5%** 程度。
- 運用フック: `PYTHON_GIL` / `-X gil` で実行時に GIL を再有効化、`sys._is_gil_enabled()` で確認、`sysconfig.get_config_var("Py_GIL_DISABLED")` でビルド判定。abi3 はそのままでは使えず → **PEP 803 の `abi3t`** が 3.15 を目標に追いかけ中(第2弾の伏線回収)。
- BKL との類比で締める: カーネルは「囲う → 細粒度化 → 削除」をやりきった。Python は今まさに「細粒度化」の途中。**GIL の死は Python の特殊事情ではなく、全域ロックを採った全てのランタイムが辿る一般的な後半生**。
- 根拠: peps.python.org/pep-0703, peps.python.org/pep-0779, peps.python.org/pep-0803, docs.python.org/3/howto/free-threading-python.html, docs.python.org/3/library/sys.html
- 根拠ファイル: extract_pep703_mechanism.json, extract_freethreading_status.json

### 8. まとめ — 「全域ロック」というレンズ
- 3層シリーズの回収表(バイトコード層 / C 拡張層 / 並行性層)に GIL を位置づける。
- 一文: **「共有可変状態を1個のロックで囲い、起動と実装を簡潔にし、必要になったら細粒度化する」**——これが GIL・GVL・BKL を貫く設計判断。
- 実務の持ち帰り: ①GIL を見たら「並列が1個に絞られる」だけで「遅い」ではない ②CPU バウンドはプロセス数 × コンテナ CPU で設計し 3.13 の `process_cpu_count` で数える ③3.13t/3.14 を試すとき何が変わるか位置づけられる。

## 主要参考 URL(plan 時点)

### Python 公式
- https://docs.python.org/3/glossary.html(GIL 定義 / I/O 時解放 / 暗黙のスレッド安全)
- https://docs.python.org/3/library/sys.html(setswitchinterval / getswitchinterval / _is_gil_enabled)
- https://docs.python.org/3/howto/free-threading-python.html(PYTHON_GIL / -X gil / 識別方法)
- https://docs.python.org/3/library/os.html(process_cpu_count / sched_getaffinity)
- https://docs.python.org/3/whatsnew/3.13.html(process_cpu_count / PYTHON_CPU_COUNT / free-threaded experimental)

### PEP
- https://peps.python.org/pep-0703/(GIL が守るもの / biased refcount / per-object lock / 性能数値)
- https://peps.python.org/pep-0779/(free-threading の3フェーズと supported 基準)
- https://peps.python.org/pep-0803/(abi3t)

### 一般現象
- https://en.wikipedia.org/wiki/Global_interpreter_lock(一般定義 / 代表実装 / プロセス分離)
- https://en.wikipedia.org/wiki/Giant_lock(BKL / Giant lock / 削除年)
- https://workingwithruby.com/wwrt/gil(Ruby GVL の存在理由)

## 不足情報 / 注意

- switch interval を「100バイトコード→時間ベース」に変えた経緯の一次資料(PEP)は未取得。本文では公式の API 仕様(0.005s, 3.2 追加)を主、歴史的経緯は「3.2 の new GIL」として二次情報で補強する形にし、断定の強さを調整する。
- BKL の「導入カーネル版数」は断定しない(「SMP 対応初期の過渡的足場」と表現)。削除は 2.6.39 / 2011 で裏取り済み。
- Node worker_threads / Go GMP の内部詳細には踏み込まない(対比の役割に限定)。
