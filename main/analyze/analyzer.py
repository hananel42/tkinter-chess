#!/usr/bin/env python3
from typing import Optional
from main.tk_widgets.display_board import MoveQuality
from main.analyze.auto_analyzer import MoveAnalysis

def map_analysis_to_move_quality(ma: Optional[MoveAnalysis]) -> Optional[MoveQuality]:
    """
    Map a MoveAnalysis object to MoveQuality with proper handling of mate positions.
    In mate positions, best_cp is usually 0, so we cannot rely on played_cp == best_cp.
    """

    if ma is None:
        return None

    delta = getattr(ma, "delta_cp", 0) or 0
    gap = getattr(ma, "best_gap", 0) or 0
    conf = getattr(ma, "confidence", 0.0) or 0.0
    iteration = getattr(ma, "iteration", 0) or 0
    is_mate = getattr(ma, "is_mate", False)

    # Thresholds for standard evaluation (centipawns)
    BLUNDER_T = 400
    MISTAKE_T = 150
    INACCURACY_T = 60

    # --- 1. Mate handling ---
    if is_mate:
        # small delta = move keeps mate line
        if abs(delta) <= 8:
            if gap > 100 and conf > 0.5 and iteration >= 20:
                return MoveQuality.GREAT
            return MoveQuality.BEST
        # significant deviation from mate line
        if delta >= 300:
            return MoveQuality.BLUNDER
        if delta >= 100:
            return MoveQuality.MISTAKE
        return MoveQuality.INACCURACY

    # --- 2. Determine if this is effectively the best move ---
    played_cp = getattr(ma, "played_cp", None)
    best_cp = getattr(ma, "best_cp", None)
    is_best = False
    if played_cp is not None and best_cp is not None:
        # for non-mate: either exact equality or very small delta
        is_best = (played_cp == best_cp) or (abs(delta) <= 8)

    if is_best:
        if gap > 90 and conf > 0.5:
            return MoveQuality.GREAT
        return MoveQuality.BEST

    # --- 3. Miss condition: large gap + notable delta ---
    if gap > 120 and delta >= 80:
        return MoveQuality.MISS

    # --- 4. Delta-based evaluation ---
    if delta >= BLUNDER_T:
        return MoveQuality.BLUNDER
    if delta >= MISTAKE_T:
        return MoveQuality.MISTAKE
    if delta >= INACCURACY_T:
        return MoveQuality.INACCURACY

    # --- 5. Small deltas ---
    if delta <= 20:
        return MoveQuality.GOOD
    if delta <= 50:
        return MoveQuality.INACCURACY

    # fallback
    return MoveQuality.MISTAKE
