// components/SourcePanel.tsx — 機能A: 起点画像の指定 UI。
//   責務は「表示」と「dispatch」のみ。検証ロジックは domain/blocks.ts のヘルパに置く。
//   API は呼ばない（編集フェーズ）。発行・PUT は実行フェーズ＝機能B/C が files.ts 経由で行う。

import { useEffect, useRef, useState } from 'react';
import { useAppDispatch, useAppState } from '../state/AppContext';
import { selectSource } from '../state/appState';
import { validateSourceFile, validateSourceUrl } from '../domain/blocks';
import styles from './SourcePanel.module.css';

type Tab = 'upload' | 'url';

export function SourcePanel() {
  const state = useAppState();
  const dispatch = useAppDispatch();
  const source = selectSource(state);

  const [tab, setTab] = useState<Tab>(source?.type === 'url' ? 'url' : 'upload');
  const [urlText, setUrlText] = useState(source?.type === 'url' ? source.url : '');
  const [error, setError] = useState<string | null>(null);

  // 直近で生成した object URL を保持し、差し替え／アンマウント時に revoke してリークを防ぐ。
  const objectUrlRef = useRef<string | null>(source?.type === 'upload' ? source.previewUrl : null);
  useEffect(
    () => () => {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    },
    [],
  );

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    // ① 仕様の事前チェック（API に投げる前に弾く）。
    const message = validateSourceFile(file);
    if (message) {
      setError(message);
      e.target.value = ''; // 同じ不正ファイルを選び直せるようリセット
      return;
    }

    // ② プレビュー用 object URL を生成（前のものは revoke）。
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    const previewUrl = URL.createObjectURL(file);
    objectUrlRef.current = previewUrl;

    setError(null);
    dispatch({ type: 'SET_SOURCE', source: { type: 'upload', file, previewUrl } });
  }

  function handleUrlCommit() {
    const message = validateSourceUrl(urlText);
    if (message) {
      setError(message);
      return;
    }
    // URL 経路に切り替えるので、保持中の upload プレビューがあれば解放する。
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
    setError(null);
    dispatch({ type: 'SET_SOURCE', source: { type: 'url', url: urlText.trim() } });
  }

  function switchTab(next: Tab) {
    if (next === tab) return;
    setTab(next);
    setError(null);
  }

  // プレビューに出す URL（upload なら object URL、url ならそのまま）。
  const previewSrc =
    source?.type === 'upload' ? source.previewUrl : source?.type === 'url' ? source.url : null;

  return (
    <section className={styles.panel}>
      <h2 className={styles.heading}>起点画像</h2>
      <p className={styles.note}>
        以降のブロックの起点となる顔画像を1つ指定します（アップロード ⇄ URL のどちらか一方）。
      </p>

      {/* 経路の切替（同時指定は不可） */}
      <div className={styles.tabs} role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'upload'}
          className={tab === 'upload' ? styles.tabActive : styles.tab}
          onClick={() => switchTab('upload')}
        >
          アップロード
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'url'}
          className={tab === 'url' ? styles.tabActive : styles.tab}
          onClick={() => switchTab('url')}
        >
          URL 指定
        </button>
      </div>

      {tab === 'upload' ? (
        <div className={styles.control}>
          <label className={styles.label}>
            顔写真を選択（jpg / jpeg / png・10MB 未満）
            <input type="file" accept="image/jpeg,image/png" onChange={handleFileChange} />
          </label>
        </div>
      ) : (
        <div className={styles.control}>
          <label className={styles.label}>
            公開アクセス可能な画像 URL
            <input
              type="url"
              placeholder="https://example.com/face.jpg"
              value={urlText}
              onChange={(e) => setUrlText(e.target.value)}
              onBlur={handleUrlCommit}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleUrlCommit();
              }}
            />
          </label>
          <button type="button" className={styles.applyButton} onClick={handleUrlCommit}>
            この URL を使う
          </button>
        </div>
      )}

      {/* 仕様外入力はその場で読めるメッセージを出す */}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}

      {/* 「何を起点にするか」を目で確認できるプレビュー */}
      {previewSrc ? (
        <figure className={styles.preview}>
          <img
            src={previewSrc}
            alt="起点画像のプレビュー"
            className={styles.previewImage}
            onError={() => setError('画像を読み込めませんでした。URL や形式を確認してください。')}
          />
          <figcaption className={styles.caption}>
            {source?.type === 'upload'
              ? `アップロード: ${source.file.name}`
              : 'URL 指定（実行時に src_file_url として渡されます）'}
          </figcaption>
        </figure>
      ) : (
        <p className={styles.placeholder}>まだ起点画像が選ばれていません。</p>
      )}
    </section>
  );
}
