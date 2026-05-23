// api/lookVto.ts — 機能D: look-vto 固有の差分だけ（実処理は task.ts に委譲）。
//   makeup-vto と同形の成功レスポンス（data.results.url・dst_id 無し）なので runTask をそのまま使う。
//   look 固有なのは ①テンプレ一覧 と ②適用 body が effects ではなく template_id の2点だけ。
//
//   ★ テンプレ一覧（~349件）は API を毎回叩かず、ローカル配信のマニフェストを読む:
//     scripts/fetch-look-templates.mjs が一覧＋サムネを public/look-templates/ へ保存し、
//     ここでは fetch('/look-templates/index.json') で読む（高速・オフライン可・CDN 依存の回避）。
//     一覧を更新したいときは `npm run fetch:looks` を実行する。

import { runTask, type TaskOutput } from './task';
import type { LookTemplate, LookTemplateManifest } from './types';

/**
 * 完成ルックを1タスク適用する。
 *   version はリファレンス未記載のため送らない（InvalidParameters が出たら version:'1.0' を足す）。
 *
 * @param src        - 起点画像の解決済み参照（src_file_id / src_file_url のどちらか）。domain.resolveSource が組み立てる。
 * @param templateId - 適用する LookTemplate.id（一覧から選んだ値）。
 */
export function runLook(
  src: { src_file_id: string } | { src_file_url: string },
  templateId: string,
): Promise<TaskOutput> {
  return runTask('look-vto', { ...src, template_id: templateId });
}

// ローカルマニフェストの配信パス（Vite が public/ をルート配信する）。
const MANIFEST_URL = '/look-templates/index.json';

// 一覧はモジュールキャッシュ（同じ JSON を何度も取りに行かない。catalog.ts と同方針）。
let templateCache: LookTemplate[] | null = null;

/**
 * 完成ルックのテンプレ一覧を取得する（ローカルマニフェストから）。
 *   thumb はローカルパス（/look-templates/thumbs/...）に差し替え済み。
 * @throws Error - マニフェストが無い／壊れている場合（LookEditor が読めるメッセージで表示）。
 *                 未生成のときは `npm run fetch:looks` を案内する。
 */
export async function listLookTemplates(): Promise<LookTemplate[]> {
  if (templateCache) return templateCache;

  const res = await fetch(MANIFEST_URL);
  if (!res.ok) {
    throw new Error(
      `完成ルック一覧（${MANIFEST_URL}）が見つかりません（HTTP ${res.status}）。` +
        '`npm run fetch:looks` を実行して一覧をローカルに取得してください。',
    );
  }
  const manifest = (await res.json()) as LookTemplateManifest;
  templateCache = manifest.templates ?? [];
  return templateCache;
}
