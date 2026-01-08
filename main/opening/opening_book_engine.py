#!/usr/bin/env python3
"""
opening_book_tree_engine.py

Tree-based OpeningBook engine.

Builds an in-memory tree (nodes indexed by canonical FEN "piece placement side castling enpassant")
from book.tsv (supports various header names and delimiters). Each node stores:
 - fen
 - continuations: { uci: count }
 - children: { uci: child_fen }
 - names_counter: { opening_name: count }   # only incremented for the final FEN of a PGN line
 - eco_counter: { eco_code: count }         # similarly for final FEN

Caches the tree to SQLite (book_tree_cache.sqlite) for fast subsequent loads.

API:
 - OpeningBookTree(tsv_path, cache_path="book_tree_cache.sqlite")
 - reset(), set_fen(fen), push_uci(uci), pop()
 - legal_continuations() -> List[(uci, freq)]
 - current_opening_name() -> Optional[str]
 - node_for_fen(fen) -> dict with node data
"""
from __future__ import annotations
import csv
import sqlite3
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import chess
import time

# CONFIG
CACHE_FILENAME = "book_tree_cache.sqlite"

# Regexes to clean PGN-like moves field
_RE_BRACES = re.compile(r"\{[^}]*\}")
_RE_PARENS = re.compile(r"\([^)]*\)")
_RE_NAG = re.compile(r"\$\d+")
_RE_MOVE_NUM = re.compile(r"\b\d+\.(\.\.)?")
_RE_RESULT = re.compile(r"\b1-0\b|\b0-1\b|\b1/2-1/2\b|\*\b", re.I)


def _clean_pgn_to_tokens(pgn: str) -> List[str]:
    """Strip comments, variations, NAGs, move numbers and results; split into SAN tokens."""
    if not pgn:
        return []
    s = pgn
    s = _RE_BRACES.sub(" ", s)
    s = _RE_PARENS.sub(" ", s)
    s = _RE_NAG.sub(" ", s)
    s = _RE_MOVE_NUM.sub(" ", s)
    s = _RE_RESULT.sub(" ", s)
    s = re.sub(r"[;,:]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return []
    toks = [t for t in s.split(" ") if t and not t.isdigit()]
    return toks


def _normalize_header(h: str) -> str:
    return re.sub(r"[^a-z0-9]", "", h.strip().lower())


def _guess_delim_from_sample(sample: str) -> Optional[str]:
    if "\t" in sample:
        return "\t"
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except Exception:
        return None


class OpeningNode:
    __slots__ = ("fen", "continuations", "children", "names_counter", "eco_counter")

    def __init__(self, fen: str):
        self.fen: str = fen
        self.continuations: Dict[str, int] = {}   # uci -> count
        self.children: Dict[str, str] = {}        # uci -> child_fen
        self.names_counter: Dict[str, int] = {}   # opening name -> count (final fen only)
        self.eco_counter: Dict[str, int] = {}     # eco -> count (final fen only)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fen": self.fen,
            "continuations": dict(self.continuations),
            "children": dict(self.children),
            "names_counter": dict(self.names_counter),
            "eco_counter": dict(self.eco_counter),
        }


class OpeningBookTree:
    def __init__(self, tsv_path: str, cache_path: str = CACHE_FILENAME):
        self.tsv_path = Path(tsv_path)
        if not self.tsv_path.exists():
            raise FileNotFoundError(f"{self.tsv_path} not found")
        self.cache_path = Path(cache_path)
        self.board = chess.Board()
        self.nodes: Dict[str, OpeningNode] = {}  # fen -> OpeningNode
        self._ensure_cache_and_load()

    # ---------------- cache management ----------------
    def _ensure_cache_and_load(self):
        tsv_mtime = self.tsv_path.stat().st_mtime
        if self.cache_path.exists() and self.cache_path.stat().st_mtime >= tsv_mtime:
            self._load_from_sqlite()
        else:
            self._build_from_tsv_and_save()

    # ---------------- building ----------------
    def _build_from_tsv_and_save(self):
        sample = self.tsv_path.read_text(encoding="utf-8")
        delim = _guess_delim_from_sample(sample) or "\t"

        rows = []
        with self.tsv_path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter=delim)
            for r in reader:
                if not any(cell.strip() for cell in r):
                    continue
                rows.append(r)

        if not rows:
            raise ValueError("Empty book file")

        header = rows[0]
        header_norm = [_normalize_header(h) for h in header]

        # find indexes
        moves_idx = None
        name_idx = None
        eco_idx = None
        for i, h in enumerate(header_norm):
            if moves_idx is None and ("pgn" in h or "move" in h or "moves" in h):
                moves_idx = i
            if name_idx is None and ("name" in h or "opening" in h or "title" in h):
                name_idx = i
            if eco_idx is None and ("eco" in h):
                eco_idx = i
        if moves_idx is None:
            moves_idx = len(header) - 1
        if name_idx is None and len(header) >= 2:
            name_idx = 1

        # start with root node (startpos)
        root_fen = self._fen_key(chess.Board())
        self._ensure_node(root_fen)

        # --- השינוי הקטן: assign default name for starting position ---
        root_node = self.nodes[root_fen]
        root_node.names_counter["Starting board"] = 1
        root_node.eco_counter[""] = 1  # אפשר להשאיר ריק אם אין ECO

        for row in rows[1:]:
            if moves_idx >= len(row):
                continue
            moves_field = row[moves_idx].strip()
            name_field = (row[name_idx].strip() if (name_idx is not None and name_idx < len(row)) else "")
            eco_field = (row[eco_idx].strip() if (eco_idx is not None and eco_idx < len(row)) else "")

            tokens = _clean_pgn_to_tokens(moves_field)
            if not tokens:
                continue

            b = chess.Board()
            prev_fen = self._fen_key(b)

            for tok in tokens:
                try:
                    mv = b.parse_san(tok)
                except Exception:
                    # cannot parse token here — stop processing this line
                    prev_fen = None
                    break
                uci = mv.uci()
                child_fen = self._fen_key_after_move(b, mv)

                # ensure nodes exist
                self._ensure_node(prev_fen)
                self._ensure_node(child_fen)

                # record continuation count
                node = self.nodes[prev_fen]
                node.continuations[uci] = node.continuations.get(uci, 0) + 1
                node.children[uci] = child_fen

                # advance
                b.push(mv)
                prev_fen = child_fen

            # at the end of the PGN line, register opening name / ECO for the final fen (if parsed fully)
            if prev_fen is not None and name_field:
                node_final = self.nodes[prev_fen]
                node_final.names_counter[name_field] = node_final.names_counter.get(name_field, 0) + 1
                if eco_field:
                    node_final.eco_counter[eco_field] = node_final.eco_counter.get(eco_field, 0) + 1

        # save to sqlite
        self._save_to_sqlite()

    def _ensure_node(self, fen: str):
        if fen not in self.nodes:
            self.nodes[fen] = OpeningNode(fen)

    def _fen_key(self, board: chess.Board) -> str:
        return " ".join(board.fen().split()[:4])

    def _fen_key_after_move(self, board: chess.Board, move: chess.Move) -> str:
        # make a copy to avoid mutating caller
        tmp = board.copy()
        tmp.push(move)
        return self._fen_key(tmp)

    # ---------------- sqlite persistence ----------------
    def _save_to_sqlite(self):
        if self.cache_path.exists():
            try:
                self.cache_path.unlink()
            except Exception:
                pass
        conn = sqlite3.connect(str(self.cache_path))
        cur = conn.cursor()
        cur.execute("PRAGMA synchronous = OFF")
        cur.execute("CREATE TABLE nodes (fen TEXT PRIMARY KEY, name TEXT, eco TEXT)")
        cur.execute("CREATE TABLE continuations (fen TEXT, uci TEXT, freq INTEGER, child_fen TEXT)")
        cur.execute("CREATE INDEX idx_cont_fen ON continuations(fen)")
        # insert nodes (we store the most frequent name/eco for convenience)
        node_rows = []
        cont_rows = []
        for fen, node in self.nodes.items():
            # choose top name/eco or NULL
            name = None
            eco = None
            if node.names_counter:
                name = max(node.names_counter.items(), key=lambda kv: kv[1])[0]
            if node.eco_counter:
                eco = max(node.eco_counter.items(), key=lambda kv: kv[1])[0]
            node_rows.append((fen, name, eco))
            for uci, freq in node.continuations.items():
                child = node.children.get(uci)
                cont_rows.append((fen, uci, freq, child))
        cur.executemany("INSERT INTO nodes (fen, name, eco) VALUES (?, ?, ?)", node_rows)
        if cont_rows:
            cur.executemany("INSERT INTO continuations (fen, uci, freq, child_fen) VALUES (?, ?, ?, ?)", cont_rows)
        conn.commit()
        conn.close()

    def _load_from_sqlite(self):
        conn = sqlite3.connect(str(self.cache_path))
        cur = conn.cursor()
        self.nodes = {}
        for fen, name, eco in cur.execute("SELECT fen, name, eco FROM nodes"):
            node = OpeningNode(fen)
            if name:
                node.names_counter[name] = 1
            if eco:
                node.eco_counter[eco] = 1
            self.nodes[fen] = node
        for fen, uci, freq, child in cur.execute("SELECT fen, uci, freq, child_fen FROM continuations"):
            self._ensure_node(fen)
            node = self.nodes[fen]
            node.continuations[uci] = freq
            if child:
                node.children[uci] = child
            # ensure child node exists (to keep structure)
            if child:
                self._ensure_node(child)
        conn.close()

    # ---------------- API ----------------
    def reset(self):
        self.board.reset()

    def set_fen(self, fen: str):
        self.board.set_fen(fen)

    def push_uci(self, uci: str):
        m = chess.Move.from_uci(uci)
        if m not in self.board.legal_moves:
            raise ValueError(f"Move {uci} not legal here")
        self.board.push(m)

    def pop(self):
        if self.board.move_stack:
            self.board.pop()

    def legal_continuations(self) -> List[Tuple[str, int]]:
        fen = self._fen_key(self.board)
        node = self.nodes.get(fen)
        if not node:
            return []
        # filter to legal moves
        items: List[Tuple[str, int]] = []
        for uci, freq in node.continuations.items():
            try:
                m = chess.Move.from_uci(uci)
            except Exception:
                continue
            if m in self.board.legal_moves:
                items.append((uci, freq))
        items.sort(key=lambda x: -x[1])
        return items

    def current_opening_name(self) -> Optional[str]:
        """
        Return the most specific opening name available along the path from the start to the current position.
        We traverse the move_stack from the root and pick the deepest node that has a name.
        """
        tmp = self.board.copy()
        best_name = None
        # check root too (some lines might name the starting position, though rare)
        root_fen = self._fen_key(tmp)
        root_node = self.nodes.get(root_fen)
        if root_node and root_node.names_counter:
            best_name = max(root_node.names_counter.items(), key=lambda kv: kv[1])[0]

        for mv in self.board.move_stack:
            tmp.push(mv)
            fen = self._fen_key(tmp)
            node = self.nodes.get(fen)
            if node and node.names_counter:
                # pick most frequent name at this fen
                name = max(node.names_counter.items(), key=lambda kv: kv[1])[0]
                best_name = name
        return best_name

    def node_for_fen(self, fen: str) -> Optional[Dict[str, Any]]:
        key = " ".join(fen.split()[:4])
        node = self.nodes.get(key)
        if not node:
            return None
        return node.to_dict()

    def get_child_fen(self, fen: str, uci: str) -> Optional[str]:
        node = self.nodes.get(" ".join(fen.split()[:4]))
        if not node:
            return None
        return node.children.get(uci)

    def get_eco_for_fen(self, fen: str) -> Optional[str]:
        key = " ".join(fen.split()[:4])
        node = self.nodes.get(key)
        if not node:
            return None
        if not node.eco_counter:
            return None
        return max(node.eco_counter.items(), key=lambda kv: kv[1])[0]


# ---------------- standalone test (no GUI) ----------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Test OpeningBookTree engine")
    parser.add_argument("tsv", nargs="?", default="book.tsv", help="path to book.tsv")
    parser.add_argument("--cache", default="book_tree_cache.sqlite", help="cache sqlite path")
    args = parser.parse_args()

    path = Path(args.tsv)
    if not path.exists():
        print(f"{path} not found. Put book.tsv in the current folder or pass the path.")
        raise SystemExit(2)

    t0 = time.time()
    book = OpeningBookTree(str(path), cache_path=args.cache)
    t1 = time.time()
    print(f"Loaded tree: {len(book.nodes)} nodes in {t1-t0:.2f}s (cache: {args.cache})")

    # startpos continuations
    book.reset()
    items = book.legal_continuations()
    print("\nTop continuations from start position (SAN, UCI, freq):")
    for i, (uci, freq) in enumerate(items[:20], start=1):
        try:
            san = book.board.san(chess.Move.from_uci(uci))
        except Exception:
            san = uci
        print(f"{i:2d}. {san:6}  {uci}  ({freq})")

    # sample node info for a common child (if exists)
    if items:
        first_uci = items[0][0]
        # push and print node info
        book.push_uci(first_uci)
        print("\nAfter playing first continuation, current FEN:", book.board.fen())
        node = book.node_for_fen(book.board.fen())
        print("Node info keys:", list(node.keys()) if node else None)
        if node:
            print("Top continuations from this node (SAN, UCI, freq):")
            for uci, freq in sorted(node["continuations"].items(), key=lambda kv: -kv[1])[:10]:
                try:
                    san = book.board.san(chess.Move.from_uci(uci))
                except Exception:
                    san = uci
                print(f"  {san:6} {uci} ({freq})")
            print("Opening names at this node (most frequent):", node["names_counter"])
            print("ECOs at this node:", node["eco_counter"])

    # show best name for current position (deepest)
    print("\nDeepest opening name for current position:", book.current_opening_name())

    print("\nDone.")
