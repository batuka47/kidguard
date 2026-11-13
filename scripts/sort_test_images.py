"""Copy labelled test images into prototype/test_images/<class>/.

Reads a labels CSV (columns: file,label,note) and copies each file from --src:

  safe / nudity / violence / gore  ->  <dst>/<label>/<file>
  exclude                          ->  <rejected>/exclude/<file>
  pending                          ->  left in --src (not labelled yet)

Never deletes and never overwrites: source files stay where they are, and a
file that already exists at the destination is skipped (or reported as a
conflict if its content differs). Unreadable images and exact duplicates
(same sha256) go to <rejected>/broken/ and <rejected>/duplicate/.

Files labelled nudity are never opened as images and are reported by hash only.

Usage:
    python scripts/sort_test_images.py --dry-run
    python scripts/sort_test_images.py
"""

import argparse
import csv
import hashlib
import shutil
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

CLASSES = ("safe", "nudity", "violence", "gore")
OTHER = ("exclude", "pending")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def opens_as_image(path: Path) -> bool:
    try:
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:  # noqa: BLE001
        return False


def show(name: str, label: str, digest: str) -> str:
    """Filename for display; nudity files are shown by hash only (CLAUDE.md)."""
    return f"<nudity sha256:{digest[:12]}>" if label == "nudity" else name


def main() -> int:
    ap = argparse.ArgumentParser(description="Copy labelled test images into class folders.")
    ap.add_argument("--src", type=Path, default=Path("data/raw/test_images_drive/drive_folder"))
    ap.add_argument("--labels", type=Path, default=Path("prototype/test_labels.csv"))
    ap.add_argument("--dst", type=Path, default=Path("prototype/test_images"))
    ap.add_argument("--rejected", type=Path, default=Path("data/interim/rejected/test_images"))
    ap.add_argument("--dry-run", action="store_true", help="print what would happen, copy nothing")
    args = ap.parse_args()

    rows = list(csv.DictReader(args.labels.open(encoding="utf-8")))
    counts: Counter[str] = Counter()
    per_class: Counter[str] = Counter()
    problems: list[str] = []
    seen: dict[str, str] = {}  # sha256 -> first file name
    plan: list[tuple[Path, Path]] = []

    for row in rows:
        name, label = row["file"].strip(), row["label"].strip().lower()
        src = args.src / name
        if label not in CLASSES + OTHER:
            counts["unknown label"] += 1
            problems.append(f"unknown label {label!r} for {name}")
            continue
        if label == "pending":
            counts["pending (not copied)"] += 1
            continue
        if not src.is_file():
            counts["missing source"] += 1
            problems.append(f"missing source file: {name}")
            continue

        digest = sha256(src)
        shown = show(name, label, digest)
        if digest in seen:
            dest = args.rejected / "duplicate" / name
            counts["duplicate -> rejected"] += 1
            problems.append(f"duplicate of {show(seen[digest], label, digest)}: {shown}")
        elif label != "nudity" and not opens_as_image(src):
            dest = args.rejected / "broken" / name
            counts["broken -> rejected"] += 1
            problems.append(f"cannot open as image: {shown}")
        elif label == "exclude":
            dest = args.rejected / "exclude" / name
            counts["exclude -> rejected"] += 1
        else:
            dest = args.dst / label / name
            counts["copy to class folder"] += 1
            per_class[label] += 1
        seen.setdefault(digest, name)

        if dest.exists():
            if sha256(dest) == digest:
                counts["already in place (skipped)"] += 1
            else:
                counts["conflict (skipped)"] += 1
                problems.append(f"different file already at {dest.parent}/: {shown}")
            continue
        plan.append((src, dest))

    if not args.dry_run:
        for src, dest in plan:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    mode = "DRY RUN (nothing copied)" if args.dry_run else "DONE"
    print(f"{mode}: {len(rows)} rows in {args.labels}")
    for p in problems:
        print(f"  ! {p}")
    for key, n in sorted(counts.items()):
        print(f"  {key:28s} {n}")
    print("  per class: " + ", ".join(f"{c}={per_class[c]}" for c in CLASSES))
    verb = "would copy" if args.dry_run else "copied"
    print(f"Summary: {len(rows)} rows, {verb} {len(plan)} files "
          f"({sum(per_class.values())} to class folders), {len(problems)} problem(s).")
    return 1 if counts["unknown label"] or counts["conflict (skipped)"] else 0


if __name__ == "__main__":
    sys.exit(main())
