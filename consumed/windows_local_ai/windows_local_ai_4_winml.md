---
title: "WindowsローカルAI実践 第4回:Windows ML で EP 自前管理を捨てる(+ Phi Silica という既製の入口)"
emoji: "🧩"
type: "tech"
topics: ["windows", "winml", "onnxruntime", "csharp", "ai"]
published: false
---

## この記事について

連載「WindowsローカルAI実践入門」の**第4回**です。第1回は7語を**1枚の技術地図**に置き、第2回はその地図の §2(ONNX→ORT→EP)を `scikit-learn`/`PyTorch` の通常 ML で歩き、第3回は同じ幹に **生成ループ・量子化・メモリ**を足して SLM を動かしました。

第2回・第3回では、**EP のパッケージを開発者が自分で選び、`--pre` を付け、混在を避け、配布と更新も抱える**運用が前提でした(`pip install onnxruntime-directml`、`pip install --pre onnxruntime-genai-directml` 等)。この自動配布・更新を担う層が **Windows ML** であり、本記事の主題です(第2回 §2/§7 と第3回 §2 で「Windows ML の領分」として言及した内容に対応)。

加えて、ONNX Runtime GenAI が Foundry Local・Windows ML の内部実装として共有されている点を、本記事 §8 で具体的に位置づけます。

:::message
本記事は連載第4回です。第1回(技術地図)・第2回(通常 ML)・第3回(SLM/GenAI)を読んでいる前提で、`ONNX → ORT → EP → ハード` の幹、5段(変換→ロード→前処理→推論→検証)、生成ループ・量子化は説明済みとして進めます。
:::

:::message alert
**第4回からコードの主軸を C#/WinRT に変えます。** Windows ML と Windows AI APIs の一級 API は C#/C++ であり、**Python は別経路の二級扱い**(ネイティブ登録が Python 環境では効かない)というのが公式の設計です。根拠は §5 で示し、Python 読者向けには §5 で別経路を明示します。
:::

対象読者は、第1〜3回で幹を理解し、**次は自前 ML/SLM を実アプリに組み込みたい、または「自前モデルすら要らない既製機能」が何かを知りたい**開発者です。C# の基本が読めれば十分です。

---

## 0. はじめに:EP の自前管理を Windows ML に委ねる

これまでの回が「縦の土台(ONNX→ORT→EP→ハード)」を実地で歩く構成であったのに対し、本記事は**その縦を横から束ねる配布層**を扱います。

本記事のゴールは次の3点です。

> 1. 従来の手作業(EP/パッケージの選択・混在禁止・配布・更新)を **`ExecutionProviderCatalog` の数行に置き換える**。
> 2. 自前モデルが不要な入口として、**Phi Silica を `LanguageModel` の数行で呼び出す**。
> 3. ONNX Runtime GenAI が Foundry Local・Windows ML の内部でどう使われているかを位置づける。

## 1. EP 自前管理が抱える4つの責務

第2回 §2 と第3回 §2 で導入した「pip で EP パッケージを入れる」手順は、利便性と引き換えに、開発者に次の**4つの責務**を残します。

- **(a) 選択**:環境ごとに正しい EP パッケージを選ぶ(`onnxruntime` か `-gpu` か `-directml` か / `-genai` か `-genai-directml` か)
- **(b) 混在禁止**:1環境に1つだけインストールする(混在は不正動作の原因)
- **(c) 配布**:ベンダー EP をアプリに同梱して配る
- **(d) 更新**:EP の新版を自分で追って差し替える

第1回 §4 で概念のみ提示した「Windows ML の自動デプロイ4ステップ」——**アプリ導入 → ハード検出 → 最適 EP ダウンロード → 即推論**——は、この4責務にちょうど1対1で対応します。Windows ML は、**この4責務を肩代わりする横断レイヤ**として定義されています([What is Windows ML?](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/overview))。

:::message alert
ただし**先に「肩代わりされないもの」を確定**しておく必要があります。Windows ML が肩代わりするのは (a)〜(d)、すなわち**EP の配布と選択だけ**です。第1回 §4 の注記どおり、**モデル最適化・量子化は行いません**(第3回 §4 の主題)。前処理も依然として開発者の責務です(第2回 §4)。「Windows ML を使えば自動で速くなる/最適化される」というものではありません。
:::

## 2. Windows ML の導入:NuGet とブートストラップ初期化

第2・3回で開発者が行っていた「pip で EP パッケージを選んで入れる」作業は、Windows ML では **NuGet 2点 + ブートストラップ初期化**に置き換わります。これにより「環境ごとに正しい EP パッケージを選び、混在を避ける」という設計上の前提(責務 a/b)が**そもそも不要になります**。EP は実行時に取得されるためです(§3)。

C#/C++ では `Microsoft.WindowsAppSDK.ML` が Windows ML ランタイムの `.winmd` を提供します。配布方式は2種類で、公式は framework-dependent を推奨しています([Windows ML APIs](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/api-reference)、[Install and deploy Windows ML](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/distributing-your-app))。

| | framework-dependent(推奨) | self-contained |
|---|---|---|
| NuGet | `Microsoft.WindowsAppSDK.ML` + `Microsoft.WindowsAppSDK.Runtime` | `Microsoft.WindowsAppSDK.ML` のみ(`.Runtime`/メインパッケージは入れない) |
| アプリサイズ | 小(Windows ML をシステム共有) | 大(約 41MB 同梱) |
| Windows ML 更新 | 自動(App SDK サービシング) | 手動(自分で新版を出す) |

self-contained の約 41MB の内訳は、Windows ML API DLL 約 1MB + `onnxruntime.dll` 約 20MB + `DirectML.dll` 約 20MB です(第1回 §4 と同一の数字)。**ベンダー EP(QNN/OpenVINO/VitisAI 等)はこの 41MB に含まれません**。これらは実行時に取得されます(§3)([Install and deploy Windows ML](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/distributing-your-app))。

実行前には Windows App SDK のブートストラップ初期化が必要です。C#/C++ では App SDK ブートストラッパが担い、Python では明示的な初期化が必要です(§5)。

第2回 §2・第3回 §2 の「pip パッケージは1環境につき1つ」という制約と比較すると、**EP を選ぶ軸が消え、代わりに「配布方式(framework-dependent か self-contained か)を選ぶ軸」に置き換わった**ことが分かります。責務の種類自体が変わっています。

## 3. EP の自前管理を置き換える:ExecutionProviderCatalog

第2・3回で開発者が手動で行っていた「環境を見て EP を選び、無ければ入れる」処理は、Windows ML では `ExecutionProviderCatalog` の**1〜数行**に置き換わります。中核となる API は次の2行です([Windows ML walkthrough](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/tutorial)、[Register Windows ML execution providers](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/register-execution-providers))。

```csharp
var catalog = Microsoft.Windows.AI.MachineLearning.ExecutionProviderCatalog.GetDefault();
await catalog.EnsureAndRegisterCertifiedAsync();
```

この2行が、第1回 §4 で示した「ハード検出 → 最適 EP を(Microsoft Store から)オンデマンド取得 → ORT に登録」を肩代わりします。§2 で (a)(b) が消えていたのに加え、ここで残りの責務 **(c) 配布**と **(d) 更新**も消えます。

ただし `EnsureAndRegister` には対になる API があり、用途に応じて使い分けます。

| API | 動作 | 使う場面 |
|---|---|---|
| `EnsureAndRegisterCertifiedAsync()` | 必要なら**ダウンロードしてから**登録 | 初回や、未取得 EP を確実に使いたい場合。**初回はダウンロードに時間を要する場合がある** |
| `RegisterCertifiedAsync()` | **既に端末にある EP のみ**登録 | 長時間のダウンロードを避け、起動を高速化したい場合 |

出典:[ExecutionProviderCatalog クラス](https://learn.microsoft.com/en-us/windows/windows-app-sdk/api/winrt/microsoft.windows.ai.machinelearning.executionprovidercatalog)。`RegisterCertifiedAsync` は「インストール済みの EP のみ登録し、`EnsureAndRegister` で発生しうる長時間のダウンロードを回避する」と明記されています。

特定の EP のみ必要な場合は、プロバイダを列挙して個別に準備する流れになります([Register Windows ML execution providers](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/register-execution-providers))。

```csharp
var installed = ExecutionProviderCatalog.GetDefault()
    .FindAllProviders()
    .Where(p => p.ReadyState != ExecutionProviderReadyState.NotPresent);

foreach (var provider in installed)
{
    var result = await provider.EnsureReadyAsync();          // 依存グラフに追加
    if (result.Status == ExecutionProviderReadyResultState.Success)
        provider.TryRegister();                                // ORT に登録
}
```

EP のバージョンは**端末ごと・時期ごとに変動します**(Windows Update の任意非セキュリティ プレビュー、第1回 §3 で触れた "D week" 経由で配信)。プログラムからは `provider.PackageId?.Version`(未取得なら `PackageId` が `null`)で、開発端末では PowerShell で確認できます([Check execution provider versions in Windows ML](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/versioning))。

```powershell
Get-AppxPackage MicrosoftCorporationII.WinML.*
```

第1回 §4 で「ベンダー EP は Windows ML 本体に含まれず、`ExecutionProviderCatalog` API で実行時取得される」と表で示しました。本節で扱った `ExecutionProviderCatalog` はその実 API に該当します。

## 4. EP 選択ポリシーと、登録後の ORT セッション継続

第1回 §4 で言及した「Windows ML はデバイスポリシーで『低電力なら NPU』『高性能なら GPU』を指定できる」点は、ここで実コードに対応します。公式 ResNet-50 walkthrough の骨格(C#)は次のとおりです([Windows ML walkthrough](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/tutorial))。

```csharp
// 1. ORT 環境
EnvironmentCreationOptions envOptions = new()
{
    logId = "ResnetDemo",
    logLevel = OrtLoggingLevel.ORT_LOGGING_LEVEL_ERROR
};
OrtEnv ortEnv = OrtEnv.CreateInstanceWithOptions(ref envOptions);

// 2. Windows ML に EP の取得・登録を任せる(§3)
var catalog = Microsoft.Windows.AI.MachineLearning.ExecutionProviderCatalog.GetDefault();
await catalog.EnsureAndRegisterCertifiedAsync();

// 3. EP 選択ポリシー = 第1回 §4 の「低電力なら…」の実コード
var sessionOptions = new SessionOptions();
sessionOptions.SetEpSelectionPolicy(ExecutionProviderDevicePolicy.MIN_OVERALL_POWER);

// 4. ここから先は第2回とまったく同じ ORT セッション
//    var session = new InferenceSession("model.onnx", sessionOptions);
//    session.Run(...);
```

ランタイムの動作は、モデルをロード → 端末に最適な IHV 提供 EP を選び**オンデマンドで Store から取得** → その EP で推論、という流れです。第1回 §4 の「自動デプロイ4ステップ」の実装に相当します([Windows ML walkthrough](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/tutorial)、[What is Windows ML?](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/overview))。

ここで重要な点を1つ挙げます。

> **EP 登録後の `SessionOptions` / `InferenceSession` / `Run` は、第2回と同一の API です。** C# では `Microsoft.ML.OnnxRuntime` 名前空間をそのまま使用します([Windows ML APIs](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/api-reference))。

第1回 §4 で「Windows ML は内部で ORT を使用しており、ORT を置き換えるものではない」と述べた点が、ここで具体的に確認できます。第2回の5段(変換→ロード→前処理→推論→検証)で見ると、**ロードの前に「EP の配布・選択」段が挿入されただけ**で、推論段(第2回の `Run`)は変わりません。前処理・検証・最適化が開発者の責務である点も同様です(第2回 §4/§5/§7、第1回 §4 注記)。

## 5. Python は別経路:言語による一級/二級の差

§0 で「コード主軸を C# に変える」とした根拠は、公式ドキュメントの次の記述です([Windows ML APIs](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/api-reference))。

> The ONNX runtime is designed in a way where the Python and native environments are separate. And native registration calls in the same process will not work for the Python environment.
> （ONNX ランタイムは Python とネイティブの環境が分離する設計であり、同一プロセス内のネイティブ登録呼び出しは Python 環境では機能しない。）

すなわち、Python から C# の `RegisterCertifiedAsync()` 系を呼んでも EP は登録されません。Python は専用の経路を踏みます([Windows ML APIs](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/api-reference)、[Register Windows ML execution providers](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/register-execution-providers))。

- 推論には `onnxruntime-windowsml` ホイール、Windows ML API には `winui3-Microsoft.Windows.AI.MachineLearning`(pywinrt)を使用する
- まず Windows App SDK を**明示的に初期化**してから Windows ML を呼び出す
- 登録は winml 側ではなく、**ORT 側**の `register_execution_provider_library(...)` で行う

なお、`onnxruntime-windowsml` は第2回 §2 で示した `onnxruntime` / `-gpu` / `-directml` とは別系統のホイールであり、Windows ML 経由で EP を取得する場合に使用します。**他の `onnxruntime-*` パッケージとの混在は不可**である点は、従来の3パッケージと同じ規則(1環境につき1つ)が適用されます。

```python
from winui3.microsoft.windows.applicationmodel.dynamicdependency.bootstrap import (
    InitializeOptions, initialize)
import winui3.microsoft.windows.ai.machinelearning as winml
import onnxruntime as ort

with initialize(options=InitializeOptions.ON_NO_MATCH_SHOW_UI):
    catalog = winml.ExecutionProviderCatalog.get_default()
    for provider in catalog.find_all_providers():
        provider.ensure_ready_async().get()
        if provider.library_path:
            ort.register_execution_provider_library(provider.name, provider.library_path)
```

これは第1回 §5「**情報源は新旧・状態どちらの話か必ず判定する**」の延長線にあります。第1回では「Windows ML(新)か(旧)か」「ドキュメントの URL に `new-windows-ml` が含まれるか」で判定しました。本記事の文脈では、その判定軸が**言語の一級/二級**にも及びます。さらに第3回 §2 で示した「GenAI は **Preview**」という状態は、Phi Silica 周りでも Windows App SDK の **preview 版**として現れます(§6/§7)。新旧・preview・言語の一級性は、まとめて判定する必要があります。

## 6. もう一つの入口:Phi Silica(自前モデルが不要)

ここまでは「自前 ONNX を Windows ML で動かす」入口でした。第1回 §7 で示したように、別系統に「**自前モデルすら不要な既製の入口 = Windows AI APIs**」があります。その代表が **Phi Silica** です。

Phi Silica は **NPU 最適化された Windows 同梱のローカル SLM** で、`LanguageModel` API から呼び出せます。第3回で実装した生成ループ(`og.Model` → `append_tokens` → `while not is_done()`)は、ここでは数行に圧縮されます([Get started with Phi Silica](https://learn.microsoft.com/en-us/windows/ai/apis/phi-silica)、[Tutorial: Phi Silica and WinUI 3](https://learn.microsoft.com/en-us/windows/ai/apis/phi-silica-winui-tutorial))。

```csharp
using Microsoft.Windows.AI;
using Microsoft.Windows.AI.Text;

if (LanguageModel.GetReadyState() == AIFeatureReadyState.NotReady)
    await LanguageModel.EnsureReadyAsync();           // 必要なら端末へ配置

using LanguageModel languageModel = await LanguageModel.CreateAsync();

var result = await languageModel.GenerateResponseAsync("Provide the molecular formula for glucose.");
Console.WriteLine(result.Text);
```

`LanguageModelOptions` / `ContentFilterOptions` / `SeverityLevel` で安全フィルタの強度なども指定できます。さらにスキル指向の設計として、`LanguageModel` インスタンスを `TextSummarizer` などの用途別オブジェクトに渡す形式もあります(名前空間 `microsoft.windows.ai` / `.text` / `.imaging`)([Get started with Phi Silica](https://learn.microsoft.com/en-us/windows/ai/apis/phi-silica))。

第3回(GenAI 直接利用)と本節(Phi Silica)を比較すると、開発者が抱える作業の差は次のとおりです。

| | 第3回(GenAI を直接利用) | 第4回(Phi Silica) |
|---|---|---|
| モデル取得 | `huggingface-cli download` + 量子化版選択 | 不要(`EnsureReadyAsync` が配置) |
| ロード | `og.Model(path)` | `LanguageModel.CreateAsync()` |
| 生成 | 生成ループを自分で実装 | `GenerateResponseAsync()` 1回 |
| 量子化 | `int4-awq-block-128` を自分で選択 | 不可視(Microsoft 側で実施) |

:::message
第3回 §7 では「speculative decoding は ONNX Runtime GenAI のロードマップ段階」と述べました。一方 Phi Silica は、**小さなドラフトモデルが複数トークン列を提案し本モデルが並列検証する speculative decoding を採用した製品**として既に稼働しています([Get started with Phi Silica](https://learn.microsoft.com/en-us/windows/ai/apis/phi-silica))。同じ技術でも、ライブラリ単体の公開機能としてはロードマップ段階、Microsoft 提供の製品としては実装済みという状態の差が生じる点に注意が必要です。
:::

自由度(モデル選択・量子化・生成ループの制御)を引き換えに、第3回で発生していた作業の大半が不要になります。代償については次節で扱う制約です。

## 7. Windows ML / Phi Silica の境界と制約

第2回 §7「ORT は最適化しない」、第3回 §7「GenAI は品質・メモリを保証しない」を、配布層の観点から整理します。

**Windows ML が肩代わりしない範囲**(第1回 §4 注記の再確認):

- モデル最適化・量子化(第1〜3回で一貫。第3回 §4 の主題)
- 学習時前処理の再現(第2回 §4)
- 推論ロジックそのもの(EP 登録後は ORT=第2回と同じ責務)

**Phi Silica は強力だが、`LanguageModel` の数行の裏に多数の前提条件があります**([Tutorial: Phi Silica and WinUI 3](https://learn.microsoft.com/en-us/windows/ai/apis/phi-silica-winui-tutorial)、[Get started with Phi Silica](https://learn.microsoft.com/en-us/windows/ai/apis/phi-silica)、[Choose your Windows AI solution](https://learn.microsoft.com/en-us/windows/ai/windows-ai-comparison))。

- **Copilot+ PC + NPU 必須**(第1回 §4 で示した「Copilot+ PC は Windows AI APIs に必須」が具体的に効く)
- Windows 11 build 26100 以降(25H2)、Developer Mode、Visual Studio 2022
- **LAF(Limited Access Feature)アンロックトークン必須**。`TryUnlockFeature` で解除する。トークンが無い場合、API 呼び出しは access denied で失敗する
- Windows App SDK **2.0.0-preview1** など Preview が絡む(第3回 §2 の Preview 状態と同様)
- **中国では利用不可**

なお、公式 Q&A には「サンプルが古い」「ARM64 で Debug ビルドが動かない」「`Not declared by app` が出る」といった報告が見られます。**Preview + LAF + 特定ビルドを前提とする機能は、現時点で実装周辺の安定度が低い**点には留意が必要です。

なお、ここで列挙した制約は Phi Silica(=Windows AI APIs)固有のものであり、**Windows ML 単体には Copilot+ PC も LAF も不要**です(Windows ML は Windows 10/11 の広いハードで動作します。第1回 §4 参照)。

**Phi Silica が向かないケース**:

- Copilot+ PC を前提にできない配布対象(一般 PC 向けに広く配布する場合)
- LAF/Preview を本番要件に組み込めない(エンタープライズの厳格な依存管理など)
- 自前モデル要件がある場合(その用途は Windows ML の領分)

第3回 §7 で述べた「ランドマークが見えていても、そこへ至る道が全部開通しているとは限らない」という構図は、本記事でも同様に効きます。Phi Silica の場合、ランドマークが NPU / Phi Silica、道が Copilot+ PC + LAF + Preview + 対応ビルドに相当します。`LanguageModel.CreateAsync()` がコンパイルできることと、ターゲット端末で実際に動作することは別問題であるため、次節で扱うフォールバック設計が必要になります。

## 8. 4つの入口の判断軸とフォールバック設計

第1回 §7 で示した「4つの入口」を、実装可能なフォールバック設計に落とし込みます。基本構成は3段です([Choose your Windows AI solution](https://learn.microsoft.com/en-us/windows/ai/windows-ai-comparison)、[Use local AI with Microsoft Foundry on Windows](https://learn.microsoft.com/en-us/windows/ai/overview))。

```
① Windows AI APIs(Phi Silica)= 最速・最小コード。ただし Copilot+ PC 限定
        │ GetReadyState() が NotSupportedOnCurrentSystem
        ▼
② Foundry Local = 任意の Windows ハード。トークン不要。OpenAI 互換 API
        │ それも不可
        ▼
③ Azure OpenAI = クラウドへ退避
```

骨格(公式 `windows-ai-comparison` の compilable 例に準拠)はこうです。

```csharp
var readyState = LanguageModel.GetReadyState();
if (readyState == AIFeatureReadyState.EnsureNeeded)
{
    var deploy = await LanguageModel.EnsureReadyAsync();
    readyState = deploy.Status == PackageDeploymentStatus.CompletedSuccess
        ? LanguageModel.GetReadyState()
        : AIFeatureReadyState.NotSupportedOnCurrentSystem;
}

if (readyState != AIFeatureReadyState.NotSupportedOnCurrentSystem)
    using var lm = await LanguageModel.CreateAsync();   // ① Phi Silica
else
    /* ② Foundry Local へ。さらにダメなら ③ Azure */ ;
```

**Foundry Local の位置づけ**(本記事では概略のみ)。Windows AI APIs より細かい制御を行いたい場合、または Copilot+ PC でない端末も対象にしたい場合の選択肢です。**特別な許可やアンロックトークンは不要**で、OpenAI 互換 API で呼び出せます。Windows 向けは `Microsoft.AI.Foundry.Local.WinML`(Windows ML ランタイムと統合し広いハード加速に対応)、クロスプラットフォームは `Microsoft.AI.Foundry.Local` です。これら3つ(Windows AI APIs / Foundry Local / Windows ML)をまとめた呼称が `Microsoft Foundry on Windows` です([Get started with Foundry Local](https://learn.microsoft.com/en-us/windows/ai/foundry-local/get-started)、[Use local AI with Microsoft Foundry on Windows](https://learn.microsoft.com/en-us/windows/ai/overview))。

:::message alert
第3回 §1/§8 で予告した「ONNX Runtime GenAI は Foundry Local・Windows ML の内部でも使われる」点は、Foundry Local 公式トラブルシュートの記述で確認できます——プログラム終了後に出力される無害な警告について、原文では「**the underlying ONNX Runtime GenAI (OGA) library**(土台の ONNX Runtime GenAI ライブラリ)」由来であると明記されています([Get started with Foundry Local](https://learn.microsoft.com/en-us/windows/ai/foundry-local/get-started))。第3回で直接利用した GenAI は、Windows AI APIs と Foundry Local の内部実装としても共有されている、というのが現状の構図です。
:::

**次回への接続**。ここまでで4つの入口の API が一通り示されました——自前 ONNX なら Windows ML、既製なら Phi Silica、それらが利用できない場合は Foundry Local / Azure。第5回(予定)では、第3回 §5/§7 で「数値一致から品質評価へ移行する」として保留した**検証**と、本記事の**配布・フォールバック**を、実アプリ統合の形にまとめる予定です。

| 回 | 内容 | 本記事との関係 |
|---|---|---|
| 第1回 | 全体地図 | (前提)§4/§5/§7 を本記事が拡大 |
| 第2回 | ORT で通常 ML | 登録後の `InferenceSession` は本記事でも不変 |
| 第3回 | SLM/GenAI | GenAI が Windows ML/Foundry の内部実装として本記事で位置づけ |
| **第4回(本記事)** | Windows ML / Phi Silica / 4入口 | EP 自前管理を Windows ML が肩代わり + 既製の入口 |
| 第5回(予定) | 実用アプリ統合 | §7 の品質評価 + 本記事の配布/フォールバックを統合 |

## 9. まとめ

- 第2・3回で開発者が抱えていた4責務のうち、(a) 選択・(b) 混在禁止は NuGet 化(`Microsoft.WindowsAppSDK.ML` 等)で、(c) 配布・(d) 更新は **`ExecutionProviderCatalog.GetDefault()` + `EnsureAndRegisterCertifiedAsync()`** で消える。長時間のダウンロードを避けたい場合は `RegisterCertifiedAsync()`(既存のみ登録)を使う
- NuGet は `Microsoft.WindowsAppSDK.ML`(framework-dependent では `.Runtime` も追加)。配布方式は framework-dependent(推奨)/ self-contained(約41MB)。**EP を選ぶ軸が、配布方式を選ぶ軸に変わる**
- 第1回 §4 で言及したデバイスポリシーは `SetEpSelectionPolicy(...)` に対応。**EP 登録後は第2回と同じ ORT (`Microsoft.ML.OnnxRuntime`) をそのまま使用する**。Windows ML は ORT を置き換えるものではない
- **Python は別経路の二級扱い**(`onnxruntime-windowsml`、ネイティブ登録は機能しない)。第1回 §5 の「新旧・状態を判定」が言語選択にも適用される
- 自前モデルが不要な入口が **Phi Silica**(`LanguageModel` 数行で利用可。speculative decoding は実装済み)。ただし **Copilot+ PC 必須・LAF・Preview・中国不可**
- 入口は4つ。**Windows AI APIs → Foundry Local → Azure** の3段フォールバック構成が基本。Foundry Local の内部実装は **OGA = ONNX Runtime GenAI**。Windows ML は配布層を肩代わりするが**最適化は行わない**
- 品質評価と実アプリ統合・配布運用は第5回で扱う

:::message
本記事のコード(`ExecutionProviderCatalog` 系、`SetEpSelectionPolicy`、`LanguageModel` 系、フォールバック例)は、公式チュートリアル・API リファレンス・compilable サンプルに基づく**最小骨格**です。Windows App SDK は **2.0 系で preview を含み**、API シグネチャや列挙子はバージョンによって変更されうるため、実装時は使用バージョンの公式 API ドキュメントで署名を確認してください。
:::

4つの入口の使い分けを押さえておけば、第5回でアプリ統合に進む際にも「現在どの入口を、どの層で使っているか」を見失わずに済みます。次回は、本記事の配布・フォールバックと第3回の品質評価を、ひとつの実アプリに統合する予定です。

---

### 参考(主要な一次情報)

- [What is Windows ML? — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/overview)
- [Windows ML walkthrough(ResNet-50)— Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/tutorial)
- [Register Windows ML execution providers — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/register-execution-providers)
- [Windows ML APIs — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/api-reference)
- [ExecutionProviderCatalog Class — Windows App SDK](https://learn.microsoft.com/en-us/windows/windows-app-sdk/api/winrt/microsoft.windows.ai.machinelearning.executionprovidercatalog)
- [Check execution provider versions in Windows ML — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/versioning)
- [Install and deploy Windows ML — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/distributing-your-app)
- [Get started with Phi Silica — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/apis/phi-silica)
- [Tutorial: Build a chat app with Phi Silica and WinUI 3 — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/apis/phi-silica-winui-tutorial)
- [Choose your Windows AI solution — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/windows-ai-comparison)
- [Get started with Foundry Local — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/foundry-local/get-started)
- [Use local AI with Microsoft Foundry on Windows — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/overview)
- [Copilot+ PCs developer guide — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/npu-devices/)
- 連載第1回:WindowsローカルAIの技術地図 2026(同連載・別記事)
- 連載第2回:ONNX Runtime で“ふつうのMLモデル”を動かす最小実装(同連載・別記事)
- 連載第3回:ONNX Runtime GenAI で SLM をローカル実行する(同連載・別記事)
