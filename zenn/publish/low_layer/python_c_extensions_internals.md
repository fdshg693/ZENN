---
title: "Python C 拡張の地図 — PyObject・参照カウント・GIL から pybind11・PyO3・abi3・free-threaded build まで"
emoji: "🧩"
type: "tech"
topics: ["python", "cpython", "capi", "performance", "architecture"]
published: false
---

## この記事について

前作 [Python は本当にインタプリタ言語か?](./python_bytecode_internals) で、`__pycache__` と `.pyc` を切り口に **CPython の VM 評価ループ** までを読み解きました。前作の最後で、V8 との対比から「Python は **実行を速くする** よりも **起動を速くする + ソースは常に権威** に振った言語」という結論にたどり着きました。

ではその「実行を速くする」側はどうやって稼いでいるのか。答えは **C 拡張** です。NumPy も Pillow も lxml も pydantic-core も orjson も、ホットパスは Python ではなく C(または C++ / Rust)で書かれている。Python は最初からそういう設計です。

この記事は、その「C で書かれている層」に降りたときに見える世界の地図を描きます。具体的には:

- 「C 拡張」は前作の VM の何処に、どう接続されているのか
- 素の C API で 1 モジュール書くと、何を必ず書くことになるのか
- `Py_INCREF` / `Py_DECREF` の所有権ルールはなぜそうなっているのか
- pybind11 / Cython / PyO3 / cffi / ctypes はどう棲み分けるか
- Python 3.13 から experimental に入った **free-threaded build(no-GIL)** で C 拡張に何が起きるか
- PEP 733 が指摘する C API の構造的な問題と、その先

対象は CPython 3.12〜3.14。PyPy / GraalPy / Cython の文法詳細などには踏み込みません。

---

## 1. 前作との接続 — VM の評価ループの「外側」とは何か

前作で示した実行モデルはこうでした。

> ソース(`.py`)→ AST → バイトコード → VM 評価ループ(`ceval`)

C 拡張は、この最後の段、`ceval` の評価ループの **真下に直接生えるネイティブ関数** です。「VM の外側を並列に走るランタイム」ではありません。Python から見れば普通の関数オブジェクト、内部から見ると **`LOAD_*` / `CALL` 命令で呼び出される関数本体のバイトコードが、C コンパイラの生成したネイティブコードに差し替わっている** だけ。

```
+-------------------+
| Python bytecode   |   ← 前作の話
|   LOAD_GLOBAL np  |
|   LOAD_METHOD dot |
|   CALL 2          |───┐
|   RETURN_VALUE    |   │ ここで呼ばれる関数の中身が
+-------------------+   │
                        ▼
              +---------------------+
              | C で書かれた関数本体  |   ← この記事の話
              |  Py_INCREF / decref |
              |  malloc / SIMD ...  |
              +---------------------+
```

ここから次の 2 点が出てきます。

- **C 拡張も GIL の支配下** にいる(VM の中で動いているのだから当然)
- **C 拡張は CPython のオブジェクトモデル** をそのまま使う(`PyObject *` のやり取り)

「C で書けば GIL を回避できる」というのは半分嘘で、**C コード内で明示的に GIL を解放しない限り** 他スレッドは止まったままです。ここが NumPy のような数値計算ライブラリが「内側で `Py_BEGIN_ALLOW_THREADS` を打って解放しているから並列に効く」と説明される所以で、第 4 節で詳しく見ます。

---

## 2. 最小の C 拡張を眺める — `PyModuleDef` から 1 ファイルで読む

論より証拠で、公式の "spam" モジュールを少しだけ短く書き直したものを置きます([extending/extending.html](https://docs.python.org/3/extending/extending.html))。

```c
#define PY_SSIZE_T_CLEAN
#include <Python.h>

static PyObject *
spam_system(PyObject *self, PyObject *args)
{
    const char *command;
    if (!PyArg_ParseTuple(args, "s", &command)) {
        return NULL;            /* 例外がセット済みであることを保証 */
    }
    int sts = system(command);
    return PyLong_FromLong(sts); /* new reference を返す */
}

static PyMethodDef spam_methods[] = {
    {"system", spam_system, METH_VARARGS, "Execute a shell command."},
    {NULL, NULL, 0, NULL}        /* sentinel */
};

static int
spam_module_exec(PyObject *m)
{
    return 0;
}

static PyModuleDef_Slot spam_module_slots[] = {
    {Py_mod_exec, spam_module_exec},
    {0, NULL}
};

static struct PyModuleDef spam_module = {
    .m_base = PyModuleDef_HEAD_INIT,
    .m_name = "spam",
    .m_size = 0,
    .m_methods = spam_methods,
    .m_slots = spam_module_slots,
};

PyMODINIT_FUNC
PyInit_spam(void)
{
    return PyModuleDef_Init(&spam_module);
}
```

たった 30 行ですが、この中に **C 拡張の背骨が 5 つすべて入っています**。

1. **`PyInit_spam`** — モジュール名と一致する init 関数。`import spam` 時にダイナミックリンクで呼ばれる。非 static で公開する唯一のシンボル
2. **`PyModuleDef`** — モジュールのメタデータ。名前 / メソッドテーブル / state サイズ / slots を持つ
3. **`PyMethodDef[]`** — Python から呼べる関数の表。最後は `{NULL, ...}` の番兵
4. **`Py_mod_exec` スロット** — モジュールロード時に実行されるフック。グローバルや型の登録はここで行う
5. **`PyArg_ParseTuple`** — 引数を C の型に展開するヘルパ

### 「単相」と「多相」 — PEP 489 の意味

注目すべきは `Py_mod_exec` の存在です。これは **PEP 489 で導入された multi-phase initialization** という機構で、現代の C 拡張はこの形が推奨されています([PEP 489 – Multi-phase extension module initialization](https://peps.python.org/pep-0489/))。

何が嬉しいのか。

- **モジュールごとの state を分離できる**(`m_size > 0` で `PyModule_GetState` 経由のローカル状態)
- **複数のインタプリタ(sub-interpreter)に対応できる**。1 プロセスに複数の独立した Python 状態を持つ機能(3.12 で正式に GIL も分離)で、シングルフェーズ init のモジュールは原則ロードできない
- **将来の機能拡張用のスロットを追加できる**。実例: `Py_mod_gil` スロット(後述、free-threaded build 対応の宣言)

旧形式(`PyModule_Create()` を `PyInit_*` の中で直接呼ぶ)はまだ動きますが、**sub-interpreter / free-threaded build / `Py_mod_gil` の宣言などモダンな機能はすべてこの multi-phase init を前提にしている** ので、新規コードは最初から `Py_mod_exec` で書くのが正解です。

### ビルド

最小の `setup.py` は次のようになります。

```python
from setuptools import setup, Extension

setup(
    name="spam",
    ext_modules=[Extension("spam", sources=["spam.c"])],
)
```

`python -m pip install .` で `spam.cpython-312-x86_64-linux-gnu.so` のような共有ライブラリができて、`import spam` できるようになる。これだけです。

`.so` のファイル名に `cpython-312` が含まれている点は、前作で見た `.pyc` の `cache_tag` と **完全に同じ仕組み**(Python バージョン依存)です。違うのは、`.pyc` は CPU 非依存だったが `.so` は CPU 依存で wheel が爆発する、という点で、ここが第 5・6 節への伏線になります。

---

## 3. 参照カウントと所有権 — New / Borrowed / Stolen を区別する

C 拡張のバグの **大半** が、ここに集中しています。ここを掴むと、公式ドキュメントの C API リファレンスがほぼ全部読めるようになる。

### 公式の定義

[C API: Introduction](https://docs.python.org/3/c-api/intro.html) に書かれている表現がそのまま骨子です。

> Ownership pertains to references, never to objects (objects are not owned: they are always shared).

つまり、**「オブジェクトを所有しているわけではない、参照を所有している」**。誰かが `Py_INCREF` するたびに「私もこの参照を握りますよ、私が放すまでは消さないでください」と宣言し、`Py_DECREF` で「もう手放しました」と宣言する。最後の所有者が手放したときに、参照カウントが 0 になってメモリが解放される。

このモデル上で C 拡張が扱う参照は、**3 種類しかありません**。

| 種別 | 意味 | 例 | 自分でやること |
|------|------|-----|---------------|
| **New reference** | 関数が返してきた、自分が所有している参照 | `PyLong_FromLong(42)`, `PyObject_GetAttrString(...)` | 用が済んだら `Py_DECREF` |
| **Borrowed reference** | 一時的に貸してもらっただけ | `PyList_GetItem(list, i)`, `PyDict_GetItem(...)` | 触ってよいが `DECREF` してはいけない。長持ちさせたいなら `Py_INCREF` で昇格 |
| **Stolen reference** | 渡したら相手が所有権を引き取った | `PyTuple_SetItem(t, i, v)`, `PyList_SetItem(...)` | 渡した後は `DECREF` しない |

### 実例 1: New reference を扱う

```c
/* PySequence_GetItem は new reference を返す */
PyObject *item = PySequence_GetItem(sequence, i);
if (item == NULL) {
    return -1;  /* 例外がセット済み */
}
/* ... item を使う ... */
Py_DECREF(item);  /* 必ずペアにする */
```

これを忘れるとリークし、二重に呼ぶと use-after-free と segfault が起きます。

### 実例 2: Stolen reference に注意する

```c
PyObject *t = PyTuple_New(3);
PyObject *n = PyLong_FromLong(42);  /* new reference */
PyTuple_SetItem(t, 0, n);            /* ← n の所有権を盗る */
/* ここで Py_DECREF(n) してはいけない */
```

「あれ、`PyTuple_SetItem` の戻り値はチェックしなくていいの?」というのが初見の疑問になりますが、**所有権をすでに盗られたあとなので、エラー時にも `n` の `DECREF` は CPython 側がやってくれる**(`SetItem` 自体は失敗するが、`n` の参照は安全に処分される)。これが「stolen」が独立した概念として存在する理由です。

### 実例 3: Borrowed reference の罠

```c
/* PyList_GetItem は borrowed reference を返す */
PyObject *item = PyList_GetItem(list, i);
/* ここで list の中身を入れ替える操作をすると、item が消える可能性がある */
PyList_SetItem(list, i, Py_None);
/* item を触ったら use-after-free */
```

これが [extending docs](https://docs.python.org/3/extending/extending.html) で "Thin Ice" と呼ばれている問題です。**借りた参照を持っている最中に、貸し主側の状態を変更しない** という規律で逃げます。長く保持したい場合は `Py_INCREF` で「新しい所有者」になればよい(これは "borrowed を strong に昇格" と呼ばれます)。

Python 3.10 で追加された `Py_NewRef()` は、この昇格を 1 行で書けるようにした API で、現代の C 拡張ではこちらが推奨です。

```c
PyObject *kept = Py_NewRef(PyList_GetItem(list, i));
/* 以降 kept は自分が所有。用が済んだら Py_DECREF(kept) */
```

### 引数と戻り値の規律

[C API Introduction](https://docs.python.org/3/c-api/intro.html) はもう一段強い規約を置いています。

> When a C function is called from Python, it borrows references to its arguments from the caller. ...
> The object reference returned from a C function that is called from Python must be an owned reference — ownership is transferred from the function to its caller.

つまり、**C 拡張関数のシグネチャは「引数 = borrowed、戻り値 = new」が原則**。これが Python の関数呼び出し規約の C 側の翻訳になっており、第 2 節の `spam_system` が `PyArg_ParseTuple` で借りた `command` を `DECREF` していない理由でもあります。

### 3.12 の地味だが重要な変化 — immortal objects

Python 3.12 で **immortal objects(PEP 683)** が導入されました。`True` / `False` / `None` / 小整数のようなオブジェクトは、参照カウントが **動かない**(マクロが no-op になる)ようになっています([refcounting.html](https://docs.python.org/3/c-api/refcounting.html))。

> This function has no effect on immortal objects.

何が嬉しいかというと、これらの「全プロセスで共有されるオブジェクト」の `Py_INCREF` / `Py_DECREF` で **メモリのキャッシュラインが書き換わらない** ようになる。free-threaded build(第 8 節)では複数スレッドが `None` の refcount を同時に書き換えるとキャッシュコヒーレンス通信で激しく遅くなるので、これは GIL を捨てるための布石でもあります。

実務上の注意は 1 点だけ:**`Py_REFCNT(obj)` の戻り値を「実際の参照数」として信用しない**。refcounting docs に明記されていますが、`0` か `1` 以外の値は意味がなくなった、と読むのが安全です。

---

## 4. GIL とエラー伝搬 — C 拡張が守るべき 2 つの規律

参照カウントの次に、C 拡張作者が必ず守る規律が 2 つあります。

### 4.1 GIL の保持と解放

C 拡張のコードが Python の C API を呼ぶ瞬間、**GIL を保持していなければなりません**。これは前作の VM 評価ループの話と直結していて、`ceval` が GIL を握ったまま C 関数を呼ぶ → C 関数も自然に GIL 保持下、という連鎖になっています。

問題は、C 拡張が「Python オブジェクトに触らない処理」をしている間も GIL を握りっぱなしだと、**他の Python スレッドが完全に止まる** こと。なので、長時間の I/O や CPU バウンドな C ロジックの間は GIL を解放するのが作法です。

```c
PyObject *
fast_compute(PyObject *self, PyObject *args)
{
    double *data;
    Py_ssize_t n;
    /* ... 引数の展開 ... */

    Py_BEGIN_ALLOW_THREADS
    /* ここから GIL を持たないネイティブ計算。
       この区間では Python の C API を呼んではいけない。 */
    for (Py_ssize_t i = 0; i < n; i++) {
        data[i] = heavy_math(data[i]);
    }
    Py_END_ALLOW_THREADS

    Py_RETURN_NONE;
}
```

`Py_BEGIN_ALLOW_THREADS` / `Py_END_ALLOW_THREADS` は対称マクロで、内部的には `PyThreadState` をセーブ・リストアしています。NumPy が「Python としては GIL があるのに、内部のループは並列に効く」と説明される理由は、まさにここを多用しているから。標準ライブラリの `time.sleep` も内部でこのマクロを使って GIL を解放しています。

逆に言うと、**C 拡張側が `ALLOW_THREADS` を打たない限り、何も並列にはなりません**。「C で書いたから速い」と「並列に動く」はまったく別の話です。

### 4.2 エラー伝搬 — 戻り値と例外の二段約束

Python の `try / except` は、C 側では **戻り値 + スレッドローカルなエラーフラグ** という二段方式で表現されています。

```c
static PyObject *
my_func(PyObject *self, PyObject *args)
{
    /* 失敗時: NULL を返す + PyErr_Set* を呼ぶ */
    if (some_error) {
        PyErr_SetString(PyExc_ValueError, "bad input");
        return NULL;
    }
    /* 成功時: new reference を返す + 例外を立てない */
    return PyLong_FromLong(42);
}
```

整数を返す関数は `-1` を「失敗の合図」にする慣例で、`int` 戻り値の関数が `-1` を返したら必ず `PyErr_Occurred()` をチェックする必要があります(`-1` が正常値である `PyLong_AsLong` のような関数は、`PyErr_Occurred()` の併用が必須)。

ここを破ると以下が起きます。

- **失敗時に例外を立て忘れた**: 次の C API 呼び出しが「正常に動いたのに `PyErr_Occurred()` が真」になり、後続コードで突然 `SystemError: error return without exception set` が出る
- **成功時に古い例外が残っている**: 1 つ前の演算で立ったまま `PyErr_Clear` されていない例外が、不可解な場所で再発火する

これらは「Python から見ると謎の例外」になりやすく、デバッグが非常に難しい。`return NULL` と `PyErr_Set*` は **必ずペア** という規律は、参照カウントと並んで C 拡張作者が叩き込まれる第二の習慣です。

### 前作との接続

前作で「Python は実行を速くするより起動を速くする側に振った」と書きました。GIL はその設計と整合しています。シングルスレッド前提なら GIL の存在は **競合制御コストをゼロにする加速装置** で、マルチコア利用は C 拡張側の `ALLOW_THREADS` か別プロセス(`multiprocessing`)に任せる、という分業を成り立たせている。

逆に「マルチコアを当然に使いたい」というモダンな要求が、PEP 703(no-GIL)を生んだ動機で、これが第 8 節の話になります。

---

## 5. ビルドと配布 — `setup.py` から `pyproject.toml` + `meson-python` へ

C 拡張の「書き方」の次は「配布」です。ここは Python 3.12 で一区切りついたばかりの領域。

### `distutils` 廃止という地殻変動

Python 3.12 で、長年標準ライブラリだった `distutils` モジュールが **削除されました**。`setup.py` が `from distutils.core import setup, Extension` で始まる書き方はもう動きません。

現代の C 拡張の主流は、**`pyproject.toml` をマニフェストにして `setuptools.Extension` を駆動する** スタイルです([Building C and C++ Extensions](https://docs.python.org/3/extending/building.html))。

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=61", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "spam"
version = "0.1.0"
```

```python
# setup.py(まだ Extension 定義は Python コードで書く)
from setuptools import setup, Extension

setup(
    ext_modules=[
        Extension(
            "spam",
            sources=["src/spam.c"],
            define_macros=[("Py_LIMITED_API", "0x030A0000")],  # 第 6 節で説明
        ),
    ],
)
```

これでビルドは `pip install .` または `python -m build` の標準コマンドで通ります。

### `meson-python` — NumPy / SciPy が採った道

数値計算系の巨大ライブラリは別の選択をしました。**`meson-python`** は Meson(Ninja を生成する Google 由来のビルドシステム)を Python 用にラップした PEP 517 backend で、NumPy 1.26 と SciPy 1.13 で正式採用されています。

```toml
# pyproject.toml
[build-system]
requires = ["meson-python>=0.16", "meson>=1.2", "ninja"]
build-backend = "mesonpy"
```

メリットは:

- **C / C++ / Fortran / Cython を 1 つのビルドグラフで扱える**(NumPy の事情)
- **インクリメンタルビルドが速い**(`setuptools` は基本フルビルド)
- **クロスコンパイル**(manylinux wheel 生成や Apple Silicon 対応)が素直

逆に学習コストは高めで、Extension が C ファイル数本に収まる規模なら `setuptools.Extension` のままで十分です。

### Multi-platform wheel — 4 軸で爆発する

前作で見た `.pyc` は **プラットフォーム非依存** でした([tutorial/modules](https://docs.python.org/3/tutorial/modules.html) に明記)。`.pyc` 1 本で x86_64 でも arm64 でも動く。

C 拡張はそうはいきません。wheel の互換性タグは **4 軸の直積** です。

```
spam-0.1.0-cp312-cp312-manylinux_2_28_x86_64.whl
           ↑     ↑    ↑                ↑
           Python  ABI  プラットフォーム  CPU
           実装+バージョン
```

- Python 実装: `cp`(CPython)、`pp`(PyPy)、...
- Python バージョン: `cp310` / `cp311` / `cp312` / `cp313` / `cp314`
- ABI: `cp312`(version-specific)または `abi3`(stable ABI、次節)
- プラットフォーム: `manylinux_2_28_x86_64` / `macosx_14_0_arm64` / `win_amd64` / ...

Linux × Mac × Windows × (x86_64 + arm64) × Python 3.10〜3.14 を網羅すると、**かんたんに 30〜40 個の wheel が必要**になります。これを `cibuildwheel` で自動生成するのが現代のリリース手順ですが、根本解決ではない。根本解決を試みたのが次の節です。

---

## 6. Limited API と abi3 — wheel を 1/N に減らす仕組み

wheel 爆発問題に対する CPython 側の回答が、PEP 384(2011)の **Limited C API** と、その ABI である **`abi3`** です。

### 2 つの概念を分けて読む

[PEP 652](https://peps.python.org/pep-0652/) で 2 つの概念が明確に分離されました。

- **Stable ABI**(`abi3`)= 「ある Python 3.x で作った `.so` が、それ以後の 3.y(y ≥ x)で **再コンパイルなしにロードできる**」というバイナリ互換の約束
- **Limited API** = その約束を満たすために、コンパイル時に使えるシンボルを絞った C API の **サブセット**

つまり Limited API は「ソースコードの書き方の縛り」、Stable ABI は「リンク結果がどこで動くか」の話。混同しがちですが片方は入力、もう片方は出力です。

### 使い方は実質 1 行

```c
#define Py_LIMITED_API 0x030A0000  /* "3.10 以降の Stable ABI を使う" */
#include <Python.h>
```

これでヘッダから内部実装の構造体定義などが消え、Stable ABI で公開された関数だけが見えるようになります([C API Stability](https://docs.python.org/3/c-api/stable.html))。`setuptools` 側は `py_limited_api=True` を `Extension` に渡せばファイル名が `spam.abi3.so` になり、wheel タグも `abi3` になる。

### 何が嬉しいか

Python 3.10〜3.14 を網羅したいライブラリで、

- Linux × Mac × Windows × (x86_64 + arm64) × 5 Python バージョン = **30 wheel**

が、

- Linux × Mac × Windows × (x86_64 + arm64) × **1**(abi3 として) = **6 wheel**

になります。pre-release の Python 3.15 に対しても、abi3 wheel は **そのままロードできる**(ABI 互換が保証されているので)。プレリリース対応の手間も激減する。

### 制約とトレードオフ

無料ではありません。

- `PyObject` の中身に直接触れない(`ob_refcnt` / `ob_type` への macro アクセスが制限される)
- 一部のレイアウト依存最適化が使えない(`PyList_GET_ITEM` のような fast macro でなく関数版を経由)
- 新しい API は **Stable ABI に追加されるまで待つ** 必要がある

数値計算ライブラリのようにホットループの最後の数 % まで削りたい人は、abi3 を避ける合理的な理由があります。一方で「機能としては薄いが、依存される側になりたい」ライブラリ(pyca/cryptography、PyNaCl、PyAV など)は abi3 を採用しています。

---

## 7. 高位ツールの地図 — Cython / pybind11 / nanobind / PyO3 / cffi / ctypes をどう選ぶか

ここまでが「素の C API で書く世界」の話でした。実際には、自分でゼロから `PyArg_ParseTuple` を書く人は **ライブラリ作者か CPython のコア開発者くらい** で、ほとんどの実務は高位ツールを通します。

PEP 733 自身が、これらを「**代替 API (Alternative APIs) と binding generator**」として整理しています([PEP 733](https://peps.python.org/pep-0733/))。重要なのは、これらは **CPython C API を置き換えるものではなく、その上に乗っている** ということ。ツールが生成するコードのコンパイルターゲットが C API なので、第 3〜6 節までの話は全部の足元にある。

### 比較表

| ツール | 言語 | 方式 | 主な向き先 |
|--------|-----|------|----------|
| **Cython** | Python+型注釈 → C | コード生成(`.pyx` → `.c`) | Python ライクな構文で書きつつ、NumPy ループなどをホットスポットだけ C 化 |
| **pybind11** | C++ | ヘッダオンリー、テンプレートメタプログラミング | 既存の C++ ライブラリへの Python バインディング(GUI、ゲームエンジン、ML フレームワーク) |
| **nanobind** | C++ | pybind11 の軽量後継 | pybind11 と同じ思想だが、バイナリサイズ・コンパイル時間・実行時オーバーヘッドを削減 |
| **PyO3** | Rust | Rust crate + procedural macro | 新規ライブラリを安全な言語で書きたい。`pydantic-core`、`polars`、`cryptography` の一部、`ruff` |
| **cffi** | C | ランタイムに `dlopen`、ABI / API モード | 既存の C ライブラリ(libssl, libgit2 など)を扱いたい。**PyPy が公式に推奨** |
| **ctypes** | Python | 標準ライブラリの `dlopen` | 最小依存。コンパイル不要、ライブラリ追加不要で C 関数を呼ぶ。配布の薄さが最大の武器 |

### 選び方の素朴な判断ツリー

```
Q: 既存の C/C++ ライブラリにバインディングを付けたい?
   YES → 言語は?
       C のみ:           ctypes(小規模)、cffi(中規模以上)
       C++ ヘビー:       pybind11 / nanobind
   NO  → 新規ロジックを高速に書きたい
       Python 由来で連続的に最適化したい:    Cython
       メモリ安全と並行性を重視:              PyO3 (Rust)
```

### 「素の C API を書くべき場面」は残るか

ほぼ残りません。例外は次の 3 つくらい:

1. **CPython 自体への寄与**(標準ライブラリの C モジュール、PEP のリファレンス実装)
2. **これらのツール自体の開発**(Cython / pybind11 / PyO3 の generator 部分)
3. **Stable ABI の最小限の `.so`** を、依存ゼロで作りたい場合

逆に言えば、3〜6 節の知識は **C 拡張を書かない実務者にとっても、これら高位ツールの挙動とエラーメッセージを読むための共通言語** になります。`pybind11` のドキュメントに `Py_INCREF` の話が出てきて意味がわからない、ということは無くなる。

### PyO3 を選ぶ実例の重み

最近のエコシステム動向で目立つのは、**`pydantic-core`(pydantic v2 のコア)が PyO3 で書かれている** という事実です。FastAPI / SQLModel / LangChain など、Python サーバサイドのほぼ全域で使われる基盤が「**Python から見えない深さで Rust + PyO3 になっている**」。`ruff`(Linter)、`polars`(DataFrame)、`uv`(パッケージマネージャ)も同じ流れ。

「Python は遅い」と言われがちですが、現代の実態は **「ホットパスは Rust か C で、Python は接着剤」** に移行しつつある、という景色を頭に入れておくと、自分のコードのプロファイル結果も解像度高く読めます。

---

## 8. Free-threaded build(3.13+, PEP 703)で C 拡張に何が起きるか

ここが 2025 年の C 拡張作者にとって **最大の論点** です。

### PEP 703 の受理と段階的導入

長年「Python から GIL を外すと壊れる」と言われ続けていた問題に、PEP 703(2023 年受理)が解を出しました。Meta のエンジニア Sam Gross の提案で、**バイアスドリファレンスカウンティング + mimalloc + 内部ロック整備** によって、シングルスレッド性能をほぼ落とさずに GIL を外せる、というもの。

- Python **3.13**: experimental として `--disable-gil` 付き build が提供開始(`python3.13t`)
- Python **3.14**(2025-10): 実装ほぼ完成。adaptive specializing interpreter(前作で触れた 3.11 の最適化)が free-threaded mode でも有効化。**シングルスレッド性能ペナルティは 5〜10 %** まで縮小([3.14 What's New](https://docs.python.org/3/whatsnew/3.14.html))

これは Python の C API が経験する **最初の根本的な ABI 変更** と言ってよく、abi3 wheel もそのままでは動きません(後述)。

### C 拡張への 6 つのインパクト

[Free-threading Extensions HOWTO](https://docs.python.org/3/howto/free-threading-extensions.html) と [PEP 703](https://peps.python.org/pep-0703/) を読んで整理すると、ポイントは 6 つ。

#### (1) 新しい ABI タグ `t`

`--disable-gil` build は `Py_GIL_DISABLED` macro が定義され、ABI タグに `t` が付きます。インストール名は `python3.14t`、wheel ファイルも `cp314t-cp314t-...` のように `t` が入る。**従来の wheel はそのままでは読み込まれません**。

`pypa/manylinux` と `pypa/cibuildwheel` が 3.14 から `t` 付き wheel のビルドを公式サポート。

#### (2) `Py_mod_gil` スロットによるオプトイン

モジュール側が「GIL なしで動かしても安全」を **明示宣言** する必要があります。multi-phase init のスロットに 1 行追加するだけ。

```c
static PyModuleDef_Slot spam_module_slots[] = {
    {Py_mod_exec, spam_module_exec},
    {Py_mod_gil, Py_MOD_GIL_NOT_USED},  /* GIL なしで安全 */
    {0, NULL}
};
```

宣言しないモジュールを free-threaded build で import すると、**ランタイムが GIL を自動的に再有効化** し、警告を出します。デフォルトは安全側。これがあるおかげで、対応していない大量の既存 C 拡張も「GIL 復活モード」で動き続けられる。

#### (3) Borrowed reference の危険性

GIL がないと、`PyList_GetItem` が返した borrowed reference を読んでいる **最中に他スレッドがリストを変更してオブジェクトが解放され得る** ようになります(3 節の "Thin Ice" がリアルな脅威に)。

HOWTO は、borrowed reference を返す古い API を、**strong reference(new reference)を返す新 API** に置き換えるよう推奨しています。

| 旧 API(borrowed) | 新 API(strong, `Ref` 接尾辞) |
|------------------|------------------------------|
| `PyList_GetItem` | `PyList_GetItemRef` |
| `PyDict_GetItem` | `PyDict_GetItemRef` |
| `PyDict_GetItemString` | `PyDict_GetItemStringRef` |
| `PyWeakref_GetObject` | `PyWeakref_GetRef` |
| `PyImport_AddModule` | `PyImport_AddModuleRef` |

「Ref が付いた版は new reference を返すので、`Py_DECREF` 責任が増える」だけで、コード量はあまり変わりません。

#### (4) `PyDict_Next` だけは特別

コンテナ系の API はほとんど内部ロックされる(`PyList_Append` などはロックを取る)ようになったのですが、`PyDict_Next` は性能の都合で例外。**`Py_BEGIN_CRITICAL_SECTION(dict)` で囲む** 必要があります。

```c
Py_BEGIN_CRITICAL_SECTION(dict);
PyObject *key, *value;
Py_ssize_t pos = 0;
while (PyDict_Next(dict, &pos, &key, &value)) {
    /* ... */
}
Py_END_CRITICAL_SECTION();
```

#### (5) Limited API / abi3 は当面非対応

第 6 節で出てきた abi3 は、**free-threaded build では使えません**。HOWTO に明記されています。

> The free-threaded build does not currently support the Limited C API or the stable ABI.

つまり、abi3 で 1 本の wheel に集約していたライブラリは、**free-threaded build 向けに別途 version-specific wheel を切る必要がある**。これが PEP 803(後述)の `abi3t` で解決を試みている問題です。

#### (6) Windows の落とし穴

公式 Windows インストーラの制約で、3.14 からは **ソースから extension を作るとき、自分で `Py_GIL_DISABLED=1` を define する必要があります**(コンパイラからの自動判定が効かない)。`setuptools` 側が `define_macros` でカバーしてくれることが多いですが、手書きビルドスクリプトを使っている人は要注意。

### PEP 803 — `abi3t` で wheel 圧縮を取り戻す

free-threaded build にも Stable ABI が欲しい、というのが [PEP 803](https://peps.python.org/pep-0803/)。`abi3` の対になる **`abi3t`** を導入し、CPython 3.15 から提供する案です(提案中)。

仕組みは `Py_LIMITED_API` の対になる **`Py_TARGET_ABI3T`** macro を立ててコンパイルすると、`abi3t` 互換の `.so` が出てくる。`abi3t` は `abi3` から **`PyObject` 構造体を完全に opaque 化** している点が決定的な違いで、これは PEP 733 が指摘していた「`PyObject` がポインタとして直接見える」問題への部分的な答えにもなっています。

将来的に free-threaded build が GIL 付き build を置き換える可能性があり(PEP 779 がそのロードマップ)、その時点で `abi3` は **「過去の互換 ABI」、`abi3t` が「現役 ABI」** という構図になる、と PEP 803 は予告しています。

---

## 9. PEP 733 が指摘する C API の構造的問題と HPy の方向

ここまで読むと、CPython C API には **設計上の「重さ」がいくつも積み上がっている** ことが見えてきます。これを公式に評価したドキュメントが [PEP 733 – An Evaluation of Python's Public C API](https://peps.python.org/pep-0733/)(2023)です。「次に直すべきは何か」を網羅的に整理した、現状把握用の PEP です。

主要な指摘は 3 つに集約されます。

### 9.1 参照カウントが API レベルで露出している

> The way that C extensions are required to manage references with calls to `Py_INCREF` and `Py_DECREF` is specific to CPython's memory model, and is hard for alternative Python implementations to emulate. (Issue 12)

`Py_INCREF` / `Py_DECREF` は **CPython のメモリモデルに特化した API** で、PyPy のような JIT + moving GC ベースの実装にとっては正直うれしくない。PyPy が `cpyext` という互換レイヤを抱えて「CPython 拡張を動かせるけど少し重い」になっている根本理由がここです。

### 9.2 `PyObject` がポインタとして直接見える

> The address of an object serves as its ID and is used for comparison, and this complicates matters for alternative Python implementations that move objects during GC. (Issue 37)

`id(obj)` が **オブジェクトのメモリアドレス** に直結している、と CPython のドキュメントは書いていますが、これは「動かす GC を持つ実装」にとっては鬼門。世代別 GC でオブジェクトを物理的に移動させたくても、C 拡張が握ったポインタが宙に浮いてしまう。

### 9.3 C ヘッダが実装詳細を漏らしている

> Headers tend to expose more than what is intended to be part of the public API ... in particular, implementation details such as the precise memory layouts of internal data structures can be exposed.

`ob_refcnt` / `ob_type` のような構造体フィールドが macro 経由で読まれてしまい、stable ABI に縛りを残している、という話。これも PEP 803(`abi3t`)が `PyObject` を opaque 化することで部分的に解決を試みているところ。

### HPy — ハンドルベース API の提案

これらの構造問題に対する代替提案が、PEP 733 の本文でも触れられている **HPy** です。ポインタの代わりに **不透明なハンドル** を返すことで、

- 実装(CPython / PyPy / GraalPy)から独立した C API になる
- moving GC が安全になる(ハンドルは GC が更新できる)
- 参照カウントの露出を減らせる(`HPy_Close` で「使い終わった」だけを宣言)

HPy 自体はまだ普及していませんが、PEP 703(no-GIL)と PEP 803(`abi3t`)が **CPython の足元から段階的に同じ方向に進んでいる**、という構図で読むと現状がきれいに繋がります。「HPy は遠いが、`abi3t` の `PyObject` opaque 化はすぐそこ」という距離感です。

---

## 10. まとめ — Python の速さを「層」で読む

前作と今回で、Python の実行モデルが 3 層で読めるようになりました。

| 層 | 速さの稼ぎ方 | 守る規律 | 代表的な道具 |
|----|-------------|----------|-------------|
| **Python コード** | `dis` でホットパスを観察、`.pyc` で起動を削る、ホットループは set / frozenset の畳み込みを活かす | バイトコード ABI(マイナーバージョン固着) | `dis`、`compileall`、`SOURCE_DATE_EPOCH`、`PYTHONPYCACHEPREFIX` |
| **C 拡張(C API)** | VM をバイパスしてネイティブ実行、`Py_BEGIN_ALLOW_THREADS` で並列化 | 参照カウント(New / Borrowed / Stolen)、GIL、エラー伝搬、ABI 互換、`Py_mod_gil` 宣言 | 素の C API、`setuptools.Extension`、`abi3` |
| **C 拡張(高位ツール)** | C/C++/Rust の表現力 + 自動生成。**現代の主流** | ツール側のバージョン追従、abi3 / abi3t の現状、free-threaded build 対応 | Cython、pybind11、nanobind、PyO3、cffi、ctypes |

そして、Python はこの 3 層を 1 本の設計判断で接続しています。

> **ソースは常に権威、起動は速く、必要なら C に降りる。**

前作で見た `__pycache__` も、今回見た `Py_INCREF` も、`abi3t` も、**根は同じ問いに対する別レイヤの回答** だった、と読めてくる。

中上級者として C 拡張の地図を頭に入れておくと、

- 次にプロファイル結果を見て「ここがホットパスだ」と分かったときに、**Cython で部分的に C 化するか、PyO3 でモジュール丸ごと Rust 化するか、まず `numpy` で済むか** という判断ができる
- pydantic-core / polars / ruff / uv のような Rust ベースのライブラリを見たときに、**「PyO3 で書かれているから配布が楽そうだな」「abi3 対応はどうしてるんだろう」** という解像度で読める
- 3.13 / 3.14 の no-GIL に関する Discourse やブログ記事を見たときに、**「`Py_GIL_DISABLED` macro で対応宣言する話だな、abi3 はまだ無理だな」** と一発で位置づけられる

ようになります。次に `import numpy` と打ったときに、その `.so` の中で何が起きているかが具体的にイメージできれば、この記事は役目を果たしたことになります。

---

## 参考

### 公式ドキュメント
- [Extending and Embedding the Python Interpreter](https://docs.python.org/3/extending/index.html)
- [1. Extending Python with C or C++](https://docs.python.org/3/extending/extending.html)
- [4. Building C and C++ Extensions](https://docs.python.org/3/extending/building.html)
- [Python/C API: Introduction](https://docs.python.org/3/c-api/intro.html)
- [Python/C API: Reference Counting](https://docs.python.org/3/c-api/refcounting.html)
- [Python/C API: C API Stability](https://docs.python.org/3/c-api/stable.html)
- [Python support for free threading](https://docs.python.org/3/howto/free-threading-python.html)
- [C API Extension Support for Free Threading](https://docs.python.org/3/howto/free-threading-extensions.html)
- [What's New in Python 3.14](https://docs.python.org/3/whatsnew/3.14.html)

### PEP
- [PEP 384 – Defining a Stable ABI](https://peps.python.org/pep-0384/)
- [PEP 489 – Multi-phase extension module initialization](https://peps.python.org/pep-0489/)
- [PEP 652 – Maintaining the Stable ABI](https://peps.python.org/pep-0652/)
- [PEP 703 – Making the Global Interpreter Lock Optional in CPython](https://peps.python.org/pep-0703/)
- [PEP 733 – An Evaluation of Python's Public C API](https://peps.python.org/pep-0733/)
- [PEP 803 – "abi3t": Stable ABI for Free-Threaded Builds](https://peps.python.org/pep-0803/)
