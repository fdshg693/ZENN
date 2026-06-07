---
title: "真実はどこにある？ — 宣言的×状態保持の2軸で読むTerraform・ARM・Bicep・Ansible"
status: plan
---

## ねらい

- 対象読者: Azure で ARM/Bicep を触っているが、Terraform の `state` 概念との違いがモヤッとしている実務者。「IaC ツールが内部で結局なにをやっているか」を概念として掴み、新しいツール（Pulumi, CloudFormation, CDK…）が出ても位置づけられる地図がほしい人。前提はクラウドを多少触ったことがある程度。各ツールの細かい構文知識は不要。
- 答える問い: **IaC ツールは結局、コードとインフラをどう対応づけているのか。その「真実の置き場所（SSOT）」はどこで、なぜツールごとに違うのか。**
- 方針: 網羅しない。**宣言的 × 状態保持の2軸地図**を立て、4ツールを代表点として置き直す。バラエティで空間の輪郭を出す。Ansible は軸の「外側」を示す境界事例として使う。
- フォーマット: 概念図・対応表中心 + 各ツールに「何が起きているか」が分かる最小コード/コマンド断片（数行）を1つずつ。
- 扱わない: 各ツールの細かい構文・関数・モジュールの書き方、CI/CD パイプライン構築手順、価格・SKU 比較、HCL/Bicep 文法ガイド。

## 背骨となる発想

「IaC」と一言で言うが、どのツールも内部では同じ3つの問いに答えている:

1. **あるべき姿をどう表現するか**（宣言的に goal を書く / 手続き的に手順を書く）
2. **現状をどう知るか**（クラウド実体に問い合わせる / 別ファイル=state を信じる / 毎回実機を評価する）
3. **その差をどう埋めるか**（差分計算してAPIを叩く）

この記事は「2 = 真実(SSOT)をどこに置くか」を縦軸、「1 = 宣言的か手続き的か」を横軸にして、4ツールを置く。差分実行・コードからインフラへの対応付け・チーム管理は、すべて「SSOT の所在」から導かれる帰結として説明する。

### 2軸地図（記事の中心図）

```
                宣言的(あるべき姿)            手続き的(手順)
              ┌────────────────────────┬────────────────────────┐
クラウド実体  │  ARM / Bicep           │                        │
が真実        │  (state を持たない)     │                        │
              ├────────────────────────┼────────────────────────┤
状態ファイル  │  Terraform             │                        │
が真実        │  (tfstate が対応表)     │                        │
              ├────────────────────────┼────────────────────────┤
状態を持たず  │                        │  Ansible               │
都度実機評価  │  (冪等モジュールで宣言的┄┄→ だが順序実行で手続き的)│
              └────────────────────────┴────────────────────────┘
```
※ Ansible は「宣言的に書けるが、状態を持たず順序実行する」ため、1つのマスに収まらず軸をまたぐ＝境界事例。これが軸の広さを示す。

## セクション構成

### 1. この記事について（問題設定）
- 主張: あなたは ARM/Bicep を書いてデプロイできる。Terraform も `apply` できる。でも「Terraform には `tfstate` があるのに ARM にはない」「なぜ Terraform は state ファイルを壊すと事故るのに Bicep は平気なのか」を説明できるだろうか。本記事は各ツールの構文ではなく、**「真実(SSOT)をどこに置くか」**という1つの軸で全部を並べ直す。
- 根拠: 導入のため特定 URL 不要。

### 1.5 まず足場を固める — Bicep / Terraform / Ansible の普段・裏側・ハマりどころ（追加）
- ねらい: 「使ったことはあるが、細かい手順や概念を忘れた」読者を拾う導入。基本説明（インストール等）はしない。各ツールについて「普段こう使う → 裏でこう動く → よくハマる」を、地図本編に効く形で固める。100行規模。
- 各ツール3点セット:
  - **Terraform**: 普段＝`init`→`plan`→`apply` のループ。裏側＝`tfstate` が対応表、`plan` は state とコードを突き合わせる。ハマり＝state ロック競合 / 手動変更によるドリフト・1対1崩れ / ローカル state をチームで共有して事故。
  - **Bicep（＋ARM）**: 普段＝`az deployment group create`（デフォルト incremental）/ `what-if`。裏側＝Bicep は ARM JSON に変換され ARM が差分実行、state ファイル無し。ハマり＝incremental なので消したはずのリソースが残る / complete モードで意図せず削除 / what-if が `reference` で毎回「変わる」と出るノイズ。
  - **Ansible**: 普段＝inventory に対象、playbook にあるべき状態、`ansible-playbook`（必要に応じ `--check`）。裏側＝state を持たず毎回実機評価、順序実行＋handler。ハマり＝モジュール次第で冪等でない / 順序・handler 依存で「2回目で結果が違う」 / `--check` が実コマンド失敗を捉えきれない。
- この節の最後に「3つを並べると、違いは結局"真実をどこに置くか"に行き着く」と本編へ橋渡しする。
- 根拠:
  - Terraform: https://developer.hashicorp.com/terraform/language/state/purpose , https://developer.hashicorp.com/terraform/language/backend , https://developer.hashicorp.com/terraform/language/state
  - Bicep/ARM: https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/deployment-modes , https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/deploy-what-if , https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/overview
  - Ansible: https://docs.ansible.com/projects/ansible/latest/reference_appendices/glossary.html , https://docs.ansible.com/projects/ansible/latest/getting_started/basic_concepts.html , https://docs.ansible.com/projects/ansible/latest/collections/ovirt/ovirt/ovirt_disk_module.html

### 2. IaC が内部でやっている3つのこと
- 主張: ツールが違っても、(a)あるべき姿の表現 (b)現状の取得 (c)差分の適用、の3ステップは共通。違うのは **(b)現状をどこから取るか**だけ。ここが SSOT の所在＝この記事の主軸。
- 補足: 「宣言的(declarative / desired state)」とは "あるべき姿" を書くこと。Bicep も Terraform も公式に desired state configuration と表現される。
- 根拠:
  - https://learn.microsoft.com/en-us/azure/developer/terraform/comparing-terraform-and-bicep （両者とも declarative / goal-seeking）
  - https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/overview （declarative・冪等）

### 3. 座標系を入れる — 宣言的 × 状態保持の2軸
- 主張: 上の2軸地図を提示。縦軸「真実はどこ？」の3パターン（①クラウド実体 ②state ファイル ③持たず都度評価）が記事の背骨。横軸は宣言的/手続き的。
- 根拠: セクション4〜6の各事実に分解（ここでは図の提示）。

### 4. パターン①: クラウドが真実 — ARM / Bicep
- 主張:
  - ARM/Bicep は **state ファイルを持たない**。真実は Azure Resource Manager（クラウド側）にあるリソースの実体そのもの。
  - デプロイのデフォルトは **incremental モード**: テンプレートに無いリソースは消さずに残す。**complete モード**はテンプレートに無いものを削除（ただし complete は段階的に非推奨化、削除は deployment stacks 推奨）。
  - Bicep は **ARM JSON への透過的な抽象化**で、デプロイ時に Bicep CLI が ARM JSON テンプレートに変換する（＝Bicep と ARM は同じエンジンに乗る同一パターン）。
  - 差分計算は **Azure サービス側（preflight）**で行われる。クライアントは「あるべき姿」を送るだけ。
  - 最小断片: `az deployment group create --mode Incremental` / `what-if` の出力イメージ。
- 根拠:
  - https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/deployment-modes （incremental がデフォルト、complete の削除挙動、complete 非推奨化）
  - https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/overview （"transparent abstraction over ARM JSON"、デプロイ時に CLI が JSON へ変換、冪等）
  - https://learn.microsoft.com/en-us/azure/developer/terraform/comparing-terraform-and-bicep （Bicep は state を保存せず incremental deployment に依存。処理は Azure サービス側=preflight）
  - https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/overview （what-if が現状をチェックし "state を管理する必要をなくす"）

### 5. パターン②: 状態ファイルが真実 — Terraform
- 主張:
  - Terraform の `terraform.tfstate` は、**設定中の resource instance と実体オブジェクトの1対1対応表**（例: `aws_instance.foo` ↔ `i-abcd1234`）。加えてリソース依存関係などメタデータも保持。
  - なぜタグでなく state か: 初期は AWS タグ方式だったが「全リソース・全クラウドがタグをサポートするわけではない」ため独自 state を採用、という公式の経緯。
  - 差分計算は **クライアント側**で行う: `plan` は state + HCL を突き合わせ、現状取得のための Azure 呼び出しに頼らず差分を出す（ARM/Bicep と対照的）。
  - state がSSOTゆえの脆さ: state を壊す/`state rm`/`import` すると1対1対応はユーザー責任。だから **リモートバックエンド + state locking** が要る。
  - 最小断片: `terraform { backend "azurerm" {...} }` と `plan/apply` の関係を数行で。
- 根拠:
  - https://developer.hashicorp.com/terraform/language/state/purpose （対応DB、タグ方式を捨てた経緯、デフォルトはローカルファイル、チームで共有が重要、locking）
  - https://developer.hashicorp.com/terraform/language/state （1対1マッピング、import/state rm はユーザー責任）
  - https://developer.hashicorp.com/terraform/language/backend （backend が state の保存先を定義、デフォルト local、backend は1つだけ）
  - https://learn.microsoft.com/en-us/azure/developer/terraform/comparing-terraform-and-bicep （Terraform はクライアント側処理、state+HCL で Azure 呼び出しなしに差分判断）

### 6. 境界事例: 状態を持たない手続き的 — Ansible
- 主張:
  - Ansible は state ファイルを持たない。各モジュールが **冪等(idempotent)**で、実行のたびに実機の現在状態を評価して desired state に収束させる（例: motd の owner/mode が違えば直す）。
  - ただし完全な宣言ではない: Play は**順序付きタスクリスト**で、handler は前タスクが `changed` のとき発火する＝手続き的側面。だから2軸地図で「宣言的⇄手続き的」をまたぐ。
  - コードと実機の対応付けは state ではなく **inventory（ホスト一覧）**が担う。agentless（managed node に常駐させない）。
  - 冪等性はモジュール依存で常に保証されるわけではない（公式に "信頼できる冪等化手段がない" と注記するモジュール例あり）→ここが「状態を持たない」ことの代償。
  - 最小断片: `file:` モジュールが mode/owner を宣言する数行 + `--check`（dry run）。
- 根拠:
  - https://docs.ansible.com/projects/ansible/latest/reference_appendices/glossary.html （idempotency 定義、resource model は冪等、必要時のみ change、--check の dry run）
  - https://docs.ansible.com/projects/ansible/latest/getting_started/basic_concepts.html （inventory、play=順序付きタスク、handler の changed 発火、modules を node にコピーして実行、managed node に通常インストールしない）
  - https://docs.ansible.com/projects/ansible/latest/collections/ovirt/ovirt/ovirt_disk_module.html （冪等化が保証できないモジュール例）

### 7. 横串①: コードからインフラへの「対応付け」3方式
- 主張: 「コードの1行が、どの実リソースを指すのか」をどう解決するかが3者で違う。
  - **state 内 ID 方式 (Terraform)**: tfstate がアドレス↔実体IDの台帳。
  - **リソースプロバイダ/API + 名前方式 (ARM/Bicep)**: スコープ(リソースグループ)＋type＋name で ARM が一意に解決。台帳は要らずクラウド自身が答える。
  - **inventory + 冪等評価 (Ansible)**: 対象ホストは inventory、リソースの一致は毎回実機属性で判定。
- 根拠: セクション4〜6 と同じ URL 群（deployment-modes / state / basic_concepts）。

### 8. 横串②: 差分実行とドリフトの扱い
- 主張:
  - ドライラン: Terraform `plan` / ARM・Bicep `what-if` / Ansible `--check`。狙いは同じ「適用前に差分を見る」。
  - だが**ドリフト（手で変えられた現実とのズレ）の見え方**が SSOT で変わる: Terraform は state と実体の差として検知（refresh）、ARM/Bicep は state を持たないので「次のデプロイで宣言に寄せる」だけ＝履歴はデプロイ履歴に残る、Ansible は毎回実機評価なのでドリフトという概念自体が薄い。
  - what-if の限界も一言: `reference` 関数は解決できず毎回「変わる」と出るなどの注意（断定の精度に関わるので明記）。
- 根拠:
  - https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/deploy-what-if （what-if は変更を加えず予測のみ）
  - https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/deploy-what-if （change types、reference 関数の限界、bicep snapshot のローカル検証）
  - https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/overview （デプロイ履歴をポータルで追跡）
  - https://developer.hashicorp.com/terraform/language/state/purpose （state を最新に保つ必要、チーム共有）

### 9. 横串③: チーム管理は「SSOT の所在」で決まる
- 主張:
  - **state がファイル(Terraform)** → そのファイルが競合の火種。リモートバックエンド + locking で「同時 apply」を止める。誰が真実を持つかをチームで一元化する運用が必須。workspace で1設定に複数 state を分けられる。
  - **真実がクラウド(ARM/Bicep)** → 共有すべき state ファイルが無い。同時実行の制御や権限は **Azure RBAC とデプロイ履歴**側に寄る（write 権限 + `Microsoft.Resources/deployments`）。
  - **真実が実機(Ansible)** → 共有するのは inventory と playbook。状態の真実は常に対象ホスト。
  - 結論: 「どこを SSOT にするか」を選ぶことが、そのままチーム運用設計（ロック・権限・レビュー対象）を選ぶこと。
- 根拠:
  - https://developer.hashicorp.com/terraform/language/state/purpose （チームで同じ state を共有、locking）
  - https://developer.hashicorp.com/terraform/language/backend （backend が保存先、デフォルト local）
  - https://developer.hashicorp.com/terraform/language/state/workspaces （複数 named workspace = 1設定に複数 state）
  - https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/deploy-rest （deployment に必要な権限、Microsoft.Resources/deployments）

### 10. まとめ — 1枚の地図に戻す
- 主張: 全部を2軸地図に戻し、「SSOT の所在 → 対応付け方式 → 差分実行 → チーム管理」が連動して決まることを再掲。最後に新ツールを地図に置いてみせ、読者が未知のツールも置けるようにする。裏取り済みの分類:
  - **Pulumi** = 状態ファイル型（Terraform 側）: state を Pulumi Cloud または S3/Blob 等の DIY backend で管理。
  - **CloudFormation** = クラウド型（ARM 側）: state は CloudFormation サービスが AWS アカウント内で管理し、ユーザーアクセス可能な state ファイルは無い。
  - **AWS CDK** = クラウド型（Bicep と同型）: プログラムを CloudFormation テンプレートにトランスパイルして流す。
- 根拠:
  - https://www.pulumi.com/docs/iac/concepts/state-and-backends （Pulumi の state/backend）
  - https://www.pulumi.com/docs/iac/comparisons/cloudformation （CloudFormation は user-accessible state file 無し）
  - https://www.pulumi.com/docs/iac/comparisons/aws-cdk （CDK は CloudFormation へトランスパイル）

## 補足調査済み・残論点
- Pulumi/CloudFormation/CDK の SSOT 分類は上記の通り公式で裏取り済み（`temp/iac_ssot/extract_other_tools.json`）。
- ドリフト検知について Terraform の `terraform plan -refresh-only` 等の具体コマンド名は本文では出さず概念に留めた（現状の根拠で足りる）。

## 根拠にした調査ファイル
- `temp/iac_ssot/extract_tf_state.json`（Terraform state/backend/workspace）
- `temp/iac_ssot/extract_arm_mode.json`（ARM deployment modes / what-if / REST）
- `temp/iac_ssot/extract_bicep.json` + `temp/iac_ssot/extract_bicep_compile.json`（Bicep overview / Terraform比較 / ARM変換）
- `temp/iac_ssot/extract_ansible.json`（idempotency / inventory / check mode）
- `temp/iac_ssot/search_iac_state_concepts.json`, `temp/iac_ssot/search_iac_tools_compare.json`（概観）
