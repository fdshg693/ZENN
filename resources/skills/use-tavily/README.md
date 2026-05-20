# Tavilyをデフォルト引数などを半固定した上でAIに呼び出させるためのスキル

Tavily の検索 / 抽出 / クロール / マップ / リサーチを、**プロジェクト固有のデフォルト引数で固定した Python ラッパー** として呼び出せるようにする Claude Code 用スキルです。AI に Tavily SDK を直接触らせるのではなく、`--detail=quick|balanced|max` のような抽象化された少数引数だけ握らせることで、検索品質と再現性を安定させます。

## 前提条件

- Python / pip
- Tavily API キー: `TAVILY_API_KEY` 環境変数にセットまたは、 `.claude\skills\use-tavily\.env` に記載
- Tavily Python SDK: `pip install tavily` でインストール

## このスキルの目的

- AI が WEB 調査をするとき、毎回パラメータがブレて品質と費用が読めなくなる問題を解決する
- Tavily SDK の細かいオプションを **スクリプト側のプリセットでロック** し、AI には「目的」と「詳細度」だけ選ばせる
- 検索結果を `temp/web/` 配下に **命名規約付き JSON** で蓄積し、後段のスクリプトやサブエージェントが拾えるようにする
- 実行のリクエスト/レスポンスを `src/logs/` に残し、後から再現・原因追跡できるようにする

## このスキルの特徴

- **判断軸つき一枚スキル**: API ごとにスキルを分けず、`SKILL.md` の冒頭に「URL が分かっているか / サイトが分かっているか / キーワードだけか」という判断フローを置いている
- **詳細度プリセット**: 各スクリプトの先頭に `DETAIL_PRESETS = {"quick": ..., "balanced": ..., "max": ...}` を持ち、Tavily の `search_depth` / `max_results` / `chunks_per_source` などはここで集中管理
- **共通モジュール化**: `.env` 読み込み・Tavily クライアント生成・JSON ペイロード整形を `src/tavily_common.py` に集約
- **出力命名規約**: `temp/web/{prefix}_{topic_slug}.json` 形式で出力先を統一(`search_` / `extract_` / `site_map_` / `site_extract_` / `site_crawl_` / `search_extract_` / `research_`)
- **bash / PowerShell 両対応の実行例**: 各スクリプトの docstring 冒頭に最小コマンド例を載せている

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

## どのスクリプトを使うか

迷ったら以下を出発点にしてください。詳細な判断フローは [SKILL.md](SKILL.md) の「最初に見るべき判断フロー」を参照。

| 状況 | 使うスクリプト |
|------|--------------|
| キーワードから関連 URL を集めたい | `src/search_topic.py` |
| キーワード → 候補 URL → 本文抽出まで一気に | `src/search_extract_topic.py` |
| 問いに対して AI 調査と要約まで任せたい | `src/research_topic.py` |
| 取得したい URL がもう手元にある | `src/extract_url_content.py` |
| サイト内のページ一覧と構造を見たい | `src/map_site_titles.py` |
| サイトをマップしてから関連ページを抽出 | `src/map_extract_site_content.py` |
| サイト全体から関連本文をまとめて回収 | `src/crawl_site_content.py` |

## ファイル構成

```text
.claude/skills/use-tavily/
├── README.md            ← このファイル
├── SKILL.md             ← AI に読ませるスキル本体(判断フロー / 引数例 / 命名規約)
└── src/
    ├── tavily_common.py        ← .env 読込、Tavily クライアント生成、JSON 整形
    ├── search_topic.py         ← キーワード検索の最小ラッパー
    ├── search_extract_topic.py ← search → extract の合成
    ├── research_topic.py       ← Research API ラッパー
    ├── extract_url_content.py  ← URL 群から本文抽出
    ├── map_site_titles.py      ← サイトの URL 一覧 + タイトル
    ├── map_extract_site_content.py ← map → extract の合成
    ├── crawl_site_content.py   ← サイトクロール + 本文回収
    └── logs/                   ← 各実行のリクエスト/レスポンス JSON
```

## カスタマイズ箇所

| 変えたいこと | 編集場所 |
|--------------|---------|
| `--detail` プリセット(検索深さ / 結果数 / チャンク数) | 各スクリプト冒頭の `DETAIL_PRESETS` 辞書 |
| デフォルトの詳細度 | 各スクリプトの `DEFAULT_DETAIL` 定数 |
| `include_answer` / `include_raw_content` などの固定フラグ | 各スクリプト冒頭の定数(`INCLUDE_ANSWER` 等) |
| タイムアウト | 各スクリプトの `REQUEST_TIMEOUT_SECONDS` |
| `.env` 読み込み挙動・JSON 出力フォーマット | `src/tavily_common.py` |
| 出力ファイル命名規約 | `SKILL.md` の「出力ファイルの推奨命名規約」セクション |
| AI に提示する判断フロー / 引数例 | `SKILL.md` 本体 |

新しい使い方を追加したい場合は、`src/` 配下に同じスタイルで新スクリプトを作り、`SKILL.md` に判断フローと引数例を追記してください。

## 詳細

AI に読ませる判断フロー、`--detail` プリセット早見表、並列実行とコストの目安、各スクリプトの位置付けは [SKILL.md](SKILL.md) を参照してください。
