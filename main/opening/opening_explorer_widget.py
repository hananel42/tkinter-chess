#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk
import chess
from main.opening.opening_book_engine import OpeningBookTree

BOOK_TSV = "book.tsv"
CACHE_DB = "book_tree_cache.sqlite"

class OpeningExplorerWidget(tk.Frame):
    def __init__(self, master, tsv_path: str, cache_path: str = CACHE_DB, move_callback=None):
        super().__init__(master, bg="#1e1e1e")
        self.book = OpeningBookTree(tsv_path, cache_path)
        self.move_callback = move_callback
        self.last_opening_name = None
        self._build_ui()
        self._refresh()

    def _build_ui(self):
        # --- שם הפתיחה ---
        self.opening_lbl = tk.Label(
            self,
            text="—",
            font=("Segoe UI", 12, "bold"),
            bg="#1e1e1e",
            fg="#ffffff",
            anchor="w",
            pady=4
        )
        self.opening_lbl.pack(fill="x", padx=8, pady=(8, 0))

        # --- קו מפריד ---
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=6, padx=8)

        # --- Treeview לשורות צבעוניות ---
        frame = tk.Frame(self, bg="#1e1e1e")
        frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        style = ttk.Style()
        style.theme_use("clam")  # חשוב לשמור על רקע כהה
        style.configure("Treeview",
                        background="#1e1e1e",
                        foreground="#e6e6e6",
                        fieldbackground="#1e1e1e",
                        rowheight=24,
                        font=("Segoe UI", 11),
                        borderwidth=0)
        style.map("Treeview",
                  background=[("selected", "#3a6ea5")],
                  foreground=[("selected", "#ffffff")])

        self.tree = ttk.Treeview(
            frame,
            columns=("move",),
            show="tree",
            selectmode="browse",
            height=10
        )
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", self._on_double_click)

        # סרגל גלילה
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.config(yscrollcommand=scrollbar.set)

        # צבעים לחלופות
        self.tree.tag_configure("even", background="#2a2a2a", foreground="#e6e6e6")
        self.tree.tag_configure("odd", background="#242424", foreground="#ffffff")

    # --- רענון תוכן ---
    def _refresh(self):
        name = self.book.current_opening_name() or self.last_opening_name or "—"
        self.last_opening_name = name
        self.opening_lbl.config(text=name)

        # מחיקה והוספת מהלכים
        self.tree.delete(*self.tree.get_children())
        items = self.book.legal_continuations()
        for i, (uci, _) in enumerate(items):
            try:
                san = self.book.board.san(chess.Move.from_uci(uci))
            except Exception:
                san = uci
            tag = "even" if i % 2 == 0 else "odd"
            self.tree.insert("", "end", text=san, tags=(tag,))

    # --- טיפול בלחיצה כפולה ---
    def _on_double_click(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        san = self.tree.item(iid, "text")

        items = self.book.legal_continuations()
        uci = None
        for move_uci, _ in items:
            try:
                if self.book.board.san(chess.Move.from_uci(move_uci)) == san:
                    uci = move_uci
                    break
            except Exception:
                continue
        if not uci:
            return

        child_fen = self.book.get_child_fen(self.book.board.fen(), uci)
        if child_fen:
            self.book.set_fen(child_fen)
        else:
            try:
                self.book.push_uci(uci)
            except Exception:
                pass

        self._refresh()
        if self.move_callback:
            self.move_callback(uci)

    # --- API ללוח חיצוני ---
    def set_fen(self, fen: str):
        self.book.set_fen(fen)
        self._refresh()
    def reset(self):
        self.book.reset()
        self._refresh()


# ---------------- demo ----------------
if __name__ == "__main__":
    def on_move(uci):
        print("Move selected:", uci)

    root = tk.Tk()
    root.title("Opening Explorer")
    root.configure(bg="#1e1e1e")

    widget = OpeningExplorerWidget(root, BOOK_TSV, CACHE_DB, move_callback=on_move)
    widget.pack(fill="both", expand=True, padx=10, pady=10)

    root.mainloop()
