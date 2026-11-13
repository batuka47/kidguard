"""Dataset statistics from data/metadata.csv -> reports/stats.md.

Images per class, per source, class x source, class x original label, number
of groups (group_id) per class, and a check that every row's file exists.
Reads metadata only; never opens an image.

    python scripts/stats.py
"""

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

from kg_common import CLASSES, METADATA, read_metadata


def table(title: str, row_keys, col_keys, cell, row_head: str) -> list[str]:
    tot_col = len(col_keys) > 1  # a total column only makes sense with several columns
    lines = [f"## {title}", "", f"| {row_head} | " + " | ".join(col_keys) + (" | total |" if tot_col else " |"),
             "|---" * (len(col_keys) + 1 + tot_col) + "|"]
    col_tot = Counter()
    for rk in row_keys:
        vals = [cell(rk, ck) for ck in col_keys]
        col_tot.update(dict(zip(col_keys, vals)))
        lines.append(f"| {rk} | " + " | ".join(str(v) for v in vals) + (f" | {sum(vals)} |" if tot_col else " |"))
    lines.append("| **total** | " + " | ".join(str(col_tot[c]) for c in col_keys)
                 + (f" | {sum(col_tot.values())} |" if tot_col else " |"))
    return lines + [""]


def main() -> int:
    ap = argparse.ArgumentParser(description="Statistics of data/metadata.csv.")
    ap.add_argument("--metadata", type=Path, default=METADATA)
    ap.add_argument("--out", type=Path, default=Path("reports/stats.md"))
    ap.add_argument("--dry-run", action="store_true", help="print only, do not write the report")
    args = ap.parse_args()

    rows = read_metadata(args.metadata)
    if not rows:
        print("Summary: metadata.csv is empty or missing")
        return 1
    missing = sum(1 for r in rows if not Path(r["path"]).is_file())
    classes = [c for c in CLASSES if any(r["label"] == c for r in rows)]
    sources = sorted({r["source"] for r in rows})
    cs = Counter((r["label"], r["source"]) for r in rows)
    groups = defaultdict(set)
    for r in rows:
        groups[r["label"]].add(r["group_id"])
    orig = Counter((r["label"], f"{r['source']}:{r['orig_label']}") for r in rows)

    n = len(rows)
    lines = ["# Dataset statistics", "",
             f"From `{args.metadata.as_posix()}`: {n} images, {sum(len(g) for g in groups.values())} groups, "
             f"{missing} rows with a missing file. Splits assigned: "
             f"{sum(1 for r in rows if r['split'])} of {n}.", ""]
    lines += ["## Images and groups per class", "", "| class | images | share | groups | images per group |",
              "|---|---|---|---|---|"]
    for c in classes:
        k = sum(v for (lab, _), v in cs.items() if lab == c)
        lines.append(f"| {c} | {k} | {100 * k / n:.1f}% | {len(groups[c])} | {k / len(groups[c]):.2f} |")
    lines.append("")
    lines += table("Images per source", sources, ["images"],
                   lambda s, _: sum(v for (_, src), v in cs.items() if src == s), "source")
    lines += table("Class x source", classes, sources, lambda c, s: cs[(c, s)], "class")
    lines += ["## Class x original label", "", "| class | source:original label | images |", "|---|---|---|"]
    for (c, o), v in sorted(orig.items(), key=lambda x: (CLASSES.index(x[0][0]), -x[1])):
        lines.append(f"| {c} | {o} | {v} |")
    lines.append("")

    print("\n".join(lines))
    if not args.dry_run:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Summary: {n} images in {len(classes)} classes from {len(sources)} sources; "
          + ", ".join(f"{c} {sum(v for (lab, _), v in cs.items() if lab == c)}" for c in classes)
          + f"; missing files {missing}" + ("" if args.dry_run else f"; wrote {args.out}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
