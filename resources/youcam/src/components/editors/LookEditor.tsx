// components/editors/LookEditor.tsx — 機能D: look ブロックの編集 UI（テンプレ選択）。
//   責務は「一覧の表示」と「dispatch」のみ。ロジック（取得・キャッシュ）は api/lookVto.ts に置く。
//   一覧は ~349件と多いので category_name ごとに折りたたむ（既定は閉。選択中のカテゴリだけ開いておく）。
//   選択するとサムネ付きカードがハイライトされ、UPDATE_LOOK で templateId が state に入る。

import { useEffect, useMemo, useState } from 'react';
import { useAppDispatch } from '../../state/AppContext';
import { listLookTemplates } from '../../api/lookVto';
import type { LookBlock } from '../../domain/blocks';
import type { LookTemplate } from '../../api/types';
import styles from './LookEditor.module.css';

/** category_name でグルーピングする（無い場合は「その他」へ）。表示順は登場順を保つ。 */
function groupByCategory(templates: LookTemplate[]): [string, LookTemplate[]][] {
  const groups = new Map<string, LookTemplate[]>();
  for (const t of templates) {
    const key = t.category_name ?? 'その他';
    const list = groups.get(key) ?? [];
    list.push(t);
    groups.set(key, list);
  }
  return [...groups.entries()];
}

export function LookEditor({ block }: { block: LookBlock }) {
  const dispatch = useAppDispatch();
  const [templates, setTemplates] = useState<LookTemplate[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // 展開中のカテゴリ集合（既定は空＝全て折りたたみ）。
  const [openCats, setOpenCats] = useState<Set<string>>(new Set());

  useEffect(() => {
    let alive = true;
    setTemplates(null);
    setError(null);
    listLookTemplates()
      .then((list) => alive && setTemplates(list))
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, []);

  // 一覧ロード時、選択中テンプレのカテゴリだけ開く（選択が一目で見えるように）。
  //   以後の手動開閉を尊重するため、依存は templates のみ（templateId 変更では再計算しない）。
  useEffect(() => {
    if (!templates) return;
    const selected = templates.find((t) => t.id === block.templateId);
    setOpenCats(selected?.category_name ? new Set([selected.category_name]) : new Set());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templates]);

  const grouped = useMemo(() => (templates ? groupByCategory(templates) : []), [templates]);

  function toggleCategory(category: string) {
    setOpenCats((prev) => {
      const next = new Set(prev);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
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
        プロが作成した完成ルックを1つ選んで適用します（1ブロック = 1タスク）。カテゴリをクリックで開閉。
      </p>

      {error && <p className={styles.error}>テンプレ取得に失敗: {error}</p>}
      {!error && !templates && <p className={styles.note}>完成ルック一覧を読み込み中…</p>}
      {!error && templates && templates.length === 0 && (
        <p className={styles.note}>利用できる完成ルックがありませんでした。</p>
      )}

      {grouped.map(([category, items]) => {
        const isOpen = openCats.has(category);
        const hasSelected = items.some((t) => t.id === block.templateId);
        return (
          <div key={category} className={styles.group}>
            <button
              type="button"
              className={styles.groupHeader}
              onClick={() => toggleCategory(category)}
              aria-expanded={isOpen}
            >
              <span className={styles.chevron}>{isOpen ? '▼' : '▶'}</span>
              <span className={styles.groupName}>{category}</span>
              <span className={styles.groupCount}>{items.length}</span>
              {hasSelected && (
                <span className={styles.selectedDot} title="選択中のルックを含む" aria-label="選択中" />
              )}
            </button>

            {isOpen && (
              <div className={styles.grid}>
                {items.map((t) => {
                  const selected = t.id === block.templateId;
                  return (
                    <button
                      key={t.id}
                      type="button"
                      className={selected ? styles.cardSelected : styles.card}
                      aria-pressed={selected}
                      onClick={() => dispatch({ type: 'UPDATE_LOOK', id: block.id, templateId: t.id })}
                    >
                      {t.thumb ? (
                        <img className={styles.thumb} src={t.thumb} alt={t.title} loading="lazy" />
                      ) : (
                        <div className={styles.thumbPlaceholder}>No image</div>
                      )}
                      <span className={styles.cardTitle}>{t.title}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}
