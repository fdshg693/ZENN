---
title: "VSCodeを\"なぜこう動くか\"から使いこなす — Electron・LSP・DAP・拡張ホストの裏側"
status: plan
---

## 想定読者と前提

- VSCodeを日常的に使っているが、「なぜ拡張を入れないと Python が動かないのか」を言語化できない中級エンジニア
- Electron / Language Server Protocol / Debug Adapter Protocol という用語は聞いたことがあるが、VSCodeの中でどう噛み合っているか説明できない人
- Command Palette や Multi-cursor を触っているが、「この機能はどの仕組みから来ているのか」を意識したことがない人

前提知識: JavaScript/TypeScript と Node.js の基本、プロセスとプロトコルの概念、どれか1言語で開発経験があること。

## この記事が答える問い

1. VSCodeの本体は何を自前で持ち、何を他に任せているのか（プロセスモデル）
2. なぜ言語ごとに拡張が必要で、**Language Server Protocol (LSP)** は何を解いたのか
3. デバッガUIが言語非依存なのはなぜか（**Debug Adapter Protocol, DAP**）
4. Python拡張が `Python` + `Pylance` + `Python Debugger` + `Jupyter` と分かれているのはなぜか
5. この構造を理解したうえで、Command Palette / Multi-cursor / Workspace 設定階層 / `tasks.json` / `launch.json` をどう位置づけるか

## 扱う / 扱わない

- **扱う**: Electron由来のプロセスモデル（main / renderer / shared / extension host / utility process）、LSP、DAP、代表的拡張（Python/Pylance, Python Debugger）の役割、実際に効く日常機能とその根っこ
- **扱わない**: GitHub Copilot / Copilot Chat（移り変わりが激しいため除外）、拡張の自作チュートリアル、Remote Development や Dev Containers の詳細、キーバインド総覧

---

## セクション構成

### 1. 「素のVSCodeは、ほぼ空箱」という視点から始める

**主張**: VSCodeをインストールしただけでは、Pythonの補完もTypeScriptの型チェックも効かない。VSCodeは「編集UIとプロトコル」だけを抱え、言語のスマートさとデバッガはすべて外部プロセスに移譲している。この分業を意識すると、あらゆる機能が一貫して読める。

**根拠URL**:
- https://code.visualstudio.com/api/language-extensions/language-server-extension-guide
- https://code.visualstudio.com/api/extension-guides/debugger-extension

### 2. プロセスモデル — main / renderer / shared / extension host

**主張**: VSCodeはElectronから多プロセス構造を受け継いでいる。2022年のサンドボックス化以降、**extension host はRendererから完全に切り離された Utility Process** で動いており、拡張が暴走してもUIは落ちない。プロセス間は `MessagePort` で直接通信する。

**押さえる内容**:
- main process（エントリ、BrowserWindow管理、Node.js 有効）
- renderer process（ウィンドウごと、Chromium、**sandboxed**）
- shared process（隠しElectronウィンドウ、拡張インストールや file watching・integrated terminal の親）
- extension host（ウィンドウごと、UtilityProcess、全拡張がここで動く）
- MessagePort による main を経由しない通信

**根拠URL**:
- https://code.visualstudio.com/blogs/2022/11/28/vscode-sandbox
- https://github.com/electron/electron/blob/main/docs/tutorial/process-model.md

**根拠ファイル**: `temp/vscode_internals_tips/extract_process_model.json`, `search_vscode_architecture.json`

### 3. LSP — 「言語スマート」をエディタから剥がした発明

**主張**: 言語機能をエディタごとに書き直す時代を終わらせたのがLSP。エディタ側の薄い **Language Client** と、別プロセスの **Language Server** に分け、JSONメッセージで会話する。重い解析をrendererから切り離せるので、UIが固まらない。サーバ側言語は何でもよい（PHPサーバをTypeScriptクライアントから呼べる）。

**押さえる内容**:
- 分離の2つの動機: (a) エディタ × 言語の組合せ爆発を解消、(b) CPU/メモリ負荷をUIから逃がす
- `initialize` で `capabilities` を交換する capability-based 設計
- Language Server が別プロセスである点は、VSCodeのextension host内でさらに子プロセスを spawn していることを意味する

**根拠URL**:
- https://microsoft.github.io/language-server-protocol/
- https://code.visualstudio.com/api/language-extensions/language-server-extension-guide

**根拠ファイル**: `temp/vscode_internals_tips/extract_lsp.json`

### 4. DAP — デバッガUIを言語から剥がす、LSPの兄弟

**主張**: LSPが編集機能を分離したように、DAPはデバッグUIを分離する。VSCodeは言語非依存のデバッガUIしか持たず、実際に言語ランタイムを操作するのは **Debug Adapter** という中間プロセス。通信はJSONだが**JSON-RPCとは非互換**（V8 Debugging Protocol由来）。バージョン番号を持たず、**capability フラグ** で互換性を維持している設計が面白い。

**押さえる内容**:
- 「デバッガUI」と「言語ランタイム」を切り離す発想はLSPと同じ系譜
- `DebugAdapterExecutable`（stdio）と `DebugAdapterServer`（ポート）の2モード
- `initialize` で capability を交換し、未知のフラグは「未対応」と解釈される後方互換戦略

**根拠URL**:
- https://microsoft.github.io/debug-adapter-protocol/overview
- https://code.visualstudio.com/api/extension-guides/debugger-extension
- https://code.visualstudio.com/blogs/2018/08/07/debug-adapter-protocol-website

**根拠ファイル**: `temp/vscode_internals_tips/extract_dap.json`, `search_lsp_dap.json`

### 5. ケーススタディ: Python拡張が4つに分かれている理由

**主張**: Marketplace で `ms-python.python` を入れると、裏で `Pylance`・`Python Debugger`・`Jupyter` が連れてくる。これは単なる抱き合わせではなく、**セクション2〜4の構造がそのまま拡張境界に投影されている**。`Python` は UI・設定・インタプリタ選択を担い、`Pylance` はLSP、`Python Debugger` はDAP（debugpy）、`Jupyter` はノートブックUI。ライセンスが違うため（Pylanceはプロプラ、Pyrightはオープン）分割が必然になっている。

**押さえる内容**:
- `Python` 拡張: インタプリタ選択、REPL、テスト発見などの「ホスト」的役割
- `Pylance`: Pyrightを内蔵したLSPサーバ。`diagnosticMode` で `openFilesOnly` / `workspace` を切り替えられる
- `Python Debugger`: debugpy を DAP で包んだ別拡張
- `isort` のような「単機能フォーマッタ1個=拡張1個」が許容されるのはextension hostの分離のおかげ

**根拠URL**:
- https://github.com/microsoft/pylance-release/blob/main/FAQ.md
- https://code.visualstudio.com/docs/python/python-tutorial
- https://github.com/microsoft/vscode-python/discussions/20252
- https://github.com/microsoft/vscode-python/discussions/16207

**根拠ファイル**: `temp/vscode_internals_tips/extract_python.json`, `search_python_ext.json`

### 6. 構造を踏まえた、実際に効く日常機能

**主張**: よく紹介される機能も、2〜5節の構造に紐づけて理解すると「なぜそう動くか」「どこまで効くか」が自然に見える。

- **Command Palette (`Ctrl+Shift+P`)**: すべての拡張が同じ `commands` contribution point を登録している。だから1つのUIで網羅できる
- **Multi-cursor (`Alt+Click` / `Ctrl+Alt+↑↓` / `Ctrl+D` / `Ctrl+Shift+L`)**: renderer 内の編集処理なので LSP/DAP を介さず高速
- **Go to Symbol (`Ctrl+Shift+O`) / Outline / Go to Definition**: これらはLSPの `textDocument/documentSymbol`・`definition` を叩いている。言語サーバ未対応だと効かない
- **Integrated Terminal**: shared processの子プロセスとして動く。だから複数ウィンドウで重くならない
- **Workspace 設定の階層**: Default < User < Remote < Workspace < WorkspaceFolder の5層＋language-specific。`.vscode/settings.json` をGit管理する設計思想
- **`tasks.json` / `launch.json`**: タスクは「外部コマンドを走らせる薄い枠」、launchはDAPへ投げる設定ファイル。`${workspaceFolder}` などの変数置換は2パス評価

**根拠URL**:
- https://code.visualstudio.com/docs/getstarted/tips-and-tricks
- https://code.visualstudio.com/docs/configure/settings
- https://code.visualstudio.com/docs/editing/workspaces/multi-root-workspaces
- https://code.visualstudio.com/docs/reference/variables-reference
- https://code.visualstudio.com/docs/debugtest/debugging-configuration
- https://code.visualstudio.com/api/references/contribution-points

**根拠ファイル**: `temp/vscode_internals_tips/search_vscode_tips.json`, `search_settings_tasks.json`

### 7. まとめ: 拡張を入れるときに見るべきもの

**主張**: 拡張カタログを眺めるとき、「どのプロセスで動くか」「LSP/DAPどちら側か」「設定はどのスコープで効くか」の3点を見るだけで、相性や重さ、競合の予測精度が一気に上がる。VSCodeの快適さは機能の多さではなく、**UI・LSP・DAPという3つの抽象の直交性**から来ている。
