// api/client.ts — 全 API リクエストの単一窓口（純粋な fetch 層）。
//   担うこと: ① Bearer 認証ヘッダ付与 ② baseURL 連結 ③ エラーの「読めるメッセージ」整形
//             ④ 429（レート制限）の指数バックオフ自動リトライ
//   狙い: 「API が原因か」を最初に切り分けられるよう、失敗は必ず整形済みメッセージで投げる。

import type { ApiErrorBody } from './types';

// dev proxy（vite.config.ts）経由で本番サーバへ。これにより開発時は CORS を完全回避する。
const BASE_URL = '/api';

// レート制限（IP/トークンとも 5 QPS・300秒で 250 req）超過時の 429 をどれだけ粘るか。
const MAX_RETRIES = 4;

// API キーはユーザー入力。state の変化に追従して AppContext から差し込む（下の setApiKey）。
let apiKey = '';

/** API キーを設定する。AppContext が state.apiKey の変化時に呼ぶ。 */
export function setApiKey(key: string): void {
  apiKey = key;
}

/** API 由来のエラー。code（API のエラーコード）と status（HTTP）を保持する。 */
export class ApiError extends Error {
  readonly code?: string;
  readonly status?: number;
  constructor(message: string, code?: string, status?: number) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }
}

// 代表的なエラーコード → 読めるメッセージ。docs/api-basics.md「エラーコード」に対応。
//   機能Aでは検知できない顔系（error_no_face 等）も、実行フェーズで整形表示できるよう用意。
const ERROR_MESSAGES: Record<string, string> = {
  InvalidApiKey: 'API キーが不正です。コンソールで発行したキーを確認してください。',
  InactiveApiKey: 'API キーが無効化されています。',
  ExpiredApiKey: 'API キーの有効期限が切れています。',
  CreditInsufficiency: 'クレジット（units）が不足しています。',
  InvalidParameters: 'リクエストのパラメータが不正です。',
  BadRequest: 'リクエストが不正です。',
  InvalidTaskId: 'タスク ID が無効です（24時間で失効します）。',
  TaskTimeout: 'タスクの保持期間が切れました。',
  error_no_face: '顔が検出できませんでした。正面の顔がはっきり写った画像を使ってください。',
  error_multiple_people: '複数の人物が検出されました。1人だけ写った画像を使ってください。',
  error_nsfw_content_detected: '不適切な画像と判定されました。',
  exceed_max_filesize: 'ファイルサイズが上限を超えています。',
  error_large_face_angle: '顔の角度が大きすぎます。正面（±10°以内）の画像を使ってください。',
  error_face_position_too_small: '顔が小さすぎます。顔幅が 100px 以上になる画像を使ってください。',
  unknown_internal_error: 'サーバ内部エラーです（アップロード未完了の可能性があります）。',
  // 機能E: 肌診断は撮影条件がシビアで makeup/look に無い固有コードが出る（読めるメッセージ＝撮り直しの指示）。
  error_src_face_too_small:
    '顔が小さすぎます。顔幅が画像幅の 60% 以上になるよう、顔を大きく写した画像を使ってください。',
  error_lighting_dark: '画像が暗すぎます。明るく均一な照明で撮影した画像を使ってください。',
  error_src_face_out_of_bound:
    '顔が画像の端で見切れています。顔全体が枠内に収まる画像を使ってください。',
  // 実機確認: 小さすぎる画像 → error_below_min_image_size、顔の無い画像（魚など）→ UNKNOWN_ERROR。
  error_below_min_image_size:
    '画像サイズが小さすぎます。SD は短辺 480px 以上、HD は短辺 1080px 以上の画像を使ってください。',
  UNKNOWN_ERROR:
    '解析に失敗しました（顔を検出できなかった可能性があります）。正面の顔がはっきり写った画像を使ってください。',
};

/**
 * エラーコードを「読めるメッセージ」に変換する（無ければ undefined）。
 *   task.ts のタスクレベルエラー（HTTP 200 + task_status:'error'）でも同じ変換を使えるよう公開する。
 */
export function describeErrorCode(code: string | undefined): string | undefined {
  return code ? ERROR_MESSAGES[code] : undefined;
}

/** エラー応答から「読めるメッセージ」を組み立てる。実エラー本文も data ラッパの可能性があるので両方を覗く。 */
function formatError(body: ApiErrorBody | null, status: number): ApiError {
  const b = body?.data ?? body ?? undefined;
  const code = b?.error ?? b?.error_code;
  const mapped = describeErrorCode(code);
  const detail = b?.error_messages?.join(' / ') ?? b?.message;
  const message =
    mapped ?? detail ?? `API リクエストに失敗しました（HTTP ${status}${code ? ` / ${code}` : ''}）。`;
  return new ApiError(message, code, status);
}

const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** 共通リクエスト。成功時はパース済み JSON を T として返す。 */
async function request<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    const res = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${apiKey}`, // "Bearer" とキーの間に半角スペースが必要
        'Content-Type': 'application/json',
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });

    // 429: 指数バックオフ＋ジッタで自動リトライ。
    if (res.status === 429 && attempt < MAX_RETRIES) {
      await delay(2 ** attempt * 500 + Math.random() * 250);
      continue;
    }

    if (!res.ok) {
      const errorBody = (await res.json().catch(() => null)) as ApiErrorBody | null;
      throw formatError(errorBody, res.status);
    }

    return (await res.json()) as T;
  }
}

/** API クライアント。各機能ファイル（files.ts / makeupVto.ts 等）はこれだけを使う。 */
export const client = {
  setApiKey,
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
};
