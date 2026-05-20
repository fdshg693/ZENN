---
title: "Foundry Local 深掘り:in-process Core API・OpenAI 互換・WinML 統合で読み解く Windows ローカル LLM ランタイム"
emoji: "🏗️"
type: "tech"
topics: ["windows", "foundrylocal", "onnxruntime", "winml", "ai"]
published: false
---

## この記事について

Microsoft の **Foundry Local** は、ローカル LLM を OpenAI 互換 API で動かせる新顔のランタイムです。`winget install Microsoft.FoundryLocal` 1行で入り、`foundry model run phi-4-mini` でチャットできる手軽さから「Ollama の Microsoft 版」と紹介されることもあります。

ところが少し中を覗くと、Ollama とは抽象化のレイヤがかなり違う、別物のソフトウェアであることに気付きます。**Foundry Local は CLI の裏に常駐するサービスでもあり、SDK としてアプリ内に in-process で読み込まれるネイティブライブラリでもあります**。Windows ではさらに Windows ML が EP プラグインの取得・登録を肩代わりしており、「ONNX Runtime を直接叩く」のとも「llama.cpp 系の単純なラッパ」とも違う独自の位置を占めています。

この記事は、Foundry Local 単独を深掘りします。**CLI と SDK の二面構成、モデル alias と variant、WinML との分担、BYOM の手順、Ollama / LM Studio との位置取り、制約**まで、公式 Docs を一次情報として整理します。

:::message
本記事は連載「[WindowsローカルAI実践入門](https://learn.microsoft.com/en-us/windows/ai/overview)」(全5回)とは独立した深掘り記事です。連載第1回で「4入口」の1つとして触れた Foundry Local、第5回で「Azure 同顔切替」の片側として扱った Foundry Local を、単体として拡大した1枚にあたります。連載側との重複は最小限に、Foundry Local 単独で完結するように書いています。
:::

対象読者は、Windows 上で OSS の LLM/SLM をローカル実行したい .NET / Python / Node / Rust 開発者、もしくは Ollama / LM Studio を触ってきて Foundry Local の位置づけを整理したい方です。ONNX / ONNX Runtime / Execution Provider の用語は前提にしますが、必要な箇所では再掲します。

---

## 0. 前提:連載側で扱った地図を3行で

連載第1回([WindowsローカルAIの技術地図](https://learn.microsoft.com/en-us/windows/ai/overview))は、Windows ローカル AI の「4入口」を提示しました。

- **Windows AI APIs**:Microsoft 提供の既製 AI 機能(Phi Silica など)。Copilot+ PC 必須
- **Foundry Local**:既製 OSS LLM / 音声モデルを OpenAI 互換 API で。任意の Windows ハード
- **Windows ML**:自前 ONNX モデルを共有 ORT + 自動 EP 配布で
- **ORT 直**:EP も配布も自分で握る

本記事は、このうち **Foundry Local** だけを単独で深掘りします。連載側で扱った Azure 側との同顔切替(連載第5回 §4)や、Windows ML の EP 配布(連載第4回)は前提として、本記事では Foundry Local 内部の仕組みに集中します。

---

## 1. Foundry Local の正体:二面構成のランタイム

Foundry Local の最初のつまずきは、**「Foundry Local」が指すもの自体が一つではない**ことです。Ollama が「常駐 daemon + CLI クライアント」の一形態しか持たないのに対し、Foundry Local は次の2つの顔を持ちます。

| 顔 | 起動形態 | 通信 | API |
|---|---|---|---|
| **CLI 系統** | 別プロセスのサービス(`foundry service status / restart` で管理) | アプリ ↔ サービス間で HTTP | OpenAI 互換 REST |
| **SDK 系統** | アプリのプロセス内に **in-process** でネイティブライブラリを読み込み | 関数呼出(HTTP オーバーヘッドなし) | 各言語のネイティブ API、オプションで OpenAI 互換 REST も起動可 |

公式アーキテクチャ概説はこう書いています。

> Foundry Local is an end-to-end local AI solution that ships as a single native library inside your application. **Rather than connecting to a separate service or daemon, your code loads the Foundry Local Core API in-process** and calls it through language-specific software development kits (SDKs).
> — [Foundry Local architecture overview](https://learn.microsoft.com/en-us/azure/foundry-local/concepts/foundry-local-architecture)

つまり SDK 側は **「ライブラリ」であって「クライアント」ではない**のがポイントです。Core API は platform-specific なネイティブライブラリ(Windows では `.dll`、Linux では `.so`、macOS では `.dylib`)で、アプリのプロセス空間にロードされます。

一方、CLI でインストールしたとき(`winget install Microsoft.FoundryLocal` や `brew install foundrylocal`)に立ち上がるのはサービスです。`foundry service status` でエンドポイント URL を確認でき、OpenAI 互換 REST サーバとして他プロセスから叩けます([Use the Foundry Local CLI (preview)](https://learn.microsoft.com/en-us/azure/foundry-local/how-to/how-to-use-foundry-local-cli))。

### 使い分けの基準

- **CLI 系統が向くケース**:手元での試用、LangChain / Open WebUI など HTTP ベースのツール統合、複数プロセスから同じモデルを共有
- **SDK 系統が向くケース**:**自分のアプリの中に閉じて動かす本番配布**。SDK は CLI のインストールを前提としません([Foundry Local SDK Reference](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-sdk-current))

> The SDK doesn't require the Foundry Local CLI to be installed on the end users machine, allowing you to ship your applications without extra setup steps for your users — your applications is self-contained.
> — [Foundry Local SDK Reference](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-sdk-current)

この「アプリ self-contained」の性質は、Ollama などの daemon ベースのツールとは大きな差です。**エンドユーザーに別サービスを入れさせずに済む** — 配布物としての成立しやすさが違います。

---

## 2. 最短経路:インストールからチャットまで

実際に手を動かす最短経路を3段に分けます。CLI で動作確認 → OpenAI SDK で叩く → ネイティブ SDK で組み込む、の順です。

### 2.1 CLI で 30 秒で動かす

Windows なら winget、macOS なら Homebrew で入ります。

```powershell
winget install Microsoft.FoundryLocal
foundry --version
```

初回のモデル列挙時、ハードに合った EP がダウンロードされます。**ここで Foundry Local が自前で EP を引っ張ってくる**点が重要です(§4 で詳述)。

```powershell
foundry model list
foundry model run phi-4-mini
```

`foundry model run` を打つと、初回はモデルもダウンロードされ、対話プロンプトが開きます。`/exit` で終了。

接続できないときの定番対処も覚えておきます。

```powershell
foundry service status   # エンドポイント URL とサービスの稼働確認
foundry service restart  # 「Request to local service failed」が出たとき
```

出典:[Use the Foundry Local CLI (preview)](https://learn.microsoft.com/en-us/azure/foundry-local/how-to/how-to-use-foundry-local-cli)、[Foundry Local CLI Reference](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-cli)。

### 2.2 OpenAI SDK で叩く

CLI 系統のサービスは OpenAI 互換 REST サーバなので、OpenAI SDK をそのまま向けられます。

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:XXXXX/v1",  # foundry service status の URL
    api_key="not-needed",
)

resp = client.chat.completions.create(
    model="phi-4-mini",
    messages=[{"role": "user", "content": "Foundry Local とは何か3行で"}],
)
print(resp.choices[0].message.content)
```

ポート番号は固定ではないため、`foundry service status` で取って渡します。

「Azure OpenAI と同じ OpenAI SDK で叩ける」という連載第5回 §4 の話は、**この CLI 系統の話**です。SDK 系統で REST を立てなければ、エンドポイント差し替えという概念は出てきません(代わりに SDK の `manager` インスタンスを差し替えることになります)。

### 2.3 ネイティブ SDK で組み込む(C# / Python)

本番アプリに組み込むなら、SDK 系統を選びます。Windows 向けは **`*.WinML` バリアント**を採るのが推奨です(§4 の理由による)。

```bash
# C# Windows 向け
dotnet add package Microsoft.AI.Foundry.Local.WinML

# Python Windows 向け
pip install foundry-local-sdk-winml openai
```

公式の説明はこうです。

> The Windows package integrates with the Windows ML runtime — **it provides the same API surface area with a wider breadth of hardware acceleration**.
> — [Foundry Local SDK Reference](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-sdk-current)

C# の最小スニペットは、Foundry Local が公開している `FoundryLocalManager` を起点に書きます([Get started with Foundry Local (Windows)](https://learn.microsoft.com/en-us/windows/ai/foundry-local/get-started))。

```csharp
using Microsoft.AI.Foundry.Local;
using Microsoft.Extensions.Logging.Abstractions;

// 1. Foundry Local を初期化(必要ならサービスを起動)
await FoundryLocalManager.CreateAsync(
    new Configuration { AppName = "my-app" },
    NullLogger.Instance);
var manager = FoundryLocalManager.Instance;

// 2. カタログから alias で取得
var catalog = await manager.GetCatalogAsync();
var model = await catalog.GetModelAsync("phi-3.5-mini")
    ?? throw new Exception("Model not found");

// 3. キャッシュになければダウンロード
if (!await model.IsCachedAsync()) {
    // 進捗を流す(実装は省略)
}
// 4. ロード → 推論 → アンロード(略)
```

このコードは **`localhost:XXXXX` のような URL を一切持ちません**。SDK 系統は in-process なので、関数呼出だけで完結します。

---

## 3. モデルカタログの読み方:alias と variant

Foundry Local のモデル指定には、Ollama の `phi3:latest` のような「タグ」に似て見えるが**裏で動くハード適合の選択が違う**仕組みがあります。

### alias = ハード適合の自動選択

`foundry model run phi-4-mini` のように **alias** を渡すと、Foundry Local が「ホストの hardware に最適な variant」を選びます。Phi-4 mini には通常、量子化や EP 別に複数の variant があり、これを開発者が手で選ぶ必要はありません。

> Use a model alias (like `phi-4-mini`) to let Foundry Local automatically select the best variant for your hardware. Use a full model ID to target a specific variant.
> — [Use the Foundry Local CLI (preview)](https://learn.microsoft.com/en-us/azure/foundry-local/how-to/how-to-use-foundry-local-cli)

特定の variant を強制したい場合だけ、フル ID を渡します。

### フィルタで variant を探す

CLI には強力なフィルタがあります。

```powershell
foundry model list --filter device=GPU
foundry model list --filter task=chat-completion
foundry model list --filter provider=OpenVINOExecutionProvider
foundry model list --filter alias=qwen   # 前方一致
```

サポートされるフィルタキーは公式リファレンスにまとまっています([Foundry Local CLI Reference](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-cli))。`provider=...` のキーは Foundry Local が認識する **EP の名前**そのもので、次節で詳しく見ます。

### キャッシュ操作

ローカルキャッシュは独立した CLI で操作できます。

```powershell
foundry cache list           # 保存済みモデル一覧
foundry cache location       # キャッシュパス
foundry cache remove phi-4-mini
foundry cache cd /path/to/new/cache   # 大容量ディスクに移したいとき
```

---

## 4. ハードウェア抽象化の中身:WinML との分担

Foundry Local の「自動で速くなる」という売り文句の中身を見ます。これは **Windows と非 Windows でやっていることが違う**のがポイントです。

### 4.1 Core API のライフサイクル4段

公式アーキテクチャ概説は、モデル実行を次の4段に分けて説明します([Foundry Local architecture overview](https://learn.microsoft.com/en-us/azure/foundry-local/concepts/foundry-local-architecture))。

1. **Download** — SDK が alias でモデルを要求 → なければ Foundry Catalog から取得しディスクに保存
2. **Load** — メモリにロード、ONNX Runtime セッション初期化、**利用可能ハードに合わせて EP を選択**
3. **Inference** — 推論(同期 / ストリーミング両対応)
4. **Unload** — メモリ解放、キャッシュは残る

このうち **Step 2 の「EP 選択」** が Foundry Local の差別化ポイントです。

### 4.2 Windows での EP 取得経路

公式アーキテクチャ概説は、Windows での EP 取得を明確に WinML に委ねていると書いています。

> On Windows, the Core API delegates execution provider management to the Windows ML runtime. WinML handles:
>
> - **Execution provider plugin acquisition** — sourcing hardware-matched execution provider plugins from the OS and Windows Update.
> - **Runtime registration** — registering acquired execution providers with ONNX Runtime so they're available during inference.
> - **Driver compatibility** — negotiating driver versions and handling compatibility checks to ensure stable execution.
>
> — [Foundry Local architecture overview](https://learn.microsoft.com/en-us/azure/foundry-local/concepts/foundry-local-architecture)

つまり、**ベンダー EP プラグインの取得・登録・ドライバ互換交渉は Windows ML が肩代わり**しており、Foundry Local 自身はそれをラップしているだけです。連載第1回 §3 で扱った Windows ML の `ExecutionProviderCatalog` の話と、Foundry Local が裏でつながっているのはこの一点です。

このため、`Microsoft.AI.Foundry.Local.WinML` パッケージのほうが「同 API でハード加速の幅が広い」と公式が説明するわけです — Windows ML の EP プールがそのまま使えるから、です。

### 4.3 Linux / macOS の取り扱い

非 Windows では WinML がないため、SDK 自身が EP プラグインを bundle します。

> On Linux and macOS, the Core API registers execution providers directly with ONNX Runtime without a platform intermediary. **The SDK bundles the required execution provider plugins** for each target platform, so registration is handled internally during model loading.
> — [Foundry Local architecture overview](https://learn.microsoft.com/en-us/azure/foundry-local/concepts/foundry-local-architecture)

Windows 以外では「OS の EP プール」という概念がなく、各 SDK パッケージが対応 EP を抱えて配ります。

### 4.4 利用可能な EP

CLI フィルタの provider 値から、Foundry Local が認識する EP を逆引きできます([Foundry Local CLI Reference](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-cli))。

| EP 名(provider 値) | 役割 |
|---|---|
| `CPUExecutionProvider` | 全環境の最終フォールバック(MLAS ベース) |
| `WebGpuExecutionProvider` | 任意の GPU の汎用フォールバック(Dawn 経由) |
| `CUDAExecutionProvider` | NVIDIA GPU 向けの常駐 EP(RTX 30 系以降) |
| `NvTensorRTRTXExecutionProvider` | NVIDIA RTX 系で TensorRT 最適化を効かせる EP |
| `OpenVINOExecutionProvider` | Intel CPU / iGPU / NPU |
| `VitisAIExecutionProvider` | AMD Vitis AI(Ryzen AI NPU 等) |
| `QNNExecutionProvider` | Qualcomm Hexagon NPU(Snapdragon X) |

Foundry Local の組み込み(built-in)EP は CPU / WebGPU / CUDA の3つで、それ以外(`NvTensorRTRTXExecutionProvider`、`OpenVINOExecutionProvider`、`QNNExecutionProvider`、`VitisAIExecutionProvider`)は Windows 上で **動的にダウンロード・登録される plugin EP** という扱いです([Foundry Local CLI Reference](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-cli))。Foundry Local 側のカタログは時期によって認識する EP が変わるため、必ず最新の CLI リファレンスで確認してください(GitHub issue 例で variant 列挙が版間で変動した事例があります、§8 で触れます)。

---

## 5. OpenAI 互換性:Chat Completions エンドポイントを中心に

Foundry Local の API は OpenAI 仕様に寄せられています。

> **OpenAI-compatible API** — Supports OpenAI request and response formats including the OpenAI Responses API format. If your application already uses the OpenAI SDK, point it to a Foundry Local endpoint with minimal code changes.
> — [What is Foundry Local?](https://learn.microsoft.com/en-us/azure/foundry-local/what-is-foundry-local)

ここは公式の表現がやや曖昧なので注意して読み解く必要があります。REST API リファレンス([Foundry Local REST API Reference](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-rest))を見ると、CLI 系統のサーバが実際に公開している OpenAI 互換エンドポイントは次の通りです。

| エンドポイント | 用途 |
|---|---|
| `POST /v1/chat/completions` | Chat Completions(OpenAI Chat Completions API と完全互換) |
| `POST /v1/audio/transcriptions` | 音声書き起こし(Whisper 系モデル向け) |

**`/v1/responses` のような Responses API 相当のエンドポイントは現時点では公開されていません**。引用の「Responses API format」という表現は、リクエスト/レスポンスのペイロード形式(reasoning 関連フィールドなど)を受け入れる、という程度の意味と読むのが安全で、**ステートフルなツール利用やセッション管理を担う Responses API 相当のエンドポイントを Foundry Local が提供している、という意味ではない**点に注意してください。

実用上の結論はシンプルで、Foundry Local 単体としては、

- **CLI 系統**:OpenAI SDK の `chat.completions` を、エンドポイントだけ差し替えればよい
- **SDK 系統**:アプリ内 OpenAI 互換 REST をオプションで起動できる(ただし HTTP オーバーヘッドが付くので、in-process 関数呼出を優先するほうが性能的に得)

この2方式を覚えておけば十分です。連載第5回 §4 で扱った「Azure OpenAI と Foundry Local の同顔切替」も、Chat Completions の base_url 差し替えが軸であり、Responses API ベースのコードをそのまま移すことを意図したものではありません。

---

## 6. BYOM:Hugging Face モデルを Olive で乗せる

カタログにないモデルを動かしたい場合、Foundry Local は **Olive で HF を ONNX 化し配置**する経路を用意しています([Compile Hugging Face models to run on Foundry Local](https://learn.microsoft.com/en-us/azure/foundry-local/how-to/how-to-compile-hugging-face-models))。Ollama の GGUF 取り込みより手間がかかりますが、EP 種別に応じた量子化を Olive 側で扱えるのが強みです。

最小手順は次の3つです。

1. **Olive で convert / optimize / quantize**(`fp16` / `fp32` / `int4` / `int8` 指定可能)。Llama-3.2-1B-Instruct の例で、コンパイル自体は約 60 秒、ダウンロード時間別。
2. **`inference_model.json` をモデルディレクトリに置く**。最小限のメタデータは次のように。

   ```python
   import json, os
   model_path = "models/llama"
   json_template = { "Name": "llama-3.2:1" }   # 任意のモデル名、既定 version は 1
   with open(os.path.join(model_path, "inference_model.json"), "w") as f:
       json.dump(json_template, f, indent=2)
   ```

3. **Foundry Local が認識**(`foundry model list` に出る)→ `foundry model run` できる

> **Important:** The Olive CLI and optimization settings change over time, and a single command line example might not work for every model, device, or execution provider.
> — [Compile Hugging Face models to run on Foundry Local](https://learn.microsoft.com/en-us/azure/foundry-local/how-to/how-to-compile-hugging-face-models)

Olive の最新 CLI と最適化設定はバージョン間で変わるため、公式は **Olive Recipes リポジトリ**(モデル別・ハード別の最適化設定セット)を参照することを推奨しています。BYOM の最終確認は記事ではなく Olive Recipes に当たるのが安全です。

---

## 7. Ollama / LM Studio との位置取り

「で、Ollama や LM Studio とは何が違うのか?」は、Foundry Local を最初に触る人が必ず持つ問いです。三者を一次仕様レベルで並べると次のようになります(性能ベンチマーク的な主観評価には踏み込みません)。

| 軸 | Foundry Local | Ollama | LM Studio |
|---|---|---|---|
| プロセスモデル | CLI = サービス / SDK = in-process の二面 | 常駐 daemon 専用 | デスクトップ GUI + ローカル HTTP サーバ |
| モデル形式 | **ONNX**(Olive 最適化) | GGUF(llama.cpp 系) | GGUF |
| ハード加速 | OpenVINO / NvTensorRTRTX / VitisAI / WebGPU / CPU(**Windows は WinML 経由で EP plugin 取得**) | CUDA / Metal / ROCm(llama.cpp 経由) | CUDA / Metal / Vulkan |
| OpenAI 互換 | Chat Completions エンドポイント(`/v1/chat/completions`)+ Audio Transcriptions | Chat Completions 互換 | Chat Completions 互換 |
| BYOM 経路 | Olive で ONNX 化 + `inference_model.json` | `Modelfile` から GGUF | GGUF を import |
| Azure 側と同 SDK 切替 | あり(OpenAI SDK の base_url 差し替え) | なし | なし |
| アプリ self-contained 配布 | あり(SDK 系統) | 不向き(daemon 配布が必要) | 不向き(GUI ベース) |

技術的な差を整理すると、選び分けは次のようになります。

- **Foundry Local が向く**:
  - Windows で NPU / iGPU 含む幅広いハード加速を1コードパスで使いたい
  - 将来 Azure OpenAI / Microsoft Foundry と OpenAI SDK で切り替えたい
  - エンドユーザーに別 daemon を入れさせず、アプリ self-contained で配布したい
  - ONNX エコシステム(Olive / WinML / ORT)の資産がすでにある
- **Ollama が向く**:
  - Mac / Linux 中心の開発、GGUF エコシステムを活かしたい
  - daemon ベースの周辺ツール(Open WebUI 等)に依存
- **LM Studio が向く**:
  - エンドユーザー向け GUI が要る、モデル選定段階の試用

「ONNX か GGUF か」は単なる形式の好みではなく、**ハード加速の経路**を決める選択です。GGUF を選ぶと llama.cpp 系の最適化ルートに乗り、ONNX を選ぶと ONNX Runtime と各社 EP の最適化ルートに乗ります。Windows での NPU / iGPU 活用を真面目にやりたい場面では、WinML 経由の EP プールが効く Foundry Local が現状のいちばん近い道です。

---

## 8. 制約と落とし穴

実装に進む前に押さえておくべき落とし穴を4つ挙げます。

### 8.1 `foundry service` の接続エラー

CLI インストール直後に `Request to local service failed` が出ることがあります。これは公式 Tips としてリカバリ手順が明示されています。

> If you see a service connection error after installation (for example, `Request to local service failed`), run `foundry service restart`.
> — [Use the Foundry Local CLI (preview)](https://learn.microsoft.com/en-us/azure/foundry-local/how-to/how-to-use-foundry-local-cli)

ポートバインディング問題で実行中だがアクセス不能、というケースの定番対処です。

### 8.2 CLI は preview 表記

CLI を扱うドキュメントのタイトルは "Use the Foundry Local CLI (preview)" のままです。**CLI のサブコマンドや出力フォーマットは将来変動する余地がある**と考え、本番のシェルスクリプトでパースに依存するのは避けるのが安全です。SDK 系統のほうが API としては安定しています。

### 8.3 モデルカタログは版間で動く

Foundry Local 本体のバージョンと、利用可能 variant のセットは同期して動きます。**特定のハード向け variant が次バージョンで消えた**事例も GitHub issue で報告されています(NPU 専用 variant が 0.7.117 で一覧から消えた件:[microsoft/Foundry-Local #259](https://github.com/microsoft/Foundry-Local/issues/259))。

実用上の対処は明確で、§3 で見た通り **alias 指定**で運ぶことです。alias は「ホストに最適な variant」を Foundry Local 側が選び直してくれるため、variant 列挙のブレを吸収できます。フル ID を CI スクリプトに焼き込んでいると、版更新で動かなくなります。

### 8.4 OGA 警告は無害

プロセス終了後に "underlying ONNX Runtime GenAI (OGA) library" 由来の警告が出ることがあります。これは無害で、**Foundry Local の内部実装が ONNX Runtime GenAI(OGA)である痕跡**でもあります([Get started with Foundry Local](https://learn.microsoft.com/en-us/windows/ai/foundry-local/get-started))。

連載第3回・第4回で扱った ONNX Runtime GenAI は、Foundry Local / Windows ML の内部実装としても共有されている、という構図がここで確認できます。SLM の生成ループのコア部分は、3者で同じものを使い回しているわけです。

---

## 9. 設計変更:旧 SDK から新 SDK へ ─ なぜ in-process に移ったか

ここまで §1〜§8 で見てきた Foundry Local の姿は、**わりと最近(2025〜2026 にかけて)行われた大きな設計変更の結果**です。古いブログ記事や旧バージョンの SDK で書かれたコードと、本記事に挙げたコードはかなり違って見えるはずです。互換性の問題でつまずく前に、なぜ変わったか・何が変わったかを押さえておきます。

このセクションは §8 の「ちょっとした落とし穴」とは性格が違います。**設計の根幹**が動いたという話で、旧版のコードベースから移行する場合や、ネット上の古いサンプルを参考にする場合は必ず影響します。

### 9.1 旧アーキテクチャ:REST web server 一択

旧 SDK の世界は「REST サーバ前提」で組まれていました。公式マイグレーションガイドは次のように要約しています。

> The following diagram shows how the previous architecture relied heavily on using a REST webserver to manage models and inference like chat completions.
> — [Foundry Local SDK Migration Guide](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-sdk-migration)

旧 `FoundryLocalManager` クラスは、CLI が立ち上げたサービスを HTTP で叩くためのクライアントでした。具体的には次のような形です([Foundry Local Legacy SDK Reference](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-sdk-legacy))。

| 旧 SDK の特徴 | 内容 |
|---|---|
| 構築 | `var manager = new FoundryLocalManager();` を直接 `new` |
| 公開プロパティ | `ServiceUri` / `Endpoint`(`ServiceUri + /v1`)/ `ApiKey`(既定 `"OPENAI_API_KEY"`)/ `IsServiceRunning` |
| サービス管理 | `StartServiceAsync()` / `StopServiceAsync()` を呼んでサービス側を制御 |
| 推論経路 | OpenAI 互換 REST を必ず経由 |
| CLI 依存 | **CLI/サービスがエンドユーザー機に必要** |

これは「OpenAI 互換 REST が常に裏で動いている」前提のシンプルな設計でしたが、**エンドユーザーに Foundry Local CLI を別インストールさせる必要**があるという配布上の制約を抱えていました。Ollama と本質的に同じ「daemon + クライアント」のモデルです。

### 9.2 新アーキテクチャの3つの変更点

新版(C# は `0.8.0` 以降、Rust は `1.0.0` 以降)は、この前提を根本から書き直しました。マイグレーションガイドが挙げる利点は3つです。

> - Your application is self-contained. It doesn't require the Foundry Local CLI to be installed separately on the end user's machine making it easier for you to deploy applications.
> - The REST web server is optional. You can still use the web server if you want to integrate with other tools that communicate over HTTP.
> - The SDK has native support for chat completions and audio transcriptions, allowing you to build conversational AI applications with fewer dependencies.
> — [Foundry Local SDK Migration Guide](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-sdk-migration)

これは §1 で見た「**二面構成のうち SDK 系統が in-process でアプリ self-contained**」という現在の姿そのものです。

| 観点 | 旧 SDK | 新 SDK |
|---|---|---|
| Core | アプリ ↔ CLI サービス間 HTTP | アプリ内 in-process ネイティブライブラリ |
| REST 必要性 | 必須 | オプション(必要時のみ起動) |
| CLI 必須 | あり(配布物に含める必要) | なし(アプリ self-contained) |
| ネイティブ chat / audio API | なし(REST 経由) | あり(SDK 直接呼出) |

### 9.3 API は「フラットな静的メソッド」から「state を持つインスタンス」へ

実装面の変更も大きく、マイグレーションガイドは次のように説明しています。

> The latest version provides a more object-oriented and composable API. The main entry point continues to be the `FoundryLocalManager` class, but instead of being a flat set of methods that operate via static calls to a stateless HTTP API, the SDK now exposes methods on the `FoundryLocalManager` instance that maintain state about the service and models.
> — [Foundry Local SDK Migration Guide](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-sdk-migration)

API シェイプの変化を見るのが早いです。

**旧 SDK(C#):**

```csharp
// new で直接構築 → サービスを HTTP で叩くクライアント
var manager = new FoundryLocalManager();
await manager.StartServiceAsync(CancellationToken.None);

// プロパティでサービス URL を取り、OpenAI SDK にそのまま渡す前提
var endpoint = manager.Endpoint;   // ServiceUri + "/v1"
var apiKey   = manager.ApiKey;     // 既定 "OPENAI_API_KEY"
```

**新 SDK(C#):**

```csharp
// factory メソッド経由で初期化、state を持つインスタンスを取得
await FoundryLocalManager.CreateAsync(
    new Configuration { AppName = "my-app" },
    NullLogger.Instance);
var manager = FoundryLocalManager.Instance;

// カタログとモデルが第一級の概念に
var catalog = await manager.GetCatalogAsync();
var model = await catalog.GetModelAsync("phi-3.5-mini");
if (!await model.IsCachedAsync()) { /* ダウンロード */ }
// 以降はモデルインスタンスにメソッドを生やしていく
```

旧版は「サービスを立てる → URL を取る → OpenAI SDK でその URL を叩く」という発想で、Foundry Local の SDK 自体は **URL とキーを露出するだけ**の薄いラッパでした。新版は逆に、**カタログ・モデル・推論のすべてを SDK の第一級概念にして**、HTTP を消しています。これが §1 で見た「SDK 系統は関数呼出だけで完結する」の正体です。

### 9.4 Rust ユーザーへの追加注意:クレート名そのものが変わった

Rust SDK は破壊的変更がもっとも大きい言語の1つで、**クレート名そのものが変わりました**。

> In the latest Rust SDK version (`1.0.0`), there are breaking changes in the API from the previous version. The crate name has changed from `foundry-local` to `foundry-local-sdk`.
> — [Foundry Local SDK Migration Guide](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-sdk-migration)

`Cargo.toml` を更新せずに `cargo update` だけしても新版に乗り換えられない、ということです。古い `foundry-local` クレートに依存している場合は、明示的に `foundry-local-sdk` に差し替える必要があります。

### 9.5 なぜこの変更が起きたかと、移行の判断軸

公式の動機を一文に畳むとこうなります — **「アプリを on-device AI で出荷しやすくするため」**。

> To improve your ability to ship applications using on-device AI, there are substantial changes to the architecture of the C# SDK in version `0.8.0` and later.
> — [Foundry Local SDK Migration Guide](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-sdk-migration)

旧 SDK は「Ollama 的な daemon + クライアント」モデルでした。これは試用には軽快ですが、エンドユーザー機に CLI を入れさせる必要がある時点で、**コンシューマ向けアプリの配布物としては成立しにくい**という弱点があります。新 SDK の in-process ネイティブライブラリ化は、この弱点を正面から消す変更です。同時に、HTTP のシリアライズ/デシリアライズが消える分、性能と依存関係の単純化も得られます。

移行の判断軸は3つです。

- **旧 SDK のまま塩漬けにする選択**:すでに配布済みで、CLI/サービスもセットで入っている運用なら、当面そのままでも動きます。ただし新機能(in-process のネイティブ chat completions / audio transcriptions API など)は乗らないことを覚悟する必要があります。
- **CLI 系統を引き続き使う選択**:アプリ内蔵ではなく開発者ツール用途であれば、§2.2 の OpenAI SDK 直接呼出はそのまま使えます。これは「旧 SDK」ではなく「新 SDK 時代の CLI 系統」で、十分にサポート対象です。
- **新 SDK に移行する選択(本記事の前提)**:エンドユーザー向けアプリで、配布の手間を最小化したい場合は新 SDK 一択です。ただしマイグレーションガイドが明言する通り、**初期化パターン、モデル管理、推論すべてが変わる**ため、機械的な置換ではなくコードレビューを伴う移行になります。

ネット上で見つけたサンプルが `new FoundryLocalManager()` で始まっていたら旧版、`FoundryLocalManager.CreateAsync(...)` で始まっていたら新版、という見分け方を覚えておくと、参照すべき情報を間違えずに済みます。

---

## 10. まとめ:Foundry Local を一文で

最後に、本記事の地図を一覧に畳みます。

- **Foundry Local は二面ランタイム**。CLI 系統(サービス + OpenAI 互換 REST)と SDK 系統(in-process ネイティブ Core API)で配布の形が変わる。アプリ self-contained で配るなら SDK 系統。
- **モデル指定は alias / フル ID の2系統**。alias を使えば Foundry Local が hardware 適合 variant を自動選択する。CI には alias を使うのが安全。
- **Windows のハード加速は Windows ML が肩代わり**。EP plugin の取得・登録・ドライバ互換交渉は WinML が担当し、Foundry Local はそれをラップしている。だから `*.WinML` パッケージは同 API でハード加速の幅が広い。Linux / macOS では SDK が EP を bundle する。
- **OpenAI 仕様サポートの実体は Chat Completions エンドポイント**(`/v1/chat/completions`)。公式が触れる「Responses API format」はペイロード形式の互換性であって、`/v1/responses` 相当のエンドポイントは公開されていない点に注意。Azure OpenAI と Chat Completions API で切り替えられる(設計は連載第5回 §4)。
- **BYOM は Olive で ONNX 化**して `inference_model.json` を置く。Olive Recipes の参照が安全。
- **Ollama / LM Studio とは抽象レイヤが違う**。Foundry Local は ONNX + WinML 経路 + Azure 同顔、Ollama / LM Studio は GGUF + llama.cpp 経路。

`winget install Microsoft.FoundryLocal` から `foundry model run phi-4-mini` までの 30 秒の体験の裏に、Windows ML との分担、Core API の in-process ロード、Olive の存在、OpenAI 仕様への寄せといった複数の選択が積み重なっています。「Microsoft 版 Ollama」と呼ぶには道具立てが違いすぎる、というのが本記事の結論です。

---

### 参考(主要な一次情報)

- [What is Foundry Local? — Microsoft Learn](https://learn.microsoft.com/en-us/azure/foundry-local/what-is-foundry-local)
- [Foundry Local architecture overview — Microsoft Learn](https://learn.microsoft.com/en-us/azure/foundry-local/concepts/foundry-local-architecture)
- [Get started with Foundry Local — Microsoft Learn](https://learn.microsoft.com/en-us/azure/foundry-local/get-started)
- [Get started with Foundry Local (Windows) — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/foundry-local/get-started)
- [Use the Foundry Local CLI (preview) — Microsoft Learn](https://learn.microsoft.com/en-us/azure/foundry-local/how-to/how-to-use-foundry-local-cli)
- [Foundry Local CLI Reference — Microsoft Learn](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-cli)
- [Foundry Local SDK Reference — Microsoft Learn](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-sdk-current)
- [Foundry Local SDK Migration Guide — Microsoft Learn](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-sdk-migration)
- [Foundry Local Legacy SDK Reference — Microsoft Learn](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-sdk-legacy)
- [Compile Hugging Face models to run on Foundry Local — Microsoft Learn](https://learn.microsoft.com/en-us/azure/foundry-local/how-to/how-to-compile-hugging-face-models)
- [microsoft/Foundry-Local — GitHub](https://github.com/microsoft/Foundry-Local)
- [microsoft/Foundry-Local Issue #259(NPU variant の列挙変動)](https://github.com/microsoft/Foundry-Local/issues/259)
