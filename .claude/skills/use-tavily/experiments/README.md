# Tavily レスポンス型の実測実験

このディレクトリは、Tavily API が **実際に返す結果オブジェクトの型** を観測して確定させるための実験用スクリプト群(使い捨ての実験ノート)です。

背景: ラッパースクリプトの戻り値はかつて「ただの `dict`」という緩い扱いでした。API がある程度安定していることを踏まえ、ここで実レスポンスを観測し、ドキュメントではなく **実体** から型を確定させました。確定した型は [`../src/tavily_common.py`](../src/tavily_common.py) の `TypedDict` に、その型の検証は [`../tests/`](../tests/README.md) にあります。

> **方針**: 公開ドキュメントの表ではなく、ライブ API の実レスポンスを正本とする。実際、ドキュメントと実体が食い違う箇所が複数見つかりました(下記)。

## ファイル構成

```text
experiments/
├── README.md                  ← このファイル
├── probe_response_shapes.py   ← search / extract / crawl / map の per-item キーと型を一括観測
├── probe_edge_shapes.py       ← failed_results の形 と extract の title 常在性を確認
├── probe_research_shape.py    ← research 完了レスポンス(content / sources)の形を観測
└── capture_fixtures.py        ← 実レスポンスを ../tests/fixtures/ に保存(テストの入力を再生成)
```

`capture_fixtures.py` は各 `*.json` に加えて、取得日時を `../tests/fixtures/captured_at.txt`(ISO 8601・ローカルタイムゾーン)に書き出します。fixtures がいつ時点のものかを後から追えるようにするためです。

各スクリプトは、**本番ラッパーと同じ固定フラグ**(`resolve_*_options` 経由)で API を1回ずつ叩きます。クレジットを抑えるため `quick` プリセットを使う箇所があります。

## 実行方法

リポジトリルートから(`.env` に `TAVILY_API_KEY` が必要):

```bash
python .claude/skills/use-tavily/experiments/probe_response_shapes.py
python .claude/skills/use-tavily/experiments/probe_edge_shapes.py
python .claude/skills/use-tavily/experiments/probe_research_shape.py   # 遅い・~1-2分

# テスト用 fixtures を本物のレスポンスで作り直す
python .claude/skills/use-tavily/experiments/capture_fixtures.py
```

`probe_*` は観測結果を標準出力に表示します(スクラッチ用の `*_result.json` は残しません)。`capture_fixtures.py` のみ `../tests/fixtures/*.json` と `../tests/fixtures/captured_at.txt`(取得日時)を更新します。

## 実測で確定した主な事実(固定フラグ前提)

`include_raw_content` / `include_images` / `include_favicon` をすべて False、`format="markdown"` という本番フラグでの観測:

- **search**: `raw_content` キーは**常に存在し値は `None`**(ドキュメントはフラグ有効時のみ存在の含み)。`favicon` キーは無い。
- **extract**: **未ドキュメントの `title` が必ず存在**(複数 URL で確認)。`images` は空リストで常に存在。
- **crawl**: `url` と `raw_content` のみ。`raw_content` は **`None` になりうる**。`title` / `images` / `favicon` は無い。
- **map**: `results` は `list[str]`(URL 文字列)。
- **research**: 完了時 `content` は `str`。`sources[]` は `{url, title, favicon}`(ドキュメントは `citation` と記載 → 実体は `favicon`)。

## 型を変えたくなったら

1. ここのプローブで実体を観測する。
2. 観測に合わせて [`../src/tavily_common.py`](../src/tavily_common.py) の `TypedDict` を更新する。
3. `capture_fixtures.py` で fixtures を更新し、[`../tests/`](../tests/README.md) のテストで一致を確認する。
