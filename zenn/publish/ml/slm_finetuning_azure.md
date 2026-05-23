---
title: "SLM を Azure で鍛えて・絞って・載せる — Microsoft エコシステムのファインチューニング・ライフサイクル"
emoji: "🪆"
type: "tech"
topics: ["azure", "finetuning", "slm", "phi", "lora"]
published: false
---

## この記事について

前作「[LoRA・DPO・蒸留・モデルマージは何が違うのか — ファインチューニング技法の地図](./finetuning_technique_map)」では、ファインチューニングを 5 つの軸で並べ直しました。その最後に **実装レイヤ(誰がどこで回すか)** という軸を置き、第3層として「マネージドに任せる(OpenAI / Azure AI Foundry / Vertex AI)」を挙げました。本記事はその第3層を、**SLM(Small Language Model)× Microsoft / Azure** に絞って、もう一段深く歩きます。

技法の地図が「**どんな手法があるか**(WHAT)」だったのに対し、本記事が描くのは **SLM を Azure で「鍛える → 絞る → 載せる」という一連の流れ(ライフサイクル)** です。Phi ファミリーを軸に、Llama / Mistral など主要 OSS にも触れます。

```
鍛える(fine-tune)      絞る(optimize)        載せる(deploy)
─────────────────  →  ─────────────────  →  ─────────────────
serverless / 自前       Olive で量子化         クラウド endpoint
で SLM を特化            ・ONNX 変換            / エッジ(手元)
```

土台としては、もう一つの前作「[Azure Machine Learning で学習からデプロイまでの最短ルート](./azure_ml)」で見た **command job** と **Online Endpoint** がそのまま効きます。自前で鍛えるとき・クラウドに載せるときに、あの一本道の上に乗る形になります。

- **対象読者**: ファインチューニング技法の地図は持っている。Azure ML の基礎(Workspace / command job / Endpoint)も分かる。SLM を Azure で実際に特化させ、運用に載せる流れを掴みたい人。
- **扱わないこと**: 個別手法の数式、Azure の基礎概念、ネットワーク隔離の作り込み、RAG/生成 AI アプリ構築、料金の精密試算。エッジ/オンデバイスは「地図の端」として軽く触れるにとどめます。

:::message
本記事は執筆時点(2026 年 5 月)の公開情報に基づきます。Microsoft Foundry はリブランド(旧 Azure AI Foundry / Azure OpenAI)が進行中で、**対応モデル・リージョン可用性・preview 状況・料金は頻繁に変わります**。本番判断の前に必ず公式ドキュメントと自分のサブスクリプションの状態を確認してください。
:::

## 1. なぜ SLM を、わざわざファインチューニングするのか

大きなモデルに RAG やプロンプト工夫で対応する道もあるなかで、なぜ小さなモデルをわざわざ追加学習するのか。Microsoft が Phi-3 のファインチューニングを発表したときの説明が、SLM を鍛える動機をよく表しています。Phi-3 は「最も高性能でコスト効率の良い SLM で、同サイズ・1 つ上のサイズのモデルを上回る」とされ、そのうえで「**特定のビジネス要件に合わせて応答品質を上げたいとき、小さいモデルをファインチューニングするのは、性能を犠牲にしない優れた代替手段だ**」と位置づけられました（[Announcing Phi-3 fine-tuning](https://azure.microsoft.com/en-us/blog/announcing-phi-3-fine-tuning-new-generative-ai-models-and-other-azure-ai-updates-to-empower-organizations-to-customize-and-scale-ai-applications)）。

向く場面として挙げられているのは、新しいスキルやタスクの習得（例: チュータリング）、応答の一貫性や品質の向上（例: チャット/Q&A での tone・style）です。

ここで SLM 固有の旨みを押さえておきます。同じ発表が続けて指摘しているのは、Phi-3 が「**小さな計算フットプリント、クラウドとエッジの両対応**」ゆえにファインチューニングに向く、という点です。さらに同じ Phi ファミリーから、デバイス向けに調整した **Phi Silica**（Copilot+ PC の NPU 向け、Windows に同梱される SLM）も生まれています。

つまり SLM では、

- **安く特化できる**（小さいので LoRA などで軽く鍛えられる）
- **鍛えた後、手元(NPU・エッジ)でも動かせる**

という 2 つが同時に成り立ちます。大規模 LLM なら「RAG で済ます」「マネージド API を叩く」で終わりがちなところを、SLM では「鍛える → 小さく絞る → デバイスに載せる」という**ライフサイクル全体**が現実的な選択肢になる。これが本記事を「手法の一覧」ではなく「縦断の流れ」として書く理由です。

技法の地図との接続も確認しておきます。SLM のファインチューニングでも、前作の **軸1(LoRA / QLoRA でどこまで重みを動かすか)** と **軸2(SFT / DPO / RFT で何を最適化するか)** はそのまま使えます。SLM で変わるのは手法そのものではなく、**それを回すプラットフォーム**と、**鍛えた後の物語(絞る・載せる)**です。では順に歩いていきましょう。

## 2. 鍛える — Azure 上、3 つのファインチューニングのレイヤ

SLM を Azure で鍛えるとき、入口は 1 つではありません。技法地図の「実装レイヤ」を Azure に具体化すると、制御と運用のラクさのトレードオフで 3 層に分かれます。

| レイヤ | 何をするか | 向くとき |
|---|---|---|
| **マネージド serverless**(Microsoft Foundry) | データと method を渡すだけ。インフラを見ない | まず特化させたい。対応モデルで足りる |
| **マネージド managed compute**(Foundry, preview) | 自分の VM クォータ上で学習・推論を回す | serverless 非対応のモデルを使いたい・より制御したい |
| **自前**(Azure ML + TRL / Unsloth) | command job で学習スクリプトを自分で回す | 手法・データ処理を完全に握りたい |

### レイヤ1: serverless — データを渡すだけ

Microsoft Foundry のファインチューニングには **serverless** と **managed compute** の 2 つのモダリティがあり、公式は「**ほとんどの顧客にとって serverless が、使いやすさ・コスト効率・プレミアムモデルへのアクセスのバランスで最良**」としています（[Fine-tuning overview](https://learn.microsoft.com/en-us/azure/foundry-classic/concepts/fine-tuning-overview)）。インフラを一切持たず、学習データ(JSONL)と手法を指定するだけで鍛えられます。

提供される学習手法は 3 つ。前作の軸2(模倣 → 選好 → 採点)がそのままマネージドの引数になります。

- **SFT（教師あり）**: 入出力ペアで学習する基礎技法。最も広い範囲をカバー。
- **DPO（選好最適化）**: どちらの応答が好ましいかを学ぶ。tone・style の調整に向く。
- **RFT（強化ファインチューニング）**: grader（採点器）の報酬で複雑な振る舞いを最適化する。

そして SLM 視点で重要なのが、**SFT の対応モデル一覧に SLM が含まれている**ことです。公式の対応リストには、GPT 4o 系のほか **Phi 4、Phi-4-mini-instruct**、Llama 2 / Llama 3.1、Mistral Nemo、**Ministral-3B**、Mistral Large (2411)、NTT Tsuzumi-7b などが並びます（[Fine-tuning overview](https://learn.microsoft.com/en-us/azure/foundry-classic/concepts/fine-tuning-overview)）。Phi を自社データで SFT する、というのがコードをほぼ書かずに到達できる、ということです。

ここで「LoRA」という言葉が地続きで出てきます。Foundry/Azure OpenAI のファインチューニング解説は、「元の高ランク行列を低ランクで近似し、重要なパラメータの小さな部分集合だけを学習することで、他の手法より**速く・安く**なる」と LoRA を説明しています（[Customize a model with fine-tuning](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/fine-tuning)）。技法地図の軸1がそのまま、マネージドの内部実装として効いているわけです。

**serverless の制約（断定の前に確認すべき点）**:

- 利用できるかは**モデル提供者がそのリージョンでオファーを出しているか**に依存します。hub/project を「そのモデルがファインチューニング可能なリージョン」に持つ必要があります（[deploy/fine-tune serverless](https://learn.microsoft.com/en-us/azure/foundry-classic/how-to/fine-tune-serverless)）。「Phi-4 を serverless で」が常にどこでも通るわけではありません。
- 学習データは **JSONL / UTF-8(BOM 付き)/ 1 ファイル 512MB 未満 / 会話形式**。
- **顧客管理キー(CMK)は serverless ファインチューニングではサポート外**。
- 料金は概ね「**学習に走った時間だけが課金対象**」（ジョブ投入・前処理・モデル生成は非課金）。RFT では grader 用の推論コストが別途乗ります（[fine-tuning cost management](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/fine-tuning-cost-management)）。

### レイヤ2: managed compute — 自分のクォータで回す

serverless で対応していないモデルを使いたい、あるいはもっと制御したい場合は **managed compute（preview）** です。hub/project と、**学習・推論用の VM クォータ**を自分で用意し、その上でファインチューニングを回します（[Fine-tuning overview](https://learn.microsoft.com/en-us/azure/foundry-classic/concepts/fine-tuning-overview)）。前作 Azure ML の「コンピュートクォータは学習・デプロイで共有」という課金の罠が、ここでもそのまま当てはまります。preview である点に注意。

なお、新しい Foundry の UI / リソースでないと扱えないモデルもあります。たとえば Ministral-3B・Qwen-32B・Llama-3.3-70B-Instruct・gpt-oss-20b といった OSS 系は「**Foundry リソースかつ新 Foundry UI でのみサポート**」と明記されています（[Customize a model with fine-tuning](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/fine-tuning)）。"対応している" の解像度はモデルごと・面ごとに違うので、必ず最新の対応表で裏を取ってください。

### レイヤ3: 自前 — Azure ML の command job で TRL / Unsloth を回す

最大の自由度がほしいなら、前作で見た **Azure ML の command job** の上で、Hugging Face TRL や Unsloth を自分で回します。これは技法地図の「第1層: 自分で書く」を Azure のマネージド計算資源に載せる形です。

Microsoft 公式のサンプル集 [Azure/LLM-Fine-Tuning-Azure](https://github.com/Azure/LLM-Fine-Tuning-Azure) には、まさに SLM を含む Lab が並んでいます。

- **Phi-3-mini** を Hugging Face TRL の LoRA で（プロコード Python SDK）
- **Phi-4-mini** を Azure Python SDK で（ローコード）
- **Llama3.2-11B Vision** を Unsloth で（プロコード）
- SFT / DPO / RFT それぞれの GPT 系 Lab

イメージとしては、前作の `command(...)` の `command` に TRL の学習スクリプトを、`environment` に TRL/Unsloth を含む環境を、`compute` に GPU クラスタを指定して投げる、という形です。学習ループとデータ処理をすべて握れる代わりに、環境構築とコストは自分持ちになります。

### 鍛えると、2 つの形のどちらかが手に入る

レイヤを問わず、ファインチューニングの**出力**は次段の分岐を決めます。

- **フルの重み**（または重みにマージ済みのモデル）
- **LoRA / PEFT アダプタ**（土台は据え置き、差分だけ）

この区別が、次の「絞る」「載せる」で効いてきます。アダプタのまま複数を差し替えて配信する道（multi-LoRA）と、量子化して 1 つの軽量モデルに固める道では、取り回しが変わるからです。

## 3. 絞る — Olive で最適化・量子化して ONNX にする

ここからが本シリーズで初めて踏み込むステージです。鍛えた SLM を「**手元で動くサイズまで絞る**」工程で、Microsoft エコシステムでは **Olive** がその中核を担います。

Olive（**O**NNX **LIVE**）は、CLI を備えたモデル最適化ツールキットです。入力は PyTorch または Hugging Face モデル、出力は **ONNX Runtime 上で動く最適化済み ONNX モデル**。Qualcomm・AMD・Nvidia・Intel といったベンダーの **NPU / GPU / CPU** という具体的なデプロイ先に向けて最適化します（[Olive overview](https://microsoft.github.io/Olive/why-olive.html)）。

仕組みは前作のモデルマージとは別物で、**workflow（一連の最適化タスク＝passes）** を順に流します。passes には圧縮・グラフキャプチャ・量子化・グラフ最適化などがあり、各 pass のパラメータを evaluator で評価しながら search で自動チューニングします。組み込みの最適化コンポーネントは 40 以上（[Olive overview](https://microsoft.github.io/Olive/why-olive.html)）。

実務では CLI のサブコマンドで十分なことが多いです。

```bash
# 1) 鍛える: HF モデルを LoRA/QLoRA で微調整 → HF PEFT アダプタが出力される(要 GPU)
olive finetune \
  --model_name_or_path meta-llama/Llama-3.2-1B-Instruct \
  --method qlora \
  --data_name <your-dataset> \
  --output_path models/ft

# 2) 絞る: 量子化して ONNX 化、最適化(アダプタも ONNX Runtime 用に変換)
olive auto-opt \
  --model_name_or_path models/ft \
  --adapter_path models/ft/adapter \
  --provider <ONNX Runtime EP> \
  --precision int4 \
  --output_path models/onnx
```

`olive finetune` は HF の PEFT アダプタ（LoRA / QLoRA）を出力し、`olive auto-opt` がそれを最適化 ONNX モデル + ONNX Runtime 用アダプタに変換します（[`finetune` CLI](https://microsoft.github.io/Olive/how-to/cli/cli-finetune.html), [Olive CLI blog](https://onnxruntime.ai/blogs/olive-cli)）。ほかに `olive quantize`、`olive capture-onnx-graph`、`olive generate-adapter`、対話ウィザードの `olive init` などがあります。

SLM の取り回しを大きく左右する機能が 2 つあります。

- **multi-LoRA serving**: 1 つの土台モデルに複数の LoRA アダプタを載せて配信できる。多数の特化版を抱えても計算フットプリントを抑えられる（[`finetune` CLI](https://microsoft.github.io/Olive/how-to/cli/cli-finetune.html)）。前章の「アダプタのまま持つ」道がここで活きます。
- **Azure AI 連携**: GPU が手元になくても、Azure AI 連携でリモート計算を使って `finetune` を回せる（[`finetune` CLI](https://microsoft.github.io/Olive/how-to/cli/cli-finetune.html)）。前章のレイヤ3(自前 Azure ML)と地続きです。

なお VS Code の **AI Toolkit** も内部で Olive を使ってモデルを微調整しており、GUI 寄りの入口も用意されています（[microsoft/olive](https://github.com/microsoft/olive)）。

:::message
**断定を避けるべき注意**: 公式自身が「Olive CLI と最適化設定は時間とともに変わり、単一のコマンド例があらゆるモデル・デバイス・実行プロバイダ(EP)で動くとは限らない」と明言しています。確実な出発点として **Olive Recipes**（モデル・ハードウェア別の最適化レシピ集）から始めることが推奨されています（[Compile HF models for Foundry Local](https://learn.microsoft.com/en-us/azure/foundry-local/how-to/how-to-compile-hugging-face-models)）。上のコマンドは流れを示す骨格として読んでください。
:::

なぜこの「絞る」が SLM 固有かというと、**1〜7B 規模のモデルを int4 などに量子化して初めて、エッジ機器や NPU に載るサイズになる**からです。大規模 LLM ではこの工程の先に「手元で動かす」現実味が薄い。SLM だからこそ、次の「載せる」でクラウドとエッジの両方が選択肢になります。

## 4. 載せる — クラウドとエッジ、2 つの行き先

絞った（あるいは絞らずに鍛えただけの）モデルを、最後にどこに載せるか。SLM では行き先が大きく 2 方向に分かれます。

### クラウドに載せる

前作 Azure ML の「Endpoint と Deployment の分離」がそのまま使えます。

- **serverless でファインチューニングした場合**: そのまま **serverless API** としてデプロイできます。しかも**学習したリージョンと別のリージョン/サブスクリプションへデプロイ**することも可能です（権限などの条件付き）（[fine-tune serverless](https://learn.microsoft.com/en-us/azure/foundry-classic/how-to/fine-tune-serverless)）。
- **managed compute / 自前の場合**: Azure ML の **managed online endpoint** に載せます。前作の `ManagedOnlineEndpoint` / `ManagedOnlineDeployment`、blue/green、scoring script、そして「**Online Endpoint の裏の VM は常時起動＝課金され続ける**」という注意点が、ここでもそっくり当てはまります。managed compute では Azure AI Content Safety を噛ませて有害コンテンツを遮断する構成も取れます（[Foundry models overview](https://learn.microsoft.com/en-us/azure/foundry-classic/concepts/foundry-models-overview)）。

### エッジ／手元に載せる（地図の端）

ここが SLM ならではの行き先です。本記事では深入りせず、輪郭だけ示します。

**Foundry Local** は、Microsoft Build 2025 で発表された、デバイス上で SLM をローカル推論するためのランタイムです。技術的土台は **ONNX Runtime**（Windows では WinML を介して実行プロバイダを登録）で、**初回にモデルと EP をダウンロードした後は完全にオフラインで動く**のが特徴です（[Foundry Local architecture](https://learn.microsoft.com/en-us/azure/foundry-local/concepts/foundry-local-architecture), [Foundry Local: A New Era of Edge AI](https://devblogs.microsoft.com/foundry/foundry-local-a-new-era-of-edge-ai)）。エッジ向けのモデル選定の目安として、1B–3B は IoT/エッジ機器（簡単な対話・分類）、3B–7B はエッジサーバ/高性能機（複雑な推論・マルチモーダル）という帯が示されています。

ここで前章「絞る」とつながります。Foundry Local はカタログのモデルに限られません。公式は「**カタログのモデルに縛られない。自分のモデルを ONNX 形式に compile・最適化して動かせる**」とし、その**推奨手段が Olive** だと明言しています（[Foundry Local architecture](https://learn.microsoft.com/en-us/azure/foundry-local/concepts/foundry-local-architecture)）。具体的には Olive で HF モデルを ONNX（`.onnx` + `genai_config.json` + tokenizer）に変換し、`inference_model.json` を置いて Foundry Local に公開する、という流れです（[Compile HF models for Foundry Local](https://learn.microsoft.com/en-us/azure/foundry-local/how-to/how-to-compile-hugging-face-models)）。**鍛える(2 章) → 絞る(3 章) → 手元に載せる**、というループがここで一周します。

もう一つ象徴的なのが **Phi Silica の LoRA ファインチューニング**です。Copilot+ PC の NPU 向けに Windows へ同梱される Phi Silica に対し、**LoRA アダプタを学習して推論時に適用**することで、特定用途の精度を上げられます。アダプタは `.safetensors` 形式で、AI Dev Gallery / AI Toolkit から扱い、`LanguageModel`(Experimental)API で読み込みます（[LoRA Fine-Tuning for Phi Silica](https://learn.microsoft.com/en-us/windows/ai/apis/phi-silica-lora)）。これは「鍛える」と「載せる」がほぼ一体化した、最もエッジ寄りの形です。

:::message
エッジ側にも明確な制約があります。Phi Silica の機能は**中国では提供されていません**。また企業向けのオンプレ展開（Foundry Local on Azure Local）では、自前モデルを **OCI レジストリのアーティファクトとして Kubernetes operator 経由で BYO** する形になり、クラウドの serverless とは運用がまったく異なります。「エッジに載る」と一言で言っても、Windows 個人デバイス・エッジサーバ・オンプレ K8s で道具立てが分かれます。
:::

**エッジで SLM FT が活きる理由**は、性能だけではありません。データがデバイス内に留まるためコンプライアンス上の利点があり（規制業種で機微データを組織の境界内に保てる）、オフラインで動き、低レイテンシになる——これらは「小さく特化させて手元に置ける」SLM だからこそ取れる選択肢です。

## 5. 通して見る — ライフサイクル 1 枚と歩き方

3 つの動詞を 1 枚に並べます。

| 段階 | 主な選択肢 | SLM 視点のポイント |
|---|---|---|
| **鍛える** | serverless(Foundry) / managed compute(preview) / 自前(Azure ML + TRL・Unsloth) | Phi-4・Ministral-3B などが対応。出力はフル重み or LoRA アダプタ |
| **絞る** | Olive(`finetune` → `auto-opt`、量子化、ONNX 化、multi-LoRA) | int4 等まで絞って初めて NPU/エッジに載る。Recipes から始める |
| **載せる** | クラウド(serverless API / Azure ML endpoint) / エッジ(Foundry Local・Phi Silica LoRA) | カタログ外の自前モデルも Olive→ONNX で Foundry Local に載る |

選定は手法名からではなく、**問いから入る**のが歩き方です。

- **まず特化させたいだけ** → serverless で SFT → serverless API で配信。コードをほぼ書かずに一周できる。
- **手元・オフラインで動かしたい** → 自前 or `olive finetune` で鍛え、`olive auto-opt` で ONNX 化 → Foundry Local / Phi Silica。データを外に出さない。
- **教えたいのが主観的な口調** → DPO。**採点で正しさを定義できる** → RFT(grader コスト増に注意)。
- **serverless 非対応のモデルを使いたい** → managed compute(preview)か自前 Azure ML。

シリーズ全体での位置づけを最後に確認します。技法地図の**軸(LoRA/QLoRA・SFT/DPO/RFT)はそのまま**効き、Azure ML 記事の **command job と Online Endpoint が土台**になり、本記事はそこに **「絞る(Olive)」と「エッジに載せる」** という SLM 固有の 2 ステージを足しました。

## まとめ

SLM のファインチューニングは、「鍛える」だけでは終わりません。Microsoft エコシステムでは、

- **鍛える**: serverless で手軽に、managed compute や自前 Azure ML で自由に
- **絞る**: Olive で量子化・ONNX 化して手元サイズへ
- **載せる**: クラウドの endpoint へ、あるいは Foundry Local / Phi Silica でデバイスへ

という 3 つの動詞が一本につながります。**このループをデバイスまで一周できること**こそ、大規模 LLM ではなく SLM をわざわざ鍛える最大の理由です。次に新しい SLM や新しい最適化ツールに出会ったときは、「それは鍛える・絞る・載せるのどの段階の道具か」を問えば、この縦断の地図の上に置けます。

---

### 主な参考資料（一次情報）

- Announcing Phi-3 fine-tuning（Azure Blog）: <https://azure.microsoft.com/en-us/blog/announcing-phi-3-fine-tuning-new-generative-ai-models-and-other-azure-ai-updates-to-empower-organizations-to-customize-and-scale-ai-applications>
- Fine-tune models with Microsoft Foundry (classic) — overview: <https://learn.microsoft.com/en-us/azure/foundry-classic/concepts/fine-tuning-overview>
- Deploy fine-tuned models with serverless API: <https://learn.microsoft.com/en-us/azure/foundry-classic/how-to/fine-tune-serverless>
- Customize a model with fine-tuning（Foundry / Azure OpenAI）: <https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/fine-tuning>
- Fine-tuning cost management: <https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/fine-tuning-cost-management>
- Foundry models overview: <https://learn.microsoft.com/en-us/azure/foundry-classic/concepts/foundry-models-overview>
- Azure/LLM-Fine-Tuning-Azure（Phi-3/Phi-4 を含む Lab 集）: <https://github.com/Azure/LLM-Fine-Tuning-Azure>
- Olive overview: <https://microsoft.github.io/Olive/why-olive.html>
- Olive `finetune` CLI: <https://microsoft.github.io/Olive/how-to/cli/cli-finetune.html>
- Democratizing AI Model optimization with the new Olive CLI: <https://onnxruntime.ai/blogs/olive-cli>
- microsoft/olive（GitHub）: <https://github.com/microsoft/olive>
- Compile Hugging Face models to run on Foundry Local: <https://learn.microsoft.com/en-us/azure/foundry-local/how-to/how-to-compile-hugging-face-models>
- Foundry Local architecture: <https://learn.microsoft.com/en-us/azure/foundry-local/concepts/foundry-local-architecture>
- Foundry Local: A New Era of Edge AI: <https://devblogs.microsoft.com/foundry/foundry-local-a-new-era-of-edge-ai>
- LoRA Fine-Tuning for Phi Silica: <https://learn.microsoft.com/en-us/windows/ai/apis/phi-silica-lora>
