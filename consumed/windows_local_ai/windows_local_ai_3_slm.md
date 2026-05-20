---
title: "WindowsローカルAI実践 第3回:ONNX Runtime GenAI で SLM をローカル実行する(量子化とメモリの壁)"
emoji: "🧮"
type: "tech"
topics: ["windows", "onnxruntime", "python", "slm", "ai"]
published: false
---

## この記事について

連載「WindowsローカルAI実践入門」の**第3回**です。第1回は本連載の全体像を**1枚の技術地図**として示し、第2回はその中の **ONNX → ONNX Runtime(ORT)→ Execution Provider(EP)** と **CPU/GPU の使い分け** を、scikit-learn と PyTorch の **“ふつうの ML モデル”** で実際に動かしました。そこで通した幹は **変換 → ロード → 前処理 → 推論 → 検証** の5段でした。

ONNX Runtime は推論を速くしますが、**量子化やモデル最適化は別工程**です。本記事はその「別工程」を、題材を **SLM(小規模言語モデル)** に変えて扱います。第2回の幹に **生成ループ・量子化・メモリ** という3つの枝を足します。

主役は **Phi-3 mini**、補足で **Phi-4 mini** を使います。

:::message
本記事は連載第3回です。第2回(ONNX Runtime で通常 ML を動かす)で扱った5段の幹(変換→ロード→前処理→推論→検証)と「`.onnx` 単体は動かない」「パッケージは用途別」は、本記事でも §0・§2 で要点を再掲するため、単独でも読めます。
:::

対象読者は、第1・2回で `ONNX → ORT → EP → ハード` の幹を理解し、**次は自分の Windows マシンで小さな LLM を動かしたい**開発者です。Python の基本と第2回相当の知識があれば読めます。コードは Python 中心、C# はインストール対応表だけ補足します。LLM の内部数学には踏み込みません。

---

## 0. はじめに:第2回の幹に「量子化」と「メモリ」を足す

第2回の到達点を1段落で再掲します。**学習済みモデルを `.onnx` に変換し、`InferenceSession` でロードし、学習時と同じ前処理を通し、`session.run()` で推論し、元フレームワークと数値一致を検証する。** これが Windows ローカル推論の変わらない幹でした。

本記事のゴールはこうです。

> Microsoft 公式の**事前量子化済み Phi-3 mini ONNX**をダウンロードし、ONNX Runtime GenAI で CPU 推論し、DirectML に載せ替え、**Phi-4 mini も同じ型で動く**ところまでを、最小コードで通す。

ただし SLM では、第2回の幹がそのまま使えません。**5段が変形し、新しく3つの壁が立ちます。**

- **生成ループ**:SLM は「1回 `run()` すれば答えが出る」モデルではない(§1)
- **量子化**:量子化しないと、そもそも普通の Windows マシンに載らない(§4)
- **メモリ**:量子化してもなお、文脈長次第でメモリが足りなくなる(§4)

第2回が「変換 → ロード → 前処理 → 推論 → 検証」を通常 ML で歩いた実地編なら、本記事は同じ幹を **SLM 固有の縮尺**で歩き直す回です。

## 1. なぜ第2回の道具では SLM が動かないか:生成ループという別物

第2回で書いた推論はこうでした。

```python
outputs = sess.run(None, {"input": x})   # 1回呼ぶ → 答えが出る
```

画像分類なら、これで終わりです。入力を入れたら出力(クラス確率)が一度に出ます。

SLM は違います。言語モデルは**次の1トークンを予測する**だけのモデルで、文章を作るには「予測したトークンを末尾に足して、また予測する」を**何百回もループ**します(自己回帰生成)。さらに毎回ゼロから計算し直すと遅すぎるので、過去の計算結果を **KV キャッシュ**として持ち回ります。つまり SLM をローカルで動かすとは、最低でも次のループを回すことです。

```
[テキスト] → トークナイズ → 整数列
                       │
                       ▼
   ┌────────── 生成ループ ──────────┐
   │  ① ORT で推論(次トークンの分布)│
   │  ② サンプリング(次の1トークン)  │
   │  ③ KV キャッシュ更新            │
   │  ④ 終了判定(EOS / 最大長)      │  ← 終わるまで①へ
   └──────────────┬─────────────────┘
                       ▼
               デトークナイズ → [テキスト]
```

これを手で書くのは大変です。そこで **ONNX Runtime GenAI**(`onnxruntime-genai`)が、この生成ループを丸ごと提供します。公式は GenAI をこう説明しています ——「ONNX モデルのための生成 AI ループを提供する。**トークナイズと前後処理、ONNX Runtime での推論、logits 処理、探索とサンプリング、KV キャッシュ管理**を含む」。高レベルの `generate()` を1回呼ぶことも、1トークンずつループを自分で回すこともでき、greedy/beam 探索や TopP/TopK サンプリング、繰り返しペナルティ、chat テンプレート、tool calling 用の構造化出力にも対応します([Generate API (Preview) — onnxruntime](https://onnxruntime.ai/docs/genai/))。

ここで層を取り違えないでください。

> **第2回の `InferenceSession` = 単発推論エンジン。GenAI = その上に「生成ループ」を載せた別ライブラリ。** GenAI は内部で ONNX Runtime を使います(置き換えではない)。

そしてもう一つ、第4回につながる重要な事実があります。**ONNX Runtime GenAI は、Foundry Local・Windows ML・Visual Studio Code AI Toolkit の中身でもあります**([microsoft/onnxruntime-genai — GitHub](https://github.com/microsoft/onnxruntime-genai))。第1回で挙げた Windows ローカル AI の「入口」のいくつかは、内部でこの GenAI を共有しています。本記事で GenAI を直接扱うのは、その土台を理解するためです。

## 2. ONNX Runtime GenAI を入れる:また3パッケージ、そして Preview

第2回 §2 で「Python の ONNX Runtime は用途別に別パッケージ。1環境に混在させるな」と書きました。**GenAI でこの問題がそっくり再来します。**

| Python パッケージ | 対象 | 備考 |
|---|---|---|
| `onnxruntime-genai` | CPU | まずこれ。どこでも動く |
| `onnxruntime-genai-directml` | Windows GPU(DirectML) | DirectX 12 GPU で動く Windows の本命 |
| `onnxruntime-genai-cuda` | NVIDIA GPU(CUDA 12) | CUDA Toolkit 必須。CUDA 11 はソースビルド |

公式 install ページは明記しています ——「CPU / DirectML / CUDA のパッケージ群は、**環境にどれか1つだけ**入れること」([Install ONNX Runtime generate() API](https://onnxruntime.ai/docs/genai/howto/install.html))。第2回と同じ「混在させない」ルールです。

```bash
pip install --pre onnxruntime-genai            # CPU
pip install --pre onnxruntime-genai-directml   # Windows GPU
pip install --pre onnxruntime-genai-cuda       # NVIDIA CUDA 12
```

C#(NuGet)も同じ構造で、やはり「どれか1つだけ」です([Install ONNX Runtime generate() API](https://onnxruntime.ai/docs/genai/howto/install.html))。

| NuGet | 対象 |
|---|---|
| `Microsoft.ML.OnnxRuntimeGenAI` | CPU |
| `Microsoft.ML.OnnxRuntimeGenAI.DirectML` | Windows GPU(DirectML) |
| `Microsoft.ML.OnnxRuntimeGenAI.Cuda` | NVIDIA CUDA |

:::message alert
**ここが「ライブラリの新旧・安定/プレビュー状態を必ず判定する」という原則が一番効く場所です。** ONNX Runtime GenAI の API は、公式ドキュメントが冒頭で **"Note: this API is in preview and is subject to change."(プレビューであり変更されうる)** と明記しています([Generate API (Preview)](https://onnxruntime.ai/docs/genai/)、[Python API](https://onnxruntime.ai/docs/genai/api/python.html))。`pip install` に `--pre` が要るのもそのためです。

さらに GitHub リポジトリは「本プロジェクトは活発に進化中で、`main` ブランチの例が最新安定版と一致しないことがある。**パッケージのバージョンに合わせて例の版を選べ**」と注意しています([microsoft/onnxruntime-genai](https://github.com/microsoft/onnxruntime-genai))。古い記事のコードをそのまま写すと動かないことがあります。本記事のコードは概念を理解するための最小例です。実装時は、使用中バージョンの公式 API ドキュメントで関数シグネチャを確認してください。
:::

バージョン境界の事実も1つだけ。GenAI は **0.4.0 以降、core ONNX Runtime バイナリと分離**されました(0.3.0 以前は同梱)。CUDA は 0.3.0 以前が CUDA 11、0.4.0 以降が CUDA 12 のみです([Install ONNX Runtime generate() API](https://onnxruntime.ai/docs/genai/howto/install.html))。

## 3. 最短経路:事前量子化済み Phi-3 mini を `generate()` で回す

第2回は「自分で `torch.onnx.export` する」から始めました。SLM では**いきなり変換しません**。Microsoft が公式に**事前量子化済みの Phi-3 mini ONNX**を HuggingFace で配っているので、まずそれを動かすのが最短です(自前変換は §6 で軽く触れます)。

Phi-3 / Phi-3.5 の ONNX は HuggingFace にホストされ、`generate()` API で動かせます。mini(3.3B)と medium(14B)があり、それぞれ短文脈(4k)版に加え、別リポジトリで長文脈(128k)版も公開されています(本記事では §3 以降 4k 版を使います)。**長文脈版はより長い入出力を扱えますが、その分メモリを多く消費します**([Phi-3 tutorial — onnxruntime](https://onnxruntime.ai/docs/genai/tutorials/phi3-python.html))。この「長文脈=メモリ増」の理由は §4 で詳しく説明します。

まず CPU 版を取得してインストールします。

```bash
huggingface-cli download microsoft/Phi-3-mini-4k-instruct-onnx \
  --include cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/* --local-dir .
pip install --pre onnxruntime-genai
```

最小の Python はこうです(token-by-token でストリーム出力する骨格)。

```python
import onnxruntime_genai as og

model = og.Model("cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4")
tokenizer = og.Tokenizer(model)
tokenizer_stream = tokenizer.create_stream()

prompt = "<|user|>\nWindows ローカル AI を一文で説明して<|end|>\n<|assistant|>\n"
input_tokens = tokenizer.encode(prompt)

params = og.GeneratorParams(model)
params.set_search_options(max_length=512)

generator = og.Generator(model, params)
generator.append_tokens(input_tokens)

while not generator.is_done():
    generator.generate_next_token()
    new_token = generator.get_next_tokens()[0]
    print(tokenizer_stream.decode(new_token), end="", flush=True)
```

第2回の `InferenceSession` と比べた要点は4つです([Python API — onnxruntime](https://onnxruntime.ai/docs/genai/api/python.html))。

1. **ロードは `og.Model`**(`InferenceSession` ではない)。GenAI が内部で ORT を使う。
2. **前処理はトークナイザ**。numpy 配列を自作するのではなく `tokenizer.encode()`。プロンプトの `<|user|>` 等は chat テンプレートの記法で、モデルにより異なる。
3. **推論は単発でなくループ**。`append_tokens` → `while not is_done(): generate_next_token()`。第2回の「1回 `run()`」が「終わるまで回す」に変わる。
4. **出力はストリーム**。`TokenizerStream.decode()` で1トークンずつ文字へ戻す(生成ループ図のデトークナイズに相当)。

自分でループを書かず、公式の対話サンプル `phi3-qa.py` をそのまま回す手もあります。モデルを指定して実行すると入力待ちのループに入り、生成結果をストリーム表示します([Phi-3 tutorial](https://onnxruntime.ai/docs/genai/tutorials/phi3-python.html))。まず公式スクリプトで動作確認 → 仕組みを上の骨格で理解、の順が安全です。

:::message
上のメソッド名(`append_tokens` / `generate_next_token` / `get_next_tokens` / `is_done` / `set_search_options` / `TokenizerStream.decode`)は公式 [Python API](https://onnxruntime.ai/docs/genai/api/python.html) と公式サンプルに基づく**最小構成**です。§2 のとおり API は Preview です。引数名(例:`set_search_options` の指定)はバージョンで変わりうるので、実装時は公式 API ドキュメントと、使用中パッケージに対応する公式サンプルを正本にしてください。
:::

## 4. 量子化を読む:なぜ INT4 が要るか、RTN と AWQ、モデル名の解読

§3 でダウンロードしたフォルダ名を見てください ——`cpu-int4-rtn-block-32-acc-level-4`。これは飾りではなく、**選択そのもの**です。SLM がローカルで動くのは量子化のおかげで、この名前を読めないと「遅い/精度が悪い/そもそも載らない」を選び分けられません。

### なぜ INT4 か

言語モデルの重みは通常 FP16/FP32 です。これを **INT4(4bit)** に量子化すると、重みのメモリ使用量とロード時間が劇的に減り、普通の Windows デバイスに載るようになります。ハードウェアを積めば即高速になるわけではないのと同様に、**量子化しなければ、そもそも実行対象にすらなりません**。実際 INT4 RTN 量子化により、最先端の Phi-3 Mini を Samsung Galaxy S21 のようなモバイルでも動かせる、と公式は述べています([ONNX Runtime supports Phi-3 mini](https://onnxruntime.ai/blogs/accelerating-phi-3))。

### RTN と AWQ:2つの量子化方式

配布されている INT4 モデルには主に2方式あります([ONNX Runtime supports Phi-3 mini](https://onnxruntime.ai/blogs/accelerating-phi-3))。

- **RTN(Round To Nearest)**:単純で軽量な量子化。`int4_accuracy_level` という調整つまみがあり、これは INT4 量子化された MatMul の活性化(入力)側の計算に用いる最小精度を指定し、性能と精度のトレードオフを取る。公式は **`accuracy_level=1`(精度寄り)** と **`accuracy_level=4`(性能寄り)** の2版を配布している。量子化時に指定したこのレベルが、配布フォルダ名の `-acc-level-<k>`(例:`cpu-int4-rtn-block-32-acc-level-4`)に反映される。
- **AWQ(Activation-Aware Quantization)**:精度維持に必要な**上位1%の重要な重みを残し、残り99%を量子化**する。これにより、多くの量子化手法より精度劣化が小さい。Windows GPU 向け Phi-3 mini が `directml-int4-awq-block-128` で配られているのはこのため。

### モデル名の読み方

事前量子化モデルのフォルダ名は、おおむね次の構造です。

```
<ターゲット>-int4-<方式>-block-<n>[-acc-level-<k>]

例) directml-int4-awq-block-128
    cpu-int4-rtn-block-32-acc-level-4
    gpu-int4-rtn-block-32
```

`block-<n>` は量子化をかける重みのまとまり(ブロック)の粒度、`acc-level-<k>` は RTN の精度レベルです。そして DirectX 12 対応 GPU なら、AMD/Intel/NVIDIA を問わず DirectML で INT4 AWQ 版が動きます([ONNX Runtime supports Phi-3 mini](https://onnxruntime.ai/blogs/accelerating-phi-3))。**DirectX 12 対応デバイスなら DirectML** という、本連載で一貫した方針どおりです。

### 量子化しても残るメモリの壁

ここが SLM 特有の落とし穴です。**量子化が削るのは主に「モデル重みのメモリ」です。** 一方、生成中に膨らむ **KV キャッシュ(§1)は文脈長にほぼ比例して別途増えます。** §3 で触れた「長文脈版(128k)は短文脈版(4k)よりメモリを多く消費する」の正体がこれです([Phi-3 tutorial](https://onnxruntime.ai/docs/genai/tutorials/phi3-python.html))。「INT4 にしたのに長いプロンプトで落ちる」のは、重みではなく KV キャッシュ側でメモリを使い切っているからです。量子化はメモリ問題の半分しか解きません。

:::message alert
**事前量子化モデルは base モデルの“最適化版”であって、同一物ではありません。** HuggingFace のモデルカードは明示しています ——「本モデルは base モデルの最適化にすぎず、最適化適用により base モデルと**出力にわずかな差が出ることがある**。各自のシナリオで検証・テストせよ」([microsoft/Phi-4-mini-instruct-onnx](https://huggingface.co/microsoft/Phi-4-mini-instruct-onnx))。この事実は §5 の「検証」段の意味を根本から変えます。
:::

## 5. 第2回の5段は SLM でこう変形する

ここまでの内容を整理します。**第2回の幹は捨てていません。各段が SLM 用に変形しているだけ**です。これを一覧にすると、各段の対応関係が一目で分かります。

| 段 | 第2回(通常 ML) | 第3回(SLM) |
|---|---|---|
| 変換 | 自前 `torch.onnx.export` / `skl2onnx` | **事前量子化済み ONNX を取得**(or Model Builder, §6) |
| ロード | `InferenceSession(path, providers=[...])` | **`og.Model(path)`**(GenAI が内部で ORT 使用) |
| 前処理 | numpy 配列・dtype・NCHW を自作 | **トークナイザ + chat テンプレート**(GenAI 同梱) |
| 推論 | 単発 `session.run()` | **生成ループ**(KV キャッシュつき自己回帰, §1) |
| 検証 | `numpy.allclose` で元フレームと数値一致 | **品質評価**(生成は確率的、量子化で base と差が出る前提, §4) |

特に最後の段が重要です。通常 ML では「変換を信用せず `numpy.allclose` で数値一致を確認する」のが定石でした。SLM では**それができません**。生成は確率的でそもそも毎回同じ出力とは限らず、さらに §4 の disclaimer どおり量子化版は base と出力が一致しない前提です。通常 ML では検証が最もつまずきやすい段でしたが、SLM では**検証の意味自体が「数値一致」から「タスク品質の評価」へ変わります**。本記事では §7 で論点として示すに留め、第5回(実用アプリ)で本格的に扱います。

## 6. CPU から GPU へ:DirectML で SLM を載せ替える(+ Phi-4 mini 補足)

通常 ML で CPU→GPU を切り替えるときは、対応パッケージへの差し替えと `providers=["DmlExecutionProvider", "CPUExecutionProvider"]` の指定変更が必要でした。GenAI ではこれに「**モデルフォルダ自体の差し替え**」が加わり、「**別フォルダのモデル + 対応パッケージ + 実行時の EP 指定**」に変わります。EP 選択が量子化バリアントの選択と一体化しているのが SLM の特徴です。

Phi-3 mini を DirectML で動かすなら、`directml/` 配下の AWQ モデルを取得し、DirectML パッケージを入れ、`-e dml` で実行します([Phi-3 tutorial](https://onnxruntime.ai/docs/genai/tutorials/phi3-python.html))。

### Phi-4 mini 補足:同じ型で動く

ここで主役を少し離れ、**Phi-4 mini も Phi-3 mini と同じ型で動く**ことを確認します。これが「幹が効いている」証拠です([microsoft/Phi-4-mini-instruct-onnx](https://huggingface.co/microsoft/Phi-4-mini-instruct-onnx))。

```bash
# DirectML(Windows GPU)
huggingface-cli download microsoft/Phi-4-mini-instruct-onnx --include gpu/* --local-dir .
pip install --pre onnxruntime-genai-directml
python model-qa.py -m gpu/gpu-int4-rtn-block-32 -e dml

# CPU
huggingface-cli download microsoft/Phi-4-mini-instruct-onnx \
  --include cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4/* --local-dir .
pip install --pre onnxruntime-genai
python model-qa.py -m cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4 -e cpu
```

モデル名(Phi-3 → Phi-4)が変わっても、**5段の幹(変換=取得 → ロード=`og.Model` → 前処理=トークナイザ → 推論=生成ループ → 検証=評価)はそのまま**です。

:::message
フォルダ構成はモデルで微妙に違います。Phi-3 mini は `cpu_and_mobile` / `cuda` / `directml`、Phi-4 mini は `cpu_and_mobile` / `gpu`(GPU 用は CUDA も DirectML も `gpu/` 配下)です([Phi-3 tutorial](https://onnxruntime.ai/docs/genai/tutorials/phi3-python.html)、[microsoft/Phi-4-mini-instruct-onnx](https://huggingface.co/microsoft/Phi-4-mini-instruct-onnx))。コマンドを写すときは、必ず対象モデルのモデルカードのフォルダ名を見てください。
:::

### 自前変換の入口:Model Builder(深入りはしない)

事前量子化版が無いモデルや、自分の PyTorch モデルを量子化したい場合は、GenAI 同梱の **Model Builder** を使います。これが第2回「変換」段の SLM 版です。

```bash
python -m onnxruntime_genai.models.builder \
  -m <model_name> -o <out_dir> -p int4 -e <execution_provider> -c <cache_dir>
```

`-p` が精度(INT4 など)、`-e` がターゲット EP です([Build models — onnxruntime](https://onnxruntime.ai/docs/genai/howto/build-model.html))。ただし公式ページ自身が「最新は Model Builder の README を参照」としており、対応方式・精度オプションは進化が速い領域です([model builder guide — GitHub](https://github.com/microsoft/onnxruntime-genai/blob/main/src/python/py/models/README.md))。本記事はコマンドの存在を示すに留め、詳細は公式 README に委ねます。

ここで §1 で触れた事実を再掲します。**GenAI は Foundry Local / Windows ML の中身でもあります。** 新規 Windows アプリで EP の配布・更新を自前で抱えたくないなら、第4回で扱う Windows ML が適切な入口になります。

## 7. GenAI が"やらない"こと:向かないケースと制約

通常 ML の文脈では「ORT は速く動かすが、量子化・最適化・前処理はしない」と整理しました。同じ問いを SLM 目線で問い直します。GenAI は生成ループを担いますが、その先は利用者の責務です。

GenAI が**やらない/保証しないこと**:

- **base モデルとの出力一致**:量子化版は base と差が出る前提(§4 の disclaimer)。回帰テストを「出力文字列の一致」で組むと壊れる
- **メモリ管理の肩代わり**:長文脈は KV キャッシュでメモリを食う(§4)。文脈長とデバイスメモリの見積もりは自分でやる
- **品質評価**:生成品質を測る仕組みは付いてこない。タスクごとの評価は自前
- **API の安定**:**Preview** であり、API・パッケージ名・サンプルが変わりうる(§2)

**向かないケース / つまずきやすいケース**:

- 厳密な再現性・決定性が必須の用途(生成は確率的、量子化で base とずれる)
- 巨大文脈 × 低メモリ機(量子化しても KV キャッシュでメモリ不足になる)
- サポート対象アーキテクチャ外の最新モデル(対応モデル/EP/OS はサポート行列を要確認。Phi・Llama・Qwen・Mistral・Gemma・DeepSeek 等が対象、speculative decoding 等はロードマップ段階)([microsoft/onnxruntime-genai](https://github.com/microsoft/onnxruntime-genai))
- 出力一致での回帰テストに依存した CI 設計

言い換えれば、「**SLM というランドマークは見えていても、そこへ通じる道(対応アーキテクチャ + 量子化版 + メモリ + 安定 API)が全部開通しているとは限らない**」のです。GenAI を入れた=動く、ではありません。

## 8. 次回へ:この実装が第4〜5回でどう伸びるか

本記事で通したのは、第2回の幹に **生成ループ + 量子化 + メモリ**を足した形でした。以降はこの幹に枝を足していきます。

| 回 | 内容 | 本記事のどこを伸ばすか |
|---|---|---|
| 第1回 | 全体地図 | (前提) |
| 第2回 | ORT で通常 ML を動かす | 幹:変換→ロード→前処理→推論→検証 |
| **第3回(本記事)** | SLM をローカル実行 | 幹を SLM 用に変形 + 生成ループ・量子化・メモリ |
| 第4回(予定) | Windows ML / Windows AI API | §2 の「EP/パッケージを自前管理」を WinML が肩代わり(GenAI は WinML の中身=§1 で触れた事実) |
| 第5回(予定) | 実用アプリへの組み込み | §5/§7 の「品質評価」と全段のアプリ統合・配布 |

第1回「技術地図」と第2回「通常 ML 実装」を横に置いて読むと、全体像の中での現在地が把握できます。

## 9. まとめ:第3回を一文で

- SLM は単発推論ではなく**生成ループ**。第2回の `InferenceSession` ではなく **ONNX Runtime GenAI**(トークナイズ・サンプリング・KV キャッシュ管理を内包、**Preview**)
- パッケージはまた3系統 ——`onnxruntime-genai`(CPU)/ `-directml`(Windows GPU)/ `-cuda`(NVIDIA)。**1環境に1つだけ**
- 最短は**事前量子化済み Phi-3 mini ONNX を取得して `generate()`**。`int4-awq-block-128` 等のモデル名は、ターゲット・量子化方式・精度の**選択を符号化したもの**
- SLM がローカルで動くのは**量子化(INT4 / RTN・AWQ)**のおかげ。ただし量子化は重みメモリを削るだけで、**KV キャッシュは文脈長で別途増える**
- 第2回の5段は捨てず**変形**(変換=取得/Builder、ロード=`og.Model`、前処理=トークナイザ、推論=生成ループ、検証=品質評価)。**base と完全一致しない前提**
- GenAI は生成ループを担うが、**品質・メモリ・Preview の含意は自分の責務**。EP/配布の自動化は第4回 Windows ML

この幹が手に馴染めば、第4回で Windows ML に進んでも、第5回でアプリ統合に進んでも、今どの段の話かを見失いません。次回は、本記事で直接扱った ONNX Runtime / GenAI を **Windows ML 経由で配布・自動 EP 取得**に載せ替えます。

---

### 参考(主要な一次情報)

- [Generate API (Preview) — onnxruntime](https://onnxruntime.ai/docs/genai/)
- [Install ONNX Runtime generate() API — onnxruntime](https://onnxruntime.ai/docs/genai/howto/install.html)
- [Python API — onnxruntime](https://onnxruntime.ai/docs/genai/api/python.html)
- [Phi-3 tutorial — onnxruntime](https://onnxruntime.ai/docs/genai/tutorials/phi3-python.html)
- [Build models (Model Builder) — onnxruntime](https://onnxruntime.ai/docs/genai/howto/build-model.html)
- [model builder guide — microsoft/onnxruntime-genai (GitHub)](https://github.com/microsoft/onnxruntime-genai/blob/main/src/python/py/models/README.md)
- [microsoft/onnxruntime-genai — GitHub](https://github.com/microsoft/onnxruntime-genai)
- [ONNX Runtime supports Phi-3 mini models across platforms and devices — onnxruntime blog](https://onnxruntime.ai/blogs/accelerating-phi-3)
- [microsoft/Phi-3-mini-4k-instruct-onnx — Hugging Face](https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-onnx)
- [microsoft/Phi-4-mini-instruct-onnx — Hugging Face](https://huggingface.co/microsoft/Phi-4-mini-instruct-onnx)
- 連載第1回:WindowsローカルAIの技術地図 2026(同連載・別記事)
- 連載第2回:ONNX Runtime で“ふつうのMLモデル”を動かす最小実装(同連載・別記事)
