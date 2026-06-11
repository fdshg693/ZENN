# 実装プラン: `--topic` をトピック蓄積ワークスペースにする

> このプランは [README.md](README.md) の「実行結果の戻り値(契約)」を前提に、`--topic` の出力を
> **「複数の調査タスクをためる作業場」**として再設計するための作業計画。実装着手前のレビュー用。

## 0. 設計の出発点 — なぜ「ただ分割」では駄目か

`tav search --topic <name>` の `<name>/` フォルダは、単一クエリの出力先ではなく
**複数回・複数種の調査タスクをためていくシンボル**。だから「同じトピックに何でも放り込む」と、
種類の違うものが混ざって視認性が崩れる。要点は**出力の“役割”がコマンドごとに根本的に違う**こと:

| 役割 | コマンド | 成果物の性質 | 読み方 | 最適な置き方 |
|------|---------|-------------|--------|-------------|
| **discovery(候補メニュー)** | `search` / `map` | `(url, title, snippet/score)` の小さい行が多数 | **一覧で表として skim** し、次に何を読むか決める | **集約**(1 タスク = 1 リストファイル) |
| **content(取得本文)** | `extract` / `crawl` | 1 件が大きい本文 | **1 件ずつ開いて読む** | **分割**(1 ファイル = 1 ページ) |
| **report(成果物)** | `research` | 統合済みの散文レポート | **通しで読む** | **単一**(1 ファイル) |

ここから最適方針が機械的に出る:

- discovery を **URL ごとに分割するのは逆効果** — 5 行のメニューが 5 ファイルに散ると一覧性が消える。
  → discovery は**集約**して 1 ファイルに、1 タスク(1 クエリ / 1 サイト)= 1 ファイルにする。
- content を **1 ファイルに集約するのは逆効果** — 数百 KB の本文が連結されると読めず、必要な 1 件だけ
  取り出せない。→ content は**1 ページ = 1 ファイル**に分割し、意味のある名前/索引で 1 件を選べるようにする。
- 役割が違うもの(メニューと本文と成果物)を**同じ連番列に混ぜない** — **役割ごとにサブフォルダで隔離**する。

> 前案の「すべてを `index.json` + 連番 `NNNN.json` に統一(search も URL 単位に展開)」は、
> discovery を分割してしまい一覧性を壊す**誤り**だった。本案はこれを採らない。

## 1. ディレクトリ設計

トピックフォルダ `<TAVILY_OUTPUT_DIR>/<topic>/` を**役割サブフォルダ**で分ける。
サブフォルダ名・ファイル名そのものが索引になり、`ls <topic>/` で全体像が掴める:

```text
<topic>/
├── search/                              ← discovery: 検索タスク。1 クエリ = 1 ファイル
│   ├── 0001-microsoft-fabric-overview.json
│   └── 0002-fabric-vs-synapse.json
├── map/                                 ← discovery: サイト URL 一覧。1 map = 1 ファイル
│   └── 0001-learn-microsoft-com.json
├── pages/                               ← content: 取得本文。1 ページ = 1 ファイル
│   ├── 0001-learn-microsoft-com-apim.md
│   ├── 0002-azure-ad-obo-flow.md
│   └── index.json                       ← url ↔ file ↔ title ↔ 由来コマンド の対応表
└── research/                            ← report: 1 問い = 1 レポート
    └── 0001-how-does-obo-work.md
```

設計上の決めごと(すべて視認性 / 情報の絞り込みから導出):

- **連番はサブフォルダ内で独立**(`search/0001`、`pages/0001` は別系列)。役割をまたぐ通し番号は作らない
  ＝混ざらない。
- **ファイル名 = `NNNN-<slug>`**。`NNNN` で順序と一意性、`slug`(クエリ/ドメイン/タイトル由来)で
  **開かずに中身が分かる**。slug 生成ヘルパー `slugify()` を追加。
- **追記は新ファイル**: 同じトピックに新タスクが来たら次の `NNNN` を採る(既存スキャンで `max+1`)。
  **上書きしない / 重複も保持**(同じクエリ再実行 → `0003-<同じクエリ>.json` が増える。同じ URL 再 extract
  → `pages/` に別ファイル + index に別エントリ)。
- **索引は `pages/` にだけ置く**。content は分割 + バイナリ的に大きく、ファイル名だけでは url/由来が辿れない
  ため `index.json` が必要。discovery / report は**ファイル名が自己説明的**なので索引なし(`ls` で足りる。
  余計なメタファイルを作らない)。
- **トップレベルの集約マニフェストは作らない**(初期)。役割フォルダ + ファイル名で全体像は読めるので、
  append 管理が要る追加索引は視認性に寄与せず保守コストだけ増える。必要が出たら後付け。

## 2. フォーマット選択 — 「読むもの」は Markdown、「処理するもの」は JSON

役割ごとに**最適なフォーマット**を選ぶ(ここも視認性/絞り込みから導出):

| 役割 | フォーマット | 理由 |
|------|------------|------|
| discovery(search/map) | **JSON**(slim・pretty) | 表データ(url/title/score/snippet)で、skim もするが**次段 extract への入力**でもある。機械可読を保つ。各行は調査トリアージに要る最小列だけ。 |
| content(extract/crawl) | **Markdown**(`# <title>` + 本文) | 本文は**読むためのもの**。JSON 文字列にエスケープされた `\n` まみれの本文より、`.md` 1 ページの方が桁違いに読める。url↔file の機械的対応は `pages/index.json` が保持するので構造は失わない。 |
| report(research) | **Markdown** | 元から markdown 本文。`.md` でそのまま読める。失敗時のみ生 dict を `.json` で残す(原因追跡用)。 |

これは「**必要な情報だけを最も読みやすい形で**」という要求③の精神そのもの。本文を `.md` 化することが
本プランで視認性に最も効く一手。

**契約への影響と切り分け**(重要):

- `--topic` **省略時**は従来どおり **stdout に単一 `ResultEnvelope`(JSON)** を出す。パイプ契約は不変。
  → `.md` 化は**トピックモードのファイル出力に限った**話で、stdout の機械可読契約は壊さない。
- すなわち `OutputChannel` は据え置き、`RESULT_FILE` の中身が役割で `.json`(discovery / index)か
  `.md`(content / report)に分岐する、という整理にする。

## 3. コマンド別 — 何を・どこに・どう変えるか(変えない理由も明記)

| コマンド | 役割 | 出力先 | 形式 | 単位 | 変更点 / 変えない理由 |
|---------|------|--------|------|------|----------------------|
| `search` | discovery | `search/NNNN-<query>.json` | 集約 JSON リスト | 1 クエリ=1 ファイル | 現状 `search.json` 上書き → **クエリ別 append** に変更。**分割しない**(メニューは一覧で読むものだから) |
| `map` | discovery | `map/NNNN-<domain>.json` | 集約 JSON リスト | 1 map=1 ファイル | **変える(置き場とファイル名のみ)**。URL 単位に**分割しない**理由 = map の価値は「サイトの URL 在庫を 1 枚で見渡す」ことで、分割するとその一覧性が消えるから |
| `extract` | content | `pages/NNNN-<slug>.md` + `pages/index.json` | 分割 MD | 1 URL=1 ファイル | 現状の split を踏襲しつつ **`.md` 本文 + 連番継続 append** に変更 |
| `crawl` | content | `pages/…` | 分割 MD | 1 URL=1 ファイル | extract と同じ(大量取得版)。同じ `pages/` に流す |
| `search-extract` | discovery+content | `search/`(メニュー)+ `pages/`(本文) | JSON + MD | — | 合成: 検索結果リストを `search/` に、抽出本文を `pages/` に**両方**残す(中間メニューも捨てない) |
| `map-extract` | discovery+content | `map/` + `pages/` | JSON + MD | — | 合成: map 一覧を `map/`、抽出本文を `pages/` に両方 |
| `research` | report | `research/NNNN-<question>.md` | 単一 MD | 1 問い=1 ファイル | 現状 `research.json` 上書き → **問い別 append**。成功は `.md`、失敗のみ `.json`(生 dict) |

> 「`map` は変えるのか」への答え: **置き場とファイル名は変える(`map/NNNN-<domain>.json`)が、
> 集約リストである性質は変えない**。理由は上表のとおり map の出力は discovery 役割だから。

## 4. 要求 4 点をこの設計に載せる

### ① 同一トピックは上書きでなく追記(重複保持)
- 各役割フォルダ内で `NNNN` を**既存スキャンして継続採番**(`max+1`)。新タスク = 新ファイル。
- `pages/index.json` は**ロード→ append→ 書き戻し**。重複 URL も別エントリで残す。横断的 dedupe はしない
  (ドメインの within-run dedupe `dedupe_preserve_order` は維持)。

### ② `.env` でログ出力先のターミナル表示を制御
- 新 env `TAVILY_SHOW_OUTPUT_PATHS`(未設定=`true`、`false`/`0`/`no`/`off`/空 で抑止)。
  `should_write_log()` と同じパースをヘルパー化して共有。
- 「Wrote … to <path>」系の **stderr `DIAGNOSTIC` パス通知だけ**をトグル。エラー/空/未完了の `message` は
  出し続ける(結果通知でありパス通知ではない)。stdout 契約・ファイル書き込み自体は不変。
- [.env.example](../.env.example) に追記:
  ```dotenv
  # Echo "Wrote … to <path>" destination lines to the terminal (stderr). Default (unset) is true.
  # Set to false / 0 / no / off to silence path notices (files are still written).
  TAVILY_SHOW_OUTPUT_PATHS=true
  ```

### ③ 調査に無関係な JSON フィールドを排除
- `ResultEnvelope` / index に書く**直前に投影** `slim_result_item(result_kind, item)` を追加。生 `*Item`
  TypedDict(L122〜)は fixtures 検証の正本として維持し、投影は別レイヤーで載せる。監査ログは生のまま。
- 役割に沿った残す/落とす(着手時に確定、コード先頭の許可リスト定数で可変):

  | result_kind | 残す | 落とす(理由) |
  |-------------|------|--------------|
  | `search_results` | `url`, `title`, `content`, `score` | `raw_content`(フラグ上常に `None`)。`score` は**残す(確定)** |
  | `extract_results` | `url`, `title`, 本文 | `images`(常に空) |
  | `crawl_results` | `url`, 本文 | (なし) |
  | `site_pages` | `url`, `title`, `short_title` | `title_source`, `final_url`, `content_type`, `status_code`, `error`(取得メタ。調査本文に無関係) |
  | `research_report` | 本文 | (成功時は元から本文のみ) |

- content の `.md` は `# <title>` + 本文だけ(images/メタを持ち込まない)。これ自体が③の体現。

### ④ 集約 vs 分割をコード/CLI ヘルプから明確化
- **設計レベルで曖昧さを消す**: 「役割 → 置き場 → 形式」が §0〜§3 の表で一意。`output_shape_for` の
  3-way 振り分けは**役割ベースの明示的ディスパッチ**に置き換え、関数名・docstring に役割名(discovery/
  content/report)を出す。
- 共有定数 `TOPIC_ARG_HELP` を [tavily_common.py](tavily_common.py) に置き全スクリプトの `--topic` で再利用:
  > `--topic NAME`: accumulate this run into `<TAVILY_OUTPUT_DIR>/NAME/`. Discovery commands
  > (`search`/`map`) append one list file under `search/` or `map/`; content commands
  > (`extract`/`crawl`) write one `.md` per page under `pages/` (indexed by `pages/index.json`);
  > `research` writes one `.md` under `research/`. Existing files are kept (never overwritten).
  > Omit `--topic` to print one `ResultEnvelope` to stdout.
- 各 parser に `epilog`(`RawDescriptionHelpFormatter`)で**そのコマンドの置き場・形式**を 2〜3 行明記。
  → `tav extract --help` を見れば「`pages/` に `.md` 1 ページずつ + index」と即分かる。
- [tav_cli.py](tav_cli.py) の `render_usage()` 各行に役割タグ(discovery/content/report)を添える。

## 5. 影響ファイル

| ファイル | 変更 |
|---------|------|
| [tavily_common.py](tavily_common.py) | 役割ベースのディスパッチ、サブフォルダ採番 append、`pages/index.json` 蓄積、`.md` レンダラ、投影層、`slugify`、`TOPIC_ARG_HELP`、パス通知トグル、docstring(中核) |
| 各ラッパー 7 本 | `TOPIC_ARG_HELP` 適用・`epilog` 追加。`search-extract`/`map-extract` は discovery 半分も残すよう結線 |
| [tav_cli.py](tav_cli.py) | `render_usage()` に役割タグ |
| [.env.example](../.env.example) | `TAVILY_SHOW_OUTPUT_PATHS` 追記 |
| [../tests/test_output_layout.py](../tests/test_output_layout.py) | サブフォルダ別 append・連番継続・`pages/index.json` 蓄積・`.md` 出力・パス通知トグルの新テスト |
| [../tests/test_result_types.py](../tests/test_result_types.py) | 投影後 `Emitted*Item` 検証を追加(生 `*Item` 検証は維持) |
| [README.md](README.md) | 「実行結果の戻り値(契約)」の出力先節を**役割ベースのディレクトリ設計**で全面改稿 |
| [../SKILL.md](../SKILL.md) | 「出力先と `--topic` レイアウト」を役割サブフォルダ + フォーマット選択に更新 |

## 6. 主要関数の変更(コア = [tavily_common.py](tavily_common.py))

- 削除: `output_shape_for`(L374)/`layout_filename_for`(L388)/`write_single_file_result`(L549)。
- 置換: `write_split_results`(L612) → 役割別の 3 ライタ
  - `write_discovery_list(role_dir, ...)`: 1 リスト JSON を `NNNN-<slug>.json` に追記書き(索引なし)。
  - `write_content_pages(pages_dir, ...)`: URL ごと `.md` を連番継続で書き、`pages/index.json` を append。
    タイトル補完 `ensure_item_titles`(L575)は維持(`.md` の H1 と index title に使う)。
  - `write_report(research_dir, ...)`: 成功 `.md` / 失敗 `.json` を `NNNN-<slug>` で書く。
- `emit_payload`(L483): `topic is None` は stdout 単一 `ResultEnvelope`(投影済み)。`topic` 指定時は
  `result_kind`(と合成コマンドの場合は複数 role)を役割にマップして上記ライタへディスパッチ。
- 新規: `slugify(text) -> str`、`next_sequence(dir) -> int`、`render_page_markdown(item) -> str`、
  `should_show_output_paths() -> bool`、`slim_result_item(kind, item) -> dict`。

## 7. テスト計画

1. **役割分離**: search→`search/`, extract→`pages/`, research→`research/` に出て、互いに混ざらない。
2. **discovery 集約**: search は URL 単位に分割されず 1 ファイルに全行が入る。
3. **content 分割 + md**: extract は URL ごと `.md`(`# title` 付き)+ `pages/index.json` に対応エントリ。
4. **追記 / 重複保持**: 同トピックで search 2 回 → `0001`,`0002` 併存。同 URL extract 2 回 → `pages/` に
   2 ファイル + index に 2 エントリ。
5. **投影**: search 出力に `raw_content` 無し / extract md に images 無し。監査ログには生フィールドが残る。
6. **パス通知トグル**: `TAVILY_SHOW_OUTPUT_PATHS=false` で「Wrote … to」行が消え、ファイルは書かれる。
7. **stdout 契約**: `--topic` 省略時は従来どおり stdout に単一 `ResultEnvelope`(投影済み)。
8. **ファイル名**: `NNNN-<slug>` の slug がクエリ/ドメイン/タイトルから生成され衝突しない。

## 8. 未確定 / 留意

- `site_pages` の落とすメタ項目(`title_source` ほか)は暫定。着手時に確定。
- content/report を `.md` にする方針は**トピックモード限定**(stdout は JSON 維持)。README/SKILL.md は
  実装確定後にコードへ追従(契約の正本はコードの型/列挙)。
- 合成コマンド(`search-extract`/`map-extract`)は discovery 半分も**残す(確定)**。検索/map のメニューを
  `search/`/`map/` に、抽出本文を `pages/` に両方書き、「何を見て何を取ったか」を後から辿れるようにする。
- サブフォルダ採番は逐次実行前提(並行採番衝突は非対応、docstring 明記)。
- `pages/index.json` のみ append 管理が要る共有ファイル。旧スキーマ移行はしない(読めなければ作り直す)。
