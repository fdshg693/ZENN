---
title: "Azure × Entra ID 認証の歩き方 ── 「誰が呼ぶか」で組み立てる一枚の地図"
status: plan
---

## この plan の位置づけ

- 目的: 「Azure で Entra を使って認証」と言われたときに、フローの違いを**1枚の地図**で読み解けるメンタルモデルを作る。
- 粒度・対象読者レベルは `zenn/publish/auth/obo_flow.md` に揃える(OAuth/OIDC 基礎は既知の読者)。
- 細かいサービス差異は「注意のいるものだけ」最小限。網羅リファレンスにはしない。
- 処理が複雑な箇所は Mermaid で可視化する。
- スコープ確定事項(ユーザー回答済み):
  - Managed Identity / Workload Identity Federation を**主要な枝として正面から扱う**。
  - 最後の具体例は **4パターン全部**(SPA→BFF→API→Graph / Azure上App→Key Vault・Storage(MI) / GitHub Actions→Azure(WIF) / デーモン→Graph(client credentials))。

## 成果物(2ファイル構成)

ユーザー指示により、本文は **2ファイル**に分割する(同階層 `zenn/publish/auth/`)。

1. **本編** `zenn/publish/auth/entra_auth_mental_model.md`
   - 下記「構成案」の **導入〜6章 + 8章(まとめ)**。メンタルモデルの幹。
   - 7章(具体例)は本編では概要+別記事への導線のみ。
2. **具体例編(別ファイル)** `zenn/publish/auth/entra_auth_patterns_examples.md`
   - 7章を独立記事として**みっちり**展開(各例で認証フローをしっかり説明 + 関連留意事項 + 関連サービス + 代替構成)。
   - 本編とは相互リンク。frontmatter は独立。

## 想定読者

- OAuth 2.0 / OIDC の基礎(認可コード、アクセストークン、`aud`、`scope`)は既知。
- Azure / Entra で認証をいくつか触ったが、フロー全体が地図として繋がっていない人。

## 記事で答える問い

1. Entra 認証は結局「何をしている」のか(共通の幹)。
2. なぜフローが何種類もあり、どれを選ぶかは何で決まるのか。
3. 主体ごとの典型・制約・注意点は何か。

## 扱う / 扱わない

- 扱う(幹): トークンの正体(ID token vs access token、`aud`、scope vs roles=delegated vs application permission)、app登録/サービスプリンシパル/マネージドIDの関係、consent。
- 扱う(枝): ユーザーサインイン(auth code+PKCE)、デーモン(client credentials)、代理(OBO ※既存記事へ委譲して軽く)、Azureリソース(Managed Identity)、外部ワークロード(Workload Identity Federation)。
- 扱う(サービス差異・最小限): App Service/Functions/Container Apps の組み込み認証(Easy Auth)、Azureリソース宛てトークンの `aud`(リソース値)、Key Vault の RBAC vs アクセスポリシー、MI はローカルで動かない。
- 扱わない: B2C / External ID の詳細、Conditional Access の細目、各言語 SDK 実装チュートリアル、プロトコル全文リファレンス、device code/ROPC などレガシー寄りフローの深掘り(地図上に位置づけるだけ)。

---

## 構成案(セクション一覧と各セクションの主張・根拠)

### 導入: トークンが何種類も出てくる理由
- 主張: 「サインイン」「デーモン」「マネージドID」「フェデレーション」…と名前が乱立して見えるが、**違うのは"誰が呼ぶか"だけ**。幹は1本。この記事はその幹を先に立てる。
- 根拠: `temp\azure_entra_auth\extract_core_overview.json`(v2-overview / app types / auth-flows-app-scenarios)

### 1. 一枚の地図 ── Entra 認証の共通の幹
- 主張: どのフローも「**プリンシパルが、資格情報で身元を証明し、宛先(`aud`)とスコープ/ロールを持つトークンを Entra から受け取り、保護リソースがそれを検証する**」に還元できる。Entra は中央のトークン発行者(IdP)。
- 図: Mermaid(principal → credential → Entra token endpoint → token(aud, scope/roles) → resource validates)。
- 補足: 認証(authn)と認可(authz)を Entra に委譲することで SSO / Conditional Access / MFA が効く、という位置づけ。
- 根拠: v2-overview, authentication-vs-authorization, app types
  - `temp\azure_entra_auth\extract_core_overview.json`, `temp\azure_entra_auth\search_entra_overview.json`

### 2. トークンの正体 ── ここを外すと地図が読めない
- 主張:
  - **ID token** =「誰がサインインしたか」を自分(クライアント)が確認するためのもの。
  - **access token** =「保護リソースを呼ぶための鍵」。宛先は `aud`、許可範囲は `scp`(scope)か `roles`。
  - **delegated permission(scope)** = ユーザーの委任権限。**application permission(app role / `roles`)** = アプリ自身の権限。「ユーザーがいるか」で使える権限の種類が変わる。
- 図: Mermaid または表(ID token / access token / scp / roles の対比)。
- 根拠: access-token-claims-reference, id tokens, client-creds(「ユーザーがいないと delegated は使えず application permission を使う」), grant-admin-consent(delegated vs application の定義)
  - `temp\azure_entra_auth\extract_tokens_permissions.json`, `temp\azure_entra_auth\extract_flows.json`

### 3. プリンシパルの入れ物 ── app登録・サービスプリンシパル・マネージドID
- 主張:
  - **アプリ登録(application object)** = 全テナント共通のテンプレ(グローバル定義)。
  - **サービスプリンシパル** = 各テナントでの実体(そのテナントで何ができるか・誰がアクセスできるか)。
  - **マネージドID** = 資格情報管理が不要な特殊なサービスプリンシパル。
  - 同意(consent)= サービスプリンシパルに権限が"効く"ようにする操作。
- 図: Mermaid(application object 1 ── * service principal、managed identity は SP の一種)。
- 根拠: app-objects-and-service-principals, managed-identities overview(「managed identity is a special type of service principal」), workload-identities-overview
  - `temp\azure_entra_auth\extract_tokens_permissions.json`, `temp\azure_entra_auth\extract_mi_wif.json`, `temp\azure_entra_auth\search_managed_identity.json`

### 4. 主体別の枝 ── 「誰が呼ぶか」で5パターン
各サブセクションは「いつ使う / トークンの出どころ / 注意点」を1セットで。各サブセクションに Mermaid。

#### 4-1. 人間ユーザーがサインインする ── 認可コードフロー + PKCE(delegated)
- 主張: ブラウザ等のリダイレクト可能な user-agent を起点に、ユーザー委任のトークンを得る。SPA / Web / モバイル/デスクトップの標準。
- 注意: SPA は `spa` リダイレクトタイプ + PKCE(implicit は非推奨)。
- 根拠: v2-oauth2-auth-code-flow → `temp\azure_entra_auth\extract_flows.json`

#### 4-2. アプリ自身で呼ぶ ── クライアントクレデンシャル(application)
- 主張: ユーザー不在。アプリがシークレット/証明書/フェデレーション資格情報で身元を証明し、**app role(application permission)** で動く。
- 注意: 資格情報をソースに埋めない。confidential client 前提。
- 根拠: v2-oauth2-client-creds-grant-flow → `temp\azure_entra_auth\extract_flows.json`

#### 4-3. ユーザーの代理で下流を呼ぶ ── OBO(delegated を引き回す)
- 主張: 中間層 API が、自分宛てユーザートークンを下流 API 宛ての新トークンに交換。**詳細は既存記事 `obo_flow.md` に委譲**し、ここでは地図上の位置づけだけ(簡略 Mermaid)。
- 根拠: 既存記事 `zenn/publish/auth/obo_flow.md`、v2-app-types

#### 4-4. Azure リソースが呼ぶ ── マネージドID(資格情報レス)
- 主張: VM / App Service / Function などの Azure リソースに ID を付与し、**シークレットを一切持たずに**トークンを取得。system-assigned / user-assigned の2種。トークンは IMDS 系エンドポイントから取得し、`resource` パラメータがそのまま `aud` になる。
- 図: Mermaid(Azureリソース → ローカルIMDSエンドポイント → token(aud=対象サービス) → Key Vault/Storage 等)。
- 根拠: managed-identities overview, how-to-use-vm-token(IMDS `169.254.169.254`, `resource`→`aud`), overview-for-developers
  - `temp\azure_entra_auth\extract_mi_wif.json`, `temp\azure_entra_auth\extract_mi_token.json`

#### 4-5. 外部ワークロード/別IdPから呼ぶ ── Workload Identity Federation(FIC)
- 主張: GitHub Actions / 他クラウド / 外部 Kubernetes など、Azure 外のワークロードが「別IdP のトークン」を Entra のトークンに**交換**して呼ぶ。シークレット不要。信頼関係(FIC)を app登録 or user-assigned MI に設定。
- 図: Mermaid(外部ワークロード → 外部IdP がトークン発行 → Entra が信頼関係+OIDC issuer 検証 → access token 発行)。
- 注意: MI を FIC に使う場合は上限20件。
- 根拠: workload-identity-federation, workload-identities-overview
  - `temp\azure_entra_auth\extract_mi_wif.json`, `temp\azure_entra_auth\search_managed_identity.json`

### 5. どれを選ぶか ── 判断フロー
- 主張: 「ユーザーがいるか?」「呼ぶのは Azure リソース上か?」「外部IdP のトークンがあるか?」「下流に委任を引き回すか?」の数問で枝が決まる。
- 図: Mermaid flowchart(decision tree)。
- 根拠: authentication-flows-app-scenarios(シナリオ対応表)→ `temp\azure_entra_auth\search_entra_overview.json`, `extract_core_overview.json`

### 6. サービス差異で「注意のいる」点だけ
- 主張(最小限・箇条書き中心):
  - **組み込み認証(Easy Auth)**: App Service / Functions / Container Apps は OAuth フローを"前段"で肩代わりし、`X-MS-CLIENT-PRINCIPAL` 等のヘッダで身元を渡す。自前 JWT 検証を書かない選択肢。Container Apps は App Service と同基盤だが差異あり。注意: ヘッダ信頼=Easy Auth を迂回されない経路設計が前提。
  - **Azureリソース宛てトークンの `aud`**: 対象サービスごとにリソース値が決まる(例 ARM=`https://management.azure.com`、Key Vault=`https://vault.azure.net`)。MI/SDK で `resource`/`scope` を取り違えると `aud` 不一致で弾かれる。
  - **MI はローカルで動かない**: IMDS は Azure 上でのみ到達可能(`169.254.169.254` / App Service は `IDENTITY_ENDPOINT`+`IDENTITY_HEADER`)。ローカル開発は `DefaultAzureCredential` 等で別資格情報にフォールバック。
  - **Key Vault は RBAC とアクセスポリシーが別系統**: MI に "Key Vault Secrets User" 等の RBAC ロールを与える(RBAC 有効化でアクセスポリシーは無効)。
- 根拠: configure-authentication-user-identities, container-apps/authentication, app-service/overview-security, how-to-use-vm-token, azure-arc managed-identity-authentication, MI トークン取得 Q&A
  - `temp\azure_entra_auth\extract_app_service_auth.json`, `temp\azure_entra_auth\extract_mi_token.json`

### 7. 具体例 ── 重要パターンの適用例(★別ファイル `entra_auth_patterns_examples.md`)

本編では「4つの典型を別記事でみっちり扱う」導線のみ置く。具体例編の各例は以下を1セットで深掘りする:
**(a) 構成図(Mermaid)/ (b) 認証フローの説明(どの枝の組み合わせか・トークンの aud/scope)/ (c) 関連する留意事項 / (d) 関連サービス / (e) 考えられる別構成**。

- **7-1. SPA → BFF → 業務API → Microsoft Graph**
  - 認証: auth code+PKCE で入口、OBO で委任を下流/Graph へ。
  - 留意事項: ブラウザにトークンを置くリスク、SPA は confidential になれない、認証用と認可用で**アプリ登録を分ける**設計。
  - 関連サービス: API Management(JWT 検証/透過プロキシ)、Easy Auth、Microsoft.Identity.Web(`IDownstreamApi`/YARP)。
  - 別構成: SPA が Graph を直接叩く(委任・OBO 不要だが権限がブラウザに露出)/ APIM でトークン検証を前段化。
  - 根拠: `extract_bff_spa.json`(backends-for-frontends, two app registrations, APIM auth overview), 既存 `obo_flow.md`
- **7-2. Azure 上の App Service/Function → Key Vault / Storage**(Managed Identity)
  - 認証: MI で資格情報レス、IMDS 系から取得、`resource`→`aud`=対象サービス。
  - 留意事項: ローカルでは IMDS 不可 → `DefaultAzureCredential` の探索順でフォールバック、system vs user-assigned の選択(chicken-and-egg)、Key Vault は RBAC ロール `Key Vault Secrets User`。
  - 関連サービス: Key Vault references(コードレスで App Settings に注入)、Azure SQL/Storage の Entra 認証。
  - 別構成: Key Vault references で完全コードレス / user-assigned を複数リソースで共有。
  - 根拠: `extract_mi_wif.json`, `extract_mi_token.json`, `extract_kv_defaultcred.json`(key-vault-references, DefaultAzureCredential order, tutorial)
- **7-3. GitHub Actions → Azure デプロイ**(Workload Identity Federation)
  - 認証: GitHub OIDC トークン → Entra が信頼(FIC)を検証して access token を発行。`azure/login@v2`、`permissions: id-token: write`、FIC の `subject`(`repo:org/repo:environment:Name`)。
  - 留意事項: シークレット運用の廃止、`subject`/`issuer` の厳密一致、FIC を app登録 or user-assigned MI どちらに付けるか。
  - 関連サービス: Azure CLI/PowerShell action、Deployment Center 生成ワークフロー。
  - 別構成: サービスプリンシパル+シークレット(非推奨)/ user-assigned MI を FIC 主体に。
  - 根拠: `extract_gha_oidc.json`(connect-from-azure-openid-connect, workload-identity-federation-create-trust, deploy-github-actions)
- **7-4. デーモン/バッチ → Microsoft Graph / 自社API**(client credentials)
  - 認証: ユーザー不在、アプリ自身の資格情報、application permission(app role)。
  - 留意事項: シークレットより証明書/フェデレーション資格情報、管理者同意が必須、application permission は広範になりがち(最小権限)。
  - 関連サービス: Azure 上で動くなら MI を FIC 化して client credentials のシークレットを消す。
  - 別構成: Azure 上なら MI 直接 / FIC でシークレットレス client credentials。
  - 根拠: `extract_flows.json`(client-creds), `extract_tokens_permissions.json`(grant-admin-consent), `extract_mi_wif.json`(MI as FIC)

### 8. まとめ ── 地図の再掲と判断の問い
- 主張: 「誰が呼ぶか(ユーザー/アプリ/Azureリソース/外部ワークロード)」→「資格情報は何か」→「トークンの `aud`/scope は何か」の3点を順に問えば、どのフローでも筋が通る。トークンの横流しではなく、宛先付きトークンの発行・検証である、という一点を持ち帰ってもらう。

### 参考リンク(本文末)
- Microsoft identity platform overview
- Application types / Authentication flows and app scenarios
- OAuth 2.0 authorization code flow / client credentials flow / On-Behalf-Of flow
- Access token claims reference / Apps & service principals
- Managed identities for Azure resources(overview / how-to-use-vm-token / for developers)
- Workload identity federation concepts / Workload identities overview
- App Service authentication(user identities)/ Container Apps authentication
- 既存記事: OBO フロー再入門(`zenn/publish/auth/obo_flow.md`)

---

## 不足情報・追加調査の余地(任意)
- 具体例の数値(トークン寿命、FIC 上限の最新値)は publish 時に必要なら個別 extract で裏取り(現状: FIC=20件は確認済み)。
- device code / ROPC は地図の隅に位置づけるのみ。深掘り要望があれば追加。
