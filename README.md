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

## Kaggle

Put your `kaggle.json` in `~/.kaggle/` (Windows: `C:\Users\<you>\.kaggle\`),
never in this repo.
