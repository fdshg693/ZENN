---
title: MCPサーバーだけでは足りなかった ― Tavilyを"プロジェクト最適化"する3層構成
emoji: 🛠
type: tech
topics: [claudecode, tavily, mcp, agentskills, python]
published: true
---

## はじめに ― AI に検索させると、品質がブレる

Claude Code や Cursor のような AI コーディングツールに「ちょっと最新情報を調べて」と頼むと、たいてい次のどれかが起きます。

- 同じ問いに対して、実行のたびに引数や検索深さが変わり、根拠の厚みもバラつく
- AI が判断で `advanced` や `crawl` を勝手に選び、知らない間にコストが跳ねる
- 出力の置き場が散らばり、後から「あの調査どこに行った?」が再現できない

これは「検索 API が悪い」のではなく、**「AI に検索 API の引数決定まで任せきっている」** ことが原因です。本記事では、検索 API として Tavily を選ぶ理由を整理した上で、それを **「MCP サーバー / 公式スキル / 自作 Python ラッパー / 自作カスタムスキル」** という層に分けて捉え直し、最終的にどう組み合わせると安定運用できるかをまとめます。

---

## なぜ Tavily か ― 汎用検索や AI 組み込み検索では足りない理由

Tavily は「LLM が読むためのコンテキスト整形まで含めて 1 コールで返してくれる」ように設計された検索 API です。汎用検索 + 自前スクレイピング + 自前要約のパイプラインに比べて段数が少なく、結果として AI に渡る情報のブレが小さくなります。

公式 API リファレンスから、特に AI 調査で効くパラメータを抜粋します。

### Search API: LLM 文脈を意識した「事前チャンク化」

- `search_depth` が 4 段階 (`ultra-fast` / `fast` / `basic` / `advanced`)。`advanced` は精度重視で 2 credit、それ以外は 1 credit
- `chunks_per_source` で「URL ごとに最大 500 文字 × N 個のチャンク」を返せる。LLM のコンテキスト窓を意識した分割が API 側で完結する
- `include_domains` / `exclude_domains` がそれぞれ最大 300 / 150 ドメインまで指定可能
- `topic` (`general` / `news` / `finance`)、`time_range`、`start_date` / `end_date` で時系列・ジャンルを絞れる
- `include_answer` で LLM 生成の直接回答、`include_raw_content` で本文も同じ呼び出しに同梱できる

参考: https://docs.tavily.com/documentation/api-reference/endpoint/search

### Extract / Crawl / Map / Research

- **Extract** は単なるスクレイピングと違い、「取得 + クリーニング + チャンク化 + クエリによる再ランク」を 1 コールで提供。失敗 URL は課金されない (https://docs.tavily.com/documentation/api-reference/endpoint/extract)
- **Map** は GET 系のサイトグラフ走査で、自然言語 `instructions`(例: 「Find all pages about the Python SDK」)、正規表現の `select_paths` / `select_domains` で絞り込める (https://docs.tavily.com/documentation/api-reference/endpoint/map)
- **Crawl** は map + extract を統合して、サイト配下の本文をまとめて回収する (https://docs.tavily.com/documentation/api-reference/endpoint/crawl)
- **Research** はエージェンティック調査 API で、`model=mini|pro|auto`、`output_schema`(JSON Schema)、`citation_format` (`numbered` / `apa` / `mla` / `chicago`) まで持つ。30〜120 秒程度で出典付きレポートが返る (https://docs.tavily.com/documentation/best-practices/best-practices-research)

### AI コードツール組み込み検索との違い

Claude Code や各種 AI エディタ組み込みの「Web 検索ツール」は便利ですが、

- 検索深さやチャンクサイズなどの細かいパラメータをこちらから握れない
- ドメインフィルタの上限や挙動が不透明で、再現性のある「公式 Docs だけを読ませる」運用がしづらい
- ツールのバージョンアップで挙動が静かに変わる可能性がある

という弱点があります。記事執筆や設計判断の根拠を集めるような「再現性が品質を左右する用途」では、引数を明示できる Tavily 側に倒したほうが結果が安定します。

> 料金体系 (Free 1,000 credits / 月、Pay-as-you-go ほか) と各 API の credit 単価は変動するので、実際の数字は公式 https://docs.tavily.com/documentation/api-credits と https://www.tavily.com/pricing を都度確認してください。

---

## なぜ MCP サーバーだけでは足りないか

「Tavily の MCP サーバーを Claude Code に繋げばいいのでは?」という発想は当然出ます。実際それで一定の調査はできます。ただ、運用に乗せると次の限界に当たります。

公式 MCP のドキュメント (https://docs.tavily.com/documentation/mcp) を読むとわかるポイント:

- リクエストごとの引数は **クライアント側 LLM がプロンプトから決定** する。つまり「いつ `advanced` を使うか」「どのドメインを優先するか」はその場の AI 任せになる
- Tavily 側は、この問題に対する逃し弁として `DEFAULT_PARAMETERS` という JSON を、リモート版はリクエストヘッダ、ローカル版は環境変数で受けられるようにしている。逆に言えば、**それを設定しない限り、引数のデフォルトはサーバ側組み込み値か AI の判断任せ**

要するに MCP は **「ツールを生やす」までの責任範囲** であって、「プロジェクトとしてどう使うか」は依然としてユーザー側の問題として残ります。MCP の上に、プロジェクト固有のデフォルト・命名規約・判断軸を載せる層が要ります。

---

## 公式 `Tavily公式スキル` の物足りなさ

ありがたいことに、Tavily は公式の Agent Skill 一式を配布しています ([README.md](https://github.com/tavily-ai/skills/README.md))。

この公式スキルは `search` / `extract` / `map` / `crawl` / `research` をそれぞれ独立した Skill として持ち、加えて `tavily-best-practices` で 6 本のリファレンス ([skills/tavily-best-practices/SKILL.md](https://github.com/tavily-ai/skills/skills/tavily-best-practices/SKILL.md) と references/{search,extract,crawl,research,sdk,integrations}.md) を用意しています。判断フローや非同期パターンまで丁寧に書かれていて、設計の出発点としては優れています。

ただ、実際に組み込むと **「素のまま使うには物足りない」** 点がいくつか見えてきます。

### 1. 利用が CLI (`tvly`) 前提

公式の README が示すワークフローは「CLI を 5 段階で escalate する」スタイルです ([README.md](https://github.com/tavily-ai/skills/README.md))。SDK 直叩きで「自前の Python スクリプトとしてプロジェクト内で持つ」想定にはなっていません。CLI の出力を `--json` で受けて自前処理に流す、という運用はやれますが、**プロジェクト固有のラッパーを置く場所**は提供されません。

### 2. デフォルト引数を「プロジェクト標準」として固定する仕組みが無い

`max_depth=1`、`chunks_per_source=3` のような実用デフォルトは references に書かれていますが、**それを「このリポジトリではこの値で固定する」というロックは Skill 側ではかからない**。結局 AI は毎回引数を判断することになり、MCP と同じ問題が形を変えて残ります。

### 3. 出力ファイルの命名・保存先がプロジェクトに合わない

`crawl --output-dir ./docs/` のような形で出力先は指定できますが、**プロジェクト内で「`temp/web/search_*.json` に統一する」のような規約はスキル側で持てません**。後段で別のスクリプトやサブエージェントが結果を探しに行く場合、命名がバラついていると拾えません。

### 4. 実行ログ・履歴の標準化が無い

`--json` で出力は構造化されますが、「いつ・どの引数で・どのクエリを打ったか」をプロジェクト配下に残す層は公式スキルの守備範囲外です。後から再現したい / コストが跳ねた原因を追いたい、というときに困ります。

### 5. スキルが API 単位で分割されている

これは長所でもありますが、**「どの Skill を呼ぶか」の判断が AI に委ねられる** という副作用があります。問いに対して `search` で済むのに `research` を選ぶ、URL がもう手元にあるのに改めて `search` する、といった選定誤りが起きやすい。Skill 単位で見るのではなく、**目的を聞いてから API を割り当てる「判断軸つきの一枚スキル」** のほうが、誤選択は減ります。

---

## 解決策 ― 「Python ラッパー」+「カスタムスキル」の 2 層

ここまでの問題は、**「Tavily を、プロジェクト標準のデフォルトと判断軸でロックする層」** を上に被せれば解決できます。私のリポジトリでは、それを次の 2 層に分けて実装しています。

```text
┌───────────────────────────────────────────────────────────────────────────────────────────────┐
│ カスタムスキル                                                                                 │  
│(https://github.com/fdshg693/ZENN/blob/main/skills/use-tavily)                                 │  ← AI が読む「目的→スクリプト」の判断軸
├───────────────────────────────────────────────────────────────────────────────────────────────┤
│ 自作 Python ラッパー                                                                           │
│(https://github.com/fdshg693/ZENN/blob/main/skills/use-tavily/src/*.py + tavily_common.py)     │  ← 引数の最小化、プリセット、ログ
├───────────────────────────────────────────────────────────────────────────────────────────────┤
│ Tavily Python SDK                                                                             │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

スキル本体は [skills/use-tavily/SKILL.md](https://github.com/fdshg693/ZENN/blob/main/skills/use-tavily/SKILL.md) です。冒頭に **「最初に見るべき判断フロー」** を置き、AI が「URL がもう分かっているか / サイト全体か / キーワードだけか」を順に分岐していけるようにしています。

ラッパー側は [skills/use-tavily/src/](https://github.com/fdshg693/ZENN/blob/main/skills/use-tavily/src/) に並んだ 7 本のスクリプト群と、共通処理を持つ [skills/use-tavily/src/tavily_common.py](https://github.com/fdshg693/ZENN/blob/main/skills/use-tavily/src/tavily_common.py) で構成しています。たとえば [skills/use-tavily/src/search_topic.py](https://github.com/fdshg693/ZENN/blob/main/skills/use-tavily/src/search_topic.py) は冒頭に次のような `DETAIL_PRESETS` を持っていて、外側からは `--detail=quick|balanced|max` の 3 択しか触らせません。

```python
DETAIL_PRESETS: dict[str, dict[str, Any]] = {
    "quick":    {"search_depth": "fast",     "max_results": 5, "chunks_per_source": 2},
    "balanced": {"search_depth": "advanced", "max_results": 5, "chunks_per_source": 3},
    "max":      {"search_depth": "advanced", "max_results": 8, "chunks_per_source": 5},
}
```

この構造の効きどころは、**「AI は目的だけ選び、ラッパーが実行品質を保証する」** に役割が分かれることです。AI に判断させる範囲が「このタスクは `quick` で十分か `max` まで上げるか」レベルに収まり、`search_depth` や `chunks_per_source` の組み合わせを毎回考えさせなくて済みます。

---

## ラッパーを書くときの設計指針

ラッパー層を作るなら、最低限この 3 点を押さえておくと運用が楽になります。

### 1. ログを残す

各実行のリクエスト/レスポンスを JSON でローカルに残しておきます。私のリポジトリでは [skills/use-tavily/src/logs/](https://github.com/fdshg693/ZENN/blob/main/skills/use-tavily/src/logs/) 配下に `extract_tavily_mcp-log.json`、`search_dynamodb_overview-log.json` のような形で実際に蓄積されています。

これがあると、

- 「先週の調査と同じ条件で打ち直したい」が再現できる
- コストが跳ねたときに「どの実行で重いオプションを使ったか」を追える
- AI が変な引数を組み立てたら、ログを根拠にスキル側を直せる

ログを残さないラッパーは、運用が AI の主観だけになるので、まず先にログ層から作るのをおすすめします。

### 2. 引数を最小限にする

SDK の細かいパラメータをそのまま CLI に流すと、ラッパーで包む意味が消えます。プロジェクト用ラッパーでは、

- 抽象化された **詳細度プリセット** (`quick` / `balanced` / `max`)
- ドメインの include / exclude のような **「効きが大きい少数の引数」**
- 出力先 `--output`

くらいに絞り、Tavily 固有のオプションは **スクリプト先頭の定数** で管理します。AI に握らせない引数は、最初から CLI に出さないのがコツです。

### 3. `--help` を整える

ラッパーは AI が初見で `--help` を見て使えないと意味がありません。

- スクリプト冒頭の docstring に、bash と PowerShell の **コピペで動く実行例** を書く
- `argparse` の各引数に一行説明を入れる
- 出力ファイルの命名規約も docstring か Skill 本体に書いておく

[skills/use-tavily/src/search_topic.py](https://github.com/fdshg693/ZENN/blob/main/skills/use-tavily/src/search_topic.py) の冒頭が、この最低限のテンプレートになっています。

---

## カスタムスキルを書くときの設計指針

ラッパーが揃ったら、それを AI に「正しく選んで」もらうための Skill 層が必要です。ここも 3 つに絞ります。

### 1. スキルは分割せず、まとめた上で「判断軸」を入れる

公式 `Tavily公式スキル` は 1 つの API につき 1 つの Skill という分け方ですが、これは AI が **「最初にどの Skill を読みに行くべきか」** を間違えやすい構造です。

私のリポジトリでは [skills/use-tavily/SKILL.md](https://github.com/fdshg693/ZENN/blob/main/skills/use-tavily/SKILL.md) に 7 本のスクリプトをすべて束ね、冒頭に「最初に見るべき判断フロー」を置いています。

```text
1. すでに対象 URL が分かっているか?
   Yes -> src/extract_url_content.py
   No  -> 2 へ

2. すでに対象サイトのルート URL が分かっているか?
   Yes -> 3 へ
   No  -> 4 へ
...
```

スキルを分けて選ばせるより、**一枚に集約して判断軸を渡す** ほうが、選定誤りは目に見えて減ります。

### 2. 引数例を必ず書く

Skill 本体には、各スクリプトに対する **「最小で動く引数列」** を bash と PowerShell の両方で載せておきます。AI は help を読みつつも、実例があるとそのまま流用するため、品質が安定します。

```bash
python ./.claude/skills/use-tavily/src/search_topic.py "Microsoft Fabric overview" \
  --include-domain learn.microsoft.com \
  --output temp/web/search_msfabric_overview.json
```

「正しい呼び方の例」がスキル内にあると、AI が引数を一から組み立てるときの自由度を絞れます。

### 3. 出力ファイルの命名規約をスキルに書き込む

出力先が散らばると、後段のスクリプトやサブエージェントが結果を探せません。私の Skill では `temp/web/{prefix}_{topic_slug}.json` という形で固定し、prefix も `search_` / `extract_` / `site_map_` などで揃えています ([skills/use-tavily/SKILL.md](https://github.com/fdshg693/ZENN/blob/main/skills/use-tavily/SKILL.md) の「出力ファイルの推奨命名規約」を参照)。

命名規約を Skill に書き込むのは地味ですが、**「次のステップで誰がこれを読むか」** を Skill が責任を持つために重要です。

---

## 使いどころ ― 1〜2 回の調べものには重い

ここまで「層を被せると安定する」と書いてきましたが、**通常のコーディング中に「ちょっと最新仕様を確認したい」程度の調べもの** であれば、正直この層は要りません。SKILL.md を読み込ませて判断フローを走らせて、ラッパーを呼んで JSON を吐かせて…という工程自体がコンテキストを食い、メリットが釣り合いません。組み込みの Web 検索や Tavily MCP を直接叩いて 1 回で済ませるほうが速いです。

この `use-tavily` スキルが本当に効くのは、**「検索 → ローカルに蓄積 → 後段で再利用する」ことが前提のワークフロー** です。具体的には次の 2 つを想定して作っています。

### 1. AI コーディングツールで調べものをして、ローカルにまとめていきたい

`temp/web/search_*.json`、`extract_*.json` のように、**調査結果が JSON ファイルとして手元に残る** こと自体が価値になるケースです。

- 同じ調査を別のセッションから読み返したい
- サブエージェントが結果を読み込んで本文に展開する
- 後で「あの調査どんな引数で打ったっけ」を `src/logs/` から復元したい

このような「調査ノートをローカルに育てていく」運用なら、スキル + ラッパー層のオーバーヘッドはすぐに回収できます。

### 2. Zenn 記事のような、複数ソースを根拠付きで束ねる執筆

複数の公式 Docs を横断して読み、根拠 URL 付きで節を組み立てる作業は、まさに「検索 → 抽出 → 蓄積 → 再利用」の繰り返しです。`use-tavily` のスクリプトと出力命名規約は、この用途に最適化されています。

(余談ですが、本記事も同じリポジトリの自作 Skill [skills/zenn/SKILL.md](https://github.com/fdshg693/ZENN/blob/main/skills/zenn/SKILL.md) を使って書いています。これは「概要提案 → `zenn/plan/*.md` → `zenn/publish/*.md`」という記事執筆フローを定型化したスキルで、調査部分は `use-tavily` を呼ぶ前提になっています。本記事の主役は `use-tavily` なので詳細は割愛しますが、Zenn 記事を継続的に書くなら、執筆スキル側もカスタムで持っておくと回りが速くなります。)

### 検索が複雑になるなら、サブエージェントとセットで使う

向いているユースケースの中でも、**「複数ドメインを横断する」「URL 候補を数十本トリアージする」「蓄積した JSON 群から事実だけ抜く」** といった工程が出てくると、メインエージェントの文脈は検索結果 JSON で一気に圧迫されます。実際、本記事の調査でも公式 Tavily の機能調査と、配布されている公式スキルの構造評価という独立した 2 つの調査を並行で走らせる必要がありました。これをメインで全部抱えていたら、本文を書く時点で文脈はほぼ調査ログで埋まっていたはずです。

このとき効くのが **サブエージェントへの分担** です。たとえば、

- **URL 候補の洗い出し** はサブエージェントに `search_topic.py` を回してもらい、最終報告だけを返してもらう
- **蓄積した `temp/web/*.json` からの事実抽出** はサブエージェントに「新規検索は禁止、JSON を読むだけ」と指示して、根拠 URL 付きの箇条書きを返してもらう
- **セクション下書き** も独立して切り出せるなら、根拠 JSON と URL を渡してサブエージェントに任せる

メインエージェントは構成判断と統合に集中し、生の JSON は基本的にサブエージェント側で消化させる、という役割分担です。

ここで重要なのは、サブエージェントへの指示で **「一般的な WEB 検索ではなく、必ず `.claude/skills/use-tavily` のスクリプトを使ってください」** と明示することです。`use-tavily` 側に「判断軸 + ラッパーのプリセット + 出力命名規約」が固められているからこそ、複数のサブエージェントが並行で動いても、出力の置き場・引数の品質・ログの形式が揃います。逆に言えば、このスキルは **「複雑な検索ほど、サブエージェントとセットで使うことを前提に設計されている」** とも言えます。

---

## まとめ

- 検索 API として Tavily を選ぶ理由は、**「AI 文脈に整形した結果を 1 コールで返す」** ことで段数が減り、ブレが小さくなるから
- ただし MCP サーバーだけでは、引数決定が毎回 AI に委ねられ、運用が再現しない
- 公式 `Tavily公式スキル` も判断フロー自体は良いが、**プロジェクト標準のロック層が無い**
- そこで 「**自作 Python ラッパー**(引数最小化・プリセット・ログ)」と 「**自作カスタムスキル**(判断軸・命名規約・実行例)」 の 2 層を上に被せると、AI に握らせる判断は最小化しつつ、品質と再現性は手元で担保できる
- ラッパーは「ログ・最小引数・help」、スキルは「分割せず判断軸を入れる・引数例・命名規約」を押さえれば、初版としては十分
- ただし **1〜2 回の単発調べものには重い**。**「検索結果をローカルに蓄積して再利用する」用途**(AI 調査ノート / 記事執筆)にこそ向く
- 検索が複雑化(多ドメイン横断・大量 URL トリアージ・JSON からの事実抽出)するなら、**サブエージェントに切り出してメインの文脈を温存** することが前提になる。判断軸と命名規約をスキルに固めておけば、複数サブエージェントの出力品質も揃う

---

## 関連記事

- [Claude Codeの設定はどこに書くべきか ― プロンプト・RULES・スキル・エージェントの使い分け](./claude-code-utilize-1)

## 参考

公式 Docs (Tavily):

- [Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)
- [Extract API](https://docs.tavily.com/documentation/api-reference/endpoint/extract)
- [Crawl API](https://docs.tavily.com/documentation/api-reference/endpoint/crawl)
- [Map API](https://docs.tavily.com/documentation/api-reference/endpoint/map)
- [Research best practices](https://docs.tavily.com/documentation/best-practices/best-practices-research)
- [MCP](https://docs.tavily.com/documentation/mcp)
- [API credits](https://docs.tavily.com/documentation/api-credits)
- [Pricing](https://www.tavily.com/pricing)

公式Tavilyスキル:

- [README.md](https://github.com/tavily-ai/skills/README.md)
- [skills/tavily-best-practices/SKILL.md](https://github.com/tavily-ai/skills/skills/tavily-best-practices/SKILL.md)
- [skills/tavily-cli/SKILL.md](https://github.com/tavily-ai/skills/skills/tavily-cli/SKILL.md)
- [skills/tavily-search/SKILL.md](https://github.com/tavily-ai/skills/skills/tavily-search/SKILL.md)
- [skills/tavily-extract/SKILL.md](https://github.com/tavily-ai/skills/skills/tavily-extract/SKILL.md)
- [skills/tavily-crawl/SKILL.md](https://github.com/tavily-ai/skills/skills/tavily-crawl/SKILL.md)
- [skills/tavily-map/SKILL.md](https://github.com/tavily-ai/skills/skills/tavily-map/SKILL.md)
- [skills/tavily-research/SKILL.md](https://github.com/tavily-ai/skills/skills/tavily-research/SKILL.md)

自作スキル:

- [skills/use-tavily/SKILL.md](https://github.com/fdshg693/ZENN/blob/main/skills/use-tavily/SKILL.md)
- [skills/use-tavily/src/search_topic.py](https://github.com/fdshg693/ZENN/blob/main/skills/use-tavily/src/search_topic.py)
- [skills/use-tavily/src/tavily_common.py](https://github.com/fdshg693/ZENN/blob/main/skills/use-tavily/src/tavily_common.py)
- [skills/use-tavily/src/logs/](https://github.com/fdshg693/ZENN/blob/main/skills/use-tavily/src/logs/)
- [skills/zenn/SKILL.md](https://github.com/fdshg693/ZENN/blob/main/skills/zenn/SKILL.md)
