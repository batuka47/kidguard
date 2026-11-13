"""Evaluate the detector on a folder tree <root>/<class>/*.png.

Classes are safe / nudity / violence / gore; a missing or empty class folder
counts as 0 images. Files under nudity/ are never shown by name, only by a
short content hash (CLAUDE.md).

Prints a per-file table (file, predicted top class, prob, correct), accuracy
per class, a confusion matrix, and every safe image that got flagged
(max unsafe prob >= blur_threshold). With --violence-backend both, the models
run once per image and both violence options are scored side by side.

Usage:
    python prototype/eval_folder.py prototype/test_images --violence-backend both
"""

import argparse
import csv
import hashlib
import time
from pathlib import Path

from PIL import Image

from detector import BACKENDS, CLASSES, DEFAULT_CONFIG, UNSAFE, Detector, load_config, top_class

EXTS = {".png", ".jpg", ".jpeg", ".webp", ".avif", ".bmp"}


def display_name(path: Path, cls: str) -> str:
    if cls == "nudity":
        return "nudity:" + hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return path.name


def pct(num: int, den: int) -> str:
    return f"{100 * num / den:5.1f}%" if den else "   n/a"


def main() -> int:
    ap = argparse.ArgumentParser(description="Score the detector on <root>/<class>/ images.")
    ap.add_argument("root", type=Path, nargs="?", default=Path("prototype/test_images"))
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--violence-backend", choices=BACKENDS + ("both",), default="both")
    ap.add_argument("--notes", type=Path, default=Path("prototype/test_labels.csv"),
                    help="optional labels CSV (file,label,note) to show notes for flagged safe images")
    ap.add_argument("--csv", type=Path, default=Path("reports/eval_prototype.csv"),
                    help="per-file scores are written here")
    ap.add_argument("--quiet", action="store_true", help="skip the per-file table")
    args = ap.parse_args()

    cfg = load_config(args.config)
    blur_t = cfg["decision"]["blur_threshold"]
    backends = list(BACKENDS) if args.violence_backend == "both" else [args.violence_backend]

    files: list[tuple[str, Path]] = []
    folder_counts = {}
    for cls in CLASSES:
        d = args.root / cls
        found = sorted(p for p in d.iterdir() if p.suffix.lower() in EXTS) if d.is_dir() else []
        folder_counts[cls] = len(found)
        files += [(cls, p) for p in found]
    skipped_dirs = [p.name for p in args.root.iterdir() if p.is_dir() and p.name not in CLASSES] if args.root.is_dir() else []
    print("images per class: " + ", ".join(f"{c}={n}" for c, n in folder_counts.items())
          + (f" | ignored folders: {skipped_dirs}" if skipped_dirs else ""))
    if not files:
        print("Summary: 0 images found, nothing to evaluate.")
        return 1

    det = Detector(cfg, backends[0], load_all=len(backends) > 1 or "vit" in backends)
    print(f"device: {det.device}, backends: {backends}, blur_threshold: {blur_t}")

    notes = {}
    if args.notes.is_file():
        notes = {r["file"]: r.get("note", "") for r in csv.DictReader(args.notes.open(encoding="utf-8"))}

    rows = []
    t0 = time.perf_counter()
    for true, path in files:
        try:
            with Image.open(path) as im:
                raw = det.raw_scores(im)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! cannot read {display_name(path, true)}: {type(exc).__name__}")
            continue
        row = {"file": display_name(path, true), "true": true, "raw": raw}
        for b in backends:
            probs = det.combine(raw, b)
            cls, prob = top_class(probs)
            row[b] = {"probs": probs, "pred": cls, "prob": prob,
                      "max_unsafe": max(probs[c] for c in UNSAFE),
                      "unsafe_cls": max(UNSAFE, key=probs.get)}
        rows.append(row)
    ms = 1000 * (time.perf_counter() - t0) / max(len(rows), 1)

    # -- per-file table ---------------------------------------------------------
    if not args.quiet:
        head = f"{'file':18s} {'true':9s}" + "".join(f" | {b + ' pred':14s} {'prob':>5s} {'ok':3s}" for b in backends)
        print("\n" + head + "\n" + "-" * len(head))
        for r in rows:
            line = f"{r['file']:18s} {r['true']:9s}"
            for b in backends:
                o = r[b]
                line += f" | {o['pred']:14s} {o['prob']:5.2f} {'yes' if o['pred'] == r['true'] else 'NO':3s}"
            print(line)

    # -- accuracy per backend -------------------------------------------------------
    present = [c for c in CLASSES if folder_counts[c]]
    print("\nAccuracy (top class == folder class)")
    hdr = f"{'':26s}" + "".join(f"{b:>12s}" for b in backends)
    print(hdr)
    def line(label, fn):
        print(f"{label:26s}" + "".join(f"{fn(b):>12s}" for b in backends))
    n = len(rows)
    line(f"overall (n={n})", lambda b: pct(sum(r[b]["pred"] == r["true"] for r in rows), n))
    for c in CLASSES:
        rc = [r for r in rows if r["true"] == c]
        line(f"  {c} (n={len(rc)})", lambda b, rc=rc, c=c: pct(sum(r[b]["pred"] == c for r in rc), len(rc)))
    unsafe_rows = [r for r in rows if r["true"] != "safe"]
    safe_rows = [r for r in rows if r["true"] == "safe"]
    line(f"unsafe caught (n={len(unsafe_rows)})",
         lambda b: pct(sum(r[b]["max_unsafe"] >= blur_t for r in unsafe_rows), len(unsafe_rows)))
    line(f"safe flagged (n={len(safe_rows)})",
         lambda b: pct(sum(r[b]["max_unsafe"] >= blur_t for r in safe_rows), len(safe_rows)))

    for b in backends:
        print(f"\nConfusion matrix [{b}] (rows = true, cols = predicted)")
        print(f"{'':10s}" + "".join(f"{c:>9s}" for c in CLASSES))
        for t in present:
            print(f"{t:10s}" + "".join(f"{sum(r['true'] == t and r[b]['pred'] == p for r in rows):9d}" for p in CLASSES))

    if "vit" in backends or det.vit is not None:
        print("\nViT label-index check: mean p(index 1) per true class "
              f"(config says violence = index {det.vit_index})")
        for c in present:
            rc = [r["raw"]["vit_index1"] for r in rows if r["true"] == c]
            print(f"  {c:9s} {sum(rc) / len(rc):.3f}")

    # -- flagged safe images ------------------------------------------------------
    for b in backends:
        flagged = sorted((r for r in safe_rows if r[b]["max_unsafe"] >= blur_t),
                         key=lambda r: -r[b]["max_unsafe"])
        print(f"\nSafe images flagged [{b}]: {len(flagged)} of {len(safe_rows)} (max unsafe prob >= {blur_t})")
        for r in flagged:
            o = r[b]
            print(f"  {r['file']:18s} {o['unsafe_cls']:9s} {o['max_unsafe']:.2f}  {notes.get(r['file'], '')}")

    # -- per-file CSV ---------------------------------------------------------------
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        raw_keys = sorted(rows[0]["raw"])
        w.writerow(["file", "true"] + raw_keys + [f"{b}_{k}" for b in backends for k in ("pred", "prob")])
        for r in rows:
            w.writerow([r["file"], r["true"]] + [f"{r['raw'][k]:.4f}" for k in raw_keys]
                       + [x for b in backends for x in (r[b]["pred"], f"{r[b]['prob']:.4f}")])

    print(f"\naverage inference: {ms:.1f} ms/image (all models, incl. image decode + preprocessing)")
    print(f"Summary: {len(rows)} images scored ({', '.join(f'{c}={folder_counts[c]}' for c in CLASSES)}), "
          f"backends {backends}, per-file scores -> {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
