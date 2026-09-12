"""
BluePulse Vision Auto-Clicker
Specialized for Blue Submit Buttons in AI / IDE Prompts.
Clicks ONCE per prompt, waits for the modal to dismiss/next to arrive.
Stop shortcut: BACKSPACE
Controls: START, PAUSE, STOP
"""

import os
import sys
import time
import ctypes
from ctypes import c_void_p, c_int, c_uint32
import threading
import tkinter as tk
import customtkinter as ctk
import pyautogui
import cv2
import numpy as np
import mss

# Enable DPI Awareness for pixel-perfect coordinates on Windows
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# Optional sound
try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

# Global hotkeys
try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

# PyAutoGUI Safety settings
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.01

TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "submit_button_template.png")


def ensure_desktop_access():
    """Ensure background threads on Windows can access the interactive desktop DC."""
    try:
        user32 = ctypes.windll.user32
        user32.OpenInputDesktop.restype = c_void_p
        user32.OpenInputDesktop.argtypes = [c_uint32, c_int, c_uint32]
        user32.SetThreadDesktop.restype = c_int
        user32.SetThreadDesktop.argtypes = [c_void_p]
        hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
    except Exception:
        pass


class RegionSelector(tk.Toplevel):
    """Full-screen translucent overlay for drag-and-drop region selection."""

    def __init__(self, parent, on_selection_complete):
        super().__init__(parent)
        self.parent = parent
        self.on_selection_complete = on_selection_complete

        self.overrideredirect(True)
        self.attributes("-alpha", 0.35)
        self.attributes("-topmost", True)
        self.config(cursor="cross")

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        self.geometry(f"{screen_w}x{screen_h}+0+0")

        self.canvas = tk.Canvas(self, bg="#050a14", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.start_x = None
        self.start_y = None
        self.rect_id = None
        self.text_id = None

        banner_text = "🎯 CLICK & DRAG TO SELECT TARGET SPACE  •  PRESS ESC TO CANCEL"
        self.canvas.create_text(
            screen_w // 2,
            50,
            text=banner_text,
            fill="#00f0ff",
            font=("Segoe UI", 16, "bold"),
        )

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Escape>", lambda e: self.cancel())

    def on_press(self, event):
        self.start_x = event.x_root
        self.start_y = event.y_root
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        if self.text_id:
            self.canvas.delete(self.text_id)

    def on_drag(self, event):
        cur_x = event.x_root
        cur_y = event.y_root

        x1 = min(self.start_x, cur_x)
        y1 = min(self.start_y, cur_y)
        x2 = max(self.start_x, cur_x)
        y2 = max(self.start_y, cur_y)
        w = x2 - x1
        h = y2 - y1

        if self.rect_id:
            self.canvas.delete(self.rect_id)
        if self.text_id:
            self.canvas.delete(self.text_id)

        self.rect_id = self.canvas.create_rectangle(
            x1, y1, x2, y2, outline="#00f0ff", width=2, fill="#003852"
        )

        dim_text = f"Space: {w} × {h} px  [{x1}, {y1}]"
        self.text_id = self.canvas.create_text(
            x1 + 10,
            max(20, y1 - 15),
            text=dim_text,
            fill="#38bdf8",
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        )

    def on_release(self, event):
        end_x = event.x_root
        end_y = event.y_root

        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)
        w = x2 - x1
        h = y2 - y1

        self.destroy()

        if w > 20 and h > 20:
            self.on_selection_complete((x1, y1, w, h))
        else:
            self.on_selection_complete(None)

    def cancel(self):
        self.destroy()
        self.on_selection_complete(None)


class AutoClickerEngine:
    """Precision vision engine: strictly detects the 'Submit' button and clicks ONCE per prompt."""

    def __init__(self, callback_on_click, callback_on_status):
        self.callback_on_click = callback_on_click
        self.callback_on_status = callback_on_status

        self.region = None  # (x, y, w, h) or None for full screen
        self.is_running = False
        self.is_paused = False
        self.thread = None

        self.use_full_screen = False
        self.sound_enabled = True

        self.total_clicks = 0
        self.fps = 0.0

        # Load Submit Button Template in grayscale and BGR
        self.template_bgr = None
        self.template_gray = None
        if os.path.exists(TEMPLATE_PATH):
            self.template_bgr = cv2.imread(TEMPLATE_PATH)
            self.template_gray = cv2.cvtColor(self.template_bgr, cv2.COLOR_BGR2GRAY)

    def start(self, region):
        """Start or resume clicking."""
        self.region = region
        if self.is_running and self.is_paused:
            self.is_paused = False
            self.callback_on_status("RUNNING", "Active • Scanning for Submit button...")
            return

        self.is_running = True
        self.is_paused = False
        self.callback_on_status("RUNNING", "Active • Scanning for Submit button...")

        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()

    def pause(self):
        """Pause clicking loop."""
        if self.is_running:
            self.is_paused = True
            self.callback_on_status("PAUSED", "Paused by user")

    def stop(self):
        """Stop clicking loop completely."""
        self.is_running = False
        self.is_paused = False
        self.callback_on_status("STOPPED", "Stopped by user")

    def _play_click_sound(self):
        if HAS_WINSOUND and self.sound_enabled:
            try:
                winsound.Beep(1850, 25)
            except Exception:
                pass

    def _find_submit_button(self, frame_bgr):
        """Strictly locate the exact 'Submit ↵' button. Returns (cx, cy, bx, by, bw, bh) or None."""
        if self.template_gray is None:
            return None

        frame_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        h, w = frame_gray.shape[:2]

        best_match = None
        # Scales to tolerate slight DPI or resolution differences
        for scale in [1.0, 0.9, 1.1, 0.85, 1.15, 1.2]:
            if scale == 1.0:
                tg = self.template_gray
            else:
                tg = cv2.resize(self.template_gray, (0, 0), fx=scale, fy=scale)

            th, tw = tg.shape[:2]
            if th > h or tw > w:
                continue

            res = cv2.matchTemplate(frame_gray, tg, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            # High confidence threshold required to strictly match the text 'Submit'
            if max_val >= 0.76:
                if best_match is None or max_val > best_match[0]:
                    best_match = (max_val, max_loc, tw, th)

        if best_match and best_match[0] >= 0.76:
            score, (mx, my), bw, bh = best_match

            # Double verification: Ensure the background area is truly the blue color
            roi = frame_bgr[my:my+bh, mx:mx+bw]
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            # Blue HSV range for IDE submit button: Hue 90-130
            lower_blue = np.array([90, 100, 70])
            upper_blue = np.array([130, 255, 255])
            mask = cv2.inRange(hsv, lower_blue, upper_blue)
            blue_ratio = np.count_nonzero(mask) / float(bw * bh)

            if blue_ratio >= 0.30:
                cx = mx + bw // 2
                cy = my + bh // 2
                return (cx, cy, mx, my, bw, bh, score)

        return None

    def _worker_loop(self):
        ensure_desktop_access()

        # State tracking: Clicks ONCE when button appears, waits until it DISAPPEARS before clicking again!
        button_present_on_last_frame = False

        scan_count = 0
        last_fps_time = time.time()

        with mss.mss() as sct:
            primary_mon = sct.monitors[1]

            while self.is_running:
                if self.is_paused:
                    time.sleep(0.08)
                    continue

                # Determine capture region
                if self.use_full_screen or not self.region:
                    rx = primary_mon["left"]
                    ry = primary_mon["top"]
                    rw = primary_mon["width"]
                    rh = primary_mon["height"]
                else:
                    rx, ry, rw, rh = self.region

                monitor = {
                    "left": int(rx),
                    "top": int(ry),
                    "width": int(rw),
                    "height": int(rh),
                }

                try:
                    sct_img = sct.grab(monitor)
                    frame_bgra = np.array(sct_img)
                    frame_bgr = cv2.cvtColor(frame_bgra, cv2.COLOR_BGRA2BGR)

                    target = self._find_submit_button(frame_bgr)

                    if target is not None:
                        cx, cy, bx, by, bw, bh, score = target
                        screen_x = int(rx + cx)
                        screen_y = int(ry + cy)

                        # ONLY CLICK ONCE when the button first appears!
                        if not button_present_on_last_frame:
                            button_present_on_last_frame = True
                            self.total_clicks += 1

                            # Dispatch automated single click
                            pyautogui.click(screen_x, screen_y)

                            threading.Thread(
                                target=self._play_click_sound, daemon=True
                            ).start()

                            self.callback_on_status(
                                "RUNNING",
                                f"Submitted! (Prompt #{self.total_clicks}) • Waiting for next prompt..."
                            )

                            self.callback_on_click(
                                (screen_x, screen_y),
                                self.total_clicks,
                                (bx, by, bw, bh),
                                (rw, rh),
                            )

                            # Allow modal/command half a second to process dismissal
                            time.sleep(0.4)
                        else:
                            # Button is still visible from the previous prompt; DO NOT CLICK AGAIN!
                            time.sleep(0.08)

                    else:
                        # Button is NOT visible in this frame
                        if button_present_on_last_frame:
                            # The previous button has successfully disappeared! Ready for the next one.
                            button_present_on_last_frame = False
                            self.callback_on_status(
                                "RUNNING",
                                "Prompt completed • Awaiting next Submit button..."
                            )

                        time.sleep(0.05)

                    # Update FPS
                    scan_count += 1
                    now = time.time()
                    if now - last_fps_time >= 1.0:
                        self.fps = scan_count / (now - last_fps_time)
                        scan_count = 0
                        last_fps_time = now

                except pyautogui.FailSafeException:
                    self.stop()
                    break
                except Exception:
                    time.sleep(0.08)


class ModernAutoClickerApp(ctk.CTk):
    """Modern Desktop Application strictly targeting Submit button with Backspace stop shortcut."""

    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("BluePulse Auto-Submitter  |  Only Clicks Submit")
        self.geometry("540x740")
        self.minsize(500, 680)
        self.configure(fg_color="#0b0f19")

        self._center_window()

        # State
        self.selected_region = None
        self.current_status = "READY"
        self.start_time = None
        self.elapsed_seconds = 0
        self.timer_active = False

        # Engine
        self.engine = AutoClickerEngine(
            callback_on_click=self._on_engine_click,
            callback_on_status=self._on_engine_status,
        )

        # UI Construction
        self._build_header()
        self._build_stop_banner()
        self._build_metrics_grid()
        self._build_target_visualizer_card()
        self._build_primary_controls()
        self._build_settings_drawer()

        self._setup_hotkeys()
        self._start_gui_pollers()

    def _center_window(self):
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        w, h = 540, 740
        x = max(0, (screen_w - w) // 2)
        y = max(0, (screen_h - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_header(self):
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=24, pady=(16, 8))

        title_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_box.pack(side="left", fill="y")

        app_title = ctk.CTkLabel(
            title_box,
            text="BLUE PULSE",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color="#38bdf8",
        )
        app_title.pack(anchor="w")

        app_subtitle = ctk.CTkLabel(
            title_box,
            text="Only Clicks Submit Button • Single-Click Per Prompt",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color="#94a3b8",
        )
        app_subtitle.pack(anchor="w")

        # Status Pill
        self.status_pill = ctk.CTkFrame(
            header_frame,
            fg_color="#1e293b",
            corner_radius=16,
            border_width=1,
            border_color="#334155",
        )
        self.status_pill.pack(side="right", pady=4)

        self.status_dot = ctk.CTkLabel(
            self.status_pill,
            text="●",
            font=ctk.CTkFont(size=14),
            text_color="#94a3b8",
        )
        self.status_dot.pack(side="left", padx=(12, 4), pady=4)

        self.status_text = ctk.CTkLabel(
            self.status_pill,
            text="READY",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color="#e2e8f0",
        )
        self.status_text.pack(side="left", padx=(0, 14), pady=4)

    def _build_stop_banner(self):
        """Prominent banner highlighting the BACKSPACE stop shortcut."""
        banner = ctk.CTkFrame(
            self,
            fg_color="#2b0f14",
            corner_radius=12,
            border_width=1,
            border_color="#ef4444",
        )
        banner.pack(fill="x", padx=24, pady=(0, 10))

        lbl_stop_notice = ctk.CTkLabel(
            banner,
            text="🛑 EMERGENCY STOP SHORTCUT:  PRESS [ BACKSPACE ] ANYTIME TO STOP",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#fca5a5",
        )
        lbl_stop_notice.pack(pady=8)

    def _build_metrics_grid(self):
        metrics_container = ctk.CTkFrame(
            self,
            fg_color="#131c2e",
            corner_radius=16,
            border_width=1,
            border_color="#1e2d4a",
        )
        metrics_container.pack(fill="x", padx=24, pady=(0, 12))

        metrics_grid = ctk.CTkFrame(metrics_container, fg_color="transparent")
        metrics_grid.pack(fill="both", padx=16, pady=10)
        metrics_grid.grid_columnconfigure((0, 1), weight=1)

        # 1. Total Submits Clicked
        card_clicks = ctk.CTkFrame(metrics_grid, fg_color="#0d1524", corner_radius=12)
        card_clicks.grid(row=0, column=0, padx=6, pady=4, sticky="nsew")

        lbl_clicks_title = ctk.CTkLabel(
            card_clicks,
            text="SUBMITS CLICKED",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#64748b",
        )
        lbl_clicks_title.pack(anchor="w", padx=12, pady=(6, 0))

        self.lbl_clicks_val = ctk.CTkLabel(
            card_clicks,
            text="0",
            font=ctk.CTkFont(family="Segoe UI", size=26, weight="bold"),
            text_color="#34d399",
        )
        self.lbl_clicks_val.pack(anchor="w", padx=12, pady=(2, 6))

        # 2. Timer
        card_timer = ctk.CTkFrame(metrics_grid, fg_color="#0d1524", corner_radius=12)
        card_timer.grid(row=0, column=1, padx=6, pady=4, sticky="nsew")

        lbl_timer_title = ctk.CTkLabel(
            card_timer,
            text="SESSION DURATION",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#64748b",
        )
        lbl_timer_title.pack(anchor="w", padx=12, pady=(6, 0))

        self.lbl_timer_val = ctk.CTkLabel(
            card_timer,
            text="00:00:00",
            font=ctk.CTkFont(family="Segoe UI", size=24, weight="bold"),
            text_color="#38bdf8",
        )
        self.lbl_timer_val.pack(anchor="w", padx=12, pady=(2, 6))

        # 3. Live State Message
        card_detail = ctk.CTkFrame(metrics_grid, fg_color="#0d1524", corner_radius=12)
        card_detail.grid(row=1, column=0, columnspan=2, padx=6, pady=4, sticky="nsew")

        lbl_detail_title = ctk.CTkLabel(
            card_detail,
            text="LIVE DETECTOR STATUS",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#64748b",
        )
        lbl_detail_title.pack(anchor="w", padx=12, pady=(6, 0))

        self.lbl_status_detail = ctk.CTkLabel(
            card_detail,
            text="Ready • Click Start to begin watching for Submit button",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#cbd5e1",
        )
        self.lbl_status_detail.pack(anchor="w", padx=12, pady=(2, 6))

    def _build_target_visualizer_card(self):
        preview_container = ctk.CTkFrame(
            self,
            fg_color="#131c2e",
            corner_radius=16,
            border_width=1,
            border_color="#1e2d4a",
        )
        preview_container.pack(fill="x", padx=24, pady=(0, 12))

        preview_header = ctk.CTkFrame(preview_container, fg_color="transparent")
        preview_header.pack(fill="x", padx=16, pady=(8, 4))

        lbl_scanner = ctk.CTkLabel(
            preview_header,
            text="RADAR TARGET VISUALIZER (ONLY CLICKS 'SUBMIT ↵')",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94a3b8",
        )
        lbl_scanner.pack(side="left")

        self.lbl_fps = ctk.CTkLabel(
            preview_header,
            text="Scan: 0 FPS",
            font=ctk.CTkFont(size=11),
            text_color="#64748b",
        )
        self.lbl_fps.pack(side="right")

        self.radar_canvas = tk.Canvas(
            preview_container,
            height=75,
            bg="#080d1a",
            highlightthickness=1,
            highlightbackground="#1e293b",
        )
        self.radar_canvas.pack(fill="x", padx=16, pady=(2, 10))
        self._draw_radar_idle()

    def _draw_radar_idle(self):
        self.radar_canvas.delete("all")
        w = self.radar_canvas.winfo_width()
        if w < 10:
            w = 480
        h = 75
        cx, cy = w // 2, h // 2

        for x in range(0, w, 40):
            self.radar_canvas.create_line(x, 0, x, h, fill="#0f172a", width=1)
        for y in range(0, h, 20):
            self.radar_canvas.create_line(0, y, w, y, fill="#0f172a", width=1)

        self.radar_canvas.create_oval(cx - 28, cy - 28, cx + 28, cy + 28, outline="#1e293b", width=1)
        self.radar_canvas.create_line(cx - 70, cy, cx + 70, cy, fill="#1e3a8a", width=1)
        self.radar_canvas.create_line(cx, cy - 28, cx, cy + 28, fill="#1e3a8a", width=1)

        self.radar_canvas.create_text(
            cx, cy, text="TARGET: BLUE SUBMIT BUTTON ↵", fill="#38bdf8", font=("Segoe UI", 10, "bold")
        )

    def _flash_target_lock(self, rel_x=0.5, rel_y=0.5):
        w = self.radar_canvas.winfo_width()
        if w < 10:
            w = 480
        h = 75

        px = int(w * rel_x)
        py = int(h * rel_y)

        self._draw_radar_idle()

        r = 15
        self.radar_canvas.create_oval(
            px - r, py - r, px + r, py + r, outline="#10b981", width=2
        )
        self.radar_canvas.create_line(px - r - 4, py, px + r + 4, py, fill="#34d399", width=2)
        self.radar_canvas.create_line(px, py - r - 4, px, py + r + 4, fill="#34d399", width=2)
        self.radar_canvas.create_text(
            px,
            max(10, py - 18),
            text="SUBMIT CLICKED! ↵",
            fill="#10b981",
            font=("Segoe UI", 9, "bold"),
        )

    def _build_primary_controls(self):
        """The 3 main commanding action buttons: START, PAUSE, STOP [Backspace]."""
        controls_frame = ctk.CTkFrame(
            self,
            fg_color="#131c2e",
            corner_radius=16,
            border_width=1,
            border_color="#1e2d4a",
        )
        controls_frame.pack(fill="x", padx=24, pady=(0, 12))

        lbl_deck = ctk.CTkLabel(
            controls_frame,
            text="PRIMARY ACTION CONTROLS",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94a3b8",
        )
        lbl_deck.pack(anchor="w", padx=16, pady=(10, 6))

        btn_row = ctk.CTkFrame(controls_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(0, 14))
        btn_row.grid_columnconfigure((0, 1, 2), weight=1)

        # 1. START
        self.btn_start = ctk.CTkButton(
            btn_row,
            text="▶  START",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            fg_color="#10b981",
            hover_color="#059669",
            text_color="#ffffff",
            height=54,
            corner_radius=12,
            command=self.handle_start,
        )
        self.btn_start.grid(row=0, column=0, padx=5, sticky="ew")

        # 2. PAUSE
        self.btn_pause = ctk.CTkButton(
            btn_row,
            text="⏸  PAUSE",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            fg_color="#d97706",
            hover_color="#b45309",
            text_color="#ffffff",
            height=54,
            corner_radius=12,
            command=self.handle_pause,
            state="disabled",
        )
        self.btn_pause.grid(row=0, column=1, padx=5, sticky="ew")

        # 3. STOP (with BACKSPACE shortcut badge!)
        self.btn_stop = ctk.CTkButton(
            btn_row,
            text="⏹  STOP\n[Backspace]",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color="#ef4444",
            hover_color="#dc2626",
            text_color="#ffffff",
            height=54,
            corner_radius=12,
            command=self.handle_stop,
            state="disabled",
        )
        self.btn_stop.grid(row=0, column=2, padx=5, sticky="ew")

    def _build_settings_drawer(self):
        """Settings drawer for Scan Scope, Space Re-selection, and Sound toggle."""
        settings_frame = ctk.CTkFrame(
            self,
            fg_color="#131c2e",
            corner_radius=16,
            border_width=1,
            border_color="#1e2d4a",
        )
        settings_frame.pack(fill="both", expand=True, padx=24, pady=(0, 16))

        title_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        title_row.pack(fill="x", padx=16, pady=(10, 6))

        lbl_settings = ctk.CTkLabel(
            title_row,
            text="TARGET SCOPE & OPTIONS",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94a3b8",
        )
        lbl_settings.pack(side="left")

        self.btn_reselect = ctk.CTkButton(
            title_row,
            text="📐 Select Target Space",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#1e293b",
            hover_color="#334155",
            text_color="#38bdf8",
            height=28,
            corner_radius=8,
            command=self.prompt_region_selection,
        )
        self.btn_reselect.pack(side="right")

        # Scope selector
        scope_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        scope_row.pack(fill="x", padx=16, pady=(2, 6))
        scope_row.grid_columnconfigure((0, 1), weight=1)

        lbl_scope = ctk.CTkLabel(
            scope_row, text="Monitoring Scope:", font=ctk.CTkFont(size=11), text_color="#94a3b8"
        )
        lbl_scope.grid(row=0, column=0, sticky="w")

        self.segmented_scope = ctk.CTkSegmentedButton(
            scope_row,
            values=["Selected Space", "Entire Screen"],
            command=self._on_scope_change,
            height=28,
            corner_radius=8,
        )
        self.segmented_scope.set("Selected Space")
        self.segmented_scope.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        # Space coordinates readout
        self.lbl_space_coords = ctk.CTkLabel(
            settings_frame,
            text="Space: None selected  (Prompts on Start, or select 'Entire Screen')",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
        )
        self.lbl_space_coords.pack(anchor="w", padx=16, pady=(4, 6))

        # Sound toggle
        sound_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        sound_row.pack(fill="x", padx=16, pady=(2, 6))

        self.switch_sound = ctk.CTkSwitch(
            sound_row,
            text="Play audio click beep on Submit",
            font=ctk.CTkFont(size=11),
            command=self._on_sound_toggle,
        )
        self.switch_sound.select()
        self.switch_sound.pack(side="left")

        # Hotkeys help footer
        footer_row = ctk.CTkFrame(settings_frame, fg_color="#0b1120", corner_radius=8)
        footer_row.pack(fill="x", padx=16, pady=(8, 10))

        lbl_keys = ctk.CTkLabel(
            footer_row,
            text="⌨ SHORTCUTS:  [Backspace] STOP   •   [F6] Start/Resume   •   [F7] Pause",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#64748b",
        )
        lbl_keys.pack(pady=5)

    def _setup_hotkeys(self):
        # Bind Backspace in Tkinter directly
        self.bind_all("<BackSpace>", lambda e: self.handle_stop())
        self.bind_all("<Escape>", lambda e: self.handle_stop())

        # Global hotkeys via keyboard library
        if HAS_KEYBOARD:
            try:
                keyboard.add_hotkey("backspace", lambda: self.after(0, self.handle_stop))
                keyboard.add_hotkey("f6", lambda: self.after(0, self.handle_start))
                keyboard.add_hotkey("f7", lambda: self.after(0, self.handle_pause))
                keyboard.add_hotkey("f8", lambda: self.after(0, self.handle_stop))
            except Exception:
                pass

    # ==================== CONTROLS ====================

    def handle_start(self):
        if self.engine.is_running and self.engine.is_paused:
            self.engine.start(self.selected_region)
            self._update_status_ui("RUNNING", "Resumed • Scanning for Submit button...")
            return

        if not self.engine.use_full_screen and not self.selected_region:
            self.prompt_region_selection(auto_start_after=True)
            return

        self._start_engine_session()

    def handle_pause(self):
        if self.engine.is_running and not self.engine.is_paused:
            self.engine.pause()
            self._update_status_ui("PAUSED", "Paused by user")

    def handle_stop(self):
        """Emergency Stop triggered via Backspace or Stop button."""
        self.engine.stop()
        self.timer_active = False
        self._update_status_ui("STOPPED", "Application Stopped [Backspace]")

    def _start_engine_session(self):
        self.timer_active = True
        self.start_time = time.time() - self.elapsed_seconds
        self.engine.start(self.selected_region)
        self._update_status_ui("RUNNING", "Active • Scanning for Submit button...")

    def prompt_region_selection(self, auto_start_after=False):
        if self.engine.is_running:
            self.handle_pause()

        self._update_status_ui("SELECTING", "Dragging target space...")
        self.withdraw()

        def on_done(selected_box):
            self.deiconify()
            self.lift()
            self.focus_force()

            if selected_box:
                self.selected_region = selected_box
                self.engine.use_full_screen = False
                self.segmented_scope.set("Selected Space")
                x, y, w, h = selected_box
                self.lbl_space_coords.configure(
                    text=f"Selected Space: X: {x} | Y: {y} | {w}×{h} px"
                )
                self._draw_radar_idle()
                if auto_start_after:
                    self._start_engine_session()
                else:
                    self._update_status_ui("READY", "Space defined • Ready to Start")
            else:
                if not self.selected_region and not self.engine.use_full_screen:
                    self.lbl_space_coords.configure(
                        text="No space selected • Click Start or switch to Entire Screen"
                    )
                self._update_status_ui("READY", "Ready")

        self.after(200, lambda: RegionSelector(self, on_done))

    def _on_scope_change(self, value):
        if value == "Entire Screen":
            self.engine.use_full_screen = True
            self.lbl_space_coords.configure(
                text="Monitoring: Entire Screen (Full Automation)"
            )
            self.btn_reselect.configure(state="disabled")
        else:
            self.engine.use_full_screen = False
            self.btn_reselect.configure(state="normal")
            if self.selected_region:
                x, y, w, h = self.selected_region
                self.lbl_space_coords.configure(
                    text=f"Selected Space: X: {x} | Y: {y} | {w}×{h} px"
                )
            else:
                self.lbl_space_coords.configure(
                    text="Selected Space: None  (Click 'Select Target Space' or 'Start')"
                )

    def _update_status_ui(self, status, detail=None):
        self.current_status = status

        if detail:
            self.lbl_status_detail.configure(text=detail)

        if status == "RUNNING":
            self.status_dot.configure(text_color="#10b981")
            self.status_text.configure(text="ACTIVE", text_color="#34d399")
            self.btn_start.configure(state="disabled", text="▶  RUNNING")
            self.btn_pause.configure(state="normal")
            self.btn_stop.configure(state="normal")
            self.btn_reselect.configure(state="disabled")

        elif status == "PAUSED":
            self.status_dot.configure(text_color="#f59e0b")
            self.status_text.configure(text="PAUSED", text_color="#fbbf24")
            self.btn_start.configure(state="normal", text="▶  RESUME")
            self.btn_pause.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.btn_reselect.configure(state="normal")

        elif status == "STOPPED":
            self.status_dot.configure(text_color="#ef4444")
            self.status_text.configure(text="STOPPED", text_color="#f87171")
            self.btn_start.configure(state="normal", text="▶  START")
            self.btn_pause.configure(state="disabled")
            self.btn_stop.configure(state="disabled")
            self.btn_reselect.configure(state="normal")

        elif status == "SELECTING":
            self.status_dot.configure(text_color="#38bdf8")
            self.status_text.configure(text="SELECTING", text_color="#38bdf8")
            self.btn_start.configure(state="disabled")
            self.btn_pause.configure(state="disabled")
            self.btn_stop.configure(state="disabled")

        else:  # READY
            self.status_dot.configure(text_color="#94a3b8")
            self.status_text.configure(text="READY", text_color="#cbd5e1")
            self.btn_start.configure(state="normal", text="▶  START")
            self.btn_pause.configure(state="disabled")
            self.btn_stop.configure(state="disabled")
            self.btn_reselect.configure(state="normal")

    def _on_sound_toggle(self):
        self.engine.sound_enabled = bool(self.switch_sound.get())

    def _on_engine_click(self, coords, total, bbox, parent_dims):
        self.after(0, lambda: self._update_click_telemetry(coords, total, bbox, parent_dims))

    def _update_click_telemetry(self, coords, total, bbox, parent_dims):
        self.lbl_clicks_val.configure(text=str(total))
        pw, ph = parent_dims
        bx, by, bw, bh = bbox
        rel_x = (bx + bw / 2) / max(1, pw)
        rel_y = (by + bh / 2) / max(1, ph)
        self._flash_target_lock(rel_x, rel_y)

    def _on_engine_status(self, status, detail=None):
        self.after(0, lambda: self._update_status_ui(status, detail))

    def _start_gui_pollers(self):
        def tick():
            if self.timer_active and self.start_time:
                self.elapsed_seconds = int(time.time() - self.start_time)
                hrs = self.elapsed_seconds // 3600
                mins = (self.elapsed_seconds % 3600) // 60
                secs = self.elapsed_seconds % 60
                self.lbl_timer_val.configure(text=f"{hrs:02d}:{mins:02d}:{secs:02d}")

            if self.engine.is_running and not self.engine.is_paused:
                self.lbl_fps.configure(text=f"Scan: {self.engine.fps:.1f} FPS")
            else:
                self.lbl_fps.configure(text="Scan: 0 FPS")

            self.after(200, tick)

        tick()


if __name__ == "__main__":
    app = ModernAutoClickerApp()
    app.mainloop()
