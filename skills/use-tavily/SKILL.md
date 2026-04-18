---
name: use-tavily
description: Skill to understand how to utilize Tavily to achieve specific goals in this project. **NOT HOW TO USE TAVILY SDK**. For that, see the `tavily-sdk` skill. 
---

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
   Yes -> src/extract_url_content.py
   No  -> 2 へ

2. すでに対象サイトのルート URL が分かっているか?
   Yes -> 3 へ
   No  -> 4 へ

3. サイトに対して何をしたいか?
   ページ一覧や構造を見たい              -> src/map_site_titles.py
   サイト本文を一気に回収したい          -> src/crawl_site_content.py
   先に候補 URL を見てから本文抽出したい -> src/map_extract_site_content.py

4. 手元にあるのは topic / question / keyword だけか?
   Yes -> 5 へ
  No  -> 追加の入力条件を整理してから再判定

5. キーワード起点なら何がほしいか?
   まず関連 URL と要約だけ見たい        -> src/search_topic.py
   まず根拠 URL を広く集めたい           -> src/search_topic.py
   関連 URL の本文まで続けて取りたい     -> src/search_extract_topic.py
   AI に調査と要約まで任せたい           -> src/research_topic.py
```

迷った場合のデフォルトは以下。

- topic 起点なら、まず `src/search_topic.py`
- URL 起点なら、まず `src/extract_url_content.py`
- サイト起点なら、まず `src/map_site_titles.py`

## Windows / bash の注意

- Windows 上で bash を使う場合、パスは `./` と `/` を使う。Windows 形式の相対パスや `\` 区切りは避ける。
- 例: `python ./.claude/skills/use-tavily/src/search_topic.py "Microsoft Fabric overview"`
- 出力先も bash では `temp/web/search_fabric_overview.json` のように `/` 区切りを使う。
- PowerShell では `.\.claude\skills\use-tavily\src\search_topic.py` のような Windows 形式でもよい。

## 実装方針

- スクリプトに渡せる引数は最小限にする
  - Tavily SDK の細かいオプションをそのまま外に出しすぎると、Python でラップする意味が薄くなる
  - AI や利用者は `--detail=max` のような抽象化された引数を使うことに集中し、Tavily のどのオプションへどう変換するかはスクリプト内のプリセットで制御する
  - デフォルト値やプリセット対応表は、各スクリプト先頭で編集しやすい形に置く
- 共通箇所は基本的に `src` 配下の共通モジュールへ切り出す
  - `.env` 読み込み
  - Tavily クライアント生成
  - JSON 出力整形
  - 共通のレスポンス整形
- 各スクリプトにはファイル冒頭コメントを書き、用途・最小引数・どこを編集すれば挙動を変えられるかを明示する
- スクリプトの詳細な引数や最新の使い方は各スクリプトの `--help` を確認する

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

## 出力ファイルの推奨命名規約

出力ファイルは基本的に `temp/web/` 配下へ保存する。別スキルから呼ばれない単独利用でも、この規約に寄せる。

- `temp/web/search_{topic_slug}.json`: `src/search_topic.py`
- `temp/web/research_{topic_slug}.json`: `src/research_topic.py`
- `temp/web/extract_{topic_slug}.json`: `src/extract_url_content.py`
- `temp/web/site_map_{topic_slug}.json`: `src/map_site_titles.py`
- `temp/web/site_extract_{topic_slug}.json`: `src/map_extract_site_content.py`
- `temp/web/site_crawl_{topic_slug}.json`: `src/crawl_site_content.py`
- `temp/web/search_extract_{topic_slug}.json`: `src/search_extract_topic.py`

`topic_slug` は英数字と `_` を使った短い識別子に揃える。

例:

- `temp/web/search_msfabric_overview.json`
- `temp/web/site_extract_apim_docs.json`

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