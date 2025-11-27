# ZENN記事をローカルで作成する手順メモ

## 記事の雛形を作成する
`npx zenn new:article`コマンドで、articles/ランダムなslug.mdというファイルが作成できる。

### 作成ファイルの例
作成されたファイルの中身は次のようになっています。
`docs\samples\99f43fb172df68.md`から確認できます。

---
title: "" # 記事のタイトル
emoji: "😸" # アイキャッチとして使われる絵文字（1文字だけ）
type: "tech" # tech: 技術記事 / idea: アイデア記事
topics: [] # タグ。["markdown", "rust", "aws"]のように指定する
published: true # 公開設定（falseにすると下書き）
---
ここから本文を書く

## 記事をプレビューする
`npx zenn preview`コマンドで、ローカルサーバーを立ち上げて記事のプレビューができる。