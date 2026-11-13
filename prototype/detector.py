"""KidGuard Phase 1 detector: PIL image -> {safe, nudity, violence, gore} probabilities.

Pretrained models only (no training in Phase 1):
  nudity    Falconsai/nsfw_image_detection (labels normal / nsfw)
  violence  backend "vit":  jaranohaal/vit-base-violence-detection
            backend "clip": CLIP zero-shot, "people fighting" prompt
  gore      CLIP zero-shot, "blood and injuries" prompt
  safe      1 - max(nudity, violence, gore)

The models are separate, so the four numbers do not sum to 1.

Note: the jaranohaal checkpoint is a timm ViT-B/16 saved under a transformers
repo. transformers cannot map its weights (it would silently use random
weights), so it is loaded with timm and strict key checking.

Demo:
    python prototype/detector.py path/to/image.png
"""

import argparse
import os
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import numpy as np  # noqa: E402
import timm  # noqa: E402
import torch  # noqa: E402
import yaml  # noqa: E402
from huggingface_hub import hf_hub_download  # noqa: E402
from PIL import Image  # noqa: E402
from safetensors.torch import load_file  # noqa: E402
from transformers import (  # noqa: E402
    AutoImageProcessor,
    AutoModelForImageClassification,
    CLIPModel,
    CLIPProcessor,
)
from huggingface_hub.utils import logging as hub_logging  # noqa: E402
from transformers.utils import logging as hf_logging  # noqa: E402

hf_logging.set_verbosity_error()
hf_logging.disable_progress_bar()
hub_logging.set_verbosity_error()

CLASSES = ("safe", "nudity", "violence", "gore")
UNSAFE = ("nudity", "violence", "gore")
BACKENDS = ("vit", "clip")
DEFAULT_CONFIG = Path(__file__).with_name("config.yaml")


def load_config(path: str | Path | None = None) -> dict:
    with open(path or DEFAULT_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def pick_device(name: str) -> torch.device:
    if name == "auto":
        name = "cuda" if torch.cuda.is_available() else "cpu"
    return torch.device(name)


class Detector:
    def __init__(self, cfg: dict, violence_backend: str | None = None, load_all: bool = False):
        """load_all=True loads both violence backends (used by eval_folder.py --violence-backend both)."""
        d = cfg["detector"]
        self.backend = violence_backend or d["violence_backend"]
        if self.backend not in BACKENDS:
            raise ValueError(f"violence_backend must be one of {BACKENDS}, got {self.backend!r}")
        self.device = pick_device(d.get("device", "auto"))
        self.total_ms = 0.0
        self.frames = 0

        # nudity
        self.nsfw_proc = AutoImageProcessor.from_pretrained(d["nsfw_model"])
        self.nsfw = AutoModelForImageClassification.from_pretrained(d["nsfw_model"]).to(self.device).eval()
        labels = {v.lower(): int(k) for k, v in self.nsfw.config.id2label.items()}
        self.nsfw_index = labels["nsfw"]

        # CLIP (gore always, violence when backend == "clip")
        self.clip_proc = CLIPProcessor.from_pretrained(d["clip_model"])
        self.clip = CLIPModel.from_pretrained(d["clip_model"]).to(self.device).eval()
        prompts, owner = [], []
        for cls, texts in d["clip_prompts"].items():
            prompts += texts
            owner += [cls] * len(texts)
        self.clip_owner = np.array(owner)
        tok = self.clip_proc(text=prompts, return_tensors="pt", padding=True)
        self.clip_text = {k: v.to(self.device) for k, v in tok.items()}

        # violence ViT (timm checkpoint)
        self.vit = None
        if self.backend == "vit" or load_all:
            weights = load_file(hf_hub_download(d["vit_violence_model"], "model.safetensors"))
            self.vit = timm.create_model("vit_base_patch16_224", pretrained=False, num_classes=2)
            self.vit.load_state_dict(weights, strict=True)
            self.vit.to(self.device).eval()
            self.vit_index = int(d["vit_violence_index"])

        # One untimed pass: the first GPU call pays one-off CUDA/cuDNN set-up costs.
        self.raw_scores(Image.new("RGB", (640, 360), (128, 128, 128)))

    # -- raw model outputs ------------------------------------------------------
    @torch.inference_mode()
    def raw_scores(self, img: Image.Image) -> dict:
        img = img.convert("RGB")
        out = {}

        x = self.nsfw_proc(images=img, return_tensors="pt")["pixel_values"].to(self.device)
        out["nsfw"] = torch.softmax(self.nsfw(pixel_values=x).logits, -1)[0, self.nsfw_index].item()

        pv = self.clip_proc(images=img, return_tensors="pt")["pixel_values"].to(self.device)
        probs = torch.softmax(self.clip(pixel_values=pv, **self.clip_text).logits_per_image, -1)[0].cpu().numpy()
        for cls in set(self.clip_owner):
            out[f"clip_{cls}"] = float(probs[self.clip_owner == cls].sum())

        if self.vit is not None:
            arr = np.asarray(img.resize((224, 224), Image.BILINEAR), dtype=np.float32) / 255.0
            t = torch.from_numpy((arr - 0.5) / 0.5).permute(2, 0, 1).unsqueeze(0).to(self.device)
            p = torch.softmax(self.vit(t), -1)[0]
            out["vit_violence"] = p[self.vit_index].item()
            out["vit_index1"] = p[1].item()  # raw, for checking the label index
        return out

    def combine(self, raw: dict, backend: str | None = None) -> dict:
        backend = backend or self.backend
        violence = raw["vit_violence"] if backend == "vit" else raw["clip_violence"]
        probs = {"nudity": raw["nsfw"], "violence": violence, "gore": raw["clip_gore"]}
        probs["safe"] = 1.0 - max(probs.values())
        return {c: probs[c] for c in CLASSES}

    # -- public API ---------------------------------------------------------------
    def predict(self, img: Image.Image) -> dict:
        t0 = time.perf_counter()
        probs = self.combine(self.raw_scores(img))
        self.total_ms += (time.perf_counter() - t0) * 1000
        self.frames += 1
        return probs

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.frames if self.frames else 0.0


def top_class(probs: dict) -> tuple[str, float]:
    cls = max(probs, key=probs.get)
    return cls, probs[cls]


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the detector on image files.")
    ap.add_argument("images", nargs="+", type=Path)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--violence-backend", choices=BACKENDS)
    args = ap.parse_args()

    det = Detector(load_config(args.config), args.violence_backend)
    print(f"device: {det.device}, violence backend: {det.backend}")
    for p in args.images:
        probs = det.predict(Image.open(p))
        cls, prob = top_class(probs)
        print(f"{p.name}: top={cls} {prob:.3f}  " + "  ".join(f"{c}={v:.3f}" for c, v in probs.items()))
    print(f"Summary: {det.frames} images, average {det.avg_ms:.1f} ms per image (inference incl. preprocessing)")


if __name__ == "__main__":
    main()
