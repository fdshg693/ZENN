// api/files.ts — File API の「2段階」を1関数に隠蔽（呼び側はミスれない）。
//   ① POST /file/{feature} で file_id と署名 URL を取得
//   ② その URL に File 実体を PUT（←これを忘れると後続タスクが 500/404）
//
//   ★ file_id は feature 単位で発行される（makeup-vto と skin-analysis は別物）。
//     そのため発行は「実行フェーズで先頭タスクの feature が確定してから」行う。
//     編集フェーズ（機能A）では File 実体だけ保持し、この関数は呼ばない。

import { client } from './client';
import type { FileCreateResponse } from './types';

/**
 * ローカルの File を指定 feature の File API でアップロードし、`file_id` を返す。
 *
 * @param feature - 'makeup-vto' / 'skin-analysis' など。先頭タスクの feature を渡す。
 * @param file    - 編集フェーズで SourceBlock に保持しておいた File 実体。
 * @returns       - 後続タスクの body に `src_file_id` として渡す file_id。
 */
export async function uploadFile(feature: string, file: File): Promise<string> {
  // ① メタを送って file_id と PUT 先 URL を発行（レスポンスは data.files[]）
  const res = await client.post<FileCreateResponse>(`/s2s/v2.0/file/${feature}`, {
    files: [{ content_type: file.type, file_name: file.name, file_size: file.size }],
  });
  const { file_id, requests } = res.data.files[0];

  // ② 実体を PUT。ここまでやって初めて「アップロード済み」になる。
  //    署名 URL はオブジェクトストレージ直叩きのため client を通さず素の fetch を使う。
  const putRes = await fetch(requests[0].url, {
    method: 'PUT',
    headers: { 'Content-Type': file.type, ...(requests[0].headers ?? {}) },
    body: file,
  });
  if (!putRes.ok) {
    throw new Error(`画像のアップロード（PUT）に失敗しました（HTTP ${putRes.status}）。`);
  }

  return file_id; // ← 呼び側（実行フェーズ）が src_file_id として使う
}
