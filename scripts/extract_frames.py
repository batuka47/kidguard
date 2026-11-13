"""Extract frames from the video datasets into data/interim/images/<class>/.

Per video: about 1 frame per second, at most --max-frames, evenly spaced over
the middle part of the video (the first and last --trim fraction are skipped;
fights often start late / end early). Very short clips still give 1 frame.

Output: data/interim/images/<class>/<dataset>_<video_stem>_f<frame index>.jpg
(JPEG q=92) and rows in data/metadata.csv with group_id = "<dataset>/<video_stem>",
so all frames of one video stay together.

Video datasets are found automatically: any dataset in scripts/label_map.yaml
whose data/raw/<name>/ folder contains video files (today: rlvs).

    python scripts/extract_frames.py --dry-run
    python scripts/extract_frames.py
"""

import argparse
import os
import sys
import time
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

from tqdm import tqdm

from kg_common import (IMAGES, load_label_map, lookup, read_metadata, rel, safe_name, upsert,
                       write_metadata)

VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".mpg", ".mpeg", ".wmv", ".flv", ".m4v"}


def find_videos(raw: Path, label_map: dict, only: list[str] | None):
    tasks, skipped = [], Counter()
    for name, entry in sorted(label_map.items()):
        if only and name not in only:
            continue
        d = raw / name
        if not d.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(d):
            dirnames[:] = sorted(x for x in dirnames if not x.startswith(("_", ".")))
            for f in sorted(filenames):
                if Path(f).suffix.lower() not in VIDEO_EXTS:
                    continue
                folder = Path(dirpath).name
                cls = lookup(entry.get("labels") or {}, folder)
                if cls in (None, "drop"):
                    skipped[f"{name}: {'unmapped' if cls is None else 'drop'}"] += 1
                    continue
                tasks.append((name, str(Path(dirpath) / f), folder, cls))
    return tasks, skipped


def sample_indices(n_frames: int, fps: float, rate: float, max_frames: int, trim: float) -> list[int]:
    dur = n_frames / fps
    start, end = trim * dur, (1 - trim) * dur
    span = max(end - start, 0.0)
    k = min(max_frames, max(1, int(span * rate)))
    times = [start + (i + 0.5) * span / k for i in range(k)]
    idx = sorted({min(n_frames - 1, max(0, round(t * fps))) for t in times})
    return idx


def process(task):
    """Worker: returns (task, frames [(index, out_path, written)], error or None)."""
    import cv2

    cv2.setNumThreads(1)
    name, video, folder, cls, opts = task
    out_dir = Path(opts["out"]) / cls
    stem = safe_name(Path(video).stem)
    cap = cv2.VideoCapture(video)
    try:
        if not cap.isOpened():
            return task, [], "cannot open"
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        if n <= 0 or not fps or fps <= 0:
            return task, [], f"bad metadata (frames={n}, fps={fps})"
        wanted = sample_indices(n, fps, opts["rate"], opts["max_frames"], opts["trim"])
        outs = {i: out_dir / f"{name}_{stem}_f{i:03d}.jpg" for i in wanted}
        if opts["dry_run"] or all(p.is_file() for p in outs.values()):
            return task, [(i, p, False) for i, p in outs.items()], None
        out_dir.mkdir(parents=True, exist_ok=True)
        frames, want = [], set(wanted)
        for i in range(max(wanted) + 1):
            if not cap.grab():
                break
            if i in want:
                ok, frame = cap.retrieve()
                if not ok or frame is None:
                    continue
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, opts["quality"]])
                if not ok:
                    continue
                tmp = outs[i].with_name(outs[i].name + ".part")
                tmp.write_bytes(buf.tobytes())
                os.replace(tmp, outs[i])
                frames.append((i, outs[i], True))
        if not frames:
            return task, [], "no frame could be decoded"
        return task, frames, None
    except Exception as exc:  # noqa: BLE001 - log and skip this video
        return task, [], f"{type(exc).__name__}: {exc}"
    finally:
        cap.release()


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract frames from video datasets.")
    ap.add_argument("--raw", type=Path, default=Path("data/raw"))
    ap.add_argument("--out", type=Path, default=IMAGES)
    ap.add_argument("--datasets", nargs="*", help="limit to these datasets (default: all with videos)")
    ap.add_argument("--rate", type=float, default=1.0, help="frames per second")
    ap.add_argument("--max-frames", type=int, default=8)
    ap.add_argument("--trim", type=float, default=0.10, help="skip this fraction at start and end")
    ap.add_argument("--quality", type=int, default=92)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    label_map = load_label_map()
    tasks, skipped = find_videos(args.raw, label_map, args.datasets)
    opts = {"out": str(args.out), "rate": args.rate, "max_frames": args.max_frames, "trim": args.trim,
            "quality": args.quality, "dry_run": args.dry_run}
    print(f"videos found: {len(tasks)} in {sorted({t[0] for t in tasks})}; workers: {args.workers}"
          + (f"; skipped: {dict(skipped)}" if skipped else ""))

    rows, errors = [], []
    per_class, per_video = Counter(), []
    written = reused = 0
    t0 = time.perf_counter()
    with Pool(args.workers) as pool:
        for task, frames, err in tqdm(pool.imap_unordered(process, [t + (opts,) for t in tasks], chunksize=4),
                                      total=len(tasks), desc="videos", unit="video"):
            name, video, folder, cls, _ = task
            if err:
                errors.append(f"{rel(Path(video))}\t{err}")
                continue
            per_video.append(len(frames))
            for i, p, w in frames:
                written += w
                reused += not w
                per_class[cls] += 1
                rows.append({"path": rel(p), "label": cls, "source": name,
                             "group_id": f"{name}/{safe_name(Path(video).stem)}", "split": "",
                             "orig_label": folder})

    meta, added, updated = upsert(read_metadata(), rows)
    write_metadata(meta, args.dry_run)
    if errors and not args.dry_run:
        log = Path("data/interim/logs/extract_frames_errors.tsv")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(errors) + "\n", encoding="utf-8")
        print(f"errors logged to {log}")
    for e in errors[:10]:
        print(f"  ! {e}")

    dist = Counter(per_video)
    print(f"frames per video: " + ", ".join(f"{k}:{v}" for k, v in sorted(dist.items())))
    verb = "would write" if args.dry_run else "written"
    print(f"Summary: {len(tasks)} videos, {len(per_video)} ok, {len(errors)} failed; {sum(per_class.values())} "
          f"frames ({verb} {written if not args.dry_run else sum(per_class.values())}, already present {reused if not args.dry_run else 0}); "
          f"per class {dict(per_class)}; metadata.csv +{added} rows, {updated} updated"
          f"{' (dry run, nothing written)' if args.dry_run else ''} in {time.perf_counter() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
