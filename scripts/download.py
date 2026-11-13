"""Download or place KidGuard datasets into data/raw/<name>/.

    python scripts/download.py status
    python scripts/download.py rlvs
    python scripts/download.py rico --limit 20000
    python scripts/download.py nsfw_detect     # run by the data keeper (CLAUDE.md)
    python scripts/download.py unsafebench     # run by the data keeper (CLAUDE.md)
    python scripts/download.py adult_content --from-zip "Adult content dataset.zip" --dry-run
    python scripts/download.py npdi            # prints manual instructions

Every subcommand is resumable: a finished dataset gets data/raw/<name>/_COMPLETE.json
and is skipped next time (use --force to redo). Archives are kept in
data/raw/<name>/_download/ and re-extraction skips files that already exist.
Nothing is ever deleted. Free disk space is printed before and after.

Files are never opened as images here; the scripts only move bytes. Nothing
under the nudity datasets is printed by name.
"""

import argparse
import csv
import json
import os
import shutil
import sys
import threading
import time
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

RAW = Path("data/raw")
MARKER = "_COMPLETE.json"

SOURCES = {
    "rlvs": "Kaggle mohamedmustafa/real-life-violence-situations-dataset "
            "(license on Kaggle: 'Data files (c) Original Authors')",
    "rico": "Hugging Face Voxel51/rico (UI screenshots only; no license stated on the page)",
    "nsfw_detect": "Hugging Face deepghs/nsfw_detect (gated, MIT)",
    "unsafebench": "Hugging Face yiting/UnsafeBench (gated)",
    "adult_content": "zip supplied by the data keeper (no README in the archive)",
    "npdi": "NPDI Pornography database (authors' agreement required)",
    "fs_lspd": "FS-LSPD (authors' agreement required)",
}

MANUAL = {
    "adult_content": """\
adult_content is supplied by the data keeper as a zip (no public URL known).
  1. Keep the zip anywhere on this PC (e.g. the repo root; *.zip is gitignored).
  2. Dry run:  python scripts/download.py adult_content --from-zip "<path to zip>" --dry-run
  3. Real run: python scripts/download.py adult_content --from-zip "<path to zip>"
     The zip is moved to data/raw/adult_content/_download/ and extracted into
     data/raw/adult_content/ (macOS __MACOSX / .DS_Store junk is skipped).""",
    "npdi": """\
NPDI Pornography database (Pornography-800 / -2k, Avila et al., UNICAMP).
  Access is by agreement with the authors. The old page
  https://sites.google.com/site/pornographydatabase/ now redirects to a Google
  sign-in (checked 2026-11), so use the link the authors send you.
  1. Download the archive(s) the authors send (zip; rar is not supported yet).
  2. python scripts/download.py npdi --from-zip "<path to zip>" --dry-run
  3. python scripts/download.py npdi --from-zip "<path to zip>"
     -> extracted into data/raw/npdi/""",
    "fs_lspd": """\
FS-LSPD: access is by request to the dataset authors; use the link they send.
  1. Download the archive they send (zip).
  2. python scripts/download.py fs_lspd --from-zip "<path to zip>" --dry-run
  3. python scripts/download.py fs_lspd --from-zip "<path to zip>"
     -> extracted into data/raw/fs_lspd/""",
}


# --- helpers -------------------------------------------------------------------
def free_gb(root: Path) -> float:
    root.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(root).free / 1e9


def tree_stats(d: Path) -> tuple[int, int]:
    """(files, bytes) under d, ignoring _download/, markers and dot files."""
    n = size = 0
    for dirpath, dirnames, filenames in os.walk(d):
        dirnames[:] = [x for x in dirnames if not x.startswith(("_", "."))]
        for f in filenames:
            if not f.startswith(("_", ".")) and not f.endswith(".part"):
                n += 1
                size += os.path.getsize(os.path.join(dirpath, f))
    return n, size


def read_marker(d: Path) -> dict | None:
    m = d / MARKER
    return json.loads(m.read_text(encoding="utf-8")) if m.is_file() else None


def write_marker(d: Path, name: str, **extra) -> dict:
    files, size = tree_stats(d)
    info = {"dataset": name, "source": SOURCES[name], "files": files, "bytes": size,
            "completed_at": datetime.now().isoformat(timespec="seconds"), **extra}
    (d / MARKER).write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def is_junk(parts: list[str]) -> bool:
    return parts[0] == "__MACOSX" or parts[-1] == ".DS_Store" or parts[-1].startswith("._")


def safe_extract(zf: zipfile.ZipFile, dest: Path, select=None, dry_run: bool = False) -> Counter:
    """Extract members into dest. Skips junk, rejects unsafe paths, skips files already present."""
    c: Counter[str] = Counter()
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/")
        parts = name.split("/")
        if is_junk(parts):
            c["junk skipped (__MACOSX/.DS_Store)"] += 1
            continue
        if name.startswith("/") or ".." in parts or parts[0].endswith(":"):
            c["unsafe path rejected"] += 1
            continue
        if select is not None and not select(name):
            c["not selected"] += 1
            continue
        target = dest / name
        if target.is_file() and target.stat().st_size == info.file_size:
            c["already extracted"] += 1
            continue
        if dry_run:
            c["would extract"] += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".part")
        with zf.open(info) as src, open(tmp, "wb") as out:
            shutil.copyfileobj(src, out, 1 << 20)
        os.replace(tmp, target)
        c["extracted"] += 1
    return c


def print_counts(c: Counter) -> None:
    for k, v in sorted(c.items()):
        print(f"  {k:36s} {v}")


def already_done(d: Path, args, check=lambda m: True) -> bool:
    m = read_marker(d)
    if m and check(m) and not args.force:
        print(f"already complete ({m['files']} files, {m['bytes'] / 1e9:.2f} GB, {m['completed_at']}); "
              f"use --force to redo")
        return True
    return False


# --- Kaggle ----------------------------------------------------------------------
def kaggle_zip(ref: str, dl: Path) -> Path:
    dl.mkdir(parents=True, exist_ok=True)
    zip_path = dl / f"{ref.split('/')[1]}.zip"
    if zip_path.is_file() and zipfile.is_zipfile(zip_path):
        print(f"zip already downloaded: {zip_path} ({zip_path.stat().st_size / 1e9:.2f} GB)")
        return zip_path
    import kaggle  # reads ~/.kaggle/kaggle.json on import

    print(f"downloading Kaggle {ref} ...", flush=True)
    kaggle.api.dataset_download_files(ref, path=str(dl), quiet=False, unzip=False, force=True)
    if not (zip_path.is_file() and zipfile.is_zipfile(zip_path)):
        raise SystemExit(f"download failed: {zip_path} missing or not a zip")
    return zip_path


def cmd_rlvs(args) -> None:
    d = args.root / "rlvs"
    if already_done(d, args):
        return
    ref = "mohamedmustafa/real-life-violence-situations-dataset"
    if args.dry_run and not (d / "_download" / f"{ref.split('/')[1]}.zip").is_file():
        print(f"dry run: would download Kaggle {ref} (~3.9 GB zip) and extract one copy of the videos into {d}")
        return
    zip_path = kaggle_zip(ref, d / "_download")
    dup_root = "real life violence situations/"
    with zipfile.ZipFile(zip_path) as zf:
        infos = {i.filename: i for i in zf.infolist() if not i.is_dir()}
        dups = [n for n in infos if n.startswith(dup_root)]
        same = sum(1 for n in dups if (t := infos.get(n[len(dup_root):])) is not None
                   and (t.CRC, t.file_size) == (infos[n].CRC, infos[n].file_size))
        print(f"zip has {len(infos)} files; nested copy under '{dup_root}': {len(dups)} files, "
              f"{same} identical (CRC + size) to the top-level copy")
        select = (lambda n: not n.startswith(dup_root)) if dups and same == len(dups) else None
        if select is None and dups:
            print("WARNING: the two copies differ; extracting both")
        c = safe_extract(zf, d, select, args.dry_run)
    print_counts(c)
    if not args.dry_run:
        info = write_marker(d, "rlvs", duplicate_copy_skipped=len(dups) if select else 0)
        print(f"done: {info['files']} files, {info['bytes'] / 1e9:.2f} GB in {d}")


# --- Hugging Face ------------------------------------------------------------------
def cmd_rico(args) -> None:
    from huggingface_hub import HfApi, hf_hub_url
    from huggingface_hub.utils import build_hf_headers, get_session

    repo = "Voxel51/rico"
    d = args.root / "rico"
    out = d / "screenshots"
    if already_done(d, args, check=lambda m: m.get("limit", 0) >= args.limit):
        return
    files = [f for f in HfApi().list_repo_files(repo, repo_type="dataset")
             if f.startswith("data/") and f.lower().endswith(".jpg")]
    files.sort(key=lambda f: (int(Path(f).stem) if Path(f).stem.isdigit() else 10**12, f))
    names = [Path(f).name for f in files]
    if len(set(names)) != len(names):
        raise SystemExit("screenshot file names are not unique across folders; aborting")
    chosen = files[: args.limit]
    out.mkdir(parents=True, exist_ok=True)
    have = {p.name for p in out.glob("*.jpg")}
    todo = [f for f in chosen if Path(f).name not in have]
    print(f"repo has {len(files)} screenshots; limit {args.limit}; already here {len(chosen) - len(todo)}; "
          f"to download {len(todo)}")
    if args.dry_run:
        return

    local = threading.local()
    headers = build_hf_headers()

    def fetch(f: str) -> str:
        if not hasattr(local, "s"):
            local.s = get_session()
        url = hf_hub_url(repo, f, repo_type="dataset")
        target = out / Path(f).name
        for attempt in range(6):
            try:
                r = local.s.get(url, headers=headers, timeout=60)
                if r.status_code == 200:
                    tmp = target.with_name(target.name + ".part")
                    tmp.write_bytes(r.content)
                    os.replace(tmp, target)
                    return "downloaded"
                if r.status_code not in (429, 500, 502, 503, 504):
                    return f"http {r.status_code}"
            except Exception:  # noqa: BLE001 - network hiccup, retry
                pass
            time.sleep(min(60, 2 ** attempt))
        return "failed after retries"

    c: Counter[str] = Counter()
    with ThreadPoolExecutor(args.workers) as pool:
        for i, fut in enumerate(as_completed(pool.submit(fetch, f) for f in todo), 1):
            c[fut.result()] += 1
            if i % 1000 == 0:
                print(f"  {i}/{len(todo)} done ({dict(c)})", flush=True)
    print_counts(c)
    n_now = len(list(out.glob("*.jpg")))
    if n_now >= min(args.limit, len(files)):
        info = write_marker(d, "rico", limit=args.limit)
        print(f"done: {info['files']} screenshots, {info['bytes'] / 1e9:.2f} GB in {out}")
    else:
        print(f"incomplete: {n_now} of {args.limit} screenshots present; run again to resume")


def hf_snapshot(repo: str, dl: Path, patterns: list[str]) -> Path:
    from huggingface_hub import snapshot_download

    print(f"downloading Hugging Face {repo} (resumable) ...", flush=True)
    return Path(snapshot_download(repo, repo_type="dataset", local_dir=dl, allow_patterns=patterns))


def cmd_nsfw_detect(args) -> None:
    d = args.root / "nsfw_detect"
    if already_done(d, args):
        return
    if args.dry_run:
        print("dry run: would download deepghs/nsfw_detect (~1.8 GB zip) and extract it into", d)
        return
    dl = hf_snapshot("deepghs/nsfw_detect", d / "_download", ["*.zip", "README.md"])
    zips = sorted(dl.glob("*.zip"))
    if not zips:
        raise SystemExit("no zip found in the download")
    c: Counter[str] = Counter()
    for z in zips:
        with zipfile.ZipFile(z) as zf:
            c += safe_extract(zf, d)
    print_counts(c)
    info = write_marker(d, "nsfw_detect")
    print(f"done: {info['files']} files, {info['bytes'] / 1e9:.2f} GB in {d}")


def image_ext(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    return ".bin"


def safe_folder(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-" else "_" for ch in text.strip()) or "unknown"


def cmd_unsafebench(args) -> None:
    import pyarrow.parquet as pq

    d = args.root / "unsafebench"
    if already_done(d, args):
        return
    if args.dry_run:
        print("dry run: would download yiting/UnsafeBench (~0.9 GB parquet) and export images into", d)
        return
    dl = hf_snapshot("yiting/UnsafeBench", d / "_download", ["data/*.parquet", "README.md"])
    c: Counter[str] = Counter()
    folders: Counter[str] = Counter()
    meta = []
    for pfile in sorted((dl / "data").glob("*.parquet")):
        split = pfile.name.split("-")[0]
        idx = 0
        for batch in pq.ParquetFile(pfile).iter_batches(
                batch_size=256, columns=["image", "safety_label", "category", "source"]):
            for row in batch.to_pylist():
                data = (row["image"] or {}).get("bytes")
                if not data:
                    c["rows without image bytes"] += 1
                    idx += 1
                    continue
                folder = f"{safe_folder(row['safety_label'] or 'unknown')}__{safe_folder(row['category'] or 'unknown')}"
                target = d / folder / f"{split}_{idx:05d}{image_ext(data)}"
                if target.is_file() and target.stat().st_size == len(data):
                    c["already exported"] += 1
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    tmp = target.with_name(target.name + ".part")
                    tmp.write_bytes(data)
                    os.replace(tmp, target)
                    c["exported"] += 1
                folders[folder] += 1
                meta.append({"file": f"{folder}/{target.name}", "split": split,
                             "safety_label": row["safety_label"], "category": row["category"],
                             "source": row["source"]})
                idx += 1
    with open(d / "_meta.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["file", "split", "safety_label", "category", "source"])
        w.writeheader()
        w.writerows(meta)
    print_counts(c)
    print("  images per folder:")
    for k, v in sorted(folders.items()):
        print(f"    {v:6d}  {k}")
    info = write_marker(d, "unsafebench")
    print(f"done: {info['files']} images, {info['bytes'] / 1e9:.2f} GB in {d} (labels in _meta.csv)")


# --- manual datasets ------------------------------------------------------------
def cmd_manual(name: str, args) -> None:
    d = args.root / name
    if not args.from_zip:
        print(MANUAL[name])
        return
    if already_done(d, args):
        return
    src = Path(args.from_zip)
    dl = d / "_download"
    dest_zip = dl / src.name
    if dest_zip.is_file() and not src.is_file():
        src = dest_zip  # moved on an earlier run
    if not src.is_file() or not zipfile.is_zipfile(src):
        raise SystemExit(f"not a zip file: {src}")
    with zipfile.ZipFile(src) as zf:
        c = safe_extract(zf, d, dry_run=True)
    print(f"zip: {src} ({src.stat().st_size / 1e9:.2f} GB)")
    if src != dest_zip:
        print(f"{'would move' if args.dry_run else 'moving'} zip -> {dest_zip}")
    print("plan:")
    print_counts(c)
    if args.dry_run:
        return
    dl.mkdir(parents=True, exist_ok=True)
    if src != dest_zip:
        shutil.move(str(src), dest_zip)
    with zipfile.ZipFile(dest_zip) as zf:
        c = safe_extract(zf, d)
    print("result:")
    print_counts(c)
    info = write_marker(d, name, zip=dest_zip.name)
    print(f"done: {info['files']} files, {info['bytes'] / 1e9:.2f} GB in {d}")


def cmd_status(args) -> None:
    done = 0
    for name in SOURCES:
        d = args.root / name
        m = read_marker(d)
        files, size = tree_stats(d) if d.is_dir() else (0, 0)
        state = "complete" if m else ("partial" if files else "missing")
        done += bool(m)
        print(f"  {name:14s} {state:9s} {files:7d} files {size / 1e9:7.2f} GB   {SOURCES[name]}")
    print(f"Summary: {done} of {len(SOURCES)} datasets complete")


# --- CLI -----------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="Download or place KidGuard datasets into data/raw/<name>/.")
    ap.add_argument("--root", type=Path, default=RAW)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_text):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--force", action="store_true", help="redo even if marked complete")
        p.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
        p.set_defaults(fn=fn)
        return p

    add("rlvs", cmd_rlvs, "Real Life Violence Situations (Kaggle, videos)")
    p = add("rico", cmd_rico, "Rico UI screenshots (Hugging Face), up to --limit")
    p.add_argument("--limit", type=int, default=20000)
    p.add_argument("--workers", type=int, default=8)
    add("nsfw_detect", cmd_nsfw_detect, "deepghs/nsfw_detect (gated) - data keeper only")
    add("unsafebench", cmd_unsafebench, "yiting/UnsafeBench (gated) - data keeper only")
    for name in MANUAL:
        p = add(name, lambda a, n=name: cmd_manual(n, a), f"{name}: manual; --from-zip to place the archive")
        p.add_argument("--from-zip", help="path to the archive you downloaded")
    sub.add_parser("status", help="show which datasets are complete").set_defaults(fn=cmd_status, force=False,
                                                                                     dry_run=False)
    args = ap.parse_args()

    if args.cmd == "status":
        args.fn(args)
        return 0
    before = free_gb(args.root)
    print(f"[{args.cmd}] disk free before: {before:.1f} GB")
    t0 = time.perf_counter()
    args.fn(args)
    after = free_gb(args.root)
    print(f"[{args.cmd}] disk free after: {after:.1f} GB (used {before - after:+.2f} GB) "
          f"in {time.perf_counter() - t0:.0f}s")
    files, size = tree_stats(args.root / args.cmd) if (args.root / args.cmd).is_dir() else (0, 0)
    print(f"Summary: {args.cmd}: {files} files, {size / 1e9:.2f} GB in {args.root / args.cmd}"
          f"{' (dry run, nothing changed)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
