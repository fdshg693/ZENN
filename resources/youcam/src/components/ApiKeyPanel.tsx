// components/ApiKeyPanel.tsx — API キー入力（最小実装）。
//   ★ フロント露出の前提: 本人のキーを本人が使う POC のため、キーはブラウザに乗る。
//     localStorage 保存も任意で行う（公開端末では使わないこと）。
//   実行フェーズ（機能B/C）でアップロード/タスクを叩く際にこのキーが client へ渡る。

import { useAppDispatch, useAppState } from '../state/AppContext';

export function ApiKeyPanel() {
  const { apiKey } = useAppState();
  const dispatch = useAppDispatch();

  return (
    <section style={{ marginBottom: '1rem', maxWidth: 480 }}>
      <label style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', fontSize: '0.85rem' }}>
        API キー（Bearer トークン）
        <input
          type="password"
          value={apiKey}
          placeholder="YouCam API キーを入力"
          onChange={(e) => dispatch({ type: 'SET_API_KEY', key: e.target.value })}
          style={{ padding: '0.3rem', fontSize: '0.9rem' }}
        />
      </label>
      <p style={{ margin: '0.35rem 0 0', fontSize: '0.75rem', color: '#999' }}>
        ※ このキーはブラウザに保存されます（フロント露出前提の POC）。共有端末では入力しないでください。
      </p>
    </section>
  );
}
