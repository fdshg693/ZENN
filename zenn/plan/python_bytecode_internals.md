---
title: "Pythonは本当にインタプリタ言語か? — __pycache__・.pyc・バイトコードの裏側を読み解く"
status: plan
---

## 想定読者と問い

- 想定読者: Python を業務で 2 年以上書いており、`__pycache__` が勝手にできること自体は知っているが、`import` / `.pyc` / バイトコードの関係を言語化できていない中上級エンジニア
- 扱うこと: CPython 3.11〜3.14 での `.pyc` の生成・無効化・最適化レベルの仕様、`importlib` / `compileall` / `dis` の使い分け、V8 との対比、実務(Docker・Lambda・再現ビルド)への応用
- 扱わないこと: CPython の C 実装詳細(ceval.c、opcode 実装)、PyPy / Jython の独自キャッシュ、Cython・C 拡張、freeze / PyInstaller による配布パッケージング

## 記事で答える問い

1. `.py` を実行するとき、**ソース → AST → バイトコード → VM** のどこで何が起きているのか
2. `__pycache__/foo.cpython-312.pyc` という名前は**なぜ**その形式なのか(PEP 3147)
3. `.pyc` が「古くなった」と判断される条件は何か(timestamp-based と hash-based、PEP 552)
4. `-O` / `-OO` / `.opt-1.pyc` / `.opt-2.pyc` は何を変えるのか(PEP 488)
5. ここから見える Python の強み(プラットフォーム非依存・自動再コンパイル・起動コスト低減)と弱み(バージョン固着・mtime 依存・obscurity にならない)
6. V8 Ignition / TurboFan と比べた場合、CPython の `.pyc` 戦略は「どこに振った設計」なのか
7. 実務で活きる具体的判断: Docker での `compileall`、Lambda / 読み取り専用 FS、`PYTHONPYCACHEPREFIX`、hash-based pyc と再現ビルド、`PYTHONDONTWRITEBYTECODE`

## 構成案

### 1. はじめに — Python は「毎回ソースを読み直している」のか?

- 「インタプリタ言語」という言葉の曖昧さを解く。CPython は実行前に必ずコンパイルする。
- `.py` を叩いた瞬間に起きることのタイムラインを要約し、記事のマップを示す。

### 2. CPython の実行モデル: ソース → AST → バイトコード → 評価ループ

- 4 段階のパイプラインを定義する: 字句解析 / 構文解析(AST)/ バイトコードコンパイル / `ceval` 評価ループ。
- 「コンパイル」という単語が **ネイティブコードではなく CPython VM 用バイトコードへの変換** を指すことを強調。
- バイトコードは `code object` としてメモリに存在する。`.pyc` はそれを **ディスクに serialize した形** に過ぎない、と位置付ける。
- 根拠: [tutorial/modules](https://docs.python.org/3/tutorial/modules.html), [reference/import §5.4](https://docs.python.org/3/reference/import.html), [dis](https://docs.python.org/3/library/dis.html)

### 3. dis で実際にバイトコードを覗いてみる

- `dis.dis(func)` の読み方(列: offset / opcode / arg / argval)
- 3.11 で導入された `CACHE` 命令、adaptive/specialized bytecode(`show_caches=True` / `adaptive=True`)
- 3.12/3.13/3.14 での出力仕様変更(offset 表現、jump ラベル化、`show_positions`)
- 「何が定数畳み込みされるか」「f-string は何に展開されるか」程度の実例を 1〜2 本
- 根拠: [dis](https://docs.python.org/3/library/dis.html)(`temp/python_bytecode_internals/extract_importlib_compileall_dis.json`)

### 4. `.pyc` と `__pycache__` の構造: PEP 3147 が解いた問題

- PEP 3147 以前の「`.pyc` がソースと同じ場所に平置きされる」問題(複数 Python バージョン共存不可・古い .pyc の誤ロード)
- 解決策としての `__pycache__/{module}.{cache_tag}.pyc`
- `cache_tag` = `sys.implementation.cache_tag`(例 `cpython-312`)。`importlib.util.cache_from_source` と `source_from_cache` の役割。
- **ソースが消えたら `__pycache__` の .pyc は無視される**という重要な仕様(PEP 3147)
- 根拠: [PEP 3147](https://peps.python.org/pep-3147/), [importlib.util](https://docs.python.org/3/library/importlib.html)

### 5. `.pyc` のヘッダ構造 — magic number を自力で読む

- .pyc ヘッダは 4 ワード(16 バイト)構成: magic / bit field / (timestamp + size) or (hash)
- magic number はバイトコードフォーマットのバージョン番号。`importlib.util.MAGIC_NUMBER` で取得可能。
- Python で `.pyc` をバイナリダンプし、先頭を解釈する短いスニペット(timestamp-based 前提)
- bit field の意味:
  - `0` → 従来の timestamp-based
  - `1` → hash-based, unchecked
  - `3` → hash-based, checked
- 根拠: [PEP 552](https://peps.python.org/pep-0552/), [importlib §MAGIC_NUMBER](https://docs.python.org/3/library/importlib.html)

### 6. キャッシュ無効化: timestamp-based と hash-based(PEP 552)

- デフォルトは timestamp-based(ソースの mtime + サイズを .pyc に埋める → インポート時に突き合わせる)
- mtime 方式の**弱点**を具体的に列挙:
  - コピー / tar 展開 / git checkout で mtime が現在時刻や epoch に揃うと判定が揺れる
  - 秒粒度しか見ない環境では同秒書き込みで古い .pyc が通る
  - 再現ビルド(同じ入力 → 同じ出力)を壊す原因になる
- PEP 552 の hash-based pyc(Python 3.7+): ソースの SipHash を埋めて比較
  - `checked` / `unchecked` の違いと `--check-hash-based-pycs default|always|never`
  - `SOURCE_DATE_EPOCH` 環境変数が設定されていると `compileall` が自動で `checked-hash` を使う
- 根拠: [PEP 552](https://peps.python.org/pep-0552/), [reference/import §5.4.6](https://docs.python.org/3/reference/import.html), [compileall](https://docs.python.org/3/library/compileall.html), [using/cmdline](https://docs.python.org/3/using/cmdline.html)

### 7. 最適化レベルと `.opt-N.pyc`(PEP 488)

- `-O` は `assert` を落とし `__debug__` を False にする。`-OO` はさらに `__doc__` も落とす。
- PEP 488 以前は `.pyo` という別拡張子だった → 最適化の種類が曖昧で、Python 3.5 で廃止
- 現在は **同じ `.pyc` 拡張子のまま、名前に `.opt-1` / `.opt-2` を埋める**(`importlib.cpython-312.opt-2.pyc`)
- 実務的影響: `-OO` でドキュメント文字列が消えるため、`inspect.getdoc()` や Sphinx を使うコードで壊れる
- 「.pyc 単体で読んだときに、最適化レベルが 1 つのファイル名から分かる」ことのメリット
- 根拠: [PEP 488](https://peps.python.org/pep-0488/), [using/cmdline -O/-OO](https://docs.python.org/3/using/cmdline.html)

### 8. ここから見える Python の構造 — 強みと弱み

強み:
- バイトコードは **プラットフォーム非依存**。`.pyc` だけあればアーキテクチャを跨いで動く([tutorial/modules](https://docs.python.org/3/tutorial/modules.html))
- import 時に **mtime 比較だけで自動的に再コンパイル**。開発体験で意識する必要がない。
- 動的言語にしては起動が遅くなりにくい(2 回目以降の import で AST→bytecode を省略)

弱み:
- バイトコードは **Python マイナーバージョン単位で互換性なし**(magic number が変わる)。3.11 の .pyc は 3.12 では読めない。
- 実行速度は上がらない。`.pyc` が速くするのは **ロード時間のみ**。VM 本体の速度は変わらない([tutorial/modules](https://docs.python.org/3/tutorial/modules.html) の明記あり)
- .pyc はソースの「obscurity(難読化)」にならない。`dis.dis` で簡単に読める。
- mtime 依存の cache invalidation は再現ビルドや分散環境で不安定 → PEP 552 が必要になった理由

### 9. V8 との対比 — 「起動を速くする側」vs「実行を速くする側」

- V8 の実行パイプライン: **Ignition**(bytecode interpreter)→ **Sparkplug**(3.9+、非最適化ベースライン JIT)→ **Maglev**(中間 JIT)→ **TurboFan**(最適化 JIT)。ホットな関数ほど上位コンパイラに tier-up される。
- V8 は bytecode を基本的に **ディスクに永続化しない**(Code Caching は別機構で、ブラウザに組み込まれている)。毎起動ごとにソース → bytecode を再生成する前提。
- CPython は真逆: **bytecode をディスクに永続化**するが、**ランタイム JIT 最適化は基本しない**(3.11 で adaptive specializing interpreter、3.13+ で experimental JIT が登場したが既定ではない)
- この対比が示すもの:
  - V8: 「同じ関数が 1 万回呼ばれる世界(Web ページ内ループ・Node サーバ)」に最適化された設計
  - CPython: 「スクリプトや CLI ツールが起動 → 有限回実行 → 終了」という世界で、**起動時 import を速くする** ことにコストを払う設計
- つまり `__pycache__` は Python が「動的言語でありながらスクリプト言語的な起動を許容するための装置」として見える
- 根拠: [V8 Ignition/TurboFan](https://v8.dev/blog/launching-ignition-and-turbofan), [V8 Sparkplug](https://v8.dev/blog/sparkplug), [V8 Maglev](https://v8.dev/blog/maglev)

### 10. 実務への応用

10.1 Docker ビルドで `compileall` を打つべきか
- イメージビルド時に `python -m compileall -q /app` を実行しておくと、**起動時の I/O とコンパイルを前倒し** できる。
- レイヤキャッシュと相性が悪い面(ソース変更で .pyc も作り直し)もあるため、RUN 位置は依存インストール後・ソースコピー直後が基本。
- `--invalidation-mode checked-hash` + `SOURCE_DATE_EPOCH` で再現ビルド可能なイメージを作れる。
- 根拠: [compileall](https://docs.python.org/3/library/compileall.html)

10.2 AWS Lambda / 読み取り専用 FS
- `.pyc` が書けない環境では初回 import で毎回コンパイルが走る。
- `PYTHONDONTWRITEBYTECODE=1` で「書き込み試行 → 失敗」のコストを消す、または**デプロイ時に事前 compileall**。
- 根拠: [PYTHONDONTWRITEBYTECODE, -B](https://docs.python.org/3/using/cmdline.html), [FAQ: .pyc が作れないケース](https://docs.python.org/3/faq/programming.html)

10.3 `PYTHONPYCACHEPREFIX` で source tree を汚さない(3.8+)
- 指定した外部ディレクトリに .pyc をミラー配置できる。
- モノレポ、read-only マウントされたソース、IDE が `__pycache__` を嫌う環境で有効。
- `compileall` とランタイムで **同じ prefix** を使うこと(公式注意)
- 根拠: [sys.pycache_prefix](https://docs.python.org/3/library/sys.html), [PYTHONPYCACHEPREFIX](https://docs.python.org/3/using/cmdline.html)

10.4 再現ビルド(Reproducible Build)
- Debian、Conda、wheel 配布で `.pyc` の mtime が揺れるとバイトコードレベルで差分が出る。
- `SOURCE_DATE_EPOCH` + hash-based pyc でビット一致可能。
- 根拠: [PEP 552](https://peps.python.org/pep-0552/), [compileall --invalidation-mode](https://docs.python.org/3/library/compileall.html)

10.5 `dis` を使ったパフォーマンス調査の小さい実例
- `if x in set(...)` vs `if x in (..., ..., ...)` のバイトコード差。
- ループ内の属性アクセス `obj.attr.method()` が何個の `LOAD_ATTR` を生むか。
- f-string vs `%` formatting vs `.format()` のバイトコード差。

### 11. まとめ

- `.pyc` / `__pycache__` は単なるキャッシュではなく、「動的言語 Python が起動コストをどう下げるか」という設計判断の結晶。
- timestamp-based ↔ hash-based、`PYTHONPYCACHEPREFIX`、`compileall`、`-O/-OO` は、**ユースケースに応じて使い分ける設計ツール**として理解するとよい。
- V8 との対比が示すように、Python は「実行を速くする」より「起動を速くする + ソースは常に権威」に振った言語。

## 根拠として参照する主要 URL・ファイル

- `temp/python_bytecode_internals/extract_peps.json`(PEP 3147 / 488 / 552)
- `temp/python_bytecode_internals/extract_importlib_compileall_dis.json`
- `temp/python_bytecode_internals/extract_cmdline_import_modules.json`
- `temp/python_bytecode_internals/search_pycache_overview.json`
- `temp/python_bytecode_internals/search_v8_ignition.json`

## 不確実な論点(本文執筆前に再確認するもの)

- Python 3.14 時点での `dis` 出力の正確な列構成(3.13 で jump ラベル化、3.14 で `-P` / `show_positions` 追加)→ 執筆時に再度[dis docs](https://docs.python.org/3/library/dis.html)で確認
- bit field の値: `0`(timestamp), `1`(hash, unchecked), `3`(hash, checked)と本文で書くが、正確な bit 割り付けは PEP 552 本文に基づく。執筆時に `check_source` bit と `hash-based` bit の組み合わせとして説明できるようにする
- experimental JIT(3.13+)の扱いは「章外の注記」で留める
