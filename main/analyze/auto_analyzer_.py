import threading
from typing import List, Tuple

import chess
import chess.engine

from main import DisplayBoard


class TopMovesTracker:
    """
    מנהל ניתוח מתמשך של Stockfish ושומר את N המהלכים הטובים ביותר.
    """

    def __init__(self, engine_path: str, callback, top_n: int = 3, min_steps: float = 10):
        self.engine = chess.engine.SimpleEngine.popen_uci(engine_path)
        self.top_n = top_n
        self.min_steps = min_steps
        self.current_board = chess.Board()
        self.best_moves = {}  # dict: multipv -> (move, score)
        self.last_best = {}
        self.new_flag = False
        self.stop_flag = False
        self.running_flag = False
        self.callback = callback

    def _trigger_callback(self):
        if set([i for i, j in self.get_top_moves()]) != set([i for i, j in self.last_best]):
            self.last_best = self.get_top_moves()
            self.callback(self.last_best)

    def set_board(self, board: chess.Board):
        """עדכן את הלוח למצב חדש."""
        if board.is_game_over():
            self.stop_flag = True
            return
        self.current_board = board.copy()
        self.best_moves = {}  # אפס את המהלכים הקודמים
        self.new_flag = True
        if not self.running_flag:
            self.start()

    def analyze(self):
        """התחל ניתוח מתמשך של המהלכים הטובים ביותר."""
        # multipv=self.top_n כדי לקבל N מהלכים טובים בו זמנית
        self.running_flag = True
        steps = 0
        with self.engine.analysis(self.current_board, chess.engine.Limit(), multipv=self.top_n) as info_stream:
            for info in info_stream:

                if self.new_flag or self.stop_flag:
                    self.stop_flag = False
                    break
                if 'pv' in info and 'multipv' in info and 'score' in info:
                    mv = info['pv'][0]  # המהלך הראשון של המסלול
                    multipv = info['multipv']
                    # המרת score לנקודות חומר (Cp) תמיד מנקודת מבט הלבן
                    score = info['score'].white().score(mate_score=100000)
                    if multipv in self.best_moves.keys():
                        if self.best_moves[multipv][1] < score:
                            self.best_moves[multipv] = self.best_moves[multipv] = (mv, score)
                    else:
                        self.best_moves[multipv] = (mv, score)
                if steps == self.min_steps:
                    self._trigger_callback()
                else:
                    steps += 1
        if self.new_flag:
            self.new_flag = False
            self.analyze()
        else:
            self.running_flag = False

    def get_top_moves(self) -> List[Tuple[chess.Move, int]]:
        """
        מחזיר רשימה של N המהלכים הטובים ביותר:
        [(מהלך, ציון), ...] לפי multipv.
        """
        # ממיין לפי multipv
        return [self.best_moves[i] for i in sorted(self.best_moves.keys())]

    def start(self):
        threading.Thread(target=self.analyze).start()

    def close(self):
        """סגור את המנוע."""
        self.engine.quit()


if __name__ == '__main__':

    import tkinter as tk

    ENGINE_PATH = "c:/stockfish/stockfish.exe"

    root = tk.Tk()


    def on_move(move, board_):
        board.clear_board_draw()
        tracker.set_board(board.clone_board())


    board = DisplayBoard(root, input_callback=on_move, allow_drawing=False)
    board.pack()


    def on_analyze(bests):
        if not bests: return
        board.clear_board_draw()
        for (i, j) in bests[1:]:
            board.draw_arrow(*board.row_col_of(i.from_square), *board.row_col_of(i.to_square), (200, 200, 230), 5,
                             delete=False)
        board.draw_arrow(*board.row_col_of(bests[0][0].from_square), *board.row_col_of(bests[0][0].to_square),
                         (100, 100, 255), 5, delete=False)
        board.safe_redraw()


    tracker = TopMovesTracker(ENGINE_PATH, on_analyze, top_n=3, min_steps=1)
    threading.Thread(target=tracker.analyze).start()
    root.mainloop()
    tracker.close()
