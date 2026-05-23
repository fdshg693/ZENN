---
title: "Azure ML studio は結局なにができるのか — 多機能を『記述レベル × 工程』の地図で俯瞰する"
status: plan
---

## 位置づけ（前作との関係）

- 前作「機械学習はわかる、クラウドはこれから — Azure Machine Learning で学習からデプロイまでの最短ルート」(`zenn/publish/ml/azure_ml.md`) で、Workspace / Compute / Environment / Data / Job / Model / Endpoint という**コアの一本道**は引いた。
- 本作はその続編。studio を開くと左メニューに並ぶ大量の機能（AutoML, Designer, Data labeling, Responsible AI, Feature store, Monitoring, Registries, Model catalog, Prompt flow …）の**全体像を地図にする**。
- やり方（SDK v2 の書き味、ジョブ投入の流れ）は前作でイメージ済みという前提。コードは各機能 1 つ最小限にとどめ、「何の機能で、いつ使い、何と組み合わさるか」を優先する。

## 想定読者と前提

- 前作レベルの理解（ローカル ML を Azure ML のコア概念に対応づけられる）はある。
- だが studio の機能数が多く、「同じ学習なのに AutoML と Designer と command job がある」「評価や運用のメニューは何のためか」が整理できていない。
- Azure の基本概念（サブスクリプション、RBAC、リージョン）は分かる。

扱わない: 各機能の手取り足取りの操作手順、コストの試算、ネットワーク隔離の作り込み、GenAI アプリ構築の深掘り（地図の端として位置づけるのみ）。

## この記事が答える問い

1. Azure ML studio の多数の機能は、どんな**座標**で整理できるのか。
2. 同じ工程に複数の選択肢（no-code / code-first）があるとき、**どう使い分ける**のか。
3. 機能同士は**どう組み合わさる**のか（単独で使うものばかりではない）。
4. **どこまでが Azure ML の領域で、どこからが Foundry** なのか。

## 地図の座標（背骨）

機能名で覚えると爆発する。**2 軸**で並べ直すと、未知の機能もこの座標に置ける。

- **縦軸＝記述レベル**: no-code(GUI) ↔ low-code ↔ code-first(SDK v2 / CLI v2)
- **横軸＝工程**: データ準備 → 学習・モデル探索 → 評価・説明責任 → デプロイ → 運用

§2 でこの 2 軸のマスターマトリクス表を 1 枚出し、以降の章はその列（工程）を 1 つずつ歩く。各工程で「コア（前作で解説済み）＝位置だけ」「新機能＝厚く（役割＋いつ使う＋組み合わせ）」を区別する。

サーベイ記事として、**境界・例外を意図的に配置**して輪郭を出す:
- Designer の v1/v2 コンポーネント非互換と v1 非推奨（no-code は無料の万能ではない）
- AutoML は ML studio にあるが Foundry にはない（studio 間の境界）
- Feature store は機能ではなく**別ワークスペース種別**
- Model monitoring / RAI scorecard の多くが preview（成熟度の境界）
- v2 SDK は独自の logging を持たず、実験追跡は MLflow（バージョン境界）
- GenAI（Model catalog / Prompt flow）は Foundry へ誘導中（地図の端）

## 章立てと各セクションの主張

### 1. この記事について — 一本道から地図へ
- 主張: 前作で「最短ルート」は引いた。だが実務では studio の他のメニューに必ず出会う。本作は studio の多機能を 2 軸の地図に並べ、使い分けと組み合わせの勘所を与える。
- 根拠: 前作 + [What is Azure ML?](https://learn.microsoft.com/en-us/azure/machine-learning/overview-what-is-azure-machine-learning?view=azureml-api-2)（`extract_overview_automl_designer.json`）

### 2. 地図の座標 — 2 軸マトリクス
- 主張: studio の機能は「記述レベル × 工程」で並ぶ。同じ工程に no-code と code-first の選択肢が併存するのが Azure ML の特徴。マスターマトリクス表を提示。
- 補足: studio は「過去の ML 経験のレベルに応じた複数のオーサリング体験」を提供する、と公式が明言（Notebooks / Designer / AutoML UI）。
- 根拠: [What is Azure ML? — Studio / authoring experiences](https://learn.microsoft.com/en-us/azure/machine-learning/overview-what-is-azure-machine-learning?view=azureml-api-2)（`extract_overview_automl_designer.json`, `extract_foundry_boundary_labeling.json`）

### 3. データ準備の機能 — ラベル付け・対話的探索・特徴量の資産化
- コア（位置のみ）: Datastore / Data asset（前作で解説済み）。
- 新機能（厚く）:
  - **Data labeling**: 画像/テキストのラベル付けプロジェクトを studio 上で共同運用。ML 支援ラベリングで一部自動化。教師データを作る入口。
  - **Notebooks**: studio 内のマネージド Jupyter。Compute Instance に紐づき、VS Code(web/desktop) でも開ける。EDA・プロトタイピングの場。
  - **Managed Feature Store**: 特徴量の定義＋変換ロジックを feature set spec として宣言、offline(ADLS Gen2)/online(Redis) に materialize、feature catalog で検索・共有・再利用、`get_offline_features()` で学習/推論に供給。**機能ではなく別のワークスペース種別**で、複数プロジェクトや Databricks からも使える。
- 使い分け: 単発の前処理は Notebook、組織で特徴量を再利用したいなら Feature store。
- 根拠: [What is Azure ML?](https://learn.microsoft.com/en-us/azure/machine-learning/overview-what-is-azure-machine-learning?view=azureml-api-2)、[What is managed feature store?](https://learn.microsoft.com/en-us/azure/machine-learning/concept-what-is-managed-feature-store?view=azureml-api-2)（`extract_overview_automl_designer.json`, `extract_rai_featurestore_monitoring.json`）

### 4. 学習・モデル探索の機能 — 同じ「学習」に 4 つの入口
- コア（位置のみ）: command job（前作で解説済み）。
- 新機能（厚く）:
  - **AutoML**: 特徴量化・アルゴリズム選択・ハイパラ調整を自動化。分類/回帰/予測/CV/NLP に対応。no-code studio UI でも code-first(SDK v2/CLI v2) でも使える。データはあるが手法に当たりを付けたいときの起点。
  - **Designer (v2)**: ドラッグ&ドロップでパイプラインを組む no-code。**カスタムコンポーネント(v2)** は自前コードを部品化し SDK v2/CLI と相互運用・共有可能。境界: クラシックなプレビルト(v1)コンポーネントは新規追加が止まっており、v1 Designer のデプロイは managed online endpoint(v2) 非対応。新規は v2 で。
  - **Sweep job（ハイパーパラメータ調整）**: 探索空間・サンプリング・早期終了ポリシー(例 MedianStoppingPolicy)・目標指標を指定し、Command/CommandComponent をスイープ。注意: 各試行は学習をゼロから再実行するので、重い前処理はパイプラインで前段に出す。
  - **Pipelines**: 工程を component に分けて連結。component は登録して再利用・自動バージョニング。YAML/CLI・Python SDK・Designer の 3 つで書け、AutoML/command/sweep/parallel/spark を step にできる。
- 使い分け（座標で見る）: 当たりを付ける=AutoML、可視で組む=Designer、自分のコードを最適化=command+Sweep、再現性ある多段=Pipelines。
- 根拠: [What is automated ML?](https://learn.microsoft.com/en-us/azure/machine-learning/concept-automated-ml?view=azureml-api-2)、[What is Designer (v2)?](https://learn.microsoft.com/en-us/azure/machine-learning/concept-designer?view=azureml-api-2)、[Hyperparameter tuning (v2)](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-tune-hyperparameters?view=azureml-api-2)、[Component pipelines (CLI)](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-create-component-pipelines-cli?view=azureml-api-2)（`extract_overview_automl_designer.json`, `extract_registry_sweep_pipeline.json`）

### 5. 評価・説明責任の機能 — 「精度が出た」の先
- 新機能（厚く）:
  - **実験追跡（MLflow）**: Azure ML workspace は MLflow 互換で、workspace を MLflow tracking server として使える。境界: **v2 SDK は独自の logging を持たず、メトリクス記録は MLflow で行う**（クラウド非依存・移植可能）。studio の Jobs でメトリクスを可視化。`MLproject` ファイルは 2026/9 廃止予定。
  - **Responsible AI dashboard**: error analysis(失敗の偏りとコホート特定)、fairness assessment(センシティブ属性間の公平性)、model interpretability、counterfactual what-if をコンポーネントとして組み、studio で可視化。
  - **RAI scorecard (preview)**: ダッシュボードから PDF レポートを生成し、非技術ステークホルダーや監査に共有。model registry の Responsible AI タブから参照。
- 使い分け: 数値の追跡=MLflow、モデルの公平性・説明性の点検=RAI dashboard、対外説明=scorecard。
- 根拠: [MLflow and Azure ML](https://learn.microsoft.com/en-us/azure/machine-learning/concept-mlflow?view=azureml-api-2)、[What is Responsible AI](https://learn.microsoft.com/en-us/azure/machine-learning/concept-responsible-ai?view=azureml-api-2)、[Responsible AI scorecard (preview)](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-responsible-ai-scorecard?view=azureml-api-2)（`extract_registry_mlflow.json`, `extract_rai_featurestore_monitoring.json`）

### 6. デプロイと運用の機能 — 出した後を支える
- コア（位置のみ）: Online / Batch Endpoint（前作で解説済み）。no-code 側では AutoML/Designer から直接デプロイもできる、と一言。
- 新機能（厚く）:
  - **Model monitoring**: 本番データを学習データ/直近データと比較し、data drift / prediction drift / data quality を監視。feature attribution drift・model performance(分類/回帰)・生成 AI の安全性品質などは preview。劣化検知→再学習トリガの起点。
  - **Registries**: Git リポジトリのように、モデル・環境・コンポーネント・データセットを**ワークスペースから切り離して組織横断で共有**。dev→test→prod を別ワークスペースへ昇格し、registry からエンドポイントへデプロイ。
  - **サービス監視**: Azure Monitor / Application Insights でエンドポイントのメトリクス・ログ。これは管理者寄りの面。
- 使い分け: モデルの中身の劣化=Model monitoring、資産の組織共有・昇格=Registries、インフラ稼働=Azure Monitor。
- 根拠: [Model monitoring](https://learn.microsoft.com/en-us/azure/machine-learning/concept-model-monitoring?view=azureml-api-2)、[ML registries for MLOps](https://learn.microsoft.com/en-us/azure/machine-learning/concept-machine-learning-registries-mlops?view=azureml-api-2)、[Monitor Azure ML](https://learn.microsoft.com/en-us/azure/machine-learning/monitor-azure-machine-learning?view=azureml-api-2)（`extract_rai_featurestore_monitoring.json`, `extract_registry_mlflow.json`）

### 7. 地図の端 — GenAI と Microsoft Foundry の境界
- 主張: studio には **Model catalog**（数百のモデルを発見・利用）と **Prompt flow**（LLM アプリの試作〜デプロイ）もあるが、Microsoft は GenAI 用途を **Foundry（旧 Azure AI Foundry）** へ誘導している。classic/カスタム ML の学習・運用は ML studio、LLM アプリ構築は Foundry、という棲み分け。
- 比較の要点（公式比較表より）: AutoML は ML studio のみ(Foundry は無)、学習 compute も ML studio 側、対応言語は ML studio が Python/R/Scala/Java に対し Foundry は Python のみ。
- 注意: SDK v1 は 2025/3/31 非推奨・サポートは 2026/6/30 まで。新規は v2 前提。
- 根拠: [What is Azure ML? — LLMs & GenAI](https://learn.microsoft.com/en-us/azure/machine-learning/overview-what-is-azure-machine-learning?view=azureml-api-2)、[ML products comparison (Foundry vs ML studio)](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/data-science-and-machine-learning)、[Foundry Models in Azure ML](https://learn.microsoft.com/en-us/azure/machine-learning/foundry-models-overview?view=azureml-api-2)（`extract_foundry_boundary_labeling.json`, `search_azureml_features.json`）

### 8. 組み合わせ方 — 地図上の代表ルート
- 主張: 機能は単独でなく経路で使う。3 つの代表ルートで地図の歩き方を示す:
  1. **no-code 完結**: Data labeling → AutoML/Designer → 直接デプロイ（コードを書かない）
  2. **当たり付け → 本実装**: AutoML で候補手法を把握 → command+Sweep で作り込み → Endpoint
  3. **code-first MLOps**: Feature store → Pipelines(component) → MLflow 追跡 → RAI 点検 → Registry 昇格 → Endpoint → Model monitoring
- 選定は機能名でなく軸の問いから: 「コードを書くか」「工程のどこにいるか」。
- 根拠: 各セクションの統合（新規 URL 不要）

### 9. まとめ
- 主張: 機能は増え続けるが座標（記述レベル × 工程）は安定。新機能に出会ったら「どの記述レベルの、どの工程の点か」を問えば地図に置ける。網羅ではなく座標を持ち帰ってほしい。前作の一本道に、本作の地図を重ねれば studio の全体像が立体になる。

## タグ案（publish 用）

`["azure", "machinelearning", "mlops", "automl", "cloud"]`（lowercase ASCII、前作の `azure`/`machinelearning`/`mlops`/`cloud` を再利用し `automl` を追加）

## 根拠ファイル一覧（temp/azureml_features_survey/）

- `search_azureml_features.json` — 機能ランドスケープ / Foundry 比較の起点
- `extract_overview_automl_designer.json` — 全機能一覧・AutoML・Designer v2
- `extract_rai_featurestore_monitoring.json` — Responsible AI・Feature store・Model monitoring
- `extract_registry_sweep_pipeline.json` — Sweep(ハイパラ)・Pipelines/component・v1→v2 移行
- `extract_foundry_boundary_labeling.json` — Foundry 境界・Data labeling・Notebooks・比較表
- `extract_registry_mlflow.json` — Registries(クロスWS)・MLflow 実験追跡

## 不足情報・本文前の留意

- preview 表記（RAI scorecard / model monitoring の一部シグナル）は本文で「(preview)」を明示し断定を避ける。
- Model catalog / Prompt flow は §7 で境界として軽く扱うのみ。Foundry 側の実体には踏み込まない。
