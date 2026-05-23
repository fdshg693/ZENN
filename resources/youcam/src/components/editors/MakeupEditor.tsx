// components/editors/MakeupEditor.tsx — 機能B: makeup ブロックの effects 編集 UI。
//   責務は「フォーム表示」と「dispatch」のみ。検証ロジックは domain/blocks.ts に置く。
//   API は呼ばない（編集フェーズ）。例外はパターンカタログの取得（catalog.ts 経由）。
//   category 判別共用体（api/types.ts）に沿ってフォームを出し分けることで取り違えを潰す。

import { useEffect, useState } from 'react';
import { useAppDispatch } from '../../state/AppContext';
import {
  ALL_CATEGORIES,
  CATEGORY_LABELS,
  createEffect,
  type MakeupBlock,
} from '../../domain/blocks';
import { loadPatterns, type PatternOption } from '../../api/catalog';
import type {
  MakeupCategory,
  MakeupEffect,
  MakeupPalette,
  PatternCategory,
} from '../../api/types';
import styles from './MakeupEditor.module.css';

const TEXTURES: { value: string; label: string }[] = [
  { value: '', label: '（なし）' },
  { value: 'matte', label: 'matte' },
  { value: 'satin', label: 'satin' },
  { value: 'shimmer', label: 'shimmer' },
  { value: 'metallic', label: 'metallic' },
  { value: 'gloss', label: 'gloss' },
  { value: 'holographic', label: 'holographic' },
  { value: 'sheer', label: 'sheer' },
];

/** palettes をパターンの色数（colorNum）に合わせて伸縮する（既存の色は保つ）。 */
function resizePalettes(current: MakeupPalette[], n: number): MakeupPalette[] {
  const out = current.slice(0, n);
  while (out.length < n) out.push({ color: '#cccccc' });
  return out;
}

// ── 小さな入力部品 ───────────────────────────────────────────────────────────

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value?: number;
  onChange: (v: number | undefined) => void;
}) {
  return (
    <label className={styles.field}>
      <span>{label}（0–100）</span>
      <input
        type="number"
        min={0}
        max={100}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
      />
    </label>
  );
}

function ColorField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className={styles.field}>
      <span>{label}</span>
      <input type="color" value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

/** 1色ぶんの palette 編集。texture により追加必須欄（shimmer/satin/gloss）を出し分ける。 */
function PaletteEditor({
  index,
  palette,
  showGloss,
  onChange,
}: {
  index: number;
  palette: MakeupPalette;
  showGloss: boolean;
  onChange: (next: MakeupPalette) => void;
}) {
  function changeTexture(value: string) {
    const texture = (value === '' ? undefined : value) as MakeupPalette['texture'];
    const next: MakeupPalette = { ...palette, texture };
    // texture 依存の必須欄を、選択時に妥当な既定値で埋める（実行前検証に通る状態にする）。
    if (texture === 'shimmer') {
      next.shimmerColor ??= '#ffffff';
      next.shimmerDensity ??= 50;
    }
    if (texture === 'satin') {
      next.glowStrength ??= 50;
    }
    onChange(next);
  }

  return (
    <div className={styles.paletteCard}>
      <div className={styles.paletteTitle}>色 {index + 1}</div>
      <div className={styles.fields}>
        <ColorField label="色" value={palette.color} onChange={(color) => onChange({ ...palette, color })} />
        <NumberField
          label="濃さ"
          value={palette.colorIntensity}
          onChange={(colorIntensity) => onChange({ ...palette, colorIntensity })}
        />
        <label className={styles.field}>
          <span>質感 (texture)</span>
          <select value={palette.texture ?? ''} onChange={(e) => changeTexture(e.target.value)}>
            {TEXTURES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>

        {palette.texture === 'shimmer' && (
          <>
            <ColorField
              label="shimmerColor"
              value={palette.shimmerColor ?? '#ffffff'}
              onChange={(shimmerColor) => onChange({ ...palette, shimmerColor })}
            />
            <NumberField
              label="shimmerDensity"
              value={palette.shimmerDensity}
              onChange={(shimmerDensity) => onChange({ ...palette, shimmerDensity })}
            />
          </>
        )}
        {palette.texture === 'satin' && (
          <NumberField
            label="glowStrength"
            value={palette.glowStrength}
            onChange={(glowStrength) => onChange({ ...palette, glowStrength })}
          />
        )}
        {showGloss && (
          <NumberField
            label="gloss"
            value={palette.gloss}
            onChange={(gloss) => onChange({ ...palette, gloss })}
          />
        )}
      </div>
    </div>
  );
}

/** パターン必須カテゴリの選択。catalog.ts の label を選択肢化し、色数を呼び側へ返す。 */
function PatternPicker({
  category,
  value,
  label,
  onPick,
}: {
  category: PatternCategory | 'lip_color';
  value: string;
  label: string;
  onPick: (name: string, colorNum: number) => void;
}) {
  const [options, setOptions] = useState<PatternOption[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setOptions(null);
    setError(null);
    loadPatterns(category)
      .then((opts) => alive && setOptions(opts))
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, [category]);

  if (error) return <p className={styles.error}>パターン取得に失敗: {error}</p>;
  if (!options) return <p className={styles.note}>パターン一覧を読み込み中…</p>;

  const selected = options.find((o) => o.label === value);
  return (
    <label className={styles.field}>
      <span>{label}</span>
      <select
        value={value}
        onChange={(e) => {
          const opt = options.find((o) => o.label === e.target.value);
          onPick(e.target.value, opt?.colorNum ?? 1);
        }}
      >
        <option value="">（選択してください）</option>
        {options.map((o) => (
          <option key={o.label} value={o.label}>
            {o.label}
            {o.colorNum > 1 ? ` (${o.colorNum}色)` : ''}
          </option>
        ))}
      </select>
      {selected?.thumbnail && (
        <img className={styles.thumbnail} src={selected.thumbnail} alt={`${selected.label} のサムネイル`} />
      )}
    </label>
  );
}

/** category ごとのフィールド群。判別共用体に沿って必須項目を出し分ける。 */
function EffectFields({
  effect,
  onChange,
}: {
  effect: MakeupEffect;
  onChange: (next: MakeupEffect) => void;
}) {
  switch (effect.category) {
    case 'skin_smooth':
      return (
        <div className={styles.fields}>
          <NumberField
            label="補正強度"
            value={effect.skinSmoothStrength}
            onChange={(v) => onChange({ ...effect, skinSmoothStrength: v })}
          />
          <NumberField
            label="色補正"
            value={effect.skinSmoothColorIntensity}
            onChange={(v) => onChange({ ...effect, skinSmoothColorIntensity: v })}
          />
        </div>
      );
    case 'foundation':
      return (
        <div className={styles.fields}>
          <ColorField label="色" value={effect.color} onChange={(color) => onChange({ ...effect, color })} />
          <NumberField label="濃さ" value={effect.colorIntensity} onChange={(v) => onChange({ ...effect, colorIntensity: v })} />
          <NumberField label="ツヤ" value={effect.glowIntensity} onChange={(v) => onChange({ ...effect, glowIntensity: v })} />
          <NumberField label="カバー力" value={effect.coverageIntensity} onChange={(v) => onChange({ ...effect, coverageIntensity: v })} />
        </div>
      );
    case 'concealer':
      return (
        <div className={styles.fields}>
          <ColorField label="色" value={effect.color} onChange={(color) => onChange({ ...effect, color })} />
          <NumberField label="濃さ" value={effect.colorIntensity} onChange={(v) => onChange({ ...effect, colorIntensity: v })} />
          <NumberField label="目の下" value={effect.colorUnderEyeIntensity} onChange={(v) => onChange({ ...effect, colorUnderEyeIntensity: v })} />
          <NumberField label="カバー" value={effect.coverageLevel} onChange={(v) => onChange({ ...effect, coverageLevel: v })} />
        </div>
      );
    case 'lip_color':
      return (
        <div className={styles.fields}>
          <PatternPicker
            category="lip_color"
            value={effect.shape.name}
            label="シェイプ"
            onPick={(name, colorNum) =>
              onChange({ ...effect, shape: { name }, palettes: resizePalettes(effect.palettes, colorNum) })
            }
          />
          <label className={styles.field}>
            <span>スタイル</span>
            <select
              value={effect.style?.type ?? 'full'}
              onChange={(e) =>
                onChange({ ...effect, style: { type: e.target.value as 'full' | 'ombre' | 'twoTone' } })
              }
            >
              <option value="full">full</option>
              <option value="ombre">ombre</option>
              <option value="twoTone">twoTone</option>
            </select>
          </label>
          <NumberField
            label="ふっくら (fullness)"
            value={effect.morphology?.fullness}
            onChange={(v) => onChange({ ...effect, morphology: { ...effect.morphology, fullness: v } })}
          />
          <NumberField
            label="シワ補正 (wrinkless)"
            value={effect.morphology?.wrinkless}
            onChange={(v) => onChange({ ...effect, morphology: { ...effect.morphology, wrinkless: v } })}
          />
          {effect.palettes.map((p, i) => (
            <PaletteEditor
              key={i}
              index={i}
              palette={p}
              showGloss
              onChange={(np) => onChange({ ...effect, palettes: effect.palettes.map((o, j) => (j === i ? np : o)) })}
            />
          ))}
        </div>
      );
    default:
      // パターン必須カテゴリ（blush 等）。pattern.name + 色数ぶんの palettes。
      return (
        <div className={styles.fields}>
          <PatternPicker
            category={effect.category}
            value={effect.pattern.name}
            label="パターン"
            onPick={(name, colorNum) =>
              onChange({ ...effect, pattern: { name }, palettes: resizePalettes(effect.palettes, colorNum) })
            }
          />
          {effect.palettes.map((p, i) => (
            <PaletteEditor
              key={i}
              index={i}
              palette={p}
              showGloss={false}
              onChange={(np) => onChange({ ...effect, palettes: effect.palettes.map((o, j) => (j === i ? np : o)) })}
            />
          ))}
        </div>
      );
  }
}

/** makeup ブロック1つぶんの編集 UI。effects の追加/更新/削除をまとめて dispatch する。 */
export function MakeupEditor({ block }: { block: MakeupBlock }) {
  const dispatch = useAppDispatch();
  const [addCategory, setAddCategory] = useState<MakeupCategory>('foundation');

  function commit(effects: MakeupEffect[]) {
    dispatch({ type: 'UPDATE_MAKEUP', id: block.id, effects });
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
      <p className={styles.note}>category を選んで効果を重ねます（1ブロック = 1タスクで適用）。</p>

      {block.effects.map((effect, i) => (
        <div key={i} className={styles.effectCard}>
          <div className={styles.effectHeader}>
            <span className={styles.effectTitle}>{CATEGORY_LABELS[effect.category]}</span>
            <button
              type="button"
              className={styles.removeBtn}
              onClick={() => commit(block.effects.filter((_, j) => j !== i))}
            >
              削除
            </button>
          </div>
          <EffectFields
            effect={effect}
            onChange={(next) => commit(block.effects.map((e, j) => (j === i ? next : e)))}
          />
        </div>
      ))}

      <div className={styles.addRow}>
        <select value={addCategory} onChange={(e) => setAddCategory(e.target.value as MakeupCategory)}>
          {ALL_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {CATEGORY_LABELS[c]}
            </option>
          ))}
        </select>
        <button
          type="button"
          className={styles.button}
          onClick={() => commit([...block.effects, createEffect(addCategory)])}
        >
          効果を追加
        </button>
      </div>
    </section>
  );
}
