#!/usr/bin/env python3
"""
map_analysis_to_move_quality: deterministic mapper that attempts to match Lichess-style
grading (BEST/GREAT/GOOD/INACCURACY/MISTAKE/BLUNDER/MISS) given MoveAnalysis produced
by auto_analyzer.

Strategy & notes:
 - Uses centipawn deltas (best_cp - played_cp) as the primary signal
 - Explicit mate handling (MATE_SENTINEL)
 - Uses best_gap to detect MISS (best >> second)
 - Uses win_probability differences as a secondary check for edge cases
 - Thresholds tuned to be similar to common practice and to Lichess-style UX
"""

from typing import Optional

from main.tk_widgets.display_board import MoveQuality
from main.analyze.auto_analyzer import MoveAnalysis

# thresholds (centipawns)
MATE_SENTINEL = 100_000

VERY_SMALL_DELTA = 8      # essentially no difference
SMALL_DELTA = 40          # still very good
INACCURACY_T = 60
MISTAKE_T = 150
BLUNDER_T = 400

# miss detection thresholds
MISS_GAP_THRESHOLD = 150
MISS_DELTA_THRESHOLD = 80

def _safe_int(x: Optional[int], default: int = 0) -> int:
    try:
        return int(x) if x is not None else default
    except Exception:
        return default

def _is_mate(cp: int) -> bool:
    return abs(cp) >= MATE_SENTINEL

def map_analysis_to_move_quality(ma: Optional[MoveAnalysis]) -> Optional[MoveQuality]:
    """
    Map MoveAnalysis -> MoveQuality.
    Returns None if ma is None.
    """
    if ma is None:
        return None

    best_cp = _safe_int(ma.best_cp)
    played_cp = _safe_int(ma.played_cp)
    second_cp = _safe_int(getattr(ma, "second_cp", None))
    best_gap = _safe_int(getattr(ma, "best_gap", best_cp - second_cp))

    delta = max(0, best_cp - played_cp)  # how much worse played is vs best

    best_is_mate = _is_mate(best_cp)
    played_is_mate = _is_mate(played_cp)

    # 1) Mate handling (explicit)
    if best_is_mate:
        # if best forces mate but played does not -> BLUNDER
        if not played_is_mate:
            return MoveQuality.BLUNDER
        # both indicate mate (or played preserves mate)
        if ma.is_best or delta <= VERY_SMALL_DELTA:
            return MoveQuality.BEST
        if delta <= MISTAKE_T:
            return MoveQuality.MISTAKE
        return MoveQuality.BLUNDER

    # 2) exact best or nearly exact
    if ma.is_best:
        return MoveQuality.BEST

    if delta <= VERY_SMALL_DELTA:
        # tiny difference -> GREAT (unless second line is equally strong, then BEST)
        return MoveQuality.GREAT

    if delta <= SMALL_DELTA:
        return MoveQuality.GOOD

    # 3) Miss detection: best unique and played far below best
    if best_gap >= MISS_GAP_THRESHOLD and delta >= MISS_DELTA_THRESHOLD:
        return MoveQuality.MISS

    # 4) conventional buckets
    if delta >= BLUNDER_T:
        return MoveQuality.BLUNDER
    if delta >= MISTAKE_T:
        return MoveQuality.MISTAKE
    if delta >= INACCURACY_T:
        return MoveQuality.INACCURACY

    # 5) secondary probability check (edge cases)
    win_best = getattr(ma, "win_probability_best", 0.0) or 0.0
    win_played = getattr(ma, "win_probability_played", 0.0) or 0.0
    win_diff = win_best - win_played

    if win_diff >= 0.30 and delta >= 40:
        return MoveQuality.MISTAKE
    if win_diff >= 0.18 and delta >= 20:
        return MoveQuality.INACCURACY

    # fallback
    return MoveQuality.GOOD
