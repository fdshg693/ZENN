#!/usr/bin/env bash
# command-group のサブスキル内容を結合出力するスクリプト
#
# 使い方:
#   get-skills.sh <name> [<name>...]     # 指定スキルのSKILL.md内容をパス付きで連結出力
#                                         # 存在しない名前は stderr に警告してスキップ

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="${SCRIPT_DIR}/sub_commands"

get_field() {
  local file="$1" field="$2"
  sed -n '/^---$/,/^---$/p' "$file" | sed '1d;$d' | yq eval ".${field}" -
}

find_skill_files() {
  find "${SKILLS_DIR}" -type f -name 'SKILL.md' 2>/dev/null | sort
}

emit_skill() {
  local target="$1"
  local found=0
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    local name
    name=$(get_field "$f" name)
    if [ "$name" = "$target" ]; then
      echo "## スキル: ${name}"
      echo
      echo "- path: ${f}"
      echo
      echo "### SKILL.md 内容"
      echo
      echo '```markdown'
      cat "$f"
      echo '```'
      echo
      found=1
      break
    fi
  done < <(find_skill_files)
  if [ "$found" -eq 0 ]; then
    echo "WARNING: skill '${target}' not found under ${SKILLS_DIR}" >&2
  fi
}

if [ $# -eq 0 ]; then
  echo "usage: $(basename "$0") <skill_name> [<skill_name>...]" >&2
  exit 1
fi

for arg in "$@"; do
  emit_skill "$arg"
done
