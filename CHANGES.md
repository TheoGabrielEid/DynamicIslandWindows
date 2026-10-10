# Changes since commit ea2a2df

These files replace the ones in your clone. Copy them over, run `git diff` to read
every change, then commit what you want to keep.

New packages are needed (they are in `requirements.txt`):

```
pip install -r requirements.txt
```

## Bugs fixed

| Problem | Cause | Fix |
|---|---|---|
| High CPU all the time, laggy on laptops | The frame timer repainted the translucent window 125 times a second even when nothing moved (54% of a core idle) | The frame loop now has four speeds and drops to idle when nothing is animating (about 2% idle) |
| Random freezes | The clipboard was read every 0.6 s; after a big copy (Excel) each read makes the source app render its data again | The clipboard is read only on Qt's `dataChanged` signal |
| Sudden closes with no error | The audio thread created new COM objects 12 times a second and released them after `CoUninitialize` | The audio endpoint is opened once, reused, and released before the thread leaves. Volume and mute are queued to that thread, so the UI thread never touches COM |
| Tray "Quit" left the process running; menu "Quit" could crash | `close()` did not quit the app, and `QApplication.quit()` ran with QThreads still alive | One `quit_app()` stops every thread first |
| App "closes immediately" from the .bat | `python` resolved to the Microsoft Store stub | The .bat tests each candidate (`py`, `python`, `python3`), installs missing packages and starts with `pythonw` |
| Bouncy open/close | Springs overshot (26% too tall) and the window mask was rebuilt every frame | One spring tuning for width and height, integrated in 4 ms sub-steps; the mask is gone (transparent pixels are already click-through) |
| Tools page rows overlapped | Six tiles plus "Add" need two rows, which did not fit | Tiles and the clipboard bar shrink slightly when there are two rows |
| Blank icons in Settings button list | The paint closure captured the loop variable `ic` | Bound per row |
| Mouse wheel skipped the last tab | Tab count was hard-coded to 4 | Uses `len(self.tabs.labels)` |
| Native crashes left no trace | `sys.excepthook` never sees access violations | `faulthandler` writes to the same `crash.log` |

## New features

- **Selectable monitors** (right-click → Monitors, or Settings): CPU, Memory, GPU, Disk,
  Download, Upload, Battery, Traffic graph, LAN / WAN IP. Defaults are whatever the PC has.
  See `MONITORS`, `SystemPage`, `NetMeter`.
- **Network strip** under the gauges: upload / download speed, a 60-second histogram
  each, LAN and WAN address. WAN is green while a VPN holds the default route and red
  otherwise (`NetMeter.probe`). The WAN lookup calls `api.ipify.org` and only runs while
  the IP readout is switched on (it is off by default).
- **Apps tab**: a launcher read from `%APPDATA%\DynamicIsland\menu.json`, hot-reloaded
  on save. See `load_menu`, `launch_command`, `AppsPage`.
- **Now playing**: real title, artist and cover art from the Windows media session
  (`MediaInfoWorker`, needs the `winrt-*` packages). Play / next / previous go to that
  session.
- **Real spectrum analyser**: loopback capture of the output device plus an FFT
  (`SpectrumWorker`, needs `numpy` and `soundcard`). Without them the old animated bars
  are used.
- **Desktop level**: with "Always on top" off (now the default) the window is pinned to
  the bottom of the z-order, so other windows cover it (`nativeEvent`, `_apply_layer`).
- **Collapse delay** defaults to 1 second; the slider goes to 3 seconds.

## Removed

- The **AI Assistant** (tab, tile, settings section, `AIPage`, `AIServiceWorker`,
  `AICache`) was removed on request. It is still in your git history at ea2a2df if you
  want it back; the main thing to restore with it is `_hold_open`, which kept the capsule
  open while typing.

## Things to know

- All optional parts fail soft: without `winrt`, `soundcard`, `pycaw` or an NVIDIA GPU
  the matching feature falls back or hides instead of crashing.
- Settings saved by older versions keep working. An old `always_on_top: true` is kept,
  so existing users stay on top until they untick it.
- Tested on Windows 11, Python 3.14, PyQt6 6.11, one laptop. Not tested on a desktop PC
  with an NVIDIA GPU or with several monitors.
