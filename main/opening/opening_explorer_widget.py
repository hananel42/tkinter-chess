#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk
import chess
from main.opening.opening_book_engine import OpeningBookTree

BOOK_TSV = "book.tsv"
CACHE_DB = "book_tree_cache.sqlite"


class OpeningExplorerWidget(tk.Frame):
    def __init__(self, master, tsv_path: str, cache_path: str = CACHE_DB, move_callback=None):
        super().__init__(master)
        self.book = OpeningBookTree(tsv_path, cache_path)
        self.move_callback = move_callback
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        self.opening_lbl = ttk.Label(self, text="—", font=("Segoe UI", 10, "bold"))
        self.opening_lbl.pack(fill="x", padx=5, pady=5)

        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=4)

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=5, pady=5)

        self.listbox = tk.Listbox(frame,
            bg="#1e1e1e",
            fg="#e6e6e6",
            selectbackground="#3a6ea5",
            selectforeground="#ffffff",
            highlightthickness=0,
            borderwidth=0,
            activestyle="none",
            font=("Segoe UI", 11),
            relief="flat",
            width=40,
            height=8
        )
        self.listbox.pack(side="left", fill="both", expand=True)
        self.listbox.bind("<Double-Button-1>", self._on_double_click)

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=scrollbar.set)

    def _refresh(self):
        # עדכון שם הפתיחה העמוק ביותר
        name = self.book.current_opening_name() or "—"
        self.opening_lbl.config(text=name)

        # עדכון רשימת המהלכים
        items = self.book.legal_continuations()
        self.listbox.delete(0, tk.END)
        for uci, _ in items:
            try:
                san = self.book.board.san(chess.Move.from_uci(uci))
            except Exception:
                san = uci
            self.listbox.insert(tk.END, san)

    def _on_double_click(self, _event):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        items = self.book.legal_continuations()
        if idx >= len(items):
            return
        uci = items[idx][0]

        # עבור לילד בעץ
        child_fen = self.book.get_child_fen(self.book.board.fen(), uci)
        if child_fen:
            self.book.set_fen(child_fen)
            self._refresh()
        else:
            try:
                self.book.push_uci(uci)
                self._refresh()
            except Exception:
                pass
        if self.move_callback:
            self.move_callback(uci)

    # API ללוח חיצוני
    def set_fen(self, fen: str):
        self.book.set_fen(fen)
        self._refresh()

    def reset(self):
        self.book.reset()
        self._refresh()


# ---------------- demo ----------------
if __name__ == "__main__":
    def on_move(fen):
        print("Move selected, new FEN:", fen)

    root = tk.Tk()
    root.title("Opening Explorer")
    widget = OpeningExplorerWidget(root, BOOK_TSV, CACHE_DB, move_callback=on_move)
    widget.pack(fill="both", expand=True)
    root.mainloop()
