// api/makeupVto.ts — 機能B: makeup-vto 固有の差分だけを定義する。
//   実処理（start → poll → 結果）は task.ts に委譲し、ここは feature 名と body 形だけを持つ。

import { runTask, type TaskOutput } from './task';
import type { MakeupEffect } from './types';

/**
 * makeup-vto を1タスク実行し、結果画像 URL と dst_id を返す。
 *
 * @param src     - 起点画像の解決済み参照（src_file_id / src_file_url のどちらか）。
 *                  どちらか一方は domain.resolveSource が機能A の選択から組み立てる。
 * @param effects - 適用する化粧パーツの配列（MakeupBlock.effects そのもの）。
 */
export function runMakeup(
  src: { src_file_id: string } | { src_file_url: string },
  effects: MakeupEffect[],
): Promise<TaskOutput> {
  return runTask('makeup-vto', { ...src, version: '1.0', effects });
}
