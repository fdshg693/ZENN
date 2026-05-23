// domain/routine.ts — ルーティン実行のオーケストレーション（機能C → 機能D で汎用化）。
//   bundle: 連続 makeup の effects を1配列へ統合し makeup-vto を1タスク実行（速い・安い）。
//   chain : ブロックごとに1タスク。前ステップの結果 url を次の src_file_url に渡す（途中経過が見える）。
//   実機確認: makeup-vto / look-vto とも dst_id を返さないため、受け渡しは結果 url（公開 S3・約2時間有効）。
//
//   ★ 機能D の中核改修: 実行対象を makeup 専用 → makeup + look の汎用へ広げる。
//     足すのは「種別ごとの feature 名（featureOf）」「種別ごとの実行関数（runBlock）」「種別ごとの検証（validateBlock）」
//     の3つの振り分けだけ。bundle は effects 統合専用なので look が混ざれば chain へ自動切替（全体設計 6-1 の安全弁）。
//   domain は reducer/Context を知らないので、進捗はコールバック（RoutineProgress）で UI へ橋渡しする。

import {
  resolveSource,
  validateEffects,
  validateLook,
  validateSkin,
  type AiBlock,
  type Block,
  type MakeupBlock,
  type SourceSelection,
} from './blocks';
import { runMakeup } from '../api/makeupVto';
import { runLook } from '../api/lookVto';
import { runSkin } from '../api/skinAnalysis';
import type { RunOutput } from '../api/task';
import type { MakeupEffect } from '../api/types';

type SrcRef = { src_file_id: string } | { src_file_url: string };

/** 各ステップの進捗を state へ橋渡しするコールバック。UI 側が中身で RUN_* を dispatch する。 */
export interface RoutineProgress {
  onStepStart(blockId: string): void;
  onStepSuccess(blockId: string, out: RunOutput): void; // 画像（image）or 診断（skin）。kind で分岐。
  onStepError(blockId: string, message: string): void; // task.ts が整形済みのメッセージ
}

/** ブロック種別 → feature 名（File API / Task のエンドポイントの feature セグメント）。 */
export function featureOf(block: AiBlock): string {
  return block.kind === 'look' ? 'look-vto' : block.kind === 'skin' ? 'skin-analysis' : 'makeup-vto';
}

/** 1ブロックを実行し RunOutput（画像 or 診断）を返す。chain / 単発（RunPanel）の双方から使う。 */
export async function runBlock(block: AiBlock, src: SrcRef): Promise<RunOutput> {
  if (block.kind === 'skin') {
    return { kind: 'skin', skin: await runSkin(src, block.resolution, block.dstActions) };
  }
  const out = block.kind === 'look' ? await runLook(src, block.templateId) : await runMakeup(src, block.effects);
  return { kind: 'image', ...out };
}

/** 1ブロックの実行前検証（種別ごと）。問題があれば読めるメッセージ、無ければ null。 */
export function validateBlock(block: AiBlock): string | null {
  return block.kind === 'skin' ? validateSkin(block)
    : block.kind === 'look' ? validateLook(block)
    : validateEffects(block.effects);
}

/** 実行対象（makeup + look + skin）を並び順で取り出す。source は起点なので除外。 */
function aiBlocksOf(blocks: Block[]): AiBlock[] {
  return blocks.filter(
    (b): b is AiBlock => b.kind === 'makeup' || b.kind === 'look' || b.kind === 'skin',
  );
}

/**
 * ルーティンを実行する。execution に応じて bundle / chain を選ぶ。
 *   - source: 起点画像（機能A）。先頭ステップの src を resolveSource で解決。
 *   - cb: 各ステップの進捗（RUN_*）を逐次通知。chain のステップ失敗は以降を中断する。
 */
export async function runRoutine(
  blocks: Block[],
  source: SourceSelection,
  execution: 'bundle' | 'chain',
  cb: RoutineProgress,
): Promise<void> {
  const ai = aiBlocksOf(blocks);
  if (ai.length === 0) return;

  // 実行前に全ブロックを検証（API に投げる前に弾く＝units を無駄に消費しない）。
  for (const b of ai) {
    const invalid = validateBlock(b);
    if (invalid) return cb.onStepError(b.id, invalid);
  }

  // look は effects に統合できない。bundle 指定でも look が混ざれば自動的に chain へ（安全弁）。
  const bundlable = execution === 'bundle' && ai.every((b) => b.kind === 'makeup');
  if (bundlable) await runBundle(ai as MakeupBlock[], source, cb);
  else await runChain(ai, source, cb);
}

/** bundle: 全 makeup の effects を1配列へ統合 → 1タスク（makeup 専用。安全弁が全 makeup を保証）。
 *  1タスクなので統合した全ブロックを同時 running にし、同じ結果 url で success にする。 */
async function runBundle(makeups: MakeupBlock[], source: SourceSelection, cb: RoutineProgress) {
  const effects: MakeupEffect[] = makeups.flatMap((b) => b.effects);
  makeups.forEach((b) => cb.onStepStart(b.id));
  try {
    const src = await resolveSource('makeup-vto', source); // 起点は1回だけ解決（file_id の二重発行を防ぐ）
    const out = await runMakeup(src, effects);
    // makeup は必ず画像結果。RunOutput（kind:'image'）に持ち上げて各ブロックへ同じ最終画像を反映。
    makeups.forEach((b) => cb.onStepSuccess(b.id, { kind: 'image', ...out }));
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    makeups.forEach((b) => cb.onStepError(b.id, message));
  }
}

/** chain: ブロックごとに1タスク。前ステップの「変換」結果 url を次の src_file_url に渡す（makeup / look / skin 混在可）。
 *  ★ skin は測定タップ＝作業画像を進めない。入力は「直近の変換結果 url があればそれ／
 *    無ければ起点を“このブロックの feature”で解決」。これが ①先頭 skin（upload）→ 次 makeup で
 *    各 feature の file_id を正しく発行、② skin → makeup を元画像に適用（Before 診断）、の双方を成立させる。
 *  途中失敗は以降のステップを実行しない（残りは idle のまま）。 */
async function runChain(blocks: AiBlock[], source: SourceSelection, cb: RoutineProgress) {
  let workUrl: string | null = null; // 直近の変換（image）結果。skin では更新しない。
  for (const block of blocks) {
    cb.onStepStart(block.id);
    try {
      const src: SrcRef = workUrl
        ? { src_file_url: workUrl } // 前段の変換結果（feature 非依存の url）
        : await resolveSource(featureOf(block), source); // まだ変換が無い → 起点を当該 feature で解決
      const out = await runBlock(block, src);
      cb.onStepSuccess(block.id, out);
      if (out.kind === 'image') workUrl = out.resultUrl; // 変換ブロックのみ作業画像を進める（skin は据え置き）
    } catch (e) {
      cb.onStepError(block.id, e instanceof Error ? e.message : String(e));
      return; // 直列の手順なので以降は中断
    }
  }
}
