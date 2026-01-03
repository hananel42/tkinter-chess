#!/usr/bin/env python3
"""
DisplayBoard
============

A high-performance, feature-rich Tkinter chessboard widget built on top of
python-chess.

This widget is designed as a **pure UI / interaction layer** that visually
represents a `chess.Board` while exposing clean hooks for engines, analyzers,
PGN systems and external controllers.

Core Design Principles
----------------------
• Stateless rendering: the canvas is always derived from the internal board state
• Zero external dependencies (except `python-chess`)
• Animation-safe and callback-safe
• Designed to scale to long games and fast updates
• No PGN logic, no engine logic — UI only

Main Capabilities
-----------------
• Full interactive chessboard rendering (Unicode pieces)
• Click-to-move and drag-to-move input
• Optional smooth piece animations
• Right-click annotations (arrows & circles)
• Move highlighting (from / to squares)
• Visual move quality badges (!!, ?, ??, ★, etc.)
• Promotion dialog handling
• Board flipping
• Undo / redo with animation support
• SVG export (with annotations)
• Fully detachable board cloning (engine-safe)

Intended Usage
--------------
DisplayBoard is meant to be embedded in:
• Chess GUIs
• Analysis tools
• PGN viewers / editors
• Training interfaces
• Engine visualizers

The widget does NOT:
• Perform engine analysis
• Assign move scores
• Manage PGN trees
• Enforce UI layout policy

Those responsibilities are intentionally left to external controllers.

Authoritative state is always the internal `chess.Board`.

All documentation and comments are written for maintainability and extension.
"""
import math
import tkinter as tk
import tkinter.font
from enum import Enum, auto
from typing import Callable, Optional, Tuple

import chess
from chess import Move


class MoveQuality(Enum):
    BRILLIANT = auto()
    GREAT = auto()
    BEST = auto()
    BOOK = auto()
    GOOD = auto()
    INACCURACY = auto()
    MISTAKE = auto()
    BLUNDER = auto()
    MISS = auto()



class DisplayBoard(tk.Frame):
    """
    DisplayBoard is a self-contained Tkinter widget that visualizes and interacts
    with a `python-chess` Board.

    It acts as a **reactive board renderer**:
    every visual element (pieces, highlights, arrows, animations) is derived
    directly from the current board state and overlay collections.

    Public Responsibilities
    -----------------------
    • Maintain an internal `chess.Board`
    • Render the board state on a Tkinter Canvas
    • Accept and validate user moves
    • Animate legal moves (optional)
    • Emit move callbacks
    • Provide visual annotations and overlays

    Architectural Notes
    -------------------
    • The widget owns the board state
    • External systems may observe but should not mutate it directly
    • All animations are interruptible and safe
    • Undo / redo preserves animation consistency
    • Rendering is idempotent (redraw() is always safe)

    Integration Model
    -----------------
    The widget integrates cleanly with:
    • Chess engines (via clone_board())
    • PGN systems (SAN / UCI handled externally)
    • Auto-analysis pipelines
    • Read-only mirror boards

    Typical Flow
    ------------
    1. User performs a move (click or drag)
    2. Move legality is validated
    3. Optional animation plays
    4. Board state is updated
    5. Move callbacks are fired
    6. Board is redrawn

    This class deliberately avoids any dependency on:
    • Engines
    • Threading
    • PGN parsing
    • Evaluation logic

    Those concerns belong outside the UI layer.
    """

    UNICODE_PIECES = {
        "P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
        "p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚"
    }

    def __init__(
            self,
            master=None,
            board_size: int = 480,
            allow_input: bool = True,
            allow_dragging: bool = True,
            allow_drawing: bool = True,
            black_bg: Tuple[int, int, int] = (181, 136, 99),
            white_bg: Tuple[int, int, int] = (240, 217, 181),
            arrow_color: Tuple[int, int, int] = (255, 0, 0),
            arrow_width: int = 3,
            circle_color: Tuple[int, int, int] = (255, 0, 0),
            circle_width: int = 3,
            show_legal: bool = True,
            legal_moves_circles_color: Tuple[int, int, int] = (50, 50, 50),
            legal_moves_circles_width: int = 5,
            legal_moves_circles_radius: int = 7,
            show_coordinates: bool = True,
            input_callback: Optional[Callable] = None,
            draw_function: Optional[Callable] = None,
            flipped: bool = False,
            highlight_color: Tuple[int, int, int] = (150, 232, 125),
            border: float = 0,
            border_bg: str | Tuple[int, int, int] = "#000",
            font: str = "Arial",
            auto_resize: bool = True,
            animation_fps: int = 60,
            animation_duration: float = 0.20,
            allow_animation: bool = True,
            auto_stop_animation: bool = False,
            from_color: str | Tuple[int, int, int] = (160, 200, 180),
            to_color: str | Tuple[int, int, int] = (160, 200, 180),
            move_quality_colors=None,
            quality_symbols=None,
            auto_queen_promotion: bool = False,
            *args,
            **kwargs):
        """
        Initialize display and internal board.

        Parameters largely mirror previously used parameter names and defaults.
        Documentation focuses on usage, not implementation details.
        """
        tk.Frame.__init__(self, master, width=board_size, height=board_size)

        # Canvas setup
        self.master = master
        self.board = chess.Board(*args, **kwargs)
        self.border_frame = tk.Frame(self, border=border, background=self.rgb_to_hex(border_bg))
        self.border_frame.pack()
        self.canvas = tk.Canvas(self.border_frame, width=board_size, height=board_size, highlightthickness=0)
        if auto_resize:
            self.bind("<Configure>", self._re_configure)
        self.canvas.pack(expand=True)

        # Interaction / state flags
        self.redo_stack = []
        self._promotion_active = False
        self._waiting_move = None
        self._promotion_buttons = []  # list[(x1,y1,x2,y2), promo]
        self._selected_square = None
        self._right_click_start = None
        self._right_click_end = None
        self._dragging_piece = None
        self._dragging_offset = (0, 0)
        self.animation_fps = max(1, int(animation_fps))
        self.animation_duration = max(0.0, float(animation_duration))
        self.allow_animation = bool(allow_animation)
        self.auto_stop_animation = auto_stop_animation
        self._anim_after_id = None
        self._anim_data = []
        self.highlighted_move: chess.Move | None = None
        self._last_move_quality: Optional[MoveQuality] = None

        # derived interval (ms)
        self._anim_frame_interval_ms = int(1000 / max(1, self.animation_fps))

        # Collections used for overlay drawing (prevent duplicates)
        self.user_highlights = []  # list[(row, col, color)]
        self.system_highlights = []
        self.user_circles = []  # list[(row, col, color, radius, width)]
        self.system_circles = []
        self.user_arrows = []  # list[(from_row, from_col, to_row, to_col, color, width)]
        self.system_arrows = []

        # Move callbacks - appended via on_move()
        self._move_callbacks = []
        if input_callback:
            self._move_callbacks.append(input_callback)

        # Display / behavior settings
        self.board_size = board_size
        self.square_size = board_size // 8
        self.allow_input = allow_input
        self.allow_dragging = allow_dragging
        self.allow_drawing = allow_drawing
        self.draw_function = draw_function
        self.flipped = flipped
        self.black_bg = black_bg
        self.white_bg = white_bg
        self.circle_color = circle_color
        self.circle_width = circle_width
        self.arrow_color = arrow_color
        self.arrow_width = arrow_width
        self.highlight_color = highlight_color
        self.legal_moves_circles_color = legal_moves_circles_color
        self.legal_moves_circles_radius = legal_moves_circles_radius
        self.legal_moves_circles_width = legal_moves_circles_width
        self.show_legal = show_legal
        self.show_coordinates = show_coordinates
        self.font = tkinter.font.Font(family=font, size=int(self.square_size * 0.6))
        self.from_color = from_color
        self.to_color = to_color
        self.move_quality_colors = move_quality_colors
        if move_quality_colors is None:
            self.move_quality_colors = {
                MoveQuality.BRILLIANT: (38, 198, 218),
                MoveQuality.GREAT: (127, 182, 193),
                MoveQuality.BEST: (150, 188, 75),
                MoveQuality.BOOK: (165, 139, 109),
                MoveQuality.GOOD: (150, 188, 75),
                MoveQuality.INACCURACY: (244, 191, 68),
                MoveQuality.MISTAKE: (229, 143, 42),
                MoveQuality.BLUNDER: (179, 52, 48),
                MoveQuality.MISS: (255, 94, 94),
            }
        self.quality_symbols = quality_symbols
        if quality_symbols is None:
            self.quality_symbols = {
                MoveQuality.BRILLIANT: "!!",
                MoveQuality.GREAT: "!",
                MoveQuality.BEST: "★",
                MoveQuality.BOOK: "B",
                MoveQuality.GOOD: "✓",
                MoveQuality.INACCURACY: "?!",
                MoveQuality.MISTAKE: "?",
                MoveQuality.BLUNDER: "??",
                MoveQuality.MISS: "∅",
            }
        self.auto_queen_promotion = auto_queen_promotion
        # Mouse bindings
        self.canvas.bind("<Button-1>", self._tk_left_click)
        self.canvas.bind("<Button-3>", self._tk_right_down)
        self.canvas.bind("<B3-Motion>", self._tk_right_motion)
        self.canvas.bind("<B1-Motion>", self._tk_left_motion)
        self.canvas.bind("<ButtonRelease-3>", self._tk_right_up)
        self.canvas.bind("<ButtonRelease-1>", self._tk_left_up)
        # Initial render
        self.redraw()

    @property
    def legal_moves(self):
        return self.board.legal_moves

    def piece_at(self, *args, **kwargs):
        return self.board.piece_at(*args, **kwargs)

    @property
    def fen(self):
        return self.board.fen

    @staticmethod
    def _ease_out_quad(t: float) -> float:
        """Ease-out quadratic: t in [0,1] -> [0,1]."""
        return 1 - (1 - t) * (1 - t)

    @staticmethod
    def map_pieces_for_animation(from_: chess.Board, to: chess.Board):
        """
        This module contains a static method that maps the pieces moved from one chess board to another for animation purposes.

        **Static Method Summary:**
        `map_pieces_for_animation(from_: chess.Board, to: chess.Board) -> List[Tuple[Square, Square]]`

        - **Parameters:**
          - `from_`: The initial state of the chess board.
          - `to`: The final state of the chess board after a move.

        - **Return:**
          - A list of tuples, where each tuple contains the source square and the target square for which a piece has moved from one board to another.

        This method is useful for visualizing how pieces are moving during a game of chess by identifying which squares have had changes in their occupancy between the initial and final states.
        """
        moves_for_animation = []
        cur = [i for i in from_.piece_map().items() if i not in to.piece_map().items()]
        tar = [i for i in to.piece_map().items() if i not in from_.piece_map().items()]
        for sq, trg in tar:
            found = None
            for sr, curr in cur:
                if curr == trg:
                    found = sr, curr
                    break
            if found is not None:
                moves_for_animation.append((found[0], sq))
                cur.remove(found)
        return moves_for_animation

    @staticmethod
    def rgb_to_hex(col):
        """Convert an (r,g,b) tuple to a hex color string, or return string as-is."""
        if isinstance(col, str):
            return col
        r, g, b = col
        return f"#{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def row_col_of(square):
        """Return (row, col) used for drawing rectangles from a chess.Square.
        Drawing uses top-left origin where row 0 is top of the canvas.
        """
        return 7 - chess.square_rank(square), chess.square_file(square)

    def _frames_for_duration(self, duration: Optional[float] = None) -> int:
        """
        The `_frames_for_duration` method calculates the number of frames needed for a given duration based on the animation's frame rate.

        Parameters:
            duration (Optional[float]): The duration in seconds. Defaults to the animation's duration if not provided.

        Returns:
            int: The number of frames required for the specified duration.
        """
        duration = self.animation_duration if duration is None else duration
        return max(1, int(round(duration * self.animation_fps)))

    def start_animation(self, from_square, to_square, at_end, callback=False, callback_data=None):
        """
        The `start_animation` method starts the animation process for moving a piece on the board. It takes the starting square (`from_square`), destination square (`to_square`), whether to animate at the end (`at_end`), and optional callback function and data as parameters.

        Parameters:
        - from_square: The starting position of the piece being animated.
        - to_square: The target position where the piece will be moved.
        - at_end: A boolean indicating whether the animation should play at the end of its duration.
        - callback (optional): A function to call when the animation completes. Must accept one argument (`data`).
        - callback_data (optional): Data to pass to the callback function.

        Returns:
        - None
        """
        piece = self.piece_at(from_square)
        if piece is None: return

        frames = self._frames_for_duration()
        data = {
            "at_end": at_end,
            "from_square": from_square,
            "to_square": to_square,
            "piece_symbol": self.UNICODE_PIECES[piece.symbol()],
            "frames": frames,
            "frame": 0,
            "callback": callback,
            "callback_data": callback_data
        }
        self._anim_data.append(data)
        # recalc interval in case fps changed
        self._anim_frame_interval_ms = int(1000 / max(1, self.animation_fps))
        # schedule first frame
        if len(self._anim_data) == 1:
            self._schedule_next_frame()

    def _schedule_next_frame(self):
        """
        Schedules the next frame of animation if there is anim data.
        """
        if not self._anim_data:
            return
        # ensure previous after id cleared
        if self._anim_after_id:
            self.after_cancel(self._anim_after_id)
            self._anim_after_id = None
        self._anim_after_id = self.after(self._anim_frame_interval_ms, self._animate_step)

    def _animate_step(self):
        """One animation tick; commit move when finished."""
        self._anim_after_id = None
        if not self._anim_data:
            return
        i = 0
        while i < len(self._anim_data):
            self._anim_data[i]["frame"] += 1
            frame = self._anim_data[i]["frame"]
            frames = self._anim_data[i]["frames"]

            if frame >= frames:

                self._anim_data[i].get("at_end")()
                if self._anim_data[i].get("callback"):
                    self._trigger_callback(self._anim_data[i].get("callback_data"))

                self._anim_data.remove(self._anim_data[i])
            else:
                i += 1
        self.redraw()
        if self._anim_data:
            self._schedule_next_frame()
            return

    def _re_configure(self, e):
        if e.widget is not self: return
        new_size = min(e.height, e.width) - self.border_frame["border"] * 2 - self["border"] * 2
        self.canvas.config(height=new_size, width=new_size)
        self.board_size = new_size
        self.square_size = self.board_size / 8
        if self.font["size"] != (new_value := int(self.square_size * 0.6)):
            self.font.config(size=new_value)
        self.redraw()

    def _tk_left_click(self, event):
        """
        Left click: handle promotion selection or select/move click flow.
        Dragging is started here if enabled.
        """
        if self.allow_drawing:
            self.clear_user_draw()
            self.redraw()
        if not self.allow_input:
            return
        if self.auto_stop_animation:
            self.stop_animation()
        elif self._anim_data:
            return

        x, y = event.x, event.y

        # If promotion dialog active, check which promo button was clicked
        if self._promotion_active:
            self._promotion_active = False
            for b_bbox, promo in self._promotion_buttons:
                x1, y1, x2, y2 = b_bbox
                if x1 <= x <= x2 and y1 <= y <= y2:
                    if self._waiting_move:
                        self.make_move(self._waiting_move.from_square, self._waiting_move.to_square, promo)
                        self._waiting_move = None
                    break
        else:
            square = self.square_at(x, y)
            if square is None:
                return

            # Try to complete a move if a square was previously selected
            if self._selected_square is not None and self.make_move(self._selected_square, square):
                self._selected_square = None
            else:
                # Otherwise select piece under cursor if it belongs to side to move
                self._selected_square = None
                piece = self.piece_at(square)
                if piece and piece.color == self.board.turn:
                    self._selected_square = square
                    # start dragging visualization if allowed
                    if self.allow_dragging:
                        self._dragging_piece = piece
                        center_x, center_y = self.square_center(square)
                        self._dragging_offset = (center_x - event.x, center_y - event.y)
                        self._show_selected()
                        self.redraw()
                        self.canvas.create_text(event.x + self._dragging_offset[0],
                                                event.y + self._dragging_offset[1],
                                                text=self.UNICODE_PIECES[self._dragging_piece.symbol()],
                                                font=self.font, fill="black")
                        return

        self._show_selected()
        self.redraw()

    def _tk_right_down(self, event):
        """Start right-click annotation (arrow/circle)."""
        if not self.allow_drawing:
            return
        if self.auto_stop_animation: self.stop_animation()
        x, y = event.x, event.y
        if self.square_at(x, y) is not None:
            self._right_click_start = x, y
            self._right_click_end = self._right_click_start
        self.redraw()

    def _tk_right_motion(self, event):
        """Update right-click annotation preview while dragging."""
        x, y = event.x, event.y
        if not self._right_click_start:
            return
        end_square = self.square_at(x, y)
        if end_square is not None:
            self._right_click_end = x, y
        self.redraw()

    def _tk_left_motion(self, event):
        """Show dragging piece while left button is held and dragging is enabled."""
        if not self.allow_input:
            return
        if not self._dragging_piece:
            return
        self.redraw()
        self.canvas.create_text(event.x + self._dragging_offset[0],
                                event.y + self._dragging_offset[1],
                                text=self.UNICODE_PIECES[self._dragging_piece.symbol()],
                                font=self.font, fill="black")

    def _tk_right_up(self, event):
        """Complete a right-click annotation: circle (same square) or arrow (different squares)."""
        x, y = event.x, event.y
        if self._right_click_start:
            start_square = self.square_at(*self._right_click_start)
            end_square = self.square_at(x, y)
            if start_square is not None and end_square is not None:
                start_row, start_col = 7 - chess.square_rank(start_square), chess.square_file(start_square)
                end_row, end_col = 7 - chess.square_rank(end_square), chess.square_file(end_square)
                if start_square == end_square:
                    self.draw_circle(start_row, start_col, self.circle_color, int(self.square_size / 2.1),
                                     self.circle_width)
                else:
                    self.draw_arrow(start_row, start_col, end_row, end_col, self.arrow_color, self.arrow_width)

        self._right_click_start = None
        self._right_click_end = None
        self.redraw()

    def _tk_left_up(self, event):
        """Finish dragging a piece (if any) and attempt to perform the move."""
        if not self.allow_input:
            return
        if self.allow_drawing:
            self.clear_user_draw()
        if self._dragging_piece is None:
            return
        to_square = self.square_at(event.x + self._dragging_offset[0], event.y + self._dragging_offset[1])
        if to_square is not None:
            if self.make_move(self._selected_square, to_square, callback=True, animate=False):
                self._selected_square = None
        self._dragging_piece = None
        self._show_selected()
        self.redraw()

    def _get_arrow_cords(self, x1, x2, y1, y2, arrow_size=None, arrow_angle=35):
        if arrow_size is None:
            arrow_size = self.square_size / 2
        dx = x2 - x1
        dy = y2 - y1
        angle = math.atan2(dy, dx)
        arrow_angle = math.radians(arrow_angle)
        left = (
            x2 - arrow_size * math.cos(angle - arrow_angle),
            y2 - arrow_size * math.sin(angle - arrow_angle)
        )
        right = (
            x2 - arrow_size * math.cos(angle + arrow_angle),
            y2 - arrow_size * math.sin(angle + arrow_angle)
        )
        return left, right

    def _draw_arrow(self, start, end, color=(255, 0, 0), width=2):
        """Draw an arrow between two canvas pixel coordinates."""
        color_hex = self.rgb_to_hex(color)
        x1, y1 = start
        x2, y2 = end
        self.canvas.create_line(x1, y1, x2, y2, width=width, fill=color_hex, smooth=True)
        left, right = self._get_arrow_cords(x1, x2, y1, y2)
        self.canvas.create_line(x2, y2, left[0], left[1], width=width, fill=color_hex, smooth=True)
        self.canvas.create_line(x2, y2, right[0], right[1], width=width, fill=color_hex, smooth=True)

    def _draw_coordinates(self):
        """Draw board coordinates (a-h and 1-8) around the board."""
        if not self.show_coordinates:
            return
        font_size = int(max(6, self.square_size // 5))
        coord_font = tkinter.font.Font(size=font_size)
        for i in range(8):
            # letters a-h
            letter_index = i if not self.flipped else 7 - i
            letter = chr(ord('a') + letter_index)
            x = i * self.square_size
            y = self.board_size - font_size - 10
            self.canvas.create_text(x, y, text=letter, anchor="nw", font=coord_font, fill="black")

            # numbers 1-8
            number_index = 7 - i if not self.flipped else i
            number = str(number_index + 1)
            x = 2
            y = i * self.square_size + 2
            self.canvas.create_text(x, y, text=number, anchor="nw", font=coord_font, fill="black")

    def _draw_promotion_dialog(self):
        """Render a simple promotion chooser in the center of the board."""
        w, h = 320, 80
        x = (self.board_size - w) // 2
        y = (self.board_size - h) // 2
        self.canvas.create_rectangle(x, y, x + w, y + h, outline=self.rgb_to_hex((230, 230, 230)), width=2)
        options = [
            (chess.QUEEN, "♕"),
            (chess.ROOK, "♖"),
            (chess.BISHOP, "♗"),
            (chess.KNIGHT, "♘"),
        ]
        gap = 15
        size = 60
        bx = x + gap
        by = y + (h - size) // 2

        self._promotion_buttons = []
        for promo, symbol in options:
            x1 = bx
            y1 = by
            x2 = bx + size
            y2 = by + size
            self.canvas.create_rectangle(x1, y1, x2, y2, fill="white", outline="black", width=1)
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            self.canvas.create_text(cx, cy, text=symbol, font=self.font, fill="black")
            self._promotion_buttons.append(((x1, y1, x2, y2), promo))
            bx += size + gap

    def _draw_temp_arrow_or_circle(self):
        """Draw preview arrow / circle while right-click dragging."""
        if self._right_click_end and self._right_click_start:
            start_x, start_y = self._right_click_start
            end_x, end_y = self._right_click_end
            start_square = self.square_at(start_x, start_y)
            end_square = self.square_at(end_x, end_y)
            if start_square is not None and end_square is not None:
                if start_square == end_square:
                    center = self.square_center(start_square)
                    r = int(self.square_size // 2.1)
                    self.canvas.create_oval(center[0] - r, center[1] - r, center[0] + r, center[1] + r,
                                            outline=self.rgb_to_hex(self.circle_color), width=self.circle_width)
                else:
                    start = self.square_center(start_square)
                    end = self.square_center(end_square)
                    self._draw_arrow(start, end, self.arrow_color, self.arrow_width)

    def _draw_squares(self):
        """Draw the 8x8 checkerboard squares."""
        fr, fc = (-1, -1) if self.highlighted_move is None else self.row_col_of(self.highlighted_move.from_square)
        tr, tc = (-1, -1) if self.highlighted_move is None else self.row_col_of(self.highlighted_move.to_square)
        if self.flipped:
            fr, fc = 7 - fr, 7 - fc
            tr, tc = 7 - tr, 7 - tc
        for r in range(8):
            for c in range(8):
                if (r, c) == (fr, fc):
                    color = self.from_color
                elif (r, c) == (tr, tc):
                    color = self.to_color
                else:
                    color = self.white_bg if (r + c) % 2 == 0 else self.black_bg
                x1 = c * self.square_size
                y1 = r * self.square_size
                x2 = x1 + self.square_size
                y2 = y1 + self.square_size
                self.canvas.create_rectangle(x1, y1, x2, y2, fill=self.rgb_to_hex(color), width=0)

        if not self.highlighted_move: return

    def _draw_highlights(self):
        for r, c, color in [*self.user_highlights, *self.system_highlights]:
            if self.flipped:
                r, c = 7 - r, 7 - c
            x1 = c * self.square_size
            y1 = r * self.square_size
            x2 = x1 + self.square_size
            y2 = y1 + self.square_size
            self.canvas.create_rectangle(x1, y1, x2, y2, outline=self.rgb_to_hex(color), width=3)

    def _draw_pieces(self):
        """Draw all pieces on the board using Unicode symbols."""
        special = [*[self.row_col_of(i["from_square"]) for i in self._anim_data]]
        if self._selected_square and self._dragging_piece:
            special.append(self.row_col_of(self._selected_square))
        for r in range(8):
            for c in range(8):
                square = chess.square(c, 7 - r)
                piece = self.piece_at(square)
                if (r, c) in special: continue
                if piece:
                    symbol = DisplayBoard.UNICODE_PIECES[piece.symbol()]
                    draw_r, draw_c = r, c
                    if self.flipped:
                        draw_r, draw_c = 7 - r, 7 - c
                    x_center = draw_c * self.square_size + self.square_size // 2
                    y_center = draw_r * self.square_size + self.square_size // 2
                    self.canvas.create_text(x_center, y_center, text=symbol, font=self.font, fill="black")

    def _draw_circles(self):
        for r, c, color, radius, width in [*self.user_circles, *self.system_circles]:
            rr, cc = r, c
            if self.flipped:
                rr, cc = 7 - r, 7 - c
            center_x = cc * self.square_size + self.square_size / 2
            center_y = rr * self.square_size + self.square_size / 2
            self.canvas.create_oval(center_x - radius, center_y - radius,
                                    center_x + radius, center_y + radius,
                                    outline=self.rgb_to_hex(color), width=width)

    def _draw_arrows(self):
        for fr, fc, tr, tc, color, width in [*self.user_arrows, *self.system_arrows]:
            fr2, fc2, tr2, tc2 = fr, fc, tr, tc
            if self.flipped:
                fr2, fc2 = 7 - fr, 7 - fc
                tr2, tc2 = 7 - tr, 7 - tc
            start = (fc2 * self.square_size + self.square_size // 2,
                     fr2 * self.square_size + self.square_size // 2)
            end = (tc2 * self.square_size + self.square_size // 2,
                   tr2 * self.square_size + self.square_size // 2)
            self._draw_arrow(start, end, color=color, width=width)

    def _get_move_quality_draw_info(self, color, symbol, square):

        row, col = self.row_col_of(square)
        if self.flipped:
            row, col = 7 - row, 7 - col

        pad = max(4, int(self.square_size * 0.08))
        radius = max(6, int(self.square_size * 0.18))

        cx = col * self.square_size + (self.square_size - pad - radius)
        cy = row * self.square_size + (pad + radius)

        bg_hex = self.rgb_to_hex(color)
        outline_hex = self.rgb_to_hex(tuple(max(0, min(255, int(c * 0.6))) for c in color))



        font_size = max(8, int(radius * 0.9))

        return radius,cx,cy,bg_hex,outline_hex,font_size

    def _draw_move_quality_badge(self):
        if not self._last_move_quality or not self.highlighted_move:
            return
        color = self.move_quality_colors.get(self._last_move_quality, (0, 0, 0))
        symbol = self.quality_symbols.get(self._last_move_quality, "error")

        radius,cx,cy,bg_hex,outline_hex,font_size = self._get_move_quality_draw_info(color, symbol, self.highlighted_move.to_square)

        self.canvas.create_oval(
            cx - radius, cy - radius, cx + radius, cy + radius,
            fill=bg_hex, outline=outline_hex, width=max(2, int(radius * 0.18))
        )
        self.canvas.create_text(cx, cy, text=symbol, font=self.font, fill="black")

    def _show_selected(self):
        """Highlight the selected square and optionally show legal move circles for that piece."""
        if self._selected_square is None:
            return
        self.highlight_square(self._selected_square, self.highlight_color, False)
        if self.show_legal:
            for move in self.legal_moves:
                if move.from_square == self._selected_square:
                    to_sq = move.to_square
                    r, c = 7 - chess.square_rank(to_sq), chess.square_file(to_sq)
                    self.draw_circle(r, c, self.legal_moves_circles_color, self.legal_moves_circles_radius,
                                     self.legal_moves_circles_width, False)

    def _trigger_callback(self, move):
        for cb in self._move_callbacks:
            cb(move, self)

    def _is_promotion(self, from_square, to_square) -> bool:
        """Return True if the move is a pawn promotion (destination rank for pawn)."""
        piece = self.piece_at(from_square)
        if not piece or piece.piece_type != chess.PAWN:
            return False
        rank_to = chess.square_rank(to_square)
        if (piece.color == chess.WHITE and rank_to == 7) or (piece.color == chess.BLACK and rank_to == 0):
            return True
        return False

    def _get_move_animation_function(self, move):
        def foo():
            self.board.push(move)
            self.highlight_move(move)
            self.redraw()

        return foo

    def _pop_animation_function(self):
        self.clear_user_draw()
        self.board.pop()
        self.clear_last_move_quality()
        if self.board.move_stack:
            self.highlighted_move = self.board.move_stack[-1]
        else:
            self.highlighted_move = None
        self.redraw()

    def _get_castling_details(self, move: chess.Move):
        if not self.board.is_castling(move): return None
        king_from = move.from_square
        rank = chess.square_rank(king_from)
        if self.board.is_kingside_castling(move):
            king_to = chess.square(6, rank)
            rook_from = chess.square(7, rank)
            rook_to = chess.square(5, rank)
        else:
            king_to = chess.square(2, rank)
            rook_from = chess.square(0, rank)
            rook_to = chess.square(3, rank)
        return (king_from, king_to), (rook_from, rook_to)

    def undo(self):
        """
        Undo the last move.

        • Animation-aware
        • Preserves redo stack
        • Safe to call repeatedly
        """
        if not self.board.move_stack: return False
        self.stop_animation()
        if self.allow_animation:
            self.redo_stack.append(self.pop_animation())
        else:
            self.redo_stack.append(self.pop())
        return True

    def redo(self, callback=True):
        """
        Redo the last undone move.

        • Respects animation settings
        • Restores board highlights
        """
        if not self.redo_stack: return False
        self.stop_animation()
        if self.allow_animation:
            if move := self.redo_stack.pop():
                self.start_move_animation(move, callback)
        else:
            self.push(self.redo_stack.pop(), callback)
        return True

    def clear_redo_stack(self):
        self.redo_stack = []

    def redraw(self):
        """Clear canvas and redraw the entire board, overlays and optional custom drawing."""
        self.canvas.delete("all")
        self._draw_squares()
        self._draw_highlights()
        self._draw_pieces()
        self._draw_move_quality_badge()
        self._draw_circles()
        self._draw_arrows()
        self._draw_coordinates()
        self._draw_temp_arrow_or_circle()
        if self._promotion_active:
            self._draw_promotion_dialog()
        if self.draw_function:
            # Optional user-supplied drawing hook: draw_function(self)
            self.draw_function(self)

        if not self._anim_data:
            return
        for ad in self._anim_data:
            frm = ad["from_square"]
            to = ad["to_square"]
            frame = ad["frame"]
            frames = ad["frames"]
            symbol = ad["piece_symbol"]

            # compute centers
            cx_from, cy_from = self.square_center(frm)
            cx_to, cy_to = self.square_center(to)

            # Normalise t in [0,1]. Use frames-1 so final frame lands exactly on dest.
            t = min(1.0, max(0.0, frame / max(1, frames - 1))) if frames > 1 else 1.0
            t_eased = self._ease_out_quad(t)

            cur_x = cx_from + (cx_to - cx_from) * t_eased
            cur_y = cy_from + (cy_to - cy_from) * t_eased

            # draw moving piece on top
            self.canvas.create_text(int(cur_x), int(cur_y), text=symbol, font=self.font, fill="black")

    def stop_animation(self):
        if not self._anim_data: return
        for i in self._anim_data:
            i["at_end"]()
            if i["callback"]:
                self._trigger_callback(i["callback_data"])
        self._anim_data = []

    def clear_last_move_quality(self):
        self._last_move_quality: Optional[MoveQuality] = None

    def set_move_quality(self, quality: Optional[MoveQuality]):
        """
        Attach a visual quality marker to the most recent move.

        This method is UI-only and does not affect the board state.
        Intended to be used by analysis systems.

        Examples:
        • BRILLIANT (!!)
        • MISTAKE (?)
        • BLUNDER (??)
        """
        self._last_move_quality = quality
        self.after(0, self.redraw)

    def clear_user_draw(self, highlights: bool = True, circles: bool = True, arrows: bool = True,last_move: bool = False):
        """Clear overlay lists selectively."""

        if highlights:
            self.user_highlights = []
        if arrows:
            self.user_arrows = []
        if circles:
            self.user_circles = []
        if last_move:
            self.highlighted_move = None

    def push(self, move: Move, callback: bool = False) -> None:
        """Push a move to the underlying chess.Board and update display."""
        self.stop_animation()
        self.board.push(move)
        self.highlight_move(move)
        if callback: self._trigger_callback(move)
        self.redraw()

    def start_move_animation(self, move_: chess.Move, callback: bool = True):
        """
        Animate a legal move on the board.
        """
        # cancel any existing animation and commit its move first (stop_animation)
        self.clear_user_draw()

        # if animations disabled -> immediate push
        if not self.allow_animation:
            self.push(move_)
            self.redraw()
            return
        if cd := self._get_castling_details(move_):
            self.start_animation(cd[1][0], cd[1][1], self._get_move_animation_function(move_), callback, move_)
            self.start_animation(cd[0][0], cd[0][1], lambda: None, False, None)

        else:
            from_sq = move_.from_square
            to_sq = move_.to_square
            self.start_animation(from_sq, to_sq, self._get_move_animation_function(move_), callback, move_)

    def pop(self) -> Move:
        """Pop last move from the board, clear overlays and update display."""
        self.stop_animation()
        self.clear_user_draw()
        move = self.board.pop()
        self.clear_last_move_quality()
        if self.board.move_stack:
            self.highlighted_move = self.board.move_stack[-1]
        else:
            self.highlighted_move = None
        self.redraw()
        return move

    def pop_animation(self) -> chess.Move | None:
        self.stop_animation()
        if not self.board.move_stack:
            return None
        move = self.board.pop()
        self.board.push(move)
        self.start_animation(move.to_square, move.from_square, self._pop_animation_function, False)
        return move

    def clone_board(self) -> chess.Board:
        """
        Return a detached copy of the current board state.

        This method is safe to use for:
        • Engine analysis
        • Background evaluation
        • PGN reconstruction
        • External inspection

        The returned board shares NO mutable state with the widget.
        """
        return self.board.copy()

    def make_move(self, from_square, to_square, promo_piece=None, callback: bool = True, animate: bool = True) -> Optional[chess.Move]:
        """
        Attempt to execute a move from one square to another.

        The move is:
        • Validated against legal moves
        • Optionally animated
        • Pushed to the internal board
        • Highlighted visually
        • Emitted via callbacks

        Promotion is handled automatically via an in-board dialog.

        Returns
        -------
        chess.Move
            If the move was legal and executed.
        None
            If the move was illegal or awaiting promotion choice.
        """
        self.stop_animation()
        if from_square is None or to_square is None:
            return None
        # If promotion needed and promotion not yet chosen, set waiting move and show dialog
        if promo_piece is None and self._is_promotion(from_square, to_square) and chess.Move(from_square, to_square,
                                                                                             chess.QUEEN) in self.legal_moves:
            if self.auto_queen_promotion:
                promo_piece = chess.QUEEN
            else:
                self._waiting_move = chess.Move(from_square, to_square)
                self._promotion_active = True
                return None
        move = chess.Move(from_square, to_square, promotion=promo_piece)
        if move in self.legal_moves:
            if not self.allow_animation or not animate:
                self.push(move)
                if callback:
                    self._trigger_callback(move)
                return move
            self.start_move_animation(move, callback)

            return move
        return None

    def square_at(self, x: int, y: int) -> Optional[chess.Square]:
        """
        Convert canvas pixel coordinates to chess.Square.

        Returns None if coordinates are outside the board.
        """
        if x < 0 or y < 0 or x >= self.board_size or y >= self.board_size:
            return None
        col = int(x // self.square_size)
        row = int(y // self.square_size)
        if self.flipped:
            col, row = 7 - col, 7 - row
        return chess.square(col, 7 - row)

    def on_move(self, callback: Callable[[chess.Move, "DisplayBoard"], None]):
        """Register a callback(move, board) called after each executed move."""
        self._move_callbacks.append(callback)

    def square_center(self, square: chess.Square) -> Tuple[int, int]:
        """
        Return the canvas pixel coordinates of the center of the given square.
        Handles flipped orientation.
        """
        col = chess.square_file(square)
        row = chess.square_rank(square)
        if self.flipped:
            col = 7 - col
            row = 7 - row
        center_x = col * self.square_size + self.square_size // 2
        center_y = (7 - row) * self.square_size + self.square_size // 2
        return center_x, center_y

    def flip_board(self):
        """Toggle board orientation and redraw."""
        self.stop_animation()
        self.flipped = not self.flipped
        self.redraw()

    def highlight_square(self, square: chess.Square, color, delete: bool = True, is_user: bool = True):
        """Highlights a given chess square on the board.

        Parameters:
        - square (chess.Square): The chess square to be highlighted.
        - color (str): The color of the highlight ('black' or 'white').
        - delete (bool): If True, removes the highlight if it exists; otherwise, adds it. Defaults to True.
        - is_user (bool): Determines whether this is a user-highlighted square or a system-highlighted one.

        This method updates the highlights list based on the provided parameters. It checks if
        the specified square and color combination already exists in the appropriate highlights list
        (user_highlights or system_highlights) and adds/removes it accordingly.
        """
        row, col = self.row_col_of(square)
        item = (row, col, color)
        list_ = self.user_highlights if is_user else self.system_highlights
        if item not in list_:
            list_.append(item)
        elif delete:
            list_.remove(item)

    def highlight_move(self, move: chess.Move):
        """
        Highlights a specific chess move on the board.

        Args:
            move (chess.Move): The chess move to be highlighted.

        Returns:
            None
        """
        self.highlighted_move = move
        self.redraw()

    def draw_circle(self, row: int, col: int, color, radius: int, width: int, delete: bool = True, is_user=True):
        """
        Draw or remove a circle on the screen.

        Parameters:
            row (int): The y-coordinate of the top-left corner of the circle.
            col (int): The x-coordinate of the top-left corner of the circle.
            color: The color of the circle. Can be a string representing a color name or an RGB tuple.
            radius (int): The radius of the circle in pixels.
            width (int): The thickness of the circle's border in pixels. If 0, no border will be drawn.
            delete (bool): If True, remove the existing circle at the specified position; otherwise, draw a new one.
            is_user (bool): Indicates whether the drawing operation should affect user circles or system circles. Default is True.

        Notes:
            This method allows for drawing and removing circles on the screen. It maintains separate lists of
            user and system circles to differentiate between them.

            If the circle is not currently present in the list, it will be appended. If delete is set to True,
            and the circle is already present, it will be removed from the list.
        """
        item = (row, col, color, radius, width)
        list_ = self.user_circles if is_user else self.system_circles
        if item not in list_:
            list_.append(item)
        elif delete:
            list_.remove(item)

    def draw_arrow(self, from_row: int, from_col: int, to_row: int, to_col: int, color, width: int, delete: bool = True, is_user=True):
        """
        Draws an arrow on the game board.

        Parameters:
            from_row (int): The starting row of the arrow.
            from_col (int): The starting column of the arrow.
            to_row (int): The ending row of the arrow.
            to_col (int): The ending column of the arrow.
            color: The color of the arrow.
            width (int): The width of the arrow.
            delete (bool): If True, deletes the existing arrow if it exists, otherwise it draw it. Defaults to True.
            is_user (bool): If True, draws an arrow for a user; otherwise, draws a system arrow. Defaults to True.

        Returns:
            None
        """
        item = (from_row, from_col, to_row, to_col, color, width)
        list_ = self.user_arrows if is_user else self.system_arrows
        if item not in list_:
            list_.append(item)
        elif delete:
            list_.remove(item)

    def set_fen(self, fen: str):
        """Set position by FEN and refresh overlays and display."""
        self.stop_animation()
        self.board.set_fen(fen)
        self.clear_user_draw()
        self.highlighted_move = None
        self._selected_square = None
        self.clear_last_move_quality()
        self.redraw()

    def set_fen_with_animation(self, fen: str, callback: Callable = lambda: None):
        """Set position by FEN and refresh overlays and display."""
        self.stop_animation()
        self.clear_user_draw()
        self.highlighted_move = None
        self._selected_square = None
        self.clear_last_move_quality()
        a = self.map_pieces_for_animation(self.clone_board(), chess.Board(fen=fen))
        if not a:
            self.set_fen(fen)
        else:
            for f, t in a[:-1]:
                self.start_animation(f, t, lambda: None, False, None)
            self.start_animation(a[-1][0], a[-1][1],
                                 lambda: [self.board.set_fen(fen), self.redraw(), callback()],
                                 False, None)

    def generate_svg(self, highlights: bool = True, circles: bool = True, arrows: bool = True,last_move:bool = True,quality:bool = True) -> str:
        """Draw the board as SVG."""
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.board_size}" height="{self.board_size}">\n'

        # Draw squares
        for r in range(8):
            for c in range(8):
                color = self.white_bg if (r + c) % 2 == 0 else self.black_bg
                x = c * self.square_size
                y = r * self.square_size
                hex_color = self.rgb_to_hex(color)
                svg += f'<rect x="{x}" y="{y}" width="{self.square_size}" height="{self.square_size}" fill="{hex_color}" />\n'

        if last_move and self.highlighted_move:
            r,c = self.row_col_of(self.highlighted_move.from_square)
            svg += f'<rect x="{c * self.square_size}" y="{r * self.square_size}" width="{self.square_size}" height="{self.square_size}" fill="{self.rgb_to_hex(self.from_color)}" />\n'
            r, c = self.row_col_of(self.highlighted_move.to_square)
            svg += f'<rect x="{c * self.square_size}" y="{r * self.square_size}" width="{self.square_size}" height="{self.square_size}" fill="{self.rgb_to_hex(self.to_color)}" />\n'


        if highlights:
            # Draw highlights
            for r, c, color in [*self.user_highlights, *self.system_highlights]:
                rr, cc = (7 - r, 7 - c) if self.flipped else (r, c)
                x = cc * self.square_size
                y = rr * self.square_size
                hex_color = self.rgb_to_hex(color)
                svg += f'<rect x="{x}" y="{y}" width="{self.square_size}" height="{self.square_size}" fill="none" stroke="{hex_color}" stroke-width="3"/>\n'

        # Draw pieces (as text)
        font_size = int(self.square_size * 0.7)
        for r in range(8):
            for c in range(8):
                square = chess.square(c, 7 - r)
                piece = self.piece_at(square)
                if piece:
                    rr, cc = (7 - r, 7 - c) if self.flipped else (r, c)
                    cx = cc * self.square_size + self.square_size / 2
                    cy = rr * self.square_size + self.square_size / 2
                    symbol = self.UNICODE_PIECES[piece.symbol()]
                    svg += f'<text x="{cx}" y="{cy}" font-size="{font_size}" text-anchor="middle" dominant-baseline="middle">{symbol}</text>\n'

        if circles:
            # Draw circles
            for r, c, color, radius, width in [*self.user_circles, *self.system_circles]:
                rr, cc = (7 - r, 7 - c) if self.flipped else (r, c)
                cx = cc * self.square_size + self.square_size / 2
                cy = rr * self.square_size + self.square_size / 2
                hex_color = self.rgb_to_hex(color)
                svg += f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{hex_color}" stroke-width="{width}"/>\n'

        if arrows:
            # Draw arrows
            for fr, fc, tr, tc, color, width in [*self.user_arrows, *self.system_arrows]:
                fr, fc = (7 - fr, 7 - fc) if self.flipped else (fr, fc)
                tr, tc = (7 - tr, 7 - tc) if self.flipped else (tr, tc)
                x1 = fc * self.square_size + self.square_size / 2
                y1 = fr * self.square_size + self.square_size / 2
                x2 = tc * self.square_size + self.square_size / 2
                y2 = tr * self.square_size + self.square_size / 2
                hex_color = self.rgb_to_hex(color)
                left, right = self._get_arrow_cords(x1, x2, y1, y2)

                svg += (
                    f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{hex_color}" stroke-width="{width}"/>\n'
                    f'<line x1="{x2}" y1="{y2}" x2="{left[0]}" y2="{left[1]}" stroke="{hex_color}" stroke-width="{width}"/>\n'
                    f'<line x1="{x2}" y1="{y2}" x2="{right[0]}" y2="{right[1]}" stroke="{hex_color}" stroke-width="{width}"/>\n'
                )


        if quality and self._last_move_quality and self.highlighted_move:
            color = self.move_quality_colors.get(self._last_move_quality, (0, 0, 0))
            symbol = self.quality_symbols.get(self._last_move_quality, " ")
            radius,cx,cy,bg_hex,outline_hex,font_size = self._get_move_quality_draw_info(color,symbol,self.highlighted_move.to_square)
            svg += f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="{bg_hex}" stroke="{outline_hex}" stroke-width="{max(2, int(radius * 0.18))}"/>\n'
            svg += f'<text x="{cx}" y="{cy}" font-family="Arial" font-size="{max(8, int(radius * 0.9))}" fill="black" text-anchor="middle" dominant-baseline="middle">{symbol}</text>\n'
        svg += "</svg>"
        return svg

    def export_svg(self, path: str, highlights: bool = True, circles: bool = True, arrows: bool = True,last_move:bool = True,quality:bool = True) -> bool:
        """Export the board as SVG."""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self.generate_svg(highlights, circles, arrows,last_move,quality))
            return True
        except OSError:
            return False

    def set_readonly(self, value: bool):
        self.allow_input = not value
        self.allow_dragging = not value
        self.allow_drawing = not value
        self._dragging_offset = (0, 0)
        self._dragging_piece = None
        self._promotion_active = False
        self._waiting_move = None
        self.redraw()

    def safe_redraw(self):
        return self.after(0, self.redraw)

    def set_board(self, board: chess.Board, animate: bool = False, callback=None):
        """
        Replace the current board with a full copy of `board`.

        :param board: chess.Board to copy from
        :param animate: if True, animate the transition (if supported)
        :param callback: optional function called after update completes
        """

        new_board = board.copy(stack=False)

        if not animate:
            self.board = new_board
            self.redraw()
            if callback:
                callback()
            return
        self.board = new_board

        def finish():
            self.redraw()
            if callback:
                callback()

        self.set_fen_with_animation(new_board.fen(), finish)


if __name__ == '__main__':

    import sys

    # Example usage: run the module and pass an optional FEN on command line.
    root = tk.Tk()
    d = DisplayBoard(root, input_callback=lambda move, b: print(move), border=5, border_bg="#000",
                     auto_stop_animation=True)
    d.flip_board()
    d.pack(expand=True, fill="both", side="left")


    def reset():
        """Resets the chess board to its starting position with an animation."""
        d.set_fen_with_animation(d.board.starting_fen)


    def undo():
        if d.undo():
            d.allow_input = False


    def redo():
        if d.redo():
            d.allow_input = not d.redo_stack


    root.bind("<Return>", lambda e: reset())
    tk.Button(d, text="<", command=undo, bg="#ccc").pack(side="left", fill="both", expand=True)
    tk.Button(d, text=">", command=redo, bg="#ccc").pack(side="right", fill="both", expand=True)
    if len(sys.argv) > 1:
        d.set_fen(sys.argv[1])
        d.update()

    anim_board = DisplayBoard(root,

                              legal_moves_circles_color=(180, 255, 200),
                              from_color=(200, 230, 200),
                              to_color=(200, 230, 200),
                              #animation_fps=240
                              )
    anim_board.set_readonly(True)
    anim_board.config(bd=15, background="black")
    anim_board.pack(expand=True, fill="both", side="right")
    example_moves = ["e2e4", "e7e5", "g1f3", "f7f6", "f3e5", "f6e5", "d1h5", "e8e7", "h5e5", "e7f7", "f1c4", "d7d5",
                     "c4d5", "f7g6", "d2d4", "g8f6", "e5g5"]
    qualities = [
        MoveQuality.BOOK,
        MoveQuality.BOOK,
        MoveQuality.BOOK,
        MoveQuality.BLUNDER,
        MoveQuality.BRILLIANT,
        MoveQuality.MISTAKE,
        MoveQuality.BEST,
        MoveQuality.BLUNDER,
        MoveQuality.BEST,
        MoveQuality.GOOD,
        MoveQuality.GREAT,
        MoveQuality.BEST,
        MoveQuality.BEST,
        MoveQuality.INACCURACY,
        MoveQuality.BEST,
        MoveQuality.INACCURACY,
        MoveQuality.BEST
    ]


    def on_move(m, b):
        if m.uci() in example_moves:
            b.set_move_quality(qualities[example_moves.index(m.uci())])


    anim_board.on_move(on_move)


    def sample_animation_loop(index):
        if index == -1:
            anim_board.set_fen(anim_board.board.starting_fen)
            root.after(1000, sample_animation_loop, 0)
            return
        if index >= len(example_moves):
            root.after(5000, sample_animation_loop, -1)
            return
        m = chess.Move.from_uci(example_moves[index])
        anim_board.start_move_animation(m)

        root.after(1000, sample_animation_loop, index + 1)


    root.after(1000, sample_animation_loop, 0)
    root.mainloop()
