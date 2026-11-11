"""Print the KidGuard environment: Python, torch, CUDA, GPU and free disk space.

Usage:
    python scripts/check_env.py
    python scripts/check_env.py --path D:/datasets
"""

import argparse
import platform
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GB = 1024**3  # same unit Windows Explorer shows as "GB"
LOW_DISK_GB = 50  # datasets + processed copies need room


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print Python/torch/CUDA/GPU versions and free disk space."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=REPO_ROOT,
        help="Folder whose drive is checked for free space (default: repo root).",
    )
    args = parser.parse_args()

    warnings: list[str] = []
    rows: list[tuple[str, str]] = []

    # Python
    rows.append(("Python", f"{platform.python_version()} ({sys.executable})"))

    # torch / CUDA / GPU
    try:
        import torch
    except ImportError:
        torch = None

    if torch is None:
        rows.append(("torch", "NOT INSTALLED"))
        rows.append(("CUDA available", "n/a"))
        rows.append(("GPU", "n/a"))
        warnings.append("torch is not installed (see README.md setup).")
    else:
        rows.append(("torch", torch.__version__))
        cuda_ok = torch.cuda.is_available()
        built_for = torch.version.cuda or "none (CPU-only build)"
        rows.append(("CUDA available", f"{cuda_ok} (torch built for CUDA {built_for})"))
        if cuda_ok:
            names = [
                f"{torch.cuda.get_device_name(i)} "
                f"({torch.cuda.get_device_properties(i).total_memory / GB:.1f} GB)"
                for i in range(torch.cuda.device_count())
            ]
            rows.append(("GPU", "; ".join(names)))
            # is_available() can be True while kernels for this GPU are
            # missing, so run one real op on the GPU.
            try:
                x = torch.randn(256, 256, device="cuda")
                (x @ x).sum().item()
                rows.append(("GPU smoke test", "OK (matmul on cuda:0)"))
            except Exception as exc:  # noqa: BLE001
                rows.append(("GPU smoke test", f"FAILED: {exc}"))
                warnings.append("CUDA is visible but a GPU op failed.")
        else:
            rows.append(("GPU", "none visible to torch"))
            warnings.append("CUDA not available; training would run on CPU.")

    # Disk
    target = args.path if args.path.exists() else REPO_ROOT
    usage = shutil.disk_usage(target)
    free_gb = usage.free / GB
    rows.append(
        ("Free disk", f"{free_gb:.1f} GB free of {usage.total / GB:.1f} GB (drive of {target})")
    )
    if free_gb < LOW_DISK_GB:
        warnings.append(f"Less than {LOW_DISK_GB} GB free.")

    width = max(len(k) for k, _ in rows)
    print("KidGuard environment check")
    print("-" * 60)
    for key, value in rows:
        print(f"{key:<{width}} : {value}")
    print("-" * 60)
    for w in warnings:
        print(f"WARNING: {w}")
    print(f"Summary: {len(rows)} items checked, {len(warnings)} warning(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
