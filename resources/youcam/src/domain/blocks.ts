// domain/blocks.ts — ブロックの型（判別共用体）と既定値・検証ヘルパ（UI 非依存）。
//   機能Aの段階では SourceBlock を精緻化して定義する。
//   機能B で MakeupBlock を union へ追加。残る LookBlock / SkinBlock は各機能の実装時に追加する。

import { uploadFile } from '../api/files';
import type { MakeupCategory, MakeupEffect, MakeupPalette, PatternCategory } from '../api/types';

/** ブロック種別の語彙（全体設計 セクション4）。Block union は実装済みのものだけを含む。 */
export type BlockKind = 'source' | 'makeup' | 'look' | 'skin';

/** ブロック共通の素性。id は実行順・並べ替えの管理キー。 */
export interface BaseBlock {
  id: string;
  kind: BlockKind;
  title: string; // ユーザーが付けられる表示名（例「起点の顔写真」）
}

/**
 * 起点画像の指定。2 経路のいずれか一方（同時指定は不可）。
 *   - upload: 編集時は File 実体を保持。file_id は実行時に発行（feature 依存のため）。
 *   - url:    そのまま src_file_url に使える。File API 不要。
 */
export type SourceSelection =
  | { type: 'upload'; file: File; previewUrl: string }
  | { type: 'url'; url: string };

/**
 * 機能A: 起点となる顔画像。AI タスクは持たず「入力の指定」だけを表す。
 *   source は未選択（null）から始まり、編集フェーズの操作で確定する。
 *   ★ file_id はここに持たせない（feature 単位で発行されるため実行時に解決する）。
 */
export interface SourceBlock extends BaseBlock {
  kind: 'source';
  source: SourceSelection | null;
}

/**
 * 機能B: makeup-vto の effects そのもの。これが共有（機能F）の最小単位になるため、
 *   型はシリアライズ可能な素直な形（api/types.ts の MakeupEffect）を保つ。
 */
export interface MakeupBlock extends BaseBlock {
  kind: 'makeup';
  effects: MakeupEffect[];
}

/**
 * 機能D: 完成ルックを template_id 一発適用。これが共有（機能F）の最小単位（id 文字列1つ）。
 *   JSON 化できる素直な形を保つ（共有のために templateId 以外の状態を持たせない）。
 */
export interface LookBlock extends BaseBlock {
  kind: 'look';
  templateId: string; // LookTemplate.id
}

/**
 * 機能E: 肌診断。SD/HD はどちらか一方に統一する（resolution で固定し UI で混在不可能にする）。
 *   これまでの makeup/look が「画像 → 画像」だったのに対し、skin は「画像 → スコア＋マスク」を返す測定ブロック。
 *   これが共有（機能F）の最小単位（resolution + dstActions の素直な JSON）。
 */
export interface SkinBlock extends BaseBlock {
  kind: 'skin';
  resolution: 'sd' | 'hd';
  dstActions: string[]; // 選択中の診断項目（resolution の系統に属するもののみ）
}

/** 実装済みブロックの判別共用体（機能E で SkinBlock を追加）。 */
export type Block = SourceBlock | MakeupBlock | LookBlock | SkinBlock;

/** 実行対象の AI ブロック（makeup + look + skin）。source は起点なので含めない。 */
export type AiBlock = MakeupBlock | LookBlock | SkinBlock;

/** 新しい SourceBlock の既定値（起点未選択）。 */
export function createSourceBlock(): SourceBlock {
  return { id: crypto.randomUUID(), kind: 'source', title: '起点の顔写真', source: null };
}

/**
 * 新しい空の makeup ブロック。
 *   既定で skin_smooth を1つ入れておく（無パターン疎通＝最初の「動いた」が取りやすい）。
 */
export function createMakeupBlock(): MakeupBlock {
  return {
    id: crypto.randomUUID(),
    kind: 'makeup',
    title: 'メイク',
    effects: [createEffect('skin_smooth')],
  };
}

/** 新しい空の look ブロック（テンプレ未選択から始め、LookEditor が一覧から選ばせる）。 */
export function createLookBlock(): LookBlock {
  return { id: crypto.randomUUID(), kind: 'look', title: '完成ルック', templateId: '' };
}

// ── 機能E: 肌診断の dst_actions カタログ（SD / HD は別系統。混在は InvalidParameters）──────
//   value=dst_actions の値, label=表示名。SkinEditor のチェックボックスはここから生成し、
//   SkinResultView の項目ラベルもここを引く。docs/skin-analysis.md の項目に対応。

/** SD/HD 各系統の選択肢。UI は resolution に対応する側だけを出す＝混在を作れない。 */
export const SKIN_ACTIONS: Record<'sd' | 'hd', { value: string; label: string }[]> = {
  sd: [
    { value: 'wrinkle', label: 'シワ' },
    { value: 'pore', label: '毛穴' },
    { value: 'texture', label: 'キメ' },
    { value: 'acne', label: 'ニキビ' },
    { value: 'oiliness', label: '皮脂' },
    { value: 'radiance', label: 'ツヤ' },
    { value: 'eye_bag', label: '目袋' },
    { value: 'age_spot', label: 'シミ' },
    { value: 'dark_circle_v2', label: 'クマ' },
    { value: 'droopy_upper_eyelid', label: '上まぶたのたるみ' },
    { value: 'droopy_lower_eyelid', label: '下まぶたのたるみ' },
    { value: 'firmness', label: 'ハリ' },
    { value: 'moisture', label: '水分' },
    { value: 'redness', label: '赤み' },
    { value: 'tear_trough', label: '涙袋' },
    { value: 'skin_type', label: '肌タイプ' },
  ],
  hd: [
    { value: 'hd_wrinkle', label: 'シワ (HD)' },
    { value: 'hd_pore', label: '毛穴 (HD)' },
    { value: 'hd_texture', label: 'キメ (HD)' },
    { value: 'hd_acne', label: 'ニキビ (HD)' },
    { value: 'hd_oiliness', label: '皮脂 (HD)' },
    { value: 'hd_radiance', label: 'ツヤ (HD)' },
    { value: 'hd_eye_bag', label: '目袋 (HD)' },
    { value: 'hd_age_spot', label: 'シミ (HD)' },
    { value: 'hd_dark_circle', label: 'クマ (HD)' },
    { value: 'hd_droopy_upper_eyelid', label: '上まぶたのたるみ (HD)' },
    { value: 'hd_droopy_lower_eyelid', label: '下まぶたのたるみ (HD)' },
    { value: 'hd_firmness', label: 'ハリ (HD)' },
    { value: 'hd_moisture', label: '水分 (HD)' },
    { value: 'hd_redness', label: '赤み (HD)' },
    { value: 'hd_tear_trough', label: '涙袋 (HD)' },
    { value: 'hd_skin_type', label: '肌タイプ (HD)' },
  ],
};

/** dst_actions の値 → 表示ラベル（SD/HD 全系統を1つに束ねた逆引き。SkinResultView が使う）。 */
export const SKIN_ACTION_LABELS: Record<string, string> = Object.fromEntries(
  [...SKIN_ACTIONS.sd, ...SKIN_ACTIONS.hd].map((a) => [a.value, a.label]),
);

/** 既定の skin ブロック（SD・基本4項目）。最初の「動いた」を取りやすい無難な初期値。 */
export function createSkinBlock(): SkinBlock {
  return {
    id: crypto.randomUUID(),
    kind: 'skin',
    title: '肌診断',
    resolution: 'sd',
    dstActions: ['wrinkle', 'pore', 'texture', 'acne'],
  };
}

/** skin ブロックの実行前検証（空・系統不一致を API に投げる前に弾く＝units と撮影リトライを無駄にしない）。 */
export function validateSkin(block: SkinBlock): string | null {
  if (block.dstActions.length === 0) return '診断する項目を1つ以上選んでください。';
  const allowed = new Set(SKIN_ACTIONS[block.resolution].map((a) => a.value));
  if (!block.dstActions.every((a) => allowed.has(a))) {
    return 'SD と HD の項目は混在できません。どちらか一方に統一してください。';
  }
  return null;
}

// ── effect カテゴリの分類（編集 UI のフォーム出し分けを domain 側で定義）──────────
//   ① 無パターン系  ② パターン+palettes 系  ③ lip_color（特殊）。

/** 無パターン系（pattern 不要・フラットなパラメータ）。 */
export const NO_PATTERN_CATEGORIES = ['skin_smooth', 'foundation', 'concealer'] as const;

/** パターン必須カテゴリ（pattern.name + palettes）。eyebrows も本 POC ではここに含める。 */
export const PATTERN_CATEGORIES: readonly PatternCategory[] = [
  'blush',
  'bronzer',
  'contour',
  'highlighter',
  'eye_shadow',
  'eye_liner',
  'eyelashes',
  'lip_liner',
  'eyebrows',
];

/** 選択肢に出す全カテゴリ（順序＝編集 UI のセレクトの並び）。 */
export const ALL_CATEGORIES: readonly MakeupCategory[] = [
  ...NO_PATTERN_CATEGORIES,
  ...PATTERN_CATEGORIES,
  'lip_color',
];

/** category のラベル（編集 UI 表示用）。 */
export const CATEGORY_LABELS: Record<MakeupCategory, string> = {
  skin_smooth: '肌補正 (skin_smooth)',
  foundation: 'ファンデ (foundation)',
  concealer: 'コンシーラ (concealer)',
  blush: 'チーク (blush)',
  bronzer: 'ブロンザー (bronzer)',
  contour: 'シェーディング (contour)',
  highlighter: 'ハイライト (highlighter)',
  eye_shadow: 'アイシャドウ (eye_shadow)',
  eye_liner: 'アイライナー (eye_liner)',
  eyelashes: 'まつげ (eyelashes)',
  lip_liner: 'リップライナー (lip_liner)',
  eyebrows: '眉 (eyebrows)',
  lip_color: 'リップ (lip_color)',
};

/** pattern.name + palettes が必須のカテゴリか（型ガード）。 */
export function isPatternCategory(category: MakeupCategory): category is PatternCategory {
  return (PATTERN_CATEGORIES as readonly string[]).includes(category);
}

/** カテゴリ既定の MakeupEffect を1つ作る（編集 UI の「効果を追加」用）。 */
export function createEffect(category: MakeupCategory): MakeupEffect {
  switch (category) {
    case 'skin_smooth':
      return { category, skinSmoothStrength: 50, skinSmoothColorIntensity: 50 };
    case 'foundation':
      return { category, color: '#e0b9a0', colorIntensity: 50 };
    case 'concealer':
      return { category, color: '#e8c0a8', colorIntensity: 50 };
    case 'lip_color':
      return {
        category,
        shape: { name: '' },
        style: { type: 'full' },
        palettes: [{ color: '#d11c43' }],
      };
    default:
      // パターン必須カテゴリ。pattern 未選択（空）から始め、UI が label を選ばせる。
      return { category, pattern: { name: '' }, palettes: [{ color: '#d96b6b' }] };
  }
}

// ── 起点画像の解決（実行フェーズ）─────────────────────────────────────────────
/**
 * 機能A の選択を、実行用の body 断片（src_file_id / src_file_url）に解決する。
 *   - url 経路: そのまま src_file_url（File API 不要）。
 *   - upload 経路: その時点で feature を指定して uploadFile を呼び src_file_id を発行。
 *     （file_id は feature 単位発行のため、編集時ではなく実行時に確定する。機能A の設計どおり）
 * 機能C のチェイン実行もこのヘルパを再利用する。
 */
export async function resolveSource(
  feature: string,
  source: SourceSelection,
): Promise<{ src_file_id: string } | { src_file_url: string }> {
  if (source.type === 'url') return { src_file_url: source.url };
  const fileId = await uploadFile(feature, source.file);
  return { src_file_id: fileId };
}

// ── effects の実行前検証（UI ではなく domain に集約）────────────────────────────
//   多色と palettes 数の不一致・texture 依存の必須欄漏れなど、API エラーになる前に弾く。

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

/** 1色ぶんの palette を検証。texture により追加必須欄が変わる。 */
function validatePalette(p: MakeupPalette, where: string): string | null {
  if (!HEX_COLOR.test(p.color)) {
    return `${where}の色は #RRGGBB 形式で指定してください。`;
  }
  if (p.texture === 'shimmer') {
    if (!p.shimmerColor || !HEX_COLOR.test(p.shimmerColor)) {
      return `${where}は shimmer のため shimmerColor（#RRGGBB）が必要です。`;
    }
    if (p.shimmerDensity === undefined) {
      return `${where}は shimmer のため shimmerDensity が必要です。`;
    }
  }
  if (p.texture === 'satin' && p.glowStrength === undefined) {
    return `${where}は satin のため glowStrength が必要です。`;
  }
  return null;
}

/** 1 effect を検証。問題があれば読めるメッセージ、無ければ null。 */
export function validateEffect(effect: MakeupEffect): string | null {
  const name = CATEGORY_LABELS[effect.category];
  switch (effect.category) {
    case 'skin_smooth':
      return null; // 省略時は API が自動で 50 を当てる。必須項目なし。
    case 'foundation':
    case 'concealer':
      return HEX_COLOR.test(effect.color) ? null : `${name}の色は #RRGGBB 形式で指定してください。`;
    case 'lip_color': {
      if (!effect.shape.name) return `${name}のシェイプを選んでください。`;
      if (effect.palettes.length === 0) return `${name}の色を1つ以上指定してください。`;
      for (let i = 0; i < effect.palettes.length; i++) {
        const m = validatePalette(effect.palettes[i], `${name} の色${i + 1}`);
        if (m) return m;
      }
      return null;
    }
    default: {
      // パターン必須カテゴリ。
      if (!effect.pattern.name) return `${name}のパターンを選んでください。`;
      if (effect.palettes.length === 0) return `${name}の色を1つ以上指定してください。`;
      for (let i = 0; i < effect.palettes.length; i++) {
        const m = validatePalette(effect.palettes[i], `${name} の色${i + 1}`);
        if (m) return m;
      }
      return null;
    }
  }
}

/**
 * makeup ブロックの effects 全体を実行前に検証する。
 * @returns 最初に見つかった問題の読めるメッセージ。問題なしなら null。
 */
export function validateEffects(effects: MakeupEffect[]): string | null {
  if (effects.length === 0) return 'メイクの効果を1つ以上追加してください。';
  for (const e of effects) {
    const m = validateEffect(e);
    if (m) return m;
  }
  return null;
}

/** look ブロックの実行前検証（テンプレ未選択を API に投げる前に弾く＝units を無駄にしない）。 */
export function validateLook(block: LookBlock): string | null {
  return block.templateId ? null : '完成ルックのテンプレートを選んでください。';
}

// ── 入力ファイル仕様（docs/api-basics.md「入力ファイルの仕様」）──────────────
//   サイズ・形式はここ（事前チェック）で弾く。
//   寸法・顔幅は API 側の error_* に委ねる（POC は自動リサイズしない）。
export const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB
export const ALLOWED_MIME_TYPES = ['image/jpeg', 'image/png'] as const;
const ALLOWED_EXTENSIONS = ['jpg', 'jpeg', 'png'];

/**
 * アップロード経路の事前チェック。
 * @returns 問題があれば読めるエラーメッセージ、無ければ null。
 */
export function validateSourceFile(file: File): string | null {
  const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
  const typeOk =
    (ALLOWED_MIME_TYPES as readonly string[]).includes(file.type) ||
    ALLOWED_EXTENSIONS.includes(ext);
  if (!typeOk) {
    return '対応していない形式です。jpg / jpeg / png の画像を選んでください。';
  }
  if (file.size >= MAX_FILE_SIZE) {
    return `ファイルサイズが大きすぎます（${(file.size / 1024 / 1024).toFixed(1)}MB）。10MB 未満にしてください。`;
  }
  return null;
}

/**
 * URL 経路の軽い形式チェック（http/https のみ）。実在性は確認しない。
 * @returns 問題があれば読めるエラーメッセージ、無ければ null。
 */
export function validateSourceUrl(url: string): string | null {
  const trimmed = url.trim();
  if (!trimmed) {
    return '画像 URL を入力してください。';
  }
  if (!/^https?:\/\/.+/i.test(trimmed)) {
    return 'http(s):// で始まる公開アクセス可能な画像 URL を入力してください。';
  }
  return null;
}
