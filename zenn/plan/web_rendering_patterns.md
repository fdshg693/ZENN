---
title: "WEBページの配信方式を整理する — 静的・SSR・SSG・ISR・ハイブリッドを尺度から読み解く"
status: plan
---

## 想定読者と問い

- 想定読者: HTTP / HTML / JavaScript の基礎と、クライアント・サーバーの違いが分かっている Web 開発者
- 扱うこと: 静的配信 / SSG / SSR / CSR / ISR / ハイブリッド の違いと選び方
- 扱わないこと: 特定フレームワーク(Next.js、Nuxt、Astro、Remix など)の API 詳細
- この記事が答える問い:
  - なぜ Web ページの配信方式は何種類も並立しているのか?
  - 自分のユースケースではどれを選ぶべきか? どういう尺度で比較するのか?

## 記事の設計方針

先に「Web ページを届けるときに評価される尺度」と「配信処理の中で動かせる変数」を整理し、**各配信方式はそれらの変数の組み合わせ** であることを見せる。方式を先に並べず、尺度 → 変数 → 方式の順に展開することで、読者が「これは○○の事情を重視した選択」という読み方ができるようにする。

## セクション構成

### 1. WEB ページを届ける処理の最小モデル

- HTTP リクエスト → HTML 受信 → CSS/JS 取得・実行 → インタラクティブ化、の流れ
- 配信方式の本質は「**HTML をいつ・どこで組み立てるか**」であることを先出しする
- 根拠: https://web.dev/articles/rendering-on-the-web, https://web.dev/articles/client-side-rendering-of-html-and-interactivity

### 2. WEB ページを評価する 5 つの尺度

以下の 5 尺度を最初にそろえる。後続セクションで方式を比較する軸になる。

1. 初期表示の速さ: TTFB / FCP / LCP
2. 操作可能になる速さ: TTI / INP
3. 検索エンジン対応: クローラーが HTML を読み取れるか、Core Web Vitals
4. データ鮮度とパーソナライズ: リクエストごとに変わるか、ユーザーごとに変わるか
5. 運用コスト: サーバー負荷、インフラ費、ビルド時間、配信経路(CDN/オリジン)

根拠: https://vercel.com/blog/how-to-choose-the-best-rendering-strategy-for-your-app, https://web.dev/articles/rendering-on-the-web

### 3. 配信方式を分ける 3 つの変数

すべての方式を以下 3 変数の組み合わせで記述できることを示す。

1. **HTML を生成するタイミング**: build 時 / request 時 / ブラウザ実行時
2. **HTML を組み立てる場所**: CDN/ファイルサーバー / アプリサーバー / ブラウザ
3. **キャッシュの置き場所**: CDN に置けるか、オリジン手前まで、まったくキャッシュ不可

各方式はこの 3 変数の選び方の違い、と位置づける。

### 4. 各方式のメリット・デメリット・ユースケース

それぞれ「どの尺度が強く、どの尺度を捨てているか」をそろえた形式で書く。

- 4.1 静的配信 (Pure Static)
  - 手書き HTML / CSS をそのまま CDN から返す
  - 強い尺度: 初期表示・コスト・堅牢性。捨てる尺度: 動的データ・パーソナライズ
  - ユースケース: LP、単一ページの告知、ドキュメント(中小)
- 4.2 SSG (Static Site Generation)
  - ビルド時に大量の HTML を生成、配信は静的と同じ
  - 強い尺度: 速度・SEO・CDN 親和性。捨てる尺度: 更新頻度・ビルド時間・パーソナライズ
  - ユースケース: ブログ、商品カタログ、ドキュメントサイト、マーケティングサイト
  - 根拠: https://nextjs.org/docs/pages/building-your-application/rendering/static-site-generation
- 4.3 SSR (Server-Side Rendering)
  - リクエストごとにサーバーで HTML を生成
  - 強い尺度: 鮮度・パーソナライズ・SEO・FCP(CSR 比)。捨てる尺度: TTFB(SSG 比)・運用コスト
  - ユースケース: 検索結果、EC の在庫/価格依存ページ、認可後でも SEO を必要としない動的ページ
- 4.4 CSR (Client-Side Rendering / SPA)
  - 空の HTML を返し、JS が API を叩いて画面を作る
  - 強い尺度: 操作感・サーバー軽量・アプリらしい UX。捨てる尺度: 初期表示・SEO・低スペック端末
  - ユースケース: ログイン後のダッシュボード、社内ツール、SaaS 管理画面
- 4.5 ISR (Incremental Static Regeneration)
  - ビルド時に静的生成し、期限切れ後は裏で再生成しつつ古いものを返す
  - 強い尺度: SSG の速度 + 中程度の鮮度、ビルド時間の抑制
  - 捨てる尺度: 厳密なリアルタイム性、キャッシュ戦略の単純さ
  - ユースケース: 大量ページで更新頻度は低〜中(ニュース、EC カタログ、レビューサイト)
  - 根拠: https://nextjs.org/docs/pages/guides/incremental-static-regeneration
- 4.6 ハイブリッド
  - ルート単位で SSG / SSR / CSR / ISR を使い分ける「方式」ではなく「運用ポリシー」
  - 強み: ページごとに最適化、全体最適
  - 弱み: 設計・デバッグ・観測が複雑、方式の切替条件を決める必要
  - ユースケース: 実サービスのほとんどは暗黙にこれになる

根拠(全体): https://vercel.com/blog/how-to-choose-the-best-rendering-strategy-for-your-app, https://strapi.io/blog/what-is-website-rendering, https://www.ramotion.com/blog/web-rendering-types-comparison/

### 5. 選び方のチェックリスト

セクション 2 の 5 尺度 × セクション 4 の各方式を、決定フロー的に並べる。
- SEO 必要? / 更新頻度は? / パーソナライズ必要? / 対話性は? / ページ数は?
- それぞれの答えに対して、推奨される方式とその理由を示す

### 6. よくある誤解と落とし穴

- 「SSR は速い」「SSG は最速」は尺度次第(TTFB か LCP か)
- CSR でも Google はインデックスできるが CWV で不利
- ハイブリッド = 複雑怪奇ではなく、むしろ現実のデフォルト
- ハイドレーションのコストはどの方式でも付きまとう
- 根拠: https://web.dev/articles/rendering-on-the-web, https://web.dev/articles/client-side-rendering-of-html-and-interactivity

### 7. まとめ

- 「方式を覚える」より「尺度 → 変数 → 選択」の筋道を身につけるのが実務的
- 実務ではハイブリッドを前提にページごとに判断する

## 根拠ファイル

- `temp/web_rendering_patterns/search_rendering_patterns_overview.json`
- `temp/web_rendering_patterns/search_rendering_patterns_official.json`

## 主要参照 URL

- https://web.dev/articles/rendering-on-the-web
- https://web.dev/articles/client-side-rendering-of-html-and-interactivity
- https://nextjs.org/learn/seo/rendering-strategies
- https://nextjs.org/docs/pages/building-your-application/rendering/static-site-generation
- https://nextjs.org/docs/pages/guides/incremental-static-regeneration
- https://vercel.com/blog/how-to-choose-the-best-rendering-strategy-for-your-app
- https://strapi.io/blog/what-is-website-rendering
- https://www.ramotion.com/blog/web-rendering-types-comparison/
