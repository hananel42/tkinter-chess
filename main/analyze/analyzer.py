#!/usr/bin/env python3
"""
Robust mapper from MoveAnalysis -> MoveQuality.

This replaces the previous brittle heuristics with clearer, better-tested
thresholds and explicit mate handling. The function tolerates missing fields
and uses sensible fallbacks.

Expectations:
 - MoveAnalysis.best_cp and .played_cp are centipawn-like integers.
 - For mate positions these may use large sentinels (e.g. +/-100_000).
 - MoveQuality enum should contain: BEST, GREAT, GOOD, INACCURACY, MISTAKE,
   BLUNDER, MISS (function uses these names).
"""
from typing import Optional

from main.tk_widgets.display_board import MoveQuality
from main.analyze.auto_analyzer import MoveAnalysis


# Thresholds (centipawns)
BLUNDER_T = 400
MISTAKE_T = 150
INACCURACY_T = 60
SMALL_DELTA_VERY_GOOD = 8    # essentially equal to best
SMALL_DELTA_GOOD = 40        # still a good move
MISS_GAP_THRESHOLD = 150    # large uniqueness gap between best and runner-up
MISS_DELTA_THRESHOLD = 80   # and significant delta
GREAT_GAP_THRESHOLD = 90

MATE_SENTINEL = 100_000


def _safe_int(x: Optional[int], default: int = 0) -> int:
    try:
        return int(x) if x is not None else default
    except Exception:
        return default


def map_analysis_to_move_quality(ma: Optional[MoveAnalysis]) -> Optional[MoveQuality]:
    """Map a MoveAnalysis -> MoveQuality with careful mate handling.

    Returns None if ma is None.

    Heuristics summary:
      * If the position is a mate-line (best indicates mate):
         - if played preserves mate (tiny delta) -> BEST or GREAT (if unique)
         - if played drops mate -> BLUNDER
         - intermediate degradations -> MISTAKE/INACCURACY
      * For regular positions use delta (best_cp - played_cp) with thresholds
        and treat very small deltas as BEST/GREAT. If the best move is highly
        unique (large best_gap) prefer GREAT when delta is tiny.
      * If best is much better than 2nd (big best_gap) and played move has
        sizeable delta, mark as MISS (special severe oversight).
    """

    if ma is None:
        return None

    # Extract safely
    best_cp = _safe_int(getattr(ma, "best_cp", None))
    played_cp = getattr(ma, "played_cp", None)
    played_cp = _safe_int(played_cp, default=None) if played_cp is not None else None
    # delta is expected to be best_cp - played_cp; but tolerate missing or inverted
    raw_delta = getattr(ma, "delta_cp", None)
    if raw_delta is None:
        # try to compute if possible
        if played_cp is not None:
            delta = max(0, best_cp - played_cp)
        else:
            delta = 0
    else:
        try:
            delta = int(raw_delta)
            # we only care about positive deltas (how much worse played is vs best)
            if delta < 0:
                # negative means played better than what we recorded as 'best' -> treat as tiny
                delta = 0
        except Exception:
            delta = 0

    gap = _safe_int(getattr(ma, "best_gap", 0))
    conf = float(getattr(ma, "confidence", 0.0) or 0.0)
    iteration = int(getattr(ma, "iteration", 0) or 0)
    is_mate_flag = bool(getattr(ma, "is_mate", False))

    # Also infer mate if cp sentinels present
    best_is_mate = abs(best_cp) >= MATE_SENTINEL
    played_is_mate = False
    if played_cp is not None:
        played_is_mate = abs(played_cp) >= MATE_SENTINEL

    # --- 1) MATE handling ---
    if is_mate_flag or best_is_mate:
        # If best indicates mate but played does not -> severe drop
        if best_is_mate and not played_is_mate:
            return MoveQuality.BLUNDER

        # Both indicate mate (or we treat it as mate-preserving)
        # If the delta is tiny, treat as BEST; if best line looks unique, consider GREAT
        if delta <= SMALL_DELTA_VERY_GOOD:
            if gap >= GREAT_GAP_THRESHOLD and conf >= 0.5:
                return MoveQuality.GREAT
            return MoveQuality.BEST

        # moderate degradation from mate -> MISTAKE / INACCURACY
        if delta <= MISTAKE_T:
            return MoveQuality.MISTAKE
        if delta <= BLUNDER_T:
            return MoveQuality.BLUNDER
        return MoveQuality.BLUNDER

    # --- 2) If played was effectively the best move ---
    if delta <= SMALL_DELTA_VERY_GOOD:
        if gap >= GREAT_GAP_THRESHOLD and conf >= 0.6:
            return MoveQuality.GREAT
        return MoveQuality.BEST

    # --- 3) Miss detection: best is unique and played is far from best ---
    if gap >= MISS_GAP_THRESHOLD and delta >= MISS_DELTA_THRESHOLD:
        return MoveQuality.MISS

    # --- 4) Delta-based buckets for non-mate positions ---
    if delta >= BLUNDER_T:
        return MoveQuality.BLUNDER
    if delta >= MISTAKE_T:
        return MoveQuality.MISTAKE
    if delta >= INACCURACY_T:
        return MoveQuality.INACCURACY

    # --- 5) Smaller deltas ---
    if delta <= SMALL_DELTA_GOOD:
        return MoveQuality.GOOD

    # fallback conservative
    return MoveQuality.INACCURACY
