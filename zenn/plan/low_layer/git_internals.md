---
title: "Gitは本当はバージョン管理ツールではない — 内容アドレス型ファイルシステムとして読み解く"
status: plan
---

## この plan の位置づけ

- 重心: **設計思想と1本の筋を主役に**(ユーザー確認済み)
- 中心メタファ: Git = **コンテンツアドレス型ファイルシステム(不変オブジェクトの Merkle DAG)＋ その上の可変ポインタ**
- 終盤の対比対象: **jj (Jujutsu) を主役**、Pijul/Sapling/Mercurial/Fossil は短く(ユーザー確認済み)
- 弱点の重心: **大規模/巨大バイナリ・UX/メンタルモデル・履歴書き換え/コンフリクト**(SHA-1/256 は軽く)(ユーザー確認済み)
- 目的: Git を「使える」を超えて、**なぜこう振る舞うのかを1つの設計判断から導けるメンタルモデル**を作る。コマンドの使い方・packfile/delta圧縮・転送プロトコル実装の詳細には踏み込まない
- 分量目安: 約450〜520行(参照 `zenn/publish/low_layer/wsl_internals.md`, `python_bytecode_internals.md`)
- スタイル: Tips寄せ集めではなく、**1つの設計判断から全現象を一本の筋で導く**(既存シリーズと同じ構造)

## 中心の主張(メンタルモデルの軸)

> Git の正体は「**内容によって名前(ハッシュ)が決まる、不変オブジェクトの有向グラフ(Merkle DAG)= コンテンツアドレス型ファイルシステム**」であり、その上に「**動かせる名前付きポインタ(ブランチ・タグ・HEAD・index)**」を薄く乗せただけのもの。
>
> 「ブランチ作成が一瞬」「分散できる」「履歴の改竄を検知できる」「rebase すると“同じ変更”が別物になる」——これらは全部、**「不変オブジェクト ＋ 可変ポインタ」という1つの設計の帰結**として一本で説明できる。
>
> そして Git の固定点を1つずつ動かしたのが代替ツールたち。**「ワーキングコピーは履歴の外側」を「ワーキングコピー = コミット」に動かしたのが jj**、**「スナップショット」を「パッチの代数」に動かしたのが Pijul**。

---

## 想定読者 / 前提 / 扱う範囲

- 想定読者: Git を毎日 add/commit/push しているが、`.git` の中を覗いたことがないエンジニア(既存シリーズと同じ層)
- 前提知識: commit / branch / merge / rebase を「操作として」知っている
- 答える問い: なぜ Git はこう振る舞うのか / 何に強く何に弱いのか / 代替ツールは「Git のどの固定点」を動かしたのか
- 扱わない: コマンドリファレンス、packfile/delta圧縮・gc の内部、転送プロトコル、C実装の詳細

---

## セクション構成

### 0. この記事について(導入)
- 主張: 「Git を `commit`/`push` の手順として覚えると、`detached HEAD`・`rebase` のコンフリクト・巨大リポジトリの遅さが全部“バラバラの罠”に見える。だが内部は驚くほど少数の原理でできていて、**1つの設計判断から全部導ける**」
- 「コマンドの使い方は説明しない。`.git` の中身の“形”と、その背後の思想を読む」とスコープ宣言
- 根拠: 全体の地ならし(出典不要)

### 1. Git は差分を保存していない — スナップショットとオブジェクト
- 主張: 多くのVCSが「ファイルごとの差分の系列」で履歴を持つのに対し、Git は**スナップショットの系列**で持つ。これが全ての出発点
- 内容:
  - `git commit` 時、各ディレクトリを tree、各ファイルを blob として保存し、commit はルート tree を指す。3ファイル初回コミットで 5 オブジェクト(blob×3 / tree×1 / commit×1)
  - blob は inode/ファイル内容、tree は UNIX ディレクトリエントリに対応。Git は「簡略化された UNIX ファイルシステム」
  - 「Git はデータを changeset/差分でなく snapshot の系列として保存する」を一次資料から引用
- 根拠 URL:
  - https://git-scm.com/book/en/v2/Git-Branching-Branches-in-a-Nutshell (スナップショット系列、5オブジェクト)
  - https://git-scm.com/book/en/v2/Git-Internals-Git-Objects (blob/tree、inode比喩、格納形式)
- 根拠ファイル: `temp/git_internals/extract_proggit_objects_refs.json`

### 2. 名前は内容から決まる — コンテンツアドレッシングと整合性
- 主張: Git のオブジェクト名(SHA)は**内容のハッシュそのもの**。これが「同じ内容なら同じ名前」「内容が1bit変われば名前が変わる」を生み、整合性・重複排除・分散の土台になる
- 内容:
  - オブジェクトは `.git/objects/` に「SHA 先頭2文字/残り38文字」で格納。全オブジェクトは type+length+NUL+content をハッシュした名前を持つ
  - **作成後オブジェクトは immutable**(AOSA: object DB は immutable)
  - commit は親 commit へのポインタを持つ(初回0/通常1/マージ2+)。「ハッシュで参照される不変ノード＋親リンク」= **Merkle DAG**。だから途中を1つ書き換えると、それを指す全祖先のハッシュが変わる → 改竄検知
- 根拠 URL:
  - https://git-scm.com/book/en/v2/Git-Internals-Git-Objects (格納形式・ヘッダ)
  - https://aosabook.org/en/v2/git.html ("all objects are immutable once created")
  - https://git-scm.com/book/en/v2/Git-Branching-Branches-in-a-Nutshell (親ポインタ)
- 根拠ファイル: `extract_proggit_objects_refs.json`, `extract_aosa_git.json`

### 3. 可変なものは全部「ポインタ」 — ブランチ・タグ・HEAD・index
- 主張: 不変DAGの上で「動く」ものは、すべて**SHA を書いたただのポインタ**。ここを掴むと branch/HEAD/detached/index が一気に繋がる
- 内容:
  - ブランチ作成 = 内部的に `update-ref`(最新 commit の SHA を参照ファイルに書くだけ)→ だからブランチは“軽い”
  - タグも `update-ref refs/tags/...` で SHA を書くだけ。違いは「動かさない」運用。タグは commit に限らず任意オブジェクトを指せる(Git 自身は GPG鍵 blob にタグ)
  - HEAD は通常「現在ブランチを指す symbolic ref」。SHA を直接持つと **detached HEAD**。HEAD は refs/ の外を指せない制約
  - index(`.git/index`) = working tree と object DB の間の**ステージング層**。`git add -p` で論理的に意味のある単位だけ束ねられる(AOSA の設計意図)。※ index が後で jj の比較軸になる伏線
- 根拠 URL:
  - https://git-scm.com/book/en/v2/Git-Internals-Git-References (update-ref、HEAD=symbolic ref、detached、タグ)
  - https://aosabook.org/en/v2/git.html (`.git` 構成、index の位置づけ、`git add -p`)
- 根拠ファイル: `extract_proggit_objects_refs.json`, `extract_aosa_git.json`

### 4. なぜこの設計だったのか — Linux カーネルという出自
- 主張: この「不変DAG＋ポインタ＋分散」は美学ではなく、**Linux カーネル開発という極端な制約**から逆算された結果
- 内容:
  - 大量のコミッタ・貢献度と信頼度のばらつき・tarball と patch での長年の保守という背景。中央集権を信頼の前提にできなかった
  - だから「全員がフルコピーを持ち、改竄を暗号学的ハッシュで検知し、マージを後でやる」分散モデルが必然だった
  - = 強みと弱みは同じ1つの設計判断の表裏、という記事の蝶番
- 根拠 URL: https://aosabook.org/en/v2/git.html (Git の起源・設計背景)
- 根拠ファイル: `extract_aosa_git.json`

### 5. 強み — 全部この1点から出てくる
- 主張: Git の長所は機能の足し算ではなく、**「内容アドレス型・不変・分散」から導かれる帰結**
- 内容(各々を §2/§3 に紐づけて短く):
  - 整合性: 暗号学的ハッシュが約束の中心(改竄・破損を検知)
  - 分散/オフライン: 全員がフル履歴を持つ
  - 軽いブランチ: ブランチ = ポインタ書き込み
  - スナップショット由来の速さ・自己完結性
  - 実は超大規模もこなせる: 「300GB・350万ファイル・4000人が20秒ごとに push」級まで拡張されてきた(ただし§6への前振り=“素のままでは”ない)
- 根拠 URL:
  - https://www.helpnetsecurity.com/2025/08/19/git-2-51-sha-256 (整合性とハッシュ)
  - https://blog.gitbutler.com/git-tips-3-really-large-repositories (大規模の具体規模)
- 根拠ファイル: `extract_git_scaling.json`, `search_sha256.json`

### 6. 弱み — 同じ設計が裏目に出るところ
- 主張: 弱点は“バグ”ではなく、**中心設計のコスト**。3つの観点で
- 6-1 大規模 / 巨大バイナリ:
  - スナップショット＋フル分散は「全部持つ」が前提 → 巨大化に弱い。Linux 4GB超 / Chromium 20GB超(高速回線でも full clone 1時間級)
  - 巨大バイナリは内容アドレッシングと相性が悪い(10MB超 blob が警告対象)。対症療法: Git LFS(ポインタだけ置く)
  - 「全部持つ」を崩す装置: partial clone(`--filter=blob:none` / `tree:0`)、shallow(`--depth=1`)、sparse-checkout(2.25.0〜)。**いずれも Git本来の分散性の期待を最低1つ壊すトレードオフ**(shallowは blame/log が壊れる)
  - monorepo では index 自体が肥大化(HEAD全ファイル分の情報を持つ)→ sparse-index 等の対処
- 6-2 UX / メンタルモデル:
  - 「内部モデルは良いが UI は悪い」という定評。porcelain/plumbing の二層、index という第3の場所、ブランチが単なるポインタであることの分かりにくさ
  - MS/Google も巨大リポジトリ対応に苦労("mixed success")
- 6-3 履歴書き換え / コンフリクト:
  - rebase/cherry-pick は「同じ変更」を**別オブジェクトとして作り直す** → 同一性が保てず「人工的なコンフリクト」やコンフリクト再解決が起きる
  - Git の conflict は「進行を止めるエラー状態」で、単なるテキスト diff(first-class オブジェクトではない)→ §7 jj の対比に直結
- 6-4 (軽く) SHA-1 → SHA-256:
  - 2005年以来 SHA-1。衝突攻撃実証後、SHA1DC で緩和(2017, v2.13)。SHA-256 は段階移行中(Git 2.51, 2025)。SHA-1=40桁/SHA-256=64桁。現状リポジトリ間相互運用には制約
- 根拠 URL:
  - https://github.blog/open-source/git/get-up-to-speed-with-partial-clone-and-shallow-clone (3手段とトレードオフ)
  - https://blog.gitbutler.com/git-tips-3-really-large-repositories (規模、shallowの破壊)
  - https://docs.gitlab.com/user/project/repository/monorepos (10MB blob, LFS, --filter)
  - https://github.blog/open-source/git/bring-your-monorepo-down-to-size-with-sparse-checkout (sparse-checkout 2.25.0)
  - https://lobste.rs/s/6jllik/sapling_source_control_s_user_friendly (UIは悪い/内部は良い、MS/Google mixed success)
  - https://pijul.org/model (artificial conflicts)
  - https://github.com/jj-vcs/jj (conflict はテキスト diff 扱い)
  - https://git-scm.com/docs/hash-function-transition + https://www.helpnetsecurity.com/2025/08/19/git-2-51-sha-256 (SHA移行)
- 根拠ファイル: `extract_git_scaling.json`, `extract_pijul_sapling.json`, `extract_jj.json`, `search_sha256.json`

### 7. 代替ツール — 「Gitのどの固定点を動かしたか」で読む(jj 主役)
- 主張: 代替は「Gitの全否定」ではなく、**Git が固定した前提を1つだけ動かした実験**として読むと一望できる
- 7-1 jj (Jujutsu) ★主役:
  - 動かした固定点①「ワーキングコピーは履歴の外側」→ **ワーキングコピー = コミット**。変更は自動で commit に取り込まれ(`git add` 不要)、stash も index も不要にする(包含する)
  - 動かした固定点②「conflict はエラー状態」→ **first-class conflict**(conflict 自体が commit に保存され、後で解決でき、コンテキストスイッチ可)
  - operation log + `jj undo`(rebase 失敗・誤マージ・誤書き換えを取り消せる)
  - anonymous branch がデフォルト(命名不要)、Mercurial 由来の revset
  - **Git backend 互換**: 同じ `.git` を読み書き、Git remote と push/fetch、チームは Git のまま自分だけ jj。= 「Git の上のレイヤー」
- 7-2 Pijul: スナップショットでなく**パッチの代数**(可換な patch、category theory の pushout)。独立変更は順序非依存、cherry-pick で人工コンフリクトが起きない。理論的に綺麗だが UX に賛否
- 7-3 Sapling (Meta): Git の良い内部モデルは保ちつつ UX を作り直す。**staging area なし**・各コマンドは1つのことだけ・ローカルブランチ名は任意・clone で全部は落とさない
- 7-4 Mercurial / Fossil(1〜2行ずつ): Mercurial = 同年代でUXは良かったが普及競争に敗北/state-based。Fossil = VCS に tickets/wiki/forum/web UI を統合した単一実行ファイル(SQLite)。設計思想が逆向き(分散の最小核 vs 全部入り)
- 根拠 URL:
  - https://github.com/jj-vcs/jj (working-copy-as-commit, first-class conflict, op log, git backend)
  - https://www.kunalganglani.com/blog/jujutsu-jj-git-version-control (undo, conflict 保持, .git 共有)
  - https://zenn.dev/usamik26/articles/jj-version-control (change, anonymous branch, add不要)
  - https://pijul.org/model + http://pijul.org (patch theory, pushout, commutation)
  - https://engineering.fb.com/2022/11/15/open-source/sapling-source-control-scalable + https://sapling-scm.com/docs/introduction/differences-git (no staging area, 各コマンド単機能)
  - https://lobste.rs/s/6jllik/sapling_source_control_s_user_friendly (Mercurial の歴史評価)
  - https://fossil-scm.org/home/doc/tip/www/fossil-v-git.wiki (Fossil = VCS+tickets+wiki+forum+UI / 単一実行ファイル / SQLite)
- 根拠ファイル: `extract_jj.json`, `extract_pijul_sapling.json`, `extract_sapling_fossil_merkle.json`, `search_fossil.json`

### 8. まとめ — 1枚の地図
- 主張: 「不変オブジェクトの Merkle DAG ＋ 可変ポインタ」という1点を握れば、強み・弱み・代替ツールが同じ地図の上に並ぶ
- 内容: 中心図(オブジェクト4種→DAG→ポインタ層)の言語化と、各代替が「どの固定点を動かしたか」の1行対応表で締める
- 根拠: 本文の統合(出典不要)

---

## frontmatter 予定(publish 用)
- title: 上記
- emoji: 🌳(Merkle tree のツリー)
- type: tech
- topics: ["git", "vcs", "lowlevel", "architecture", "jujutsu"]
  - 既存タグ再利用: `lowlevel`, `architecture`(low_layer 既存記事と統一)。`git` は新規だがテーマ中核
- published: false(ユーザー指示があるまで)

## 未確認・断定回避メモ
- 「スナップショット由来の速さ」の定量ベンチは一次資料に無し → 定性表現に留める
- "Merkle DAG/Tree" は一次の git-scm 本文に明示語がない → 「構成要素(ハッシュ参照される不変ノード＋親リンク)はこれであり、一般にこの構造を Merkle DAG と呼ぶ」という書き方にする(用語を一次資料に帰属させない)
