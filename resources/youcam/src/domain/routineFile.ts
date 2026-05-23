// domain/routineFile.ts — 機能F の中核: ルーティンの JSON 直列化（export）と外部 JSON の復元（import）。
//   UI 非依存・API 非依存。機能F はネットワークを発生させない（PLAN「利用 API: なし」）。
//   AiBlock（makeup|look|skin）は blocks.ts の設計上そのまま直列化できる素直な値だけを持つ。
//   source（顔画像）と runs（結果 url）は意図的に含めない（プライバシー／揮発する S3 url）。

import {
  ALL_CATEGORIES,
  validateEffects,
  validateSkin,
  type AiBlock,
  type SkinBlock,
} from './blocks';
import type { MakeupEffect } from '../api/types';

/** これがファイルとして書き出され、他人が取り込む単位。共有 JSON のスキーマの正本。 */
export interface SharedRoutine {
  app: 'youcam-routine-share'; // 別アプリの JSON を取り違えないための識別子（マジック）
  version: 1; // スキーマ版。将来変えたら import 側で弾く / 変換する分岐点
  execution: 'bundle' | 'chain'; // 機能C: 実行方式も共有対象
  blocks: AiBlock[]; // makeup / look / skin の並び（source は含めない）
}

/** parse の結果。成功なら state に流せる素材、失敗なら読めるエラー。例外を投げず Result で返す。 */
export type ParseResult =
  | { ok: true; execution: 'bundle' | 'chain'; blocks: AiBlock[] }
  | { ok: false; error: string };

/**
 * export 側。AiBlock は素直な値のみ＝そのまま安全に直列化できる。
 * source / runs を含めないことが要点（呼び出し側が selectAiBlocks で渡す＝source は既に除外済み）。
 */
export function serializeRoutine(blocks: AiBlock[], execution: 'bundle' | 'chain'): string {
  const shared: SharedRoutine = { app: 'youcam-routine-share', version: 1, execution, blocks };
  return JSON.stringify(shared, null, 2);
}

/**
 * import 側（機能F の本体）。外部 JSON は信頼できないので、state に入れる前に段階的に検証する。
 *   ① JSON パース ② 封筒（app/version/execution/blocks）③ 各ブロックの構造・enum
 *   ④ 意味検証は既存 validate* に委譲（正本を二重定義しない）⑤ id を再発行（衝突回避）。
 * 各段で落ちたら { ok:false, error } を返し、例外でクラッシュさせない。
 */
export function parseRoutine(text: string): ParseResult {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return { ok: false, error: 'JSON として読めませんでした。ファイルの中身を確認してください。' };
  }

  // ── 封筒の検証 ──────────────────────────────────────────────
  if (!isObject(raw)) return { ok: false, error: 'ルーティン JSON の形式ではありません。' };
  if (raw.app !== 'youcam-routine-share')
    return { ok: false, error: 'このアプリのルーティン JSON ではありません。' };
  if (raw.version !== 1)
    return { ok: false, error: `対応していないバージョン（version ${String(raw.version)}）です。` };
  if (raw.execution !== 'bundle' && raw.execution !== 'chain')
    return { ok: false, error: 'execution は bundle / chain のいずれかです。' };
  if (!Array.isArray(raw.blocks)) return { ok: false, error: 'blocks が配列ではありません。' };

  // ── 各ブロックの構造・enum 検証 ──────────────────────────────
  const blocks: AiBlock[] = [];
  for (let i = 0; i < raw.blocks.length; i++) {
    const b = raw.blocks[i];
    const where = `ブロック${i + 1}`;
    if (!isObject(b) || typeof b.title !== 'string') {
      return { ok: false, error: `${where}の形式が不正です。` };
    }
    const title = b.title; // 構造検証済み（空文字は許容＝編集 UI で付け直せる）

    switch (b.kind) {
      case 'makeup': {
        if (!Array.isArray(b.effects))
          return { ok: false, error: `${where}（メイク）の effects が配列ではありません。` };
        if (
          !b.effects.every(
            (e) => isObject(e) && (ALL_CATEGORIES as readonly string[]).includes(e.category as string),
          )
        )
          return { ok: false, error: `${where}（メイク）に未知のカテゴリが含まれます。` };
        // 色形式・パターン未選択など意味検証も機能B の正本に流用する。
        const m = validateEffects(b.effects as MakeupEffect[]);
        if (m) return { ok: false, error: `${where}（メイク）: ${m}` };
        blocks.push({
          id: crypto.randomUUID(),
          kind: 'makeup',
          title,
          effects: b.effects as MakeupEffect[],
        });
        break;
      }
      case 'look': {
        if (typeof b.templateId !== 'string')
          return { ok: false, error: `${where}（完成ルック）の templateId が不正です。` };
        // 未選択・未収載 id は弾かない（取り込み後に LookEditor で選び直せる。実行前 validateLook が最終的に弾く）。
        blocks.push({ id: crypto.randomUUID(), kind: 'look', title, templateId: b.templateId });
        break;
      }
      case 'skin': {
        if (b.resolution !== 'sd' && b.resolution !== 'hd')
          return { ok: false, error: `${where}（肌診断）の resolution が不正です。` };
        if (!Array.isArray(b.dstActions) || !b.dstActions.every((a) => typeof a === 'string'))
          return { ok: false, error: `${where}（肌診断）の dstActions が不正です。` };
        const skin: SkinBlock = {
          id: crypto.randomUUID(),
          kind: 'skin',
          title,
          resolution: b.resolution,
          dstActions: b.dstActions as string[],
        };
        // SD/HD 混在・空を弾く（機能E の検証を再利用）。
        const s = validateSkin(skin);
        if (s) return { ok: false, error: `${where}（肌診断）: ${s}` };
        blocks.push(skin);
        break;
      }
      default:
        return { ok: false, error: `${where}: 未知のブロック種別「${String(b.kind)}」です。` };
    }
  }

  return { ok: true, execution: raw.execution, blocks };
}

/** プレーンオブジェクト（配列・null 以外）の型ガード。外部 JSON の入口で使う。 */
function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}
