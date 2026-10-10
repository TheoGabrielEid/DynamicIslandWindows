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

import psutil

warnings.filterwarnings("ignore", category=FutureWarning)

from PyQt6.QtCore import Qt, QTimer, QTime, QRectF, QPointF, QRect, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QAbstractButton, QSlider, QStackedWidget, QSystemTrayIcon, QMenu,
    QGraphicsOpacityEffect
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QPainterPath, QLinearGradient,
    QRadialGradient, QIcon, QCursor, QRegion, QPixmap
)

try:
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume, IAudioMeterInformation
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    PYCAW = True
except Exception:
    PYCAW = False

try:
    import pynvml
    pynvml.nvmlInit()
    NVML = True
except Exception:
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
    f.setPixelSize(size)
    f.setWeight(weight)
    return f


# ───────────────────────── System services ─────────────────────────
class Volume:
    _cached_vol = 50
    _cached_mute = False

    @staticmethod
    def _dev():
        if not PYCAW:
            return None
        try:
            return AudioUtilities.GetSpeakers()
        except Exception:
            return None

    @classmethod
    def get(cls):
        return cls._cached_vol

    @classmethod
    def is_muted(cls):
        return cls._cached_mute

    @classmethod
    def set(cls, pct):
        cls._cached_vol = int(max(0, min(100, pct)))
        if not PYCAW:
            return
        try:
            dev = cls._dev()
            if dev and hasattr(dev, "EndpointVolume") and dev.EndpointVolume:
                dev.EndpointVolume.SetMasterVolumeLevelScalar(cls._cached_vol / 100.0, None)
        except Exception:
            pass

    @classmethod
    def toggle_mute(cls):
        if not PYCAW:
            cls._cached_mute = not cls._cached_mute
            return cls._cached_mute
        try:
            dev = cls._dev()
            if dev and hasattr(dev, "EndpointVolume") and dev.EndpointVolume:
                ev = dev.EndpointVolume
                m = not ev.GetMute()
                ev.SetMute(m, None)
                cls._cached_mute = m
                return m
        except Exception:
            pass
        cls._cached_mute = not cls._cached_mute
        return cls._cached_mute


class AudioWorker(QThread):
    """Background worker that queries Windows COM audio without blocking the UI loop."""
    audio_updated = pyqtSignal(bool, float, str, int, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True

    def stop(self):
        self._running = False
        self.wait(400)

    def run(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pythoncom = None

        hits = 0
        last_sound = 0.0
        playing = False
        app_name = ""

        while self._running:
            peak = 0.0
            cur_app = ""
            vol_val = Volume._cached_vol
            is_muted = Volume._cached_mute

            if PYCAW:
                try:
                    dev = None
                    try:
                        dev = AudioUtilities.GetSpeakers()
                    except Exception:
                        dev = None

                    if dev:
                        if hasattr(dev, "EndpointVolume") and dev.EndpointVolume:
                            try:
                                ev = dev.EndpointVolume
                                vol_val = int(round(ev.GetMasterVolumeLevelScalar() * 100))
                                is_muted = bool(ev.GetMute())
                                Volume._cached_vol = vol_val
                                Volume._cached_mute = is_muted
                            except Exception:
                                pass

                        # Check master endpoint meter first
                        if hasattr(dev, "_dev") and dev._dev:
                            try:
                                meter_itf = dev._dev.Activate(IAudioMeterInformation._iid_, CLSCTX_ALL, None)
                                meter = cast(meter_itf, POINTER(IAudioMeterInformation))
                                peak = float(meter.GetPeakValue())
                            except Exception:
                                pass

                        # If audio is playing or to identify active session
                        if hasattr(dev, "AudioSessionManager") and dev.AudioSessionManager:
                            try:
                                mgr = dev.AudioSessionManager
                                sessions = mgr.GetSessionEnumerator()
                                count = sessions.GetCount() if hasattr(sessions, "GetCount") else 0
                                for i in range(count):
                                    try:
                                        s = sessions.GetSession(i)
                                        s_meter = s.QueryInterface(IAudioMeterInformation)
                                        sp = float(s_meter.GetPeakValue())
                                        if sp > 0.01:
                                            if sp > peak:
                                                peak = sp
                                            try:
                                                from pycaw.pycaw import IAudioSessionControl2
                                                ctl2 = s.QueryInterface(IAudioSessionControl2)
                                                pid = ctl2.GetProcessId()
                                                if pid:
                                                    cur_app = psutil.Process(pid).name().replace(".exe", "").capitalize()
                                            except Exception:
                                                pass
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                except Exception:
                    pass

            now = time.monotonic()
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
                    app_name = ""

            try:
                self.audio_updated.emit(playing, peak, app_name, vol_val, is_muted)
            except Exception:
                pass
            time.sleep(0.08)

        if pythoncom:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def gpu_stats():
    if not NVML:
        return None
    try:
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
        import win32api, win32con
        win32api.keybd_event(vk, 0, 0, 0)
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    except Exception:
        pass

VK_NEXT, VK_PREV, VK_PLAY = 0xB0, 0xB1, 0xB3


# ───────────────────────── Spring physics ─────────────────────────
class Spring:
    def __init__(self, value, stiffness=300.0, damping_ratio=0.74):
        self.x = self.target = float(value)
        self.v = 0.0
        self.k = stiffness
        self.c = 2 * damping_ratio * math.sqrt(stiffness)

    def step(self, dt):
        a = self.k * (self.target - self.x) - self.c * self.v
        self.v += a * dt
        self.x += self.v * dt
        if abs(self.target - self.x) < 0.05 and abs(self.v) < 0.05:
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
        p.drawEllipse(R(0.36, 0.36, 0.28, 0.28)); p.drawEllipse(R(0.16, 0.16, 0.68, 0.68))
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
    def __init__(self, icon, label, accent=M3.PRIMARY, parent=None):
        super().__init__(parent)
        self.icon_name, self.label, self.accent = icon, label, accent
        self.active = False
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
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(M3.PRIMARY_CONT if self.active else M3.SURFACE_2)
        p.drawRoundedRect(r, 20, 20)
        if self._hover:
            p.setBrush(QColor(255, 255, 255, 18))
            p.drawRoundedRect(r, 20, 20)
        draw_icon(p, self.icon_name, QRectF(r.center().x() - 10, r.y() + 12, 20, 20),
                  M3.PRIMARY if self.active else self.accent)
        p.setPen(M3.ON_SURFACE)
        p.setFont(font(11, QFont.Weight.DemiBold))
        p.drawText(QRectF(r.x(), r.y() + 38, r.width(), 16), Qt.AlignmentFlag.AlignCenter, self.label)


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
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text_)


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
        self.changed.emit(i)

    def tick(self, dt):
        if self.ind.step(dt):
            self.update()

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
    """Circular M3 gauge with eased value."""
    def __init__(self, icon, label, color, parent=None):
        super().__init__(parent)
        self.icon_name, self.label, self.color = icon, label, color
        self.value = Spring(0, stiffness=120, damping_ratio=1.0)
        self.sub = ""
        self.setFixedSize(96, 118)

    def set_value(self, v, sub=""):
        self.value.target = max(0, min(100, v))
        self.sub = sub

    def tick(self, dt):
        if self.value.step(dt):
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = 76
        rr = QRectF((self.width() - d) / 2, 4, d, d)
        p.setPen(QPen(M3.SURFACE_2, 7, cap=Qt.PenCapStyle.RoundCap))
        p.drawArc(rr, 0, 360 * 16)
        span = int(-self.value.x / 100 * 360 * 16)
        if span:
            p.setPen(QPen(self.color, 7, cap=Qt.PenCapStyle.RoundCap))
            p.drawArc(rr, 90 * 16, span)
        draw_icon(p, self.icon_name, QRectF(rr.center().x() - 8, rr.y() + 17, 16, 16), self.color, 1.6)
        p.setPen(M3.ON_SURFACE)
        p.setFont(font(15, QFont.Weight.Bold))
        p.drawText(QRectF(rr.x(), rr.y() + 36, d, 22), Qt.AlignmentFlag.AlignCenter, f"{int(round(self.value.x))}%")
        p.setPen(M3.ON_SURFACE_VAR)
        p.setFont(font(11, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, 86, self.width(), 16), Qt.AlignmentFlag.AlignCenter, self.label)
        if self.sub:
            p.setPen(M3.MUTED)
            p.setFont(font(10))
            p.drawText(QRectF(0, 101, self.width(), 14), Qt.AlignmentFlag.AlignCenter, self.sub)


class AlbumArt(QWidget):
    """Animated gradient artwork with rotating sheen while playing."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(64, 64)
        self.phase = 0.0
        self.playing = False

    def tick(self, dt):
        if self.playing:
            self.phase += dt * 0.8
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
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
    """Material Capsule style bouncing bars with fluid organic harmonics and peak reaction."""
    def __init__(self, bars=28, parent=None):
        super().__init__(parent)
        self.n = bars
        self.levels = [0.1] * bars
        self.targets = [0.1] * bars
        self.energy = 0.0
        self.active = False
        self.phase = 0.0
        self.setFixedHeight(30)

    def tick(self, dt):
        self.phase += dt * 5.0
        for i in range(self.n):
            if self.active:
                # Harmonic wave pattern modulated by real sound peak
                harmonic = 0.35 * math.sin(self.phase + i * 0.45) + 0.25 * math.sin(self.phase * 1.6 - i * 0.3)
                base = 0.18 + max(0.0, harmonic) * (0.3 + self.energy * 0.9)
                if random.random() < 0.25:
                    jitter = random.random() * (0.2 + self.energy * 0.5)
                    self.targets[i] = min(1.0, base + jitter)
                else:
                    self.targets[i] = max(0.1, min(1.0, base))
            else:
                self.targets[i] = 0.08
            self.levels[i] += (self.targets[i] - self.levels[i]) * min(1.0, dt * 18.0)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        w, h = float(self.width()), float(self.height())
        gap = 4.0
        bw = max(2.5, (w - gap * (self.n - 1)) / self.n)
        
        g = QLinearGradient(0, 0, w, 0)
        g.setColorAt(0, M3.PRIMARY)
        g.setColorAt(0.5, M3.TERTIARY)
        g.setColorAt(1, M3.PRIMARY)
        p.setBrush(g if self.active else M3.SURFACE_3)
        
        for i, lv in enumerate(self.levels):
            bh = max(4.0, lv * (h - 2.0))
            x_pos = i * (bw + gap)
            y_pos = (h - bh) / 2.0
            p.drawRoundedRect(QRectF(x_pos, y_pos, bw, bh), bw / 2.0, bw / 2.0)



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
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMouseTracking(True)
        self._hover_center = False

    def tick(self, dt):
        for i in range(4):
            if self.playing and random.random() < 0.35:
                self.bar_t[i] = 0.2 + random.random() * min(0.8, 0.25 + self.energy * 2.2)
            elif not self.playing:
                self.bar_t[i] = 0.2
            self.bars[i] += (self.bar_t[i] - self.bars[i]) * min(1.0, dt * 16.0)
        self.update()

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
        if e.button() != Qt.MouseButton.LeftButton:
            return e.ignore()
        pos = e.position()
        if self.playing and self.badge_rect().adjusted(-4, -4, 4, 4).contains(pos):
            self.play_clicked.emit()
        elif not self.toast_text and self.pause_btn_rect().adjusted(-6, -6, 6, 6).contains(pos):
            self.clock_pause_clicked.emit()
        else:
            self.expand_clicked.emit()

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
        self.title = label("Nothing playing", 16, M3.ON_SURFACE, QFont.Weight.Bold)
        self.sub = label("Play something to see it here", 12, M3.MUTED)
        info.addWidget(self.title)
        info.addWidget(self.sub)
        info.addStretch()
        top.addLayout(info, 1)

        ctrls = QHBoxLayout()
        ctrls.setSpacing(8)
        self.btn_prev = IconButton("prev", 38, 15)
        self.btn_play = IconButton("play", 46, 18, filled=True)
        self.btn_next = IconButton("next", 38, 15)
        self.btn_prev.clicked.connect(lambda: media_key(VK_PREV))
        self.btn_play.clicked.connect(island.toggle_play)
        self.btn_next.clicked.connect(lambda: media_key(VK_NEXT))
        for b in (self.btn_prev, self.btn_play, self.btn_next):
            ctrls.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addLayout(ctrls)
        root.addLayout(top)

        self.wave = Waveform(30)
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
        self.art.tick(dt)
        self.wave.tick(dt)


class SystemPage(QWidget):
    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 0)
        lay.setSpacing(0)
        self.cpu = RingGauge("cpu", "CPU", M3.PRIMARY)
        self.ram = RingGauge("ram", "Memory", M3.GREEN)
        self.gpu = RingGauge("gpu", "GPU", M3.NVIDIA)
        self.bat = RingGauge("battery", "Battery", M3.ORANGE)
        for g in (self.cpu, self.ram, self.gpu, self.bat):
            lay.addStretch()
            lay.addWidget(g, 0, Qt.AlignmentFlag.AlignTop)
        lay.addStretch()

    def tick(self, dt):
        for g in (self.cpu, self.ram, self.gpu, self.bat):
            g.tick(dt)


class ToolsPage(QWidget):
    def __init__(self, island):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.t_snip = TileButton("snip", "Screenshot")
        self.t_mute = TileButton("mute", "Mute")
        self.t_lock = TileButton("lock", "Lock")
        self.t_task = TileButton("pulse", "Task Manager")
        self.t_snip.clicked.connect(island.snip)
        self.t_mute.clicked.connect(island.toggle_mute)
        self.t_lock.clicked.connect(island.lock)
        self.t_task.clicked.connect(lambda: subprocess.Popen(["taskmgr"]))
        for i, t in enumerate((self.t_snip, self.t_mute, self.t_lock, self.t_task)):
            grid.addWidget(t, 0, i)
        root.addLayout(grid)

        clip = QWidget()
        clip.setFixedHeight(48)
        clip.setStyleSheet(f"background: {M3.SURFACE_1.name()}; border-radius: 16px;")
        cl = QHBoxLayout(clip)
        cl.setContentsMargins(14, 0, 14, 0)
        cl.setSpacing(10)
        head = label("CLIPBOARD", 10, M3.PRIMARY, QFont.Weight.Bold)
        cl.addWidget(head)
        self.clip_text = label("Nothing copied yet", 12, M3.ON_SURFACE)
        cl.addWidget(self.clip_text, 1)
        root.addWidget(clip)
        root.addStretch()

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


# ───────────────────────── The capsule window ─────────────────────────
class DynamicCapsule(QWidget):
    WIN_W, WIN_H = 600, 320          # fixed transparent canvas
    TOP = 8
    COMPACT_H = 40
    W_IDLE, W_MEDIA, W_TOAST = 196, 236, 320
    EXP_W, EXP_H = 540, 268
    PAD = 18

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(self.WIN_W, self.WIN_H)

        # High-performance snappy springs (stiffness 950, damping 0.76 for instant responsive spring)
        self.sw = Spring(self.W_IDLE, 950, 0.76)
        self.sh = Spring(self.COMPACT_H, 1050, 0.78)
        self.expanded = False
        self.pinned = False
        self.aura = 0.0
        self.aura_color = M3.PRIMARY
        self.audio_playing = False
        self.audio_peak = 0.0
        self.audio_app = ""
        self.focus_left = 0
        self.focus_total = 0
        self.focus_paused = False
        self.clock_frozen_time = None
        self.toast_until = 0.0
        self.last_clip = QApplication.clipboard().text()

        self._build()
        self._place()

        self.setMouseTracking(True)
        self.content.setMouseTracking(True)
        self.compact.setMouseTracking(True)
        self.panel.setMouseTracking(True)
        self.leave_timer = QTimer(self, singleShot=True, interval=180, timeout=self.collapse)

        # Background Audio Worker thread (zero main thread blocking!)
        self.audio_worker = AudioWorker(self)
        self.audio_worker.audio_updated.connect(self._on_audio_worker_update)
        self.audio_worker.start()

        self._t = time.perf_counter()
        self.frame = QTimer(self, timerType=Qt.TimerType.PreciseTimer, interval=8, timeout=self._frame)
        self.frame.start()
        QTimer(self, interval=1000, timeout=self._tick_1s).start()
        QTimer(self, interval=1200, timeout=self._tick_hw).start()
        QTimer(self, interval=600, timeout=self._tick_clip).start()
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
        self.tabs = SegmentedTabs(["Media", "System", "Tools", "Focus"])
        self.tabs.setFixedWidth(300)
        header.addWidget(self.tabs, 0, Qt.AlignmentFlag.AlignVCenter)
        pl.addLayout(header)

        self.stack = QStackedWidget()
        self.media = MediaPage(self)
        self.system = SystemPage()
        self.tools = ToolsPage(self)
        self.focus = FocusPage(self)
        for pg in (self.media, self.system, self.tools, self.focus):
            self.stack.addWidget(pg)
        self.tabs.changed.connect(self.stack.setCurrentIndex)
        pl.addWidget(self.stack, 1)

    def _place(self):
        screen = QApplication.primaryScreen()
        if screen:
            scr = screen.geometry()
            self.move(scr.x() + (scr.width() - self.WIN_W) // 2, scr.y())
        else:
            self.move((1920 - self.WIN_W) // 2, 0)

    # ---------- geometry ----------
    def pill_rect(self):
        w, h = self.sw.x, self.sh.x
        return QRectF((self.WIN_W - w) / 2, self.TOP, w, h)

    def _frame(self):
        now = time.perf_counter()
        dt = min(0.033, now - self._t)
        self._t = now
        moving = self.sw.step(dt) | self.sh.step(dt)

        if self.toast_until and now > self.toast_until:
            self.toast_until = 0
            self.compact.toast_text = ""
            self._update_compact_target()

        if self.aura > 0:
            self.aura = max(0.0, self.aura - dt * 1.4)

        r = self.pill_rect()
        rect = r.toRect()
        self.content.setGeometry(rect)
        self.compact.setGeometry(0, 0, rect.width(), self.COMPACT_H)
        self.panel.move(int((rect.width() - self.EXP_W) / 2), 0)

        prog = max(0.0, min(1.0, (self.sh.x - self.COMPACT_H) / (self.EXP_H - self.COMPACT_H)))
        self.compact_fx.setOpacity(max(0.0, 1 - prog * 3))
        self.panel_fx.setOpacity(max(0.0, (prog - 0.35) / 0.65))
        self.compact.setVisible(prog < 0.34)
        self.panel.setVisible(prog > 0.3)

        # Only update geometry, mask, and repaint when moving or aura changes
        if moving or (self.aura > 0) or (prog > 0.01 and prog < 0.99):
            path = QPainterPath()
            rad = min(r.height() / 2, 32)
            path.addRoundedRect(r.adjusted(-1.5, -1.5, 1.5, 1.5), rad, rad)
            self.setMask(QRegion(path.toFillPolygon().toPolygon()))
            self.update()

        self.compact.tick(dt)
        self.tabs.tick(dt)
        if self.expanded:
            self.media.tick(dt)
            self.system.tick(dt)
            self.focus.ring.tick(dt)

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
        self._frame()

    def collapse(self):
        if not self.expanded or self.pinned:
            return
        self.expanded = False
        self._update_compact_target()
        self._frame()

    def toast(self, text, icon, color, secs=2.6):
        self.compact.toast_text, self.compact.toast_icon, self.compact.toast_color = text, icon, color
        self.toast_until = time.perf_counter() + secs
        self.aura, self.aura_color = 1.0, color
        self._update_compact_target()

    def enterEvent(self, e):
        self.leave_timer.stop()
        if not self.expanded:
            self.expand()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self.expanded and not self.pinned:
            self.leave_timer.start()
        super().leaveEvent(e)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self.pill_rect().contains(pos):
            self.leave_timer.stop()
            if not self.expanded:
                self.expand()
        else:
            if self.expanded and not self.pinned and not self.leave_timer.isActive():
                self.leave_timer.start()
        super().mouseMoveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self._menu(e.globalPosition().toPoint())

    def wheelEvent(self, e):
        if self.expanded:
            n = 4
            self.tabs.set_index((self.tabs.index + (-1 if e.angleDelta().y() > 0 else 1)) % n)

    # ---------- actions ----------
    def toggle_play(self):
        media_key(VK_PLAY)
        self.aura, self.aura_color = 0.8, M3.PRIMARY

    def toggle_mute(self):
        m = Volume.toggle_mute()
        self.media.vol_icon.set_icon("mute" if m else "speaker")
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
        if secs:
            self.toast(f"Focus · {secs // 60} min", "timer", M3.TERTIARY)
        self._update_compact_target()

    @staticmethod
    def _fmt(s):
        return f"{s // 60:02d}:{s % 60:02d}"

    # ---------- monitors ----------
    def _on_audio_worker_update(self, playing, peak, app_name, vol_val, is_muted):
        was = self.audio_playing
        self.audio_playing = playing
        self.audio_peak = peak
        self.audio_app = app_name

        self.compact.playing = playing
        self.compact.energy = peak
        self.media.wave.active = playing
        self.media.wave.energy = peak
        self.media.art.playing = playing
        self.media.btn_play.set_icon("pause" if playing else "play")
        self.media.vol_icon.set_icon("mute" if is_muted else "speaker")
        self.tools.t_mute.active = is_muted
        self.tools.t_mute.update()

        if playing:
            self.media.title.setText(app_name or "Now playing")
            self.media.sub.setText("Playing on this PC")
        else:
            self.media.title.setText("Nothing playing")
            self.media.sub.setText("Play something to see it here")

        if not self.media.slider.isSliderDown() and vol_val != self.media.slider.value():
            self.media.slider.blockSignals(True)
            self.media.slider.setValue(vol_val)
            self.media.slider.blockSignals(False)
            self.media.vol_lbl.setText(f"{vol_val}%")

        if was != playing:
            self._update_compact_target()

    def _tick_1s(self):
        now = QTime.currentTime()
        self.h_time.setText(now.toString("HH:mm"))
        from PyQt6.QtCore import QDate
        self.h_date.setText(QDate.currentDate().toString("dddd, d MMMM"))

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
            self.compact.time_text = self._fmt(self.focus_left)
        else:
            if self.clock_frozen_time is not None:
                self.compact.time_text = self.clock_frozen_time
            else:
                self.compact.time_text = now.toString("HH:mm")

        try:
            b = psutil.sensors_battery()
        except Exception:
            b = None
        if b:
            self.compact.battery, self.compact.charging = int(b.percent), bool(b.power_plugged)
            self.system.bat.set_value(b.percent, "Charging" if b.power_plugged else "On battery")
        else:
            self.compact.battery = None
            self.system.bat.set_value(100, "AC power")

    def _tick_hw(self):
        try:
            self.system.cpu.set_value(psutil.cpu_percent(None), f"{psutil.cpu_count()} threads")
            vm = psutil.virtual_memory()
            self.system.ram.set_value(vm.percent, f"{vm.used / 2**30:.1f} / {vm.total / 2**30:.0f} GB")
            g = gpu_stats()
            if g:
                util, mem, temp = g
                self.system.gpu.set_value(util, f"VRAM {mem}%" + (f" · {temp}°C" if temp else ""))
            else:
                self.system.gpu.set_value(0, "Not available")
        except Exception:
            pass

    def _tick_clip(self):
        t = QApplication.clipboard().text()
        if t and t != self.last_clip:
            self.last_clip = t
            self.tools.set_clip(t)
            self.toast("Copied · " + t.strip().replace("\n", " ")[:60], "copy", M3.PRIMARY)

    # ---------- menus ----------
    def _menu_style(self, m):
        m.setStyleSheet(f"""
            QMenu {{ background: {M3.SURFACE_1.name()}; color: {M3.ON_SURFACE.name()};
                     border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 6px; }}
            QMenu::item {{ padding: 8px 20px; border-radius: 8px; font-family: '{FONT}'; font-size: 12px; }}
            QMenu::item:selected {{ background: {M3.SURFACE_3.name()}; }}
            QMenu::separator {{ height: 1px; background: rgba(255,255,255,0.08); margin: 4px 8px; }}
        """)

    def _menu(self, pos):
        m = QMenu(self)
        self._menu_style(m)
        a_pin = m.addAction("Unpin" if self.pinned else "Keep expanded")
        m.addSeparator()
        pages = [m.addAction(n) for n in ("Media", "System", "Tools", "Focus")]
        m.addSeparator()
        a_quit = m.addAction("Quit")
        a = m.exec(pos)
        if a == a_pin:
            self.pinned = not self.pinned
            if self.pinned:
                self.expand()
        elif a in pages:
            self.expand(); self.tabs.set_index(pages.index(a))
        elif a == a_quit:
            QApplication.quit()

    def _tray(self):
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
        m.addAction("Expand", self.expand)
        m.addAction("Collapse", self.collapse)
        m.addSeparator()
        m.addAction("Quit", self.close)
        self.tray.setContextMenu(m)
        self.tray.show()

    def closeEvent(self, e):
        if hasattr(self, "audio_worker"):
            self.audio_worker.stop()
        super().closeEvent(e)


def main():
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass

    # Read initial hardware master volume before building UI
    if PYCAW:
        try:
            dev = AudioUtilities.GetSpeakers()
            if dev and hasattr(dev, "EndpointVolume"):
                Volume._cached_vol = int(round(dev.EndpointVolume.GetMasterVolumeLevelScalar() * 100))
                Volume._cached_mute = bool(dev.EndpointVolume.GetMute())
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setFont(font(12))
    w = DynamicCapsule()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
