---
title: "Azure ML studio は結局なにができるのか — 多機能を『記述レベル × 工程』の地図で俯瞰する"
emoji: "🗺️"
type: "tech"
topics: ["azure", "machinelearning", "mlops", "automl", "cloud"]
published: false
---

## この記事について — 一本道から地図へ

前作「[機械学習はわかる、クラウドはこれから — Azure Machine Learning で学習からデプロイまでの最短ルート](./azure_ml)」では、Workspace を中心に **Compute / Environment / Data / Job / Model / Endpoint** という登場人物をたどり、「ローカルの ML 作業をクラウドで回す一本道」を引きました。

ところが Azure ML studio を実際に開くと、左メニューにはその一本道に出てこない機能がずらりと並んでいます。AutoML、Designer、Data labeling、Responsible AI、Feature store、Monitoring、Registries、さらには Model catalog や Prompt flow……。**「同じ学習なのに入口が何個もある」「評価や運用のメニューは何のためにあるのか」**——多機能ゆえに全体像が掴めない、というのが本記事の出発点です。

この記事は、

- 前作レベルの理解(ローカル ML を Azure ML のコア概念に対応づけられる)はある
- でも studio の機能数が多くて、それぞれの役割と使い分けが整理できていない

という読者に向けて、**Azure ML studio の多機能を 1 枚の地図に並べる**ことを目的にします。やり方(SDK v2 の書き味やジョブ投入の流れ)は前作でイメージできている前提とし、コードは各機能につき要点を示す最小限にとどめます。優先するのは「**何の機能で、いつ使い、何と組み合わさるか**」です。

扱わないこと: 各機能の手取り足取りの操作手順、コストの試算、ネットワーク隔離の作り込み、そして LLM/生成 AI アプリ構築の深掘り(これは「地図の端」として位置づけるだけにします)。

:::message
本記事は Azure ML の v2 系(`azureml-api-2` / SDK v2 `azure-ai-ml`)を前提にしています。preview の機能や上限値・既定値は変わりうるため、本番判断の前に必ず公式ドキュメントを確認してください。
:::

## 1. 地図の座標 — 2 軸で並べ直す

機能を名前で 1 つずつ覚えようとすると、数が多くてすぐ破綻します。代わりに **2 つの軸**で並べ直すと、未知の機能も同じ座標の上に置けるようになります。

- **縦軸＝記述レベル**: どれだけコードを書くか。`no-code(GUI)` ↔ `low-code` ↔ `code-first(SDK v2 / CLI v2)`
- **横軸＝工程**: ML プロジェクトのどの段階か。`データ準備` → `学習・モデル探索` → `評価・説明責任` → `デプロイ` → `運用`

Azure ML studio の特徴は、**同じ工程に no-code と code-first の選択肢が併存する**ことです。公式も「studio は過去の ML 経験のレベルに応じた複数のオーサリング体験を提供する」と述べており、Notebooks・Designer・AutoML UI がその代表です。

この 2 軸で主要機能を並べると、地図はこうなります(★は前作で解説したコア機能 = 一本道)。

| 工程 \ 記述レベル | no-code (GUI) | code-first (SDK v2 / CLI v2) |
|---|---|---|
| **データ準備** | Data labeling | ★Datastore / Data asset、Feature store |
| | Notebooks(対話的) | |
| **学習・モデル探索** | AutoML(UI)、Designer(v2) | AutoML(SDK)、★command job、Sweep job、Pipelines |
| **評価・説明責任** | Responsible AI dashboard、RAI scorecard | 実験追跡(MLflow) |
| **デプロイ** | AutoML/Designer から直接デプロイ | ★Online / Batch Endpoint |
| **運用** | Model monitoring(設定 UI)、Azure Monitor | Registries、Model monitoring(定義) |

以降の章は、この表の**列(工程)を左から 1 つずつ歩いて**いきます。各工程では、前作で解説済みのコア機能は「地図上の位置」だけ確認し、まだ触れていない機能を「役割 → いつ使う → 何と組み合わせるか」の順で見ていきます。

参考: [What is Azure Machine Learning?](https://learn.microsoft.com/en-us/azure/machine-learning/overview-what-is-azure-machine-learning?view=azureml-api-2)

## 2. データ準備 — ラベル付け・対話的探索・特徴量の資産化

**コア(位置だけ):** データの接続情報を登録する **Datastore** と、バージョン付き参照の **Data asset** は前作で扱いました。ここは「データをジョブに渡す」ための土台です。その上に、データ準備を支える機能が乗ります。

### Data labeling — 教師データを作る入口

**Data labeling** は、画像やテキストのラベル付けプロジェクトを studio 上で立ち上げ、複数人で分担・進捗管理する機能です。手元に生データはあるがラベルがない、というときの最初の一歩になります。ML 支援ラベリングを使うと、一定量ラベル付けした段階でモデルが残りの候補を提案し、人手を一部肩代わりします。

- **いつ使う**: 学習データのラベルをこれから作る、チームで分担したい。
- **組み合わせ**: 出来上がったラベル付きデータを Data asset として登録 → AutoML や command job の入力にする。

### Notebooks — studio の中の対話的開発

**Notebooks** は studio に統合されたマネージド Jupyter です。前作の Compute Instance に紐づいて動き、同じものを VS Code(web / desktop)で開くこともできます。EDA(探索的データ分析)やプロトタイピングのように、対話的に試行錯誤したい段階の作業場です。

- **いつ使う**: データを眺める、前処理を試す、モデルの当たりを手で付ける。
- **組み合わせ**: ここで固まった処理を command job やパイプラインの component に昇格させる。

### Managed Feature Store — 特徴量を「資産」にする

**Managed Feature Store** は、特徴量(feature)の定義と変換ロジックを `feature set` の仕様として宣言しておき、システム側が計算・保管・配信・監視を肩代わりする仕組みです。

- 計算結果を **offline store(ADLS Gen2)** や **online store(Redis)** に materialize(実体化)して、学習・推論で素早く再利用できる。
- **feature catalog** で特徴量を検索・共有・再利用でき、`get_offline_features()` で学習や一括推論にデータを供給する。

ここが地図上の小さな境界です。Feature store は単なる一機能ではなく、**専用のワークスペース種別**として存在し、複数のプロジェクトワークスペースや Azure Databricks などからも利用できます。

- **いつ使う**: 同じ特徴量を複数モデル・チームで使い回したい、学習時と推論時で特徴量の作り方をズラしたくない。
- **組み合わせ**: パイプラインの学習ステップ・推論ステップから特徴量を取得する。単発の前処理なら Notebook で十分で、組織的に再利用したくなって初めて Feature store の出番です。

参考: [What is managed feature store?](https://learn.microsoft.com/en-us/azure/machine-learning/concept-what-is-managed-feature-store?view=azureml-api-2)

## 3. 学習・モデル探索 — 同じ「学習」に 4 つの入口

ここが Azure ML が最も多機能に見える工程です。前作の **command job(★)** はその 1 つにすぎません。「学習する」という同じゴールに、記述レベルの違う入口が複数用意されています。

### AutoML — 手法選びを自動化する

**AutoML(自動機械学習)** は、特徴量化・アルゴリズム選択・ハイパーパラメータ調整という、本来は試行錯誤が要る部分を自動で回します。対応タスクは **分類・回帰・予測(時系列)・コンピュータビジョン・NLP**。no-code の studio UI でも、code-first の SDK v2 / CLI v2 でも同じことができます。

- **いつ使う**: データはあるが、どのアルゴリズムが効くか当たりが付いていない。ベースラインを素早く作りたい。
- **組み合わせ**: AutoML が出した最良モデルをそのまま Model 登録・デプロイへ。あるいは「どの手法が効くか」だけ掴んで、本実装は command job に移す。

### Designer (v2) — ドラッグ&ドロップでパイプラインを組む

**Designer** は、データ処理や学習のステップを部品として画面上でつなぐ no-code のパイプラインビルダーです。現行の **Designer (v2)** では、自前のコードを **カスタムコンポーネント(v2)** として包めるので、GUI で組みつつ SDK v2 / CLI と相互運用・共有できます。

:::message
ここは地図の例外ゾーンです。Designer には旧来の **クラシックなプレビルトコンポーネント(v1)** もありますが、新規追加は止まっており、v1 と v2 のコンポーネントは同じパイプライン内で混在できません。さらに **v1 Designer のデプロイは managed online endpoint(v2) に対応しません**。新規プロジェクトはカスタムコンポーネント(v2)で組むのが推奨です。
:::

- **いつ使う**: コードを書かずに処理の流れを可視化して組みたい、チームで処理フローを共有したい。
- **組み合わせ**: 組んだフローをそのままパイプラインジョブとして実行・デプロイ。

### Sweep job — ハイパーパラメータ探索

自分のコード(command job)を、ハイパーパラメータを変えながら多数回まわして最良を探すのが **Sweep job** です。探索空間・サンプリング方法・早期終了ポリシー(例: 走行中の中央値より悪い試行を打ち切る `MedianStoppingPolicy`)・最適化したい指標を指定し、Command や CommandComponent をスイープします。

:::message alert
**各試行(trial)は学習をゼロから再実行**します。モデル再構築やデータローダの再作成も毎回走るため、重い前処理はパイプラインで前段に切り出し、スイープ対象の学習だけを軽くするとコストを抑えられます。
:::

- **いつ使う**: 自前モデルの精度を、ハイパラ調整で詰めたい。
- **組み合わせ**: 前処理パイプライン → Sweep で学習 → 最良モデルを登録。

### Pipelines — 工程を部品に分けて連結する

**Pipelines** は、データ前処理・学習・評価といった工程を **component(部品)** に分割し、連結して 1 つのジョブとして回す仕組みです。component は workspace に登録すると再利用でき、自動でバージョン管理されます。書き方は **YAML/CLI・Python SDK・Designer** の 3 通りがあり、これがまさに「同じことを記述レベル違いで書ける」例になっています。component には command だけでなく AutoML・sweep・parallel・spark も載せられます。

- **いつ使う**: 多段の処理を再現可能に、再実行・部分差し替えしたい。MLOps の背骨にしたい。
- **組み合わせ**: 前処理 component → 学習 component → 評価 component を連結。各 component を別チームで共有・再利用。

ここまでを座標で言い直すと、**当たりを付ける=AutoML、可視で組む=Designer、自前コードを詰める=command+Sweep、再現性ある多段=Pipelines** という棲み分けになります。

参考: [What is automated ML?](https://learn.microsoft.com/en-us/azure/machine-learning/concept-automated-ml?view=azureml-api-2) / [What is Designer (v2)?](https://learn.microsoft.com/en-us/azure/machine-learning/concept-designer?view=azureml-api-2) / [Hyperparameter tuning (v2)](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-tune-hyperparameters?view=azureml-api-2) / [Create component-based pipelines (CLI)](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-create-component-pipelines-cli?view=azureml-api-2)

## 4. 評価・説明責任 — 「精度が出た」の先

学習が回ってメトリクスが出た、で終わらないのがクラウドの ML 運用です。この工程の機能は「記録する」「点検する」「説明する」を担います。

### 実験追跡(MLflow) — メトリクスを記録・比較する

Azure ML の workspace は **MLflow 互換**で、workspace をそのまま MLflow の tracking server として使えます。記録したメトリクス・パラメータ・成果物は studio の Jobs で可視化・比較できます。

:::message
ここはバージョン境界として知っておくと良い点です。**v2 SDK 自体には logging 機能がありません**。実験のメトリクス記録は MLflow の API で行うのが前提で、これによりコードはクラウド非依存・移植可能になります。なお `MLproject` ファイル(MLflow Projects)のサポートは 2026 年 9 月に廃止予定で、Azure ML Jobs への移行が推奨されています。MLflow による追跡自体は引き続き推奨です。
:::

- **いつ使う**: 実験の履歴を残し、複数 run を比較したい。
- **組み合わせ**: command job / Sweep / Pipelines の中で MLflow ログ → studio で比較 → 良い run のモデルを登録。

### Responsible AI dashboard — モデルを多面的に点検する

**Responsible AI(責任ある AI)dashboard** は、精度以外の観点でモデルを点検するコンポーネント群を 1 画面に集めたものです。

- **error analysis**: 誤りがどこに偏っているかを可視化し、平均より誤差の大きいデータのコホート(部分集合)を特定する。
- **fairness assessment**: 性別・年齢など、センシティブな属性のグループ間で挙動が偏っていないかを評価する。
- **model interpretability / counterfactual what-if**: 予測の根拠を人間が理解できる形で説明し、「入力をどう変えれば結果が変わるか」を示す。

### RAI scorecard(preview) — 対外的に説明する

**Responsible AI scorecard(preview)** は、上記ダッシュボードの結果を **PDF レポート**として生成し、技術者でないステークホルダーや監査向けに共有できる機能です。model registry でモデルを開き、Responsible AI タブから生成・参照します。

- **いつ使う**: 規制・監査・社内承認で、モデルの健全性を説明する必要がある。
- **組み合わせ**: 登録済みモデルに対してダッシュボードを生成 → scorecard を出力して共有。

使い分けはシンプルで、**数値の追跡=MLflow、モデルの公平性・説明性の点検=RAI dashboard、対外説明=scorecard** です。

参考: [MLflow and Azure Machine Learning](https://learn.microsoft.com/en-us/azure/machine-learning/concept-mlflow?view=azureml-api-2) / [What is Responsible AI?](https://learn.microsoft.com/en-us/azure/machine-learning/concept-responsible-ai?view=azureml-api-2) / [Responsible AI scorecard (preview)](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-responsible-ai-scorecard?view=azureml-api-2)

## 5. デプロイと運用 — 出した後を支える

**コア(位置だけ):** リアルタイム推論の **Online Endpoint** と一括推論の **Batch Endpoint** は前作で扱いました。補足すると、no-code 側では AutoML や Designer から学習済みモデルを**そのまま直接デプロイ**することもできます。ここでは「デプロイした後」を支える機能を見ます。

### Model monitoring — モデルの中身の劣化を見張る

デプロイしたモデルは、時間とともに入力データの分布が学習時とズレて精度が落ちます。**Model monitoring** は、本番データを学習データや直近の本番データと比較して、その劣化を検知します。

| 監視シグナル | 何を見るか |
|---|---|
| Data drift | 入力データの分布が学習時からどれだけズレたか |
| Prediction drift | 予測(出力)の分布のズレ |
| Data quality | 欠損値・型不一致・範囲外値などの入力データの健全性 |
| Feature attribution drift (preview) | 特徴量の重要度が学習時から変化していないか |
| Model performance: 分類/回帰 (preview) | 正解データと比較した精度(Accuracy / MAE など) |
| 生成 AI: 生成の安全性と品質 (preview) | groundedness や relevance などを GPT 支援で評価 |

- **いつ使う**: 本番モデルの精度劣化を早期に捉え、再学習のトリガにしたい。
- **組み合わせ**: ドリフト検知 → アラート → パイプラインで再学習 → Endpoint を更新、というループ。

### Registries — 資産を組織横断で共有・昇格する

前作の Model 登録は「1 つの workspace の中での」バージョン管理でした。**Registries(レジストリ)** は、その一段上です。Git リポジトリのように、**モデル・環境・コンポーネント・データセットを workspace から切り離して中央に置き、組織内のすべての workspace から使えるように**します。

- 開発 workspace でモデルを育て、良い候補をレジストリに publish。
- そこから **テスト用・本番用の別 workspace** へ昇格し、各環境の Endpoint にデプロイする。

- **いつ使う**: dev / test / prod を別 workspace で分け、資産を昇格させながら回す本格的な MLOps。
- **組み合わせ**: パイプラインで作った component やモデルをレジストリに登録 → 複数 workspace で共有。

### サービス監視(Azure Monitor / Application Insights)

モデルの中身ではなく、エンドポイントというインフラの稼働を見るのがこちらです。**Azure Monitor** と **Application Insights** で、エンドポイントのメトリクス・ログ・障害・パフォーマンスを追えます(どちらかというと管理者寄りの面です)。

使い分けは、**モデルの中身の劣化=Model monitoring、資産の組織共有・昇格=Registries、インフラの稼働=Azure Monitor** です。

参考: [Azure Machine Learning model monitoring](https://learn.microsoft.com/en-us/azure/machine-learning/concept-model-monitoring?view=azureml-api-2) / [Machine Learning registries for MLOps](https://learn.microsoft.com/en-us/azure/machine-learning/concept-machine-learning-registries-mlops?view=azureml-api-2) / [Monitor Azure Machine Learning](https://learn.microsoft.com/en-us/azure/machine-learning/monitor-azure-machine-learning?view=azureml-api-2)

## 6. 地図の端 — 生成 AI と Microsoft Foundry の境界

ここまで classic な ML(教師あり学習や自前モデルの学習・運用)の地図を描いてきました。studio にはもう一区画、**生成 AI(LLM)向けの機能**があります。

- **Model catalog**: Azure OpenAI・Mistral・Meta・Cohere・NVIDIA・Hugging Face など、数百のモデルを発見して使えるハブ。
- **Prompt flow**: LLM アプリの試作 → 実験 → 反復 → デプロイの開発サイクルを支援するツール。

ただし、ここが地図の端です。Microsoft は**生成 AI 用途を [Microsoft Foundry](https://learn.microsoft.com/en-us/azure/machine-learning/foundry-models-overview?view=azureml-api-2)(旧 Azure AI Foundry)へ誘導**しており、Azure ML studio と Foundry のどちらを使うべきかという公式ガイドがあるほどです。大まかな棲み分けは「**classic / カスタム ML の学習・運用は Azure ML studio、LLM アプリ構築は Foundry**」です。

公式の比較表から、両者の性格の違いが見えます。

| 観点 | Azure ML studio | Microsoft Foundry |
|---|---|---|
| AutoML | あり(回帰/分類/予測/CV/NLP) | なし |
| 学習用 compute | あり(ML クラスタ、Spark、Azure Arc) | なし |
| 対応言語 | Python / R / Scala / Java | Python のみ |

つまり、**自分でモデルを学習して運用する**なら Azure ML studio が地図の本体で、**既製の LLM を組み合わせてアプリを作る**なら Foundry へ歩いていく、という関係です。本記事はあくまで前者の地図なので、Foundry 側の中身には踏み込みません。

:::message
バージョンの境界として: SDK v1 は 2025 年 3 月 31 日に非推奨となり、サポートは 2026 年 6 月 30 日までです。既存の v1 ワークフローはそれまで動きますが、新規はすべて v2 を前提にしてください。
:::

参考: [What is Azure Machine Learning? — LLMs and Generative AI](https://learn.microsoft.com/en-us/azure/machine-learning/overview-what-is-azure-machine-learning?view=azureml-api-2) / [Microsoft ML products comparison](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/data-science-and-machine-learning)

## 7. 組み合わせ方 — 地図上の代表ルート

機能は単独でなく、つないで使います。地図の歩き方として、記述レベルの違う 3 つの代表ルートを挙げます。

**ルート A: no-code で完結する**
Data labeling でラベルを作る → AutoML か Designer で学習 → そのまま直接デプロイ。コードを 1 行も書かずに、データから推論 API まで到達できます。まず ML をクラウドで体験したい、データサイエンスの専任がいないチーム向け。

**ルート B: 当たりを付けてから作り込む**
AutoML で「どの手法が効くか」を素早く掴む → 有望な手法を command job で実装し直し、Sweep でハイパラを詰める → Model 登録 → Endpoint。探索の速さと作り込みの自由度を両取りするルートです。

**ルート C: code-first の本格 MLOps**
Feature store で特徴量を資産化 → Pipelines(component)で多段の学習を組む → MLflow で実験追跡 → Responsible AI dashboard で点検 → Registries で dev→test→prod へ昇格 → Endpoint にデプロイ → Model monitoring で劣化を見張り、ドリフトを検知したら再学習へ。地図のほぼ全域を使う、チーム開発・継続運用向けの経路です。

選定のコツは、機能名から入らないことです。**「コードをどれだけ書くか(縦軸)」と「いま工程のどこにいるか(横軸)」**の 2 つを自分に問えば、使うべき機能はおのずと地図上の 1 点に定まります。

## 8. まとめ

Azure ML studio の機能は今後も増えますが、それらを並べる**座標(記述レベル × 工程)は安定**しています。新しい機能に出会ったら、「これは no-code 寄りか code-first 寄りか」「データ準備・学習・評価・デプロイ・運用のどの工程の道具か」を問えば、地図のどこに置けばよいかが分かります。

| 工程 | この記事で見た主な機能(新規) | ひとことの役割 |
|---|---|---|
| データ準備 | Data labeling / Notebooks / Feature store | ラベル作成・対話的探索・特徴量の資産化 |
| 学習・探索 | AutoML / Designer / Sweep / Pipelines | 自動化・可視化・ハイパラ探索・多段の連結 |
| 評価・説明責任 | MLflow / Responsible AI dashboard / scorecard | 記録・点検・対外説明 |
| デプロイ・運用 | Model monitoring / Registries / Azure Monitor | 劣化検知・組織共有/昇格・インフラ監視 |
| 地図の端 | Model catalog / Prompt flow → Foundry | 生成 AI アプリは Foundry へ |

前作で引いた一本道(Compute → Job → Model → Endpoint)に、本作の地図を重ねると、Azure ML studio の全体像が立体になります。網羅リストを暗記する必要はありません。**この 2 軸の座標系を持ち帰り、必要になった工程で、必要な記述レベルの機能を地図から取り出してください。**

---

### 参考リンク(一次情報)

- [What is Azure Machine Learning?](https://learn.microsoft.com/en-us/azure/machine-learning/overview-what-is-azure-machine-learning?view=azureml-api-2)
- [What is automated ML? (AutoML)](https://learn.microsoft.com/en-us/azure/machine-learning/concept-automated-ml?view=azureml-api-2)
- [What is Designer (v2)?](https://learn.microsoft.com/en-us/azure/machine-learning/concept-designer?view=azureml-api-2)
- [Hyperparameter tuning a model (v2)](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-tune-hyperparameters?view=azureml-api-2)
- [Create and run component-based ML pipelines (CLI)](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-create-component-pipelines-cli?view=azureml-api-2)
- [What is managed feature store?](https://learn.microsoft.com/en-us/azure/machine-learning/concept-what-is-managed-feature-store?view=azureml-api-2)
- [MLflow and Azure Machine Learning](https://learn.microsoft.com/en-us/azure/machine-learning/concept-mlflow?view=azureml-api-2)
- [What is Responsible AI?](https://learn.microsoft.com/en-us/azure/machine-learning/concept-responsible-ai?view=azureml-api-2)
- [Use Responsible AI scorecard (preview)](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-responsible-ai-scorecard?view=azureml-api-2)
- [Azure Machine Learning model monitoring](https://learn.microsoft.com/en-us/azure/machine-learning/concept-model-monitoring?view=azureml-api-2)
- [Machine Learning registries for MLOps](https://learn.microsoft.com/en-us/azure/machine-learning/concept-machine-learning-registries-mlops?view=azureml-api-2)
- [Monitor Azure Machine Learning](https://learn.microsoft.com/en-us/azure/machine-learning/monitor-azure-machine-learning?view=azureml-api-2)
- [Microsoft Machine Learning products comparison](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/data-science-and-machine-learning)
