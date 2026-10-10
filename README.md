# Dynamic Island for Windows (Material Capsule) 🏝️

A sleek, fluid **Material Capsule / Material 3 Expressive** desktop overlay for Windows with **0-delay instant hover animations**, organic spring physics, real-time hardware monitoring (CPU, RAM, Battery, and dedicated NVIDIA GPU), active audio visualizer, master volume control, quick shortcuts, and focus timer.

---

## ✨ Features

- **Material Capsule / M3 Expressive Aesthetics**: Pure black OLED pill with Material 3 tonal surfaces, pill buttons (radius 999), and ambient glow aura.
- **Zero-Delay Hover Morphing**: Real-time spring physics, damped so the capsule glides open and settles without a bounce.
- **⚙️ Right-Click Settings Menu & Dialog**:
  - Right-click anywhere on the capsule or system tray to open the **Settings** menu.
  - Customize **Idle Width** (150–280px), **Top Margin** (0–32px), and **Expanded Height** with live real-time preview.
  - Select between **6 Material 3 Accent Themes** (Sky Blue, Emerald, Neon Violet, Sunset Gold, Crimson Rose, Cyber Cyan).
  - Configure **Auto-Collapse Delay**, **Always On Top**, **Start with Windows**, and **Clipboard Change Toasts**.
- **Rich Interactive Modules**:
  1. 🎵 **Media Hub**: Real spectrum analyser of whatever the PC is playing (bass to treble, with peak markers), the real track title, artist and cover art from the Windows media session (browser tabs, Spotify, VLC, ...), play/pause, track navigation, and master volume slider with mute toggle.
  2. 📊 **Hardware & System Stats**: Live gauges you choose yourself — CPU, Memory, Disk, **Download / Upload speed**, Battery, and **dedicated NVIDIA GPU** (utilization, VRAM usage, and temperature). Turn each one on or off from right-click → **Monitors** or in Settings; only the ones your PC actually has are shown by default. A **network strip** under the gauges adds upload / download speed with a 60-second histogram each, and (opt-in) the **LAN / WAN IP** — the WAN address turns green while a VPN carries your traffic and red when it does not.
  3. ⚡ **Quick Utilities**: Screenshot snipping tool, master audio mute toggle, workstation lock, Windows Task Manager launcher, live clipboard preview, and instant Settings access.
  4. ⏱️ **Focus Timer / Clock**: Interactive Pomodoro focus session with 5m, 15m, 25m, 50m presets, plus an interactive compact clock pause button.
  5. 🚀 **Apps Launcher**: your own grouped menu of apps, folders and links, read from `%APPDATA%\DynamicIsland\menu.json`. Edit it from the Apps tab (pencil button) or right-click → **Apps** → *Edit menu file*; saving the file reloads it automatically.
     ```json
     { "groups": [ { "name": "Office", "items": [
         { "name": "Word", "path": "\"C:\\Program Files\\Microsoft Office\\root\\Office16\\WINWORD.EXE\"" },
         { "name": "Teams", "path": "shell:AppsFolder\\MSTeams_8wekyb3d8bbwe!MSTeams" },
         { "name": "Admin prompt", "path": "cmd.exe", "runAsAdmin": true }
     ] } ] }
     ```
- **Desktop level or always on top**: by default the capsule sits on the desktop like a widget, so any window you open or maximise covers it. Tick *Always on top* in Settings to float it above everything instead.
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
   - Double-click `Launch_DynamicIsland.bat` (finds a working Python, installs missing packages, starts without a console window)
   - Or run directly:
     ```bash
     python dynamic_island.py
     ```

---

## 📄 License

MIT License. Free and open source.
