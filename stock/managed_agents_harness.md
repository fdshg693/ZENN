---
title: エージェントハーネスは OS である — Managed Agents と長時間 AI エージェント基盤の本質
emoji: 🧠
type: tech
topics: [ai, agent, langchain, anthropic, architecture]
published: false
---

## 背景：長時間動くエージェントは何が難しいのか

LLM エージェントを本番投入すると、対話型チャットボットでは顕在化しなかった問題が一気に出てくる。代表的なのは次の 3 つだ。

- **状態の永続化**：数分〜数時間動く session の途中でプロセスが落ちたら、そこまでの推論履歴・ツール呼び出し結果をどう復元するか
- **実行環境の分離**：モデルが生成したコードをどこで走らせるか。prompt injection や hallucinated package によるサプライチェーン攻撃をどう封じるか
- **リソースの割当て**：純粋な reasoning 中心の session と、大量のコード実行を伴う session を同じインフラ形状で扱うのは非効率

Anthropic の [Scaling Managed Agents](https://www.anthropic.com/engineering/managed-agents) は、この 3 点に対する社内実装の再設計を報告している。本稿ではその設計を、LangGraph・Temporal・E2B / Daytona など他実装と対応づけて読み解く。

中心となる設計命題は 1 つ：

> **エージェントハーネスは OS である。LLM は CPU にすぎない。**

OS が `read()` という syscall でディスクの物理種別（HDD / SSD / ネットワーク越しのブロックデバイス）を隠蔽するのと同じく、ハーネスはモデルの側に「どんなツールをどんな実行環境で呼ぶか」を固定のインタフェースで見せ、裏側の実装を交換可能にする。Anthropic と Hugo Nogueira の [The Agent Harness](https://hugo.im/posts/agent-harness-infrastructure/) は、独立にこの比喩に到達している。

---

## 1. 用語整理：Framework / Runtime / Harness

LangChain の Harrison Chase が整理している 3 層（Hugo Nogueira [記事](https://hugo.im/posts/agent-harness-infrastructure/)より）：

- **Framework**：モデルとツールを結線する building block。LangChain、LlamaIndex などのライブラリ層
- **Runtime**：実行エンジン。durable execution（途中で落ちても再開できる実行）、ストリーミング、human-in-the-loop を担う
- **Harness**：ポリシーを持つ層。system prompt、使わせるツール一式、メモリ戦略、context 管理を決める

Anthropic の Managed Agents は Runtime と Harness の境界層にあたる。本稿では主に Runtime 層の設計、すなわち「session の永続化」「harness プロセスの再起動可能性」「sandbox の分離」を扱う。

---

## 2. Managed Agents の構成：3 コンポーネントへの分解

Anthropic の実装は agent を以下の 3 つに分解し、各コンポーネントを独立した仮想リソースとして管理する。

- **session**：発生したイベントをすべて追記する append-only の event log
- **harness**：Claude API を呼び、返ってきた tool_use をルーティングするループ本体
- **sandbox**：Claude が生成したコードの実行環境（ファイルシステム編集、コマンド実行を行う）

これらを束ねる API は次の形に落ちている（[Ken Huang の解説](https://kenhuangus.substack.com/p/how-anthropic-scaling-managed-agents)）：

- `wake(sessionId)` — session ID から harness プロセスを起動（または再起動）する
- `getSession(id)` — event log を全取得する
- `emitEvent(id, event)` — harness が session に永続的に書き込む
- `execute(name, input) → string` — sandbox を呼び出す統一インタフェース

重要なのは「harness と sandbox はいつ殺してもよい」という点だ。状態は session にしかない。harness / sandbox はリクエスト到着時に lazy に起動される使い捨てリソースになる。

---

## 3. pet → cattle 化：初期実装の何が問題だったか

初期の Managed Agents は session / harness / sandbox を同一 container に同居させていた。利点は明確で、

- ファイル編集がローカル syscall 1 回で済み低レイテンシ
- コンポーネント間の境界設計が不要

しかしこの構成には致命的な弱点があった。container が 1 つ落ちると session ごと消える。container が不調になると手動で延命するしかない。個体ごとに名前をつけて世話する「pet」になる、というインフラ運用上の典型的アンチパターンである。

session を container の外（別ストレージ）に永続化すれば、harness プロセスは使い捨て可能な「cattle」になる。落ちたら `wake(sessionId)` で新しい harness を起動し、`getSession(id)` で event log を読み込み、最後のイベントから推論ループを再開するだけでよい。

同じ設計思想は LangChain / Temporal も共有している。

- **LangGraph の checkpointer**：[設計ブログ](https://www.langchain.com/blog/building-langgraph)で明示されている要求は「チェックポイントは任意のマシン上で、任意時間経過後に再開できること。特定プロセスのメモリや生存状態に依存しない」
- **Temporal**：[LLM 呼び出しを Activity でラップ](https://temporal.io/blog/building-durable-agents-with-temporal-and-ai-sdk-by-vercel)することで、rate limit エラーやネットワーク断を自動 retry し、障害地点から正確に再開する

ただし LangChain は Temporal の直接採用を見送っている。理由は

- トークンごとのストリーミングに対応できない
- step 間に workflow engine のレイテンシが乗る
- event 履歴が長くなるほど workflow リプレイのコストが増える

という LLM 固有の要件だ。Managed Agents が自前実装を選んだ動機もここと重なる。

---

## 4. session 設計：状態の外在化と context rot

session を harness の外に置く設計が効いてくるのは 3 つの局面である。

- **復旧**：harness プロセスが死んでも event log があれば再構築可能
- **スケール**：同じ session に別 harness を後からアタッチできる（brain と hand を N:M にできる）
- **multi-agent 連携**：別エージェントへの引き継ぎ時に「session の内容」が共通のデータソースになる

なぜ「context window を伸ばす」だけでは足りないか。Claude の [Context engineering cookbook](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools) が指摘する通り、window を埋めるほど **context rot**（初期に読み込んだ情報への recall 精度が低下する現象）が発生する。1M トークンの window でも、最後まで進んだ時点では冒頭のドキュメントは「技術的には context 内にある」が、モデルの注意がそこまで届かない。

この問題への対処として cookbook は次の 3 手法を挙げる。

- **Compaction**：古い対話をモデル生成のサマリで置き換える
- **Tool-result clearing**：古いツール出力の本文を捨て、「呼んだ事実」だけ残す
- **Memory / structured note-taking**：context window の外にノートを書き出し、必要な箇所だけ読み戻す

[Inkeep の実践記事](https://inkeep.com/blog/context-engineering-why-agents-fail)では、複数セッションにまたがる troubleshooting エージェントが `troubleshooting_notes.md` をセッション開始時に読み込み、終了時に更新する運用を紹介している。Anthropic の姉妹記事 [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) で示される、進捗を `progress.md` に書き出し git commit で履歴化するパターンも同型だ。

要するに session を外部ストレージに持つ決定は、context engineering で積み上げられた「状態を window の外に逃がす」手法を、インフラ層の標準装備に引き上げたものといえる。

---

## 5. harness 設計：復旧単位はフレームワークごとに異なる

「落ちても cattle として作り直せる」という要件は共通でも、**どの単位で再開するか**はフレームワークごとに設計が分かれる。[Galileo の比較](https://galileo.ai/blog/autogen-vs-crewai-vs-langgraph-vs-openai-agents-framework)をもとに整理する。

| フレームワーク | エラー時の挙動 | 復旧単位 |
|---|---|---|
| **AutoGen** | エージェントが失敗を会話履歴に含め推論を継続 | 会話ターン |
| **CrewAI** | manager エージェントが別エージェントに再割当て、必要なら人間にエスカレーション | task / crew |
| **LangGraph** | graph の error edge に遷移、checkpointer で直近ノードにロールバック | graph node |
| **Managed Agents** | harness クラッシュを tool_use error として表現し、`wake()` で session を再接続 | session 全体 |

粗い粒度（session 全体のリプレイ）ほど harness 実装はシンプルになるが、1 回のエラーで多くの推論が無効になる。細かい粒度（node 単位）ほど復旧は安価だが、graph をどう切るかの設計コストが先に要る。Galileo 記事が指摘する "cascading dialogue loops"（エラーを会話で吸収しようとして延々とリトライし続ける）は、復旧単位を決めずに retry ロジックを散在させた結果として発生する。

**自前実装のときは「どの単位で再実行するか」を先に決め、その単位でイベントを保存せよ**、というのが実用的な指針になる。

---

## 6. sandbox 設計：`execute(name, input) → string` が隠蔽するもの

sandbox を呼び出すインタフェースを `execute(name, input) → string` まで絞り込むと、harness 側は裏側の実装を知らずに済む。実装は Linux container でも、Firecracker microVM でも、ブラウザ自動化でも、MCP server 経由でも構わない。モデルから見えるのは「ツール名と入力」だけ。

加えて、Managed Agents は **credential を sandbox に置かない** という設計判断をしている（[Ken Huang 解説](https://kenhuangus.substack.com/p/how-anthropic-scaling-managed-agents)）。sandbox は「信頼しない前提」で動き、認証情報は harness 側に保持し、ツール呼び出しのたびにハーネスが必要最小限を sandbox に渡す構造になっている。モデルが誤って credential を出力するリスクに対しプロンプトで注意するのではなく、構造的にそもそも見せないことで対処する。

### 実装候補の比較

[Northflank](https://northflank.com/blog/daytona-vs-e2b-ai-code-execution-sandboxes) と [SoftwareSeni](https://www.softwareseni.com/e2b-daytona-modal-and-sprites-dev-choosing-the-right-ai-agent-sandbox-platform/) の整理を抜粋する。

| 実装 | 分離方式 | 起動時間 | 特性 |
|---|---|---|---|
| **E2B / Sprites.dev** | Firecracker microVM（専用 kernel） | cold start 〜125ms | kernel 分離でハードウェア仮想化レベル。AWS Lambda が採用するのと同系統 |
| **Daytona** | Docker container（kernel 共有） | 〜27–90ms | 起動が速く永続ディスクを活かせる。kernel 共有のため脱獄リスクは残る |
| **Modal** | gVisor（user-space kernel による syscall フィルタ） | ネイティブ比 2–9x オーバーヘッド | syscall 約 350 のうち約 68 を intercept。GPU ワークロードに強い |

### なぜ kernel レベルの分離が要るのか

LLM 固有の脅威モデルを考えると理由が見える。

- **prompt injection は OWASP の LLM リスクトップに位置する**。プロンプトだけの防御は多くの実験で 84% 以上の確率で突破される
- **AI が生成するコードのうち約 19.7% が存在しないパッケージ名を参照する**。攻撃者が npm / PyPI にその名前で悪性パッケージを登録すると、サプライチェーン攻撃が成立する

プロンプト側の防御では原理的に塞げない攻撃面が残るため、**プロセス境界や kernel 境界による技術的分離が最終防衛線になる**。`execute(name, input) → string` というインタフェースは、脅威モデルが更新されて将来 Daytona から Firecracker に差し替えるときでも harness 側のコードを書き換えずに済ませる、抽象化の保険でもある。

---

## 7. スケール効果：N:M brains-to-hands

decouple による計測値は次の通り（[Ken Huang 解説](https://kenhuangus.substack.com/p/how-anthropic-scaling-managed-agents)）。

- **p50 TTFT（Time To First Token）: -60%**
- **p95 TTFT: -90% 以上**
- **brain（モデル呼び出し）と hand（sandbox）を 1:1 に固定しない**：1:0、1:N、N:M すべて取れる

改善メカニズムは単純である。従来は session 開始時に必ず container を起動していたため、ツール呼び出しが 0 回の session でも container 起動コストを払っていた。decouple 後は、モデルが最初の tool_use を出した時点ではじめて sandbox を lazy に provision する。reasoning だけで完結する session の TTFT は、モデル推論のレイテンシだけで決まるようになる。

副産物として multi-agent での委譲が素直に書ける。hand が特定の brain に束縛されていないので、brain A が作った sandbox セッションへの参照を brain B に渡し、そのまま続きを実行させる、という構造が自然に組める。

---

## 8. 本番で詰まるパターン：抽象の外にある問題

ハーネスの抽象化は「落ちても復元できる」基盤を提供するが、それだけでは足りない failure mode が本番では多発する。[Aryeian の分析](https://aryeian.blog/presentations/multi_agent_ai_production.html)・[Inkeep 記事](https://inkeep.com/blog/context-engineering-why-agents-fail)・[Anthropic 姉妹記事](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)を総合すると、典型例は次のとおり。

- **エラー伝播の雪崩**：Agent A の hallucination を Agent B が前提とし、Agent C がそれに基づく決定を下す
- **ツール過多による混乱**：20〜30 ツールを一度に露出すると、タスクに無関係な API が「存在するから」という理由で呼ばれる
- **偽の完了宣言**：後続エージェントが前段エージェントの進行ログだけを見て "done" と判断する（姉妹記事の具体例）
- **context pollution**：過去の会話全部・ツール定義一式・関連ドキュメントを毎リクエスト丸投げする
- **context rot**：1M window を使っても、window 後半では冒頭情報への recall が目に見えて劣化する

これらはハーネスのインフラ設計では救えず、**context engineering 層の設計**（何を残し何を落とすか、どのツールをいつ見せるか）が別途要る。実運用でのエンジニアリング工数は、おおむね次の配分に寄る。

- **インフラ層（session 永続化、sandbox 分離、harness 復旧）**：約 50%
- **context engineering 層（note-taking、tool clearing、just-in-time retrieval）**：約 30%
- **プロンプト・振る舞い設計**：約 20%

デモと本番の差は、ハーネスと context engineering の両方を実装できているかで決まる。

---

## 9. エージェント基盤を設計する際のチェックリスト

1. **session は harness プロセスの外にあるか**：event log を外部ストレージに append-only で書き、harness を使い捨てにできる構造になっているか
2. **tool 呼び出しは `execute(name, input) → string` 相当の薄い層に隔離されているか**：特定 sandbox 実装（例：特定の Docker イメージ前提）に依存するコードが harness 側に漏れていないか
3. **sandbox の分離レベルは脅威モデルに対応しているか**：LLM 生成コードを共有 kernel の container で実行していないか。Firecracker / gVisor / container / プロセスのどこまで必要か、根拠を持って選べるか
4. **compaction だけでなく外部ノートによる状態退避を併用しているか**：長時間 session で context rot が発生する前提を置き、`progress.md` / `NOTES.md` 相当を維持しているか
5. **エラー時の復旧単位は明示されているか**：tool call / node / task / session のどれを単位に retry / replay するか、実装前に決まっているか

モデル側の性能は今後も変化する。ハーネス実装の前提も書き換わっていく。長期的に腐りにくいのは、これらのインタフェース境界の切り方だけだ。

---

## 参考文献

**Anthropic**

- [Scaling Managed Agents: Decoupling the brain from the hands](https://www.anthropic.com/engineering/managed-agents)
- [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Context engineering: memory, compaction, and tool clearing](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools)

**外部分析**

- [Ken Huang: How Anthropic Scaling Managed Agents with Future-proof Architecture?](https://kenhuangus.substack.com/p/how-anthropic-scaling-managed-agents)
- [Hugo Nogueira: The Agent Harness — Why 2026 is About Infrastructure, Not Intelligence](https://hugo.im/posts/agent-harness-infrastructure/)

**フレームワーク・ランタイム**

- [LangChain: Building LangGraph — Designing an Agent Runtime from first principles](https://www.langchain.com/blog/building-langgraph)
- [Temporal: Building durable agents with Temporal and AI SDK by Vercel](https://temporal.io/blog/building-durable-agents-with-temporal-and-ai-sdk-by-vercel)
- [Galileo: AutoGen vs CrewAI vs LangGraph vs OpenAI AI Agents Framework](https://galileo.ai/blog/autogen-vs-crewai-vs-langgraph-vs-openai-agents-framework)

**Sandbox / 実行環境**

- [Northflank: Daytona vs E2B in 2026](https://northflank.com/blog/daytona-vs-e2b-ai-code-execution-sandboxes)
- [SoftwareSeni: E2B, Daytona, Modal, and Sprites.dev — Choosing the Right AI Agent Sandbox Platform](https://www.softwareseni.com/e2b-daytona-modal-and-sprites-dev-choosing-the-right-ai-agent-sandbox-platform/)

**本番運用の failure mode**

- [Inkeep: Context Engineering — The Real Reason AI Agents Fail in Production](https://inkeep.com/blog/context-engineering-why-agents-fail)
- [Aryeian: Why 90% of Multi-Agent AI Projects Fail in Production](https://aryeian.blog/presentations/multi_agent_ai_production.html)
