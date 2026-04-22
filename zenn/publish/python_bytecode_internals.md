---
title: "Pythonは本当にインタプリタ言語か? — __pycache__・.pyc・バイトコードの裏側を読み解く"
emoji: "🐍"
type: "tech"
topics: ["python", "cpython", "bytecode", "performance", "architecture"]
published: false
---

## この記事について

Python を毎日書いている。`__pycache__` が勝手にできていることも、コミットしないことも知っている。`.pyc` という拡張子も見たことがある。

それでも、同僚や後輩から以下のように聞かれて、**30 秒で自分の言葉で答えられるか** と言われると、中上級者でも詰まる人は多いはずです。

- 「Python はインタプリタ言語だから `.py` を毎回読んでるんですよね?」
- 「`__pycache__/foo.cpython-312.pyc` って、なんでこんな変な名前なんですか?」
- 「`-O` つけると速くなるって聞いたんですけど本当ですか?」
- 「Docker の中で `.pyc` って作った方がいいんですか? どうせ毎回捨てられるのに?」
- 「hash-based pyc って何が嬉しいんですか?」

この記事は、**CPython が `.py` を実行するときに裏で何が起きているか** を、`__pycache__` と `.pyc` を切り口にしてきれいに整理することを目的にしています。構文や `import` の使い方ではなく、**「Python という実行系がどういう設計判断をしているのか」** を読み解く話です。

対象は以下のような人:

- Python 歴 2 年以上で、`__pycache__` は知っているが import まわりの内部モデルがない
- Docker / AWS Lambda / CI / 配布 で `.pyc` に絡んで違和感を感じたことがある
- JavaScript(V8)や Java(JVM)と比べて、Python の実行モデルを言語化したい

扱うのは CPython 3.11〜3.14。PyPy や Cython、freeze 系配布ツールの話はしません。

---

## 1. 「インタプリタ言語」という言葉の曖昧さ

まず最初に、この記事の前提をひとつ崩しておきます。

**CPython は `.py` をそのまま実行していません。**

`python foo.py` と叩いた瞬間、CPython は内部でコンパイルを通してから実行しています。ここでいう「コンパイル」はネイティブコード(x86_64 の機械語)ではなく、**CPython VM が解釈する「バイトコード」** への変換です。

つまり、Python の実行モデルは

> ソース(`.py`)→ AST → バイトコード → VM 評価ループ(`ceval`)

という 4 段構成になっていて、「Python はインタプリタ言語」という言葉が本当に指しているのは、**最後の「VM 評価ループでバイトコードを 1 命令ずつ実行する」段階だけ** です。

`__pycache__` と `.pyc` は、この 4 段構成のうち **「バイトコード」段階をディスクに永続化する仕組み** です。つまり、2 回目以降の import で「ソース → AST → バイトコード」の 3 段ぶんをスキップするための装置です。

これが分かると、この先の仕様は全部「じゃあ、その永続化をどう安全にやるか」の話として一本筋で読めるようになります。

---

## 2. dis で実際にバイトコードを覗いてみる

抽象論だけ続けても仕方ないので、実物を見ます。標準ライブラリの [`dis`](https://docs.python.org/3/library/dis.html) を使うと、任意の関数がどんなバイトコードに翻訳されているかを確認できます。

```python
import dis

def add(a, b):
    return a + b

dis.dis(add)
```

出力(Python 3.12 の例):

```
  1           RESUME                   0

  2           LOAD_FAST                0 (a)
              LOAD_FAST                1 (b)
              BINARY_OP                0 (+)
              RETURN_VALUE
```

左から順に、行番号 / opcode / 引数 / argval(人間向けの解釈)です。`LOAD_FAST` が 2 回、`BINARY_OP` が 1 回、`RETURN_VALUE` が 1 回。たったこれだけが、`return a + b` の正体です。

### Python 3.11 以降の adaptive/specialized interpreter

Python 3.11 で導入された「adaptive specializing interpreter」の影響で、`dis` の出力にはいくつか注意点があります([dis docs](https://docs.python.org/3/library/dis.html))。

- 3.11 で **`CACHE` 命令** が追加された。opcode 間に埋め込まれた「型情報などを保持するスロット」で、通常は `dis` の出力からは隠される。`dis.dis(add, show_caches=True)` で表示できる。
- 実行中に頻度の高い opcode が「特殊化」される。たとえば `BINARY_OP` が `BINARY_OP_ADD_INT` に書き換わる、など。これは `dis.dis(add, adaptive=True)` で見られる。
- 3.12 以降、jump 命令の引数は「バイトオフセット」ではなく「命令オフセット」になり、3.13 ではジャンプ先がオフセットではなく**ラベル** として表示されるようになった。

中上級者としてここで掴んでおくべきなのは、**「Python のバイトコードは Python マイナーバージョン単位で頻繁に変わる」** という事実です。これは後で出てくる `.pyc` の magic number の話に直結します。

### バイトコードは「何が速くなるか」を素直に見せてくれる

いくつか実例を見ておきます。

```python
def in_tuple(x):
    return x in (1, 2, 3, 4, 5)

def in_set(x):
    return x in {1, 2, 3, 4, 5}
```

`dis.dis(in_tuple)` と `dis.dis(in_set)` を比べると、**どちらも定数としてコンパイル時に畳み込まれている**(`LOAD_CONST (1, 2, 3, 4, 5)` と `LOAD_CONST frozenset({...})`)のが見えます。後者が定数畳み込みされる `frozenset` リテラルに変わっているのが面白いポイントで、「ループ内で `x in {...}` を書いても毎回 set を作り直すコストはない」という一般論の根拠がここに見えます。

`dis` を使う習慣があると、「このコードは本当に速いのか、遅いのか」を推測ではなくバイトコードの差で話せるようになります。これは実務でパフォーマンスを議論するときに非常に強い道具です。

---

## 3. `.pyc` と `__pycache__` の構造 — PEP 3147 が解いた問題

ここからが本題。先ほどの「バイトコード」をディスクに serialize したものが `.pyc` です。

現代の CPython では、`foo.py` を import した瞬間、`__pycache__/foo.cpython-312.pyc` というファイルが隣のディレクトリに生成されます。この **変なファイル名** には、歴史的な理由があります。

### PEP 3147 以前の悲劇

PEP 3147([PEP 3147 – PYC Repository Directories](https://peps.python.org/pep-3147/))以前、`.pyc` は `.py` と同じ場所に **平置き** されていました。

```
foo.py
foo.pyc
```

これには 2 つの問題がありました。

1. **複数の Python バージョンが共存できない。** Python 2.7 で生成した `foo.pyc` と Python 3.2 で生成した `foo.pyc` は**同じ名前**です。片方が上書きされる。
2. **`foo.py` を削除しても `foo.pyc` が残る → 意図せず古いコードが動く。** リネームしたつもりが古い `.pyc` がロードされて、デバッグで 1 日溶ける、というインシデントが実際に起きていた。

### PEP 3147 の解決策

PEP 3147 は、次の形でこの問題を解決しました([PEP 3147](https://peps.python.org/pep-3147/))。

```
foo.py
__pycache__/
    foo.cpython-312.pyc
    foo.cpython-313.pyc   # Python 3.13 を使うと増える
```

- `.pyc` は **`__pycache__` サブディレクトリの中** に置く
- ファイル名には **`cache_tag`**(例: `cpython-312`)が埋め込まれる
- 同じソースに対する **異なる Python バージョンの .pyc が共存可能**
- **ソースが消えた `.pyc` は無視される**(PEP 3147 の明確な仕様)

`cache_tag` は `sys.implementation.cache_tag` で取れます。

```python
>>> import sys
>>> sys.implementation.cache_tag
'cpython-312'
```

### `importlib` で「どの .pyc を探しにいくか」を計算する

実務で覚えておくと便利なのが、[`importlib.util`](https://docs.python.org/3/library/importlib.html) の 2 つの関数です。

```python
import importlib.util

importlib.util.cache_from_source('/foo/bar/baz.py')
# -> '/foo/bar/__pycache__/baz.cpython-312.pyc'

importlib.util.source_from_cache('/foo/bar/__pycache__/baz.cpython-312.pyc')
# -> '/foo/bar/baz.py'
```

この 2 関数が、**CPython の import システムが `.py` と `.pyc` を行き来するときに使っている本物のロジック** です。自分で「この `.pyc` はどのソースのキャッシュなんだ?」と調べたいとき、この関数を直接呼べば迷わない。

### 「ソースオンリーパッケージ」という例外

ここには 1 つの例外があります。[tutorial/modules](https://docs.python.org/3/tutorial/modules.html) に書かれている通り:

> Python does not check the cache in two circumstances. First, it always recompiles and does not store the result for the module that's loaded directly from the command line. Second, it does not check the cache if there is no source module.

つまり、**`.py` が無く `.pyc` だけがある** ケースに限り、`__pycache__` ではなく**ソースと同じ場所に置かれた `.pyc`** が有効になります。これは「バイトコードだけの配布」を成り立たせるための逃げ道ですが、実務で使うケースはほぼありません。記事で押さえておくべきは「`__pycache__` の中の `.pyc` は、ソースが消えたら必ず無視される」という挙動の方です。

---

## 4. `.pyc` のヘッダ構造 — magic number を自力で読む

`.pyc` のバイナリは、そこまで怖いものではありません。先頭 **16 バイトがヘッダ** で、その後にシリアライズされた code object が続くだけです。

PEP 552([PEP 552 – Deterministic pycs](https://peps.python.org/pep-0552/))の仕様を引用すると:

> The pyc header currently consists of 3 32-bit words. We will expand it to 4. The first word will continue to be the magic number, versioning the bytecode and pyc format. The second word, conceptually the new word, will be a bit field.

つまり、4 つの 32-bit ワード(計 16 バイト)構成で:

| オフセット | 内容 |
| --- | --- |
| 0〜3 | magic number(バイトコードフォーマットのバージョン) |
| 4〜7 | bit field(後述) |
| 8〜11 | timestamp または hash 前半 |
| 12〜15 | source size または hash 後半 |

### バイナリダンプしてみる

試しに Python で自前に読んでみます。

```python
import importlib.util
import struct
from pathlib import Path

pyc = Path("__pycache__") / "foo.cpython-312.pyc"
data = pyc.read_bytes()

magic = data[0:4]
bit_field = struct.unpack("<I", data[4:8])[0]
word3 = struct.unpack("<I", data[8:12])[0]
word4 = struct.unpack("<I", data[12:16])[0]

print(f"magic       = {magic.hex()}")
print(f"cur MAGIC   = {importlib.util.MAGIC_NUMBER.hex()}")
print(f"bit_field   = {bit_field:#x}")
print(f"word3/word4 = {word3}, {word4}")
```

`importlib.util.MAGIC_NUMBER` が現在の Python のバイトコードバージョン番号です。自分で読み出した `magic` とこれを比較すると、**その `.pyc` が今の Python に対応しているか** が一瞬で分かります。

### bit field の意味

第 2 ワード(bit field)の下位ビットで、残りのヘッダの解釈が変わります([PEP 552](https://peps.python.org/pep-0552/))。

- `bit_field == 0` → 従来の **timestamp-based pyc**。word3 は source の mtime、word4 は source のサイズ。
- `bit_field != 0` → **hash-based pyc**。word3/word4 は source の hash(8 バイト)。下位ビットの意味は:
  - bit 0(値 `1`): ファイルが hash-based であることを示す
  - bit 1(値 `2`): `check_source` フラグ。立っていれば **checked-hash**(毎回ハッシュを再計算して検証する)、立っていなければ **unchecked-hash**(ファイルがあれば検証せず信頼する)

つまり、実際に現れる値は大まかに `0`(timestamp)、`1`(hash, unchecked)、`3`(hash, checked)の 3 パターンです。

ここまで分かると、`.pyc` は「難読化されたバイナリ」ではなく、**ヘッダの先頭数バイトだけでその正体が分かる素直なシリアライズ**であることが見えてきます。裏を返すと、**`.pyc` はソースの obscurity としてはほぼ意味がない** ということでもあります(後の節で触れます)。

---

## 5. キャッシュ無効化 — timestamp-based と hash-based(PEP 552)

`.pyc` を永続化するうえで一番難しいのは、**「これ、まだ使っていい .pyc なんだっけ?」** を判定する部分です。CPython はここに 2 つの方式を持っています。

### 5.1 timestamp-based(デフォルト)

仕組みは単純で、`.pyc` のヘッダにソースの mtime と size を埋めておき、import 時に:

1. `.py` の mtime を stat する
2. `.pyc` ヘッダの mtime と一致するか比較する
3. 一致しなければ `.pyc` を破棄して再コンパイル

これはほとんどのワークフローで問題なく動きます。開発中にエディタで保存すれば mtime が進むので、次の import で自動的に再コンパイルされる。

ただし、**mtime に頼ることによる既知の不安定性** があります。

- **tar / zip の展開** で mtime が展開時刻にリセットされる実装がある。git checkout も同様で、mtime はチェックアウト時刻になる(ファイル内容の新旧を反映しない)
- **ビルド直後にすぐ import する CI** などで、ソースと `.pyc` の mtime が同秒になり、粒度不足で古い方が通ってしまうケース
- **再現ビルド** を壊す。同じソースから 2 回ビルドすると、mtime が違うため `.pyc` がビット単位で一致しない

### 5.2 hash-based(PEP 552、Python 3.7+)

これらの不安定性に対して、PEP 552 が **ソースの内容ハッシュ** を mtime の代わりに埋める方式を追加しました。Python 3.7+ で使えます([reference/import §5.4.6](https://docs.python.org/3/reference/import.html))。

hash-based pyc には 2 亜種あります:

| 種別 | 挙動 |
| --- | --- |
| **checked-hash** | import のたびにソースをハッシュ再計算して突き合わせる。mtime 方式より安全だが、I/O コストは増える |
| **unchecked-hash** | ファイルがあれば無条件に信頼する。ビルド時に「ソースは変わらない」と保証できるケース専用 |

ランタイム側からは `--check-hash-based-pycs default|always|never` で、この検証挙動を override できます([using/cmdline](https://docs.python.org/3/using/cmdline.html))。

### 5.3 `SOURCE_DATE_EPOCH` と再現ビルド

[`compileall`](https://docs.python.org/3/library/compileall.html) の挙動で実務的に重要なのは次の一文です:

> The default is `timestamp` if the `SOURCE_DATE_EPOCH` environment variable is not set, and `checked-hash` if the `SOURCE_DATE_EPOCH` environment variable is set.

`SOURCE_DATE_EPOCH` は Debian 由来の再現ビルド用の標準環境変数で、「ビルドに使う擬似的な現在時刻」を秒で与えるものです。これを設定すると、`compileall` は自動で hash-based pyc を使うようになる。つまり、**「ビルド結果がビット一致するように `.pyc` を作りたい」なら、`SOURCE_DATE_EPOCH` を立てれば勝手に正しい方が選ばれる** という設計になっています。

これは地味ですが、「Python を含むディストリビューションの再現ビルド」という現代的な要件に、言語レベルで応答したエンジニアリング判断で、PEP 552 の本当の価値はここにあります。

---

## 6. 最適化レベルと `.opt-N.pyc`(PEP 488)

次に `-O` と `-OO` の話。

### 6.1 何を変えるオプションか

- `-O`: `assert` 文を外す / `__debug__` を `False` にする
- `-OO`: `-O` の効果に加えて、`__doc__`(docstring)を削除する

名前から「パフォーマンス最適化をする」と想像しがちですが、**実態はサイズを少し小さくする程度** です。[tutorial/modules](https://docs.python.org/3/tutorial/modules.html) にも明記されています:

> A program doesn't run any faster when it is read from a `.pyc` file than when it is read from a `.py` file; the only thing that's faster about `.pyc` files is the speed with which they are loaded.

**実行時の CPU 速度は変わりません**。ロード時間だけです。

### 6.2 PEP 488 以前の問題: `.pyo`

Python 3.5 以前、最適化した .pyc には `.pyo` という別拡張子が使われていました。しかしこれには:

- `-O` と `-OO` の区別がファイル名から付かない
- 異なる最適化オプションで生成された `.pyo` が同じ名前で上書きされ得る

という問題がありました。

### 6.3 PEP 488: 拡張子を `.pyc` に統一し、名前に `opt-N` を埋める

PEP 488([PEP 488 – Elimination of PYO files](https://peps.python.org/pep-0488/))は、この問題を「拡張子を統一して、最適化レベルをファイル名の一部に格上げする」という形で解決しました。

```
foo.py
__pycache__/
    foo.cpython-312.pyc          # 最適化なし
    foo.cpython-312.opt-1.pyc    # -O でコンパイル
    foo.cpython-312.opt-2.pyc    # -OO でコンパイル
```

`.opt-N` は cache_tag と拡張子の間に挟まります。これによって、**1 つの `.pyc` ファイルを見ただけで、Python バージョン・最適化レベル・バイトコードかどうか**がすべて読み取れる、という気持ちのいい設計になりました。

### 6.4 実務上の落とし穴

`-OO` の **docstring 削除** は、中上級者向けに 1 つ注意点があります。

- `inspect.getdoc()`, `help(func)`, pydantic の一部バージョン、FastAPI の自動ドキュメント、Sphinx の autodoc など、**docstring に依存しているライブラリは `-OO` で壊れる**
- テストや CI が `-OO` で走っていないと、本番で初めて気付くことがある

また、`assert` の抜け落ちも地味に重要です。`-O` は `assert` を全消去するので、「本番ではアサーションを殺して速度を稼ぐ」意図でも使えるし、**逆に「`assert` でデータバリデーションをしてはいけない」という標準的な警告の根拠** にもなっています。

---

## 7. Python の構造 — 強みと弱み

ここまでの仕様から、Python の強みと弱みが同じ根っこから出ていることが見えてきます。

### 強み

1. **バイトコードはプラットフォーム非依存**。[tutorial/modules](https://docs.python.org/3/tutorial/modules.html) にも「the compiled modules are platform-independent」と書かれているとおり、`.pyc` だけあれば x86_64 でも arm64 でも動く。コンテナイメージを multi-arch 対応にするときに、C 拡張と違って何もしなくていい層。
2. **自動再コンパイル**。mtime が進めば自動で `.pyc` を作り直す。開発者は「ビルド」というステップを意識しなくていい。これはスクリプト言語としての体感速度に直結している。
3. **import が 2 回目以降速い**。ソース → AST → バイトコード の 3 段階が、2 回目以降は「バイトコードをロードするだけ」に短縮される。CLI ツールや、多数のサブコマンドから共有ライブラリを叩くようなワークフローに効く。

### 弱み

1. **バイトコードは Python マイナーバージョン固着**。magic number が 3.11 / 3.12 / 3.13 で変わるので、`cpython-311.pyc` は 3.12 では読めない。`__pycache__` に異なるバージョンの `.pyc` が並ぶのは、この固着を前提にした共存策。
2. **`.pyc` は速くしない(実行速度を)**。ロード時間だけ。「Python を速くしたい」人が `.pyc` にたどり着いても、期待するほどのスループットは得られない。
3. **`.pyc` はソースの難読化にならない**。magic number はヘッダ 4 バイトで取れる、中身は `dis.dis` で読める。IP 保護目的で `.pyc` だけ配布しても意味がない、という結論になる。
4. **mtime 依存の invalidation は壊れやすい**。5.1 で書いた通り、tar 展開・git checkout・再現ビルドで落とし穴が出る。PEP 552 はこの弱みに対するパッチ。

この 2 つのリストが、根本的には同じ設計判断から出ていることに注意してください。**「import 時に勝手にソースを正として比較し、古ければ作り直す」** という単純な規約を徹底したからこそ、開発体験は良くなり、代償として配布・再現ビルド・固着という弱みが出ている。

---

## 8. V8 との対比 — 「起動を速くする側」vs「実行を速くする側」

Python をもっと立体的に見るために、JavaScript 実行系(V8)と対比してみます。

### V8 の実行パイプライン

V8 は、実行モデルとしては驚くほど Python に似ています。ソースを **Ignition** というバイトコード interpreter 用のバイトコードに落として実行する、という部分は同じです([Launching Ignition and TurboFan](https://v8.dev/blog/launching-ignition-and-turbofan))。

ただし決定的に違うのは、V8 は「ホットな関数」を検出して、**ランタイム中により上位のコンパイラに tier-up する**設計になっていることです。

```
Ignition (interpreter)
    ↓ ホットなら
Sparkplug (非最適化ベースライン JIT)         [V8 v9.1+]
    ↓ さらにホットなら
Maglev (中間最適化 JIT)                      [2023+]
    ↓ さらに
TurboFan (最適化 JIT、機械語へ)
```

参考: [Sparkplug](https://v8.dev/blog/sparkplug), [Maglev](https://v8.dev/blog/maglev)。

つまり V8 は、**「同じ関数が何万回も呼ばれる世界(ブラウザのイベントループ、Node のサーバ)」に最適化されている**。実行中にプロファイルを取って、熱い部分を本物の機械語に焼いていく。

そして V8 は、**バイトコードを基本的にディスクに永続化しません**。毎起動ごとにソース → バイトコードを作り直す前提です(Chromium の Code Caching は別レイヤで、V8 のコア言語機能としては持っていない)。

### CPython の設計は真逆

CPython は逆です。

- **バイトコードをディスクに永続化する**(`.pyc`)
- **ランタイムでの JIT 最適化は基本しない**(3.11 の adaptive specializing interpreter で opcode レベルの特殊化は入ったが、JIT ではない。3.13+ の experimental JIT はまだ既定ではない)

つまり CPython は、**「スクリプトや CLI ツールが起動 → 有限回実行 → 終了」という世界** を暗黙の前提にしている。サーバとして 24 時間動き続ける用途も当然あるけれど、言語の基本姿勢としては「起動して import を大量にこなすまで」のコストを削ることに予算を使っている。

### だから `__pycache__` は「Python らしさ」の結晶

この対比を踏まえると、`__pycache__` の存在理由がはっきり見えます。

- V8 は「実行を速くする」に振った → 永続キャッシュを必須にしなくていい(毎回パース + bytecode 化しても、ホットループが JIT でカバーしてくれる)
- CPython は「起動を速くする」に振った → 初回の重い部分(構文解析 + bytecode 化)を `__pycache__` で使い回すしかない

**`__pycache__` は単なる高速化キャッシュではなく、CPython の実行モデルを成立させるための構造的な仕組み** として読めるようになります。

---

## 9. 実務への応用

ここまでの仕様理解を、実際にコードを書くときの判断に変換していきます。

### 9.1 Docker イメージで `compileall` を打つべきか

**結論: 基本的に打って良い。** ただし、`RUN` の位置と invalidation_mode に注意。

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ソースをコピーした後に、ソースと依存ライブラリの両方を事前コンパイル
RUN python -m compileall -q /app /usr/local/lib/python3.12/site-packages
```

メリット:

- コンテナ起動後の **初回 import が速くなる**(特にサーバのコールドスタート)
- runtime の `.pyc` 書き込み権限(コンテナが read-only FS で走る場合)を考えなくて良くなる

注意:

- `COPY . .` より**後** に走らせる必要がある(じゃないとアプリのコードがコンパイル対象に入らない)
- ソース変更で毎回 `.pyc` が作り直されるので、**レイヤキャッシュ的にはソース層の直後に配置する** のが素直
- `-q` 指定で標準出力が静かになる([compileall](https://docs.python.org/3/library/compileall.html) の `-q`)

さらに再現ビルドを意識するなら:

```dockerfile
ENV SOURCE_DATE_EPOCH=1700000000
RUN python -m compileall -q --invalidation-mode checked-hash /app
```

これで `.pyc` が hash-based になり、同じソースから同じバイト列の `.pyc` が出るようになります。

### 9.2 AWS Lambda / 読み取り専用 FS

AWS Lambda のコンテナは、基本的に **`/var/task`(デプロイパッケージが展開されるディレクトリ)に書き込めません**。ここで Python がナイーブに `.pyc` を書こうとすると書き込みに失敗し、[FAQ](https://docs.python.org/3/faq/programming.html) に書かれている通り **`__pycache__` サブディレクトリの生成失敗** で `.pyc` が作られないだけで、処理自体は進みます。ただし、試行コストは無駄に発生する。

選択肢は 2 つ:

1. **`PYTHONDONTWRITEBYTECODE=1` を設定** して、そもそも書き込みを試行しないようにする([using/cmdline](https://docs.python.org/3/using/cmdline.html))
2. **デプロイ時(ビルドマシン側)に `compileall` を走らせて**、`.pyc` 込みでパッケージングする

コールドスタート対策としては 2 の方が強いです。Lambda のコンテナイメージ内に `__pycache__` が同梱されていれば、起動時の import で `.pyc` がそのまま再利用されます。

### 9.3 `PYTHONPYCACHEPREFIX` — ソースツリーを汚さない(Python 3.8+)

ソースコードが置かれるディレクトリが read-only の場合、あるいは IDE やビルドツールが `__pycache__` の存在を嫌う場合、`.pyc` の出力先を別ディレクトリに飛ばせます。

```bash
export PYTHONPYCACHEPREFIX=/var/cache/pycache
python app.py
```

すると `.pyc` は `/var/cache/pycache/` 以下に **ソースツリーをミラーした形** で出力されます([sys.pycache_prefix](https://docs.python.org/3/library/sys.html))。

重要な注意点が `sys` ドキュメントに明記されています:

> if you use `compileall` as a pre-build step, you must ensure you run it with the same pycache prefix (if any) that you will use at runtime.

**ビルド時の `compileall` と runtime の Python で、同じ prefix を使わないと `.pyc` が再利用されない**。Docker で事前コンパイルする構成と組み合わせるときに、ハマりやすい点です。

### 9.4 再現ビルド(Reproducible Build)

Debian / Conda / 各種 wheel ディストリビューションで `.pyc` を配布する場合、**mtime のゆらぎでバイナリ差分が出て署名検証が通らない** という問題が起きます。

対策は 2 段:

1. `SOURCE_DATE_EPOCH` を立てる → `compileall` のデフォルトが `checked-hash` に切り替わる
2. `python -m compileall --invalidation-mode checked-hash` を明示

これで、同じソースから **ビット一致する `.pyc`** が生成されるようになります([PEP 552](https://peps.python.org/pep-0552/))。

### 9.5 `dis` を使ったパフォーマンス調査の小さい実例

最後に、`dis` が実務デバッグでどう効くかの例を 1 つ。

```python
import dis

def lookup_deep(obj):
    return obj.child.grand.leaf

dis.dis(lookup_deep)
```

出力(抜粋):

```
  RESUME 0
  LOAD_FAST 0 (obj)
  LOAD_ATTR 1 (NULL|self + child)
  LOAD_ATTR 3 (NULL|self + grand)
  LOAD_ATTR 5 (NULL|self + leaf)
  RETURN_VALUE
```

`LOAD_ATTR` が 3 回走っています。つまり、同じホットループで `obj.child.grand.leaf` を何度も書くと、**毎回 3 回の属性解決**が走る。

```python
def lookup_deep_cached(obj):
    leaf = obj.child.grand.leaf
    # 以降はローカル変数 leaf を使い回す
    ...
```

このリライトで `LOAD_ATTR` が減って `LOAD_FAST` になる、というのが `dis` の出力でそのまま確認できる。推測ではなく、バイトコードの差として議論できるのが重要です。

---

## 10. まとめ

- `.pyc` / `__pycache__` は単なるキャッシュファイルではなく、**CPython の実行モデル(ソース→AST→バイトコード→VM)** の「バイトコード段階をディスクに永続化する層」として理解するといい
- PEP 3147 の `__pycache__` 構造、PEP 488 の `.opt-N.pyc`、PEP 552 の hash-based pyc は、すべて「`.pyc` を安全に永続化するには」という同じ問いへの段階的な回答
- mtime 依存の invalidation と、hash-based pyc(`SOURCE_DATE_EPOCH` 連動)を使い分けることで、再現ビルドや分散環境での `.pyc` の扱いが安定する
- V8(Ignition/TurboFan)との対比で見ると、Python は **「実行を速くする」より「起動を速くする + ソースは常に権威」に振った言語** として読める。`__pycache__` はその設計判断の結晶
- 実務では `compileall`、`PYTHONPYCACHEPREFIX`、`PYTHONDONTWRITEBYTECODE`、`-O/-OO`、`dis` を **目的別に選び取る道具箱** として捉えるとよい

中上級者として `.pyc` を理解すると、「Python はなぜこう書かれているのか」「なぜこの制約があるのか」という話が、自分のコードを書く判断の根拠になります。次に `__pycache__` を見たとき、それが単なる邪魔なフォルダではなく、Python 全体の設計判断を 3 文字で表したアイコンに見えてくれば、この記事は役目を果たしたことになります。

---

## 参考

- [6. Modules — Python 3 tutorial](https://docs.python.org/3/tutorial/modules.html)
- [5. The import system — Python 3 reference](https://docs.python.org/3/reference/import.html)
- [importlib — Python 3 library](https://docs.python.org/3/library/importlib.html)
- [compileall — Python 3 library](https://docs.python.org/3/library/compileall.html)
- [dis — Python 3 library](https://docs.python.org/3/library/dis.html)
- [sys — Python 3 library](https://docs.python.org/3/library/sys.html)
- [1. Command line and environment — Python 3](https://docs.python.org/3/using/cmdline.html)
- [Programming FAQ — Python 3](https://docs.python.org/3/faq/programming.html)
- [PEP 3147 – PYC Repository Directories](https://peps.python.org/pep-3147/)
- [PEP 488 – Elimination of PYO files](https://peps.python.org/pep-0488/)
- [PEP 552 – Deterministic pycs](https://peps.python.org/pep-0552/)
- [V8: Launching Ignition and TurboFan](https://v8.dev/blog/launching-ignition-and-turbofan)
- [V8: Sparkplug — a non-optimizing JavaScript compiler](https://v8.dev/blog/sparkplug)
- [V8: Maglev — V8's Fastest Optimizing JIT](https://v8.dev/blog/maglev)
