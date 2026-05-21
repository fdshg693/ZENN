# simple_rpg_go

[`resources/src/simple_rpg/`](../simple_rpg/) の Elixir 版じゃんけんサーバーを、Go の goroutine + channel で1対1に書き写したもの。Zenn 記事「Elixirの並行処理を、PythonとGoの実装と並べて読む」の対比用。

## 構成

| ファイル | Elixir 版の対応 |
|---|---|
| `game_server.go` | `lib/game_server.ex` |
| `player.go` | `lib/player.ex` |
| `main.go` | `lib/rps_game.ex` |

## 実行

Go 1.21 以上。

```bash
go run .
```

`Alice の手` → `1` 、`Bob の手` → `2` のように入力すると、結果が両プレイヤーの goroutine に broadcast される。
