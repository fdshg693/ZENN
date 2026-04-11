---
title: "Copilot CLI をスクリプトで活用する: Hooks による継続実行と YAML ワークフロー化"
emoji: "🧩"
type: "tech"
topics:
  - githubcopilot
  - copilotcli
  - shellscript
  - python
  - automation
published: true
---

# はじめに

Copilot CLI をスクリプトから使うとき、単発の [`-p` 実行](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-command-reference#command-line-options) や単純な [`--resume`](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-command-reference#command-line-options) だけでもそれなりに便利です。

ただ、もう一歩踏み込んで次のようなことをやりたくなると、話が変わってきます。

- 対話セッションが終わったあとに、自動で 1 回だけ follow-up を実行したい
- 並列実行と逐次実行を 1 つの定義にまとめたい
- あるタスクは独立で走らせつつ、別のタスク列は同じ会話履歴を引き継ぎたい
- 毎回シェルスクリプトを増やすのではなく、ワークフローとして管理したい

このレベルまで来ると、単なる「CLI の呼び出し例」ではなく、**Copilot CLI のセッション管理や [Hook](https://docs.github.com/en/enterprise-cloud@latest/copilot/how-tos/copilot-cli/customize-copilot/use-hooks) の仕組みを前提にしたアーキテクチャ設計**が必要になります。

この記事では、以下の二つの発展的な構成を取り上げます。

1. **`sessionEnd` Hook を起点に、会話終了後に 1 回だけ `--resume` する構成**
2. **YAML でワークフローを定義し、Python で Copilot CLI をオーケストレーションする構成**

ここでは、コード全文の再掲による再現性の追求は目的とせず、代わりに以下を重点的に説明します。

- アーキテクチャ全体の考え方
- どの GitHub Copilot CLI の機能・仕組みを使っているか
- なぜそう分割しているのか
- どこがハマりどころか

# 関連記事: まず前編で基本形を押さえる

基礎から順番に追いたい場合は、先に[前編「Copilot CLIをスクリプトから使い倒す: 単発実行からセッション再開まで」](./zenn-copilot-cli-lv1-lv2)を読むのがおすすめです。

前編では、[`-p`](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-command-reference#command-line-options) による単発実行、順次実行・並列実行、[`--resume`](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-command-reference#command-line-options) / [`--continue`](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-command-reference#command-line-options)、そして Hooks を使った `session_id` 取得までを扱っています。この記事はその続きとして、**セッション終了を起点にした継続実行**と**YAML によるワークフロー化**に話を進めます。

# 自動化における主な課題

Copilot CLI を用いた自動化で注意すべき点は、主に次の 2 点に集約されます。

## 1. セッションは「ただの標準出力」ではない

単発の `copilot -p` なら、プロンプトを投げて応答を受け取るだけです。

しかし、会話履歴を引き継ぎたい場合は、**セッション ID** と **セッション状態** を意識しないといけません。

- GitHub のドキュメントでも、Copilot CLI は設定ディレクトリ配下の [`session-state/`](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-config-dir-reference#automatically-managed-files) にセッション履歴を保存し、それが [`--resume`](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-command-reference#command-line-options) や [`--continue`](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-command-reference#command-line-options) に利用されると説明されています。

つまり、発展的な構成では「1 回実行して終わり」ではなく、

- どのセッションを再開するのか
- そのセッションはまだ有効な状態か
- 並列実行で他のセッションと競合しないか

を考える必要があります。

## 2. Hook は便利だが、イベント駆動ゆえの制約がある

Copilot CLI には [Hooks](https://docs.github.com/en/enterprise-cloud@latest/copilot/how-tos/copilot-cli/customize-copilot/use-hooks) があり、[`.github/hooks/*.json`](https://docs.github.com/en/enterprise-cloud@latest/copilot/how-tos/copilot-cli/customize-copilot/use-hooks#creating-a-hook-in-a-repository-on-github) から自動ロードされます。

Hook は `sessionStart`、`sessionEnd`、`preToolUse` などのイベントで外部コマンドを実行できます。ここがとても強力です。

ただし、イベント駆動なので「何でも好きなタイミングでプロンプトを差し込める」わけではありません。

特に重要なのが [**prompt hook は `sessionStart` でしか使えない**](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-command-reference#prompt-hooks) ことです。しかも initial prompt より前に投入されます。

この制約があるので、

- セッション終了後に follow-up を 1 回だけ走らせたい
- 対話が終わったあとで、自動レビューや振り返りをさせたい

という要件は、素直な prompt hook だけでは組めません。

ここから先は、**Hook をトリガーとして使い、実際の `copilot --resume` 実行は別コンポーネントに逃がす**発想が必要になります。

# 発展ユースケース1: `sessionEnd` Hook で会話終了後に 1 回だけ継続させる

まずは 1 つ目の構成です。

やりたいことはシンプルです。

> ユーザーが対話セッションを終えたあと、その会話履歴を保ったまま、決まった follow-up prompt を 1 回だけ自動実行したい

たとえば、こんな用途です。

- 直前の作業内容を 3 点で振り返らせる
- 作業後の README 更新案だけ考えさせる
- 自己レビューだけさせる
- 次に確認すべき項目だけ列挙させる

## なぜ prompt hook では足りないのか

Copilot CLI の [Hook リファレンス](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-command-reference#hooks-reference) では、prompt hook は [`sessionStart`](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-command-reference#sessionstart--sessionstart) のみ対応で、initial prompt より前に自動投入されます。

つまり、prompt hook は「開始時の自動プロンプト」には向いていますが、**終了後の追撃**には向いていません。

そこで構成を次のように変えます。

1. `sessionStart` で `session_id` と `source` を記録する
2. `sessionEnd` で follow-up 実行を**予約**する
3. 少し待ってから別プロセスで `copilot --resume=<SESSION_ID> -p "..."` を実行する

ここで重要なのは、`sessionEnd` の Hook の中でそのまま `copilot --resume` を叩かないことです。

理由は単純で、**元のセッションがまだ終了途中かもしれないから**です。

同じセッションを終了イベントの真っ最中に再開しようとすると、気持ちとしてはやる気満々でも、実際には race condition の匂いがします。CLI にも人間にも、終了処理の余韻は大事です。

## 全体アーキテクチャ

全体の流れを図にすると、だいたいこうです。

```text
ユーザー
  ↓
Copilot CLI 対話セッション
  ├─ sessionStart Hook
  │    └─ session_id / source を保存
  │
  └─ sessionEnd Hook
       └─ follow-up を予約
             ↓
         遅延ディスパッチャ
             └─ copilot --resume=<SESSION_ID> -p "follow-up prompt"
```

この構成で役割を分けると、各部品の責務は次のようになります。

- **設定部品**
  - モデル、待機秒数、follow-up prompt を持つ
- **SessionStart ハンドラ**
  - `session_id` と `source` を記録する
- **SessionEnd ハンドラ**
  - そのセッションが follow-up 対象か判定する
  - 直接再開せず、遅延実行を予約する
- **ディスパッチャ**
  - 数秒待ってから `--resume` を実行する
- **ログ / トレース部品**
  - 何が起きたか追跡しやすくする

## 使っている Copilot CLI の機能・仕組み

この構成で効いているのは、主に次の仕組みです。

- [`.github/hooks/*.json` からの Hook 自動ロード](https://docs.github.com/en/enterprise-cloud@latest/copilot/how-tos/copilot-cli/customize-copilot/use-hooks#creating-a-hook-in-a-repository-on-github)
- [`sessionStart` / `sessionEnd` イベント](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-command-reference#hooks-reference)
- Hook payload に含まれる `session_id` / `sessionId`
- Hook payload に含まれる `source`
  - `new`, `resume`, `startup`
- Hook payload に含まれる `reason`
  - `complete`, `user_exit`, `error` など
- `--resume=<SESSION_ID>`
- `-p` による programmatic 実行
- `--silent` によるスクリプト向け出力

Hook payload については、イベント名を camelCase にするか PascalCase にするかで、入力 JSON のフィールド名が変わる点も重要です。

- `sessionStart` と書くと camelCase payload
- `SessionStart` と書くと VS Code 互換の snake_case payload

実装側で `sessionId` と `session_id` の両方を吸収しておくと、ここはだいぶ平和になります。

## Hook 定義はどう分けるか

Hook 定義自体はシンプルです。要点だけ抜くと、次のような形になります。

```json
{
  "version": 1,
  "hooks": {
    "sessionStart": [
      {
        "type": "command",
        "bash": "<session-start handler>",
        "cwd": ".",
        "timeoutSec": 10
      }
    ],
    "sessionEnd": [
      {
        "type": "command",
        "bash": "<session-end scheduler>",
        "cwd": ".",
        "timeoutSec": 10
      }
    ]
  }
}
```

大事なのは、JSON の書き方そのものより、**責務を 1 ファイルに詰め込まないこと**です。

`sessionEnd` 側で payload 解析、ループ検知、待機、再開実行、ログ保存まで全部やると、すぐに読めなくなります。

## 重要点 1: `sessionStart` で `source` を記録する

`sessionStart` payload には、そのセッションが

- 新規開始なのか
- `resume` なのか
- 起動時の自動開始なのか

が入っています。

この `source` が、無限ループを防ぐためのかなり重要な材料になります。

たとえば、最初の対話セッションが終わって `sessionEnd` Hook が発火し、follow-up を `--resume` で実行したとします。

すると、その follow-up 側でも再び `sessionStart` / `sessionEnd` が発火します。

ここで何も判定しないと、

- sessionEnd で resume
- その resume セッションの sessionEnd でまた resume
- さらにその sessionEnd でまた resume

……という無限ループが発生する可能性があります。

そこで、`sessionStart` で記録した `source=resume` を後段が見て、**resume 由来のセッションでは follow-up を予約しない**ようにします。

これは Copilot CLI の Hook ペイロード設計をそのままループ検知に利用している事例です。

## 重要点 2: `sessionEnd` では即再開せず、予約のみ行う

`sessionEnd` でやることは、なるべく短くしておきます。

判断材料はせいぜいこのくらいです。

- `session_id` が取れたか
- 終了理由 `reason` が対象か
  - たとえば `complete` / `user_exit` だけ許可
- そのセッションの `source` が `resume` ではないか
- 同じ `session_id` で既に予約済みではないか
- follow-up prompt が空ではないか

擬似コードで書くと、イメージはこうです。

```bash
if [[ "$source" == "resume" ]]; then
  exit 0
fi

case "$reason" in
  complete|user_exit) ;;
  *) exit 0 ;;
esac

if ! create_once_file "$session_id"; then
  exit 0
fi

schedule_delayed_resume "$session_id"
```

ここでの設計意図は 2 つあります。

### 終了 Hook を軽く保つ

GitHub の Hook ドキュメントでも、Hook は同期的に動作し、長い処理は体感を悪くするとされています。

なので、重い処理を `sessionEnd` Hook に直接載せるより、**予約だけしてすぐ返す**方が筋が良いです。

### セッション終了と再開の race を避ける

`sessionEnd` イベントの瞬間は、まだ終了処理の文脈の中です。

この瞬間に即 `--resume` すると、

- 元セッションが完全に閉じていない
- session state の更新と衝突する
- Hook 連鎖の順序が読みづらくなる

といった問題が起きやすくなります。

そのため、少し待ってから別プロセスで再開する構成にしています。

## 重要点 3: ディスパッチャは「遅延 + `--resume`」に専念させる

実際に再開するディスパッチャは、役割をかなり絞れます。

```bash
sleep "$LV3_AUTO_RESUME_DELAY_SEC"

copilot \
  --model="$LV3_AUTO_RESUME_MODEL" \
  --resume="$SESSION_ID" \
  --silent \
  -p "$LV3_AUTO_RESUME_PROMPT" \
  > "$OUTPUT_FILE"
```

これだけでも、設計としては十分意味があります。

- **何秒待つか**
- **どのモデルを使うか**
- **どんな follow-up prompt を投げるか**
- **結果をどこへ保存するか**

を設定化しておけば、

- 振り返り専用
- ドキュメント提案専用
- 自己レビュー専用

のような派生が作りやすくなります。

## 重要点 4: ロックファイルで再実行を防止する

`source=resume` 判定だけでもかなり効きますが、実運用では**同じセッションに対して複数回予約しないこと**も大切です。

そのため、`session_id` ごとに once ファイルや lock ファイルを置いておくのが手堅いです。

考え方は単純で、

- `sessionEnd` で `SESSION_ID.scheduled` のようなファイルを原子的に作る
- 既に存在していれば、そのセッションは予約済みとみなしてスキップする

というだけです。

これで、

- 同じ Hook が複数回走った
- 終了イベントの扱いが思ったより複雑だった
- デバッグ中に再度フックが呼ばれた

といった場合でも被害を減らせます。

## この方式の良いところ

この構成の良いところは、**「セッション終了」というイベントを、そのまま自動化の起点に変えられる**ことです。

たとえば、こんな用途に向いています。

- すべての作業後に必ず簡単な振り返りを残す
- 作業後のドキュメント差分候補だけ別 prompt で考えさせる
- 終了直後に「次の一手」だけを書かせる
- セッション単位の軽い監査ログを残す

つまり、「人間が作業する本編」と「その後始末・整理」を分けられるわけです。

## この方式の限界

もちろん、きれいごとだけではありません。

- `sessionEnd` 直後に再開できる保証が厳密にあるわけではないので、遅延実行というワークアラウンドが必要
- Hook とバックグラウンド実行を跨ぐため、ログ設計がないと追跡しづらい
- `source` や `reason` に依存した分岐は、仕様変更時に再確認が必要
- あまり攻めたことをすると、Hook 連鎖が理解しづらくなる

なので、この構成は「魔法の完全解」ではなく、**Hook の制約を理解したうえでの妥当な設計**と考えるのがよいです。

# 発展ユースケース2: YAML で Copilot CLI ワークフローを定義する

次は 2 つ目の構成です。

こちらのテーマは、**複数タスクのオーケストレーション**です。

やりたいことは、たとえばこんな感じです。

- バグ調査タスクは並列で 2 本走らせる
- 実装案のドラフト → 自己レビュー → 次のドキュメント項目整理、は同じ会話履歴で順に進める
- その両方を 1 つの定義で管理したい

シェルスクリプトでも不可能ではありませんが、ワークフローが増えるほど、スクリプトの条件分岐と配列操作が顔を出してきます。

そこで発想を変えて、

- **ワークフローは YAML で定義する**
- **実行制御は Python に寄せる**

という構成にします。

## 全体像

この構成では、Python 側のランナーが YAML を読んで、各タスクを Copilot CLI に変換して実行します。

```text
workflow.yml
  ↓
Python ランナー
  ├─ タスク定義を検証
  ├─ depends_on を解決
  ├─ 並列実行可能なバッチを作る
  ├─ session_namespace ごとに config-dir を分離
  ├─ copilot を subprocess で実行
  └─ stdout / stderr / session_id / summary を保存
```

ここで大事なのは、**Copilot CLI 自体にワークフロー機能を期待するのではなく、CLI を 1 つの実行エンジンとして扱う**ことです。

CLI の外側に薄いオーケストレーション層を置くことで、

- 並列制御
- 依存関係制御
- resume 制御
- ログ収集

を自分で定義できるようになります。

## YAML で何を定義するのか

定義ファイルでは、主に次の 2 層を持たせます。

- `defaults`
  - 全タスクの既定設定
- `tasks`
  - 実際のタスク配列

コア部分だけ抜くと、イメージはこんな感じです。

```yaml
{
  "defaults": {
    "model": "claude-haiku-4.5",
    "effort": "low",
    "max_parallel": 2,
    "silent": true,
    "no_custom_instructions": true,
    "disable_builtin_mcps": true,
    "add_dirs": ["."]
  },
  "tasks": [
    {
      "id": "investigate_bug",
      "session_namespace": "workflow-a",
      "prompt": "調査観点を3点に整理してください。"
    },
    {
      "id": "draft_solution",
      "session_namespace": "workflow-b",
      "prompt": "実装案を4点に整理してください。"
    },
    {
      "id": "review_solution",
      "depends_on": ["draft_solution"],
      "resume_from": "draft_solution",
      "prompt": "直前の提案を自己レビューしてください。"
    }
  ]
}
```

ここでのポイントは、タスクごとに **`depends_on`** と **`resume_from`** を持てることです。

- `depends_on`
  - 実行順序の依存関係
- `resume_from`
  - どのタスクのセッションを引き継ぐか

`resume_from` は「順番に実行する」だけではなく、**前タスクの会話履歴を引き継ぐ**ことを意味します。

この区別があると、

- ただ順番を守りたいタスク
- 本当に同じ会話を継続したいタスク

を分けて表現できます。

## 使っている Copilot CLI の機能・仕組み

この構成で効いている Copilot CLI の要素は次の通りです。

- `-p` によるプログラム実行
- `--resume=<SESSION_ID>`
- `--config-dir=<PATH>`
- `--model`
- `--effort`
- `--silent`
- `--no-custom-instructions`
- `--disable-builtin-mcps`
- `--add-dir`
- 設定ディレクトリ配下の `session-state/`

特に重要なのは [**`--config-dir`**](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-config-dir-reference#changing-the-location-of-the-configuration-directory) です。

このオプションは、Copilot CLI の設定・セッション状態の保存先を切り替えられます。GitHub のドキュメントでも、`--config-dir` は `COPILOT_HOME` より優先され、[`session-state/`](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-config-dir-reference#automatically-managed-files) などを含む一式の保存先を丸ごと切り替えると説明されています。

これが、並列実行と `--resume` を両立させる上での主要な要素になります。

## なぜ `session_namespace` と `--config-dir` 分離が必要なのか

ここが後者の最も重要な点です。

もし複数タスクを並列実行し、それぞれが新しいセッションを作る場合、同じ `~/.copilot/session-state/` を共有していると、**どのタスクがどの session ID を作ったのか判定しづらくなります。**

たとえば、

- タスク A が新規セッションを開始
- タスク B もほぼ同時に新規セッションを開始
- どちらも `session-state/` に新しいディレクトリを作る

という状況になると、「この差分は A のものか B のものか」が怪しくなります。

そこで、タスク列ごとに `session_namespace` を持たせ、**namespace ごとに別の `--config-dir` を使う**ようにします。

イメージはこうです。

```text
.tmp/copilot-home/
  workflow-a/
    session-state/
      <session-id-for-A>
  workflow-b/
    session-state/
      <session-id-for-B>
```

これなら、各 namespace の `session-state/` を見ればよく、並列実行中でも session ID の推測がかなり安全になります。

つまり LV3_2 は、`session-state/` を直接見るハックをやめたわけではありません。むしろ逆で、**見るなら競合しないように設計ごと分離した**わけです。

この発想は実務的に有用です。

## ランナーはどう動くのか

Python 側のランナーの流れは、概ね次の通りです。

1. YAML を読み込む
2. `defaults` と `tasks` をパースする
3. `depends_on` の循環や未知タスク参照を検証する
4. `resume_from` があるタスクは、依存関係にも自動追加する
5. `resume_from` したタスクと `session_namespace` が食い違っていないか検証する
6. 実行可能なタスク群をバッチとしてまとめる
7. 同一 namespace のタスクが同じバッチに入らないよう検証する
8. バッチ内を並列実行する
9. 新規セッションなら `session-state/` 差分から session ID を取る
10. `resume_from` タスクなら保存済み session ID を `--resume` に渡す
11. 実行結果をファイルへ保存する

文章で書くと少し大げさですが、実際の役割はかなり明快です。

- **定義を解釈する**
- **危ない組み合わせを弾く**
- **Copilot CLI 実行に落とす**
- **結果を回収する**

だけです。

## 実行コマンドはどう組み立てるか

各タスクは、最終的には Copilot CLI の引数列に変換されます。

概念的にはこんな感じです。

```python
command = [
    "copilot",
    f"--config-dir={config_dir}",
    f"--model={model}",
    "--silent",
    "--no-custom-instructions",
    "--disable-builtin-mcps",
    *add_dir_args,
]

if resume_id:
    command.append(f"--resume={resume_id}")

command.extend(["-p", prompt])
```

ここで重要なのは、ランナーが Copilot CLI を再実装しているわけではないことです。

**CLI の責務はあくまで 1 タスクの実行**であり、ランナーはその外側で順序と保存先を決めているだけです。

この分離は、将来的にかなり効きます。

- CLI のオプションが増えても、ランナー側は引数生成ロジックを少し増やせばよい
- タスク定義の DSL を大きく変えずにすむ
- ワークフロー定義と実行エンジンを別々に改善できる

## session ID はどう拾うのか

新規タスクの session ID は、実行前後の `session-state/` を比較して推測します。

概念だけ抜くと、こういう動きです。

```python
before = list_session_ids(session_state_dir)
completed = subprocess.run(command, ...)
after = list_session_ids(session_state_dir)
session_id = detect_new_session_id(before, after)
```

GitHub の設定ディレクトリのドキュメントでは、`session-state/` は session ID ごとのサブディレクトリを持ち、`--resume` / `--continue` のための履歴を保存するとされています。

なので、namespace を分離したうえで見るなら、この方法はかなり実用的です。

もちろん完全無欠ではありません。

- CLI の内部保存形式が将来変わる可能性はある
- 異常終了時の扱いは工夫がいる
- 同じ namespace を並列化すると再び危うい

ですが、そこはランナー側で **同一 namespace の同時実行を禁止する**ことで、かなり整理できます。

## 並列実行の安全弁としての namespace 検証

この設計が上手いのは、同じ `session_namespace` を共有するタスクが同じバッチで並列実行されそうになったら、**実行前にエラーにする**ことです。

これは初めから「危ない組み合わせを最初から作らせない」方針です。

たとえば、

- `draft_solution`
- `review_solution` (`resume_from=draft_solution`)

が同時に走るような定義は、そもそも意味的におかしいです。

また、

- 同じ会話線を共有する 2 タスクを parallel にしてしまう

のも危険です。

このあたりをランナーが先に弾いてくれると、YAML を触る人間が「暗黙の前提」を全部覚えていなくても済みます。

## 成果物をファイルとして残す

オーケストレーション層を自前で持つ価値は、出力の整理にもあります。

各タスクで次のような成果物を残しておくと、あとから見返しやすくなります。このリポジトリのサンプルでも、`LV3_2/.tmp/runs/<RUN_ID>/...` と `LV3_2/.tmp/copilot-home/<namespace>/...` にまとまって保存されるようにしています。

- `stdout.txt`
  - Copilot の標準出力
- `stderr.txt`
  - エラー出力
- `metadata.json`
  - `session_id`, 実行コマンド, 実行時間, namespace など
- `summary.json`
  - ワークフロー全体の成否一覧

これは単なるログ保存ではなく、**Copilot CLI を処理系として扱うための監査面**でもあります。

タスクが増えてくると、あとから欲しくなるのはだいたい次の情報です。

- どの prompt がどの session に紐づいたか
- どのタスクがどの順番で失敗したか
- resume 先は本当に想定どおりだったか
- 同じワークフローを再定義するとき、前回どう動いたか

その意味でも、ランナーはただ `subprocess.run()` を呼ぶだけではなく、**状態と結果を構造化して保存する係**として価値があります。

## 本物の Copilot を使わずに制御だけ試せるのも大きい

この種の仕組みは、オーケストレーションが合っているかを見たいだけなのに、毎回本物の Copilot に問い合わせるとコストも時間もかかります。

そこで、Copilot CLI の代わりに振る舞う簡易スタブを差し込めるようにしておくと便利です。

たとえば、

- `--config-dir` を受け取る
- `--resume` があればその session ID を使う
- なければ `session-state/` に擬似 session ディレクトリを作る
- `prompt` をそのまま出力する

程度の偽物を用意すれば、

- 並列制御
- session ID 受け渡し
- namespace 分離
- 成果物保存

だけを単体で確かめられます。

この「本物の推論系」と「外側の制御系」を分離してテストできるとさらに安心です。

# 2 つの構成はどう使い分けるべきか

ここまでの 2 つは、似ているようで役割が違います。

## `sessionEnd` Hook 構成が向くケース

- 対話セッションを起点に自動 follow-up したい
- 作業後の振り返りや自己レビューを必ず走らせたい
- ユーザー操作に寄り添ったイベント駆動の自動化をしたい

つまり、**会話のライフサイクルをトリガーにしたい**ときです。

## YAML ワークフロー構成が向くケース

- 複数タスクの順序・並列度・resume 関係を明示したい
- 同じようなワークフローを定義差し替えで再利用したい
- 実行ログや成果物を構造化して残したい

つまり、**ジョブオーケストレーションとして Copilot CLI を扱いたい**ときです。

## 両者を組み合わせるとどうなるか

組み合わせ自体は可能です。

- Hook は「いつ起動するか」を決める
- YAML ランナーは「何をどの順序で走らせるか」を決める

という分担にできます。

ただし、最初から全部盛りにすると、一気に複雑になります。

個人的には、次の順序が扱いやすいです。

1. まずは YAML ランナー単体で、並列・逐次・resume の整理をする
2. そのあと必要なら Hook で自動起動を足す

いきなり Hook からワークフロー全体を起動すると、トリガー条件、再入防止、ログの見通しが全部いっぺんに難しくなります。

# 設計上の注意点

最後に、特に気をつけたい点をまとめます。

## 1. 同じセッション線を並列化しない

`--resume` を使う系統は、同じ会話履歴を共有しています。

ここを並列化すると、

- どの順で履歴が積まれるのか
- どの応答が次の前提になるのか

が崩れやすくなります。

同じ会話を継続するタスク列は、基本的に直列と考えた方が安全です。

## 2. Hook の責務は小さく保つ

Hook の中に本処理を全部入れたくなるのですが、やりすぎるとデバッグ性が落ちます。

- Hook はトリガーと軽い判定
- 重い処理は外部スクリプトや別プロセス

の分離はかなり大事です。

## 3. `--config-dir` 分離はかなり効く

並列実行と session ID 推定を両立したいなら、保存先を分けるのがいちばん効きます。

これはやや地味な点ですが、後者の中核となる要素です。

## 4. 追跡できるようにしておく

自動化は、動いているときより、**動かなかったとき**に困ります。

なので、

- 何の Hook が発火したか
- どの session ID を拾ったか
- どの理由でスキップしたか
- どのコマンドを実行したか

を最低限追えるようにしておくと、あとで自分を助けてくれます。

ログを残しておくと、後で問題の調査や再現に役立ちます。

# 参考情報

- [GitHub Copilot CLI command reference](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-command-reference)
  - [`-p`](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-command-reference#command-line-options)、[`--resume`](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-command-reference#command-line-options)、[`--config-dir`](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-command-reference#command-line-options)、[Hooks reference](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-command-reference#hooks-reference)
- [GitHub Copilot CLI configuration directory](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-config-dir-reference)
  - [`session-state/`](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-config-dir-reference#automatically-managed-files) の役割と、[`COPILOT_HOME` / `--config-dir`](https://docs.github.com/en/enterprise-cloud@latest/copilot/reference/copilot-cli-reference/cli-config-dir-reference#changing-the-location-of-the-configuration-directory) の優先順位
- [Using hooks with GitHub Copilot CLI](https://docs.github.com/en/enterprise-cloud@latest/copilot/how-tos/copilot-cli/customize-copilot/use-hooks)
  - [`.github/hooks/*.json` の配置](https://docs.github.com/en/enterprise-cloud@latest/copilot/how-tos/copilot-cli/customize-copilot/use-hooks#creating-a-hook-in-a-repository-on-github) やトラブルシュート
- [Agent hooks in Visual Studio Code (Preview)](https://code.visualstudio.com/docs/copilot/customization/hooks)
  - VS Code 側の Hook 形式や、Copilot CLI 形式との違いを見比べたいときの補助資料

# まとめ

今回の記事において、Copilot CLI の使い方は「単発で prompt を投げるツール」から、かなり印象が変わります。

今回見たのは次の 2 つです。

- **`sessionEnd` Hook を起点に、会話終了後に 1 回だけ `--resume` する構成**
- **YAML でタスクを宣言し、Python で並列・逐次・resume を制御する構成**

前者では、Copilot CLI の Hook イベントと `source` / `reason` を活用して、**セッションのライフサイクルを自動化トリガーに変える**ことができます。

後者では、`--config-dir` と `session-state/` を前提に設計することで、**並列実行とセッション継続を破綻しにくく組み合わせる**ことができます。

つまり今回の記事で重要な点は、**Copilot CLI の内部状態とイベントをどう扱うかを設計すること**です。

Copilot CLI は、単発実行でももちろん使えます。

でも本当に面白くなるのは、

- セッションをどう継続するか
- どのタイミングで何を自動実行するか
- 複数タスクをどう安全に束ねるか

を自分で配線し始めたあたりからです。

このあたりまで来ると、CLI は「単発で prompt を投げるツール」よりも、**会話状態を持つ実行エンジン**として見た方がしっくりきます。
