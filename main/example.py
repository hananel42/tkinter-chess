import random
import tkinter as tk
import chess
from main.tk_widgets.display_board import DisplayBoard
from main.tk_widgets.san_list import SanListFrame
from main.opening.opening_explorer_widget import OpeningExplorerWidget


def rgb_to_hex(col):
    if isinstance(col, str):
        return col
    r, g, b = col
    return f"#{r:02x}{g:02x}{b:02x}"


# noinspection PyTypeChecker
class ChessAnalyzerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AutoAnalyzer + Board integration demo")
        self.root.configure(background="#fcc")
        self.root.geometry("1300x800")
        self.colors = ["#f00", "#0f0", "#00f", "#ff0", "#0ff", "#f0f"]
        self.colors_index = 0


        self._build_ui()
        self._init_logic()
        self._bind_events()

    # ---------- UI ----------

    def _build_ui(self):
        # === Right panel root ===
        self.right = tk.Frame(self.root, bg="#ccf")
        self.right.pack(side="right", fill="y")

        # === Board ===
        self.board = DisplayBoard(self.root, animation_fps=120)
        self.board.configure(background="#fcc")
        self.board.pack(expand=True, fill="both", side="left", padx=10, pady=10)

        # === Moves list (top, stretch) ===
        moves_frame = tk.Frame(self.right, bg="#ccf")
        moves_frame.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        self.san_list = SanListFrame(moves_frame, on_select=self.on_select)
        self.san_list.pack(fill="both",expand=True,)

        # === Navigation + export (middle, compact) ===
        controls_frame = tk.Frame(self.right, bg="#ccf")
        controls_frame.pack(fill="x", padx=8, pady=4)
        opening_frame = tk.Frame(self.right, bg="#ccf")
        opening_frame.pack(fill="x", padx=8, pady=4)

        self.o_m = OpeningExplorerWidget(opening_frame,"book.tsv",move_callback=self._on_ex_m)
        self.o_m.pack(fill="x", padx=8, pady=4)
        tk.Button(
            controls_frame, text="Export SVG",
            command=self.export_svg, relief="ridge", bd=3
        ).pack(fill="x", pady=2)

        tk.Button(
            controls_frame, text="Export PGN",
            command=self.export_pgn, relief="ridge", bd=3
        ).pack(fill="x", pady=2)

        nav_frame = tk.Frame(controls_frame, bg="#ccf")
        nav_frame.pack(fill="x", pady=(6, 2))

        tk.Button(
            nav_frame, text="◀",
            command=self.san_list.prev, relief="ridge", bd=3
        ).pack(side="left", expand=True, fill="x", padx=(0, 4))

        tk.Button(
            nav_frame, text="▶",
            command=self.san_list.next, relief="ridge", bd=3
        ).pack(side="right", expand=True, fill="x", padx=(4, 0))


    # ---------- Logic ----------
    def _on_ex_m(self, e):
        move = chess.Move.from_uci(e)
        if move in self.board.legal_moves:
            self.board.start_move_animation(move)
    def _init_logic(self):
        self.board.on_move(self.on_move)

    def on_select(self, node, fen):
        self.board.stop_animation()

        def apply():
            self.o_m.last_opening_name = None
            self.o_m.set_fen(self.board.fen())
            if node.parent:
                self.board.board.set_fen(node.parent.fen)
                move = self.board.board.parse_san(node.san)
                self.board.push(move, True)

        self.board.set_fen_with_animation(fen, apply)
        self.board.clear_user_draw()
        self.board.system_arrows = []



    def on_move(self, move, board_widget: DisplayBoard):
        board_widget.clear_last_move_quality()
        c = board_widget.clone_board()
        c.pop()
        san = c.san(move)
        self.o_m.set_fen(board_widget.fen())
        if self.san_list.get_selected_node().fen == c.fen():
            self.san_list.add_move(san)

    def random_move(self, *_):
        self.board.stop_animation()
        moves = list(self.board.legal_moves)
        if moves:
            self.board.start_move_animation(random.choice(moves))

    def next_color(self):
        self.colors_index = (self.colors_index + 1) % len(self.colors)
        self.board.arrow_color = self.board.circle_color = self.colors[self.colors_index]

    def export_svg(self):
        self.root.withdraw()
        path = tk.filedialog.asksaveasfilename(defaultextension=".svg")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.board.generate_svg())
        self.root.deiconify()

    def export_pgn(self):
        self.root.withdraw()
        path = tk.filedialog.asksaveasfilename(defaultextension=".pgn")
        if path:
            self.san_list.export_pgn(path)
        self.root.deiconify()

    def on_close(self):
        print("goodbye")
        self.root.destroy()

    # ---------- Bindings ----------

    def _bind_events(self):
        self.root.bind("<Key-r>", self.random_move)
        self.root.bind("<Key-c>", lambda e: self.next_color())
        self.root.bind("<Key-f>", lambda e: self.board.flip_board())
        self.root.bind("<Right>", lambda e: self.san_list.next())
        self.root.bind("<Left>", lambda e: self.san_list.prev())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- Run ----------

    def run(self):
        """
        Run the GUI application by entering the main event loop of Tkinter.

        This method initializes and starts the main window's event loop, allowing it to display and respond to user interactions.
        """
        self.root.mainloop()


if __name__ == "__main__":
    ChessAnalyzerApp().run()

