import random
import tkinter as tk
from main.analyze.analyzer import map_analysis_to_movequality, ENGINE_PATH
from main.analyze.auto_analyzer import AutoAnalyzer, MoveAnalysis
from main.analyze.auto_analyzer_ import TopMovesTracker
from main.analyze.opening import OpeningManager
from main.tk_widgets.display_board import DisplayBoard, MoveQuality
from main.tk_widgets.san_list import SanListFrame


def rgb_to_hex(col):
    """
    Convert an RGB color tuple to its hexadecimal representation.

    Parameters:
    col (tuple[int, int, int]): An RGB color tuple containing three integers representing the red, green, and blue components.

    Returns:
    str: The hexadecimal string representation of the input RGB color.
    """
    if isinstance(col, str):
        return col
    r, g, b = col
    return f"#{r:02x}{g:02x}{b:02x}"
def on_analyze(bests):
    """
    Analyzes a list of best moves and updates the game board accordingly.

    Parameters:
    bests (list): A list of move objects containing from_square, to_square attributes.

    Summary:
    This function takes a list of move objects as input and processes them to draw arrows on the game board.
    If no moves are provided, it returns immediately. The function iterates over all best moves except for the
    first one, drawing an arrow between each pair of squares specified in the move objects. The first move
    is drawn with a different color to distinguish it from subsequent moves.

    The function then redraws the safe area of the board using `board.safe_redraw()` to ensure that any pending changes
    are reflected on the game board.
    """
    if not bests: return
    board.system_arrows = []

    for (i, j) in bests[1:]:
        board.draw_arrow(*board.row_col_of(i.from_square), *board.row_col_of(i.to_square), "#88f", 5, delete=False,
                         is_user=False)
    board.draw_arrow(*board.row_col_of(bests[0][0].from_square), *board.row_col_of(bests[0][0].to_square),
                     (80, 80, 180), 5, delete=False, is_user=False)
    board.safe_redraw()
def on_select(node: SanListFrame._Node, fen):
    board.stop_animation()
    def a():
        tracker.set_board(board.clone_board())
        if node.parent:
            board.board.set_fen(node.parent.fen)
            move = board.board.parse_san(node.san)
            board.push(move,True)
    board.set_fen_with_animation(fen, a)
    board.clear_user_draw()
    board.system_arrows = []
def on_new_analysis(ma: MoveAnalysis):
    quality = map_analysis_to_movequality(ma)
    san_list.after(0, lambda: san_list.set_move_color(san_list.get_selected_node(),
                                                      rgb_to_hex(board.move_quality_colors[quality])))
    board.after(0, board.set_move_quality(quality))
def _on_move_callback(move, board_widget: DisplayBoard):
    board_widget.clear_last_move_quality()
    c = board_widget.clone_board()
    c.pop()
    san = c.san(move)
    if san_list.get_selected_node().fen == c.fen():
        san_list.add_move(san)
    c.push(move)
    if info := om.opening_from_board(board_widget.board):
        root.title(info.name)
        board.after(0, lambda: board.set_move_quality(MoveQuality.BOOK))
        san_list.after(0, lambda: san_list.set_move_color(san_list.get_selected_node(),
                                                          rgb_to_hex(board.move_quality_colors[MoveQuality.BOOK])))
    else:
        analyzer.start_analayse(c)
    board.system_arrows = []
    tracker.set_board(board.clone_board())
def on_close():
    """
    This function performs the following actions when called:

    - Calls the `quit` method on the `analyzer` object.
    - Closes the `tracker` object.
    - Destroys the main window `root`.

    It is intended to be used as a handler for closing events, such as when the user clicks
    the close button of a GUI application or when certain conditions are met that require
    the application to terminate gracefully.
    """
    analyzer.quit()
    tracker.close()
    root.destroy()
def export_svg() -> None:
    """
    Export the current game board state to an SVG file.

    This function is triggered when the user clicks the "Export SVG" button. It hides the main window, prompts for a save location,
    generates the SVG content of the current board state, and writes it to a file. The function then deactivates the main window
    and prints a success message.

    Returns:
        None: This function does not return any value.
    """

    root.withdraw()  # Hide the main window
    file_path = tk.filedialog.asksaveasfilename(defaultextension=".svg",
                                                filetypes=[("SVG files", "*.svg"), ("All files", "*.*")])

    if file_path:
        svg_content = board.generate_svg()
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(svg_content)
        print(f"SVG exported to {file_path}")
    root.deiconify()
def export_pgn() -> None:
    """
    Export the current game board state to an SVG file.

    This function is triggered when the user clicks the "Export SVG" button. It hides the main window, prompts for a save location,
    generates the SVG content of the current board state, and writes it to a file. The function then deactivates the main window
    and prints a success message.

    Returns:
        None: This function does not return any value.
    """

    root.withdraw()  # Hide the main window
    file_path = tk.filedialog.asksaveasfilename(defaultextension=".svg",
                                                filetypes=[("PGN files", "*.pgn"), ("All files", "*.*")])

    if file_path:
        san_list.export_pgn(file_path)
        print(f"PGN exported to {file_path}")
    root.deiconify()
def random_move(*e):
    """
    Perform a random move on the current chessboard.

    This function stops any ongoing animations, generates a list of all possible legal moves,
    and selects one at random to start an animation for that move if there are any legal moves available.
    """
    board.stop_animation()
    legal_moves = list(board.legal_moves)
    if not legal_moves: return
    board.start_move_animation(random.choice(legal_moves))

root = tk.Tk()
root.title("AutoAnalyzer + Board integration demo")
root.configure(background="#fcc")
right = tk.Frame(root, bg="#ccf")
right.pack(side="right",fill="both")

board = DisplayBoard(root, animation_fps=120)
board.configure(background="#fcc")
board.pack(expand=True, fill="both",side="left",padx=10, pady=10)
tracker = TopMovesTracker(ENGINE_PATH, on_analyze, top_n=3, min_steps=1)
board.after(0, tracker.start)
san_list = SanListFrame(right, on_select=on_select)
san_list.pack(expand=True, fill="y")

board.on_move(_on_move_callback)


root.bind("<Key-r>", random_move)
root.protocol("WM_DELETE_WINDOW", on_close)
root.bind("<Right>", lambda e: san_list.next())
root.bind("<Left>", lambda e: san_list.prev())
tk.Button(right, text="Export SVG", command=export_svg,relief="ridge", bd=3).pack(fill="x",padx=10,pady=10)
tk.Button(right, text="Export PGN", command=export_pgn,relief="ridge", bd=3).pack(fill="x",padx=10,pady=10)
tk.Button(right, text="<", command=san_list.prev, relief="ridge", bd=3).pack(side="left", fill="both",expand=True,padx=10,pady=10)
tk.Button(right, text=">", command=san_list.next, relief="ridge", bd=3).pack(side="right", fill="both",expand=True,padx=10,pady=10)



om = OpeningManager()
om.load_eco_pgn("analyze/eco.pgn")
analyzer = AutoAnalyzer(
    engine_path=ENGINE_PATH,
    multipv=4,
    on_new_analysis=on_new_analysis,
    time_steps=[0.003, 0.012, 0.05, 0.2, 0.5, 2, 5],
)



root.mainloop()
