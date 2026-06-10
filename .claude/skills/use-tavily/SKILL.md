---
# Version 2.0.0
name: use-tavily
description: Skill to understand how to utilize Tavily to achieve specific goals in this project. **NOT HOW TO USE TAVILY SDK**. For that, see the `tavily-sdk` skill. 

# 同階層の.envファイルに有効なTAVILY_API_KEYの設定が必要
# 同じ .env で TAVILY_OUTPUT_DIR(出力先ベース、未設定時は temp/web)と TAVILY_WRITE_LOG(監査ログ出力トグル、未設定=true)も設定できる
# Python が使える環境
# tavily / python-dotenv がグローバルにインストールされていること
# 短縮コマンド tav を使うには、初回のみ `pip install -e .claude/skills/use-tavily` を実行する
---

## エントリポイント: `tav` コマンド

| サブコマンド | 対応スクリプト | 概要 |
|------|------|------|
| `tav search` | `src/search_topic.py` | キーワード → 関連 URL とスニペット |
| `tav search-extract` | `src/search_extract_topic.py` | キーワード → 関連 URL → 本文抽出まで |
| `tav research` | `src/research_topic.py` | 問いを Tavily research に投げてレポートを待つ |
| `tav extract` | `src/extract_url_content.py` | 既知 URL → 本文抽出 |
| `tav map` | `src/map_site_titles.py` | サイトルート → URL 一覧 + タイトル |
| `tav map-extract` | `src/map_extract_site_content.py` | サイトを map してから対象 URL を extract |
| `tav crawl` | `src/crawl_site_content.py` | サイトをクロールして関連本文を収集 |

- 引数の確認: `tav <サブコマンド> --help`、サブコマンド一覧: `tav`(引数なし)。
- 編集は editable install なので、スクリプトを直したら再インストール不要でそのまま反映される。
- `tav` が未インストールの環境では、従来どおり `python .\.claude\skills\use-tavily\src\<script>.py ...` でも動く。以下の例は `tav` 形で示す。

## クエリ言語とドメインフィルタの実務ルール

- `query` や `input` は **日本語でも問題なく使ってよい**。特に記事調査や要件整理では、日本語の問いをそのまま渡して構わない。
- ただし、製品名、機能名、正式ドキュメント名は英語のほうが強いことがある。日本語で結果が弱い場合は、英語または日英混在クエリで再実行する。
- `--include-domain` は「その host を優先・許可するための強い絞り込み」と考え、**厳密な完全一致隔離フィルタ** だと思わないこと。
- 実際には、関連する Microsoft 系サブドメインやリダイレクト先が返ることがある。`microsoft.com` のように広い指定より、`learn.microsoft.com` や `techcommunity.microsoft.com` のような狭い host 指定を優先する。
- 返ってきた URL が想定外なら、後段で URL 一覧を見て手動またはスクリプト側で再選別する。

## 最初に見るべき判断フロー

初見で迷ったら、以下の順で選ぶ。

```text
1. すでに対象 URL が分かっているか?
   Yes -> tav extract
   No  -> 2 へ

2. すでに対象サイトのルート URL が分かっているか?
   Yes -> 3 へ
   No  -> 4 へ

3. サイトに対して何をしたいか?
   ページ一覧や構造を見たい              -> tav map
   サイト本文を一気に回収したい          -> tav crawl
   先に候補 URL を見てから本文抽出したい -> tav map-extract

4. 手元にあるのは topic / question / keyword だけか?
   Yes -> 5 へ
  No  -> 追加の入力条件を整理してから再判定

5. キーワード起点なら何がほしいか?
   まず関連 URL と要約だけ見たい        -> tav search
   まず根拠 URL を広く集めたい           -> tav search
   関連 URL の本文まで続けて取りたい     -> tav search-extract
   AI に調査と要約まで任せたい           -> tav research
```

迷った場合のデフォルトは以下。

- topic 起点なら、まず `tav search`
- URL 起点なら、まず `tav extract`
- サイト起点なら、まず `tav map`

## Windows / bash の注意

- `tav` はインストール済みなら PowerShell でも bash でもそのまま `tav search "..."` で呼べる(PATH 上の console コマンドなので、シェルによるパス記法の差を受けない)。
- 出力先は `--topic <name>` で指定する(トピック名のスラッグだけ。実際の保存先は `<TAVILY_OUTPUT_DIR>/<topic>/` に解決される)。`--topic` を省くと単一 `ResultEnvelope` を stdout に出す。シェルによるパス記法の差を受けないのが利点。
- `tav` を使わず生のスクリプトを叩く場合のみ、bash では `python ./.claude/skills/use-tavily/src/search_topic.py "..."` のように `./` と `/` を使い、`\` 区切りは避ける。

## ユースケースごとの使い分け

- 特定サイトの網羅的な情報抽出
  - URL 一覧の取得だけ Tavily を使い、その後は自前処理で制御したい: `map`
  - URL 取得から本文回収まで Tavily に任せたい: `crawl`
  - URL をいったん見極めてから本文抽出したい: `map` -> `extract`
- 特定 URL から内容を取得
  - 対象 URL がすでに決まっている: `extract`
  - Python などで直接 HTML を取る方法もあるが、このスキルでは原則として非推奨
- キーワードに関連した情報抽出
  - まず関連 URL やスニペットを把握したい: `search`
  - 根拠 URL の本文まで続けて確認したい: `search` -> `extract`
  - AI に調査と要約まで任せたい: `research`

## `--detail` プリセット早見表

各スクリプトの `DETAIL_PRESETS` が正本。ここではスクリプト横断で比較しやすいように主要パラメータだけ抜き出す。

| 対象 | `quick` | `balanced` | `max` |
|------|------|------|------|
| `src/search_topic.py` | `search_depth=fast`, `max_results=5`, `chunks=2` | `search_depth=advanced`, `max_results=5`, `chunks=3` | `search_depth=advanced`, `max_results=8`, `chunks=5` |
| `src/research_topic.py` | `model=mini`, `poll=5s`, `wait<=120s` | `model=auto`, `poll=5s`, `wait<=180s` | `model=pro`, `poll=10s`, `wait<=300s` |
| `src/extract_url_content.py` | `extract_depth=basic`, `query_chunks=2` | `extract_depth=advanced`, `query_chunks=3` | `extract_depth=advanced`, `query_chunks=5` |
| `src/crawl_site_content.py` | `depth=1`, `breadth=20`, `limit=10`, `extract=basic`, `query_chunks=2` | `depth=2`, `breadth=30`, `limit=20`, `extract=advanced`, `query_chunks=3` | `depth=3`, `breadth=40`, `limit=40`, `extract=advanced`, `query_chunks=5` |
| `src/map_site_titles.py` | `map_depth=1`, `breadth=20`, `limit=20`, `title_workers=4` | `map_depth=2`, `breadth=30`, `limit=40`, `title_workers=6` | `map_depth=3`, `breadth=40`, `limit=80`, `title_workers=8` |
| `src/map_extract_site_content.py` | `map_limit=10`, `extract=basic`, `query_chunks=2` | `map_limit=20`, `extract=advanced`, `query_chunks=3` | `map_limit=40`, `extract=advanced`, `query_chunks=5` |
| `src/search_extract_topic.py` | `search_results=5`, `search_chunks=2`, `extract=basic`, `extract_chunks=2` | `search_results=5`, `search_chunks=3`, `extract=advanced`, `extract_chunks=3` | `search_results=8`, `search_chunks=5`, `extract=advanced`, `extract_chunks=5` |

使い分けの目安:

- まず当たりを付ける探索段階: `quick`
- 普段の標準: `balanced`
- URL 数や抽出粒度を増やしたい再実行: `max`

## 出力先と `--topic` レイアウト

出力先はフルパスではなく `--topic <name>` で指定する。実際の保存先は `<TAVILY_OUTPUT_DIR>/<topic>/`(`.env` の `TAVILY_OUTPUT_DIR`、未設定時は `temp/web`)に解決される。`topic` は記事やテーマ単位の短いスラッグ(英数字と `_`)に揃える。

**解決の基準ディレクトリ(重要)**: `TAVILY_OUTPUT_DIR` が絶対パスならそのまま使う。相対パス(既定の `temp/web` を含む)は **コマンドを実行したカレントディレクトリ基準**で解決される(`.env` の場所でも、スクリプトの場所でもない)。したがって出力は `<実行時のcwd>/<TAVILY_OUTPUT_DIR>/<topic>/` に作られる。意図どおり `./temp/web/<topic>/` に出すには、**リポジトリルートから実行する**こと(旧来の `--output temp/web/...` も同じく cwd 基準だった)。`temp/web` を使う他スキル(例: `zenn`)も、この「ルートから実行」前提を共有する。

- `--topic <name>` を渡す → トピックフォルダ配下に新レイアウトで書き出す(下記)。
- `--topic` を省く → 単一 `ResultEnvelope` を stdout に出す(パイプ用途。従来どおり)。

旧来の `--output temp/web/<command>_<slug>.json`(スクリプトごとにフルパスを毎回手書きする)は廃止した(後方互換なし)。トピックフォルダ内のレイアウトは `result_kind` で決まる 3 系統:

- **集約(aggregate)**: `search` → `search.json` / `map` → `map.json`。url+title の一覧をコマンド名のファイル 1 つにまとめる。中身は通常の `ResultEnvelope`。
- **分割(split)**: `extract` / `crawl` / `search-extract` / `map-extract`。URL ごとに `0001.json`, `0002.json`, …(0001 から 4 桁ゼロ埋め)を 1 ファイルずつ作り、加えてマスター索引 `index.json` を置く。各連番ファイルは `result` がその URL 単体の content アイテム(リストではない)で、必ず `title` を持つ `ResultEnvelope`。`index.json` が唯一の url↔ファイル対応表。
- **単一(single)**: `research` → `research.json`。research レポートは分割しない。

レイアウト例:

```text
temp/web/                         ← TAVILY_OUTPUT_DIR(.env)
└── msfabric_overview/            ← <topic>
    ├── search.json               ← 集約(search)
    ├── map.json                  ← 集約(map)
    ├── research.json             ← 単一(research)
    ├── index.json                ← 分割: マスター索引
    ├── 0001.json                 ← 分割: 1 URL の本文
    └── 0002.json
```

`index.json` の形(content 系コマンドが書く。1 URL = 1 エントリ):

```json
{
  "script": "crawl_site_content.py",
  "result_kind": "crawl_results",
  "topic": "msfabric_overview",
  "entries": [
    {"file": "0001.json", "url": "https://…", "title": "…", "title_source": "html|existing|url_fallback", "exit_code": 0}
  ]
}
```

- `title` は content 系で必ず埋まる。既にタイトルがあれば保持(`title_source:"existing"`)、欠けていれば HTML を直接 Fetch して補完(`"html"`、失敗時は URL 由来のスラッグで `"url_fallback"`)。Tavily はタイトル取得に使わない。
- 同じコマンドを同じ `--topic` で再実行すると、各ファイルと `index.json` を上書きする(直近の実行を正とする)。

例(コマンド):

- `tav search "Microsoft Fabric overview" --include-domain learn.microsoft.com --topic msfabric_overview` → `temp/web/msfabric_overview/search.json`
- `tav map-extract https://learn.microsoft.com/azure/api-management/ --topic apim_docs` → `temp/web/apim_docs/0001.json …` + `index.json`

## 出力エンベロープと終了コード

各スクリプトが書き出す JSON は **自己記述エンベロープ** で、トップレベルは常に同じ形。生の配列ではない。

```json
{ "script": "...", "result_kind": "search_results", "exit_code": 0, "result": [ /* 本体 */ ] }
```

- 出力先は `--topic` の有無で決まる。`--topic <name>` 指定時はトピックフォルダ配下のファイル(上記レイアウト)へ、未指定時は単一 `ResultEnvelope` を stdout へ出す。`--output` は廃止した。
- 後段で結果を読むサブエージェントは、必ず **トップレベルの `result` を取り出してから** 中身を処理する。
- content 系(分割レイアウト: `extract` / `crawl` / `search-extract` / `map-extract`)を `--topic` で受けた場合は、**まず `index.json` を読み、各エントリの `file`(`0001.json` …)を順に開く**。各連番ファイルは `result` がその URL 単体の content アイテムで、必ず `title` を持つ。集約系(`search.json` / `map.json`)・単一系(`research.json`)はそのファイル 1 つを読めばよい。
- `result_kind` が `result` の読み方を示す: `search_results` / `extract_results` / `crawl_results`(`list[dict]`)、`site_pages`(`list[dict]`、タイトル記録)、`research_report`(`str` 本文 or `dict`)。分割レイアウトの連番ファイルでは `result` が単一アイテム(リストではない)。
- `exit_code` でファイル単体でも成否が分かる。`0`=成功、`2`/`3`=API キー不備、`4`=抽出対象 URL が 0 件(`search_extract`/`map_extract`)、`5`=research がタイムアウト、`1`=その他失敗。
- 全実行のフル詳細(リクエスト/レスポンス)は `src/logs/<script>-log.json` に別途残る。`.env` の `TAVILY_WRITE_LOG`(未設定=`true`、`false`/`0`/`no`/`off`/空で抑止)でこの監査ログ出力をトグルできる。

正本は `src/tavily_common.py` の `ExitCode` / `ResultKind` / `ResultEnvelope`。詳細表は [src/README.md](src/README.md) の「実行結果の戻り値(契約)」。

## 並列実行・レート・コストの扱い

Tavily の credit 消費量やレート制限は、プラン、API、詳細度、将来の仕様変更で変わりうる。正確な数値は Tavily の公式ドキュメントやダッシュボードを必ず確認すること。このスキルには固定の credit 数を埋め込まない。

このリポジトリでの運用上の目安は以下。

- 軽い処理の初期探索では `search_topic.py` や `map_site_titles.py` を優先し、重い `extract` / `crawl` / `research` は候補を絞ってから打つ
- `quick` または `balanced` の `search` / `map` / 単発 `extract` は、まず 3 並列を基準にする
- 問題がなければ 5 並列程度までは試してよいが、`crawl` と `research` は 1 から 2 並列を基本にする
- `map_extract` や `search_extract` は内部で 2 段階 API を呼ぶため、外側の並列度は低めに保つ
- `429`、タイムアウト増加、応答遅延が見えたら並列数を半分に落とす
- 大量実行時は、まず `quick` で候補選定し、必要な対象だけ `balanced` または `max` で再実行する

## スクリプト一覧

各スクリプトの詳細な引数や最新の使い方は、対象スクリプトの `--help` を利用して確認する。

### 1. キーワード起点で調べる

ここが最も呼び出し頻度が高い起点。特に迷ったら、まず `src/search_topic.py` を使う。

| 区分 | スクリプト | 概要 | 使う場面 |
|------|------|------|------|
| 1.a | `src/search_topic.py` | `search` 単体を実行する最小ラッパー。詳細度プリセットと必要最小限のドメインフィルタだけ公開する。 | 関連 URL とスニペットをまず確認したい場合。初手として最も無難。 |
| 1.b | `src/search_extract_topic.py` | `search` で候補 URL を集め、返ってきた URL をそのまま `extract` に渡して本文を取得する。`src/search_topic.py` と `src/extract_url_content.py` の再利用で構成する。 | まず関連ページを把握し、その後に根拠ページ本文まで明示的に確認したい場合。 |
| 1.c | `src/research_topic.py` | `research` を使って調査タスクを投げ、完了まで待ってレポートを JSON で返す最小ラッパー。モデル選択と待機設定は詳細度プリセットで管理する。 | キーワードや問いに対して、単発検索ではなく AI に調査と要約までまとめて任せたい場合。 |

### 2. URL 起点で調べる

| 区分 | スクリプト | 概要 | 使う場面 |
|------|------|------|------|
| 2.a | `src/extract_url_content.py` | 1つ以上の URL を対象に `extract` を実行する最小ラッパー。詳細度プリセットで Tavily の抽出設定を内包する。 | 対象 URL がすでに決まっており、全文または特定話題に絞った内容をすぐ取得したい場合。 |

### 3. サイト起点で網羅的に調べる

| 区分 | スクリプト | 概要 | 使う場面 |
|------|------|------|------|
| 3.a | `src/map_site_titles.py` | `map` で URL 一覧を取得し、各ページの HTML からタイトルを自動取得して一覧化する。失敗時は URL 由来のフォールバック名を返す。 | サイト内ページの一覧や構造を確認しつつ、後段の処理を自分で細かく制御したい場合。 |
| 3.b | `src/crawl_site_content.py` | `crawl` を 1 ステップで実行する最小ラッパー。詳細度プリセットでクロール深さ・抽出品質を内包し、`--query` は内部で `instructions` に変換して関連内容を優先取得する。 | サイト全体から関連ページ本文をまとめて収集したい場合。 |
| 3.c | `src/map_extract_site_content.py` | `map` で候補 URL を取得し、その URL 群に対して `extract` を実行する合成ラッパー。`map_site_titles.py` と同じフィルタ引数を維持しつつ、抽出対象を最大 20 URL に絞る。 | 取得対象 URL をいったん見極めてから、必要なページだけ抽出したい場合。 |