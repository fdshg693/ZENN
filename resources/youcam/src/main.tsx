// main.tsx — React マウントのみ。
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { AppProvider } from './state/AppContext';
import App from './App';

const rootEl = document.getElementById('root');
if (!rootEl) throw new Error('#root が見つかりません。');

createRoot(rootEl).render(
  <StrictMode>
    <AppProvider>
      <App />
    </AppProvider>
  </StrictMode>,
);
