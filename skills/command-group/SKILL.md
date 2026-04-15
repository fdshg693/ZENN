---
name: command-group
description: 指定したサブスキルの内容をまとめて読み込んで提供するユーザー呼び出し専用スキル
disable-model-invocation: true
user-invocable: true
---

ユーザーが `/command-group skill1 skill2 ...` の形で呼び出し、指定されたサブスキルの内容を
一度にAIのコンテキストへ読み込ませるためのスキルです。AI側からの自動呼び出しは想定していません。

サブスキルは `${CLAUDE_SKILL_DIR}/sub_commands/` 配下に配置された `SKILL.md` のフロントマター
`name` によって識別されます。

## 指定されたサブスキルの内容

!`bash ${CLAUDE_SKILL_DIR}/get-skills.sh $ARGUMENTS`

## 利用手順

1. 上のセクションで出力された各サブスキルの内容を確認する
2. 各サブスキルに記載されている指示や参照ファイルのパスに従って作業を実施する
   - パスは `path:` として併記されているため、同階層のファイル参照はそのディレクトリを基準に解決する
3. 該当スキルが見つからなかった場合は stderr に警告が出力されるため、ユーザーに名前を確認する

## スクリプトの引数仕様

```bash
bash ${CLAUDE_SKILL_DIR}/get-skills.sh <skill_name> [<skill_name>...]
```

- 各スキルの以下を Markdown 形式で出力
  - `## スキル: <name>`
  - `- path: <SKILL.mdの絶対パス>`
  - `SKILL.md` の全内容（コードブロックで囲む）
- 存在しないスキル名を指定した場合: stderr に `WARNING: skill '<name>' not found ...` を出力し、他の引数の処理は継続

## `skill-group` との違い

- `skill-group`: AIがスキルを探索して利用する。一覧→概要→内容と段階的に読み込む。
- `command-group`: ユーザーが必要なスキルを正確に指定し、1回の呼び出しで複数スキルの内容をまとめて提供する。AIからの自動呼び出しはしない。
