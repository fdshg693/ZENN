// state/appState.ts — アプリ状態の型・初期値・reducer。
//   状態遷移を1ファイルに集約し、ブロックの追加/削除/並べ替え/実行結果反映を1か所で追えるようにする。
//   機能A: SET_API_KEY / SET_SOURCE。機能B: ADD/UPDATE/REMOVE_MAKEUP と単発実行結果（RUN_*）。

import {
  createLookBlock,
  createMakeupBlock,
  createSkinBlock,
  createSourceBlock,
  type AiBlock,
  type Block,
  type MakeupBlock,
  type SourceBlock,
  type SourceSelection,
} from '../domain/blocks';
import type { MakeupEffect } from '../api/types';
import type { RunOutput } from '../api/task';

// AiBlock（makeup + look）は domain が正本。実行対象を扱う UI が appState 経由で使うため再公開する。
export type { AiBlock } from '../domain/blocks';

// API キーの localStorage キー（任意の永続化。フロント露出のリスクは ApiKeyPanel に明記）。
const API_KEY_STORAGE = 'youcam_api_key';

/** ルーティン = 起点画像 + 並んだブロック + 実行方式（機能C）。 */
export interface Routine {
  blocks: Block[];
  execution: 'bundle' | 'chain';
}

/**
 * ブロック単位の実行状態（機能B は単発）。
 *   success は RunOutput（画像 or 診断）を保持する（機能E で一般化）。
 *   画像（kind:'image'）の resultUrl が機能C のチェイン入力の受け渡し点になる。
 */
export type RunStatus =
  | { phase: 'idle' }
  | { phase: 'running' }
  | { phase: 'success'; output: RunOutput }
  | { phase: 'error'; message: string };

/** アプリ全体の状態。 */
export interface AppState {
  apiKey: string;
  routine: Routine;
  // ブロック id → 実行状態。機能C が多段の進捗表示へ拡張する土台。
  runs: Record<string, RunStatus>;
}

export type Action =
  | { type: 'SET_API_KEY'; key: string }
  | { type: 'SET_SOURCE'; source: SourceSelection | null }
  | { type: 'ADD_MAKEUP' }
  | { type: 'UPDATE_MAKEUP'; id: string; effects: MakeupEffect[] }
  // 機能D: look ブロックの追加・テンプレ選択の反映。
  | { type: 'ADD_LOOK' }
  | { type: 'UPDATE_LOOK'; id: string; templateId: string }
  // 機能E: skin ブロックの追加・診断項目の反映。
  | { type: 'ADD_SKIN' }
  | { type: 'UPDATE_SKIN'; id: string; resolution: 'sd' | 'hd'; dstActions: string[] }
  // 削除は種別非依存に一般化（旧 REMOVE_MAKEUP。makeup / look / skin を消す）。
  | { type: 'REMOVE_BLOCK'; id: string }
  | { type: 'RUN_START'; id: string }
  // 機能E: 成功結果を RunOutput（画像 or 診断）で一般化（旧 { url, dstId } を置換）。
  | { type: 'RUN_SUCCESS'; id: string; output: RunOutput }
  | { type: 'RUN_ERROR'; id: string; message: string }
  // 機能C: 実行方式の切替と、ルーティン実行前の結果クリア。RUN_* は機能B のものを再利用。
  | { type: 'SET_EXECUTION'; execution: 'bundle' | 'chain' }
  | { type: 'RESET_RUNS' }
  // 機能F: 取り込んだルーティンを一括読込。source は温存し AI ブロックと execution を差し替える。
  | { type: 'LOAD_ROUTINE'; blocks: AiBlock[]; execution: 'bundle' | 'chain' };

export const initialState: AppState = {
  // localStorage に保存済みのキーがあれば復元（無ければ空）。
  apiKey: (typeof localStorage !== 'undefined' && localStorage.getItem(API_KEY_STORAGE)) || '',
  // 起点用の SourceBlock を1つだけ持って始める。
  routine: { blocks: [createSourceBlock()], execution: 'chain' },
  runs: {},
};

export function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'SET_API_KEY': {
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem(API_KEY_STORAGE, action.key);
      }
      return { ...state, apiKey: action.key };
    }
    case 'SET_SOURCE': {
      // 唯一の source ブロックに選択結果を反映する（不変更新）。
      const blocks = state.routine.blocks.map((b) =>
        b.kind === 'source' ? { ...b, source: action.source } : b,
      );
      return { ...state, routine: { ...state.routine, blocks } };
    }
    case 'ADD_MAKEUP': {
      // makeup ブロックを末尾に追加（起点 source の後ろに並ぶ）。
      const blocks = [...state.routine.blocks, createMakeupBlock()];
      return { ...state, routine: { ...state.routine, blocks } };
    }
    case 'UPDATE_MAKEUP': {
      // 対象ブロックの effects を差し替える。編集すると実行結果は陳腐化するので idle に戻す。
      const blocks = state.routine.blocks.map((b) =>
        b.id === action.id && b.kind === 'makeup' ? { ...b, effects: action.effects } : b,
      );
      const runs = { ...state.runs, [action.id]: { phase: 'idle' } as RunStatus };
      return { ...state, routine: { ...state.routine, blocks }, runs };
    }
    case 'ADD_LOOK': {
      // look ブロックを末尾に追加（起点 source・既存ブロックの後ろに並ぶ）。
      const blocks = [...state.routine.blocks, createLookBlock()];
      return { ...state, routine: { ...state.routine, blocks } };
    }
    case 'UPDATE_LOOK': {
      // テンプレ選択を反映。編集すると実行結果は陳腐化するので当該ブロックの run を idle に戻す。
      const blocks = state.routine.blocks.map((b) =>
        b.id === action.id && b.kind === 'look' ? { ...b, templateId: action.templateId } : b,
      );
      const runs = { ...state.runs, [action.id]: { phase: 'idle' } as RunStatus };
      return { ...state, routine: { ...state.routine, blocks }, runs };
    }
    case 'ADD_SKIN': {
      // skin ブロックを末尾に追加（起点 source・既存ブロックの後ろに並ぶ）。
      const blocks = [...state.routine.blocks, createSkinBlock()];
      return { ...state, routine: { ...state.routine, blocks } };
    }
    case 'UPDATE_SKIN': {
      // 系統（SD/HD）と診断項目を反映。編集すると実行結果は陳腐化するので run を idle に戻す。
      const blocks = state.routine.blocks.map((b) =>
        b.id === action.id && b.kind === 'skin'
          ? { ...b, resolution: action.resolution, dstActions: action.dstActions }
          : b,
      );
      const runs = { ...state.runs, [action.id]: { phase: 'idle' } as RunStatus };
      return { ...state, routine: { ...state.routine, blocks }, runs };
    }
    case 'REMOVE_BLOCK': {
      // 種別非依存の削除（makeup / look とも id 一致でフィルタ）。
      const blocks = state.routine.blocks.filter((b) => b.id !== action.id);
      const runs = { ...state.runs };
      delete runs[action.id];
      return { ...state, routine: { ...state.routine, blocks }, runs };
    }
    case 'RUN_START':
      return { ...state, runs: { ...state.runs, [action.id]: { phase: 'running' } } };
    case 'RUN_SUCCESS':
      // 成功時の結果（画像 or 診断）を RunOutput で保持。画像なら resultUrl が機能C のチェイン入力になる。
      return {
        ...state,
        runs: { ...state.runs, [action.id]: { phase: 'success', output: action.output } },
      };
    case 'RUN_ERROR':
      return {
        ...state,
        runs: { ...state.runs, [action.id]: { phase: 'error', message: action.message } },
      };
    case 'SET_EXECUTION':
      // 機能C: bundle / chain の切替。
      return { ...state, routine: { ...state.routine, execution: action.execution } };
    case 'RESET_RUNS':
      // 機能C: ルーティン実行前に古い結果を一掃する。
      return { ...state, runs: {} };
    case 'LOAD_ROUTINE': {
      // 機能F: 取り込み側の起点（顔写真）はそのまま温存。無ければ新規 source を1つ用意する。
      const source =
        state.routine.blocks.find((b): b is SourceBlock => b.kind === 'source') ??
        createSourceBlock();
      return {
        ...state,
        routine: { blocks: [source, ...action.blocks], execution: action.execution },
        runs: {}, // 取り込んだブロックは未実行。古い結果（前ルーティンの url）を残さない。
      };
    }
    default:
      return state;
  }
}

/** 現在の起点画像の選択を取り出す（未選択なら null）。 */
export function selectSource(state: AppState): SourceSelection | null {
  const block = state.routine.blocks.find((b): b is SourceBlock => b.kind === 'source');
  return block?.source ?? null;
}

/** makeup ブロックを並び順で取り出す。 */
export function selectMakeupBlocks(state: AppState): MakeupBlock[] {
  return state.routine.blocks.filter((b): b is MakeupBlock => b.kind === 'makeup');
}

/** 実行対象の AI ブロック（makeup + look + skin）を並び順で取り出す。source は起点なので除外。 */
export function selectAiBlocks(state: AppState): AiBlock[] {
  return state.routine.blocks.filter(
    (b): b is AiBlock => b.kind === 'makeup' || b.kind === 'look' || b.kind === 'skin',
  );
}

/** 指定ブロックの実行状態を取り出す（未実行なら idle）。 */
export function selectRun(state: AppState, id: string): RunStatus {
  return state.runs[id] ?? { phase: 'idle' };
}
