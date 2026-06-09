---
title: "GIL とは何だったのか — Python の GIL を「ランタイム全域ロック」という一般現象として読む"
emoji: "🔒"
type: "tech"
topics: ["python", "cpython", "gil", "performance", "architecture"]
published: false
---

## この記事について

このシリーズでは、Python の実行系を「層」で読み解いてきました。

- 第1弾 [Python は本当にインタプリタ言語か?](./python_bytecode_internals) で、`.py` → AST → **バイトコード** → VM 評価ループ(`ceval`)という 4 段構成を見ました。
- 第2弾 [Python C 拡張の地図](./python_c_extensions_internals) で、その VM の真下に生える **C 拡張**と、`Py_INCREF` / `Py_DECREF` の参照カウント、そして GIL を C 拡張作者の視点から眺めました。

第2弾で GIL は、「C 拡張が守る 2 つの規律のひとつ」「no-GIL(PEP 703)の動機」として、**断片的に**何度も顔を出しました。この記事は、その GIL を**正面から主題に据え直す**ものです。

ただし、本記事の狙いは「GIL の仕組みを Python に閉じて細かく説明すること」ではありません。むしろ逆で、

> **GIL は Python という言語の特異な欠陥ではなく、「共有可変状態を 1 個の粗いロックで囲い、実装と起動を簡潔にする」という、言語・OS・データベースに繰り返し現れる一般的な工学パターンの、Python における現れ方にすぎない**

という見方を提示することが目的です。だから途中で何度も Python を離れ、Ruby の GVL、Node の単一スレッド、そして Linux カーネルの **Big Kernel Lock** に寄り道します。それらを並べたとき、GIL は「Python の病」ではなく「**全域ロックを採ったランタイムが必ず通る道**」の 1 地点として読めるようになります。

対象は CPython 3.12〜3.14。想定読者は、第1弾・第2弾を**大まかに**理解している中上級者です。`ceval`・参照カウント・`Py_BEGIN_ALLOW_THREADS` といった語は、いちいち再説明しません。

---

## 1. 「GIL があるから遅い」の解像度を上げる

まず、よくある一文の解像度を上げるところから始めます。

> 「Python は GIL があるから遅い」

これは中上級者が口にするには、雑すぎます。GIL は「Python が遅い」原因では**ありません**。正確には、

> **GIL は、1 プロセス内で複数スレッドを立てても、CPU バウンドな Python バイトコードが複数コアで同時に走らない、という制約**

です。ここで効いている区別は「並行(concurrent)」と「並列(parallel)」です。

- **並行**: 複数の処理が「進行中」であること。スレッドは作れるし、切り替わるし、I/O 待ちは重ねられる。GIL があっても並行はできる。
- **並列**: 複数の処理が「物理的に同時刻に」走ること。GIL は、Python バイトコードの実行に関してこれを 1 個に絞る。

だから GIL が刺さるのは「マルチコアで CPU をブン回したい数値計算を、スレッドで並列化しようとしたとき」だけです。I/O バウンドなコード(HTTP リクエストを 100 本投げて待つ)はスレッドで普通に重なるし、NumPy の内部ループのように C 側で GIL を手放す処理も並列に効きます(第2弾の `Py_BEGIN_ALLOW_THREADS` の話)。

### 一般定義から入る

ここで、あえて Python の外側にある定義から入ります。Wikipedia の [Global interpreter lock](https://en.wikipedia.org/wiki/Global_interpreter_lock) の定義はこうです。

> A global interpreter lock (GIL) is a mechanism used in computer-language interpreters to synchronize the execution of threads so that only one native thread (per process) can execute basic operations (such as memory allocation and reference counting) at a time. ... Some popular interpreters that have a GIL are CPython and Ruby MRI.

注目してほしいのは 2 点です。

1. GIL の定義に「Python」という固有名詞が**出てこない**。これは「インタプリタ一般」の機構として定義されている。
2. 代表例として **CPython と Ruby MRI** が並記されている。つまり最初から「複数の言語が独立に同じ選択をした」ことが含意されている。

この記事はこの 2 点を出発点にします。GIL を「Python のクセ」として閉じて見るのをやめ、「**ランタイム全域ロック(runtime-wide lock)という一般現象の一例**」として開いて見る。すると、後半で出てくる Ruby も Linux カーネルも、同じ地図の上に乗ってきます。

---

## 2. GIL は何を守っているのか — refcount と組み込み型の不可分性

「1 個のロックで囲う」と言うとき、では**何を**囲っているのか。ここが GIL 理解の本丸です。

第2弾で見たとおり、CPython のあらゆるオブジェクトは先頭に参照カウント `ob_refcnt` を持っていて、`Py_INCREF` / `Py_DECREF` がそれを増減させます。問題は、**この増減が単純な `n = n + 1` だということ**です。複数スレッドがロックなしでこれを同時に行うと、古典的な lost update が起きます。

- カウントが**過小**になる → まだ使われているオブジェクトが解放される → use-after-free → segfault
- カウントが**過大**になる → 誰も使っていないオブジェクトが解放されない → メモリリーク

さらに、壊れるのは refcount だけではありません。PEP 703 ([Making the Global Interpreter Lock Optional](https://peps.python.org/pep-0703/))は、GIL が無い世界で何が壊れるかをこう書いています。

> ... if multiple threads concurrently modify the same list, the GIL ensures that the length of the list (`ob_size`) accurately matches the number of elements, and that the reference counts of each element accurately reflect the number of references to those elements. Without the GIL — and absent other changes — concurrent modifications would corrupt those fields and likely lead to program crashes.

つまり GIL が守っているのは、**あなたの Python コードのデータ競合ではなく、インタプリタ内部状態の整合性**です。`list` の「長さ(`ob_size`)」と「実際に入っている要素数」がズレない、`dict` の内部ハッシュテーブルが壊れない——そういう**インタプリタの足元**を守っている。

その副産物として、[用語集(glossary)](https://docs.python.org/3/glossary.html) が書くように、組み込み型(`dict` を含む)が**暗黙にスレッドセーフ**になります。

> This lock is necessary mainly because CPython's memory management is not thread-safe. ... it makes the object model (including critical built-in types such as `dict`) implicitly safe against concurrent access.

ここで「全域ロック」というパターンの本質が見えます。

> CPython の内部には、refcount を持つオブジェクトが**何百万個**ある。それぞれに専用の細粒度ロックを付ければ理論上は並列化できるが、(a) ロックのメモリオーバーヘッドが膨大になり、(b) `Py_INCREF` のような超高頻度操作が毎回ロック取得になって単一スレッドでも激遅になる。だから **1 個の粗いロックで全部まとめて囲ってしまう**。

この「**守るべき共有可変状態が大量にあり、個別にロックすると高コストすぎるので、1 個でまとめて囲う**」という判断こそが、GIL の正体です。そしてこの判断は、Python に固有のものではありません——第4章・第5章で、まったく同じ判断を Ruby と Linux カーネルがしていたことを見ます。

---

## 3. GIL はいつ解放されるのか — switch interval と「協調的な手放し」

GIL が「常に 1 スレッドを止め続ける壁」だと思っていると、スレッドがそもそも切り替わる理由が説明できません。実際には GIL は**手放される**ように作られています。手放されるのは主に 3 つの場面です。

1. **I/O 操作のとき**。glossary に明記されています。
   > The GIL is always released when doing I/O.

   `socket.recv`、ファイル読み書き、`time.sleep` の内部で、CPython は GIL を手放します。だから「100 本の HTTP リクエストをスレッドで投げて待つ」は、ちゃんと重なる。
2. **C 拡張が明示的に手放したとき**。`Py_BEGIN_ALLOW_THREADS` / `Py_END_ALLOW_THREADS`(第2弾の主役)。NumPy の重いループが並列に効くのはこれ。
3. **一定時間が経って、他のスレッドが「代わって」と要求したとき**。これが次の switch interval の話です。

### switch interval — 時間で殴る

CPU バウンドな Python コード(I/O も C 拡張呼び出しもしない、ただの重いループ)は、放っておくと GIL を握りっぱなしになります。これを防ぐため、CPython は次の仕組みを持ちます。

> 待機中のスレッドが「GIL を手放してくれ」というフラグ(`gil_drop_request`)を立てる。GIL を握っている側のスレッドは、バイトコードを何命令か進めるごとに `eval_breaker` をチェックし、フラグが立っていたら区切りのいいところで GIL を手放す。

この「どれくらいの時間待ってからフラグを立てるか」が **thread switch interval** で、[`sys.setswitchinterval()` / `sys.getswitchinterval()`](https://docs.python.org/3/library/sys.html) で読み書きできます。

```python
>>> import sys
>>> sys.getswitchinterval()
0.005
```

**デフォルトは 0.005 秒、つまり 5 ミリ秒**です。重要なのは、ドキュメントが釘を刺している次の点です。

> Note that the actual value of the switch interval may be slightly higher than the value set, since it is the operating system that decides when to actually perform the thread switch, not the interpreter.

つまり、GIL を手放したあと**どのスレッドを次に走らせるかを決めるのは OS スケジューラ**であって、CPython 独自のスケジューラではありません。CPython は「そろそろ代わってあげて」と促すだけで、実際の交代は OS に委ねている。

### なぜ「時間ベース」なのか — 100 バイトコードからの歴史

この時間ベースの仕組みは、Python **3.2**(2009 年、Antoine Pitrou のいわゆる "new GIL")で入りました。`getswitchinterval` / `setswitchinterval` の追加バージョンが 3.2 であることはドキュメントにも明記されています。

それ以前は、`sys.setcheckinterval()` / `sys.getcheckinterval()`(現在は非推奨・実質無効)という別の仕組みで、単位が**時間ではなくバイトコード命令の数**でした。デフォルトは **100 命令ごと**にスレッド切り替えのチェックをする、というもの。

なぜ「命令数」から「時間」へ変えたのか。命令数ベースだと、

- 1 命令が一瞬で終わる軽い処理でも、重い C 関数を 1 回呼ぶ命令でも「1 命令」とカウントされる。実時間の公平性が保証されない。
- マルチコア環境で、CPU バウンドなスレッドが GIL を握ったまま他スレッドを飢えさせる(GIL の取り合いに負け続ける)現象が観測されていた。

new GIL は「100 命令」ではなく「5 ミリ秒」という**実時間の予算**でスレッドに交代を促すことで、この不公平を緩和しました。

### ここで掴むべき一般化

この章の要点は、仕様の暗記ではありません。

> **GIL は、ハードウェアが強制する物理的な壁ではなく、スレッド同士が「区切りのいいところで譲り合う」という協調的な約束で回っている。**

だからこそ、第2弾で見たように **C ループが `ALLOW_THREADS` を打たなければ何も並列化しない**(譲らないスレッドは止まらない)し、逆に**手放しすぎれば**スレッド切り替えのオーバーヘッドで遅くなる。GIL は「ロックを持つ/持たない」の二値ではなく、「**どれくらいの粒度で譲り合うか**」というチューニング可能なパラメータを持った機構なのです。

---

## 4. 同じ現象を、別の名前で — Ruby・Node・Go/JVM

ここで一度 Python を離れます。「全域ロックは Python のクセ」という思い込みを崩すには、他の言語が**同じ問題に対してどう答えたか**を並べるのが一番です。設計空間には、大きく 3 つの座標があります。

### 4.1 Ruby MRI の GVL — 動機まで瓜二つ

Ruby の標準実装 MRI(CRuby)には **GVL(Global VM Lock)** があります。名前が違うだけで、やっていることは GIL とほぼ同じ——1 プロセスに 1 個、Ruby のバイトコードを同時に 1 スレッドしか実行させない。

驚くのは、**存在理由まで同型**だということです。[The GIL and MRI](https://workingwithruby.com/wwrt/gil) が挙げる GVL の 3 つの存在理由は、

1. MRI 内部(C で書かれている)を race condition から守る
2. ガベージコレクションを簡素化する
3. スレッド非安全な C ライブラリ/C 拡張を、複雑な同期から守る

——これは第2章で見た GIL の動機(refcount/内部状態の保護)と、第2弾で見た「C 拡張作者をスレッド安全地獄から守る」という話の、**そっくりそのままの裏返し**です。そして GVL も、ブロッキング I/O(内部の `ppoll(2)` など)では手放されるので、I/O バウンドな Ruby スレッドは重なる。GIL とまったく同じ挙動です。

さらに、Ruby の**別実装**である JRuby や TruffleRuby は GVL を持ちません。これらは JVM や GraalVM という、最初からマルチスレッド GC を備えたランタイムの上に乗っているからです。「言語仕様」ではなく「**実装が抱える C のオブジェクトモデル**」が GVL を要求している、という構図まで CPython と一致しています。

つまり Ruby は、Python とは独立に、しかし**まったく同じ理由で同じ全域ロックにたどり着いた**。これが「GIL は一般現象だ」という主張の、一番直接的な証拠です。

### 4.2 Node.js / V8 — 共有を「消す」ことで勝つ

逆方向の解き方もあります。Node.js(V8)は、そもそも**共有可変状態を作らない**という戦略を採りました。JavaScript の実行は基本的に**単一スレッド + イベントループ**で、複数の処理は「並行」はするが「並列」はしない。

GIL は「守るべき共有がたくさんあるから 1 個のロックで囲う」でしたが、Node は「**守るべき共有をそもそも持たない**から、ロックが要らない」。`worker_threads` は存在しますが、各ワーカは独立した V8 isolate(独立したヒープ)で、メモリを直接共有しない。ロックで守る代わりに、守る対象を消した、という解き方です。

GIL を持つランタイムと「GIL が無い」と言われるランタイムの差は、しばしば「並列化が得意」ではなく「**そもそも共有メモリ並行を提供しない**」だけ、というのは押さえておく価値があります。

### 4.3 Go / JVM — 最初に難しい方を払った側

Go と JVM は、3 つ目の座標です。最初から**細粒度ロック + 真の並列スレッド**で設計されている。Go の goroutine は複数 OS スレッドにスケジューリングされて物理的に並列に走るし、JVM のスレッドも同様。

その代わり、これらのランタイムは「すべての共有データ構造をスレッドセーフに作る」という**重いコストを最初に払って**います。GC もコンカレント/パラレルに動くよう作り込まれている。Python/Ruby が「とりあえず 1 個のロックで動かして、難しい部分は後回し」を選んだのに対し、Go/JVM は「最初に全部払う」を選んだ。

### この 3 択が「全域ロックという現象」の地図

整理すると、共有可変状態 × マルチコアという問題に対する答えは、おおよそ次の 3 つです。

| 戦略 | 代表 | やっていること | コストの払い方 |
|------|------|----------------|----------------|
| ① 全域ロックで囲う | CPython, Ruby MRI | 1 個の粗いロックで内部状態を保護 | 後払い(並列性を犠牲に) |
| ② 共有を消す | Node.js / V8 | 単一スレッド + isolate 分離 | そもそも共有並行を提供しない |
| ③ 最初から細粒度化 | Go, JVM | 全データ構造をスレッドセーフに | 前払い(実装が重い) |

GIL は**この地図の上の一点**にすぎません。そして次の章で見るように、①を選んだ者は、十分に時間が経つと③へ向かって移動を始めます。

---

## 5. OS カーネルにも GIL があった — Big Kernel Lock の生と死

「①全域ロックで囲い、後で③へ移動する」という現象の、**もっとも完結した実例**は、実は Python でも Ruby でもなく **Linux カーネル**にあります。

### Big Kernel Lock(BKL)

Linux が SMP(対称型マルチプロセッシング、要するにマルチコア)対応を始めたとき、カーネル開発者が採った最初の手は、**カーネル全体を 1 個の巨大なロックで囲う**ことでした。これが **Big Kernel Lock(BKL)** です。

挙動は GIL と不気味なほど似ています。プロセスが**カーネル空間に入るときに BKL を取得し、出るときに解放する**。つまり、複数の CPU があっても、カーネルコードは実質 1 個ずつしか走らない。

そして、その**導入の動機**が決定的に重要です。BKL は「これが最終的に正しい設計だ」と思って入れられたのではなく、**coarse-grained(粗粒度)から fine-grained(細粒度)ロックへ移行するための過渡的な足場**として導入されました。「まず 1 個の粗いロックで正しく動かし、それから 1 サブシステムずつ細粒度ロックに置き換えていく」——この順序を可能にするための、意図的な踏み台だったのです。

これは第2章で見た GIL の動機と、論理的に同じものです。「守るべき内部状態が大量にあり、いきなり全部に細粒度ロックを付けるのは難しすぎる。だからまず 1 個で囲って、後で削っていく」。

### そして BKL は解体された

カーネルの BKL は、長い時間をかけて 1 サブシステムずつ細粒度ロックに置き換えられ、最終的に **Linux 2.6.39(2011 年)で完全に削除**されました(Arnd Bergmann による仕上げ)。このとき LWN などのコミュニティが「**Ding Dong, the Big Kernel Lock is Dead**(でかいカーネルロックは死んだ)」と祝った、というのは有名な逸話です。

同じことは BSD でも起きています。FreeBSD は SMP 対応の初期に **Giant lock** と呼ばれる単一の巨大ロックを導入し、SMPng プロジェクトで何年もかけて段階的に分解していきました。

### Python をこの時間軸の上に置く

ここで、本記事の中心的な主張が形になります。

> **GIL・GVL・BKL は、いずれも「①全域ロックで囲う」という同じ第一歩から始まった。違いは正しさではなく、時間軸上の位置だけ。**

- Linux カーネル: 囲う → 細粒度化 → **削除しきった**(2011)。フルコース完走。
- FreeBSD: 同じく Giant lock を段階分解。
- CPython / Ruby MRI: 囲う → **今まさに細粒度化の途中**。

「とりあえず 1 個の粗いロックで動かし、必要になった部分だけ後から細粒度化する」は、**間違い**ではありません。むしろ、巨大で複雑なシステムを正しく動かすための**王道のエンジニアリング順序**です。GIL を「Python の怠慢」と見るのは、BKL を「Linux の怠慢」と呼ぶのと同じくらい的外れで、実態は「正しい第一歩を踏んで、いま後半生にいる」だけなのです。

---

## 6. コンテナと GIL — CPU 制限が二重に効く場所

ここまでは「GIL とは何か」の話でした。この章では、それが**現代の実行環境=コンテナ**でどう効いてくるかを見ます。ここは実務に直結します。

### まず、GIL があるとスケールはどう決まるか

GIL のせいで、1 プロセス内の CPU バウンド Python は 1 コアぶんしか使えません。マルチコアを使い切る正攻法は 2 つです。

1. **プロセスを分ける**(`multiprocessing`)。Wikipedia の定義どおり、**プロセスごとに独立した GIL** を持つので、N プロセス立てれば N コア使える。
2. **C 拡張に降りる**。NumPy のように内部で `Py_BEGIN_ALLOW_THREADS` してネイティブスレッドを張る。

どちらにせよ、現実のスケールは「**プロセス数 × そのマシンが実際に使える CPU 数**」で決まります。そして、この「実際に使える CPU 数」をコンテナの中で正しく数えるのが、意外と落とし穴だらけなのです。

### `os.cpu_count()` はコンテナの制限を見ない

古典的な罠は、ワーカ数やプールサイズを `os.cpu_count()` で決めてしまうことです。

```python
import os
os.cpu_count()   # ← ホストの論理 CPU 数を返しがち
```

`os.cpu_count()` は**システム全体の論理 CPU 数**を返します。ところがコンテナは、cgroup の CPU quota や CPU affinity で「このコンテナは 2 コアぶんまで」と**制限されている**ことが多い。32 コアのホスト上で 2 コア制限のコンテナを動かしているのに `os.cpu_count()` が 32 を返すと、プロセスプールを 32 並列で作ってしまい、実際には 2 コアを 32 プロセスで奪い合う **oversubscription** が起きます。

### 3.13 の回答 — `os.process_cpu_count()`

Python **3.13** は、まさにこの問題に対する API を追加しました。[`os.process_cpu_count()`](https://docs.python.org/3/library/os.html) です。

```python
import os
os.process_cpu_count()   # 呼び出しプロセスが実際に使える論理 CPU 数(affinity 反映)
os.sched_getaffinity(0)  # 使用可能な CPU の集合そのもの(Linux)
```

`process_cpu_count()` は「呼び出しスレッド・プロセスが利用可能な論理 CPU 数」を返し、CPU affinity による制限を反映します。さらに [What's New in 3.13](https://docs.python.org/3/whatsnew/3.13.html) によれば、環境変数 **`PYTHON_CPU_COUNT`**(または `-X cpu_count`)で、アプリのコードを書き換えずに「見える CPU 数」を上書きできるようになりました。コンテナのオーケストレータ側から CPU 数を注入する、という運用が素直になります。

実務的には、**プールサイズやワーカ数は `os.cpu_count()` ではなく `os.process_cpu_count()`(3.13 未満なら `len(os.sched_getaffinity(0))`)で決める**、が現代の作法です。

### C 拡張との「合わせ技」の罠

もう一段ややこしいのは、GIL を手放す C ライブラリと `multiprocessing` を**組み合わせたとき**です。

NumPy/SciPy が内部で使う OpenBLAS や MKL は、第2弾で見たように GIL を手放して**自前のスレッドプール**を張ります。ここで、

- `multiprocessing` で 8 プロセス起動し、
- 各プロセスの中で NumPy が BLAS スレッドを 8 本張る

と、`8 × 8 = 64` スレッドが、コンテナに許された 2 コアを奪い合う、という**古典的 oversubscription** が完成します。対策は `OMP_NUM_THREADS` / `OPENBLAS_NUM_THREADS` で BLAS のスレッド数を絞ること。「GIL があるからプロセスで並列化したら、今度は GIL を手放す C ライブラリが裏でスレッドを増やしていた」という、層をまたいだ罠です。

### この章のまとめ

> GIL は「1 プロセス内の並列を 1 個に絞る」。だから現実のスケールは **プロセス数 × コンテナが許す CPU** で決まる。その「コンテナが許す CPU」を正しく数える API(`process_cpu_count`)が 3.13 でようやく標準に揃い、さらに C 拡張のスレッドまで含めて勘定しないと oversubscription で逆に遅くなる。

GIL を理解することは、最終的に「**どこに並列の予算があり、それをどう配るか**」を設計できるようになることです。

---

## 7. 全域ロックの解体 — free-threading は Python でどこまで来たか

第5章で「①全域ロックを採った者は、やがて③細粒度化へ向かう」と書きました。Python は今まさにその移動の途中です。それが **free-threaded build(no-GIL、PEP 703)** です。

### なぜ外すのが「難しかった」のか

GIL を外すのが何十年も難航したのは、第2章の裏返しです。**refcount が全オブジェクトの全アクセスに乗っている**ため、これを素朴にスレッドセーフ化(`Py_INCREF` を毎回アトミック操作に)すると、**マルチスレッドにすらしていない単一スレッドのコードまで激遅になる**。過去の no-GIL の試みは、ここで「並列化は得意になったが、普通のスクリプトが 2 倍遅い」という壁にぶつかって潰れてきました。

PEP 703(Sam Gross 提案、2023 年受理)は、この壁を複数の技術の組み合わせで越えました。整理すると、

- **biased reference counting**: オブジェクトを「主に触るスレッド」に偏らせ、そのスレッドからの refcount 操作は非アトミックの安いパスで済ませる。アトミック化の代償を減らす中核。
- **immortal objects(PEP 683、3.12)**: `None` / `True` / 小整数のような「絶対に消えない」オブジェクトは refcount をそもそも動かさない(第2弾で触れた話)。複数スレッドが `None` の refcount を奪い合ってキャッシュラインが暴れるのを防ぐ布石。
- **deferred reference counting**: 一部の参照は即時に数えず、後でまとめて精算する。
- **per-object locks**: GIL を「全部を守る 1 個」から、**各 `list` / `dict` / `set` ごとの軽量ロック**へ砕く。まさに「①→③の細粒度化」そのもの。
- **QSBR(Quiescent State Based Reclamation)**: ロックを取らずに読める list/dict API を支える、安全なメモリ回収方式。
- **critical sections**: デッドロックを避けつつロックを一時保留する仕組み(C 拡張から `Py_BEGIN_CRITICAL_SECTION` で使う。第2弾参照)。
- **mimalloc**: GC を簡素化し、読み取り時のロックを避けやすいアロケータ。

「GIL を消す」とは、要するに**この粒度の細かいロック群とロックフリー技法の束で、GIL 1 個が担っていた保護を肩代わりさせる**ことです。第5章で見た BKL の「1 サブシステムずつ細粒度ロックに置き換える」と、構造的にまったく同じことをやっています。

### 単一スレッド性能の代償

それでも、ただではありません。PEP 703 自身の計測では、GIL を無効化したビルドの**単一スレッド性能ペナルティ**は、

- Intel Skylake で **約 6 %**、AMD Zen 3 で **約 5 %**

程度とされています(マルチスレッド時はもう少し増える)。「単一スレッドが 2 倍遅い」だった過去の試みと比べれば、実用域に入ったと言える数字です。

### 現状(3.13 → 3.14)— PEP 779 の 3 フェーズ

free-threading の導入は、[PEP 779](https://peps.python.org/pep-0779/) が定めた **3 フェーズ**で段階的に進みます。

| フェーズ | バージョン | 位置づけ |
|----------|-----------|----------|
| **Phase I** | 3.13 | experimental。`--disable-gil` ビルドが提供され、`python3.13t` として入手できるが「実験的」と明示 |
| **Phase II** | 3.14 | **officially supported**(ただし optional)。サポート対象に格上げ |
| **Phase III** | 将来 | free-threaded build を**デフォルト**にする(時期・条件は今後の判断) |

つまり 2025 年時点では、free-threaded Python は「**公式サポートされた、しかしまだ選択式の**」ビルドです。デフォルトの Python は依然として GIL ありです。

### 実行時・ビルド時のフック

free-threaded ビルドかどうか、GIL が実際に効いているかは、[free-threading の HOWTO](https://docs.python.org/3/howto/free-threading-python.html) と [sys](https://docs.python.org/3/library/sys.html) のとおり次で判別・制御します。

```python
import sys, sysconfig

sys._is_gil_enabled()                          # 今この瞬間 GIL が有効か(3.13+)
sysconfig.get_config_var("Py_GIL_DISABLED")    # ビルドが free-threading 対応か(1 なら対応)
```

- 環境変数 **`PYTHON_GIL=1`** または **`-X gil=1`** で、free-threaded ビルドでも**実行時に GIL を再有効化**できる。
- free-threading 非対応の C 拡張を import すると、ランタイムが**自動的に GIL を再有効化**し警告を出す(第2弾の `Py_mod_gil` 宣言の話)。デフォルトは安全側。

そして配布の面では、第2弾で伏線を張った **abi3 がそのままでは free-threaded build に使えない**問題があり、それを追いかけるのが [PEP 803 の `abi3t`](https://peps.python.org/pep-0803/) で、Steering Council は「Stable ABI for free-threading を 3.15 に向けて用意する」としています。

### BKL との類比で締める

第5章の地図に Python を置き直すと、こうなります。

> Linux カーネルは「囲う → 細粒度化 → 削除」をやりきった(2011)。**Python は今まさに「細粒度化」の真っ最中**で、`per-object lock` と `QSBR` で GIL を砕いている。free-threading が将来デフォルトになる日(Phase III)は、Python にとっての「Ding Dong, the GIL is Dead」になる。

free-threading は Python の特殊事情で起きている革命ではありません。**全域ロックを採ったすべてのランタイムが辿る、後半生の標準的な一区切り**です。

---

## 8. まとめ — 「全域ロック」というレンズ

このシリーズで、Python の実行モデルが 3 つの層で読めるようになりました。GIL は、その最後の「並行性の層」に座ります。

| 層 | 記事 | 中心概念 | 守る/砕く対象 |
|----|------|----------|---------------|
| バイトコード層 | 第1弾 | `.pyc` / VM 評価ループ | ソースを正、起動を速く |
| C 拡張層 | 第2弾 | 参照カウント / C API | New/Borrowed/Stolen、GIL の解放 |
| **並行性層** | **本作** | **GIL = 全域ロック** | **refcount/内部状態を 1 個で守り、いま細粒度へ砕く** |

そして、この記事で一番持ち帰ってほしいのは、GIL を見る**レンズ**です。

> **共有可変状態を 1 個の粗いロックで囲い、実装と起動を簡潔にし、必要になったら細粒度化する。** これが GIL・GVL・BKL を貫く、たった一本の設計判断だった。

Python の GIL は、Ruby の GVL とも、Linux の BKL とも、同じ第一歩から出発していました。違うのは正しさではなく、解体がどこまで進んだかという時間軸の位置だけ。カーネルは完走し、Python は今まさに走っている途中です。

最後に、実務の持ち帰りを 3 つ。

1. **GIL を見たら「並列が 1 個に絞られる」と読む。「遅い」ではない。** I/O バウンドや C 拡張内ループは別世界。問題は CPU バウンドな Python の並列だけ。
2. **CPU バウンドは「プロセス数 × コンテナが許す CPU」で設計する。** ワーカ数は `os.process_cpu_count()`(3.13+)で数え、BLAS のスレッドまで含めて oversubscription を避ける。
3. **3.13t / 3.14 の free-threaded build を試すとき、何が変わるかを位置づけられる。** `sys._is_gil_enabled()` で確認し、abi3 が効かない(→ `abi3t` 待ち)ことを把握しておく。

次に「Python は GIL があるから…」という一文を見たとき、それが Ruby と Linux カーネルと地続きの、**全域ロックという普遍的な現象の話**だと読めるようになっていれば、この記事は役目を果たしたことになります。

---

## 参考

### Python 公式ドキュメント
- [Glossary — global interpreter lock](https://docs.python.org/3/glossary.html)
- [sys — System-specific parameters and functions](https://docs.python.org/3/library/sys.html)(`setswitchinterval` / `getswitchinterval` / `_is_gil_enabled`)
- [os — Miscellaneous operating system interfaces](https://docs.python.org/3/library/os.html)(`process_cpu_count` / `sched_getaffinity`)
- [Python support for free threading](https://docs.python.org/3/howto/free-threading-python.html)
- [What's New in Python 3.13](https://docs.python.org/3/whatsnew/3.13.html)

### PEP
- [PEP 703 – Making the Global Interpreter Lock Optional in CPython](https://peps.python.org/pep-0703/)
- [PEP 779 – Criteria for supported status for free-threaded Python](https://peps.python.org/pep-0779/)
- [PEP 803 – "abi3t": Stable ABI for Free-Threaded Builds](https://peps.python.org/pep-0803/)

### 一般現象(他言語・OS)
- [Global interpreter lock — Wikipedia](https://en.wikipedia.org/wiki/Global_interpreter_lock)
- [Giant lock — Wikipedia](https://en.wikipedia.org/wiki/Giant_lock)(Big Kernel Lock / FreeBSD Giant lock)
- [The GIL and MRI — Working With Ruby Threads](https://workingwithruby.com/wwrt/gil)

### シリーズ関連記事
- [Python は本当にインタプリタ言語か?](./python_bytecode_internals)
- [Python C 拡張の地図](./python_c_extensions_internals)
