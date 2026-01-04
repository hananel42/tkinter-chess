#!/usr/bin/env python3
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional, List, Dict, Any

import chess
import chess.engine


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


def score_to_cp(score: Optional[chess.engine.PovScore], pov: bool) -> int:
    """Convert a Score/PovScore to centipawns; mates mapped to large values."""
    if score is None:
        return 0
    # If it's a Score, convert to PovScore relative to pov
    try:
        sc = score.pov(pov)
    except Exception:
        sc = score
    # povscore methods: is_mate(), mate(), score(mate_score=...)
    try:
        if sc.is_mate():
            m = sc.mate()
            return 100_000 if m > 0 else -100_000
    except Exception:
        pass
    try:
        s = sc.score(mate_score=100_000)
        return int(s) if s is not None else 0
    except Exception:
        return 0


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
        self.time_steps = time_steps or [0.05, 0.2, 0.6]

        self._engine_lock = threading.RLock()
        self._engine: Optional[chess.engine.SimpleEngine] = None

        self._task_lock = threading.Lock()
        self._task_id = 0
        self._before: Optional[chess.Board] = None
        self._after: Optional[chess.Board] = None
        self._move: Optional[chess.Move] = None
        self._cancel_event = threading.Event()

        self._stop_event = threading.Event()

        self._worker = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="AutoAnalyzerWorker"
        )
        self._worker.start()

    def start_analayse(self, board: chess.Board, move: Optional[chess.Move] = None):
        board = board.copy(stack=True)

        if move is None:
            if not board.move_stack:
                raise ValueError("Board has no last move")
            move = board.move_stack[-1]

        after = board.copy(stack=True)
        before = board.copy(stack=True)
        before.pop()

        with self._task_lock:
            self._task_id += 1
            self._before = before
            self._after = after
            self._move = move

            # cancel any running analysis immediately
            self._cancel_event.set()
            self._cancel_event = threading.Event()

    def quit(self):
        self._stop_event.set()
        self._cancel_event.set()
        self._worker.join(timeout=0.4)
        with self._engine_lock:
            if self._engine:
                try:
                    self._engine.quit()
                except Exception:
                    pass
                self._engine = None

    def _ensure_engine(self):
        with self._engine_lock:
            if self._engine is None:
                self._engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)
                try:
                    self._engine.configure({
                        "Threads": 4,
                        "Hash": 256,
                        "MultiPV": self.multipv,
                    })
                except Exception:
                    pass

    def _snapshot_from_latest_infos(self, latest_infos: Dict[int, Dict[str, Any]], mover: bool, move: chess.Move):
        pvs: List[Dict[str, Any]] = []
        for idx in range(1, self.multipv + 1):
            info = latest_infos.get(idx)
            if info is None:
                continue
            pv_moves = [m.uci() for m in info.get("pv", [])]
            cp = score_to_cp(info.get("score"), mover)
            pvs.append({"cp": cp, "pv": pv_moves})

        if not pvs:
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
                time.sleep(0.01)
                continue

            last_task = task_id

            try:
                self._ensure_engine()
            except Exception as e:
                print("AutoAnalyzer: engine start failed:", e)
                time.sleep(0.2)
                continue

            mover = before.turn  # pov color for scores (True=White, False=Black)

            # QUICK probe for 'after' evaluated from the same POV as 'before'
            played_cp_quick: Optional[int] = None
            try:
                with self._engine_lock:
                    # short synchronous probe - done before starting long analysis to avoid conflicts
                    info_after = self._engine.analyse(after, chess.engine.Limit(time=0.03))
                played_cp_quick = score_to_cp(info_after.get("score"), mover)
            except Exception:
                played_cp_quick = None

            try:
                with self._engine.analysis(before, chess.engine.Limit(), multipv=self.multipv) as analysis:
                    latest_infos: Dict[int, Dict[str, Any]] = {}
                    for iteration, budget in enumerate(self.time_steps):
                        if cancel.is_set() or self._stop_event.is_set():
                            break

                        iter_start = time.time()
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
                                break

                            mpv = info.get("multipv", 1)
                            try:
                                mpv = int(mpv)
                                if mpv < 1:
                                    mpv = 1
                            except Exception:
                                mpv = 1

                            latest_infos[mpv] = info

                        t0 = iter_start
                        t1 = time.time()
                        time_used = t1 - t0

                        if cancel.is_set() or self._stop_event.is_set():
                            break

                        pvs, best_cp, second_cp, played_cp = self._snapshot_from_latest_infos(
                            latest_infos, mover, move
                        )

                        if played_cp is None:
                            # use the quick probe result computed earlier
                            played_cp = played_cp_quick if played_cp_quick is not None else 0

                        delta = best_cp - played_cp
                        best_gap = best_cp - second_cp
                        # treat as mate if either best or played indicates mate sentinel
                        mate = abs(best_cp) >= 100_000 or abs(played_cp) >= 100_000

                        confidence = min(1.0, 0.25 + 0.25 * iteration + 0.15 * len(pvs))

                        result = MoveAnalysis(
                            move=move,
                            ply=len(after.move_stack),
                            best_cp=best_cp,
                            played_cp=played_cp,
                            delta_cp=delta,
                            best_gap=best_gap,
                            is_mate=mate,
                            pvs=pvs,
                            iteration=iteration,
                            confidence=confidence,
                            time_used=time_used,
                        )

                        if self.on_new_analysis and not cancel.is_set():
                            try:
                                self.on_new_analysis(result)
                            except Exception:
                                pass

                        time.sleep(0.005)
            except chess.engine.EngineTerminatedError:
                with self._engine_lock:
                    try:
                        if self._engine:
                            self._engine.quit()
                    except Exception:
                        pass
                    self._engine = None
                time.sleep(0.05)
            except Exception as e:
                print("AutoAnalyzer worker error:", e)
                time.sleep(0.05)

        # end worker loop
