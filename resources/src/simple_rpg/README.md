# RpsGame

Elixirの並行処理とメッセージパッシングの特性を実演するロック・ペーパー・シザーズゲーム。複数プロセスの独立実行とプロセス間通信を活かしたシンプルな設計です。

## 特徴

- **プロセス生成**：各プレイヤーが独立したプロセスとして実行
- **メッセージパッシング**：プレイヤーとゲームサーバー間で非同期メッセージ通信
- **状態カプセル化**：各プレイヤーは他のプレイヤーの手を見えない独立状態を実現
- **サーバー責務**：全員の手が確定後、ゲームサーバーが全プレイヤーに結果をブロードキャスト
- **シンプル**：プロセス通信の本質を示す最小限のコード（140行以下）

## 使い方

### インタラクティブゲーム

Elixirの並行処理の威力を体験するため、同一シェル内で複数の独立したプレイヤープロセスを実行します。

**ステップ1: ゲームサーバー起動**

シェルを開いてサーバーを起動：
```bash
iex -S mix
```

```elixir
iex(1)> server = RpsGame.start_game()
=== Rock Paper Scissors Game Server Started ===
Server PID: #PID<0.123.0>
Step 1: Players join with RpsGame.join_as_player(server, "name")
Step 2: Players play with RpsGame.play(server, "name")
#PID<0.123.0>
```

**ステップ2: プレイヤーたちが参加（プレイヤープロセスが起動）**

```elixir
iex(2)> RpsGame.join_as_player(server, "Alice")
=== Alice joined the game ===
#PID<0.156.0>

iex(3)> RpsGame.join_as_player(server, "Bob")
=== Bob joined the game ===
#PID<0.158.0>
```

**ステップ3: プレイヤーたちが手を出す（独立して入力）**

```elixir
iex(4)> RpsGame.play(server, "Alice")
Alice's turn! Enter your hand (1=Rock, 2=Paper, 3=Scissors)
Aliceの手 (1-3): 1
Alice has played!

iex(5)> RpsGame.play(server, "Bob")
Bob's turn! Enter your hand (1=Rock, 2=Paper, 3=Scissors)
Bobの手 (1-3): 2
Bob has played!
[Alice] Result: Alice: Rock, Bob: Paper → Bob win!
[Bob] Result: Alice: Rock, Bob: Paper → Bob win!
```

全プレイヤーが手を送信すると、サーバーが結果を各プレイヤーにブロードキャストします。プレイヤープロセスは独立して実行されており、メッセージパッシングによる非同期通信を実演しています。

## アーキテクチャ

### GameServer

中央のゲーム調整プロセス。プレイヤーの参加管理、手の収集、勝敗判定、結果の配信を担当。

- `start_link/0` - ゲームサーバー起動
- メッセージ：`:join`, `:play`

### Player

各プレイヤーのプロセス。ゲームサーバーにメッセージを送信し、結果を受け取る。

- `join/2` - ゲームサーバーに参加登録
- `play/3` - 手を送信（1-3の数値）

## ルール

1. 全プレイヤーが手を送信するまで待機
2. 全員揃ったら勝敗判定：
   - 全員同じ手 → Draw
   - 2種類の手 → 勝つ手を出した方が勝利
   - 3種類の手 → 三角形なので Draw
3. 結果は全プレイヤーにブロードキャスト

