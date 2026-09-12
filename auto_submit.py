"""
BluePulse Quick Auto-Submit CLI
Lightweight background script to auto-detect and click the blue 'Submit' button
Clicks ONCE per prompt, waits for it to dismiss and next to arrive.
Press BACKSPACE or Ctrl+C to stop.
"""

import os
import sys
import time
import ctypes
from ctypes import c_void_p, c_int, c_uint32
import pyautogui
import cv2
import numpy as np
import mss

# DPI awareness
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.01

TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "submit_button_template.png")

def ensure_desktop():
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

def main():
    print("=" * 60)
    print(" ⚡ BLUEPULSE AUTONOMOUS SUBMIT CLICKER")
    print(" [✓] Mode: ONLY Click 'Submit ↵' Button")
    print(" [✓] Logic: Click ONCE per prompt • Wait for next to arrive")
    print(" [🛑] STOP SHORTCUT: Press [ BACKSPACE ] or Ctrl+C")
    print("=" * 60)

    ensure_desktop()

    tpl_gray = None
    if os.path.exists(TEMPLATE_PATH):
        tpl_bgr = cv2.imread(TEMPLATE_PATH)
        tpl_gray = cv2.cvtColor(tpl_bgr, cv2.COLOR_BGR2GRAY)
        print(" [✓] Loaded 'Submit ↵' template.")
    else:
        print(" [❌] ERROR: submit_button_template.png not found!")
        return

    should_stop = False

    def on_stop():
        nonlocal should_stop
        should_stop = True
        print("\n [🛑] BACKSPACE pressed! Stopping...")

    if HAS_KEYBOARD:
        keyboard.add_hotkey("backspace", on_stop)

    total_clicks = 0
    button_present_on_last_frame = False

    with mss.mss() as sct:
        mon = sct.monitors[1]
        print(f" [✓] Watching display ({mon['width']}x{mon['height']})...\n")

        try:
            while not should_stop:
                sct_img = sct.grab(mon)
                frame_bgra = np.array(sct_img)
                frame_bgr = cv2.cvtColor(frame_bgra, cv2.COLOR_BGRA2BGR)
                frame_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                h, w = frame_gray.shape[:2]

                best_match = None
                for scale in [1.0, 0.9, 1.1, 0.85, 1.15, 1.2]:
                    if scale == 1.0:
                        tg = tpl_gray
                    else:
                        tg = cv2.resize(tpl_gray, (0, 0), fx=scale, fy=scale)
                    th, tw = tg.shape[:2]
                    if th > h or tw > w:
                        continue
                    res = cv2.matchTemplate(frame_gray, tg, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                    if max_val >= 0.76:
                        if best_match is None or max_val > best_match[0]:
                            best_match = (max_val, max_loc, tw, th)

                is_detected = False
                if best_match and best_match[0] >= 0.76:
                    score, (mx, my), bw, bh = best_match
                    roi = frame_bgr[my:my+bh, mx:mx+bw]
                    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
                    mask = cv2.inRange(hsv, np.array([90, 100, 70]), np.array([130, 255, 255]))
                    if (np.count_nonzero(mask) / float(bw * bh)) >= 0.30:
                        is_detected = True
                        cx = mx + bw // 2
                        cy = my + bh // 2
                        screen_x = mon["left"] + cx
                        screen_y = mon["top"] + cy

                if is_detected:
                    if not button_present_on_last_frame:
                        button_present_on_last_frame = True
                        total_clicks += 1
                        print(f" [🎯] Submit button detected (confidence {score:.2f})! Clicking ONCE at ({screen_x}, {screen_y})...")
                        pyautogui.click(screen_x, screen_y)
                        print(f"      Submitted! Total: {total_clicks}. Waiting for modal dismissal...")
                        time.sleep(0.4)
                    else:
                        time.sleep(0.08)
                else:
                    if button_present_on_last_frame:
                        button_present_on_last_frame = False
                        print(" [⏳] Previous modal dismissed. Ready & awaiting next prompt...")
                    time.sleep(0.05)

        except KeyboardInterrupt:
            pass
        except pyautogui.FailSafeException:
            print("\n [⏹] Mouse moved to corner (FailSafe).")

    print(f"\n [⏹] Session Ended. Total Submits Clicked: {total_clicks}")

if __name__ == "__main__":
    main()
