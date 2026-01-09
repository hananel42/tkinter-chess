# smooth_color_frame_safe.py
import tkinter as tk
from PIL import Image, ImageTk, ImageFilter, ImageEnhance
import numpy as np
import threading
import time
import math
import gc

class SmoothColorFrame(tk.Frame):
    """
    Frame עם רקע צבעוני חלק, יעיל ובטוח מבחינת זיכרון.
    ניתן להכניס ילדים כרגיל (pack/grid/place).
    שימוש:
      scf = SmoothColorFrame(root, fps=20, low_res=48, speed=0.3, amplitude=0.12, blur=6)
      scf.pack(fill="both", expand=True)
      scf.start()
    שיטות: start(), stop(), reset(seed=None), set_params(...)
    """
    def __init__(self, master, fps=60, low_res=48, speed=0.5, amplitude=0.2,
                 blur=3, saturation=1.0, brightness=1.0, seed=0, bg=None, **kwargs):
        super().__init__(master, bg=bg, **kwargs)

        # פרמטרים ניתנים לשינוי
        self.fps = max(1, int(fps))
        self.low_res = max(4, int(low_res))
        self.speed = float(speed)
        self.amplitude = float(amplitude)
        self.blur = max(1, int(blur))
        self.saturation = float(saturation)
        self.brightness = float(brightness)
        self.seed = int(seed)

        # מצב פנימי
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        self._latest_pil = None   # PIL.Image שנוצרה ברקע ומוכנה להצגה
        self._photo = None        # PhotoImage לשמירה מפני GC
        self._width = max(1, self.winfo_reqwidth())
        self._height = max(1, self.winfo_reqheight())
        self._t = 0.0
        self._last_time = time.time()
        self._stop_event = threading.Event()

        # Label מאחורי הילדים להצגת הרקע
        self._bg_label = tk.Label(self, bd=0)
        self._bg_label.place(x=0, y=0, relwidth=1.0, relheight=1.0)

        # מאזין לשינוי גודל (עדכון מידי של רוחב/גובה)
        self.bind("<Configure>", self._on_configure)

        # אתחול low-res בסיסי
        self._rng = np.random.RandomState(self.seed)
        self._low = self._make_low_res_noise(self.low_res, self.low_res, self.seed)

        # הצגה ראשונית (שקטה)
        initial = self._upscale_and_smooth(self._low, self._width, self._height, self.blur)
        self._latest_pil = Image.fromarray(initial, mode="RGB")
        self._draw_from_latest()

    # --- יצירת רעש ברזולוציה נמוכה ---
    def _make_low_res_noise(self, h, w, seed):
        rng = np.random.RandomState(seed)
        return rng.rand(h, w, 3).astype(np.float32)

    # --- upscale וטשטוש (PIL) ---
    def _upscale_and_smooth(self, low, target_w, target_h, blur_ksize):
        img = Image.fromarray((low * 255).astype(np.uint8), mode="RGB")
        img = img.resize((max(1, target_w), max(1, target_h)), resample=Image.BICUBIC)
        k = int(blur_ksize)
        if k % 2 == 0:
            k += 1
        if k > 1:
            img = img.filter(ImageFilter.GaussianBlur(radius=k/2))
        return np.asarray(img).astype(np.uint8)

    # --- שינוי גודל ה-widget ---
    def _on_configure(self, event):
        w, h = max(1, event.width), max(1, event.height)
        with self._lock:
            if w != self._width or h != self._height:
                self._width, self._height = w, h
                # בקש עדכון רקע מיד (הרקע יתאים לגודל החדש)
                # אין יצירת משימות רבות — רק דגל שוטף
                # אם הריצה פעילה, ה-thread יבחין בגודל החדש בלולאתו
                # אם לא רץ, נעדכן מיד
                if not self._running:
                    # עדכון סינכרוני קטן כדי שהרקע יתאים מיד
                    up = self._upscale_and_smooth(self._low, self._width, self._height, self.blur)
                    self._latest_pil = Image.fromarray(up, mode="RGB")
                    self._draw_from_latest()

    # --- חוט רקע יחיד שמייצר תמונות עדכניות ---
    def _background_loop(self):
        # ריצה עד שה-_stop_event מוגדר
        last = time.time()
        while not self._stop_event.is_set():
            now = time.time()
            dt = now - last
            last = now
            # עדכון זמן פנימי
            with self._lock:
                local_speed = self.speed
                local_amplitude = self.amplitude
                local_low_res = self.low_res
                local_seed = self.seed
                local_blur = self.blur
                local_w = self._width
                local_h = self._height
                local_saturation = self.saturation
                local_brightness = self.brightness

            self._t += dt * local_speed

            # צור low-res משתנה לפי t
            s1 = int(local_seed + math.floor(self._t)) & 0xFFFF
            s2 = int(local_seed + math.floor(self._t) + 1) & 0xFFFF
            n1 = self._make_low_res_noise(local_low_res, local_low_res, s1)
            n2 = self._make_low_res_noise(local_low_res, local_low_res, s2)
            frac = self._t - math.floor(self._t)
            low = (1.0 - frac) * n1 + frac * n2

            # וריאציה מקומית עדינה
            local_rng = np.random.RandomState(int((self._t * 1000) % 100000))
            local_var = local_rng.normal(0, 0.01, low.shape).astype(np.float32)
            low = np.clip(low + local_var * local_amplitude, 0.0, 1.0)

            # upscale וטשטוש
            try:
                up_arr = self._upscale_and_smooth(low, local_w, local_h, local_blur)
                pil = Image.fromarray(up_arr, mode="RGB")
                # כוונון רוויה ובהירות ברקע
                if abs(local_saturation - 1.0) > 1e-3:
                    pil = ImageEnhance.Color(pil).enhance(local_saturation)
                if abs(local_brightness - 1.0) > 1e-3:
                    pil = ImageEnhance.Brightness(pil).enhance(local_brightness)
                # שמור את התמונה המוכנה להצגה
                with self._lock:
                    # החלפת latest_pil במקום (אין הצטברות)
                    self._latest_pil = pil
                    # שמור גם את ה-low כדי שהשינוי יתפתח
                    self._low = low
            except Exception:
                # אל תקרוס; הדפס לשגיאות אם צריך
                import traceback
                traceback.print_exc()

            # המתן לפי fps (או מעט פחות כדי לא לצבור)
            sleep_time = max(0.001, 1.0 / max(1, self.fps))
            # שינה קצרה מאפשרת תגובה מהירה ל-stop/configure
            if self._stop_event.wait(timeout=sleep_time):
                break

    # --- ציור מהתמונה האחרונה (במיין ת'רד) ---
    def _draw_from_latest(self):
        with self._lock:
            pil = self._latest_pil
        if pil is None:
            return
        # המרה ל-PhotoImage והצגה
        try:
            self._photo = ImageTk.PhotoImage(pil)
            self._bg_label.configure(image=self._photo)
        except Exception:
            # אם יש בעיה בהמרה — תפס ואל תקרוס
            import traceback
            traceback.print_exc()

    # --- לולאת הצגה קלה שמרעננת את התמונה לפי fps ---
    def _mainloop_draw(self):
        if not self._running:
            return
        # קח את התמונה האחרונה והצג
        self._draw_from_latest()
        # בקש קריאה הבאה
        delay_ms = max(1, int(1000 / max(1, self.fps)))
        self.after(delay_ms, self._mainloop_draw)

    # --- ממשק חיצוני ---
    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        # הפעל חוט רקע דמון
        self._thread = threading.Thread(target=self._background_loop, daemon=True)
        self._thread.start()
        # הפעל לולאת הצגה במיין ת'רד
        self._last_time = time.time()
        self._mainloop_draw()

    def stop(self):
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        # המתן קצר לחוט להסתיים
        if self._thread is not None:
            self._thread.join(timeout=0.2)
            self._thread = None
        # שחרור זיכרון קל
        gc.collect()

    def reset(self, seed=None):
        if seed is not None:
            self.seed = int(seed)
        with self._lock:
            self._low = self._make_low_res_noise(self.low_res, self.low_res, self.seed)
        # בקש עדכון מיד
        if self._running:
            # background loop יפיק תמונה חדשה בקרוב
            pass
        else:
            # עדכון סינכרוני קטן
            up = self._upscale_and_smooth(self._low, self._width, self._height, self.blur)
            self._latest_pil = Image.fromarray(up, mode="RGB")
            self._draw_from_latest()

    def set_params(self, **kwargs):
        # עדכון פרמטרים בזמן ריצה
        with self._lock:
            if "fps" in kwargs:
                self.fps = max(1, int(kwargs.pop("fps")))
            if "low_res" in kwargs:
                self.low_res = max(4, int(kwargs.pop("low_res")))
                self._low = self._make_low_res_noise(self.low_res, self.low_res, self.seed)
            if "speed" in kwargs:
                self.speed = float(kwargs.pop("speed"))
            if "amplitude" in kwargs:
                self.amplitude = float(kwargs.pop("amplitude"))
            if "blur" in kwargs:
                self.blur = max(1, int(kwargs.pop("blur")))
            if "saturation" in kwargs:
                self.saturation = float(kwargs.pop("saturation"))
            if "brightness" in kwargs:
                self.brightness = float(kwargs.pop("brightness"))
            if "seed" in kwargs:
                self.seed = int(kwargs.pop("seed"))
                self._low = self._make_low_res_noise(self.low_res, self.low_res, self.seed)

    def get_pil_image(self):
        with self._lock:
            return None if self._latest_pil is None else self._latest_pil.copy()

    def destroy(self):
        # עצור חוט רקע ושחרר משאבים
        try:
            self.stop()
        except Exception:
            pass
        # שחרור הפניות
        self._latest_pil = None
        self._photo = None
        gc.collect()
        super().destroy()
if __name__ == '__main__':
    from main.tk_widgets.display_board import DisplayBoard

    root = tk.Tk()
    root.title("SmoothColorFrame Demo")

    # יצירת ה-Frame הצבעוני
    scf = SmoothColorFrame(root, fps=30,
                           low_res=48, speed=0.3, amplitude=0.2,
                           blur=5, saturation=1.0, brightness=1.0, seed=42, bg="black")
    scf.pack(fill="both", expand=True,side="left")
    DisplayBoard(scf).pack(fill="both", pady=40,padx=40)
    # פאנל בקרות
    ctrl = tk.Frame(root)
    ctrl.pack(fill="x",side="right")

    # מהירות
    tk.Label(ctrl, text="Speed").grid(row=0, column=0)
    speed_var = tk.DoubleVar(value=0.3)
    tk.Scale(ctrl, variable=speed_var, from_=0.0, to=2.0, resolution=0.01, orient="horizontal",
             command=lambda v: scf.set_params(speed=float(v))).grid(row=0, column=1, sticky="we")

    # עוצמה
    tk.Label(ctrl, text="Amplitude").grid(row=1, column=0)
    amp_var = tk.DoubleVar(value=0.2)
    tk.Scale(ctrl, variable=amp_var, from_=0.0, to=1.0, resolution=0.01, orient="horizontal",
             command=lambda v: scf.set_params(amplitude=float(v))).grid(row=1, column=1, sticky="we")

    # רזולוציית רעש
    tk.Label(ctrl, text="LowRes").grid(row=2, column=0)
    lr_var = tk.IntVar(value=48)
    tk.Scale(ctrl, variable=lr_var, from_=8, to=256, resolution=1, orient="horizontal",
             command=lambda v: scf.set_params(low_res=int(v))).grid(row=2, column=1, sticky="we")

    # Blur
    tk.Label(ctrl, text="Blur").grid(row=3, column=0)
    blur_var = tk.IntVar(value=5)
    tk.Scale(ctrl, variable=blur_var, from_=1, to=25, resolution=1, orient="horizontal",
             command=lambda v: scf.set_params(blur=int(v))).grid(row=3, column=1, sticky="we")

    # Saturation
    tk.Label(ctrl, text="Saturation").grid(row=4, column=0)
    sat_var = tk.DoubleVar(value=1.0)
    tk.Scale(ctrl, variable=sat_var, from_=0.0, to=3.0, resolution=0.01, orient="horizontal",
             command=lambda v: scf.set_params(saturation=float(v))).grid(row=4, column=1, sticky="we")

    # Brightness
    tk.Label(ctrl, text="Brightness").grid(row=5, column=0)
    bri_var = tk.DoubleVar(value=1.0)
    tk.Scale(ctrl, variable=bri_var, from_=0.2, to=3.0, resolution=0.01, orient="horizontal",
             command=lambda v: scf.set_params(brightness=float(v))).grid(row=5, column=1, sticky="we")

    # Seed
    tk.Label(ctrl, text="Seed").grid(row=6, column=0)
    seed_var = tk.IntVar(value=42)
    tk.Entry(ctrl, textvariable=seed_var, width=8).grid(row=6, column=1, sticky="w")
    tk.Button(ctrl, text="Apply Seed", command=lambda: scf.reset(seed=seed_var.get())).grid(row=6, column=1,
                                                                                            sticky="e")

    # Start / Stop / Reset
    btn_frame = tk.Frame(ctrl)
    btn_frame.grid(row=7, column=0, columnspan=2, pady=6)
    tk.Button(btn_frame, text="Start", command=scf.start).pack(side="left", padx=4)
    tk.Button(btn_frame, text="Stop", command=scf.stop).pack(side="left", padx=4)
    tk.Button(btn_frame, text="Reset", command=lambda: scf.reset()).pack(side="left", padx=4)

    # הפעלת ה-Frame
    scf.start()
    root.mainloop()


