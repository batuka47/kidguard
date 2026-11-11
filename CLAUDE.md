# KidGuard — instructions for Claude

KidGuard is an AI system that watches what is on a child's Android phone
screen, blurs/blocks harmful content, and notifies the parent.
Inference runs ON THE PHONE (TFLite). Training runs on the laptop (Windows,
RTX 5070 Ti) or Colab. Built by two university students in Mongolia.

## PERMANENT RULES (apply in every session)

### Classes and labels
- Exactly four classes: `safe`, `nudity`, `violence`, `gore`.
- Labels live in `data/metadata.csv` with columns:
  `path,label,source,group_id,split`

### Data sourcing
- NEVER scrape or download adult/explicit content from websites. Only use the
  datasets the user downloads into `data/raw/`.

### Handling nudity data
- NEVER open, view, render or describe any image under a `nudity` folder or
  labelled `nudity`. Handle them only via code (counts, sizes, hashes, file ops).
- This includes: the Read tool on those files, thumbnails, contact sheets,
  sample grids, and any PNG in `reports/` that would contain such images.

### Git
- Never commit data, weights, tokens or `kaggle.json`.
- `data/metadata.csv` IS committed (the one exception under `data/`).
  Before committing it, check whether any filenames from the nudity sources are
  descriptive words. If they are, rename those files to content hashes (with a
  script that follows the rules below, `--dry-run` first), update
  `metadata.csv`, and only then commit.

### Every script
- argparse CLI.
- `--dry-run` wherever it moves/deletes/renames files.
- Prints a summary with counts at the end.
- Never deletes: moves rejects to `data/interim/rejected/`.

### Workflow
- Before coding a phase: show a short plan and wait for the user's OK.
- After running anything: report the real numbers, not guesses.

## Environments
- `requirements.txt`: training, data prep, desktop prototype. Windows + Linux.
  On Windows, torch/torchvision come from the PyTorch cu130 index (see README).
- `requirements-export.txt`: PyTorch -> TFLite export (`litert-torch`,
  `ai-edge-litert`). Installed ONLY in Phase 7, on Linux/Colab/WSL2
  (no Windows wheels).
- torch is pinned to 2.14.x in both, because litert-torch 0.10 requires
  torch < 2.15.

## Layout
```
data/raw/        datasets as downloaded by the user        (gitignored)
data/interim/    intermediate files; rejected/ for rejects  (gitignored)
data/processed/  final train/val/test images                (gitignored)
data/metadata.csv  labels + splits                          (committed)
scripts/         data prep scripts
training/        train / eval code
prototype/       desktop demo (mss screen capture + PyQt6 overlay)
android/         Android app (later)
models/          .pt / .onnx / .tflite                      (gitignored)
reports/         metrics, confusion matrices, small PNGs only
notebooks/       Colab / Jupyter notebooks
```
