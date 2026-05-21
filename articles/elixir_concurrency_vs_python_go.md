---
title: "Elixirの並行処理を、PythonとGoの実装と並べて読む — じゃんけんサーバーを題材に"
emoji: "🪐"
type: "tech"
topics: ["elixir", "python", "go", "concurrency", "actor"]
published: false
---

## はじめに — 誰向けの記事か

Elixirは「BEAM上のアクターモデル」「軽量プロセス」「不変データ」「パターンマッチ」など、他言語の中級者が初見で読むと**1ファイルに複数の知らない概念が同時に出てくる**言語です。文法だけ眺めても「で、何が嬉しいのか」が掴みにくい。

そこで本記事では、`140行以下の小さなじゃんけんサーバー`を題材に、**全く同じ機能を Python と Go でも書き起こした上で**、Elixir の特徴を5つの観点で並列に対比します。Hello World ではなく「メッセージで動く小さなサーバー」という具体例を3言語で並べることで、Elixir の「書き味」と「設計の重心」が浮かび上がるはずです。

- **想定読者**: Python / Go / TypeScript などで並行処理を一度は書いたことがあり、Elixir は未経験〜入門段階の方
- **書き味の比較**に焦点を当てます。性能・本番運用・OTPの深い部分には踏み込みません

> ⚠️ 本記事では「BEAMのプロセスは軽量だ」程度の一般論にとどめ、「数百万プロセス起動できる」などのベンチ的な断定は避けています。実数値が気になる方は Erlang/OTP 公式の方を参照してください。

## 題材 — じゃんけんサーバー

複数の独立した「プレイヤー」プロセスが、中央の「ゲームサーバー」にメッセージで参加 → 手を送信 → 全員揃ったらサーバーが結果を全プレイヤーに broadcast する、というシンプルなモデルです。

3言語のソースは次の3つのディレクトリにあります（リポジトリは [`fdshg693/ZENN`](https://github.com/fdshg693/ZENN)）。

| 言語 | ディレクトリ |
|---|---|
| Elixir | [`resources/src/simple_rpg/`](https://github.com/fdshg693/ZENN/tree/main/resources/src/simple_rpg) |
| Python | [`resources/src/simple_rpg_python/`](https://github.com/fdshg693/ZENN/tree/main/resources/src/simple_rpg_python) |
| Go | [`resources/src/simple_rpg_go/`](https://github.com/fdshg693/ZENN/tree/main/resources/src/simple_rpg_go) |

3言語とも構成を1対1で対応させています。

| 役割 | Elixir | Python | Go |
|---|---|---|---|
| 起点・対話入力 | [`lib/rps_game.ex`](https://github.com/fdshg693/ZENN/blob/main/resources/src/simple_rpg/lib/rps_game.ex) | [`main.py`](https://github.com/fdshg693/ZENN/blob/main/resources/src/simple_rpg_python/main.py) | [`main.go`](https://github.com/fdshg693/ZENN/blob/main/resources/src/simple_rpg_go/main.go) |
| ゲームサーバー | [`lib/game_server.ex`](https://github.com/fdshg693/ZENN/blob/main/resources/src/simple_rpg/lib/game_server.ex) | [`game_server.py`](https://github.com/fdshg693/ZENN/blob/main/resources/src/simple_rpg_python/game_server.py) | [`game_server.go`](https://github.com/fdshg693/ZENN/blob/main/resources/src/simple_rpg_go/game_server.go) |
| プレイヤー | [`lib/player.ex`](https://github.com/fdshg693/ZENN/blob/main/resources/src/simple_rpg/lib/player.ex) | [`player.py`](https://github.com/fdshg693/ZENN/blob/main/resources/src/simple_rpg_python/player.py) | [`player.go`](https://github.com/fdshg693/ZENN/blob/main/resources/src/simple_rpg_go/player.go) |

### アーキテクチャ

```
        ┌──────────────┐
        │ GameServer   │   状態: { Alice: {mailbox, hand?}, Bob: {...} }
        │ (loop)       │
        └──────┬───────┘
       receive │ send (broadcast)
   ┌──────────┼──────────┐
   │ {:join}  │ {:result}│
   │ {:play}  │          │
   ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐
│Alice   │ │Bob     │ │…       │
│Process │ │Process │ │        │
└────────┘ └────────┘ └────────┘
```

各プレイヤーは自分専用の「mailbox（メッセージの受け口）」を持ち、サーバーは参加時にその参照を保管しておく、というのが共通の骨格です。

---

## 対比1: プロセスを起こす — `spawn_link` vs `Thread` vs `go`

**Elixir** ([`game_server.ex`](https://github.com/fdshg693/ZENN/blob/main/resources/src/simple_rpg/lib/game_server.ex), [`player.ex`](https://github.com/fdshg693/ZENN/blob/main/resources/src/simple_rpg/lib/player.ex))

```elixir
def start_link do
  {:ok, spawn_link(fn -> game_loop(%{}) end)}
end

def join(game_server, name) do
  player_pid = spawn_link(fn -> player_loop(name) end)
  send(game_server, {:join, player_pid, name})
  player_pid
end
```

**Python** ([`game_server.py`](https://github.com/fdshg693/ZENN/blob/main/resources/src/simple_rpg_python/game_server.py), [`player.py`](https://github.com/fdshg693/ZENN/blob/main/resources/src/simple_rpg_python/player.py))

```python
def start_link(self) -> "GameServer":
    self._thread = threading.Thread(target=self._game_loop, args=({},), daemon=True)
    self._thread.start()
    return self

@staticmethod
def join(game_server, name):
    mailbox = queue.Queue()
    threading.Thread(target=Player._player_loop, args=(name, mailbox), daemon=True).start()
    game_server.send(("join", mailbox, name))
    return mailbox
```

**Go** ([`game_server.go`](https://github.com/fdshg693/ZENN/blob/main/resources/src/simple_rpg_go/game_server.go), [`player.go`](https://github.com/fdshg693/ZENN/blob/main/resources/src/simple_rpg_go/player.go))

```go
func StartGameServer() chan<- Message {
    mailbox := make(chan Message, 16)
    go gameLoop(mailbox, map[string]playerState{})
    return mailbox
}

func JoinPlayer(server chan<- Message, name string) chan Result {
    mailbox := make(chan Result, 1)
    go playerLoop(name, mailbox)
    server <- Message{Kind: MsgJoin, Name: name, PlayerMailbox: mailbox}
    return mailbox
}
```

**何が違うか**

| 軸 | Elixir | Python | Go |
|---|---|---|---|
| 実行単位 | BEAM のプロセス（OSスレッドではない） | OSスレッド | goroutine（OSスレッドにM:N多重化） |
| 起動コスト | 軽い（言語の設計上、大量に起こす前提） | 重い | 軽い |
| 障害の伝播 | `spawn_link` で**親子が死を伝え合う** | なし（自分で例外監視） | なし（自分で `recover` / `context`） |

Elixir の `spawn_link` が他言語より一段上にあるのは「障害が黙って握りつぶされない」点です。Python の Thread や Go の goroutine は、内部で例外/panic を起こしても親側は気づきません。`spawn_link` ならリンクで繋がった相手の終了が自分にも伝搬し、`Supervisor` を組めば再起動戦略まで宣言できます（OTPの話なので本記事では深入りしません）。

なお Python の `threading` は GIL の影響で「同時並列実行」にはなりません。本記事は**書き味の対比**が目的なので、ここでは並列性能ではなく「並行モデルの記述」を比べていると思ってください。

---

## 対比2: メッセージパッシング — `send`/`receive` vs `Queue` vs `chan`

**Elixir**

```elixir
# 送信側（player.ex）
def play(game_server, name, hand) do
  send(game_server, {:play, name, hand})
end

# 受信側（game_server.ex）
defp game_loop(players) do
  receive do
    {:join, player_pid, name} -> ...
    {:play, name, hand}       -> ...
  end
end
```

**Python**

```python
# 送信側（player.py）
def play(game_server, name, hand):
    game_server.send(("play", name, hand))

# 受信側（game_server.py）
def _game_loop(self, players):
    while True:
        message = self.mailbox.get()
        match message:
            case ("join", player_mailbox, name): ...
            case ("play", name, hand): ...
```

**Go**

```go
// 送信側（player.go）
func PlayHand(server chan<- Message, name string, hand int) {
    server <- Message{Kind: MsgPlay, Name: name, Hand: hand}
}

// 受信側（game_server.go）
for {
    select {
    case msg := <-mailbox:
        switch msg.Kind { ... }
    }
}
```

**何が違うか**

ポイントは「**mailbox がどこに属しているか**」です。

- **Elixir**: mailbox は**プロセス自身に内蔵**されている。`send(pid, msg)` と書けば送り先プロセスの mailbox に積まれる。プログラマは別途 Queue を用意・受け渡す必要がない。
- **Python**: `threading.Thread` には mailbox がない。`queue.Queue` を**明示的に作り**、相手に「これがあなたのメールボックスです」と渡す必要がある（本記事の Python 版でも、プレイヤーは自前の `Queue` を作って join 時にサーバーへ参照を渡している）。
- **Go**: 同じく channel を**明示的に作って渡す**。Elixir と違い channel には所有者という概念がない（誰でも `send`/`recv` できる）ため、所有権を設計時に取り決める必要がある。

「mailbox がプロセスに付属する」というモデルが、Elixir の `send` をあれほど短く書ける理由です。

---

## 対比3: 受信時のパターンマッチ — `receive do … end` vs `match` vs `select`

メッセージは構造化データ（タプル）として送られ、受信側は「形」で分岐します。

**Elixir**

```elixir
receive do
  {:join, player_pid, name} ->
    new_players = Map.put(players, name, %{pid: player_pid, hand: nil})
    game_loop(new_players)

  {:play, name, hand} ->
    updated = put_in(players[name][:hand], hand)
    check_and_announce(updated)

  :quit ->
    :ok
end
```

**Python** (3.10+ の構造的パターンマッチ)

```python
match message:
    case ("join", player_mailbox, name):
        players = {**players, name: {"mailbox": player_mailbox, "hand": None}}
    case ("play", name, hand):
        players = {**players, name: {**players[name], "hand": hand}}
        if self._all_hands_ready(players):
            ...
    case ("quit",):
        return
```

**Go**

```go
switch msg.Kind {
case MsgJoin:
    players[msg.Name] = playerState{mailbox: msg.PlayerMailbox}
case MsgPlay:
    p := players[msg.Name]
    h := msg.Hand
    p.hand = &h
    players[msg.Name] = p
    if allHandsReady(players) { ... }
case MsgQuit:
    return
}
```

**何が違うか**

- **Elixir** は型なしで `{:join, pid, name}` のような**形そのもの**を直接パターンに書け、ローカル変数 `player_pid` / `name` への束縛まで1行で済みます。
- **Python 3.10+** の `match` 文は構文的にはかなり近いところまで来ています。
- **Go** は構造体 `Message` を定義し、判別用フィールド (`Kind`) を持ち、`switch` で分岐するスタイル。型安全な代わりに**メッセージの種類が増えるほどボイラープレートが増える**傾向があります（タグ付きunionが言語にないため）。

Elixir の `receive` は「キューを覗いてマッチするものを取り出す」という意味論なので、**マッチしないメッセージは mailbox に残る**という性質まで標準で備わっている点も Go の `select` とは違います（本記事のサンプルでは全メッセージにマッチするため発動していません）。

---

## 対比4: 末尾再帰ループ + 不変状態 — `game_loop(players)` vs `while` + 可変辞書

ここが**Elixirを読んで最初に戸惑う**ところでしょう。

**Elixir**

```elixir
defp game_loop(players) do
  receive do
    {:join, player_pid, name} ->
      new_players = Map.put(players, name, %{pid: player_pid, hand: nil})
      game_loop(new_players)         # ← 自分自身を呼び直す

    {:play, name, hand} ->
      updated = put_in(players[name][:hand], hand)
      check_and_announce(updated)    # ← 中で game_loop(...) を呼ぶ
  end
end
```

`players` は引数として渡された**不変な Map**。状態を更新したいときは「新しい Map を作って、自分自身を再帰呼び出しする」。BEAMの末尾呼び出し最適化により、これがそのまま無限ループとして動きます。

**Python**

```python
def _game_loop(self, players):
    while True:                       # ← 普通のループ
        message = self.mailbox.get()
        match message:
            case ("join", mailbox, name):
                players = {**players, name: {"mailbox": mailbox, "hand": None}}
                # ↑ ここは不変っぽく書いたが、ローカル変数 players を上書きしている
```

**Go**

```go
func gameLoop(mailbox <-chan Message, players map[string]playerState) {
    for {                             // ← 普通のループ
        select {
        case msg := <-mailbox:
            // players は map なので、要素を直接書き換えている
            players[msg.Name] = playerState{...}
        }
    }
}
```

**何が違うか**

| | Elixir | Python | Go |
|---|---|---|---|
| ループの形 | 関数の再帰 | `while True` | `for { }` |
| 状態の置き場所 | 関数引数（不変） | ローカル変数（書き換え） | map / struct（書き換え） |
| 「状態遷移」の表現 | `game_loop(new_players)` という**呼び出し** | 代入 | 代入 |

「**ループ変数 = 関数の引数**、**状態遷移 = 自分自身への引数違いの再呼び出し**」というメンタルモデルを掴むと、Elixir の `game_loop(players)` パターンが急に読めるようになります。これは GenServer 内部の `handle_call/3` → `{:reply, value, new_state}` の流れと同じ思想で、Elixir / OTP 全般に通底する設計です。

---

## 対比5: 関数節レベルのパターンマッチ — `defp beats?(1, 3), do: true`

「2つの手のうちどちらが勝つか」を判定する小さな関数。

**Elixir** ([`game_server.ex`](https://github.com/fdshg693/ZENN/blob/main/resources/src/simple_rpg/lib/game_server.ex))

```elixir
defp beats?(1, 2), do: false  # Paper beats Rock
defp beats?(1, 3), do: true   # Rock beats Scissors
defp beats?(2, 3), do: false  # Scissors beats Paper
defp beats?(_, _), do: false
```

**Python**

```python
def _beats(hand1, hand2):
    table = {
        (1, 2): False,
        (1, 3): True,
        (2, 3): False,
    }
    return table.get((hand1, hand2), False)
```

**Go**

```go
func beats(h1, h2 int) bool {
    switch {
    case h1 == 1 && h2 == 2:
        return false
    case h1 == 1 && h2 == 3:
        return true
    case h1 == 2 && h2 == 3:
        return false
    }
    return false
}
```

**何が違うか**

Elixir では**関数定義そのものが入力値に対するパターンマッチ**。同名の関数を引数違いで複数定義し、上から順にマッチした節が実行されます。条件分岐を `if` / `switch` で書かずに、「**この入力ならこの出力**」を表として並べる感覚です。

Python では辞書テーブル、Go では `switch` 文でほぼ同等のことができますが、Elixir のように**関数定義そのものに条件を埋め込む**ことはできません（Python の `singledispatch` や Go のジェネリクスでも、引数値そのものでのディスパッチは1段階構文上の遠さがあります）。

---

## おまけ: パイプ演算子 `|>` の読み心地

`find_winners` 内の「2種類の手が出たケース」の処理。

**Elixir**

```elixir
winners = hands
  |> Enum.filter(fn {_name, h} -> h == hand1 end)
  |> Enum.map(fn {name, _} -> name end)
  |> Enum.join(", ")
```

**Python** (リスト内包 + `join`)

```python
names = [name for name, h in hands.items() if h == winning_hand]
winners = ", ".join(names)
```

**Go** (1つ1つ手で書く)

```go
winners := []string{}
for _, name := range orderedNames {
    if hands[name] == winningHand {
        winners = append(winners, name)
    }
}
out := strings.Join(winners, ", ")
```

**何が違うか**

`|>` は「左側の値を、右側の関数の**第1引数**に渡す」だけの構文糖です。`Enum.filter` / `Enum.map` を順に流すと、**処理の流れと書き順が一致**します。Python のリスト内包も読みやすさで張り合えますが、変換が3段4段になると Elixir のパイプが優位になります。Go は標準ライブラリ的に1つ1つ手で書くスタイル（ジェネリクスを使った関数型ライブラリもありますが、慣用ではない）。

---

## まとめ — Elixirを読む4点セット

Elixirの並行処理コードは、**この4点セット**を意識すると一気に腑に落ちます。

1. **軽量プロセス** — `spawn_link` で起こす独立した実行単位。死は親に伝搬する
2. **メッセージング** — `send` / `receive`。mailbox はプロセスに付属するので明示的に持ち回さない
3. **不変状態 + 末尾再帰ループ** — `game_loop(state)` を `game_loop(new_state)` で呼び直す＝状態遷移
4. **パターンマッチ** — メッセージの形でも、関数定義の引数でも、両方で活躍

Python や Go で同じことをやろうとすると、`Thread` / `Queue`、`goroutine` / `chan`、可変 dict / map、構造体 + switch のように**4つの仕組みをそれぞれ別の道具で組み立てる**必要があります。一方 Elixir はこれらが**言語の中で噛み合うように設計された1つのモデル**として提供されている、というのが本記事を通して伝えたかった点です。

実コードを並べて読んでみたい方は、冒頭の表から3言語のディレクトリへどうぞ。

- Elixir: [`resources/src/simple_rpg/`](https://github.com/fdshg693/ZENN/tree/main/resources/src/simple_rpg)
- Python: [`resources/src/simple_rpg_python/`](https://github.com/fdshg693/ZENN/tree/main/resources/src/simple_rpg_python)
- Go: [`resources/src/simple_rpg_go/`](https://github.com/fdshg693/ZENN/tree/main/resources/src/simple_rpg_go)
