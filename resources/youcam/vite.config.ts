import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// dev proxy: ブラウザからの直叩きで詰まる CORS を開発時に回避する唯一の集約点。
//   client.ts の baseURL は '/api' 固定 → ここで本番 API サーバへ転送する。
//   （全体設計 セクション7「つまりどころと対策」に対応）
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'https://yce-api-01.makeupar.com',
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      // 機能B: パターンカタログ JSON（blush.json 等）は API 本体と別ホスト。
      //   catalog.ts の baseURL は '/catalog' 固定 → ここで配信ホストへ転送し CORS を回避。
      '/catalog': {
        target: 'https://plugins-media.makeupar.com',
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/catalog/, ''),
      },
    },
  },
});
