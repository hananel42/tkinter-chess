#!/usr/bin/env python3
# san_list_widget.py
from __future__ import annotations

import io
import tkinter as tk
import tkinter.colorchooser as colorchooser
import tkinter.filedialog as filedialog
import tkinter.messagebox as messagebox
import tkinter.simpledialog as simpledialog
import typing as t

import chess
import chess.pgn

# Mapping from common NAG symbols to numeric codes (PGN NAG)
NAG_SYMBOL_TO_CODE = {
    "!": 1,
    "?": 2,
    "!!": 3,
    "??": 4,
    "!?": 5,
    "?!": 6,
}

NAG_CODE_TO_SYMBOL = {v: k for k, v in NAG_SYMBOL_TO_CODE.items()}


class SanListFrame(tk.Frame):
    """
    SanListWidget — configurable inline SAN moves with:
      - per-move coloring (efficient: color tags cached)
      - inline display/editing of comments
      - NAG annotations (stored & exported)
      - PGN export including comments and NAGs
      - context menu on right-click for quick annotation actions
      - load PGN from string/file (preserves comments & NAGs)
      - on_select callback returns (node, fen, history) with full history data to reconstruct game
    """

    class _Node:
        """
        Represents a node in the tree structure representing moves and their metadata.

        Attributes:
            san (str): The SAN representation of the move.
            fen (str): The FEN string representing the board state after the move.
            move_number (int): The number of the move in the sequence.
            color (str): The color of the player who made the move ("white" or "black").
            parent (_Node | None): The parent node in the tree structure.
            node_children (list[_Node]): A list of child nodes representing subsequent moves.
            comment (str): An optional comment associated with the node.
            nags (set[int]): A set of numeric NAG codes indicating special annotations for the move.
            annot_color (str | None): The hexadecimal color string used for displaying move text.
            extras (dict[str, Any]): Additional metadata about the node, such as engine evaluations or UI flags.

        Methods:
            add_child(node: _Node): Adds a child node to this node and updates its parent reference.
            remove_child(node: _Node): Removes a child node from this node and updates its parent reference.
            is_root() -> bool: Checks if this node is the root of the tree (i.e., has no parent).
        """
        __slots__ = (
            "san", "fen", "move_number", "color", "parent",
            "node_children", "comment", "nags", "annot_color","extras"
        )

        def __init__(
                self,
                san: str | None,
                fen: str | None,
                move_number: int,
                color: str | None,
                parent: "SanListFrame._Node | None" = None,
                comment: str | None = None,
        ):
            self.san = san
            self.fen = fen
            self.move_number = move_number
            self.color = color  # "white" or "black"
            self.parent = parent
            self.node_children: list[SanListFrame._Node] = []
            self.comment = comment or ""
            self.nags: set[int] = set()  # numeric NAG codes (e.g. {1} for "!")
            self.annot_color: str | None = None  # hex color string for this move text (e.g. "#ff0000")
            self.extras: dict[str, t.Any] = {}  # arbitrary per-node metadata (engine eval, UI flags, etc.)
        def add_child(self, node: "SanListFrame._Node"):
            node.parent = self
            self.node_children.append(node)

        def remove_child(self, node: "SanListFrame._Node"):
            try:
                self.node_children.remove(node)
                node.parent = None
            except ValueError:
                pass

        def is_root(self) -> bool:
            return self.parent is None

        def __repr__(self):
            return f"<Node san={self.san!r} num={self.move_number} children={len(self.node_children)}>"

    def __init__(
            self,
            master,
            *,

            starting_fen: str = chess.STARTING_FEN,
            max_chars_per_line: int = 80,
            on_select: t.Optional[t.Callable[["SanListFrame._Node", str], None]] = None,
            font: tuple[str, int] = ("Arial", 10, "bold"),
            bold_font: tuple[str, int, str] = ("Arial", 10, "bold"),
            color_paren: str = "#888888",
            color_variation: str = "#666666",
            color_mainline: str = "#000000",
            color_comment: str = "#2f4f4f",
            color_current_bg: str = "#fff3bf",
            **kwargs,
    ):
        super().__init__(master, **kwargs)
        self._starting_fen = starting_fen
        self._max_chars = max_chars_per_line
        # on_select signature: (node, fen, history_list)
        self._on_select = on_select

        # style options
        self._font = font
        self._bold_font = bold_font
        self._color_paren = color_paren
        self._color_variation = color_variation
        self._color_mainline = color_mainline
        self._color_comment = color_comment
        self._color_current_bg = color_current_bg

        # Model
        self._root = SanListFrame._Node(san=None, fen=self._starting_fen, move_number=0, color=None, parent=None)
        self._selected: SanListFrame._Node = self._root

        # UI helpers
        self._node_tag: dict[SanListFrame._Node, str] = {}
        self._tag_node: dict[str, SanListFrame._Node] = {}
        # color tag cache: hex -> tagname
        self._color_tag_map: dict[str, str] = {}

        # Build UI
        self._build_ui()
        self.refresh()

    # ---------------- UI ----------------
    def _build_ui(self):
        self._text = tk.Text(
            self,
            wrap="word",
            state="disabled",
            cursor="arrow",
            height=10,
            width=50,
            font=self._font,
            padx=5,
            pady=5,
            undo=False,
        )
        self._text.pack(side="left", fill="both", expand=True)
        self._text.bind("<<Selection>>", lambda e: self._text.tag_remove("sel", "1.0", "end"))
        vsb = tk.Scrollbar(self, orient="vertical", command=self._text.yview)
        vsb.pack(side="right", fill="y")
        self._text.configure(yscrollcommand=vsb.set)

        # tags
        self._text.tag_configure("paren", foreground=self._color_paren)
        self._text.tag_configure("variation", foreground=self._color_variation)
        self._text.tag_configure("mainline", foreground=self._color_mainline)
        self._text.tag_configure("comment", foreground=self._color_comment, font=self._font)
        # current uses a background highlight; font will be applied via dynamic tag
        self._text.tag_configure("current_bg", background=self._color_current_bg)

        # context menu template
        self._context_menu = tk.Menu(self, tearoff=0)
        # menu entries will be built on demand per node

    # ---------------- model helpers ----------------
    @staticmethod
    def _create_node(parent: _Node, san: str) -> _Node:
        board = chess.Board(fen=parent.fen)
        prior_turn = board.turn
        try:
            mv = board.parse_san(san)
        except Exception as e:
            raise ValueError(f"Invalid SAN '{san}': {e}")
        board.push(mv)
        color = "white" if prior_turn == chess.WHITE else "black"
        move_number = board.fullmove_number if color == "white" else board.fullmove_number - 1
        node = SanListFrame._Node(san=san, fen=board.fen(), move_number=move_number, color=color, parent=parent)
        return node

    @staticmethod
    def _is_descendant(node: _Node | None, ancestor: _Node) -> bool:
        cur = node
        while cur is not None:
            if cur is ancestor:
                return True
            cur = cur.parent
        return False

    @staticmethod
    def is_variation_start(node: SanListFrame._Node) -> bool:
        if not node.parent:
            return False
        # node is a variation if it is not the first child
        return node.parent.node_children and node.parent.node_children[0] is not node

    # ---------------- Public Operations ----------------
    def add_move(self, san: str) -> _Node | None:
        # Safety: don't update if widget destroyed
        try:
            if not self.winfo_exists():
                return None
        except tk.TclError:
            return None

        parent = self._selected

        # avoid duplicate identical SAN under same parent
        existing = next((c for c in parent.node_children if c.san == san), None)
        if existing:
            node = existing
        else:
            node = self._create_node(parent, san)
            parent.add_child(node)

        # move selection to new node
        self._selected = node
        self.refresh()
        return node

    def add_variation(self, san: str, parent_node: _Node | None = None) -> _Node:
        parent = parent_node or self._selected
        node = self._create_node(parent, san)
        parent.add_child(node)
        self.refresh()
        return node

    def go_to_node(self, node: _Node):
        self._selected = node
        self.refresh()
        self._trigger_callback()

    def go_to_start(self):
        self._selected = self._root
        self.refresh()
        self._trigger_callback()

    def go_to_end(self):
        node = self._root
        while node.node_children:
            node = node.node_children[0]
        self._selected = node
        self.refresh()
        self._trigger_callback()

    def prev(self):
        if self._selected.parent:
            self._selected = self._selected.parent
            self.refresh()
            self._trigger_callback()

    def next(self):
        if self._selected.node_children:
            self._selected = self._selected.node_children[0]
            self.refresh()
            self._trigger_callback()

    def delete_node(self, node: _Node) -> bool:
        """
        Remove node and its subtree from the tree.
        If node is root or not attached -> return False.
        After deletion, selection moves sensibly:
          - if parent exists, select parent
          - else select root
        """
        if node is None or node.is_root():
            return False
        parent = node.parent
        if parent is None:
            return False
        # detach subtree
        parent.remove_child(node)
        # adjust selection
        if self._selected is node or self._is_descendant(self._selected, node):
            self._selected = parent or self._root

        self.refresh()
        self._trigger_callback()
        return True

    def create_board(self) -> chess.Board:
        """
        Create and return a chess.Board representing the position
        at the currently selected node.
        """
        board = chess.Board(fen=self._starting_fen)

        # collect SAN moves from root -> selected
        moves: list[str] = []
        node = self._selected

        while node and not node.is_root():
            if node.san:
                moves.append(node.san)
            node = node.parent

        # apply moves in correct order
        for san in reversed(moves):
            try:
                board.push(board.parse_san(san))
            except Exception as e:
                raise ValueError(f"Failed to rebuild board from SAN '{san}': {e}")

        return board

    # ---------------- PGN loading ----------------
    def load_pgn_from_string(self, pgn_text: str) -> bool:
        """
        Replace current tree with the first game parsed from pgn_text.
        Returns True on success. Preserves node comments and NAGs when available.
        """
        stream = io.StringIO(pgn_text)
        game = chess.pgn.read_game(stream)
        if game is None:
            return False
        self._load_game_tree(game)
        return True

    def load_pgn_from_file(self, filepath: str) -> bool:
        with open(filepath, "r", encoding="utf8") as f:
            game = chess.pgn.read_game(f)
            if game is None:
                return False
            self._load_game_tree(game)
            self._trigger_callback()
            return True

    def _load_game_tree(self, game: chess.pgn.Game):
        # Reset model
        self._root = SanListFrame._Node(san=None, fen=self._starting_fen, move_number=0, color=None, parent=None)
        self._selected = self._root

        board = chess.Board(fen=self._starting_fen)

        def rec(pgn_node: chess.pgn.ChildNode | chess.pgn.Game, parent_node: SanListFrame._Node):
            for var in pgn_node.variations:
                mv = var.move
                san = board.san(mv)
                # create a child for this variation under parent_node
                child = SanListFrame._Node(san=san, fen=None, move_number=0, color=None, parent=parent_node)
                parent_node.add_child(child)

                # push move on board to compute fen and move numbers for this child subtree
                board.push(mv)
                # update child's fen and metadata properly
                prior_turn = not board.turn  # because we've already pushed
                color = "white" if prior_turn == chess.WHITE else "black"
                move_number = board.fullmove_number if color == "white" else board.fullmove_number - 1
                child.fen = board.fen()
                child.color = color
                child.move_number = move_number

                # copy comment and NAGs if present
                try:
                    if getattr(var, "comment", None):
                        child.comment = var.comment
                except Exception:
                    pass
                try:
                    if getattr(var, "nags", None):
                        child.nags = set(var.nags) if var.nags else set()
                except Exception:
                    pass

                # recurse into this node
                rec(var, child)

                # pop after finishing this variation subtree
                board.pop()

        # start from root of PGN (game)
        rec(game, self._root)

        # set selected to end of mainline if exists
        node = self._root
        while node.node_children:
            node = node.node_children[0]
        self._selected = node
        self.refresh()

    # ---------------- Rendering ----------------
    def refresh(self):
        """
        Re-render the whole Text widget representation of the moves.
        We create a unique tag per node (node_{id}) so we can color and bind events.
        Color tags are cached and reused for efficiency.
        """

        self._text.configure(state="normal")
        self._text.delete("1.0", tk.END)

        self._node_tag.clear()
        self._tag_node.clear()

        # Render recursively (inline variations)
        def render_node(node: SanListFrame._Node, is_var: bool = False):

            style = "variation" if is_var else "mainline"

            show_move_number = (
                    node.color == "white"
                    or (is_var and self.is_variation_start(node))
            )

            if show_move_number:
                move_prefix = (
                    f"{node.move_number}. "
                    if node.color == "white"
                    else f"{node.move_number}... "
                )
                self._text.insert(tk.END, move_prefix, style)

            san_text = (node.san or "") + " "
            tag_id = f"node_{id(node)}"
            self._node_tag[node] = tag_id
            self._tag_node[tag_id] = node

            # Decide color tag name (cached) if node.annot_color
            color_tag = None
            if node.annot_color:
                color_hex = node.annot_color.lower()
                color_tag = self._ensure_color_tag(color_hex)

            # insert san with tags (main style + node-specific tag + optional color tag)
            tag_tuple = (style, tag_id) + ((color_tag,) if color_tag else ())
            self._text.insert(tk.END, san_text, tag_tuple)

            # insert NAG symbol (if present) directly after SAN (no space)
            if node.nags:
                # show only single NAG symbol for display if multiple exist: choose any
                symbol = NAG_CODE_TO_SYMBOL.get(next(iter(node.nags)), "")
                if symbol:
                    nag_tag = f"{tag_id}_nag"
                    self._text.insert(tk.END, symbol + " ", ("mainline", nag_tag))
                    # configure nag color (slightly darker) once
                    try:
                        if not self._text.tag_cget(nag_tag, "foreground"):
                            self._text.tag_configure(nag_tag, foreground="#b22222")
                    except tk.TclError:
                        pass

            # insert comment inline if present
            if node.comment:
                comment_tag = f"{tag_id}_comment"
                self._text.insert(tk.END, "{" + node.comment + "} ", ("comment", comment_tag))
                # clickable/editable comment area
                try:
                    self._text.tag_bind(comment_tag, "<Double-Button-1>", lambda e, n=node: self.edit_comment(n))
                except tk.TclError:
                    pass

            # bind left-click select and right-click menu on node tag (do once)
            try:
                self._text.tag_bind(tag_id, "<Button-1>", lambda e, n=node: (self.go_to_node(n), "break"))
                self._text.tag_bind(tag_id, "<Button-3>", lambda e, n=node: self._show_context_menu(e, n))
            except tk.TclError:
                pass

            if not node.node_children:
                return

            main_child = node.node_children[0] if node.node_children else None
            variations = node.node_children[1:] if len(node.node_children) > 1 else []

            # render variations inline: each variation is shown in parentheses as a linear sequence
            for v in variations:
                self._text.insert(tk.END, "(", "paren")
                # walk variation mainline chain
                curr = v
                while True:
                    render_node(curr, is_var=True)
                    if curr.node_children:
                        curr = curr.node_children[0]
                    else:
                        break
                self._text.insert(tk.END, ") ", "paren")

            # continue mainline (do not render if currently rendering a variation)
            if not is_var and main_child:
                render_node(main_child, is_var=False)

        # Start
        render_node(self._root)

        # highlight current
        try:
            self._text.tag_remove("current_bg", "1.0", tk.END)
            if self._selected and not self._selected.is_root():
                tag = self._node_tag.get(self._selected)
                if tag:
                    ranges = self._text.tag_ranges(tag)
                    if ranges:
                        start = ranges[0]
                        end = ranges[1]
                        # apply background highlight tag
                        self._text.tag_add("current_bg", start, end)
                        # also apply bold font for the selection
                        try:
                            b_tag = f"{tag}_bold"
                            if not self._text.tag_cget(b_tag, "font"):
                                self._text.tag_configure(b_tag, font=self._bold_font, foreground=self._color_mainline)
                            self._text.tag_add(b_tag, start, end)
                        except tk.TclError:
                            pass
                        # auto-scroll to show selection
                        try:
                            self._text.see(start)
                        except tk.TclError:
                            pass
        except tk.TclError:
            # widget may be closing
            pass

        try:
            self._text.configure(state="disabled")
        except tk.TclError:
            pass

    # ---------------- Context menu & edit helpers ----------------
    def _show_context_menu(self, event: tk.Event, node: _Node):
        """
        Build and show context menu for a node. Options:
          - Edit comment
          - Delete move
        """
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Edit comment...", command=lambda n=node: self.edit_comment(n))
        menu.add_separator()
        menu.add_command(label="Delete move", command=lambda n=node: self._confirm_delete(n))

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def edit_comment(self, node: _Node):
        """Open a simple dialog to edit the comment for node."""
        initial = node.comment or ""
        new = simpledialog.askstring("Edit comment", "Comment for move:",
                                     initialvalue=initial, parent=self)
        if new is None:
            return
        node.comment = new.strip()
        self.refresh()

    def set_move_color(self, node: _Node, color_hex: str | None):
        """Set or clear the text color for a specific node and refresh view.

        Efficient: uses shared color tags so we don't configure per-node tags repeatedly.
        """
        if color_hex:
            node.annot_color = color_hex.lower()
        else:
            node.annot_color = None
        # ensure tag exists if needed
        if node.annot_color:
            self._ensure_color_tag(node.annot_color)
        # repaint minimal: full refresh (you can optimize to only re-tag ranges if needed)
        self.refresh()

    def _ensure_color_tag(self, hex_color: str) -> str:
        """Return a tag name for this color, creating it if needed."""
        if hex_color in self._color_tag_map:
            return self._color_tag_map[hex_color]
        tag = f"color_{len(self._color_tag_map)}"
        try:
            self._text.tag_configure(tag, foreground=hex_color)
        except tk.TclError:
            # fallback: ignore
            pass
        self._color_tag_map[hex_color] = tag
        return tag

    # ---------------- NAG helpers ----------------
    def set_node_nag_by_symbol(self, node: _Node, symbol: str):
        """Assign NAG to node by symbol (like '!' or '??'). Overwrites existing NAGs for clarity."""
        code = NAG_SYMBOL_TO_CODE.get(symbol)
        if code is None:
            return
        node.nags = {code}
        self.refresh()

    def clear_node_nag(self, node: _Node):
        node.nags.clear()
        self.refresh()

    # ---------------- confirmation ----------------
    def _confirm_delete(self, node: _Node):
        if messagebox.askyesno("Delete move", f"Delete move {node.san}? This will remove its subtree."):
            self.delete_node(node)

    # ---------------- PGN export ----------------
    def build_pgn_game(self) -> chess.pgn.Game:
        """
        Build a chess.pgn.Game object from the internal SanList tree.
        Comments and NAGs are preserved.
        """
        root = self._root
        game = chess.pgn.Game()
        exporter_board = chess.Board(fen=root.fen)

        def rec_build(parent_pgn_node: chess.pgn.ChildNode, san_node: SanListFrame._Node, board: chess.Board):
            for idx, child in enumerate(san_node.node_children):
                try:
                    mv = board.parse_san(child.san)
                except Exception as e:
                    raise ValueError(f"Invalid SAN '{child.san}' relative to FEN {board.fen()}: {e}")
                new_pgn_node = parent_pgn_node.add_variation(mv)
                # comments
                if getattr(child, "comment", None):
                    new_pgn_node.comment = child.comment
                # preserve nags
                if getattr(child, "nags", None):
                    try:
                        new_pgn_node.nags.update(child.nags)
                    except Exception:
                        for code in child.nags:
                            new_pgn_node.nags.add(code)
                # push and recurse
                board.push(mv)
                rec_build(new_pgn_node, child, board)
                board.pop()

        rec_build(game, root, exporter_board)
        return game

    def export_pgn(self, file_path: str | None = None) -> str | None:
        """
        Export current tree to PGN text (including variations/comments/NAGs).
        If file_path is provided, writes to disk and returns None.
        Otherwise returns the PGN as a string.
        """
        try:
            game = self.build_pgn_game()
        except Exception as e:
            messagebox.showerror("Export PGN", f"Failed to build PGN: {e}")
            return None

        exporter = chess.pgn.StringExporter(headers=True, variations=True, comments=True)
        pgn_text = game.accept(exporter)

        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(pgn_text)
            except OSError as e:
                messagebox.showerror("Export PGN", f"Could not write file: {e}")
            return None
        return pgn_text

    def export_pgn_dialog(self):
        p = filedialog.asksaveasfilename(defaultextension=".pgn", filetypes=[("PGN files", "*.pgn")], parent=self)
        if not p:
            return
        self.export_pgn(p)
        messagebox.showinfo("Exported", f"PGN saved to {p}")

    # ---------------- Utility accessors ----------------
    def get_selected_node(self) -> _Node:
        return self._selected

    def set_selected_node(self, node: _Node):
        self.go_to_node(node)

    def find_node_by_san(self, san: str) -> list[_Node]:
        """Return a list of nodes whose SAN matches (search entire tree)."""
        res: list[SanListFrame._Node] = []

        def rec(n: SanListFrame._Node):
            for c in n.node_children:
                if c.san == san:
                    res.append(c)
                rec(c)

        rec(self._root)
        return res

    def _trigger_callback(self):
        if self._on_select and self._selected:
            self._on_select(self._selected, self._selected.fen)
        else:
            self._on_select(self._root, self._root.fen)

# ---------------- Example usage ----------------

if __name__ == "__main__":
    from main.tk_widgets.display_board import DisplayBoard

    root = tk.Tk()
    root.title("SanListWidget Clean")
    root.geometry("900x600")

    display_board = DisplayBoard(root)

    def on_select(node, fen):
        def at_end():
            if node.is_root():return
            display_board.set_fen(node.parent.fen)
            display_board.push(display_board.board.parse_san(node.san))
        display_board.set_fen_with_animation(fen,at_end)
    def on_move(move: chess.Move, board):
        m = board.board.pop()
        san = board.board.san(m)
        board.board.push(m)
        san_list.add_move(san)


    display_board.on_move(on_move)
    display_board.pack(side="left", fill="both", expand=True)


    san_list = SanListFrame(root, starting_fen=chess.STARTING_FEN,
                            on_select=on_select)
    san_list.pack(fill="both", expand=True, padx=10, pady=10, side="right")
    root.bind("<Right>", lambda e: san_list.next())
    root.bind("<Left>", lambda e: san_list.prev())
    root.bind("<Key-s>", lambda e: san_list.export_pgn_dialog())
    root.bind("<Key-o>", lambda e: san_list.load_pgn_from_file(r"C:\Users\PC\Downloads\a.pgn"))
    root.mainloop()
