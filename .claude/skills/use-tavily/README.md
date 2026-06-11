# Tavilyをデフォルト引数などを半固定した上でAIに呼び出させるためのスキル

Tavily の検索 / 抽出 / クロール / マップ / リサーチを、**プロジェクト固有のデフォルト引数で固定した Python ラッパー** として呼び出せるようにする Claude Code 用スキルです。AI に Tavily SDK を直接触らせるのではなく、`--detail=quick|balanced|max` のような抽象化された少数引数だけ握らせることで、検索品質と再現性を安定させます。

このファイルは **スキルの設定・全体像の理解** に責務を絞っています。Python スクリプトの使い方・引数・カスタマイズ箇所は [src/README.md](src/README.md) を、AI に読ませる判断フロー・命名規約は [SKILL.md](SKILL.md) を参照してください。

## 前提条件

- Python / pip
- Tavily API キー: `TAVILY_API_KEY` 環境変数にセットまたは、 `.claude\skills\use-tavily\.env` に記載
- (任意)`.env` で出力先と監査ログを調整:
  - `TAVILY_OUTPUT_DIR`: `--topic` の解決先ベースディレクトリ。未設定時は `temp/web`
  - `TAVILY_WRITE_LOG`: `logs/<script>-log.json` を書くか。未設定=`true`、`false`/`0`/`no`/`off`/空で抑止
- Tavily Python SDK / 依存パッケージ: `pip install tavily python-dotenv` でインストール

## このスキルの目的

- AI が WEB 調査をするとき、毎回パラメータがブレて品質と費用が読めなくなる問題を解決する
- Tavily SDK の細かいオプションを **スクリプト側のプリセットでロック** し、AI には「目的」と「詳細度」だけ選ばせる
- 検索結果を `<TAVILY_OUTPUT_DIR>/<topic>/` 配下(既定 `temp/web/<topic>/`)に **トピック単位のレイアウトで** 蓄積し、後段のスクリプトやサブエージェントが拾えるようにする
- 実行のリクエスト/レスポンスを `src/logs/` に残し、後から再現・原因追跡できるようにする

## このスキルの特徴

- **判断軸つき一枚スキル**: API ごとにスキルを分けず、`SKILL.md` の冒頭に「URL が分かっているか / サイトが分かっているか / キーワードだけか」という判断フローを置いている
- **詳細度プリセット**: 各スクリプトの先頭に `DETAIL_PRESETS = {"quick": ..., "balanced": ..., "max": ...}` を持ち、Tavily の `search_depth` / `max_results` / `chunks_per_source` などはここで集中管理
- **共通モジュール化**: `.env` 読み込み・Tavily クライアント生成・JSON ペイロード整形・戻り値契約を `src/tav_core/` パッケージに責務ごとに分割して集約(旧 `tavily_common.py` を `result_contract` / `environment` / `output` / `topic_layout` などへ分割)
- **`--topic` トピックレイアウト**: 出力先はフルパスでなく `--topic <name>` で指定し、`<TAVILY_OUTPUT_DIR>/<topic>/`(既定 `temp/web/<topic>/`)配下に集約(`search.json`/`map.json`)・分割(`0001.json`… + `index.json`)・単一(`research.json`)の 3 系統で書き出す(`--topic` 省略時は stdout に単一 `ResultEnvelope`)
- **戻り値の契約**: 全スクリプトが同一形状の自己記述エンベロープ(`result_kind` + `result` + `exit_code`)を出力し、終了コードは `ExitCode`(`IntEnum`)で共通化。`src/tav_core/result_contract.py` の列挙/`TypedDict` が正本で、詳細は [src/README.md](src/README.md) の「実行結果の戻り値(契約)」を参照
- **bash / PowerShell 両対応の実行例**: 各スクリプトの docstring 冒頭に最小コマンド例を載せている

## ドキュメント構成

責務ごとに 3 つのドキュメントへ分割しています。

| ファイル | 読む人 | 内容 |
|----------|--------|------|
| `README.md`(このファイル) | スキルを導入・把握したい人 | スキルの目的、前提条件、全体像、ドキュメント構成 |
| [SKILL.md](SKILL.md) | AI(スキル本体) | 判断フロー、`--detail` プリセット早見表、並列/コストの目安、`--topic` 出力レイアウト |
| [src/README.md](src/README.md) | スクリプトを使う / 改修する人 | クイックスタート、スクリプト一覧、引数、カスタマイズ箇所 |

## ファイル構成

```text
.claude/skills/use-tavily/
├── README.md            ← このファイル(スキルの設定・全体像)
├── SKILL.md             ← AI に読ませるスキル本体(判断フロー / 引数例 / 命名規約)
└── src/
    ├── README.md              ← Python コードの説明(使い方 / カスタマイズ)
    ├── tav_core/              ← 共通実装パッケージ(.env 読込・クライアント生成・JSON 整形・戻り値契約・出力レイアウト・title 補完)
    │   ├── result_contract.py / tavily_types.py   ← 戻り値契約の型・列挙 / Tavily レスポンス要素型
    │   ├── environment.py / output.py             ← .env・クライアント・環境トグル / 出力シンク emit()
    │   ├── topic_layout.py / run_shell.py         ← 役割別出力ライタ(何をどこへ)/ 命令的シェル finalize()・spawn
    │   ├── projection.py                          ← 結果アイテムの投影(調査に要る列だけ残す)
    │   └── page_title.py / text_utils.py          ← HTML タイトル取得 / slugify・dedupe
    ├── search_topic.py        ← キーワード検索の最小ラッパー
    ├── search_extract_topic.py ← search → extract の合成
    ├── research_topic.py      ← Research API ラッパー
    ├── extract_url_content.py ← URL 群から本文抽出
    ├── map_site_titles.py     ← サイトの URL 一覧 + タイトル
    ├── map_extract_site_content.py ← map → extract の合成
    ├── crawl_site_content.py  ← サイトクロール + 本文回収
    ├── tav_cli.py             ← サブコマンドを各ラッパーへ振り分けるディスパッチャ(`tav` の実体)
    └── logs/                  ← 各実行のリクエスト/レスポンス JSON
```

## 次に読むもの

- スクリプトをすぐ動かしたい・引数やカスタマイズ箇所を知りたい → [src/README.md](src/README.md)
- AI に読ませる判断フロー、`--detail` プリセット早見表、並列実行とコストの目安 → [SKILL.md](SKILL.md)
