// api/types.ts — YouCam API のリクエスト/レスポンス型（＝仕様の正本）
//   ここに型として仕様を載せることで、入れ子 JSON の取り違えをコンパイル時に潰す。
//   機能Aで必要なのは File API の型のみ。task 系（機能B〜E）は各機能ファイルで追加する。

/**
 * File API 開始リクエスト。
 * 寸法・サイズの「実体」は送らず、メタ情報だけを送る（実体は後段の PUT で送る）。
 */
export interface FileCreateRequest {
  files: { content_type: string; file_name: string; file_size: number }[];
}

/**
 * File API レスポンス（実レスポンスで確認した形）。
 * ラッパは `data`、ファイル配列は `data.files[]`。
 * `data.files[].requests[].url` が「実体を PUT する事前署名 URL」。
 * `data.files[].file_id` を後続タスクの `src_file_id` に使う。
 */
export interface FileCreateResponse {
  status?: number;
  data: {
    files: {
      file_id: string;
      requests: { method?: string; url: string; headers?: Record<string, string> }[];
    }[];
  };
}

/**
 * YouCam API のエラー応答（共通形）。
 * フィールド名は機能・エラー種別で揺れるため、client.ts 側で寛容に拾う。
 * 代表コード: InvalidApiKey / CreditInsufficiency / error_no_face など。
 */
export interface ApiErrorBody {
  error?: string;
  error_code?: string;
  error_messages?: string[];
  message?: string;
  // 実エラー本文は File/Task と同じく data ラッパに入る場合があるため、入れ子も許容する。
  data?: {
    error?: string;
    error_code?: string;
    error_messages?: string[];
    message?: string;
  };
}

// ── 機能B: makeup-vto の effects スキーマ（＝仕様の正本）─────────────────────
//   effects の入れ子 JSON が本機能の最大の複雑さ。category で判別する共用体にして、
//   カテゴリごとの必須項目をコンパイル時に固定する（取り違えを潰す）。
//   domain の MakeupBlock はこの MakeupEffect を再利用する（仕様の置き場は api 側）。

/**
 * 1色ぶんの塗り設定。texture により「追加で必須になる項目」がある（下記コメント）。
 * texture 依存の必須欄漏れは MakeupEditor が出し分け、domain が実行前に検証して弾く。
 */
export interface MakeupPalette {
  color: string; // "#RRGGBB"
  colorIntensity?: number; // 0–100
  texture?: 'matte' | 'satin' | 'shimmer' | 'metallic' | 'gloss' | 'holographic' | 'sheer';
  shimmerColor?: string; // texture==='shimmer' のとき必須
  shimmerDensity?: number; //   〃（0–100）
  glowStrength?: number; // texture==='satin' のとき必須
  gloss?: number; // lip_color の gloss 系で使用
}

/** パターン名 / シェイプ名 = カタログ JSON 内の `label` 値（例 "2colors1", "plump"）。 */
export interface PatternRef {
  name: string;
}

/** パターン必須カテゴリ（pattern.name + palettes 系）。 */
export type PatternCategory =
  | 'blush'
  | 'bronzer'
  | 'contour'
  | 'highlighter'
  | 'eye_shadow'
  | 'eye_liner'
  | 'eyelashes'
  | 'lip_liner'
  | 'eyebrows';

/** effect は category で判別。スキーマは大きく 3 系統（無パターン / パターン+palettes / lip_color）。 */
export type MakeupEffect =
  // ① 無パターン系（pattern 不要・フラットなパラメータ）
  | { category: 'skin_smooth'; skinSmoothStrength?: number; skinSmoothColorIntensity?: number }
  | {
      category: 'foundation';
      color: string;
      colorIntensity?: number;
      glowIntensity?: number;
      coverageIntensity?: number;
    }
  | {
      category: 'concealer';
      color: string;
      colorIntensity?: number;
      colorUnderEyeIntensity?: number;
      coverageLevel?: number;
    }
  // ② パターン + palettes 系（pattern.name 必須・多色は palettes を色数ぶん）
  | {
      category: PatternCategory;
      pattern: PatternRef;
      palettes: MakeupPalette[];
    }
  // ③ lip_color（shape + style + morphology）
  | {
      category: 'lip_color';
      shape: PatternRef;
      style?: { type: 'full' | 'ombre' | 'twoTone' };
      morphology?: { fullness?: number; wrinkless?: number };
      palettes: MakeupPalette[];
    };

/** effect の category 値の全集合（編集 UI のセレクト生成に使う）。 */
export type MakeupCategory = MakeupEffect['category'];

/** makeup-vto タスク開始リクエスト。src_* はどちらか一方（機能A の選択を実行時に解決）。 */
export interface MakeupTaskRequest {
  src_file_id?: string;
  src_file_url?: string;
  version: string; // "1.0"
  effects: MakeupEffect[];
}

// ── 機能D: look-vto の型（＝仕様の正本）──────────────────────────────────────
//   look-vto は makeup-vto と同形（成功は data.results.url・dst_id 無し）なので、
//   結果系の型（TaskResultItem / TaskStatusResponse）は再利用する。増えるのは
//   「テンプレ一覧の型」と「look の req 型（effects ではなく template_id）」だけ。

/** テンプレ一覧の1件。リファレンス: data.templates[]。id を look の template_id に渡す。 */
export interface LookTemplate {
  id: string; // ← look-vto の template_id に渡す値
  title: string; // 表示名
  thumb?: string; // サムネイル URL（一覧 UI で表示）
  category_name?: string; // カテゴリ（一覧のグルーピングに使える）
}

/** テンプレ一覧レスポンス。ラッパは data（機能B/C と共通）。next_token でページング。
 *   注: page_size は API 上限 20（超過で InvalidParameters）。実機確認済み。
 *   アプリは毎回これを叩かず、scripts/fetch-look-templates.mjs が生成した
 *   ローカルマニフェスト（LookTemplateManifest）を読む（349件・サムネ CDN 依存の回避）。 */
export interface LookTemplateListResponse {
  status?: number;
  data: { templates: LookTemplate[]; next_token?: string | number | null };
}

/** ローカル配信用マニフェスト（public/look-templates/index.json）。
 *   scripts/fetch-look-templates.mjs が生成。thumb はローカルパス（/look-templates/thumbs/...）に差し替え済み。 */
export interface LookTemplateManifest {
  generatedAt: string;
  source: string;
  count: number;
  templates: LookTemplate[];
}

/** look-vto タスク開始リクエスト。src_* はどちらか一方。version はリファレンス未記載のため送らない。 */
export interface LookTaskRequest {
  src_file_id?: string;
  src_file_url?: string;
  template_id: string;
}

// ── 機能E: skin-analysis の型（＝仕様の正本）──────────────────────────────────
//   機能B〜D が「画像 → 画像（結果 url 1枚）」だったのに対し、skin は「画像 → スコア＋マスク」を返す。
//   成功ペイロードが結果 url 1枚ではないため、結果系の型を新設する（TaskStatusResponse は再利用しない）。
//   results の形の揺れ（output[] 形 / score_info の keyed map 形）は skinAnalysis.ts の extractSkin で吸収する。

/** 診断1項目ぶんのスコア。type は dst_actions の値（'wrinkle' / 'hd_pore' 等）。 */
export interface SkinScore {
  type: string;
  uiScore: number; // ui_score（表示用に補正・高め）
  rawScore?: number; // raw_score（1–100 の実スコア。高いほど良好）
  maskUrls?: string[]; // mask_urls（検出箇所の重ね合わせ PNG。任意）
}

/** 肌診断の結果（=画像 url ではなくスコア群）。これが機能E の「結果」。 */
export interface SkinResult {
  scores: SkinScore[]; // 項目別（results.output[] 由来）
  overall?: number; // all.score（総合点）
  skinAge?: number; // skin_age（推定肌年齢）
}

/** skin-analysis タスク開始リクエスト。src_* はどちらか一方。SD/HD は dst_actions で一系統に統一。 */
export interface SkinTaskRequest {
  src_file_id?: string;
  src_file_url?: string;
  dst_actions: string[];
  format?: 'json';
  miniserver_args?: { enable_mask_overlay?: boolean };
}

/** skin の成功ペイロード。実機確認: results.output[] は診断項目・総合点・肌年齢・リサイズ画像が混在するフラット配列。
 *   score_info 形（keyed map・ZIP 由来）の揺れは extractSkin がフォールバックで吸収。 */
export interface SkinStatusData {
  task_status: 'running' | 'success' | 'error';
  results?: {
    // 各要素は type で区別: 診断項目（ui_score/raw_score/mask_urls）・'all'（score=総合点）・
    //   'skin_age'（score=推定年齢）・'resize_image'（mask_urls=解析用リサイズ画像）。url は常に null。
    output?: {
      type: string;
      ui_score?: number;
      raw_score?: number;
      score?: number; // type:'all' / 'skin_age' のときの値
      mask_urls?: string[] | null;
      url?: string | null;
    }[];
    // keyed map 形のフォールバック用（output[] が無い ZIP 派生の形）。
    all?: { score?: number };
    skin_age?: number;
    [key: string]: unknown;
  };
  error?: string;
  error_message?: string;
}

// ── タスク開始/ステータスの共通形（feature 横断。task.ts がここに取り出しを集約）──
//   ラッパは File API と同じく `data`（実レスポンスで確認）。
//   results の内側の入れ子（results.url / results[].url / results[].data[].url 等）は
//   機能・バージョンで揺れるため、task.ts の extractResult で寛容に吸収する。

/** タスク開始レスポンス。task_id を以後のポーリングに使う。 */
export interface TaskStartResponse {
  status?: number;
  data: { task_id: string };
}

/** 結果1件ぶん。url / download_url のどちらか、dst_id は同階層 or data[] 内にあり得る。 */
export interface TaskResultItem {
  url?: string;
  download_url?: string;
  dst_id?: string;
  data?: { url?: string; dst_id?: string }[];
}

/** タスクステータス。success 時に results（配列 or 単体）へ結果画像 URL と dst_id が入る。 */
export interface TaskStatusResponse {
  status?: number;
  data: {
    task_status: 'running' | 'success' | 'error';
    results?: TaskResultItem | TaskResultItem[]; // success 時に結果画像 URL と dst_id
    error?: string; // error 時のコード（client.ts が整形）
    error_message?: string;
  };
}
