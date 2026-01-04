#!/usr/bin/env python3
"""
AutoAnalyzer (reworked)

Continuous / infinite analysis using a single persistent UCI engine (Stockfish).
This version uses the "infinite analysis" generator (engine.analysis(..., Limit(infinite=True)))
and snapshots the latest multipv infos at each time-step (budget). It cancels previous
analyses immediately, preserves existing result semantics and increases efficiency
by avoiding repeated short analyse() calls.

Dependencies:
    pip install chess

Notes:
 - start_analayse(board, move=None) cancels any running task and starts a new one.
 - quit() requests fast shutdown and closes the engine.
 - The worker thread is the only thread that talks to the engine.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional, List, Dict, Any

import chess
import chess.engine


# ============================================================
# Result object
# ============================================================

@dataclass
class MoveAnalysis:
    move: chess.Move
    ply: int

    best_cp: int
    played_cp: int
    delta_cp: int
    best_gap: int

    is_mate: bool

    pvs: List[Dict[str, Any]]
    iteration: int
    confidence: float
    time_used: float


# ============================================================
# Utility helpers
# ============================================================

def score_to_cp(score: Optional[chess.engine.PovScore], pov: bool) -> int:
    """Convert a PovScore (or Score) to centipawns; mates mapped to large values."""
    if score is None:
        return 0
    # score.pov expects a color (True for White, False for Black) or returns PovScore when it's a Score
    try:
        sc = score.pov(pov)
    except Exception:
        # if score already a PovScore-like
        sc = score
    if sc.is_mate():
        m = sc.mate()
        return 100_000 if m > 0 else -100_000
    # score.score(mate_score=100000) returns int or None
    s = sc.score(mate_score=100_000)
    return int(s) if s is not None else 0


def material(board: chess.Board, color: bool) -> int:
    values = {
        chess.PAWN: 100,
        chess.KNIGHT: 320,
        chess.BISHOP: 330,
        chess.ROOK: 500,
        chess.QUEEN: 900,
    }
    total = 0
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p and p.color == color:
            total += values.get(p.piece_type, 0)
    return total


# ============================================================
# AutoAnalyzer (infinite-analysis based)
# ============================================================

class AutoAnalyzer:
    def __init__(
            self,
            *,
            engine_path: str,
            multipv: int = 4,
            on_new_analysis: Optional[Callable[[MoveAnalysis], None]] = None,
            time_steps: Optional[List[float]] = None,
    ):
        self.engine_path = engine_path
        self.multipv = max(1, multipv)
        self.on_new_analysis = on_new_analysis
        # default progressive budgets (seconds)
        self.time_steps = time_steps or [0.05, 0.2, 0.6]

        # engine state (only touched by worker under locks when necessary)
        self._engine_lock = threading.RLock()
        self._engine: Optional[chess.engine.SimpleEngine] = None

        # task state protected by _task_lock
        self._task_lock = threading.Lock()
        self._task_id = 0
        self._before: Optional[chess.Board] = None
        self._after: Optional[chess.Board] = None
        self._move: Optional[chess.Move] = None
        # cancel event for current outstanding task
        self._cancel_event = threading.Event()

        # stop the worker completely
        self._stop_event = threading.Event()

        # worker thread
        self._worker = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="AutoAnalyzerWorker"
        )
        self._worker.start()

    # --------------------------------------------------------

    def start_analayse(self, board: chess.Board, move: Optional[chess.Move] = None):
        """
        Start (or restart) analysis for the given board and the given move.
        If move is None, it will use the last move on the board (board.move_stack[-1]).
        This method cancels any in-flight analysis immediately.
        """
        board = board.copy(stack=True)

        if move is None:
            if not board.move_stack:
                raise ValueError("Board has no last move")
            move = board.move_stack[-1]

        after = board.copy(stack=True)
        before = board.copy(stack=True)
        before.pop()

        with self._task_lock:
            # bump task id
            self._task_id += 1
            self._before = before
            self._after = after
            self._move = move

            # cancel current analysis immediately
            self._cancel_event.set()
            # and replace with a fresh cancel event for the new task
            self._cancel_event = threading.Event()

    # --------------------------------------------------------

    def quit(self):
        """
        Stop the worker and shut down the engine. Attempts to be fast.
        """
        self._stop_event.set()
        # cancel any current analyses
        self._cancel_event.set()

        # wait briefly for worker to finish
        self._worker.join(timeout=0.4)

        # close engine
        with self._engine_lock:
            if self._engine:
                try:
                    self._engine.quit()
                except Exception:
                    pass
                self._engine = None

    # ========================================================
    # Internal helpers
    # ========================================================

    def _ensure_engine(self):
        with self._engine_lock:
            if self._engine is None:
                self._engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)
                # configure once
                try:
                    self._engine.configure({
                        "Threads": 4,
                        "Hash": 256,
                        "MultiPV": self.multipv,
                    })
                except Exception:
                    # some engines ignore configure; ignore failures
                    pass

    # --------------------------------------------------------

    def _snapshot_from_latest_infos(self, latest_infos: Dict[int, Dict[str, Any]], mover: bool, move: chess.Move):
        """
        Given latest_infos keyed by multipv index (1..n), build MoveAnalysis fields.
        latest_infos values are raw info dicts from engine.analysis stream.
        """
        pvs: List[Dict[str, Any]] = []
        for idx in range(1, self.multipv + 1):
            info = latest_infos.get(idx)
            if info is None:
                continue
            pv_moves = [m.uci() for m in info.get("pv", [])]
            cp = score_to_cp(info.get("score"), mover)
            pvs.append({"cp": cp, "pv": pv_moves})

        if not pvs:
            # fallback empty
            pvs = [{"cp": 0, "pv": []}]

        best_cp = pvs[0]["cp"]
        second_cp = pvs[1]["cp"] if len(pvs) > 1 else best_cp

        played_cp = None
        move_uci = move.uci()
        for pv in pvs:
            if pv["pv"] and pv["pv"][0] == move_uci:
                played_cp = pv["cp"]
                break

        return pvs, best_cp, second_cp, played_cp

    # --------------------------------------------------------
    def stop_analyze(self):
        self._cancel_event.set()

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
                # no new task
                time.sleep(0.01)
                continue

            last_task = task_id

            # ensure engine running
            try:
                self._ensure_engine()
            except Exception as e:
                # engine failed to start; sleep and retry later
                print("AutoAnalyzer: engine start failed:", e)
                time.sleep(0.2)
                continue

            mover = before.turn  # color for pov conversions (True=White, False=Black)

            # We run a single infinite analysis generator per task (per 'before' position).
            # At each configured time-step (budget) we take the latest multipv infos
            # we've received and emit a MoveAnalysis snapshot.
            try:
                with self._engine.analysis(
                        before,
                        chess.engine.Limit(),
                        multipv=self.multipv
                ) as analysis:
                    # holder for latest infos per multipv index (1..multipv)
                    latest_infos: Dict[int, Dict[str, Any]] = {}
                    # iteration over configured budgets
                    for iteration, budget in enumerate(self.time_steps):
                        if cancel.is_set() or self._stop_event.is_set():
                            break

                        iter_start = time.time()
                        # collect stream until budget elapsed or cancel
                        while True:
                            # break conditions
                            if cancel.is_set() or self._stop_event.is_set():
                                break
                            now = time.time()
                            if now - iter_start >= budget:
                                break

                            try:
                                info = next(analysis)
                            except StopIteration:
                                # engine closed the analysis (unexpected) -> exit
                                cancel.set()
                                break
                            except Exception:
                                # on any engine error / transient issue, break this iteration
                                break

                            # We expect 'info' to possibly contain a multipv field (1..n).
                            # Some engines include 'multipv' entry; default to 1 otherwise.
                            mpv = info.get("multipv", 1)
                            try:
                                mpv = int(mpv)
                                if mpv < 1:
                                    mpv = 1
                            except Exception:
                                mpv = 1

                            # store latest info for this multipv
                            latest_infos[mpv] = info

                        # at end of budget, snapshot latest_infos
                        t0 = iter_start
                        t1 = time.time()
                        time_used = t1 - t0

                        # If cancel set, skip snapshot
                        if cancel.is_set() or self._stop_event.is_set():
                            break

                        # Build pvs and primary metrics
                        pvs, best_cp, second_cp, played_cp = self._snapshot_from_latest_infos(
                            latest_infos, mover, move
                        )

                        # If we couldn't find played_cp among the pvs, do a quick eval of 'after'
                        if played_cp is None:
                            try:
                                # small quick probe for the actual played move evaluation
                                with self._engine_lock:
                                    info_after = self._engine.analyse(after, chess.engine.Limit(time=0.02))
                                played_cp = score_to_cp(info_after.get("score"), mover)
                            except Exception:
                                played_cp = 0

                        delta = best_cp - (played_cp if played_cp is not None else 0)
                        best_gap = best_cp - second_cp
                        mate = abs(played_cp) >= 100_000

                        # confidence heuristic (improves with iterations and more multipv hits)
                        confidence = min(1.0, 0.25 + 0.25 * iteration + 0.15 * len(pvs))

                        result = MoveAnalysis(
                            move=move,
                            ply=len(after.move_stack),
                            best_cp=best_cp,
                            played_cp=played_cp if played_cp is not None else 0,
                            delta_cp=delta,
                            best_gap=best_gap,
                            is_mate=mate,
                            pvs=pvs,
                            iteration=iteration,
                            confidence=confidence,
                            time_used=time_used,
                        )

                        # dispatch callback (guarded)
                        if self.on_new_analysis and not cancel.is_set():
                            try:
                                self.on_new_analysis(result)
                            except Exception:
                                # swallow exceptions from user callback to keep worker alive
                                pass

                        # small throttle to avoid starving CPU / UI updates
                        # (still very responsive; increase if you want fewer updates)
                        time.sleep(0.005)

                    # finished iterations for this task, close analysis and continue (or next task)
                    # exiting the 'with' will close the analysis generator cleanly
            except chess.engine.EngineTerminatedError:
                # Engine died unexpectedly; drop and try to recreate on next loop
                with self._engine_lock:
                    try:
                        if self._engine:
                            self._engine.quit()
                    except Exception:
                        pass
                    self._engine = None
                time.sleep(0.05)
            except Exception as e:
                # unexpected error; print optionally and continue loop
                # (don't crash the worker thread)
                print("AutoAnalyzer worker error:", e)
                time.sleep(0.05)

        # end worker loop


# ============================================================
# Demo (same style as before)
# ============================================================

if __name__ == "__main__":
    import random


    def callback(res: MoveAnalysis):
        print(
            f"[iter {res.iteration}] "
            f"{res.move.uci()}  "
            f"best={res.best_cp}  "
            f"played={res.played_cp}  "
            f"Δ={res.delta_cp}  "
            f"conf={res.confidence:.2f}  "
            f"t={res.time_used:.3f}s"
        )


    # adjust the path to your engine binary
    ENGINE_PATH = "c:/stockfish/stockfish.exe"

    analyzer = AutoAnalyzer(
        engine_path=ENGINE_PATH,
        multipv=4,
        on_new_analysis=callback,
        time_steps=[0.02, 0.12, 0.5],
    )

    board = chess.Board()

    try:
        for _ in range(6):
            m = random.choice(list(board.legal_moves))
            board.push(m)
            analyzer.start_analayse(board)
            # while analysis runs, simulate user doing things (the analyzer will cancel old tasks)
            time.sleep(0.35)

        # let last analysis finish some iterations
        time.sleep(1.0)
    finally:
        analyzer.quit()
        print("Stopped.")
