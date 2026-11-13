"""Copy image datasets into data/interim/images/<class>/ using scripts/label_map.yaml.

Output name: <dataset>_<original stem>.jpg (spaces/brackets -> "_"; a short hash
suffix is added if two files would get the same name). Bytes are copied as-is:
a few PNG/WEBP/BMP files sit under a .jpg name until clean_basic.py re-encodes
every image as a real RGB JPEG. Labels mapped to "drop" are skipped.

group_id = "<dataset>/<stem>" (one image = one group).
Rico is capped at --rico-limit images, sampled at random with --seed.

Never prints file names (sensitive datasets); counts only.

    python scripts/import_images.py --dry-run
    python scripts/import_images.py
"""

import argparse
import hashlib
import os
import random
import shutil
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tqdm import tqdm

from kg_common import (IMAGES, load_label_map, lookup, read_metadata, rel, safe_name, upsert,
                       write_metadata)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
DEFAULT_DATASETS = ["nsfw_detect", "adult_content", "unsafebench", "rico"]


def collect(raw: Path, name: str, labels: dict) -> tuple[list[tuple[Path, str, str]], Counter]:
    """[(source file, our class, original label folder)], counts of skipped files."""
    items, skipped = [], Counter()
    for dirpath, dirnames, filenames in os.walk(raw / name):
        dirnames[:] = sorted(x for x in dirnames if not x.startswith(("_", ".")))
        folder = Path(dirpath).name
        for f in sorted(filenames):
            if f.startswith(("_", ".")) or f.endswith(".part"):
                continue
            if Path(f).suffix.lower() not in IMAGE_EXTS:
                skipped["not an image extension"] += 1
                continue
            cls = lookup(labels, folder)
            if cls is None:
                skipped["unmapped label"] += 1
            elif cls == "drop":
                skipped["label mapped to drop"] += 1
            else:
                items.append((Path(dirpath) / f, cls, folder))
    return items, skipped


def copy_one(job: tuple[Path, Path, bool]) -> str:
    src, dest, dry_run = job
    if dest.is_file() and dest.stat().st_size == src.stat().st_size:
        return "already present"
    if dry_run:
        return "would copy"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dest)
    return "copied"


def main() -> int:
    ap = argparse.ArgumentParser(description="Copy image datasets into data/interim/images/<class>/.")
    ap.add_argument("--raw", type=Path, default=Path("data/raw"))
    ap.add_argument("--out", type=Path, default=IMAGES)
    ap.add_argument("--datasets", nargs="*", default=DEFAULT_DATASETS)
    ap.add_argument("--rico-limit", type=int, default=8000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    label_map = load_label_map()
    jobs, rows = [], []
    report = defaultdict(Counter)
    renamed = 0
    for name in args.datasets:
        entry = label_map.get(name)
        if entry is None or not (args.raw / name).is_dir():
            print(f"  ! {name}: not in label_map.yaml or not downloaded; skipped")
            continue
        items, skipped = collect(args.raw, name, entry.get("labels") or {})
        for k, v in skipped.items():
            report[name][k] += v
        if name == "rico" and len(items) > args.rico_limit:
            report[name]["not sampled (rico limit)"] += len(items) - args.rico_limit
            items = sorted(random.Random(args.seed).sample(items, args.rico_limit))
        used: set[tuple[str, str]] = set()
        for src, cls, folder in items:
            stem = safe_name(src.stem)
            if (cls, stem) in used:  # same stem twice in one class -> add a short hash of the source path
                stem = f"{stem}_{hashlib.sha1(rel(src).encode()).hexdigest()[:6]}"
                renamed += 1
            used.add((cls, stem))
            dest = args.out / cls / f"{name}_{stem}.jpg"
            jobs.append((src, dest, args.dry_run))
            rows.append({"path": rel(dest), "label": cls, "source": name,
                         "group_id": f"{name}/{stem}", "split": "", "orig_label": folder})
            report[name][f"-> {cls}"] += 1

    t0 = time.perf_counter()
    outcome = Counter()
    with ThreadPoolExecutor(args.workers) as pool:
        for r in tqdm(pool.map(copy_one, jobs), total=len(jobs), desc="images", unit="img"):
            outcome[r] += 1

    meta, added, updated = upsert(read_metadata(), rows)
    write_metadata(meta, args.dry_run)

    print("\nper dataset:")
    for name, c in report.items():
        print(f"  {name:14s} " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
    per_class = Counter(r["label"] for r in rows)
    print(f"names made unique with a hash suffix: {renamed}")
    print(f"Summary: {len(jobs)} images ({', '.join(f'{k} {v}' for k, v in sorted(outcome.items()))}); "
          f"per class {dict(sorted(per_class.items()))}; metadata.csv +{added} rows, {updated} updated, "
          f"{len(meta)} total{' (dry run, nothing written)' if args.dry_run else ''} "
          f"in {time.perf_counter() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
