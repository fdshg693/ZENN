---
title: "Copilot CLIをスクリプトから使い倒す: 単発実行からセッション再開まで"
emoji: "🤖"
type: "tech"
topics:
  - githubcopilot
  - copilotcli
  - shellscript
  - automation
  - zenn
published: true
---

# はじめに

Copilot CLI は便利ですが、単発で `-p` 実行するだけだと、VS Code 上の Copilot Chat / Agent を使う場合より明確な優位があるとは言いにくいです。

一方で、**他のスクリプトから呼び出したい**、**複数回の実行を制御したい**、**CLI でしか触りにくい仕組みを使いたい**という場面では話が変わります。

この記事では、Copilot CLI を次の順序で活用する方法を 1 本にまとめます。

1. 最小構成で 1 回だけ実行する
2. 同じプロンプトを順番に複数回実行する
3. 同じプロンプトを並列に複数回実行する
4. セッション ID を拾って `--resume` で会話を再開する
5. Hooks を使ってセッション ID を安全寄りに取得する

ソースコード全文は載せませんが、**再現に必要なコア部分はしっかり載せる**方針です。

# この記事で扱う前提

- OS は Linux / macOS 系のシェル環境を想定します
- `copilot` コマンドがインストール済みでログイン済みであることを前提にします
- モデル名は表示名ではなく、CLI が受け付ける**内部識別名**を使います
  - 例: `Claude Haiku 4.5` ではなく `claude-haiku-4.5`

まずは、いちばん小さい形を見ます。

# まずは最小構成で 1 回だけ動かす

Copilot CLI をプログラムから扱うとき、まず押さえておきたいのが次の形です。

```bash
copilot \
  --available-tools="fake-tool" \
  --disable-builtin-mcps \
  --silent \
  --model="claude-haiku-4.5" \
  --effort="low" \
  -p "1+1"
```

この形で重要なのは以下です。

- `-p` でプロンプトをそのまま実行できる
- `--silent` を付けると、スクリプトで扱いやすい素直な出力になる
- `--disable-builtin-mcps` を付けると、ビルトイン MCP の影響を減らせる
- `--available-tools="fake-tool"` を使うと、実質的に追加ツールなしの構成にできる

ここで少しクセがあるのが `--available-tools` です。空文字だと「指定なし」と同じような扱いになりやすいため、**存在しないツール名をわざと指定して使えるツールを空に寄せる**、というテクニックを使っています。

この最小構成だけでも、外部スクリプトから「定型プロンプトを実行して結果だけ受け取る」用途には十分使えます。

# Copilot CLI を順番に複数回実行する

最初の発展形は、同じ処理を連続実行するパターンです。

たとえば以下のようなシェルスクリプトにすると、モデル名・プロンプト・回数を変えるだけで順番に実行できます。

```bash
#!/usr/bin/env bash
set -euo pipefail

MODEL="claude-haiku-4.5"
PROMPT="1+1"
LOOP_COUNT=2

COMMON_ARGS=(
  --available-tools="fake-tool"
  --disable-builtin-mcps
  --silent
  --model="$MODEL"
  --effort="low"
)

for ((i = 1; i <= LOOP_COUNT; i++)); do
  echo "=== Run ${i}/${LOOP_COUNT} ==="
  copilot "${COMMON_ARGS[@]}" -p "$PROMPT"
  echo
done
```

ポイントは 2 つです。

## 引数を配列にまとめる

```bash
COMMON_ARGS=(
  --available-tools="fake-tool"
  --disable-builtin-mcps
  --silent
  --model="$MODEL"
  --effort="low"
)
```

Bash では、CLI 引数を配列にまとめて `"${COMMON_ARGS[@]}"` で展開すると、スペースや引用符を含む値でも壊れにくくなります。Copilot CLI 側のオプションが増えても整理しやすいので、この形はかなりおすすめです。

## 各回が独立セッションになる

`copilot -p` をそのまま毎回呼ぶと、基本的には**毎回別セッション**として実行されます。

これは欠点にも利点にもなります。

- 前回の文脈を引き継ぎたい用途では不便
- 各回を完全に独立させたいバッチ用途では便利

たとえば「複数のプロンプトを汚染なしで順番に流したい」場合は、むしろこの独立性が使いやすいです。

# Copilot CLI を並列実行する

次は並列実行です。考え方は単純で、バックグラウンド実行して最後に `wait` します。

ただし、そのまま標準出力へ流すとログが混ざって読みにくくなります。そこで、**いったん一時ファイルへ保存してから順番に表示する**のが実用的です。

コア部分は次のとおりです。

```bash
#!/usr/bin/env bash
set -euo pipefail

MODEL="claude-haiku-4.5"
PROMPT="1+1"
LOOP_COUNT=2

COMMON_ARGS=(
  --available-tools="fake-tool"
  --disable-builtin-mcps
  --silent
  --model="$MODEL"
  --effort="low"
)

OUTPUT_DIR="$(mktemp -d)"
trap 'rm -rf "$OUTPUT_DIR"' EXIT

run_one() {
  local run_number="$1"
  copilot "${COMMON_ARGS[@]}" -p "$PROMPT" > "$OUTPUT_DIR/${run_number}.txt"
}

for ((i = 1; i <= LOOP_COUNT; i++)); do
  run_one "$i" &
done

wait

for ((i = 1; i <= LOOP_COUNT; i++)); do
  echo "=== Run ${i}/${LOOP_COUNT} ==="
  cat "$OUTPUT_DIR/${i}.txt"
  echo
done
```

## 並列実行の勘どころ

このやり方の良いところは、**Copilot の各実行が完全に独立**していることです。

- ある実行のコンテキストが別の実行へ混ざらない
- 単純な問い合わせをまとめて投げる用途に向いている
- UI 側のサブエージェント制御に依存せず、シェルスクリプトとして明示的に制御できる

一方で、後で説明する「セッション再開」を絡めると事情が変わります。**セッション ID をあとから拾う必要がある処理は、完全並列と相性が悪い**です。

ここ、わりと重要です。並列は万能ではなく、独立ジョブ向けです。

# `--resume` でセッションを再開する

ここからが本題です。

Copilot CLI には、過去の会話を再開するためのオプションがあります。

- `--continue`: 直前のセッションを再開
- `--resume=<SESSION-ID>`: 指定したセッションを再開

これを使うと、1 回目の実行で「秘密の文字列を覚えて」と伝え、2 回目の実行で「さっきの秘密を返して」と確認するようなフローを組めます。

ただし問題があります。

> `copilot -p` の結果から、その場でセッション ID だけを簡単に取得する専用オプションが見当たりにくい

なので、**1 回目の実行で作られたセッション ID を外部から拾う**必要があります。

この記事では、以下の 2 パターンを紹介します。

1. `~/.copilot/session-state/` を見て新しくできたセッションを特定する
2. Hooks の `SessionStart` イベントで `session_id` を保存する

# 方法1: `session-state/` を直接参照する

公式ドキュメントでは、`GitHub Copilot CLI configuration directory` の `session-state/` の説明で、セッション履歴がここに保存され、`--resume` / `--continue` に利用されることが案内されています。

つまり、1 回目の実行の前後でディレクトリ一覧を比較すれば、「新しく作られたセッション ID」をかなり高い確率で特定できます。

コア部分は次のようになります。

```bash
#!/usr/bin/env bash
set -euo pipefail

MODEL="claude-haiku-4.5"
COPILOT_CONFIG_DIR="${COPILOT_CONFIG_DIR:-${COPILOT_HOME:-$HOME/.copilot}}"
SESSION_STATE_DIR="${COPILOT_CONFIG_DIR}/session-state"
SECRET="${SECRET:-session-secret-$(date +%s)}"

FIRST_PROMPT="次の秘密の文字列を次の実行まで覚えてください。返答は『記憶しました』だけにしてください。秘密の文字列: ${SECRET}"
SECOND_PROMPT="このセッションで直前に伝えた秘密の文字列だけを1行で正確に返してください。前置き、説明、引用符は禁止です。"

COMMON_ARGS=(
  --available-tools="fake-tool"
  --disable-builtin-mcps
  --silent
  --model="$MODEL"
  --effort="low"
)

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

list_session_ids() {
  find "$SESSION_STATE_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort
}

list_session_ids > "$TEMP_DIR/before.txt"
first_output="$(copilot "${COMMON_ARGS[@]}" -p "$FIRST_PROMPT")"
printf '%s\n' "$first_output"

list_session_ids > "$TEMP_DIR/after.txt"
new_session_ids="$(comm -13 "$TEMP_DIR/before.txt" "$TEMP_DIR/after.txt" || true)"
SESSION_ID="$(printf '%s\n' "$new_session_ids" | tail -n 1)"

second_output="$(copilot "${COMMON_ARGS[@]}" --resume="$SESSION_ID" -p "$SECOND_PROMPT")"
printf '%s\n' "$second_output"
```

## この方法のメリットと注意点

メリット:

- Hook を使わずに実現できる
- 仕組みが単純で、シェルだけで完結しやすい

注意点:

- `session-state/` は CLI の内部管理ディレクトリなので、ややハック寄り
- 並列に複数セッションを起動すると、どのディレクトリがどの実行に対応するか崩れやすい
- 1 回目の実行直後に新規ディレクトリが複数あると判定が難しくなる

つまり、**再現はしやすいが、きれいな方法とは言いにくい**です。

# Hooks の `SessionStart` でセッション ID を保存する

より素直なのは、Copilot CLI の Hooks を使う方法です。

公式ドキュメントによると、リポジトリの `.github/hooks/*.json` に Hook 定義を置くと、CLI が自動で読み込みます。さらに `SessionStart` イベントを PascalCase で定義すると、VS Code 互換の snake_case ペイロードが渡され、`session_id` をそのまま取り出せます。

これを使うと、1 回目の実行開始時点でセッション ID をフック側に保存できるので、あとで `--resume` にそのまま渡せます。

## Hook 定義

たとえば `.github/hooks/session-start-capture.json` は次のように書けます。

```json
{
  "version": 1,
  "hooks": {
    "SessionStart": [
      {
        "type": "command",
        "bash": "./hooks/capture-session-id.sh",
        "cwd": ".",
        "timeoutSec": 10
      }
    ]
  }
}
```

ポイント:

- `.github/hooks/*.json` に置く
- イベント名を `SessionStart` にする
- `cwd` でフックスクリプトを置いたディレクトリに寄せる
- 実処理は外部スクリプトへ逃がす

## Hook スクリプト

Hook から渡される JSON を読み、`session_id` をファイルへ保存する部分は次のように書けます。

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${SCRIPT_DIR}/../tmp"
OUTPUT_FILE="${SESSION_ID_OUTPUT_FILE:-${OUTPUT_DIR}/session-id-from-hook.txt}"

mkdir -p "$OUTPUT_DIR"
payload="$(cat)"

session_id="$({
  printf '%s' "$payload" | python3 -c 'import json,sys; data=json.load(sys.stdin); print(data.get("session_id") or data.get("sessionId") or "")'
} 2>/dev/null)"

printf '%s\n' "$session_id" > "$OUTPUT_FILE"
```

`session_id` だけ使うなら `jq` ではなく Python 標準ライブラリでも十分です。追加依存を減らせるので、サンプルとしても扱いやすいです。

## `--resume` で再開する本体スクリプト

本体側は、1 回目の実行後に Hook が保存したセッション ID を読み、それを 2 回目に渡すだけです。

```bash
#!/usr/bin/env bash
set -euo pipefail

HOOK_STATE_FILE="tmp/session-id-from-hook.txt"
MODEL="claude-haiku-4.5"
SECRET="${SECRET:-session-secret-$(date +%s)}"

FIRST_PROMPT="次の秘密の文字列を次の実行まで覚えてください。返答は『記憶しました』だけにしてください。秘密の文字列: ${SECRET}"
SECOND_PROMPT="このセッションで直前に伝えた秘密の文字列だけを1行で正確に返してください。前置き、説明、引用符は禁止です。"

COMMON_ARGS=(
  --available-tools="fake-tool"
  --disable-builtin-mcps
  --silent
  --model="$MODEL"
  --effort="low"
)

rm -f "$HOOK_STATE_FILE"

first_output="$(copilot "${COMMON_ARGS[@]}" -p "$FIRST_PROMPT")"
printf '%s\n' "$first_output"

SESSION_ID="$(<"$HOOK_STATE_FILE")"
second_output="$(copilot "${COMMON_ARGS[@]}" --resume="$SESSION_ID" -p "$SECOND_PROMPT")"
printf '%s\n' "$second_output"
```

この方法なら、1 回目の開始時点でセッション ID が確定して保存されるので、`session-state/` を直接なめるより意図が明確です。

# セッション再開でハマりやすいポイント

実際に組んでみると、次のあたりでつまずきやすいです。

## 1. 並列実行と混ぜない

セッション ID を捕捉する処理は、「今始まった実行がどれか」を特定する必要があります。

そのため、**同じ Copilot 設定ディレクトリに対して並列に複数の `copilot -p` を流す**と、対応関係が崩れやすいです。

- 並列実行は「独立ジョブ」向け
- セッション再開は「依存関係つきジョブ」向け

と考えると整理しやすいです。

## 2. Hook は配置場所を間違えると動かない

Copilot CLI の Hook は `.github/hooks/*.json` から自動ロードされます。ファイル名は自由ですが、場所がズレると実行されません。

また、フックスクリプト側も以下を確認してください。

- 実行権限があるか
- shebang が正しいか
- JSON が壊れていないか
- `timeoutSec` が短すぎないか

## 3. `SessionStart` の payload 形式を意識する

イベント名を `SessionStart` のように PascalCase で定義すると、`session_id` のような snake_case の payload が渡されます。

ここを `sessionStart` と混同すると、取り出すキー名を間違えて「あれ、取れない……」となりがちです。CLI あるあるです。ちょっとだけ罠です。

# どの方法を選ぶべきか

結論としては、次の使い分けがわかりやすいです。

## とにかく最小構成で投げたい

`-p` + `--silent` + ツール制限の最小構成。

用途:

- 他のスクリプトから 1 回だけ実行
- CI の補助的な問い合わせ
- 純粋にテキスト応答だけほしいケース

## 同じ仕事を大量に投げたい

順次実行 / 並列実行。

用途:

- 定型プロンプトのバッチ処理
- 独立した問い合わせのまとめ打ち
- 出力をあとから収集して整形したい場合

## 前回の文脈を引き継ぎたい

`--resume`。

用途:

- 1 回目で前提を与えて 2 回目以降で利用したい
- セッション単位の状態をまたいでワークフローを組みたい
- Hooks を使って自動化したい

この中では、**実運用に耐えやすいのは Hooks を使う方法**です。

# ここまでの内容を実際に試す手順

最小構成で再現するなら、以下の 4 ファイルを用意すれば十分です。

- `run-sequential.sh`
- `run-parallel.sh`
- `run-resume-using-session-state.sh`
- `run-resume-using-hooks.sh`

Hooks を使う方法では、追加で以下も必要です。

- `.github/hooks/session-start-capture.json`
- `hooks/capture-session-id.sh`

## 順次実行・並列実行を試す

それぞれのスクリプトで、先頭の以下を用途に応じて調整します。

- `MODEL`
- `PROMPT`
- `LOOP_COUNT`

## セッション再開を試す

`session-state/` を直接見る方法では、以下を調整できるようにしておくと使いやすいです。

- `MODEL`
- `SECRET`
- `COPILOT_CONFIG_DIR`

Hooks を使う方法では、少なくとも以下を調整できるようにしておくと再利用しやすいです。

- `MODEL`
- `SECRET`
- セッション ID の保存先ファイル

つまり、再現の最小単位は「本体スクリプト」だけではなく、**Hook 定義 + Hook 実装 + 再開本体**の 3 点セットです。

# 参考: 公式ドキュメントで押さえておきたい箇所

記事で使った内容は、主に以下の公式ドキュメントに対応しています。

- Copilot CLI command reference
  - `--available-tools`
  - `--disable-builtin-mcps`
  - `-p`
  - `--continue`
  - `--resume`
  - Hooks reference
  - https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-command-reference
- Copilot CLI configuration directory
  - `~/.copilot/session-state/` の役割
  - `COPILOT_HOME` / `--config-dir`
  - https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-config-dir-reference
- Using hooks with GitHub Copilot CLI
  - `.github/hooks/*.json` の配置
  - Hook の基本構成
  - トラブルシュート
  - https://docs.github.com/en/enterprise-cloud@latest/copilot/how-tos/copilot-cli/customize-copilot/use-hooks

# まとめ

Copilot CLI は、単発で雑に呼ぶだけだと UI より強いとは限りません。

ただし、次のように**スクリプトで制御する前提**に立つと、一気に面白くなります。

- 最小構成で 1 回だけ問い合わせる
- 連続実行・並列実行でバッチ化する
- セッション ID を拾って `--resume` する
- Hooks でセッション開始イベントを拾って自動化する

特に「前の実行の結果や文脈を次に渡したい」ケースでは、CLI ならではの組み立て方ができます。

もしこれをさらに進めるなら、次はこんな方向が面白いです。

- Hook でログ収集や監査を入れる
- 実行結果に対して自動で lint / test を回す
- セッション単位のワークフローを複数段に分けて組む

Copilot CLI、単発質問機として終わらせるには少し惜しいです。ちゃんと配線すると、いい感じに働きます。
