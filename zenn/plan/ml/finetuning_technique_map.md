---
title: "LoRA・DPO・蒸留・モデルマージは何が違うのか — ファインチューニング技法の地図"
status: plan
---

## ねらい

- 対象読者: ファインチューニングの概要は知っている（SFT で特定タスクにモデルを寄せられることは分かる）が、LoRA・DPO・蒸留・モデルマージ・RFT が「同じ話なのか別物なのか」「それぞれ何の問題を解くのか」の地図を持っていないエンジニア。
- 答える問い: それらの技法は互いにどう位置づけられ、どんな時にどれを選ぶのか。
- 方針: 網羅しない。**いくつかの軸を立て、各軸から代表点をいくつか選び、ツールを 1 つずつ紐付ける**ことで全体の輪郭を出す。バラエティ重視。
- フォーマット: 概念マップ中心 + 各手法に最小コード/設定断片（数行）。
- 扱わない: ツールの網羅列挙、数式の導出、ハイパラ完全ガイド、ファインチューニング概論そのもの、RAG 等「学習しない適応」との詳細比較（軸の外として一言）。

## 背骨となる発想

「ファインチューニング」は一枚岩ではなく、**いくつかの軸が張る空間**。座標を決める問いは大きく 3 つ:

1. **どこまで重みを動かすか**（全部 / ごく一部 / 動かさず重み空間で操作）
2. **何を最適化するか**（模倣 / 人間の選好 / 採点関数）
3. **どの知識を、どこから入れるか**（自前データ / ドメインコーパス / 別モデル）

加えて「**どのモダリティか**」「**自分で書くか / マネージドに任せるか**」が直交する。記事はこの座標で各手法を置き直す。

## セクション構成

### 1. この記事について（問題設定）
- 主張: あなたは「ファインチューニング＝追加学習で特化」までは知っている。だが現場の語彙（LoRA, QLoRA, DPO, GRPO, RFT, 蒸留, マージ）は層も目的もバラバラで、並べても地図にならない。本記事は手法を"軸"で並べ直し、輪郭を与える。
- 根拠: （導入のため特定 URL 不要）

### 2. 地図の座標 — ファインチューニングを軸で見る
- 主張: 個々の手法名で覚えると爆発する。上記 3 つの問い（重みの可動域・最適化対象・知識の出所）＋ 2 つの直交軸（モダリティ・実装レイヤ）で見ると、新しい手法も既存の座標に置けるようになる。
- 根拠: PEFT が「全パラメータを動かさず少数だけ」と定義する点 / TRL が SFT・DPO・GRPO・PPO を別トレーナとして並べる点を座標の妥当性の裏付けに。
  - https://huggingface.co/docs/peft/index
  - https://huggingface.co/docs/trl/peft_integration
- 根拠ファイル: `temp/ft_variety/search_hf_tools.json`

### 3. 軸1: どこまで重みを動かすか（full FT ⇄ PEFT）
- 主張: 最初の分岐は「全部の重みを更新するか、少数の追加パラメータだけ学習して土台は凍結するか」。PEFT は後者で、LoRA（低ランク行列を学習）→ QLoRA（土台を量子化して載せる）→ DoRA/IA3 など派生、さらに soft prompt 系（prompt/prefix tuning）まで幅がある。
- 効くポイント/制約: 学習率は full FT の約 10 倍が目安（SFT で 2e-5 → 2e-4）。アダプタは軽量で差し替え・共有・base へのマージが効く。prompt tuning は PEFT ライブラリ直叩きが必要で一部 Trainer 非対応。
- 代表ツール: Hugging Face PEFT（`LoraConfig`）。最小コード: `get_peft_model(model, LoraConfig(...))`。
- 根拠:
  - https://huggingface.co/docs/peft/index
  - https://huggingface.co/docs/transformers/peft （LoRA/IA3/AdaLoRA、prompt/prefix は PEFT 直叩き）
  - https://huggingface.co/docs/trl/peft_integration （LR 10x 表、`peft >= 0.18.0`）
- 根拠ファイル: `temp/ft_variety/search_hf_tools.json`

### 4. 軸2: 何を最適化するか（模倣 → 選好 → 採点）
- 主張: SFT は「お手本の次トークンを当てる＝模倣」。だが模倣では伝えにくい「どちらの応答が好ましいか」を入れたいとき、最適化対象が変わる。RLHF/PPO（報酬モデル + 強化学習）→ DPO（報酬モデルを介さず選好ペアで直接重み更新、RLHF 相当を軽い計算で）→ GRPO/ORPO などの派生。さらに RFT（reinforcement fine-tuning）は grader（採点関数）で chain-of-thought 自体を最適化する点で RLHF/DPO とも別物。
- 効くポイント/制約: DPO は tone/style/主観の調整に向く。LR は手法ごとに桁が違う（SFT 2e-5 / DPO 5e-7 / GRPO 1e-6、LoRA 併用で各 10x）。RFT は推論モデル（例 o4-mini）に対し採点で性能を伸ばす新しめの枠。
- 代表ツール: Hugging Face TRL（`SFTTrainer` / `DPOTrainer` / `GRPOTrainer` / `PPOTrainer`）。最小コード: `DPOConfig` 数行。
- 根拠:
  - https://huggingface.co/docs/trl/peft_integration （SFT/DPO/GRPO/PPO、LR 早見表）
  - https://community.openai.com/t/fine-tuning-updates-reinforcement-fine-tuning-now-available-gpt-4-1-nano-fine-tuning/1255539 （RFT は grader で CoT 最適化、RLHF/DPO と別物、o4-mini で GA、DPO は 4.1 系で利用可）
- 根拠ファイル: `temp/ft_variety/search_hf_tools.json`, `temp/ft_variety/search_cloud_ft.json`

### 5. 軸3: どの知識を、どこから入れるか（自前データ / ドメイン / 別モデル）
- 主張: 同じ「追加学習」でも入れる知識の出所で性格が変わる。(a) instruction tuning＝指示追従の作法を入れる、(b) 継続事前学習（continued pretraining / domain adaptation）＝生コーパスで素の言語分布をドメインに寄せる、(c) 蒸留（distillation）＝大きな teacher の振る舞いを小さな student に移す。蒸留は「特化」ではなく「圧縮・移送」で、ファインチューニングの境界に立つ好例。
- 効くポイント/制約: 継続事前学習はラベル不要だが破滅的忘却に注意。蒸留は教師出力（logits や生成データ）が前提で、目的は推論コスト削減・小型化。
- 代表ツール: TRL/PEFT 上での SFT（instruction）、Diffusers/TRL の蒸留例、各社の蒸留済みモデル。
- 根拠:
  - https://huggingface.co/docs/trl/peft_integration （SFTTrainer = instruction データでの教師ありFT）
  - https://huggingface.co/docs/peft/index
  - ※蒸留・継続事前学習の確証 URL は本文前に補強（下記「不足情報」）
- 根拠ファイル: `temp/ft_variety/search_hf_tools.json`

### 6. 軸4: 勾配を使わず重み空間で操作する（モデルマージ）
- 主張: ここまでは勾配で重みを更新してきたが、**学習せずに既存モデルの重みを混ぜる**という別ルートがある。SLERP（2 モデルを球面補間）、TIES（符号衝突を解消して結合）、DARE（一部を間引いてリスケール）、task arithmetic（タスクベクトルの加減算で能力を足し引き）、model soup（線形平均）。GPU 学習不要・データ不要で動くのが、勾配ベース手法との対比軸。
- 効くポイント/制約: 同一アーキテクチャ/系統が前提。SLERP は基本 2 モデル。実験的だが Open LLM Leaderboard 上位を生んだ実績。
- 代表ツール: mergekit（SLERP/TIES/DARE/task arithmetic/passthrough/MoE）。最小: マージ設定 yaml。
- 根拠:
  - https://huggingface.co/blog/mlabonne/merge-models （SLERP/TIES/DARE/passthrough、mergekit、学習不要）
  - https://developer.nvidia.com/blog/an-introduction-to-model-merging-for-llms （Model Soup/SLERP/Task Arithmetic/TIES/DARE、task vector）
- 根拠ファイル: `temp/ft_variety/search_merging.json`

### 7. 軸5: モダリティを越える（LLM / VLM / 拡散モデル）
- 主張: 軸 1〜2 の手法はテキスト LLM 専用ではない。VLM では DPO が画像つき選好に拡張され、拡散モデルでは DreamBooth（数枚で被写体を個人化）・Textual Inversion（新概念を埋め込みとして学習）・LoRA（UNet/テキストエンコーダに適用）が並ぶ。**「LoRA は LLM 発祥だが拡散モデルにも効く」**が、手法が軸として横断することの象徴。
- 効くポイント/制約: DreamBooth は過学習しやすくハイパラに敏感。拡散では UNet＋（任意で）テキストエンコーダに LoRA を当てる。
- 代表ツール: Hugging Face Diffusers / PEFT（DreamBooth + LoRA）。最小: `train_dreambooth_lora_sdxl.py` の主要引数。
- 根拠:
  - https://huggingface.co/docs/peft/main/task_guides/dreambooth_lora （LoRA は LLM 由来だが拡散にも適用、DreamBooth/Textual Inversion）
  - https://huggingface.co/docs/diffusers/v0.22.2/training/lora （拡散の LoRA/DreamBooth、`--train_text_encoder`）
  - https://huggingface.co/blog/dpo_vlm （VLM への DPO 拡張、`use_peft` + `all-linear`）
- 根拠ファイル: `temp/ft_variety/search_diffusion_ft.json`, `temp/ft_variety/search_hf_tools.json`

### 8. ツールの地層 — 同じ手法を、どのレイヤで回すか
- 主張: 技法軸とは別に「実装レイヤ」という直交軸がある。同じ LoRA/DPO でも、(1) 自分で組む（PEFT + TRL / Diffusers）、(2) 設定ファイルで回す（Axolotl / Unsloth / LLaMA-Factory）、(3) マネージドに任せる（OpenAI fine-tuning API、Azure AI Foundry、Vertex AI）の 3 階層がある。上に行くほど制御が減り、運用が楽になる。Azure Foundry は supervised / DPO / RFT を method 切替で提供し、技法軸とレイヤ軸が交差する例。
- 効くポイント/制約: マネージドは対応モデル・対応 method・リージョン・プレビュー状況に縛られる（例: RFT は対象モデル限定、DPO は特定 GPT 系で GA）。OSS 統合系は同一 config で複数手法を切替できるのが利点。
- 代表ツール: 各レイヤから 1 つずつ（PEFT+TRL / Unsloth or Axolotl / Azure Foundry）。最小: Azure の `method={"type":"supervised"|...}`。
- 根拠:
  - https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/fine-tuning （method で supervised/DPO/RFT 切替、`gpt-4.1` 例）
  - https://github.com/Azure/LLM-Fine-Tuning-Azure （SFT/DPO/RFT、TRL/Unsloth、Vision FT を横断的に列挙、ノーコード〜プロコード）
  - ※Axolotl/Unsloth/LLaMA-Factory の個別確証は本文前に補強（下記「不足情報」）
- 根拠ファイル: `temp/ft_variety/search_cloud_ft.json`

### 9. 地図の歩き方 — どの軸の問いから入るか
- 主張: 選定は手法名からではなく軸の問いから入る。「GPU/データはどれだけある？」→ 可動域軸（full or PEFT or マージ）、「正解が一意か、好ましさか？」→ 最適化軸（SFT or 選好 or RFT）、「ドメイン語彙が足りないのか、作法が足りないのか？」→ 知識の出所軸。小さな決定フロー or 対応表で締める。
- 根拠: 上記各セクションの統合（新規 URL 不要）

### 10. まとめ
- 主張: 手法は増え続けるが軸は安定している。新手法に出会ったら「どの軸の点か」を問えば地図に置ける。網羅ではなく座標を持ち帰ってほしい。

## 不足情報・本文前に補強する調査

- 蒸留 / 継続事前学習の公式・準公式な根拠 URL（現状は概念的記述のみ）。`search_topic.py` で 1 回補強。
- Axolotl / Unsloth / LLaMA-Factory の現行スタンス（config 駆動・対応手法）を GitHub 公式で 1 回裏取り。
- （任意）OpenAI 側 fine-tuning ガイドの一次情報（platform.openai.com）で RFT/DPO の現行記述を確認。

## タグ案（publish 用）

`["machinelearning", "llm", "finetuning", "lora", "ai"]`（lowercase ASCII、既存 `machinelearning`/`ai` を再利用）
