# Dynamic Island for Windows (Material Capsule) 🏝️

A sleek, fluid **Material Capsule / Material 3 Expressive** desktop overlay for Windows with **0-delay instant hover animations**, organic spring physics, real-time hardware monitoring (CPU, RAM, Battery, and dedicated NVIDIA GPU), active audio visualizer, master volume control, quick shortcuts, and focus timer.

---

## ✨ Features

- **Material Capsule / M3 Expressive Aesthetics**: Pure black OLED pill with Material 3 tonal surfaces, pill buttons (radius 999), and ambient glow aura.
- **Zero-Delay Hover Morphing**: Real-time spring physics (stiffness 950, damping 0.76) with instant frame execution upon mouse contact.
- **⚙️ Right-Click Settings Menu & Dialog**:
  - Right-click anywhere on the capsule or system tray to open the **Settings** menu.
  - Customize **Idle Width** (150–280px), **Top Margin** (0–32px), and **Expanded Height** with live real-time preview.
  - Select between **6 Material 3 Accent Themes** (Sky Blue, Emerald, Neon Violet, Sunset Gold, Crimson Rose, Cyber Cyan).
  - Configure **Auto-Collapse Delay**, **Always On Top**, **Start with Windows**, and **Clipboard Change Toasts**.
- **4 Rich Interactive Modules**:
  1. 🎵 **Media Hub**: Real-time harmonic audio visualizer that reacts to actual sound output, animated album art, play/pause, track navigation, and master volume slider with mute toggle.
  2. 📊 **Hardware & System Stats**: Live gauges for CPU, RAM, Battery, and **dedicated NVIDIA GPU** (utilization, VRAM usage, and temperature).
  3. ⚡ **Quick Utilities**: Screenshot snipping tool, master audio mute toggle, workstation lock, Windows Task Manager launcher, live clipboard preview, and instant Settings access.
  4. ⏱️ **Focus Timer / Clock**: Interactive Pomodoro focus session with 5m, 15m, 25m, 50m presets, plus an interactive compact clock pause button.
- **Universal Device Compatibility & Crash Protection**:
  - Preflight dependency detection with friendly native dialog alerts if packages are missing.
  - Graceful hardware detection with automatic fallbacks for non-NVIDIA GPUs, machines without audio endpoints, or battery-less desktops.
  - Built-in crash logger saving diagnostics to `%APPDATA%\DynamicIsland\crash.log`.
  - Zero-dependency Windows media key simulation via native Windows API.
  - Non-blocking background COM audio thread with safe OLE initialization.
- **Windows Integration**: Frameless, translucent, multi-monitor geometry tracking, and system tray integration.


---

## 🛠️ Installation & Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/TheoGabrielEid/DynamicIslandWindows.git
   cd DynamicIslandWindows
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run Dynamic Island**:
   - Double-click `Launch_DynamicIsland.bat`
   - Or run directly:
     ```bash
     python dynamic_island.py
     ```

---

## 📄 License

MIT License. Free and open source.
