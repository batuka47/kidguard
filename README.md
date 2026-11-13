# KidGuard

On-device AI that detects harmful content on a child's Android screen
(`safe` / `nudity` / `violence` / `gore`), blurs or blocks it, and notifies
the parent. Models are trained in PyTorch and run on the phone as TFLite.

## Setup

Requires Python 3.11 or newer. The `venv/` folder is gitignored.

### Windows (PowerShell)

```powershell
py -3.14 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip

# 1) torch + torchvision with CUDA 13.0 (PyPI only has CPU builds for Windows).
#    cu130 is needed for RTX 50-series (Blackwell) GPUs.
python -m pip install "torch>=2.14,<2.15" "torchvision>=0.29,<0.30" --index-url https://download.pytorch.org/whl/cu130

# 2) everything else
python -m pip install -r requirements.txt

# 3) check
python scripts\check_env.py
```

If `Activate.ps1` is blocked, run this once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

**Always use `python -m <tool>`, not `<tool>.exe`, on Windows.** With
Windows 11 Smart App Control on, the unsigned launchers in `venv\Scripts\`
(`pip.exe`, `jupyter.exe`, `kaggle.exe`, `hf.exe`, ...) are blocked with
"An Application Control policy has blocked this file". `python.exe` is signed,
so `python -m pip ...` works.

### Linux

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip

# PyPI torch on Linux already includes CUDA.
# CPU-only machine: first run
#   pip install "torch>=2.14,<2.15" "torchvision>=0.29,<0.30" --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

python scripts/check_env.py
```

### TFLite export environment (Phase 7 only)

`requirements-export.txt` installs `litert-torch` (PyTorch -> TFLite converter)
and `ai-edge-litert` (TFLite runtime). It works only on Linux, Colab or WSL2,
because the converter has no Windows wheels. We use WSL2 (or Colab).

**Python version: use Python 3.12 in WSL2.** All export packages ship Linux
wheels for 3.11-3.14, but 3.12 is the version the converter
(`litert-converter`) has supported the longest, and it is the system Python
on Ubuntu 24.04. 3.13 also works; avoid 3.10 (below this project's 3.11 minimum).

Use a fresh environment, separate from the Windows `venv/`. Keep it inside the
WSL2 home folder (not under `/mnt/c/`) because pip installs are much faster there:

```bash
# WSL2, Ubuntu 24.04
sudo apt install python3.12-venv
python3.12 -m venv ~/kidguard-export
source ~/kidguard-export/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-export.txt
```

On Colab, use the runtime's Python and run `pip install -r requirements-export.txt`.

## Phase 1: desktop prototype

Pretrained models only (no training yet). The first run downloads about 1.3 GB
of models into the Hugging Face cache, outside this repo.

```powershell
# live: screen -> detector -> blur/block overlay; quit with Ctrl+Shift+Q
python prototype\main.py

# score the detector on prototype\test_images\<class>\ with both violence options
python prototype\eval_folder.py prototype\test_images --violence-backend both
```

Settings (fps, thresholds, violence backend `vit` or `clip`) are in
`prototype/config.yaml`. Every decision is logged to `reports/prototype_log.csv`.

## Phase 2: datasets

```powershell
python scripts\download.py status            # what is downloaded
python scripts\download.py rlvs              # Kaggle, videos
python scripts\download.py rico --limit 20000
python scripts\inventory.py                  # counts per label folder -> reports\inventory.md
```

`nsfw_detect` and `unsafebench` contain adult content, so only the data keeper
runs them (CLAUDE.md). Manual datasets (`adult_content`, `npdi`, `fs_lspd`):
run the subcommand without arguments for instructions, then place the archive
with `--from-zip`. Original labels are mapped to our classes in
`scripts/label_map.yaml`.

Not used: WVD (GTA V footage; game violence is safe in our policy), RWF-2000
(withdrawn by its authors), Movies/Hockey Fight (official page offline).

## Phase 3: frames + cleaning

Run in this order (each script has `--dry-run`):

```powershell
python scripts\extract_frames.py    # video -> frames (1/s, max 8, middle 80%)
python scripts\import_images.py     # image datasets -> data\interim\images\<class>\
python scripts\clean_basic.py       # reject broken/tiny/flat; RGB JPEG, long side <= 512
python scripts\dedup.py             # phash: label conflicts, duplicates
python scripts\rename_to_hash.py    # Pixiv-ID names -> content hashes (before committing metadata.csv)
python scripts\stats.py             # -> reports\stats.md
```

Labels end up in `data/metadata.csv` (`path,label,source,group_id,split,orig_label`).
Rejected files are moved to `data\interim\rejected\<reason>\`, never deleted.

## Kaggle

Put your `kaggle.json` in `~/.kaggle/` (Windows: `C:\Users\<you>\.kaggle\`),
never in this repo.
