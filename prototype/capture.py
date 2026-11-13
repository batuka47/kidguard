"""Screen capture with unchanged-frame skipping.

ScreenCapture.grab() returns the primary monitor as a PIL RGB image.
ScreenCapture.is_new(img) returns False (and counts a skip) when the frame's
perceptual hash is within `phash_skip_distance` of the last analysed frame.

Demo:
    python prototype/capture.py --seconds 10
"""

import argparse
import time

import imagehash
import mss
from PIL import Image


class ScreenCapture:
    def __init__(self, monitor: int = 1, phash_skip_distance: int = 4):
        self.monitor = monitor
        self.phash_skip_distance = phash_skip_distance
        self.grabbed = 0
        self.analysed = 0
        self.skipped = 0
        self._sct = None  # created lazily: mss handles must stay on one thread
        self._last_hash = None

    def grab(self) -> Image.Image:
        if self._sct is None:
            self._sct = mss.MSS() if hasattr(mss, "MSS") else mss.mss()
        shot = self._sct.grab(self._sct.monitors[self.monitor])
        self.grabbed += 1
        return Image.frombytes("RGB", shot.size, shot.rgb)

    def is_new(self, img: Image.Image) -> bool:
        """True if the frame should be analysed, False if the screen did not change."""
        h = imagehash.phash(img)
        if self._last_hash is not None and h - self._last_hash <= self.phash_skip_distance:
            self.skipped += 1
            return False
        self._last_hash = h
        self.analysed += 1
        return True

    def close(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None


def main() -> None:
    ap = argparse.ArgumentParser(description="Grab the screen and count changed/unchanged frames.")
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--monitor", type=int, default=1)
    ap.add_argument("--phash-skip-distance", type=int, default=4)
    args = ap.parse_args()

    cap = ScreenCapture(args.monitor, args.phash_skip_distance)
    period = 1.0 / args.fps
    end = time.perf_counter() + args.seconds
    grab_ms = 0.0
    size = None
    while time.perf_counter() < end:
        t0 = time.perf_counter()
        img = cap.grab()
        size = img.size
        cap.is_new(img)
        grab_ms += (time.perf_counter() - t0) * 1000
        time.sleep(max(0.0, period - (time.perf_counter() - t0)))
    cap.close()
    print(f"monitor {args.monitor} size {size}, {grab_ms / max(cap.grabbed, 1):.0f} ms per grab+hash")
    print(f"Summary: grabbed {cap.grabbed}, analysed {cap.analysed}, skipped (unchanged) {cap.skipped}")


if __name__ == "__main__":
    main()
