// api/catalog.ts — パターン必須カテゴリの「カタログ JSON」を取得し、選択肢化する。
//   blush 等は pattern.name に「カタログ JSON 内の label 値」を指定する必要がある。
//   ここで label / thumbnail / colorNum を取り出し、MakeupEditor がそのまま選択肢に使う。
//
//   ★ カタログ JSON は API 本体とは別ホスト（plugins-media.makeupar.com）。
//     CORS を避けるため vite.config.ts の dev proxy（/catalog）経由で取得する。
//   ★ JSON の正確な構造は未検証のため、配列＋label を寛容に探す実装にしてある
//     （実挙動を Playground で確認できたら抽出ロジックを固められる）。

import type { PatternCategory } from './types';

/** UI に出す1パターンの選択肢。colorNum ぶんの palettes 入力を MakeupEditor が強制する。 */
export interface PatternOption {
  label: string; // pattern.name に渡す値
  thumbnail?: string; // サムネイル画像 URL（あれば）
  colorNum: number; // 必要な palettes 数（多色パターン）。不明なら 1。
}

// dev proxy（/catalog → https://plugins-media.makeupar.com）経由のパス。
//   eye_shadow→eyeshadow、eye_liner→eyeliner、lip_liner→lipliner のように
//   ファイル名はアンダースコア無し。lip_color のみ shapes/ 配下。
const CATALOG_PATHS: Record<PatternCategory | 'lip_color', string> = {
  blush: '/catalog/wcm-saas/patterns/blush.json',
  bronzer: '/catalog/wcm-saas/patterns/bronzer.json',
  contour: '/catalog/wcm-saas/patterns/contour.json',
  highlighter: '/catalog/wcm-saas/patterns/highlighter.json',
  eyebrows: '/catalog/wcm-saas/patterns/eyebrows.json',
  eye_shadow: '/catalog/wcm-saas/patterns/eyeshadow.json',
  eye_liner: '/catalog/wcm-saas/patterns/eyeliner.json',
  eyelashes: '/catalog/wcm-saas/patterns/eyelashes.json',
  lip_liner: '/catalog/wcm-saas/patterns/lipliner.json',
  lip_color: '/catalog/wcm-saas/shapes/lipshape.json',
};

/** カテゴリ別キャッシュ（同じ JSON を何度も取りに行かない）。 */
const cache = new Map<string, PatternOption[]>();

/** JSON の中から「label を持つオブジェクトの配列」を再帰的に探す（構造の揺れに寛容）。 */
function findItems(node: unknown): Record<string, unknown>[] | null {
  if (Array.isArray(node)) {
    const objs = node.filter(
      (v): v is Record<string, unknown> => typeof v === 'object' && v !== null && 'label' in v,
    );
    if (objs.length > 0) return objs;
  }
  if (typeof node === 'object' && node !== null) {
    for (const value of Object.values(node as Record<string, unknown>)) {
      const found = findItems(value);
      if (found) return found;
    }
  }
  return null;
}

/** 任意のキー候補から数値を拾う（colorNum / color_num など名称の揺れに対応）。 */
function pickNumber(item: Record<string, unknown>, keys: string[]): number | undefined {
  for (const k of keys) {
    const v = item[k];
    if (typeof v === 'number') return v;
    if (typeof v === 'string' && v.trim() !== '' && !Number.isNaN(Number(v))) return Number(v);
  }
  return undefined;
}

function pickString(item: Record<string, unknown>, keys: string[]): string | undefined {
  for (const k of keys) {
    const v = item[k];
    if (typeof v === 'string' && v) return v;
  }
  return undefined;
}

/**
 * 指定カテゴリのパターン選択肢を取得する（カテゴリ別キャッシュ付き）。
 * @throws Error - 取得・パースに失敗した場合（MakeupEditor が読めるメッセージで表示）。
 */
export async function loadPatterns(category: PatternCategory | 'lip_color'): Promise<PatternOption[]> {
  const cached = cache.get(category);
  if (cached) return cached;

  const path = CATALOG_PATHS[category];
  const res = await fetch(path);
  if (!res.ok) {
    throw new Error(`パターン一覧の取得に失敗しました（HTTP ${res.status}）。`);
  }

  const json = (await res.json()) as unknown;
  const items = findItems(json);
  if (!items) {
    throw new Error('パターン一覧の形式を解釈できませんでした。');
  }

  const options: PatternOption[] = items.map((item) => ({
    label: String(item.label),
    thumbnail: pickString(item, ['thumbnail', 'thumbnailUrl', 'thumb', 'preview']),
    colorNum: pickNumber(item, ['colorNum', 'color_num', 'colors', 'colorCount']) ?? 1,
  }));

  cache.set(category, options);
  return options;
}
