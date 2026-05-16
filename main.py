"""
pystage.py — ASCII video & image viewer with zoom, color, and aspect ratio preservation.
"""

import cv2
import os
import time
import argparse
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, font
from PIL import Image as PILImage
import numpy as np
import pygame

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

# Resolution presets (cols, rows)
RESOLUTIONS = {
    "Low (144p)": (40, 24),
    "Medium (360p)": (80, 24),
    "High (720p)": (120, 36),
    "Ultra (8K)": (160, 48),
    "Ultra HD (240x72)": (240, 72),
    "Ultra HD+ (320x96)": (320, 96),
    "Ultra HD++ (400x120)": (400, 120),
}

# Color quantization
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

def frame_to_ascii(frame_or_img, cols, rows, palette, char_w, char_h, use_color=False, zoom=1.0):
    """Convert a video frame or static image (numpy array) to ASCII grid."""
    h, w = frame_or_img.shape[:2]
    if zoom > 1.0:
        crop_w = int(w / zoom)
        crop_h = int(h / zoom)
        start_x = (w - crop_w) // 2
        start_y = (h - crop_h) // 2
        cropped = frame_or_img[start_y:start_y+crop_h, start_x:start_x+crop_w]
    else:
        cropped = frame_or_img
        crop_h, crop_w = h, w

    video_pixel_aspect = crop_w / crop_h
    char_physical_aspect = char_h / char_w
    target_character_aspect = video_pixel_aspect * char_physical_aspect
    grid_aspect = cols / rows

    if target_character_aspect > grid_aspect:
        target_w = cols
        target_h = int(cols / target_character_aspect)
    else:
        target_h = rows
        target_w = int(rows * target_character_aspect)

    target_w = max(1, target_w)
    target_h = max(1, target_h)

    img_rgb = cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB)
    pil_img = PILImage.fromarray(img_rgb).resize((target_w, target_h), PILImage.BILINEAR)
    pixels = np.array(pil_img)

    if use_color:
        full_grid = np.zeros((rows, cols, 3), dtype=np.uint8)
    else:
        full_lines = [[" " for _ in range(cols)] for __ in range(rows)]

    x_offset = (cols - target_w) // 2
    y_offset = (rows - target_h) // 2

    if use_color:
        full_grid[y_offset:y_offset+target_h, x_offset:x_offset+target_w] = pixels
        gray = (0.299 * full_grid[:,:,0] + 0.587 * full_grid[:,:,1] + 0.114 * full_grid[:,:,2])
        lo, hi = gray.min(), gray.max()
        if hi > lo:
            gray = (gray - lo) / (hi - lo) * 255.0
        n = len(palette) - 1
        indices = (gray / 255.0 * n).astype(int).clip(0, n)
        lines = ["".join(palette[indices[y, x]] for x in range(cols)) for y in range(rows)]
        r_idx = full_grid[:,:,0] // 51
        g_idx = full_grid[:,:,1] // 51
        b_idx = full_grid[:,:,2] // 51
        color_indices = r_idx * 36 + g_idx * 6 + b_idx
        return lines, color_indices
    else:
        gray_resized = (0.299 * pixels[:,:,0] + 0.587 * pixels[:,:,1] + 0.114 * pixels[:,:,2])
        lo, hi = gray_resized.min(), gray_resized.max()
        if hi > lo:
            gray_resized = (gray_resized - lo) / (hi - lo) * 255.0
        n = len(palette) - 1
        indices = (gray_resized / 255.0 * n).astype(int).clip(0, n)
        ascii_resized = ["".join(palette[indices[y, x]] for x in range(target_w)) for y in range(target_h)]
        for y in range(target_h):
            for x in range(target_w):
                full_lines[y_offset + y][x_offset + x] = ascii_resized[y][x]
        lines = ["".join(row) for row in full_lines]
        return lines, None


class PyStage:
    def __init__(self, root, path, start_color, start_detailed):
        self.root = root
        self.path = path
        self.use_color = start_color
        self.use_detailed = start_detailed
        self.palette = PALETTE_DETAILED if start_detailed else PALETTE_SIMPLE
        self.resolution_name = "Medium (360p)"
        self.zoom_factor = 1.0

        self.paused = False
        self.seeking = False
        self.running = True
        self._seek_frame = None
        self.cap = None
        self.total_frames = 1
        self.fps = 24
        self.video_width = 1920
        self.video_height = 1080
        self.is_image = False
        self.static_image = None   # store numpy array for images

        self.cap_lock = threading.Lock()
        self.audio_loaded = False

        self.ascii_cols, self.ascii_rows = RESOLUTIONS[self.resolution_name]
        self._char_w = None
        self._char_h = None

        self._resize_after_id = None
        self._color_tags_initialized = False

        pygame.mixer.init()
        self._open_media()
        self._build_ui()
        self._start_playback()

    def _is_image_file(self, path):
        ext = os.path.splitext(path)[1].lower()
        return ext in ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.tif')

    def _open_media(self):
        if self._is_image_file(self.path):
            self.is_image = True
            # Load image using OpenCV (BGR)
            img = cv2.imread(self.path)
            if img is None:
                messagebox.showerror("PyStage", f"Cannot open image:\n{self.path}")
                self.root.destroy()
                return
            self.static_image = img
            self.video_height, self.video_width = img.shape[:2]
            self.total_frames = 1
            self.fps = 0
            self.audio_loaded = False
            # Stop any audio
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        else:
            self.is_image = False
            with self.cap_lock:
                if self.cap is not None:
                    self.cap.release()
                self.cap = cv2.VideoCapture(self.path)
                if not self.cap.isOpened():
                    messagebox.showerror("PyStage", f"Cannot open video:\n{self.path}")
                    self.root.destroy()
                    return
                self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 24
                self.total_frames = max(1, int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)))
                self.video_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                self.video_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self._load_audio()

    def _load_audio(self):
        if self.is_image:
            return
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.load(self.path)
            self.audio_loaded = True
            if not self.paused:
                pygame.mixer.music.play()
        except Exception:
            self.audio_loaded = False

    def _set_resolution(self, resolution_name):
        self.resolution_name = resolution_name
        self.ascii_cols, self.ascii_rows = RESOLUTIONS[resolution_name]
        display_w = self.display.winfo_width()
        display_h = self.display.winfo_height()
        if display_w > 10 and display_h > 10:
            max_char_w = display_w / self.ascii_cols
            max_char_h = display_h / self.ascii_rows
            new_size = max(3, min(20, int(min(max_char_w, max_char_h) * 0.8)))
            self.text.config(font=(FONT, new_size))
            f = font.Font(family=FONT, size=new_size)
            self._char_w = f.measure("X")
            self._char_h = f.metrics("linespace")
        self._recalc_grid()
        self._force_redraw()

    def _zoom_in(self):
        self.zoom_factor = min(4.0, self.zoom_factor + 0.25)
        self._update_zoom_label()
        self._force_redraw()

    def _zoom_out(self):
        self.zoom_factor = max(1.0, self.zoom_factor - 0.25)
        self._update_zoom_label()
        self._force_redraw()

    def _reset_zoom(self):
        self.zoom_factor = 1.0
        self._update_zoom_label()
        self._force_redraw()

    def _update_zoom_label(self):
        self.zoom_label.config(text=f"Zoom: {self.zoom_factor:.2f}x")

    def _force_redraw(self):
        """Re-render current frame (video or image) with current settings."""
        if self._char_w is None or self._char_h is None:
            return  # not ready yet
        if self.is_image:
            if self.static_image is not None:
                lines, color_indices = frame_to_ascii(self.static_image, self.ascii_cols, self.ascii_rows,
                                                      self.palette, self._char_w, self._char_h,
                                                      self.use_color, self.zoom_factor)
                self.root.after(0, self._update_display, lines, color_indices, 0)
        else:
            if self.paused and self.cap is not None:
                with self.cap_lock:
                    cur_frame = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, cur_frame)
                    ret, frame = self.cap.read()
                    if ret:
                        lines, color_indices = frame_to_ascii(frame, self.ascii_cols, self.ascii_rows,
                                                              self.palette, self._char_w, self._char_h,
                                                              self.use_color, self.zoom_factor)
                        self.root.after(0, self._update_display, lines, color_indices, cur_frame)
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, cur_frame)

    def _sync_audio_position(self, frame_number):
        if self.is_image or not self.audio_loaded or self.seeking:
            return
        try:
            pygame.mixer.music.set_pos(frame_number / self.fps)
        except:
            pass

    def _play_audio(self):
        if not self.is_image and self.audio_loaded:
            pygame.mixer.music.unpause()

    def _pause_audio(self):
        if not self.is_image and self.audio_loaded:
            pygame.mixer.music.pause()

    def _restart_audio(self):
        if not self.is_image and self.audio_loaded:
            pygame.mixer.music.stop()
            pygame.mixer.music.play()

    def _stop_audio(self):
        if not self.is_image and self.audio_loaded:
            pygame.mixer.music.stop()

    def _build_ui(self):
        title = "PyStage" + (" [IMAGE]" if self.is_image else " [VIDEO]")
        self.root.title(title)
        self.root.configure(bg=BG_COLOR)
        self.root.resizable(True, True)

        top = tk.Frame(self.root, bg=BG_COLOR)
        top.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(top, text="PyStage", font=(FONT, 13, "bold"),
                 bg=BG_COLOR, fg=TITLE_FG).pack(side="left")
        self.fname_lbl = tk.Label(top, text=f"  {os.path.basename(self.path)}",
                                  font=(FONT, 10), bg=BG_COLOR, fg=TIME_FG)
        self.fname_lbl.pack(side="left")

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

        ctrl = tk.Frame(self.root, bg=BAR_BG, pady=8)
        ctrl.pack(fill="x", side="bottom")

        # Progress bar row (hide for images)
        prog_row = tk.Frame(ctrl, bg=BAR_BG)
        prog_row.pack(fill="x", padx=14, pady=(4, 2))

        self.time_var = tk.StringVar(value="0:00 / 0:00")
        self.time_label = tk.Label(prog_row, textvariable=self.time_var,
                                   font=(FONT, 9), bg=BAR_BG, fg=TIME_FG)
        self.time_label.pack(side="right", padx=(6, 0))

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

        if self.is_image:
            # Disable progress bar and time label for images
            self.progress.config(state="disabled")
            self.time_label.config(text="[image]")
            self.progress.pack_forget()
            self.time_label.pack_forget()

        # Row 1: playback controls (disabled for images except Restart reloads image)
        btn_row1 = tk.Frame(ctrl, bg=BAR_BG)
        btn_row1.pack(pady=(4, 0))
        self.play_btn = self._btn(btn_row1, "⏸ Pause" if not self.paused else "▶ Play", self._toggle_pause)
        self.play_btn.pack(side="left", padx=5)
        self.restart_btn = self._btn(btn_row1, "↺ Restart", self._restart)
        self.restart_btn.pack(side="left", padx=5)
        if self.is_image:
            self.play_btn.config(state="disabled")
            self.restart_btn.config(text="↺ Reload", command=self._reload_image)

        # Row 2: file, color, palette, resolution, about, quit
        btn_row2 = tk.Frame(ctrl, bg=BAR_BG)
        btn_row2.pack(pady=(4, 0))
        self._btn(btn_row2, "Open", self._open_new).pack(side="left", padx=5)
        self.color_btn = self._btn(btn_row2, "Color: ON" if self.use_color else "Color: OFF", self._toggle_color)
        self.color_btn.pack(side="left", padx=5)
        self.palette_btn = self._btn(btn_row2, "Palette: Detailed" if self.use_detailed else "Palette: Simple", self._toggle_palette)
        self.palette_btn.pack(side="left", padx=5)

        self.resolution_var = tk.StringVar(value=self.resolution_name)
        resolution_menu = tk.OptionMenu(btn_row2, self.resolution_var, *RESOLUTIONS.keys(), command=self._set_resolution)
        resolution_menu.config(font=(FONT, 9, "bold"), bg=BTN_BG, fg=BTN_FG,
                              activebackground=ACCENT, activeforeground=BG_COLOR,
                              relief="flat", padx=10, pady=4, cursor="hand2", bd=0)
        resolution_menu.pack(side="left", padx=5)

        self._btn(btn_row2, "About", self._show_about).pack(side="left", padx=5)
        self._btn(btn_row2, "✕ Quit", self._quit, fg="#ff4444").pack(side="left", padx=5)

        # Row 3: zoom controls
        btn_row3 = tk.Frame(ctrl, bg=BAR_BG)
        btn_row3.pack(pady=(4, 4))
        self._btn(btn_row3, "Zoom -", self._zoom_out).pack(side="left", padx=5)
        self.zoom_label = tk.Label(btn_row3, text="Zoom: 1.00x", font=(FONT, 9, "bold"),
                                   bg=BAR_BG, fg=ACCENT)
        self.zoom_label.pack(side="left", padx=5)
        self._btn(btn_row3, "Zoom +", self._zoom_in).pack(side="left", padx=5)
        self._btn(btn_row3, "Reset Zoom", self._reset_zoom).pack(side="left", padx=5)

        # Keyboard shortcuts
        self.root.bind("<space>", lambda e: self._toggle_pause())
        self.root.bind("<Escape>", lambda e: self._quit())
        self.root.bind("<r>", lambda e: self._restart())
        self.root.bind("<c>", lambda e: self._toggle_color())
        self.root.bind("<p>", lambda e: self._toggle_palette())
        self.root.bind("<a>", lambda e: self._show_about())
        self.root.bind("<plus>", lambda e: self._zoom_in())
        self.root.bind("<minus>", lambda e: self._zoom_out())
        self.root.bind("<0>", lambda e: self._reset_zoom())
        self.root.protocol("WM_DELETE_WINDOW", self._quit)

        # Initial window size
        scr_w = self.root.winfo_screenwidth()
        scr_h = self.root.winfo_screenheight()
        win_w = min(960, int(scr_w * 0.90))
        win_h = min(620, int(scr_h * 0.90))
        ui_overhead_h = 148 + 32
        content_h = win_h - ui_overhead_h
        content_w = int(content_h * self.video_width / self.video_height) if self.video_height else win_w
        if content_w > win_w:
            content_w = win_w
            content_h = int(content_w * self.video_height / self.video_width)
        win_w = max(480, content_w + 8)
        win_h = content_h + ui_overhead_h
        self.root.geometry(f"{win_w}x{win_h}")

        self.root.after(150, self._measure_char)

    def _reload_image(self):
        """Reload the current image file (used as 'Restart' for images)."""
        img = cv2.imread(self.path)
        if img is not None:
            self.static_image = img
            self.video_height, self.video_width = img.shape[:2]
            self._force_redraw()

    def _style_scale(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("Horizontal.TScale", background=BAR_BG, troughcolor="#333",
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
        self._force_redraw()   # now char dimensions are ready

    def _recalc_grid(self):
        if self._char_w is None:
            return
        px_w = int(self.ascii_cols * self._char_w)
        px_h = int(self.ascii_rows * self._char_h)
        self.center_frame.config(width=px_w, height=px_h)
        self.text.config(width=self.ascii_cols, height=self.ascii_rows)

    def _on_display_resize(self, event):
        if self._resize_after_id:
            self.root.after_cancel(self._resize_after_id)
        self._resize_after_id = self.root.after(80, self._recalc_grid)

    def _seek_press(self):
        if self.is_image:
            return
        self.seeking = True

    def _seek_release(self):
        if self.is_image:
            return
        with self.cap_lock:
            self._seek_frame = int(self.progress_var.get())
        self.seeking = False
        if self.paused:
            self._force_seek_redraw()

    def _force_seek_redraw(self):
        if self.is_image:
            return
        with self.cap_lock:
            if self.cap and self._seek_frame is not None:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, self._seek_frame)
                ret, frame = self.cap.read()
                if ret:
                    lines, color_indices = frame_to_ascii(frame, self.ascii_cols, self.ascii_rows,
                                                          self.palette, self._char_w, self._char_h,
                                                          self.use_color, self.zoom_factor)
                    self.root.after(0, self._update_display, lines, color_indices, self._seek_frame)
                self._seek_frame = None

    def _on_scrub(self, val):
        if self.is_image:
            return
        fi = int(float(val))
        self.time_var.set(f"{fmt_time(fi / self.fps)} / {fmt_time(self.total_frames / self.fps)}")

    def _toggle_pause(self):
        if self.is_image:
            return
        self.paused = not self.paused
        self.play_btn.config(text="⏸ Pause" if not self.paused else "▶ Play")
        if self.paused:
            self._pause_audio()
        else:
            self._play_audio()

    def _restart(self):
        if self.is_image:
            self._reload_image()
            return
        with self.cap_lock:
            self._seek_frame = 0
        if self.paused:
            self._toggle_pause()
        self._restart_audio()

    def _toggle_color(self):
        self.use_color = not self.use_color
        self.color_btn.config(text="Color: ON" if self.use_color else "Color: OFF")
        self._force_redraw()

    def _toggle_palette(self):
        self.use_detailed = not self.use_detailed
        self.palette = PALETTE_DETAILED if self.use_detailed else PALETTE_SIMPLE
        self.palette_btn.config(text="Palette: Detailed" if self.use_detailed else "Palette: Simple")
        self._force_redraw()

    def _show_about(self):
        about_win = tk.Toplevel(self.root)
        about_win.title("About PyStage")
        about_win.configure(bg=BG_COLOR)
        about_win.geometry("550x380")
        about_win.resizable(False, False)
        about_win.transient(self.root)
        about_win.grab_set()

        frame = tk.Frame(about_win, bg=BG_COLOR, padx=20, pady=20)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="PyStage", font=(FONT, 18, "bold"),
                 bg=BG_COLOR, fg=ACCENT).pack(pady=(0, 5))
        tk.Label(frame, text="Version 0.5 – Video & Image Viewer", font=(FONT, 10),
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

        tk.Label(frame, text="\n• Digital zoom – works on video & images\n• Seek bar while paused (video)\n• Supports any video/image aspect ratio\n• Resolution: more characters = more detail (font auto-scales)",
                 font=(FONT, 9), bg=BG_COLOR, fg=TIME_FG).pack(pady=(10, 5))

        tk.Button(frame, text="Close", command=about_win.destroy,
                  font=(FONT, 9), bg=BTN_BG, fg=BTN_FG,
                  activebackground=ACCENT, activeforeground=BG_COLOR,
                  relief="flat", padx=15, pady=4, cursor="hand2",
                  bd=0).pack(pady=(15, 0))

    def _open_new(self):
        path = filedialog.askopenfilename(
            title="PyStage — Open media",
            filetypes=[("Media files", "*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.jpg *.jpeg *.png *.bmp *.gif *.tiff"),
                       ("Video files", "*.mp4 *.avi *.mkv *.mov *.wmv *.flv"),
                       ("Image files", "*.jpg *.jpeg *.png *.bmp *.gif *.tiff"),
                       ("All files", "*.*")]
        )
        if not path:
            return
        self.running = False
        time.sleep(0.2)
        with self.cap_lock:
            if self.cap:
                self.cap.release()
        self.path = path
        self._open_media()
        # Rebuild UI to hide/show appropriate controls
        self._rebuild_ui()

    def _rebuild_ui(self):
        # Destroy current UI and rebuild (simple approach)
        for widget in self.root.winfo_children():
            widget.destroy()
        self._build_ui()
        self._start_playback()

    def _quit(self):
        self.running = False
        with self.cap_lock:
            if self.cap:
                self.cap.release()
        self._stop_audio()
        self.root.after(200, self.root.destroy)

    def _start_playback(self):
        if self.is_image:
            # No thread needed for image
            return
        threading.Thread(target=self._play_loop, daemon=True).start()

    def _play_loop(self):
        if self.is_image:
            return
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
                self._sync_audio_position(seek_to)

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
                    self._restart_audio()
                    continue
                cur_frame = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))

            if self._char_w is None or self._char_h is None:
                time.sleep(0.02)
                continue

            lines, color_indices = frame_to_ascii(frame, self.ascii_cols, self.ascii_rows,
                                                  self.palette, self._char_w, self._char_h,
                                                  self.use_color, self.zoom_factor)
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

        if not self.is_image and not self.seeking:
            self.progress_var.set(cur_frame)
        if not self.is_image:
            self.time_var.set(f"{fmt_time(cur_frame / self.fps)} / {fmt_time(self.total_frames / self.fps)}")


def main():
    parser = argparse.ArgumentParser(description="PyStage — ASCII video & image viewer")
    parser.add_argument("media", nargs="?", default=None,
                        help="Path to video or image file")
    parser.add_argument("--color", action="store_true", help="Start with color mode ON")
    parser.add_argument("--detail", action="store_true", help="Start with detailed palette")
    args = parser.parse_args()

    root = tk.Tk()

    media_path = args.media
    if not media_path:
        root.withdraw()
        media_path = filedialog.askopenfilename(
            title="PyStage — Open media",
            filetypes=[("Media files", "*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.jpg *.jpeg *.png *.bmp *.gif *.tiff"),
                       ("Video files", "*.mp4 *.avi *.mkv *.mov *.wmv *.flv"),
                       ("Image files", "*.jpg *.jpeg *.png *.bmp *.gif *.tiff"),
                       ("All files", "*.*")]
        )
        if not media_path:
            root.destroy()
            return
        root.deiconify()
        root.lift()
        root.focus_force()

    PyStage(root, media_path, args.color, args.detail)
    root.mainloop()


if __name__ == "__main__":
    main()