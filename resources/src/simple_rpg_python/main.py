"""Python equivalent of rps_game.ex.

Elixir の iex 対話セッションに相当する起点。標準入力から手を受け取り、
GameServer / Player に対してメッセージを送る。
"""

from __future__ import annotations

import time

from game_server import GameServer
from player import Player


def start_game() -> GameServer:
    print("=== Rock Paper Scissors Game Server Started ===")
    server = GameServer().start_link()
    print(f"Server thread: {server._thread.name}")
    print('Step 1: server.join(name)')
    print('Step 2: server.play(name)')
    return server


def join_as_player(server: GameServer, name: str):
    print(f"=== {name} joined the game ===")
    return Player.join(server, name)


def play(server: GameServer, name: str) -> None:
    print(f"{name}'s turn! Enter your hand (1=Rock, 2=Paper, 3=Scissors)")
    hand = _get_hand(name)
    Player.play(server, name, hand)
    print(f"{name} has played!")


def _get_hand(player_name: str) -> int:
    while True:
        raw = input(f"{player_name}の手 (1-3): ").strip()
        if raw in {"1", "2", "3"}:
            return int(raw)
        print("1、2、または3を入力してください")


if __name__ == "__main__":
    server = start_game()
    join_as_player(server, "Alice")
    join_as_player(server, "Bob")
    play(server, "Alice")
    play(server, "Bob")
    # 結果の broadcast がプレイヤースレッドに届くのを少し待つ
    time.sleep(0.2)
