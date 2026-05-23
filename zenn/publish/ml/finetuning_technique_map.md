---
title: "LoRA・DPO・蒸留・モデルマージは何が違うのか — ファインチューニング技法の地図"
emoji: "🧭"
type: "tech"
topics: ["machinelearning", "llm", "finetuning", "lora", "ai"]
published: false
---

## この記事について

ファインチューニングが何かは知っている。事前学習済みモデルに自分のデータを追加で学習させて、特定のタスクやドメインに寄せる——そこまでは説明できる。

ところが、いざ手を動かそうとして情報を集めると、語彙が一気に増える。LoRA、QLoRA、DoRA、SFT、RLHF、DPO、GRPO、RFT、蒸留、継続事前学習、モデルマージ、Axolotl、Unsloth、LLaMA-Factory……。これらは**同じ「ファインチューニング」の話なのか、別物なのか**。それぞれ何の問題を解いていて、どういうときにどれを選ぶのか。並べただけでは地図にならない。

この記事は、個々の手法を覚え直すための記事ではありません。**手法を「軸」で並べ直して、全体の輪郭を見えるようにする**ための地図です。網羅はしません。各軸から代表的な点をいくつか選び、それぞれに代表ツールを 1 つずつ紐付けて、最小限のコード断片を添えます。バラエティを通して「ファインチューニングという言葉が指す空間の広さ」をつかんでもらうのが狙いです。

対象読者は、概要は知っているがこの地図を持っていない人。逆に言うと、「そもそもファインチューニングとは」「LoRA の数式」「ハイパラの完全ガイド」は扱いません。

## 地図の座標 — ファインチューニングを「軸」で見る

手法名を一つずつ暗記すると、新しい名前が出るたびに知識が増殖して破綻します。代わりに、いくつかの**軸**を用意して、各手法を「どの軸のどのあたりの点か」として捉えると、未知の手法も既存の座標に置けるようになります。

この記事では次の軸を使います。

| 軸 | 問い | 端と端 |
|----|------|--------|
| 軸1: 可動域 | どこまで重みを動かすか | 全部 ⇄ ごく一部 ⇄ 動かさない |
| 軸2: 最適化対象 | 何を最適化するか | 模倣 ⇄ 選好 ⇄ 採点 |
| 軸3: 知識の出所 | どの知識を、どこから入れるか | 自前データ ⇄ ドメインコーパス ⇄ 別モデル |
| 軸4: モダリティ | どの種類のモデルか | テキスト ⇄ 画像 ⇄ マルチモーダル |
| 軸5: 実装レイヤ | 誰がどこで回すか | 自分で書く ⇄ 設定で回す ⇄ 任せる |

この軸立てには裏付けがあります。Hugging Face の [PEFT](https://huggingface.co/docs/peft/index) は「全パラメータを動かすのではなく、少数の追加パラメータだけを学習する」という定義そのもので軸1を立てています。[TRL](https://huggingface.co/docs/trl/peft_integration) は `SFTTrainer` / `DPOTrainer` / `GRPOTrainer` / `PPOTrainer` を別々のトレーナとして並べていて、これはそのまま軸2に対応します。Meta AI の [Methods for adapting large language models](https://ai.meta.com/blog/adapting-large-language-models-llms) は記事まるごとが「LLM をどう適応させるか」の手法比較で、軸3 の存在を裏づけています。

では、軸ごとに代表点を歩いていきましょう。

## 軸1: どこまで重みを動かすか（full FT ⇄ PEFT）

最初の分岐は単純です。**モデルの全パラメータを更新するか、土台を凍結して少数の追加パラメータだけを学習するか**。

前者が full fine-tuning。後者が PEFT（Parameter-Efficient Fine-Tuning）です。PEFT 公式は「全パラメータの学習は法外にコストが高いので、少数の（追加）パラメータだけを学習する。それでも full FT に匹敵する性能が出せ、コンシューマ向けハードウェアでも大規模モデルを扱えるようになる」と説明しています（[PEFT docs](https://huggingface.co/docs/peft/index)）。

この「少数だけ動かす」の中にもバリエーションがあります。

- **LoRA**: 元の重みを凍結したまま、低ランクの分解行列のペアを学習する。タスク特化のための保存コストを大きく下げる（[DPO for VLMs ブログ内の LoRA 解説](https://huggingface.co/blog/dpo_vlm)）。
- **QLoRA**: 土台のモデルを量子化して載せた上に LoRA を当てる。メモリをさらに削る。
- **IA3 / AdaLoRA / DoRA** など、LoRA の発展形。Transformers は LoRA・IA3・AdaLoRA を直接統合しています（[Transformers PEFT](https://huggingface.co/docs/transformers/peft)）。
- **soft prompt 系**（prompt tuning / prefix tuning）: 重みではなく、入力に差し込む「学習可能なベクトル」だけを学習する。ただしこれらは Trainer 統合の対象外で、PEFT ライブラリを直接使う必要があります（同上）。

代表ツールは Hugging Face PEFT。最小のコードはこれだけです。

```python
from peft import get_peft_model, LoraConfig

peft_config = LoraConfig(target_modules="all-linear")
model = get_peft_model(model, peft_config)  # 以降、学習対象はアダプタだけ
```

**効きどころと注意点**:

- 学習率は full FT の約 10 倍が目安。TRL の早見表では SFT の full FT が `2.0e-5` に対し、LoRA 併用では `2.0e-4` です。動かすパラメータが少ない分、1 ステップを大きく踏む必要があるためです（[TRL PEFT Integration](https://huggingface.co/docs/trl/peft_integration)）。
- アダプタは軽量なので、共有・差し替え・base へのマージが容易。1 つの土台に複数のアダプタを付け替えて使えます。
- ただし soft prompt 系のように、トレーナ統合の都合でツールの対応状況が分かれる手法もあります（PEFT は `>= 0.18.0` で Transformers 統合が要件、など）。

軸1 のポイントは、「PEFT は手法ではなく**動かす範囲を絞るための共通レイヤ**」だということ。次の軸2 の手法とも、後の軸4 の画像モデルとも組み合わさります。

## 軸2: 何を最適化するか（模倣 → 選好 → 採点）

可動域を決めても、「何を目標に重みを更新するか」はまだ自由度が残っています。ここが軸2 です。

**模倣 — SFT（教師ありファインチューニング）**
お手本（指示と理想的な応答のペア）を見せて、次トークンを当てさせる。最も基本的で、TRL の `SFTTrainer` が担当します（[TRL PEFT Integration](https://huggingface.co/docs/trl/peft_integration)）。「こう答えてほしい」を直接見せられるときに効きます。

**選好 — RLHF / DPO / GRPO**
ところが「どちらの応答がより好ましいか」は、模倣では伝えにくい。ここで最適化対象が「正解の再現」から「好ましさ」へ移ります。

- **RLHF / PPO**: 報酬モデルを別途学習し、強化学習で方策を最適化する。古典的だが重い。
- **DPO（Direct Preference Optimization）**: 報酬モデルを介さず、選好ペア（chosen / rejected）から直接重みを更新する。Azure の解説では「RLHF に匹敵する効果を、より速い計算で得られる。tone・style・特定の content の好みといった**主観的な要素**の調整に特に向く」とされています（[Azure OpenAI の新FT技法アナウンス](https://www.linkedin.com/posts/ssweetman_introducing-new-fine-tuning-techniques-and-activity-7275636221031194624-qBxa)）。
- **GRPO / ORPO / KTO / SimPO** など、選好最適化の派生も多数あります。

```python
from trl import DPOConfig, DPOTrainer

training_args = DPOConfig(learning_rate=5e-6)  # LoRA 併用時の目安
trainer = DPOTrainer(model=model, args=training_args, train_dataset=pref_dataset)
trainer.train()
```

ここで学習率が手法ごとに桁違いになる点は覚えておく価値があります。TRL の早見表より：

| トレーナ | Full Fine-Tuning | LoRA 併用（10x） |
|----------|------------------|------------------|
| SFT | `2.0e-5` | `2.0e-4` |
| DPO | `5.0e-7` | `5.0e-6` |
| GRPO | `1.0e-6` | `1.0e-5` |
| Prompt Tuning | — | `1.0e-2` 〜 `3.0e-2` |

（出典: [TRL PEFT Integration](https://huggingface.co/docs/trl/peft_integration)）

**採点 — RFT（Reinforcement Fine-Tuning）**
さらに最近、選好とも別物の枠が登場しました。RFT は **grader（採点関数）で、モデルの隠れた chain-of-thought 自体を最適化する**点が特徴です。RLHF や DPO が「人間の選好に出力を寄せる」のに対し、RFT は「あらかじめ定義した採点者が正解と判定する答えに至るよう、思考の連鎖を最適化する」と説明されています（[OpenAI Developer Community: RFT now available](https://community.openai.com/t/fine-tuning-updates-reinforcement-fine-tuning-now-available-gpt-4-1-nano-fine-tuning/1255539)）。OpenAI では推論モデル o4-mini に対して GA、DPO は GPT-4.1 系で利用可能、というように対象モデルと手法の対応が動いています。

軸2 のポイントは、**「模倣 → 選好 → 採点」と進むほど、教えたい対象が「正解」から「好ましさ」「正しさの判定基準」へと抽象化していく**こと。同じデータ量でも、何を最適化するかで適した手法が変わります。

## 軸3: どの知識を、どこから入れるか

可動域（軸1）と最適化対象（軸2）が同じでも、**入れる知識の出所**で性格が変わります。

- **instruction tuning**: 「指示に従って答える」という作法を入れる。データは指示と応答のペアで、`SFTTrainer` がそのまま担当します。
- **継続事前学習（continued pretraining / CPT）**: ラベルのない生コーパスで、素の言語分布をドメインに寄せる。Meta AI の解説では、CPT は事前学習のごく一部のコストで性能を伸ばせ、多言語能力の追加などに成功したと報告されています。一方で具体例として FinPythia-6.9B は、金融特化のために **24 億トークンを 18 日かけて** CPT したとあり、依然として高コストです。さらに CPT は破滅的忘却を起こしやすく、リソースの限られたチームには推奨しない、とまで述べられています（[Methods for adapting LLMs](https://ai.meta.com/blog/adapting-large-language-models-llms)）。
- **蒸留（distillation）**: 大きな teacher モデルの振る舞いを、小さな student モデルに移す。ここでの目的は「特化」ではなく「圧縮・移送」です。だから蒸留は、ファインチューニングの**境界**に立つ好例と言えます——重みを学習で更新する点では仲間ですが、ゴールがタスク特化ではなく推論コスト削減・小型化にある。

**境界としての注意点**: 軸3 のどの手法も、重みを更新する以上「破滅的忘却（catastrophic forgetting）」のリスクを共有します。Meta の解説でも、医療ドメインにファインチューニングしたモデルが instruction-following や一般 QA で性能を落とした研究が引かれています。新しい知識を入れることと、既存の能力を保つことはトレードオフになりがちで、これは継続学習研究の中心的な課題です（[Methods for adapting LLMs](https://ai.meta.com/blog/adapting-large-language-models-llms)）。

軸3 のポイントは、「追加学習」と一言で言っても、**作法を入れたいのか、ドメインの語彙を入れたいのか、別モデルから能力を移したいのかで、まったく違う手法になる**こと。

## 軸4: 勾配を使わず、重み空間で操作する（モデルマージ）

ここまでの軸はすべて「勾配で重みを更新する」前提でした。ところが、**学習せずに既存モデルの重みを混ぜる**という、まったく別のルートがあります。これがモデルマージです。

mergekit の解説によれば、モデルマージは複数の LLM を 1 つに統合する技術で、「比較的新しく実験的だが驚くほどうまく機能し、Open LLM Leaderboard で多くの最先端モデルを生み出した。**GPU 不要・学習データ不要**で、重み空間で直接行われる」とされています（[Merge LLMs with mergekit](https://huggingface.co/blog/mlabonne/merge-models)）。

代表的なアルゴリズム（mergekit / NVIDIA の整理より）：

- **Model Soup（Linear）**: 単純な重み付き平均。
- **SLERP（Spherical Linear Interpolation）**: 2 つのモデルを球面に沿って補間する。基本的に 2 モデル限定で、片方を base model に取る。
- **Task Arithmetic（タスクベクトル）**: 「base からの差分（タスクベクトル）」を足し引きして、能力を追加・除去する。
- **TIES（Trim, Elect Sign, Merge）**: 冗長なパラメータを刈り、符号の衝突を解消してから結合し、複数モデル併合時の干渉を抑える。
- **DARE**: ランダムにパラメータを間引いてリスケールし、大規模なマージでの干渉を減らす。**DARE-TIES** はその併用。

（出典: [mergekit 解説](https://huggingface.co/blog/mlabonne/merge-models), [NVIDIA: An Introduction to Model Merging for LLMs](https://developer.nvidia.com/blog/an-introduction-to-model-merging-for-llms)）

代表ツールは mergekit。学習が無いので、設定はマージのレシピを書く YAML だけです（概念を示すための最小例）。

```yaml
# 2 モデルを SLERP で混ぜる、という宣言だけ。GPU 学習は走らない
merge_method: slerp
base_model: model_A
models:
  - model: model_B
parameters:
  t: 0.5   # 0 で base、1 で model_B 寄り
```

**効きどころと注意点**: 同一アーキテクチャ・同一系統のモデルが前提です。SLERP は基本 2 モデル。実験的な手法ですが、Open LLM Leaderboard 上位を実際に生み出した実績があります。

軸4 のポイントは、**「ファインチューニング＝勾配で学習」という思い込みを外す**こと。重み空間での操作という、コストの桁が違う選択肢が地図の端にあります。

## 軸5: モダリティを越える（LLM / VLM / 拡散モデル）

ここまでの手法は、テキスト LLM 専用ではありません。軸4 までで見た技法が、画像やマルチモーダルにも横断するのが軸5 です。

象徴的なのが LoRA です。PEFT 公式は「**LoRA はもともと大規模言語モデルの学習パラメータを減らすための技術として設計されたが、拡散モデルにも適用できる**」と明言しています。拡散モデルの full FT は時間がかかるため、DreamBooth や Textual Inversion のような軽量手法が人気を得ていて、LoRA はそれをさらに速くした、という位置づけです（[DreamBooth fine-tuning with LoRA](https://huggingface.co/docs/peft/main/task_guides/dreambooth_lora)）。

画像生成側の代表的な手法：

- **DreamBooth**: 被写体の画像 3〜5 枚で text2image モデルを個人化する。ただしハイパラに非常に敏感で過学習しやすい（[Diffusers LoRA docs](https://huggingface.co/docs/diffusers/v0.22.2/training/lora)）。
- **Textual Inversion**: 新しい概念を「埋め込み」として学習する軽量手法。
- **LoRA**: 拡散モデルの UNet に当てる。任意で `--train_text_encoder` を付けてテキストエンコーダにも当てると、わずかな計算増で結果が良くなることが多い（同上）。

```bash
# 拡散モデル(SDXL)に DreamBooth + LoRA を当てる例(主要引数のみ)
accelerate launch train_dreambooth_lora_sdxl.py \
  --pretrained_model_name_or_path="stabilityai/stable-diffusion-xl-base-1.0" \
  --instance_prompt="a photo of sks dog" \
  --resolution=1024 --learning_rate=1e-4 --max_train_steps=500
```

マルチモーダル（VLM）側でも、軸2 の手法がそのまま延びています。TRL の DPO 実装は Idefics2・Llava 1.5・PaliGemma といった VLM に対応し、`--use_peft` と `lora_target_modules=all-linear` を付ければ LoRA 併用で画像つき選好データに DPO を回せます（[Preference Optimization for VLMs with TRL](https://huggingface.co/blog/dpo_vlm)）。

軸5 のポイントは、**手法は軸として、モダリティを横断する**こと。「LoRA は LLM 用、DreamBooth は画像用」と縦割りで覚えると、この横の広がりが見えなくなります。

## ツールの地層 — 同じ手法を、どのレイヤで回すか

ここまでは技法の軸でした。それとは直交する最後の軸が**実装レイヤ**です。同じ LoRA や DPO でも、「誰がどこで回すか」で 3 つの層に分かれます。上の層に行くほど制御は減り、運用は楽になります。

**第1層: 自分で書く（PEFT + TRL / Diffusers）**
トレーナを直接組む。最も自由度が高く、研究や細かい制御に向く。これまでのコード断片はすべてこの層です。

**第2層: 設定ファイルで回す（Axolotl / Unsloth / LLaMA-Factory）**
学習ループを書かず、YAML などの宣言的な設定で回す層。

- **Axolotl**: YAML の config-first で、full / LoRA / QLoRA / relora / gptq などを切り替える。Unsloth に着想を得たカーネル最適化も持つ（ただし LoRA カーネルは現状 SFT のみ対応で RLHF は非対応、といった制約あり）（[Axolotl LoRA Optimizations](https://docs.axolotl.ai/docs/lora_optims.html)）。
- **Unsloth**: 単一 GPU での速度とメモリ効率に強い。
- **LLaMA-Factory**: 100 以上のモデルを統一的に扱う「全部入り」。対応手法の表が分かりやすく、Pre-Training・SFT・Reward Modeling・PPO・DPO・KTO・ORPO・SimPO を、それぞれ Full / Freeze / LoRA / QLoRA で回せます。さらに `use_unsloth: true` で Unsloth を「加速オペレータ」として取り込める設計です（[LLaMA-Factory](https://github.com/hiyouga/LlamaFactory)）。

ここで重要なのは、第2層のツールは**1 つの設定ファイルの中で軸1〜軸3 を切り替えられる**こと。`merge_method` や `stage: dpo` のような 1 行で、これまで見てきた技法軸を行き来できます。

**第3層: マネージドに任せる（OpenAI / Azure AI Foundry / Vertex AI）**
インフラもトレーナも見ず、API にデータと method を渡すだけ。Azure AI Foundry は `method` の切り替えで supervised / DPO / RFT を提供しています。

```python
client.fine_tuning.jobs.create(
    training_file="file-abc123",
    model="gpt-4.1-2025-04-14",
    method={"type": "supervised", "supervised": {"hyperparameters": {"n_epochs": 2}}},
)
```

（出典: [Customize a model with fine-tuning - Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/fine-tuning)）

ここでも技法軸とレイヤ軸が交差しているのが見えます。Azure の `method` を `dpo` や `reinforcement` に変えれば、軸2 の手法がそのままマネージドの引数になる。実際 Azure のサンプル集 [LLM-Fine-Tuning-Azure](https://github.com/Azure/LLM-Fine-Tuning-Azure) には、SFT / DPO / RFT、TRL や Unsloth 経由、Vision FT までがノーコード〜プロコードで並んでいます。

**第3層の注意点**: マネージドは「対応モデル・対応 method・リージョン・プレビュー状況」に縛られます。RFT は対象モデルが限定され、DPO も特定の GPT 系で GA、というように、できることがプラットフォーム側の都合で決まります。自由度と運用の楽さはトレードオフです。

## 地図の歩き方 — 手法名ではなく、軸の問いから入る

ここまで来ると、選定は手法名から始めるものではないと分かります。**軸の問いから入る**のが地図の歩き方です。

- **GPU とデータはどれだけある？** → 軸1（可動域）。潤沢なら full FT、限られるなら PEFT、学習自体を避けたいならマージ。
- **教えたいのは「正解の再現」か「好ましさ」か「正しさの判定基準」か？** → 軸2（最適化対象）。順に SFT / 選好最適化（DPO 等）/ RFT。
- **足りないのはドメインの語彙か、それとも指示に従う作法か？** → 軸3（知識の出所）。前者は継続事前学習、後者は instruction tuning。
- **対象はテキストか、画像か、マルチモーダルか？** → 軸4（モダリティ）。手法は横断するが、ツールとデータ形式が変わる。
- **自分で制御したいか、運用を任せたいか？** → 軸5（実装レイヤ）。自分で書く / 設定で回す / マネージド。

実際のプロジェクトでは、これらが組み合わさります。たとえば「コンシューマ GPU 1 枚で、自社の問い合わせ口調に寄せたい」なら、軸1=QLoRA・軸2=DPO（口調は主観的なので選好が向く）・軸5=Unsloth/Axolotl、という座標に着地する、といった具合です。

## まとめ

ファインチューニングの手法は今も増え続けています。次に新しい名前——たとえば見慣れない選好最適化の変種や、新しいマージアルゴリズム——に出会ったとき、覚えるべきは名前そのものではありません。

**「それはどの軸の、どのあたりの点か」**を問えばよい。

- どこまで重みを動かす手法か（軸1）
- 何を最適化する手法か（軸2）
- どの知識を入れる手法か（軸3）
- どのモダリティに効くか（軸4）
- どのレイヤで回すものか（軸5）

この 5 つの座標さえ持っていれば、未知の手法もすでにある地図の上に置けます。網羅された一覧ではなく、この座標系を持ち帰ってもらえれば、この記事の狙いは果たせています。

---

### 主な参考資料

- Hugging Face PEFT: <https://huggingface.co/docs/peft/index>
- Hugging Face Transformers / PEFT: <https://huggingface.co/docs/transformers/peft>
- Hugging Face TRL / PEFT Integration（LR 早見表）: <https://huggingface.co/docs/trl/peft_integration>
- Preference Optimization for VLMs with TRL: <https://huggingface.co/blog/dpo_vlm>
- DreamBooth fine-tuning with LoRA（PEFT）: <https://huggingface.co/docs/peft/main/task_guides/dreambooth_lora>
- Diffusers LoRA / DreamBooth: <https://huggingface.co/docs/diffusers/v0.22.2/training/lora>
- Merge LLMs with mergekit: <https://huggingface.co/blog/mlabonne/merge-models>
- NVIDIA: An Introduction to Model Merging for LLMs: <https://developer.nvidia.com/blog/an-introduction-to-model-merging-for-llms>
- Meta AI: Methods for adapting large language models: <https://ai.meta.com/blog/adapting-large-language-models-llms>
- LLaMA-Factory: <https://github.com/hiyouga/LlamaFactory>
- Axolotl LoRA Optimizations: <https://docs.axolotl.ai/docs/lora_optims.html>
- Azure: Customize a model with fine-tuning: <https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/fine-tuning>
- OpenAI: Reinforcement fine-tuning now available: <https://community.openai.com/t/fine-tuning-updates-reinforcement-fine-tuning-now-available-gpt-4-1-nano-fine-tuning/1255539>
