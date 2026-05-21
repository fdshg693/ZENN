# simple_rpg_python

[`resources/src/simple_rpg/`](../simple_rpg/) の Elixir 版じゃんけんサーバーを、Python の `threading` + `queue.Queue` で1対1に書き写したもの。Zenn 記事「Elixirの並行処理を、PythonとGoの実装と並べて読む」の対比用。

## 構成

| ファイル | Elixir 版の対応 |
|---|---|
| `game_server.py` | `lib/game_server.ex` |
| `player.py` | `lib/player.ex` |
| `main.py` | `lib/rps_game.ex` |

## 実行

Python 3.10 以上（`match` 文を使うため）。

```bash
python main.py
```

`Alice の手` → `1` 、`Bob の手` → `2` のように入力すると、結果が両プレイヤーのスレッドに broadcast される。
