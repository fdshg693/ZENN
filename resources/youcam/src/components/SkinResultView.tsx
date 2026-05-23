// components/SkinResultView.tsx — 機能E: 肌診断結果（SkinResult）の純表示。
//   makeup/look が結果画像1枚だったのに対し、skin は総合点・推定肌年齢・項目別 ui_score・マスク群を見せる。
//   ロジックは持たず（取り出しは api/skinAnalysis.ts、ラベルは domain の SKIN_ACTION_LABELS）、描画だけを担う。

import { SKIN_ACTION_LABELS } from '../domain/blocks';
import type { SkinResult } from '../api/types';
import styles from './SkinResultView.module.css';

/** ui_score（0–100）の項目ラベルを引く。カタログに無い type は値そのものを表示。 */
function actionLabel(type: string): string {
  return SKIN_ACTION_LABELS[type] ?? type;
}

export function SkinResultView({ result }: { result: SkinResult }) {
  return (
    <div className={styles.root}>
      {/* 総合点・推定肌年齢を見出しに（あれば）。 */}
      {(result.overall != null || result.skinAge != null) && (
        <div className={styles.summary}>
          {result.overall != null && (
            <div className={styles.summaryItem}>
              <span className={styles.summaryValue}>{Math.round(result.overall)}</span>
              <span className={styles.summaryLabel}>総合スコア</span>
            </div>
          )}
          {result.skinAge != null && (
            <div className={styles.summaryItem}>
              <span className={styles.summaryValue}>{result.skinAge}</span>
              <span className={styles.summaryLabel}>推定肌年齢</span>
            </div>
          )}
        </div>
      )}

      {/* 項目別 ui_score を横バーで。スコアが高いほど良好（docs/skin-analysis.md）。 */}
      <ul className={styles.scoreList}>
        {result.scores.map((s) => (
          <li key={s.type} className={styles.scoreRow}>
            <span className={styles.scoreName}>{actionLabel(s.type)}</span>
            <span className={styles.barTrack}>
              <span
                className={styles.barFill}
                style={{ width: `${Math.max(0, Math.min(100, s.uiScore))}%` }}
              />
            </span>
            <span className={styles.scoreValue}>{Math.round(s.uiScore)}</span>
            {s.maskUrls && s.maskUrls.length > 0 && (
              <span className={styles.masks}>
                {s.maskUrls.map((url, i) => (
                  <img
                    key={i}
                    className={styles.mask}
                    src={url}
                    alt={`${actionLabel(s.type)} の検出箇所`}
                    loading="lazy"
                  />
                ))}
              </span>
            )}
          </li>
        ))}
      </ul>

      {result.scores.length === 0 && (
        <p className={styles.empty}>診断スコアを取得できませんでした。</p>
      )}
    </div>
  );
}
