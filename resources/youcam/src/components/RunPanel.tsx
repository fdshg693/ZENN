// components/RunPanel.tsx — AI ブロックの「単発実行」UI（機能B → 機能D で種別汎用化）。
//   実行ボタン → running 中はスピナー文言、success で結果画像、error で整形済みメッセージ。
//   feature 名 / 実行関数 / 検証は block 種別で振り分ける（domain/routine.ts の featureOf / runBlock / validateBlock を再利用）。
//   これにより makeup でも look でも「このブロックを実行 → 進捗 → 結果画像」の同じ導線が動く。
//   機能C の RoutinePanel が複数ブロックの連結実行を担い、本パネルは1ブロックの単発実行を担う。

import { useAppDispatch, useAppState } from '../state/AppContext';
import { selectRun, selectSource, type AiBlock } from '../state/appState';
import { resolveSource } from '../domain/blocks';
import { featureOf, runBlock, validateBlock } from '../domain/routine';
import { SkinResultView } from './SkinResultView';
import styles from './RunPanel.module.css';

export function RunPanel({ block }: { block: AiBlock }) {
  const state = useAppState();
  const dispatch = useAppDispatch();
  const run = selectRun(state, block.id);
  const source = selectSource(state);

  const feature = featureOf(block);

  async function handleRun() {
    // 実行前のローカル検証（API に投げる前に弾く。units を無駄に消費しない）。
    if (!state.apiKey) {
      dispatch({ type: 'RUN_ERROR', id: block.id, message: 'API キーを入力してください。' });
      return;
    }
    if (!source) {
      dispatch({ type: 'RUN_ERROR', id: block.id, message: '起点画像（機能A）を指定してください。' });
      return;
    }
    const invalid = validateBlock(block); // makeup は effects、look はテンプレ未選択を弾く
    if (invalid) {
      dispatch({ type: 'RUN_ERROR', id: block.id, message: invalid });
      return;
    }

    dispatch({ type: 'RUN_START', id: block.id });
    try {
      // 起点画像を実行時に解決（upload なら当該 feature の file_id をここで発行）。
      const src = await resolveSource(feature, source);
      // RunOutput（画像 or 診断）をそのまま state へ。描画は success 側で kind 分岐する。
      const output = await runBlock(block, src);
      dispatch({ type: 'RUN_SUCCESS', id: block.id, output });
    } catch (e) {
      // client.ts / task.ts が整形済みメッセージを投げる想定。読めるメッセージをそのまま表示。
      dispatch({ type: 'RUN_ERROR', id: block.id, message: e instanceof Error ? e.message : String(e) });
    }
  }

  const running = run.phase === 'running';

  return (
    <section className={styles.panel}>
      <button type="button" className={styles.runButton} onClick={handleRun} disabled={running}>
        {running ? '実行中…' : 'このブロックを実行'}
      </button>

      {running && <p className={styles.status}>{feature} を実行しています（ポーリング中）…</p>}

      {run.phase === 'error' && (
        <p className={styles.error} role="alert">
          {run.message}
        </p>
      )}

      {run.phase === 'success' && run.output.kind === 'image' && (
        <figure className={styles.result}>
          <img src={run.output.resultUrl} alt="適用結果" className={styles.resultImage} />
          <figcaption className={styles.meta}>
            適用結果（units を消費しました）
            {run.output.dstId ? ` / dst_id: ${run.output.dstId}（チェイン入力に使用）` : ''}
          </figcaption>
        </figure>
      )}

      {run.phase === 'success' && run.output.kind === 'skin' && (
        <figure className={styles.result}>
          <SkinResultView result={run.output.skin} />
          <figcaption className={styles.meta}>診断結果（units を消費しました）</figcaption>
        </figure>
      )}
    </section>
  );
}
