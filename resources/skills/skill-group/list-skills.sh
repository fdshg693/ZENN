#!/usr/bin/env bash
# skill-group のスキル一覧/詳細を出力するスクリプト
#
# 使い方:
#   list-skills.sh                        # スキル名一覧を改行区切りで出力
#   list-skills.sh list                   # 同上
#   list-skills.sh <name> [<name>...]     # 指定スキルの 名前/説明/SKILL.mdパス を出力
#                                         # 存在しない名前は stderr に警告

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="${SCRIPT_DIR}/skills"

# SKILL.md からフロントマター部分のみを抽出して yq に渡す
get_field() {
  local file="$1" field="$2"
  sed -n '/^---$/,/^---$/p' "$file" | sed '1d;$d' | yq eval ".${field}" -
}

find_skill_files() {
  find "${SKILLS_DIR}" -type f -name 'SKILL.md' 2>/dev/null | sort
}

cmd_list() {
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    get_field "$f" name
  done < <(find_skill_files)
}

cmd_show() {
  local target="$1"
  local found=0
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    local name
    name=$(get_field "$f" name)
    if [ "$name" = "$target" ]; then
      local desc
      desc=$(get_field "$f" description)
      echo "## ${name}"
      echo "- description: ${desc}"
      echo "- path: ${f}"
      echo
      found=1
      break
    fi
  done < <(find_skill_files)
  if [ "$found" -eq 0 ]; then
    echo "WARNING: skill '${target}' not found under ${SKILLS_DIR}" >&2
  fi
}

if [ $# -eq 0 ] || { [ $# -eq 1 ] && [ "$1" = "list" ]; }; then
  cmd_list
else
  for arg in "$@"; do
    cmd_show "$arg"
  done
fi
