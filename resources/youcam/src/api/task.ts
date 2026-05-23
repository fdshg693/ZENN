// api/task.ts — 汎用の非同期タスク実行（全 AI 機能の共通骨格）。
//   全機能が「File → Task → Poll → Result」の同じ流れなので、骨格をここに1つ持ち、
//   各機能ファイル（makeupVto.ts 等）は feature 名と body 形だけを渡す。
//   ★ チェイン（機能C）の土台は「結果 url を次タスクの src_file_url に渡す」こと。
//     実機確認: makeup-vto は dst_id を返さず成功レスポンスは data.results.url。
//     dst_id は skin-analysis 固有の可能性が高く未確認なので、取れれば併せて返す（extractResult が両対応）。
//     レスポンスの取り出しはここ（extractResult）に集約する。

import { client, ApiError, describeErrorCode } from './client';
import type { SkinResult, TaskResultItem, TaskStartResponse, TaskStatusResponse } from './types';

/**
 * タスクの結果。チェイン（機能C）の起点は resultUrl を次タスクの src_file_url に渡すこと。
 * dstId は dst_id を返す機能（skin-analysis の可能性・未確認）でのみ入る。makeup-vto では undefined。
 */
export interface TaskOutput {
  resultUrl: string;
  dstId?: string;
}

/**
 * 実行結果を「画像」と「診断」の判別共用体に一般化する（機能E）。
 *   makeup/look は image（結果 url 1枚）、skin は skin（スコア群）。
 *   RunPanel / RunStatus / runChain がこの kind で分岐する（kind を見れば型が確定）。
 */
export type RunOutput =
  | { kind: 'image'; resultUrl: string; dstId?: string } // 機能B/D: 変換ブロックの結果画像
  | { kind: 'skin'; skin: SkinResult }; // 機能E: 測定ブロックの診断スコア

const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * results の入れ子の揺れを1か所で吸収する。
 *   results は配列 or 単体、URL は url / download_url、dst_id は同階層 or data[] 内にあり得る。
 */
function extractResult(results: TaskResultItem | TaskResultItem[] | undefined): TaskOutput | null {
  const item = Array.isArray(results) ? results[0] : results;
  if (!item) return null;
  const url = item.url ?? item.download_url ?? item.data?.[0]?.url;
  const dstId = item.dst_id ?? item.data?.[0]?.dst_id;
  return url ? { resultUrl: url, dstId } : null;
}

/**
 * start → poll（緩い間隔＋全体タイムアウト）し、success 時の生 data を返す（取り出しは呼び側）。
 *   units（クレジット）は success 時のみ消費。失敗・タイムアウト・ポーリング中は非消費。
 *   ★ 機能E の核: 肌診断は成功ペイロードが url ではないので、ポーリングだけ共通化し、
 *     取り出し（結果 url か診断スコアか）は feature 側に委ねる。makeup/look は extractResult、
 *     skin は extractSkin（skinAnalysis.ts）が生 data から取り出す。
 *
 * @param feature - 'makeup-vto' / 'skin-analysis' など。エンドポイントの feature セグメントになる。
 * @param body    - タスク開始リクエスト（各機能ファイルが組み立てた body）。
 */
export async function pollTask<
  T extends { task_status: string; error?: string; error_message?: string },
>(
  feature: string,
  body: unknown,
  { intervalMs = 1500, timeoutMs = 120_000 }: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<T> {
  const start = await client.post<TaskStartResponse>(`/s2s/v2.0/task/${feature}`, body);
  const taskId = start.data.task_id;

  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const st = await client.get<{ data: T }>(`/s2s/v2.0/task/${feature}/${taskId}`);
    const r = st.data;

    if (r.task_status === 'success') return r;
    if (r.task_status === 'error') {
      // タスクレベルのエラーは HTTP 200 で返るため client.ts の整形を通らない。
      //   ここで describeErrorCode を使い、生コード（error_no_face 等）を読めるメッセージに変換する。
      const message = describeErrorCode(r.error) ?? r.error_message ?? r.error ?? 'タスクが失敗しました。';
      throw new ApiError(message, r.error);
    }
    if (Date.now() > deadline) throw new ApiError('タスクがタイムアウトしました。');

    await delay(intervalMs);
  }
}

/**
 * 機能B/D: 結果 url を返す従来の runTask は pollTask + extractResult に再構成（戻り値・挙動は不変）。
 *   makeup/look は無改変でこのまま通る。
 */
export async function runTask(feature: string, body: unknown, opts = {}): Promise<TaskOutput> {
  const r = await pollTask<TaskStatusResponse['data']>(feature, body, opts);
  const out = extractResult(r.results);
  if (!out) throw new ApiError('結果 URL が取得できませんでした。');
  return out;
}
