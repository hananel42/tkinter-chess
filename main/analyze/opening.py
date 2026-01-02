#!/usr/bin/env python3
# opening_manager.py

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional

import chess
import chess.pgn

# -----------------------------
# Data model
# -----------------------------
ECO_PGN_PATH = "eco.pgn"


@dataclass(frozen=True)
class OpeningInfo:
    eco: str
    name: str


# -----------------------------
# Opening Manager
# -----------------------------

class OpeningManager:
    """
    Ultra-fast opening book manager.

    Loads ECO PGN once and allows O(1) lookup:
    Given a board, determine whether the *last move*
    is still inside the opening book, and return opening name.
    """

    def __init__(self):
        # key -> OpeningInfo
        self._book: Dict[str, OpeningInfo] = {}

    # ---------- Public API ----------

    def load_eco_pgn(self, pgn_path: str) -> None:
        """
        Load an ECO PGN file (can be very large).
        This should be done ONCE at startup.
        """
        if not os.path.exists(pgn_path):
            raise FileNotFoundError(pgn_path)

        with open(pgn_path, "r", encoding="utf-8", errors="ignore") as f:
            while True:
                game = chess.pgn.read_game(f)
                if game is None:
                    break
                self._index_game(game)

    def opening_from_board(self, board: chess.Board) -> Optional[OpeningInfo]:
        """
        Given a board AFTER a move was played,
        returns OpeningInfo if still in opening book,
        otherwise None.
        """
        key = self._position_key(board)
        return self._book.get(key)

    # ---------- Internal ----------

    def _index_game(self, game: chess.pgn.Game) -> None:
        """
        Index all positions from a single opening PGN game.
        """
        eco = game.headers.get("ECO")
        name = game.headers.get("Opening")

        if not eco or not name:
            return

        opening = OpeningInfo(eco=eco, name=name)

        board = game.board()

        for move in game.mainline_moves():
            board.push(move)

            key = self._position_key(board)

            # Only set if not already known — earlier definition wins
            if key not in self._book:
                self._book[key] = opening

    @staticmethod
    def _position_key(board: chess.Board) -> str:
        """
        Fast, stable position key.

        Includes:
        - piece placement
        - side to move
        - castling rights
        - en-passant square

        Excludes:
        - move clocks (irrelevant for openings)
        """
        parts = board.fen().split(" ")
        return " ".join(parts[:4])


# -----------------------------
# Example usage
# -----------------------------

if __name__ == "__main__":
    """
    Demo: load openings, play some moves, query opening name.
    """

    # 1) Create manager
    om = OpeningManager()

    # 2) Load ECO database (see sources below)

    om.load_eco_pgn(ECO_PGN_PATH)

    # 3) Play a known opening
    board = chess.Board()
    moves = [
        "e2e4",
        "h7h6",
        "h2h3",
    ]

    for uci in moves:
        board.push(chess.Move.from_uci(uci))
        info = om.opening_from_board(board)
        if info:
            print(f"Opening: {info.eco} – {info.name}")
        else:
            print("Out of book")
