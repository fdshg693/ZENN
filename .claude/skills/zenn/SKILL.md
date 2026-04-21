---
name: zenn
description: ZENN記事を作成するスキル
disable-model-invocation: false
user-invocable: true
---

以下の手順で ZENN 記事を作成してください。

重要:

- 外部情報の収集は、基本的にすべて `.claude\skills\use-tavily` 配下のスクリプトを使って行うこと。
- 一般的な WEB 検索ツールや曖昧なブラウズ指示ではなく、`use-tavily` スキルの各スクリプトを明示的に使い分けること。
- 既存知識だけで記事を書かないこと。概要提案の段階でも、調査が必要なら Tavily で最新情報を確認すること。
- どの工程でも、まず対象トピックに対して「何を知るための調査か」を明確にしてから検索・抽出を行うこと。

## 0. 事前確認

まず `.claude\skills\use-tavily\SKILL.md` を読み、このスキルを使う前提で進めてください。

利用する主なスクリプト:

- `src/search_topic.py`: キーワードから関連 URL を探す
- `src/search_extract_topic.py`: キーワードから関連 URL を探し、そのまま内容も抽出する
- `src/research_topic.py`: 調査タスクをまとめて Tavily に任せる
- `src/extract_url_content.py`: 既知の URL 群から内容を抽出する
- `src/map_site_titles.py`: 公式 Docs サイト内の URL 一覧とタイトルを把握する
- `src/map_extract_site_content.py`: サイトをマップしてから対象 URL の内容を抽出する
- `src/crawl_site_content.py`: 特定サイトを直接クロールして内容を集める

必要に応じて各スクリプトの `--help` も確認してください。

出力ファイルは基本的に `temp\{unique_name_per_article}\` 以下へ保存してください。記事ごとにトピック名のスラッグを決め、以下のように整理します。

- `temp\{unique_name_per_article}\search_{topic_slug}.json`
- `temp\{unique_name_per_article}\research_{topic_slug}.json`
- `temp\{unique_name_per_article}\extract_{topic_slug}.json`
- `temp\{unique_name_per_article}\site_map_{topic_slug}.json`
- `temp\{unique_name_per_article}\site_extract_{topic_slug}.json`

`topic_slug` は英数字と `_` を使った短い識別子に揃えてください。

## 0.a 記事ファイルの配置と frontmatter ルール

- 構成案は `zenn\plan\*.md` に置く
- 本文の下書きと公開候補は `zenn\publish\*.md` に置く
- `zenn\publish` の Markdown には Zenn frontmatter を必ず付ける

`zenn\publish` の frontmatter では最低限以下を明示してください。

- `title`: 記事タイトル
- `emoji`: 1 文字の絵文字
- `type`: 原則 `tech`
- `topics`: 3 から 5 個のタグ
- `published`: **デフォルトは `false`**

このリポジトリでは、現時点で `topics` の公式な統一一覧は見当たりません。したがって新規記事では以下を守ってください。

- 既存の `zenn\plan` / `zenn\publish` で使っているタグを優先して再利用する
- lowercase ASCII を使い、空白入りタグを作らない
- 同じテーマで表記揺れを増やさない
- ユーザーが明示的に公開指示をしない限り、`published: true` にしない

`zenn\plan` 側は publish 用 frontmatter をそのまま流用せず、`title` と `status: plan` を含む簡易 frontmatter を基本にしてください。

## 0.b ユーザーフィードバックを受けたときの更新ルール

ユーザーから追記・修正依頼が来たら、以下で `plan` / `publish` の更新順を判断します。

- **構成変更**(セクション追加・削除・並べ替え / 対象読者・問い・結論の変更) → **先に `zenn\plan`**、その後 `publish` に反映
- **軽微な本文修正**(語尾・表現調整、見出しを変えない加筆) → `zenn\publish` を直接更新
- **publish を直接編集した結果、見出し構成や主張が変わった場合** → 同じターンで `plan` も同期

必須ルール: `plan` が存在する記事では、**見出し構成またはセクションの主張が変わったら、最終的に `plan` と `publish` を一致させる**。

## 1. 記事の概要を提案する

- テーマ、対象読者、前提知識、比較対象、扱うバージョンやサービス範囲が曖昧なら、概要提案の前にユーザーへ質問して内容を明確にすること。
- 特定のツール、ライブラリ、サービス、公式機能の紹介記事であれば、概要提案の前に軽く最新情報を確認すること。
- この段階では深掘りしすぎず、概要提案に必要な情報だけを収集すること。

### 1.a 軽い事前調査の基本パターン

まずは `search_topic.py` を使い、公式 Docs や GitHub がどこにあるかを確認してください。

例:

```powershell
python .\.claude\skills\use-tavily\src\search_topic.py "Azure API Management OpenAI integration" --detail balanced --include-domain learn.microsoft.com --include-domain github.com --output temp\{unique_name_per_article}\search_apim_openai_overview.json
```

より「問い」に近いテーマで、概要までまとめてほしい場合は `research_topic.py` を使っても構いません。

例:

```powershell
python .\.claude\skills\use-tavily\src\research_topic.py "Azure API Management で Azure OpenAI を公開する設計上のポイントを整理してください。公式 Docs と Github を優先し、記事概要の判断に必要な最新論点をまとめてください。" --detail balanced --output temp\{unique_name_per_article}\research_apim_openai_overview.json
```

### 1.b 軽い事前調査で止めてよいライン

概要提案の前は、原則として以下が揃えば十分です。

- 主要な公式 URL が 2 から 5 本見つかっている
- 最新の製品名、機能名、比較対象が確認できている
- 想定読者、記事の問い、扱う範囲を説明できる
- 構成に効く大きな制約や preview 情報を把握できている

通常は以下のどちらかで止めてよいです。

- `search_topic.py` を 1 から 2 回実行する
- または `research_topic.py` を 1 回実行する

同じ問いに対して `search_topic.py` を無目的に繰り返さないでください。追加検索は、**まだ未確定な論点を 1 文で言える場合だけ** 行ってください。

### 1.c 本格調査へ進む条件

以下のどれかに当てはまる場合は、概要提案段階を切り上げて本格調査へ進んでください。

- ユーザーが概要案を承認し、記事構成や本文作成に進む場合
- 公式情報同士で食い違いがあり、追加確認が必要な場合
- SKU、制約、ライセンス、preview 条件など、本文で断定するための根拠が不足している場合
- 各セクションに対応する根拠 URL をまだ十分に揃えられていない場合

### 1.d 概要提案時の出力要件

概要提案では少なくとも以下を含めてください。

- 記事タイトル案を 2 から 4 個
- 想定読者
- 記事で答える問い
- どこまで扱い、どこから扱わないか
- 概要提案の根拠にした主要 URL または調査ファイル

## 2. 概要提案が受け入れられたら、関連情報を収集する

既存知識だけで回答しようとしないでください。必ず Tavily を使って最新情報を収集してください。

この工程は以下の順で進めます。

1. 参考にすべき公式 Docs や GitHub を確定する
2. 参照候補 URL を一覧化する
3. 記事に必要な URL の内容を抽出する
4. 不足する論点だけ追加調査する

### 2.a サブエージェントを使うか判断する

以下なら、まずメインエージェントで進めてください。

- 調査対象が 1 つの製品群、または 1 つの比較テーマに収まる
- `search` / `extract` を 1 から 3 回回せば足りる見込み
- 候補 URL が 10 本前後で、人手で十分に選別できる
- 構成提案から本文統合まで同じ文脈で進めたほうが速い

以下なら、サブエージェント利用を検討してください。

- 比較対象が複数あり、別ドメインの調査を並列化したい
- URL 候補の洗い出しだけで独立した作業になる
- セクションごとの下書き作成を分担したい
- サイトマップや大量 URL の整理を別タスクとして切り出せる

迷ったら、**最初の軽い調査はメインエージェントで行い、独立しやすい URL トリアージやセクション下書きだけサブエージェントに切り出す** 方針を基本にしてください。

### 2.b サブエージェントに URL 候補の洗い出しをさせる

サブエージェントには「WEB検索して」とだけ言わず、`.claude\skills\use-tavily` を使うように明示してください。

サブエージェント指示例:

```markdown
`.claude\skills\use-tavily\SKILL.md` を先に読んでください。

{keyword1 keyword2 ...} に関する最新の情報を収集してください。
一般的な WEB 検索ツールではなく、`.claude\skills\use-tavily\src\search_topic.py` または必要に応じて `src\research_topic.py` を使ってください。

まずは参考になる公式 Docs や GitHub を確定させてください。
そのうえで、公式 Docs を中心に参照すべき URL とそれらのタイトルを整理し、`temp\{unique_name_per_article}\search_{keyword1_keyword2_...}.md` に保存してください。(スクリプトの出力をそのまま使うのでなく、スクリプトの結果を元に不要箇所の削除等を行い、読みやすい形に整形してください)

可能なら include-domain を使って公式ドメインを優先してください。
最終報告では以下を返してください。

- 実行したコマンド
- 確定した主要ドメイン
- 重要 URL 一覧
- 出力ファイルパス
```

推奨コマンド例:

```powershell
python .\.claude\skills\use-tavily\src\search_topic.py "Azure API Management policy expressions" --detail balanced --include-domain learn.microsoft.com --include-domain github.com --output temp\{unique_name_per_article}\search_apim_policy_expressions.json
```

広めに調査して論点整理も必要なら:

```powershell
python .\.claude\skills\use-tavily\src\research_topic.py "Azure API Management policy expressions の最新情報を整理してください。公式 Docs と Github を優先し、記事執筆で先に読むべき資料を洗い出してください。" --detail balanced --output temp\{unique_name_per_article}\research_apim_policy_expressions.json
```

### 2.c URL 候補から、読むべき資料を特定する

`search_*.json` や `research_*.json` を読み、記事を書くために本文まで確認すべき URL を選定してください。

選定の基準:

- 公式 Docs である
- バージョンや公開日が新しい、または現行仕様を説明している
- 概要ページだけでなく、実装や制約が書かれている
- 記事の各セクションに直接使える

### 2.d URL 内容の取得方法を使い分ける

URL がすでに決まっている場合は `extract_url_content.py` を使ってください。

例:

```powershell
python .\.claude\skills\use-tavily\src\extract_url_content.py https://learn.microsoft.com/azure/api-management/api-management-policies https://learn.microsoft.com/azure/api-management/api-management-policy-expressions --query "APIM policy で何ができるか、制約、実務上重要な注意点" --detail balanced --output temp\{unique_name_per_article}\extract_apim_policies.json
```

キーワードから候補 URL の抽出まで含めて一気に行いたい場合は `search_extract_topic.py` を使ってください。

例:

```powershell
python .\.claude\skills\use-tavily\src\search_extract_topic.py "Azure API Management policy expressions limitations" --detail balanced --include-domain learn.microsoft.com --output temp\{unique_name_per_article}\extract_apim_policy_limitations.json
```

公式 Docs サイト全体の構造を先に見たい場合は `map_site_titles.py` を使ってください。

例:

```powershell
python .\.claude\skills\use-tavily\src\map_site_titles.py https://learn.microsoft.com/azure/api-management/ --detail balanced --select-domain learn.microsoft.com --select-path "/azure/api-management/.*" --output temp\{unique_name_per_article}\site_map_apim_docs.json
```

特定サイトから関連ページ本文をまとめて収集したい場合は `map_extract_site_content.py` を使ってください。

例:

```powershell
python .\.claude\skills\use-tavily\src\map_extract_site_content.py https://learn.microsoft.com/azure/api-management/ --query "self-hosted gateway architecture, limitations, pricing-related considerations" --detail balanced --select-domain learn.microsoft.com --select-path "/azure/api-management/.*" --output temp\{unique_name_per_article}\site_extract_apim_gateway.json
```

サイト全体を直接クロールしたい場合は `crawl_site_content.py` を使ってください。対象サイトが限定されていて、関連情報を広く拾いたい場合に向いています。

例:

```powershell
python .\.claude\skills\use-tavily\src\crawl_site_content.py https://learn.microsoft.com/azure/api-management/ --query "workspace feature, v2 tiers, current limitations" --detail balanced --select-domain learn.microsoft.com --select-path "/azure/api-management/.*" --output temp\{unique_name_per_article}\site_crawl_apim_workspace.json
```

### 2.e 追加調査の原則

- 情報が足りない論点だけ追加で検索すること
- 追加調査も `use-tavily` のスクリプトを使うこと
- 追加検索のたびに、何を確認したかったかを明示すること
- 同じ URL を何度も雑に取得せず、必要ならクエリを変えて抽出し直すこと

## 3. 記事の構成を提案する

- 2 で収集した情報をもとに、記事の構成を提案してください。
- 構成だけでなく、各セクションの概要も記述してください。
- それぞれのセクションで参考にすべき URL を示してください。
- 可能であれば、どの収集ファイルを根拠にしたかも併記してください。
- **記事は、`zenn\plan`配下のファイルとして出力してください。**
  - こうすることで、ユーザーがコメントをつけやすくなります。

構成提案には少なくとも以下を含めてください。

- 仮タイトル
- 導入で解決する問題
- セクション一覧
- 各セクションで述べる主張
- 各セクションの根拠 URL
- 必要なら不足情報と追加調査ポイント

構成提案の時点で、各セクションに対応する「読むべき URL」が不足しているなら、記事執筆に進まず先に追加調査してください。

## 4. 問題なければ記事を作成する

- 3 で提案した構成をもとに記事を作成してください。
  - `zenn\publish`配下のファイルとして出力してください。
- 収集済みの資料を根拠にして書き、根拠が薄いことを推測で埋めないでください。
- 必要に応じてサブエージェントを使い、セクション単位で下書きを作らせてください。
- サブエージェントにも、一般的な WEB 検索ではなく `use-tavily` のスクリプトを使う方針を守らせてください。

### 4.a セクション下書きをサブエージェントに任せる場合の指示例

```markdown
`.claude\skills\use-tavily\SKILL.md` を先に読んでください。

以下の Zenn 記事セクションの下書きを作成してください。

- セクション名: {section_title}
- 記事全体のテーマ: {article_theme}
- このセクションで答える問い: {section_goal}
- 主に参照するファイル: {temp\{unique_name_per_article}\...json}
- 主に参照する URL: {url1, url2, ...}

まずは指定された JSON 調査結果と URL を読み、根拠を確認してください。
根拠が不足する場合のみ、`.claude\skills\use-tavily\src\extract_url_content.py` または `src\search_extract_topic.py` を使って追加調査してください。
一般的な WEB 検索ツールは使わないでください。

出力では以下を返してください。

- セクション下書き本文
- 根拠として使った URL 一覧
- 追加調査した場合はそのコマンドと出力ファイル
- 不確実な点
```

### 4.b 蓄積した調査 JSON から事実を抽出させる指示例

本格調査で `temp\{unique_name_per_article}\*.json` が 5 本以上溜まった段階では、メインエージェントで全て読むと文脈を圧迫します。この「事実抽出のみ」を Explore / 汎用サブエージェントに切り出すと効きます(Web 検索はさせず、既存 JSON の読解だけさせるのがポイント)。

```markdown
以下の JSON 調査結果を読み、記事の各セクションに使う**具体的で検証可能な事実**を抽出してください。
新しい検索は行わないでください。既に保存された JSON を読むだけです。

- 対象ファイル: `temp\{unique_name_per_article}\{topic_slug}_*.json`(複数)
- 記事全体のテーマ: {article_theme}

各結果オブジェクトは `url` と `content` / `raw_content` を持ちます。

以下のセクションごとに、6〜15 個の事実を、各事実に**根拠 URL を inline で** 併記してください。
具体的な数値(上限、SLA、レイテンシ、RU、料金)が本文に書かれている場合は必ず引用してください。

セクション:

1. {section_1}
2. {section_2}
...

形式: セクション見出しごとに箇条書き。全体で 1800 語以下。
JSON に載っていない事実は「not in files — need separate check」と明記し、推測で埋めないでください。
```

### 4.c 記事執筆時の品質基準

- 公式資料に基づく説明を優先する
- 読者にとっての判断材料になる比較や制約を落とさない
- 「できること」だけでなく「向いていないケース」「制約」「設計上の注意点」も書く
- 概要ページだけでなく、実装ページや制約ページに当たって確認する
- 日付やプレビュー状況、SKU 依存、リージョン依存などの変動要素があれば明記する

## 5. 禁止事項

- 外部情報が必要なのに、既存知識だけで断定して書かないこと
- 「WEB検索した」とだけ書いて、何をどう調べたか曖昧にしないこと
- 一般的な WEB 検索ツールを優先しないこと
- 公式ソースがあるのに、非公式ブログだけを根拠にしないこと
- 根拠 URL が不足したまま構成や本文を書き進めないこと