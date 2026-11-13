"""Full-screen, frameless, always-on-top, click-through overlay (PyQt6).

Modes:
  hidden  window not shown
  blur    heavy Gaussian blur of the captured frame, drawn over the screen
  block   black screen with a message

On Windows the window is excluded from screen capture
(SetWindowDisplayAffinity WDA_EXCLUDEFROMCAPTURE, Windows 10 2004+), so the
detector keeps seeing the real screen instead of its own overlay.

Also provides GlobalHotkey (Windows RegisterHotKey), which works while the
overlay is up because it does not need keyboard focus.

Demo / capture-exclusion check (shows the overlay for a few seconds):
    python prototype/overlay.py --mode block --seconds 2 --check-capture
"""

import argparse
import ctypes
import sys
from ctypes import wintypes

from PIL import Image, ImageFilter
from PyQt6.QtCore import QAbstractNativeEventFilter, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QImage, QPainter
from PyQt6.QtWidgets import QApplication, QWidget

MODES = ("hidden", "blur", "block")
IS_WINDOWS = sys.platform == "win32"
WDA_EXCLUDEFROMCAPTURE = 0x11
WM_HOTKEY = 0x0312
MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x0002, 0x0004, 0x4000


def make_blur(img: Image.Image, radius: float = 12, width: int = 320) -> Image.Image:
    """Heavy blur: shrink to `width` px, blur, and let the overlay scale it back up."""
    small = img.convert("RGB")
    small = small.resize((width, max(1, round(img.height * width / img.width))), Image.BILINEAR)
    return small.filter(ImageFilter.GaussianBlur(radius))


def pil_to_qimage(img: Image.Image) -> QImage:
    img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    return QImage(data, img.width, img.height, 3 * img.width, QImage.Format.Format_RGB888).copy()


class Overlay(QWidget):
    def __init__(self, block_text: str):
        super().__init__()
        self.block_text = block_text
        self.mode = "hidden"
        self._image: QImage | None = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # no taskbar entry
            | Qt.WindowType.WindowTransparentForInput  # click-through
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setGeometry(QApplication.primaryScreen().geometry())
        self.excluded_from_capture = self._exclude_from_capture()

    def _exclude_from_capture(self) -> bool:
        if not IS_WINDOWS:
            return False
        hwnd = int(self.winId())
        return bool(ctypes.windll.user32.SetWindowDisplayAffinity(wintypes.HWND(hwnd), WDA_EXCLUDEFROMCAPTURE))

    def set_mode(self, mode: str, blurred: Image.Image | None = None) -> None:
        if mode not in MODES:
            raise ValueError(mode)
        if blurred is not None:
            self._image = pil_to_qimage(blurred)
        self.mode = mode
        if mode == "hidden":
            self.hide()
            return
        if not self.isVisible():
            self.show()
            self.raise_()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt name)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.mode == "blur" and self._image is not None:
            p.drawImage(self.rect(), self._image)
        else:  # block (or blur before the first frame arrives)
            p.fillRect(self.rect(), QColor("black"))
            if self.mode == "block":
                p.setPen(QColor("white"))
                p.setFont(QFont("Segoe UI", 36, QFont.Weight.Bold))
                p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.block_text)
        p.end()


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, hotkey_id: int, callback):
        super().__init__()
        self.hotkey_id = hotkey_id
        self.callback = callback

    def nativeEventFilter(self, event_type, message):  # noqa: N802 (Qt name)
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                self.callback()
                return True, 0
        return False, 0


class GlobalHotkey:
    """System-wide Ctrl+Shift+<key> on Windows. Call from the Qt (GUI) thread."""

    def __init__(self, app: QApplication, callback, key: str = "Q", hotkey_id: int = 0xB0B):
        self.app, self.hotkey_id, self.registered = app, hotkey_id, False
        if not IS_WINDOWS:
            return
        mods = MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT
        self.registered = bool(ctypes.windll.user32.RegisterHotKey(None, hotkey_id, mods, ord(key.upper())))
        self._filter = _HotkeyFilter(hotkey_id, callback)
        app.installNativeEventFilter(self._filter)

    def close(self) -> None:
        if self.registered:
            ctypes.windll.user32.UnregisterHotKey(None, self.hotkey_id)
            self.registered = False


def _mean_abs_diff(a: Image.Image, b: Image.Image) -> float:
    import numpy as np

    a = np.asarray(a.convert("L").resize((320, 180)), dtype=np.float32)
    b = np.asarray(b.convert("L").resize((320, 180)), dtype=np.float32)
    return float(np.abs(a - b).mean())


def main() -> None:
    ap = argparse.ArgumentParser(description="Show the overlay briefly (demo / capture-exclusion check).")
    ap.add_argument("--mode", choices=("blur", "block"), default="block")
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--text", default="Tokhiromjgui kontent ilerlee")
    ap.add_argument("--check-capture", action="store_true",
                    help="grab the screen with mss while the overlay is up and report whether it was captured")
    args = ap.parse_args()

    from capture import ScreenCapture

    app = QApplication(sys.argv)
    cap = ScreenCapture()
    before = cap.grab()
    ov = Overlay(args.text)
    print(f"excluded from capture (SetWindowDisplayAffinity): {ov.excluded_from_capture}")
    ov.set_mode(args.mode, make_blur(before) if args.mode == "blur" else None)
    result = {}

    def check():
        import numpy as np

        during = cap.grab()
        result["diff"] = _mean_abs_diff(before, during)
        result["dark"] = float(np.asarray(during.convert("L"), dtype=np.float32).mean())

    if args.check_capture:
        QTimer.singleShot(int(args.seconds * 500), check)
    QTimer.singleShot(int(args.seconds * 1000), app.quit)
    app.exec()
    ov.close()
    cap.close()
    if args.check_capture:
        seen = result["diff"] > 25 if args.mode == "block" else result["diff"] > 15
        print(f"capture during overlay: mean abs diff vs before = {result['diff']:.1f}, "
              f"mean brightness = {result['dark']:.0f}/255")
        print(f"Summary: overlay shown {args.seconds:.1f}s in {args.mode} mode; "
              f"overlay {'APPEARS' if seen else 'does NOT appear'} in screen capture")


if __name__ == "__main__":
    main()
