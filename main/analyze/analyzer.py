#!/usr/bin/env python3
"""
connect_analyzer_to_board.py

דוגמה לחיבור AutoAnalyzer ללוח ProMax/MoveQualityOverlayBoard שלך.

דרישות:
 - python-chess
 - קובץ auto_analyzer.AutoAnalyzer (המחלקה שהוכנה קודם)
 - המודול main.display_board.pro עם MoveQualityOverlayBoard ו־MoveQuality
 - Stockfish קיים ב־ENGINE_PATH
"""

import tkinter as tk
from typing import Optional

from main import DisplayBoard

ENGINE_PATH = "c:/stockfish/stockfish.exe"

from main.tk_widgets.display_board import MoveQuality
from main.analyze.auto_analyzer import AutoAnalyzer, MoveAnalysis


# ---------------------------
# מפה ברירת מחדל (ניתנת לכוונון) שממפה MoveAnalysis -> MoveQuality
# ---------------------------
def map_analysis_to_movequality(ma: MoveAnalysis) -> Optional[MoveQuality]:
    """
    קביעת כללים פשוטה וברורה:
     - delta_cp = best_cp - played_cp (positive => מהלך גרוע יותר)
     - best_gap = how much PV0 better than PV1 (difficulty)
     - sacrifice flag, confidence, iteration
    המפה מחזירה ערך מתוך MoveQuality enum שב־main.display_board.pro.
    ניתן לכוונן את הספים בהתאם לדיוק שתרצה.
    """
    delta = ma.delta_cp
    gap = ma.best_gap
    conf = ma.confidence
    it = ma.iteration

    # ספים (ניתנים לכוונון)
    BLUNDER_T = 400
    MISTAKE_T = 150
    INACCURACY_T = 60

    # האם המהלך שוחק הוא מהלך הטוב ביותר?
    is_best = (ma.played_cp == ma.best_cp) or (abs(delta) <= 8)

    if is_best:
        if gap > 90 and conf > 0.5:
            return MoveQuality.GREAT
        return MoveQuality.BEST

    if delta >= BLUNDER_T:
        return MoveQuality.BLUNDER
    if delta >= MISTAKE_T:
        return MoveQuality.MISTAKE
    if delta >= INACCURACY_T:
        return MoveQuality.INACCURACY

    # פספוס: לא הטוב ביותר אבל הפסד גדול יחסית וההזדמנות היתה משמעותית
    if gap > 120 and delta >= 80:
        return MoveQuality.MISS

    # קטן אבל לא חיובי: טוב / טוב מאוד
    if delta <= 20:
        return MoveQuality.GOOD

    # ברירת מחדל: אינאקורציה / טעות בהתאם לגודל
    if delta <= 50:
        return MoveQuality.INACCURACY
    return MoveQuality.MISTAKE


# ---------------------------
# דוגמת שימוש מלאה
# ---------------------------
def demo():
    root = tk.Tk()
    root.title("AutoAnalyzer + MoveQualityOverlayBoard integration demo")

    board = DisplayBoard(root,
                         legal_moves_circles_color=(180, 255, 200),
                         from_color=(200, 230, 200),
                         to_color=(200, 230, 200))
    board.pack(expand=True, fill="both")

    def on_new_analysis(ma: MoveAnalysis):
        quality = map_analysis_to_movequality(ma)
        print("__")
        board.after(0, lambda: board.set_move_quality(quality))

    analyzer = AutoAnalyzer(
        engine_path=ENGINE_PATH,
        multipv=4,
        on_new_analysis=on_new_analysis,
        time_steps=[0.03, 0.12, 0.5, 2, 5],
    )

    def _on_move_callback(move, board_widget):
        try:
            analyzer.start_analayse(board_widget.clone_board())
        except Exception as e:
            print("Failed to start analysis:", e)

    board.on_move(_on_move_callback)

    # close handler: stop analyzer cleanly then destroy UI
    def on_close():
        analyzer.quit()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    demo()
