---
title: "Python C 拡張の地図 — `PyObject`・参照カウント・GIL から `pybind11`・`PyO3`・abi3・free-threaded build まで"
status: plan
---

## 想定読者と前提

- 前作 `python_bytecode_internals.md` を読んで、「Python は CPython VM がバイトコードを 1 命令ずつ回している」というメンタルモデルを獲得した中上級 Python 開発者
- NumPy / Pillow / lxml / pydantic-core / orjson が C(または Rust)で書かれていることは知っているが、自分で `Py_INCREF` を書いたことはない人
- `pybind11` / `Cython` / `PyO3` / `cffi` / `ctypes` の名前は聞くが、どれをいつ選ぶかの判断基準を言語化できていない人
- Python 3.13 で導入された no-GIL / free-threaded build(PEP 703)が、C 拡張に何を要求するかを整理したい人

前提知識: CPython の VM とバイトコードの存在を知っていること(前作のレベル感)。C は読めるが日常的には書かない、くらいでよい。

## この記事が答える問い

1. 「C 拡張」とは、前作の VM 評価ループの何処にどう接続されるのか
2. 素の C API で 1 モジュールを書くと、何を必ず書くことになるのか(`PyModuleDef`, `PyMethodDef`, `PyMODINIT_FUNC`)
3. 参照の「所有権(New / Borrowed / Stolen)」とは何で、間違えると何が壊れるのか
4. GIL とエラー伝搬という「C 拡張が守る 2 つの規律」は具体的に何か
5. `setup.py` から `pyproject.toml` + `meson-python` までのビルドと配布の現状
6. Limited API / Stable ABI / abi3 で wheel をどこまで圧縮できるか、できないことは何か
7. Cython / pybind11 / nanobind / PyO3 / cffi / ctypes はどう棲み分けるか、どう選ぶか
8. 3.13 / 3.14 の free-threaded build(PEP 703)で C 拡張に何が起き、PEP 803 の `abi3t` は何の話か
9. PEP 733 が指摘する C API の構造的問題と、その先(HPy, multi-phase init)

## 扱う / 扱わない

- **扱う**: CPython 3.12〜3.14 を前提にした C API のメンタルモデル、参照カウント、GIL、エラー伝搬、`setuptools.Extension` / `meson-python` の最小例、Limited API / abi3 / abi3t、高位ツールの比較表、free-threaded build と C 拡張の関係、PEP 733 が指摘する構造課題
- **扱わない**: C / C++ 自体の入門、各ツール固有の詳細チュートリアル、CPython の GC アルゴリズムの内部、埋め込み(Embedding Python)側、Cython の `.pxd` の書き方の詳細、PyPy / GraalPy の話

---

## セクション構成

### 1. 前作との接続 — VM の評価ループの「外側」とは何か

**主張**: 前作で扱った「ソース → AST → バイトコード → `ceval` の評価ループ」は、純粋な Python コードの実行モデル。C 拡張はこの **評価ループに `LOAD_*` / `CALL` で呼び出される関数ノードの中身を、バイトコードではなくネイティブの C 関数に差し替える** 仕組みとして読める。逆に言えば C 拡張は VM の外側で並列に走るランタイムではなく、**評価ループの真下に直結したフックポイント**である。これが分かると、「なぜ Python の高速ライブラリは C で書かれていて、それでも GIL に縛られるのか」が一本筋で説明できる。

**根拠URL**:
- https://docs.python.org/3/extending/index.html
- https://docs.python.org/3/c-api/intro.html
- (前作との接続なので、`python_bytecode_internals.md` 自体も内部リンク)

### 2. 最小の C 拡張を眺める — `PyModuleDef` から 1 ファイルで読む

**主張**: 素の C API で書かれた「`spam` モジュール」を 30 行で示し、`PyMODINIT_FUNC PyInit_spam`、`PyModuleDef`、`PyMethodDef`、`Py_mod_exec` スロット(multi-phase init / PEP 489)、`PyArg_ParseTuple` の 5 要素がモジュールの背骨であることを見せる。これだけで「`.so` / `.pyd` を import するときに CPython が何を呼んでいるか」が分かる。PEP 489 の **multi-phase 初期化** が現代の推奨で、`Py_mod_gil` スロットなど将来のメタ情報の追加点になっていることも触れる。

**根拠URL**:
- https://docs.python.org/3/extending/extending.html
- https://peps.python.org/pep-0489/
- https://docs.python.org/3/extending/building.html

**根拠ファイル**: `temp/python_c_extension/extract_c_api_core.json`

### 3. 参照カウントと所有権 — New / Borrowed / Stolen を区別する

**主張**: C 拡張のバグの大半は **参照カウントの誤り** から来る。「オブジェクトを所有しているわけではなく、参照を所有している」という公式の言い回しがすべての出発点。3 種類だけ覚えればよい:

- **New reference**: 関数が返してきた、自分が `Py_DECREF` する責任を負う参照(`PyLong_FromLong` など)
- **Borrowed reference**: 一時的に貸してもらっているだけで、自分で `DECREF` してはいけない(`PyList_GetItem`, `PyDict_GetItem` など)
- **Stolen reference**: 自分が持っていた参照を、関数に「取られた」 — 渡したらもう `DECREF` しない(`PyTuple_SetItem` など)

実例として `sum_sequence` を引用し、`PySequence_GetItem` が new reference を返すので必ず `Py_DECREF(item)` がペアになることを示す。Python 3.10 で追加された `Py_NewRef()` で borrowed → strong の昇格が安全になったこと、3.12 で導入された **immortal objects(PEP 683)** で `True` / `False` / `None` / 小整数の refcount が「動かない」ことも触れる(GC 内部で `Py_REFCNT` の値を盲信できなくなった、という地味だが重要な変化)。

**根拠URL**:
- https://docs.python.org/3/c-api/intro.html (#reference-counts, #ownership-rules)
- https://docs.python.org/3/c-api/refcounting.html
- https://docs.python.org/3/extending/extending.html (#reference-counts)

**根拠ファイル**: `temp/python_c_extension/extract_c_api_core.json`, `search_refcount.json`

### 4. GIL とエラー伝搬 — C 拡張が守るべき 2 つの規律

**主張**: C 拡張は CPython VM の中で動く以上、2 つの規律から逃れられない。

1. **GIL 規律**: C API を呼ぶときは GIL を保持していなければならない。長時間の I/O や CPU バウンドな C ロジックの間は `Py_BEGIN_ALLOW_THREADS` / `Py_END_ALLOW_THREADS` で **解放してよいし、解放するべき**(`time.sleep` も内部でこれをやっている)
2. **エラー伝搬規律**: Python 例外は **戻り値と `PyErr_Set*` の組み合わせ** で表現される。「`NULL` または `-1` を返すと同時に例外をセットする」「成功時は例外が立っていないことを保証する」という二段約束を破ると、後続のコードで `PyErr_Occurred()` が `True` になっていて謎の二重例外が出る

ここで前作の「Python は起動を速くする側に振っている」という設計と一貫していることを見せる: GIL は **シングルスレッド前提なら高速** だが、マルチコア利用は C 拡張側の `ALLOW_THREADS` か別プロセスに任せる、という分担になっている。

**根拠URL**:
- https://docs.python.org/3/c-api/intro.html (#exceptions)
- https://docs.python.org/3/c-api/init.html (Py_BEGIN_ALLOW_THREADS)
- https://docs.python.org/3/c-api/exceptions.html

### 5. ビルドと配布 — `setup.py` から `pyproject.toml` + `meson-python` へ

**主張**: かつての `setup.py` + `distutils.core.Extension` は、Python 3.12 で `distutils` が標準ライブラリから削除されたため過去のものになりつつある。現代の選択肢は実質 2 つ:

- **`setuptools.Extension`** を `pyproject.toml` から駆動する(現状の主流。NumPy 系以外はほぼこれ)
- **`meson-python`** で Meson にビルドを任せる(NumPy / SciPy / scikit-learn が移行済み)

最小の `pyproject.toml` 例と、配布側の `cibuildwheel` による multi-platform wheel 構築のフローまでを 1 つの図で繋ぐ。前作で触れた `.pyc` がプラットフォーム非依存だったのと対照的に、**C 拡張は `cp312-cp312-manylinux_2_28_x86_64.whl` のように 4 軸**(Python 実装 × Python バージョン × ABI × プラットフォーム)で wheel が増えるという話を、次節の伏線にする。

**根拠URL**:
- https://docs.python.org/3/extending/building.html
- https://docs.python.org/3/whatsnew/3.12.html (distutils removal)
- https://meson-python.readthedocs.io/ (公式案内)

### 6. Limited API と abi3 — wheel を 1/N に減らす仕組み

**主張**: 5 節の「wheel が爆発する」問題に対する CPython 側の回答が、PEP 384(2011)で提案された **Limited C API** とその ABI である **`abi3`**。鍵は 2 つの概念分離。

- **Stable ABI** = 「CPython 3.x で作った `.so` が、それ以後の 3.y(y ≥ x)でロードできる」というバイナリ互換の約束
- **Limited API** = その約束を満たすために、コンパイル時に使えるシンボルを絞った C API の **サブセット**

`Py_LIMITED_API=0x03070000` を define してコンパイルすると、ファイル名が `mymod.abi3.so` のような **バージョン非依存 wheel** になり、3.7 以降であれば 1 本の wheel で済む。`PEP 652` がこの約束を正式に「テスト付きで維持される契約」に格上げした。注意点: `PyObject` の中身など実装詳細は触れなくなる、メモリレイアウト最適化を諦める部分が出るため **若干のオーバーヘッドと表現力のトレードオフ** がある。

**根拠URL**:
- https://peps.python.org/pep-0384/
- https://peps.python.org/pep-0652/
- https://docs.python.org/3/c-api/stable.html

**根拠ファイル**: `temp/python_c_extension/extract_peps_abi.json`

### 7. 高位ツールの地図 — Cython / pybind11 / nanobind / PyO3 / cffi / ctypes をどう選ぶか

**主張**: 公式 C API を直接書くのは、ライブラリ作者か CPython 自体のコア開発者くらい。実務では「言語の橋渡し方式」と「コード生成方式」の 2 軸で考えると整理できる。

| ツール | 言語 | 方式 | 向くケース |
|--------|-----|------|----------|
| **Cython** | Python+型注釈 → C | コード生成 | Python ライクな構文で書きつつ NumPy 連携などホットループを段階的に C 化したい |
| **pybind11** | C++ | ヘッダオンリーのバインディング | 既存の C++ ライブラリを Python から触りたい(モダン C++ ヘビー) |
| **nanobind** | C++ | pybind11 の軽量後継 | pybind11 と同思想だがバイナリサイズ / ビルド時間を削りたい |
| **PyO3** | Rust | Rust crate + procedural macro | 新規ライブラリを安全な言語で書きたい、`pydantic-core` / `polars` 系 |
| **cffi** | C | ランタイム dlopen + ABI / API モード | 既存の C ライブラリ(libssl, libgit2 など)をバインディング |
| **ctypes** | Python | 標準ライブラリの dlopen | 最小依存で **インストール不要** に C ライブラリを叩きたい(配布の薄さが最大の武器) |

PEP 733 自身が「これらは alternative APIs であり、CPython API の上に構築されている」と整理しているので、ここを引用して **「C API はこれらのツールが生成するコードのコンパイルターゲットでもある」** という位置づけを示す。

**根拠URL**:
- https://docs.python.org/3/c-api/intro.html (Recommended third-party tools)
- https://peps.python.org/pep-0733/ (Alternative APIs and Binding Generators)
- https://docs.python.org/3/extending/index.html

**根拠ファイル**: `temp/python_c_extension/extract_nogil_api_eval.json`

### 8. Free-threaded build(3.13+, PEP 703)で C 拡張に何が起きるか

**主張**: ここが 2025 年の C 拡張作者にとって最大の論点。PEP 703 が受理されたことで、CPython 3.13 で `--disable-gil` 付きの **free-threaded build** が experimental として提供開始、3.14 でほぼ実装が完了し、単スレ性能ペナルティは 5〜10 % まで縮んだ。C 拡張側の現実的なインパクトは以下:

- **新しい ABI**: `Py_GIL_DISABLED` macro が定義され、ABI タグに `t` が付く(`python3.14t`)。**従来の wheel はそのままでは使えない**。`cibuildwheel` / `manylinux` が 3.14 から対応
- **モジュール側のオプトイン**: `Py_mod_gil` モジュールスロットで「GIL なしでも安全」を宣言しないと、インポート時に **ランタイムが GIL を自動的に再有効化** する(警告付き)。デフォルトは安全側
- **borrowed reference の危険性**: GIL が無いと、`PyList_GetItem` のような borrowed reference を読んでいる最中に他スレッドがリストを変更してオブジェクトが解放され得る。HOWTO は `PyList_GetItemRef` / `PyDict_GetItemRef` / `PyImport_AddModuleRef` などの **`Ref` 接尾辞付きの新 API** に置き換えることを推奨
- **`PyDict_Next` は特別扱い**: コンテナはほとんど内部ロックされるが、`PyDict_Next` だけは例外で `Py_BEGIN_CRITICAL_SECTION(dict)` で囲む必要がある
- **Limited API / Stable ABI は当面非対応**: free-threaded build は **abi3 では作れない**(PEP 803 が解決を提案中、3.15 から `abi3t` として提供予定)
- **Windows の落とし穴**: 公式インストーラの制約で、ソースから extension を作るときは手動で `Py_GIL_DISABLED=1` を define する必要がある

これは「Python の C API が初めて経験する根本変更」と言ってよく、前作 V8 比較で言及した「実行を速くする側の世界」へ Python が一歩踏み出したことを意味する。

**根拠URL**:
- https://peps.python.org/pep-0703/
- https://docs.python.org/3/howto/free-threading-extensions.html
- https://docs.python.org/3/howto/free-threading-python.html
- https://docs.python.org/3/whatsnew/3.14.html

**根拠ファイル**: `temp/python_c_extension/extract_nogil_api_eval.json`, `search_c_ext_nogil.json`

### 9. PEP 733 が指摘する C API の構造的問題と HPy の方向

**主張**: ここまで眺めると、CPython C API には設計上の「重さ」がいくつも見える。PEP 733(2023)はそれを公式に評価したドキュメントで、特に 3 点を指摘している。

1. **参照カウントが API レベルで露出していること**: `Py_INCREF` / `Py_DECREF` の挙動は CPython のメモリモデル前提で、PyPy / GraalPy のような **moving GC を持つ実装には移植が難しい**
2. **`PyObject` がポインタとして直接見えること**: オブジェクトのアドレスを ID として使う API があるため、**動かす GC が原理的に困難**
3. **C ヘッダが内部実装を漏らしていること**: `ob_refcnt` / `ob_type` のようなフィールドが macro 経由でアクセスされてしまい、stable ABI に縛りを残している

この延長線上にある代替提案が **HPy**(handle-based API)で、ポインタの代わりにハンドルを返すことで実装非依存にする。PEP 733 自体は方向を定めただけだが、PEP 703(no-GIL)と PEP 803(`abi3t`)が CPython の足元から段階的に進めている、という構図で読むと現状がきれいに繋がる。

**根拠URL**:
- https://peps.python.org/pep-0733/
- https://hpyproject.org/ (PEP 733 から参照)

**根拠ファイル**: `temp/python_c_extension/extract_nogil_api_eval.json`

### 10. まとめ — Python の速さを「層」で読む

**主張**: 前作と今回で、Python の実行モデルを 3 つの層で読めるようになる。

| 層 | 速さの稼ぎ方 | 守る規律 |
|----|-------------|----------|
| **Python コード** | `dis` でホットパスを観察、`.pyc` で起動を削る | バイトコード ABI(マイナーバージョン固着) |
| **C 拡張(C API)** | VM をバイパスしてネイティブ実行 | 参照カウント、GIL、エラー伝搬、ABI 互換 |
| **C 拡張(高位ツール)** | C/C++/Rust の表現力 + 自動生成 | ツール側のバージョン追従、abi3 / abi3t の現状 |

そして、Python はこの 3 層を **「ソースは常に権威、起動は速く、必要なら C に降りる」** という設計判断で一貫して接続している。`__pycache__` も `Py_INCREF` も `abi3t` も、根は同じ問いに対する別レイヤの回答だった、と読めるところで締める。

---

## 不足情報 / 追加調査が必要な可能性

- 各高位ツール(pybind11 / nanobind / PyO3)の最新版での free-threaded build 対応状況 — 必要なら本文執筆時に公式リポジトリ README を `extract_url_content.py` で追加抽出
- `meson-python` の Adoption 状況の具体数(NumPy 1.26+ / SciPy 1.13+ などは確定だが、それ以外) — 公式ガイド側で十分カバーできる見込み
- PEP 489 multi-phase init の本文抽出が薄かったので、本文執筆時に再度 `extract_url_content.py` で取得(短い 1 セクションのみ追記想定)
