"""
Dynamic Capsule for Windows — Material Capsule / Material 3 Expressive style.

Design notes (UI/UX Pro Max: Material 3 Expressive):
- Pure black capsule, M3 dark tonal surfaces, pill-shaped controls (radius 999)
- Real spring physics (stiffness ~300, damping ratio ~0.75) for width/height morphs
- The window never resizes; the pill is painted and animated inside a fixed
  transparent window and a mask follows it -> perfectly smooth, no jitter
- Content crossfades (compact <-> expanded) driven by the spring progress
- Every component is custom-painted on a fixed grid for pixel alignment
"""
import sys
import os
import math
import time
import random
import subprocess
import warnings
import json
import ctypes
from ctypes import wintypes
import gc
import glob
import fnmatch
import socket
from collections import deque
import shutil
import faulthandler
import queue
import threading
import urllib.request
import urllib.error
import re

try:
    import winreg
except ImportError:
    winreg = None

warnings.filterwarnings("ignore", category=FutureWarning)

# Pre-flight check for PyQt6
try:
    from PyQt6.QtCore import Qt, QTimer, QTime, QRectF, QPointF, QRect, pyqtSignal, QThread, QFileSystemWatcher
    from PyQt6.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
        QAbstractButton, QSlider, QStackedWidget, QSystemTrayIcon, QMenu,
        QGraphicsOpacityEffect, QPushButton, QFrame, QCheckBox, QScrollArea, QSizePolicy,
        QInputDialog
    )
    from PyQt6.QtGui import (
        QPainter, QColor, QBrush, QPen, QFont, QPainterPath, QLinearGradient,
        QRadialGradient, QIcon, QCursor, QRegion, QPixmap
    )
except ImportError as _pyqt_err:
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            f"Dynamic Island for Windows requires dependencies to run.\n\nError: {_pyqt_err}\n\nPlease open Command Prompt or Terminal and run:\n  pip install -r requirements.txt",
            "Dynamic Island - Missing Dependencies",
            0x10
        )
    except Exception:
        pass
    sys.exit(1)

# Graceful psutil handling (does not crash if missing)
try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    psutil = None
    HAS_PSUTIL = False

try:
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume, IAudioMeterInformation
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    PYCAW = True
except Exception:
    PYCAW = False

# Only needed to name the app that is playing; optional
try:
    from pycaw.pycaw import IAudioSessionManager2, IAudioSessionControl2
except Exception:
    IAudioSessionManager2 = IAudioSessionControl2 = None

try:
    import pynvml
    pynvml.nvmlInit()
    NVML = True
except (Exception, BaseException):
    NVML = False


# ───────────────────────── Material 3 dark tokens ─────────────────────────
class M3:
    CAPSULE = QColor(0, 0, 0)
    SURFACE_1 = QColor(0x1B, 0x1B, 0x1F)
    SURFACE_2 = QColor(0x26, 0x26, 0x2B)
    SURFACE_3 = QColor(0x31, 0x31, 0x37)
    OUTLINE = QColor(255, 255, 255, 22)
    ON_SURFACE = QColor(0xE3, 0xE2, 0xE6)
    ON_SURFACE_VAR = QColor(0xC4, 0xC6, 0xD0)
    MUTED = QColor(0x8E, 0x90, 0x99)
    PRIMARY = QColor(0xA8, 0xC7, 0xFA)
    ON_PRIMARY = QColor(0x06, 0x2E, 0x6F)
    PRIMARY_CONT = QColor(0x28, 0x46, 0x7A)
    TERTIARY = QColor(0xE7, 0xB9, 0xF5)
    GREEN = QColor(0x7F, 0xD8, 0x8F)
    ORANGE = QColor(0xFF, 0xB8, 0x6C)
    NVIDIA = QColor(0x9B, 0xD8, 0x4A)
    ERROR = QColor(0xFF, 0xB4, 0xAB)

FONT = "Segoe UI Variable Display"


def font(size, weight=QFont.Weight.Normal):
    f = QFont(FONT)
    f.setStyleHint(QFont.StyleHint.SansSerif)
    f.setFamilies(["Segoe UI Variable Display", "Segoe UI", "Aptos", "Arial", "sans-serif"])
    f.setPixelSize(size)
    f.setWeight(weight)
    return f


DEFAULT_BUTTONS = [
    {"id": "snip", "label": "Screenshot", "icon": "snip", "action": "snip"},
    {"id": "mute", "label": "Mute", "icon": "mute", "action": "mute"},
    {"id": "lock", "label": "Lock", "icon": "lock", "action": "lock"},
    {"id": "taskmgr", "label": "Task Manager", "icon": "pulse", "action": "taskmgr"},
    {"id": "settings", "label": "Settings", "icon": "settings", "action": "settings"},
]

AVAILABLE_BUTTON_PRESETS = [
    {"id": "calc", "label": "Calculator", "icon": "calc", "action": "calc"},
    {"id": "notepad", "label": "Notepad", "icon": "note", "action": "notepad"},
    {"id": "term", "label": "Terminal", "icon": "term", "action": "term"},
    {"id": "explorer", "label": "Explorer", "icon": "folder", "action": "explorer"},
    {"id": "browser", "label": "Browser", "icon": "globe", "action": "browser"},
    {"id": "snip", "label": "Screenshot", "icon": "snip", "action": "snip"},
    {"id": "mute", "label": "Mute", "icon": "mute", "action": "mute"},
    {"id": "lock", "label": "Lock", "icon": "lock", "action": "lock"},
    {"id": "taskmgr", "label": "Task Manager", "icon": "pulse", "action": "taskmgr"},
    {"id": "settings", "label": "Settings", "icon": "settings", "action": "settings"},
]

def mono(size, weight=QFont.Weight.Normal):
    """Fixed-pitch digits, so numbers and addresses do not shimmy as they change."""
    f = QFont("Cascadia Mono")
    f.setFamilies(["Cascadia Mono", "Consolas", "Courier New"])
    f.setPixelSize(size)
    f.setWeight(weight)
    return f


class WINDOWPOS(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("hwndInsertAfter", wintypes.HWND),
                ("x", ctypes.c_int), ("y", ctypes.c_int), ("cx", ctypes.c_int), ("cy", ctypes.c_int),
                ("flags", ctypes.c_uint)]


# System-page monitors: id -> (label, icon, ring color; None = follow the accent color)
# Entries without an icon are not gauges: they switch parts of the network strip on.
MONITORS = {
    "cpu": ("CPU", "cpu", None),
    "ram": ("Memory", "ram", M3.GREEN),
    "gpu": ("GPU", "gpu", M3.NVIDIA),
    "disk": ("Disk", "disk", QColor(0xE8, 0x9A, 0xB5)),
    "net_down": ("Download", "arrow_down", QColor(0xF5, 0xC0, 0x4A)),
    "net_up": ("Upload", "arrow_up", QColor(0x6F, 0xD8, 0xF5)),
    "battery": ("Battery", "battery", M3.ORANGE),
    "net_graph": ("Traffic graph", None, None),
    "ips": ("LAN / WAN IP", None, None),
}
MONITOR_ORDER = list(MONITORS)


def monitor_available(mid):
    """Whether this PC can actually feed the given monitor."""
    if not HAS_PSUTIL:
        return False
    if mid == "gpu":
        return gpu_stats() is not None
    if mid == "battery":
        try:
            return psutil.sensors_battery() is not None
        except Exception:
            return False
    return mid in MONITORS


def default_monitors():
    """Everything this PC has, minus the opt-in ones: the disk gauge, and the IP
    readout (showing the WAN address means asking an outside service for it)."""
    return [m for m in MONITOR_ORDER if m not in ("disk", "ips") and monitor_available(m)]


# ───────────────────────── Settings & Persistence ─────────────────────────
class SettingsManager:
    DEFAULTS = {
        "idle_width": 196,
        "exp_height": 268,
        "top_offset": 8,
        "collapse_delay": 1000,  # ms the capsule stays open after the mouse leaves
        "always_on_top": False,  # False = desktop level: other windows cover the capsule
        "start_on_boot": False,
        "accent_color": "#A8C7FA",
        "clipboard_toast": True,
        "wan_vpn_color": True,  # WAN address green while a VPN carries the traffic, red otherwise
        "monitors": None,  # None = auto-detect (see default_monitors)
        "tools_buttons": DEFAULT_BUTTONS,
    }

    def __init__(self):
        self.dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "DynamicIsland")
        self.file = os.path.join(self.dir, "settings.json")
        self.data = dict(self.DEFAULTS)
        self.load()

    def load(self):
        try:
            if os.path.exists(self.file):
                with open(self.file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        self.data.update(loaded)
        except Exception:
            pass

    def save(self):
        try:
            os.makedirs(self.dir, exist_ok=True)
            with open(self.file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass

    def get(self, key, default=None):
        return self.data.get(key, self.DEFAULTS.get(key, default))

    def set(self, key, val):
        self.data[key] = val
        self.save()

    def reset(self):
        self.data = dict(self.DEFAULTS)
        self.save()


def get_windows_autostart() -> bool:
    if not winreg:
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ
        )
        val, _ = winreg.QueryValueEx(key, "DynamicIslandWindows")
        winreg.CloseKey(key)
        return bool(val)
    except Exception:
        return False


def set_windows_autostart(enable: bool):
    if not winreg:
        return
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
        )
        if enable:
            if getattr(sys, "frozen", False):
                cmd = f'"{sys.executable}"'
            else:
                script = os.path.abspath(sys.argv[0])
                cmd = f'"{sys.executable}" "{script}"'
            winreg.SetValueEx(key, "DynamicIslandWindows", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, "DynamicIslandWindows")
            except Exception:
                pass
        winreg.CloseKey(key)
    except Exception:
        pass


# ───────────────────────── System services ─────────────────────────
class Volume:
    """Cached master volume. Every COM call happens on the AudioWorker thread."""
    _cached_vol = 50
    _cached_mute = False
    worker = None

    @classmethod
    def get(cls):
        return cls._cached_vol

    @classmethod
    def is_muted(cls):
        return cls._cached_mute

    @classmethod
    def set(cls, pct):
        cls._cached_vol = int(max(0, min(100, pct)))
        if cls.worker:
            cls.worker.request_volume(cls._cached_vol)

    @classmethod
    def toggle_mute(cls):
        cls._cached_mute = not cls._cached_mute
        if cls.worker:
            cls.worker.request_mute(cls._cached_mute)
        return cls._cached_mute


class AudioWorker(QThread):
    """Background worker that owns all Windows COM audio objects.

    The endpoint is opened once and reused (re-resolved every few seconds so a
    newly plugged headset is picked up). Volume / mute changes from the UI are
    queued here, so the UI thread never touches COM and never blocks on it.
    """
    audio_updated = pyqtSignal(bool, float, str, int, bool)
    REOPEN_SECS = 4.0
    APP_SCAN_SECS = 1.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_evt = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._want_vol = None
        self._want_mute = None

    def request_volume(self, pct):
        with self._lock:
            self._want_vol = pct
        self._wake.set()

    def request_mute(self, mute):
        with self._lock:
            self._want_mute = bool(mute)
        self._wake.set()

    def stop(self):
        self._stop_evt.set()
        self._wake.set()
        self.wait(1500)

    @staticmethod
    def _open():
        dev = AudioUtilities.GetSpeakers()
        raw = getattr(dev, "_dev", dev)  # newer pycaw wraps the IMMDevice
        vol = raw.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None).QueryInterface(IAudioEndpointVolume)
        meter = raw.Activate(IAudioMeterInformation._iid_, CLSCTX_ALL, None).QueryInterface(IAudioMeterInformation)
        mgr = None
        if IAudioSessionManager2 is not None:
            try:
                mgr = raw.Activate(IAudioSessionManager2._iid_, CLSCTX_ALL, None).QueryInterface(IAudioSessionManager2)
            except Exception:
                mgr = None
        return vol, meter, mgr

    @staticmethod
    def _loudest_app(mgr):
        """Name of the process currently making the most noise ('' if unknown)."""
        best, name = 0.01, ""
        sessions = mgr.GetSessionEnumerator()
        for i in range(sessions.GetCount()):
            try:
                s = sessions.GetSession(i)
                sp = float(s.QueryInterface(IAudioMeterInformation).GetPeakValue())
                if sp > best:
                    pid = s.QueryInterface(IAudioSessionControl2).GetProcessId()
                    if pid:
                        best, name = sp, pretty_app(psutil.Process(pid).name())
            except Exception:
                pass
        return name

    def run(self):
        if not PYCAW:
            return
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0)  # 0 = COINIT_MULTITHREADED
        except Exception:
            pass

        vol = meter = mgr = None
        opened_at = app_scan_at = 0.0
        hits = 0
        last_sound = 0.0
        playing = False
        app_name = cur_app = ""
        last_emit = None

        while not self._stop_evt.is_set():
            now = time.monotonic()
            if vol is None or now - opened_at > self.REOPEN_SECS:
                vol = meter = mgr = None
                opened_at = now
                try:
                    vol, meter, mgr = self._open()
                except Exception:
                    vol = meter = mgr = None

            with self._lock:
                want_vol, self._want_vol = self._want_vol, None
                want_mute, self._want_mute = self._want_mute, None

            peak = 0.0
            vol_val, is_muted = Volume._cached_vol, Volume._cached_mute
            if vol is not None:
                try:
                    if want_vol is not None:
                        vol.SetMasterVolumeLevelScalar(want_vol / 100.0, None)
                    if want_mute is not None:
                        vol.SetMute(int(want_mute), None)
                    vol_val = int(round(vol.GetMasterVolumeLevelScalar() * 100))
                    is_muted = bool(vol.GetMute())
                    peak = float(meter.GetPeakValue())
                except Exception:
                    vol = meter = mgr = None  # device went away; reopen on the next pass

            if (mgr is not None and peak > 0.005 and HAS_PSUTIL
                    and IAudioSessionControl2 is not None and now - app_scan_at > self.APP_SCAN_SECS):
                app_scan_at = now
                try:
                    cur_app = self._loudest_app(mgr) or cur_app
                except Exception:
                    pass

            if peak > 0.005:
                hits += 1
                last_sound = now
                if hits >= 2:
                    playing = True
                    if cur_app:
                        app_name = cur_app
            else:
                hits = 0
                if playing and now - last_sound > 1.2:
                    playing = False
                    app_name = cur_app = ""

            state = (playing, round(peak, 2), app_name, vol_val, is_muted)
            if state != last_emit:
                last_emit = state
                try:
                    self.audio_updated.emit(playing, peak, app_name, vol_val, is_muted)
                except Exception:
                    pass

            self._wake.wait(0.08)
            self._wake.clear()

        # Release every COM pointer on this thread before leaving the apartment
        vol = meter = mgr = None
        gc.collect()
        try:
            ctypes.windll.ole32.CoUninitialize()
        except Exception:
            pass


class NetMeter:
    """Traffic, LAN address and VPN state, all derived locally from psutil + the routing table."""
    # VPN / virtual adapters carry the same bytes a second time, so they are not metered
    SKIP = ("loopback", "tailscale", "nordlynx", "nordvpn", "wireguard", "openvpn", "vpn", "tap-",
            "teredo", "isatap", "vethernet", "bluetooth")
    VPN = ("nordlynx", "nordvpn", "wireguard", "openvpn", "tailscale", "vpn", "tap-")
    MIN_SCALE = 125_000.0   # 1 Mbps in bytes/s: floor for autoscaling, so idle noise stays small
    HISTORY = 60            # one bar per second

    def __init__(self):
        self.prev = None
        self.prev_t = 0.0
        self.down = self.up = 0.0
        self.scale = self.MIN_SCALE
        self.hist_down = deque([0.0] * self.HISTORY, maxlen=self.HISTORY)
        self.hist_up = deque([0.0] * self.HISTORY, maxlen=self.HISTORY)
        self.totals = {}        # adapter -> bytes so far (picks the busiest physical adapter)
        self.lan_ip = ""
        self.vpn = False
        self.route_key = None   # changes whenever the route to the internet changes

    @classmethod
    def _skipped(cls, name):
        low = name.lower()
        return any(s in low for s in cls.SKIP)

    def sample(self):
        rx = tx = 0
        for name, c in psutil.net_io_counters(pernic=True).items():
            if self._skipped(name):
                continue
            rx += c.bytes_recv
            tx += c.bytes_sent
            self.totals[name] = c.bytes_recv + c.bytes_sent
        now = time.monotonic()
        if self.prev is not None:
            dt = now - self.prev_t
            if dt < 0.2:
                return
            d_rx, d_tx = rx - self.prev[0], tx - self.prev[1]
            if d_rx >= 0 and d_tx >= 0:  # negative = an adapter vanished and its counters with it
                self.down, self.up = d_rx / dt, d_tx / dt
            self.scale = max(self.MIN_SCALE, self.scale * 0.97, self.down, self.up)
            self.hist_down.append(self.down)
            self.hist_up.append(self.up)
        self.prev, self.prev_t = (rx, tx), now

    def probe(self):
        """Refresh lan_ip / vpn. Returns True when the route to the internet changed.

        "Is the VPN on" is answered by the routing table, not by the adapter existing:
        NordLynx stays up with an address even while disconnected. A UDP connect()
        sends nothing; it only asks Windows which local address it would route from.
        """
        src = ""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 53))
            src = s.getsockname()[0]
        except OSError:
            pass
        finally:
            s.close()

        route_nic, physical = "", []
        try:
            up = {n for n, st in psutil.net_if_stats().items() if st.isup}
            for name, addrs in psutil.net_if_addrs().items():
                for a in addrs:
                    if a.family != socket.AF_INET or a.address.startswith(("127.", "169.254.")):
                        continue
                    if a.address == src:
                        route_nic = name
                    if name in up and not self._skipped(name):
                        physical.append((self.totals.get(name, 0), a.address))
        except Exception:
            pass

        low = route_nic.lower()
        self.vpn = bool(route_nic) and any(v in low for v in self.VPN)
        # Under a VPN the LAN address is still the physical adapter's, not the tunnel's
        self.lan_ip = max(physical)[1] if physical and (self.vpn or not src) else src
        key = (src, self.vpn)
        changed = key != self.route_key
        self.route_key = key
        return changed


def fmt_rate(bps):
    """Bytes/second -> ('1.2', 'Mbps'), in the units internet speeds are quoted in."""
    bits = bps * 8
    if bits < 999_500:
        return f"{bits / 1e3:.0f}", "Kbps"
    if bits < 99.95e6:
        return f"{bits / 1e6:.1f}", "Mbps"
    if bits < 999.5e6:
        return f"{bits / 1e6:.0f}", "Mbps"
    return f"{bits / 1e9:.2f}", "Gbps"


def fetch_wan_ip(timeout=6):
    """Public IPv4 address, or '' on failure. The one outbound request this app makes on
    its own, and only while the LAN / WAN readout is switched on."""
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=timeout) as resp:
            text = resp.read(64).decode("ascii", "ignore").strip()
        socket.inet_aton(text)
        return text if text.count(".") == 3 else ""
    except Exception:
        return ""


# ───────────────────────── App launcher (menu.json) ─────────────────────────
_LOCAL_MENU = os.path.join(os.path.dirname(os.path.abspath(__file__)), "menu.json")
_APPDATA_MENU = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "DynamicIsland", "menu.json")
MENU_FILE = _LOCAL_MENU if os.path.exists(_LOCAL_MENU) else _APPDATA_MENU

# Written the first time the app runs; edit it from right-click → Apps → Edit menu file
DEFAULT_MENU = {
    "groups": [
        {"name": "Apps", "items": [
            {"name": "Notepad", "path": "notepad.exe"},
            {"name": "Calculator", "path": "calc.exe"},
            {"name": "File Explorer", "path": "explorer.exe"},
        ]},
        {"name": "System", "items": [
            {"name": "Settings", "path": "ms-settings:"},
            {"name": "Task Manager", "path": "taskmgr.exe"},
            {"name": "Terminal (Admin)", "path": "cmd.exe", "runAsAdmin": True},
        ]},
        {"name": "Web", "items": [
            {"name": "Google", "path": "https://www.google.com"},
        ]},
    ]
}


def load_menu(path=MENU_FILE):
    """Read menu.json -> [{'name', 'items': [{'name', 'path', 'admin'}]}]. Raises on a bad file.

    Format: {"groups": [{"name": "...", "items": [{"name": "...", "path": "...", "runAsAdmin": false}]}]}
    """
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_MENU, f, indent=2)
    with open(path, "r", encoding="utf-8-sig") as f:
        root = json.load(f)
    if not isinstance(root, dict) or not isinstance(root.get("groups"), list):
        raise ValueError('top level must be {"groups": [...]}')
    groups = []
    for g in root["groups"]:
        if not isinstance(g, dict) or not g.get("name"):
            continue
        items = [
            {"name": str(it["name"]), "path": str(it.get("path", "")), "admin": bool(it.get("runAsAdmin"))}
            for it in g.get("items") or [] if isinstance(it, dict) and it.get("name")
        ]
        groups.append({"name": str(g["name"]), "items": items})
    return groups


def _split_command(cmd):
    """'"C:\\a b\\x.exe" args' -> ('C:\\a b\\x.exe', 'args')."""
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        if end != -1:
            return cmd[1:end], cmd[end + 1:].strip()
    file, _, params = cmd.partition(" ")
    return file, params.strip()


def _resolve_wildcard(path):
    """Expand one '*' path segment, e.g. ...\\WindowsApps\\Claude_*_x64__abc\\app\\claude.exe.

    Store-app folders embed a version that changes on every update. WindowsApps itself
    cannot be listed without elevation, so those are looked up in the per-user package
    registry instead; anything else is a plain directory match.
    """
    parts = path.split("\\")
    idx = next((i for i, seg in enumerate(parts) if "*" in seg), None)
    if idx is None or idx == 0:
        return path
    before, pattern, after = "\\".join(parts[:idx]), parts[idx], parts[idx + 1:]
    if before.lower().endswith("windowsapps") and winreg:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CLASSES_ROOT,
                r"Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages")
            for i in range(winreg.QueryInfoKey(key)[0]):
                name = winreg.EnumKey(key, i)
                if fnmatch.fnmatch(name.lower(), pattern.lower()):
                    with winreg.OpenKey(key, name) as pkg:
                        root, _ = winreg.QueryValueEx(pkg, "PackageRootFolder")
                    return "\\".join([root] + after)
        except OSError:
            pass
    matches = glob.glob(before + "\\" + pattern)
    return "\\".join([matches[0]] + after) if matches else path


def launch_command(cmd, admin=False):
    """Run one menu entry: an exe with arguments, a shell:/ms- link, a URL or a document."""
    cmd = os.path.expandvars((cmd or "").strip())
    if not cmd:
        return
    shell_execute = ctypes.windll.shell32.ShellExecuteW
    if not admin and (cmd.startswith(("shell:", "ms-")) or "explorer.exe" in cmd.lower() or "!" in cmd):
        shell_execute(None, "open", cmd, None, None, 1)
        return
    file, params = _split_command(cmd)
    if "*" in file:
        file = _resolve_wildcard(file)
    if admin:
        shell_execute(None, "runas", file, params or None, None, 1)  # UAC prompt
        return
    try:
        subprocess.Popen(f'"{file}" {params}'.strip(), cwd=os.path.dirname(file) or None)
    except OSError:
        # Not an executable (URL, document, shortcut): let the shell decide what opens it
        shell_execute(None, "open", file, params or None, None, 1)


APP_NAMES = {"msedge": "Microsoft Edge", "chrome": "Google Chrome", "firefox": "Firefox", "vlc": "VLC",
             "spotify": "Spotify", "brave": "Brave", "opera": "Opera", "wmplayer": "Media Player"}


def pretty_app(app_id):
    """'MSEdge' / 'SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify' / 'vlc.exe' -> a readable name."""
    name = (app_id or "").split("!")[-1]
    if name.lower().endswith(".exe"):
        name = name[:-4]
    name = name.split(".")[-1]
    return APP_NAMES.get(name.lower(), name[:1].upper() + name[1:])


class SpectrumWorker(threading.Thread):
    """Real spectrum of whatever the PC is playing: loopback-captures the default
    output device, FFTs it and publishes one 0..1 level per log-spaced band.

    Optional (needs numpy + soundcard, both imported on this thread only). Captures
    only while `active`, i.e. while something is audibly playing. A daemon thread:
    the capture call can block during silence and must never hold up quitting.
    """
    BANDS = 48
    RATE = 48000
    BLOCK = 1024          # ~21 ms of audio per update
    FFT = 4096            # longer window = bass notes resolve into separate bars
    F_LO, F_HI = 50.0, 16000.0
    RANGE_DB = 38.0       # bar height spans this much below the recent loudest band

    def __init__(self):
        super().__init__(daemon=True)
        self.active = False
        self.available = False
        self._quit = threading.Event()
        self._bands = None
        self._stamp = 0.0

    def read(self):
        """Latest band levels, or None when no fresh capture exists."""
        if self._bands is None or time.monotonic() - self._stamp > 0.3:
            return None
        return self._bands

    def stop(self):
        self._quit.set()

    def run(self):
        try:
            import numpy as np
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import soundcard as sc
        except Exception:
            return
        self.available = True
        warnings.filterwarnings("ignore", module="soundcard")

        # Band edges: equal steps in pitch (log frequency), each at least one FFT bin wide
        freqs = np.geomspace(self.F_LO, self.F_HI, self.BANDS + 1)
        bins = np.maximum(1, np.round(freqs * self.FFT / self.RATE).astype(int))
        for i in range(1, len(bins)):
            bins[i] = max(bins[i], bins[i - 1] + 1)
        starts = bins[:-1]
        # Music carries far less energy up high (roughly -3 dB per octave); lifting the
        # treble by that slope lets the whole row move instead of only the bass end
        tilt = (np.sqrt(freqs[:-1] * freqs[1:]) / 1000.0) ** 0.5
        window = np.hanning(self.FFT)
        floor_db = 20 * np.log10(self.FFT / 4) - 58   # ignore anything quieter than about -58 dBFS

        while not self._quit.is_set():
            if not self.active:
                time.sleep(0.1)
                continue
            try:
                speaker = sc.default_speaker()
                mic = sc.get_microphone(speaker.id, include_loopback=True)
                buf = np.zeros(self.FFT)
                ref = floor_db + self.RANGE_DB
                checked = time.monotonic()
                with mic.recorder(samplerate=self.RATE, blocksize=self.BLOCK) as rec:
                    while self.active and not self._quit.is_set():
                        data = rec.record(numframes=self.BLOCK)
                        buf = np.concatenate((buf[self.BLOCK:], data.mean(axis=1)))
                        mag = np.abs(np.fft.rfft(buf * window))
                        band = np.maximum.reduceat(mag[:bins[-1]], starts) * tilt
                        db = 20 * np.log10(band + 1e-9)
                        # Auto-gain: follow the loudest band up at once, come down slowly
                        ref = max(float(db.max()), ref - 0.04, floor_db + self.RANGE_DB)
                        self._bands = np.clip((db - (ref - self.RANGE_DB)) / self.RANGE_DB, 0.0, 1.0).tolist()
                        self._stamp = time.monotonic()
                        if self._stamp - checked > 3.0:   # headphones plugged in / output switched
                            checked = self._stamp
                            if sc.default_speaker().id != speaker.id:
                                break
            except Exception:
                time.sleep(1.0)


class MediaInfoWorker(QThread):
    """Now-playing details (title, artist, cover art) from the Windows media session -
    the same source as the volume flyout - plus transport commands sent to that session.

    Optional: without the winrt packages the Media page falls back to naming the app.
    winrt is imported on this thread only, so it cannot disturb the UI thread's COM setup.
    """
    info = pyqtSignal(object)   # None, or dict(app, title, artist, playing, art)
    COMMANDS = {"toggle": "try_toggle_play_pause_async", "next": "try_skip_next_async",
                "prev": "try_skip_previous_async"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_evt = threading.Event()
        self._cmds = queue.Queue()
        self.available = False   # True once a session manager was obtained

    def command(self, name):
        self._cmds.put(name)

    def stop(self):
        self._stop_evt.set()
        if not self.wait(2500):  # stuck inside a Windows call: never leave a QThread running
            self.terminate()
            self.wait(500)

    def run(self):
        try:
            import asyncio
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager
            from winrt.windows.storage.streams import Buffer, InputStreamOptions
        except Exception:
            return
        try:
            asyncio.run(self._main(asyncio, Manager, Buffer, InputStreamOptions))
        except Exception:
            pass

    async def _main(self, asyncio, Manager, Buffer, InputStreamOptions):
        mgr = await Manager.request_async()
        self.available = True

        async def read_art(props):
            try:
                if props.thumbnail is None:
                    return b""
                stream = await props.thumbnail.open_read_async()
                buf = Buffer(stream.size)
                await stream.read_async(buf, stream.size, InputStreamOptions.NONE)
                return bytes(memoryview(buf))[:buf.length]
            except Exception:
                return b""

        track, art, art_tries, sent, ticks = None, b"", 0, "unset", 0
        while not self._stop_evt.is_set():
            acted = False
            try:
                session = mgr.get_current_session()
                while not self._cmds.empty():
                    name = self._cmds.get_nowait()
                    if session is not None:
                        await getattr(session, self.COMMANDS[name])()
                        acted = True
                if ticks % 4 == 0 or acted:
                    state = None
                    if session is not None:
                        props = await session.try_get_media_properties_async()
                        key = (session.source_app_user_model_id, props.title, props.artist)
                        if key != track:
                            track, art, art_tries = key, b"", 0
                        if not art and art_tries < 4:   # browsers publish the cover a moment after the title
                            art_tries += 1
                            art = await read_art(props)
                        if props.title:
                            state = {"app": pretty_app(key[0]), "title": props.title, "artist": props.artist,
                                     "playing": int(session.get_playback_info().playback_status) == 4,
                                     "art": art}
                    if state != sent:
                        sent = state
                        self.info.emit(state)
            except Exception:
                pass
            ticks += 1
            await asyncio.sleep(0.25)


def gpu_stats():
    if not NVML:
        return None
    try:
        if pynvml.nvmlDeviceGetCount() < 1:
            return None
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        util = pynvml.nvmlDeviceGetUtilizationRates(h).gpu
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        try:
            temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
        except Exception:
            temp = None
        return util, int(mem.used / mem.total * 100), temp
    except Exception:
        return None


def media_key(vk):
    try:
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)  # 2 = KEYEVENTF_KEYUP
    except Exception:
        try:
            import win32api, win32con
            win32api.keybd_event(vk, 0, 0, 0)
            win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
        except Exception:
            pass


VK_NEXT, VK_PREV, VK_PLAY = 0xB0, 0xB1, 0xB3


# ───────────────────────── Spring physics ─────────────────────────
class Spring:
    def __init__(self, value, stiffness=300.0, damping_ratio=0.74, eps=0.05):
        self.x = self.target = float(value)
        self.v = 0.0
        self.k = stiffness
        self.c = 2 * damping_ratio * math.sqrt(stiffness)
        self.eps = eps  # closer than this (and nearly still) counts as arrived

    def step(self, dt):
        # Integrate in slices of at most 4 ms: one long frame then moves exactly as far
        # as several short ones would, instead of lurching (or overshooting) on a hiccup.
        n = max(1, math.ceil(dt / 0.004))
        h = dt / n
        for _ in range(n):
            a = self.k * (self.target - self.x) - self.c * self.v
            self.v += a * h
            self.x += self.v * h
        if abs(self.target - self.x) < self.eps and abs(self.v) < self.eps * 20:
            self.x, self.v = self.target, 0.0
            return False
        return True


# ───────────────────────── Icons (single source of truth) ─────────────────────────
def draw_icon(p: QPainter, name: str, r: QRectF, color: QColor, stroke=1.8):
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    P = lambda fx, fy: QPointF(x + w * fx, y + h * fy)
    R = lambda fx, fy, fw, fh: QRectF(x + w * fx, y + h * fy, w * fw, h * fh)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()

    def fill():
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)

    if name == "windows":
        fill()
        g = w * 0.08
        s = (w - g) / 2
        for ox in (0, s + g):
            for oy in (0, s + g):
                p.drawRoundedRect(QRectF(x + ox, y + oy, s, s), w * 0.06, w * 0.06)
    elif name == "play":
        fill()
        path.moveTo(P(0.30, 0.18)); path.lineTo(P(0.82, 0.5)); path.lineTo(P(0.30, 0.82)); path.closeSubpath()
        p.drawPath(path)
    elif name == "pause":
        fill()
        p.drawRoundedRect(R(0.24, 0.2, 0.18, 0.6), w * 0.06, w * 0.06)
        p.drawRoundedRect(R(0.58, 0.2, 0.18, 0.6), w * 0.06, w * 0.06)
    elif name in ("next", "prev"):
        fill()
        if name == "next":
            path.moveTo(P(0.18, 0.2)); path.lineTo(P(0.64, 0.5)); path.lineTo(P(0.18, 0.8))
            bar = R(0.68, 0.2, 0.13, 0.6)
        else:
            path.moveTo(P(0.82, 0.2)); path.lineTo(P(0.36, 0.5)); path.lineTo(P(0.82, 0.8))
            bar = R(0.19, 0.2, 0.13, 0.6)
        path.closeSubpath(); p.drawPath(path)
        p.drawRoundedRect(bar, w * 0.05, w * 0.05)
    elif name in ("speaker", "mute"):
        path.moveTo(P(0.14, 0.38)); path.lineTo(P(0.32, 0.38)); path.lineTo(P(0.54, 0.2))
        path.lineTo(P(0.54, 0.8)); path.lineTo(P(0.32, 0.62)); path.lineTo(P(0.14, 0.62)); path.closeSubpath()
        p.drawPath(path)
        if name == "speaker":
            p.drawArc(R(0.46, 0.32, 0.28, 0.36), -55 * 16, 110 * 16)
            p.drawArc(R(0.46, 0.18, 0.44, 0.64), -55 * 16, 110 * 16)
        else:
            p.drawLine(P(0.66, 0.38), P(0.88, 0.62)); p.drawLine(P(0.88, 0.38), P(0.66, 0.62))
    elif name == "music":
        p.drawEllipse(R(0.16, 0.62, 0.26, 0.22)); p.drawEllipse(R(0.56, 0.54, 0.26, 0.22))
        p.drawLine(P(0.42, 0.73), P(0.42, 0.2)); p.drawLine(P(0.82, 0.65), P(0.82, 0.12))
        p.drawLine(P(0.42, 0.2), P(0.82, 0.12))
    elif name == "cpu":
        p.drawRoundedRect(R(0.24, 0.24, 0.52, 0.52), w * 0.1, w * 0.1)
        p.drawRoundedRect(R(0.39, 0.39, 0.22, 0.22), w * 0.04, w * 0.04)
        for f in (0.38, 0.62):
            p.drawLine(P(f, 0.1), P(f, 0.24)); p.drawLine(P(f, 0.76), P(f, 0.9))
            p.drawLine(P(0.1, f), P(0.24, f)); p.drawLine(P(0.76, f), P(0.9, f))
    elif name == "gpu":
        p.drawRoundedRect(R(0.1, 0.26, 0.8, 0.46), w * 0.08, w * 0.08)
        p.drawEllipse(R(0.4, 0.34, 0.3, 0.3))
        p.drawLine(P(0.22, 0.72), P(0.22, 0.86)); p.drawLine(P(0.34, 0.72), P(0.34, 0.86))
    elif name == "ram":
        p.drawRoundedRect(R(0.12, 0.3, 0.76, 0.36), w * 0.06, w * 0.06)
        for f in (0.28, 0.43, 0.58, 0.73):
            p.drawLine(P(f, 0.66), P(f, 0.8))
    elif name == "battery":
        p.drawRoundedRect(R(0.08, 0.28, 0.74, 0.44), w * 0.1, w * 0.1)
        fill(); p.drawRoundedRect(R(0.86, 0.4, 0.07, 0.2), w * 0.03, w * 0.03)
    elif name == "bolt":
        fill()
        path.moveTo(P(0.56, 0.08)); path.lineTo(P(0.22, 0.56)); path.lineTo(P(0.47, 0.56))
        path.lineTo(P(0.42, 0.92)); path.lineTo(P(0.78, 0.42)); path.lineTo(P(0.53, 0.42)); path.closeSubpath()
        p.drawPath(path)
    elif name == "snip":
        p.drawEllipse(R(0.12, 0.6, 0.26, 0.26)); p.drawEllipse(R(0.62, 0.6, 0.26, 0.26))
        p.drawLine(P(0.32, 0.62), P(0.72, 0.12)); p.drawLine(P(0.68, 0.62), P(0.28, 0.12))
    elif name == "lock":
        p.drawRoundedRect(R(0.2, 0.44, 0.6, 0.44), w * 0.1, w * 0.1)
        path.moveTo(P(0.32, 0.44)); path.lineTo(P(0.32, 0.32))
        path.arcTo(R(0.32, 0.12, 0.36, 0.4), 180, -180); path.lineTo(P(0.68, 0.44))
        p.drawPath(path)
    elif name == "pulse":
        path.moveTo(P(0.08, 0.52)); path.lineTo(P(0.3, 0.52)); path.lineTo(P(0.42, 0.2))
        path.lineTo(P(0.56, 0.82)); path.lineTo(P(0.68, 0.44)); path.lineTo(P(0.92, 0.44))
        p.drawPath(path)
    elif name == "timer":
        p.drawEllipse(R(0.16, 0.22, 0.68, 0.68))
        p.drawLine(P(0.5, 0.56), P(0.5, 0.38)); p.drawLine(P(0.5, 0.56), P(0.64, 0.62))
        p.drawLine(P(0.4, 0.1), P(0.6, 0.1))
    elif name == "copy":
        p.drawRoundedRect(R(0.3, 0.3, 0.52, 0.56), w * 0.08, w * 0.08)
        path.moveTo(P(0.18, 0.66)); path.lineTo(P(0.18, 0.2))
        path.quadTo(P(0.18, 0.14), P(0.24, 0.14)); path.lineTo(P(0.62, 0.14))
        p.drawPath(path)
    elif name == "settings":
        p.drawEllipse(R(0.34, 0.34, 0.32, 0.32))
        cx, cy, rad = x + w * 0.5, y + h * 0.5, w * 0.4
        for a_deg in range(0, 360, 45):
            rad_ang = math.radians(a_deg)
            p.drawLine(QPointF(cx + (rad - w * 0.1) * math.cos(rad_ang), cy + (rad - w * 0.1) * math.sin(rad_ang)),
                       QPointF(cx + rad * math.cos(rad_ang), cy + rad * math.sin(rad_ang)))
    elif name == "close":
        p.drawLine(P(0.28, 0.28), P(0.72, 0.72))
        p.drawLine(P(0.72, 0.28), P(0.28, 0.72))
    elif name == "disk":
        p.drawRoundedRect(R(0.14, 0.22, 0.72, 0.56), w * 0.1, w * 0.1)
        p.drawLine(P(0.14, 0.56), P(0.86, 0.56))
        p.drawPoint(P(0.7, 0.67))
    elif name == "reload":
        p.drawArc(R(0.2, 0.2, 0.6, 0.6), 70 * 16, 270 * 16)
        p.drawLine(P(0.62, 0.06), P(0.62, 0.24)); p.drawLine(P(0.62, 0.24), P(0.44, 0.24))
    elif name == "plus":
        p.drawLine(P(0.5, 0.22), P(0.5, 0.78))
        p.drawLine(P(0.22, 0.5), P(0.78, 0.5))
    elif name == "trash":
        p.drawLine(P(0.24, 0.28), P(0.76, 0.28))
        p.drawLine(P(0.4, 0.28), P(0.4, 0.2))
        p.drawLine(P(0.4, 0.2), P(0.6, 0.2))
        p.drawLine(P(0.6, 0.2), P(0.6, 0.28))
        p.drawRoundedRect(R(0.3, 0.28, 0.4, 0.54), w * 0.05, w * 0.05)
        p.drawLine(P(0.42, 0.38), P(0.42, 0.7))
        p.drawLine(P(0.58, 0.38), P(0.58, 0.7))
    elif name == "arrow_up":
        p.drawLine(P(0.5, 0.76), P(0.5, 0.24))
        p.drawLine(P(0.28, 0.44), P(0.5, 0.24))
        p.drawLine(P(0.72, 0.44), P(0.5, 0.24))
    elif name == "arrow_down":
        p.drawLine(P(0.5, 0.24), P(0.5, 0.76))
        p.drawLine(P(0.28, 0.56), P(0.5, 0.76))
        p.drawLine(P(0.72, 0.56), P(0.5, 0.76))
    elif name == "calc":
        p.drawRoundedRect(R(0.22, 0.16, 0.56, 0.68), w * 0.08, w * 0.08)
        p.drawRoundedRect(R(0.3, 0.24, 0.4, 0.16), w * 0.04, w * 0.04)
        for ox in (0.34, 0.5, 0.66):
            for oy in (0.48, 0.62, 0.74):
                p.drawPoint(P(ox, oy))
    elif name == "note":
        p.drawRoundedRect(R(0.22, 0.16, 0.56, 0.68), w * 0.08, w * 0.08)
        p.drawLine(P(0.32, 0.32), P(0.68, 0.32))
        p.drawLine(P(0.32, 0.48), P(0.68, 0.48))
        p.drawLine(P(0.32, 0.64), P(0.54, 0.64))
    elif name == "term":
        p.drawRoundedRect(R(0.18, 0.2, 0.64, 0.6), w * 0.08, w * 0.08)
        p.drawLine(P(0.28, 0.38), P(0.42, 0.5))
        p.drawLine(P(0.42, 0.5), P(0.28, 0.62))
        p.drawLine(P(0.48, 0.62), P(0.66, 0.62))
    elif name == "folder":
        path.moveTo(P(0.18, 0.32)); path.lineTo(P(0.4, 0.32)); path.lineTo(P(0.48, 0.42))
        path.lineTo(P(0.82, 0.42)); path.lineTo(P(0.82, 0.76)); path.lineTo(P(0.18, 0.76)); path.closeSubpath()
        p.drawPath(path)
    elif name == "globe":
        p.drawEllipse(R(0.18, 0.18, 0.64, 0.64))
        p.drawLine(P(0.18, 0.5), P(0.82, 0.5))
        p.drawEllipse(R(0.33, 0.18, 0.34, 0.64))
    elif name == "spark":
        fill()
        path.moveTo(P(0.5, 0.16))
        path.quadTo(P(0.5, 0.5), P(0.84, 0.5))
        path.quadTo(P(0.5, 0.5), P(0.5, 0.84))
        path.quadTo(P(0.5, 0.5), P(0.16, 0.5))
        path.quadTo(P(0.5, 0.5), P(0.5, 0.16))
        p.drawPath(path)
    p.restore()



# ───────────────────────── Reusable M3 components ─────────────────────────
class IconButton(QAbstractButton):
    """Pill/circle icon button with M3 state layers and press-scale."""
    def __init__(self, icon, size=36, icon_size=16, filled=False, parent=None):
        super().__init__(parent)
        self.icon_name = icon
        self.icon_size = icon_size
        self.filled = filled
        self.setFixedSize(size, size)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._hover = False

    def set_icon(self, name):
        if name != self.icon_name:
            self.icon_name = name
            self.update()

    def enterEvent(self, e): self._hover = True; self.update()
    def leaveEvent(self, e): self._hover = False; self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        if self.isDown():
            r = r.adjusted(2, 2, -2, -2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(M3.PRIMARY if self.filled else M3.SURFACE_2)
        p.drawEllipse(r)
        if self._hover:
            p.setBrush(QColor(255, 255, 255, 22 if not self.filled else 40))
            p.drawEllipse(r)
        s = self.icon_size
        ir = QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s)
        draw_icon(p, self.icon_name, ir, M3.ON_PRIMARY if self.filled else M3.ON_SURFACE)


class TileButton(QAbstractButton):
    """M3 tonal tile: icon + label, rounded 20."""
    def __init__(self, icon, label, accent=M3.PRIMARY, parent=None, button_data=None, island=None, index=-1):
        super().__init__(parent)
        self.icon_name, self.label, self.accent = icon, label, accent
        self.button_data = button_data or {}
        self.island = island
        self.index = index
        self.active = False
        self.setFixedHeight(64)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._hover = False

    def enterEvent(self, e): self._hover = True; self.update()
    def leaveEvent(self, e): self._hover = False; self.update()

    def contextMenuEvent(self, e):
        if not self.island:
            super().contextMenuEvent(e)
            return
        m = QMenu(self)
        self.island._menu_style(m)
        total = len(self.island.get_buttons())
        a_left = m.addAction("◀  Move Left") if self.index > 0 else None
        a_right = m.addAction("▶  Move Right") if 0 <= self.index < total - 1 else None
        m.addSeparator()
        a_del = m.addAction("🗑️  Remove Button")
        a_add = m.addAction("➕  Add Button...")
        m.addSeparator()
        a_sett = m.addAction("⚙️  Customize in Settings...")
        act = m.exec(e.globalPos())
        if act == a_left:
            self.island.move_button(self.index, -1)
        elif act == a_right:
            self.island.move_button(self.index, 1)
        elif act == a_del:
            self.island.remove_button(self.index)
        elif act == a_add:
            self.island.show_add_button_picker(e.globalPos())
        elif act == a_sett:
            self.island.open_settings()
        e.accept()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isDown():
            r = r.adjusted(2, 2, -2, -2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(M3.PRIMARY_CONT if self.active else M3.SURFACE_2)
        p.drawRoundedRect(r, 20, 20)
        if self._hover:
            p.setBrush(QColor(255, 255, 255, 18))
            p.drawRoundedRect(r, 20, 20)
        draw_icon(p, self.icon_name, QRectF(r.center().x() - 10, r.y() + 12 + (self.height() - 64) / 2, 20, 20),
                  M3.PRIMARY if self.active else self.accent)
        p.setPen(M3.ON_SURFACE)
        p.setFont(font(11, QFont.Weight.DemiBold))
        p.drawText(QRectF(r.x(), r.y() + 38 + (self.height() - 64) / 2, r.width(), 16), Qt.AlignmentFlag.AlignCenter, self.label)


class AddTileButton(QAbstractButton):
    """M3 dashed/translucent tile for adding a new button directly from Tools."""
    def __init__(self, island, parent=None):
        super().__init__(parent)
        self.island = island
        self.setFixedHeight(64)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._hover = False

    def enterEvent(self, e): self._hover = True; self.update()
    def leaveEvent(self, e): self._hover = False; self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isDown():
            r = r.adjusted(2, 2, -2, -2)
        p.setPen(QPen(QColor(255, 255, 255, 45 if self._hover else 25), 1, Qt.PenStyle.DashLine))
        p.setBrush(QColor(255, 255, 255, 14 if self._hover else 6))
        p.drawRoundedRect(r, 20, 20)
        draw_icon(p, "plus", QRectF(r.center().x() - 9, r.y() + 13 + (self.height() - 64) / 2, 18, 18),
                  M3.PRIMARY if self._hover else M3.MUTED)
        p.setPen(M3.PRIMARY if self._hover else M3.MUTED)
        p.setFont(font(11, QFont.Weight.DemiBold))
        p.drawText(QRectF(r.x(), r.y() + 38 + (self.height() - 64) / 2, r.width(), 16), Qt.AlignmentFlag.AlignCenter, "Add")


class Chip(QAbstractButton):
    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.text_ = text
        self.selected = False
        self.setFixedHeight(30)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._hover = False

    def enterEvent(self, e): self._hover = True; self.update()
    def leaveEvent(self, e): self._hover = False; self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(M3.PRIMARY if self.selected else M3.SURFACE_2)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        if self._hover and not self.selected:
            p.setBrush(QColor(255, 255, 255, 18))
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(M3.ON_PRIMARY if self.selected else M3.ON_SURFACE)
        p.setFont(font(12, QFont.Weight.DemiBold))
        text = p.fontMetrics().elidedText(self.text_, Qt.TextElideMode.ElideRight, int(r.width()) - 8)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)


class SegmentedTabs(QWidget):
    """M3 segmented control with a sliding spring indicator."""
    changed = pyqtSignal(int)

    def __init__(self, labels, parent=None):
        super().__init__(parent)
        self.labels = labels
        self.index = 0
        self.ind = Spring(0, stiffness=420, damping_ratio=0.8)
        self.setFixedHeight(34)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def set_index(self, i):
        self.index = i
        self.ind.target = i
        self.update()
        self.changed.emit(i)

    def tick(self, dt):
        """Advance the indicator; True while it is still moving."""
        if self.ind.step(dt):
            self.update()
            return True
        return False

    def mousePressEvent(self, e):
        seg = self.width() / len(self.labels)
        self.set_index(min(len(self.labels) - 1, int(e.position().x() // seg)))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(M3.SURFACE_1)
        p.drawRoundedRect(r, 17, 17)
        seg = r.width() / len(self.labels)
        ir = QRectF(self.ind.x * seg + 3, 3, seg - 6, r.height() - 6)
        p.setBrush(M3.SURFACE_3)
        p.drawRoundedRect(ir, ir.height() / 2, ir.height() / 2)
        p.setFont(font(12, QFont.Weight.DemiBold))
        for i, t in enumerate(self.labels):
            p.setPen(M3.ON_SURFACE if i == self.index else M3.MUTED)
            p.drawText(QRectF(i * seg, 0, seg, r.height()), Qt.AlignmentFlag.AlignCenter, t)


class RingGauge(QWidget):
    """Circular M3 gauge with eased value. The ring shrinks with the widget width,
    so more gauges can share the row. `text` replaces the default "NN%" readout."""
    def __init__(self, icon, label, color=None, width=96, parent=None):
        super().__init__(parent)
        self.icon_name, self.label, self.color = icon, label, color
        self.value = Spring(0, stiffness=120, damping_ratio=1.0)
        self.sub = ""
        self.text = None
        self.setFixedSize(width, 118)

    def set_value(self, v, sub="", text=None):
        self.value.target = max(0, min(100, v))
        if sub != self.sub or text != self.text:
            self.sub, self.text = sub, text
            self.update()

    def tick(self, dt):
        """Advance the eased value; True while it is still moving."""
        if self.value.step(dt):
            self.update()
            return True
        return False

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = max(40, min(76, self.width() - 12))
        k = d / 76
        color = self.color or M3.PRIMARY
        stroke = max(5.0, 7 * k)
        rr = QRectF((self.width() - d) / 2, 4, d, d)
        p.setPen(QPen(M3.SURFACE_2, stroke, cap=Qt.PenCapStyle.RoundCap))
        p.drawArc(rr, 0, 360 * 16)
        span = int(-self.value.x / 100 * 360 * 16)
        if span:
            p.setPen(QPen(color, stroke, cap=Qt.PenCapStyle.RoundCap))
            p.drawArc(rr, 90 * 16, span)
        ic = 16 * k
        draw_icon(p, self.icon_name, QRectF(rr.center().x() - ic / 2, rr.y() + 17 * k, ic, ic), color, 1.6)
        p.setPen(M3.ON_SURFACE)
        p.setFont(font(max(11, round(15 * k)), QFont.Weight.Bold))
        text = self.text if self.text is not None else f"{int(round(self.value.x))}%"
        p.drawText(QRectF(rr.x(), rr.y() + 36 * k, d, 22 * k), Qt.AlignmentFlag.AlignCenter, text)
        p.setPen(M3.ON_SURFACE_VAR)
        p.setFont(font(11, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, d + 10, self.width(), 16), Qt.AlignmentFlag.AlignCenter, self.label)
        if self.sub:
            p.setPen(M3.MUTED)
            p.setFont(font(10))
            p.drawText(QRectF(0, d + 25, self.width(), 14), Qt.AlignmentFlag.AlignCenter, self.sub)


class AlbumArt(QWidget):
    """Animated gradient artwork with rotating sheen while playing."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self.phase = 0.0
        self.playing = False
        self.cover = None
        self._art = b""

    def set_art(self, data):
        """Cover image bytes from the media session (b'' = back to the gradient)."""
        if data == self._art:
            return
        self._art = data
        pm = QPixmap()
        self.cover = pm if data and pm.loadFromData(data) else None
        self.update()

    def tick(self, dt):
        animate = self.playing and self.cover is None
        if animate:
            self.phase += dt * 0.8
            self.update()
        return animate

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        if self.cover is not None:
            clip = QPainterPath()
            clip.addRoundedRect(r, 18, 18)
            p.setClipPath(clip)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            pm = self.cover.scaled(self.size() * self.devicePixelRatioF(),
                                   Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation)
            src = QRectF(0, 0, r.width() * self.devicePixelRatioF(), r.height() * self.devicePixelRatioF())
            src.moveCenter(QRectF(pm.rect()).center())
            p.drawPixmap(r, pm, src)
            return
        a = self.phase
        g = QLinearGradient(QPointF(32 + 32 * math.cos(a), 32 + 32 * math.sin(a)),
                            QPointF(32 - 32 * math.cos(a), 32 - 32 * math.sin(a)))
        g.setColorAt(0, QColor(0x3B, 0x6E, 0xD8))
        g.setColorAt(0.55, QColor(0x8E, 0x5B, 0xD9))
        g.setColorAt(1, QColor(0xE0, 0x6C, 0xB4))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, 18, 18)
        draw_icon(p, "music", QRectF(20, 20, 24, 24), QColor(255, 255, 255), 2.0)


class Waveform(QWidget):
    """Spectrum analyser: one bar per frequency band, bass on the left, with falling
    peak markers. Fed by SpectrumWorker (the real sound); without it the bars fall back
    to a synthetic wave driven by overall loudness."""
    def __init__(self, bars=48, parent=None):
        super().__init__(parent)
        self.n = bars
        self.levels = [0.0] * bars
        self.peaks = [0.0] * bars
        self.energy = 0.0
        self.active = False
        self.spectrum = None   # SpectrumWorker, set by the capsule
        self.phase = 0.0
        self.setFixedHeight(44)

    def _targets(self, dt):
        if not self.active:
            return [0.0] * self.n
        live = self.spectrum.read() if self.spectrum else None
        if live and len(live) == self.n:
            return live
        # No capture available: harmonic wave modulated by the sound peak
        self.phase += dt * 5.0
        out = []
        for i in range(self.n):
            harmonic = 0.35 * math.sin(self.phase + i * 0.45) + 0.25 * math.sin(self.phase * 1.6 - i * 0.3)
            out.append(min(1.0, 0.12 + max(0.0, harmonic) * (0.3 + self.energy * 0.9)))
        return out

    def tick(self, dt):
        """Animate the bars; False once they are flat and silent (nothing to repaint)."""
        if not self.active and max(self.levels) < 0.004 and max(self.peaks) < 0.004:
            return False
        targets = self._targets(dt)
        for i in range(self.n):
            lv, t = self.levels[i], targets[i]
            # Jump up with the beat, sink back slowly: how a hardware analyser reads
            lv += (t - lv) * min(1.0, dt * (38.0 if t > lv else 9.0))
            self.levels[i] = lv
            self.peaks[i] = max(lv, self.peaks[i] - dt * 0.55)
        self.update()
        return True

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        w, h = float(self.width()), float(self.height())
        gap = 3.0
        bw = max(2.0, (w - gap * (self.n - 1)) / self.n)
        rad = min(2.0, bw / 2.0)

        g = QLinearGradient(0, 0, w, 0)
        g.setColorAt(0, M3.PRIMARY)
        g.setColorAt(0.5, M3.TERTIARY)
        g.setColorAt(1, M3.PRIMARY)
        cap = QColor(M3.ON_SURFACE)
        cap.setAlpha(170)
        for i, lv in enumerate(self.levels):
            x = i * (bw + gap)
            bh = max(2.0, lv * (h - 4.0))
            p.setBrush(g if lv > 0.01 else M3.SURFACE_3)
            p.drawRoundedRect(QRectF(x, h - bh, bw, bh), rad, rad)
            pk = self.peaks[i]
            if pk > 0.03 and pk - lv > 0.02:
                p.setBrush(cap)
                p.drawRect(QRectF(x, h - 2.0 - pk * (h - 4.0), bw, 2.0))


class ElideLabel(QWidget):
    """Single-line text that is cut with "…" when it does not fit (a QLabel would
    widen the layout to fit a long song title)."""
    def __init__(self, text, size, color, weight=QFont.Weight.Normal):
        super().__init__()
        self._text, self._font, self._color = text, font(size, weight), color
        self.setFixedHeight(size + 8)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def text(self):
        return self._text

    def setText(self, text):
        if text != self._text:
            self._text = text
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setFont(self._font)
        p.setPen(self._color)
        text = p.fontMetrics().elidedText(self._text, Qt.TextElideMode.ElideRight, self.width())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


def label(text, size, color, weight=QFont.Weight.Normal):
    l = QLabel(text)
    l.setFont(font(size, weight))
    l.setStyleSheet(f"color: {color.name()}; background: transparent;")
    return l


# ───────────────────────── Compact capsule view ─────────────────────────
class CompactView(QWidget):
    """Fully painted compact content: [left badge] [center text + pause] [right indicator]."""
    play_clicked = pyqtSignal()
    clock_pause_clicked = pyqtSignal()
    expand_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.time_text = "00:00"
        self.toast_text = ""
        self.toast_icon = ""
        self.toast_color = M3.PRIMARY
        self.playing = False
        self.app = ""
        self.battery = None
        self.charging = False
        self.clock_paused = False
        self.bars = [0.3, 0.6, 0.45, 0.8]
        self.bar_t = [0.3, 0.6, 0.45, 0.8]
        self.energy = 0.0
        self.spectrum = None   # SpectrumWorker, set by the capsule
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMouseTracking(True)
        self._hover_center = False

    def tick(self, dt):
        """Animate the mini equalizer; False when the bars are at rest (nothing to repaint)."""
        changed = False
        live = self.spectrum.read() if (self.playing and self.spectrum) else None
        for i in range(4):
            if live:
                q = len(live) * 3 // 16   # four slices over the lower three quarters, where music lives
                self.bar_t[i] = 0.2 + 0.8 * max(live[i * q:(i + 1) * q])
            elif self.playing and random.random() < 0.35:
                self.bar_t[i] = 0.2 + random.random() * min(0.8, 0.25 + self.energy * 2.2)
            elif not self.playing:
                self.bar_t[i] = 0.2
            step = (self.bar_t[i] - self.bars[i]) * min(1.0, dt * 16.0)
            if abs(step) > 0.002:
                self.bars[i] += step
                changed = True
        if changed:
            self.update()
        return self.playing or changed

    def badge_rect(self):
        h = self.height()
        return QRectF(7, (h - 28) / 2, 28, 28)

    def pause_btn_rect(self):
        """Hoverable pause/play button next to the clock/timer."""
        center = self.center_rect()
        return QRectF(center.right() - 20, (self.height() - 16) / 2, 16, 16)

    def center_rect(self):
        b = self.badge_rect()
        w, h = self.width(), self.height()
        right_w = 52
        return QRectF(b.right() + 6, 0, w - b.right() - right_w - 14, h)

    def mouseMoveEvent(self, e):
        center = self.center_rect()
        if center.contains(e.position()) and not self.toast_text:
            if not self._hover_center:
                self._hover_center = True
                self.update()
        else:
            if self._hover_center:
                self._hover_center = False
                self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self._hover_center = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            if hasattr(self.window(), "_menu"):
                self.window()._menu(e.globalPosition().toPoint())
            e.accept()
            return
        if e.button() != Qt.MouseButton.LeftButton:
            return e.ignore()
        pos = e.position()
        if self.playing and self.badge_rect().adjusted(-4, -4, 4, 4).contains(pos):
            self.play_clicked.emit()
        elif not self.toast_text and self.pause_btn_rect().adjusted(-6, -6, 6, 6).contains(pos):
            self.clock_pause_clicked.emit()
        else:
            self.expand_clicked.emit()

    def contextMenuEvent(self, e):
        if hasattr(self.window(), "_menu"):
            self.window()._menu(e.globalPos())
            e.accept()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        b = self.badge_rect()

        # Left badge
        p.setPen(Qt.PenStyle.NoPen)
        if self.toast_text:
            p.setBrush(QColor(self.toast_color.red(), self.toast_color.green(), self.toast_color.blue(), 50))
            p.drawEllipse(b)
            draw_icon(p, self.toast_icon, b.adjusted(7, 7, -7, -7), self.toast_color)
        elif self.playing:
            g = QLinearGradient(b.topLeft(), b.bottomRight())
            g.setColorAt(0, QColor(0x3B, 0x6E, 0xD8)); g.setColorAt(1, QColor(0xE0, 0x6C, 0xB4))
            p.setBrush(g)
            p.drawEllipse(b)
            draw_icon(p, "pause", b.adjusted(8, 8, -8, -8), QColor(255, 255, 255))
        else:
            p.setBrush(M3.SURFACE_2)
            p.drawEllipse(b)
            draw_icon(p, "windows", b.adjusted(8.5, 8.5, -8.5, -8.5), M3.PRIMARY)

        # Right indicator area (fixed 52px)
        right = QRectF(w - 7 - 52, 0, 52, h)
        if self.playing and not self.toast_text:
            bw, gap = 3.5, 3.5
            total = 4 * bw + 3 * gap
            x0 = right.right() - 8 - total
            g = QLinearGradient(x0, 0, x0 + total, 0)
            g.setColorAt(0, M3.PRIMARY); g.setColorAt(1, M3.TERTIARY)
            p.setBrush(g)
            for i, lv in enumerate(self.bars):
                bh = max(4.0, lv * 16.0)
                p.drawRoundedRect(QRectF(x0 + i * (bw + gap), (h - bh) / 2, bw, bh), bw / 2, bw / 2)
        elif self.battery is not None and not self.toast_text:
            col = M3.GREEN if self.charging else (M3.ERROR if self.battery <= 20 else M3.ON_SURFACE)
            p.setFont(font(12, QFont.Weight.DemiBold))
            p.setPen(col)
            if self.charging:
                p.drawText(right.adjusted(14, 0, -4, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{self.battery}%")
                draw_icon(p, "bolt", QRectF(right.right() - 48, (h - 13) / 2, 13, 13), col)
            else:
                p.drawText(right.adjusted(0, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{self.battery}%")

        # Center text & clock pause control
        center = self.center_rect()
        if self.toast_text:
            center_toast = QRectF(b.right() + 10, 0, w - b.right() - 24, h)
            p.setPen(M3.ON_SURFACE)
            p.setFont(font(12, QFont.Weight.DemiBold))
            txt = p.fontMetrics().elidedText(self.toast_text, Qt.TextElideMode.ElideRight, int(center_toast.width()))
            p.drawText(center_toast, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, txt)
        else:
            p.setPen(M3.ORANGE if self.clock_paused else M3.ON_SURFACE)
            p.setFont(font(13, QFont.Weight.Bold))
            text_rect = QRectF(center.left(), 0, center.width() - (16 if self._hover_center or self.clock_paused else 0), h)
            p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self.time_text)
            
            # Show pause / play button icon on hover or when paused
            if self._hover_center or self.clock_paused:
                pb = self.pause_btn_rect()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(M3.SURFACE_3)
                p.drawEllipse(pb)
                icon_name = "play" if self.clock_paused else "pause"
                draw_icon(p, icon_name, pb.adjusted(3.5, 3.5, -3.5, -3.5),
                          M3.ORANGE if self.clock_paused else M3.PRIMARY, 1.4)


# ───────────────────────── Expanded pages ─────────────────────────
class MediaPage(QWidget):
    def __init__(self, island):
        super().__init__()
        self.island = island
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        top = QHBoxLayout()
        top.setSpacing(14)
        self.art = AlbumArt()
        top.addWidget(self.art, 0, Qt.AlignmentFlag.AlignVCenter)
        info = QVBoxLayout()
        info.setSpacing(2)
        info.addStretch()
        self.title = ElideLabel("Nothing playing", 16, M3.ON_SURFACE, QFont.Weight.Bold)
        self.sub = ElideLabel("Play something to see it here", 12, M3.MUTED)
        info.addWidget(self.title)
        info.addWidget(self.sub)
        info.addStretch()
        top.addLayout(info, 1)

        ctrls = QHBoxLayout()
        ctrls.setSpacing(8)
        self.btn_prev = IconButton("prev", 38, 15)
        self.btn_play = IconButton("play", 46, 18, filled=True)
        self.btn_next = IconButton("next", 38, 15)
        self.btn_prev.clicked.connect(lambda: island.media_cmd("prev"))
        self.btn_play.clicked.connect(island.toggle_play)
        self.btn_next.clicked.connect(lambda: island.media_cmd("next"))
        for b in (self.btn_prev, self.btn_play, self.btn_next):
            ctrls.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addLayout(ctrls)
        root.addLayout(top)

        self.wave = Waveform(SpectrumWorker.BANDS)
        root.addWidget(self.wave)

        vol = QHBoxLayout()
        vol.setSpacing(10)
        self.vol_icon = IconButton("speaker", 30, 14)
        self.vol_icon.clicked.connect(island.toggle_mute)
        vol.addWidget(self.vol_icon)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(Volume.get())
        self.slider.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.slider.setStyleSheet(f"""
            QSlider {{ background: transparent; height: 22px; }}
            QSlider::groove:horizontal {{ height: 8px; background: {M3.SURFACE_2.name()}; border-radius: 4px; }}
            QSlider::sub-page:horizontal {{ background: {M3.PRIMARY.name()}; border-radius: 4px; }}
            QSlider::handle:horizontal {{ background: {M3.PRIMARY.name()}; width: 6px; margin: -7px 0; border-radius: 3px; }}
        """)
        self.slider.valueChanged.connect(self._vol_changed)
        vol.addWidget(self.slider, 1)
        self.vol_lbl = label(f"{self.slider.value()}%", 12, M3.ON_SURFACE_VAR, QFont.Weight.DemiBold)
        self.vol_lbl.setFixedWidth(38)
        self.vol_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        vol.addWidget(self.vol_lbl)
        root.addLayout(vol)
        root.addStretch()

    def _vol_changed(self, v):
        Volume.set(v)
        self.vol_lbl.setText(f"{v}%")

    def tick(self, dt):
        return self.art.tick(dt) | self.wave.tick(dt)


class NetStrip(QWidget):
    """Two-line network readout: UL / DL speed, a 60-second histogram for each,
    and the LAN / WAN addresses (WAN tinted by VPN state when that option is on)."""
    UP_COLOR = QColor(0x6F, 0xD8, 0xF5)     # cyan / amber: off the red-green axis,
    DOWN_COLOR = QColor(0xF5, 0xC0, 0x4A)   # which is reserved for the VPN state
    VPN_ON = QColor(74, 222, 128)
    VPN_OFF = QColor(255, 95, 95)
    ROW_H = 21

    def __init__(self, island):
        super().__init__()
        self.island = island
        self.show_graph = True
        self.show_ips = False
        self.setFixedHeight(50)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(M3.SURFACE_1)
        p.drawRoundedRect(QRectF(self.rect()), 14, 14)

        net = self.island.net
        wan_color = M3.ON_SURFACE
        if self.island.settings.get("wan_vpn_color", True):
            wan_color = self.VPN_ON if net.vpn else self.VPN_OFF
        rows = (
            ("UL", net.up, net.hist_up, self.UP_COLOR, "LAN", net.lan_ip or "—", M3.ON_SURFACE),
            ("DL", net.down, net.hist_down, self.DOWN_COLOR, "WAN", self.island.wan_ip or "…", wan_color),
        )
        ip_w = 150 if self.show_ips else 0
        gx0, gx1 = 122.0, w - 12.0 - (ip_w + 12 if ip_w else 0)
        V = Qt.AlignmentFlag.AlignVCenter
        for i, (tag, rate, hist, color, ip_tag, ip, ip_color) in enumerate(rows):
            y = 4 + i * self.ROW_H
            p.setPen(color)
            p.setFont(font(10, QFont.Weight.Bold))
            p.drawText(QRectF(12, y, 22, self.ROW_H), V | Qt.AlignmentFlag.AlignLeft, tag)
            num, unit = fmt_rate(rate)
            p.setPen(M3.ON_SURFACE)
            p.setFont(mono(12, QFont.Weight.DemiBold))
            p.drawText(QRectF(32, y, 46, self.ROW_H), V | Qt.AlignmentFlag.AlignRight, num)
            p.setPen(M3.MUTED)
            p.setFont(font(10))
            p.drawText(QRectF(83, y, 36, self.ROW_H), V | Qt.AlignmentFlag.AlignLeft, unit)

            if self.show_graph and gx1 - gx0 > 40:
                # Each series scales to its own recent peak, so a small upload stays readable
                p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                p.setPen(Qt.PenStyle.NoPen)
                pitch = (gx1 - gx0) / len(hist)
                peak = max(NetMeter.MIN_SCALE, max(hist))
                base = y + self.ROW_H - 3
                p.setBrush(M3.SURFACE_3)
                p.drawRect(QRectF(gx0, base, gx1 - gx0, 1))
                p.setBrush(color)
                for n, v in enumerate(hist):
                    if v > 0:
                        bh = max(1.0, v / peak * (self.ROW_H - 6))
                        p.drawRect(QRectF(gx0 + n * pitch, base - bh, max(1.0, pitch - 1), bh))
                p.setRenderHint(QPainter.RenderHint.Antialiasing)

            if ip_w:
                x = w - 12 - ip_w
                p.setPen(ip_color if ip_tag == "WAN" else M3.MUTED)
                p.setFont(font(10, QFont.Weight.Bold))
                p.drawText(QRectF(x, y, 30, self.ROW_H), V | Qt.AlignmentFlag.AlignLeft, ip_tag)
                p.setPen(ip_color)
                p.setFont(mono(12))
                p.drawText(QRectF(x + 30, y, ip_w - 30, self.ROW_H), V | Qt.AlignmentFlag.AlignRight, ip)


class SystemPage(QWidget):
    """One ring gauge per enabled monitor plus the network strip (see MONITORS);
    rebuilt when the selection changes."""
    ROW_W = 504  # panel width minus its padding

    def __init__(self, island):
        super().__init__()
        self.island = island
        self.gauges = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 0)
        root.setSpacing(2)
        self.lay = QHBoxLayout()
        self.lay.setSpacing(0)
        root.addLayout(self.lay)
        self.strip = NetStrip(island)
        root.addWidget(self.strip)
        root.addStretch()
        self.rebuild()

    def rebuild(self):
        while self.lay.count():
            w = self.lay.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        self.gauges = {}
        ids = self.island.get_monitors()
        self.strip.show_graph = "net_graph" in ids
        self.strip.show_ips = "ips" in ids
        self.strip.setVisible(self.strip.show_graph or self.strip.show_ips)
        if not ids:
            hint = label("No monitors selected  ·  right-click → Monitors", 12, M3.MUTED)
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lay.addWidget(hint, 1)
            return
        gauge_ids = [m for m in ids if MONITORS[m][1]]
        if not gauge_ids:
            return
        width = max(64, min(96, self.ROW_W // len(gauge_ids)))
        for mid in gauge_ids:
            title, icon, color = MONITORS[mid]
            g = RingGauge(icon, title, color, width)
            self.lay.addStretch()
            self.lay.addWidget(g, 0, Qt.AlignmentFlag.AlignTop)
            self.gauges[mid] = g
        self.lay.addStretch()

    def set(self, mid, v, sub="", text=None):
        g = self.gauges.get(mid)
        if g:
            g.set_value(v, sub, text)

    def tick(self, dt):
        moving = False
        for g in self.gauges.values():
            moving |= g.tick(dt)
        return moving


class ToolsPage(QWidget):
    def __init__(self, island):
        super().__init__()
        self.island = island
        self.tiles = []
        self.t_mute = None

        self.root_lay = QVBoxLayout(self)
        self.root_lay.setContentsMargins(0, 0, 0, 0)
        self.root_lay.setSpacing(10)

        self.grid = QGridLayout()
        self.grid.setSpacing(8)
        self.root_lay.addLayout(self.grid)

        clip = self.clip = QWidget()
        clip.setFixedHeight(48)
        clip.setStyleSheet(f"background: {M3.SURFACE_1.name()}; border-radius: 16px;")
        cl = QHBoxLayout(clip)
        cl.setContentsMargins(14, 0, 14, 0)
        cl.setSpacing(10)
        head = label("CLIPBOARD", 10, M3.PRIMARY, QFont.Weight.Bold)
        cl.addWidget(head)
        self.clip_text = label("Nothing copied yet", 12, M3.ON_SURFACE)
        cl.addWidget(self.clip_text, 1)
        self.root_lay.addWidget(clip)
        self.root_lay.addStretch()

        self.rebuild_buttons()

    def rebuild_buttons(self):
        # Clear existing items in grid
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.tiles.clear()
        self.t_mute = None

        buttons = self.island.get_buttons()
        # Max 5 buttons per row
        cols = 5
        idx = 0
        for i, b in enumerate(buttons):
            tile = TileButton(
                b.get("icon", "pulse"),
                b.get("label", "Action"),
                button_data=b,
                island=self.island,
                index=i,
                parent=self
            )
            # Wire click to execute action
            tile.clicked.connect(lambda _, item=b: self.island.execute_button_action(item))
            if b.get("action") == "mute" or b.get("id") == "mute":
                self.t_mute = tile
                self.t_mute.active = Volume.is_muted()
            row = idx // cols
            col = idx % cols
            self.grid.addWidget(tile, row, col)
            self.tiles.append(tile)
            idx += 1

        # Add '+' button at the end
        add_btn = AddTileButton(self.island, parent=self)
        add_btn.clicked.connect(lambda: self.island.show_add_button_picker(
            add_btn.mapToGlobal(QPointF(0, add_btn.height()).toPoint())
        ))
        row = idx // cols
        col = idx % cols
        self.grid.addWidget(add_btn, row, col)

        # Two rows of full-size tiles do not fit above the clipboard bar at the
        # default panel height, so a second row makes everything slightly shorter.
        two_rows = row >= 1
        for t in self.tiles + [add_btn]:
            t.setFixedHeight(56 if two_rows else 64)
        self.clip.setFixedHeight(40 if two_rows else 48)
        self.root_lay.setSpacing(8 if two_rows else 10)

    def set_clip(self, text):
        fm = self.clip_text.fontMetrics()
        self.clip_text.setText(fm.elidedText(text.replace("\n", " "), Qt.TextElideMode.ElideRight, 360))


class FocusRing(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(124, 124)
        self.progress = Spring(1.0, 140, 1.0)
        self.text = "25:00"
        self.running = False

    def tick(self, dt):
        if self.progress.step(dt):
            self.update()
            return True
        return False

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(8, 8, 108, 108)
        p.setPen(QPen(M3.SURFACE_2, 9, cap=Qt.PenCapStyle.RoundCap))
        p.drawArc(r, 0, 360 * 16)
        p.setPen(QPen(M3.TERTIARY, 9, cap=Qt.PenCapStyle.RoundCap))
        p.drawArc(r, 90 * 16, int(-self.progress.x * 360 * 16))
        p.setPen(M3.ON_SURFACE)
        p.setFont(font(24, QFont.Weight.Bold))
        p.drawText(r.adjusted(0, -8, 0, -8), Qt.AlignmentFlag.AlignCenter, self.text)
        p.setPen(M3.MUTED)
        p.setFont(font(10, QFont.Weight.DemiBold))
        p.drawText(r.adjusted(0, 30, 0, 0), Qt.AlignmentFlag.AlignCenter, "FOCUS" if self.running else "READY")


class FocusPage(QWidget):
    def __init__(self, island):
        super().__init__()
        self.island = island
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(24)
        self.ring = FocusRing()
        lay.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignVCenter)
        right = QVBoxLayout()
        right.setSpacing(10)
        right.addStretch()
        right.addWidget(label("Focus session", 16, M3.ON_SURFACE, QFont.Weight.Bold))
        right.addWidget(label("Pick a duration. The capsule keeps counting.", 12, M3.MUTED))
        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.chips = []
        for mins in (5, 15, 25, 50):
            c = Chip(f"{mins} min")
            c.setFixedWidth(64)
            c.clicked.connect(lambda _, m=mins: island.start_focus(m * 60))
            chips.addWidget(c)
            self.chips.append((mins, c))
        stop = Chip("Stop")
        stop.setFixedWidth(56)
        stop.clicked.connect(lambda: island.start_focus(0))
        chips.addWidget(stop)
        chips.addStretch()
        right.addLayout(chips)
        right.addStretch()
        lay.addLayout(right, 1)


class AppsPage(QWidget):
    """Launcher driven by menu.json: a row of groups, the chosen group's entries below."""
    def __init__(self, island):
        super().__init__()
        self.island = island
        self.group = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(4)
        self.groups_lay = QHBoxLayout()
        self.groups_lay.setSpacing(4)
        top.addLayout(self.groups_lay, 1)
        btn_edit = IconButton("note", 26, 13)
        btn_edit.setToolTip("Edit menu file")
        btn_edit.clicked.connect(island.edit_menu)
        btn_reload = IconButton("reload", 26, 13)
        btn_reload.setToolTip("Reload menu file")
        btn_reload.clicked.connect(lambda: island.reload_menu(True))
        top.addWidget(btn_edit)
        top.addWidget(btn_reload)
        root.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: transparent; width: 4px; margin: 0; }
            QScrollBar::handle:vertical { background: rgba(255, 255, 255, 0.2); border-radius: 2px; min-height: 20px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        scroll.viewport().setStyleSheet("background: transparent;")
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        self.grid = QGridLayout(host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        self.rebuild()

    def rebuild(self):
        for lay in (self.groups_lay, self.grid):
            while lay.count():
                w = lay.takeAt(0).widget()
                if w:
                    w.hide()
                    w.deleteLater()
        groups = self.island.menu_groups
        self.group = max(0, min(self.group, len(groups) - 1))
        for i, g in enumerate(groups):
            chip = Chip(g["name"])
            chip.selected = i == self.group
            chip.clicked.connect(lambda _, i=i: self.select(i))
            self.groups_lay.addWidget(chip, 1)
        items = groups[self.group]["items"] if groups else []
        if not items:
            hint = label("Nothing here yet  ·  use the pencil button to edit menu.json", 12, M3.MUTED)
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(hint, 0, 0)
            return
        cols = 3 if len(items) <= 12 else 4
        for n, item in enumerate(items):
            btn = Chip(item["name"])
            btn.setToolTip(item["path"])
            btn.clicked.connect(lambda _, it=item: self.island.launch_item(it))
            self.grid.addWidget(btn, n // cols, n % cols)

    def select(self, index):
        self.group = index
        self.rebuild()


class ColorChip(QAbstractButton):
    def __init__(self, color_hex, name, parent=None):
        super().__init__(parent)
        self.color_hex = color_hex
        self.color_name = name
        self.selected = False
        self.setFixedSize(38, 38)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(name)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(self.color_hex)
        r = QRectF(4, 4, 30, 30)
        if self.selected:
            p.setPen(QPen(QColor(255, 255, 255, 230), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(1, 1, 36, 36))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(r)
        if self.selected:
            p.setPen(QPen(QColor(0, 0, 0, 210), 2.2, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
            p.drawLine(QPointF(14, 19), QPointF(18, 23))
            p.drawLine(QPointF(18, 23), QPointF(24, 15))


class SettingsDialog(QWidget):
    """M3-styled Settings Window accessible via right-click to customize island dimensions, colors & behavior."""
    def __init__(self, island, parent=None):
        super().__init__(parent)
        self.island = island
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(460, 620)
        self._drag_pos = None

        self._build_ui()
        self._center()

    def _center(self):
        try:
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                self.move(
                    geo.x() + (geo.width() - self.width()) // 2,
                    geo.y() + (geo.height() - self.height()) // 2
                )
        except Exception:
            self.move(200, 200)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(M3.OUTLINE, 1))
        p.setBrush(M3.SURFACE_1)
        p.drawRoundedRect(r, 22, 22)

    def _style_slider(self, s):
        s.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 6px;
                background: {M3.SURFACE_3.name()};
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: {M3.PRIMARY.name()};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: #FFFFFF;
                width: 16px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 8px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {M3.PRIMARY.name()};
            }}
        """)

    def _build_ui(self):
        main_root = QVBoxLayout(self)
        main_root.setContentsMargins(18, 16, 18, 16)
        main_root.setSpacing(10)

        # Header
        hdr = QHBoxLayout()
        hdr_icon = QWidget()
        hdr_icon.setFixedSize(36, 36)
        def _paint_hdr_icon(e):
            p = QPainter(hdr_icon)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(M3.SURFACE_2)
            p.drawRoundedRect(QRectF(0, 0, 36, 36), 18, 18)
            draw_icon(p, "settings", QRectF(8, 8, 20, 20), M3.PRIMARY)
        hdr_icon.paintEvent = _paint_hdr_icon
        hdr.addWidget(hdr_icon)

        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        t_lbl = QLabel("Capsule Settings")
        t_lbl.setFont(font(15, QFont.Weight.Bold))
        t_lbl.setStyleSheet(f"color: {M3.ON_SURFACE.name()};")
        sub_lbl = QLabel("Customize buttons, geometry & behavior")
        sub_lbl.setFont(font(11, QFont.Weight.Normal))
        sub_lbl.setStyleSheet(f"color: {M3.MUTED.name()};")
        title_box.addWidget(t_lbl)
        title_box.addWidget(sub_lbl)
        hdr.addLayout(title_box)
        hdr.addStretch()

        close_btn = IconButton("close", size=32, icon_size=12)
        close_btn.clicked.connect(self.hide)
        hdr.addWidget(close_btn)
        main_root.addLayout(hdr)

        # Scroll Area for all settings cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(255, 255, 255, 0.2);
                min-height: 24px;
                border-radius: 3px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {M3.PRIMARY.name()};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}
        """)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        root = QVBoxLayout(container)
        root.setContentsMargins(4, 4, 8, 4)
        root.setSpacing(12)

        # ─── Group 0: Buttons & Quick Actions ───
        grp_btns = QFrame()
        grp_btns.setStyleSheet(f"background: {M3.SURFACE_2.name()}; border-radius: 14px;")
        btns_layout = QVBoxLayout(grp_btns)
        btns_layout.setContentsMargins(14, 12, 14, 12)
        btns_layout.setSpacing(10)

        hdr_btns_row = QHBoxLayout()
        lbl_sec0 = QLabel("BUTTONS & QUICK ACTIONS")
        lbl_sec0.setFont(font(10, QFont.Weight.Bold))
        lbl_sec0.setStyleSheet(f"color: {M3.PRIMARY.name()};")
        hdr_btns_row.addWidget(lbl_sec0)
        hdr_btns_row.addStretch()

        btn_add_preset = QPushButton("+ Add Button")
        btn_add_preset.setFont(font(11, QFont.Weight.DemiBold))
        btn_add_preset.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_add_preset.setStyleSheet(f"""
            QPushButton {{
                background: {M3.SURFACE_3.name()};
                color: {M3.ON_SURFACE.name()};
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 4px 10px;
            }}
            QPushButton:hover {{ background: {M3.PRIMARY.name()}; color: {M3.ON_PRIMARY.name()}; }}
        """)
        btn_add_preset.clicked.connect(lambda: self.island.show_add_button_picker(
            btn_add_preset.mapToGlobal(QPointF(0, btn_add_preset.height()).toPoint())
        ))
        hdr_btns_row.addWidget(btn_add_preset)

        btn_rst_btns = QPushButton("Reset")
        btn_rst_btns.setFont(font(11, QFont.Weight.Normal))
        btn_rst_btns.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_rst_btns.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {M3.MUTED.name()};
                border: none;
                padding: 4px 6px;
            }}
            QPushButton:hover {{ color: {M3.ERROR.name()}; }}
        """)
        btn_rst_btns.clicked.connect(self.island.reset_buttons)
        hdr_btns_row.addWidget(btn_rst_btns)
        btns_layout.addLayout(hdr_btns_row)

        self.btns_list_layout = QVBoxLayout()
        self.btns_list_layout.setSpacing(6)
        btns_layout.addLayout(self.btns_list_layout)
        root.addWidget(grp_btns)

        # ─── Group 0b: System monitors ───
        grp_mon = QFrame()
        grp_mon.setStyleSheet(f"background: {M3.SURFACE_2.name()}; border-radius: 14px;")
        mon_layout = QVBoxLayout(grp_mon)
        mon_layout.setContentsMargins(14, 12, 14, 12)
        mon_layout.setSpacing(8)

        lbl_mon = QLabel("SYSTEM MONITORS")
        lbl_mon.setFont(font(10, QFont.Weight.Bold))
        lbl_mon.setStyleSheet(f"color: {M3.PRIMARY.name()};")
        mon_layout.addWidget(lbl_mon)

        mon_grid = QGridLayout()
        mon_grid.setHorizontalSpacing(12)
        mon_grid.setVerticalSpacing(8)
        self.mon_checks = {}
        for i, mid in enumerate(MONITOR_ORDER):
            cb = QCheckBox(MONITORS[mid][0])
            cb.setStyleSheet(f"""
                QCheckBox {{ color: {M3.ON_SURFACE.name()}; font-family: '{FONT}'; font-size: 12px; spacing: 8px; }}
                QCheckBox:disabled {{ color: {M3.MUTED.name()}; }}
                QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
                    background: {M3.SURFACE_3.name()}; border: 1px solid rgba(255, 255, 255, 0.15); }}
                QCheckBox::indicator:checked {{ background: {M3.PRIMARY.name()}; border-color: {M3.PRIMARY.name()}; }}
            """)
            cb.toggled.connect(lambda on, m=mid: self.island.set_monitor(m, on))
            mon_grid.addWidget(cb, i // 2, i % 2)
            self.mon_checks[mid] = cb
        mon_layout.addLayout(mon_grid)
        root.addWidget(grp_mon)

        # ─── Group 1: Geometry & Position ───
        grp_geo = QFrame()
        grp_geo.setStyleSheet(f"background: {M3.SURFACE_2.name()}; border-radius: 14px;")
        geo_layout = QVBoxLayout(grp_geo)
        geo_layout.setContentsMargins(14, 12, 14, 12)
        geo_layout.setSpacing(8)

        lbl_sec1 = QLabel("DIMENSIONS & POSITION")
        lbl_sec1.setFont(font(10, QFont.Weight.Bold))
        lbl_sec1.setStyleSheet(f"color: {M3.PRIMARY.name()};")
        geo_layout.addWidget(lbl_sec1)

        # Idle width
        r_w = QHBoxLayout()
        r_w_lbl = QLabel("Idle Width")
        r_w_lbl.setFont(font(12, QFont.Weight.DemiBold))
        r_w_lbl.setStyleSheet(f"color: {M3.ON_SURFACE.name()};")
        self.lbl_w_val = QLabel("196 px")
        self.lbl_w_val.setFont(font(11, QFont.Weight.Normal))
        self.lbl_w_val.setStyleSheet(f"color: {M3.MUTED.name()};")
        r_w.addWidget(r_w_lbl); r_w.addStretch(); r_w.addWidget(self.lbl_w_val)
        geo_layout.addLayout(r_w)
        self.sl_w = QSlider(Qt.Orientation.Horizontal)
        self.sl_w.setRange(150, 280)
        self._style_slider(self.sl_w)
        self.sl_w.valueChanged.connect(self._on_w_changed)
        geo_layout.addWidget(self.sl_w)

        # Top offset
        r_top = QHBoxLayout()
        r_top_lbl = QLabel("Top Margin")
        r_top_lbl.setFont(font(12, QFont.Weight.DemiBold))
        r_top_lbl.setStyleSheet(f"color: {M3.ON_SURFACE.name()};")
        self.lbl_top_val = QLabel("8 px")
        self.lbl_top_val.setFont(font(11, QFont.Weight.Normal))
        self.lbl_top_val.setStyleSheet(f"color: {M3.MUTED.name()};")
        r_top.addWidget(r_top_lbl); r_top.addStretch(); r_top.addWidget(self.lbl_top_val)
        geo_layout.addLayout(r_top)
        self.sl_top = QSlider(Qt.Orientation.Horizontal)
        self.sl_top.setRange(0, 32)
        self._style_slider(self.sl_top)
        self.sl_top.valueChanged.connect(self._on_top_changed)
        geo_layout.addWidget(self.sl_top)

        # Exp height
        r_h = QHBoxLayout()
        r_h_lbl = QLabel("Expanded Height")
        r_h_lbl.setFont(font(12, QFont.Weight.DemiBold))
        r_h_lbl.setStyleSheet(f"color: {M3.ON_SURFACE.name()};")
        self.lbl_h_val = QLabel("268 px")
        self.lbl_h_val.setFont(font(11, QFont.Weight.Normal))
        self.lbl_h_val.setStyleSheet(f"color: {M3.MUTED.name()};")
        r_h.addWidget(r_h_lbl); r_h.addStretch(); r_h.addWidget(self.lbl_h_val)
        geo_layout.addLayout(r_h)
        self.sl_h = QSlider(Qt.Orientation.Horizontal)
        self.sl_h.setRange(220, 320)
        self._style_slider(self.sl_h)
        self.sl_h.valueChanged.connect(self._on_h_changed)
        geo_layout.addWidget(self.sl_h)
        root.addWidget(grp_geo)

        # ─── Group 2: Accent Theme ───
        grp_theme = QFrame()
        grp_theme.setStyleSheet(f"background: {M3.SURFACE_2.name()}; border-radius: 14px;")
        th_layout = QVBoxLayout(grp_theme)
        th_layout.setContentsMargins(14, 12, 14, 12)
        th_layout.setSpacing(10)

        lbl_sec2 = QLabel("ACCENT COLOR")
        lbl_sec2.setFont(font(10, QFont.Weight.Bold))
        lbl_sec2.setStyleSheet(f"color: {M3.PRIMARY.name()};")
        th_layout.addWidget(lbl_sec2)

        chips_row = QHBoxLayout()
        chips_row.setSpacing(12)
        self.palette = [
            ("#A8C7FA", "Sky Blue"),
            ("#7FD88F", "Emerald"),
            ("#D0BCFF", "Neon Violet"),
            ("#FFB86C", "Sunset Gold"),
            ("#FFB4AB", "Crimson Rose"),
            ("#70F0FF", "Cyber Cyan"),
        ]
        self.color_chips = []
        for hex_code, col_name in self.palette:
            chip = ColorChip(hex_code, col_name)
            chip.clicked.connect(lambda _, h=hex_code: self._on_color_picked(h))
            chips_row.addWidget(chip)
            self.color_chips.append(chip)
        chips_row.addStretch()
        th_layout.addLayout(chips_row)
        root.addWidget(grp_theme)

        # ─── Group 3: Behavior ───
        grp_beh = QFrame()
        grp_beh.setStyleSheet(f"background: {M3.SURFACE_2.name()}; border-radius: 14px;")
        beh_layout = QVBoxLayout(grp_beh)
        beh_layout.setContentsMargins(14, 12, 14, 12)
        beh_layout.setSpacing(10)

        lbl_sec3 = QLabel("SYSTEM & BEHAVIOR")
        lbl_sec3.setFont(font(10, QFont.Weight.Bold))
        lbl_sec3.setStyleSheet(f"color: {M3.PRIMARY.name()};")
        beh_layout.addWidget(lbl_sec3)

        # Auto collapse
        r_del = QHBoxLayout()
        r_del_lbl = QLabel("Auto-Collapse Delay")
        r_del_lbl.setFont(font(12, QFont.Weight.DemiBold))
        r_del_lbl.setStyleSheet(f"color: {M3.ON_SURFACE.name()};")
        self.lbl_del_val = QLabel("1000 ms")
        self.lbl_del_val.setFont(font(11, QFont.Weight.Normal))
        self.lbl_del_val.setStyleSheet(f"color: {M3.MUTED.name()};")
        r_del.addWidget(r_del_lbl); r_del.addStretch(); r_del.addWidget(self.lbl_del_val)
        beh_layout.addLayout(r_del)
        self.sl_del = QSlider(Qt.Orientation.Horizontal)
        self.sl_del.setRange(50, 3000)
        self._style_slider(self.sl_del)
        self.sl_del.valueChanged.connect(self._on_del_changed)
        beh_layout.addWidget(self.sl_del)

        cb_style = f"""
            QCheckBox {{
                color: {M3.ON_SURFACE.name()};
                font-family: '{FONT}';
                font-size: 12px;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 4px;
                background: {M3.SURFACE_3.name()};
                border: 1px solid rgba(255, 255, 255, 0.15);
            }}
            QCheckBox::indicator:checked {{
                background: {M3.PRIMARY.name()};
                border-color: {M3.PRIMARY.name()};
            }}
        """
        self.cb_ontop = QCheckBox("Always on top  (off = on the desktop, apps cover it)")
        self.cb_ontop.setStyleSheet(cb_style)
        self.cb_ontop.toggled.connect(lambda v: self.island.apply_setting("always_on_top", v))
        beh_layout.addWidget(self.cb_ontop)

        self.cb_boot = QCheckBox("Start with Windows")
        self.cb_boot.setStyleSheet(cb_style)
        self.cb_boot.toggled.connect(lambda v: self.island.apply_setting("start_on_boot", v))
        beh_layout.addWidget(self.cb_boot)

        self.cb_toast = QCheckBox("Clipboard Copy Notifications")
        self.cb_toast.setStyleSheet(cb_style)
        self.cb_toast.toggled.connect(lambda v: self.island.apply_setting("clipboard_toast", v))
        beh_layout.addWidget(self.cb_toast)

        self.cb_wan = QCheckBox("Colour the WAN address by VPN  (green = VPN, red = direct)")
        self.cb_wan.setStyleSheet(cb_style)
        self.cb_wan.toggled.connect(lambda v: self.island.apply_setting("wan_vpn_color", v))
        beh_layout.addWidget(self.cb_wan)
        root.addWidget(grp_beh)

        scroll.setWidget(container)
        main_root.addWidget(scroll, 1)

        # ─── Footer ───
        footer = QHBoxLayout()
        footer.setSpacing(10)
        btn_reset = QPushButton("Reset Defaults")
        btn_reset.setFont(font(12, QFont.Weight.DemiBold))
        btn_reset.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_reset.setStyleSheet(f"""
            QPushButton {{
                background: {M3.SURFACE_2.name()};
                color: {M3.ON_SURFACE.name()};
                border: 1px solid rgba(255,255,255,0.08);
                border-radius: 12px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{ background: {M3.SURFACE_3.name()}; }}
        """)
        btn_reset.clicked.connect(self._reset_defaults)
        footer.addWidget(btn_reset)
        footer.addStretch()

        btn_done = QPushButton("Done")
        btn_done.setFont(font(12, QFont.Weight.DemiBold))
        btn_done.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_done.setStyleSheet(f"""
            QPushButton {{
                background: {M3.PRIMARY.name()};
                color: {M3.ON_PRIMARY.name()};
                border: none;
                border-radius: 12px;
                padding: 8px 24px;
            }}
            QPushButton:hover {{ background: #FFFFFF; color: #000000; }}
        """)
        btn_done.clicked.connect(self.hide)
        footer.addWidget(btn_done)
        main_root.addLayout(footer)

    def _on_w_changed(self, v):
        self.lbl_w_val.setText(f"{v} px")
        self.island.apply_setting("idle_width", v)

    def _on_top_changed(self, v):
        self.lbl_top_val.setText(f"{v} px")
        self.island.apply_setting("top_offset", v)

    def _on_h_changed(self, v):
        self.lbl_h_val.setText(f"{v} px")
        self.island.apply_setting("exp_height", v)

    def _on_del_changed(self, v):
        self.lbl_del_val.setText(f"{v} ms")
        self.island.apply_setting("collapse_delay", v)

    def _on_color_picked(self, hex_val):
        for chip in self.color_chips:
            chip.selected = (chip.color_hex == hex_val)
            chip.update()
        self.island.apply_setting("accent_color", hex_val)
        self._style_slider(self.sl_w)
        self._style_slider(self.sl_top)
        self._style_slider(self.sl_h)
        self._style_slider(self.sl_del)

    def _reset_defaults(self):
        self.island.reset_settings()
        self.sync_ui()

    def sync_ui(self):
        s = self.island.settings
        w = int(s.get("idle_width", 196))
        self.sl_w.blockSignals(True)
        self.sl_w.setValue(w)
        self.sl_w.blockSignals(False)
        self.lbl_w_val.setText(f"{w} px")

        top = int(s.get("top_offset", 8))
        self.sl_top.blockSignals(True)
        self.sl_top.setValue(top)
        self.sl_top.blockSignals(False)
        self.lbl_top_val.setText(f"{top} px")

        h = int(s.get("exp_height", 268))
        self.sl_h.blockSignals(True)
        self.sl_h.setValue(h)
        self.sl_h.blockSignals(False)
        self.lbl_h_val.setText(f"{h} px")

        delay = int(s.get("collapse_delay", 1000))
        self.sl_del.blockSignals(True)
        self.sl_del.setValue(delay)
        self.sl_del.blockSignals(False)
        self.lbl_del_val.setText(f"{delay} ms")

        cur_accent = s.get("accent_color", "#A8C7FA").upper()
        for chip in self.color_chips:
            chip.selected = (chip.color_hex.upper() == cur_accent)
            chip.update()

        self.cb_ontop.blockSignals(True)
        self.cb_ontop.setChecked(bool(s.get("always_on_top", False)))
        self.cb_ontop.blockSignals(False)

        boot_val = get_windows_autostart()
        self.cb_boot.blockSignals(True)
        self.cb_boot.setChecked(boot_val)
        self.cb_boot.blockSignals(False)

        self.cb_toast.blockSignals(True)
        self.cb_toast.setChecked(bool(s.get("clipboard_toast", True)))
        self.cb_toast.blockSignals(False)

        self.cb_wan.blockSignals(True)
        self.cb_wan.setChecked(bool(s.get("wan_vpn_color", True)))
        self.cb_wan.blockSignals(False)

        self.sync_buttons_list()
        self.sync_monitors()

    def sync_monitors(self):
        enabled = self.island.get_monitors()
        for mid, cb in self.mon_checks.items():
            on = mid in enabled
            cb.blockSignals(True)
            cb.setChecked(on)
            cb.blockSignals(False)
            # Something this PC lacks (e.g. no NVIDIA GPU) can be switched off but not on
            available = on or monitor_available(mid)
            cb.setEnabled(available)
            cb.setText(MONITORS[mid][0] + ("" if available else "  (not on this PC)"))

    def sync_buttons_list(self):
        while self.btns_list_layout.count():
            item = self.btns_list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        buttons = self.island.get_buttons()
        n = len(buttons)

        if not buttons:
            empty_lbl = QLabel("No active buttons. Click '+ Add Button' above.")
            empty_lbl.setFont(font(11, QFont.Weight.Normal))
            empty_lbl.setStyleSheet(f"color: {M3.MUTED.name()}; padding: 6px 0;")
            self.btns_list_layout.addWidget(empty_lbl)
            return

        for i, b in enumerate(buttons):
            row = QFrame()
            row.setStyleSheet(f"""
                QFrame {{
                    background: {M3.SURFACE_3.name()};
                    border-radius: 10px;
                }}
            """)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 6, 8, 6)
            rl.setSpacing(8)

            ic = QWidget()
            ic.setFixedSize(22, 22)
            icon_name = b.get("icon", "pulse")
            def _make_icon_painter(iname, ic=ic):
                def _paint(e):
                    p = QPainter(ic)
                    p.setRenderHint(QPainter.RenderHint.Antialiasing)
                    draw_icon(p, iname, QRectF(2, 2, 18, 18), M3.PRIMARY)
                return _paint
            ic.paintEvent = _make_icon_painter(icon_name)
            rl.addWidget(ic)

            lbl = QLabel(b.get("label", "Action"))
            lbl.setFont(font(12, QFont.Weight.DemiBold))
            lbl.setStyleSheet(f"color: {M3.ON_SURFACE.name()};")
            rl.addWidget(lbl, 1)

            btn_style = f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.08);
                    color: {M3.ON_SURFACE.name()};
                    border: none;
                    border-radius: 6px;
                    min-width: 26px;
                    max-width: 26px;
                    min-height: 26px;
                    max-height: 26px;
                    font-size: 11px;
                }}
                QPushButton:hover {{ background: rgba(255, 255, 255, 0.2); }}
                QPushButton:disabled {{ color: rgba(255, 255, 255, 0.2); background: transparent; }}
            """

            btn_up = QPushButton("▲")
            btn_up.setStyleSheet(btn_style)
            btn_up.setEnabled(i > 0)
            btn_up.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn_up.clicked.connect(lambda _, idx=i: self.island.move_button(idx, -1))
            rl.addWidget(btn_up)

            btn_down = QPushButton("▼")
            btn_down.setStyleSheet(btn_style)
            btn_down.setEnabled(i < n - 1)
            btn_down.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn_down.clicked.connect(lambda _, idx=i: self.island.move_button(idx, 1))
            rl.addWidget(btn_down)

            del_style = f"""
                QPushButton {{
                    background: rgba(255, 80, 80, 0.15);
                    color: #FF8080;
                    border: none;
                    border-radius: 6px;
                    min-width: 26px;
                    max-width: 26px;
                    min-height: 26px;
                    max-height: 26px;
                    font-size: 11px;
                }}
                QPushButton:hover {{ background: rgba(255, 80, 80, 0.35); color: #FFFFFF; }}
            """
            btn_del = QPushButton("✕")
            btn_del.setStyleSheet(del_style)
            btn_del.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn_del.clicked.connect(lambda _, idx=i: self.island.remove_button(idx))
            rl.addWidget(btn_del)

            self.btns_list_layout.addWidget(row)


# ───────────────────────── The capsule window ─────────────────────────
class DynamicCapsule(QWidget):
    wan_ready = pyqtSignal(str)  # emitted from the lookup thread
    WIN_W, WIN_H = 620, 370          # fixed transparent canvas
    TOP = 8
    COMPACT_H = 40
    W_IDLE, W_MEDIA, W_TOAST = 196, 236, 320
    EXP_W, EXP_H = 540, 268
    PAD = 18

    def __init__(self):
        super().__init__()
        self.settings = SettingsManager()
        self.settings_dialog = None
        self.W_IDLE = int(self.settings.get("idle_width", 196))
        self.TOP = int(self.settings.get("top_offset", 8))
        self.EXP_H = int(self.settings.get("exp_height", 268))
        accent = self.settings.get("accent_color", "#A8C7FA")
        M3.PRIMARY = QColor(accent)
        self.aura_color = M3.PRIMARY

        flags = (Qt.WindowType.FramelessWindowHint |
                 Qt.WindowType.Tool |
                 Qt.WindowType.NoDropShadowWindowHint)
        self._desktop_level = not self.settings.get("always_on_top", False)
        if not self._desktop_level:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(self.WIN_W, self.WIN_H)

        # Width and height share one spring tuning so the pill keeps its shape while it
        # morphs; damped just short of critical: it glides in and settles with no bounce.
        self.sw = Spring(self.W_IDLE, 420, 0.9, eps=0.2)
        self.sh = Spring(self.COMPACT_H, 420, 0.9, eps=0.2)
        self.expanded = False
        self.pinned = False
        self.aura = 0.0
        self.audio_playing = False
        self.audio_peak = 0.0
        self.audio_app = ""
        self.focus_left = 0
        self.focus_total = 0
        self.focus_paused = False
        self.clock_frozen_time = None
        self.toast_until = 0.0
        self.last_clip = ""
        self.net = NetMeter()
        self._cpu_at = 0.0
        self._cpu_pct = 0.0
        self._threads = (psutil.cpu_count() if HAS_PSUTIL else None) or 4
        self._manual_open = False
        self._layout_key = None
        self._quitting = False
        self.wan_ip = ""
        self._wan_busy = False
        self._probe_n = 0
        self.media_info = None
        self._peak_ref = 0.05
        self.menu_groups = []
        try:
            self.menu_groups = load_menu()
        except Exception:
            pass  # reported by reload_menu once the window exists

        self._build()
        self._place()
        try:
            app = QApplication.instance()
            app.primaryScreenChanged.connect(self._on_primary_screen)  # dock / undock / projector
            screen = QApplication.primaryScreen()
            if screen:
                screen.geometryChanged.connect(lambda _: self._place())
        except Exception:
            pass


        self.setMouseTracking(True)
        self.content.setMouseTracking(True)
        self.compact.setMouseTracking(True)
        self.panel.setMouseTracking(True)
        collapse_ms = int(self.settings.get("collapse_delay", 1000))
        self.leave_timer = QTimer(self, singleShot=True, interval=collapse_ms, timeout=self.collapse)

        # Background Audio Worker thread (zero main thread blocking!)
        self.audio_worker = AudioWorker(self)
        self.audio_worker.audio_updated.connect(self._on_audio_worker_update)
        Volume.worker = self.audio_worker
        self.audio_worker.start()

        self._t = time.perf_counter()
        self.frame = QTimer(self, timerType=Qt.TimerType.PreciseTimer, interval=self.FRAME_FAST, timeout=self._frame)
        self.frame.start()
        QTimer(self, interval=1000, timeout=self._tick_1s).start()
        QTimer(self, interval=1000, timeout=self._tick_hw).start()

        # Public address: looked up on a route change (settled for 2 s, a VPN connecting
        # fires a burst of changes) and every 5 minutes as a backstop
        self.wan_ready.connect(self._on_wan)
        self.wan_debounce = QTimer(self, singleShot=True, interval=2000, timeout=self._refresh_wan)
        QTimer(self, interval=300000, timeout=self._refresh_wan).start()

        # menu.json hot reload
        self.menu_timer = QTimer(self, singleShot=True, interval=300, timeout=lambda: self.reload_menu(True))
        self.menu_watch = QFileSystemWatcher(self)
        self.menu_watch.fileChanged.connect(lambda _: self.menu_timer.start())
        self.reload_menu()

        self.spectrum = SpectrumWorker()
        self.media.wave.spectrum = self.compact.spectrum = self.spectrum
        self.spectrum.start()

        self.media_worker = MediaInfoWorker(self)
        self.media_worker.info.connect(self._on_media_info)
        self.media_worker.start()
        # Read the clipboard only when Windows says it changed (and once it has settled).
        # Polling it forces the source app to render its data again on every poll,
        # which stalls both apps when the copy is large (e.g. a big Excel range).
        self.clip_timer = QTimer(self, singleShot=True, interval=250, timeout=self._read_clip)
        cb = QApplication.clipboard()
        if cb:
            cb.dataChanged.connect(self.clip_timer.start)
        self._tick_1s(); self._tick_hw()
        self._tray()


    # ---------- build ----------
    def _build(self):
        self.content = QWidget(self)
        self.content.setStyleSheet("background: transparent;")

        self.compact = CompactView(self.content)
        self.compact.play_clicked.connect(self.toggle_play)
        self.compact.clock_pause_clicked.connect(self.toggle_clock_pause)
        self.compact.expand_clicked.connect(self.expand)
        self.compact_fx = QGraphicsOpacityEffect(self.compact)
        self.compact.setGraphicsEffect(self.compact_fx)

        self.panel = QWidget(self.content)
        self.panel.setFixedSize(self.EXP_W, self.EXP_H)
        self.panel_fx = QGraphicsOpacityEffect(self.panel)
        self.panel_fx.setOpacity(0)
        self.panel.setGraphicsEffect(self.panel_fx)
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(self.PAD, 16, self.PAD, self.PAD)
        pl.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(10)
        self.h_time = label("00:00", 22, M3.ON_SURFACE, QFont.Weight.Bold)
        self.h_date = label("", 12, M3.MUTED, QFont.Weight.DemiBold)
        dcol = QVBoxLayout(); dcol.setSpacing(0)
        dcol.addWidget(self.h_time); dcol.addWidget(self.h_date)
        header.addLayout(dcol)
        header.addStretch()
        self.tabs = SegmentedTabs(["Media", "System", "Tools", "Focus", "Apps"])
        self.tabs.setFixedWidth(360)
        header.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignVCenter)
        pl.addLayout(header)

        self.stack = QStackedWidget()
        self.media = MediaPage(self)
        self.system = SystemPage(self)
        self.tools = ToolsPage(self)
        self.focus = FocusPage(self)
        self.apps = AppsPage(self)
        for pg in (self.media, self.system, self.tools, self.focus, self.apps):
            self.stack.addWidget(pg)
        self.tabs.changed.connect(self.stack.setCurrentIndex)
        pl.addWidget(self.stack, 1)

    def _place(self):
        try:
            screen = QApplication.primaryScreen()
            if screen:
                scr = screen.geometry()
                self.move(scr.x() + (scr.width() - self.WIN_W) // 2, scr.y() + self.TOP)
            else:
                self.move((1920 - self.WIN_W) // 2, self.TOP)
        except Exception:
            self.move(200, self.TOP)

    # ---------- window layer ----------
    def _apply_layer(self):
        """Desktop level = bottom of the window stack, like a widget on the wallpaper."""
        if self._desktop_level:
            try:
                ctypes.windll.user32.SetWindowPos(
                    wintypes.HWND(int(self.winId())), wintypes.HWND(1),  # 1 = HWND_BOTTOM
                    0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)                # NOSIZE | NOMOVE | NOACTIVATE
            except Exception:
                pass

    def showEvent(self, e):
        super().showEvent(e)
        self._apply_layer()

    def nativeEvent(self, event_type, message):
        # Clicking the capsule would normally raise it above everything. At desktop
        # level every z-order change is redirected to "stay at the bottom" instead.
        if self._desktop_level:
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0046:  # WM_WINDOWPOSCHANGING
                    pos = WINDOWPOS.from_address(msg.lParam)
                    pos.hwndInsertAfter = 1   # HWND_BOTTOM
                    pos.flags &= ~0x0004      # clear SWP_NOZORDER so the line above applies
            except Exception:
                pass
        return False, 0

    def _on_primary_screen(self, screen):
        if screen:
            screen.geometryChanged.connect(lambda _: self._place())
        self._place()

    # ---------- geometry ----------
    def pill_rect(self):
        w, h = self.sw.x, self.sh.x
        return QRectF((self.WIN_W - w) / 2, self.TOP, w, h)

    # Frame pacing: full speed only while something is really moving. An always-on
    # 125 fps repaint of a translucent window is what pinned a CPU core on laptops.
    FRAME_FAST = 8       # springs / aura in motion
    FRAME_SPECTRUM = 16  # live spectrum on the Media page
    FRAME_AMBIENT = 33   # mini equalizer, gauges, album art
    FRAME_IDLE = 150     # nothing to draw; just watch for toasts ending

    def _frame(self):
        now = time.perf_counter()
        dt = min(0.033, now - self._t)
        self._t = now
        moving = self.sw.step(dt) | self.sh.step(dt)

        if self.toast_until and now > self.toast_until:
            self.toast_until = 0
            self.compact.toast_text = ""
            self.compact.update()
            self._update_compact_target()

        fading = self.aura > 0
        if fading:
            self.aura = max(0.0, self.aura - dt * 1.4)

        # Re-lay-out, re-mask and repaint only when the pill actually changed
        r = self.pill_rect()
        key = (r.x(), r.width(), r.height(), self.TOP, self.EXP_H)
        if key != self._layout_key:
            self._layout_key = key
            moving = True
            rect = r.toRect()
            self.content.setGeometry(rect)
            self.compact.setGeometry(0, 0, rect.width(), self.COMPACT_H)
            self.panel.move(int((rect.width() - self.EXP_W) / 2), 0)

            denom = max(1.0, float(self.EXP_H - self.COMPACT_H))
            prog = max(0.0, min(1.0, (self.sh.x - self.COMPACT_H) / denom))
            self.compact_fx.setOpacity(max(0.0, 1 - prog * 3))
            self.panel_fx.setOpacity(max(0.0, (prog - 0.35) / 0.65))
            # A fully opaque effect still renders through an off-screen copy; switch it off
            self.compact_fx.setEnabled(prog > 0.001)
            self.panel_fx.setEnabled(prog < 0.999)
            self.compact.setVisible(prog < 0.34)
            self.panel.setVisible(prog > 0.3)
            # No window mask: the transparent canvas is click-through on its own, and
            # re-cutting the window region on every frame made the morph stutter.
            self.update()
        elif fading:
            self.update()

        spectrum = False
        ambient = self.compact.isVisible() and self.compact.tick(dt)
        moving |= self.tabs.tick(dt)
        if self.panel.isVisible():
            page = self.stack.currentWidget()
            if page is self.media:
                ambient |= self.media.tick(dt)
                if self.media.wave.active:
                    spectrum = True
            elif page is self.system:
                ambient |= self.system.tick(dt)
            elif page is self.focus:
                moving |= self.focus.ring.tick(dt)

        rate = (self.FRAME_FAST if (moving or fading) else self.FRAME_SPECTRUM if spectrum
                else self.FRAME_AMBIENT if ambient else self.FRAME_IDLE)
        if self.frame.interval() != rate:
            self.frame.setInterval(rate)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.pill_rect()
        rad = min(r.height() / 2, 32)
        # aura (inside the mask, as an inner glow ring)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(M3.CAPSULE)
        p.drawRoundedRect(r, rad, rad)
        if self.aura > 0:
            c = QColor(self.aura_color)
            c.setAlphaF(min(1.0, self.aura) * 0.9)
            p.setPen(QPen(c, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), rad - 1, rad - 1)
            g = QRadialGradient(QPointF(r.center().x(), r.top()), r.width() * 0.6)
            c2 = QColor(c); c2.setAlphaF(min(1.0, self.aura) * 0.18)
            g.setColorAt(0, c2); g.setColorAt(1, QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(r, rad, rad)
        else:
            p.setPen(QPen(QColor(255, 255, 255, 18), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)

    # ---------- state ----------
    def _update_compact_target(self):
        if self.expanded:
            return
        if self.compact.toast_text:
            self.sw.target = self.W_TOAST
        elif self.audio_playing or self.focus_left:
            self.sw.target = self.W_MEDIA
        else:
            self.sw.target = self.W_IDLE
        self.sh.target = self.COMPACT_H

    def expand(self):
        self.leave_timer.stop()
        if self.expanded:
            return
        self.expanded = True
        self.sw.target, self.sh.target = self.EXP_W, self.EXP_H
        self._tick_hw()
        self._frame()

    def collapse(self):
        if not self.expanded or self.pinned:
            return
        self.expanded = False
        self._manual_open = False
        self._update_compact_target()
        self._frame()

    def toast(self, text, icon, color, secs=2.6):
        self.compact.toast_text, self.compact.toast_icon, self.compact.toast_color = text, icon, color
        self.toast_until = time.perf_counter() + secs
        self.aura, self.aura_color = 1.0, color
        self.compact.update()
        self._update_compact_target()
        self._frame()

    def _hold_open(self):
        """Stay expanded while one of our menus is open."""
        return QApplication.activePopupWidget() is not None

    def _schedule_collapse(self):
        if self.expanded and not self.pinned and not self.leave_timer.isActive() and not self._hold_open():
            self.leave_timer.start()

    def enterEvent(self, e):
        self.leave_timer.stop()
        self._manual_open = False
        if not self.expanded:
            self.expand()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._schedule_collapse()
        super().leaveEvent(e)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self.pill_rect().contains(pos):
            self.leave_timer.stop()
            if not self.expanded:
                self.expand()
        else:
            self._schedule_collapse()
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self._menu(e.globalPosition().toPoint())
            e.accept()
            return
        super().mousePressEvent(e)

    def contextMenuEvent(self, e):
        self._menu(e.globalPos())
        e.accept()


    def wheelEvent(self, e):
        if self.expanded:
            n = len(self.tabs.labels)
            self.tabs.set_index((self.tabs.index + (-1 if e.angleDelta().y() > 0 else 1)) % n)

    # ---------- actions ----------
    def media_cmd(self, name):
        """toggle / next / prev: sent to the playing app's media session when there is
        one, otherwise as a keyboard media key."""
        if self.media_info and self.media_worker.available:
            self.media_worker.command(name)
        else:
            media_key({"toggle": VK_PLAY, "next": VK_NEXT, "prev": VK_PREV}[name])

    def toggle_play(self):
        self.media_cmd("toggle")
        self.aura, self.aura_color = 0.8, M3.PRIMARY

    def toggle_mute(self):
        m = Volume.toggle_mute()
        self.media.vol_icon.set_icon("mute" if m else "speaker")
        if self.tools.t_mute:
            self.tools.t_mute.active = m
            self.tools.t_mute.update()
        self.toast("Muted" if m else "Sound on", "mute" if m else "speaker", M3.ERROR if m else M3.PRIMARY)

    def toggle_clock_pause(self):
        """Pause or unpause the clock display or active focus countdown."""
        if self.focus_left > 0:
            self.focus_paused = not self.focus_paused
            self.compact.clock_paused = self.focus_paused
            self.toast("Timer paused" if self.focus_paused else "Timer resumed", "timer",
                       M3.ORANGE if self.focus_paused else M3.TERTIARY)
        else:
            if self.clock_frozen_time is None:
                self.clock_frozen_time = self.compact.time_text
                self.compact.clock_paused = True
                self.toast(f"Clock paused at {self.clock_frozen_time}", "timer", M3.ORANGE)
            else:
                self.clock_frozen_time = None
                self.compact.clock_paused = False
                now = QTime.currentTime()
                self.compact.time_text = now.toString("HH:mm")
                self.toast("Clock resumed", "timer", M3.PRIMARY)
        self.compact.update()

    def snip(self):
        self.collapse()
        QTimer.singleShot(300, lambda: subprocess.Popen(["explorer", "ms-screenclip:"]))

    def lock(self):
        try:
            import ctypes
            ctypes.windll.user32.LockWorkStation()
        except Exception:
            pass

    # ---------- button customization ----------
    def get_buttons(self):
        btns = self.settings.get("tools_buttons", DEFAULT_BUTTONS)
        if not isinstance(btns, list):
            btns = list(DEFAULT_BUTTONS)
        # Settings saved by older versions may still list the removed AI Assistant tile
        return [b for b in btns if isinstance(b, dict) and b.get("action") != "ai"]

    def set_buttons(self, btns):
        self.settings.set("tools_buttons", btns)
        if hasattr(self, "tools") and self.tools is not None:
            self.tools.rebuild_buttons()
        if hasattr(self, "settings_dialog") and self.settings_dialog is not None:
            self.settings_dialog.sync_buttons_list()

    def move_button(self, index: int, direction: int):
        btns = list(self.get_buttons())
        target = index + direction
        if 0 <= index < len(btns) and 0 <= target < len(btns):
            btns[index], btns[target] = btns[target], btns[index]
            self.set_buttons(btns)

    def remove_button(self, index: int):
        btns = list(self.get_buttons())
        if 0 <= index < len(btns):
            item = btns.pop(index)
            self.set_buttons(btns)
            self.toast(f"Removed '{item.get('label', 'button')}'", "trash", M3.ERROR)

    def add_button(self, button_data: dict):
        btns = list(self.get_buttons())
        btns.append(button_data)
        self.set_buttons(btns)
        self.toast(f"Added '{button_data.get('label', 'button')}'", "plus", M3.PRIMARY)

    def reset_buttons(self):
        self.set_buttons(list(DEFAULT_BUTTONS))
        self.toast("Reset buttons to defaults", "settings", M3.PRIMARY)

    def execute_button_action(self, b: dict):
        act = b.get("action", "")
        if act == "snip":
            self.snip()
        elif act == "mute":
            self.toggle_mute()
        elif act == "lock":
            self.lock()
        elif act == "taskmgr":
            subprocess.Popen(["taskmgr"])
        elif act == "settings":
            self.open_settings()
        elif act == "calc":
            subprocess.Popen("calc.exe", shell=True)
        elif act == "notepad":
            subprocess.Popen("notepad.exe", shell=True)
        elif act == "term":
            subprocess.Popen("wt.exe" if shutil.which("wt") else "cmd.exe", shell=True)
        elif act == "explorer":
            subprocess.Popen("explorer.exe", shell=True)
        elif act == "browser":
            subprocess.Popen("start https://www.google.com", shell=True)
        elif act == "custom":
            cmd = b.get("cmd", "")
            if cmd:
                subprocess.Popen(cmd, shell=True)
        else:
            cmd = b.get("cmd") or act
            if cmd:
                try:
                    subprocess.Popen(cmd, shell=True)
                except Exception:
                    pass

    def show_add_button_picker(self, global_pos):
        m = QMenu(self)
        self._menu_style(m)
        m.addAction("⚡ Presets").setEnabled(False)
        m.addSeparator()
        preset_acts = {}
        for p in AVAILABLE_BUTTON_PRESETS:
            act = m.addAction(f"{p['label']}")
            preset_acts[act] = p
        m.addSeparator()
        a_custom = m.addAction("➕  Custom Command / App...")
        chosen = m.exec(global_pos)
        if chosen in preset_acts:
            self.add_button(dict(preset_acts[chosen]))
        elif chosen == a_custom:
            self.prompt_add_custom_button()

    def prompt_add_custom_button(self):
        name, ok1 = QInputDialog.getText(self, "Add Custom Button", "Button Name:")
        if not ok1 or not name.strip():
            return
        cmd, ok2 = QInputDialog.getText(self, "Add Custom Button", "Command or App path to run:")
        if not ok2 or not cmd.strip():
            return
        btn = {
            "id": f"custom_{int(time.time())}",
            "label": name.strip(),
            "icon": "term",
            "action": "custom",
            "cmd": cmd.strip()
        }
        self.add_button(btn)

    def start_focus(self, secs):
        self.focus_left = self.focus_total = secs
        self.focus_paused = False
        self.compact.clock_paused = False
        for m, c in self.focus.chips:
            c.selected = secs == m * 60
            c.update()
        self.focus.ring.running = secs > 0
        self.focus.ring.progress.target = 1.0
        self.focus.ring.text = self._fmt(secs) if secs else "25:00"
        self.focus.ring.update()
        self.compact.update()
        if secs:
            self.toast(f"Focus · {secs // 60} min", "timer", M3.TERTIARY)
        self._update_compact_target()

    @staticmethod
    def _fmt(s):
        return f"{s // 60:02d}:{s % 60:02d}"

    # ---------- monitors ----------
    def get_monitors(self):
        """Enabled System-page monitors, in display order."""
        chosen = self.settings.get("monitors")
        if not isinstance(chosen, list):
            chosen = default_monitors()
        return [m for m in MONITOR_ORDER if m in chosen]

    def set_monitor(self, mid, on):
        chosen = set(self.get_monitors())
        if on:
            chosen.add(mid)
        else:
            chosen.discard(mid)
        self.settings.set("monitors", [m for m in MONITOR_ORDER if m in chosen])
        self._monitors_changed()

    def _monitors_changed(self):
        self.system.rebuild()
        if self.system.strip.show_ips and not self.wan_ip:
            self.net.probe()
            self._refresh_wan()
        self._tick_1s()
        self._tick_hw()
        if self.settings_dialog is not None:
            self.settings_dialog.sync_monitors()

    def _on_media_info(self, info):
        self.media_info = info
        self._refresh_media()

    def _refresh_media(self):
        """Media page text: the real track when Windows knows it, else the app making sound."""
        m = self.media_info
        playing = self.audio_playing
        if m:
            title = m["title"]
            sub = "  ·  ".join(x for x in (m["artist"], m["app"]) if x)
            playing = m["playing"]
        elif playing:
            title, sub = self.audio_app or "Now playing", "Playing on this PC"
        else:
            title, sub = "Nothing playing", "Play something to see it here"
        self.media.title.setText(title)
        self.media.sub.setText(sub)
        self.media.art.set_art(m["art"] if m else b"")
        self.media.btn_play.set_icon("pause" if playing else "play")

    def _on_audio_worker_update(self, playing, peak, app_name, vol_val, is_muted):
        was = self.audio_playing
        self.audio_playing = playing
        self.audio_peak = peak
        self.audio_app = app_name
        Volume._cached_mute = is_muted

        # Loudness relative to the recent peak, so the bars also move at low volume
        self._peak_ref = max(self._peak_ref * 0.995, peak, 0.02)
        energy = min(1.0, peak / self._peak_ref)
        self.compact.playing = playing
        self.compact.energy = energy
        self.media.wave.active = playing
        self.spectrum.active = playing
        self.media.wave.energy = energy
        self.media.art.playing = playing
        self.media.vol_icon.set_icon("mute" if is_muted else "speaker")
        if self.tools.t_mute and self.tools.t_mute.active != is_muted:
            self.tools.t_mute.active = is_muted
            self.tools.t_mute.update()

        self._refresh_media()

        if not self.media.slider.isSliderDown() and vol_val != self.media.slider.value():
            Volume._cached_vol = vol_val
            self.media.slider.blockSignals(True)
            self.media.slider.setValue(vol_val)
            self.media.slider.blockSignals(False)
            self.media.vol_lbl.setText(f"{vol_val}%")

        if was != playing:
            self.compact.update()
            self._update_compact_target()
            self._frame()

    def _tick_1s(self):
        now = QTime.currentTime()
        self.h_time.setText(now.toString("HH:mm"))
        from PyQt6.QtCore import QDate
        self.h_date.setText(QDate.currentDate().toString("dddd, d MMMM"))

        shown = (self.compact.time_text, self.compact.battery, self.compact.charging)
        if self.focus_left > 0:
            if not self.focus_paused:
                self.focus_left -= 1
                self.focus.ring.text = self._fmt(self.focus_left)
                self.focus.ring.progress.target = self.focus_left / max(1, self.focus_total)
                if self.focus_left == 0:
                    self.focus.ring.running = False
                    self.focus.ring.text = "Done"
                    for _, c in self.focus.chips:
                        c.selected = False; c.update()
                    self.toast("Focus session complete", "timer", M3.TERTIARY, 4)
                self.focus.ring.update()
            self.compact.time_text = self._fmt(self.focus_left)
        else:
            if self.clock_frozen_time is not None:
                self.compact.time_text = self.clock_frozen_time
            else:
                self.compact.time_text = now.toString("HH:mm")

        b = None
        if HAS_PSUTIL and psutil:
            try:
                b = psutil.sensors_battery()
            except Exception:
                b = None
        if b:
            self.compact.battery, self.compact.charging = int(b.percent), bool(b.power_plugged)
            self.system.set("battery", b.percent, "Charging" if b.power_plugged else "On battery")
        else:
            self.compact.battery = None
            self.system.set("battery", 100, "AC power")
        if shown != (self.compact.time_text, self.compact.battery, self.compact.charging):
            self.compact.update()

        # Safety net: a missed leave event must not leave the capsule stuck open
        if self.expanded and not self._manual_open:
            if not self.pill_rect().contains(QPointF(self.mapFromGlobal(QCursor.pos()))):
                self._schedule_collapse()

    def _tick_hw(self):
        if not (HAS_PSUTIL and psutil):
            return
        try:
            now = time.monotonic()
            if now - self._cpu_at >= 0.5:  # shorter windows give meaningless percentages
                self._cpu_at = now
                self._cpu_pct = psutil.cpu_percent(None)
                self.net.sample()
                self._probe_n += 1
                if self._probe_n % 3 == 1 and self.system.strip.show_ips and self.net.probe():
                    self.wan_ip = ""
                    self.wan_debounce.start()
            if not self.expanded:
                return  # nobody is looking at the gauges
            if self.system.strip.isVisibleTo(self.system):
                self.system.strip.update()

            shown = self.system.gauges
            if "cpu" in shown:
                self.system.set("cpu", self._cpu_pct, f"{self._threads} threads")
            if "ram" in shown:
                vm = psutil.virtual_memory()
                self.system.set("ram", vm.percent, f"{vm.used / 2**30:.1f} / {vm.total / 2**30:.0f} GB")
            if "gpu" in shown:
                g = gpu_stats()
                if g:
                    util, mem, temp = g
                    self.system.set("gpu", util, f"VRAM {mem}%" + (f" · {temp}°C" if temp else ""))
                else:
                    self.system.set("gpu", 0, "Not available")
            if "disk" in shown:
                du = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
                self.system.set("disk", du.percent, f"{du.free / 2**30:.0f} GB free")
            for mid, rate in (("net_down", self.net.down), ("net_up", self.net.up)):
                if mid in shown:
                    num, unit = fmt_rate(rate)
                    self.system.set(mid, rate / self.net.scale * 100, unit, num)
        except Exception:
            pass

    def _refresh_wan(self):
        if self._wan_busy or "ips" not in self.get_monitors():
            return
        self._wan_busy = True

        def work():
            ip = fetch_wan_ip()
            try:
                self.wan_ready.emit(ip)
            except RuntimeError:
                pass  # the app quit while the lookup was in flight
        threading.Thread(target=work, daemon=True).start()

    def _on_wan(self, ip):
        self._wan_busy = False
        self.wan_ip = ip
        self.system.strip.update()

    # ---------- app launcher ----------
    def reload_menu(self, announce=False):
        try:
            self.menu_groups = load_menu()
        except Exception as err:
            # Keep the previous menu; a half-saved or mistyped file must not empty it
            self.toast(f"menu.json: {err}"[:80], "close", M3.ERROR, 6)
        else:
            self.apps.rebuild()
            if announce:
                self.toast("Menu reloaded", "reload", M3.PRIMARY)
        # Editors that save by replacing the file drop it from the watch list
        if os.path.exists(MENU_FILE) and MENU_FILE not in self.menu_watch.files():
            self.menu_watch.addPath(MENU_FILE)

    def edit_menu(self):
        # Always Notepad, in its own window. The default .json handler is often an
        # editor that is already running (VS Code), which opens the file as a
        # background tab without coming forward - it looks like nothing happened.
        try:
            subprocess.Popen(["notepad.exe", MENU_FILE])
            self.toast("menu.json opened in Notepad  ·  save to apply", "note", M3.PRIMARY, 3)
        except OSError:
            os.startfile(MENU_FILE)

    def launch_item(self, item):
        try:
            launch_command(item["path"], item["admin"])
            self.toast(f"Opening {item['name']}", "bolt", M3.PRIMARY, 1.8)
        except Exception as err:
            self.toast(f"{item['name']}: {err}"[:80], "close", M3.ERROR, 5)

    def _read_clip(self):
        if not self.settings.get("clipboard_toast", True):
            return
        cb = QApplication.clipboard()
        try:
            md = cb.mimeData() if cb else None
            if md is None or not md.hasText():
                return
            t = cb.text()[:2000]
            if t and t != self.last_clip:
                self.last_clip = t
                self.tools.set_clip(t)
                self.toast("Copied · " + t.strip().replace("\n", " ")[:60], "copy", M3.PRIMARY)
        except Exception:
            pass

    # ---------- settings ----------
    def open_settings(self):
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(self)
        self.settings_dialog.sync_ui()
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def apply_setting(self, key, val):
        self.settings.set(key, val)
        if key == "idle_width":
            self.W_IDLE = int(val)
            if not self.expanded:
                self.sw.target = self.W_IDLE
        elif key == "top_offset":
            self.TOP = int(val)
            self._place()
        elif key == "exp_height":
            self.EXP_H = int(val)
            self.panel.setFixedSize(self.EXP_W, self.EXP_H)
            if self.expanded:
                self.sh.target = self.EXP_H
        elif key == "collapse_delay":
            self.leave_timer.setInterval(int(val))
        elif key == "always_on_top":
            flags = self.windowFlags()
            if val:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            else:
                flags &= ~Qt.WindowType.WindowStaysOnTopHint
            self.setWindowFlags(flags)
            self._desktop_level = not val
            self.show()
        elif key == "accent_color":
            col = QColor(val)
            M3.PRIMARY = col
            self.aura_color = col
            self.compact.toast_color = col
            self.update()
            for g in self.system.gauges.values():
                g.update()
        elif key == "start_on_boot":
            set_windows_autostart(bool(val))
        elif key == "wan_vpn_color":
            self.system.strip.update()
        self._frame()  # wake the frame loop so the change shows immediately

    def reset_settings(self):
        self.settings.reset()
        self.apply_setting("idle_width", self.settings.get("idle_width"))
        self.apply_setting("top_offset", self.settings.get("top_offset"))
        self.apply_setting("exp_height", self.settings.get("exp_height"))
        self.apply_setting("collapse_delay", self.settings.get("collapse_delay"))
        self.apply_setting("always_on_top", self.settings.get("always_on_top"))
        self.apply_setting("accent_color", self.settings.get("accent_color"))
        self.apply_setting("clipboard_toast", self.settings.get("clipboard_toast"))
        self.apply_setting("start_on_boot", self.settings.get("start_on_boot"))
        self.apply_setting("wan_vpn_color", self.settings.get("wan_vpn_color"))
        self.tools.rebuild_buttons()
        self._monitors_changed()

    # ---------- menus ----------
    def _menu_style(self, m):
        m.setStyleSheet(f"""
            QMenu {{ background: {M3.SURFACE_1.name()}; color: {M3.ON_SURFACE.name()};
                     border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 6px; }}
            QMenu::item {{ padding: 8px 20px; border-radius: 8px; font-family: '{FONT}'; font-size: 12px; }}
            QMenu::item:selected {{ background: {M3.SURFACE_3.name()}; }}
            QMenu::item:disabled {{ color: {M3.MUTED.name()}; }}
            QMenu::separator {{ height: 1px; background: rgba(255,255,255,0.08); margin: 4px 8px; }}
        """)

    def _expand_manual(self, page=None):
        """Expand from a menu: stays open until the mouse has visited the capsule."""
        self.expand()
        self._manual_open = True
        if page is not None:
            self.tabs.set_index(page)

    def _menu(self, pos):
        m = QMenu(self)
        self._menu_style(m)
        a_sett = m.addAction("⚙️  Settings...")
        m.addSeparator()
        a_pin = m.addAction("📌  Unpin" if self.pinned else "📌  Keep expanded")
        m.addSeparator()
        pages = [m.addAction(f"📄  {n}") for n in self.tabs.labels]
        m.addSeparator()
        apps = m.addMenu("🚀  Apps")
        self._menu_style(apps)
        app_acts = {}
        for g in self.menu_groups:
            sub = apps.addMenu(g["name"])
            self._menu_style(sub)
            for item in g["items"]:
                app_acts[sub.addAction(item["name"])] = item
        if self.menu_groups:
            apps.addSeparator()
        a_edit = apps.addAction("✏️  Edit menu file")
        a_reload = apps.addAction("🔄  Reload menu file")
        mon = m.addMenu("📊  Monitors")
        self._menu_style(mon)
        enabled = self.get_monitors()
        mon_acts = {}
        for mid in MONITOR_ORDER:
            title = MONITORS[mid][0]
            if mid in enabled:
                act = mon.addAction(f"✓  {title}")
            elif monitor_available(mid):
                act = mon.addAction(f"     {title}")
            else:
                act = mon.addAction(f"     {title}  (not on this PC)")
                act.setEnabled(False)
            mon_acts[act] = mid
        m.addSeparator()
        a_quit = m.addAction("🚪  Quit")
        a = m.exec(pos)
        m.deleteLater()
        if a == a_sett:
            self.open_settings()
        elif a == a_pin:
            self.pinned = not self.pinned
            if self.pinned:
                self.expand()
        elif a in pages:
            self._expand_manual(pages.index(a))
        elif a in app_acts:
            self.launch_item(app_acts[a])
        elif a == a_edit:
            self.edit_menu()
        elif a == a_reload:
            self.reload_menu(True)
        elif a in mon_acts:
            mid = mon_acts[a]
            self.set_monitor(mid, mid not in enabled)
            self._expand_manual(self.tabs.labels.index("System"))
        elif a == a_quit:
            self.quit_app()

    def _tray(self):
        try:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                return
            pm = QPixmap(64, 64)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QColor(0, 0, 0)); p.setPen(QPen(M3.PRIMARY, 3))
            p.drawRoundedRect(QRectF(4, 20, 56, 24), 12, 12)
            p.end()
            self.tray = QSystemTrayIcon(QIcon(pm), self)
            self.tray.setToolTip("Dynamic Capsule")
            m = QMenu()
            self._menu_style(m)
            m.addAction("⚙️  Settings...", self.open_settings)
            m.addSeparator()
            m.addAction("Expand", lambda: self._expand_manual())
            m.addAction("Collapse", self.collapse)
            m.addSeparator()
            m.addAction("Quit", self.quit_app)
            self._tray_menu = m
            self.tray.setContextMenu(m)
            self.tray.show()
        except Exception:
            pass

    def quit_app(self):
        """The one way out: stop every thread first, then leave the event loop.
        (Qt aborts the process if a QThread is still running when it is destroyed.)"""
        if self._quitting:
            return
        self._quitting = True
        self.frame.stop()
        Volume.worker = None
        self.audio_worker.stop()
        self.media_worker.stop()
        self.spectrum.stop()
        if self.settings_dialog is not None:
            self.settings_dialog.close()
        tray = getattr(self, "tray", None)
        if tray is not None:
            tray.hide()
        QApplication.quit()

    def closeEvent(self, e):
        self.quit_app()
        super().closeEvent(e)


_fault_log = None


def setup_crash_handler():
    global _fault_log
    log_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "DynamicIsland")
    log_file = os.path.join(log_dir, "crash.log")
    try:
        # Native crashes (access violations in Qt / COM) never reach sys.excepthook;
        # faulthandler writes their Python stack to the same log instead.
        os.makedirs(log_dir, exist_ok=True)
        _fault_log = open(log_file, "a", encoding="utf-8")
        faulthandler.enable(file=_fault_log)
    except Exception:
        pass

    def _hook(exctype, value, tb):
        import traceback
        try:
            os.makedirs(log_dir, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n==================== CRASH AT {time.strftime('%Y-%m-%d %H:%M:%S')} ====================\n")
                f.write(f"OS: {sys.platform} | Python: {sys.version}\n")
                traceback.print_exception(exctype, value, tb, file=f)
        except Exception:
            pass
        if sys.stderr is not None:  # None under pythonw.exe
            traceback.print_exception(exctype, value, tb)
    sys.excepthook = _hook


def main():
    setup_crash_handler()
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        try:
            ctypes.windll.ole32.CoInitialize(None)
        except Exception:
            pass

    # Read initial hardware master volume before building UI
    if PYCAW:
        try:
            dev = AudioUtilities.GetSpeakers()
            if dev and hasattr(dev, "EndpointVolume") and dev.EndpointVolume:
                Volume._cached_vol = int(round(dev.EndpointVolume.GetMasterVolumeLevelScalar() * 100))
                Volume._cached_mute = bool(dev.EndpointVolume.GetMute())
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setFont(font(12))

    try:
        w = DynamicCapsule()
        w.show()
    except Exception as err:
        # Started without a console (pythonw), a startup failure would otherwise be invisible
        sys.excepthook(type(err), err, err.__traceback__)
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                f"Dynamic Island could not start.\n\n{type(err).__name__}: {err}\n\n"
                "Details were saved to %APPDATA%\\DynamicIsland\\crash.log",
                "Dynamic Island",
                0x10
            )
        except Exception:
            pass
        sys.exit(1)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

