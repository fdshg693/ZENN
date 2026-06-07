---
title: "VSCodeを\"なぜこう動くか\"から使いこなす — Electron・LSP・DAP・拡張ホストの裏側"
emoji: "🧩"
type: "tech"
topics: ["vscode", "electron", "lsp", "python", "architecture"]
published: false
---

## この記事について

VSCodeは毎日触っているけれど、「なぜ Python 拡張を入れないと補完すら効かないのか」「ESLint と Prettier と Pylance がそれぞれ別の拡張になっているのはなぜか」「`launch.json` の中で何が起きているのか」を言語化できる人は意外と少ないと思います。

この記事では、Copilot のような**移り変わりの激しいAI系機能は扱わず**、VSCode という編集環境の**変わりにくい土台**に焦点を当てます。具体的には、

1. VSCodeの本体は何を自前で持ち、何を外に任せているのか（プロセスモデル）
2. Language Server Protocol (LSP) が解いたのは結局どんな問題か
3. デバッガUIが言語非依存でいられるのはなぜか（Debug Adapter Protocol, DAP）
4. Python拡張が `Python` / `Pylance` / `Python Debugger` / `Jupyter` の4本に分かれている理由
5. この構造を踏まえて、Command Palette・Multi-cursor・Workspace 設定・`tasks.json` / `launch.json` をどう位置づけるか

という順に、**「仕組み → 代表例 → 日常機能」** でつなげます。機能の羅列ではなく、**理解の背骨** を1本通すのが狙いです。

---

## 1. 素のVSCodeは、ほぼ空箱である

最初に言っておきたいのは、**VSCodeを入れただけでは Python も TypeScript もまともに扱えない** ということです。

- Python ファイルを開いても、補完も型チェックも走らない
- F5 を押しても、デバッガは立ち上がらない
- `go to definition` も動かない

これは「VSCodeが未完成だから」ではなく、**意図された設計** です。VSCodeは、

- エディタUI（テキスト編集、ツリー、パネル、コマンド）
- 拡張をホストする仕組み
- **言語機能と話すためのプロトコル（LSP）**
- **デバッガと話すためのプロトコル（DAP）**

までしか自前で持っていません。「Pythonを理解する」「Rustをデバッグする」といった言語固有のスマートさは、**ぜんぶ外部プロセスに任せる** 作りです。

この前提を最初に置くと、あとで出てくる話（拡張が分割されている理由、なぜ重い解析でもUIが落ちないか、なぜMarketplaceが爆発的に広がれたか）が全部同じ文脈で読めます。

公式のLanguage Server Extension Guideも、Debugger Extension Guideも、この前提から話を始めています[^lsp-guide][^dap-guide]。

## 2. プロセスモデル — main / renderer / shared / extension host

VSCodeはElectronで書かれており、Electronの多プロセスモデルをそのまま引き継いでいます。Electron側のドキュメントではこう説明されています[^electron-proc]。

> Electron inherits its multi-process architecture from Chromium, which makes the framework architecturally very similar to a modern web browser.

VSCode固有の工夫を加えると、現在の構造は次のようになります[^vscode-sandbox]。

| プロセス | 個数 | 役割 | Node.js |
|---|---|---|---|
| **main** | 1 | エントリポイント。`BrowserWindow` 管理、アプリライフサイクル | ✅ |
| **renderer** | ウィンドウごと | エディタUI（Monaco, ワークベンチ）。**サンドボックス化済み** | ❌ |
| **shared process** | 1 | 隠しElectronウィンドウ。拡張インストール、file watching、ターミナルの親 | ✅ |
| **extension host** | ウィンドウごと | 全拡張がここで動く。Electronの **UtilityProcess** API で実装 | ✅ |

### sandbox 化で何が変わったか

2022年、VSCodeはrendererをChromiumの標準どおりサンドボックス化しました[^vscode-sandbox]。これにより renderer はブラウザタブと同じくらい権限が絞られ、Node.js API を直接叩けなくなりました。

そのために拡張の実行場所を変える必要があり、**Electronに新しい `UtilityProcess` API を貢献** して、extension host をそこへ移設しています。

> we contributed a new utility process API to Electron. This API enabled us to move the extension host away from the renderer process and into a utility process that is created from the main process.[^vscode-sandbox]

これの何が嬉しいのかというと、

- **拡張がクラッシュしてもUIは落ちない**（extension host は別プロセス）
- **重い拡張がUI描画をブロックしない**
- **renderer はサンドボックス越しにOSに触れない** ので、悪意あるwebviewの被害範囲が縮む

### MessagePort による直通

主要プロセス間の通信は、従来のようにmainを経由するIPCではなく、**MessagePortで直結** されています[^vscode-sandbox]。integrated terminal や file watching も、ウィンドウから shared process に MessagePort 経由でサービスを問い合わせる形です。

実際にタスクマネージャやActivity Monitorで VSCode を開くと、`Code`, `Code Helper`, `Code Helper (Renderer)`, `Code Helper (Plugin)` のようにプロセスが分かれて見えますが、これは上の表にそのまま対応しています。**「VSCodeが重い」と感じたら、どのプロセスがCPUを使っているかを見るだけでかなり原因が絞れる** のも、この構造のご褒美です。

## 3. LSP — 「言語スマート」をエディタから剥がした発明

### 解いた問題

LSP以前、「Pythonのオートコンプリート」「Goのgo-to-definition」「RustのHoverドキュメント」は、**エディタ×言語の組み合わせごとに書き直されていました**。M個のエディタとN個の言語があれば M × N 個の実装が必要で、ほぼ全部のエディタが「Python対応はちょっと弱い」みたいな状態になっていました。

LSPはこれを M + N に畳みました。公式ページの説明がこの一点に尽きます[^lsp-home]。

> A Language Server is meant to provide the language-specific smarts and communicate with development tools over a protocol that enables inter-process communication. (...) a single Language Server can be re-used in multiple development tools, which in turn can support multiple languages with minimal effort.

### VSCodeでの構造

VSCodeでの実装は、**Language Client（拡張内、TypeScript）** と **Language Server（別プロセス、実装言語は自由）** の二層です[^lsp-guide]。

```
[ renderer (UI) ]
      │ （VSCode API）
      ▼
[ extension host ]
      │ Language Client (TypeScript)
      │   ↕ JSONメッセージ（stdio or socket）
      ▼
[ Language Server プロセス ]
      └─ PHP, Python, Rust, Go... 何でも良い
```

**ポイントは2つ** あります[^lsp-guide]。

1. **組み合わせ爆発の解消**: 「PHPで書かれたPHP Language Server」を、「TypeScriptで書かれたVSCode拡張」が呼び出せる。逆にLSPに準拠した他のエディタ（Neovim, Emacs, Zedなど）からも同じサーバが使える。
2. **UIを固めないため**: 言語解析はCPUとメモリを大量に食う。これをrendererや extension host 本体で動かすとエディタがガクつく。別プロセスに逃がすことで、**UIはイベントループを離さない**。

### capability-based な初期化

LSPでは、接続時に `initialize` リクエストで **「このサーバは何ができるか」** を交換します。公式ガイドには、サーバがコード補完を提供する場合の宣言例が載っています[^lsp-guide]。

```ts
connection.onInitialize((params): InitializeResult => {
  return {
    capabilities: {
      completionProvider: { resolveProvider: true }
    }
  };
});
```

クライアント側はこの `capabilities` を見て「ならば補完UIを出そう」と判断します。**サーバとクライアントのバージョンが一致している必要がなく**、機能ごとに flag で交渉できる、というのが LSP が長寿命な理由です。同じ発想がこのあとの DAP にも出てきます。

### 「Rustだけ動かない」ときに何を疑うか

この構造が分かっていると、トラブル切り分けが一気に楽になります。

- **補完が全く出ない** → Language Server プロセスが立ち上がっていない／クラッシュしている（extension host のログを見る）
- **補完は出るが遅い** → Language Server のCPU張り付き（サーバ自体を profile）
- **拡張だけ再読み込みしたい** → `Developer: Reload Window` ではなく、サーバを kill してもらう（拡張ごとに再起動コマンドがあることが多い）

## 4. DAP — デバッガUIを言語から剥がす、LSPの兄弟

LSPが編集機能を分離したなら、**デバッグUIを分離したのがDAP** です[^dap-blog]。VSCode本体は「ブレークポイント」「変数」「スタック」「ステップ実行ボタン」といった **言語非依存のデバッガUIしか持たず**、実際に各言語のランタイムを操作するのは **Debug Adapter** という中間プロセスです[^dap-vscode]。

### アーキテクチャ

```
[ VSCode UI (renderer) ]
      ↕ DAP（JSONメッセージ）
[ Debug Adapter (別プロセス) ]
      ↕ 各言語のデバッグAPI（GDB, debugpy, node inspectorなど）
[ デバッグ対象プロセス ]
```

> VS Code implements a generic (language-agnostic) debugger UI based on an abstract protocol that we've introduced to communicate with debugger backends. Because debuggers typically do not implement this protocol, some intermediary is needed to "adapt" the debugger to the protocol.[^dap-vscode]

VSCodeのデフォルトは **stdio モード**、つまり Debug Adapter は独立した実行ファイルとして起動され、stdin/stdout でJSONメッセージを交換します[^dap-vscode]。

- `DebugAdapterExecutable`: 外部実行ファイルを stdin/stdout で話す（**既定**）
- `DebugAdapterServer`: 特定ポートで待ち受けるサーバとして動作

### 文字列が主役のプロトコル

DAPの設計上の割り切りとして、公式Overviewはこう書いています[^dap-overview]。

> it is fairly high-level and does not have to surface all the fine details of the underlying language and low-level debugger API. The most important data type used in the protocol are strings, because that's what the end user will see in the UI.

Debug Adapter は言語固有のデバッガAPI（例えばPythonなら `debugpy`）から得た情報を、**ユーザーに見せる文字列データに整形するだけ** で済みます。だからDebug Adapterを書くコスト自体は低く、言語ごとに「誰かが書いてくれれば済む」状態を作れます。

### バージョン番号のない後方互換

DAPはLSP同様、**明示的なバージョン番号を持ちません**。代わりに **capability フラグの集合** で表現し、未知のフラグは「未対応」として解釈する、という運用です[^dap-overview]。

> Making this possible without version numbers requires that every new feature gets a corresponding flag that lets a development tool know whether a debug adapter supports the feature or not. The absence of the flag always means that the feature is not supported.

なお地味に注意すべきなのは、**DAPのJSONフォーマットは JSON-RPC と "似ているが互換ではない"** 点です。V8 Debugging Protocol を起源にしているためで、LSPのJSON-RPCとは別系統です[^dap-blog]。

### LSPとDAPの関係

| | LSP | DAP |
|---|---|---|
| 分離するもの | 言語スマート（補完、定義、診断） | デバッグ機能 |
| 公開年 | 2016 | 2018年に独立サイト化 |
| 分離先 | Language Server | Debug Adapter |
| 拡張性 | capability | capability |
| ワイヤフォーマット | JSON-RPC | JSON（JSON-RPC非互換） |

**「重い・言語固有・別ライフサイクル」のものを、プロトコル越しに別プロセスに追い出す** という設計思想はLSPとDAPで完全に共通で、これがVSCodeの拡張エコシステムの骨格になっています。

## 5. ケーススタディ: Python拡張が4つに分かれている理由

ここまでの仕組みが **実際にどうパッケージ化されているか** を、もっとも使われる Python 拡張で見てみます。

Marketplaceで `ms-python.python` を入れたつもりが、実は裏で以下も入ります[^python-tutorial][^python-discussion]。

- **Python** (`ms-python.python`): UI、設定、インタプリタ選択、REPL、テスト発見、フォーマッタ統合など、**他の拡張を束ねるホスト**。ソースはMITライセンス
- **Pylance** (`ms-python.vscode-pylance`): LSPサーバ。内部でオープンソースの **Pyright** 型チェッカを動かし、補完・診断・ナビゲーションを提供する。**プロプラエタリライセンス**
- **Python Debugger** (`ms-python.debugpy`): DAP側。`debugpy` を Debug Adapter として包む
- **Jupyter**: Python拡張の**ハード依存**として自動インストールされる

一見すると「1つで済む機能をバラしているだけ」に見えますが、**これはセクション2〜4の構造がそのまま拡張境界になっている** だけです。

### なぜこの切り方になるのか

1. **ライセンス境界**: Pyrightは Microsoft がオープンソース化していますが、Pylance 本体は **プロプラエタリ** です[^pylance-faq]。MITのPython拡張に混ぜ込めないため、必然的に別拡張になります
2. **プロトコル境界**: Pylance は LSP サーバ、Python Debugger は DAP アダプタ。**動いているプロトコルが違うので、拡張として分けたほうが素直**
3. **着脱可能性**: Pylance を使いたくない場合（ライセンスが気になる、Jedi に戻したい）、`python.languageServer` 設定で切り替えられる[^pylance-faq]。LSPが疎結合だから成立する
4. **性能境界**: Pylanceには `diagnosticMode` 設定があり、`openFilesOnly`（開いたファイルだけ解析、軽い）と `workspace`（全体解析、重いがバグ発見率高）を選べる[^pylance-faq]。これもLSPが別プロセスだから「別プロセスの挙動を外から調整する」発想が成立する

結果として、こうなります。

```
VSCode (renderer)
 ├─ extension host
 │    ├─ Python 拡張（ホスト・UI・設定統合）
 │    ├─ Pylance 拡張 ──┐ spawn
 │    │                  └→ Pylance LS プロセス (LSP, JSON-RPC)
 │    ├─ Python Debugger 拡張 ──┐ spawn
 │    │                          └→ debugpy プロセス (DAP)
 │    └─ Jupyter 拡張
 └─ shared process （ファイル監視、ターミナル）
```

`isort` や `black-formatter` のような **フォーマッタ1個=拡張1個** という細かい切り方が許されているのも、extension host がプロセス分離されていて、1個増えても UI が遅くならないからです。

### 他言語でも同じパターン

この分割は Python 特有ではありません。

- **TypeScript**: VSCode同梱の `tsserver` が LSP相当として動き、`vscode-js-debug` が DAP アダプタ
- **Rust**: `rust-analyzer` が LSP、`codelldb` が DAP
- **Go**: `gopls` が LSP、`dlv` を Delve DAP として包む

**「LSP実装1つ + DAP実装1つ + 設定UI = 言語対応」** というテンプレートが、このエコシステムのほぼ全言語で再利用されている、と思って読むと Marketplace の景色がかなり変わります。

## 6. 構造を踏まえた、実際に効く日常機能

ここまで仕組みを押さえたうえで、よく紹介される機能を**「どの層で動いているか」**と一緒に見ていきます。

### Command Palette (`Ctrl+Shift+P`)

**どの層**: VSCode本体 + 全拡張の contribution points。

すべての拡張は `package.json` の `commands` contribution point で自分のコマンドを宣言します[^contrib]。Command Palette はその統合ビューなので、**拡張を入れた瞬間に、設定画面を探さずに `Ctrl+Shift+P` でなんでも叩ける** のはこれが理由です。

キーバインドを覚えていないコマンドも、ここから辿れば必ず動きます。「とりあえずCommand Paletteを開く」を体に入れるのが、VSCodeの最大のショートカットだと思います。

### Multi-cursor (`Alt+Click` / `Ctrl+Alt+↑↓` / `Ctrl+D` / `Ctrl+Shift+L`)

**どの層**: renderer 内（Monaco エディタ）[^tips]。

重要なのは、**これは LSP も extension host も一切通っていない** こと。純粋にテキストバッファに対する編集なので、**どれだけ遅い Language Server を使っていても、Multi-cursor だけは常に高速** です。「補完は遅いけど複数行編集はサクサク動く」場合、それはLSPの層だけ詰まっていて、編集層は健全という意味になります。

`Ctrl+D`（同じ語の次の出現に選択追加）は、個人的にVSCodeで最も見返りの大きいキーです。

### Go to Symbol (`Ctrl+Shift+O`) / Outline / Go to Definition (`F12`)

**どの層**: LSP。`textDocument/documentSymbol`、`textDocument/definition` などの要求を Language Server に投げています。

これが効かないときに疑うべきは、

- **言語のLSPサーバが起動していない**: 対応拡張が入っていない、インタプリタが未選択、サーバがクラッシュ
- **対応していない**: 例えばプレーンテキストファイルや、LSPのないマイナー言語

F12 が効かなければ `Ctrl+Shift+O` も効かない、というのは同じプロトコル上の要求だからです。

### Integrated Terminal

**どの層**: shared process の子プロセス[^vscode-sandbox]。

ウィンドウを複数開いてもターミナルの重量が蓄積しないのは、**shared process に一本化されている** からです。ターミナル内で `python` や `npm` を走らせてもVSCodeのUIレンダリングには影響しません（renderer とは別プロセスなので）。

### Workspace 設定の階層

VSCodeの設定は **5層の優先順位** があります[^settings]。

```
Default < User < Remote < Workspace < Workspace Folder
```

さらに **language-specific 設定** が各層に重なります（例: `"[python]": { "editor.tabSize": 4 }`）。使い分けの基本は次のとおり。

- **User 設定**: 自分の好み（キーマップ、テーマ、フォント）
- **Workspace 設定** (`.vscode/settings.json`): プロジェクトの決めごと（formatter、tabSize、ruff の ON/OFF）。**Gitにコミットする前提**
- **Workspace Folder 設定**: multi-root 構成で、フォルダごとに設定を変えるとき

contribution points には scope という概念があり、拡張が公開する設定ごとに `application` / `machine` / `machine-overridable` / `window` / `resource` のどれで効くかが決まっています[^contrib]。`resource` スコープはファイル/フォルダごとに違ってよく、`application` はユーザー設定にしか書けません。**「ワークスペースで上書きできない設定」があるのはこれのため** です。

なお multi-root の場合、**UI レイアウトに関わる設定（ズームなど）はフォルダごとに分けても無視される**、という挙動は覚えておくと混乱しません[^multiroot]。

### `tasks.json` / `launch.json`

- **`tasks.json`** (`version: "2.0.0"` 必須[^multiroot]): 外部コマンドを走らせる薄い枠。ビルド、テスト、lint をVSCodeから叩けるようにする
- **`launch.json`**: **DAPへ投げる設定ファイル**。`type` フィールドがどの Debug Adapter を使うかを指定する

両ファイルとも、`${workspaceFolder}` / `${file}` / `${env:USERNAME}` などの変数置換が使えます。このとき[^varsref]、

> In the first pass, all variables are evaluated to string results. (...) In the second pass, all variables are substituted with the results from the first pass.

という **2パス評価** なので、「変数の中で別の変数を参照する」ようなネスト展開はできません。これを知っていると、謎の置換失敗で数時間溶かす事故を避けられます。

multi-rootで特定フォルダを指すときは `${workspaceFolder:Program}` のように**名前指定**できます[^multiroot]。

## 7. まとめ — 拡張を入れるときに見るべきもの

VSCodeは、

- **UI層**（renderer）
- **拡張をホストするだけの層**（extension host）
- **言語スマート（LSP）**
- **デバッガ（DAP）**

という **直交する4つの抽象** の上に、設定階層と contribution points を重ねた構造でできています。機能が多いから便利なのではなく、**「機能がここまで直交しているから新しい拡張が安く書けて増え続ける」** のが本質です。

新しい拡張を入れるとき、次の3つを見るだけで体感品質の予想がかなり当たるようになります。

1. **どのプロセスで動くか**: extension hostで動く重い拡張は、同時に複数入れると効いてくる
2. **LSP / DAP / どちらでもない？**: 補完系ならLSP、デバッグ系ならDAP、それ以外なら純粋なUI系。**プロトコル越しなら別プロセスなので基本軽い**
3. **設定のスコープ**: ワークスペースで上書きできるか、ユーザー専用か

Copilot などのAI補助機能も、内部的には **「extension host にいる拡張が、自分でLLMと話し、結果を VSCode API で提示しているだけ」** です。今後どんなAI拡張が来ても、この基本構造を握っておけば、ほぼ同じ読み方で中身を当てられます。

VSCodeは「空箱」で始まって、拡張で埋めていくエディタです。埋め方のルールが見えると、自分のワークフローに合う拡張の見つけ方が変わってきます。

---

## 参考リンク

[^lsp-guide]: [Language Server Extension Guide - Visual Studio Code](https://code.visualstudio.com/api/language-extensions/language-server-extension-guide)
[^dap-guide]: [Debugger Extension | Visual Studio Code Extension API](https://code.visualstudio.com/api/extension-guides/debugger-extension)
[^electron-proc]: [electron/docs/tutorial/process-model.md](https://github.com/electron/electron/blob/main/docs/tutorial/process-model.md)
[^vscode-sandbox]: [Migrating VS Code to Process Sandboxing (VS Code Blog, 2022)](https://code.visualstudio.com/blogs/2022/11/28/vscode-sandbox)
[^lsp-home]: [Official page for Language Server Protocol](https://microsoft.github.io/language-server-protocol/)
[^dap-blog]: [New home for the Debug Adapter Protocol (VS Code Blog, 2018)](https://code.visualstudio.com/blogs/2018/08/07/debug-adapter-protocol-website)
[^dap-overview]: [DAP Overview](https://microsoft.github.io/debug-adapter-protocol/overview)
[^dap-vscode]: [Debugger Extension | Visual Studio Code Extension API](https://code.visualstudio.com/api/extension-guides/debugger-extension)
[^python-tutorial]: [Getting Started with Python in VS Code](https://code.visualstudio.com/docs/python/python-tutorial)
[^python-discussion]: [vscode python extensions · microsoft/vscode-python · Discussion #20252](https://github.com/microsoft/vscode-python/discussions/20252)
[^pylance-faq]: [Pylance Frequently Asked Questions](https://github.com/microsoft/pylance-release/blob/main/FAQ.md)
[^contrib]: [Contribution Points | Visual Studio Code Extension API](https://code.visualstudio.com/api/references/contribution-points)
[^tips]: [Visual Studio Code tips and tricks](https://code.visualstudio.com/docs/getstarted/tips-and-tricks)
[^settings]: [User and workspace settings](https://code.visualstudio.com/docs/configure/settings)
[^multiroot]: [Multi-root Workspaces](https://code.visualstudio.com/docs/editing/workspaces/multi-root-workspaces)
[^varsref]: [Variables reference](https://code.visualstudio.com/docs/reference/variables-reference)
