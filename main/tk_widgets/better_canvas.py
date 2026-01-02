import tkinter as tk

import cv2
import numpy as np
from PIL import Image, ImageTk


class SuperCanvas(tk.Label):
    def __init__(self, master, width, height, bg_color=(255, 255, 255)):
        self.w = width
        self.h = height
        self.bg_color_tuple = bg_color

        # אתחול ה-Label
        super().__init__(master, borderwidth=0, highlightthickness=0)

        # יצירת הבאפר (NumPy Matrix)
        self.buffer = np.full((height, width, 3), bg_color[::-1], dtype=np.uint8)
        self.clear()

    def _get_color(self, color):
        """המרת צבע (שם או RGB) לפורמט BGR של OpenCV"""
        standard_colors = {
            "white": (255, 255, 255), "black": (0, 0, 0),
            "red": (255, 0, 0), "green": (0, 255, 0),
            "blue": (0, 0, 255), "yellow": (255, 255, 0),
            "gray": (128, 128, 128), "purple": (128, 0, 128)
        }
        if isinstance(color, str):
            color = standard_colors.get(color.lower(), (0, 0, 0))
        return (color[2], color[1], color[0])  # RGB -> BGR

    def clear(self):
        """מנקה את כל הקנבס לצבע הרקע"""
        self.buffer[:] = self._get_color(self.bg_color_tuple)

    def create_rectangle(self, x1, y1, x2, y2, fill=None, outline="black", width=1):
        """ציור מלבן - תואם API של Tkinter"""
        pt1, pt2 = (int(x1), int(y1)), (int(x2), int(y2))

        if fill:
            cv2.rectangle(self.buffer, pt1, pt2, self._get_color(fill), -1)
        if outline:
            cv2.rectangle(self.buffer, pt1, pt2, self._get_color(outline), int(width))

    def create_oval(self, x1, y1, x2, y2, fill=None, outline="black", width=1):
        """ציור אליפסה/עיגול"""
        center = (int((x1 + x2) / 2), int((y1 + y2) / 2))
        axes = (int(abs(x2 - x1) / 2), int(abs(y2 - y1) / 2))

        if fill:
            cv2.ellipse(self.buffer, center, axes, 0, 0, 360, self._get_color(fill), -1, cv2.LINE_AA)
        if outline:
            cv2.ellipse(self.buffer, center, axes, 0, 0, 360, self._get_color(outline), int(width), cv2.LINE_AA)

    def create_line(self, x1, y1, x2, y2, fill="black", width=1):
        """ציור קו (ב-Tkinter הפרמטר לצבע הוא 'fill')"""
        cv2.line(self.buffer, (int(x1), int(y1)), (int(x2), int(y2)),
                 self._get_color(fill), int(width), cv2.LINE_AA)

    def create_text(self, x, y, text, fill="black", font_size=0.5, thickness=1, anchor="sw"):
        """ציור טקסט וקטורי מהיר"""
        # OpenCV מצייר מהפינה השמאלית התחתונה כברירת מחדל
        cv2.putText(self.buffer, str(text), (int(x), int(y)),
                    cv2.FONT_HERSHEY_SIMPLEX, font_size, self._get_color(fill), int(thickness), cv2.LINE_AA)

    def update_now(self):
        """עדכון התצוגה הגרפית בחלון"""
        rgb_img = cv2.cvtColor(self.buffer, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb_img)
        self.tk_img = ImageTk.PhotoImage(image=img)
        self.config(image=self.tk_img)


# ---------------------------------------------------------
# דוגמת שימוש פשוטה ומקיפה
# ---------------------------------------------------------

def example_draw():
    sc.clear()

    # מלבן (רקע למבנה)
    sc.create_rectangle(50, 200, 250, 400, fill=(200, 200, 200), outline="black", width=2)

    # עיגול (חלון)
    sc.create_oval(100, 230, 200, 330, fill="blue", outline="white", width=3)

    # קווים (איקס על החלון)
    sc.create_line(100, 280, 200, 280, fill="white", width=2)
    sc.create_line(150, 230, 150, 330, fill="white", width=2)

    # טקסט
    sc.create_text(50, 180, "My Precise House", fill="black", font_size=0.8, thickness=2)

    # הדגמת אלפי פריטים מהירים (גשם)
    import random
    for _ in range(10000):
        x = random.randint(0, 800)
        y = random.randint(0, 600)
        sc.create_line(x, y, x + 2, y + 5, fill=(150, 150, 255))
    root.after(100, example_draw)
    sc.update_now()


if __name__ == "__main__":
    root = tk.Tk()
    root.title("Fast SuperCanvas API")

    sc = SuperCanvas(root, width=800, height=600, bg_color=(245, 245, 245))
    sc.pack(pady=20)

    example_draw()
    root.mainloop()
