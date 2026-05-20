# ZENN記事作成スキル

Tavily で集めた根拠を元に、Zenn 記事を **「概要提案 → 構成案(plan)→ 本文(publish)」** の 3 段階で安定して書き上げるための Claude Code 用スキルです。AI が既存知識だけで断定することを禁じ、必ず `use-tavily` スキルで最新情報を確認させた上で、根拠 URL 付きの記事に組み立てます。

## 前提条件

- `use-tavily` スキルが存在し、Tavily API キーがセットされていること
  - 詳細は [.claude/skills/use-tavily/README.md](../use-tavily/README.md) を参照
- リポジトリ直下に `zenn/` ディレクトリ、その配下に `plan/` と `publish/` を作成可能なこと(初回実行時に作られる想定)
- 調査結果の置き場として `temp/web/` ディレクトリが利用可能なこと

## このスキルの目的

- AI に Zenn 記事を書かせるとき、「既存知識で書ききってしまう」「根拠 URL が曖昧」「構成と本文がズレる」といった事故を防ぐ
- 記事執筆を **概要提案 → 構成 plan → 本文 publish** の 3 工程に分解し、各工程でユーザーがレビューできるチェックポイントを置く
- Web 調査は曖昧なブラウズ指示や AI 組み込み検索ではなく、`use-tavily` のスクリプトを **明示的に使い分けさせる**
- 構成案と本文の同期ルール(構成変更が入ったら plan → publish の順で更新)を固定する

## このスキルの特徴

- **3 段階フロー**: 概要提案(対話)→ `zenn/plan/*.md`(構成と根拠)→ `zenn/publish/*.md`(本文)
- **調査スキルとの分業**: Tavily への呼び出し方は `use-tavily` 側に任せ、本スキルは「いつどのスクリプトを呼ぶか」と「成果物の形」だけ規定
- **frontmatter ルール固定**: `published: false` をデフォルトにし、ユーザーの明示指示なしに公開状態にしない
- **plan / publish の同期ルール**: 見出しやセクション主張が変わったら、必ず両方を一致させる
- **サブエージェント活用ガイド**: URL 候補の洗い出し、JSON 群からの事実抽出、セクション下書きをサブエージェントに切り出すパターンを SKILL.md 内に持つ

## クイックスタート

Claude Code 上で次のように呼び出します。

```
/zenn Azure API Management で Azure OpenAI を公開する設計上のポイント
```

これで以下が走ります。

1. `use-tavily` で軽い事前調査(主要な公式 URL を把握)
2. タイトル候補・想定読者・問い・扱う範囲を含む **概要案** を提示
3. ユーザーが OK を出したら、構成詳細を `zenn/plan/{topic_slug}.md` に書き出す
4. plan を承認すると、本文を `zenn/publish/{topic_slug}.md` に書き出す(`published: false`)

公開可能だと判断したら、ユーザー側で `published: true` に書き換えてください(スキルは自動で公開状態に切り替えません)。

## ファイル / 出力構成

```text
.claude/skills/zenn/
├── README.md   ← このファイル
└── SKILL.md    ← AI に読ませるスキル本体(3 段階フローの手順 / frontmatter ルール / サブエージェント指示例)

リポジトリ直下:
├── temp/web/                  ← use-tavily が出す調査 JSON
└── zenn/
    ├── plan/{topic_slug}.md     ← 構成案(レビュー用、簡易 frontmatter + status: plan)
    └── publish/{topic_slug}.md  ← 本文(Zenn frontmatter 完備、デフォルト published: false)
```

## カスタマイズ箇所

| 変えたいこと | 編集場所 |
|--------------|---------|
| 概要提案で必須にする項目(タイトル候補数、想定読者の粒度など) | `SKILL.md` の「1.d 概要提案時の出力要件」 |
| frontmatter のデフォルト値・必須項目(emoji / type / topics 規約) | `SKILL.md` の「0.a 記事ファイルの配置と frontmatter ルール」 |
| 軽い事前調査と本格調査の切り替え基準 | `SKILL.md` の「1.b 軽い事前調査で止めてよいライン」「1.c 本格調査へ進む条件」 |
| サブエージェントへの指示テンプレ(URL 洗い出し / 事実抽出 / セクション下書き) | `SKILL.md` の「2.b」「4.a」「4.b」 |
| plan と publish の同期ルール | `SKILL.md` の「0.b ユーザーフィードバックを受けたときの更新ルール」 |
| タグ(`topics`)の運用ルール | `SKILL.md` の frontmatter ルール内 |

タグの統一一覧をリポジトリで持ちたくなったら、`SKILL.md` の topics ルールを「正の一覧」に置き換えてください。

## よくあるユースケース

- 公式 Docs を横断して比較する技術解説記事
- 自作スキル / 自作ツールの紹介記事(本記事自体がこの用途で書かれた例)
- 設計判断の根拠を整理した「設計ノート」的な記事

「単発の感想記事」や「外部情報がほぼ要らないチュートリアル」には重いので、向きません。検索結果をローカルに蓄積して根拠付きで束ねる必要がある記事に使ってください。

## 詳細

実際の調査手順、スクリプト選択基準、サブエージェント指示テンプレ、plan / publish の同期ルールは [SKILL.md](SKILL.md) を参照してください。Tavily スクリプト側の使い方は [.claude/skills/use-tavily/README.md](../use-tavily/README.md) と [.claude/skills/use-tavily/SKILL.md](../use-tavily/SKILL.md) にあります。
