# Tavily ラッパースクリプト群(Python 実装)

このディレクトリは、Tavily SDK を **プロジェクト固有のデフォルト引数で固定した Python ラッパー** の実体です。AI や利用者には `--detail=quick|balanced|max` のような抽象化された少数引数だけ握らせ、Tavily SDK の細かいオプションはスクリプト側のプリセットでロックします。

スキルとしての位置付け・前提条件・ドキュメント構成は、一つ上の階層の [README.md](../README.md) を参照してください。AI に読ませる判断フローや命名規約は [SKILL.md](../SKILL.md) にあります。このファイルは **Python コードそのものの説明** に責務を絞っています。

## 実装方針

- スクリプトに渡せる引数は最小限にする
  - Tavily SDK の細かいオプションをそのまま外に出しすぎると、Python でラップする意味が薄くなる
  - AI や利用者は `--detail=max` のような抽象化された引数を使うことに集中し、Tavily のどのオプションへどう変換するかはスクリプト内のプリセットで制御する
  - デフォルト値やプリセット対応表は、各スクリプト先頭で編集しやすい形に置く
- 共通箇所は基本的に `tavily_common.py` へ切り出す
  - `.env` 読み込み
  - Tavily クライアント生成
  - JSON 出力整形
  - 共通のレスポンス整形
  - **戻り値の契約**(`ExitCode` / `ResultKind` / `ResultEnvelope` / `ResponseEnvelope` / `OutputChannel` / `RunOutcome` / `emit()` / `finalize()`)。終了コード・出力形状・出力先はここの列挙/`TypedDict`/`dataclass` が正本(詳細は後述の「実行結果の戻り値(契約)」)
- 各スクリプトにはファイル冒頭コメントを書き、用途・最小引数・どこを編集すれば挙動を変えられるかを明示する
- スクリプトの詳細な引数や最新の使い方は各スクリプトの `--help` を確認する

## クイックスタート

1. Tavily API キーを `.claude/skills/use-tavily/.env` に書くか、環境変数 `TAVILY_API_KEY` にセット
2. `pip install tavily python-dotenv` を実行
3. 一番簡単なキーワード検索を試す:

```bash
python ./.claude/skills/use-tavily/src/search_topic.py "Microsoft Fabric overview" \
  --include-domain learn.microsoft.com \
  --output temp/web/search_msfabric_overview.json
```

PowerShell の場合:

```powershell
python .\.claude\skills\use-tavily\src\search_topic.py "Microsoft Fabric overview" `
  --include-domain learn.microsoft.com `
  --output temp\web\search_msfabric_overview.json
```

各スクリプトの引数詳細は `--help` で確認できます。

```bash
python ./.claude/skills/use-tavily/src/search_topic.py --help
```

## 実行結果の戻り値(契約)

CLI の戻り値は **終了コード・出力データ・監査ログ・出力先** の 4 つの契約に分かれ、いずれも `tavily_common.py` の型/列挙で固定しています。コメントではなく実体(`IntEnum` / `Enum` / `TypedDict` / `dataclass`)が正本で、この表はその写しです。

### 内部構造 — functional core / imperative shell

各スクリプトの `main()` は **副作用を持たない計算ステップ** で、戻り値として `RunOutcome`(`dataclass`: 終了コード + 出力先 + ログ + `result_kind` + `result` + stderr メッセージ)を返すだけ。ファイル書き込みや stdout/stderr 出力は一切しない。

I/O は唯一 `finalize(outcome) -> ExitCode` が担う。エントリポイントは常に次の 1 行:

```python
if __name__ == "__main__":
    raise SystemExit(finalize(main()))
```

これにより `main()` の本当の成果物(payload と終了コード)が **戻り値として型に現れる**。stdout やファイルを捕捉せずに `main(argv)` を呼んで結果を検証・合成できる(`finalize` を呼ばなければ何も書かれない)。エラー時(API キー不備・例外)は `RunOutcome` の `log` を `None` にして返し、`finalize` は出力エンベロープを書かず `message` だけを stderr に出す。

### 1. プロセス終了コード — `ExitCode`(`tavily_common.py`)

全スクリプトの `main()` は `ExitCode` のメンバーを返します。呼び出し側はこの整数で分岐できます。

| code | メンバー | 意味 |
|------|---------|------|
| `0` | `SUCCESS` | 正常完了。データは下記エンベロープにある(検索 0 件でも成功扱い) |
| `1` | `RUNTIME_ERROR` | 想定外の失敗(ネットワーク / API エラー、research が failed・cancelled で終了) |
| `2` | `MISSING_API_KEY` | `TAVILY_API_KEY` が未設定または空 |
| `3` | `INVALID_API_KEY` | Tavily にキーを拒否された |
| `4` | `EMPTY_RESULT` | 呼び出しは成功したが後段に渡せるデータが無い(抽出対象 URL が 0 件)。`search_extract` / `map_extract` のみ |
| `5` | `INCOMPLETE` | 長時間処理(research)が待機時間内に終端状態へ到達しなかった。`research_topic` のみ |

`4` / `5` は以前 1 つのコードに混在していたものを分離しています(`research` のタイムアウトは `4` ではなく `5`)。

### 2. 出力データ — `ResultEnvelope`(`--output` ファイル / stdout)

全スクリプトが **同一形状の自己記述エンベロープ** を出力します。`--output` 指定時はそのファイルへ、未指定時は stdout へ書き出します。`result_kind` が判別子で、`result` の中身の読み方を示します(スクリプトのソースを読まずに形が分かる)。

```json
{
  "script": "search_topic.py",
  "result_kind": "search_results",
  "exit_code": 0,
  "result": [ /* result_kind で形が決まる */ ]
}
```

`result_kind`(`ResultKind`)と各スクリプトの `result` の中身:

| スクリプト | `result_kind` | `result` の中身 |
|-----------|---------------|----------------|
| `search_topic.py` | `search_results` | `list[SearchResultItem]`: Tavily search の結果オブジェクト |
| `extract_url_content.py` | `extract_results` | `list[ExtractResultItem]`: Tavily extract の結果オブジェクト |
| `crawl_site_content.py` | `crawl_results` | `list[CrawlResultItem]`: Tavily crawl の結果オブジェクト |
| `map_site_titles.py` | `site_pages` | `list[SitePageItem]`: ページタイトル記録(`PageTitleResult`) |
| `map_extract_site_content.py` | `extract_results` | `list[ExtractResultItem]`: extract 結果(URL 0 件なら空配列) |
| `search_extract_topic.py` | `extract_results` | `list[ExtractResultItem]`: extract 結果(URL 0 件なら空配列) |
| `research_topic.py` | `research_report` | `str`: レポート本文(markdown)。失敗時のみ最終レスポンス dict 全体 |

> 後段で結果を読むときは、トップレベルの `result` を取り出してから中身を処理する。`exit_code` を見れば、ファイル単体でも成功/空/未完了が判別できる。

各 `*Item` は `tavily_common.py` の `TypedDict` で **実際の API レスポンスから実測して確定** させた型です(ドキュメントではなく実体が正本)。スクリプトの固定フラグ(`include_raw_content` / `include_images` / `include_favicon` はすべて False)前提なので、例えば search は `raw_content` キーを常に持つが値は `None`、extract は未ドキュメントの `title` を必ず持つ、といった実測事実を反映しています。

- 型を **どう実測して確定したか**(プローブ各種・fixtures 再生成)→ [../experiments/README.md](../experiments/README.md)
- 型が **実 API と一致することの検証**(オフライン構造検証 + `TAVILY_LIVE_TESTS=1` のライブ再検証)→ [../tests/README.md](../tests/README.md)

### 3. 監査ログ — `ResponseEnvelope`(常時)

`--output` の有無にかかわらず、毎回 `logs/<script>-log.json` にリクエスト/レスポンス全体を `{script, request, environment, response}` の形で残します。再現・原因追跡用の詳細ビューで、出力エンベロープよりも冗長です。

### 4. 出力先 — `OutputChannel`(どのストリーム/ファイルに何が出るか)

上の 1〜3 が **何を** 返すかなら、これは **どこへ** 出すかの契約です。全出力は唯一のシンク `emit(channel, ...)` を通り、`OutputChannel` で行先が決まります。これにより「どこからどこまでが結果で、どこからが通知か」が一意になります。

| メンバー | 中身 | 行先 | 構造化 |
|---------|------|------|--------|
| `RESULT_STDOUT` | `ResultEnvelope` JSON | stdout(`--output` 未指定時のみ) | あり |
| `RESULT_FILE` | `ResultEnvelope` JSON | `--output` のパス | あり |
| `AUDIT_LOG` | `ResponseEnvelope` JSON | `logs/<script>-log.json`(常時) | あり |
| `DIAGNOSTIC` | 「Wrote ...」「Research finished ...」等の 1 行 | stderr | なし |

規律: **stdout には機械可読な `ResultEnvelope` だけ(または何も出さない)。「Wrote ...」等の通知・エラー・進捗はすべて stderr の `DIAGNOSTIC`。** 後段で結果をパースするときは stdout をそのまま読めばよく、stderr は純粋な診断として扱える。`emit()` 以外の場所で `print` しない(出力点を一箇所に集約する)ことがこの契約を成立させています。

## どのスクリプトを使うか

迷ったら以下を出発点にしてください。詳細な判断フローは [SKILL.md](../SKILL.md) の「最初に見るべき判断フロー」を参照。

| 状況 | 使うスクリプト |
|------|--------------|
| キーワードから関連 URL を集めたい | `search_topic.py` |
| キーワード → 候補 URL → 本文抽出まで一気に | `search_extract_topic.py` |
| 問いに対して AI 調査と要約まで任せたい | `research_topic.py` |
| 取得したい URL がもう手元にある | `extract_url_content.py` |
| サイト内のページ一覧と構造を見たい | `map_site_titles.py` |
| サイトをマップしてから関連ページを抽出 | `map_extract_site_content.py` |
| サイト全体から関連本文をまとめて回収 | `crawl_site_content.py` |

## ファイル構成

```text
src/
├── README.md                    ← このファイル(Python コードの説明)
├── tavily_common.py             ← .env 読込、クライアント生成、JSON 整形、戻り値契約(ExitCode/ResultKind/各 Envelope/OutputChannel/RunOutcome/emit/finalize)
├── search_topic.py              ← キーワード検索の最小ラッパー
├── search_extract_topic.py      ← search → extract の合成
├── research_topic.py            ← Research API ラッパー
├── extract_url_content.py       ← URL 群から本文抽出
├── map_site_titles.py           ← サイトの URL 一覧 + タイトル
├── map_extract_site_content.py  ← map → extract の合成
├── crawl_site_content.py        ← サイトクロール + 本文回収
└── logs/                        ← 各実行のリクエスト/レスポンス JSON
```

## カスタマイズ箇所

| 変えたいこと | 編集場所 |
|--------------|---------|
| `--detail` プリセット(検索深さ / 結果数 / チャンク数) | 各スクリプト冒頭の `DETAIL_PRESETS` 辞書 |
| デフォルトの詳細度 | 各スクリプトの `DEFAULT_DETAIL` 定数 |
| `include_answer` / `include_raw_content` などの固定フラグ | 各スクリプト冒頭の定数(`INCLUDE_ANSWER` 等) |
| タイムアウト | 各スクリプトの `REQUEST_TIMEOUT_SECONDS` |
| `.env` 読み込み挙動・JSON 出力フォーマット | `tavily_common.py` |
| 出力ファイル命名規約 | [SKILL.md](../SKILL.md) の「出力ファイルの推奨命名規約」セクション |
| AI に提示する判断フロー / 引数例 | [SKILL.md](../SKILL.md) 本体 |

新しい使い方を追加したい場合は、`src/` 配下に同じスタイルで新スクリプトを作り、`SKILL.md` に判断フローと引数例を追記してください。`--detail` プリセットやデフォルト値は新スクリプト冒頭にも同じ形で置きます。
