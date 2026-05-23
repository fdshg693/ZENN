// components/ImportExport.tsx — 機能F: ルーティンの保存・共有（JSON）UI。
//   責務は「直列化結果の取り出し（ダウンロード／コピー）」と「外部 JSON の取り込み（ファイル／貼り付け）」のみ。
//   検証・直列化は domain/routineFile.ts に置く。API は呼ばない（機能F はネットワークを発生させない）。
//   import 後の編集・実行は既存導線（各 Editor / RunPanel / RoutinePanel）にそのまま乗る。

import { useRef, useState } from 'react';
import { useAppDispatch, useAppState } from '../state/AppContext';
import { selectAiBlocks } from '../state/appState';
import { parseRoutine, serializeRoutine } from '../domain/routineFile';
import styles from './ImportExport.module.css';

export function ImportExport() {
  const state = useAppState();
  const dispatch = useAppDispatch();
  const aiBlocks = selectAiBlocks(state);

  const [pasteText, setPasteText] = useState('');
  const [importError, setImportError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const hasBlocks = aiBlocks.length > 0;

  // ── export ──────────────────────────────────────────────────
  function handleDownload() {
    const json = serializeRoutine(aiBlocks, state.routine.execution);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'routine.json';
    a.click();
    URL.revokeObjectURL(url);
  }

  async function handleCopy() {
    const json = serializeRoutine(aiBlocks, state.routine.execution);
    try {
      // best-effort（権限/HTTP でブロックされうる）。失敗時はダウンロード経路へ誘導する。
      await navigator.clipboard.writeText(json);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
      setImportError(null);
      setNotice('クリップボードにコピーできませんでした。「JSON をダウンロード」をご利用ください。');
    }
  }

  // ── import ──────────────────────────────────────────────────
  // 取り込みは現在のルーティンを差し替える破壊的操作。既存 AI ブロックがあれば確認を挟む。
  function confirmReplace(): boolean {
    if (!hasBlocks) return true;
    return window.confirm(
      '現在のブロックは取り込んだルーティンに置き換えられます。よろしいですか？（起点画像の指定は残ります）',
    );
  }

  function applyParsed(text: string) {
    const result = parseRoutine(text);
    if (!result.ok) {
      setNotice(null);
      setImportError(result.error);
      return;
    }
    if (!confirmReplace()) return;
    dispatch({ type: 'LOAD_ROUTINE', blocks: result.blocks, execution: result.execution });
    setImportError(null);
    setNotice(
      `${result.blocks.length} ブロックを取り込みました。起点画像はご自身のものを指定して実行してください。`,
    );
    setPasteText('');
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    file
      .text()
      .then((text) => applyParsed(text))
      .catch(() => {
        setNotice(null);
        setImportError('ファイルを読み込めませんでした。');
      });
    e.target.value = ''; // 同じファイルを選び直せるようリセット
  }

  function handlePasteImport() {
    if (!pasteText.trim()) {
      setNotice(null);
      setImportError('取り込む JSON を貼り付けてください。');
      return;
    }
    applyParsed(pasteText);
  }

  return (
    <section className={styles.panel}>
      <h2 className={styles.heading}>ルーティンの保存・共有</h2>
      <p className={styles.note}>
        組んだルーティン（ブロックの並び・各設定・実行方式）を JSON で書き出し／取り込みます。
        <strong>顔写真と結果画像は含まれません</strong>
        ので、共有しても自分の顔は相手に渡りません。取り込んだ後は起点画像をご自身のもので指定して実行します。
      </p>

      {/* ── エクスポート ─────────────────────────────── */}
      <div className={styles.block}>
        <h3 className={styles.subheading}>エクスポート</h3>
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.primary}
            onClick={handleDownload}
            disabled={!hasBlocks}
          >
            JSON をダウンロード
          </button>
          <button
            type="button"
            className={styles.secondary}
            onClick={handleCopy}
            disabled={!hasBlocks}
          >
            {copied ? 'コピーしました ✓' : 'クリップボードにコピー'}
          </button>
        </div>
        {!hasBlocks && <p className={styles.hint}>共有するブロックがありません。</p>}
      </div>

      {/* ── インポート ───────────────────────────────── */}
      <div className={styles.block}>
        <h3 className={styles.subheading}>インポート</h3>
        <label className={styles.label}>
          ファイルから取り込む
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json,.json"
            onChange={handleFileChange}
          />
        </label>
        <label className={styles.label}>
          または JSON を貼り付け
          <textarea
            className={styles.textarea}
            rows={5}
            placeholder='{ "app": "youcam-routine-share", "version": 1, ... }'
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
          />
        </label>
        <button
          type="button"
          className={styles.primary}
          onClick={handlePasteImport}
          disabled={!pasteText.trim()}
        >
          貼り付けた JSON を取り込む
        </button>
      </div>

      {importError && (
        <p className={styles.error} role="alert">
          {importError}
        </p>
      )}
      {notice && <p className={styles.notice}>{notice}</p>}
    </section>
  );
}
