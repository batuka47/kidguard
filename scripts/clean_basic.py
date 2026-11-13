"""Basic cleaning of data/interim/images/ (rows of data/metadata.csv).

Moves a file to data/interim/rejected/<reason>/<class>/ if it:
  verify_failed      fails PIL verify()
  not_rgb            cannot be loaded / converted to RGB
  too_small          short side < --min-side px after the long-side resize
                     (so very wide/tall images, > 4:1, are rejected too)
  single_colour      grayscale std < --min-std (black / white / flat frames)
Every other file is re-saved in place as an RGB JPEG (q=--quality) with the
long side <= --max-side, rotated upright from EXIF. Files that already are an
upright RGB JPEG within the size limit are left untouched (no re-compression).
Originals in data/raw/ are never touched. Rows of moved files are removed from
metadata.csv; reports/clean_basic.md gets counts per class and reason.

Images are processed by code only and never shown.

    python scripts/clean_basic.py --dry-run
    python scripts/clean_basic.py
"""

import argparse
import os
import sys
import time
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

from tqdm import tqdm

from kg_common import CLASSES, move_to_rejected, read_metadata, write_metadata

REASONS = ("verify_failed", "not_rgb", "too_small", "single_colour")


def to_rgb(im):
    from PIL import Image

    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        return bg
    return im.convert("RGB")


def check(job):
    """Worker: returns (path, label, outcome, detail). outcome: keep|reencode|<reason>|missing."""
    import numpy as np
    from PIL import Image, ImageOps

    path, label, o = job
    p = Path(path)
    if not p.is_file():
        return path, label, "missing", ""
    try:
        with Image.open(p) as im:
            im.verify()
    except Exception as exc:  # noqa: BLE001
        return path, label, "verify_failed", type(exc).__name__
    try:
        with Image.open(p) as im:
            fmt = im.format
            orient = im.getexif().get(0x0112, 1)
            im.load()
            im = ImageOps.exif_transpose(im)
            rgb = to_rgb(im)
    except Exception as exc:  # noqa: BLE001
        return path, label, "not_rgb", type(exc).__name__
    w, h = rgb.size
    scale = min(1.0, o["max_side"] / max(w, h))
    fw, fh = round(w * scale), round(h * scale)  # size after the long-side resize
    if min(fw, fh) < o["min_side"]:
        return path, label, "too_small", f"{w}x{h} -> {fw}x{fh}"
    small = rgb.copy()
    small.thumbnail((256, 256))
    std = float(np.asarray(small.convert("L"), dtype=np.float32).std())
    if std < o["min_std"]:
        return path, label, "single_colour", f"std {std:.1f}"

    needs_resize = max(w, h) > o["max_side"]
    clean_jpeg = fmt == "JPEG" and im.mode == "RGB" and orient in (None, 1)
    if clean_jpeg and not needs_resize:
        return path, label, "keep", ""
    if o["dry_run"]:
        return path, label, "reencode", "resize" if needs_resize else "convert"
    if needs_resize:
        rgb.thumbnail((o["max_side"], o["max_side"]), Image.LANCZOS)
    tmp = p.with_name(p.name + ".part")
    rgb.save(tmp, "JPEG", quality=o["quality"])
    os.replace(tmp, p)
    return path, label, "reencode", "resize" if needs_resize else "convert"


def main() -> int:
    ap = argparse.ArgumentParser(description="Reject broken/tiny/flat images; re-save the rest as RGB JPEG <= 512 px.")
    ap.add_argument("--min-side", type=int, default=128)
    ap.add_argument("--min-std", type=float, default=5.0)
    ap.add_argument("--max-side", type=int, default=512)
    ap.add_argument("--quality", type=int, default=92)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--report", type=Path, default=Path("reports/clean_basic.md"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = read_metadata()
    opts = {"min_side": args.min_side, "min_std": args.min_std, "max_side": args.max_side,
            "quality": args.quality, "dry_run": args.dry_run}
    jobs = [(r["path"], r["label"], opts) for r in rows]
    print(f"metadata rows: {len(rows)}; workers: {args.workers}")

    t0 = time.perf_counter()
    table = defaultdict(Counter)  # class -> outcome -> n
    by_source = defaultdict(Counter)  # source -> reason -> n (rejects only)
    source_of = {r["path"]: r["source"] for r in rows}
    drop = set()
    with Pool(args.workers) as pool:
        for path, label, outcome, detail in tqdm(pool.imap_unordered(check, jobs, chunksize=64),
                                                 total=len(jobs), desc="images", unit="img"):
            key = f"reencode ({detail})" if outcome == "reencode" else outcome
            table[label][key] += 1
            if outcome in REASONS:
                move_to_rejected(Path(path), outcome, label, args.dry_run)
                by_source[source_of[path]][outcome] += 1
                drop.add(path)
            elif outcome == "missing":
                drop.add(path)

    kept_rows = [r for r in rows if r["path"] not in drop]
    write_metadata(kept_rows, args.dry_run)

    cols = list(REASONS) + ["missing", "keep", "reencode (convert)", "reencode (resize)"]
    lines = ["# clean_basic report", "",
             f"Rules: PIL verify, RGB conversion, short side >= {args.min_side} px, grayscale std >= "
             f"{args.min_std}. Kept files re-saved as RGB JPEG q={args.quality}, long side <= {args.max_side} px.",
             "", "| class | " + " | ".join(cols) + " | total |", "|---" * (len(cols) + 2) + "|"]
    for cls in [c for c in CLASSES if c in table]:
        c = table[cls]
        lines.append(f"| {cls} | " + " | ".join(str(c[k]) for k in cols) + f" | {sum(c.values())} |")
    tot = Counter()
    for c in table.values():
        tot.update(c)
    lines.append("| **total** | " + " | ".join(str(tot[k]) for k in cols) + f" | {sum(tot.values())} |")
    lines += ["", "Rejected per source:", ""]
    for src, c in sorted(by_source.items()):
        lines.append(f"- {src}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
    if not by_source:
        lines.append("- none")
    lines += ["", f"metadata.csv: {len(rows)} rows before, {len(kept_rows)} after (this run).", ""]
    # cumulative state over all runs: files currently in rejected/<reason>/<class>/
    from kg_common import REJECTED
    lines += ["## All runs: files in data/interim/rejected/", "",
              "| class | " + " | ".join(REASONS) + " | total |", "|---" * (len(REASONS) + 2) + "|"]
    cum_tot = Counter()
    for cls in CLASSES:
        c = Counter({r: sum(1 for f in (REJECTED / r / cls).glob("*") if f.is_file()) if (REJECTED / r / cls).is_dir() else 0
                     for r in REASONS})
        cum_tot.update(c)
        if sum(c.values()):
            lines.append(f"| {cls} | " + " | ".join(str(c[r]) for r in REASONS) + f" | {sum(c.values())} |")
    lines += ["| **total** | " + " | ".join(str(cum_tot[r]) for r in REASONS) + f" | {sum(cum_tot.values())} |", ""]
    if not args.dry_run:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text("\n".join(lines), encoding="utf-8")

    print("\n" + "\n".join(lines[4:]))
    rejected = sum(tot[k] for k in REASONS)
    print(f"Summary: {len(rows)} images checked; rejected {rejected} "
          f"({', '.join(f'{k} {tot[k]}' for k in REASONS)}); missing {tot['missing']}; "
          f"kept {tot['keep'] + tot['reencode (convert)'] + tot['reencode (resize)']} "
          f"(re-encoded {tot['reencode (convert)'] + tot['reencode (resize)']}); "
          f"metadata.csv {len(rows)} -> {len(kept_rows)} rows"
          f"{' (dry run, nothing changed)' if args.dry_run else f'; report: {args.report}'} "
          f"in {time.perf_counter() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
