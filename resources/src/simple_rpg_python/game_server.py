"""Python equivalent of game_server.ex.

Elixir 版の game_loop(players) を threading.Thread + queue.Queue で再現する。
Elixir の mailbox に相当する Queue を GameServer 側で1つ保有し、
プレイヤーからの (type, payload) タプルを receive 相当で取り出して分岐する。
"""

from __future__ import annotations

import queue
import threading
from typing import Optional


HAND_NAMES = {1: "Rock", 2: "Paper", 3: "Scissors"}


def _beats(hand1: int, hand2: int) -> bool:
    # Elixir の defp beats?/2 と同じ表 (1=Rock, 2=Paper, 3=Scissors)
    table = {
        (1, 2): False,
        (1, 3): True,
        (2, 3): False,
    }
    return table.get((hand1, hand2), False)


class GameServer:
    def __init__(self) -> None:
        self.mailbox: "queue.Queue[tuple]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None

    def start_link(self) -> "GameServer":
        self._thread = threading.Thread(target=self._game_loop, args=({},), daemon=True)
        self._thread.start()
        return self

    def send(self, message: tuple) -> None:
        self.mailbox.put(message)

    def _game_loop(self, players: dict) -> None:
        while True:
            message = self.mailbox.get()
            match message:
                case ("join", player_mailbox, name):
                    players = {**players, name: {"mailbox": player_mailbox, "hand": None}}
                case ("play", name, hand):
                    players = {**players, name: {**players[name], "hand": hand}}
                    if self._all_hands_ready(players):
                        result = self._judge_game(players)
                        for _name, info in players.items():
                            info["mailbox"].put(("result", result))
                        players = {}
                case ("quit",):
                    return

    @staticmethod
    def _all_hands_ready(players: dict) -> bool:
        return all(info["hand"] is not None for info in players.values())

    @staticmethod
    def _judge_game(players: dict) -> str:
        hands = {name: info["hand"] for name, info in players.items()}
        hand_names = ", ".join(f"{name}: {HAND_NAMES[h]}" for name, h in hands.items())
        winners = GameServer._find_winners(hands)
        return f"Result: {hand_names} → {', '.join(winners)}"

    @staticmethod
    def _find_winners(hands: dict) -> list[str]:
        unique = sorted(set(hands.values()))
        if len(unique) == 1:
            return ["Draw!"]
        if len(unique) == 2:
            hand1, hand2 = unique
            winning_hand = hand1 if _beats(hand1, hand2) else hand2
            names = [name for name, h in hands.items() if h == winning_hand]
            return [f"{', '.join(names)} win!"]
        return ["Three-way: Scissors beats Paper, Paper beats Rock, Rock beats Scissors - Draw!"]
