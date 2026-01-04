import random
import tkinter as tk

from main.analyze.analyzer import map_analysis_to_movequality, ENGINE_PATH
from main.analyze.auto_analyzer import AutoAnalyzer, MoveAnalysis
from main.analyze.auto_analyzer_ import TopMovesTracker
from main.analyze.opening import OpeningManager
from main.tk_widgets.display_board import DisplayBoard, MoveQuality
from main.tk_widgets.san_list import SanListFrame


def rgb_to_hex(col):
    if isinstance(col, str):
        return col
    r, g, b = col
    return f"#{r:02x}{g:02x}{b:02x}"


class ChessAnalyzerApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AutoAnalyzer + Board integration demo")
        self.root.configure(background="#fcc")

        self.colors = ["#f00", "#0f0", "#00f", "#ff0", "#0ff", "#f0f"]
        self.colors_index = 0

        self.engine_enabled = tk.BooleanVar(self.root,True)
        self.tracker_enabled = tk.BooleanVar(self.root,True)


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
        self.san_list.pack(fill="both", expand=True)

        # === Navigation + export (middle, compact) ===
        controls_frame = tk.Frame(self.right, bg="#ccf")
        controls_frame.pack(fill="x", padx=8, pady=4)

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

        # === Engine controls (bottom, fixed) ===
        engine_frame = tk.LabelFrame(
            self.right, text="Engine", bg="#ccf", labelanchor="n"
        )
        engine_frame.pack(fill="x", padx=8, pady=(6, 8))

        tk.Checkbutton(
            engine_frame,
            text="Analysis",
            variable=self.engine_enabled,
            command=self.toggle_analysis,
            bg="#ccf"
        ).pack(anchor="w", pady=2)

        tk.Button(
            engine_frame,
            text="Re-analyze position ↺",
            command=self.reanalyze,
            relief="ridge", bd=3
        ).pack(fill="x", pady=4)

        tk.Checkbutton(
            engine_frame,
            text="Show best moves",
            variable=self.tracker_enabled,
            command=self.toggle_tracker,
            bg="#ccf"
        ).pack(anchor="w", pady=2)

    # ---------- Logic ----------

    def _init_logic(self):
        self.tracker = TopMovesTracker(
            ENGINE_PATH,
            self.on_analyze,
            top_n=3,
            min_steps=1
        )
        self.board.after(0, self.tracker.start)

        self.om = OpeningManager()
        self.om.load_eco_pgn("analyze/eco.pgn")

        self.analyzer = AutoAnalyzer(
            engine_path=ENGINE_PATH,
            multipv=4,
            on_new_analysis=self.on_new_analysis,
            time_steps=[0.003, 0.012, 0.05, 0.2, 0.5, 2, 5],
        )

        self.board.on_move(self.on_move)

    # ---------- Engine control ----------

    def toggle_analysis(self):
        if self.engine_enabled.get():
            if self.board.board.move_stack:
                self.on_move(self.board.board.peek(),self.board)
        else:
            self.board.clear_last_move_quality()
            self.analyzer.stop_analyze()
            self.board.safe_redraw()

    def reanalyze(self):
        self.board.clear_last_move_quality()
        if self.board.board.move_stack:
            self.on_move(self.board.board.peek(), self.board)

    def toggle_tracker(self):
        if self.tracker_enabled.get():
            self.tracker.set_board(self.board.clone_board())
        else:
            self.board.system_arrows = []
            self.board.safe_redraw()


    # ---------- Callbacks ----------

    def on_analyze(self, bests):
        if not self.tracker_enabled.get():
            return

        if not bests:
            return

        self.board.system_arrows = []

        for move, _ in bests[1:]:
            self.board.draw_arrow(
                *self.board.row_col_of(move.from_square),
                *self.board.row_col_of(move.to_square),
                "#88f", 5, delete=False, is_user=False
            )

        best_move = bests[0][0]
        self.board.draw_arrow(
            *self.board.row_col_of(best_move.from_square),
            *self.board.row_col_of(best_move.to_square),
            (80, 80, 180), 5, delete=False, is_user=False
        )

        self.board.safe_redraw()

    def on_select(self, node: SanListFrame._Node, fen):
        self.board.stop_animation()

        def apply():
            self.tracker.set_board(self.board.clone_board())
            if node.parent:
                self.board.board.set_fen(node.parent.fen)
                move = self.board.board.parse_san(node.san)
                self.board.push(move, True)

        self.board.set_fen_with_animation(fen, apply)
        self.board.clear_user_draw()
        self.board.system_arrows = []

    def on_new_analysis(self, ma: MoveAnalysis):
        quality = map_analysis_to_movequality(ma)

        self.san_list.after(
            0,
            lambda: self.san_list.set_move_color(
                self.san_list.get_selected_node(),
                rgb_to_hex(self.board.move_quality_colors[quality])
            )
        )

        self.board.after(0, lambda: self.board.set_move_quality(quality))

    def on_move(self, move, board_widget: DisplayBoard):
        board_widget.clear_last_move_quality()

        c = board_widget.clone_board()
        c.pop()
        san = c.san(move)

        if self.san_list.get_selected_node().fen == c.fen():
            self.san_list.add_move(san)

        c.push(move)
        self.board.system_arrows = []
        self.tracker.set_board(self.board.clone_board())
        if not self.engine_enabled.get():return
        if info := self.om.opening_from_board(board_widget.board):
            self.root.title(info.name)
            self.board.set_move_quality(MoveQuality.BOOK)
            self.san_list.set_move_color(
                self.san_list.get_selected_node(),
                rgb_to_hex(self.board.move_quality_colors[MoveQuality.BOOK])
            )
        else:
           self.analyzer.start_analayse(c)




    # ---------- Utilities ----------

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
        self.analyzer.quit()
        self.tracker.close()
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
        self.root.mainloop()


if __name__ == "__main__":
    ChessAnalyzerApp().run()
