---
title: "Gitは本当はバージョン管理ツールではない — 内容アドレス型ファイルシステムとして読み解く"
emoji: "🌳"
type: "tech"
topics: ["git", "vcs", "lowlevel", "architecture", "jujutsu"]
published: false
---

## この記事について

Git を毎日使っている。`git add` して `git commit` して `git push` する。ブランチを切ってマージして、たまに `rebase` でコンフリクトに溺れる。`.gitignore` も書けるし、`HEAD` という言葉も知っている。

それでも、後輩や同僚から次のように聞かれて、**30 秒で自分の言葉で答えられるか** と言われると、中上級者でも詰まる人は多いはずです。

- 「ブランチを作るのってなんであんなに一瞬なんですか? コピーしてるわけじゃないんですよね?」
- 「`detached HEAD` って結局なんなんですか? どこから来たんですか?」
- 「`rebase` すると“同じ変更”のはずなのに、なんでまたコンフリクトするんですか?」
- 「Git ってどうやって履歴の改竄を検知してるんですか?」
- 「最近よく聞く jj(Jujutsu)って、Git と何が根本的に違うんですか?」

この記事の目的は、**コマンドの使い方を説明することではありません**。`.git` の中身がどういう「形」をしていて、その背後にどんな**設計思想**があるのかを読み解くことです。そして、その1つの形さえ掴めば、上の疑問が全部「バラバラの罠」ではなく**1本の筋**としてつながる、というのを体験してもらうことがゴールです。

先に結論を一文で置いておきます。

> **Git はバージョン管理ツールである前に、「内容によって名前が決まる、不変オブジェクトのファイルシステム」である。** バージョン管理の機能は、その上に薄く乗っている。

対象は以下のような人:

- Git を操作としては使えるが、`.git` の中を覗いたことがない
- branch / merge / rebase を「手順」として覚えていて、内部モデルがない
- 最近の代替ツール(jj, Sapling, Pijul)が「何を変えようとしているのか」を言語化したい

コマンドリファレンス、packfile や delta 圧縮・gc の内部、転送プロトコルの実装には踏み込みません。**メンタルモデルを作ること**に集中します。

---

## 1. Git は「差分」を保存していない

まず、多くの人が持っているであろう前提を1つ崩します。

**Git は「ファイルがどう変わったか(差分)」を保存していません。** 各コミット時点の **スナップショット** を保存しています。

古典的なバージョン管理ツール(RCS, CVS, Subversion など)は、ファイルごとに「初期版＋それに対する差分(delta)の列」として履歴を持っていました。「v3 が欲しければ、初期版に差分1・差分2・差分3を順に当てる」というモデルです。

Git はそうではありません。公式の Pro Git は、はっきりこう書いています。

> Git はデータを変更セット(changeset)や差分の系列としてではなく、**スナップショットの系列(a series of snapshots)** として扱う。
> ([Git Branching - Branches in a Nutshell](https://git-scm.com/book/en/v2/Git-Branching-Branches-in-a-Nutshell))

`git commit` を打つと、Git は内部でこういうことをします。

1. 変更された各ファイルの内容を **blob オブジェクト** として保存する
2. 各ディレクトリの構成(どのファイル名がどの blob か)を **tree オブジェクト** として保存する
3. ルートの tree を指し、メタデータ(著者・日時・メッセージ)と親コミットへのポインタを持つ **commit オブジェクト** を保存する

たとえば 3 つのファイルを最初にコミットすると、リポジトリには **5 つのオブジェクト** ができます。blob が 3 つ(各ファイルの内容)、tree が 1 つ(ディレクトリの中身を列挙したもの)、commit が 1 つ(ルート tree を指すもの)です([Branches in a Nutshell](https://git-scm.com/book/en/v2/Git-Branching-Branches-in-a-Nutshell))。

この `blob` / `tree` という名前は飾りではありません。Pro Git は Git のオブジェクトストアを **「簡略化された UNIX ファイルシステム」** だと説明しています。tree が UNIX のディレクトリエントリに、blob が inode やファイル内容に対応します([Git Internals - Git Objects](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects))。

```
commit  ──> tree (ルートディレクトリ)
              ├─ "README.md"  ──> blob (ファイル内容)
              ├─ "src/"       ──> tree (サブディレクトリ)
              │                     └─ "main.go" ──> blob
              └─ "go.mod"     ──> blob
```

つまり Git の中身は、**ディレクトリとファイルのスナップショットを、そのままオブジェクトとして固めたもの**です。ここが全ての出発点になります。

---

## 2. 名前は「内容」から決まる — コンテンツアドレッシング

次が Git の心臓部です。

これらのオブジェクトの **名前(ID)は、その内容のハッシュそのもの** です。Git は `<タイプ> <バイト長>\0<内容>` という形にしたデータを SHA-1(現在は SHA-256 への移行も進行中。後述)でハッシュし、その 40 桁の 16 進文字列をオブジェクトの名前にします([Git Objects](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects))。

保存先も名前で決まります。`.git/objects/` 配下に、ハッシュの先頭 2 文字をディレクトリ名、残り 38 文字をファイル名として置かれます。

```
.git/objects/bd/9dbf5aae1a3862dd1526723246b20206e5fc37
             ~~ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
             先頭2  残り38文字
```

この「**名前 = 内容のハッシュ**」という方式を **コンテンツアドレッシング(内容アドレス指定)** と呼びます。データベースの世界では content-addressable storage(CAS)です。ここから、Git の重要な性質がほぼ自動的に導かれます。

- **同じ内容なら、必ず同じ名前になる。** だから同一ファイルが複数箇所にあっても、blob は 1 つで済む(自動的な重複排除)。
- **内容が 1 ビットでも変われば、名前が変わる。** つまり「名前を保ったまま中身をすり替える」ことが原理的にできない。
- **オブジェクトは作成後、不変(immutable)。** AOSA(オープンソースアプリケーションのアーキテクチャ)の Git 章は、`.git/objects` を「すべてのオブジェクトが作成後 immutable である Git のオブジェクトデータベース」と定義しています([AOSA: Git](https://aosabook.org/en/v2/git.html))。

そして commit オブジェクトは、**親コミットへのポインタ(ハッシュ)** を持っています。最初のコミットは親 0 個、通常は 1 個、マージは 2 個以上です([Branches in a Nutshell](https://git-scm.com/book/en/v2/Git-Branching-Branches-in-a-Nutshell))。

ここで形が見えてきます。

> ハッシュで名前が付いた不変ノードが、ハッシュで互いを指し合う。commit は tree を指し、tree は blob やサブ tree を指し、commit は親 commit を指す。

これは **ハッシュで連結された有向非巡回グラフ(DAG)** であり、一般にこの構造を **Merkle DAG**(あるいは Merkle ツリー)と呼びます。ブロックチェーンや IPFS と同じ原理です。

この構造の一番おいしい帰結が **整合性** です。あるコミットの中身を 1 文字でも書き換えると、そのコミットのハッシュが変わります。すると、そのコミットを親として指していた次のコミットの中身(=親ハッシュ)も変わり、そのハッシュも変わり……と、**変更が祖先方向に連鎖して全部のハッシュが変わります**。

つまり「履歴の途中をこっそり改竄する」と、それ以降のすべての ID が変わってしまう。だから Git では、コミットハッシュが一致していれば「そのコミットとその全祖先が、ビット単位で同一であること」が暗号学的に保証されます。Git 2.51(2025 年 8 月)のリリースに寄せた解説も、「Git の分散モデルとオブジェクトストアはデータ整合性を保証するよう設計されており、暗号学的ハッシュがその約束の中心にある」と述べています([Help Net Security: Git 2.51 と SHA-256](https://www.helpnetsecurity.com/2025/08/19/git-2-51-sha-256))。

**Git の改竄検知は、追加の機能ではありません。コンテンツアドレッシングという1つの設計の、ただの副作用です。**

---

## 3. 可変なものは、全部「ただのポインタ」

ここまでで「不変オブジェクトの DAG」ができました。でもこれだけでは、固まった過去しか表せません。`main` ブランチが進んだり、`git checkout` で行ったり来たりする「動き」はどこから来るのか。

答えは拍子抜けするほど単純です。

> **動く(可変な)ものは、すべて「どこかのオブジェクトの名前(ハッシュ)を書いた、ただのポインタ」である。**

不変な DAG の世界に、可変なポインタの層を薄く乗せている。これが Git の全体構造です。

### ブランチ = SHA を 1 行書いたファイル

`git branch <名前>` を実行すると、Git は内部的に `update-ref` を呼び、**いま居るコミットの SHA-1 を、新しい参照ファイルに書き込むだけ** です([Git Internals - Git References](https://git-scm.com/book/en/v2/Git-Internals-Git-References))。`refs/heads/main` の中身は、たった 40 文字のハッシュ 1 行です。

ここで冒頭の疑問が 1 つ解けます。「ブランチを作るのはなぜ一瞬か?」——**ファイルを 1 つも複製していないから**です。ファイルに 40 文字書くだけ。だから Git のブランチは「重い分岐」ではなく「軽い付箋」なのです。コミットすると、その付箋(現在のブランチ)が新しいコミットを指すように動きます。

### タグも同じ。違うのは「動かす運用かどうか」

タグも本質は同じで、`git update-ref refs/tags/v1.0 <SHA>` のように、参照ファイルに SHA を書くだけです。ブランチとの違いは「ブランチは進むにつれ動かす」「タグは固定して動かさない」という運用上の約束だけです([Git References](https://git-scm.com/book/en/v2/Git-Internals-Git-References))。

ついでに言うと、タグは commit 以外も指せます。Git 自身のソースリポジトリには、メンテナの GPG 公開鍵を **blob として** 保存してタグ付けした例があり、Linux カーネルには **tree を指す** タグもあります([Git References](https://git-scm.com/book/en/v2/Git-Internals-Git-References))。「参照は何のオブジェクトでも指せるポインタにすぎない」ことがよく分かる例です。

### HEAD = ポインタを指すポインタ、そして detached HEAD

`HEAD` は「いま自分がどこに居るか」を表すファイルです。普段の `HEAD` は、**現在のブランチを指す「シンボリック参照(symbolic reference)」** です。中身はだいたい `ref: refs/heads/main` のようになっていて、「main ブランチを見ろ」と言っているだけ。つまり **ポインタを指すポインタ** です([Git References](https://git-scm.com/book/en/v2/Git-Internals-Git-References))。

では `detached HEAD` とは何か。これは、`HEAD` が **ブランチ参照ではなく、コミットの SHA そのものを直接持っている状態** です。特定のコミットやタグ、リモートブランチを直接 checkout したときに起きます([Git References](https://git-scm.com/book/en/v2/Git-Internals-Git-References))。

つまり「detached(切り離された)」とは、**「ポインタを指すポインタ」だった HEAD が、「直接コミットを指すポインタ」に変わった状態**のことです。怖い特殊状態ではなく、ポインタの参照先が 1 段ショートカットされただけ。ちなみに `HEAD` は `refs/` の外を指すことはできず、`git symbolic-ref HEAD test` のような操作は `Refusing to point HEAD outside of refs/` と拒否されます([Git References](https://git-scm.com/book/en/v2/Git-Internals-Git-References))。

### index = もう 1 つの可変な場所「ステージング層」

最後にもう 1 つ可変なものがあります。`git add` した内容が溜まる場所、**index(ステージングエリア)** です。実体は `.git/index` というファイルで、AOSA はこれを「ローカル作業ディレクトリとローカルリポジトリの間のステージングエリア」と位置づけています([AOSA: Git](https://aosabook.org/en/v2/git.html))。

index があることで、作業ディレクトリでいろいろいじっていても、**関連する変更だけを選んで 1 つの論理的なコミットにまとめる**ことができます。`git add -p` でファイルの一部だけをステージできるのもこのためです([AOSA: Git](https://aosabook.org/en/v2/git.html))。

ここで Git のメンタルマップが完成します。**3 つの場所**があります。

```
[作業ディレクトリ]  --git add-->  [index(ステージング)]  --git commit-->  [オブジェクトDB(不変DAG)]
   可変・編集中                      可変・コミット予定                     不変・確定済み
```

「ワーキングコピー」と「index」という 2 つの可変な場所があり、その外側に不変の DAG がある。この **「index が DAG の外にいる」** という点は、あとで jj を理解するときの決定的な伏線になります。覚えておいてください。

---

## 4. なぜ、この設計だったのか — Linux カーネルという出自

ここまでの「不変 DAG ＋ ポインタ ＋ 分散」は、美しさのために選ばれた設計ではありません。**極端な制約から逆算された結果**です。

Git は 2005 年、Linux カーネル開発のために生まれました。AOSA の Git 章は当時の状況をこう描いています。Linux カーネルコミュニティは、商用プロジェクトとは違って **膨大な数のコミッタを抱え、貢献度も知識レベルもばらつきが極端に大きく**、長年 tarball とパッチのやり取りで保守されていて、ニーズを満たすバージョン管理システムを見つけられずに苦労していた——と([AOSA: Git](https://aosabook.org/en/v2/git.html))。

この状況を出発点にすると、Git の設計はほぼ必然になります。

- 中央サーバを「信頼の中心」にできない(コミッタが多すぎ、信頼度もバラバラ)→ **全員がフル履歴のコピーを持つ分散モデル**にする。
- 誰が触ったか分からないコピーが世界中にある → 内容を**暗号学的ハッシュで縛り**、改竄や破損を検知できるようにする(= コンテンツアドレッシング)。
- 並行作業が大量に走る → マージは**後からやる**前提にし、ブランチを限界まで軽くする。

つまり Git の中心設計は、「Linux カーネルという、信頼が分散し人数がスケールする現場」への解答でした。ここが本記事の蝶番です。**Git の強みと弱みは、別々の話ではなく、この同じ 1 つの設計判断の表と裏**です。次の 2 章で、それを確かめます。

---

## 5. 強み — 全部、同じ 1 点から出てくる

Git の長所は「便利機能の足し算」ではなく、§2・§3 の設計の **帰結** として説明できます。

- **整合性(改竄・破損の検知)**:コンテンツアドレッシングの副作用(§2)。コミットハッシュが、そのコミットと全祖先の同一性を保証する。
- **分散・オフライン作業**:全員がフル履歴を持つので、ネットワークなしでコミット・ブランチ・履歴閲覧ができる。中央サーバは「待ち合わせ場所」にすぎない。
- **超軽量なブランチ**:ブランチは SHA を書いたポインタ(§3)。だから作成・切り替え・破棄が一瞬。「気軽にブランチを切る」という Git 文化そのものが、この設計から生えている。
- **スナップショット由来の自己完結性**:各コミットは「その時点の世界」をまるごと指す(§1)。だから任意の時点を差分の再計算なしに復元できる。

そして意外に思われがちですが、**素の Git は巨大リポジトリにも耐えます**。たとえば「300GB・350 万ファイル・4000 人の開発者が 20 秒ごとに push する」級のリポジトリを扱えるところまで進化してきました([GitButler: 巨大リポジトリ](https://blog.gitbutler.com/git-tips-3-really-large-repositories))。代替ツールの議論でも、「Git は UI は良くないが、**内部モデルは良い**」というのが共通評価です([lobste.rs: Sapling 議論](https://lobste.rs/s/6jllik/sapling_source_control_s_user_friendly))。

——ただし、いまの「巨大リポジトリも扱える」には注釈が付きます。それが次の章です。

---

## 6. 弱み — 同じ設計が、裏目に出るところ

ここが本記事のもう半分です。Git の弱点は「バグ」ではなく、**中心設計を貫いたことのコスト**として理解すると見通しが良くなります。3 つの観点で見ます。

### 6-1. 大規模・巨大バイナリに弱い

Git の前提は「全員がフル履歴を持つ」「コミットはスナップショット」でした。これは裏返すと **「原則、全部を手元に持つ」** ということです。リポジトリが巨大化すると、これが重くのしかかります。

具体的な規模感として、Linux は 4GB 超、Chromium は 20GB 超になり、Chromium のフルクローンは高速回線でも 1 時間かかることがあります([GitButler](https://blog.gitbutler.com/git-tips-3-really-large-repositories))。

巨大**バイナリ**はさらに相性が悪い。コンテンツアドレッシングは「1 ビット違えば別オブジェクト」なので、少しずつ変わる大きなバイナリは、版ごとに丸ごと別 blob として溜まっていきます。GitLab のドキュメントは「10MB を超える blob があると、サーバ・クライアント双方で問題を起こしうる」と警告しています([GitLab: monorepo](https://docs.gitlab.com/user/project/repository/monorepos))。対症療法が **Git LFS** で、これは大きなファイルを外部ストレージに置き、リポジトリには **ポインタだけ** を残します([GitLab](https://docs.gitlab.com/user/project/repository/monorepos))。

そして Git は、自身の中心設計である「全部持つ」を、後付けで崩す装置をいくつも導入してきました。

- `git clone --filter=blob:none`(blob を落とさない)/ `--filter=tree:0`(tree も落とさない)= **partial clone**
- `git clone --depth=1` = **shallow clone**(履歴を浅く切る)
- `git sparse-checkout`(作業ディレクトリを指定ディレクトリだけに絞る。Git 2.25.0 で導入)

ここが重要なのですが、GitHub の解説はこれらについて **「いずれも Git 本来の分散性の期待を、少なくとも 1 つは壊す」** と明言しています([GitHub Blog: partial/shallow clone](https://github.blog/open-source/git/get-up-to-speed-with-partial-clone-and-shallow-clone))。たとえば shallow clone では `git blame` や完全な `git log` ができなくなります([GitButler](https://blog.gitbutler.com/git-tips-3-really-large-repositories))。partial clone と sparse-checkout を組み合わせれば必要な blob だけ取得してさらに速くできますが([GitHub Blog: sparse-checkout](https://github.blog/open-source/git/bring-your-monorepo-down-to-size-with-sparse-checkout))、いずれも **「分散・自己完結」という Git の核を一部返上する** トレードオフなのです。

「素の Git は巨大リポジトリも扱える」(§5)と「Git は大規模に弱い」(ここ)は矛盾しません。**核となる設計を一部諦めれば扱える**、というのが正確な姿です。

### 6-2. UX とメンタルモデルが難しい

Git は「内部モデルは良いが、ユーザーインターフェースはかなり悪い」と評されます([lobste.rs](https://lobste.rs/s/6jllik/sapling_source_control_s_user_friendly))。これは好みの問題というより、構造に根があります。

- **plumbing と porcelain の二層**:`update-ref` や `hash-object` のような低レベルコマンド(plumbing)の上に、`commit` や `pull` のような高レベルコマンド(porcelain)が乗っている。歴史的経緯でコマンド体系に一貫性がなく、同じ操作に複数の道がある。
- **index という「第 3 の場所」**:作業ディレクトリでもリポジトリでもない中間状態(§3)。便利だが、初学者の混乱の最大の発生源でもある。
- **ブランチが「ただのポインタ」であること自体の分かりにくさ**:仕組みを知らないと、ブランチを「もの」だと思ってしまい、`detached HEAD` やリモート追跡ブランチで迷子になる。

巨大企業も例外ではありません。Microsoft も Google も巨大リポジトリへ Git をスケールさせるのに多大な労力を割きましたが、その結果は「**mixed success(まちまちの成果)**」と総括されています([lobste.rs](https://lobste.rs/s/6jllik/sapling_source_control_s_user_friendly))。

### 6-3. 履歴の書き換えとコンフリクトが本質的に苦手

冒頭の「`rebase` すると“同じ変更”のはずなのに、なぜまたコンフリクトするのか」に答えます。

§2 を思い出してください。コミットは「内容のハッシュ」で名前が決まる **不変** オブジェクトでした。`rebase` や `cherry-pick` は、コミットの土台(親)を付け替える操作ですが、親が変われば内容が変わり、**ハッシュも変わります**。つまり Git は、見た目が「同じ変更」でも、**毎回まったく別のオブジェクトを作り直している**のです。

この「同一性が保てない」ことが厄介を生みます。Pijul の解説は、Git/Mercurial では cherry-pick したコミットの表現が変わるため、同じ枝からさらに cherry-pick すると **「人工的なコンフリクト(artificial conflicts)」** が生じる、と指摘します([Pijul: model](https://pijul.org/model))。rebase でコンフリクト解決をやり直させられるのも、根は同じです。

さらに Git では、コンフリクトは **「作業を止めるエラー状態」** として扱われます。`git rebase main` でコンフリクトが起きると `CONFLICT: Automatic merge failed` となり、全部解決するまで操作の途中で **行き詰まる(stuck)** ([Level Up: jj 解説](https://levelup.gitconnected.com/jujutsu-vcs-a-git-compatible-revolution-in-version-control-620f9d3306fe))。そしてコンフリクトは、コミットのような一級のオブジェクトではなく、ファイルに書き込まれた **ただのテキスト diff** として表現されます([jj README](https://github.com/jj-vcs/jj))。この点は §7 で jj がひっくり返すので、覚えておいてください。

### 6-4.(軽く)SHA-1 から SHA-256 へ

整合性の土台だったハッシュにも宿題があります。Git は 2005 年以来 SHA-1 を使ってきましたが、SHA-1 には衝突攻撃が実証されました([Help Net Security](https://www.helpnetsecurity.com/2025/08/19/git-2-51-sha-256))。Git は 2017 年に衝突検知付きの SHA1DC で当座をしのぎ([Stack Overflow: SHA1DC](https://stackoverflow.com/questions/60087759/))、より根本的には **SHA-256 への移行** を段階的に進めています(Git 2.51, 2025 年)([Help Net Security](https://www.helpnetsecurity.com/2025/08/19/git-2-51-sha-256))。

SHA-1 名は 40 桁、SHA-256 名は 64 桁の 16 進です([hash-function-transition](https://git-scm.com/docs/hash-function-transition))。ただし `git init --object-format=sha256` で作れるとはいえ、デフォルトは依然 `sha1` で、**現時点では SHA-256 リポジトリと SHA-1 リポジトリの相互運用には制約があります**([git-init docs](https://git-scm.com/docs/git-init/2.47.0))。「コンテンツアドレッシングはハッシュ関数に運命を握られている」という、設計の弱点というより構造上の宿命です。

---

## 7. 代替ツール — 「Gitのどの固定点を動かしたか」で読む

ここからが本記事の締めです。Git の代替として打ち出されたツールは、「Git の全否定」ではありません。**Git が当然としている前提(固定点)を、1 つだけ動かした実験**として読むと、一望できます。

主役は **jj(Jujutsu)** です。残りは「どの固定点を動かしたか」だけ短く触れます。

### 7-1. jj(Jujutsu)— 「ワーキングコピーは履歴の外」をやめた

jj が動かした固定点は 2 つあります。

**固定点①「ワーキングコピーと index は DAG の外にいる」(§3)→ 「ワーキングコピー = コミット」にする。**

jj では、作業ディレクトリの状態が **常に 1 つのコミットとして自動的に記録** されます。ファイルを編集するたび、その変更は現在の作業コピーコミットに自動で取り込まれます。jj の README は、この設計が「データモデルを単純化し、Git の stash や index/staging-area を完全に**包含(subsume)**する」と説明しています([jj README](https://github.com/jj-vcs/jj))。`git add` に相当する操作が要りません。変更すれば、それはもうコミットの中にいます([Zenn: jj 入門](https://zenn.dev/usamik26/articles/jj-version-control))。

§3 で「index が DAG の外にいるのが伏線」と書いたのは、これです。jj は **その外側の可変領域(作業コピーと index)を、DAG の中(コミット)に取り込んでしまった**。これ 1 つで、stash も staging も「特別な状態」ではなくなります。

**固定点②「コンフリクトは作業を止めるエラー」(§6-3)→ 「コンフリクトを一級のオブジェクトにする」。**

jj はコンフリクトを、コミットと同じ意味での **first-class なオブジェクト** としてモデルに保持します([jj README](https://github.com/jj-vcs/jj))。コンフリクトはコミットグラフの一部として保存されるので、コンフリクトしたまま別の作業に切り替え、後で戻って解決する、ということができます。コンフリクトはもう「行き詰まり」ではなく、「未解決という状態を持ったコミット」になります([Kunal Ganglani: jj](https://www.kunalganglani.com/blog/jujutsu-jj-git-version-control))。

これらに加えて jj は、

- **operation log と `jj undo`**:コミット・pull・push などリポジトリへの全操作を記録し、rebase の失敗や誤マージ、誤った履歴書き換えを `jj undo` で取り消せる([jj README](https://github.com/jj-vcs/jj) / [Kunal Ganglani](https://www.kunalganglani.com/blog/jujutsu-jj-git-version-control))。§6-3 の「Git は履歴操作の取り消しが難しい」への直球の回答です。
- **匿名ブランチがデフォルト**:ブランチ名を考えずに作業でき、名前は必要になってから付ける([Zenn: jj 入門](https://zenn.dev/usamik26/articles/jj-version-control))。

そして jj の最も賢いところは、**これらを Git の上に乗せた**点です。jj には独自バックエンドもありますが、ほとんどのユーザーは **Git バックエンド** を使い、jj は同じ `.git` ディレクトリを読み書きします([Tony Finn: jj](https://tonyfinn.com/blog/jj))。作った変更は普通の Git コミットに見え、任意の Git リモートと fetch/push でき、いつでも Git に戻れます([jj README](https://github.com/jj-vcs/jj))。**チームメイトは Git のまま、自分だけ同じリポジトリで jj** という共存ができる([Kunal Ganglani](https://www.kunalganglani.com/blog/jujutsu-jj-git-version-control))。

つまり jj は「Git を置き換える」のではなく、**§2 の優れたオブジェクトモデル(Merkle DAG)はそのまま使い、§3 と §6-3 のつらい部分(index・stash・コンフリクト・undo)だけを再設計した上位レイヤー**だと読めます。

### 7-2. Pijul — 「スナップショット」をやめてパッチの代数にした

Pijul が動かした固定点は、もっと深いところ、**§1 の「スナップショット」そのもの**です。Pijul はスナップショットの系列ではなく、**パッチ(変更)の理論** に立っています。「ブランチとは、ちょうどパッチの集合である」とされます([Pijul: model](https://pijul.org/model))。

肝は **可換性(commutation)** です。独立した変更どうしは、適用順によらず同じ結果・同じ識別子になるよう数学的に設計されています(圏論の pushout に着想)([Pijul](http://pijul.org))。これにより、§6-3 で見た「cherry-pick で人工的なコンフリクトが起きる」問題が **そもそも発生しません**([Pijul: model](https://pijul.org/model))。理論的な美しさで言えば最右翼ですが、UX には「扱いにくく不透明」という賛否もあり、まだ広くは使われていません([Pijul Discourse](https://discourse.pijul.org/t/pijul-as-first-version-control-system/810))。

### 7-3. Sapling(Meta)— モデルは残し、UX を作り直した

Sapling は Meta(Facebook)発で、Git 互換系の中で「最も成熟している」と評されます([Tony Finn: jj](https://tonyfinn.com/blog/jj))。動かしたのは内部モデルではなく **UX** です。Meta のエンジニアリングブログは「**ステージングエリアがない**。各コマンドは 1 つのことだけをする。ローカルブランチ名は任意」と、Git の引っかかりどころを次々に外していると述べています([Meta Engineering: Sapling](https://engineering.fb.com/2022/11/15/open-source/sapling-source-control-scalable))。ステージングが欲しければ対話的コミットや一時コミットで代替できます([Sapling docs: Git との違い](https://sapling-scm.com/docs/introduction/differences-git))。「内部モデルは良いが UI が悪い」(§6-2)への、UX 側からの回答です。

### 7-4. Mercurial / Fossil — 別の方向に振った同時代人

- **Mercurial**:Git とほぼ同年代で、UX は明らかに Git より良かったと言われますが、普及競争に敗れました。Git ホスティング(GitHub 等)の支配が決定打でした([lobste.rs](https://lobste.rs/s/6jllik/sapling_source_control_s_user_friendly))。内部モデルは Git と同じ state-based です。
- **Fossil**:思想が逆向きです。Git が「分散の最小核」に徹したのに対し、Fossil は **VCS にチケット・Wiki・フォーラム・Web UI までを 1 つの自己完結した実行ファイルに統合** し、データストアに SQLite を使います([Fossil vs Git](https://fossil-scm.org/home/doc/tip/www/fossil-v-git.wiki))。「ツールを足し算する Git エコシステム」への、「全部入り」というアンチテーゼです。

---

## 8. まとめ — 1 枚の地図

長くなったので、1 枚の地図に畳みます。Git の全体像は、これだけです。

```
■ 不変の層(オブジェクトDB / Merkle DAG)= 「内容アドレス型ファイルシステム」
    blob(ファイル内容)・tree(ディレクトリ)・commit(スナップショット+親)・tag
    名前 = 内容のハッシュ → 同一性・重複排除・改竄検知が“タダで”付いてくる

■ 可変の層(ポインタ)
    branch / tag / HEAD = SHA を書いたただの参照 → ブランチが軽い理由
    index = DAG の外にある第3の場所 → ステージングの便利さと分かりにくさ
```

この 1 点——**「内容で名前が決まる不変オブジェクトの DAG ＋ その上の可変ポインタ」**——さえ握れば、本記事で見たことが全部、同じ地図の上に並びます。

- ブランチが軽いのは、ブランチがポインタだから(§3)
- 改竄を検知できるのは、名前が内容のハッシュだから(§2)
- `detached HEAD` は、HEAD が直接コミットを指しただけ(§3)
- `rebase` でまたコンフリクトするのは、不変オブジェクトを作り直しているから(§6-3)
- 巨大リポジトリに弱いのは、「全部持つ分散」を貫いているから(§6-1)

そして代替ツールは、**この地図のどの固定点を動かしたか**で読めます。

| ツール | 動かした固定点 |
| --- | --- |
| **jj** | 「ワーキングコピー/index は DAG の外」→ ワーキングコピー = コミット。「コンフリクト = エラー」→ 一級オブジェクト |
| **Pijul** | 「スナップショット」→ パッチの代数(可換) |
| **Sapling** | 内部モデルは維持、UX を作り直す(staging なし等) |
| **Fossil** | 「分散の最小核」→ チケット/Wiki/UI まで全部入り |

Git を「コマンドの手順」として覚えると、振る舞いはバラバラの暗記になります。でも「内容アドレス型ファイルシステム」という 1 つのメンタルモデルから見ると、強みも弱みも、そして次の世代のツールが何を変えようとしているのかも、ひとつの筋として見えてきます。

`.git` の中は、思っているよりずっと単純で、ずっと深い。
