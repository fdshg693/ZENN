---
title: "WindowsローカルAI実践 第2回:ONNX Runtime で“ふつうのMLモデル”を動かす最小実装"
emoji: "🛠️"
type: "tech"
topics: ["windows", "onnxruntime", "python", "pytorch", "ai"]
published: false
---

## この記事について

連載「WindowsローカルAI実践入門」の第2回です。第1回「WindowsローカルAIの技術地図 2026」では、`ONNX / ONNX Runtime / Execution Provider / DirectML / Windows ML / NPU / Copilot+ PC` という7語を、層の違う概念として1枚の技術地図に整理しました。第1回は概念の整理に絞っています。

第2回は、その土台 —— **ONNX(形式)→ ONNX Runtime(推論エンジン)→ Execution Provider(実行経路)→ CPU / GPU(ハードウェア)** —— を、Python のコードで実際に踏む実地編です。

題材は LLM / SLM ではなく、あえて **scikit-learn の分類器と PyTorch の画像分類**という “ふつうの ML モデル” を使います。理由は単純で、**「変換 → ロード → 前処理 → 推論 → 検証」という幹はどんなモデルでも共通**だからです。この5段はどのモデルでも変わらない幹であり、第3回(SLM)以降はこの幹に枝を足していくだけになります。

:::message
本記事は連載第2回です。用語の層(ONNX = 形式、ORT = エンジン、EP = 実行経路)は第1回で整理済みのものとして進めます。
:::

対象読者は、学習済みモデル(PyTorch / scikit-learn)はあるが、Windows ローカルでの推論経路を書いたことがない開発者です。Python の基本、pip、numpy が分かれば読めます。コード例は Python 中心とし、GPU 切り替えの C# のみ補足します。

---

## 1. ゴールと全体の道のり

第1回で示した土台を再掲します。**ONNX(モデルの入れ物)→ ONNX Runtime(推論エンジン)→ Execution Provider(どのハードで実行するか)** の3層が変わらない土台で、その下の **CPU / GPU / NPU(ハード)** で実際に計算します。この縦の積み重ねが、Windows ローカル AI の基盤です。

本記事のゴールは次のとおりです。

> scikit-learn と PyTorch のモデルを、**変換 → ロード → 前処理 → 推論 → 検証**の5段で通す。CPU で動かしたうえで DirectML EP に載せ替え、**元のフレームワークと結果が一致するところまで**を最小コードで確認する。

どのフレームワーク由来でも、ローカル推論は必ず次の5段になります。

```
[1] 変換    学習済みモデル → .onnx(形式に詰め替える)
   │   つまずき: opset / 入出力名 / 未対応 op
   ▼
[2] ロード  onnxruntime.InferenceSession(".onnx", providers=[...])
   │   つまずき: EP(providers)の指定漏れ
   ▼
[3] 前処理  入力を「学習時と同じ」かつ「ONNX が食える形」に
   │   つまずき: dtype(float32?)/ 形状(NCHW?)/ 正規化の再現
   ▼
[4] 推論    session.run(出力名 or None, { 入力名: numpy 配列 })
   │
   ▼
[5] 検証    元フレームワークの出力と数値比較
```

ここで一つ重要な事実を確認します。**`.onnx` ファイル単体は動きません。** ONNX は「形式」であって、読んで実行するエンジン(ONNX Runtime、略して ORT)が要ります。ONNX Runtime は PyTorch / TensorFlow / Keras / scikit-learn など複数フレームワーク由来のモデルを実行できるクロスプラットフォームの推論エンジンで、Linux / Windows / macOS、C/C++/C#/Python/Java/JS に対応します([ONNX Runtime docs](https://onnxruntime.ai/docs/)、[ONNX Runtime and Models — Azure ML](https://learn.microsoft.com/en-us/azure/machine-learning/concept-onnx))。

本記事では2つの例を扱います。**例A(scikit-learn)は [1] 変換における「入力契約の固定」**を、**例B(PyTorch)は [3] 前処理の再現と可変形状の扱い**を、それぞれ深掘りします。そして5段のうち **[3] 前処理 と [5] 検証 を省くと、たいてい「動いているのに結果が違う」で詰まります**。これは §4・§5 で実演します。

---

## 2. ONNX Runtime を CPU 環境に入れる

最初の段差はインストールです。Python の ONNX Runtime は用途別に別パッケージになっています。まず **CPU 版だけ**を入れます(GPU 版の選び分けは §6 で扱います)。1つの環境に複数の ONNX Runtime を混在させないでください。

```bash
pip install onnxruntime          # ONNX Runtime 本体(CPU)
pip install skl2onnx             # 例A:scikit-learn → ONNX 変換
pip install onnx onnxscript      # 例B:PyTorch → ONNX 変換に必要
```

`onnxruntime` が推論エンジン本体です。変換側は対象フレームワークごとに別パッケージで、scikit-learn は `skl2onnx`、PyTorch のエクスポータは `onnx` と `onnxscript` を使って PyTorch の演算を ONNX の演算へ翻訳します。本記事で使う追加パッケージはこれで揃います。

出典:[Install ONNX Runtime](https://onnxruntime.ai/docs/install/)、[Get started with Python](https://onnxruntime.ai/docs/get-started/with-python.html)、[Export a PyTorch model to ONNX](https://docs.pytorch.org/tutorials/beginner/onnx/export_simple_model_to_onnx_tutorial.html)。

---

## 3. 例A:入力契約を変換時に固定する(scikit-learn)

最初の例は、あえて深層学習ではなく **scikit-learn** にします。ONNX は scikit-learn のような伝統的 ML(線形モデル、決定木、ランダムフォレスト等)も載せられます。それを実際に確認しつつ、変換時に「入力契約」を固定するという最初の本質的な段差を体験します。変換には `skl2onnx` を使います。

```python
import numpy as np
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression

iris = load_iris()
X, y = iris.data, iris.target
X_train, X_test, y_train, y_test = train_test_split(X, y)

clr = LogisticRegression()
clr.fit(X_train, y_train)
```

ここまではただの scikit-learn です。変換は次のようにします。

```python
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType

# 入力の型と形を「自分で」宣言する
initial_type = [('float_input', FloatTensorType([None, 4]))]
onx = convert_sklearn(clr, initial_types=initial_type)

with open("logreg_iris.onnx", "wb") as f:
    f.write(onx.SerializeToString())
```

ここに**最初の本質的な段差**があります。`initial_types` で **入力名・dtype・形状を明示的に宣言**している点です(`FloatTensorType([None, 4])` = 4 特徴量、バッチ可変)。PyTorch なら実行時に決まる入力型を、ONNX では**変換時に固定**します。これは「ONNX は静的な計算グラフ」という性質の最初の現れで、以降ずっと付きまといます([sklearn-onnx Introduction](https://onnx.ai/sklearn-onnx/introduction.html))。

推論は次のとおりです。

```python
import numpy as np
import onnxruntime as ort

sess = ort.InferenceSession("logreg_iris.onnx", providers=["CPUExecutionProvider"])

input_name = sess.get_inputs()[0].name
label_name = sess.get_outputs()[0].name

pred_onx = sess.run([label_name], {input_name: X_test.astype(np.float32)})
print(pred_onx)
```

注目点が2つあります。

1. **入力名をハードコードしない。** `sess.get_inputs()[0].name` でモデルから取り出します。変換時に付けた名前(ここでは `float_input`)に依存して書くと、別モデルで壊れます([Get started with Python](https://onnxruntime.ai/docs/get-started/with-python.html))。
2. **`dtype` を合わせる。** `X_test.astype(np.float32)` が要ります。宣言した `FloatTensorType` と入力配列の型がズレると実行時に弾かれます。

なお、分類器を変換すると `get_outputs()` が**複数**(ラベル予測と、クラス確率など)になることがあります。だから上のコードは `[label_name]` で**欲しい出力だけ**を指定しています。全出力が欲しければ `sess.run(None, {...})` です([Get started with Python](https://onnxruntime.ai/docs/get-started/with-python.html))。

:::message
入力型の宣言が面倒な場合、`skl2onnx` には学習データ1行から型を推論する簡便関数 `to_onnx(clr, X_train[:1])` もあります。入力名は既定で `'X'`、DataFrame を渡すと**列名が入力名**になります([sklearn-onnx Introduction](https://onnx.ai/sklearn-onnx/introduction.html))。ただし、入力契約を明示的に管理する書き方は `convert_sklearn` + `initial_types` で一度確認しておくとよいでしょう。
:::

---

## 4. 例B:前処理の再現と dynamic axes(PyTorch)

次は深層学習側です。ここで「ONNX は形式であって魔法ではない」が一番はっきり出ます。

:::message alert
**ここでも「新旧の同名問題」が現れます。** PyTorch 2.5 以降、ONNX エクスポータは2系統あります。

- `torch.onnx.export(..., dynamo=True)` — **推奨**。`torch.export` と Torch FX でグラフを捕捉する新方式
- `torch.onnx.export(...)`(`dynamo` なし)— 旧 TorchScript ベース。**非推奨(deprecated)**

出典:[Export a PyTorch model to ONNX](https://docs.pytorch.org/tutorials/beginner/onnx/export_simple_model_to_onnx_tutorial.html)。

古い記事の `torch.onnx.export` 例をそのまま写すと旧経路に乗ってしまいます。情報源が新旧どちらの話かを必ず判定する必要があるのは、用語だけでなく**この変換 API にも当てはまります**。
:::

エクスポートの最小形(画像分類モデルを想定):

```python
import torch

model.eval()
sample = torch.randn(1, 3, 224, 224)  # 学習時と同じ前処理後の形状

torch.onnx.export(
    model,
    sample,
    "model.onnx",
    input_names=["input"],
    output_names=["output"],
    dynamic_axes={                       # バッチサイズを可変に
        "input":  {0: "batch_size"},
        "output": {0: "batch_size"},
    },
    dynamo=True,
)
```

ポイントは、**入力名・出力名・可変にしたい軸(`dynamic_axes`)を変換時に決め切る**ことです。ここで `dynamic_axes` を指定しないと、バッチサイズが `sample` の形に固定された `.onnx` ができてしまいます([Export a PyTorch model to ONNX](https://docs.pytorch.org/tutorials/beginner/onnx/export_simple_model_to_onnx_tutorial.html)、[Get started with Python](https://onnxruntime.ai/docs/get-started/with-python.html))。

:::message
`dynamo=True` 系のエクスポータが受け付ける引数は PyTorch のバージョンによって変化しています(可変形状の指定が `dynamic_axes` から新形式へ移行しつつあるなど)。実装時は、使用中の PyTorch バージョンの公式ドキュメントで引数を確認してください。
:::

推論側で重要なのは前処理です。**ONNX は PyTorch のすべての型・データ構造を表現できません。** だから入力を ONNX が食える形(numpy)に直し、「入力名 → numpy 配列」の辞書で渡します([Export a PyTorch model to ONNX](https://docs.pytorch.org/tutorials/beginner/onnx/export_simple_model_to_onnx_tutorial.html))。

```python
import onnxruntime as ort
import numpy as np

sess = ort.InferenceSession("model.onnx", providers=["CPUExecutionProvider"])

# x は「学習時と同じ前処理を通した」入力テンソル
inputs = {"input": x.numpy().astype(np.float32)}
outputs = sess.run(None, inputs)
predicted = outputs[0].argmax(axis=1)
```

重要なのは、`x` に**学習時とまったく同じ前処理**(リサイズ、`ToTensor`、正規化の平均 / 分散、チャネル順 NCHW)を通すことです。ONNX Runtime はモデルの計算を実行するだけで、**前処理を再現してはくれません**。前処理がズレると、エラーは出ないのに結果だけ静かに間違います。次の §5 で、この種のズレを検出する方法を扱います。

---

## 5. 変換は信用しない:出力一致を検証する

変換は**黙って壊れる**ことがあります。「動いた = 正しい」ではありません。最低限、次の2つを行ってください。検証手順はフレームワークに依存しません。

**(1) 構造を検証する**

```python
import onnx

onnx_model = onnx.load("model.onnx")
onnx.checker.check_model(onnx_model)
```

`onnx.checker.check_model` はモデルが ONNX 仕様として整合しているかを検査します。これは例A(`logreg_iris.onnx`)・例B(`model.onnx`)どちらの `.onnx` でも同じです([Get started with Python](https://onnxruntime.ai/docs/get-started/with-python.html)、[Export a PyTorch model to ONNX](https://docs.pytorch.org/tutorials/beginner/onnx/export_simple_model_to_onnx_tutorial.html))。

**(2) 出力を数値で突き合わせる**

同じ入力を、元のフレームワークと ONNX Runtime の両方に通し、出力が一致するかを比較します。ラベルのような整数出力は完全一致、浮動小数の出力は `numpy.allclose` のような**許容誤差つきの比較**で見ます。

scikit-learn(例A)の場合:

```python
import numpy as np

skl_pred = clr.predict(X_test).astype(np.int64)
ort_pred = sess.run([label_name], {input_name: X_test.astype(np.float32)})[0]
assert np.array_equal(skl_pred, ort_pred)
```

PyTorch(例B)の場合:

```python
torch_out = model(sample).detach().numpy()
ort_out   = sess.run(None, {"input": sample.numpy().astype(np.float32)})[0]
assert np.allclose(torch_out, ort_out, rtol=1e-3, atol=1e-5)
```

PyTorch チュートリアル自体が「PyTorch の結果と ONNX Runtime の結果を比較する」ことを手順に含めています([Export a PyTorch model to ONNX](https://docs.pytorch.org/tutorials/beginner/onnx/export_simple_model_to_onnx_tutorial.html))。

失敗の典型は3つです。

- **opset 不一致 / 未対応 op**:変換は通るが実行で落ちる、または精度が落ちる
- **前処理ズレ**:数値だけ違う(エラーは出ない)。最も発見が遅れる
- **dtype / 形状の取り違え**:`float64` を渡している、NCHW / NHWC が逆 など

Netron でグラフを目視し、入出力名・形状を確認するのも有効です([Export a PyTorch model to ONNX](https://docs.pytorch.org/tutorials/beginner/onnx/export_simple_model_to_onnx_tutorial.html))。

---

## 6. CPU から GPU へ:DirectML EP に載せ替える

ここまでは CPU 推論でした。Windows GPU で速くしたい場合、まず GPU 用パッケージを選び分けます。Python の ONNX Runtime は用途別に別パッケージで、CPU 版とは混在させません。

| Python パッケージ | 対象 | Windows での意味 |
|---|---|---|
| `onnxruntime` | CPU | どこでも動く土台(§2 で導入済み) |
| `onnxruntime-gpu` | NVIDIA GPU(CUDA) | 既定の CUDA は 12.x。CUDA 11.8 は別 index 指定 |
| `onnxruntime-directml` | Windows GPU(DirectML) | 広い Windows GPU で動く。**保守モード(sustained engineering)** |

```bash
pip install onnxruntime-gpu       # NVIDIA CUDA(default CUDA 12.x)
pip install onnxruntime-directml  # Windows GPU(DirectML)
```

C# / C / C++ 側も対応関係は同じ構造です。参考として一覧を示します。

| NuGet | 対象 |
|---|---|
| `Microsoft.ML.OnnxRuntime` | CPU |
| `Microsoft.ML.OnnxRuntime.Gpu` | NVIDIA CUDA |
| `Microsoft.ML.OnnxRuntime.DirectML` | Windows GPU(DirectML、保守モード) |

新規 Windows アプリで推奨される配布形態(Windows ML)は第4回で扱います。

出典:[Install ONNX Runtime](https://onnxruntime.ai/docs/install/)。

:::message alert
ONNX Runtime 公式の install ページは、DirectML について **"DirectML (sustained engineering - use WinML for new projects)"**、Windows 向けには **"WinML (recommended for Windows)"** と明記しています([Install ONNX Runtime](https://onnxruntime.ai/docs/install/))。

つまり「Windows GPU で動かす最短経路」は今でも `onnxruntime-directml` ですが、新規 Windows プロジェクトで推奨されるのは Windows ML(本連載 第4回の主題)です。本記事で DirectML EP を直接叩くのは、EP の挙動(どの演算が GPU に載り、どこが CPU に落ちるか)を実装で理解するためです。実運用の配布形態は第4回で扱います。
:::

`onnxruntime-directml` を入れたら、`InferenceSession` の `providers` に DirectML EP を指定します。

```python
import onnxruntime as ort

print(ort.get_available_providers())  # 環境で使える EP を確認

sess = ort.InferenceSession(
    "model.onnx",
    providers=["DmlExecutionProvider", "CPUExecutionProvider"],
)
```

ここで効いてくる仕様が3つあります。

1. **ONNX Runtime 1.10 以降、`providers` の明示は必須**です。`providers` を省略してよいのは CPU のみで実行する場合だけ、と公式 API ドキュメントが明記しています([Python API documentation](https://onnxruntime.ai/docs/api/python/api_summary.html))。本記事のコード例は、CPU の場合も一貫して `providers` を明示しています。
2. **`providers` は優先順位リストで、フォールバックします。** `["DmlExecutionProvider", "CPUExecutionProvider"]` は「できる演算は DirectML、無理なら CPU」という意味です。リストの最後に CPU を置くのが定石です([Python API documentation](https://onnxruntime.ai/docs/api/python/api_summary.html)、[Execution Providers](https://onnxruntime.ai/docs/execution-providers/))。
3. **利用可能 EP は `ort.get_available_providers()` で確認できます。** `DmlExecutionProvider` が出てこなければ、そもそも `onnxruntime-directml` が入っていない、または環境が対応していません([Execution Providers](https://onnxruntime.ai/docs/execution-providers/))。

:::message alert
**DirectML EP には固有の制約があります。** ONNX Runtime 公式の DirectML ページは、`InferenceSession` を直接構築する場合、セッションの `execution_mode` を `ORT_SEQUENTIAL` に、`enable_mem_pattern` を `false` に設定する必要があると明記しています。また DirectML の opset 対応は ONNX Runtime 本体と異なる場合があり、対応外の高い opset を要求するモデルは性能が出ません。ハード要件として **DirectX 12 対応デバイス**が必要です(DirectML は Windows 10 1903 で導入)([DirectML Execution Provider](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html))。
:::

C# でも考え方は同じです(最小)。`Microsoft.ML.OnnxRuntime.DirectML` を入れて、セッションオプションに DirectML EP を追加します。

```csharp
using Microsoft.ML.OnnxRuntime;

var sessionOptions = new SessionOptions();
sessionOptions.GraphOptimizationLevel = GraphOptimizationLevel.ORT_ENABLE_ALL;
sessionOptions.AppendExecutionProvider_DML(0);  // 0 = device_id
using var session = new InferenceSession("model.onnx", sessionOptions);
```

出典:[DirectML Execution Provider](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html)。

`onnxruntime-directml` / `Microsoft.ML.OnnxRuntime.DirectML` は保守モード(sustained engineering)です。EP の挙動を理解するために直接叩く価値はありますが、新規 Windows アプリで「EP の配布と更新を自前で抱えたくない」場合は、第4回の Windows ML が入口になります。

---

## 7. ONNX Runtime は何を“やらない”か

ONNX Runtime は実行時にグラフ最適化(演算融合など)を行いますが、それでも「モデルを載せれば速くなる」ものではありません。**量子化のようなモデル最適化は別の責務**です。これを実装目線で整理します。

ONNX Runtime が**やらないこと**(実行時のグラフ最適化はする):

- **学習時の前処理の再現**:§4 でみたとおり、前処理は呼び出し側の責任
- **量子化・モデル最適化**:速くするための量子化等は別工程(第3回 SLM の主題)
- **EP の自動配布・更新**:ベンダー EP を環境に合わせて自動で配るのは Windows ML の役割(第4回の主題)

**向かないケース / つまずきやすいケース**:

- 変換非対応の演算を含む最先端モデル(変換は通っても実行で落ちる / 遅い)
- 制御フローが極端に動的なモデル(静的グラフと相性が悪い)
- 前処理が ONNX の外で複雑(画像 / 音声 / テキストの重い前処理を別途用意する必要)
- DirectML の opset 制約や `ORT_SEQUENTIAL` 制約が要件と噛み合わない場合

**CPU フォールバックは「速度が出ない」の主因**になりがちです。EP が扱えない演算ノードは CPU で実行されます([Execution Providers](https://onnxruntime.ai/docs/execution-providers/)、[Python API documentation](https://onnxruntime.ai/docs/api/python/api_summary.html))。`DmlExecutionProvider` を指定したのに思ったほど速くないときは、「GPU に載っていない演算がどれだけあるか」を疑うのが第一歩です。NPU や GPU というハードウェアがあっても、対応 EP と対応 op がそろわなければ性能は出ません。

---

## 8. まとめと、この幹が連載でどう伸びるか

本記事で通した **変換 → ロード → 前処理 → 推論 → 検証** の5段は、連載全体の幹です。要点をまとめます。

- ローカル推論は **変換 → ロード → 前処理 → 推論 → 検証** の5段。**`.onnx` 単体は動かない**(読むエンジンと、学習時と同じ前処理が要る)
- Python の ONNX Runtime は **3パッケージを使い分け**:`onnxruntime`(CPU)/ `onnxruntime-gpu`(CUDA)/ `onnxruntime-directml`(Windows GPU、**保守モード**)
- scikit-learn は `skl2onnx`(**入力型を自分で宣言**)、PyTorch は `torch.onnx.export(..., dynamo=True)`(**旧 TorchScript 経路は非推奨**)
- **変換は信用しない。** `onnx.checker` + 元フレームワークとの**数値一致**を必ず検証する
- GPU は `providers=["DmlExecutionProvider", "CPUExecutionProvider"]`(優先順位 + フォールバック)。`ort.get_available_providers()` で確認。DirectML には `ORT_SEQUENTIAL` 等の固有制約
- ONNX Runtime は**推論実行と実行時のグラフ最適化はするが、量子化などのモデル最適化・前処理の再現・EP 配布はしない**

この幹に、後続の各回が枝を足していきます。

| 回 | 内容 | 本記事のどこを伸ばすか |
|---|---|---|
| 第1回 | 全体地図 | (前提) |
| **第2回(本記事)** | ORT で通常 ML を動かす | 幹そのもの:変換 → ロード → 前処理 → 推論 → 検証 |
| 第3回 | SLM をローカル実行 | §7 の「ORT はやらない」= 量子化 / メモリを足す |
| 第4回 | Windows ML / Windows AI API | §6 の「EP を自前で管理」を Windows ML が肩代わり |
| 第5回 | 実用アプリへの組み込み | 全段をアプリ統合・配布まで |

次回は、この幹に**量子化とメモリ制約**を足して、小規模言語モデル(SLM)をローカルで動かします。

---

### 参考(主要な一次情報)

- [Welcome to ONNX Runtime — onnxruntime.ai](https://onnxruntime.ai/docs/)
- [Install ONNX Runtime — onnxruntime.ai](https://onnxruntime.ai/docs/install/)
- [Get started with Python — onnxruntime.ai](https://onnxruntime.ai/docs/get-started/with-python.html)
- [Python API documentation — onnxruntime.ai](https://onnxruntime.ai/docs/api/python/api_summary.html)
- [ONNX Runtime Execution Providers — onnxruntime.ai](https://onnxruntime.ai/docs/execution-providers/)
- [DirectML Execution Provider — onnxruntime.ai](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html)
- [Export a PyTorch model to ONNX — PyTorch Tutorials](https://docs.pytorch.org/tutorials/beginner/onnx/export_simple_model_to_onnx_tutorial.html)
- [sklearn-onnx Introduction](https://onnx.ai/sklearn-onnx/introduction.html)
- [ONNX Runtime and Models — Azure Machine Learning](https://learn.microsoft.com/en-us/azure/machine-learning/concept-onnx)
- 連載第1回:WindowsローカルAIの技術地図 2026(同連載・別記事)
