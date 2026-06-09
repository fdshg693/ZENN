---
title: "OBO（On-Behalf-Of）フロー再入門 ── トークン交換は知ってる人のための『使いどころ』ガイド"
status: plan
---

## この plan の位置づけ

- 重心: **「概念のおさらい」より「従来フローとの違い」と「向く/向かない場面の判断」を主役に**（ユーザー確認済み）
- 実装の軸: **Microsoft Entra ID を主軸にしつつ、概念は汎用的に書く**（ユーザー確認済み）
- 「最近の発展」枠: **Agent ID（AIエージェントの代理OBO）に軽く触れる**（ユーザー確認済み）
- コード量: **最小スニペット（トークン交換のraw HTTPリクエスト1〜2個）まで**。SDK実装の詳細には踏み込まない（ユーザー確認済み）
- 想定読者: OAuth 2.0の認可コードフロー・アクセストークン・トークン交換の基本は理解している層。「APIがさらに別のAPIを呼ぶ」構成で権限の引き回しに悩む人
- 分量目安: 約280〜360行（他記事より短めの単発解説。参照 `zenn/publish/network/closed_network.md` 規模）
- スタイル: Tips寄せ集めではなく、「OBO＝aud付き委任トークンの交換」という1つの軸から、違い・使いどころ・落とし穴を一本で導く

## 中心の主張（記事の軸）

> OBOフローの正体は「**中間層API（confidential client）が、自分宛て（aud=自分）に届いたユーザーのアクセストークンを、下流API宛ての新しいアクセストークンに交換する**」こと。
>
> ポイントは2つ。(1) 単なるトークンの**横流し（パススルー）ではない** ── トークンには宛先（`aud`）があり、API Bに届けるにはB宛てのトークンに作り直す必要がある。(2) 交換後もトークンは**ユーザーの委任（delegation）の文脈を保持する** ── 「アプリ自身の権限」ではなく「ユーザーの権限でアプリが代理する」が引き回される。
>
> だから OBO が刺さるのは「機密クライアントである中間層Web APIが、サインイン中ユーザーの権限で下流API/Graphを呼ぶ」場面に限られ、SPA・モバイル・デーモン・単純なゲートウェイには向かない／使えない。

---

## 想定読者 / 前提 / 扱う範囲

- 前提知識: 認可コードフロー、アクセストークン（JWT）、`aud`/`scope`、トークン交換という言葉は知っている
- 答える問い:
  1. OBOは結局「何を何に交換している」のか（おさらい）
  2. 従来フロー（認可コード / クライアントクレデンシャル）と**何が決定的に違う**のか
  3. **どこで使い、どこでは使わない／使えない**のか（制約・アンチパターン）
- 扱わない: MSAL/Microsoft.Identity.Web の詳細実装、管理画面の手順、SAML assertion版OBOの詳細（軽く触れるのみ）

---

## セクション構成

### 0. 導入：トークンを「そのまま転送」したくなる瞬間
- 主張: APIがさらに別のAPIを呼ぶとき、受け取ったトークンをそのまま下流に転送したくなる。だがそれは（多くの場合）動かないし、動いてはいけない。なぜか？ から入る
- 根拠: OBO main doc（「web API using an identity other than its own to call another web API」）
- 出力: `temp/obo_flow/extract_obo_main.json`

### 1. かんたんなおさらい：OBOは「aud付きトークンの交換」
- 主張:
  - OBO = 中間層APIが、自分宛てに来たユーザートークン（token A, `aud`=API A）を、下流API宛てのトークン（token B, `aud`=API B）に交換する
  - 5ステップの流れを図示（client → API A → 識別基盤 → API B）
  - これは OAuth で言う **delegation（委任）**：ユーザーのID・権限をリクエストチェーンに引き回す
- 根拠: OBO main doc のProtocol diagram / 5ステップ記述
- 出力: `extract_obo_main.json`

### 2. 最小スニペット：実際のトークン交換リクエスト
- 主張: 何が交換されているかをHTTPで具体的に見る。キモは3パラメータ
  - `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`（token-exchangeではない点に後で触れる）
  - `assertion=<受け取ったアクセストークン>`（これが「交換に出す」トークン。`aud`は自分でなければならない）
  - `requested_token_use=on_behalf_of`
  - クライアント認証（`client_assertion`（証明書）または `client_secret`）が必須＝**confidential clientであることが前提**
- 根拠: OBO main doc のリクエストパラメータ表 + raw HTTPサンプル
- 出力: `extract_obo_main.json`

### 3. 従来フローと何が違うのか（対比表）
- 主張: 「誰の権限で・誰が呼ぶ・トークンの宛先は誰か」で3フローを並べる
  - 認可コードフロー: ユーザーがサインインし、クライアントがユーザー委任でAPIを呼ぶ（チェーンの入口）
  - クライアントクレデンシャル: **ユーザー不在**。アプリ自身の資格情報で、アプリの権限（application permission / app role）で呼ぶ。委任ではない（two-legged OAuth, RFC 6749）
  - OBO: 受け取ったユーザー委任トークンを**作り直して**チェーンを延長する。委任を保ったまま下流へ
  - 決定的な違い: OBOは「新しい認証」ではなく「既存の委任コンテキストを別aud向けに再発行」する操作
- 根拠: client credentials doc（"use its own credentials, instead of impersonating a user" / "no user → can't use delegated permissions, must use application permissions"）、auth code doc（"on behalf of the user", redirect必須）、OBO main doc
- 出力: `extract_compare_flows.json`, `extract_obo_main.json`

### 4. RFC 8693（Token Exchange）との関係 ── 「トークン交換」だが同じではない
- 主張: 読者が知っている「トークン交換」とOBOの関係を整理
  - RFC 8693 は汎用的なToken Exchange: `grant_type=...token-exchange`、`subject_token`/`actor_token`/`requested_token_type`、delegation と impersonation を区別、`may_act`/`act` クレーム
  - 一方 Entra の OBO は **`jwt-bearer` グラント**（assertionに受領トークンを載せる）で実装されており、RFC 8693のtoken-exchangeグラントとはパラメータ体系が別
  - 「概念としてのトークン交換／委任」は共通だが、**実装プロファイルが違う**。混同しないことが落とし穴回避になる
- 根拠: RFC 8693（subject_token/actor_token/may_act 定義）、OBO main doc（jwt-bearer grant_type）
- 出力: `extract_rfc8693.json`, `extract_obo_main.json`

### 5. 向く場面 ── OBOが正解になるとき
- 主張:
  - 機密クライアントである**中間層Web API**が、サインイン中ユーザーの権限で下流API（自社API/Microsoft Graph等）を呼ぶ
  - 下流でも「誰のデータか」を保ちたい（監査・最小権限・ユーザー単位の認可をチェーン全体で効かせたい）
  - アプリ種別ドキュメントが示す典型: 「web APIがさらに別のdownstream web APIを呼ぶ」
- 根拠: app-types doc（"web APIs can take advantage of OBO ... exchange an incoming access token for another"）、OBO main doc
- 出力: `search_obo_overview.json`（app-types抜粋）, `extract_obo_main.json`

### 6. 向かない／使えない場面 ── ここを外すと事故る
- 主張（アンチパターンを列挙、各々に理由）:
  - **SPA・モバイル等パブリッククライアント**: OBOはクライアント認証（secret/cert）必須＝confidential client前提。ブラウザ内に秘密は置けない → 使えない
  - **ユーザー不在のデーモン/バッチ**: 委任の元になるユーザートークンがない → OBOではなくクライアントクレデンシャル
  - **単純なAPIゲートウェイ的パススルー**: 同じaud・同じ下流で良いなら交換不要。OBOはあくまで「別aud向けに作り直す」必要があるときの仕組み
  - **`aud`不一致トークンの流用**: 自分宛てでないトークン（例: Graph宛てトークン）をOBOに出すのは不可。受け取ったAPIは拒否すべき（典型エラー源）
  - **多段OBOの濫用**: チェーンが深くなるほどスコープ・同意・トークン寿命管理が複雑化。設計の臭い
- 根拠: OBO main doc（assertion must have aud of this app / can't redeem a token meant for another app）、client credentials doc（no user → application permissions）、auth code doc（spa redirect とclient credentialの排他）
- 出力: `extract_obo_main.json`, `extract_compare_flows.json`

### 7. 最近の発展：AIエージェントの代理（Agent ID OBO）＜軽く＞
- 主張: エージェントがサインイン中ユーザーの代理で動く文脈にも標準OBOが拡張されている
  - Agent identity が delegated permission を割り当てられ、ユーザー同意のうえでOBO（agent-specific impersonation）
  - サポートされるgrant: `client_credential` / `jwt-bearer` / `refresh_token`。client credentialに**マネージドID（FIC）**も使える
  - 発展領域なので深入りせず「OBOの委任モデルがエージェント時代にどう延長されるか」の視点提示に留める＋公式SDK利用推奨に言及
- 根拠: agent OBO doc
- 出力: `extract_agent_obo.json`

### 8. まとめ：判断チェックリスト
- 主張: 「confidential clientか？／ユーザー委任を引き回したいか？／下流のaudは別か？」の3問でOBOの要否を判断できる、で締める
- 根拠: 上記全体の統合

---

## frontmatter（publish時）案

```yaml
title: "OBO（On-Behalf-Of）フロー再入門 ── トークン交換は知ってる人のための『使いどころ』ガイド"
emoji: "🪪"
type: "tech"
topics: ["oauth", "oidc", "security", "azure", "認証"]
published: false
```

- タグは既存規約に合わせ lowercase ASCII を基本（`security`, `azure` は既存記事で使用実績あり）。`oauth`/`oidc` を新規追加。5枠目は `認証`（日本語）に確定（ユーザー確認済み）

## 確定事項（ユーザー確認済み）

- 5枠目タグ: `認証`（日本語）
- 図: mermaid シーケンス図を1枚（セクション1）
- セクション7（Agent ID）: 「軽く触れる」の分量で確定
