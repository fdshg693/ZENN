# AI Skin Analysis（肌診断）

肌の状態を AI でスコア化する。POC では「ルーティンの最初の Before 診断」「化粧前後の比較」ブロックに使える。

公式リファレンス: <https://docs.perfectcorp.com/reference/ai_skin_analysis>
Markdown 版: <https://docs.perfectcorp.com/reference/ai_skin_analysis.md>

## エンドポイント / バージョン

- v2.0: `POST /s2s/v2.0/file/skin-analysis` → `POST /s2s/v2.0/task/skin-analysis` → `GET /s2s/v2.0/task/skin-analysis/{task_id}`
- v2.1（新モデル、入力解像度を 1920→4096 に拡張）: 同パスの `v2.1`
- サーバ: `https://yce-api-01.makeupar.com`

ワークフローは共通（[api-basics.md](./api-basics.md)）。タスク作成時に **解析したい項目を `dst_actions` で指定**する。

## リクエスト例

```json
{
  "src_file_id": "<file_id>",                  // または src_file_url
  "dst_actions": ["wrinkle", "pore", "texture", "acne"],
  "miniserver_args": {
    "enable_mask_overlay": true                 // true: 1枚にブレンド合成 / false(既定): 項目ごとのマスク画像を別々に出力
  },
  "format": "json"
}
```

- **`dst_actions`**: 解析項目の配列。**HD 系と SD 系を混在させると `InvalidParameters` エラー**（混ぜられない）。
- 結果保持 24時間。ポーリング中は units 非消費。

## 解析項目（dst_actions）

2系統あり、**どちらか一方に統一**して指定する。

- **SD**: `wrinkle`, `pore`, `texture`, `acne`, `oiliness`, `radiance`, `eye_bag`, `age_spot`, `dark_circle_v2`, `droopy_upper_eyelid`, `droopy_lower_eyelid`, `firmness`, `moisture`, `redness`, `tear_trough`, `skin_type`
- **HD**（`hd_` プレフィックス、より細分化のサブカテゴリあり）: `hd_wrinkle`, `hd_pore`, `hd_texture`, `hd_acne`, `hd_oiliness`, `hd_radiance`, `hd_eye_bag`, `hd_age_spot`, `hd_dark_circle`, `hd_droopy_upper_eyelid`, `hd_droopy_lower_eyelid`, `hd_firmness`, `hd_moisture`, `hd_redness`, `hd_tear_trough`, `hd_skin_type`
  - 例: `hd_pore` は forehead/nose/cheek/whole、`hd_wrinkle` は forehead/glabellar/crowfeet/periocular/nasolabial/marionette/whole などサブ領域別にスコア化

## 結果（出力）

- レスポンス `data.results.output[]` に項目ごとの `type` / `ui_score` / `raw_score` / `mask_urls`。
- または ZIP（`skinanalysisResult/`）として、`score_info.json` ＋ 各項目のマスク PNG。
  - `raw_score`: 1–100 の実スコア（高いほど良好）
  - `ui_score`: 表示用に高めに補正したスコア（ユーザー心理向け）
  - `all.score`: 総合点 / `skin_age`: 推定肌年齢
  - マスク PNG は alpha で元画像に重ねて「どこを検出したか」を可視化できる

```json
// score_info.json の例（SD・抜粋）
{
  "wrinkle": { "raw_score": 36.09, "ui_score": 60, "output_mask_name": "wrinkle_output.png" },
  "pore":    { "raw_score": 88.38, "ui_score": 84, "output_mask_name": "pore_output.png" },
  "all":     { "score": 75.76 },
  "skin_age": 37
}
```

## 撮影・入力条件（精度に直結）

- 正面・無表情・口を閉じる、前髪を上げて額を出す、明るく均一な照明、メガネは外す推奨。
- **顔幅が画像幅の 60% 超**であること（小さすぎると `error_src_face_too_small`）。
- 入力寸法: SD = 長辺<=4096 / 短辺>=480、HD = 長辺<=4096 / 短辺>=1080、< 10MB、jpg/jpeg/png。ポートレート推奨。
- 撮影ミス系エラー: `error_lighting_dark`, `error_src_face_out_of_bound` 等。

## POC への示唆

- ルーティンの「診断ブロック」として、化粧前に肌診断 → スコアやマスクを表示 → 改善提案（どの化粧を勧めるか）に繋げられる。
- `dst_id` で診断結果画像をそのまま次の VTO ブロックに渡せる（[api-basics.md](./api-basics.md) の「タスクのチェイン」）。
