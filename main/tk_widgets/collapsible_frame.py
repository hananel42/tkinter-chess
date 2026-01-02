import tkinter as tk


class CollapsibleFrame(tk.Frame):
    """
    CollapsibleFrame
    =================

    A reusable Tkinter widget that provides a collapsible (expand/collapse)
    container controlled by a single button.

    The widget consists of:
    - A header button (used to toggle visibility)
    - A content frame that can contain arbitrary child widgets

    This class is intentionally simple and predictable:
    - No Canvas
    - No geometry hacks
    - Uses only pack() for layout

    Typical use cases:
    - PGN variations (expandable side-lines)
    - Settings panels
    - Sections of a long UI
    - Any "dropdown" style content block

    ------------------------------------------------------------
    Constructor Parameters
    ------------------------------------------------------------
    master : tk.Widget
        Parent widget.

    title : str, optional
        Text displayed on the toggle button.

    initially_open : bool, optional
        If True, the content frame is visible at startup.
        Default is False.

    ------------------------------------------------------------
    Public Attributes
    ------------------------------------------------------------
    button : tk.Button
        The toggle button (header).

    content : tk.Frame
        The inner frame where user widgets should be placed.

    is_open : bool
        Current open/closed state.

    ------------------------------------------------------------
    Public Methods
    ------------------------------------------------------------
    open()
        Show the content frame.

    close()
        Hide the content frame.

    toggle()
        Toggle between open and closed states.
    """

    def __init__(self, master, title="", initially_open=False, *args, **kwargs):
        super().__init__(master, bd=2, relief="groove", *args, **kwargs)

        self.is_open = initially_open
        self._title = title

        # Header button
        self.button = tk.Button(
            self,
            anchor="w",
            command=self.toggle,
            bd=0, relief="groove"
        )
        self.button.pack(fill="x")

        # Content container
        self.content = tk.Frame(self)

        if self.is_open:
            self.content.pack(fill="both", expand=True)

        self._update_button_text()

    # ---------------------------------------------------------
    # State control methods
    # ---------------------------------------------------------
    def open(self):
        """Open (show) the content frame."""
        if not self.is_open:
            self.is_open = True
            self.content.pack(fill="both", expand=True)
            self._update_button_text()

    def close(self):
        """Close (hide) the content frame."""
        if self.is_open:
            self.is_open = False
            self.content.forget()
            self._update_button_text()

    def toggle(self):
        """Toggle between open and closed states."""
        if self.is_open:
            self.close()
        else:
            self.open()

    # ---------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------
    def _update_button_text(self):
        """Update button label according to open/closed state."""
        arrow = "▼" if self.is_open else "▶"
        self.button.config(text=f"{arrow} {self._title}")


if __name__ == "__main__":
    from main.tk_widgets.display_board import DisplayBoard
    from main.tk_widgets.scrollable_frame import ScrollableFrame

    root = tk.Tk()
    root.title("CollapsibleFrame Demo")
    f = ScrollableFrame(root)
    f.pack(fill="both", expand=True)
    for i in range(10):
        section = CollapsibleFrame(
            f.frame,
            title="Board",
            initially_open=False,
        )
        section.pack(padx=10, pady=10, fill="x")
        DisplayBoard(section.content).pack(fill="both", expand=True)

    root.mainloop()
