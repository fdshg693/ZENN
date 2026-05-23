---
title: "SLM を Azure で鍛えて・絞って・載せる — Microsoft エコシステムのファインチューニング・ライフサイクル"
status: plan
---

## ねらいと位置づけ

シリーズの後続記事。前作の接続点:

- 「[ファインチューニング技法の地図](../../publish/ml/finetuning_technique_map.md)」の **実装レイヤ(第3層: マネージド)** を、**SLM × Microsoft/Azure** に絞って深掘りする。
- 「[Azure Machine Learning の最短ルート](../../publish/ml/azure_ml.md)」の **command job / Online Endpoint** が、自前ファインチューニングとデプロイの土台としてそのまま効く。

技法の地図が「**どんな手法があるか**(WHAT)」だったのに対し、本記事は **SLM を Azure で「鍛える → 絞る → 載せる」という一連の流れ(ライフサイクル)** を縦に追う。Phi を軸に、Llama / Mistral など主要 OSS にも触れる。エッジ/オンデバイス(Foundry Local / Phi Silica)は「地図の端」として軽く扱う。

- **対象読者**: FT 技法の地図は持っている。Azure ML の基礎(Workspace / command job / Endpoint)も分かる。SLM を Azure で実際に特化させ、運用に載せる流れを掴みたい人。
- **答える問い**: SLM を Azure で鍛えるならどこで(どのレイヤで)やるか、鍛えた後どう絞って、どこ(クラウド/エッジ)に載せるか。
- **扱わない**: 個別手法の数式、Azure の基礎概念、ネットワーク隔離の作り込み、RAG/生成 AI アプリ構築、料金の精密試算。

## タイトル案

1. SLM を Azure で鍛えて・絞って・載せる — Microsoft エコシステムのファインチューニング・ライフサイクル
2. 小さく特化させて、手元でも動かす — Azure で SLM をファインチューニングする縦断ルート
3. Phi を自分のデータで鍛える — Microsoft エコシステムの SLM ファインチューニング地図

## 構成

### この記事について
位置づけ・対象読者・扱う/扱わない範囲。前2作との接続を明示。

### 1. なぜ SLM を、わざわざファインチューニングするのか
- SLM は compute footprint が小さく、cloud と edge の両対応で低コスト低レイテンシ。Phi-3 は同サイズ・1つ上のサイズのモデルを上回るとされる。
- 小さいモデルを FT するのは「性能を犠牲にしない良い代替」。特定タスク/スキルの習得、tone/style/一貫性の改善に向く。
- SLM 固有の旨み = **安く特化でき、かつ手元(NPU/エッジ)でも動かせる** → だから「鍛える→絞る→載せる」というライフサイクル全体が意味を持つ(大規模 LLM なら RAG で済ますところ)。
- 技法地図との接続: SLM FT も軸1(LoRA/QLoRA)・軸2(SFT/DPO/RFT)はそのまま。変わるのは「プラットフォーム」と「鍛えた後の物語(絞る+エッジ)」。
- 根拠: extract_why_slm(Azure blog Phi-3 FT 発表)

### 2. 鍛える — Azure 上、3つのファインチューニングのレイヤ
SLM をどこで FT するか。技法地図の実装レイヤを SLM×Azure に具体化。
- **マネージド serverless(Microsoft Foundry)**: API にデータを渡すだけ。SFT 対応に Phi-4 / Phi-4-mini-instruct / Llama / Mistral Nemo / Ministral-3B / Mistral Large / NTT Tsuzumi-7b など。3技法(SFT/DPO/RFT)。「ほとんどの顧客は serverless が ease-of-use・コスト・プレミアムモデルのバランスで最良」。制約: hub/project とリージョン可用性、データは JSONL/UTF-8+BOM/<512MB/会話形式、CMK 非対応。
- **マネージド managed compute(Foundry, preview)**: 自分の VM クォータで学習・推論。serverless にない open model やより強い制御が要るとき。
- **自前(Azure ML + TRL / Unsloth)**: 前作の command job がそのまま土台。`LLM-Fine-Tuning-Azure` に Phi-3-mini(TRL+LoRA)、Phi-4-mini(Azure SDK)、Llama3.2-11B Vision(Unsloth)等の Lab。最大の自由度。
- **鍛えた後に手に入る2形態**: フルの重み or LoRA/PEFT アダプタ。これが次段(絞る/載せる)の分岐を決める。
- 根拠: extract_foundry_ft, extract_managed_compute_ft, extract_why_slm(repo)

### 3. 絞る — Olive で最適化・量子化して ONNX にする
本シリーズ初出のステージ。SLM 固有の「小さくして手元に載せる」中核。
- Olive(ONNX LIVE)= 最適化ツールキット + CLI。PyTorch/HF → デバイス(NPU/GPU/CPU; Qualcomm/AMD/Nvidia/Intel)向け最適化 ONNX を出力。
- workflow = passes(compression / graph capture / quantization / graph optimization)の列、evaluator と search で自動チューニング。40+ コンポーネント。
- CLI: `olive finetune`(→ HF PEFT アダプタ, LoRA/QLoRA, 要 GPU)、`olive quantize`、`olive auto-opt`(→ 最適化 ONNX + アダプタ)、`olive capture-onnx-graph`、`olive generate-adapter`、`olive init`(対話ウィザード)。
- Multi-LoRA serving / Azure AI 連携(リモート計算)/ shared cache。AI Toolkit(VS Code)も内部で Olive。
- 正直な注意: 「Olive CLI と最適化設定は変わり、単一コマンドが全モデル/デバイス/EP で動くとは限らない」→ Olive Recipes から始める。
- 根拠: extract_olive, extract_olive_cli

### 4. 載せる — クラウドとエッジ、2つの行き先
- **クラウド**: serverless はそのまま serverless API としてデプロイ(クロスリージョン/サブスクも可)。managed compute は Azure ML の managed online endpoint(前作の Endpoint/Deployment 分離がそのまま)。Content Safety 連携。
- **エッジ(地図の端)**:
  - Foundry Local: デバイス上で ONNX を実行(ONNX Runtime + WinML、初回 DL 後はオフライン)。推奨パラメータ帯 1B–3B / 3B–7B。カタログに限らず、Olive で HF→ONNX に compile して `inference_model.json` で公開すれば自前モデルも動く。
  - Phi Silica LoRA(Windows Copilot+ PC の NPU): LoRA アダプタを学習し推論時に適用。`.safetensors` アダプタ、AI Dev Gallery / AI Toolkit、LanguageModelExperimental。中国では非提供。
  - (軽く)Foundry Local on Azure Local: OCI レジストリ + k8s operator で BYO(vLLM/ONNX)。
- エッジでこそ SLM FT が活きる: データがデバイス内に留まる(コンプライアンス)、オフライン、低レイテンシ。
- 根拠: extract_foundry_ft, extract_foundry_local, extract_edge

### 5. 通して見る — ライフサイクル1枚と歩き方
- 1枚表/図: 鍛える(レイヤ選択)→ 絞る(Olive)→ 載せる(クラウド/エッジ)。
- 選定ガイド(問いから入る): とりあえず特化=serverless SFT→serverless 配信 / 手元・オフライン=自前 or `olive finetune`→`auto-opt`→Foundry Local・Phi Silica / 口調=DPO / 採点できる正しさ=RFT。
- 接続のまとめ: 軸(技法地図)はそのまま、command job/Endpoint(azure_ml)は土台、本記事は「絞る」と「エッジ」を足した。

### まとめ
3つの動詞「鍛える・絞る・載せる」。SLM の独自価値 = このループをデバイスまで一周できること。

## 主要参考 URL(根拠)
- Azure blog: Announcing Phi-3 fine-tuning <https://azure.microsoft.com/en-us/blog/announcing-phi-3-fine-tuning-new-generative-ai-models-and-other-azure-ai-updates-to-empower-organizations-to-customize-and-scale-ai-applications>
- Fine-tune models with Microsoft Foundry (classic) — overview <https://learn.microsoft.com/en-us/azure/foundry-classic/concepts/fine-tuning-overview>
- Deploy fine-tuned models with serverless API <https://learn.microsoft.com/en-us/azure/foundry-classic/how-to/fine-tune-serverless>
- Customize a model with fine-tuning (Foundry / Azure OpenAI) <https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/fine-tuning>
- Azure/LLM-Fine-Tuning-Azure <https://github.com/Azure/LLM-Fine-Tuning-Azure>
- Olive overview <https://microsoft.github.io/Olive/why-olive.html> / `finetune` CLI <https://microsoft.github.io/Olive/how-to/cli/cli-finetune.html>
- Olive CLI blog <https://onnxruntime.ai/blogs/olive-cli> / microsoft/olive <https://github.com/microsoft/olive>
- Compile Hugging Face models to run on Foundry Local <https://learn.microsoft.com/en-us/azure/foundry-local/how-to/how-to-compile-hugging-face-models>
- Foundry Local architecture <https://learn.microsoft.com/en-us/azure/foundry-local/concepts/foundry-local-architecture>
- Foundry Local: A New Era of Edge AI <https://devblogs.microsoft.com/foundry/foundry-local-a-new-era-of-edge-ai>
- LoRA Fine-Tuning for Phi Silica <https://learn.microsoft.com/en-us/windows/ai/apis/phi-silica-lora>
