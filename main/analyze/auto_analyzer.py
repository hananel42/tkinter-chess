#!/usr/bin/env python3
"""
AutoAnalyzer - continuous local analysis intended to mimic Lichess-style analysis.

Features:
 - Reuses a single engine process (auto-restarts if it dies)
 - Uses engine.analysis(...) generator for iterative snapshots
 - Performs a short probe on the 'after' position to obtain played move eval
 - Produces MoveAnalysis snapshots (including best_cp, second_cp, best_gap)
 - Calls on_new_analysis(result) each snapshot unless cancelled
 - Configurable: multipv, time_steps, threads, hash_mb, quick_probe_time

Notes about reproducibility:
 - To get results identical to Lichess you must use the same Stockfish build/version,
   the same engine options, same node/hash/threads, and run on equivalent hardware.
"""

from __future__ import annotations

import threading
import time
import math
from dataclasses import dataclass
from typing import Callable, Optional, List, Dict, Any, Tuple

import chess
import chess.engine

# -----------------------
# Data model
# -----------------------

@dataclass
class MoveAnalysis:
    # Basic
    is_best: bool
    best_cp: int
    played_cp: int
    second_cp: int
    best_gap: int

    # Probabilities in range [0.0, 1.0] for the side-to-move (win/draw/loss)
    win_probability_played: float
    win_probability_best: float
    draw_probability_played: float
    draw_probability_best: float
    loss_probability_played: float
    loss_probability_best: float

    # Iteration/depth-like snapshot index (1..n)
    deep: int

# -----------------------
# Constants / defaults
# -----------------------

MATE_SENTINEL = 100_000
DEFAULT_TIME_STEPS = [0.05, 0.2, 0.6]  # seconds per snapshot iteration (small -> med -> long)
CP_CLAMP = 4000

# Lichess-like logistic constant (from community / lichess accuracy discussion).
# win_rate ~= 1/(1 + exp(-A * cp)), with A ~= 0.00368208 (see references).
# We will use it to compute raw win expectation before adding draw mass.
LICHESS_LOGISTIC_A = 0.00368208  # empirical value referenced in Lichess community. (see doc)

# quick probe budget for 'after' to evaluate the actually-played move if missing in PV
DEFAULT_QUICK_PROBE = 0.03  # seconds


# -----------------------
# Helpers: score -> cp and cp -> (win,draw,loss)
# -----------------------

def _score_to_cp(info_score: Any, pov: bool) -> int:
    """Convert engine info['score'] (Score or PovScore) into centipawns (int).
    Handle mate as sentinel values +/- MATE_SENTINEL.
    """
    if info_score is None:
        return 0
    try:
        sc = info_score.pov(pov)
    except Exception:
        sc = info_score
    try:
        if sc.is_mate():
            m = sc.mate()
            return MATE_SENTINEL if m > 0 else -MATE_SENTINEL
    except Exception:
        pass
    try:
        s = sc.score(mate_score=MATE_SENTINEL)
        return int(s) if s is not None else 0
    except Exception:
        return 0


def _lichess_win_raw(cp: int) -> float:
    """Return raw win expectation in range (0,1) using Lichess-like logistic mapping.
    (This is the 'win%' mapping discussed for Lichess accuracy; see refs).
    """
    # clamp cp so logistic doesn't overflow
    c = max(-CP_CLAMP, min(CP_CLAMP, cp))
    return 1.0 / (1.0 + math.exp(-LICHESS_LOGISTIC_A * c))


def _cp_to_probs(cp: int) -> Tuple[float, float, float]:
    """
    Convert cp -> (win, draw, loss) probabilities for the side-to-move.
    Strategy:
      - win_raw from logistic (Lichess-like)
      - loss_raw = 1 - win_raw
      - draw_mass decreases with |cp| (positions near equal have more draws)
      - allocate draw_mass and renormalize so win+draw+loss == 1.0
    This is an approximation (Lichess uses a logistic for win; draw mass is not public),
    but yields visually and numerically similar curves.
    """
    win_raw = _lichess_win_raw(cp)
    loss_raw = 1.0 - win_raw

    # draw mass: choose a decay so draws are meaningful near cp=0 and small far away
    draw_raw = math.exp(-abs(cp) / 450.0) * 0.28  # ~0.28 draw weight at cp==0

    # combine and renormalize
    w = win_raw
    l = loss_raw
    d = draw_raw

    total = w + d + l
    if total <= 0.0:
        return 0.0, 0.0, 1.0

    return w / total, d / total, l / total


# -----------------------
# AutoAnalyzer
# -----------------------

class AutoAnalyzer:
    """
    Continuous analyzer that:
      - reuses a single engine
      - runs analysis(before) with MultiPV
      - probes after for played move eval if needed
      - calls on_new_analysis() with MoveAnalysis per snapshot
    """

    def __init__(
        self,
        *,
        engine_path: str,
        multipv: int = 4,
        on_new_analysis: Optional[Callable[[MoveAnalysis], None]] = None,
        time_steps: Optional[List[float]] = None,
        threads: int = 2,
        hash_mb: int = 64,
        quick_probe: float = DEFAULT_QUICK_PROBE,
        debug: bool = False,
    ):
        self.engine_path = engine_path
        self.multipv = max(1, multipv)
        self.on_new_analysis = on_new_analysis
        self.time_steps = time_steps if time_steps is not None else DEFAULT_TIME_STEPS
        self.threads = max(1, threads)
        self.hash_mb = max(1, hash_mb)
        self.quick_probe = quick_probe
        self.debug = bool(debug)

        # engine and locks
        self._engine: Optional[chess.engine.SimpleEngine] = None
        self._engine_lock = threading.RLock()

        # task scheduling
        self._task_lock = threading.Lock()
        self._task_id = 0
        self._before: Optional[chess.Board] = None
        self._after: Optional[chess.Board] = None
        self._move: Optional[chess.Move] = None
        self._cancel_event = threading.Event()

        # lifecycle
        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="AutoAnalyzerWorker")
        self._worker.start()

    # Public API
    def start_analyse(self, board: chess.Board, move: Optional[chess.Move] = None):
        """Schedule analysis of last move on board (or explicit move).
        Copies board (stack=True) to avoid races with caller.
        """
        bc = board.copy(stack=True)
        if move is None:
            if not bc.move_stack:
                raise ValueError("Board has no last move")
            move = bc.move_stack[-1]

        after = bc.copy(stack=True)
        before = bc.copy(stack=True)
        before.pop()

        with self._task_lock:
            self._task_id += 1
            self._before = before
            self._after = after
            self._move = move

            # cancel previous job immediately
            self._cancel_event.set()
            self._cancel_event = threading.Event()

        if self.debug:
            print(f"[AutoAnalyzer] scheduled task #{self._task_id} move={move}")

    def stop_analyze(self):
        """Cancel the current running analysis."""
        self._cancel_event.set()

    def quit(self, join_timeout: float = 0.6):
        """Shutdown worker and engine."""
        self._stop_event.set()
        self._cancel_event.set()
        self._worker.join(timeout=join_timeout)
        with self._engine_lock:
            if self._engine:
                try:
                    self._engine.quit()
                except Exception:
                    pass
                self._engine = None

    # Internal
    def _ensure_engine(self):
        with self._engine_lock:
            if self._engine is None:
                self._engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)
                try:
                    self._engine.configure({
                        "Threads": self.threads,
                        "Hash": self.hash_mb,
                        "MultiPV": self.multipv,
                    })
                except Exception:
                    # ignore unknown options for some engines
                    pass
                if self.debug:
                    print("[AutoAnalyzer] Engine started/configured")

    def _snapshot_from_infos(self, infos: Dict[int, Dict[str, Any]], pov: bool, move: chess.Move) -> Tuple[List[Dict[str, Any]], int, int, Optional[int], int]:
        """
        Build snapshot:
         - pvs: list of {'cp':int, 'pv':[uci,...]}
         - best_cp, second_cp, played_cp (if present), best_gap
        """
        pvs: List[Dict[str, Any]] = []
        for idx in range(1, self.multipv + 1):
            inf = infos.get(idx)
            if inf is None:
                continue
            pvlist = []
            for m in inf.get("pv", []):
                try:
                    pvlist.append(m.uci() if isinstance(m, chess.Move) else str(m))
                except Exception:
                    pvlist.append(str(m))
            cp = _score_to_cp(inf.get("score"), pov)
            pvs.append({"cp": cp, "pv": pvlist})

        if not pvs:
            pvs = [{"cp": 0, "pv": []}]

        best_cp = pvs[0]["cp"]
        second_cp = pvs[1]["cp"] if len(pvs) > 1 else best_cp

        played_cp = None
        move_uci = move.uci()
        for idx, pv in enumerate(pvs, start=1):
            if pv["pv"] and pv["pv"][0] == move_uci:
                played_cp = pv["cp"]
                break

        best_gap = best_cp - second_cp
        return pvs, best_cp, second_cp, played_cp, best_gap

    def _worker_loop(self):
        last_task = None
        while not self._stop_event.is_set():
            with self._task_lock:
                task_id = self._task_id
                before = self._before
                after = self._after
                move = self._move
                cancel = self._cancel_event

            if before is None or task_id == last_task:
                time.sleep(0.01)
                continue

            last_task = task_id

            try:
                self._ensure_engine()
            except Exception as e:
                if self.debug:
                    print("[AutoAnalyzer] engine start failed:", e)
                time.sleep(0.2)
                continue

            pov = before.turn  # True for White, False for Black

            # Quick probe on 'after' to get played eval if PVs do not include it
            played_cp_quick = None
            try:
                with self._engine_lock:
                    info_after = self._engine.analyse(after, chess.engine.Limit(time=self.quick_probe))
                played_cp_quick = _score_to_cp(info_after.get("score"), pov)
            except Exception:
                played_cp_quick = None

            # Long analysis on 'before'
            try:
                with self._engine.analysis(before, chess.engine.Limit(), multipv=self.multipv) as analysis:
                    latest_infos: Dict[int, Dict[str, Any]] = {}
                    for deep_index, budget in enumerate(self.time_steps, start=1):
                        if cancel.is_set() or self._stop_event.is_set():
                            break

                        iter_start = time.time()
                        # consume generator for budget seconds
                        while True:
                            if cancel.is_set() or self._stop_event.is_set():
                                break
                            now = time.time()
                            if now - iter_start >= budget:
                                break
                            try:
                                info = next(analysis)
                            except StopIteration:
                                cancel.set()
                                break
                            except Exception:
                                # generator hiccup: break iteration
                                break

                            mpv = info.get("multipv", 1)
                            try:
                                mpv = int(mpv)
                                if mpv < 1:
                                    mpv = 1
                            except Exception:
                                mpv = 1
                            latest_infos[mpv] = info

                        # build snapshot
                        pvs, best_cp, second_cp, played_cp, best_gap = self._snapshot_from_infos(latest_infos, pov, move)

                        if played_cp is None:
                            played_cp = played_cp_quick if played_cp_quick is not None else 0

                        # probabilities
                        w_b, d_b, l_b = _cp_to_probs(best_cp)
                        w_p, d_p, l_p = _cp_to_probs(played_cp)

                        is_best = (played_cp == best_cp) or (len(pvs) and pvs[0]["pv"] and pvs[0]["pv"][0] == move.uci())

                        result = MoveAnalysis(
                            is_best=is_best,
                            best_cp=int(best_cp),
                            played_cp=int(played_cp),
                            second_cp=int(second_cp),
                            best_gap=int(best_gap),

                            win_probability_played=float(w_p),
                            win_probability_best=float(w_b),
                            draw_probability_played=float(d_p),
                            draw_probability_best=float(d_b),
                            loss_probability_played=float(l_p),
                            loss_probability_best=float(l_b),

                            deep=int(deep_index),
                        )

                        if self.on_new_analysis and not cancel.is_set():
                            try:
                                self.on_new_analysis(result)
                            except Exception:
                                # swallow exceptions in callback to keep worker alive
                                pass

                        # tiny sleep to yield CPU / rate-limit callbacks
                        time.sleep(0.003)

            except chess.engine.EngineTerminatedError:
                # engine died: ensure we drop reference so _ensure_engine restarts it
                with self._engine_lock:
                    try:
                        if self._engine:
                            self._engine.quit()
                    except Exception:
                        pass
                    self._engine = None
                time.sleep(0.05)
            except Exception:
                # generic worker error: continue to next task
                time.sleep(0.05)
