import random
import tkinter as tk

import chess

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


root = tk.Tk()
root.title("AutoAnalyzer + MoveQualityOverlayBoard integration demo")


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


def on_select(node: SanListFrame._Node, fen, history):
    """
    This function handles the selection event for a chess node in a game.

    Parameters:
    - node (SanListFrame._Node): The selected chess node from a list frame.
    - fen (str): The Forsyth-Edwards Notation (FEN) string representing the current board state.
    - history (List[Dict[str, Any]]): A list of dictionaries containing past game moves and their corresponding FEN strings.

    This function performs the following actions:
    1. Stops any running animations on the chessboard.
    2. If there is no history or if the current board position matches the last recorded position,
       it sets the FEN to the selected fen and animates the transition to this position.
    3. If the current board position does not match the last recorded position but matches the previous
       position in the history, it starts a move animation for the last move.
    4. If the current board position does not match either the selected fen or the last recorded position,
       it sets the FEN to the last recorded FEN before the move and pushes the last move onto the chessboard without animation.
    5. Clears any user drawings from the chessboard.
    6. Resets the system arrows on the chessboard.
    7. Updates the tracker's board state to the cloned version of the current chessboard.
    """
    board.stop_animation()
    if not history:
        board.set_fen_with_animation(fen, lambda: tracker.set_board(board.clone_board()))

    elif board.fen() == history[-1]["fen_before"]:
        board.start_move_animation(chess.Move.from_uci(history[-1]["uci"]))
    else:
        board.set_fen(history[-1]["fen_before"])
        board.push(chess.Move.from_uci(history[-1]["uci"]), True)
    board.clear_user_draw()
    board.system_arrows = []
    tracker.set_board(board.clone_board())


def on_new_analysis(ma: MoveAnalysis):
    """
    Handle the new analysis for a given MoveAnalysis object.

    Parameters:
        ma (MoveAnalysis): The MoveAnalysis object containing the quality and move information.

    Summary:
        This method is triggered when a new analysis is available. It maps the analysis result to a move quality,
        updates the visual color of the selected node in the SAN list, and sets the move quality for the board.

    Note:
        This function assumes that there are helper functions `map_analysis_to_movequality`, `san_list.after`,
        `rgb_to_hex`, and `board.move_quality_colors` defined elsewhere.
    """
    quality = map_analysis_to_movequality(ma)
    san_list.after(0, lambda: san_list.set_move_color(san_list.get_selected_node(),
                                                      rgb_to_hex(board.move_quality_colors[quality])))
    board.after(0, board.set_move_quality(quality))


def _on_move_callback(move, board_widget: DisplayBoard):
    """
    Handles the callback for a move event in the display board.

    Args:
        move (tuple): The coordinates of the move.
        board_widget (DisplayBoard): The display board widget associated with the move.

    Side effects:
        - Updates the san_list to include the new move if it is selected.
        - Adds the move to the cloned board.
        - Analyzes the board and updates the title and move quality.
        - Resets the system_arrows on the board.
        - Updates the tracker's board state.
    """
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


board = DisplayBoard(root, animation_fps=120)
board.pack(expand=True, fill="both", side="left")
tracker = TopMovesTracker(ENGINE_PATH, on_analyze, top_n=3, min_steps=1)
board.after(0, tracker.start)
san_list = SanListFrame(root, on_select=on_select)
san_list.pack(expand=True, fill="y", side="right")

board.on_move(_on_move_callback)
om = OpeningManager()
om.load_eco_pgn("analyze/eco.pgn")
analyzer = AutoAnalyzer(
    engine_path=ENGINE_PATH,
    multipv=4,
    on_new_analysis=on_new_analysis,
    time_steps=[0.003, 0.012, 0.05, 0.2, 0.5, 2, 5],
)


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


root.bind("<Key-r>", random_move)
# root.bind("<Return>",lambda e:san_list.go_to_start())
root.protocol("WM_DELETE_WINDOW", on_close)
root.bind("<Right>", lambda e: san_list.next())
root.bind("<Left>", lambda e: san_list.prev())
tk.Button(board, text="<", command=san_list.prev, bg="#ccc", relief="ridge", bd=3).pack(side="left", fill="both",
                                                                                        expand=True)
tk.Button(board, text=">", command=san_list.next, bg="#ccc", relief="ridge", bd=3).pack(side="right", fill="both",
                                                                                        expand=True)


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


# Create the export button
export_button = tk.Button(root, text="Export SVG", command=export_svg)
export_button.pack(side="bottom")
root.mainloop()
