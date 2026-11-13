"""KidGuard Phase 1 desktop prototype: capture -> detect -> decide -> overlay.

Run:
    python prototype/main.py                    # until Ctrl+Shift+Q (or Ctrl+C)
    python prototype/main.py --max-seconds 30   # stop by itself

Decision rules (thresholds in config.yaml):
  - a frame is unsafe if max(nudity, violence, gore) >= blur_threshold
  - act only when >= trigger_count of the last `window` analysed frames are unsafe
  - action: block if those unsafe frames average > block_threshold, else blur
    (while active it can escalate blur -> block, never the other way)
  - clear after clear_count safe frames in a row
Every analysed frame is logged to reports/prototype_log.csv.
"""

import argparse
import csv
import signal
import sys
import time
from collections import Counter, deque
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication

from capture import ScreenCapture
from detector import BACKENDS, DEFAULT_CONFIG, UNSAFE, Detector, load_config, top_class
from overlay import IS_WINDOWS, GlobalHotkey, Overlay, make_blur

LEVEL = {"hidden": 0, "blur": 1, "block": 2}


class Decider:
    """Sliding-window decision with hysteresis. Pure logic, no Qt."""

    def __init__(self, blur_threshold=0.5, block_threshold=0.8, window=5, trigger_count=3, clear_count=3):
        self.blur_t, self.block_t = blur_threshold, block_threshold
        self.trigger, self.clear = trigger_count, clear_count
        self.window: deque[float | None] = deque(maxlen=window)  # unsafe prob, or None if safe
        self.safe_streak = 0
        self.action = "hidden"

    def update(self, probs: dict) -> str:
        m = max(probs[c] for c in UNSAFE)
        unsafe = m >= self.blur_t
        self.window.append(m if unsafe else None)
        self.safe_streak = 0 if unsafe else self.safe_streak + 1

        hits = [v for v in self.window if v is not None]
        level = "block" if hits and sum(hits) / len(hits) > self.block_t else "blur"
        if self.action == "hidden":
            if len(hits) >= self.trigger:
                self.action = level
        elif self.safe_streak >= self.clear:
            self.action = "hidden"
        elif hits and LEVEL[level] > LEVEL[self.action]:
            self.action = level  # escalate only
        return self.action


class Worker(QObject):
    decided = pyqtSignal(str, object)  # action, blurred PIL image (or None)
    finished = pyqtSignal()

    def __init__(self, cfg: dict, backend: str | None, max_seconds: float | None):
        super().__init__()
        self.cfg, self.backend, self.max_seconds = cfg, backend, max_seconds
        self.running = True
        self.actions: Counter[str] = Counter()
        self.activations = 0
        self.capture: ScreenCapture | None = None
        self.detector: Detector | None = None
        self.error: str | None = None

    def stop(self) -> None:
        self.running = False

    def run(self) -> None:
        try:
            self._loop()
        except Exception as exc:  # noqa: BLE001 - report and shut down cleanly
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            if self.capture:
                self.capture.close()
            self.finished.emit()

    def _loop(self) -> None:
        c, d = self.cfg["capture"], self.cfg["decision"]
        self.capture = ScreenCapture(c["monitor"], c["phash_skip_distance"])
        print("loading models ...", flush=True)
        self.detector = Detector(self.cfg, self.backend)
        print(f"running: device {self.detector.device}, violence backend {self.detector.backend}, "
              f"{c['fps']} fps. Quit: Ctrl+Shift+Q" + ("" if IS_WINDOWS else " (not on Linux: use Ctrl+C)"),
              flush=True)
        decider = Decider(d["blur_threshold"], d["block_threshold"], d["window"],
                          d["trigger_count"], d["clear_count"])
        radius = self.cfg["overlay"]["blur_radius"]
        log_path = Path(self.cfg["log"]["path"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not log_path.exists()
        period = 1.0 / c["fps"]
        start = time.perf_counter()

        with log_path.open("a", newline="", encoding="utf-8") as f:
            log = csv.writer(f)
            if new_file:
                log.writerow(["time", "top_class", "prob", "action"])
            while self.running:
                t0 = time.perf_counter()
                if self.max_seconds and t0 - start >= self.max_seconds:
                    break
                img = self.capture.grab()
                if self.capture.is_new(img):
                    probs = self.detector.predict(img)
                    prev = decider.action
                    action = decider.update(probs)
                    cls, prob = top_class(probs)
                    log.writerow([datetime.now().isoformat(timespec="seconds"), cls, f"{prob:.4f}", action])
                    f.flush()
                    self.actions[action] += 1
                    if prev == "hidden" and action != "hidden":
                        self.activations += 1
                    self.decided.emit(action, make_blur(img, radius) if action == "blur" else None)
                    if self.detector.frames % 10 == 0:
                        print(f"  {self.detector.frames} frames analysed, avg inference "
                              f"{self.detector.avg_ms:.0f} ms/frame, skipped {self.capture.skipped}", flush=True)
                # sleep in small steps so stop() is noticed quickly
                while self.running and time.perf_counter() - t0 < period:
                    time.sleep(0.05)


def main() -> int:
    ap = argparse.ArgumentParser(description="KidGuard desktop prototype (screen -> detector -> overlay).")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--violence-backend", choices=BACKENDS, help="override config.yaml")
    ap.add_argument("--max-seconds", type=float, help="stop after this many seconds (for testing)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    app = QApplication(sys.argv)
    overlay = Overlay(cfg["overlay"]["block_text"])
    if IS_WINDOWS and not overlay.excluded_from_capture:
        print("WARNING: could not exclude the overlay from screen capture; "
              "the detector may see its own overlay.", flush=True)

    worker = Worker(cfg, args.violence_backend, args.max_seconds)
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.decided.connect(overlay.set_mode)
    worker.finished.connect(thread.quit)
    thread.finished.connect(app.quit)

    def quit_all(*_):
        worker.stop()  # the loop exits within ~50 ms, then the thread and app close

    hotkey = GlobalHotkey(app, quit_all)
    if IS_WINDOWS and not hotkey.registered:
        print("WARNING: Ctrl+Shift+Q is taken by another app; use Ctrl+C in this terminal.", flush=True)
    signal.signal(signal.SIGINT, quit_all)
    tick = QTimer()  # lets Python handle Ctrl+C while Qt's event loop runs
    tick.start(200)
    tick.timeout.connect(lambda: None)

    t_start = time.perf_counter()
    thread.start()
    app.exec()
    thread.wait(5000)
    hotkey.close()
    overlay.close()

    if worker.error:
        print(f"ERROR: {worker.error}")
    cap, det = worker.capture, worker.detector
    secs = time.perf_counter() - t_start
    print(f"avg inference: {det.avg_ms:.1f} ms/frame" if det and det.frames else "avg inference: n/a")
    print(f"Summary: ran {secs:.0f}s, grabbed {cap.grabbed if cap else 0}, analysed {cap.analysed if cap else 0}, "
          f"skipped (unchanged) {cap.skipped if cap else 0}; decisions "
          + ", ".join(f"{a}={worker.actions[a]}" for a in ("hidden", "blur", "block"))
          + f"; overlay activations {worker.activations}; log: {cfg['log']['path']}")
    return 1 if worker.error else 0


if __name__ == "__main__":
    sys.exit(main())
