"""
pystage.py — ASCII video player with its own window, play/pause & progress bar!

Requirements:
    pip install opencv-python pillow numpy
    (tkinter is built into Python — no install needed)

Usage:
    python pystage.py                        # opens file picker
    python pystage.py <video_file>           # load directly
    python pystage.py <video_file> --color   # with color
    python pystage.py <video_file> --detail  # detailed palette
"""

import cv2
import os
import time
import argparse
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image
import numpy as np

# ── Char palettes (dark→dense, bright→sparse) ─────────────────────────────────
PALETTE_DETAILED = r'@#MW&8%B$*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\|()1{}[]?-_+~<>i!lI;:,"^`. '
PALETTE_SIMPLE   = "@#S%?*+;:,. "

# ── Theme ──────────────────────────────────────────────────────────────────────
BG_COLOR = "#0d0d0d"
FG_COLOR = "#00ff88"
BAR_BG   = "#1a1a1a"
BTN_BG   = "#1a1a1a"
BTN_FG   = "#00ff88"
TIME_FG  = "#888888"
TITLE_FG = "#ffffff"
ACCENT   = "#00ff88"
FONT     = "Courier New"
FONT_SZ  = 9          # fixed readable size; window resize changes cols/rows, not font

# ── Helpers ────────────────────────────────────────────────────────────────────
def fmt_time(seconds):
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def frame_to_ascii(frame_bgr, cols, rows, palette):
    img_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb).resize((cols, rows), Image.LANCZOS)
    pixels  = np.array(pil_img)
    gray    = (0.299 * pixels[:,:,0] +
               0.587 * pixels[:,:,1] +
               0.114 * pixels[:,:,2])
    lo, hi  = gray.min(), gray.max()
    if hi > lo:
        gray = (gray - lo) / (hi - lo) * 255.0
    n       = len(palette) - 1
    indices = (gray / 255.0 * n).astype(int).clip(0, n)
    lines   = ["".join(palette[indices[y, x]] for x in range(cols))
               for y in range(rows)]
    return lines, pixels


# ══════════════════════════════════════════════════════════════════════════════
class PyStage:
    def __init__(self, root, video_path, use_color, palette):
        self.root        = root
        self.video_path  = video_path
        self.use_color   = use_color
        self.palette     = palette

        self.paused      = False
        self.seeking     = False
        self.running     = True
        self._seek_frame = None
        self.cap         = None
        self.total_frames= 1
        self.fps         = 24
        self.vid_aspect  = 9 / 16   # h/w ratio, updated from file

        # Current ASCII grid size — derived from widget size each frame
        self.ascii_cols  = 80
        self.ascii_rows  = 24

        # Char cell size in pixels (measured after first render)
        self._char_w     = None
        self._char_h     = None

        self._resize_after_id = None   # debounce resize events

        self._open_video()
        self._build_ui()
        self._start_playback()

    # ── Open video ─────────────────────────────────────────────────────────────
    def _open_video(self):
        self.cap = cv2.VideoCapture(self.video_path)
        if not self.cap.isOpened():
            messagebox.showerror("PyStage", f"Cannot open:\n{self.video_path}")
            self.root.destroy()
            return
        self.fps          = self.cap.get(cv2.CAP_PROP_FPS) or 24
        self.total_frames = max(1, int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)))
        orig_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        orig_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.vid_aspect   = orig_h / max(1, orig_w)   # pure pixel aspect

    # ── Build UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.root.title("🎬 PyStage")
        self.root.configure(bg=BG_COLOR)
        self.root.resizable(True, True)

        # ── Title bar ──
        top = tk.Frame(self.root, bg=BG_COLOR)
        top.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(top, text="▶ PyStage", font=(FONT, 13, "bold"),
                 bg=BG_COLOR, fg=TITLE_FG).pack(side="left")
        self.fname_lbl = tk.Label(top, text=f"  {os.path.basename(self.video_path)}",
                 font=(FONT, 10), bg=BG_COLOR, fg=TIME_FG)
        self.fname_lbl.pack(side="left")

        # ── ASCII display ──
        # Outer frame fills all available space (used to measure pixel room)
        self.display = tk.Frame(self.root, bg=BG_COLOR)
        self.display.pack(fill="both", expand=True, padx=4, pady=(2, 0))

        # Inner centering frame — text widget sits inside this, centered
        self.center_frame = tk.Frame(self.display, bg=BG_COLOR)
        self.center_frame.place(relx=0.5, rely=0.5, anchor="center")

        self.text = tk.Text(
            self.center_frame,
            font=(FONT, FONT_SZ),
            bg=BG_COLOR, fg=FG_COLOR,
            insertwidth=0, relief="flat",
            state="disabled", wrap="none", cursor="arrow",
        )
        self.text.pack()

        # ── Controls ──
        ctrl = tk.Frame(self.root, bg=BAR_BG, pady=8)
        ctrl.pack(fill="x", side="bottom")

        prog_row = tk.Frame(ctrl, bg=BAR_BG)
        prog_row.pack(fill="x", padx=14, pady=(4, 2))

        self.time_var = tk.StringVar(value="0:00 / 0:00")
        tk.Label(prog_row, textvariable=self.time_var,
                 font=(FONT, 9), bg=BAR_BG, fg=TIME_FG).pack(side="right", padx=(6, 0))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress = ttk.Scale(
            prog_row, from_=0, to=self.total_frames - 1,
            orient="horizontal", variable=self.progress_var,
            command=self._on_scrub,
        )
        self._style_scale()
        self.progress.pack(fill="x", expand=True, side="left")
        self.progress.bind("<ButtonPress-1>",   lambda e: self._seek_press())
        self.progress.bind("<ButtonRelease-1>", lambda e: self._seek_release())

        btn_row = tk.Frame(ctrl, bg=BAR_BG)
        btn_row.pack(pady=(4, 4))
        self.play_btn = self._btn(btn_row, "⏸  Pause",   self._toggle_pause)
        self.play_btn.pack(side="left", padx=5)
        self._btn(btn_row, "⏮  Restart", self._restart).pack(side="left", padx=5)
        self._btn(btn_row, "📂  Open",   self._open_new).pack(side="left", padx=5)
        self._btn(btn_row, "✕  Quit",    self._quit, fg="#ff4444").pack(side="left", padx=5)

        self.root.bind("<space>",     lambda e: self._toggle_pause())
        self.root.bind("<Escape>",    lambda e: self._quit())
        self.root.bind("<r>",         lambda e: self._restart())
        self.root.bind("<Configure>", self._on_window_resize)
        self.root.protocol("WM_DELETE_WINDOW", self._quit)

        # Cap initial window to 90% of screen so it never spawns off-screen
        # on machines with small or huge displays
        scr_w = self.root.winfo_screenwidth()
        scr_h = self.root.winfo_screenheight()
        win_w = min(960, int(scr_w * 0.90))
        win_h = min(620, int(scr_h * 0.90))
        # Also respect video aspect: try to pre-size window to match
        # video ratio (controls bar ~110px, title ~38px)
        ui_overhead_h = 148
        content_h     = win_h - ui_overhead_h
        content_w_from_h = int(content_h / self.vid_aspect)   # pixel width for that height
        if content_w_from_h < win_w:
            win_w = max(480, content_w_from_h + 8)
        self.root.geometry(f"{win_w}x{win_h}")
        self.root.maxsize(int(scr_w * 0.98), int(scr_h * 0.95))
        # Measure char metrics after first paint
        self.root.after(150, self._measure_char)

    # ── Measure a single char's pixel size (done once after UI is drawn) ───────
    def _measure_char(self):
        # Insert a test char, read bbox, delete it
        self.text.config(state="normal")
        self.text.insert("1.0", "X")
        self.root.update_idletasks()
        bbox = self.text.bbox("1.0")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")

        if bbox:
            _, _, cw, ch = bbox
            self._char_w = max(1, cw)
            self._char_h = max(1, ch)
        else:
            # Fallback estimate
            self._char_w = FONT_SZ * 0.62
            self._char_h = FONT_SZ * 1.35

        self._recalc_grid()

    # ── Recalculate how many cols/rows fit the display frame ────────────────
    def _recalc_grid(self):
        if self._char_w is None:
            return
        self.root.update_idletasks()
        w = self.display.winfo_width()
        h = self.display.winfo_height()
        if w < 10 or h < 10:
            return

        # Char aspect ratio (monospace chars are taller than wide, ~2:1)
        char_aspect = self._char_h / self._char_w

        # Fit cols & rows inside the available pixel space while
        # preserving the video's original aspect ratio
        # Try fitting by width first
        cols = max(10, int(w / self._char_w))
        rows = max(4,  int(cols * self.vid_aspect / char_aspect))

        # If that's too tall, fit by height instead
        if rows * self._char_h > h:
            rows = max(4, int(h / self._char_h))
            cols = max(10, int(rows * char_aspect / self.vid_aspect))

        self.ascii_cols = cols
        self.ascii_rows = rows

        # Resize the text widget to exactly the grid's pixel footprint
        # so it stays truly centered with no leftover space
        px_w = int(cols * self._char_w)
        px_h = int(rows * self._char_h)
        self.text.config(width=cols, height=rows)
        self.center_frame.config(width=px_w, height=px_h)

    # ── Debounced resize handler ───────────────────────────────────────────────
    def _on_window_resize(self, event):
        if event.widget is not self.root:
            return
        if self._resize_after_id:
            self.root.after_cancel(self._resize_after_id)
        self._resize_after_id = self.root.after(80, self._recalc_grid)

    def _style_scale(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("Horizontal.TScale",
                    background=BAR_BG, troughcolor="#333",
                    sliderlength=14, sliderrelief="flat")

    def _btn(self, parent, text, cmd, fg=BTN_FG):
        b = tk.Button(parent, text=text, command=cmd,
                      font=(FONT, 9, "bold"),
                      bg=BTN_BG, fg=fg, activebackground=ACCENT,
                      activeforeground=BG_COLOR,
                      relief="flat", padx=10, pady=4, cursor="hand2", bd=0)
        b.bind("<Enter>", lambda e: b.config(bg="#222"))
        b.bind("<Leave>", lambda e: b.config(bg=BTN_BG))
        return b

    # ── Seek ───────────────────────────────────────────────────────────────────
    def _seek_press(self):
        self.seeking = True

    def _seek_release(self):
        self._seek_frame = int(self.progress_var.get())
        self.seeking = False

    def _on_scrub(self, val):
        fi = int(float(val))
        self.time_var.set(f"{fmt_time(fi / self.fps)} / {fmt_time(self.total_frames / self.fps)}")

    # ── Controls ───────────────────────────────────────────────────────────────
    def _toggle_pause(self):
        self.paused = not self.paused
        self.play_btn.config(text="▶  Play " if self.paused else "⏸  Pause")

    def _restart(self):
        self._seek_frame = 0
        if self.paused:
            self._toggle_pause()

    def _open_new(self):
        path = filedialog.askopenfilename(
            title="PyStage — Open video",
            filetypes=[("Video files", "*.mp4 *.avi *.mkv *.mov *.wmv *.flv"),
                       ("All files", "*.*")]
        )
        if not path:
            return
        self.running = False
        time.sleep(0.2)
        self.cap.release()
        self.video_path = path
        self._open_video()
        self.progress.config(to=self.total_frames - 1)
        self.fname_lbl.config(text=f"  {os.path.basename(path)}")
        self._recalc_grid()
        self.running = True
        self.paused  = False
        self.play_btn.config(text="⏸  Pause")
        self._start_playback()

    def _quit(self):
        self.running = False
        self.root.after(200, self.root.destroy)

    # ── Playback thread ────────────────────────────────────────────────────────
    def _start_playback(self):
        threading.Thread(target=self._play_loop, daemon=True).start()

    def _play_loop(self):
        delay = 1.0 / self.fps
        while self.running:
            if self._seek_frame is not None:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, self._seek_frame)
                self._seek_frame = None

            if self.paused or self.seeking:
                time.sleep(0.05)
                continue

            t0 = time.perf_counter()
            ret, frame = self.cap.read()
            if not ret:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue

            cur  = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
            cols = self.ascii_cols
            rows = self.ascii_rows

            lines, pixels = frame_to_ascii(frame, cols, rows, self.palette)
            self.root.after(0, self._update_display, lines, pixels, cur)

            sleep_t = delay - (time.perf_counter() - t0)
            if sleep_t > 0:
                time.sleep(sleep_t)

    # ── Render frame ───────────────────────────────────────────────────────────
    def _update_display(self, lines, pixels, cur_frame):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")

        if self.use_color:
            for y, line in enumerate(lines):
                for x, ch in enumerate(line):
                    r = int(pixels[y, x, 0])
                    g = int(pixels[y, x, 1])
                    b = int(pixels[y, x, 2])
                    tag = f"#{r:02x}{g:02x}{b:02x}"
                    if tag not in self.text.tag_names():
                        self.text.tag_configure(tag, foreground=tag)
                    self.text.insert("end", ch, tag)
                self.text.insert("end", "\n")
        else:
            self.text.insert("1.0", "\n".join(lines))

        self.text.config(state="disabled")

        if not self.seeking:
            self.progress_var.set(cur_frame)
        self.time_var.set(
            f"{fmt_time(cur_frame / self.fps)} / {fmt_time(self.total_frames / self.fps)}"
        )


# ══════════════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="PyStage — ASCII video player")
    parser.add_argument("video",    nargs="?", default=None)
    parser.add_argument("--color",  action="store_true")
    parser.add_argument("--detail", action="store_true")
    args = parser.parse_args()

    palette = PALETTE_DETAILED if args.detail else PALETTE_SIMPLE

    root = tk.Tk()

    video_path = args.video
    if not video_path:
        # Hide root while file picker is open — prevents it from
        # spawning as a blank window and minimizing to taskbar
        root.withdraw()
        video_path = filedialog.askopenfilename(
            title="PyStage — Open a video",
            filetypes=[("Video files", "*.mp4 *.avi *.mkv *.mov *.wmv *.flv"),
                       ("All files", "*.*")]
        )
        if not video_path:
            root.destroy()
            return
        # Bring window back, focused and on top
        root.deiconify()
        root.lift()
        root.focus_force()

    PyStage(root, video_path, args.color, palette)
    root.mainloop()


if __name__ == "__main__":
    main()