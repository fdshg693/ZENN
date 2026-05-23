// components/editors/SkinEditor.tsx — 機能E: skin ブロックの編集 UI（系統トグル＋項目チェック）。
//   責務は「表示」と「dispatch」のみ。カタログ（SKIN_ACTIONS）・検証は domain が持つ。
//   SD/HD は混在不可（API 仕様）。系統トグルで当該系統の項目しか出さない＝混在を作れない。
//   系統を切り替えたら選択は当該系統で作り直す（前系統の項目が残らない）。

import { useAppDispatch } from '../../state/AppContext';
import { SKIN_ACTIONS, type SkinBlock } from '../../domain/blocks';
import styles from './SkinEditor.module.css';

type Resolution = 'sd' | 'hd';

const RESOLUTION_LABELS: Record<Resolution, { title: string; note: string }> = {
  sd: { title: 'SD（標準）', note: '標準解像度。基本の診断項目。短辺 480px 以上。' },
  hd: { title: 'HD（高精細）', note: '高精細モデル。サブ領域別に細分化。短辺 1080px 以上。' },
};

export function SkinEditor({ block }: { block: SkinBlock }) {
  const dispatch = useAppDispatch();
  const selected = new Set(block.dstActions);

  // 系統切替: 選択は当該系統で作り直す（混在を作れない）。既定で全項目クリア。
  function changeResolution(resolution: Resolution) {
    if (resolution === block.resolution) return;
    dispatch({ type: 'UPDATE_SKIN', id: block.id, resolution, dstActions: [] });
  }

  // 項目チェックの切替（当該系統の値だけが対象）。
  function toggleAction(value: string) {
    const next = new Set(selected);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    dispatch({
      type: 'UPDATE_SKIN',
      id: block.id,
      resolution: block.resolution,
      dstActions: [...next],
    });
  }

  return (
    <section className={styles.block}>
      <div className={styles.blockHeader}>
        <h2 className={styles.heading}>{block.title}</h2>
        <button
          type="button"
          className={styles.removeBtn}
          onClick={() => dispatch({ type: 'REMOVE_BLOCK', id: block.id })}
        >
          ブロック削除
        </button>
      </div>
      <p className={styles.note}>
        肌状態を AI でスコア化します（測定ブロック＝画像は変換しません）。SD と HD は混在できないため、どちらか一方を選んでください。
      </p>

      {/* 系統トグル（SD / HD）。切替で選択を作り直す＝混在不可能。 */}
      <div className={styles.options} role="radiogroup" aria-label="解像度">
        {(Object.keys(RESOLUTION_LABELS) as Resolution[]).map((value) => (
          <label
            key={value}
            className={block.resolution === value ? styles.optionActive : styles.option}
          >
            <input
              type="radio"
              name={`resolution-${block.id}`}
              value={value}
              checked={block.resolution === value}
              onChange={() => changeResolution(value)}
            />
            <span className={styles.optionTitle}>{RESOLUTION_LABELS[value].title}</span>
            <span className={styles.optionNote}>{RESOLUTION_LABELS[value].note}</span>
          </label>
        ))}
      </div>

      {/* 当該系統の診断項目チェック。 */}
      <div className={styles.actions}>
        {SKIN_ACTIONS[block.resolution].map((a) => (
          <label key={a.value} className={styles.action}>
            <input
              type="checkbox"
              checked={selected.has(a.value)}
              onChange={() => toggleAction(a.value)}
            />
            <span>{a.label}</span>
          </label>
        ))}
      </div>

      {block.dstActions.length === 0 && (
        <p className={styles.hint}>診断する項目を1つ以上選んでください。</p>
      )}
    </section>
  );
}
