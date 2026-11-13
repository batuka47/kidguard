"""Shared helpers for the KidGuard data scripts (metadata.csv, label map, names)."""

import csv
import fnmatch
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import yaml

CLASSES = ("safe", "nudity", "violence", "gore")
METADATA = Path("data/metadata.csv")
COLUMNS = ["path", "label", "source", "group_id", "split", "orig_label"]
IMAGES = Path("data/interim/images")
REJECTED = Path("data/interim/rejected")
BACKUPS = Path("data/interim/metadata_backups")
LABEL_MAP = Path("scripts/label_map.yaml")


def load_label_map(path: Path = LABEL_MAP) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("datasets", {})


def lookup(labels: dict, folder: str) -> str | None:
    """Our class for an original label folder; exact keys win over glob patterns."""
    if folder in labels:
        return labels[folder]
    for key, cls in labels.items():
        if any(ch in key for ch in "*?[") and fnmatch.fnmatchcase(folder, key):
            return cls
    return None


def safe_name(text: str) -> str:
    """File-name-safe version of a stem: anything but letters, digits, '.', '-' becomes '_'."""
    out = re.sub(r"[^A-Za-z0-9.\-]+", "_", text).strip("_")
    return out or "unnamed"


def read_metadata(path: Path = METADATA) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [{c: r.get(c, "") or "" for c in COLUMNS} for r in csv.DictReader(f)]


def write_metadata(rows: list[dict], dry_run: bool, path: Path = METADATA) -> None:
    """Back up the current file, then write rows sorted by path (atomic replace)."""
    if dry_run:
        return
    if path.is_file():
        BACKUPS.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, BACKUPS / f"metadata_{datetime.now():%Y%m%d_%H%M%S}.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["path"]))
    os.replace(tmp, path)


def upsert(existing: list[dict], new: list[dict]) -> tuple[list[dict], int, int]:
    """Merge rows by path. Returns (rows, added, updated)."""
    by_path = {r["path"]: r for r in existing}
    added = updated = 0
    for r in new:
        r = {c: r.get(c, "") or "" for c in COLUMNS}
        if r["path"] in by_path:
            if by_path[r["path"]] != r:
                updated += 1
            by_path[r["path"]] = r
        else:
            added += 1
            by_path[r["path"]] = r
    return list(by_path.values()), added, updated


def move_to_rejected(path: Path, reason: str, label: str, dry_run: bool) -> Path:
    """Move a file to data/interim/rejected/<reason>/<label>/ (never deletes, never overwrites)."""
    dest = REJECTED / reason / label / path.name
    if dry_run:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    stem, n = dest.stem, 1
    while dest.exists():
        dest = dest.with_name(f"{stem}_{n}{dest.suffix}")
        n += 1
    shutil.move(str(path), dest)
    return dest


def rel(path: Path) -> str:
    return Path(path).as_posix()
