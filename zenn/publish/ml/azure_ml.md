---
title: "機械学習はわかる、クラウドはこれから — Azure Machine Learning で学習からデプロイまでの最短ルート"
emoji: "☁️"
type: "tech"
topics: ["azure", "machinelearning", "mlops", "python", "cloud"]
published: false
---

## この記事について

scikit-learn や PyTorch でモデルは書ける。ローカルでなら学習も評価も回せる。でも「これをクラウドで動かして」と言われた瞬間に手が止まる——という人は多いと思います。詰まるのはたいていアルゴリズムではなく、**計算資源・実行環境・データ・成果物をどこに置き、どう管理して回すか**という運用部分です。

Azure はこの部分を **Azure Machine Learning(以下 Azure ML)** という 1 つのマネージドサービスに集約しています。この記事は、

- 機械学習自体は理解している
- Azure の基本概念(サブスクリプション、リソースグループ、RBAC、リージョン)は分かる
- でも ML 向けの個々のサービスは知らない

という読者を対象に、**Azure ML の地図を描く**ことを目的にします。操作は Python SDK v2(`azure-ai-ml`)を中心に説明しますが、コードは要点を示す最小限にとどめ、「どのサービスが何の役割か」の理解を優先します。

扱わないこと: 機械学習アルゴリズムそのもの、ネットワーク隔離(Managed VNet / Private Endpoint)の作り込み、MLOps の CI/CD パイプライン構築。これらは入口だけ触れます。

:::message
本記事は Azure ML の v2 系(`azureml-api-2` / SDK v2 `azure-ai-ml`)を前提にしています。サービス仕様・既定値・上限値・料金は変わりうるため、本番判断の前に必ず公式ドキュメントと自分のサブスクリプションの状態を確認してください。
:::

## 1. 全体地図 — Azure ML を構成する登場人物

Azure ML の中心には **Workspace(ワークスペース)** という 1 つのリソースがあります。これは Azure ポータルで作る他のリソースと同じく、特定のリソースグループ・リージョンに属する Azure リソースです。そして ML に必要なほぼすべての要素が、この Workspace の下にぶら下がります。

```
Workspace(中心)
├── Compute      … 計算資源(学習・推論を動かすマシン)
├── Environment  … 実行環境(依存パッケージ・Docker イメージ)
├── Datastore / Data asset … データの接続情報と参照
├── Job          … 学習などの実行単位(ログ・メトリクスも記録)
├── Model        … 学習済みモデル(バージョン管理)
└── Endpoint     … 推論を公開する窓口
```

ローカルでやっていることに置き換えると、対応はこうなります。

| ローカルでやっていること | Azure ML での対応 |
|---|---|
| 自分のマシンや GPU サーバで計算する | **Compute**(Compute Instance / Cluster / Serverless) |
| `conda` 環境 / `requirements.txt` / Dockerfile を整える | **Environment** |
| データを特定パスから読む | **Datastore + Data asset** |
| `python train.py` を実行する | **command job** |
| `model.pkl` を保存しておく | **Model**(登録してバージョン管理) |
| FastAPI などで API として公開する | **Online Endpoint** |

つまり Azure ML を学ぶとは、**ローカルでバラバラにやっていた作業を、Workspace 配下の名前の付いた概念に対応づける**ことだと考えると整理しやすいです。以降はこの登場人物を 1 つずつ見ていきます。

参考: [What is a workspace?](https://learn.microsoft.com/en-us/azure/machine-learning/concept-workspace?view=azureml-api-2) / [Overview of ML products](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/data-science-and-machine-learning)

## 2. Workspace を作ると裏で何ができるか(付随リソース)

Workspace を作るとき、Azure ML は単独では動きません。データやシークレットを保管するために、いくつかの Azure リソースを必要とします。**自分で指定しなければ、Azure ML が自動で作ってくれます。** これらを「付随リソース(associated resources)」と呼びます。

| 付随リソース | ML 文脈での役割 |
|---|---|
| **Azure Storage アカウント** | 成果物・ジョブログ・ノートブック・アップロードしたデータの既定の置き場。Compute Instance のファイルもここに保存される |
| **Azure Key Vault** | ストレージの接続文字列、ACR のパスワード、データストアの資格情報などのシークレット保管庫 |
| **Azure Container Registry (ACR)** | Environment から焼いた Docker イメージのキャッシュ置き場 |
| **Application Insights** | 推論エンドポイントの監視・診断情報の収集 |

ここが「Azure の概念は分かるが個々のサービスを知らない」読者にとって最初の山場です。**Storage / Key Vault / ACR / Application Insights は、それぞれ単独でも使われる汎用 Azure サービス**ですが、Azure ML はそれらを「ML のための置き場・金庫・イメージ倉庫・監視基盤」として束ねて使っている、と理解してください。

いくつか実務上の注意があります。

- ACR は、最初に Environment からイメージをビルドするタイミングで作られることがあります(Workspace 作成と同時とは限りません)。
- これらの付随リソースは複数 Workspace で共有もできます。共有時は `enableDataIsolation` で名前衝突やアクセス分離を制御しますが、**この設定は Workspace 作成時にしか指定できません**。
- さらに Compute(後述)を作ると、その裏で VM・ロードバランサー・仮想ネットワークなどの**サブリソース**も作られます。ロードバランサーは Compute を停止していても料金が発生する点に注意。

付随リソースには、Workspace のマネージド ID に対して適切な RBAC ロール(Storage への Contributor + Storage Blob Data Contributor、Key Vault への権限など)が必要です。自動作成に任せれば通常は気にする必要はありませんが、既存のストレージや Key Vault を持ち込む場合はロール割り当てを意識します。

参考: [What is a workspace? — Associated resources / Subresources](https://learn.microsoft.com/en-us/azure/machine-learning/concept-workspace?view=azureml-api-2) / [Set up service authentication](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-identity-based-service-authentication?view=azureml-api-2)

## 3. Workspace への接続 — SDK v2 の入口

Workspace を操作する窓口は複数あります。

- **Azure ML studio**(ブラウザの GUI)
- **Python SDK v2**(`azure-ai-ml`)
- **Azure CLI v2**(`ml` 拡張)
- **VS Code 拡張**

この記事では Python SDK v2 を中心にします。すべての操作の起点は `MLClient` というオブジェクトで、これが「どの Workspace を操作するか」を表します。

```python
from azure.ai.ml import MLClient
from azure.identity import DefaultAzureCredential

ml_client = MLClient(
    DefaultAzureCredential(),
    subscription_id="<サブスクリプションID>",
    resource_group_name="<リソースグループ名>",
    workspace_name="<ワークスペース名>",
)
```

ポイントは 2 つあります。

**1つ目: 認証は `DefaultAzureCredential` に任せる。**
これは複数の認証方法(環境変数、マネージド ID、`az login` のキャッシュ、VS Code のサインインなど)を順に試し、最初に成功したものを使う仕組みです。ローカルで開発するなら `az login` 済みであればそのまま通り、後述の Compute Instance 上で動かすなら**マネージド ID が自動で効く**ため、コードを変えずに環境を移せます。サービスプリンシパルを使う場合は `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` / `AZURE_CLIENT_SECRET` を環境変数で渡します。

**2つ目: `MLClient` の生成では、まだ接続していない。**
`MLClient(...)` を作った時点では Workspace に接続せず、最初に実際の呼び出し(Compute の作成やジョブ投入など)が必要になったときに初めて接続します(遅延初期化)。なので生成自体は一瞬で終わり、ここでエラーが出なくても接続情報が正しいとは限りません。

接続情報を毎回ベタ書きしたくない場合は、Workspace からダウンロードできる `config.json` を使って `MLClient.from_config(DefaultAzureCredential())` と書けます。

参考: [Set up authentication](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-setup-authentication?view=azureml-api-2) / [Tutorial: ML pipelines with SDK v2](https://learn.microsoft.com/en-us/azure/machine-learning/tutorial-pipeline-python-sdk?view=azureml-api-2)

## 4. Compute — 計算資源の選び方と「課金の罠」

クラウドで ML を回すうえで最初に理解すべき、そして最もコスト事故を起こしやすいのが Compute(計算資源)です。Azure ML が管理する Compute は大きく 3 種類あります。

| 種類 | 性質 | 主な用途 |
|---|---|---|
| **Compute Instance** | 単一ノード。クラウド上の「自分の開発マシン」 | ノートブック、対話的な開発・デバッグ |
| **Compute Cluster (AmlCompute)** | マルチノード。ジョブ投入で自動スケール | 本番の学習ジョブ、並列・大規模学習 |
| **Serverless Compute** | 自分で作らない。ジョブごとに Azure が用意・破棄 | とりあえずジョブを回したいとき(最も手軽) |

### Compute Instance — クラウド上の自分のマシン

Compute Instance は単一ノードの VM で、Jupyter / JupyterLab / VS Code(Web)/ RStudio がプリインストールされた開発環境です。重要なのは、**Workspace の Azure Files 共有がマウントされる**点です。ここに作ったノートブックやファイルは共有領域に永続化され、同じ Workspace の別の Compute Instance からも見えます。CUDA・Docker・Azure CLI なども最初から入っています。

### Compute Cluster — 自動スケールする学習用クラスタ

Compute Cluster はジョブを投げると `max_instances` まで自動でノードを増やし、ジョブが終わると縮小します。SDK v2 では次のように定義します。

```python
from azure.ai.ml.entities import AmlCompute

cluster = AmlCompute(
    name="cpu-cluster",
    type="amlcompute",
    size="STANDARD_DS3_v2",
    min_instances=0,        # ★ アイドル時に 0 まで縮小 = 課金されない
    max_instances=2,
    idle_time_before_scale_down=120,  # 秒。既定 120
)
ml_client.begin_create_or_update(cluster).result()
```

### Serverless — そもそも作らない

Serverless Compute は「作成・管理が不要」な選択肢です。ジョブを投げるときに compute を指定しなければ、Azure ML が単一ノードの CPU VM を自動で用意して実行し、終わったら片付けます。**まず動かしてみたいだけなら Serverless が一番ラク**で、インフラを一切意識せずに済みます。

### ここが課金の罠

クラウド初心者が最も事故るのがここです。

:::message alert
- **Compute Cluster は `min_instances=0` にする。** 0 より大きい値にすると、ジョブが走っていなくてもその数のノードが起動し続け、課金され続けます。
- **Compute Instance は「停止」してもゼロ円にならない。** 停止すると計算時間の課金は止まりますが、ディスク・パブリック IP・標準ロードバランサーの料金は残ります。完全に止めるには、使わないときは**アイドルシャットダウン**やスケジュール起動停止を設定します。
- **クォータは共有。** 1 リージョン・1 サブスクリプションあたりの総コンピュート上限は既定で 500(最大 2,500 まで引き上げ可)。この枠は**学習クラスタ・Compute Instance・マネージドオンラインエンドポイントのデプロイで共有**されます。デプロイ用の枠が学習で食い尽くされる、という事故が起きえます。
- ジョブの最長実行時間は 21 日(low-priority ノードでは 7 日)。
:::

最初の一歩としては、**開発は Compute Instance、ジョブは Serverless から始める**のがコスト的にも認知負荷的にも無難です。慣れてから、繰り返し回す学習を Compute Cluster に載せ替えます。

参考: [Understand compute targets](https://learn.microsoft.com/en-us/azure/machine-learning/concept-compute-target?view=azureml-api-2) / [Compute instance](https://learn.microsoft.com/en-us/azure/machine-learning/concept-compute-instance?view=azureml-api-2) / [Create a compute cluster](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-create-attach-compute-cluster?view=azureml-api-2) / [Serverless compute](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-use-serverless-compute?view=azureml-api-2) / [Manage quotas](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-manage-quotas?view=azureml-api-2)

## 5. Environment — 再現可能な実行環境

ローカルでいう「自分の conda 環境」や `requirements.txt` に当たるのが **Environment** です。違いは、Azure ML の Environment は **Workspace がバージョン管理し、複数の Compute やチームで共有・再現できる**こと。さらに、学習で使った Environment をそのままデプロイでも使えるので、「学習時とデプロイ時で依存が違って動かない」という事故を防げます。

Environment には 2 系統あります。

- **Curated(用意済み)Environment**: Microsoft があらかじめ用意したもの(`sklearn-1.1` など)。すぐ使えてキャッシュ済み。名前の `AzureML-` / `Microsoft` 接頭辞は予約されており、自分では使えません。
- **カスタム Environment**: 自分で定義するもの。さらに 2 通り。
  - **system-managed**: conda の指定を渡すと、ベースイメージの上に conda 環境を Azure ML が組み立てる。
  - **user-managed (BYOC)**: 自分の Docker イメージや Docker ビルドコンテキストを持ち込む。

仕組みとして知っておくとよいのは、**初回ジョブ時に Environment 定義から Docker イメージがビルドされ、Workspace に紐づく ACR にキャッシュされる**点です。次回以降、同じ定義(ベースイメージ・Docker ステップ・Python パッケージから計算したハッシュ)であれば、再ビルドせずキャッシュ済みイメージを再利用します。だから 2 回目以降のジョブ起動は速くなります。

```python
from azure.ai.ml.entities import Environment

env = Environment(
    name="my-train-env",
    image="mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu22.04:latest",
    conda_file="./conda.yml",
)
ml_client.environments.create_or_update(env)
```

参考: [About Azure ML environments](https://learn.microsoft.com/en-us/azure/machine-learning/concept-environments?view=azureml-api-2)

## 6. データ — Datastore と Data asset

ローカルではデータをパス指定で読むだけですが、クラウドでは「データがどのストレージにあって、どう認証してアクセスするか」を扱う必要があります。Azure ML はこれを 2 段階の概念で整理します。

- **Datastore**: Azure Blob Storage や ADLS などのストレージへの**接続情報**を Workspace に登録したもの。資格情報は Key Vault に保管されるので、コードに認証情報をベタ書きしなくて済みます。Workspace には既定の Datastore が最初から用意されています。
- **Data asset**: 特定のデータ(ファイル/フォルダ/テーブル)への**バージョン付きの参照**。種類は `uri_file`(単一ファイル)/ `uri_folder`(フォルダ)/ `mltable`(スキーマ付きテーブル)。

ジョブからデータを渡すときは `Input` を使い、`path` と `mode` を指定します。

```python
from azure.ai.ml import Input
from azure.ai.ml.constants import AssetTypes, InputOutputModes

# 登録済み Data asset を参照する例
data_asset = ml_client.data.get(name="my-dataset", version="1")
job_input = Input(
    type=AssetTypes.URI_FILE,
    path=data_asset.id,
    mode=InputOutputModes.RO_MOUNT,  # 読み取り専用でマウント
)
```

`path` には複数の形式が使えます。

| 形式 | 例 |
|---|---|
| ローカル | `./data/train.csv` |
| Blob | `wasbs://<container>@<account>.blob.core.windows.net/<path>` |
| ADLS | `abfss://<container>@<account>.dfs.core.windows.net/<path>` |
| Datastore 経由 | `azureml://datastores/<datastore>/paths/<path>` |
| Data asset | `azureml:<name>:<version>` |

`mode` は**マウント**(必要な部分だけストリーミングし、巨大データでもディスクを食わない)と**ダウンロード**(ジョブ開始前に丸ごとコピー)を選べます。大きなデータはマウント、小さく何度も読むならダウンロード、と使い分けます。

参考: [Create data assets](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-create-data-assets?view=azureml-api-2) / [Access data in a job](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-read-write-data-v2?view=azureml-api-2)

## 7. 学習ジョブを投げる — command job

ローカルの `python train.py` に当たるのが **command job** です。「どのコードを、どの環境で、どの計算資源で、どの入力に対して実行するか」をまとめた実行単位です。

```python
from azure.ai.ml import command

job = command(
    code="./src",                       # このフォルダ一式がアップロードされる
    command="python train.py --data ${{inputs.training_data}}",
    inputs={"training_data": job_input},  # 6 章の Input
    environment="my-train-env:1",         # 5 章の Environment(名前:バージョン)
    compute="cpu-cluster",                # 4 章の Compute。省略すると Serverless
)
returned_job = ml_client.jobs.create_or_update(job)  # 投入
print(returned_job.studio_url)  # Studio で進捗・ログを確認できる URL
```

`ml_client.jobs.create_or_update(job)` を呼んだ瞬間、Azure ML は裏で次のことを自動でやります。

1. 指定された Environment の Docker イメージを ACR から取得(なければビルド)
2. 指定された Compute を確保(Cluster ならスケールアップ、未指定なら Serverless を用意)
3. `code` のフォルダと `inputs` のデータを Compute 上にマウント
4. `command` を実行
5. 標準出力・メトリクス・出力ファイル・スクリプトのスナップショットを Workspace に記録(=後から再現・追跡できる **lineage**)

ここが「ローカルとクラウドの溝」の核心です。ローカルでは自分の手で環境を整え、データを置き、実行し、結果を保存していました。クラウドでは**その一連を宣言的に書いて投げると、Azure ML が代行して記録まで残してくれる**わけです。

`compute` を省略すれば Serverless で走るので、最初の 1 本は Compute を作らずに試せます。

参考: [Access data in a job](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-read-write-data-v2?view=azureml-api-2) / [Quickstart: Azure ML in a day](https://learn.microsoft.com/en-us/azure/machine-learning/tutorial-azure-ml-in-a-day?view=azureml-api-2)

## 8. モデルを登録する

学習で出てきたモデルファイル(`model.pkl` など)を、Workspace に **Model** としてバージョン付きで登録します。登録すると Storage に保管され、以後はデプロイから「名前 + バージョン」で参照できます。

ローカルファイルから登録する最小例:

```python
from azure.ai.ml.entities import Model
from azure.ai.ml.constants import AssetTypes

model = Model(
    path="./outputs/model/",          # 学習で出力したモデル
    name="credit-defaults-model",
    type=AssetTypes.CUSTOM_MODEL,
)
registered = ml_client.models.create_or_update(model)
```

学習ジョブの中で `mlflow` などを使ってそのまま登録する流れもよく使われます(Azure ML は MLflow と統合しています)。いずれにせよ、**「どの学習ジョブから生まれたモデルか」が追跡できる状態でバージョン管理される**のがクラウドで運用する利点です。

参考: [Tutorial: ML pipelines with SDK v2](https://learn.microsoft.com/en-us/azure/machine-learning/tutorial-pipeline-python-sdk?view=azureml-api-2) / [Deploy to online endpoints](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-deploy-online-endpoints?view=azureml-api-2)

## 9. デプロイ — Managed Online Endpoint

最後に、登録したモデルをリアルタイム推論 API として公開します。ここで重要なのが **Endpoint と Deployment の分離**という考え方です。

- **Endpoint(エンドポイント)**: 安定した URL と認証を提供する「窓口」。クライアントはこの URL に対して推論リクエストを送る。
- **Deployment(デプロイ)**: その窓口の裏で実際にモデルを動かす VM 群。Endpoint には複数の Deployment(例: `blue` と `green`)を置き、トラフィックを割合で振り分けられる。

この分離のおかげで、新バージョンを `green` として立て、少しずつトラフィックを移す **blue/green デプロイ**が標準でできます。

最小構成のコードは次の通りです。

```python
from azure.ai.ml.entities import (
    ManagedOnlineEndpoint,
    ManagedOnlineDeployment,
    CodeConfiguration,
)

# 1) 窓口(Endpoint)を作る
endpoint = ManagedOnlineEndpoint(name="credit-endpoint", auth_mode="key")
ml_client.begin_create_or_update(endpoint).result()

# 2) 実体(Deployment)を作る
deployment = ManagedOnlineDeployment(
    name="blue",
    endpoint_name="credit-endpoint",
    model="credit-defaults-model:1",   # 8 章で登録した Model
    environment="my-train-env:1",      # 学習と同じ Environment を使える
    code_configuration=CodeConfiguration(
        code="./onlinescoring", scoring_script="score.py"
    ),
    instance_type="Standard_DS3_v2",
    instance_count=1,
)
ml_client.begin_create_or_update(deployment).result()

# 3) トラフィックを blue に 100% 流す
endpoint.traffic = {"blue": 100}
ml_client.begin_create_or_update(endpoint).result()
```

### scoring script(`score.py`)

デプロイにはモデルをどう呼ぶかを書いた **scoring script** が必須で、2 つの関数を実装します。

```python
import os, joblib, json

def init():
    # コンテナ起動時に 1 回だけ呼ばれる。モデルをメモリにロードする
    global model
    model_dir = os.getenv("AZUREML_MODEL_DIR")  # モデルが展開されるパス
    model = joblib.load(os.path.join(model_dir, "model.pkl"))

def run(raw_data):
    # リクエストごとに呼ばれる。推論して結果を返す
    data = json.loads(raw_data)["data"]
    return model.predict(data).tolist()
```

`init()` でモデルをロードし、`run()` でリクエストごとに推論する——FastAPI でいう起動処理とエンドポイント関数に近い役割分担です。モデルファイルは環境変数 `AZUREML_MODEL_DIR` が指すパスから読みます。

### Online と Batch

エンドポイントには 2 種類あります。

- **Online Endpoint**: 上記のリアルタイム推論。低レイテンシで即レスポンス。
- **Batch Endpoint**: 大量データに対する非同期・長時間のバッチ推論。`init()` / `run()` を持つ scoring script を書く点は共通ですが、`run()` はファイル単位のミニバッチを受け取ります。

### デプロイの課金注意

:::message alert
**Online Endpoint の裏の VM は常時起動**です。学習ジョブと違って「終わったら勝手に止まる」ものではないため、立てている間ずっと課金されます。検証が終わったら `ml_client.online_endpoints.begin_delete(name=...)` で削除してください。また 4 章で触れたとおり、エンドポイントのデプロイ用 VM もリージョンのコンピュートクォータ(既定 500)を学習リソースと共有します。
:::

参考: [Deploy to online endpoints](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-deploy-online-endpoints?view=azureml-api-2) / [Access resources from online endpoints](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-access-resources-from-endpoints-managed-identities?view=azureml-api-2) / [Author scoring scripts for batch deployments](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-batch-scoring-script?view=azureml-api-2)

## 10. まとめ — ローカル ML → Azure ML 対応表と最初の一歩

最後に全体を 1 枚にまとめます。

| ローカルでの作業 | Azure ML の概念 | SDK v2 の主な型・呼び出し |
|---|---|---|
| 計算する | Compute(Instance / Cluster / Serverless) | `AmlCompute`, `begin_create_or_update` |
| 環境を整える | Environment | `Environment`, `environments.create_or_update` |
| データを読む | Datastore / Data asset | `Input`, `data.get` |
| `python train.py` | command job | `command`, `jobs.create_or_update` |
| モデルを保存 | Model | `Model`, `models.create_or_update` |
| API として公開 | Online Endpoint | `ManagedOnlineEndpoint` / `ManagedOnlineDeployment` |

### コストで事故らないためのチェックリスト

- ☑ Compute Cluster は `min_instances=0`
- ☑ Compute Instance は使わないとき止める(アイドルシャットダウン / スケジュール)。ただし停止してもディスク等の課金は残る
- ☑ Online Endpoint は検証後に削除する(常時起動課金)
- ☑ まず Serverless で試し、必要になってから Cluster を作る
- ☑ コンピュートクォータ(既定 500)は学習・開発・デプロイで共有される点を頭に入れる

### 最初に試す順番

1. **Studio で Workspace を作成**(GUI が一番速い。付随リソースは自動作成に任せる)
2. **Compute Instance を立てて**、付属の Jupyter / VS Code で対話的に開発
3. **Serverless で command job を 1 本投げる**(Compute を作らずに済む)
4. うまくいったら **Model を登録 → Online Endpoint にデプロイ**、最後に**削除してコストを止める**

機械学習そのものが分かっているなら、あとは「ローカルの各作業が Workspace 配下のどの概念に対応するか」を掴むだけです。この対応表を手元に置いて、まずは Serverless でジョブを 1 本投げてみてください。それがクラウドで ML を回す最短ルートです。

---

### 参考リンク(一次情報)

- [What is a workspace?](https://learn.microsoft.com/en-us/azure/machine-learning/concept-workspace?view=azureml-api-2)
- [Understand compute targets](https://learn.microsoft.com/en-us/azure/machine-learning/concept-compute-target?view=azureml-api-2)
- [What is a compute instance?](https://learn.microsoft.com/en-us/azure/machine-learning/concept-compute-instance?view=azureml-api-2)
- [Create a compute cluster](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-create-attach-compute-cluster?view=azureml-api-2)
- [Model training on serverless compute](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-use-serverless-compute?view=azureml-api-2)
- [Manage resources and quotas](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-manage-quotas?view=azureml-api-2)
- [What are Azure ML environments?](https://learn.microsoft.com/en-us/azure/machine-learning/concept-environments?view=azureml-api-2)
- [Create data assets](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-create-data-assets?view=azureml-api-2)
- [Access data in a job](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-read-write-data-v2?view=azureml-api-2)
- [Set up authentication](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-setup-authentication?view=azureml-api-2)
- [Deploy ML models to online endpoints](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-deploy-online-endpoints?view=azureml-api-2)
