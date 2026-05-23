// scripts/fetch-look-templates.mjs — 完成ルック（look-vto）のテンプレ一覧と
//   サムネイルを一度だけ取得し、ローカル（public/look-templates/）に保存する準備スクリプト。
//
//   なぜローカル化するか:
//     ・テンプレは ~300 件と多く、毎回 API を叩くと一覧取得が遅く units 消費の懸念もある。
//     ・サムネは外部 CDN（cdn.perfectcorp.com）依存で表示が不安定 → ローカル配信で安定＆オフライン可。
//   出力:
//     public/look-templates/thumbs/<id>.jpg   … 各サムネ画像（id 単位）
//     public/look-templates/index.json        … アプリが読むマニフェスト（thumb はローカルパスに差し替え済み）
//   Vite は public/ をルート配信するので、アプリからは fetch('/look-templates/index.json') で読める。
//
//   使い方:
//     node scripts/fetch-look-templates.mjs          … 一覧取得 → 画像ダウンロード → index.json 生成
//     node scripts/fetch-look-templates.mjs --dry     … 取得とレスポンス形/件数の確認だけ（ダウンロードしない）
//   既にダウンロード済みの画像はスキップする（再実行で差分のみ取得）。
//   API キーはルート直下の .env（YOUCAM_API_KEY=...）から読む。

import { readFileSync, mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { writeFile } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');

// ── 設定 ──────────────────────────────────────────────────────────────────────
const API_BASE = 'https://yce-api-01.makeupar.com'; // vite.config.ts の /api proxy と同じ本番サーバ
const ENDPOINT = '/s2s/v2.0/task/template/look-vto';
const OUT_DIR = join(ROOT, 'public', 'look-templates');
const THUMB_DIR = join(OUT_DIR, 'thumbs');
const MANIFEST = join(OUT_DIR, 'index.json');
const PAGE_SIZE = 20; // 1ページの取得件数（API 上限 = 20。next_token で全件辿る）
const CONCURRENCY = 10; // サムネ同時ダウンロード数（CDN なので高めでよい）
const DRY = process.argv.includes('--dry');

// ── .env から API キーを読む（依存を増やさず手書きパース）────────────────────────
function readEnv(key) {
  const path = join(ROOT, '.env');
  if (!existsSync(path)) throw new Error('.env が見つかりません（ルート直下に YOUCAM_API_KEY=... を置いてください）。');
  for (const line of readFileSync(path, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (m && m[1] === key) return m[2].replace(/^["']|["']$/g, '');
  }
  return undefined;
}

const apiKey = readEnv('YOUCAM_API_KEY');
if (!apiKey) {
  console.error('YOUCAM_API_KEY が .env にありません。');
  process.exit(1);
}

// ── 一覧を全件取得（next_token を辿る。先頭ページでレスポンス形を出力して検証）──────────
async function fetchAllTemplates() {
  const all = [];
  let token;
  let page = 0;
  do {
    const qs = new URLSearchParams({ page_size: String(PAGE_SIZE) });
    if (token) qs.set('starting_token', token);
    const url = `${API_BASE}${ENDPOINT}?${qs}`;
    const res = await fetch(url, { headers: { Authorization: `Bearer ${apiKey}` } });
    if (!res.ok) {
      const body = await res.text().catch(() => '');
      throw new Error(`一覧取得に失敗（HTTP ${res.status}）page=${page}: ${body.slice(0, 300)}`);
    }
    const json = await res.json();
    const data = json.data ?? {};
    const templates = Array.isArray(data.templates) ? data.templates : [];
    all.push(...templates);

    if (page === 0) {
      console.log('── レスポンス形の確認（先頭ページ）─────────────────');
      console.log('  top-level keys :', Object.keys(json));
      console.log('  data keys      :', Object.keys(data));
      console.log('  next_token     :', typeof data.next_token, JSON.stringify(data.next_token));
      console.log('  1件目          :', JSON.stringify(templates[0]));
      console.log('────────────────────────────────────────────────');
    }

    token = data.next_token != null && data.next_token !== '' ? String(data.next_token) : undefined;
    page += 1;
    console.log(`page ${page}: +${templates.length}件（累計 ${all.length}）next_token=${token ?? '<終端>'}`);
  } while (token);

  return all;
}

// ── サムネ URL から拡張子を推定（クエリを除いた pathname の末尾）──────────────────
function extOf(url) {
  try {
    const m = new URL(url).pathname.match(/\.(jpe?g|png|webp|gif)$/i);
    return m ? m[0].toLowerCase() : '.jpg';
  } catch {
    return '.jpg';
  }
}

// ファイル名に使える形へ（id は all_nightmare 等で概ね安全だが念のため正規化）。
const safeName = (id) => String(id).replace(/[^a-z0-9_-]/gi, '_');

// 1件のサムネをダウンロード（既存はスキップ）。戻り値はアプリが使うローカルパス（失敗時 null）。
async function downloadThumb(t) {
  if (!t.thumb) return null;
  const file = `${safeName(t.id)}${extOf(t.thumb)}`;
  const dest = join(THUMB_DIR, file);
  const localPath = `/look-templates/thumbs/${file}`;
  if (existsSync(dest)) return localPath; // 再実行時はスキップ（差分取得）
  const res = await fetch(t.thumb);
  if (!res.ok) {
    console.warn(`  サムネ取得失敗 ${t.id}: HTTP ${res.status}`);
    return null;
  }
  await writeFile(dest, Buffer.from(await res.arrayBuffer()));
  return localPath;
}

// CONCURRENCY 本のワーカーで並列ダウンロードしつつ、入力順を保ったマニフェスト配列を組み立てる。
async function downloadAll(templates) {
  const manifest = new Array(templates.length);
  let next = 0;
  let done = 0;
  async function worker() {
    while (next < templates.length) {
      const idx = next++;
      const t = templates[idx];
      const thumb = await downloadThumb(t);
      manifest[idx] = {
        id: t.id,
        title: t.title ?? t.id,
        category_name: t.category_name ?? 'その他',
        thumb, // ローカルパス（/look-templates/thumbs/...）or null
      };
      done += 1;
      if (done % 25 === 0 || done === templates.length) {
        console.log(`  画像 ${done}/${templates.length} 取得`);
      }
    }
  }
  await Promise.all(Array.from({ length: CONCURRENCY }, worker));
  return manifest;
}

// カテゴリ別の件数を表示（折りたたみ UI の規模感の確認用）。
function printCategoryHistogram(templates) {
  const byCat = new Map();
  for (const t of templates) {
    const k = t.category_name ?? 'その他';
    byCat.set(k, (byCat.get(k) ?? 0) + 1);
  }
  const sorted = [...byCat.entries()].sort((a, b) => b[1] - a[1]);
  console.log(`── カテゴリ別件数（${byCat.size} カテゴリ / 合計 ${templates.length} 件）──`);
  for (const [cat, n] of sorted) console.log(`  ${String(n).padStart(4)}  ${cat}`);
}

// ── main ────────────────────────────────────────────────────────────────────
async function main() {
  console.log(`look-vto テンプレ取得を開始（${DRY ? 'DRY: ダウンロードなし' : '本実行'}）`);
  const templates = await fetchAllTemplates();
  printCategoryHistogram(templates);

  if (DRY) {
    console.log('DRY 実行のため、画像ダウンロードと index.json 生成はスキップしました。');
    return;
  }

  mkdirSync(THUMB_DIR, { recursive: true });
  const manifestTemplates = await downloadAll(templates);
  const withThumb = manifestTemplates.filter((t) => t.thumb).length;

  const out = {
    generatedAt: new Date().toISOString(),
    source: `${API_BASE}${ENDPOINT}`,
    count: manifestTemplates.length,
    templates: manifestTemplates,
  };
  writeFileSync(MANIFEST, JSON.stringify(out, null, 2));
  console.log(`完了: ${manifestTemplates.length} 件（サムネ ${withThumb} 件）→ ${MANIFEST}`);
}

main().catch((e) => {
  console.error('失敗:', e.message);
  process.exit(1);
});
