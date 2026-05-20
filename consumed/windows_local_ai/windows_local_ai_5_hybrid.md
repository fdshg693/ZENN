---
title: "WindowsローカルAI実践 第5回:タスクごとに入口を選ぶ ─ 4入口を束ねるハイブリッド設計と Foundry Local/Azure 同顔の活かし方"
emoji: "🧭"
type: "tech"
topics: ["windows", "winml", "foundrylocal", "onnxruntime", "ai"]
published: false
---

## この記事について

連載「WindowsローカルAI実践入門」の**第5回(最終回)**です。第1回で7語の技術地図を組み立て、第2回で ONNX Runtime の幹を通常 ML で歩き、第3回で SLM を載せ、第4回で Windows ML に EP 自前管理を渡し、Phi Silica の最小コードまで届きました。

ここまでで「4つの入口」(Windows AI APIs / Foundry Local / Windows ML / ORT 直)は単体としては揃いました。**ところが、実アプリに統合する段になると、入口を1つに固定できない問いが残ります。** 同じアプリに OCR・要約・独自分類・音声書き起こしが同居していたら、それらを全部 Phi Silica にも、全部 Windows ML にも寄せられません。

本記事は、この「**入口を1つに固定できない**」現実に正面から答えます。**主軸はタスクルーティング**:タスク種別ごとに4入口(+クラウド)を割り当てる設計です。コードは数行のスニペットに留め、**判定表とチェックリスト**を中心に据えます。

:::message
本記事は連載第5回(最終回)です。第1〜4回で扱った「層」「EP」「Phi Silica」「Windows ML の自動配布」は説明済みとして進めます。
:::

対象読者は、第1〜4回で個別の入口を理解し、**いま実アプリに組み込む段で複数タスクの捌き方に詰まっている**開発者です。コードは C# / Python の最小スニペットを示し、設計判断を中心にします。

---

## 0. はじめに:統合段階で残る問い

連載のここまでで、4つの入口は単体としては揃いました。

| 入口 | 担当 | 出てきた回 |
|---|---|---|
| Windows AI APIs(Phi Silica など) | 既製の AI 機能(Copilot+ PC 前提) | 第1回 §8 / 第4回 §4 |
| Foundry Local | 既製 OSS LLM・音声(OpenAI 互換 API) | 第1回 §8 / 第4回 §8 |
| Windows ML | 自前 ONNX を共有 ORT + 自動 EP 配布で | 第3回 §2 / 第4回 全体 |
| ORT 直 | EP も配布も自分で握る | 第2回・第3回 |

統合段階の問いはここからです。

> 同じアプリに、OCR・要約・独自分類・音声書き起こし・長文要約が同居していたら、それぞれをどの入口に流すか。全部を1つの入口に寄せられるのか。

公式の答えは「**寄せられない、組み合わせろ**」です。「[Microsoft Foundry on Windows overview](https://learn.microsoft.com/en-us/windows/ai/overview)」の本文は3段優先順位を提示したうえで、こう書いています。

> Your app can also use a combination of all three of these technologies.

ところが**組み合わせ方の指針は3つのページに散在**しています。`/windows/ai/overview` は3段優先順位、`/windows/ai/cloud-ai` は local vs cloud のトレードオフ、`/azure/architecture/ai-ml/guide/choose-ai-model` は model routing strategy。本記事はこれらを**タスクルーティング**という1つの軸に束ねます。

本記事の構成は3部です。**第I部(§1〜§3)で判定軸**(タスク種別・3段優先順位・ローカル/クラウド)を組み、**第II部(§4〜§5)で実装上の前提**(Foundry Local/Azure の "同じ顔"、端末能力検出)を確定し、**第III部(§6〜§8)で配布・フォールバック設計と最終判定表**に畳みます。

---

# 第I部:判定軸を組む

## 1. 第1回の地図に「タスク」軸を足す

第1回は7語を層として並べました。実アプリ統合では、その層に**タスク種別**という横軸を1本足します。

| タスク種別 | 候補入口(後述の3段優先で並べる) | 根拠 |
|---|---|---|
| OCR | Windows AI APIs(`TextRecognizer`)/ なければ Foundry Local の VLM 系 | [overview](https://learn.microsoft.com/en-us/windows/ai/overview) のタスク表 |
| 画像説明・前景抽出・解像度向上 | Windows AI APIs(Copilot+ PC 必須) | 同上 |
| 短文 LLM(要約・チャット・リライト) | Phi Silica(Copilot+ PC)/ Foundry Local / Azure OpenAI | 同上 + [windows-ai-comparison](https://learn.microsoft.com/en-us/windows/ai/windows-ai-comparison) |
| 音声書き起こし(STT) | Foundry Local(Whisper)/ Windows SDK の `SpeechRecognizer` | 同上 |
| 独自分類・回帰(自前 ONNX) | Windows ML / ORT 直 | 第2〜4回 |
| 長文要約・高度推論 | Foundry Local の大きめモデル / Azure OpenAI | [cloud-ai](https://learn.microsoft.com/en-us/windows/ai/cloud-ai) |
| セマンティック検索 | Windows AI APIs(`App Content Search`, Copilot+ PC) | [overview](https://learn.microsoft.com/en-us/windows/ai/overview) のタスク表 |

ここに第1回の「層 × タスク」の構図ができます。**入口は層の話**、タスクは横軸の話で、両者は直交します。だから「全部を1つの入口に」はそもそも層の上の異なる位置を1点に潰す要求であり、無理が出ます。

## 2. 公式の3段優先順位を「ルーティング判断」として読み直す

`/windows/ai/overview` の3段優先順位は、原文ではこう書かれています([overview](https://learn.microsoft.com/en-us/windows/ai/overview))。

1. Check if the built-in Windows AI APIs cover your scenario and you're targeting Copilot+ PCs.
2. If Windows AI APIs don't have what you need, or you need to support Windows 10 and later, consider Foundry Local for LLM or voice-to-text scenarios.
3. If you need custom models, ..., Windows ML gives you the flexibility ...

これは「アプリ全体の入口選び」ではなく、**タスクごとに上から順に当てはまるかを見て、最初に当てはまった入口を採る**というルーティング判断手順として読めます。手順を判定フローに直すとこうです。

```
タスク t について:
   ├─ Windows AI APIs に当該タスクの既製 API があるか?
   │    └ Yes → Copilot+ PC でだけ動かす前提で OK か?
   │           ├ Yes → Windows AI APIs を採用
   │           └ No  → 次へ(Windows 10 含めたい等)
   │
   ├─ LLM / STT で、既製モデルで足りるか?
   │    └ Yes → Foundry Local を採用(任意の Windows ハードウェア)
   │
   └─ 自前モデル / 既製にない要件か?
        └ Yes → Windows ML を採用(任意の Windows ハードウェア)
            └ EP 管理も自前で握りたい例外時のみ → ORT 直
```

**ポイントは、これを「アプリにつき1回」ではなく「タスクにつき1回」回すことです。** 同じアプリに OCR と独自分類と長文要約があるなら、3回回って3つの異なる入口が選ばれて構いません。

> **「Windows ML を中心に据える」の意味**:連載全体で Windows ML を中心と呼んできましたが、これは「自前 ONNX を扱うタスクの中心」という意味です。アプリ全体の入口を Windows ML に寄せるという意味ではありません。タスクごとに3段を回した結果、自前 ONNX タスクが多ければ Windows ML 中心になります。OCR と既製 LLM だけのアプリなら、Windows ML はそもそも出てきません。

## 3. ローカル/クラウド軸を重ねる:判定の二段目

3段優先で「Foundry Local」が選ばれたタスクには、**さらに二段目の問い**があります。同じ OpenAI 互換 API の中で、ローカルで動かすか、クラウド(Azure OpenAI / Foundry)を呼ぶか、です。

`/windows/ai/cloud-ai` のトレードオフ表は、この二段目の判断材料を一覧化しています([cloud-ai](https://learn.microsoft.com/en-us/windows/ai/cloud-ai))。

| 軸 | ローカル寄りに振る理由 | クラウド寄りに振る理由 |
|---|---|---|
| 遅延 | 端末で完結、ネットワーク往復なし | (劣る) |
| プライバシー | データが端末を出ない | (劣る、契約・地理要件で許容なら可) |
| 通信前提 | オフラインで動く | 常時接続が前提 |
| コスト | 端末リソースは固定費 | 従量課金で変動 |
| モデル鮮度・性能 | (劣る、端末で動くサイズに限定) | フロンティアモデルが使える |
| カスタマイズ | (限定的) | 多様な選択肢 |

`/windows/ai/windows-ai-comparison` の "Other" 節は、両者の関係を一文で要約しています([windows-ai-comparison](https://learn.microsoft.com/en-us/windows/ai/windows-ai-comparison))。

> Microsoft Foundry — Cloud-hosted frontier models (GPT-4o, DALL-E, etc.) via REST API. **Combine with Foundry Local for on-device/cloud fallback.**

公式が「**combine と fallback**」と書いている以上、ローカル/クラウドはどちらか一方ではなく、組み合わせるのが既定です。ただし本記事の射程は**ローカル側のハイブリッド設計**で、クラウド側の構築(認可・課金・デプロイ・監視)は扱いません。**ローカル側からクラウドの "同じ顔" をどう活かすか**だけを次節で扱います。

---

# 第II部:実装上の前提

## 4. Foundry Local と Azure OpenAI の "同じ顔" を活かす

ローカル/クラウドの切り替えコストを大きく左右するのは、**コードパスが2系統に分かれるかどうか**です。LLM/SLM テキスト系に関しては、Microsoft は両者を **OpenAI SDK サーフェス**に集約しており、コードパスは事実上1系統で済みます。

### 4.1 Foundry Local 側:OpenAI 互換 REST がアプリ内に立つ

[Foundry Local architecture overview](https://learn.microsoft.com/en-us/azure/foundry-local/concepts/foundry-local-architecture) の "Optional REST API" 節はこう書いています。

> For scenarios that require HTTP-based communication, the Foundry Local SDK can start an optional OpenAI-compatible REST endpoint within your application process.

つまり Foundry Local SDK は、アプリ内に **OpenAI 互換 REST エンドポイント**を立てられます。HTTP 通信が要らないなら SDK ネイティブ呼出で済みますが、要るなら同じプロセス内で REST が話せます。

さらに同ページの "Hardware abstraction" 節:

> Foundry Local abstracts the underlying hardware so your application code doesn't need to detect devices or select execution providers.

ハードウェア抽象化までやってくれます。Windows 上では WinML がプラグイン取得・登録・ドライバ互換交渉を肩代わりし、Linux/macOS では SDK が EP プラグインを同梱します。**アプリ側は EP を意識しません**。

### 4.2 Azure OpenAI 側:同じ OpenAI SDK で叩ける

[Azure Foundry SDKs and Endpoints](https://learn.microsoft.com/en-us/azure/foundry/how-to/develop/sdk-overview) は、OpenAI SDK が Azure 側の Foundry / OpenAI モデルにそのまま使えると書いています。

> OpenAI SDK ... Latest OpenAI SDK models and features with the full OpenAI API surface, including embeddings.

つまり「**Foundry Local も Azure OpenAI も OpenAI SDK で叩ける**」が成立します。

### 4.3 パッケージ構成:Windows 用は Windows ML 統合版を採る

[Foundry Local SDK Reference](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-sdk-current) のインストール節は、Windows 向けと Cross-Platform でパッケージを使い分けます。

| ターゲット | C# | Python | JavaScript |
|---|---|---|---|
| Windows(推奨) | `Microsoft.AI.Foundry.Local.WinML` + `OpenAI` | `foundry-local-sdk-winml` + `openai` | `foundry-local-sdk-winml` + `openai` |
| Cross-Platform | `Microsoft.AI.Foundry.Local` + `OpenAI` | `foundry-local-sdk` + `openai` | `foundry-local-sdk` + `openai` |

公式の説明はこうです。

> The Windows package integrates with the Windows ML runtime — it provides the same API surface area with a wider breadth of hardware acceleration.

**API サーフェスは同じで、ハードウェア加速の幅が広がる**版が Windows 用です。Windows のみのアプリでも、ハイブリッド設計でクロスプラットフォーム要件がない限り、Windows 用パッケージを採るのが妥当です。

### 4.4 コードパス:エンドポイント差し替えで切替できる

上記から、LLM テキスト系の local/cloud 切替は次のように書けます(Python の最小例)。

```python
from openai import OpenAI

# ローカル(Foundry Local が立てた OpenAI 互換 REST)
local_client = OpenAI(
    base_url="http://localhost:XXXXX/v1",  # Foundry Local のローカル endpoint
    api_key="not-needed",
)

# クラウド(Azure OpenAI / Foundry)
cloud_client = OpenAI(
    base_url="https://<your-resource>/openai/v1",
    api_key="<key-or-entra-token>",
)

def summarize(text: str, use_cloud: bool) -> str:
    client = cloud_client if use_cloud else local_client
    resp = client.chat.completions.create(
        model="<model-id>",
        messages=[{"role": "user", "content": f"Summarize:\n{text}"}],
    )
    return resp.choices[0].message.content
```

`use_cloud` の切替条件は §6 のフォールバック設計で扱います。**重要なのは、`summarize` 関数の本体が1つしかないことです。** 2系統のコードパスを持たずに済みます。

### 4.5 "同じ顔" が成立する範囲

ただし「同じ顔」は **OpenAI 互換 API の範囲のみ**で成立します。図にすると次のようになります。

```
   ┌──────────────────────────────────────────────────┐
   │           OpenAI SDK が叩ける範囲(= 同顔可能)        │
   │   ┌──────────────────────────┐                  │
   │   │  Foundry Local           │   Azure OpenAI   │
   │   │  (OpenAI 互換 REST)      │  Foundry         │
   │   └──────────────────────────┘                  │
   └──────────────────────────────────────────────────┘

   ┌──────────────────────────────────────────────────┐
   │           同顔不能ゾーン(別 API で実装)               │
   │                                                  │
   │   Windows AI APIs   |   Windows ML 自前 ONNX     │
   │   (`LanguageModel`  |   (`InferenceSession` /    │
   │    `TextRecognizer`)│    `LearningModel`)        │
   └──────────────────────────────────────────────────┘
```

つまり同じアプリ内に、次の2系統は最低限残ります。

- **OpenAI 互換ゾーン**:Foundry Local ←→ Azure OpenAI の切替で済む(1関数)
- **WinRT / Windows ML ゾーン**:Windows AI APIs と自前 ONNX は別 API で書く

ハイブリッド設計上は、**LLM テキスト系をなるべく OpenAI 互換ゾーンに寄せ**、OCR・画像系・自前 ONNX は別レーンとして抱える、という整理になります。

## 5. 端末能力検出:`ExecutionProviderCatalog` でルーティング条件を取る

§2 の3段優先順位は静的な判定でしたが、実アプリでは**動的な端末能力**を見る必要もあります。Copilot+ PC でなければ Phi Silica は使えませんし、NPU 系 EP が利用不能なら自前 ONNX を CPU EP に流すしかありません。

Microsoft はこれを**プログラム的に取れる**API を用意しています。

### 5.1 EP 一覧と `ReadyState`

[Install Windows ML execution providers](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/initialize-execution-providers) は、`ExecutionProviderCatalog.FindAllProviders()` で互換 EP の全列挙と `ReadyState` 取得ができると書いています。

```csharp
var catalog = ExecutionProviderCatalog.GetDefault();
foreach (var provider in catalog.FindAllProviders())
{
    Console.WriteLine($"{provider.Name}: {provider.ReadyState}");
}
```

`ReadyState` は「インストール済み」「未インストール(DL 必要)」などを返します。これを起動時に1回取って、ルーティング条件として保持します。

### 5.2 インストール済 EP のバージョン取得

[Check execution provider versions](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/versioning) によれば、`PackageId.Version` が `null` なら未インストール、非 `null` ならバージョンが取れます。

```csharp
if (provider.PackageId != null) {
    var v = provider.PackageId.Version;
    Debug.WriteLine($"Version: {v.Major}.{v.Minor}.{v.Build}.{v.Revision}");
} else {
    Debug.WriteLine("Version: Not installed");
}
```

各 EP には最小ドライバ要件があり(第1回 §7 で言及)、想定下限を割っていればフォールバック対象になります。

### 5.3 Copilot+ PC 判定の実用代替

Microsoft は「Copilot+ PC かどうか」を直接判定する単一 API を強調していませんが、[accelerate-ai-models](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/accelerate-ai-models) の Silicon-to-EP マッピングから、**NPU 系 EP(QNN / OpenVINO / VitisAI)のいずれかが `ReadyState` で利用可能か**を実用代替として使えます。

```csharp
bool hasNpuEp = catalog.FindAllProviders()
    .Where(p => p.Name == "QNNExecutionProvider"
             || p.Name == "OpenVINOExecutionProvider"
             || p.Name == "VitisAIExecutionProvider")
    .Any(p => p.ReadyState == ExecutionProviderReadyState.Present);
```

ただし Phi Silica など Windows AI APIs 側の機能は、各 API が独自に「使えるか」を返します(§6.1)。EP 検出は自前 ONNX 経路の能力判定で、Windows AI APIs の能力判定は API 側で行うのが筋です。

### 5.4 ORT 側のデバイスポリシー指定

EP を 1個ずつ手で指定する代わりに、**ORT 側の "デバイスポリシー" でゴール指向に書ける**ようになっています。[Select execution providers](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/select-execution-providers) の例から(Python):

```python
import onnxruntime as ort
options = ort.SessionOptions()
options.set_provider_selection_policy(
    ort.OrtExecutionProviderDevicePolicy.MAX_EFFICIENCY
)
```

ポリシー値は `MAX_PERFORMANCE` / `MAX_EFFICIENCY` / `PREFER_NPU` / `MIN_OVERALL_POWER` などがあります。これらは「**NPU があれば NPU、なければ CPU フォールバック**」のような**自動選択**を ORT に委ねる API です。

**含意**:アプリで EP を明示指定しなくても、ポリシーを宣言するだけで端末能力に応じた自動切替が成立します。タスクルーティングと組み合わせるなら、「自前 ONNX タスクで、低電力指向 → `MAX_EFFICIENCY`、性能指向 → `MAX_PERFORMANCE`」のようにタスクごとにポリシーを使い分けられます。

---

# 第III部:配布・フォールバック設計と最終判定表

## 6. フォールバック設計:Microsoft 公式の参照チェーン

ハイブリッド設計の核は、**ターゲット入口が使えなかったときに何に落とすか**です。Microsoft はこれを「開発者の責務」と明記しています([accelerate-ai-models](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/accelerate-ai-models))。

> Windows ML handles execution provider distribution, not model optimization. **You're still responsible for optimizing your models for different hardware.**

ただし**フォールバックチェーンの参照コード**だけは、公式が `/windows/ai/windows-ai-comparison` に置いています。これがそのまま最小実装の雛形になります。

### 6.1 公式フォールバックチェーン(LLM テキスト系)

[windows-ai-comparison](https://learn.microsoft.com/en-us/windows/ai/windows-ai-comparison) の参照コードはこの順で並んでいます(C#、要約引用)。

```csharp
// 1. Try Windows AI APIs (fastest — Copilot+ only)
var readyState = LanguageModel.GetReadyState();

if (readyState == AIFeatureReadyState.EnsureNeeded) {
    var deploymentResult = await LanguageModel.EnsureReadyAsync();
    if (deploymentResult.Status == PackageDeploymentStatus.CompletedSuccess) {
        readyState = LanguageModel.GetReadyState();
    } else {
        // インストール失敗時はサポート外として下に落とす
        readyState = AIFeatureReadyState.NotSupportedOnCurrentSystem;
    }
}

if (readyState != AIFeatureReadyState.NotSupportedOnCurrentSystem) {
    // Phi Silica via Windows AI APIs を使う
    using LanguageModel languageModel = await LanguageModel.CreateAsync();
    // ...
}
// 2. Fall back to Foundry Local (any hardware)
else if (/* Foundry Local が利用可能 */) {
    // ...
}
// 3. Fall back to Azure OpenAI
```

3段の意味は次のとおりです。

1. **Phi Silica を試す**:`GetReadyState` で能力検出 → `EnsureNeeded` ならインストール、それでも `NotSupportedOnCurrentSystem` なら(= Copilot+ PC でなければ)下へ
2. **Foundry Local に落とす**:任意の Windows ハードウェアで動く
3. **Azure OpenAI に落とす**:OpenAI 互換 SDK の同顔切替で、1関数のまま

**重要な観察**:このフォールバックチェーンは、§2 の3段優先順位と**同じ順序**です。優先順位とフォールバック順は同一で、片方は「採用順序」、片方は「失敗時の代替順序」として読めるよう設計されています。

### 6.2 Phi Silica 固有の制約(Windows AI APIs の追加注意)

[Phi Silica チュートリアル](https://learn.microsoft.com/en-us/windows/ai/apis/phi-silica-winui-tutorial)から、フォールバック設計に効く制約を3点拾います。

- **Limited Access Feature**:Phi Silica APIs は LAF。アンロックトークンを取得する必要があります(`LimitedAccessFeatures` クラス)
- **中国では利用不可**:`Phi Silica features are not available in China.`
- **Windows 11 build 26100(25H2)以降**

つまり「Copilot+ PC を持っていても Phi Silica が使えない地域・ビルドがある」状態が存在します。フォールバック1段目で `NotSupportedOnCurrentSystem` が返ってきうるケースは、**NPU 非搭載だけではない**ということです。設計上は「`GetReadyState` の返り値を信用してそのまま落とす」だけで十分で、原因の特定はテレメトリ側に逃がす方が現実的です。

### 6.3 Windows ML 起動シーケンス(自前 ONNX 経路)

LLM テキスト系のフォールバックが §6.1 だとすると、**自前 ONNX 経路の起動時シーケンス**はそれと並行に必要です。第4回 §3 で導入した `RegisterCertifiedAsync` と `EnsureAndRegisterCertifiedAsync` の差は、ここで効きます([initialize-execution-providers](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/initialize-execution-providers))。

| API | 何をするか | 使いどころ |
|---|---|---|
| `RegisterCertifiedAsync()` | **既にインストール済みの EP のみ**を登録(DL なし) | アプリ起動時の高速パス・オフライン許容 |
| `EnsureAndRegisterCertifiedAsync()` | 必要なら DL してから登録(時間がかかる) | ユーザー同意後の初期セットアップ |

推奨シーケンスは2段です。

```
[起動時]
  RegisterCertifiedAsync()
   └ 既存 EP のみで動くなら即推論開始

[ユーザー同意 or 初回セットアップ]
  EnsureAndRegisterCertifiedAsync()
   └ ターゲット EP を DL(進捗表示、長時間警告)

[なお取れない場合のフォールバック]
  ① 同梱 EP に落とす(DirectML / CPU)
  ② Foundry Local 経由の代替モデルへ
  ③ クラウド同顔切替(§4)
```

### 6.4 配布方式と起動シーケンスの組み合わせ

第4回 §2 で導入した framework-dependent / self-contained は、起動シーケンスと組み合わせると次の表になります。

| 配布方式 | 起動時に何が確定しているか | 推奨起動シーケンス |
|---|---|---|
| framework-dependent | システム共有の ORT/同梱 EP は存在。ベンダー EP は端末次第 | `RegisterCertifiedAsync` で軽く起動 → 必要時のみ `EnsureAndRegisterCertifiedAsync` |
| self-contained | 同梱 EP(CPU / DirectML)は確実に動く | DirectML を初期目標に置き、ベンダー EP の DL は任意 |

self-contained でも `DirectML.dll` 同梱なので「GPU 推論が常に成立する」と思いがちですが、**DirectML は保守モード**(第1回 §5)で、ベンダー EP の方が高性能なケースが多い点は変わりません。self-contained は「最低保証ライン」を上げる選択であって、「最善を取る」選択ではありません。

## 7. 品質評価の位置づけ(短く)

第3回 §5/§7 で「数値一致から品質評価へ」を保留しました。ハイブリッド設計上、これは1点だけ位置づけが必要です。

**タスクルーティングは「同一品質基準を満たす入口を選ぶ」設計ではありません。** タスクごとに許容品質の幅は異なります。

- OCR は正解判定が厳密に取れる(文字一致率)
- 要約・チャットは確率的で、評価は LLM-as-judge / golden set / 主観評価のいずれか
- 独自分類は通常 ML のメトリクス(精度・再現率)で取れる
- 長文要約・推論は人手評価を含む

つまりフォールバックチェーンを Phi Silica → Foundry Local → Azure OpenAI と落とした場合、**3者は同じ品質ではない**前提で設計する必要があります。Azure 側がフロンティアモデル(GPT-4 系)で品質が高く、ローカル側が小型モデルで品質が低い、という非対称が常態です。

評価設計そのもの(LLM-as-judge の作り方、golden set の維持、メトリクスの取り方)は本記事の射程外ですが、**ハイブリッド設計上は「タスクごとに評価基準を別に持ち、フォールバック前後で品質要件を緩めうるか」を最初に決める**のが筋です。これを決めずに自動フォールバックを書くと、「ローカルで失敗してクラウドに落ちた瞬間にコスト爆発、または逆に劣化を検知できない」事故になります。

## 8. まとめ:タスクルーティングを1枚の判定表に

ここまでを1枚の判定表に畳みます。

```
新しいタスク t をアプリに追加するとき、次の5問を順に答える。

[1] タスク種別は?
       OCR / 画像 / 短文LLM / STT / 独自分類 / 長文推論 / セマンティック検索

[2] 3段優先(§2)を回す:
       Windows AI APIs に既製 API あり & Copilot+ PC 前提で OK?
        ├ Yes → Windows AI APIs を採用(終了)
        └ No  → LLM/STT で既製で足りる?
                 ├ Yes → Foundry Local を採用 → [3] へ
                 └ No  → 自前モデル?
                          ├ Yes → Windows ML を採用 → [4] へ
                          └ No(EP 直握り)→ ORT 直 → [4] へ

[3] (Foundry Local 採用時)Local/Cloud 軸を重ねる(§3)
       オフライン要件 / プライバシー要件 / モデル鮮度・性能要件で
       Local を基本とし、クラウドフォールバックを §4 の同顔で書く

[4] (Windows ML / ORT 採用時)端末能力(§5)を取る
       FindAllProviders + ReadyState、または ORT デバイスポリシー
       (MAX_EFFICIENCY / PREFER_NPU 等)で自動切替させる

[5] フォールバックを §6 で書く
       LLM系 → Phi Silica → Foundry Local → Azure OpenAI(同顔)
       自前 ONNX → Register → Ensure → DirectML/CPU → Foundry 代替
       品質基準は §7 のとおりタスクごとに別に決める
```

この5問を、アプリに乗っている全タスクについて回せば、**「どのタスクをどの入口に流し、何にフォールバックさせるか」が一意に決まる**設計になります。

これが本連載の到達点です。第1回で組んだ7語の地図は、第2回で ORT の幹を歩き、第3回で SLM の縮尺を変え、第4回で配布層を Windows ML に渡し、本記事で**タスク × 入口 × ローカル/クラウド** の3次元判定表まで来ました。新しいタスクが増えても、地図と判定表の上に置き直すだけです。

---

### 参考(主要な一次情報)

- [Use local AI with Microsoft Foundry on Windows — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/overview)
- [Choose between cloud-based and local AI models — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/cloud-ai)
- [Choose your Windows AI solution — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/windows-ai-comparison)
- [Accelerate AI models with Windows ML — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/accelerate-ai-models)
- [Install Windows ML execution providers — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/initialize-execution-providers)
- [Check execution provider versions in Windows ML — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/versioning)
- [Select execution providers — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/select-execution-providers)
- [Install and deploy Windows ML — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/distributing-your-app)
- [Foundry Local architecture overview — Microsoft Learn](https://learn.microsoft.com/en-us/azure/foundry-local/concepts/foundry-local-architecture)
- [Foundry Local SDK Reference — Microsoft Learn](https://learn.microsoft.com/en-us/azure/foundry-local/reference/reference-sdk-current)
- [Get started with Microsoft Foundry SDKs and Endpoints — Microsoft Learn](https://learn.microsoft.com/en-us/azure/foundry/how-to/develop/sdk-overview)
- [Get started with Phi Silica in the Windows App SDK — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/apis/phi-silica)
- [Tutorial: Build a chat app with Phi Silica and WinUI 3 — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/apis/phi-silica-winui-tutorial)
