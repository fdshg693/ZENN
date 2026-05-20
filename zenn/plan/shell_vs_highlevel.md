---
title: "シェルスクリプトをいつ捨てるか — Google と GitLab の閾値で考える「高級言語へのスイッチライン」"
status: plan
---

## 想定読者と前提

- 普段は Python / Go / TypeScript などで仕事しており、CI、Dockerfile、entrypoint、Makefile、本番デプロイ手順で時々 bash や PowerShell に触れる **中級以上のエンジニア**
- 「この処理、shell でいいの? Python に書き換えたほうがいいの?」をチームで議論したことがある人
- 「PowerShell も入れたほうがいい?」と聞かれて即答できないアプリケーション/プラットフォーム開発者
- 前提: `set -e`、`if [ ... ]`、パイプとリダイレクト、`$(...)` を読み書きできる。bash と POSIX sh の違いを完全に説明できる必要はない。

ジュニア向けの「シェルとは何か」「コマンドの紹介」は扱わない。

## この記事が答える問い

1. シェルスクリプトが**本当に得意な領域**はどこか (なぜ Python が普及した今も生き残っているか)
2. **いつ高級言語に切り替えるべきか** — Google / GitLab / 実務者の合意する具体的な閾値
3. `set -euo pipefail` だけでは守れない領域がどこにあるか
4. PowerShell は bash とどう違い、bash と同じ閾値で判断していいのか
5. 中級以上の各職種が、どこまでシェルを書けて読めるべきか

## 扱う範囲 / 扱わない範囲

- 扱う: Bash / POSIX sh / PowerShell 7 の「使いどころ判断」、業界のコンセンサス、衛生ツール、職種別の到達ライン
- 扱わない: 個別構文のチュートリアル、awk/sed の詳細、fish/zsh の対話シェル機能、cmd.exe、Windows PowerShell 5.1 系の互換維持

## 章立てと各セクションの主張

### 1. はじめに — なぜ「いつ shell を捨てるか」が現代でも重要なのか

主張: Python/Go/Node が当たり前になった今でも、CI step / Dockerfile RUN / systemd ExecStart / cron / installer / entrypoint といった「他言語を呼び出す側」の場所には shell が残り続ける。読めないと困るが、全部 shell で書くと事故る。業界トップは明確にラインを引いている。

根拠:
- Google Shell Style Guide「Shell should only be used for small utilities or simple wrapper scripts」(`extract_google_shellguide.json`)
- GitLab 「Avoid using shell scripts ... This is a must-read section」(`extract_gitlab_guide.json`)

### 2. 一度だけ宣言する「シェル衛生」の最低ライン

主張: これ以降のコード例ではいちいち書かないが、最低限以下は前提とする。

- `#!/usr/bin/env bash` または `#!/bin/bash` + `set -euo pipefail`
- ShellCheck を CI で走らせる
- フォーマットは shfmt (`-i 2 -ci`)
- ただし `set -euo pipefail` は「お守り」であって**完全な防御ではない**(後段で扱う)
- GitHub Actions の `run:` は `bash` シェルで `set -eo pipefail` を**自動付与する**が `-u` は付かない

根拠:
- Google Shell Style Guide のヘッダ規約
- GitLab Shell scripting standards の `shellcheck` / `shfmt` CI ジョブ例
- emmer.dev "Defensive Shell Scripting with Shell Options" — GitHub Actions のデフォルトと Cloudflare 2021 年事故の言及
- Greg's Wiki BashFAQ/105 — set -e の本質的な穴

### 3. シェルが本当に得意な領域 (狭いが確実)

主張: shell が他言語より明確に勝つのは以下の場面だけ。

- 既存コマンド (`grep` / `awk` / `curl` / `tar` / `git` / `kubectl` など) を**接着剤として並べる**処理
- パイプとリダイレクトで「テキストストリームを継ぎ足す」処理
- **起動が薄い**、ランタイム依存ゼロ
- 「Python 自体をインストールする」「リポジトリを clone する前の bootstrap」など、**実行環境がまだ整っていない段階**
- 既に shell が前提とされている場所: Dockerfile の `RUN`、CI の inline step、systemd の `ExecStart`、Git hooks

根拠: Stack Overflow / Super User の議論、GitLab guide の「依存サイズ制約がある場合のみ shell」、Google guide の用途記述。

### 4. 切り替えるべき閾値 — 業界が合意するライン

主張: 以下のいずれかが当てはまったら、その時点で**書き始めずに別言語に逃がす**。

| シグナル | 出典 |
|---|---|
| 100 行を超えそう / 超えた | Google Shell Style Guide |
| `${PIPESTATUS}` を入れる以外の用途で**配列**が要る | Google Shell Style Guide |
| 性能が要件に入る | Google Shell Style Guide |
| 複雑な条件分岐、多段の curl/JSON 加工 | Tim O'Hearn、sap1ens |
| 構造化データ (JSON / YAML / XML) を**真面目に**扱う | コミュニティ合意 |
| ユニットテストが必要 | GitLab guide |
| 外部 API を多数叩く / リトライ・冪等性が要る | Tim O'Hearn |

GitLab はさらに踏み込んで「依存サイズ制約がない限り、そもそも shell を避けろ」と言う。デフォルトを Python/Ruby に置く前提で、shell は「逃げ場」と位置づけるのが現代的。

### 5. `set -euo pipefail` だけでは守れない領域

主張: お守りに過信しないこと。具体例ベースで罠を 3 つ示す。

- **`set -e` は条件文の中では無効化される**: `&&` / `||` / `if` / `while` / `until` / `!` の中、パイプの最後以外。bash man と FAQ105 の明示。
- **`local var=$(cmd)` は cmd の失敗を握りつぶす**: `local` の戻り値 0 が `var` の代入ステータスをマスクする (FAQ105 の代表的な落とし穴)。
- **コマンド置換のサブシェルでは `-e` が伝播しない**: bash 4.4 以降の `shopt -s inherit_errexit` を有効にしない限り。
- 一次資料: Cloudflare 2021 年 12 月のインシデントは `set -o pipefail` があれば防げたとされている (emmer.dev で引用)。

これらを毎回正しく書けない / レビューで弾けないチーム条件下では、**閾値を下げて高級言語に逃がす方が安い**。

### 6. PowerShell の場合 — bash との「差分」だけ

主張: PowerShell 7 はクロスプラットフォームだが Bash の代替ではない。bash と同じ閾値判断 (行数、複雑度、テスト性) は共通で適用してよい。**ここでは差分だけを述べる。**

- **パイプはオブジェクトを流す**: テキスト前提の bash と違い、構造化データの取り回しが楽。`Get-Process | Where-Object ...` のような書き味は CSV/JSON 加工に強い。
- **`$ErrorActionPreference = "Stop"` は `set -e` と同じではない**: PowerShell には「terminating error」と「non-terminating error」がある。`Write-Error` は `catch` を発火しない。HN 議論でも「`set -e` の等価が無い」と明言されている。
- **戻り値の意味が独特**: 関数内の式は全部「戻り値ストリーム」に積まれる。`return` を書かなくても返ってくる。
- **PowerShell が bash より明確に勝つ場面**: Windows 固有 (レジストリ、AD、Exchange、WMI、Excel COM)、Az モジュール経由の Azure 操作、構造化ログを処理するワンライナー。
- **クロスプラットフォーム要件があるからといって PowerShell を採用する理由にはならない**: macOS/Linux ネイティブの呼び出しでは object pipeline の恩恵が薄い。Python のほうが普通は楽。
- 閾値: 500 行を超えるような業務ロジック / 永続するデーモン的処理になってきたら C# (.NET) か Python に逃がす。

### 7. 中級以上のレベル別到達ライン

主張: 「シェルをどこまで理解すべきか」はレベルではなく**仕事の依存先**で決まる。中級以上に絞った 4 つの像。

- **中級アプリケーション開発者**
  - 20〜50 行のラッパーを書ける
  - `set -euo pipefail` の罠を 1 つ以上説明できる
  - ShellCheck を CI に組み込める
  - 既存の長い shell スクリプトを読んで Python へ移植できる
- **SRE / DevOps / プラットフォームエンジニア**
  - 制約環境 (alpine, busybox, distroless 直前段) を意識した書き分けができる
  - POSIX sh と Bash の差分を把握している
  - bats などでテストが書ける
  - 「これは shell の限界」を即座に判断して Go/Python に逃がせる
- **データ・ML エンジニア**
  - パイプラインの**外側** (env 用意、データ取得、ジョブ起動) を 30 行程度書ければ十分
  - ML 本体・ETL 本処理は必ず Python に
- **Windows / Azure 中心の開発者**
  - PowerShell の object pipeline と error 体系を理解
  - terminating / non-terminating error を区別できる
  - Az モジュール経由のスクリプトを書けるが、業務ロジックが入ったら C# に逃がせる

### 8. 判断フローまとめ (チェックリスト)

書き始める前のチェックリスト。1 つでも yes が出たら shell では書かない。

- [ ] 100 行を超える予感がするか
- [ ] 連想配列・構造化データを扱うか
- [ ] テストを書きたいか
- [ ] 性能/並列処理が要件か
- [ ] 外部 API を 3 回以上叩いてリトライしたいか
- [ ] チームのレビュアーが `set -e` の落とし穴を全員説明できないか

「チームで明文化したスイッチライン」を CONTRIBUTING に書いておくことを推奨。

### 9. まとめ

- shell は「狭く深く使う道具」。Google も GitLab も「広く使わない」と明言している
- `set -euo pipefail` は最低条件であって安全網ではない
- PowerShell は同じ閾値で判断しつつ、object pipeline と error モデルの差分だけ意識する
- 中級以上のエンジニアにとっての到達目標は「書ける量」ではなく「いつ書かない判断ができるか」

## 各セクションの根拠 URL

- Google Shell Style Guide: https://google.github.io/styleguide/shellguide.html (extract: `temp/shell_vs_highlevel/extract_google_shellguide.json`)
- GitLab Shell scripting standards: https://docs.gitlab.com/development/shell_scripting_guide/ (extract: `temp/shell_vs_highlevel/extract_gitlab_guide.json`)
- Bash FAQ 105 / Greg's Wiki: https://mywiki.wooledge.org/BashFAQ/105 (search: `temp/shell_vs_highlevel/search_set_e_caveats.json`)
- Defensive Shell Scripting with Shell Options: https://emmer.dev/blog/defensive-shell-scripting-with-shell-options/ (同上)
- Stack Overflow "Bash subshell errexit semantics": https://stackoverflow.com/questions/29532904/bash-subshell-errexit-semantics (同上)
- PowerShell 7.x differences (Microsoft Learn): https://learn.microsoft.com/en-us/powershell/scripting/whats-new/differences-from-windows-powershell (search: `temp/shell_vs_highlevel/search_powershell_positioning.json`)
- PowerShell exceptions (Microsoft Learn): https://learn.microsoft.com/en-us/powershell/scripting/learn/deep-dives/everything-about-exceptions (同上)
- HN "Linux Bash vs. Windows PowerShell" 議論 — `$ErrorActionPreference` ≠ `set -e` の証言 (同上)
- Tim O'Hearn "Bash Versus Python Scripting": https://www.tjohearn.com/2018/01/28/bash-versus-python-scripting/ (search: `temp/shell_vs_highlevel/search_shell_vs_python_general.json`)
- sap1ens "Bash scripting best practices": https://sap1ens.com/blog/2017/07/01/bash-scripting-best-practices/ (同上)
- Stack Overflow "Strengths of Shell Scripting compared to Python": https://stackoverflow.com/questions/796319/strengths-of-shell-scripting-compared-to-python (同上)

## 不足情報 / 追加調査ポイント

- Cloudflare 2021 年 12 月のインシデント postmortem 原典は引用元 (emmer.dev) で示されているが本文確認はしていない。本文で言及する場合は「emmer.dev によれば」と二次引用にとどめる
- GitHub Actions の `run:` シェルが `set -eo pipefail` を自動付与する件は emmer.dev 経由の言及。本文に書く場合、GitHub Docs の一次資料 (https://docs.github.com/actions) で念のため裏取りする
