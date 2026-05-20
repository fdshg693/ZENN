---
title: "LLM は知っているが Physical AI は知らない AI エンジニアのための 2026 年版地図"
emoji: "🤖"
type: "tech"
topics: ["ai", "robotics", "llm", "machinelearning", "physicalai"]
published: false
---

## この記事について

LLM やマルチモーダルモデルを日常的に扱っているエンジニアにとって、Physical AI は名前を聞く機会が急速に増えた一方で、LLM との技術的な差異や学習経路が見えにくい領域です。本記事はそのような読者を想定し、Physical AI の現状を特定ベンダーに偏らずに整理します。NVIDIA Cosmos、Figure Helix、Physical Intelligence の π0、Google DeepMind の Gemini Robotics、Tesla Optimus、Amazon の倉庫ロボット ― これらが何を解こうとしていて、LLM と技術的にどう連続し、どこが本質的に異なるのかを俯瞰します。

扱う範囲は「概念」「技術スタック」「LLM との比較」「プレイヤー俯瞰」「未解決問題」です。SDK の使い方や ROS のコードは扱いません。

:::message
業界用語、製品名、リリース時期はすべて 2024 年末〜 2026 年前半時点の調査に基づきます。動きが速い領域なので、断定的な記述は適宜公式情報で裏取りしてください。
:::

## 1. なぜ「Physical AI が来た」と言われるのか

本領域には現時点で確立した統一名称が存在しません。Georgetown の CSET レポートは、同じ概念に対して "embodied AI"、"physical AI"、"embodied machine intelligence"、"generative physical AI" が並存していると指摘しています[^cset]。NVIDIA は "Physical AI" を強く押し出していますが、これは特定企業のマーケティング文脈と切り離せない呼称でもあります。

それでも 2025 年に "Physical AI" という呼称が一気に普及したのは、複数の事象が同時に起きたためです。

- ヒューマノイドロボット系スタートアップに 2023〜2025 で **$10B 超**の投資が集中(Figure AI は $39B のバリュエーション)[^robozaps]
- Amazon は倉庫で **100 万台**のロボットを稼働中と公表し、独自 foundation model「DeepFleet」を投入[^cset]
- OpenAI が **2025 年初頭にロボティクス部門を再開**(2021 年に閉じていた)[^cset]
- Tesla、XPeng のような EV メーカーがヒューマノイドに参入
- NVIDIA が **2026 年 4 月に Google Cloud と Agentic + Physical AI で提携**するなど、クラウド側の動きも本格化[^cosmoslp]

過度な期待を差し引いても、技術面で 3 つの重要な変化があります。WEF のレポートはこれを **rule-based → training-based → context-based** という 3 階層で整理しています[^wef]:

1. **rule-based robotics**: 従来の決められた動きを正確に実行するロボット(産業用ロボの主流)
2. **training-based robotics**: 強化学習・模倣学習で可変タスクを覚えるロボット
3. **context-based robotics**: ロボティクス向け foundation model でゼロショットに新環境・新タスクへ対応するロボット

ここ 1〜2 年で本格化したのは 3 番目で、WEF レポートはこれを Physical AI の中核に位置づけています。

LLM エンジニア向けに要約すると、CSET レポートが引用する NVIDIA の整理が端的です[^cset]:

> 「LLM は 1 次元の予測(次のトークン)、画像・動画生成モデルは 2 次元の予測。Physical AI が解こうとしているのは **3 次元 + 時間軸 + 物理拘束**の予測である」

これが LLM と Physical AI の根本的な構造差を示しています。

## 2. Physical AI / Embodied AI の定義をそろえる

複数の定義の最大公約数を取ります。

- **Deloitte Tech Trends 2026**: 「Physical AI は、機械が物理世界を**リアルタイムに知覚・理解・推論・相互作用**できるようにする AI システム。事前プログラムに従う従来のロボットと違い、環境を知覚し、経験から学び、リアルタイムデータに基づき行動を適応させる」[^deloitte]
- **JST CRDS(日本)**: 「**センサーやアクチュエーターを通じて物理環境と直接相互作用しながら知能を獲得・発達させる embodied AI**。Physical AI システムは、自律的に行動・学習・意思決定する AI ロボットとそれを支えるインフラから成る」[^jst]
- **NVIDIA(CSET 経由)**: 「ロボット、自動運転車、スマートスペースなどの自律システムが、現実(物理)世界を知覚・理解し、複雑な行動を実行できるようにする」[^cset]

整理すると:

- **Embodied AI**: 「身体を持った AI」という性質を強調した呼称(学術寄り)
- **Physical AI**: 「物理世界を扱う AI」という能力を強調した呼称(産業寄り、NVIDIA 流)
- **Generative Physical AI**: 生成モデルの活用を前面に出した呼称(NVIDIA が用いる)

本記事ではコミュニティで最も通りの良い **Physical AI** を採用し、必要に応じて Embodied AI と読み替えます。

「ロボティクスの一部か」という問いに対しては、CSET の整理が最も明快です。すなわち **Physical AI はロボティクスの「認知側」を foundation model で置き換える流れ**であり、ロボティクスを置換するのではなく、その中核を再構築している、と整理できます。

## 3. 技術スタックの全景 ― AI エンジニア視点で

本節では Physical AI スタックを、AI エンジニアに馴染みやすい 4 層で整理します。

```
┌─────────────────────────────────────────┐
│ 認知層: VLA(Vision-Language-Action)モデル │  ← LLM/VLM の延長
├─────────────────────────────────────────┤
│ 環境層: World Foundation Model            │  ← 生成モデルの延長
├─────────────────────────────────────────┤
│ 訓練層: シミュレーション / Sim-to-Real    │  ← 強化学習 + 物理エンジン
├─────────────────────────────────────────┤
│ ハードウェア層: アクチュエータ・センサ・本体 │
└─────────────────────────────────────────┘
```

### 3.1 認知層: VLA(Vision-Language-Action)モデル

**VLA は VLM の出力に「アクション」を加えた拡張**と捉えてよいモデルです。視覚と言語の入力から、ロボットの関節角・トルク・グリッパ姿勢などの**連続アクション**を出力する foundation model を指します[^deloitte][^vlawiki]。

#### 主要なアーキテクチャ系統(複数社が並列に取り組んでいる)

**(a) Dual-system(System 2 + System 1)**

Figure AI の Helix(2025 年 2 月発表)が代表で、NVIDIA の GR00T N1(2025 年 3 月発表)も同じ構造を取っています[^vlawiki]:

- **System 2(S2)**: インターネット規模で訓練された VLM。シーン理解と言語理解を担当し、低頻度で推論を行います。
- **System 1(S1)**: 視覚運動ポリシー(visuomotor policy)。S2 が生成した潜在表現を連続アクションへ変換し、高頻度で動作します。

カーネマン(Kahneman)の「速い思考・遅い思考」のロボティクス版に相当します。LLM のような単一の巨大モデル構成ではなく、**「思考側」と「制御側」を分離し、後者を軽量・高頻度に保つ**点が本アーキテクチャの特徴です。

**(b) Flow matching / diffusion action expert**

Physical Intelligence の **π0**(2024 年 10 月)/ **π0-FAST**(2025 年 1 月)/ **π0.5**(2025 年 4 月)系統[^pi0site][^pi0arxiv]。事前学習された VLM(PaliGemma、SigLIP と Gemma を結合した 3B モデル)をバックボーンに、**action expert** を flow matching で訓練し、最大 50Hz の連続アクションを生成します。

π0-FAST は **FAST(Frequency-space Action Sequence Tokenization)** という時系列圧縮で、生成的にアクション系列を扱う離散トークン化を導入しています。

**(c) エンドツーエンドの単一 VLA**

OpenVLA、Google の RT-2、Allen Institute for AI の MolmoAct(2025 年 8 月)、HuggingFace の SmolVLA(2025 年 6 月)、Google DeepMind の **Gemini Robotics**(2025 年)。Gemini Robotics は Gemini 2.0 VLM をバックボーンに、低レベルロボットアクションを学習させた構成です。**Gemini Robotics On-Device**(2025 年 6 月)は VLA をロボット上でローカル実行できるよう軽量化し、開発者向けに fine-tuning も開放しました[^vlawiki]。

#### 重要なエンジニアリング制約

LLM の常識と異なる点として、**VLA のパラメータ規模は比較的小さい**ことが挙げられます:

- π0: 2B
- GR00T N1: 2B
- Helix の S2: 7B(これでも大きい部類)

Rohit Bandaru の整理によると、これは **「ロボティクスのレイテンシ制約が極端に強い」** ためです[^rohit]:

> デジタルタスク(コーディングなど)には時間制限がない。一方、ロボティクスでは世界が動き続けているため、遅いことが「失敗」に直結する。LLM の推論レイテンシ改善が、より大きく・より高性能なモデルをロボットに展開する道を開く。

つまり、**スケーリング則は LLM ほど明確には成立していません**(少なくとも現時点では)。30〜50Hz で安定して制御できることが、モデルサイズより優先される領域です。

### 3.2 環境層: World Foundation Model(WFM)

VLA が「行動するモデル」だとすると、World Foundation Model は **「世界そのものを生成・予測するモデル」** です。出力は多くの場合 video です。

NVIDIA Cosmos の論文(arXiv:2501.03575)が、この概念を最も明示的に押し出しました[^cosmospaper]:

> Physical AI はまずデジタルで訓練される必要がある。自分自身のデジタルツイン(=ポリシーモデル)と、世界のデジタルツイン(=ワールドモデル)が必要だ。Cosmos World Foundation Model Platform は、開発者がカスタム world model を構築するためのプラットフォームを提供する。

Cosmos は open-source / open-weight で公開されており(arXiv 2025 年 1 月版)、その後 Cosmos Transfer(写実的合成データ生成)、Cosmos Reason(動画と物理を理解する推論モデル)が追加されています[^cosmosblog]。

**LLM との対応関係**:

| LLM | WFM |
|---|---|
| next token を予測 | next frame / next physical state を予測 |
| トークン列を生成 | 動画と物理状態を生成 |
| 学習信号: 大量テキスト | 学習信号: 大量動画 |
| 主用途: 対話・生成 | 主用途: 合成データ生成、シミュレーション、長尾シナリオ生成 |

Voxel51 の記事が指摘するとおり、WFM は NVIDIA だけのものではありません。**Google DeepMind、OpenAI、そのほか競合各社が独自の WFM 路線を持っており**、共通の設計原則として以下が観察されます[^voxel51]:

- 動画を主要な学習信号にする(動画は静止画と違い、動き・因果・物理を内包する)
- 潜在表現で動画を圧縮し、効率的な訓練信号にする
- テキスト・幾何・センサー・アクションを fuse するマルチモーダル学習
- 物理シミュレーションと統合して、反復訓練ループを作る

「LLM が事前学習で世界の知識を獲得したように、WFM は事前学習で世界の物理を獲得する」 ― これが Voxel51 の整理に表れている現在の設計思想です[^voxel51]。

### 3.3 訓練層: シミュレーションと Sim-to-Real

WFM とは別に、**古典的な物理シミュレーション**も Physical AI の中核です。VLA を実機だけで訓練するのは、データコスト・安全性・スピードの全てで不可能だからです。

#### Sim-to-Real ギャップ

「シミュレーション上では完璧に動作するのに、実機では失敗する」という典型的な問題があります。Annual Reviews の総説によると、これは **photorealistic な見え方の再現**、**接触・変形・摩擦の物理再現**、**センサーモデル**の不完全さに起因します[^annualrev]。

近年の対策はおおむね以下の組み合わせ:

- **大規模並列シミュレーション**: GPU 上で数千ロボットを同時シミュレートし、強化学習データを量産[^annualrev]
- **ドメインランダム化**: 質量、摩擦、モーター定数などをランダム化して頑健性を上げる[^rai2025]
- **Real-to-Sim**: スマホで実空間を撮影 → COLMAP → 3DGUT/NuRec などで再構成 → Isaac Sim 等にロード。Re3Sim は 2025 年 2 月時点でシミュレーションのみで **zero-shot 平均 58% 成功**を報告[^jimfan]
- **Photorealistic 合成データ**: Cosmos Transfer のような WFM で写実的な動画を生成しデータ拡張

#### 物理エンジンの再編

近年の動向として、**Newton 物理エンジン**(2025 年 3 月発表、CoRL 2025 でも公表)が登場しています[^jimfan]:

- NVIDIA + Google DeepMind + Disney Research の共同開発
- NVIDIA Warp 上に構築、GPU 加速
- **Linux Foundation 管理**でオープンソース化

NVIDIA、DeepMind、Disney が物理エンジンの共通基盤化で合意した点は、競合関係にある企業間の連携として特異です。Physical AI 領域では各社の競争が継続する一方、**物理エンジンとデータフォーマットの標準化**が進行しています。

### 3.4 ハードウェア層(概略)

本記事の対象読者を考慮し、要点のみを示します。

**「ハードウェアの差は急速に縮小しており、差別化要因は AI に移った」**

- Unitree R1 は $5,900
- Tesla Optimus のターゲット価格は $20,000〜30,000
- 1X NEO は買い切り(約 $20,000)と **$499/月のサブスクリプション**の両プランを発表[^robozaps]
- 中国勢(Unitree、UBTECH、AgiBot、Fourier、LimX、XPeng)が量産で先行

ヒューマノイドが選択される理由は、**人間が設計した環境(階段、ドアノブ、工具、スイッチ)が人型の身体を前提としているため**、という点が業界の共通認識です[^metaintel]。

## 4. LLM と Physical AI のスケーリング感覚を比較する

LLM エンジニアが対応関係を把握しやすい形で、両者を比較表に整理します。

| 観点 | LLM | Physical AI(VLA を念頭に) |
|---|---|---|
| 主入力 | テキスト(+画像) | 視覚 + 言語 + センサー(関節角、力、深度) |
| 主出力 | 次トークン | 連続アクション(30〜50Hz) |
| データ源 | Web 上のテキストが豊富 | ロボット軌跡データが極端に希少 |
| 訓練データ規模感 | T tokens 級 | 数百〜数千時間の teleoperation + シム生成 |
| スケーリング則 | 経験的に強く成立 | 模倣学習にも scaling law が存在することが ICLR 2025 で報告された段階[^iclr2025] |
| モデルサイズ感 | 数十〜数百 B | 2〜7B 中心(レイテンシ制約) |
| 評価 | ベンチマークが豊富 | 実機評価が必要、再現性が低い |
| 安全性 | 出力テキストの審査 | 物理的事故になりうるため eval が難しい |

ここで最も重要なのは **「データ希少性」** です。Jim Fan(NVIDIA)が指摘する通り[^jimfan]:

> Robotics has a data scarcity problem - you simply can't scrape robot control data from webpages.

(訳: ロボティクスはデータ希少性の問題を抱えている。Web ページからロボット制御データをスクレイピングすることはできない)

LLM はインターネットから T tokens 規模のデータを取得できる一方、ロボット制御データは Web 上にほぼ存在しません。この不足を埋めるための主要アプローチは以下です:

1. **Teleoperation**: 人間がロボットを遠隔操作してデモ収集(高品質だが高コスト)
2. **Cross-embodiment 学習**: 違うロボット間でデータを共有(π0 は 8 種のロボットで訓練)
3. **シミュレーションでの大量生成**: GPU 並列で訓練
4. **WFM による合成データ**: 動画生成モデルで多様なシーンを作る
5. **ヒト動画からの学習**: GR00T N1 は人間の動画も訓練データに含む

**「ロボティクスでも LLM 並みに scaling law が成立するのか」**は、まだ完全には決着していません。ICLR 2025 では模倣学習における scaling law の存在が報告されており[^iclr2025]、特に「拡散モデル(アクション側)のスケーリングは効きにくい一方、視覚エンコーダのスケーリングは効く」という非対称な結果が示されています。

## 5. プレイヤー俯瞰(ベンダー横断)

Physical AI 周辺は呼称が乱立し、同一企業がモデル・ハードウェア・プラットフォームを跨いで展開しているため、全体像を俯瞰しにくい構造です。**「何を主軸にしているか」で 3 つに分類すると見通しが良くなります**。

### A. Foundation model 中心(モデル中心型)

ハードウェアを持たない、あるいは副次的に扱い、**モデル**で勝負する陣営です。

- **Physical Intelligence (π0 / π0.5)**: 2024 年末から立て続けに generalist policy を公開。OpenAI、Sequoia、Lux Capital、Khosla、Bezos などが出資[^pi0site]。π0 は **2025 年 2 月にオープンソース化済み**[^pi0site]
- **Google DeepMind (Gemini Robotics)**: Gemini 2.0 ベースの VLA。On-Device 版で fine-tuning を開放
- **Allen Institute for AI (MolmoAct, 2025 年 8 月)**: 完全自己回帰型のオープンソース VLA
- **HuggingFace (SmolVLA, 2025 年 6 月)**: π0 アーキテクチャを参考にした軽量 VLA
- **Skild AI、Covariant、TRI**: いずれも robotics foundation model 路線[^wef]

### B. ハードウェア + 自社モデル(垂直統合型)

ロボット本体を製造し、その上で動作するモデルも自社開発する垂直統合型です。

- **Figure AI**: Helix(VLA)、Figure 02。$39B バリュエーションでヒューマノイド分野で最高評価額の一社[^robozaps]
- **Tesla**: Optimus。自動運転で蓄積した Occupancy Network や end-to-end NN を転用[^metaintel]
- **1X**: Neo Gamma、Neo。家庭向けヒューマノイドとサブスクリプションを打ち出し[^robozaps]
- **Boston Dynamics、Apptronik、Neura、Unitree、UBTECH、AgiBot、XPeng**: 産業・家庭向けヒューマノイド

### C. プラットフォーム / 横断型

「ロボットや AI を開発する側を支える」ポジションです。

- **NVIDIA**: 全層をカバーする戦略を取っており、**Cosmos(WFM)+ Isaac Sim / Omniverse(シミュレーション)+ GR00T(VLA)+ Newton(物理エンジン)+ GPU(ハードウェア)**を展開。Cosmos の論文はオープン公開、Newton は Linux Foundation 管理のため、エコシステム戦略は完全クローズではありません
- **Amazon**: 倉庫運用と組み合わせ、**実運用規模で最大級の Physical AI 事業者の一つ**。100 万台稼働、独自 foundation model DeepFleet を保有[^cset]
- **OpenAI**: 2025 年に robotics 部門を再開。Figure と 1X に出資[^cset]
- **Google Cloud / Microsoft / 各クラウド**: Physical AI 向け学習基盤を提供

### 国別の濃淡

- **中国**: ヒューマノイドの **量産・低価格化で先行**。Unitree、UBTECH、AgiBot、XPeng が代表[^robozaps]
- **米国**: foundation model と高性能ヒューマノイドで先行
- **日本**: JST CRDS が国家戦略提案を出している段階[^jst]
- **韓国**: Samsung、Hyundai がヒューマノイド投資に参加

特定 1 社にロックインされる構図は現時点では成立していません。**モデル、ハードウェア、シミュレーション、物理エンジン、データのそれぞれで競争と協調が混在**しています。

## 6. 未解決問題と、AI エンジニアの次の一手

### 残っている主要問題

Physical Intelligence 自身が論文・ブログで挙げている未解決の論点が、業界全体の論点とよく重なります[^pi0site]:

1. **データ希少性とスケーリング**: 実機デモ / シミュレーション / video learning のバランス、cross-embodiment データの共有
2. **Long-horizon reasoning**: LLM 的な複数ステップ計画とロボット制御の接続
3. **自律的な自己改善**: 実機運用中にデータが増えるたびにモデルが伸びる仕組み
4. **頑健性と安全性**: 評価が LLM eval よりはるかに難しい
5. **Latency と on-device 制約**: 大きい VLM を使いたいが、リアルタイム制御に乗らない

加えて、AI エンジニア視点での課題:

6. **Agentic AI との合流**: 「LLM agent がロボットの脳になる」流れ(Deloitte がこの先 10 年の主軸として言及)[^deloitte]
7. **評価基盤の標準化**: LeRobot、Open X-Embodiment などのデータセット標準化が進行中

### AI エンジニアが触り始めるなら

特定ベンダーに依存せず手を動かせる対象を以下に列挙します。

- **オープン VLA を読む**: OpenVLA、π0(2025 年 2 月にオープンソース化)、SmolVLA(HuggingFace、軽量)、MolmoAct(Allen Institute for AI、完全 OSS)
- **WFM 論文を読む**: NVIDIA Cosmos の論文(arXiv:2501.03575)で「video token + action token + 物理拘束」の設計を確認[^cosmospaper]
- **シミュレーションを動かす**: LeRobot(HuggingFace、Python から利用可能)、Isaac Sim、MuJoCo。物理エンジン側は Newton が今後の本命候補
- **survey を読む**: arXiv 2509.19012 の「Pure VLA Models: A Comprehensive Survey」が 2025 年の VLA を網羅的に整理[^vlasurvey]
- **agentic との接続を観察**: ロボットの「脳」が LLM agent に置き換わる流れ。Claude / GPT 系の tool use とロボット制御の合流地点

注目すべき点として、**Physical AI のオープンソース化は LLM 領域と同等の速度で進行しています**。Cosmos、π0、OpenVLA、SmolVLA、Newton、LeRobot ― 重要な部品の多くが open-weight / OSS で公開済みです。GPU を 1 枚保有していれば、π0 の fine-tuning も実施可能になりつつあります。

## 7. まとめ

- **Physical AI は LLM の延長**(VLA は VLM + アクション)**であると同時に、ロボティクスの再構築**(認知側を foundation model で置き換える)でもあります
- 技術スタックは **VLA / WFM / シミュレーション / ハードウェア** の 4 層で整理できます
- LLM との最大の差異は **データ希少性とレイテンシ制約**であり、これを WFM、テレオペレーション、シミュレーション、cross-embodiment、video learning で埋める試みが進行しています
- **特定ベンダーロックインの構図は現時点で成立していません**。NVIDIA は全層をカバーする戦略を取っていますが、Cosmos も Newton もオープンであり、Figure / Tesla / 1X / Physical Intelligence / DeepMind / OpenAI / Amazon が独自路線を保っています
- AI エンジニアの観点では、**LLM 開発で培った知識の大部分は VLA・WFM の理解に転用可能**であり、追加で必要となるのは物理シミュレーション、制御、ロボット固有のデータパイプラインといった領域です

LLM の次に主軸となる候補として有力視されている領域であり、ハイプと並行して産業実装が現実に進行している点が特徴です。

---

## 参考文献

[^cset]: Center for Security and Emerging Technology (Georgetown), "Physical AI", 2025. https://cset.georgetown.edu/publication/physical-ai/
[^deloitte]: Deloitte Insights, "Physical AI and humanoid robots", Tech Trends 2026. https://www.deloitte.com/us/en/insights/topics/technology-management/tech-trends/2026/physical-ai-humanoid-robots.html
[^wef]: World Economic Forum, "Physical AI: Powering the New Age of Industrial Operations", 2025. https://reports.weforum.org/docs/WEF_Physical_AI_Powering_the_New_Age_of_Industrial_Operations_2025.pdf
[^jst]: JST CRDS, "(Strategic Proposals) Physical AI System - Integration of Embodied AI and Robotics", CRDS-FY2025-SP-01. https://www.jst.go.jp/crds/en/publications/CRDS-FY2025-SP-01.html
[^vlawiki]: Wikipedia, "Vision–language–action model". https://en.wikipedia.org/wiki/Vision-language-action_model
[^vlasurvey]: "Pure Vision Language Action (VLA) Models: A Comprehensive Survey", arXiv:2509.19012. https://arxiv.org/html/2509.19012v1
[^rohit]: Rohit Bandaru, "Foundation Models for Robotics: Vision-Language-Action (VLA)", 2025. https://rohitbandaru.github.io/blog/Foundation-Models-for-Robotics-VLA/
[^pi0site]: Physical Intelligence, "π0: Our First Generalist Policy" など各種ブログ. https://www.pi.website/blog/pi0 および https://www.pi.website/
[^pi0arxiv]: "π0: A Vision-Language-Action Flow Model for General Robot Control", arXiv:2410.24164. https://arxiv.org/html/2410.24164v1
[^cosmospaper]: "Cosmos World Foundation Model Platform for Physical AI", arXiv:2501.03575 (NVIDIA). http://ui.adsabs.harvard.edu/abs/2025arXiv250103575N/abstract
[^cosmosblog]: NVIDIA Developer Blog, "Scale Synthetic Data and Physical AI Reasoning with NVIDIA Cosmos World Foundation Models", 2026. https://developer.nvidia.com/blog/scale-synthetic-data-and-physical-ai-reasoning-with-nvidia-cosmos-world-foundation-models/
[^cosmoslp]: NVIDIA Cosmos landing page. https://www.nvidia.com/en-us/ai/cosmos/
[^voxel51]: Voxel51 blog, "The Rise of World Foundation Models". https://voxel51.com/blog/the-rise-of-world-foundation-models
[^annualrev]: Annual Reviews of Control, Robotics, and Autonomous Systems, "The Reality Gap in Robotics: Challenges, Solutions, and Best Practices". https://www.annualreviews.org/content/journals/10.1146/annurev-control-031924-100130
[^rai2025]: RAI Institute, "RAI Institute 2025: A Year of Innovation for Robotics and AI". https://rai-inst.com/resources/blog/rai-institute-2025-a-year-of-innovation-for-robotics-and-ai/
[^jimfan]: Jim Fan (NVIDIA) の LinkedIn 投稿、および Newton 発表(CoRL 2025)関連投稿. https://www.linkedin.com/posts/drjimfan_robotics-has-a-data-scarcity-problem-you-activity-7282783528847613952-KFQO
[^iclr2025]: Fanqi Lin et al., "Data Scaling Laws in Imitation Learning for Robotic Manipulation", ICLR 2025 Oral. https://openreview.net/forum?id=pISLZG7ktL
[^robozaps]: "What Is a Humanoid Robot? [2026]", robozaps. https://blog.robozaps.com/b/humanoid-robot
[^metaintel]: Meta Intelligence, "Humanoid Robots 2026: Tesla Optimus, Figure 02 & NVIDIA Isaac". https://www.meta-intelligence.tech/en/insight-physical-ai
　