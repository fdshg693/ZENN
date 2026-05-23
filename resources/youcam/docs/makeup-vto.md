# AI Makeup Virtual Try-On（化粧 VTO）

POC の中核。1リクエストで複数の化粧パーツ（`effects`）をまとめて適用できる。
この「`effects` 配列＝化粧の手順・パーツ集合」が、本 POC の「ルーティン/ブロック」と直接対応する。

公式リファレンス（フル）: <https://docs.perfectcorp.com/reference/makeup_vto>
Markdown 版: <https://docs.perfectcorp.com/reference/makeup_vto.md>
API Playground: <https://yce.makeupar.com/api-console/en/api-playground/ai-makeup-virtual-try-on/>

## エンドポイント

- ファイル: `POST /s2s/v2.0/file/makeup-vto`
- タスク開始: `POST /s2s/v2.0/task/makeup-vto`
- ステータス: `GET /s2s/v2.0/task/makeup-vto/{task_id}`
- サーバ: `https://yce-api-01.makeupar.com`

## リクエストの形

```json
{
  "src_file_url": "https://.../selfie.jpg",   // または File API の file_id
  "version": "1.0",
  "effects": [ /* 適用したい化粧パーツの配列。下記カテゴリを参照 */ ]
}
```

- `effects` は **複数パーツを同時指定可能**（例: skin_smooth + blush + lip_color を一括）。
- 各 effect は `category` で種類を指定し、種類ごとにスキーマが異なる。
- レスポンスは `task_id` → ポーリングして `data.results.url`（結果画像）。

## 化粧パーツ（effect カテゴリ）一覧

| category | 主な指定項目 | パターン要否 | パターンカタログ JSON |
| --- | --- | --- | --- |
| `skin_smooth` | `skinSmoothStrength`, `skinSmoothColorIntensity`(0–100) | 不要 | （省略時は自動で 50 適用） |
| `foundation` | color, colorIntensity, glowIntensity, coverageIntensity | 不要 | — |
| `concealer` | color, colorIntensity, colorUnderEyeIntensity, coverageLevel | 不要 | — |
| `blush` | pattern.name + palettes[](color/texture/colorIntensity…) | 要 | [blush.json](https://plugins-media.makeupar.com/wcm-saas/patterns/blush.json) |
| `bronzer` | pattern.name + palettes[](color, colorIntensity) | 要 | [bronzer.json](https://plugins-media.makeupar.com/wcm-saas/patterns/bronzer.json) |
| `contour` | pattern.name + palettes[](color, colorIntensity) | 要 | [contour.json](https://plugins-media.makeupar.com/wcm-saas/patterns/contour.json) |
| `highlighter` | pattern.name + palettes[](color, glow/shimmer 系) | 要 | [highlighter.json](https://plugins-media.makeupar.com/wcm-saas/patterns/highlighter.json) |
| `eyebrows` | pattern(type=shape/color, curvature/thickness/definition) + palettes | 要(shape時) | [eyebrows.json](https://plugins-media.makeupar.com/wcm-saas/patterns/eyebrows.json) |
| `eye_shadow` | pattern.name + palettes[](color/texture/shimmer/metallic) | 要 | [eyeshadow.json](https://plugins-media.makeupar.com/wcm-saas/patterns/eyeshadow.json) |
| `eye_liner` | pattern.name + palettes[](color/texture/shimmer/metallic) | 要 | [eyeliner.json](https://plugins-media.makeupar.com/wcm-saas/patterns/eyeliner.json) |
| `eyelashes` | pattern.name + palettes[](color, colorIntensity) | 要 | [eyelashes.json](https://plugins-media.makeupar.com/wcm-saas/patterns/eyelashes.json) |
| `lip_color` | shape.name + style(full/ombre/twoTone) + morphology + palettes | 要(shape) | [lipshape.json](https://plugins-media.makeupar.com/wcm-saas/shapes/lipshape.json) |
| `lip_liner` | pattern.name + palettes[](color/texture/thickness/smoothness) | 要 | [lipliner.json](https://plugins-media.makeupar.com/wcm-saas/patterns/lipliner.json) |

### パターン(`pattern.name`)の考え方

- パターンが必要なカテゴリは、`pattern.name` に **カタログ JSON 内の `label` 値**（例: `"2colors1"`, `"OvalFace6"`）を指定する。
- 多色パターン（`colorNum: 2/3/…`）は **その色数ぶん `palettes` を渡す**必要がある（例: `2colors1` なら palettes 2要素）。
- 選択肢を UI に出すには、上表のカタログ JSON を取得して `label` / `thumbnail` を一覧表示するとよい。

### texture（質感）の主な enum

- 共通的に `matte` / `satin` / `shimmer` / `metallic` など（カテゴリにより使える値が異なる）。
- `lip_color` はさらに `gloss` / `holographic` / `sheer` も持つ。
- `texture` によって追加必須項目が変わる（例: `shimmer` なら `shimmerColor`/`shimmerDensity` 必須、`satin` なら `glowStrength` 必須）。詳細は各カテゴリのスキーマ（公式リファレンス）参照。

## 複数パーツ適用の例（公式の有効ペイロード例）

```json
{
  "version": "1.0",
  "effects": [
    { "category": "skin_smooth", "skinSmoothStrength": 55, "skinSmoothColorIntensity": 45 },
    {
      "category": "blush",
      "pattern": { "name": "2colors1" },
      "palettes": [
        { "color": "#e19f9f", "texture": "matte", "colorIntensity": 60, "shimmerColor": "#d63252", "shimmerDensity": 50 },
        { "color": "#c98a8a", "texture": "satin", "glowStrength": 40, "colorIntensity": 70 }
      ]
    },
    {
      "category": "lip_color",
      "shape": { "name": "plump" },
      "morphology": { "fullness": 30, "wrinkless": 25 },
      "style": { "type": "full" },
      "palettes": [ { "color": "#e11c43", "texture": "gloss", "colorIntensity": 80, "gloss": 75 } ]
    }
  ]
}
```

## POC への示唆

- **ルーティン定義 = この `effects` JSON（＋ソース画像）**。共有はこの JSON をエクスポート/インポートするだけで成立する。
- 「ブロック1個 = 1 effect」または「ブロック1個 = 1タスク」のどちらの粒度でも設計可能:
  - 軽量: 全パーツを1つの `effects` にまとめて **1タスク** で実行（速い・安い）。
  - 柔軟: パーツごとにタスクを分け、**前タスクの結果 url を次の `src_file_url` に渡して チェイン**（途中結果を見せられる／Makeup以外の機能も挟める）。
    - ⚠️ **実機確認**: makeup-vto は `dst_id` を返さない（成功レスポンスは `data.results` の単体 `{ url }`）。チェインは結果 url（公開 S3・約2時間有効）を渡す方式になる。`dst_id` は skin-analysis 固有の可能性が高い（[api-basics.md](./api-basics.md) のチェイン節参照）。
- 共有時に注意: ソース画像 URL（他人の顔）は除外し、**effects 設定だけ**を共有対象にする。**結果 url は揮発する（約2時間）ため共有 JSON に含めない**。

## ファイル仕様・エラー

- 入力: 長辺 < 1920px、顔幅 >= 100px、< 10MB、jpg/jpeg/png
- 顔系エラー: `error_no_face`, `error_face_position_invalid`, `error_face_angle_invalid`（正面 ±10°以内）等
- 共通は [api-basics.md](./api-basics.md) のエラー節、公式: <https://docs.perfectcorp.com/develop/error_codes>
