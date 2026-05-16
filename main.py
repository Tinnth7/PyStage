"""
pystage.py — ASCII video player with color & palette toggles, about dialog.

Requirements:
    pip install opencv-python pillow numpy

Usage:
    python pystage.py                        # opens file picker
    python pystage.py <video_file>           # load directly
    python pystage.py <video_file> --color   # start with color ON
    python pystage.py <video_file> --detail  # start with detailed palette
"""

import cv2
import os
import time
import argparse
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, font
from PIL import Image
import numpy as np

# Char palettes
PALETTE_DETAILED = r'@#MW&8%B$*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\|()1{}[]?-_+~<>i!lI;:,"^`. '
PALETTE_SIMPLE   = "@#S%?*+;:,. "

# Theme
BG_COLOR = "#0d0d0d"
FG_COLOR = "#00ff88"
BAR_BG   = "#1a1a1a"
BTN_BG   = "#1a1a1a"
BTN_FG   = "#00ff88"
TIME_FG  = "#888888"
TITLE_FG = "#ffffff"
ACCENT   = "#00ff88"
FONT     = "Courier New"
FONT_SZ  = 9

# Color quantization (216 colors, instant)
COLOR_PALETTE_RGB = []
for r in range(0, 256, 51):
    for g in range(0, 256, 51):
        for b in range(0, 256, 51):
            COLOR_PALETTE_RGB.append((r, g, b))

def quantize_color_indices(rgb_image):
    r_idx = rgb_image[:, :, 0] // 51
    g_idx = rgb_image[:, :, 1] // 51
    b_idx = rgb_image[:, :, 2] // 51
    return r_idx * 36 + g_idx * 6 + b_idx

def fmt_time(seconds):
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def frame_to_ascii(frame_bgr, cols, rows, palette, use_color=False):
    img_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb).resize((cols, rows), Image.BILINEAR)
    pixels = np.array(pil_img)

    gray = (0.299 * pixels[:,:,0] + 0.587 * pixels[:,:,1] + 0.114 * pixels[:,:,2])
    lo, hi = gray.min(), gray.max()
    if hi > lo:
        gray = (gray - lo) / (hi - lo) * 255.0
    n = len(palette) - 1
    indices = (gray / 255.0 * n).astype(int).clip(0, n)

    lines = ["".join(palette[indices[y, x]] for x in range(cols)) for y in range(rows)]

    if use_color:
        color_indices = quantize_color_indices(pixels)
        return lines, color_indices
    else:
        return lines, None


class PyStage:
    def __init__(self, root, video_path, start_color, start_detailed):
        self.root = root
        self.video_path = video_path
        self.use_color = start_color
        self.use_detailed = start_detailed
        self.palette = PALETTE_DETAILED if start_detailed else PALETTE_SIMPLE

        self.paused = False
        self.seeking = False
        self.running = True
        self._seek_frame = None
        self.cap = None
        self.total_frames = 1
        self.fps = 24
        self.vid_aspect = 9 / 16

        self.cap_lock = threading.Lock()

        self.ascii_cols = 80
        self.ascii_rows = 24
        self._char_w = None
        self._char_h = None

        self._resize_after_id = None
        self._color_tags_initialized = False

        self._open_video()
        self._build_ui()
        self._start_playback()

    def _open_video(self):
        with self.cap_lock:
            if self.cap is not None:
                self.cap.release()
            self.cap = cv2.VideoCapture(self.video_path)
            if not self.cap.isOpened():
                messagebox.showerror("PyStage", f"Cannot open:\n{self.video_path}")
                self.root.destroy()
                return
            self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 24
            self.total_frames = max(1, int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)))
            orig_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            orig_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.vid_aspect = orig_h / max(1, orig_w)

    def _build_ui(self):
        self.root.title("PyStage")
        self.root.configure(bg=BG_COLOR)
        self.root.resizable(True, True)

        # Title bar
        top = tk.Frame(self.root, bg=BG_COLOR)
        top.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(top, text="PyStage", font=(FONT, 13, "bold"),
                 bg=BG_COLOR, fg=TITLE_FG).pack(side="left")
        self.fname_lbl = tk.Label(top, text=f"  {os.path.basename(self.video_path)}",
                                  font=(FONT, 10), bg=BG_COLOR, fg=TIME_FG)
        self.fname_lbl.pack(side="left")

        # Display area with centering
        self.display = tk.Frame(self.root, bg=BG_COLOR)
        self.display.pack(fill="both", expand=True, padx=4, pady=(2, 0))
        self.display.bind("<Configure>", self._on_display_resize)

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

        # Controls
        ctrl = tk.Frame(self.root, bg=BAR_BG, pady=8)
        ctrl.pack(fill="x", side="bottom")

        # Progress bar row
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
        self.progress.bind("<ButtonPress-1>", lambda e: self._seek_press())
        self.progress.bind("<ButtonRelease-1>", lambda e: self._seek_release())

        # Button row 1: Pause, Play, Restart
        btn_row1 = tk.Frame(ctrl, bg=BAR_BG)
        btn_row1.pack(pady=(4, 0))

        self.play_btn = self._btn(btn_row1, "⏸ Pause" if not self.paused else "▶ Play", self._toggle_pause)
        self.play_btn.pack(side="left", padx=5)

        self._btn(btn_row1, "↺ Restart", self._restart).pack(side="left", padx=5)

        # Button row 2: Open, Color, Palette, About, Quit
        btn_row2 = tk.Frame(ctrl, bg=BAR_BG)
        btn_row2.pack(pady=(4, 4))

        self._btn(btn_row2, "Open", self._open_new).pack(side="left", padx=5)

        self.color_btn = self._btn(btn_row2, "Color: ON" if self.use_color else "Color: OFF", self._toggle_color)
        self.color_btn.pack(side="left", padx=5)

        self.palette_btn = self._btn(btn_row2, "Palette: Detailed" if self.use_detailed else "Palette: Simple", self._toggle_palette)
        self.palette_btn.pack(side="left", padx=5)

        self._btn(btn_row2, "About", self._show_about).pack(side="left", padx=5)

        self._btn(btn_row2, "✕ Quit", self._quit, fg="#ff4444").pack(side="left", padx=5)

        # Keyboard shortcuts
        self.root.bind("<space>", lambda e: self._toggle_pause())
        self.root.bind("<Escape>", lambda e: self._quit())
        self.root.bind("<r>", lambda e: self._restart())
        self.root.bind("<c>", lambda e: self._toggle_color())
        self.root.bind("<p>", lambda e: self._toggle_palette())
        self.root.bind("<a>", lambda e: self._show_about())
        self.root.bind("<A>", lambda e: self._show_about())
        self.root.protocol("WM_DELETE_WINDOW", self._quit)

        # Initial window size (no maxsize restriction)
        scr_w = self.root.winfo_screenwidth()
        scr_h = self.root.winfo_screenheight()
        win_w = min(960, int(scr_w * 0.90))
        win_h = min(620, int(scr_h * 0.90))
        ui_overhead_h = 148
        content_h = win_h - ui_overhead_h
        content_w_from_h = int(content_h / self.vid_aspect) if self.vid_aspect else 480
        if content_w_from_h < win_w:
            win_w = max(480, content_w_from_h + 8)
        self.root.geometry(f"{win_w}x{win_h}")
        # No maxsize – window can be maximized fully

        self.root.after(150, self._measure_char)

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

    def _measure_char(self):
        try:
            f = font.Font(family=FONT, size=FONT_SZ)
            self._char_w = f.measure("X")
            self._char_h = f.metrics("linespace")
        except:
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
                self._char_w = FONT_SZ * 0.62
                self._char_h = FONT_SZ * 1.35
        self._recalc_grid()

    def _recalc_grid(self):
        if self._char_w is None:
            return
        w = self.display.winfo_width()
        h = self.display.winfo_height()
        if w < 10 or h < 10:
            return
        char_aspect = self._char_h / self._char_w
        cols = max(10, int(w / self._char_w))
        rows = max(4, int(cols * self.vid_aspect / char_aspect))
        if rows * self._char_h > h:
            rows = max(4, int(h / self._char_h))
            cols = max(10, int(rows * char_aspect / self.vid_aspect))
        self.ascii_cols = cols
        self.ascii_rows = rows
        self.text.config(width=cols, height=rows)
        px_w = int(cols * self._char_w)
        px_h = int(rows * self._char_h)
        self.center_frame.config(width=px_w, height=px_h)

    def _on_display_resize(self, event):
        if self._resize_after_id:
            self.root.after_cancel(self._resize_after_id)
        self._resize_after_id = self.root.after(80, self._recalc_grid)

    def _seek_press(self):
        self.seeking = True

    def _seek_release(self):
        with self.cap_lock:
            self._seek_frame = int(self.progress_var.get())
        self.seeking = False

    def _on_scrub(self, val):
        fi = int(float(val))
        self.time_var.set(f"{fmt_time(fi / self.fps)} / {fmt_time(self.total_frames / self.fps)}")

    def _toggle_pause(self):
        self.paused = not self.paused
        self.play_btn.config(text="⏸ Pause" if not self.paused else "▶ Play")

    def _restart(self):
        with self.cap_lock:
            self._seek_frame = 0
        if self.paused:
            self._toggle_pause()

    def _toggle_color(self):
        self.use_color = not self.use_color
        self.color_btn.config(text="Color: ON" if self.use_color else "Color: OFF")

    def _toggle_palette(self):
        self.use_detailed = not self.use_detailed
        self.palette = PALETTE_DETAILED if self.use_detailed else PALETTE_SIMPLE
        self.palette_btn.config(text="Palette: Detailed" if self.use_detailed else "Palette: Simple")

    def _show_about(self):
        about_win = tk.Toplevel(self.root)
        about_win.title("About PyStage")
        about_win.configure(bg=BG_COLOR)
        about_win.geometry("500x250")
        about_win.resizable(False, False)
        about_win.transient(self.root)
        about_win.grab_set()

        frame = tk.Frame(about_win, bg=BG_COLOR, padx=20, pady=20)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="PyStage", font=(FONT, 18, "bold"),
                 bg=BG_COLOR, fg=ACCENT).pack(pady=(0, 5))
        tk.Label(frame, text="Beta v0.4", font=(FONT, 10),
                 bg=BG_COLOR, fg=TIME_FG).pack()

        tk.Frame(frame, height=2, bg=ACCENT).pack(fill="x", pady=15)

        github_url = "https://github.com/Tinnth7/PyStage"
        github_link = tk.Label(frame, text=f"GitHub: {github_url}",
                               font=(FONT, 10), bg=BG_COLOR, fg=FG_COLOR,
                               cursor="hand2")
        github_link.pack(anchor="w", pady=2)
        github_link.bind("<Button-1>", lambda e: webbrowser.open(github_url))

        creator_url = "https://www.comradelituz.straw.page"
        creator_link = tk.Label(frame, text=f"Creator: {creator_url}",
                                font=(FONT, 10), bg=BG_COLOR, fg=FG_COLOR,
                                cursor="hand2")
        creator_link.pack(anchor="w", pady=2)
        creator_link.bind("<Button-1>", lambda e: webbrowser.open(creator_url))

        tk.Button(frame, text="Close", command=about_win.destroy,
                  font=(FONT, 9), bg=BTN_BG, fg=BTN_FG,
                  activebackground=ACCENT, activeforeground=BG_COLOR,
                  relief="flat", padx=15, pady=4, cursor="hand2",
                  bd=0).pack(pady=(15, 0))

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
        with self.cap_lock:
            if self.cap:
                self.cap.release()
        self.video_path = path
        self._open_video()
        self.progress.config(to=self.total_frames - 1)
        self.fname_lbl.config(text=f"  {os.path.basename(path)}")
        self._recalc_grid()
        self.running = True
        self.paused = False
        self.play_btn.config(text="⏸ Pause")
        self._start_playback()

    def _quit(self):
        self.running = False
        with self.cap_lock:
            if self.cap:
                self.cap.release()
        self.root.after(200, self.root.destroy)

    def _start_playback(self):
        threading.Thread(target=self._play_loop, daemon=True).start()

    def _play_loop(self):
        frame_interval = 1.0 / self.fps
        next_frame_time = time.perf_counter()

        while self.running:
            seek_to = None
            with self.cap_lock:
                if self._seek_frame is not None:
                    seek_to = self._seek_frame
                    self._seek_frame = None
            if seek_to is not None:
                with self.cap_lock:
                    if self.cap:
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, seek_to)

            if self.paused or self.seeking:
                time.sleep(0.02)
                continue

            with self.cap_lock:
                if not self.cap:
                    time.sleep(0.02)
                    continue
                ret, frame = self.cap.read()
                if not ret:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                cur_frame = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))

            lines, color_indices = frame_to_ascii(frame, self.ascii_cols, self.ascii_rows,
                                                  self.palette, self.use_color)
            self.root.after(0, self._update_display, lines, color_indices, cur_frame)

            next_frame_time += frame_interval
            sleep_time = next_frame_time - time.perf_counter()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                next_frame_time = time.perf_counter() + frame_interval

    def _init_color_tags(self):
        if self._color_tags_initialized:
            return
        for idx, (r, g, b) in enumerate(COLOR_PALETTE_RGB):
            color_name = f"#{r:02x}{g:02x}{b:02x}"
            self.text.tag_configure(color_name, foreground=color_name)
        self._color_tags_initialized = True

    def _update_display(self, lines, color_indices, cur_frame):
        if not self.running:
            return

        self.text.config(state="normal")
        self.text.delete("1.0", "end")

        if self.use_color and color_indices is not None:
            self._init_color_tags()
            rows = len(lines)
            cols = len(lines[0]) if rows > 0 else 0
            for y in range(rows):
                row_chars = lines[y]
                row_colors = color_indices[y]
                for x in range(cols):
                    ch = row_chars[x]
                    r, g, b = COLOR_PALETTE_RGB[row_colors[x]]
                    tag = f"#{r:02x}{g:02x}{b:02x}"
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


def main():
    parser = argparse.ArgumentParser(description="PyStage — ASCII video player")
    parser.add_argument("video", nargs="?", default=None)
    parser.add_argument("--color", action="store_true", help="Start with color mode ON")
    parser.add_argument("--detail", action="store_true", help="Start with detailed palette")
    args = parser.parse_args()

    root = tk.Tk()

    video_path = args.video
    if not video_path:
        root.withdraw()
        video_path = filedialog.askopenfilename(
            title="PyStage — Open a video",
            filetypes=[("Video files", "*.mp4 *.avi *.mkv *.mov *.wmv *.flv"),
                       ("All files", "*.*")]
        )
        if not video_path:
            root.destroy()
            return
        root.deiconify()
        root.lift()
        root.focus_force()

    PyStage(root, video_path, args.color, args.detail)
    root.mainloop()


if __name__ == "__main__":
    main()