---
name: skill-group
description: 様々なスキルをグループ化したスキル
disable-model-invocation: false
user-invocable: true
---

`${CLAUDE_SKILL_DIR}/skills/` 配下に配置された複数のサブスキルを確認するスキルです。

## 利用可能なサブスキル一覧

!`bash ${CLAUDE_SKILL_DIR}/list-skills.sh $ARGUMENTS`

## サブスキルの詳細を確認する手順

`bash ${CLAUDE_SKILL_DIR}/list-skills.sh`により特定のスキルの詳細を取得可能です。

### スクリプトの引数仕様

```bash
bash ${CLAUDE_SKILL_DIR}/list-skills.sh list                  # 上と同じ
bash ${CLAUDE_SKILL_DIR}/list-skills.sh <skill_name> [<skill_name>...]    # 各スキルの 名前/説明/SKILL.mdパス を出力
```

- `list` : `sub_skills/` 配下を再帰探索し、各 `SKILL.md` のフロントマター `name` を改行区切りで出力
- スキル名（複数可）: 各スキルの以下を Markdown 形式で出力
  - `## <name>`
  - `- description: <フロントマターのdescription>`
  - `- path: <SKILL.mdの絶対パス>`
- 存在しないスキル名を指定した場合: stderr に `WARNING: skill '<name>' not found ...` を出力し、他の引数の処理は継続

## サブスキルの利用

- 利用したいサブスキルが見つかった場合は直接SKILLのファイルを読み込み、内容を確認して利用することが可能
  - スキルとしての呼び出しはできないことに注意してください
