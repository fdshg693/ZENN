# 利用可能な AI 機能カタログ

YouCam API で使える AI 機能の一覧（カテゴリ別）。各行のリンクが公式リファレンス。
※ 全機能とも基本は [api-basics.md](./api-basics.md) の「File → Task → Poll」ワークフローで動く。
※ Markdown 版が欲しい場合は URL 末尾に `.md` を付ける。

サイト全体の構造はマップ済み（`docs/` 作成時点）。新機能は <https://docs.perfectcorp.com/release/changelog> で確認。

## Beauty / Makeup（★ POC の主役）

| 機能 | 用途 | リファレンス |
| --- | --- | --- |
| AI Makeup Virtual Try-On | 化粧パーツを個別指定して適用（POC の中核） | <https://docs.perfectcorp.com/reference/makeup_vto> |
| AI Look Virtual Try-On | プロ作成の完成ルックを template_id 一発適用 | <https://docs.perfectcorp.com/reference/ai_look_vto> |
| AI Makeup Transfer | 参照画像の化粧を転写 | <https://docs.perfectcorp.com/reference/ai_makeup_transfer> |
| AI Eye Color Lens VTO | カラコン試着 | <https://docs.perfectcorp.com/reference/ai_eye_color_lens> |
| AI Nail Virtual Try-On | ネイル試着 | <https://docs.perfectcorp.com/reference/ai_nail_vto> |
| AI Teeth Whitening | ホワイトニング | <https://docs.perfectcorp.com/reference/ai_teeth_whitening> |

→ Makeup VTO の詳細スキーマは [makeup-vto.md](./makeup-vto.md)。

## Skin / Face 分析・補正

| 機能 | 用途 | リファレンス |
| --- | --- | --- |
| AI Skin Analysis | 肌診断（しわ/毛穴/きめ/ニキビ等のスコア化） | <https://docs.perfectcorp.com/reference/ai_skin_analysis> |
| AI Skin Simulation | 肌補正シミュレーション | <https://docs.perfectcorp.com/reference/ai_skin_simulation> |
| AI Face Attributes & Ratio Analyzer | 顔属性・比率解析 | <https://docs.perfectcorp.com/reference/ai_face_analyzer> |
| AI Face Reshape | 顔の形状補正 | <https://docs.perfectcorp.com/reference/ai_face_reshape> |
| AI Face Lift | リフトアップ | <https://docs.perfectcorp.com/reference/ai_face_lift> |
| AI Smile | 笑顔生成 | <https://docs.perfectcorp.com/reference/ai_smile> |

→ Skin Analysis の入出力は [skin-analysis.md](./skin-analysis.md)。

## Hair（ヘア）

| 機能 | リファレンス |
| --- | --- |
| AI Hair Style VTO | <https://docs.perfectcorp.com/reference/ai_hairstyle> |
| AI Bangs Filter VTO | <https://docs.perfectcorp.com/reference/ai_bangs> |
| AI Wavy Hair VTO | <https://docs.perfectcorp.com/reference/ai_wavy_hair> |
| AI Hair Volume VTO | <https://docs.perfectcorp.com/reference/ai_hair_volume> |
| AI Hair Length / Type / Density Detection | <https://docs.perfectcorp.com/reference/ai_hair_length_detection> ほか |

## Fashion / Accessory（試着系）

| 機能 | リファレンス |
| --- | --- |
| AI Clothes VTO | <https://docs.perfectcorp.com/reference/ai_clothes> |
| AI Fabric VTO | <https://docs.perfectcorp.com/reference/ai_fabric> |
| AI Bag / Scarf / Shoes / Hat VTO | <https://docs.perfectcorp.com/reference/ai_bag> ほか |
| AI Ring / Watch / Necklace / Earrings VTO | <https://docs.perfectcorp.com/reference/ring_vto> ほか |
| AI Body Reshape | <https://docs.perfectcorp.com/reference/ai_body_reshape> |

## Generative / Editing（画像・動画生成編集）

| 機能 | リファレンス |
| --- | --- |
| AI Background Removal | <https://docs.perfectcorp.com/reference/ai_background_removal> |
| AI Object Removal Pro | <https://docs.perfectcorp.com/reference/ai_object_removal_pro> |
| AI Replace | <https://docs.perfectcorp.com/reference/ai_replace> |
| AI Face Swap / Video Face Swap | <https://docs.perfectcorp.com/reference/ai_face_swap> |
| AI Headshot / Avatar Generator | <https://docs.perfectcorp.com/reference/ai_headshot_generator> |
| AI Video Generator / Enhancer / Style Transfer | <https://docs.perfectcorp.com/reference/ai_video_generator> ほか |

## 補足

- 一部機能には **テンプレート/パターン照会 API** がペアで存在する（例: Look VTO の `GET /s2s/v2.0/task/template/look-vto`）。
  「適用前に選択肢を一覧表示する」UI を作るときに使う。
- カメラ撮影をブラウザ/モバイルで行う **JS Camera Kit / Mobile Camera Kit** が一部機能で提供されている
  （撮影モード: `makeup`, `skincare`, `hdskincare`, `shadefinder`, `facereshape`, `hairlength`, `ring`, `wrist`, `necklace`, `earring` 等）。
  出典: <https://yce.perfectcorp.com/document/index.html>
