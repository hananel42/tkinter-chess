import threading
from typing import List, Tuple

import chess
import chess.engine

from main import DisplayBoard


import threading
from typing import List, Tuple, Optional, Dict

import chess
import chess.engine


class TopMovesTracker:
    """
    מנהל ניתוח מתמשך של Stockfish ושומר את N המהלכים הטובים ביותר לפי multipv,
    עם סינון איכותי (יחסי לעמדה), יציבות (stability) ויכולת לשנות top_n בזמן ריצה.

    Callback יקבל רשימה של (move, score) כשהתוצאות מוכנות: List[Tuple[chess.Move, int]]
    (score ב-centipawns, מנקודת מבט של הצד שמבצע את המהלך — גבוה יותר = טוב יותר).
    """

    def __init__(
        self,
        engine_path: str,
        callback,
        top_n: int = 3,
        min_steps: int = 10,
        max_drop_from_best: int = 120,
        min_stability: int = 2,
    ):
        # engine
        self.engine_path = engine_path
        self.engine = chess.engine.SimpleEngine.popen_uci(engine_path)

        # parameters (thread-safe setters provided)
        self._lock = threading.RLock()
        self.top_n = top_n
        self.min_steps = min_steps  # מספר עדכונים לפני קריאת callback
        self.MAX_DROP_FROM_BEST = max_drop_from_best
        self.MIN_STABILITY = min_stability

        # מצב פנימי
        self.current_board: chess.Board = chess.Board()
        # best_moves: multipv -> (move, score)
        self.best_moves: Dict[int, Tuple[chess.Move, int]] = {}
        self._stability: Dict[int, int] = {}
        self._last_emitted: List[Tuple[chess.Move, int]] = []

        # flags / threading
        self._new_board_event = threading.Event()
        self._stop_event = threading.Event()
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # callback
        self.callback = callback

    # ---------------- lifecycle ----------------

    def start(self) -> None:
        """הפעלת ריצת ניתוח ברקע (אם לא כבר רץ)."""
        with self._lock:
            if self._running:
                return
            self._stop_event.clear()
            self._new_board_event.clear()
            self._thread = threading.Thread(target=self._analyze_loop, daemon=True)
            self._running = True
            self._thread.start()

    def stop(self) -> None:
        """בקש עצירה נקייה של הלולאה (ייחרך עד סיום הלולאה הנוכחית)."""
        self._stop_event.set()
        # Don't join here — caller can if desired.

    def close(self) -> None:
        """עצור וסגור את המנוע."""
        self.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        try:
            self.engine.quit()
        except Exception:
            pass
        with self._lock:
            self._running = False

    # ---------------- configuration setters ----------------

    def set_top_n(self, n: int) -> None:
        """שנה את מספר ההצעות המבוקש (top_n). אם הרצה פעילה — יאופס ויתחיל מחדש."""
        with self._lock:
            if n <= 0:
                raise ValueError("top_n must be >= 1")
            self.top_n = n
            self._new_board_event.set()

    def set_filters(self, max_drop_from_best: Optional[int] = None, min_stability: Optional[int] = None) -> None:
        """עדכן פרמטרי סינון דינמיים."""
        with self._lock:
            if max_drop_from_best is not None:
                self.MAX_DROP_FROM_BEST = max_drop_from_best
            if min_stability is not None:
                self.MIN_STABILITY = min_stability

    def set_min_steps(self, min_steps: int) -> None:
        with self._lock:
            self.min_steps = max(1, int(min_steps))

    # ---------------- board control ----------------

    def set_board(self, board: chess.Board) -> None:
        """
        עדכן את הלוח למצב חדש; יאפס מצבים פנימיים ויעיר את הלולאה להתחיל ניתוח חדש.
        אם המשחק נגמר — התהליך ייעצר.
        """
        with self._lock:
            if board.is_game_over():
                # עצור ניתוח אם המשחק נגמר
                self._stop_event.set()
                return
            self.current_board = board.copy()
            self.best_moves.clear()
            self._stability.clear()
            self._new_board_event.set()
            # אם עדיין לא רץ — התחל
            if not self._running:
                self.start()

    # ---------------- results / utilities ----------------

    def get_top_moves(self) -> List[Tuple[chess.Move, int]]:
        """
        מחזיר רשימה מסוננת וממוינת של מהלכים [(move, score), ...]
        (score מנורמל כבר לנקודת המבט של הצד לשחק).
        """
        with self._lock:
            if not self.best_moves:
                return []
            # קבל רשימה מסוננת לפי drop מהטוב ביותר
            best_score = max(sc for mv, sc in self.best_moves.values())
            filtered = [
                (mv, sc)
                for mv, sc in self.best_moves.values()
                if sc >= best_score - self.MAX_DROP_FROM_BEST
            ]
            # סדר לפי score יורד (הטוב ביותר ראשון) והגבג עד top_n
            filtered.sort(key=lambda x: -x[1])
            return filtered[: self.top_n]

    def _emit_if_changed(self) -> None:
        """קריאה ל־callback רק אם יש שינוי ממשי בתוצאה (בהשוואה למה שנשלח לפני כן)."""
        new = self.get_top_moves()
        # השוואה פשוטה: זוגות מהלך+ציון
        if new and (len(new) != len(self._last_emitted or []) or any(n[0] != l[0] or n[1] != l[1] for n, l in zip(new, self._last_emitted))):
            self._last_emitted = new.copy()
            try:
                self.callback(new)
            except Exception as e:
                print(e)

    # ---------------- core analyze loop ----------------

    def _analyze_loop(self) -> None:
        """
        לולאת ניתוח רציפה. מריצה `engine.analysis()` עם multipv = self.top_n,
        מעדכנת self.best_moves כשהמידע מגיע, ובודקת יציבות/ספים לפני קריאה ל-callback.
        """
        while not self._stop_event.is_set():
            with self._lock:
                board_snapshot = self.current_board.copy()
                top_n = self.top_n
                min_steps = self.min_steps

            # השתמש ב־analysis context של python-chess
            try:
                steps = 0
                # multipv=top_n מבטיח שנקבל עד top_n PVs לכל info
                with self.engine.analysis(board_snapshot, chess.engine.Limit(), multipv=top_n) as analysis:
                    for info in analysis:
                        if self._stop_event.is_set():
                            break
                        if self._new_board_event.is_set():
                            # בקשת עדכון לוח/פרמטרים — נצא לולאה על מנת לאתחל מחדש
                            self._new_board_event.clear()
                            break

                        # process info only if it contains pv & score & multipv
                        try:
                            if "pv" not in info or "multipv" not in info or "score" not in info:
                                continue
                            pv = info["pv"]
                            multipv = int(info["multipv"])
                            score_obj = info["score"]
                        except Exception:
                            continue

                        # המרה לנקודת מבט של הצד לשחק (higher == better for side to move)
                        # score_obj.pov(color) נותן Score מאותו צבע
                        try:
                            pov_score = score_obj.pov(board_snapshot.turn)
                            # נביא int (centipawns) כולל טיפול במצב mate
                            score_cp = pov_score.score(mate_score=100000)
                        except Exception:
                            # שינוי פורמט score — דילג
                            continue
                        if score_cp is None:
                            continue

                        move = pv[0]  # המהלך הראשון ב-pv
                        # עדכון מבנה המידע תוך שימוש ב-lock
                        with self._lock:
                            prev = self.best_moves.get(multipv)
                            # אם אין או אם הציון טוב יותר — נשמור ונעדכן יציבות
                            if prev is None or score_cp > prev[1]:
                                self.best_moves[multipv] = (move, score_cp)
                                self._stability[multipv] = self._stability.get(multipv, 0) + 1

                        # trigger when enough steps collected
                        if steps >= min_steps:
                            # נבדוק יציבות: דרישת מינימום הופעות לכל multipv
                            stable_enough = True
                            with self._lock:
                                # בדוק שלפחות אחד מהמהלכים קיים עם יציבות מספקת
                                has_any = any(s >= self.MIN_STABILITY for s in self._stability.values())
                                if not has_any:
                                    stable_enough = False
                            if stable_enough:
                                # סינון יחסי נעשה ב-get_top_moves()
                                self._emit_if_changed()
                        steps += 1
                        # המשך קבלת info עד שיתבקש לעדכן/להפסיק
                # אם הייתה בקשת עדכון (new_board_event) — נמשיך בלולאה והניתוח יתחיל מחדש
                with self._lock:
                    # אם לא הוגדרה בקשת עדכון — סיימנו ריצה זמנית
                    if not self._new_board_event.is_set():
                        # ננקה יציבות אם רוצים להישאר נקיים בין ריצות
                        self._stability.clear()
                        # שינה לסיום ריצה (הניתוח הסתיים ללא בקשת עדכון)
                        # השאר רץ בבקשה במידה שה־stop לא הוגדר
                        # נעצור בריצה הבאה אם _stop_event נשאר gesetzt
                        pass
            except Exception:
                # אם משהו השתבש עם המנוע — נסגור וננסה לפתוח מחדש
                try:
                    self.engine.quit()
                except Exception:
                    pass
                try:
                    self.engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)
                except Exception:
                    # אם אי אפשר להפעיל את המנוע — המתן ואז ננסה שוב
                    if self._stop_event.is_set():
                        break
                    threading.Event().wait(0.5)

        # יציאה — סיים את מצב הריצה
        with self._lock:
            self._running = False

    # ---------------- convenience / debug ----------------

    def is_running(self) -> bool:
        with self._lock:
            return self._running and (self._thread is not None and self._thread.is_alive())



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
