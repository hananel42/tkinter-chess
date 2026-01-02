"""
ScrollableFrame - reusable Tkinter widget

Usage:
    from scrollable_frame import ScrollableFrame
    root = tk.Tk()
    sf = ScrollableFrame(root, width=400, height=300)
    sf.pack(fill='both', expand=True)

    # add widgets into sf.frame (the interior frame)
    for i in range(50):
        tk.Label(sf.frame, text=f"Item {i}").pack(anchor='w', pady=2)

    root.mainloop()
"""

from __future__ import annotations

import sys
import tkinter as tk
from typing import Optional


class ScrollableFrame(tk.Frame):
    """
    ScrollableFrame(parent, orient='vertical', autohide=True, width=None, height=None, bg=None, **kwargs)

    A frame with scrollable interior implemented using a Canvas.
    - Access the interior container as `.frame` (this is a regular tk.Frame you add children to).
    - Supports mouse-wheel scrolling when the cursor is over the widget.
    - orient: 'vertical', 'horizontal' or 'both'
    - autohide: if True, hides scrollbars when not needed
    """

    def __init__(
            self,
            master,
            orient: str = "vertical",
            autohide: bool = True,
            width: Optional[int] = None,
            height: Optional[int] = None,
            bg: Optional[str] = None,
            scroll_speed: int = 2,
            **kwargs,
    ):
        super().__init__(master, bg=bg, **kwargs)

        if orient not in ("vertical", "horizontal", "both"):
            raise ValueError("orient must be 'vertical', 'horizontal' or 'both'")

        self.orient = orient
        self.autohide = autohide
        self.scroll_speed = max(1, int(scroll_speed))

        # Canvas that will host the interior frame
        self._canvas = tk.Canvas(self, highlightthickness=0, bg=bg)
        self._canvas.grid(row=0, column=0, sticky="nsew")

        # Scrollbars
        self._v_scroll = None
        self._h_scroll = None
        if orient in ("vertical", "both"):
            self._v_scroll = tk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
            self._canvas.configure(yscrollcommand=self._v_scroll.set)
            self._v_scroll.grid(row=0, column=1, sticky="ns")
        if orient in ("horizontal", "both"):
            self._h_scroll = tk.Scrollbar(self, orient="horizontal", command=self._canvas.xview)
            self._canvas.configure(xscrollcommand=self._h_scroll.set)
            self._h_scroll.grid(row=1, column=0, sticky="ew")

        # make grid expandable
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Interior frame placed inside the canvas
        self.frame = tk.Frame(self._canvas, bg=bg)
        # Create window in canvas
        self._window_id = self._canvas.create_window(0, 0, anchor="nw", window=self.frame)

        # Bind events to keep scrollregion and width/height in sync
        self.frame.bind("<Configure>", self._on_frame_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        # Bind mousewheel only when cursor is over canvas (prevents global capture)
        self._enter_binding = self._canvas.bind("<Enter>", self._bind_mousewheel)
        self._leave_binding = self._canvas.bind("<Leave>", self._unbind_mousewheel)

        # Optionally set initial size
        if width is not None:
            self.config(width=width)
            self._canvas.config(width=width)
        if height is not None:
            self.config(height=height)
            self._canvas.config(height=height)

        # initial autohide check
        self.after(10, self._update_scrollbar_visibility)

    # ----------------------
    # Event handlers
    # ----------------------
    def _on_frame_configure(self, event):
        """Update scrollregion when the interior frame changes size."""
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        self._update_scrollbar_visibility()

    def _on_canvas_configure(self, event):
        """Ensure interior width matches canvas width for vertical scrolling use-case."""
        # If vertical scrolling only, stretch inner frame width to canvas width (common behavior)
        if self.orient == "vertical":
            canvas_width = event.width
            # set inner frame width to canvas width
            self._canvas.itemconfigure(self._window_id, width=canvas_width)
        # For horizontal or both, we usually don't forcibly set the width.
        self._update_scrollbar_visibility()

    # ----------------------
    # Mousewheel binding (platform-aware)
    # ----------------------
    def _bind_mousewheel(self, _event=None):
        if sys.platform.startswith("win") or sys.platform == "darwin":
            self._canvas.bind_all("<MouseWheel>", self._on_mousewheel, add="+")
        else:
            # Linux typical
            self._canvas.bind_all("<Button-4>", self._on_mousewheel, add="+")
            self._canvas.bind_all("<Button-5>", self._on_mousewheel, add="+")

    def _unbind_mousewheel(self, _event=None):
        if sys.platform.startswith("win") or sys.platform == "darwin":
            self._canvas.unbind_all("<MouseWheel>")
        else:
            self._canvas.unbind_all("<Button-4>")
            self._canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event):
        """Normalize mousewheel events and scroll canvas."""
        if self.orient in ("vertical", "both"):
            if sys.platform.startswith("win"):
                delta = -int(event.delta / 120)  # Windows: delta is multiple of 120
            elif sys.platform == "darwin":
                # macOS: event.delta is small, use sign only
                delta = -int(event.delta)
            else:
                # X11: use Button-4 / Button-5
                if getattr(event, "num", None) == 4:
                    delta = -1
                elif getattr(event, "num", None) == 5:
                    delta = 1
                else:
                    delta = 0
            # Scroll by units scaled with scroll_speed
            self._canvas.yview_scroll(delta * self.scroll_speed, "units")
        elif self.orient == "horizontal":
            # horizontal scrolling (rare for mouse wheel)
            if getattr(event, "delta", None) is not None:
                delta = -int(event.delta / 120)
                self._canvas.xview_scroll(delta * self.scroll_speed, "units")

    # ----------------------
    # Scrollbar visibility
    # ----------------------
    def _update_scrollbar_visibility(self):
        """Show or hide scrollbars depending on content size when autohide is enabled."""
        if not self.autohide:
            return

        bbox = self._canvas.bbox("all")
        if not bbox:
            # nothing inside
            if self._v_scroll:
                self._v_scroll.grid_remove()
            if self._h_scroll:
                self._h_scroll.grid_remove()
            return

        x1, y1, x2, y2 = bbox
        content_w = x2 - x1
        content_h = y2 - y1
        canvas_w = self._canvas.winfo_width() or 1
        canvas_h = self._canvas.winfo_height() or 1

        if self._v_scroll:
            if content_h <= canvas_h:
                self._v_scroll.grid_remove()
            else:
                self._v_scroll.grid()
        if self._h_scroll:
            if content_w <= canvas_w:
                self._h_scroll.grid_remove()
            else:
                self._h_scroll.grid()

    # ----------------------
    # Convenience API
    # ----------------------
    def scroll_to_top(self):
        self._canvas.yview_moveto(0)

    def scroll_to_bottom(self):
        self._canvas.yview_moveto(1)

    def scroll_to(self, fraction: float):
        """Scroll to a vertical fraction between 0.0 (top) and 1.0 (bottom)."""
        fraction = max(0.0, min(1.0, fraction))
        self._canvas.yview_moveto(fraction)

    def bind_to_canvas(self, sequence, func, add: bool = False):
        """Bind an event to the internal canvas (helper)."""
        self._canvas.bind(sequence, func, add="+" if add else None)

    # Clean up bindings if the widget is destroyed
    def destroy(self):
        try:
            self._unbind_mousewheel()
        except Exception:
            pass
        super().destroy()


# ----------------------
# Demo / Example usage
# ----------------------
if __name__ == "__main__":
    import tkinter as tk

    root = tk.Tk()
    root.title("ScrollableFrame Demo")
    root.geometry("420x320")

    sf = ScrollableFrame(root, orient="vertical", autohide=True, width=400, height=300, bg="#f5f5f5")
    sf.pack(fill="both", expand=True, padx=8, pady=8)

    # Populate with many widgets
    for i in range(60):
        row = tk.Frame(sf.frame, bg="#ffffff", bd=1, relief="solid")
        tk.Label(row, text=f"Row {i}", anchor="w").pack(side="left", padx=6, pady=6)
        tk.Button(row, text="Action", command=lambda m=i: print(f"Action {m}")).pack(side="right", padx=6, pady=6)
        row.pack(fill="x", padx=6, pady=4)

    # Example controls
    ctrl = tk.Frame(root)
    ctrl.pack(fill="x", padx=8, pady=(0, 8))
    tk.Button(ctrl, text="Top", command=sf.scroll_to_top).pack(side="left")
    tk.Button(ctrl, text="Bottom", command=sf.scroll_to_bottom).pack(side="left")

    root.mainloop()
