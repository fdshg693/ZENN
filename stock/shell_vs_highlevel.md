---
title: "シェルスクリプトをいつ捨てるか — Google と GitLab の閾値で考える「高級言語へのスイッチライン」"
emoji: "🐚"
type: "tech"
topics: ["shell", "bash", "powershell", "devops", "python"]
published: false
---

## この記事について

CI を整備すれば bash、Dockerfile を書けば bash、デプロイ手順を整理すれば bash、Windows サーバを触れば PowerShell。Python や Go が標準になった今でも、シェルスクリプトはチームから完全には消えません。

一方で、「100 行を超えた bash がレビューで誰にも読めない」「`set -e` を信じていたのに本番でだけスルーされた」「PowerShell の関数の戻り値が想像と違う」――どこかで踏んだことがあると思います。

この記事では、業界の主要なスタイルガイド (Google・GitLab) と Bash の有名な落とし穴 (Greg's Wiki BashFAQ/105 ほか) を根拠に、

- シェルスクリプトが**本当に得意な領域**
- いつ**高級言語に切り替えるべきか**(具体的な閾値)
- `set -euo pipefail` が**守れない領域**
- PowerShell は bash とどう違うのか (差分だけ)
- **中級以上のエンジニア**が職種別にどこまで理解しておくべきか

を整理します。前提知識として `set -e`、パイプ、`$(...)` を読み書きできる中級以上のエンジニアを想定し、構文チュートリアルは扱いません。

## まず最初に: この記事の前提となる「シェル衛生」

これ以降のコード例では、いちいち書きませんが**以下を前提にしています**。チームで shell を書くなら同じ前提に揃えるべきラインです。

1. **冒頭の宣言**

   ```bash
   #!/usr/bin/env bash
   set -euo pipefail
   ```

   - `-e` で「コマンドが失敗したら止まる」、`-u` で「未定義変数を参照したら止まる」、`-o pipefail` で「パイプの途中の失敗を末端まで伝播する」。
2. **静的解析: [ShellCheck](https://www.shellcheck.net/) を CI で必ず走らせる**。GitLab の公式コーディング規約は ShellCheck の CI ジョブ例を直接示しています ([GitLab Docs](https://docs.gitlab.com/development/shell_scripting_guide/))。
3. **フォーマット: shfmt を `-i 2 -ci` で**。GitLab は Google Shell Style Guide にフォーマットを合わせるため `shfmt -i 2 -ci -w scripts/**/*.sh` を推奨しています ([GitLab Docs](https://docs.gitlab.com/development/shell_scripting_guide/))。

ただしここで強調しておきたいのは、**`set -euo pipefail` は安全網ではない**ということです。なぜ完全ではないかは後段「§5」で具体的に示します。

なお、GitHub Actions の `run:` ステップは shell の指定方法によって自動付与されるフラグが変わります ([GitHub Docs: Workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax))。

| `shell` 指定 | 実行コマンド | 自動で付くフラグ |
|---|---|---|
| 未指定 (Linux/macOS) | `bash -e {0}` | `-e` のみ |
| `shell: bash` | `bash --noprofile --norc -eo pipefail {0}` | `-e -o pipefail` |
| `shell: pwsh` | `pwsh -command ". '{0}'"` | 自動付与なし |

つまり「`shell: bash` を**明示**すると pipefail が付くが、未指定なら付かない」「`-u` はどちらでも付かない」。本気で安全にしたければ、`run:` の中で自分で `set -euo pipefail` を書くのが確実です。

## §1. シェルスクリプトが本当に得意な領域 (狭いが確実)

まず「shell の勝ち筋」を狭く確定させます。ここを誤ると「全部 shell」も「全部 Python」も両方が悪手になります。

シェルが他言語より明確に強いのは、以下に集約されます。

1. **既存コマンド群の「接着剤」**
   `grep` / `awk` / `curl` / `tar` / `kubectl` / `gh` / `git` などをパイプで繋ぎ、ストリーム処理する場面。
2. **起動が薄い・依存ゼロ**
   インタプリタの初期化がほぼないため、CI の中で 100 回呼ばれるような小さなチェックには Python より速くて軽い。
3. **実行環境がまだ整っていない段階の bootstrap**
   「Python 自体をインストールするスクリプト」を Python では書けません。`asdf-vm` / `rustup` / `homebrew` / `pyenv-installer` のインストーラがどれも shell なのは偶然ではない。
4. **shell が前提になっている場所**
   - Dockerfile の `RUN`
   - GitHub Actions / GitLab CI の inline step
   - systemd の `ExecStart=`
   - Git hooks (`pre-commit`、`prepare-commit-msg` など)
   - cron / Kubernetes の `command:` フィールド

これらの場所で「短く書く」目的なら shell が最適解です。逆に**これ以外**では、shell が他言語に勝つ理由はほぼ無いと考えてよい。

ここに関連して、GitLab Docs の表現は非常にはっきりしています ([GitLab Docs "Shell scripting standards"](https://docs.gitlab.com/development/shell_scripting_guide/))。

> Having said all of the above, we recommend staying away from shell scripts as much as possible. A language like Ruby or Python ... is almost always a better choice.
> Use shell scripts only if there's a strong restriction on project's dependencies size or any other requirements that are more important in a particular case.

「依存サイズなどの強い制約がないなら、そもそも shell を避けろ」という、かなり強い表現です。

## §2. 切り替えるべき閾値 — 業界が合意するライン

「いつ書き始めるか」より、「**書き始める前にやめるか**」を決めるほうが安い。

[Google Shell Style Guide](https://google.github.io/styleguide/shellguide.html) の "When to use Shell" は実務でそのまま使える基準です。重要部分を一次引用すると:

> Shell should only be used for small utilities or simple wrapper scripts.

そして同ガイドが配列の説明に付している補足:

> if more advanced data manipulation is required, shell scripting should be avoided altogether

これに、コミュニティで広く合意されている定量基準を加えると、以下のチェックリストになります。

| シグナル | 出典 |
|---|---|
| 100 行を超えそう / 超えた | Google Shell Style Guide ("scripts grow") |
| `${PIPESTATUS}` の保管以外で**配列**が要る、または「より高度なデータ操作」が要る | Google Shell Style Guide |
| 性能が要件に入る | Google Shell Style Guide |
| 構造化データ (JSON / YAML / XML) を**真面目に**扱う | コミュニティ合意 |
| 複雑な条件分岐、多段の curl 加工、リトライ | [Tim O'Hearn "Bash Versus Python Scripting"](https://www.tjohearn.com/2018/01/28/bash-versus-python-scripting/) |
| ユニットテストを書きたい | GitLab Docs |
| プロジェクトの依存サイズ制約がない | GitLab Docs |

「100 行ルール」は厳密な閾値というより、「100 行に**到達する前に**鞍替えしろ」という意味で読んでください。Google ガイドが添えている注も同じです:

> Bear in mind that scripts grow. Rewrite your script in another language early to avoid a time-consuming rewrite at a later date.

実務では、最初の段階で「これは bash で書ききれるか」を判定し、**怪しい時点で Python / Go を選ぶ**ほうが、後からの書き直しコストより安い。これは GitLab ガイドの「デフォルトは Python/Ruby、shell は逃げ場」という方針と完全に一致します。

### 切り替えサインの具体例

- `jq` でパイプを 3 段以上重ねて JSON を加工し始めた → Python の `json` モジュール / Go の `encoding/json` に。
- 関数を 3 つ以上書き、変数の受け渡しが文字列ベースで読みづらい → 言語を変える。
- リトライ・タイムアウト・並列度を制御し始めた → 高級言語に。
- shell の上で「設定ファイル」を YAML で持ち始めた → そもそも shell でない。

## §3. `set -euo pipefail` だけでは守れない領域

「お守り」と書いた理由を、ここで具体例ベースに示します。一次資料は [Greg's Wiki BashFAQ/105](https://mywiki.wooledge.org/BashFAQ/105) と [emmer.dev "Defensive Shell Scripting with Shell Options"](https://emmer.dev/blog/defensive-shell-scripting-with-shell-options/)、Stack Overflow の [bash subshell errexit semantics](https://stackoverflow.com/questions/29532904/bash-subshell-errexit-semantics) 議論です。

### 罠 1: `set -e` は条件文の中では無効化される

Bash man に明記されているとおり、`set -e` は次のいずれかの中では発火しません。

- `&&` / `||` のリスト (最後を除く)
- `if`、`while`、`until` の条件部
- `!` で反転されたコマンド
- パイプの最後以外

つまり、よくある防御的なつもりの書き方:

```bash
some_command && echo "ok"
```

は、`some_command` が失敗してもスクリプトは止まりません。さらに次のパターン、

```bash
if some_command; then
  do_something
fi
```

の中の `some_command` の失敗も `set -e` の対象外です。これは [Greg's Wiki BashFAQ/105](https://mywiki.wooledge.org/BashFAQ/105) と Stack Overflow 議論の両方で繰り返し指摘されています。

### 罠 2: `local var=$(cmd)` は cmd の失敗を握りつぶす

```bash
f() {
  local var=$(somecommand_that_fails)   # スクリプトは止まらない
}

g() {
  local var
  var=$(somecommand_that_fails)         # スクリプトは止まる
}
```

`local`(同様に `declare`、`export`、`typeset`) の戻り値は**それ自体の代入成功**を表すため、右辺コマンドの失敗をマスクしてしまう。これは [BashFAQ/105](https://mywiki.wooledge.org/BashFAQ/105) に最も古典的な落とし穴として記載されています。

### 罠 3: コマンド置換のサブシェルでは `-e` が伝播しない

Bash のデフォルトでは、`$(...)` の中のサブシェルは親の `-e` を継承しません。

```bash
set -e
foo="result is: $(false; echo "still running")"
echo "$foo"   # "result is: still running" が表示される
```

Bash 4.4 以降の `shopt -s inherit_errexit` を有効化しないと止まりません ([Stack Overflow](https://stackoverflow.com/questions/29532904/bash-subshell-errexit-semantics))。

### 罠 4: pipefail が無いと末端コマンドだけが終了コードに反映される

Cloudflare の 2021 年 12 月のインシデントは、`set -o pipefail` を有効にしていれば防げたとされており、emmer.dev の "Defensive Shell Scripting" でも引用されています。GitHub Actions が `shell: bash` 明示時に `-eo pipefail` を自動で付けるのも、この罠を踏みやすいからです。

### 罠が示すこと

これらを毎回・全員が・レビューで・正しく扱えないチームなら、**閾値を下げて高級言語に逃がす方が現実的に安い**。`set -euo pipefail` を書くのは最低条件であって、それで安全になるわけではない、と理解しておく必要があります。

## §4. PowerShell の場合 — bash との「差分」だけ

ここまでの議論の大部分は PowerShell にもそのまま適用できます。**100 行ルール、テストが要るなら別言語、複雑なデータ加工は別言語 — どれも同じ**です。

ですので以下では PowerShell **固有の差分**だけに絞ります。

### 差分 1: パイプはオブジェクトを流す

PowerShell のパイプはテキストではなくオブジェクトを流します。`Get-Process | Where-Object { $_.WorkingSet -gt 100MB } | Select-Object Name, Id` のように、シリアライズ / パースを介さずに**構造化フィルタが書ける**。これは bash の `awk`/`jq` 多段に比べて明確な強みです。

CSV、Windows イベントログ、レジストリ、AD オブジェクト、Excel COM、Az モジュール経由の Azure リソースなど、「型のあるデータ」を流すケースでは PowerShell のほうが短く・読みやすく書けます。

### 差分 2: `$ErrorActionPreference = "Stop"` は `set -e` と等価ではない

PowerShell には「terminating error」と「non-terminating error」の区別があります ([Microsoft Learn: Everything you wanted to know about exceptions](https://learn.microsoft.com/en-us/powershell/scripting/learn/deep-dives/everything-about-exceptions))。

> An exception is generally a terminating error. ... I point this out because `Write-Error` and other non-terminating errors do not trigger the `catch`.

つまり `Write-Error` で出力されるエラーは `try { } catch { }` に拾われません。`$ErrorActionPreference = "Stop"` を立てれば多くの cmdlet エラーを terminating に格上げできますが、**ネイティブ exe の終了コードはそもそもこの仕組みの外**にあり、`$LASTEXITCODE` を自分で確認する必要があります。

HN の "Linux Bash vs. Windows PowerShell" 議論でもこの差は繰り返し指摘されています。「bash の `set -e` 相当が PowerShell には存在しない」と理解しておくほうが事故が減ります。

### 差分 3: 関数の戻り値は「ストリーム」

PowerShell の関数は `return` を書かなくても、関数本体で**評価されたあらゆる式の値**がパイプライン出力に積まれます。

```powershell
function Get-Stuff {
  "first"
  Write-Host "this prints to host, not pipeline"
  42
  # 呼び出し側は ["first", 42] を受け取る
}
```

これは bash の「最後の式の終了コードが関数の戻り値」とは全く違う。`Write-Host` と「裸の式」を混同しただけで戻り値が壊れます。

### 差分 4: クロスプラットフォーム要件があるなら PowerShell は近道ではない

PowerShell 7.x は macOS / Linux で動きます ([Microsoft Learn: Differences between Windows PowerShell 5.1 and PowerShell 7.x](https://learn.microsoft.com/en-us/powershell/scripting/whats-new/differences-from-windows-powershell))。しかし「クロスプラットフォームだから PowerShell」と選ぶのは多くの場合**裏目に出ます**。Linux/macOS では:

- object pipeline の旨味が薄い (相手のコマンドが文字列を返してくる)
- ランタイムを別途インストールする手間が増える
- 周辺ツールの ergonomics が悪い (`Get-` 系 cmdlet がない)

「クロスプラットフォームで書きたい」が要件なら、**Python のほうが普通は楽**です。

### PowerShell の閾値

- **PowerShell が bash より明確に勝つ**: Windows 固有 (レジストリ、AD、Exchange、WMI、Excel COM)、Az モジュール経由の Azure 操作、構造化オブジェクトを処理するワンライナー
- **PowerShell でも別言語に切り替えるべき**: bash と同じ閾値(100 行・テスト・複雑なデータ加工・性能要件)
- 業務ロジックが入ってきたら **C# (.NET) か Python に逃がす**。PowerShell モジュールとして配布する場合でも、ロジック本体は C# にして PowerShell は薄いラッパーに保つのが定石。

## §5. 中級以上のレベル別到達ライン

「どこまでシェルを理解すべきか」は経験年数ではなく、**仕事の依存先**で決まります。中級以上を想定すると 4 つの像になります。

### 中級アプリケーション開発者 (Web / バックエンド / モバイル)

- 20〜50 行程度のラッパーが書ける。`set -euo pipefail` の罠を 1 つ以上具体的に説明できる
- ShellCheck を CI に組み込める
- 既存の長い shell スクリプトを読み解いて、必要なら Python に移植する判断ができる
- **書けないと困らない領域**: 自前で複雑な shell を新規に量産する必要はない

### SRE / DevOps / プラットフォームエンジニア

- 制約環境 (alpine、busybox、distroless 一歩手前、initramfs) を意識した書き分けができる
- POSIX sh と Bash の差分を把握している (どのコンテナでは `[[ ]]` が使えないか、など)
- [bats-core](https://github.com/bats-core/bats-core) でシェルスクリプトのテストが書ける
- 「これは shell の限界」を即座に判断して Go / Python に逃がせる
- 既存の shell の温床 (long-running なデプロイスクリプトなど) を**段階的に縮める**戦略を持っている

### データ・ML エンジニア

- パイプラインの「外側」(env 用意、データ取得、ジョブ起動、後始末) を 30 行程度書ければ十分
- ETL / モデル本体は必ず Python (もしくは SQL)。shell に処理が漏れ出していたら即座に Python に引き戻す
- `aws s3 cp` / `gsutil cp` / `kubectl apply` のような外部 CLI を「待つ・リトライする・タイムアウトする」だけのラッパーを書けるとよい

### Windows / Azure 中心の開発者

- PowerShell の object pipeline と error 体系 (terminating / non-terminating) を区別できる
- `$ErrorActionPreference` と `$LASTEXITCODE` を使い分けられる
- Az / Microsoft.Graph モジュール経由のスクリプトを書ける
- 業務ロジックを PowerShell から **C#** に引き剥がす判断ができる

共通する到達目標は「**書ける行数**」ではなく「**いつ書かない判断ができるか**」です。中級以上なら、その判断を**根拠つきで**チームに説明できることが本質的なスキルになります。

## §6. 判断フロー(チェックリスト)

新しいタスクを shell で書き始める前に、以下を回してください。**1 つでも yes が出たら shell では書きません**。

- [ ] 100 行を超える予感がある
- [ ] 連想配列・構造化データ (JSON / YAML / XML) を扱う
- [ ] テストを書きたい / 単体動作を保証したい
- [ ] 性能 / 並列度を要件にしている
- [ ] 外部 API を 3 回以上叩く、またはリトライ・タイムアウトを制御する必要がある
- [ ] 設定ファイルを別途持ちたい
- [ ] チームのレビュアー全員が `set -e` の落とし穴 (条件文・`local`・サブシェル・pipefail) を説明できるわけではない
- [ ] 半年後に他人が触る可能性が高い

このチェックリストを、`CONTRIBUTING.md` や ADR に「うちのチームのスイッチライン」として明文化しておくのを強く推奨します。判断の属人化を防ぐ最も安いやり方です。

## まとめ

- シェルスクリプトは「狭く深く使う道具」です。Google も GitLab も「広く使うな」と明言している
- 切り替え閾値は **100 行 / 配列・構造化データ / 性能 / テスト / 複雑な条件分岐** が代表的。怪しい時点で別言語に逃がす
- `set -euo pipefail` は最低ラインであって安全網ではない。条件文・`local`・コマンド置換サブシェル・pipefail の罠は別途意識する必要がある
- PowerShell は object pipeline と error モデルが違うだけで、**閾値は bash と同じ**。「`set -e` の等価がない」ことを忘れない
- **中級以上のエンジニアの到達目標は「書ける」ではなく「書かない判断ができる」**こと

判断のラインをチームで明文化したいときに、本記事の §6 のチェックリストをそのまま叩き台にどうぞ。

## 参考資料

- [Google Shell Style Guide](https://google.github.io/styleguide/shellguide.html)
- [GitLab Docs: Shell scripting standards and style guidelines](https://docs.gitlab.com/development/shell_scripting_guide/)
- [Greg's Wiki — BashFAQ/105 "Why doesn't set -e work as expected?"](https://mywiki.wooledge.org/BashFAQ/105)
- [emmer.dev "Defensive Shell Scripting with Shell Options"](https://emmer.dev/blog/defensive-shell-scripting-with-shell-options/)
- [Stack Overflow "Bash subshell errexit semantics"](https://stackoverflow.com/questions/29532904/bash-subshell-errexit-semantics)
- [GitHub Docs: Workflow syntax for GitHub Actions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [Microsoft Learn: Differences between Windows PowerShell 5.1 and PowerShell 7.x](https://learn.microsoft.com/en-us/powershell/scripting/whats-new/differences-from-windows-powershell)
- [Microsoft Learn: Everything you wanted to know about exceptions (PowerShell)](https://learn.microsoft.com/en-us/powershell/scripting/learn/deep-dives/everything-about-exceptions)
- [Tim O'Hearn "Bash Versus Python Scripting"](https://www.tjohearn.com/2018/01/28/bash-versus-python-scripting/)
- [sap1ens "Bash scripting best practices"](https://sap1ens.com/blog/2017/07/01/bash-scripting-best-practices/)
