"""Rename image files listed in data/metadata.csv to content hashes.

CLAUDE.md: before data/metadata.csv is committed, file names from the nudity
sources must not carry descriptive words or traceable source IDs. This script
renames matching files in place (same class folder) to
    <source>_<first 16 hex of sha256(file bytes)>.jpg
and updates path and group_id in metadata.csv (and the path cache in
data/interim/hashes.parquet, so dedup does not recompute hashes).

Default selection: rows whose file name matches --pattern (Pixiv-style
"<id>_p0_master1200" names). Use --all to rename every row of --sources.
Never deletes; never overwrites. File names are never printed, counts only.

    python scripts/rename_to_hash.py --dry-run
    python scripts/rename_to_hash.py
"""

import argparse
import hashlib
import os
import re
import sys
from collections import Counter
from pathlib import Path

from tqdm import tqdm

from kg_common import read_metadata, rel, write_metadata

PIXIV = r"_p\d+_master\d+"


def main() -> int:
    ap = argparse.ArgumentParser(description="Rename files to content hashes and update metadata.csv.")
    ap.add_argument("--sources", nargs="*", default=["nsfw_detect"])
    ap.add_argument("--pattern", default=PIXIV, help="regex on the file name; rows that match are renamed")
    ap.add_argument("--all", action="store_true", help="rename every row of --sources, ignore --pattern")
    ap.add_argument("--cache", type=Path, default=Path("data/interim/hashes.parquet"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows = read_metadata()
    rx = re.compile(args.pattern)
    todo = [r for r in rows if r["source"] in args.sources
            and (args.all or rx.search(Path(r["path"]).name))]
    print(f"metadata rows: {len(rows)}; selected for renaming: {len(todo)} "
          f"(sources {args.sources}, {'all rows' if args.all else 'pattern ' + args.pattern})")

    counts, mapping = Counter(), {}
    for r in tqdm(todo, desc="renaming", unit="img"):
        src = Path(r["path"])
        if not src.is_file():
            counts["missing file (skipped)"] += 1
            continue
        digest = hashlib.sha256(src.read_bytes()).hexdigest()
        n = 16
        dest = src.with_name(f"{r['source']}_{digest[:n]}.jpg")
        while dest.exists() and dest != src:
            if hashlib.sha256(dest.read_bytes()).hexdigest() == digest:
                break  # identical bytes already there under this name
            n += 4
            dest = src.with_name(f"{r['source']}_{digest[:n]}.jpg")
        if dest.exists() and dest != src:
            counts["identical file already present (skipped)"] += 1
            continue
        if not args.dry_run:
            os.rename(src, dest)
        mapping[r["path"]] = (rel(dest), f"{r['source']}/{digest[:n]}")
        counts["renamed" if not args.dry_run else "would rename"] += 1

    for r in rows:
        if r["path"] in mapping:
            r["path"], r["group_id"] = mapping[r["path"]]
    write_metadata(rows, args.dry_run)

    if mapping and args.cache.is_file() and not args.dry_run:
        import pandas as pd

        df = pd.read_parquet(args.cache)
        hit = df["path"].isin(mapping)
        df.loc[hit, "path"] = df.loc[hit, "path"].map(lambda p: mapping[p][0])
        df.to_parquet(args.cache, index=False)
        counts["hash-cache paths updated"] = int(hit.sum())

    left = sum(1 for r in read_metadata() if rx.search(Path(r["path"]).name) or rx.search(r["group_id"]))
    for k, v in sorted(counts.items()):
        print(f"  {k:40s} {v}")
    print(f"Summary: {len(todo)} selected, {counts['renamed'] + counts['would rename']} "
          f"{'would be ' if args.dry_run else ''}renamed; rows still matching the pattern in metadata.csv: "
          f"{left if not args.dry_run else 'n/a (dry run)'}{' (dry run, nothing changed)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
