"""Python equivalent of player.ex.

Elixir の Player プロセスを threading.Thread で再現する。
各プレイヤーは自分専用の Queue（mailbox）を持ち、サーバーに参加登録時に渡す。
"""

from __future__ import annotations

import queue
import threading

from game_server import GameServer


class Player:
    @staticmethod
    def join(game_server: GameServer, name: str) -> "queue.Queue[tuple]":
        mailbox: "queue.Queue[tuple]" = queue.Queue()
        threading.Thread(target=Player._player_loop, args=(name, mailbox), daemon=True).start()
        game_server.send(("join", mailbox, name))
        return mailbox

    @staticmethod
    def play(game_server: GameServer, name: str, hand: int) -> None:
        game_server.send(("play", name, hand))

    @staticmethod
    def _player_loop(name: str, mailbox: "queue.Queue[tuple]") -> None:
        message = mailbox.get()
        match message:
            case ("result", result):
                print(f"[{name}] {result}")
