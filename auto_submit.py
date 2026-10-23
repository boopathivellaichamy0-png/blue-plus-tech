import os
import sys
import time
import ctypes
from ctypes import c_void_p, c_int, c_uint32
import pyautogui
import cv2
import numpy as np
import mss
import difflib
import re

# Native Windows OCR
try:
    import winocr
    HAS_WINOCR = True
except Exception:
    HAS_WINOCR = False

# Strictly accepted button target keywords
TARGET_KEYWORDS = ["submit", "accept all", "accept", "proceed"]

def normalize_button_text(text):
    if not text:
        return ""
    s = text.lower().replace("'", "").replace("’", "")
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', ' ', s)
    return ' '.join(cleaned.split())

def match_target_button_keyword(text):
    """
    Strictly verifies whether text matches one of the target button keywords:
    - 'submit'
    - 'accept'
    - 'accept all'
    - 'proceed'
    
    Returns matched keyword string or None.
    Rejects any negative phrasing ('do not accept', 'cannot submit', 'cancel', etc.).
    """
    clean = normalize_button_text(text)
    if not clean:
        return None

    negatives = {"not", "dont", "no", "cancel", "decline", "reject", "close", "skip", "ignore", "never"}
    tokens = clean.split()
    tokens_set = set(tokens)

    if tokens_set.intersection(negatives):
        return None
    if any(neg in clean for neg in ["dont", "do not", "cannot", "cant"]):
        return None

    if "accept all" in clean:
        return "accept all"
    if "submit" in tokens_set or clean == "submit":
        return "submit"
    if "proceed" in tokens_set or clean == "proceed":
        return "proceed"
    if "accept" in tokens_set or clean == "accept":
        return "accept"

    for tok in tokens:
        for kw in ["submit", "accept", "proceed"]:
            if len(tok) >= 4 and difflib.SequenceMatcher(None, tok, kw).ratio() >= 0.80:
                return kw

    return None

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
TARGET_KEYWORDS = ["submit"]

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

def dispatch_click(screen_x, screen_y):
    """Dispatches exactly ONE clean, reliable mouse click on Windows and clears cursor from button."""
    orig_x, orig_y = None, None
    try:
        orig_x, orig_y = pyautogui.position()
    except Exception:
        pass

    clicked = False
    try:
        ctypes.windll.user32.SetCursorPos(int(screen_x), int(screen_y))
        time.sleep(0.02)
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
        time.sleep(0.05)
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
        time.sleep(0.08)
        clicked = True
    except Exception:
        pass

    if not clicked:
        try:
            pyautogui.click(screen_x, screen_y)
        except Exception:
            pass



# Cached verified target: (bx, by, bw, bh, keyword, expire_time)
_verified_cache = None

def verify_button_text(roi, bx, by, bw, bh, ocr_reader):
    global _verified_cache
    now = time.time()

    # 1. Physical Button Container Checks (Reject Normal Text sentences, letters, abnormal boxes)
    if bw < 35 or bw > 480 or bh < 18 or bh > 95:
        return None

    aspect = bw / float(bh)
    if aspect < 1.05 or aspect > 8.5:
        return None

    # 2. Check Blue Button Color Fill (Density)
    hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    lower_blue = np.array([85, 45, 45])
    upper_blue = np.array([135, 255, 255])
    mask_blue = cv2.inRange(hsv_roi, lower_blue, upper_blue)

    b, g, r = cv2.split(roi)
    bgr_blue = (b > (r.astype(np.int16) + 10)) & (b > 60)
    mask_blue = mask_blue & bgr_blue.astype(np.uint8) * 255

    blue_density = np.count_nonzero(mask_blue) / float(max(1, bw * bh))

    # Reject normal text on white page
    gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    white_px_ratio = np.count_nonzero(gray_roi > 240) / float(gray_roi.size)
    if white_px_ratio > 0.85 and blue_density < 0.25:
        return None

    if blue_density < 0.28:
        if _verified_cache:
            cbx, cby, cbw, cbh, ckw, expire = _verified_cache
            if abs(bx - cbx) < 25 and abs(by - cby) < 25:
                _verified_cache = None
        return None

    # 3. Check verified cache
    if _verified_cache:
        cbx, cby, cbw, cbh, ckw, expire = _verified_cache
        if now < expire and abs(bx - cbx) < 20 and abs(by - cby) < 20 and abs(bw - cbw) < 25:
            return ckw

    # 4. OCR check: WinOCR (Windows native) -> EasyOCR
    detected_text = ""
    bg_color = [int(c) for c in roi[0, 0]]
    padded = cv2.copyMakeBorder(roi, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=bg_color)
    ph, pw = padded.shape[:2]
    if ph < 50:
        scale = 50.0 / ph
        padded = cv2.resize(padded, (int(pw * scale), 50), interpolation=cv2.INTER_CUBIC)

    if HAS_WINOCR:
        try:
            res = winocr.recognize_cv2_sync(padded, 'en')
            detected_text = res.get('text', '').strip()
        except Exception:
            detected_text = ""

    if not detected_text and ocr_reader is not None:
        try:
            results = ocr_reader.readtext(padded, detail=0)
            if results:
                detected_text = " ".join(results).strip()
        except Exception:
            detected_text = ""

    if detected_text:
        matched_kw = match_target_button_keyword(detected_text)
        if matched_kw:
            _verified_cache = (bx, by, bw, bh, matched_kw, now + 3.0)
            return matched_kw
        else:
            return None

    return None

def find_blue_button(frame_bgr, tpl_gray=None, ocr_reader=None):
    h, w = frame_bgr.shape[:2]
    candidates = []

    # 1. Authentic Blue HSV mask
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    lower_blue = np.array([85, 45, 45])
    upper_blue = np.array([135, 255, 255])
    mask = cv2.inRange(hsv, lower_blue, upper_blue)

    # Blue channel must dominate red
    b, g, r = cv2.split(frame_bgr)
    bgr_blue = (b > (r.astype(np.int16) + 10)) & (b > 60)
    mask = mask & bgr_blue.astype(np.uint8) * 255

    # 2. Multi-scale template matching if template loaded
    if tpl_gray is not None:
        frame_gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        for scale in [0.75, 0.85, 0.9, 1.0, 1.1, 1.15, 1.25, 1.4]:
            if scale == 1.0:
                tg = tpl_gray
            else:
                tg = cv2.resize(tpl_gray, (0, 0), fx=scale, fy=scale)
            th, tw = tg.shape[:2]
            if th > h or tw > w:
                continue
            res = cv2.matchTemplate(frame_gray, tg, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val >= 0.52:
                mx, my = max_loc
                roi_mask = mask[my:my+th, mx:mx+tw]
                blue_density = np.count_nonzero(roi_mask) / float(tw * th)
                if blue_density >= 0.30:
                    tpl_roi = frame_bgr[my:my+th, mx:mx+tw]
                    kw = verify_button_text(tpl_roi, mx, my, tw, th, ocr_reader)
                    if kw is not None:
                        candidates.append({
                            'cx': mx + tw // 2,
                            'cy': my + th // 2,
                            'score': float(max_val) * 20.0 + 15.0,
                            'kw': kw,
                        })
                        break

    # 3. Computer Vision: Blue Color Segmentation & Contour Analysis
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5))
    mask_closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        bx, by, bw, bh = cv2.boundingRect(cnt)
        area = cv2.contourArea(cnt)
        if 35 <= bw <= 480 and 18 <= bh <= 95:
            aspect = bw / float(bh)
            if 1.05 <= aspect <= 8.5:
                fill_ratio = area / float(bw * bh)
                if fill_ratio >= 0.38:
                    roi = mask[by:by+bh, bx:bx+bw]
                    blue_density = np.count_nonzero(roi) / float(bw * bh)
                    if blue_density >= 0.28:
                        button_roi = frame_bgr[by:by+bh, bx:bx+bw]
                        matched_kw = verify_button_text(button_roi, bx, by, bw, bh, ocr_reader)
                        if matched_kw is not None:
                            aspect_bonus = 3.0 if 1.8 <= aspect <= 4.5 else 1.0
                            score = (area / float(h * w)) * 10.0 + aspect_bonus + 5.0
                            candidates.append({
                                'cx': bx + bw // 2,
                                'cy': by + bh // 2,
                                'score': score,
                                'kw': matched_kw,
                            })

    if not candidates:
        return None

    candidates.sort(key=lambda c: c['score'], reverse=True)
    best = candidates[0]
    return (best['cx'], best['cy'], best['kw'])

def main():
    global _verified_cache
    print("=" * 65)
    print(" ⚡ BLUE PLUSE TECH AUTONOMOUS BUTTON CLICKER")
    print(" [✓] Target: Buttons: 'Submit' | 'Accept' | 'Accept All' | 'Proceed'")
    print(" [✓] Latency: 2.0s • Clicks ONCE per button • Waits for next")
    print(" [🛑] STOP SHORTCUT: Press ANY KEY or Ctrl+C to Stop")
    print("=" * 65)

    ensure_desktop()

    tpl_gray = None
    if os.path.exists(TEMPLATE_PATH):
        tpl_bgr = cv2.imread(TEMPLATE_PATH)
        if tpl_bgr is not None:
            tpl_gray = cv2.cvtColor(tpl_bgr, cv2.COLOR_BGR2GRAY)
            print(" [✓] Loaded 'Submit ↵' template.")

    print(" [⏳] Initializing text vision (EasyOCR)...")
    try:
        import easyocr
        ocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
        print(" [✓] Text vision ready for 'Submit'!\n")
    except Exception:
        ocr_reader = None
        print(" [!] EasyOCR not available; using template matching fallback.\n")

    should_stop = False

    def on_stop(e=None):
        nonlocal should_stop
        should_stop = True
        key_name = getattr(e, 'name', 'Key') if e else 'Key'
        print(f"\n [🛑] Key '{key_name}' pressed! Emergency stop triggered...")

    if HAS_KEYBOARD:
        keyboard.on_press(on_stop)

    LATENCY_SECONDS = 2.0
    RECLICK_COOLDOWN = 2.0

    total_clicks = 0
    last_click_time = 0.0
    last_click_pos = None
    button_first_seen_time = None
    was_absent = True

    sct_factory = getattr(mss, "MSS", mss.mss)
    with sct_factory() as sct:
        mon = sct.monitors[1]
        print(f" [✓] Watching display ({mon['width']}x{mon['height']})...\n")

        try:
            while not should_stop:
                try:
                    sct_img = sct.grab(mon)
                    frame_bgra = np.array(sct_img)
                    frame_bgr = cv2.cvtColor(frame_bgra, cv2.COLOR_BGRA2BGR)
                except Exception:
                    from PIL import ImageGrab
                    bbox = (mon["left"], mon["top"], mon["left"] + mon["width"], mon["top"] + mon["height"])
                    pil_img = ImageGrab.grab(bbox=bbox)
                    frame_bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

                target = find_blue_button(frame_bgr, tpl_gray, ocr_reader)
                now = time.time()
                time_since_click = now - last_click_time

                if target is not None:
                    cx, cy, kw = target
                    screen_x = mon["left"] + cx
                    screen_y = mon["top"] + cy

                    is_different_pos = False
                    if last_click_pos is not None:
                        dist = ((screen_x - last_click_pos[0]) ** 2 + (screen_y - last_click_pos[1]) ** 2) ** 0.5
                        if dist > 35:
                            is_different_pos = True

                    is_eligible = was_absent or is_different_pos or (time_since_click >= RECLICK_COOLDOWN)

                    if not is_eligible:
                        time.sleep(0.04)
                        continue

                    if button_first_seen_time is None:
                        button_first_seen_time = now
                        print(f" [🎯] Button '{kw.upper()}' detected! Waiting {LATENCY_SECONDS:.1f}s latency before click...")

                    elapsed_seen = now - button_first_seen_time
                    if elapsed_seen < LATENCY_SECONDS:
                        time.sleep(0.04)
                        continue

                    total_clicks += 1
                    print(f" [⚡] Clicking '{kw.upper()}' ONCE at ({screen_x}, {screen_y}) | Prompt #{total_clicks}")
                    dispatch_click(screen_x, screen_y)

                    last_click_time = time.time()
                    last_click_pos = (screen_x, screen_y)
                    was_absent = False
                    button_first_seen_time = None
                    _verified_cache = None
                    time.sleep(0.12)
                else:
                    was_absent = True
                    button_first_seen_time = None
                    time.sleep(0.04)

        except KeyboardInterrupt:
            pass

    print(f"\n [⏹] Session Ended. Total Blue Submit Buttons Handled: {total_clicks}")

if __name__ == "__main__":
    main()
