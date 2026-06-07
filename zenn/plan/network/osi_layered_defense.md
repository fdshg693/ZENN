---
title: "「7層のどこで守るか」— Web公開システムの多層防御を層の地図で設計する"
status: plan
---

## この plan について

- 記事スラッグ: `osi_layered_defense`
- 配置予定: `zenn/publish/network/osi_layered_defense.md`
- 方針（ユーザー確定済み）
  - クラウド: **一般原理＋AWS/Azure 対比**（既存 network シリーズと同じスタイル）
  - 構成: **1 つの参照構成（Internet → CDN/エッジ → LB → アプリ → DB）を、上の層から下へ縦に歩く**
  - L1/L2: **「クラウドが抽象化」として軽く**触れる程度
- 既出として再説明しないもの（`zenn/publish/network/*` で既述）
  - OSI/TCP-IP の層構造そのもの、カプセル化、PDU 名称
  - 「機器ごとに見る層が違う」（スイッチ L2 / ルータ L3 / FW L3-L4）
  - CIDR・サブネット・ルーティング・NAT・SG/NACL のステートフル・DNS 解決の基礎
  - 閉域（プライベートネットワーク）の作り方そのもの
- この記事の差別化点
  - 既存記事は **「つながる／閉じる（接続性）」** が主題。本記事は **「公開して、守る（防御）」** が主題。
  - 同じ層の地図を使うが、見る軸を「どこが壊れているか」から **「どこが狙われ、どこで止めるか」** に変える。

## 導入で解決する問題

「公開した瞬間から、システムは全層が攻撃面になる」。だが現場では、

- WAF を入れたのに L3/L4 のボリュメトリック DDoS で落ちた／逆に DDoS 対策をしたのに HTTP Flood (L7) で落ちた
- セキュリティグループ（L3/L4）を固めたのに、SQLi（L7）はそのまま通った
- TLS を「どこで終端するか」を決めずに、WAF も効かず、固定 IP も取れない構成になった
- ロードバランサを ALB / NLB のどちらにすべきか、層の観点で選べていない

——これらは全部「**その防御がどの層を見ているか／見ていないか**」を地図で持っていないことが原因。本記事は、参照構成を上の層から順に歩き、**各層に何が露出し、どの部品でどう止めるか**をイメージできる状態を作る。最終ゴールは「新しい構成を見たとき、層ごとに穴を埋められること」。

## 参照構成（記事全体で使う 1 枚の図）

```
[Internet]
   │  ← ここから下、全部が攻撃面
[L3/L4 DDoS 吸収：クラウド標準保護 / CDN・エッジ網]   ← Shield Standard / Azure DDoS / Cloudflare
[CDN・エッジ + WAF（L7 第一防御線）+ TLS 終端]        ← CloudFront/Front Door + WAF, TLS
[ロードバランサ（L4 NLB / L7 ALB）]                    ← 接続管理・固定IP・TLS・コンテンツ振り分け
[セキュリティグループ / NSG（L3/L4 マイクロ境界）]
[アプリ（L7 ロジック・認証・入力検証）]
[DB / 内部サービス（最深部・最小権限）]
```

各セクションは「この層に**何が露出**するか → **どの部品**が守るか → その部品の**守備範囲と限界**（＝次の層に残る穴）」の 3 点で書く。

## セクション構成

### 0. 導入 — 公開した瞬間、全層が攻撃面になる
- **主張**: 接続性の地図（既存記事）と同じ 7 層を、今度は「攻撃面と防御」の軸で読み替える。防御は単一の壁ではなく、層ごとに別の部品が別の脅威を止める **defense in depth**。
- **書くこと**: 既存 network シリーズ（特に OSI 記事）への接続を 2-3 行で。ゴール提示。参照構成図の提示。
- **根拠**: `research_overview.json`（defense-in-depth 要旨）, Exabeam OSI Layer Security（layered controls）。

### 1. 攻撃面の二分法 — 「体力を奪う層」と「論理を突く層」
- **主張**: 公開システムへの攻撃は大きく 2 系統。**インフラ層（L3/L4）= 量で殴る**（帯域・接続枯渇）と、**アプリ層（L6/L7）= 正規に見えるリクエストで殴る／論理の穴を突く**。両者は止める部品も場所も違うので、**片方だけ対策しても落ちる**。これが多層防御が必要な根本理由。
- **書くこと**: AWS Shield の公式区分（infrastructure layer attacks = L3/L4、application layer attacks = L7）を地図に重ねる。DDoS のトレンドが L3/4 → L7（HTTP/S）に移ってきた事実。SYN flood（L4・接続枯渇）と HTTP flood（L7・正規リクエスト氾濫）の対比。
- **根拠**: AWS `ddos-overview.html`（L3/4 infra vs L7 application、SYN flood の説明）, AWS WAF L7 DDoS blog（トレンド変化）, CISA DDoS ガイド（protocol-based L3/4 vs application L7）。

### 2. L3 — 入口でボリュームを吸収する（届かせない防御）
- **主張**: L3 の防御目的は唯一「**大容量を自分の前で吸収させ、origin に届かせない**」。ここは自前のサーバ増強では勝てない領域で、**クラウド/CDN のグローバル容量に外出しする**のが原則。クラウド標準保護（Shield Standard / Azure 既定のインフラ保護）は無料で全サイトに効く基礎で、可視化・コスト保護・専任対応が要るなら有償（Shield Advanced / Azure DDoS Protection）。
- **書くこと**: Shield Standard（自動 L3/L4・無料）vs Advanced（24/7・コスト保護・WAF 連携）。Azure は L3/4 を DDoS Protection、アプリ層は別途 WAF が必要という分担。Cloudflare Magic Transit のような「IP プレフィックスごと外部吸収」の選択肢。**判断軸**: 想定攻撃規模 × 可用性要件 × 運用対応力。
- **限界（次層へ残る穴）**: L3/4 を吸収しても、正規に見える L7 リクエストは素通りする。
- **根拠**: `research_overview.json`（Shield Standard/Advanced, Azure, Cloudflare Magic Transit）, Azure application-ddos-protection（既定のインフラ DDoS 保護）, AWS `ddos-overview.html`。

### 3. L4 — 接続をさばく場所と TLS をどこで終端するか
- **主張**: L4 の主役はロードバランサ。ここでの設計判断は 2 つ：**(a) L4(NLB) か L7(ALB) か**、**(b) TLS をどこで終端するか**。この 2 つは独立ではなく連動する。WAF とコンテンツ振り分けが要るなら L7 LB で TLS 終端（=平文を見られる）、固定 IP・超低レイテンシ・TCP 透過が要るなら L4 LB、という形で**要件が層を決める**。
- **書くこと**:
  - NLB（L4）: 静的 IP / Elastic IP、TLS 終端も可、ただし SG 非対応 → ターゲット側で制御。
  - ALB（L7）: ヘッダ操作・コンテンツルーティング・WAF 連携が前提、TLS パススルー非対応（=必ず終端する）、mTLS 対応。
  - TLS 終端位置の意味: **終端した所より手前は暗号、奥は平文**。WAF/L7 検査は「平文が見える所」でしか効かない → だから「エッジ or L7 LB で終端 → WAF → 必要なら再暗号化して origin へ」という縦深になる。
  - 固定 IP が要るが L7 機能も欲しい → Global Accelerator + ALB のような組み合わせ。
- **限界**: LB は「誰と接続するか・どこへ振るか」までで、リクエストの中身の正当性（SQLi 等）は判定しない。
- **根拠**: `research_overview.json`（NLB/ALB 判断軸, TLS 終端, mTLS, Global Accelerator）, AWS NLB TLS termination blog, ALB mutual-authentication doc。

### 4. L7 — アプリ層の防御線（WAF・レート制限・認証）
- **主張**: L7 こそ「正規の皮をかぶった攻撃」を捌く最重要層で、ここは **WAF（既知パターン）+ レート制限（量）+ アプリ自身の入力検証/認証（ロジック）** の 3 枚重ね。WAF は OWASP Top 10 系（SQLi/XSS 等）とマネージドルールでカバーするが、**WAF は万能ではなく、最終防御はアプリ側**。導入は **COUNT（観測）→ チューニング → BLOCK（遮断）** で段階移行するのが実務。
- **書くこと**:
  - WAF の守備範囲: OWASP Top 10、マネージドルール、ボット対策。エッジ WAF を第一防御線にしつつ origin 側でも重ねる二重構成。
  - レート制限: スライディングウィンドウ。AWS WAF は 5 分ウィンドウで IP カウント、最小閾値 10 req/5min まで設定可能（具体数値）。L7 DDoS（HTTP flood）の主対策。
  - L7 DDoS は WAF（Front Door Premium / App Gateway WAF v2 / Cloud Armor Adaptive Protection）で。CDN キャッシュがエッジで急増トラフィックを吸収して origin を守る副次効果。
  - 認証・認可は L7 のアプリ責務（WAF では守れない領域）。
- **限界**: WAF はパターンと量に強いが、業務ロジックの欠陥（権限昇格・IDOR 等）はアプリでしか塞げない。
- **根拠**: `extract_l7_edge_defense.json`（Azure L7 DDoS, Front Door/App Gateway）, `research_overview.json`（WAF COUNT→BLOCK, rate-based 5min/10req, Cloud Armor Adaptive）, AWS WAF rate-based lower limits, OWASP Top 10。

### 5. L1/L2 と最深部 — クラウドが抽象化する層と、内側の最小権限
- **主張（短く）**: L1/L2（物理・データリンク）はクラウドが**責任共有モデル**で引き受ける領域で、利用者が直接守るのは基本 L3 以上。ただし「外周を固める」だけでは不十分で、**内側ほど最小権限**（DB は LB/アプリからのみ、SG はマイクロ境界、内部も暗号化）にして、1 層破られても被害を局所化する。
- **書くこと**: 責任共有モデルで L1/L2 は事業者側。内側の縦深（SG マイクロセグメンテーション、DB を公開しない、east-west も絞る）。ゼロトラスト的に「内側も信用しない」発想。
- **限界/注記**: ゼロトラスト(ZTNA)の具体手順は本記事の範囲外（概念に留める）。
- **根拠**: Exabeam OSI Layer Security（physical/data-link mitigations, defense-in-depth）, `research_overview.json`（内側の最小権限・Evidence Gaps として ZTNA 詳細は除外）。

### 6. まとめ — 層ごとの「守備担当表」と設計チェックリスト
- **主張**: 最後に 1 枚の表で「層 / 露出する脅威 / 守る部品（AWS・Azure）/ 残る穴」を俯瞰。新しい構成を見たら、この表を上から当てて穴を探せる状態にする。
- **書くこと**:
  - 層別 守備担当表（L3=DDoS 吸収 / L4=LB・TLS終端 / L7=WAF・レート・認証 / 内側=最小権限）。
  - 設計チェックリスト（標準 DDoS 保護は効いているか / 固定IP・L7 可視化の要否で LB 選択 / TLS 終端位置と WAF の位置は整合しているか / WAF は COUNT で観測してから BLOCK か / DB・内部は最小権限か / ログ・メトリクスとアラート閾値）。
  - 運用の一言: WAF メトリクス（BlockedRequests 急増）でアラート、ログは集中管理して継続チューニング。
- **根拠**: `research_overview.json`（意思決定チェックリスト、監視・コスト判断）。

## トーン・分量の方針
- 中級者前提。既出の基礎は「（既存記事参照）」で軽く流し、**判断軸・限界・残る穴**に紙幅を割く。
- 各層で「できること」だけでなく「**この部品では守れないこと**」を必ず書く（= 多層防御の動機を毎セクションで補強）。
- AWS/Azure の対比は表または並記で。具体数値（10 req/5min 等）は出典付きで入れる。
- 全体 4000〜6000 字程度を目安。

## frontmatter（publish 時の予定）
- `title`: 「7層のどこで守るか」— Web公開システムの多層防御を層の地図で設計する
- `emoji`: 🛡️
- `type`: tech
- `topics`: ["networking", "security", "aws", "azure", "infrastructure"]（既存 network/closed_network 記事のタグを再利用）
- `published`: false

## 不足情報・追加調査の余地（publish 前に必要なら補う）
- AWS WAF rate-based の「10 req/5min 最小」は 2024 アップデート。publish で断定する前に出典 URL を本文脚注に残す（`research_overview.json` 内 [12]）。
- Cloud Armor Adaptive Protection / Azure DRR の細部は概念紹介に留める（深掘りは範囲外）。
- ゼロトラスト具体手順は意図的に除外（Evidence Gap）。

---

次の段階: この構成へのレビュー・修正指示を待って、`zenn/publish/network/osi_layered_defense.md` に本文を書きます。
