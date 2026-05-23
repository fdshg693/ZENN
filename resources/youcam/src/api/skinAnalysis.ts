// api/skinAnalysis.ts — 機能E: skin-analysis 固有の差分（取り出しを含む）。
//   API の骨格（File → Task → Poll）は makeup/look と同じだが、成功ペイロードが結果 url 1枚ではない。
//   そこで start→poll の中核（pollTask）は task.ts と共有し、ここは ①body 形（dst_actions）と
//   ②結果取り出し（output[] / score_info の keyed map の揺れ吸収）の2点だけを持つ。

import { pollTask } from './task';
import type { SkinResult, SkinScore, SkinStatusData } from './types';

/**
 * 肌診断を1タスク実行し、SkinResult（スコア群）を返す。
 *   dst_actions は SD/HD 一系統に統一済み前提（domain.validateSkin が実行前に裏当て）。
 *   format:'json' 固定で mask_urls を JSON で受ける（ZIP 強制を回避）。
 *
 * @param src        - 起点画像の解決済み参照（src_file_id / src_file_url のどちらか）。domain.resolveSource が組み立てる。
 * @param resolution - 'sd' | 'hd'。dst_actions の系統と一致している前提（混在は InvalidParameters）。
 * @param dstActions - 解析する診断項目（resolution の系統に属するもののみ）。
 */
export async function runSkin(
  src: { src_file_id: string } | { src_file_url: string },
  _resolution: 'sd' | 'hd',
  dstActions: string[],
): Promise<SkinResult> {
  const data = await pollTask<SkinStatusData>('skin-analysis', {
    ...src,
    dst_actions: dstActions,
    format: 'json',
  });
  return extractSkin(data);
}

/**
 * results の形の揺れを1か所で吸収する。
 *   ①output[] 形（実機確認済み・第一）: フラットな配列に診断項目と特殊項目が混在する。
 *     - 診断項目（type='wrinkle' 等）: { ui_score, raw_score, mask_urls }。
 *     - type='all': 総合点（値は score フィールド）。type='skin_age': 推定肌年齢（同 score）。
 *     - type='resize_image': 解析用にリサイズされた元画像（mask_urls のみ・スコアではない）→ 一覧から除外。
 *   ②score_info の keyed map 形（ZIP 由来のフォールバック）: results['wrinkle'] = { ui_score, raw_score } …。
 */
function extractSkin(data: SkinStatusData): SkinResult {
  const r = data.results ?? {};

  if (Array.isArray(r.output)) {
    const scores: SkinScore[] = [];
    let overall: number | undefined;
    let skinAge: number | undefined;
    for (const o of r.output) {
      if (o.type === 'all') overall = o.score;
      else if (o.type === 'skin_age') skinAge = o.score;
      else if (o.type === 'resize_image') continue; // 解析用リサイズ画像。スコアではない。
      else {
        scores.push({
          type: o.type,
          uiScore: o.ui_score ?? 0,
          rawScore: o.raw_score,
          maskUrls: o.mask_urls ?? undefined,
        });
      }
    }
    return { scores, overall, skinAge };
  }

  // ②keyed map 形（フォールバック）。診断項目以外のキー（all / skin_age / output）は除外する。
  const reserved = new Set(['all', 'skin_age', 'output']);
  const scores = Object.entries(r)
    .filter(([key, value]) => !reserved.has(key) && value != null && typeof value === 'object')
    .map(([key, value]) => {
      const v = value as { ui_score?: number; raw_score?: number; mask_urls?: string[] };
      return { type: key, uiScore: v.ui_score ?? 0, rawScore: v.raw_score, maskUrls: v.mask_urls };
    });
  return { scores, overall: r.all?.score, skinAge: r.skin_age };
}
