---
title: "WindowsローカルAIの技術地図 2026:ONNX Runtime・Windows ML・DirectML・NPUの関係を整理する"
emoji: "🗺️"
type: "tech"
topics: ["windows", "onnxruntime", "winml", "npu", "ai"]
published: false
---

## この記事について

「WindowsでローカルAIを動かしたい」と思って調べ始めると、ONNX / ONNX Runtime / DirectML / Windows ML / Execution Provider / NPU / Copilot+ PC という言葉が一斉に出てきます。さらに厄介なことに、ある記事は「DirectMLを使え」と言い、別の記事は「Windows MLを使え」と言い、しかも「Windows ML」と名のつくものが2つ存在します。

この記事は、これらを1枚の技術地図に置き直すことを目的にします。コードは出てきません。代わりに、「どの言葉がどの層の話なのか」「2026年時点で何が中心で、何が脇に退いたのか」をはっきりさせます。

対象読者は、Windows 上でローカル AI(通常の ML モデルや小規模言語モデル)を動かしたいが、用語の層がごちゃ混ぜになっているアプリ / .NET / Python 開発者です。機械学習推論の概念(モデル・推論・前後処理)をざっくり理解していれば読めます。特定言語の経験は問いません。

:::message
本記事は連載「WindowsローカルAI実践入門」の第1回(全体地図)です。第2回以降の実装記事は、この地図の特定の場所を拡大していきます。連載構成は §9 にまとめます。
:::

:::message alert
**2025→2026 で構図が変わっています。** 少し前まで「Windows で GPU 推論なら DirectML」が定番でしたが、2025 年に Windows ML が登場・GA し、DirectML は新規開発が止まった「保守モード(sustained engineering)」に入りました。本記事は古い DirectML 中心の地図ではなく、Windows ML を中心に据えた現行の地図を提示します。根拠は §5 で示します。
:::

この記事は3部構成です。**第I部(§0〜§4)で地図そのもの**を概念として組み立て、**第II部(§5〜§7)で 2025→2026 の構図変化と典型的なつまずき**を3つに整理し、**第III部(§8〜§10)で実践の入口と連載の歩き方**を示します。

---

# 第I部:地図を組み立てる

## 0. はじめに:なぜ技術地図が必要か

WindowsローカルAIの解説が分かりにくい最大の理由は、技術用語が層の違うものを同じ平面で並べてしまうことにあります。

たとえば「ONNX と DirectML と Windows ML、どれを使えばいい?」という問いは、問いとして成立していません。これは「ネジ(ONNX)と特定の工具(DirectML)と工具の調達網(Windows ML)、どれを使えばいい?」と聞くのに近く、それぞれ別の層のものだからです。この比喩でいう「ネジ」が形式の層、「工具」が実行経路(EP)の層の一例、「調達網」が後述の管理層 Windows ML にあたります。

冒頭の7語を抽象度で仕分けると、次のようになります。横並びで比較できる7つではありません。

- **モデルが通る縦の実行線(4要素)**:ONNX(形式)→ ONNX Runtime(エンジン)→ Execution Provider(実行経路)→ ハードウェア
- **その縦を横から束ねる管理層(1つ)**:Windows ML
- **層ではなく、層の中の具体例やラベル(3つ)**:DirectML(= Execution Provider の一例)/ NPU(= ハードウェアの一種)/ Copilot+ PC(= 一定水準のハードを備えた PC の呼び名)

DirectML・NPU・Copilot+ PC は「新しい段」ではなく、すでにある層の中身を指す言葉です。ここを取り違えると、層の違うものを横並びで比較してしまい、答えの出ない問いに延々と悩むことになります。まず層を確定し、各層を1つずつ見る。これが本記事のやり方です。

この第1回の役割は、続く第2回〜第5回(ONNX Runtime 実行、SLM、Windows ML・AI アプリ開発、実用例)の共通の前提地図を作ることです。

## 1. 全体像:7語を1枚の地図に置く

先に結論の地図を出します。7語は積み重なる7段ではなく、次のように配置されます。

```
[PCカテゴリ]  Copilot+ PC
   = ハード要件(40 TOPS 級 NPU 等、詳細は §4)を満たす Windows 11 PC の呼び名
   ※ 技術ではなく、下の「ハードウェア」を一定水準以上で備えた PC のラベル

あなたのアプリ
   │ ONNX モデルを渡す
   ▼
┌─ 配布・管理レイヤ ─────────────────────────
│  Windows ML(新)
│    ・共有 ONNX Runtime を提供
│    ・環境に合った Execution Provider を自動取得/管理
│    ・縦の土台を「横から」束ねる(ORT を置き換えず内部で使う)
└────────────────────────────────────────────
   │ 内部で下の土台を駆動
   ▼
╔═ 不変の土台3層(§2 で扱う範囲)══════════════
║  ONNX … モデルの入れ物(形式)
║    ▼
║  ONNX Runtime (ORT) … 推論エンジン(グラフ最適化・サブグラフ分割)
║    ▼
║  Execution Provider (EP) … 実行経路
║      例) CPU / DirectML / QNN / OpenVINO / VitisAI / TensorRT …
║      └ DirectML はこの層の「一例」。独立した層ではない
╚════════════════════════════════════════════
   │ 選ばれた EP がハードウェアを駆動
   ▼
[ハードウェア]  CPU  /  GPU  /  NPU
   └ NPU もこの層の一要素。独立した層ではない
```

この地図の読み方は3点です。

1. **モデルが通る縦の実行線は4要素**(ONNX → ONNX Runtime → Execution Provider → ハードウェア)です。**そのうち上の3層が「変わらない土台」**で、二重線で囲ってあります。一番下のハードウェア(CPU/GPU/NPU)は実行線の4要素目ですが、内容が独立した話題になるため §4 で別に扱います。土台3層は §2 です。
2. **Windows ML はこの縦を横から束ねる管理層**です。ORT と EP の「配布と管理」を肩代わりするもので、ORT を置き換えるものではありません(内部で ORT を使います)。
3. **DirectML・NPU・Copilot+ PC は新しい段ではありません。** DirectML は Execution Provider 層の一例、NPU はハードウェア層の一要素、Copilot+ PC はそのハードウェアを一定水準で備えた PC のラベルです。だから地図上に独立した行を持ちません。

以降は、まず不変の土台(§2)→ それを束ねる Windows ML(§3)→ 一番下のハードウェア(§4)の順に地図を拡大し、その後で 2025→2026 に動いた部分と落とし穴(§5〜§7)に進みます。

## 2. 不変の土台3層:ONNX → ONNX Runtime → Execution Provider

ここは Windows ML 時代になってもまったく変わらない土台です。ここを押さえれば、以降の章はすべてこの土台の上に積む説明になります。

### ONNX:モデルの「入れ物」

ONNX は学習済みモデルの交換フォーマットです。PyTorch、TensorFlow/Keras、TFLite、scikit-learn など、異なるフレームワークで作ったモデルを ONNX に変換すると、共通の入れ物に収まります([ONNX Runtime docs](https://onnxruntime.ai/docs/))。

重要なのは、ONNX は形式であって実行する仕組みではないという点です。`.onnx` ファイル単体は動きません。読んで実行するエンジンが要ります。それが次の ONNX Runtime です。

### ONNX Runtime (ORT):推論エンジン

ONNX Runtime は、ONNX モデルを実行するクロスプラットフォームの推論エンジンです。内部では、モデルのグラフに最適化をかけ、利用可能なハードウェア固有アクセラレータに合わせてサブグラフに分割してから実行します([ONNX Runtime docs](https://onnxruntime.ai/docs/))。

ORT は実験的なものではありません。Office、Azure、Bing、そして Windows 自身が、AI 機能をこの ORT で動かしています([ONNX Runtime docs](https://onnxruntime.ai/docs/))。本連載が ORT を土台に置くのは、それが Windows ローカル AI の事実上の共通基盤だからです。

### Execution Provider (EP):ハードウェアへの実行経路

Execution Provider は、ORT がどのハードウェアで計算を実行するかを抽象化する層です。ORT は `GetCapability()` というインターフェースを通じて、モデルのノードやサブグラフを、対応する EP ライブラリ(CPU / GPU / FPGA / 専用 NPU 向け)に割り当てます([ONNX Runtime Execution Providers](https://onnxruntime.ai/docs/execution-providers/))。

EP は多数あります。CPU(デフォルト)、NVIDIA CUDA / TensorRT、DirectML、Intel OpenVINO、AMD MIGraphX、Qualcomm QNN などです([ONNX Runtime Execution Providers](https://onnxruntime.ai/docs/execution-providers/))。EP を指定しなければ CPU にフォールバックします。つまり「ONNX モデルは最低限どこでも動くが、速くするには適切な EP が要る」という構造です。**DirectML はこの EP の一種**であり、§5 で扱う構図変化の主役になります。

ここまでが、二重線で囲った不変の土台3層(ONNX → ORT → EP)です。次は、この土台を横から束ねる Windows ML を見ます。

## 3. 束ねる層:Windows ML(新)とは

中心に座った Windows ML(新)とは何か。一言でいうと、次のとおりです。

> システム共有の ONNX Runtime + ハードウェアに合った Execution Provider を自動ダウンロード/管理してくれる、Windows 標準のローカル推論ランタイム

アプリ側が ORT も EP もバンドルしなくてよくなる、というのが核心です([What is Windows ML?](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/overview))。

### 仕組み:自動デプロイの4ステップ

公式ドキュメントは動作を次の4段階で説明しています([What is Windows ML?](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/overview))。

1. **アプリ導入** — Windows App SDK のブートストラッパが Windows ML を初期化
2. **ハードウェア検出** — ランタイムが利用可能なプロセッサを特定
3. **EP ダウンロード** — 最適な Execution Provider を自動取得
4. **即推論** — アプリはすぐ モデルを実行できる

これにより、開発者は「ベンダーごとに EP をバンドルする」「EP ごとに別ビルドを作る」「EP 更新を手動で扱う」必要がなくなります([What is Windows ML?](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/overview))。

### 同梱 EP と、動的取得される EP

ここが地図の重要な分岐点です。

| 区分 | EP | 説明 |
|---|---|---|
| 同梱(Windows ML の ORT に同梱) | CPU / DirectML | DirectML はここに含まれる。`DirectML.dll` 約 20MB |
| 動的取得(`ExecutionProviderCatalog` 経由) | QNN(Qualcomm)/ OpenVINO(Intel)/ VitisAI・MIGraphX(AMD)/ NvTensorRtRtx(NVIDIA) | ベンダー EP は Windows ML 本体には含まれず、別途取得・登録される |

出典:[Windows ML execution providers](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/supported-execution-providers)、[Install and deploy Windows ML](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/distributing-your-app)。

DirectML が「消えていない」のはこの表のためです。DirectML は Windows ML が同梱する GPU 用 EP として地図に残っています。一方、各ベンダーの高性能 EP は Windows ML 本体には含まれず、`ExecutionProviderCatalog` API で実行時に取得されます。EP の更新版は Windows Update の任意の非セキュリティ プレビュー(通称 "D week" リリース)で配布されます([Windows ML execution providers](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/supported-execution-providers))。「保守モードに入った DirectML がなぜまだ同梱なのか」は §5 で扱います。

### 配布の2方式

アプリへの組み込みには2方式あり、公式は前者を推奨します([Install and deploy Windows ML](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/distributing-your-app))。

| | framework-dependent(推奨) | self-contained |
|---|---|---|
| アプリサイズ | 小さい(Windows ML バイナリをシステム共有) | 大きい(約 41MB を同梱) |
| Windows ML 更新 | 自動(Windows App SDK のサービシング経由) | 手動(自分で新版を出す) |
| インストール済みランタイム依存 | あり(Windows App SDK ランタイムが必要) | なし(全依存をアプリに同梱) |

同梱 EP の置き場所も配布方式で変わります。framework-dependent では同梱 EP もシステム側にあり、self-contained では同梱 EP もアプリ側に入ります。だから self-contained は約 41MB になり、内訳は Windows ML API の DLL 約 1MB + `onnxruntime.dll` 約 20MB + `DirectML.dll` 約 20MB です([Install and deploy Windows ML](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/distributing-your-app))。

### システム要件と現在の状態

- **GA**:2025-09-23([Windows ML is generally available](https://blogs.windows.com/windowsdeveloper/2025/09/23/windows-ml-is-generally-available-empowering-developers-to-scale-local-ai-across-windows-devices/))
- **同梱**:Windows App SDK 1.8.1 以降
- **対応 OS**:Windows 11 24H2(build 26100)以降(ベンダー EP の動的取得はこの条件)
- **アーキテクチャ**:x64 / ARM64
- **言語**:C# / C++ / Python

出典:[Windows ML is generally available](https://blogs.windows.com/windowsdeveloper/2025/09/23/windows-ml-is-generally-available-empowering-developers-to-scale-local-ai-across-windows-devices/)、[Windows ML execution providers](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/supported-execution-providers)。

## 4. 一番下の層:ハードウェアと Copilot+ PC

地図の一番下、ハードウェア層です。土台3層が選んだ EP は、最終的にここで計算します。

### CPU / GPU / NPU の役割分担

- **CPU**:最も広く動く。EP 未指定時のフォールバック。互換性と柔軟性
- **GPU**:生のスループット(重い並列計算)
- **NPU**:低電力で持続的な推論に向く専用 AI 演算ハードウェア

Windows ML はデバイスポリシーで「低電力なら NPU」「高性能なら GPU」のように、用途に応じたプロセッサ(CPU/GPU/NPU)の使い分けを指定できます([Windows ML is generally available](https://blogs.windows.com/windowsdeveloper/2025/09/23/windows-ml-is-generally-available-empowering-developers-to-scale-local-ai-across-windows-devices/))。

### Copilot+ PC は「技術」ではなく「PC カテゴリ」

Copilot+ PC は、ハードウェア要件で定義された PC のクラスです。具体的には、40 TOPS 以上の NPU、16GB 以上の RAM、特定の SoC(Qualcomm Snapdragon X Elite/Plus、Intel Core Ultra など)を満たす Windows 11 PC を指します([Choose your Windows AI solution](https://learn.microsoft.com/en-us/windows/ai/windows-ai-comparison)、[Copilot+ PCs developer guide](https://learn.microsoft.com/en-us/windows/ai/npu-devices/))。

ここで地図上の重要な関係を1つ押さえます。

> Copilot+ PC は Windows AI APIs には必須だが、Windows ML や Foundry Local には必須ではない。
> — [Choose your Windows AI solution](https://learn.microsoft.com/en-us/windows/ai/windows-ai-comparison)

つまり「Copilot+ PC を持っていないとローカル AI は何もできない」ではありません。自前 ONNX モデルを Windows ML で動かすだけなら、任意の Windows ハードウェアで可能です。Copilot+ PC が必要になるのは、§8 で扱う高レベルの Windows AI APIs を使う場合です。

ここまでが地図の全要素です。次の第II部では、この地図のうち 2025→2026 で動いた部分と、読者が必ずつまずく3点を整理します。

---

# 第II部:3つの落とし穴

地図そのものは以上です。ここからは、地図を正しく持っていても引っかかる3つの落とし穴を、同じ形式(**誤解 → 事実 → 地図で言うと**)でまとめます。どれも実装段階で効いてくる重要点です。

## 5. 落とし穴1:DirectML は中心から退いた(2025→2026 の構図変化)

**誤解:** 「Windows で GPU 推論するなら DirectML EP」。少し前の記事はこう書いています。これは間違いではありませんが、2026 年時点ではもはや中心ではありません。新旧の解説が食い違う最大の原因がこの点です。

**事実:DirectML は「保守モード」に入った。**

ONNX Runtime 公式の DirectML EP ドキュメントは、冒頭でこう述べています。

> DirectML is in sustained engineering. DirectML continues to be supported, but new feature development has moved to WinML for Windows-based ONNX Runtime deployments.
> （DirectML は保守エンジニアリング段階にある。サポートは継続するが、新機能開発は Windows 向け ONNX Runtime デプロイにおいて WinML へ移行した。）
> — [DirectML Execution Provider](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html)

Microsoft Learn の「Windows AI ソリューションの選択」ページの用語集でも、DirectML は "No longer being actively developed (in sustained engineering)"、そして "Windows ML IHV-specific Execution Providers = The replacement for DirectML"(ベンダー固有 EP が DirectML の置き換え)と明記されています([Choose your Windows AI solution](https://learn.microsoft.com/en-us/windows/ai/windows-ai-comparison))。さらに Copilot+ PC 開発ガイドは、NPU/GPU へのプログラム的アクセスの推奨が DirectML から Windows ML へ移ったと書いています([Copilot+ PCs developer guide](https://learn.microsoft.com/en-us/windows/ai/npu-devices/))。

変化の時期は次の2点です。

- **2025-05-19**:Windows ML が発表される。当時の公式ブログは Windows ML を「過去1年の学びに基づく DirectML の進化形(evolution of DirectML)」と位置づけています([Introducing Windows ML](https://blogs.windows.com/windowsdeveloper/2025/05/19/introducing-windows-ml-the-future-of-machine-learning-development-on-windows/))。
- **2025-09-23**:Windows ML が一般提供(GA)。本番アプリ向けの推論フレームワークとして提供開始([Windows ML is generally available](https://blogs.windows.com/windowsdeveloper/2025/09/23/windows-ml-is-generally-available-empowering-developers-to-scale-local-ai-across-windows-devices/))。

ただし DirectML が削除されたわけではありません。§3 の表のとおり、`DirectML.dll` は Windows ML に同梱される GPU 用 EP として現役です。変わったのは「学ぶ入口」です。

**地図で言うと:** DirectML は「中心のランドマーク」から「Windows ML 内の一区画」へ移動しました。2026 年に新しく Windows ローカル AI を始めるなら、DirectML を直接学ぶより Windows ML を入口にするのが正解です。

## 6. 落とし穴2:「Windows ML」は新旧2つある

**誤解:** 「Windows ML」と書いてある情報はすべて同じものを指している。実際には「Windows ML」という名前のものが2つあります。

**事実:**

| 名前 | 実体 | 状態 |
|---|---|---|
| Windows ML(旧) | WinRT ベースの推論 API。Windows 10 1809 から OS 同梱(inbox) | 今も動くが新規投資なし |
| Windows ML(新) | ONNX Runtime ベースの NuGet パッケージ | 現行・活発に開発中 |

出典:[Choose your Windows AI solution](https://learn.microsoft.com/en-us/windows/ai/windows-ai-comparison) の用語集。

古い記事や古い API リファレンスが「Windows ML」と書いているとき、その多くは旧版を指しています。本記事および本連載で「Windows ML」と言うときは、断りがなければ新版(ONNX Runtime ベース、NuGet、`/windows/ai/new-windows-ml/` 配下のドキュメント)を指します。

見分け方の目安は次の3点です。

- ドキュメントの URL に `new-windows-ml` が入っているか
- 「ONNX Runtime ベース」「Windows App SDK の NuGet パッケージ」と説明されているか
- WinRT API(`Windows.AI.MachineLearning` 名前空間)中心の説明なら旧版の可能性が高い

**地図で言うと:** 同じ「Windows ML」というラベルが地図上の別の場所を指している状態です。情報源を読むときは、まず新旧どちらの Windows ML の話かを判定する。これを習慣にすると、新旧の記述が混ざる事故を防げます。

## 7. 落とし穴3:「載せれば速くなる」ではない

**誤解:** 「Windows ML を使えば自動で速くなる」「NPU 搭載 PC なら推論は勝手に高速」。どちらも違います。

**事実1:Windows ML / ORT はモデル最適化をしない。** 公式ドキュメントは明言しています。Windows ML は EP の配布を担うが、モデルの最適化はしない。モデルを各ハードウェア向けに最適化(量子化など)する責務は、開発者側(AI Toolkit for VS Code などのモデル最適化ツールや ORT 側)にあります([What is Windows ML?](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/overview))。ORT / Windows ML は「モデルを載せれば速くなる」ものではなく、最適化は別の責務です。

**事実2:NPU 搭載 = 即高速、ではない。** EP がそのハードウェアで動くには、対応 EP + 対応ドライバの最小バージョン + 適切なモデル形式が揃う必要があります。実際、Windows ML の EP 一覧では、EP ごとに最小ドライバ要件が個別に定義されています(例:Qualcomm QNN は Hexagon NPU のドライバ 30.0.140.0 以上、Intel OpenVINO は CPU/GPU/NPU で世代別の最小ドライバ要件、AMD VitisAI は特定の Adrenalin Edition + NPU ドライバ範囲)([Windows ML execution providers](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/supported-execution-providers))。

**地図で言うと:** ハードウェア層に NPU があっても、対応 EP と最小バージョンを満たすドライバ、そして最適化済みモデルが揃わなければ使えません。この最適化要件とドライバ要件は、後続の SLM 回で実際に重要となる論点です。

---

# 第III部:実践と歩き方

## 8. どの入口を選ぶか:4つの判断軸

ここまでの地図を踏まえると、Windows で AI を実装する「入口」は大きく4つに整理できます([Choose your Windows AI solution](https://learn.microsoft.com/en-us/windows/ai/windows-ai-comparison))。

| 入口 | 何か | ハードウェア要件 | 向くケース |
|---|---|---|---|
| Windows AI APIs | Microsoft 提供の既製 AI 機能(Phi Silica、OCR、画像、意味検索 等) | Copilot+ PC 必須 | ML の専門知識なしで既製 AI 機能を組み込む |
| Foundry Local | 20 種類以上の OSS LLM/音声モデルを OpenAI 互換 API で | 任意の Windows ハードウェア | 既製 LLM を OpenAI 互換 API で手早く使う |
| Windows ML | 自前 ONNX モデルをローカル推論(CPU/GPU/NPU) | 任意の Windows ハードウェア | 自分のモデルを推論パイプライン込みで制御 |
| ORT を直接 | ONNX Runtime を自前で叩く | 任意 | EP 管理を自分で握る/既存 ORT 資産がある |

判断フロー(簡略版)は次のとおりです。

```
既製の AI 機能(OCR・要約・画像など)で足りる?
   ├ Yes → Copilot+ PC 前提でよい?
   │         ├ Yes → Windows AI APIs
   │         └ No  → Foundry Local(任意ハードウェア)
   └ No(自前 ONNX モデルを動かしたい)
             → Windows ML を起点にする
                  └ EP 管理まで細かく制御したい → ORT を直接
```

本連載が主役に据えるのは Windows ML です。理由は、自前の ML / SLM モデルを動かすという連載のテーマに最も合致し、かつ §5 で見たとおり 2026 年時点で Microsoft が推す中心だからです。

## 9. この連載の歩き方:地図のどこを深掘りするか

第2回以降は、この地図の特定レイヤーの拡大図です。今どこを見ているか分かるように対応を示します。

| 回 | 内容 | 地図上のどこ |
|---|---|---|
| 第1回(本記事) | 全体地図 | 地図全体 |
| 第2回(予定) | ONNX Runtime で通常 ML モデルを動かす | §2 の土台 + §4 のハードウェアを、実装で |
| 第3回(予定) | SLM をローカル実行 | §2/§3/§4 を SLM 固有論点(量子化・メモリ等)で |
| 第4回(予定) | Windows ML / Windows AI API / Copilot+ PC 開発 | §3/§6/§8 を開発者視点で |
| 第5回(予定) | 実用アプリへの組み込み | 全レイヤーの統合 |

## 10. まとめ:地図を一文で

最後に、この地図を一覧に畳みます。

- **7語は層が違う。** ONNX(形式)→ ONNX Runtime(エンジン)→ Execution Provider(実行経路)→ ハードウェア(CPU/GPU/NPU)が縦の実行線で、うち ONNX/ORT/EP の3層が不変の土台。DirectML・NPU・Copilot+ PC は層ではなく層内の具体例やラベル。
- **DirectML は中心から退いた。** 削除ではなく「保守モード(sustained engineering)」入り。今は Windows ML 同梱の GPU 用 EP という一区画。新規に学ぶ入口は Windows ML。
- **Windows ML(新)= 共有 ONNX Runtime + EP の動的配布・管理。** GA は 2025-09、Windows 11 24H2 以降 / Windows App SDK 1.8.1 以降。ただしモデル最適化はしない(別責務)。
- **「Windows ML」は新旧2つある。** 旧(WinRT/OS 同梱)は今も動くが新規投資なし。情報源は新旧どちらの話か必ず判定する。
- **Copilot+ PC は 40 TOPS 以上の PC カテゴリ。** Windows AI APIs には必須だが、Windows ML には必須ではない。
- **入口は4つ**(Windows AI APIs / Foundry Local / Windows ML / ORT 直)。本連載は Windows ML を起点に進む。

この地図を頭に入れておけば、第2回以降で個別の実装に入っても「今どの層の話をしているか」を見失いません。次回は、この地図の土台にあたる ONNX Runtime で通常の ML モデルを実際に動かすところから始めます。

---

### 参考(主要な一次情報)

- [What is Windows ML? — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/overview)
- [Windows ML execution providers — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/supported-execution-providers)
- [Install and deploy Windows ML — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/distributing-your-app)
- [Choose your Windows AI solution — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/windows-ai-comparison)
- [Copilot+ PCs developer guide — Microsoft Learn](https://learn.microsoft.com/en-us/windows/ai/npu-devices/)
- [ONNX Runtime docs](https://onnxruntime.ai/docs/) / [Execution Providers](https://onnxruntime.ai/docs/execution-providers/) / [DirectML Execution Provider](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html)
- [Introducing Windows ML(2025-05-19)— Windows Developer Blog](https://blogs.windows.com/windowsdeveloper/2025/05/19/introducing-windows-ml-the-future-of-machine-learning-development-on-windows/)
- [Windows ML is generally available(2025-09-23)— Windows Developer Blog](https://blogs.windows.com/windowsdeveloper/2025/09/23/windows-ml-is-generally-available-empowering-developers-to-scale-local-ai-across-windows-devices/)
