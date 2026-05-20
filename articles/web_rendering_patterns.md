---
title: "WEBページの配信方式を整理する — 静的・SSR・SSG・ISR・ハイブリッドを尺度から読み解く"
emoji: "🧭"
type: "tech"
topics: ["web", "frontend", "ssr", "ssg", "performance"]
published: false
---

## この記事について

Web アプリを作っていると、**静的配信 / SSG / SSR / CSR / ISR / ハイブリッド** という言葉が当たり前のように飛び交います。
が、「結局それぞれどう違うのか」「自分のプロダクトではどれを選べばいいのか」を、チームの後輩に 5 分で説明できるかと言われると、意外と難しい。

フレームワーク(Next.js、Nuxt、Astro、Remix、SvelteKit…)のドキュメントを読むと、それぞれ独自の用語で説明されていて、**「そもそも何と何を比較しているのか」が抽象的に整理されていない** ことが多いです。

この記事では、フレームワーク固有の話には踏み込まず、

1. Web ページを届けるときに、そもそも **何を評価しているのか**(尺度)
2. 配信処理のどこを **動かせるのか**(変数)
3. その変数の組み合わせとして、**各方式は何を選び、何を捨てているのか**

という順で整理します。対象読者は、HTTP / HTML / JavaScript の基礎は分かるが、配信方式の選択に自信が持てない Web 開発者です。

## 1. 前提: Web ページを届ける処理の最小モデル

まず全員が同じ絵を共有するところから始めます。

ブラウザがある URL を開くとき、ざっくり以下のことが起きます。

1. ブラウザが HTTP リクエストを送る
2. サーバー or CDN が **HTML** を返す
3. ブラウザが HTML を解釈し、参照されている CSS / JS / 画像を取得する
4. JavaScript が実行され、ページが **インタラクティブになる**

配信方式の違いは、この流れの中の「**HTML をいつ、どこで組み立てるか**」と「**ブラウザ側でどれだけ後から HTML を足すか**」のバリエーションにすぎません。これを軸に据えておくと、後の話が追いやすくなります。

> The choice of rendering architecture affects performance, user experience, and SEO. Tools and frameworks let you pick where and when HTML is produced.
> — [Rendering on the Web | web.dev](https://web.dev/articles/rendering-on-the-web)

## 2. Web ページを評価する 5 つの尺度

方式を比較する前に、**何を良し悪しの物差しにしているのか** を明確にします。Web ページの配信については、実務的には以下の 5 つを押さえれば十分です。

### 2.1 初期表示の速さ

代表的な指標は以下の 3 つ。

- **TTFB (Time To First Byte)**: 最初の 1 バイトが返るまでの時間。サーバー側の処理時間が効く
- **FCP (First Contentful Paint)**: 何かしらのコンテンツが画面に出るまでの時間
- **LCP (Largest Contentful Paint)**: メインコンテンツが出るまでの時間。Core Web Vitals の一つ

これは「ユーザーが白画面を見せられる時間」の指標です。

### 2.2 操作可能になる速さ

- **TTI (Time To Interactive)**: ページがちゃんと操作を受け付けるようになるまでの時間
- **INP (Interaction to Next Paint)**: 実際に操作したときの反応速度

HTML が見えても、JavaScript が重くてクリックを受け付けない状態(いわゆる**ハイドレーション中**)はここに効いてきます。

### 2.3 検索エンジン対応(SEO)

- クローラーが**初期 HTML の時点でコンテンツを読める**か
- Core Web Vitals(LCP / CLS / INP)がランキング要因になっている

最近の Google クローラーは JavaScript を実行して SPA もインデックスできますが、**CWV で不利になりやすい**のは依然として事実です。

> Even though Google can render client-side JavaScript, your Core Web Vitals are still a major factor in determining your ranking.
> — [How to choose the best rendering strategy for your app | Vercel](https://vercel.com/blog/how-to-choose-the-best-rendering-strategy-for-your-app)

### 2.4 データ鮮度とパーソナライズ

- **鮮度**: コンテンツがどれくらい最新である必要があるか(数分? 数時間? 毎リクエスト最新?)
- **パーソナライズ**: ユーザーやセッションごとに内容が変わるか

ここは「配信前にキャッシュできるか」に直結する尺度です。完全に個別化された画面は、原理的に事前生成できません。

### 2.5 運用コスト・スケーラビリティ

- サーバーの CPU / メモリ負荷
- インフラ費(オリジンサーバーの台数、関数実行回数)
- **ビルド時間**(ページが多くなると爆発する)
- **配信経路**: CDN に置いてエッジから返せるのか、オリジンまで毎回往復するのか

同じトラフィックでも、方式によって必要なインフラ費用は桁で変わります。

この 5 尺度が、以下で登場する各方式を見るときの共通の物差しになります。

## 3. 配信処理の中で「動かせる変数」は 3 つだけ

一見方式がたくさんあるように見えても、触っているのは以下の 3 変数です。

### 変数 A: HTML を生成するタイミング

- **build 時**: リリース前にまとめて生成する
- **request 時**: ユーザーのリクエストが来たときに生成する
- **ブラウザ実行時**: JavaScript が動いてから組み立てる

### 変数 B: HTML を組み立てる場所

- **CDN / ファイルサーバー**(すでに出来上がった HTML を置いておくだけ)
- **アプリケーションサーバー / 関数**(サーバー側で動的に組み立てる)
- **ブラウザ**(JavaScript が DOM を操作する)

### 変数 C: どこでキャッシュされるか

- **CDN のエッジ**: 地理的に近いところから返せる、最速・低コスト
- **オリジンの手前**: ある程度軽減されるが、配信距離は遠い
- **キャッシュなし**: 毎回計算する

各配信方式は、この 3 変数の **どこを選ぶかの組み合わせ** として説明できます。先に一度このマッピングを頭に入れておくと、次章の読解が非常に楽になります。

| 方式 | A: いつ生成 | B: どこで生成 | C: キャッシュ |
|------|------|------|------|
| 静的配信 | 人間が事前に書く | なし(CDN が返すだけ) | CDN |
| SSG | build 時 | ビルドサーバー | CDN |
| SSR | request 時 | アプリサーバー | 原則なし(部分的に可) |
| CSR | ブラウザ実行時 | ブラウザ | 空 HTML は CDN |
| ISR | build 時 + 期限後に request 時 | ビルド + アプリサーバー | CDN(期限付き) |
| ハイブリッド | ページごとに切替 | ページごとに切替 | ページごとに切替 |

## 4. 各方式のメリット・デメリット・ユースケース

ここから本題です。各方式を **「どの尺度が強く、どの尺度を捨てているか」** の形で読んでいきます。

### 4.1 静的配信 (Pure Static)

手書きの HTML / CSS / 画像をそのまま CDN に置き、ブラウザへ返すだけのもっとも素朴な方式です。ビルドもデータ取得も介さず、**ファイルがそのまま配信物** です。

- 強い尺度
  - 初期表示(TTFB / FCP / LCP すべて速い)
  - 運用コスト(サーバーサイド処理がほぼ不要、CDN のエッジから返せる)
  - 堅牢性とセキュリティ(動く処理が少ないぶん、壊れにくい・攻撃面が小さい)
- 捨てている尺度
  - 動的データ・パーソナライズ(原理的に不可)
  - ページ数が多い場合の管理性(テンプレート機能がないため、手動整合)
- 向くケース
  - キャンペーン LP、採用ページ、シンプルなコーポレートサイト
  - 数十ページ程度の告知サイトやドキュメント

> Static rendering ... achieves a consistently fast TTFB, because the HTML for a page doesn't have to be dynamically generated on the server.
> — [Rendering on the Web | web.dev](https://web.dev/articles/rendering-on-the-web)

### 4.2 SSG (Static Site Generation)

ビルド時に、データ取得もテンプレート適用も済ませて **大量の静的 HTML をまとめて生成** します。配信時の挙動は「静的配信」とまったく同じで、CDN からそのまま返せます。

- 強い尺度
  - 初期表示(静的配信と同等に速い)
  - SEO(HTML がすでに完成している)
  - スケーラビリティ(CDN 任せにできる)
- 捨てている尺度
  - 鮮度(更新にはリビルド・再デプロイが必要)
  - ビルド時間(ページ数が多いと数十分〜になる)
  - パーソナライズ(ユーザーごとに変えられない)
- 向くケース
  - ブログ、技術記事サイト、ドキュメントサイト
  - ある程度固定された商品カタログ、マーケティングサイト

Next.js 公式も、以下のようなものを SSG の代表例として挙げています。

> You can use Static Generation for many types of pages, including: Marketing pages / Blog posts and portfolios / E-commerce product listings / Help and documentation.
> — [Static Site Generation (SSG) | Next.js](https://nextjs.org/docs/pages/building-your-application/rendering/static-site-generation)

静的配信と SSG の違いは「**人間が HTML を書くか、ビルドが HTML を生成するか**」だけで、**配信物としては同じ** です。選択は「コンテンツソース(CMS か Git か)」と「ページ数」で決まることが多いです。

### 4.3 SSR (Server-Side Rendering)

リクエストが来るたびに、アプリケーションサーバーで HTML を組み立てて返します。

- 強い尺度
  - 鮮度(常に最新)
  - パーソナライズ(セッション・Cookie・位置情報などで出し分け可)
  - SEO(HTML が完成して返る)
  - CSR との比較では初期表示が速い(ブラウザは JS 実行を待たずに描画できる)
- 捨てている尺度
  - TTFB(SSG より遅い。サーバー処理を挟むぶん増える)
  - 運用コスト(毎リクエストでサーバーが働くため、スケールに費用がかかる)
  - CDN 親和性(リクエストごとに結果が違う前提なので、素朴にキャッシュできない)
- 向くケース
  - 検索結果ページ、ログイン後のパーソナライズ画面
  - EC の在庫・価格反映ページ
  - リアルタイム性が SEO 的にも必要なページ(ニュース速報など)

SSR の落とし穴は、**TTFB が SSG より悪化する**ことです。CSR との比較だけ見ていると「SSR は速い」という印象を持ちがちですが、**SSG との比較では遅い** 点を覚えておくと、選択のときに迷いません。

### 4.4 CSR (Client-Side Rendering / SPA)

サーバーはほぼ空の HTML と JS バンドルだけを返し、**ブラウザが JS を実行して API を叩き、DOM を組み立てる** 方式です。「SPA」と呼ばれるのは通常この形態です。

- 強い尺度
  - アプリらしい操作感(画面遷移で全ページを再取得しない)
  - サーバー負荷が軽い(API だけ処理すればよい)
  - バックエンドを他のクライアント(モバイル等)と共有しやすい
- 捨てている尺度
  - 初期表示(JS をダウンロード・パース・実行してから内容が出る)
  - SEO(HTML がほぼ空で返るため、CWV で不利)
  - 低スペック端末 / 遅い回線への適合性(バンドルが重いとつらい)
- 向くケース
  - ログイン後のダッシュボード、管理画面
  - SaaS の内部ツール、社内ツール
  - 検索エンジンに載せる必要がない業務アプリ

web.dev は CSR の問題点をこう整理しています。

> Some websites will use the SPA pattern ... a minimal initial payload of HTML is provided by the server, but then the client will populate the main content area of a page with HTML assembled from data fetched from the server.
> — [Client-side rendering of HTML and interactivity | web.dev](https://web.dev/articles/client-side-rendering-of-html-and-interactivity)

この「まず空っぽの HTML を返す」ところが、初期表示と SEO の弱さの根本原因です。

### 4.5 ISR (Incremental Static Regeneration)

SSG と SSR の中間として、Next.js などで提案された方式です。一度 build 時に静的 HTML を作って CDN に置き、**一定時間ごとに「期限切れ」としてマーク**、次に来たリクエストでは古い HTML を返しつつ、**裏で新しい HTML を再生成** して差し替えます(いわゆる stale-while-revalidate)。

- 強い尺度
  - 初期表示(SSG と同じく CDN から即返せる)
  - 鮮度(時間指定で更新できる)
  - ビルド時間の抑制(全ページを毎回作り直す必要がない)
- 捨てている尺度
  - 厳密なリアルタイム性(「最大 N 秒は古い」を許容する必要)
  - 実装・挙動の理解コスト(キャッシュ・再生成の挙動を把握する必要)
  - フレームワーク・ホスティングへの依存度が高い
- 向くケース
  - 大量ページを持ち、更新頻度が低〜中のサイト(ニュース、EC カタログ、レビューサイト)
  - SSG ではリビルドが追いつかないが、SSR ほどのリアルタイム性は不要なケース

Next.js の公式ドキュメントでは、以下の効果が挙げられています。

> Incremental Static Regeneration (ISR) enables you to: Update static content without rebuilding the entire site / Reduce server load by serving prerendered, static pages for most requests / Handle large amounts of content pages without long `next build` times.
> — [How to implement Incremental Static Regeneration (ISR) | Next.js](https://nextjs.org/docs/pages/guides/incremental-static-regeneration)

ISR は「キャッシュ戦略としての SSG の拡張」と捉えるのが実務的な理解です。

### 4.6 ハイブリッド

「ハイブリッド」は独立した **方式** ではなく、**ページ単位(ルート単位)で 4.1〜4.5 を使い分ける運用** の呼び名です。

現代の Meta-framework(Next.js、Nuxt、SvelteKit、Astro など)はだいたいこれができます。たとえば 1 つの EC サイトの中で、

- トップページ・カテゴリ LP → SSG
- 商品一覧・検索結果 → SSR または ISR
- カート・マイページ → CSR(または SSR + 最小限のハイドレーション)
- 記事(ブログ) → SSG か ISR

のように、**ページの事情ごとに最適な方式を選ぶ**のがハイブリッドです。

- 強み
  - ページごとに「どの尺度を優先するか」を変えられる
  - 全体最適ができる(マーケ LP に SSR を使わなくて済む、など)
- 弱み
  - 設計・レビュー・デバッグが複雑(同じアプリで挙動が違うルートが混在)
  - キャッシュ戦略の全体像を把握するコストが上がる
  - 観測・監視の難易度が上がる(ページごとに見るべき指標が変わる)
- 向くケース
  - 実サービスのほとんど。「SSG 一本」「SSR 一本」で済むプロダクトはむしろ例外

Vercel のブログも、**実質ハイブリッドがデフォルト** であるという整理をしています。

> Lean on SSG and ISR as much as possible, and only introduce SSR when you need fresh to that moment data. ... CSR is almost exclusively for responsive interactions—not fetching external data.
> — [How to choose the best rendering strategy for your app | Vercel](https://vercel.com/blog/how-to-choose-the-best-rendering-strategy-for-your-app)

## 5. 選び方のチェックリスト

ここまでの整理を、実務で判断に使えるチェックリストにまとめます。**1 ページ単位で** 適用してください(サービス全体で決めるものではない、というのがハイブリッドの章の主張です)。

| 問い | 答えが Yes なら候補 |
|------|------|
| このページは SEO が重要か? | SSG / ISR / SSR(CSR は原則除外) |
| 表示するデータは数時間〜日単位の鮮度で十分か? | SSG / ISR |
| 毎リクエスト最新データが必要か? | SSR(または CSR+API) |
| ユーザーごとに内容が変わるか(ログイン後・Cookie 依存)? | SSR / CSR |
| ページ数が非常に多く、全ビルドが重いか? | ISR / SSR |
| 認証済みで SEO が不要、対話性重視か? | CSR |
| ネットワーク・端末が非力なユーザーを想定するか? | SSG / SSR(CSR は避ける) |
| コンテンツを手書きしていて、テンプレートもほぼ要らないか? | 静的配信 |

実務でよくある判断順序は、たとえば以下のようになります。

1. そもそも SEO が必要か?
    - 不要ならまず CSR で足りないか検討
    - 必要なら 2 以降
2. 鮮度要件はどの粒度か?
    - build 時でよい → SSG
    - 数分〜数時間遅れて OK → ISR
    - 毎リクエスト必要 → SSR
3. パーソナライズが必要な部分はあるか?
    - そこだけ CSR もしくは SSR(セッション付き)
4. 残りのページは SSG / ISR に寄せる

## 6. よくある誤解と落とし穴

### 誤解 1: 「SSR は遅い」「SSG は最速」は尺度による

- TTFB の観点では、**SSG > SSR**(SSG のほうが速い)
- 一方で、CSR と SSR を比べた場合、**FCP / LCP は SSR のほうが速い** ことが多い
- どの指標で語っているかを意識しないと議論が噛み合わない

### 誤解 2: 「CSR は SEO NG」

- 現代の Google クローラーは JS を実行してインデックスできる
- ただし **Core Web Vitals でほぼ確実に不利** になる
- 「インデックスされるか」ではなく「上位に表示されるか」が問題

### 誤解 3: 「ハイブリッド = 複雑怪奇」

- 実態は「ページごとに最適を選ぶ」だけ
- むしろ **1 つの方式で全ページを賄おうとするほうが不自然**
- 複雑さは「切り分けのルール」を明文化すれば十分に管理できる

### 落とし穴: ハイドレーションはどの方式でも残る

- SSR / SSG / ISR はいずれも、**HTML を返した後にブラウザで JS を動かして**インタラクティブにする工程(ハイドレーション)が発生する
- HTML が見える ≠ 操作できる、という乖離は残る
- TTI / INP が悪いページは、方式を SSR に変えても改善しない。**JS バンドルを減らす**ほうが効く

## 7. まとめ

- Web ページの配信方式は、**HTML を「いつ」「どこで」組み立て「どこでキャッシュするか」** の組み合わせにすぎない
- 方式を覚えるより、**尺度(速度・SEO・鮮度・運用コスト) → 変数 → 選択** の筋道を身につけるほうが実務的
- 実サービスはほぼ必ずハイブリッドになる。ページ単位で「このページはどの尺度を優先するか」を意識的に決める
- 「SSR は速い/遅い」「CSR は SEO NG」といった一般論は、**どの尺度で語っているかを補わないと正しくない**

自分のプロジェクトを振り返って、「このページは本当にその方式で最適か?」と 1 ページずつ問い直すことが、結局は一番効くチューニングになります。

## 参考

- [Rendering on the Web | web.dev](https://web.dev/articles/rendering-on-the-web)
- [Client-side rendering of HTML and interactivity | web.dev](https://web.dev/articles/client-side-rendering-of-html-and-interactivity)
- [SEO: Rendering Strategies | Next.js](https://nextjs.org/learn/seo/rendering-strategies)
- [Static Site Generation (SSG) | Next.js](https://nextjs.org/docs/pages/building-your-application/rendering/static-site-generation)
- [How to implement Incremental Static Regeneration (ISR) | Next.js](https://nextjs.org/docs/pages/guides/incremental-static-regeneration)
- [How to choose the best rendering strategy for your app | Vercel](https://vercel.com/blog/how-to-choose-the-best-rendering-strategy-for-your-app)
- [What Is Website Rendering: CSR, SSR, and SSG Explained | Strapi](https://strapi.io/blog/what-is-website-rendering)
- [Web Rendering Types: CSR, SSR, SSG, and ISR | Ramotion](https://www.ramotion.com/blog/web-rendering-types-comparison/)
