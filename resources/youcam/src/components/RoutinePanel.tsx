// components/RoutinePanel.tsx — 機能C: ルーティン（複数ブロック）の連結実行 UI。
//   責務は「方式の選択」「実行の起動」「全体進捗の表示」。実行戦略そのものは domain/routine.ts が持つ。
//   各ステップの {status, resultUrl} 表示は機能B の RunPanel が blockId 単位で描画する（ここでは持たない）。
//   前提チェック（API キー・起点画像）は RunPanel と同じ導線を踏襲する。

import { useAppDispatch, useAppState } from '../state/AppContext';
import { selectAiBlocks, selectSource } from '../state/appState';
import { runRoutine, type RoutineProgress } from '../domain/routine';
import styles from './RoutinePanel.module.css';

type Execution = 'bundle' | 'chain';

const EXECUTION_LABELS: Record<Execution, { title: string; note: string }> = {
  bundle: { title: '一括（bundle）', note: '全ブロックの効果を1配列に統合し、1タスクで適用（速い・安い・途中経過なし）。' },
  chain: { title: 'チェイン（chain）', note: 'ブロックごとに1タスク。前ステップの結果を次の起点に渡す（中間画像が見える）。' },
};

export function RoutinePanel() {
  const state = useAppState();
  const dispatch = useAppDispatch();
  const aiBlocks = selectAiBlocks(state);
  const source = selectSource(state);
  const execution = state.routine.execution;

  // 全体の実行中表示は runs から導出（個別フラグは持たない）。
  const running = aiBlocks.some((b) => state.runs[b.id]?.phase === 'running');

  // 前提（API キー・起点画像・ブロック有無）が揃わなければ実行不可。
  const blocked =
    !state.apiKey ? 'API キーを入力してください。'
    : !source ? '起点画像（機能A）を指定してください。'
    : aiBlocks.length === 0 ? 'ブロック（メイク／完成ルック）を1つ以上追加してください。'
    : null;

  async function handleRun() {
    if (blocked || !source) return;

    // 古い結果を一掃してから実行（前回の中間/最終画像が残らないように）。
    dispatch({ type: 'RESET_RUNS' });

    // domain は reducer を知らないので、進捗コールバックの中で RUN_* を dispatch する。
    const cb: RoutineProgress = {
      onStepStart: (id) => dispatch({ type: 'RUN_START', id }),
      // out は RunOutput（画像 or 診断）。分解せずそのまま渡し、描画は RunPanel が kind 分岐する。
      onStepSuccess: (id, out) => dispatch({ type: 'RUN_SUCCESS', id, output: out }),
      onStepError: (id, message) => dispatch({ type: 'RUN_ERROR', id, message }),
    };

    await runRoutine(state.routine.blocks, source, execution, cb);
  }

  return (
    <section className={styles.panel}>
      <h2 className={styles.heading}>ルーティンの実行</h2>
      <p className={styles.note}>
        並んだブロック（メイク／完成ルック／肌診断）を実行方式に従って連結実行します。各ブロックの進捗・結果は上のブロックごとに表示されます。
        完成ルック・肌診断は effects 統合できないため、bundle を選んでもこれらを含む場合は自動的に chain で実行されます。
        肌診断は測定ブロックで画像を変換しないため、後続のメイクは肌診断の直前と同じ画像に適用されます（Before 診断）。
      </p>

      {/* 方式トグル（bundle / chain → SET_EXECUTION）。 */}
      <div className={styles.options} role="radiogroup" aria-label="実行方式">
        {(Object.keys(EXECUTION_LABELS) as Execution[]).map((value) => (
          <label
            key={value}
            className={execution === value ? styles.optionActive : styles.option}
          >
            <input
              type="radio"
              name="execution"
              value={value}
              checked={execution === value}
              disabled={running}
              onChange={() => dispatch({ type: 'SET_EXECUTION', execution: value })}
            />
            <span className={styles.optionTitle}>{EXECUTION_LABELS[value].title}</span>
            <span className={styles.optionNote}>{EXECUTION_LABELS[value].note}</span>
          </label>
        ))}
      </div>

      <button
        type="button"
        className={styles.runButton}
        onClick={handleRun}
        disabled={running || blocked !== null}
      >
        {running ? '実行中…' : 'ルーティンを実行'}
      </button>

      {blocked && <p className={styles.hint}>{blocked}</p>}
      {running && (
        <p className={styles.status}>
          {execution === 'bundle'
            ? '統合した1タスクを実行しています（ポーリング中）…'
            : 'ブロックを順に実行しています（ポーリング中）…'}
        </p>
      )}
    </section>
  );
}
