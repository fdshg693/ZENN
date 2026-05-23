// App.tsx — 画面全体のレイアウト・各パネルの配置。
//   機能A（起点画像）+ 機能B（メイク）+ 機能C（連結実行）+ 機能D（完成ルック）+ 機能E（肌診断）+ 機能F（JSON 共有）の構成。
//   AI ブロック（makeup / look / skin）を並び順で回し、kind で編集 UI を出し分け、各ブロックに RunPanel を添える。
//   ブロックの追加ボタンの後に共有（ImportExport）、末尾に連結実行の RoutinePanel を置く。

import type { CSSProperties } from 'react';
import { ApiKeyPanel } from './components/ApiKeyPanel';
import { SourcePanel } from './components/SourcePanel';
import { MakeupEditor } from './components/editors/MakeupEditor';
import { LookEditor } from './components/editors/LookEditor';
import { SkinEditor } from './components/editors/SkinEditor';
import { RunPanel } from './components/RunPanel';
import { RoutinePanel } from './components/RoutinePanel';
import { ImportExport } from './components/ImportExport';
import { useAppDispatch, useAppState } from './state/AppContext';
import { selectAiBlocks } from './state/appState';

const addButtonStyle: CSSProperties = {
  marginTop: '1rem',
  marginRight: '0.5rem',
  padding: '0.45rem 1rem',
  border: '1px solid #1f6feb',
  borderRadius: 6,
  background: '#1f6feb',
  color: '#fff',
  cursor: 'pointer',
  fontSize: '0.9rem',
};

export default function App() {
  const state = useAppState();
  const dispatch = useAppDispatch();
  const aiBlocks = selectAiBlocks(state);

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: '1.5rem', lineHeight: 1.5 }}>
      <h1 style={{ fontSize: '1.4rem' }}>YouCam ルーティン共有 POC</h1>
      <p style={{ color: '#666', fontSize: '0.9rem', maxWidth: 480 }}>
        機能A: 起点となる顔画像を指定し、機能B: メイク／機能D: 完成ルック／機能E: 肌診断のブロックを1タスクで適用、機能C: 複数ブロックを一括／チェインで連結実行、機能F: 組んだルーティンを JSON で保存・共有します。
      </p>
      <ApiKeyPanel />
      <SourcePanel />

      {/* AI ブロック（makeup / look / skin）ごとに「編集 → 実行」を並び順で縦に並べる。 */}
      {aiBlocks.map((block) => (
        <div key={block.id}>
          {block.kind === 'look' ? (
            <LookEditor block={block} />
          ) : block.kind === 'skin' ? (
            <SkinEditor block={block} />
          ) : (
            <MakeupEditor block={block} />
          )}
          <RunPanel block={block} />
        </div>
      ))}

      <div>
        <button type="button" onClick={() => dispatch({ type: 'ADD_MAKEUP' })} style={addButtonStyle}>
          ＋ メイクブロックを追加
        </button>
        <button type="button" onClick={() => dispatch({ type: 'ADD_LOOK' })} style={addButtonStyle}>
          ＋ 完成ルックを追加
        </button>
        <button type="button" onClick={() => dispatch({ type: 'ADD_SKIN' })} style={addButtonStyle}>
          ＋ 肌診断を追加
        </button>
      </div>

      {/* 機能F: 組んだルーティンを JSON で書き出し／取り込み（顔写真・結果は含めない）。 */}
      <ImportExport />

      {/* 機能C: 並んだブロックを一括／チェインで連結実行する。進捗は上の各 RunPanel に出る。 */}
      <RoutinePanel />
    </main>
  );
}
