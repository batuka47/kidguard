"""Remove duplicate and label-conflicting images (perceptual hash).

1. phash (64-bit) for every row of data/metadata.csv, cached in
   data/interim/hashes.parquet (key: path + size + mtime).
2. Near pairs (Hamming <= --threshold) without O(n^2): the 64 bits are split
   into 6 blocks; two hashes within 5 bits must share at least one block
   exactly (pigeonhole), so comparing only inside equal-block buckets finds
   every pair.
3. Label conflicts first: if an image is identical or near-identical to an
   image with a DIFFERENT label, all of those copies go to
   rejected/label_conflict/ and are listed in the report.
4. Exact duplicates (same phash): keep one (first by path), rest -> rejected/dup/.
5. Within one group_id (frames of one video) near duplicates are expected:
   each cluster of near-identical frames keeps at most --max-per-group frames,
   evenly spaced in time; the rest -> rejected/dup_in_group/.
6. Across different groups: keep the first by path, move later near
   duplicates -> rejected/dup/.

Moves only (never deletes). Updates metadata.csv, writes reports/dedup.md.
Images are processed by code only and never shown.

    python scripts/dedup.py --dry-run     # computes and caches hashes, moves nothing
    python scripts/dedup.py
"""

import argparse
import os
import re
import sys
import time
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

from kg_common import CLASSES, move_to_rejected, read_metadata, write_metadata

BANDS = [(0, 11), (11, 22), (22, 33), (33, 44), (44, 54), (54, 64)]


def phash_one(path: str) -> tuple[str, int]:
    import imagehash
    from PIL import Image

    with Image.open(path) as im:
        return path, int(str(imagehash.phash(im)), 16)


def load_hashes(paths: list[str], cache: Path, workers: int) -> tuple[np.ndarray, int]:
    old = {}
    if cache.is_file():
        df = pd.read_parquet(cache)
        old = {r.path: (r.size, r.mtime_ns, r.phash) for r in df.itertuples(index=False)}
    stats = {p: os.stat(p) for p in paths}
    out, todo = {}, []
    for p in paths:
        s = stats[p]
        hit = old.get(p)
        if hit and hit[0] == s.st_size and hit[1] == s.st_mtime_ns:
            out[p] = int(np.int64(hit[2]).view(np.uint64))
        else:
            todo.append(p)
    if todo:
        with Pool(workers) as pool:
            for p, h in tqdm(pool.imap_unordered(phash_one, todo, chunksize=64), total=len(todo),
                             desc="phash", unit="img"):
                out[p] = h
    cache.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "path": paths,
        "size": [stats[p].st_size for p in paths],
        "mtime_ns": [stats[p].st_mtime_ns for p in paths],
        "phash": [int(np.uint64(out[p]).view(np.int64)) for p in paths],
    }).to_parquet(cache, index=False)
    return np.array([out[p] for p in paths], dtype=np.uint64), len(paths) - len(todo)


def near_pairs(h: np.ndarray, threshold: int) -> dict[tuple[int, int], int]:
    pairs: dict[tuple[int, int], int] = {}
    for lo, hi in tqdm(BANDS, desc="bands", unit="band"):
        key = (h >> np.uint64(lo)) & np.uint64((1 << (hi - lo)) - 1)
        order = np.argsort(key, kind="stable")
        cuts = np.flatnonzero(np.diff(key[order])) + 1
        for grp in np.split(order, cuts):
            if len(grp) < 2:
                continue
            hv = h[grp]
            for k in range(len(grp) - 1):
                d = np.bitwise_count(np.bitwise_xor(hv[k], hv[k + 1:]))
                for j in np.flatnonzero(d <= threshold):
                    a, b = int(grp[k]), int(grp[k + 1 + j])
                    pairs[(min(a, b), max(a, b))] = int(d[j])
    return pairs


def frame_no(path: str) -> int:
    m = re.search(r"_f(\d+)\.jpg$", path)
    return int(m.group(1)) if m else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Remove duplicates and label conflicts (phash).")
    ap.add_argument("--threshold", type=int, default=5, help="max Hamming distance for near duplicates")
    ap.add_argument("--max-per-group", type=int, default=4)
    ap.add_argument("--cache", type=Path, default=Path("data/interim/hashes.parquet"))
    ap.add_argument("--report", type=Path, default=Path("reports/dedup.md"))
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--dry-run", action="store_true", help="move nothing (the hash cache is still written)")
    args = ap.parse_args()
    if args.threshold > 5:
        raise SystemExit("the 6-block index is only complete for --threshold <= 5")

    t0 = time.perf_counter()
    rows = sorted(read_metadata(), key=lambda r: r["path"])
    missing = [r for r in rows if not Path(r["path"]).is_file()]
    rows = [r for r in rows if Path(r["path"]).is_file()]
    paths = [r["path"] for r in rows]
    labels = [r["label"] for r in rows]
    groups = [r["group_id"] for r in rows]
    sources = [r["source"] for r in rows]
    print(f"metadata rows: {len(rows) + len(missing)} ({len(missing)} missing files ignored)")

    h, cached = load_hashes(paths, args.cache, args.workers)
    print(f"hashes: {len(h)} ({cached} from cache, {len(h) - cached} computed) -> {args.cache}")
    pairs = near_pairs(h, args.threshold)
    dist = Counter(pairs.values())
    print(f"near pairs (<= {args.threshold}): {len(pairs)}; by distance: {dict(sorted(dist.items()))}")

    reason: dict[int, str] = {}
    # 3. label conflicts
    conflicts = [(a, b, d) for (a, b), d in pairs.items() if labels[a] != labels[b]]
    for a, b, d in conflicts:
        reason[a] = reason[b] = "label_conflict"
    # 4. exact duplicates (same phash), keep the first by path
    first_of: dict[int, int] = {}
    for i, v in enumerate(h.tolist()):
        if i in reason:
            continue
        if v in first_of:
            reason[i] = "dup"
        else:
            first_of[v] = i
    # 5. within-group clusters of near-identical frames: keep max N, evenly spaced
    adj = defaultdict(set)
    for (a, b), d in pairs.items():
        adj[a].add(b)
        adj[b].add(a)
    by_group = defaultdict(list)
    for i, g in enumerate(groups):
        if i not in reason:
            by_group[g].append(i)
    for members in by_group.values():
        if len(members) <= args.max_per_group:
            continue
        mset, seen = set(members), set()
        for m in members:
            if m in seen:
                continue
            comp, stack = [], [m]
            seen.add(m)
            while stack:  # connected component of near-identical frames inside this group
                x = stack.pop()
                comp.append(x)
                for y in adj[x] & mset:
                    if y not in seen:
                        seen.add(y)
                        stack.append(y)
            if len(comp) > args.max_per_group:
                comp.sort(key=lambda i: (frame_no(paths[i]), paths[i]))
                keep = {comp[k] for k in np.linspace(0, len(comp) - 1, args.max_per_group).round().astype(int)}
                for i in comp:
                    if i not in keep:
                        reason[i] = "dup_in_group"
    # 6. across groups: keep the first by path
    for i in range(len(paths)):
        if i in reason:
            continue
        for j in adj[i]:
            if j < i and j not in reason and groups[j] != groups[i]:
                reason[i] = "dup"
                break

    # move + metadata
    table = defaultdict(Counter)
    by_source = defaultdict(Counter)
    for i in range(len(paths)):
        r = reason.get(i, "kept")
        table[labels[i]][r] += 1
        by_source[sources[i]][r] += 1
    moved = [i for i in reason]
    for i in tqdm(moved, desc="moving", unit="img", disable=args.dry_run):
        move_to_rejected(Path(paths[i]), reason[i], labels[i], args.dry_run)
    keep_paths = {paths[i] for i in range(len(paths)) if i not in reason}
    all_rows = read_metadata()
    new_rows = [r for r in all_rows if r["path"] in keep_paths]
    write_metadata(new_rows, args.dry_run)

    # report
    cols = ["label_conflict", "dup", "dup_in_group", "kept"]
    lines = ["# dedup report", "",
             f"phash 64-bit, near duplicate = Hamming distance <= {args.threshold}; "
             f"max {args.max_per_group} near-identical frames per group.", "",
             f"Near pairs found: {len(pairs)} (by distance: {dict(sorted(dist.items()))}).", "",
             "| class | " + " | ".join(cols) + " | total |", "|---" * (len(cols) + 2) + "|"]
    tot = Counter()
    for cls in [c for c in CLASSES if c in table]:
        c = table[cls]
        tot.update(c)
        lines.append(f"| {cls} | " + " | ".join(str(c[k]) for k in cols) + f" | {sum(c.values())} |")
    lines.append("| **total** | " + " | ".join(str(tot[k]) for k in cols) + f" | {sum(tot.values())} |")
    lines += ["", "| source | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
    for src, c in sorted(by_source.items()):
        lines.append(f"| {src} | " + " | ".join(str(c[k]) for k in cols) + " |")
    pair_kinds = Counter((tuple(sorted((labels[a], labels[b]))), tuple(sorted((sources[a], sources[b]))))
                         for a, b, _ in conflicts)
    lines += ["", f"## Label conflicts: {len(conflicts)} pairs, "
                  f"{sum(1 for v in reason.values() if v == 'label_conflict')} images moved", ""]
    for (lab, src), n in pair_kinds.most_common():
        lines.append(f"- {n} pairs: {lab[0]} vs {lab[1]} ({src[0]} / {src[1]})")
    if conflicts:
        lines += ["", "| image A | label A | image B | label B | distance |", "|---|---|---|---|---|"]
        for a, b, d in sorted(conflicts, key=lambda x: (x[2], paths[x[0]])):
            lines.append(f"| `{Path(paths[a]).name}` | {labels[a]} | `{Path(paths[b]).name}` | {labels[b]} | {d} |")
    lines += ["", f"metadata.csv: {len(all_rows)} rows before, {len(new_rows)} after.", ""]
    if not args.dry_run:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text("\n".join(lines), encoding="utf-8")

    print("\n" + "\n".join(lines[6:6 + len(table) + 3 + len(by_source) + 3]))
    for (lab, src), n in pair_kinds.most_common():
        print(f"  conflict pairs {n}: {lab[0]} vs {lab[1]} ({src[0]} / {src[1]})")
    print(f"Summary: {len(paths)} images; label_conflict {tot['label_conflict']}, dup {tot['dup']}, "
          f"dup_in_group {tot['dup_in_group']}, kept {tot['kept']}; metadata.csv {len(all_rows)} -> {len(new_rows)} rows"
          f"{' (dry run, nothing moved)' if args.dry_run else f'; report: {args.report}'} "
          f"in {time.perf_counter() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
