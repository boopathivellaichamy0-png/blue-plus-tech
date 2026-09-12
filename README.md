# ⚡ BluePulse Auto-Clicker | Intelligent Vision

An advanced, beautifully styled desktop auto-clicker built with **Python**, **CustomTkinter**, and **OpenCV**. It visually scans a user-defined screen region and automatically clicks any blue button within that space until paused or stopped.

---

## 🚀 Key Features

- **Only Three Primary Actions**:
  - 🟢 **START**: Prompts space selection (on first launch or when requested) and begins scanning and clicking. Resumes from paused state seamlessly.
  - 🟡 **PAUSE**: Temporarily halts clicking without losing the target space.
  - 🔴 **STOP**: Completely terminates the clicking loop and resets the session.
- **Translucent Screen Snip Tool**:
  - Click and drag across any area of your screen with crosshairs and real-time pixel measurements.
- **Accurate Computer Vision Engine**:
  - Uses HSV color space filtering with morphological noise cleanup to precisely lock onto blue buttons.
  - Automatically calculates button centroids and translates coordinates into global screen space.
- **Ultra-Modern Dark Aesthetics**:
  - Cyberpunk dark neon UI with live glowing status pills (`IDLE`, `SELECTING`, `ACTIVE CLICKING`, `PAUSED`, `STOPPED`).
  - Animated Radar Target Visualizer displaying real-time target locks.
  - Live digital metrics: Total Clicks registered, Session Timer, Coordinates, and FPS.
- **Customizable Speed & Profiles**:
  - Adjustable click delay slider (20ms – 1000ms).
  - Blue shade color profiles: *Standard Blue*, *Sky / Electric Blue*, *Deep / Royal Blue*, and *All Blue Shades*.
  - Optional mechanical audio feedback.
- **Safety First**:
  - PyAutoGUI corner failsafe enabled (move cursor to any screen corner to abort instantly).
  - Global Hotkeys:
    - **`F6`**: Start / Resume
    - **`F7`**: Pause
    - **`F8`**: Emergency Stop

---

## 📦 Installation & Setup

1. Make sure Python 3.10+ is installed.
2. Install the required dependencies:
```bash
pip install -r requirements.txt
```

---

## 🎯 How to Run

### 1. Launch the Auto-Clicker
```bash
python app.py
```

### 2. (Optional) Launch the Target Practice Playground
To immediately test the auto-clicker without needing a game or external website:
```bash
python test_target_demo.py
```

### 3. Usage Workflow
1. Click **`▶ START`** on the BluePulse app.
2. The screen will dim into a translucent selector. Click and drag your mouse over the target window or region.
3. As soon as you release the mouse, BluePulse immediately begins detecting and clicking all blue buttons in that space!
4. Click **`⏸ PAUSE`** to pause at any time; click **`▶ RESUME`** to continue.
5. Click **`⏹ STOP`** or press **`F8`** when finished.
