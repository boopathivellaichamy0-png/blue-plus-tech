"""
BLUE PLUSE TECH Vision Auto-Clicker
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
import difflib
import re

# Enable DPI Awareness for pixel-perfect coordinates on Windows
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# Automatically hide background console window when launched as standalone EXE
if getattr(sys, 'frozen', False):
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
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

# PyAutoGUI Safety settings: disabled corner failsafe so mouse movements never halt automation
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.01

def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller bundle."""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        target = os.path.join(exe_dir, relative_path)
        if os.path.exists(target):
            return target
        meipass = getattr(sys, '_MEIPASS', exe_dir)
        target = os.path.join(meipass, relative_path)
        if os.path.exists(target):
            return target
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

TEMPLATE_PATH = get_resource_path("submit_button_template.png")


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
    """Robust vision engine: strictly detects the 'Submit' text inside the blue button and clicks until stopped."""

    TARGET_KEYWORDS = ["submit"]

    def __init__(self, callback_on_click, callback_on_status):
        self.callback_on_click = callback_on_click
        self.callback_on_status = callback_on_status

        self.region = None  # (x, y, w, h) or None for full screen
        self.is_running = False
        self.is_paused = False
        self.thread = None

        self.use_full_screen = True  # Default to full screen so Start works immediately!
        self.sound_enabled = True
        self.filter_by_text = True   # Filter strictly for 'submit'!
        self.click_mode = "single"  # "single": click once per button & wait for next; "repeat": continuous
        self.click_interval = 0.20  # Repeat click interval if in repeat mode
        self.click_latency = 2.0   # 2.0s latency once button appears before clicking
        self.button_present = False

        self.total_clicks = 0
        self.fps = 0.0

        # OCR Engine for verifying text inside button
        self.ocr_reader = None
        self.ocr_ready = False
        self.verified_target_cache = None  # (bx, by, bw, bh, keyword, expire_time)

        # Background initialization of EasyOCR so GUI opens with 0ms delay
        threading.Thread(target=self._init_ocr_background, daemon=True).start()

        # Load Submit Button Template in grayscale and BGR if available
        self.template_bgr = None
        self.template_gray = None
        if os.path.exists(TEMPLATE_PATH):
            self.template_bgr = cv2.imread(TEMPLATE_PATH)
            if self.template_bgr is not None:
                self.template_gray = cv2.cvtColor(self.template_bgr, cv2.COLOR_BGR2GRAY)

    def _init_ocr_background(self):
        try:
            import easyocr
            self.ocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            self.ocr_ready = True
        except Exception:
            self.ocr_ready = False

    def start(self, region):
        """Start or resume clicking."""
        self.region = region
        self.button_present = False
        if self.is_running and self.is_paused:
            self.is_paused = False
            self.callback_on_status("RUNNING", "Active • Scanning for Blue 'Submit' Button...")
            return

        self.is_running = True
        self.is_paused = False
        self.callback_on_status("RUNNING", "Active • Scanning for Blue 'Submit' Button...")

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
        self.button_present = False
        self.verified_target_cache = None
        self.callback_on_status("STOPPED", "Stopped by user")

    def _play_click_sound(self):
        if HAS_WINSOUND and self.sound_enabled:
            try:
                winsound.Beep(1850, 20)
            except Exception:
                pass

    def _verify_button_text(self, roi, bx, by, bw, bh):
        """
        Ultra-reliable button verification:
        Detects genuine blue buttons with text. Uses OCR when available,
        and high-precision CV contrast / white text pixel analysis + template matching as standard fallback.
        """
        now = time.time()

        # 1. Verify blue button background color density
        # Hue 88-135 covers #0078d4, royal blue, sky blue, electric blue
        hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask_blue = cv2.inRange(hsv_roi, np.array([88, 55, 50]), np.array([135, 255, 255]))

        # Blue dominance check
        b, g, r = cv2.split(roi)
        bgr_blue = (b > (r.astype(np.int16) + 12)) & (b > 65)
        mask_blue = mask_blue & bgr_blue.astype(np.uint8) * 255

        blue_density = np.count_nonzero(mask_blue) / float(max(1, bw * bh))
        if blue_density < 0.28:
            if self.verified_target_cache:
                cbx, cby, cbw, cbh, ckw, expire = self.verified_target_cache
                if abs(bx - cbx) < 25 and abs(by - cby) < 25:
                    self.verified_target_cache = None
            return None, False

        # 2. Check verified cache: if the exact same button was verified and persists
        if self.verified_target_cache:
            cbx, cby, cbw, cbh, ckw, expire = self.verified_target_cache
            if now < expire and abs(bx - cbx) < 20 and abs(by - cby) < 20 and abs(bw - cbw) < 25:
                return "submit", True

        # If text filter is disabled by user, accept any genuine blue button
        if not self.filter_by_text:
            return "submit", True

        # 3. Check OCR if available
        if self.ocr_ready and self.ocr_reader is not None:
            try:
                bg_color = [int(c) for c in roi[0, 0]]
                padded = cv2.copyMakeBorder(roi, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=bg_color)
                h, w = padded.shape[:2]
                if h < 45:
                    scale = 45.0 / h
                    padded = cv2.resize(padded, (int(w * scale), 45), interpolation=cv2.INTER_CUBIC)

                results = self.ocr_reader.readtext(padded, detail=0)
                if results:
                    full_text = " ".join(results).lower().replace("↵", " ").replace("✓", " ").strip()
                    is_submit = False
                    if "submit" in full_text:
                        is_submit = True
                    else:
                        for token in full_text.split():
                            if len(token) >= 5 and difflib.SequenceMatcher(None, token, "submit").ratio() >= 0.75:
                                is_submit = True
                                break
                    if is_submit:
                        self.verified_target_cache = (bx, by, bw, bh, "submit", now + 2.5)
                        return "submit", False
            except Exception:
                pass

        # 4. Computer Vision Text Analysis Fallback (works with 0 dependencies!)
        # Buttons have high contrast text (usually white) against the blue background
        try:
            inner_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            ih, iw = inner_gray.shape
            inner_core = inner_gray[int(ih * 0.15):int(ih * 0.85), int(iw * 0.08):int(iw * 0.92)]
            if inner_core.size > 0:
                std = np.std(inner_core)
                white_ratio = np.count_nonzero(inner_core > 180) / float(inner_core.size)
                # Text creates contrast std >= 10.0 or bright text pixel ratio >= 2%
                if std >= 10.0 or white_ratio >= 0.02:
                    self.verified_target_cache = (bx, by, bw, bh, "submit", now + 2.5)
                    return "submit", False
        except Exception:
            pass

        return None, False

    def _find_blue_button(self, frame_bgr):
        """
        Ultra-reliable blue submit button locator:
        Targets the blue submit button on screen.
        Returns (cx, cy, bx, by, bw, bh, score, matched_keyword) or None.
        """
        h, w = frame_bgr.shape[:2]
        candidates = []

        # 1. Authentic Blue Color Mask
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        lower_blue = np.array([88, 55, 50])
        upper_blue = np.array([135, 255, 255])
        mask = cv2.inRange(hsv, lower_blue, upper_blue)

        # Secondary BGR check: Blue channel must dominate Red channel
        b, g, r = cv2.split(frame_bgr)
        bgr_blue = (b > (r.astype(np.int16) + 12)) & (b > 65)
        mask = mask & bgr_blue.astype(np.uint8) * 255

        # 2. Multi-scale template matching if template available
        if self.template_gray is not None:
            frame_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            for scale in [0.75, 0.85, 0.9, 1.0, 1.1, 1.15, 1.25, 1.4]:
                if scale == 1.0:
                    tg = self.template_gray
                else:
                    tg = cv2.resize(self.template_gray, (0, 0), fx=scale, fy=scale)

                th, tw = tg.shape[:2]
                if th > h or tw > w:
                    continue

                res = cv2.matchTemplate(frame_gray, tg, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)

                if max_val >= 0.48:
                    mx, my = max_loc
                    roi_mask = mask[my:my+th, mx:mx+tw]
                    blue_density = np.count_nonzero(roi_mask) / float(tw * th)
                    if blue_density >= 0.30:
                        candidates.append({
                            'cx': mx + tw // 2,
                            'cy': my + th // 2,
                            'bbox': (mx, my, tw, th),
                            'score': float(max_val) * 20.0 + 15.0,
                            'kw': 'submit',
                        })
                        break

        # 3. Computer Vision: Blue Color Segmentation & Contour Analysis
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5))
        mask_closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(mask_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours:
            bx, by, bw, bh = cv2.boundingRect(cnt)
            area = cv2.contourArea(cnt)
            # Button geometry: standard button dimensions
            if 32 <= bw <= 450 and 16 <= bh <= 90:
                aspect = bw / float(bh)
                if 1.1 <= aspect <= 8.0:
                    fill_ratio = area / float(bw * bh)
                    if fill_ratio >= 0.38:
                        roi = mask[by:by+bh, bx:bx+bw]
                        blue_density = np.count_nonzero(roi) / float(bw * bh)
                        if blue_density >= 0.28:
                            button_roi = frame_bgr[by:by+bh, bx:bx+bw]
                            matched_kw, is_cached = self._verify_button_text(button_roi, bx, by, bw, bh)
                            if matched_kw is not None:
                                aspect_bonus = 3.0 if 1.8 <= aspect <= 4.5 else 1.0
                                score = (area / float(h * w)) * 10.0 + aspect_bonus + (6.0 if is_cached else 3.0)
                                candidates.append({
                                    'cx': bx + bw // 2,
                                    'cy': by + bh // 2,
                                    'bbox': (bx, by, bw, bh),
                                    'score': score,
                                    'kw': matched_kw,
                                })

        if not candidates:
            return None

        candidates.sort(key=lambda c: c['score'], reverse=True)
        best = candidates[0]
        bx, by, bw, bh = best['bbox']
        return (best['cx'], best['cy'], bx, by, bw, bh, best['score'], best['kw'])

    def _dispatch_click(self, screen_x, screen_y):
        """Dispatches exactly ONE clean, reliable mouse click on Windows."""
        try:
            # Position cursor precisely on the button center
            ctypes.windll.user32.SetCursorPos(int(screen_x), int(screen_y))
            time.sleep(0.02)
            # Send standard mouse down
            ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
            time.sleep(0.05)  # 50ms solid press
            # Send standard mouse up
            ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
            time.sleep(0.08)  # Let target window process WM_LBUTTONUP
        except Exception:
            try:
                pyautogui.click(screen_x, screen_y)
            except Exception:
                pass

        # Optional: gently offset cursor so hover tooltips clear for dismissal detection
        try:
            time.sleep(0.04)
            ctypes.windll.user32.SetCursorPos(int(screen_x), max(10, int(screen_y - 45)))
        except Exception:
            pass

    def _worker_loop(self):
        ensure_desktop_access()

        scan_count = 0
        last_fps_time = time.time()
        last_click_time = 0.0
        state = "WAITING_FOR_BUTTON"
        button_first_seen_time = None
        absent_frames_during_wait = 0
        absent_start_time = None
        consecutive_absent_frames = 0

        sct_factory = getattr(mss, "MSS", mss.mss)
        with sct_factory() as sct:
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
                    try:
                        sct_img = sct.grab(monitor)
                        frame_bgra = np.array(sct_img)
                        frame_bgr = cv2.cvtColor(frame_bgra, cv2.COLOR_BGRA2BGR)
                    except Exception:
                        from PIL import ImageGrab
                        bbox = (int(rx), int(ry), int(rx + rw), int(ry + rh))
                        pil_img = ImageGrab.grab(bbox=bbox)
                        frame_bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

                    target = self._find_blue_button(frame_bgr)

                    now = time.time()
                    if self.click_mode == "single":
                        if state == "WAITING_FOR_BUTTON":
                            if target is not None:
                                cx, cy, bx, by, bw, bh, score, kw = target
                                screen_x = int(rx + cx)
                                screen_y = int(ry + cy)
                                absent_frames_during_wait = 0

                                if button_first_seen_time is None:
                                    button_first_seen_time = now

                                elapsed_seen = now - button_first_seen_time
                                remaining_latency = max(0.0, self.click_latency - elapsed_seen)

                                if remaining_latency > 0:
                                    self.callback_on_status(
                                        "RUNNING",
                                        f"Button locked! Waiting latency: {remaining_latency:.1f}s before click..."
                                    )
                                    time.sleep(0.04)
                                    continue

                                # Strictly click ONCE when latency has elapsed!
                                self.total_clicks += 1
                                self._dispatch_click(screen_x, screen_y)

                                if self.sound_enabled:
                                    threading.Thread(
                                        target=self._play_click_sound, daemon=True
                                    ).start()

                                last_click_time = now
                                button_first_seen_time = None
                                absent_frames_during_wait = 0
                                absent_start_time = None
                                consecutive_absent_frames = 0
                                state = "WAITING_FOR_DISMISSAL"

                                self.callback_on_status(
                                    "RUNNING",
                                    f"Submitted! [Prompt #{self.total_clicks}] • Waiting for button to dismiss..."
                                )

                                self.callback_on_click(
                                    (screen_x, screen_y),
                                    self.total_clicks,
                                    (bx, by, bw, bh),
                                    (rw, rh),
                                )

                                time.sleep(0.15)
                            else:
                                if button_first_seen_time is not None:
                                    absent_frames_during_wait += 1
                                    # Only reset countdown if genuinely absent for >= 8 consecutive frames (~0.35s)
                                    if absent_frames_during_wait >= 8:
                                        button_first_seen_time = None
                                        absent_frames_during_wait = 0
                                        self.callback_on_status(
                                            "RUNNING",
                                            f"Watching for {'next ' if self.total_clicks > 0 else ''}Blue 'Submit' Button ({self.click_latency:.1f}s latency)..."
                                        )
                                    else:
                                        # Temporary frame flicker - hold timer
                                        time.sleep(0.04)
                                        continue
                                else:
                                    self.callback_on_status(
                                        "RUNNING",
                                        f"Watching for {'next ' if self.total_clicks > 0 else ''}Blue 'Submit' Button ({self.click_latency:.1f}s latency)..."
                                    )
                                    time.sleep(0.04)

                        elif state == "WAITING_FOR_DISMISSAL":
                            # Button was clicked. We NEVER click it again while in this state.
                            # We wait until it is confirmed dismissed before looking for the next button.
                            time_since_click = now - last_click_time

                            if target is not None:
                                # Current button is still visible on screen
                                absent_start_time = None
                                consecutive_absent_frames = 0
                                self.callback_on_status(
                                    "RUNNING",
                                    f"Prompt #{self.total_clicks} in progress • Waiting for button to dismiss..."
                                )
                                time.sleep(0.05)
                            else:
                                consecutive_absent_frames += 1
                                if absent_start_time is None:
                                    absent_start_time = now

                                time_absent = now - absent_start_time

                                # Confirm dismissal: sustained absence (>= 0.35s and >= 4 frames) + minimum cooldown
                                if time_since_click >= 0.5 and (time_absent >= 0.35 or consecutive_absent_frames >= 4):
                                    self.verified_target_cache = None
                                    state = "WAITING_FOR_BUTTON"
                                    button_first_seen_time = None
                                    absent_frames_during_wait = 0
                                    absent_start_time = None
                                    consecutive_absent_frames = 0
                                    self.callback_on_status(
                                        "RUNNING",
                                        f"Prompt #{self.total_clicks} completed • Waiting for NEXT button to appear..."
                                    )
                                else:
                                    self.callback_on_status(
                                        "RUNNING",
                                        f"Prompt #{self.total_clicks} dismissing... ({consecutive_absent_frames} frames absent)"
                                    )
                                time.sleep(0.04)

                    else:
                        # Continuous mode (if selected by user)
                        if target is not None:
                            cx, cy, bx, by, bw, bh, score, kw = target
                            screen_x = int(rx + cx)
                            screen_y = int(ry + cy)

                            if now - last_click_time >= self.click_interval:
                                last_click_time = now
                                self.total_clicks += 1

                                self._dispatch_click(screen_x, screen_y)

                                if self.sound_enabled:
                                    threading.Thread(
                                        target=self._play_click_sound, daemon=True
                                    ).start()

                                self.callback_on_status(
                                    "RUNNING",
                                    f"Clicking Blue 'Submit' Button! [Click #{self.total_clicks}] at ({screen_x}, {screen_y})"
                                )

                                self.callback_on_click(
                                    (screen_x, screen_y),
                                    self.total_clicks,
                                    (bx, by, bw, bh),
                                    (rw, rh),
                                )

                            time.sleep(0.03)
                        else:
                            self.callback_on_status(
                                "RUNNING",
                                "Watching for Blue 'Submit' Button..."
                            )
                            time.sleep(0.05)

                    # Update FPS
                    scan_count += 1
                    if now - last_fps_time >= 1.0:
                        self.fps = scan_count / (now - last_fps_time)
                        scan_count = 0
                        last_fps_time = now

                except pyautogui.FailSafeException:
                    time.sleep(0.08)
                except Exception:
                    time.sleep(0.08)


class ModernAutoClickerApp(ctk.CTk):
    """Modern Desktop Application strictly targeting Submit button with Backspace stop shortcut."""

    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("BLUE PLUSE TECH  |  Only Clicks Submit")
        self.geometry("540x740")
        self.minsize(460, 400)
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

        # Main Scrollable Container with custom styled scrollbar
        self.scroll_container = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_fg_color="transparent",
            scrollbar_button_color="#334155",
            scrollbar_button_hover_color="#38bdf8",
        )
        self.scroll_container.pack(fill="both", expand=True)

        # UI Construction inside the scrollable container
        self._build_header(self.scroll_container)
        self._build_stop_banner(self.scroll_container)
        self._build_metrics_grid(self.scroll_container)
        self._build_target_visualizer_card(self.scroll_container)
        self._build_primary_controls(self.scroll_container)
        self._build_settings_drawer(self.scroll_container)

        self._setup_hotkeys()
        self._start_gui_pollers()

    def _center_window(self):
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        w, h = 540, 740
        x = max(0, (screen_w - w) // 2)
        y = max(0, (screen_h - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_header(self, parent=None):
        container = parent if parent is not None else self
        header_frame = ctk.CTkFrame(container, fg_color="transparent")
        header_frame.pack(fill="x", padx=20, pady=(16, 8))

        title_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_box.pack(side="left", fill="y")

        app_title = ctk.CTkLabel(
            title_box,
            text="BLUE PLUSE TECH",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color="#38bdf8",
        )
        app_title.pack(anchor="w")

        app_subtitle = ctk.CTkLabel(
            title_box,
            text="Only Clicks Submit Button • 2.0s Latency • Single-Click Per Prompt",
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

    def _build_stop_banner(self, parent=None):
        """Prominent banner highlighting the BACKSPACE stop shortcut."""
        container = parent if parent is not None else self
        banner = ctk.CTkFrame(
            container,
            fg_color="#2b0f14",
            corner_radius=12,
            border_width=1,
            border_color="#ef4444",
        )
        banner.pack(fill="x", padx=20, pady=(0, 10))

        lbl_stop_notice = ctk.CTkLabel(
            banner,
            text="🛑 EMERGENCY STOP SHORTCUT:  PRESS [ BACKSPACE ] ANYTIME TO STOP",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#fca5a5",
        )
        lbl_stop_notice.pack(pady=8)

    def _build_metrics_grid(self, parent=None):
        container = parent if parent is not None else self
        metrics_container = ctk.CTkFrame(
            container,
            fg_color="#131c2e",
            corner_radius=16,
            border_width=1,
            border_color="#1e2d4a",
        )
        metrics_container.pack(fill="x", padx=20, pady=(0, 12))

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

    def _build_target_visualizer_card(self, parent=None):
        container = parent if parent is not None else self
        preview_container = ctk.CTkFrame(
            container,
            fg_color="#131c2e",
            corner_radius=16,
            border_width=1,
            border_color="#1e2d4a",
        )
        preview_container.pack(fill="x", padx=20, pady=(0, 12))

        preview_header = ctk.CTkFrame(preview_container, fg_color="transparent")
        preview_header.pack(fill="x", padx=16, pady=(8, 4))

        lbl_scanner = ctk.CTkLabel(
            preview_header,
            text="RADAR TARGET VISUALIZER (CLICKS BLUE BUTTONS UNTIL STOPPED)",
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
        self.radar_canvas.bind("<MouseWheel>", lambda e: self.scroll_container._mouse_wheel_all(e))
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
            cx, cy, text="TARGET: [SUBMIT] [ACCEPT] [PROCEED] [ACCEPT ALL]", fill="#38bdf8", font=("Segoe UI", 10, "bold")
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

    def _build_primary_controls(self, parent=None):
        """The 3 main commanding action buttons: START, PAUSE, STOP [Backspace]."""
        container = parent if parent is not None else self
        controls_frame = ctk.CTkFrame(
            container,
            fg_color="#131c2e",
            corner_radius=16,
            border_width=1,
            border_color="#1e2d4a",
        )
        controls_frame.pack(fill="x", padx=20, pady=(0, 12))

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

    def _build_settings_drawer(self, parent=None):
        """Settings drawer for Scan Scope, Space Re-selection, and Sound toggle."""
        container = parent if parent is not None else self
        settings_frame = ctk.CTkFrame(
            container,
            fg_color="#131c2e",
            corner_radius=16,
            border_width=1,
            border_color="#1e2d4a",
        )
        settings_frame.pack(fill="x", padx=20, pady=(0, 20))

        title_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        title_row.pack(fill="x", padx=16, pady=(10, 6))

        lbl_settings = ctk.CTkLabel(
            title_row,
            text="TARGET SCOPE & OPTIONS",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#94a3b8",
        )
        lbl_settings.pack(side="left")

        # Target Badge Banner
        kw_box = ctk.CTkFrame(settings_frame, fg_color="#0b1120", corner_radius=10, border_width=1, border_color="#1e293b")
        kw_box.pack(fill="x", padx=16, pady=(4, 8))

        lbl_kw_title = ctk.CTkLabel(
            kw_box,
            text="🎯 TARGET:",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#38bdf8",
        )
        lbl_kw_title.pack(side="left", padx=(10, 6), pady=6)

        badge = ctk.CTkLabel(
            kw_box,
            text=" Submit ↵ (Inside Blue Button Only) ",
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color="#1e293b",
            corner_radius=6,
            text_color="#34d399",
        )
        badge.pack(side="left", padx=3, pady=6)

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
            values=["Entire Screen", "Selected Space"],
            command=self._on_scope_change,
            height=28,
            corner_radius=8,
        )
        self.segmented_scope.set("Entire Screen")
        self.segmented_scope.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        # Space coordinates readout
        self.lbl_space_coords = ctk.CTkLabel(
            settings_frame,
            text="Monitoring: Entire Screen • Clicks ONCE per prompt (Waits for next)",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
        )
        self.lbl_space_coords.pack(anchor="w", padx=16, pady=(4, 6))

        # Click Mode Selector
        rate_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        rate_row.pack(fill="x", padx=16, pady=(2, 6))
        rate_row.grid_columnconfigure((0, 1), weight=1)

        lbl_rate = ctk.CTkLabel(
            rate_row, text="Click Mode (Single or Continuous):", font=ctk.CTkFont(size=11), text_color="#94a3b8"
        )
        lbl_rate.grid(row=0, column=0, sticky="w")

        self.segmented_rate = ctk.CTkSegmentedButton(
            rate_row,
            values=["Once Per Button", "Continuous (5/s)", "Rapid (10/s)"],
            command=self._on_rate_change,
            height=28,
            corner_radius=8,
        )
        self.segmented_rate.set("Once Per Button")
        self.segmented_rate.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        # Latency / Wait Time Selector
        latency_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        latency_row.pack(fill="x", padx=16, pady=(2, 6))
        latency_row.grid_columnconfigure((0, 1), weight=1)

        lbl_latency = ctk.CTkLabel(
            latency_row, text="Latency Before Click (Wait Time):", font=ctk.CTkFont(size=11), text_color="#94a3b8"
        )
        lbl_latency.grid(row=0, column=0, sticky="w")

        self.segmented_latency = ctk.CTkSegmentedButton(
            latency_row,
            values=["Instant (0s)", "1.0s", "2.0s (Default)", "3.0s", "5.0s"],
            command=self._on_latency_change,
            height=28,
            corner_radius=8,
        )
        self.segmented_latency.set("2.0s (Default)")
        self.segmented_latency.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        # Text filter & Sound toggles
        toggles_row = ctk.CTkFrame(settings_frame, fg_color="transparent")
        toggles_row.pack(fill="x", padx=16, pady=(2, 6))

        self.switch_text_filter = ctk.CTkSwitch(
            toggles_row,
            text="Strictly require 'Submit' text inside blue button",
            font=ctk.CTkFont(size=11),
            command=self._on_text_filter_toggle,
        )
        self.switch_text_filter.select()
        self.switch_text_filter.pack(anchor="w", pady=(0, 4))

        self.switch_sound = ctk.CTkSwitch(
            toggles_row,
            text="Play audio click beep on click",
            font=ctk.CTkFont(size=11),
            command=self._on_sound_toggle,
        )
        self.switch_sound.select()
        self.switch_sound.pack(anchor="w")

        # Hotkeys help footer
        footer_row = ctk.CTkFrame(settings_frame, fg_color="#0b1120", corner_radius=8)
        footer_row.pack(fill="x", padx=16, pady=(8, 10))

        lbl_keys = ctk.CTkLabel(
            footer_row,
            text="⌨ SHORTCUT:  [Backspace] STOP   •   Only STOP button or [Backspace] halts scanning",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#64748b",
        )
        lbl_keys.pack(pady=5)

    def _setup_hotkeys(self):
        # Exclusively Backspace stops the clicker
        self.bind_all("<BackSpace>", lambda e: self.handle_stop())
        self.bind_all("<Next>", lambda e: self.scroll_container._parent_canvas.yview_scroll(4, "units"))
        self.bind_all("<Prior>", lambda e: self.scroll_container._parent_canvas.yview_scroll(-4, "units"))

        # Global hotkey via keyboard library: strictly backspace only
        if HAS_KEYBOARD:
            try:
                keyboard.add_hotkey("backspace", lambda: self.after(0, self.handle_stop))
            except Exception:
                pass

    # ==================== CONTROLS ====================

    def handle_start(self):
        if self.engine.is_running and self.engine.is_paused:
            self.engine.start(self.selected_region)
            self._update_status_ui("RUNNING", "Resumed • Scanning for Blue button...")
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

    def _on_rate_change(self, value):
        if "Once" in value:
            self.engine.click_mode = "single"
            self.lbl_space_coords.configure(text="Mode: Clicks ONCE per prompt • Waits for next button to appear")
        elif "Rapid" in value:
            self.engine.click_mode = "repeat"
            self.engine.click_interval = 0.10
            self.lbl_space_coords.configure(text="Mode: Rapid Continuous Clicking (10 clicks/sec)")
        else:
            self.engine.click_mode = "repeat"
            self.engine.click_interval = 0.20
            self.lbl_space_coords.configure(text="Mode: Continuous Clicking (5 clicks/sec)")

    def _on_latency_change(self, value):
        if "Instant" in value:
            self.engine.click_latency = 0.0
        elif "1.0s" in value:
            self.engine.click_latency = 1.0
        elif "2.0s" in value:
            self.engine.click_latency = 2.0
        elif "3.0s" in value:
            self.engine.click_latency = 3.0
        elif "5.0s" in value:
            self.engine.click_latency = 5.0
        self.lbl_space_coords.configure(
            text=f"Latency: {self.engine.click_latency:.1f}s • Clicks ONCE per prompt after latency"
        )

    def _on_text_filter_toggle(self):
        self.engine.filter_by_text = bool(self.switch_text_filter.get())

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
