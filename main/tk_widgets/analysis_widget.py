#!/usr/bin/env python3
# white_black_bar.py
"""
Two-sided analysis bar (White vs Black) + background analyzer thread.
- WhiteBlackBar: horizontal bar split between white (left) and black (right).
  Equal split => draw. Values are percentages 0..100 for each side.
- BackgroundAnalyzer: background thread producing an 'advantage' in [-1, +1].
  advantage = +1 => 100% White, advantage = -1 => 100% Black.
  Replace the simulator with real engine/auto-analyzer as needed.
"""

from __future__ import annotations
import threading
import time
import math
import hashlib
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import tkinter as tk


# -------------------------
# White vs Black bar widget
# -------------------------
class WhiteBlackBar(tk.Frame):
    """
    Simple two-segment bar: left = White, right = Black.
    animate_to(white_prob, black_prob) with white_prob+black_prob ~= 1.0.
    """

    def __init__(
        self,
        master,
        width: int = 520,
        height: int = 36,
        padding: int = 4,
        *args,
        **kwargs,
    ):
        super().__init__(master, *args, **kwargs)
        self.width = width
        self.height = height
        self.pad = padding

        self.canvas = tk.Canvas(self, width=self.width, height=self.height, highlightthickness=0)
        self.canvas.pack()

        # labels
        self.label_frame = tk.Frame(self)
        self.label_frame.pack(fill="x", pady=(6, 0))
        self.white_label = tk.Label(self.label_frame, text="White: 50%", anchor="w")
        self.center_label = tk.Label(self.label_frame, text="Draw", anchor="center")
        self.black_label = tk.Label(self.label_frame, text="Black: 50%", anchor="e")
        self.white_label.pack(side="left", fill="x", expand=True)
        self.center_label.pack(side="left", fill="x", expand=True)
        self.black_label.pack(side="left", fill="x", expand=True)

        # colors
        self.white_color = "#ffffff"
        self.white_border = "#bbbbbb"
        self.black_color = "#333333"
        self.black_border = "#000000"
        self.bg_color = self.master.cget("bg") if hasattr(self.master, "cget") else "#f0f0f0"

        # current and target
        self._cur_white = 0.5
        self._cur_black = 0.5
        self._target_white = self._cur_white
        self._target_black = self._cur_black

        # animation control
        self._anim_after_id = None
        self._anim_steps = 18
        self._anim_step = 0

        # initial draw
        self._draw_background()
        self._draw_segments(self._cur_white, self._cur_black)

    def _draw_background(self):
        self.canvas.delete("bg")
        self.canvas.create_rectangle(
            self.pad,
            self.pad,
            self.width - self.pad,
            self.height - self.pad,
            fill=self.bg_color,
            outline="",
            tags=("bg",),
        )

    def _draw_segments(self, w: float, b: float):
        """Draw left (white) and right (black) rectangles proportionally."""
        self.canvas.delete("segments")
        inner_w = self.width - 2 * self.pad
        # normalize
        w = max(0.0, min(w, 1.0))
        b = max(0.0, min(b, 1.0))
        total = w + b
        if total <= 0:
            w, b = 0.5, 0.5
            total = 1.0
        w_w = inner_w * (w / total)
        b_w = inner_w - w_w

        x = self.pad
        # white segment with subtle border to show it's white
        if w_w > 0.5:
            self.canvas.create_rectangle(x, self.pad, x + w_w, self.height - self.pad,
                                         fill=self.white_color, outline=self.white_border, tags=("segments",))
        x += w_w
        # black segment
        if b_w > 0.5:
            self.canvas.create_rectangle(x, self.pad, x + b_w, self.height - self.pad,
                                         fill=self.black_color, outline=self.black_border, tags=("segments",))

    def _update_labels(self, w: float, b: float):
        # center label shows 'Draw' when nearly equal, otherwise empty
        w_pct = int(round(w * 100))
        b_pct = int(round(b * 100))
        self.white_label.config(text=f"White: {w_pct}%")
        self.black_label.config(text=f"Black: {b_pct}%")
        if abs(w - b) <= 0.03:
            self.center_label.config(text="Draw")
        else:
            self.center_label.config(text="")

    def animate_to(self, white_prob: float, black_prob: float, duration: float = 0.5, fps: int = 30):
        """Animate smoothly from current to target."""
        # normalize to sum 1
        vals = [max(0.0, white_prob), max(0.0, black_prob)]
        s = sum(vals) or 1.0
        self._target_white, self._target_black = (vals[0] / s, vals[1] / s)

        # cancel previous animation
        if self._anim_after_id is not None:
            try:
                self.after_cancel(self._anim_after_id)
            except Exception:
                pass
            self._anim_after_id = None

        # compute steps
        self._anim_steps = max(1, int(duration * fps))
        self._anim_step = 0
        self._start_white = self._cur_white
        self._start_black = self._cur_black

        self._do_anim_frame()

    def _do_anim_frame(self):
        t = self._anim_step / max(1, self._anim_steps)
        # ease in/out cubic
        t_e = (3 * t ** 2 - 2 * t ** 3)
        new_w = self._start_white + (self._target_white - self._start_white) * t_e
        new_b = 1.0 - new_w  # ensure sum==1
        self._cur_white = new_w
        self._cur_black = new_b

        self._draw_background()
        self._draw_segments(self._cur_white, self._cur_black)
        self._update_labels(self._cur_white, self._cur_black)

        self._anim_step += 1
        if self._anim_step <= self._anim_steps:
            self._anim_after_id = self.after(int(1000 / 30), self._do_anim_frame)
        else:
            # finalize
            self._cur_white = self._target_white
            self._cur_black = self._target_black
            self._draw_background()
            self._draw_segments(self._cur_white, self._cur_black)
            self._update_labels(self._cur_white, self._cur_black)
            self._anim_after_id = None


# -------------------------
# Background analyzer (simulated advantage)
# -------------------------
@dataclass
class AnalysisVal:
    # advantage in [-1.0, +1.0] (negative -> favor black, positive -> favor white)
    advantage: float


class BackgroundAnalyzer:
    """
    Background thread that computes an 'advantage' in [-1..1] for the current board.
    It schedules UI updates via the provided scheduler function.
    """
    def __init__(self, schedule_fn: Callable[[Callable, Tuple], None],
                 ui_update_fn: Callable[[float, float], None],
                 poll_interval: float = 0.12):
        """
        schedule_fn: (fn, args_tuple) -> schedules fn(*args) on UI thread, e.g. root.after(0, fn, *args)
        ui_update_fn: function on UI thread taking (white_prob, black_prob)
        """
        self._schedule = schedule_fn
        self._ui_update = ui_update_fn
        self._poll = max(0.02, poll_interval)

        self._thread = threading.Thread(target=self._loop, name="BackgroundAnalyzer", daemon=True)
        self._stop = threading.Event()

        # board state (string representation)
        self._board = "startpos"
        self._lock = threading.Lock()
        self._version = 0

        # simulated smooth internal state
        self._cur_adv = 0.0
        self._target_adv = 0.0
        self._phase = 0.0

        self._thread.start()

    def set_board(self, board_repr: str):
        """Set board representation; increments version. Returns new version."""
        with self._lock:
            self._board = board_repr
            self._version += 1
            v = self._version
            # compute deterministic new target advantage
            self._target_adv = self._compute_advantage_from_board(board_repr)
        return v

    def stop(self):
        self._stop.set()
        self._thread.join(timeout=0.6)

    def _compute_advantage_from_board(self, board_repr: str) -> float:
        """
        Deterministic mapping from board string to advantage in [-1,1].
        Replace with real engine call for real analysis.
        """
        h = hashlib.blake2b(board_repr.encode(), digest_size=8).digest()
        seed = int.from_bytes(h, "little", signed=False)
        # map to [-1,1]
        val = (seed % 10000) / 10000.0  # 0..0.9999
        adv = math.sin(val * 2.0 * math.pi)  # -1..1
        # bias scale down a bit so draws exist
        adv *= 0.85
        return max(-1.0, min(1.0, adv))

    def _loop(self):
        """Worker loop: slowly approach target advantage and schedule UI updates."""
        last_version = -1
        while not self._stop.is_set():
            with self._lock:
                board = self._board
                version = self._version
                target = self._target_adv

            if version != last_version:
                # when board changes, small bump to phase for lively feeling
                self._phase += 1.1
                last_version = version

            # gentle approach to target
            alpha = 0.14  # smoothing
            self._cur_adv += (target - self._cur_adv) * alpha

            # small thinking jitter (so the bar moves slightly)
            self._phase += 0.08
            jitter = 0.02 * math.sin(self._phase * 0.9)
            adv_with_jitter = max(-1.0, min(1.0, self._cur_adv + jitter))

            # compute probs: map advantage -> white_prob in [0,1]
            # transform: adv -1 => white 0.0, adv 0 => white 0.5, adv +1 => white 1.0
            white_prob = 0.5 * (1.0 + adv_with_jitter)
            black_prob = 1.0 - white_prob

            # schedule UI update (ensure UI thread does the actual widget work)
            def _ui_call(wp=white_prob, bp=black_prob):
                try:
                    self._ui_update(wp, bp)
                except Exception:
                    pass

            self._schedule(_ui_call, ())

            time.sleep(self._poll)


# -------------------------
# Demo app
# -------------------------
def main():
    root = tk.Tk()
    root.title("White vs Black Analysis Bar")
    root.geometry("600x160")
    frame = tk.Frame(root, padx=12, pady=12)
    frame.pack(fill="both", expand=True)

    bar = WhiteBlackBar(frame, width=560, height=34)
    bar.pack(pady=(0, 10))

    # scheduler helper
    def schedule_ui(fn: Callable, args: Tuple):
        # ensure called on UI thread
        root.after(0, fn, *args)

    # create analyzer (simulated)
    analyzer = BackgroundAnalyzer(
        schedule_fn=schedule_ui,
        ui_update_fn=lambda w, b: bar.animate_to(w, b, duration=0.45),
        poll_interval=0.09,
    )

    # controls
    btn_frame = tk.Frame(frame)
    btn_frame.pack(fill="x")
    def set_start():
        analyzer.set_board("startpos")
    def set_white_adv():
        analyzer.set_board("white_advantage")
    def set_black_adv():
        analyzer.set_board("black_advantage")
    def random_pos():
        analyzer.set_board(f"random-{time.time()}")

    tk.Button(btn_frame, text="Startpos (balanced)", command=set_start).pack(side="left")
    tk.Button(btn_frame, text="White advantage", command=set_white_adv).pack(side="left", padx=6)
    tk.Button(btn_frame, text="Black advantage", command=set_black_adv).pack(side="left")
    tk.Button(btn_frame, text="Random", command=random_pos).pack(side="left", padx=6)

    # close handler
    def on_close():
        analyzer.stop()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)

    root.mainloop()


if __name__ == "__main__":
    main()
