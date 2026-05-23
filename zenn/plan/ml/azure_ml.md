---
title: "機械学習はわかる、クラウドはこれから — Azure Machine Learning で学習からデプロイまでの最短ルート"
status: plan
---

## 想定読者と前提

- 機械学習(学習・評価・モデルの考え方、scikit-learn / PyTorch などでローカルでは回せる)を理解している
- だがクラウドでどう環境を構築して回すのか、勘所が分からない
- Azure の基本概念(サブスクリプション、リソースグループ、RBAC、リージョン)は分かるが、**ML 向けの個々のサービスを知らない**

扱わない: 機械学習アルゴリズムそのものの解説、ネットワーク隔離(Managed VNet / Private Endpoint)の作り込み、MLOps パイプライン・CI/CD の本格構築。

## この記事が答える問い

1. ローカルで動く ML を Azure に持っていくとき、**どのサービスをどう組み合わせる**のか
2. **Azure Machine Learning の Workspace** を 1 つ作ると、裏で何が一緒に作られ、それぞれ何の役割なのか
3. 学習用の**計算資源(Compute)**は何種類あり、どう選び、**課金を抑える**にはどうするか
4. **Environment(実行環境)** はローカルの conda/Docker と何が違うのか
5. データはどこに置き、学習ジョブはどう投げ、モデルをどう**デプロイ(Online Endpoint)**するのか

## 操作インターフェイスの方針

- **Python SDK v2(`azure-ai-ml`)を中心**に説明する。コードは要点を示す最小限にとどめ、概念対応を優先する。
- 必要に応じて Studio(GUI)/ CLI v2 にも触れるが、深追いはしない。

## 章立てと各セクションの主張

### 1. はじめに — 「ローカルでは動く」と「クラウドで回る」の間にある溝

- ML エンジニアがクラウドで詰まるのは、アルゴリズムではなく「計算資源・実行環境・データ・成果物の置き場所」をどう用意し管理するか、という運用部分。
- Azure はこれを **Azure Machine Learning** という 1 つのマネージドサービスに集約していること、本記事はその地図を描くことを宣言。
- 根拠: [Overview of ML products](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/data-science-and-machine-learning)(`search_azureml_overview.json`)

### 2. 全体地図 — Azure ML を構成する登場人物

- 中心は **Workspace**。その下に Compute / Environment / Data / Job / Model / Endpoint が紐づく、という関係図を最初に提示。
- 「ML でやりたいこと → 対応する Azure ML の概念」の対応表を置く(学習を回す→Compute+Job、再現性→Environment、データ管理→Datastore/Data asset、公開→Endpoint)。
- 根拠: [What is a workspace?](https://learn.microsoft.com/en-us/azure/machine-learning/concept-workspace?view=azureml-api-2)、[Quickstart: Azure ML in a day](https://learn.microsoft.com/en-us/azure/machine-learning/tutorial-azure-ml-in-a-day?view=azureml-api-2)(`extract_core_concepts.json`, `search_azureml_overview.json`)

### 3. Workspace を作ると裏で何ができるか(付随リソース)

- Workspace 作成時に、指定しなければ Azure が自動で 4 つの**付随リソース**を作る:
  - **Storage Account**: 成果物・ジョブログ・ノートブック・アップロードデータの既定置き場
  - **Key Vault**: 接続文字列・ACR パスワード・データストア資格情報などのシークレット
  - **Container Registry (ACR)**: Environment から焼いた Docker イメージのキャッシュ置き場(初回ジョブ時に作られることがある)
  - **Application Insights**: 推論エンドポイントの監視・診断
- Compute を作るとさらに VM / Load Balancer / VNet などのサブリソースが付く。
- 「Azure 概念は分かるが個々のサービスを知らない」読者に、各サービスが ML 文脈で何の役割かを結びつける。
- 根拠: [What is a workspace? — Associated resources / Subresources](https://learn.microsoft.com/en-us/azure/machine-learning/concept-workspace?view=azureml-api-2)、[Set up service authentication(RBAC 表)](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-identity-based-service-authentication?view=azureml-api-2)(`extract_core_concepts.json`, `search_azureml_resources.json`)

### 4. Workspace への接続(SDK v2 の入口)

- `MLClient(DefaultAzureCredential(), subscription_id, resource_group, workspace)` が全ての操作の起点。`MLClient.from_config()` で `config.json` から読む方法も。
- `DefaultAzureCredential` は CLI ログイン / マネージドID / 環境変数などを順に試す。Compute Instance 上では自動でマネージドID が効く。
- `MLClient` 生成は遅延初期化で、最初の呼び出しまで実際には接続しない、という注意点。
- 操作の窓口は Studio / SDK v2 / CLI v2 / VS Code 拡張があることを一覧で示す(本記事は SDK v2 中心)。
- 根拠: [Set up authentication](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-setup-authentication?view=azureml-api-2)、[Tutorial: ML pipelines(MLClient 遅延初期化)](https://learn.microsoft.com/en-us/azure/machine-learning/tutorial-pipeline-python-sdk?view=azureml-api-2)(`search_extract_sdkv2.json`)

### 5. Compute — 計算資源の選び方と課金の罠

- 3 種類を役割で整理:
  - **Compute Instance**: 単一ノード。開発・ノートブック用の「クラウド上の自分のマシン」。Workspace の file share がマウントされ、ファイルが永続。
  - **Compute Cluster (AmlCompute)**: マルチノード、ジョブ投入で自動スケール。学習の本番用。
  - **Serverless Compute**: 自分で作らない。ジョブごとに Azure が用意・破棄する最も手軽な選択肢。
- **課金の最重要ポイント**:
  - Cluster は `min_instances=0` にすればアイドル時にノードが解放され課金されない(`idle_time_before_scale_down` 既定 120 秒)。
  - Compute Instance は「停止」しても disk / public IP / load balancer の課金は残る。アイドルシャットダウンやスケジュールで止める。
- **クォータ**: 1 リージョンの総コンピュート上限は既定 500(学習クラスタ・Compute Instance・マネージドオンラインエンドポイントで共有)。ジョブ最長 21 日(low-priority は 7 日)。
- 最小コード: `AmlCompute(...)` を `ml_client.begin_create_or_update(...)`。ただし「まず Serverless から始めれば作成不要」と勧める。
- 根拠: [Understand compute targets](https://learn.microsoft.com/en-us/azure/machine-learning/concept-compute-target?view=azureml-api-2)、[Compute instance](https://learn.microsoft.com/en-us/azure/machine-learning/concept-compute-instance?view=azureml-api-2)、[Create a compute cluster](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-create-attach-compute-cluster?view=azureml-api-2)、[Serverless compute](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-use-serverless-compute?view=azureml-api-2)、[Manage quotas](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-manage-quotas?view=azureml-api-2)(`search_extract_compute.json`)

### 6. Environment — 再現可能な実行環境

- ローカルの「自分の conda 環境」に相当するが、Workspace がバージョン管理し、複数の Compute・チームで共有・再現できる。
- **Curated(用意済み)** vs **カスタム**。カスタムは system-managed(conda 指定)/ user-managed(BYOC・Docker)。
- 仕組み: 初回ジョブ時に定義から Docker イメージをビルドし ACR にキャッシュ。定義のハッシュが一致すれば再ビルドせず再利用。`AzureML-` / `Microsoft` 接頭辞は予約。
- 学習とデプロイで同じ Environment を使えるのが再現性の肝。
- 根拠: [About Azure ML environments](https://learn.microsoft.com/en-us/azure/machine-learning/concept-environments?view=azureml-api-2)(`extract_core_concepts.json`)

### 7. データ — Datastore と Data asset

- **Datastore**: ストレージ(Blob/ADLS など)への接続情報を Workspace に登録したもの。資格情報は Key Vault 管理。
- **Data asset**: 特定のデータ(ファイル/フォルダ/テーブル)へのバージョン付き参照。`uri_file` / `uri_folder` / `mltable`。
- ジョブからの参照は `Input(type=..., path=..., mode=...)`。path は local / Blob(wasbs) / ADLS(abfss) / `azureml://datastores/...` / `azureml:name:version` をサポート。mount と download の違い。
- 根拠: [Create data assets](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-create-data-assets?view=azureml-api-2)、[Access data in a job](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-read-write-data-v2?view=azureml-api-2)(`search_extract_sdkv2.json`)

### 8. 学習ジョブを投げる(command job)

- ローカルの「`python train.py` を実行」を、クラウドで再現可能に回す単位が **command job**。
- `command(code="./src", command="python train.py ...", inputs=..., environment=..., compute=...)` を `ml_client.jobs.create_or_update(job)` で投入。
- 投げた瞬間 Azure ML がやること:Environment のイメージ取得→Compute の確保→コードと入力をマウント→実行→ログ・メトリクス・出力を Workspace に記録(lineage)。
- compute を指定しなければ Serverless で走る。
- 根拠: [Access data in a job](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-read-write-data-v2?view=azureml-api-2)、[Quickstart: Azure ML in a day](https://learn.microsoft.com/en-us/azure/machine-learning/tutorial-azure-ml-in-a-day?view=azureml-api-2)(`search_extract_sdkv2.json`, `search_azureml_overview.json`)

### 9. モデルを登録する

- 学習成果物(モデルファイル)を Workspace に **Model** としてバージョン付きで登録。Storage に保管され、以後デプロイから名前+バージョンで参照できる。
- ジョブ内で登録する方法と、ローカルファイルから登録する方法。
- 根拠: [Tutorial: ML pipelines(モデル登録)](https://learn.microsoft.com/en-us/azure/machine-learning/tutorial-pipeline-python-sdk?view=azureml-api-2)、[Deploy to online endpoints(登録済みアセット参照)](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-deploy-online-endpoints?view=azureml-api-2)(`search_extract_sdkv2.json`, `search_extract_endpoint.json`)

### 10. デプロイ — Managed Online Endpoint

- **Endpoint(エンドポイント)** = 安定した URL と認証。**Deployment(デプロイ)** = その裏で実際にモデルを動かす VM 群。1 つの Endpoint に複数 Deployment(blue/green)を置き、トラフィックを割り振れる。
- 最小構成: `ManagedOnlineEndpoint` を作り、`ManagedOnlineDeployment(model=..., code_configuration=CodeConfiguration(code, scoring_script="score.py"), environment=..., instance_type=..., instance_count=...)` を作る。
- **scoring script(`score.py`)** には `init()`(モデルロード)と `run()`(推論)が必須。モデルは `AZUREML_MODEL_DIR` から読む。
- 課金注意: オンラインエンドポイントの VM は常時起動なので課金が続く。検証後は削除する。エンドポイントのコンピュートもリージョンのコンピュートクォータ(既定 500)を共有する。
- Online(リアルタイム)と Batch(大量・非同期)の違いに一言触れる。
- 根拠: [Deploy to online endpoints](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-deploy-online-endpoints?view=azureml-api-2)、[Access resources from endpoints(Deployment 定義)](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-access-resources-from-endpoints-managed-identities?view=azureml-api-2)、[Batch scoring script](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-batch-scoring-script?view=azureml-api-2)(`search_extract_endpoint.json`)

### 11. まとめ — ローカル ML → Azure ML の対応表と、最初の一歩

- ローカルの各作業が Azure ML のどの概念に対応するかを 1 枚の表で再掲。
- コストで事故らないためのチェックリスト(Cluster は min=0、Compute Instance は止める、Endpoint は消す、まず Serverless)。
- 最初に試すなら「Studio で Workspace 作成 → Compute Instance でノートブック → Serverless で command job → Online Endpoint」の順を推奨。

## タグ案

`["azure", "machinelearning", "mlops", "python", "cloud"]`(既存記事で `azure` / `python` を使用済み)

## 不足情報・追加調査の候補

- Batch Endpoint の詳細(本記事では入口のみ。深掘りするなら追加調査)
- 料金の具体額(変動するため記事では断定せず「常時起動課金が続く」という性質のみ記述)
