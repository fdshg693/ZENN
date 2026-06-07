---
title: "真実はどこにある？ — 宣言的×状態保持の2軸で読むTerraform・ARM・Bicep・Ansible"
emoji: "🗺️"
type: "tech"
topics: ["iac", "terraform", "bicep", "ansible", "azure"]
published: false
---

## この記事について

あなたは ARM テンプレートや Bicep を書いてデプロイできる。Terraform も `apply` できる。Ansible の playbook も流せる。

でも、こう聞かれたら答えられるだろうか。

- Terraform には `terraform.tfstate` というファイルがあるのに、**なぜ ARM や Bicep には state ファイルが無い**のか？
- なぜ Terraform は state ファイルを壊すと事故になるのに、**Bicep は state を気にしなくていい**のか？
- 結局、コードに書いた1行は **どうやって実際のクラウドリソースに結びついている**のか？

これらは「ツールの使い方」を覚えても出てこない。各ツールが内部で前提にしている **「真実(SSOT, Single Source of Truth)をどこに置くか」** という設計判断の違いだからだ。

この記事は、ARM / Bicep / Terraform / Ansible の構文を比較しない。代わりに **1枚の地図**を用意して、「真実をどこに置くか」という1つの軸で全部を並べ直す。地図ができれば、Pulumi でも CloudFormation でも、まだ知らないツールでも、自分で置けるようになる。

:::message
扱わないこと: 各ツールの文法・関数・モジュールの細かい違い、CI/CD パイプラインの組み方、価格や SKU の比較。ここで欲しいのは「IaC と言ったとき内部で何が起きているか」の見取り図です。
:::

## まず足場を固める — Bicep / Terraform / Ansible を思い出す

地図に入る前に、3つのツールの記憶を呼び戻しておこう。インストールや基本文法はやらない。代わりに各ツールを **「普段こう使う → 裏でこう動く → だいたいここでハマる」** の3点で復習する。「触ったことはあるけど細かい概念は忘れた」状態から、本編の地図に乗れる状態まで戻すのが目的だ。

### Terraform — `plan` と `apply` の往復、そして state

**普段の使い方。** ディレクトリに `.tf` ファイルを置き、`terraform init`（プロバイダと backend の初期化）→ `terraform plan`（差分プレビュー）→ `terraform apply`（適用）を回す。日々触っているのはこのループだ。

```bash
terraform init     # プロバイダ取得 + backend 初期化
terraform plan     # 差分を表示（まだ何も変えない）
terraform apply    # 差分を実インフラに適用
```

**裏で何が起きているか。** `apply` のたびに Terraform は `terraform.tfstate` を更新する。これは「コードに書いた `azurerm_resource_group.main` が、実際のどのリソースか」を記録した **対応表（台帳）** だ。`plan` は実は **この state とコードを突き合わせて** 差分を出している——毎回クラウドに全部問い合わせているわけではない。だから state はただのキャッシュではなく、**Terraform にとっての「現実の代理」** になっている。

**よくハマるところ。**

- **state ロックで止まる**: チームで使うと、リモートバックエンド（S3 / Azure Blob 等）に置いた state を **lock** して同時 apply を防ぐ。誰かの実行が異常終了するとロックが残り、`Error acquiring the state lock` で動けなくなる。フル機能の backend は処理中に state をロックして競合・不整合を防ぐ仕組みだ[^tf-purpose]。
- **手動変更でドリフト**: ポータルで手作業で設定を変えると、state とのズレ（ドリフト）が生まれる。Terraform は「コードの各リソースと実体の **1対1対応**」を前提にしており、`terraform import` で取り込んだり `terraform state rm` で手を入れたりしたときは、その1対1を保つのは **あなたの責任** になる[^tf-state]。
- **ローカル state をチームで共有して事故る**: state はデフォルトで実行ディレクトリのローカルファイルに置かれる[^tf-purpose]。これを Git に入れたり各自バラバラに持ったりすると、すぐ壊れる。だから「リモートバックエンドに1つ」が定石になる。

### Bicep（と ARM）— `what-if` してデプロイ、state は無い

**普段の使い方。** `.bicep` ファイルを書き、`az deployment group create`（リソースグループへのデプロイ）で流す。事故を避けたいときは先に `what-if` で差分を見る。

```bash
az deployment group what-if \   # 何が変わるか予測（変更は加えない）
  --resource-group rg-demo --template-file main.bicep
az deployment group create \    # デプロイ（モード未指定なら incremental）
  --resource-group rg-demo --template-file main.bicep
```

**裏で何が起きているか。** Bicep ファイルは、デプロイ時に **ARM の JSON テンプレートに変換** され、実際のデプロイは Azure Resource Manager が行う[^bicep-overview]。Terraform と違い **state ファイルは無い**。代わりに「テンプレート（あるべき姿）」と「クラウドの現状」を比べる **incremental デプロイ** に依存する[^bicep-cmp]。手元に台帳を持たず、現状はクラウドに聞く。

**よくハマるところ。**

- **「消したはず」のリソースが残る**: デフォルトの incremental モードは、**テンプレートに書かれていない既存リソースを削除しない**[^arm-modes]。Bicep から定義を消しても、クラウド上のリソースはそのまま残る。「コードから消えた＝消える」ではない点で Terraform 感覚だと戸惑う。
- **complete モードで消しすぎる**: その逆に complete モードはテンプレートに無いものを **削除する**[^arm-modes]。意図せず巻き込み削除しやすいので、公式も complete の前に `what-if` を推奨している。
- **what-if のノイズ**: what-if は `reference` 関数を解決できず、`reference` を含む式は **毎回「変わる」と表示** される[^whatif]。「差分ゼロのはずなのに毎回差分が出る」と悩むのはたいていこれ。

### Ansible — inventory と playbook、毎回が初回のように振る舞う

**普段の使い方。** `inventory`（対象ホスト一覧）と `playbook`（あるべき状態を書いた YAML）を用意し、`ansible-playbook` を流す。様子見したいときは `--check`（dry run）。

```bash
ansible-playbook -i inventory.ini site.yml --check  # dry run
ansible-playbook -i inventory.ini site.yml          # 実行
```

**裏で何が起きているか。** Ansible は **state ファイルを持たない**。各モジュールが **冪等(idempotent)** で、実行のたびに **実機の現在状態を見て**、あるべき姿と違えば直す[^ansible-glossary]。コントロールノードからモジュールを各ホストにコピーして実行し、エージェントは常駐させない（agentless）[^ansible-basic]。「コードと実機の対応」を担うのは state ではなく **inventory** だ。

**よくハマるところ。**

- **冪等じゃないモジュールがある**: 「2回流せば同じ」は理想で、モジュール次第で崩れる。公式にも「**冪等性を達成する信頼できる方法がない**ため毎回コピーが走る」と注記されたモジュールがある[^ansible-ovirt]。冪等性は仕組みで保証されるのではなく、モジュールの作り込みに依存する。
- **順序と handler で「2回目が違う」**: Play は **順序付きタスクリスト** で、handler は前タスクが `changed` のときだけ発火する[^ansible-basic]。書き方によって実行順や通知に依存し、「1回目と2回目で挙動が違う」が起きる。宣言的に見えて手続き的な側面がここに出る。
- **`--check` を信じすぎる**: `--check` は実機を変えずに差分を見せるが、公式は「予期せぬコマンド失敗や cascade effect は考慮されず、良いステージング環境の代わりにはならない」と釘を刺している[^ansible-glossary]。

### 3つを並べて見えてくること

同じ「インフラをコードで管理する」のに、3つは「**"今あるもの"の記録を誰が持つか**」がまるで違う。

- Terraform は **自前の台帳(state)** を真実にし、それゆえロックやドリフトと戦う。
- Bicep/ARM は台帳を持たず、**クラウドが保持している資源モデル** を真実にし、それゆえ incremental の残留や complete の削除に戸惑う。
- Ansible は台帳も中央のモデルも持たず、**毎回実機を評価する**。それゆえ state を持たない代わりに冪等性とにらめっこする。

つまり「ハマりどころ」すら、各ツールが **真実(SSOT)をどこに置いたか** の裏返しになっている。ここから先は、この「真実の置き場所」を正面から軸にして地図を描く。

## IaC が内部でやっている3つのこと

ツールがどれだけ違って見えても、IaC が裏でやっていることは3ステップに分解できる。

1. **あるべき姿を表現する** — 「VM が1台、こういう設定で存在してほしい」をコードに書く
2. **現状を知る** — 今クラウド（や対象マシン）はどうなっているかを取得する
3. **差分を埋める** — 1 と 2 の差を計算し、必要なAPIを叩いて寄せる

面白いのは、ツールごとに本質的に違うのは **2番「現状をどこから取るか」だけ** だということ。1（書き方）や3（差分適用）は表面的な違いに過ぎない。そして「現状をどこから取るか」は、言い換えれば **「何を真実(SSOT)として信じるか」** という問いそのものだ。

ここが、この記事全体を貫く1本の軸になる。

## 座標系を入れる — 宣言的 × 状態保持の2軸

真実の置き場所は「**"今あるもの"の権威ある記録（＝SSOT）を、誰が保持するか**」で3つに分かれる。「状態ファイルの有無」ではないことに注意してほしい——下の①と③はどちらも自前の状態ファイルを持たないが、それでも本質が違う。

- **① クラウドが保持** — 自分は台帳を持たない。クラウドの制御プレーンが資源モデル（把握しているリソースの一覧・構成）を持っていて、問い合わせれば一貫した現状を返す
- **② 自分が保持** — `tfstate` という外部台帳を自分で持ち、それを正と信じる
- **③ 誰も保持しない** — どこにも記録が無く、毎回ゼロから実機の個別属性を評価して判定する

①と③の差は「クラウドか実機か」という**管理対象**の違いではない。**「何があるか」を把握している中央の権威（クラウドの制御プレーン）が居るか／居ないか**の違いだ。①ではクラウドがモデルを持つから問い合わせれば済む。③では誰もモデルを持たないから、毎回ホストを覗いて再構築するしかない。

これを縦軸に、「あるべき姿を**宣言的**に書くのか／**手続き的**に手順を書くのか」を横軸に取ると、4ツールはこう置ける。

```
                宣言的(あるべき姿)            手続き的(手順)
              ┌────────────────────────┬────────────────────────┐
クラウドが    │  ARM / Bicep           │                        │
モデルを保持  │  自分は台帳を持たない  │                        │
              ├────────────────────────┼────────────────────────┤
自分が台帳で  │  Terraform             │                        │
モデルを保持  │  tfstate が対応表       │                        │
              ├────────────────────────┼────────────────────────┤
誰も保持せず  │           Ansible       (宣言的に書けるが…       │
毎回実機評価  │  冪等モジュール ┄┄┄┄┄┄→  順序実行で手続き的)      │
              └────────────────────────┴────────────────────────┘
```

ARM/Bicep/Terraform はきれいにマスに収まる。一方 **Ansible だけは「宣言的に書けるのに、順序実行で手続き的に振る舞う」ため、1つのマスに収まらず横軸をまたぐ**。この「収まらなさ」こそが、軸が捉えている空間の広さを教えてくれる。だから Ansible は後で「境界事例」として扱う。

以下、3つのパターンを順に見ていく。

## パターン①: クラウドがモデルを保持 — ARM / Bicep

ARM テンプレート（JSON）と Bicep は、**自分では state ファイルを持たない**。代わりに真実を預ける先が **Azure Resource Manager（ARM）** だ。ARM は「このリソースグループに何があるか」を把握している制御プレーンなので、問い合わせれば一貫した現状が返ってくる。自前の台帳を持たずに済むのは、**クラウド側が資源モデルを保持してくれている**からだ。

なぜそれで成立するのか。デプロイの挙動を見ると分かる。ARM のデプロイには2つのモードがあり、**デフォルトは incremental（増分）モード**だ[^arm-modes]。

- **incremental**: テンプレートに書いたリソースを作成・更新する。テンプレートに**書かれていない**既存リソースは、リソースグループに残っていても **そのまま残す**。
- **complete**: テンプレートに書かれていないリソースは **削除する**。

[^arm-modes]: [Azure Resource Manager deployment modes](https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/deployment-modes)。"The default mode is incremental." と明記。complete モードは意図しない削除を避けるため、適用前に what-if を実行するよう公式が推奨している。なお complete モードは段階的に非推奨化され、リソース削除には deployment stacks の利用が推奨されつつある。

両モードに共通するのは、**既存リソースが設定変更なしなら何もしない（no operation）** という挙動だ。つまり ARM は「テンプレート（あるべき姿）」と「クラウドの現状」を比べて差分を出している。**現状はクラウドに聞けば分かるので、手元に台帳を持つ必要がない。**

```bash
# 既存リソースは残しつつ、テンプレート分を反映（デフォルト=incremental）
az deployment group create \
  --resource-group rg-demo \
  --template-file main.bicep \
  --mode Incremental
```

差分計算が **どこで行われるか** も重要だ。公式の Terraform 比較ドキュメントは、Bicep について「処理は **core Azure infrastructure service 側** で行われる（preflight でポリシーチェックなどが可能）」と説明している[^bicep-cmp]。クライアントは「あるべき姿」を送るだけで、差分判断はクラウド側がやる。

[^bicep-cmp]: [Comparing Terraform and Bicep](https://learn.microsoft.com/en-us/azure/developer/terraform/comparing-terraform-and-bicep)。「Like Terraform, Bicep is declarative and goal-seeking. **However, Bicep doesn't store state. Instead, Bicep relies on incremental deployment.**」「In Bicep, the processing is done by the core Azure infrastructure service」と明記（訳: Terraform と同様 Bicep も宣言的でゴール志向だが、Bicep は state を保存せず incremental デプロイに依存する。Bicep では処理は core Azure インフラサービス側で行われる）。

### Bicep と ARM は同じパターン

Bicep は ARM とは別のツールに見えるが、立ち位置は同じだ。公式は Bicep を **「ARM JSON テンプレートに対する透過的な抽象化（transparent abstraction）」** と表現し、**デプロイ時に Bicep CLI が Bicep ファイルを ARM JSON テンプレートに変換する** と述べている[^bicep-overview]。つまり Bicep は読みやすい皮で、エンジンは ARM そのもの。2軸地図では同じマスに入る。

[^bicep-overview]: [Bicep overview](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/overview)。「Bicep is a transparent abstraction over a Resource Manager JSON template」「During deployment, the Bicep CLI converts a Bicep file into a Resource Manager JSON template.」（訳: Bicep は Resource Manager JSON テンプレートに対する透過的な抽象化であり、デプロイ時に Bicep CLI が Bicep ファイルを Resource Manager JSON テンプレートに変換する）。また Bicep ファイルは idempotent（冪等）で、同じファイルを何度デプロイしても同じ状態になる、とある。

**このマスのまとめ**: 宣言的に「あるべき姿」を書く。自前の state ファイルは無く、資源モデルを保持するのはクラウドの制御プレーン。だから差分もクラウド側が計算する。

## パターン②: 自分が台帳でモデルを保持 — Terraform

Terraform は、ここが決定的に違う。**`terraform.tfstate` という台帳を別ファイルとして持ち、それを真実として信じる。**

state が保持しているのは、**設定中の resource instance と、リモートにある実体オブジェクトの1対1の対応表**だ。たとえば設定の `aws_instance.foo` が、AWS 上のインスタンス ID `i-abcd1234` を指す——この紐付けを state が記録する[^tf-purpose]。加えてリソース間の依存関係などのメタデータも保持する。

[^tf-purpose]: [Purpose of Terraform State](https://developer.hashicorp.com/terraform/language/state/purpose)。Terraform は config を実世界にマップするため「ある種のデータベース」を必要とする、と説明。

なぜわざわざ台帳を持つのか。公式の経緯が示唆的だ。**Terraform の初期プロトタイプは state ファイルを持たず、AWS のタグでリソースを識別していた。** だが「すべてのリソースがタグをサポートするわけではなく、すべてのクラウドがタグをサポートするわけでもない」という問題にすぐ突き当たり、独自の state 構造を採用した[^tf-purpose]。

これは ARM/Bicep との対比をはっきりさせる。ARM は Azure 専用なので「クラウドに聞けば現状が分かる」を前提にできる。Terraform は **多数のプロバイダを横断する**ので、共通の問い合わせ手段を当てにできない。だから **自前で台帳を持つ** ——これが state の正体だ。

その帰結として、差分計算は **クライアント側** で行われる。`terraform plan` は **state と HCL（あなたのコード）を突き合わせて** 差分を出す。Terraform は「現状を知るための呼び出し」に頼らず、手元の state を現実の代理として使う[^bicep-cmp]。

```hcl
# state の保存先（リモートバックエンド）を宣言
terraform {
  backend "azurerm" {
    resource_group_name  = "rg-tfstate"
    storage_account_name = "sttfstate"
    container_name       = "state"
    key                  = "prod.tfstate"
  }
}
# plan: state + コード を突き合わせて差分を出す → apply で適用
```

### state を持つことの「脆さ」

台帳を真実にする以上、**台帳が現実とズレると壊れる**。Terraform は「設定された各 resource instance と実体オブジェクトの1対1対応」を期待しており、`terraform import`（外部で作られたものを取り込む）や `terraform state rm`（忘れさせる）で state を手で触った場合、この1対1を保証するのは **ユーザーの責任** になる[^tf-state]。

[^tf-state]: [State](https://developer.hashicorp.com/terraform/language/state)。「Terraform expects each remote object to be bound to only one resource instance」。

そして state は、デフォルトでは **実行ディレクトリ内のローカルファイル**に置かれる[^tf-purpose]。1人なら問題ないが、チームでは全員が同じ state を共有しないと破綻する。だから次章のチーム管理で見るように、**リモートバックエンド + state locking** が事実上必須になる。`backend` ブロックは「state をどこに保存するか」を定義するもので、デフォルトは `local`（ディスク上のファイル）だ[^tf-backend]。

[^tf-backend]: [Backend configuration](https://developer.hashicorp.com/terraform/language/backend)。1つの設定が持てる backend は1つだけ、という制約もある。

**このマスのまとめ**: 宣言的に書く。だが真実は別ファイルの台帳。台帳ゆえに差分はクライアント側で速く出せるが、台帳と現実のズレ・共有・ロックを自分で面倒みる必要がある。

## 境界事例: 誰もモデルを保持しない — Ansible

Ansible は2軸地図のどのマスにもきれいに収まらない。だから面白い。

まず縦軸。Ansible は **state ファイルを持たない**——が、それだけなら ARM/Bicep も同じだ。「自前の台帳が無い」は両者で共通で、ここを違いだと思うと混乱する。決定的に違うのは、**ARM のような「資源モデルを保持する中央の制御プレーン」がどこにも無い**ことだ。クラウドは自分の資源を把握しているシステムなので Bicep はそれに問い合わせられるが、素の対象ホストには「何が設定されているか」の台帳も登録簿も存在しない。だから Ansible は誰にも問い合わせられず、各モジュールが **冪等(idempotent)** に作られていて、実行のたびに **実機の現在状態を直接評価し、あるべき姿に収束させる**しかない。公式の例がわかりやすい——`file` モジュールは「`/etc/motd` の owner が `root` でなければ `root` にし、mode が `0644` でなければ `0644` にする」。実際の属性を**毎回見て**、違えば直すだけだ[^ansible-glossary]。台帳は要らない。真実は常に対象マシンの今の状態にある。

[^ansible-glossary]: [Ansible glossary](https://docs.ansible.com/projects/ansible/latest/reference_appendices/glossary.html)。idempotency の定義（1回の実行と、間に何もせず繰り返した実行の結果が同一）、resource model が冪等であること、`--check`（dry run）モードを説明。

```yaml
# 「mode と owner はこうあるべき」を宣言（手順ではない）
- name: motd を正しい状態にする
  ansible.builtin.file:
    path: /etc/motd
    owner: root
    mode: "0644"
# ansible-playbook --check で dry run（実機を変えずに差分だけ表示）
```

ここまでは宣言的に見える。ところが横軸では手続き的な顔を出す。Ansible の Play は **順序付きのタスクリスト** であり、handler（特殊なタスク）は「前のタスクが `changed` になったとき」にだけ発火する[^ansible-basic]。つまり「あるべき姿の集合」ではなく「上から順に流す手順」の性質を持つ。だから2軸地図で **宣言的と手続き的をまたぐ**。

[^ansible-basic]: [Ansible basic concepts](https://docs.ansible.com/projects/ansible/latest/getting_started/basic_concepts.html)。Play は順序付きタスクリスト、handler は `changed` で発火、modules は各ノードにコピーして実行、通常 managed node にエージェントを常駐させない（agentless）こと、inventory がホスト一覧であることを説明。

そして「コードと実機の対応付け」も独特だ。Terraform のような state も、ARM のような type+name 解決もない。**対象は inventory（ホスト一覧）で指定し、リソースの一致は毎回実機を評価して判定する**。エージェントを常駐させない（agentless）。

冪等性は便利だが、**常に保証されるわけではない**点も「状態を持たない」ことの代償だ。たとえば oVirt の `ovirt_disk` モジュールには「**冪等性を達成する信頼できる方法がない**ため、このパラメータを指定するたびにディスクがコピーされる。毎回コピーしないよう playbook 側で対処せよ」と公式に注記がある[^ansible-ovirt]。台帳が無いぶん、冪等かどうかはモジュールと操作の作り込みに依存する。

[^ansible-ovirt]: [ovirt_disk module](https://docs.ansible.com/projects/ansible/latest/collections/ovirt/ovirt/ovirt_disk_module.html)。

**このマスのまとめ**: 中央のモデルを誰も持たず、毎回実機そのものを真実として評価する。宣言的に書けるが順序実行するため横軸をまたぐ。だからこそ「モデルを誰が持つか」「宣言的/手続き的」という軸の存在が浮かび上がる。

## 横串①: コードからインフラへの「対応付け」3方式

ここまでを踏まえると、冒頭の問い「**コードの1行は、どうやって実リソースに結びつくのか**」に3通りの答えが見える。

| 方式 | ツール | 「この1行はどのリソース？」をどう解決するか |
|------|--------|------|
| **state内ID 方式** | Terraform / Pulumi | tfstate という台帳が `アドレス ↔ 実体ID` を記録。台帳を引く。 |
| **API + 名前 方式** | ARM / Bicep / CloudFormation | スコープ(リソースグループ)＋type＋name で、クラウド自身が一意に解決。台帳は要らない。 |
| **inventory + 冪等評価 方式** | Ansible | 対象ホストは inventory で決め、一致は毎回実機の属性を見て判定。 |

「対応付けをどこに持つか」が、そのまま「真実(SSOT)をどこに置くか」と一致しているのが分かる。**台帳(state)を持つツールは台帳が対応表を兼ね、台帳を持たないツールはクラウドや実機に対応付けを肩代わりさせている。**

## 横串②: 差分実行とドリフトの扱い

「適用前に差分を見たい」という要求はどのツールにもあり、それぞれドライランの手段を持つ。

- Terraform: `terraform plan`
- ARM / Bicep: `what-if`（変更を一切加えず、デプロイしたら何が起きるかを予測する）[^whatif]
- Ansible: `--check`

[^whatif]: [Template deployment what-if](https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/deploy-what-if) / [Bicep what-if](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/deploy-what-if)。what-if は既存リソースに変更を加えず予測のみ行う。ただし `reference` 関数は解決できず、`reference` を含む式は毎回「変わる」と報告される、という限界も公式が明記している。

狙いは同じでも、**ドリフト（手作業で変えられた現実とのズレ）の見え方は SSOT で変わる**。

- **Terraform（state が真実）**: state と実体の差として **ドリフトを明示的に検知**できる（refresh）。台帳があるからこそ「台帳と現実がズレた」と言える。
- **ARM / Bicep（クラウドが真実）**: そもそも台帳が無いので「ズレ」という常設の概念が薄い。次のデプロイで宣言に寄せるだけだ。代わりに **デプロイ履歴（誰がいつ何を流したか）が Azure ポータルに残る**[^arm-overview]。
- **Ansible（実機が真実）**: 毎回実機を評価して直すので、ドリフトは「次の実行で勝手に直るもの」。検知の対象というより吸収の対象になる。

[^arm-overview]: [ARM templates overview](https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/overview)。what-if が現状をチェックして「state を管理する必要をなくす（eliminates the need to manage state）」こと、デプロイ履歴をポータルで追跡できることを説明。

つまり「ドリフトをどう扱うか」はツールの優劣ではなく、**SSOT をどこに置いたかの帰結**にすぎない。

## 横串③: チーム管理は「SSOT の所在」で決まる

最後の横串。チーム運用の設計も、突き詰めれば「真実をどこに置いたか」で自動的に決まる。

- **真実が state ファイル（Terraform）** → その1ファイルが競合の火種になる。だから **リモートバックエンド + state locking** で「2人が同時に apply する」事故を止める[^tf-purpose]。state を共有・ロック・レビューする運用がチームの中心課題になる。環境ごとに state を分けたいなら **workspace** で1つの設定に複数 state を関連付けられる[^tf-workspace]。
- **真実がクラウド（ARM / Bicep）** → 共有すべき state ファイルが存在しない。代わりに統制は **Azure RBAC とデプロイ履歴** 側に寄る。デプロイには対象リソースへの write 権限と `Microsoft.Resources/deployments` への操作権限が要る[^arm-rest]。「誰がデプロイできるか」を権限で縛る世界だ。
- **真実が実機（Ansible）** → 共有するのは inventory と playbook。状態の真実は常に対象ホストにあるので、チームが管理するのは「手順とホスト一覧」になる。

[^tf-workspace]: [State: Workspaces](https://developer.hashicorp.com/terraform/language/state/workspaces)。一部の backend は複数の named workspace をサポートし、1つの設定に複数の state を関連付けられる。

[^arm-rest]: [Deploy with REST API](https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/deploy-rest)。デプロイには対象リソースへの write 権限と `Microsoft.Resources/deployments` への全操作権限が必要。

ここまで来ると、最初の地図が効いてくる。**「どこを SSOT にするか」を選ぶことは、そのまま「ロックが要るか／権限で縛るか／何をレビューするか」というチーム運用を選ぶこと**なのだ。

## まとめ — 1枚の地図に戻す

最初の問いに戻ろう。「Terraform には tfstate があるのに ARM には無いのはなぜか」。答えはこうだ。

> **"今あるもの"の権威ある記録を誰が持つかが違うから。** ARM/Bicep はクラウドの制御プレーンが資源モデルを保持しているので、自分の台帳が要らない。Terraform は多数のプロバイダを横断し、どのクラウドにも頼れる共通の問い合わせ手段が無いため、自前の台帳(state)を持つ。Ansible は中央のモデルがどこにも無いので、毎回ゼロから実機を評価する。

そして「SSOT の所在」を決めると、芋づる式に残り全部が決まる。

| | SSOT(モデルを誰が持つか) | 対応付け | 差分の計算場所 | チーム管理の要 |
|---|---|---|---|---|
| **ARM / Bicep** | クラウドの制御プレーン | API + type/name | クラウド側(preflight) | RBAC・デプロイ履歴 |
| **Terraform** | 自前の state 台帳 | state 内ID | クライアント側 | リモートbackend・lock |
| **Ansible** | 誰も持たない／実機を毎回評価 | inventory + 冪等評価 | 実機上 | inventory・playbook |

最後に、この地図の使い方を試そう。新しいツールが出てきたら、こう問えばいい——**「真実をどこに置いている？」**。

- **Pulumi**: 汎用言語で書くが、**state を持つ**（Pulumi Cloud かS3/Blob等の self-managed backend に保存）。→ Terraform と同じ「自分が台帳を保持」のマス[^pulumi]。
- **AWS CloudFormation**: スタックの状態を **CloudFormation サービスが AWS アカウント内で管理し、ユーザーがアクセスできる state ファイルは無い**。モデルを保持するのは自分でなくクラウド側のサービス。→ ARM と同じ「クラウドがモデルを保持」のマス[^pulumi-cfn]。
- **AWS CDK**: プログラムを **CloudFormation テンプレートにトランスパイル** して CloudFormation に流す。→ Bicep が ARM に変換されるのと同じ構図。CloudFormation と同じマス[^pulumi-cdk]。

[^pulumi]: [Pulumi state and backends](https://www.pulumi.com/docs/iac/concepts/state-and-backends)。state は Pulumi Cloud がデフォルト、または S3 / Azure Blob / GCS / ローカル等の DIY backend で自己管理できる。

[^pulumi-cfn]: [Pulumi vs. CloudFormation](https://www.pulumi.com/docs/iac/comparisons/cloudformation)。CloudFormation の state は「Managed by the CloudFormation service inside the AWS account; no user-accessible state file」と整理されている。

[^pulumi-cdk]: [Pulumi vs. AWS CDK](https://www.pulumi.com/docs/iac/comparisons/aws-cdk)。「AWS CDK transpiles programs into AWS CloudFormation templates that the AWS CloudFormation service deploys」。

ツールの数は増え続けるが、軸は変わらない。**「あるべき姿をどう書くか」より、「真実をどこに置くか」を先に見れば、新しいツールでも自分の地図に置ける。** それが、IaC を構文の暗記ではなく設計判断として読むということだ。
