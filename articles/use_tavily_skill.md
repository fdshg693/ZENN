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

:::message
本記事では **公式仕様として確認できる事実** と **筆者の運用経験に基づく設計判断** が混在します。前者は Tavily の公式 Docs / MCP ドキュメント / 公式 Skills リポジトリで裏取り可能なもの、後者は「再現性・ログ・命名規約・コスト統制を重視する運用」という筆者の前提から導かれた選択です。読むときは `事実` と `設計判断` を分けて受け取ってください(章ごとにどちら寄りかを明示します)。
:::

---

## なぜ Tavily か ― 汎用検索や AI 組み込み検索では足りない理由

Tavily は「LLM が読むためのコンテキスト整形まで含めて 1 コールで返してくれる」ように設計された検索 API です。汎用検索 + 自前スクレイピング + 自前要約のパイプラインに比べて段数が少なく、結果として AI に渡る情報のブレが小さくなります。

公式 API リファレンスから、特に AI 調査で効くパラメータを抜粋します。

### Search API: LLM 文脈を意識した「事前チャンク化」(事実寄り)

- `search_depth` が 4 段階 (`ultra-fast` / `fast` / `basic` / `advanced`)。`advanced` は精度重視で 2 credit、それ以外は 1 credit
- `chunks_per_source` で「URL ごとに最大 500 文字 × N 個のチャンク」を返せる。ただし公式 Docs 上では、説明文では `advanced` / `fast` いずれも複数チャンクを返す旨の記述があり、パラメータ定義では `chunks_per_source` は `advanced` で利用可能と書かれている箇所もあり、**記述に揺れがある**。実装時はレスポンスの形を実機で確認してから前提を組むのが安全です
- `include_domains` / `exclude_domains` がそれぞれ最大 300 / 150 ドメインまで指定可能
- `topic` (`general` / `news` / `finance`)、`time_range`、`start_date` / `end_date` で時系列・ジャンルを絞れる
- `include_answer` で LLM 生成の直接回答、`include_raw_content` で本文も同じ呼び出しに同梱できる

参考: https://docs.tavily.com/documentation/api-reference/endpoint/search

### Extract / Crawl / Map / Research(事実寄り)

- **Extract** は単なるスクレイピングと違い、「取得 + クリーニング + チャンク化 + クエリによる再ランク」を 1 コールで提供。失敗 URL は課金されない (https://docs.tavily.com/documentation/api-reference/endpoint/extract)
- **Map** は GET 系のサイトグラフ走査で、自然言語 `instructions`(例: 「Find all pages about the Python SDK」)、正規表現の `select_paths` / `select_domains` で絞り込める (https://docs.tavily.com/documentation/api-reference/endpoint/map)
- **Crawl** は map + extract を統合して、サイト配下の本文をまとめて回収する (https://docs.tavily.com/documentation/api-reference/endpoint/crawl)
- **Research** はエージェンティック調査 API で、`model=mini|pro|auto`、`output_schema`(JSON Schema)、`citation_format` (`numbered` / `apa` / `mla` / `chicago`) まで持つ。**Research API は非同期タスクとしてキューされる設計**で、応答時間は入力の広さやモデル選択に依存する。公式 README や best practices ページには「30〜120 秒程度で出典付きレポート」という表現があるが、これは **体感値に近い目安であって SLA ではない**。本番で呼ぶときは非同期前提のコードパス(ポーリング or コールバック)を組むのが安全 (https://docs.tavily.com/documentation/best-practices/best-practices-research)

### AI コードツール組み込み検索との違い

Claude Code や各種 AI エディタ組み込みの「Web 検索ツール」は便利ですが、

- 検索深さやチャンクサイズなどの細かいパラメータをこちらから握れない
- ドメインフィルタの上限や挙動が不透明で、再現性のある「公式 Docs だけを読ませる」運用がしづらい
- ツールのバージョンアップで挙動が静かに変わる可能性がある

という弱点があります。記事執筆や設計判断の根拠を集めるような「再現性が品質を左右する用途」では、引数を明示できる Tavily 側に倒したほうが結果が安定します。

> 料金体系 (Free 1,000 credits / 月、Pay-as-you-go ほか) と各 API の credit 単価は変動するので、実際の数字は公式 https://docs.tavily.com/documentation/api-credits と https://www.tavily.com/pricing を都度確認してください。

---

## MCP サーバー単体で、どこまでカバーできるか(事実 + 設計判断)

「Tavily の MCP サーバーを Claude Code に繋げばいいのでは?」という発想は当然出ます。実際、**個人の軽い調査やチームによっては、MCP + `DEFAULT_PARAMETERS` + プロンプト規約で十分** というケースもあります。ここでは、MCP がどこまで担い、どこから別の層が欲しくなるかを仕様ベースで整理します。

### MCP の仕様(ここは事実)

公式 MCP のドキュメント (https://docs.tavily.com/documentation/mcp) から:

- リクエストごとの引数は **クライアント側 LLM がプロンプトから決定** する。「いつ `advanced` を使うか」「どのドメインを優先するか」はその場の AI に委ねられる
- Tavily 側は、この問題に対する逃し弁として `DEFAULT_PARAMETERS` という JSON を、リモート版はリクエストヘッダ、ローカル版は環境変数で受けられる仕組みを用意している。裏を返せば、**それを設定しない限り、引数のデフォルトはサーバ側組み込み値か AI の判断任せ**
- MCP は接続層として「ツールを生やす」ところまでを担当し、**運用ポリシー層(命名規約・ログ・コスト上限など)は含まない**

### どこで足りなくなるかは「規模と要求次第」(ここは設計判断)

MCP だけで回るかは、筆者の経験ではおおむね次のラインで分かれます。

- **MCP だけで十分になりやすいケース**: 単発調べもの中心、チーム共有が不要、ログ再現は諦められる、`DEFAULT_PARAMETERS` にチームの好みを詰めれば AI の引数迷走も許容範囲
- **MCP だけでは不足しやすいケース**: 調査結果をローカルに蓄積して後段で再利用する、複数人や複数セッションで命名を揃えたい、コストが跳ねた原因を後から追いたい、サブエージェントに検索を任せたい

本記事はこの後者、つまり **「大規模 / 継続運用では MCP の上に層を足したくなる」** という前提で話を進めます。「MCP では常に足りない」という主張ではない点だけ、はっきり切り分けておきます。

---

## 公式 `Tavily公式スキル` の物足りなさ(事実 + 設計判断)

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

## 選択肢の比較 ― どこに「ロック層」を置くか(設計判断)

「プロジェクト標準のデフォルトと判断軸をロックする層」をどこに置くかには、現実的に 3 択あります。以下は筆者が実際に検討した比較で、あくまで **筆者の運用(調査結果を JSON で蓄積して記事執筆や再利用に回す)を前提にした判断** です。別の運用なら結論は変わり得ます。

| 案 | 要旨 | 向くケース | つらくなるケース |
|----|------|-----------|-----------------|
| **A. MCP + `DEFAULT_PARAMETERS` だけ足す** | サーバ接続設定に JSON でデフォルトを積むだけ。追加コード 0 | 引数のブレだけ抑えたい / ログや命名規約は不要 / チーム共有不要 | JSON 保存先・命名・実行ログ・コスト上限などポリシー層を入れたくなった瞬間に限界 |
| **B. 公式 skills を fork して薄く包む** | `tavily-*` 系スキルを自リポジトリに取り込み、命名規約やデフォルトだけ足す | CLI (`tvly`) 運用に合っている / 公式更新に追従したい | スクリプトを SDK 直叩きで書きたい / 出力を Python で後処理したい / スキル分割の AI 選定誤りは残る |
| **C. 自前 Python ラッパー + カスタムスキル(本記事)** | SDK を自前スクリプトで包み、命名規約・ログ・プリセットをコードに落とす | 調査結果をローカル JSON に蓄積して再利用 / サブエージェントに検索を任せたい / コスト統制を強く効かせたい | 単発調べもの中心の運用ではオーバースペック / 公式更新に追従する手間が出る |

A→B→C は「追加コード量」も「プロジェクト固有の統制力」も増えていく並びです。筆者が C を採っているのは、Zenn 記事執筆のように「検索 → JSON 蓄積 → 後段で再利用」を繰り返す運用で、A と B では出力の置き場や実行ログの形式が揃わなかったからです。**同じ痛みが無い人は、A か B で止めるほうが総コストは安い** と思います。

---

## 解決策(C 案の実装)― 「Python ラッパー」+「カスタムスキル」の 2 層

前節の C 案、つまり **「Tavily を、プロジェクト標準のデフォルトと判断軸でロックする層」** を自前で 2 層に分けて持つ構成です。私のリポジトリでは次のようになっています。

```text
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ カスタムスキル   ← AI が読む「目的→スクリプト」の判断軸                                       │  
│(https://github.com/fdshg693/ZENN/blob/main/skills/use-tavily)                             │ 
├───────────────────────────────────────────────────────────────────────────────────────────┤
│ 自作 Python ラッパー  ← 引数の最小化、プリセット、ログ                                        │
│(https://github.com/fdshg693/ZENN/blob/main/skills/use-tavily/src/*.py + tavily_common.py) │  
├───────────────────────────────────────────────────────────────────────────────────────────┤
│ Tavily Python SDK                                                                         │
└───────────────────────────────────────────────────────────────────────────────────────────┘
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

## どれを採るべきか ― 読者向けの分岐

ここまでの整理をもとに、**どの層で止めるのが合っているか** を読者の状況別にまとめます。これは筆者の経験に基づく設計判断なので、自分の運用に読み替えてください。

### MCP + `DEFAULT_PARAMETERS` で十分な人

- 調査は単発中心で、結果を JSON に残す必要はあまりない
- チームで命名規約を揃える必要がない / 1 人運用
- 引数ブレだけ抑えられれば、ログやコスト追跡はひとまず要らない
- まず最小構成で動かしたい

→ Tavily MCP を接続し、`DEFAULT_PARAMETERS` に `search_depth`、`include_domains`、`chunks_per_source` の既定値を詰めるだけで、かなりの部分は改善します。

### 公式 skills を fork して薄く包むのが合う人

- CLI (`tvly`) 中心の運用で、Python スクリプトは書きたくない
- 公式スキルの段階的ワークフロー(search → extract → map → crawl → research)に違和感がない
- 公式の更新に追従する前提で、自分の規約は小さく上乗せしたい

→ 公式 skills を fork し、命名規約(`temp/web/...` のような)とデフォルト値だけ追加で足す形が、学習コストと統制のバランスが良いです。

### 自前 Python ラッパー + カスタムスキル(本記事の C 案)が効く人

- **検索結果を JSON でローカルに蓄積して、後段で再利用する** ワークフローがある(調査ノート / 記事執筆 / 社内レポート)
- **サブエージェントに検索を任せたい** ユースケースがあり、出力の置き場と形式を揃えたい
- コストが跳ねた原因を実行ログから追える状態にしたい
- スキルの分割選定誤り(AI が `search` で済むところに `research` を使う等)を減らしたい

→ 本記事の構成(Python ラッパー + 判断軸入りの一枚 Skill)が、費用対効果に見合います。

逆に、**この条件に当てはまらないのに C 案を採ると、SKILL.md を読み込ませる時点でコンテキストを食うだけで見返りが薄い** ので、A か B で止めたほうが良いです。

---

## まとめ

- 検索 API として Tavily を選ぶ理由は、**「AI 文脈に整形した結果を 1 コールで返す」** ことで段数が減り、ブレが小さくなるから(事実寄り)
- MCP サーバーは接続層としてはよくできていて、`DEFAULT_PARAMETERS` と組み合わせれば **小規模運用なら十分足りる**。ただし大規模 / 継続運用では、命名規約・ログ・コスト統制といった運用ポリシー層が不足しがち(事実 + 設計判断)
- 公式 `Tavily公式スキル` の判断フロー自体は良いが、**プロジェクト標準のロック層は Skill 側では持てない**(事実 + 設計判断)
- 運用側のロック層の置き方には、**A: MCP + `DEFAULT_PARAMETERS` / B: 公式 skills を fork / C: 自前 Python ラッパー + カスタムスキル** の 3 案がある。本記事は C を推すが、A や B で止めるべきケースも明確にある(設計判断)
- C を採る場合、ラッパーは「ログ・最小引数・help」、スキルは「分割せず判断軸を入れる・引数例・命名規約」を押さえれば、初版としては十分
- C が効くのは **「検索結果をローカルに蓄積して再利用する」用途**(AI 調査ノート / 記事執筆)、特に **サブエージェントに検索を任せる** ケース。単発調べもの中心なら A で十分
- `chunks_per_source` の適用条件や Research API の応答時間など、**Tavily 公式 Docs には表現の揺れがある部分もある**。本記事の数値や条件は、一次情報で検証してから実装するのが安全

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
