"""V-00 smoke test: run the ResNet34-UNet floor-plan segmenter on one cubicasa5k PNG.

    uv run python vision/smoke.py [image] [--device mps|cpu] [--size 512]

Writes artifacts/vision_smoke/<stem>_{mask,overlay}.png and prints time per image.
Weights: weights/yytsi_unet/best.safetensors (Yytsi/floorplan-to-3d-walls, MIT).
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from safetensors.torch import load_file

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from unet_resnet34 import CLASS_NAMES, UNetResNet34  # noqa: E402

COLORS = np.array([(0, 0, 0), (40, 40, 45), (230, 120, 50), (60, 150, 220)], dtype=np.uint8)
MEAN, STD = np.array([0.485, 0.456, 0.406]), np.array([0.229, 0.224, 0.225])
DEFAULT_IMG = ROOT / "data/junction-dataset-preview/data/cubicasa5k/colorful-11397.png"


def letterbox(img: Image.Image, size: int):
    w, h = img.size
    s = size / max(w, h)
    nw, nh = round(w * s), round(h * s)
    canvas = Image.new("RGB", (size, size), tuple(int(m * 255) for m in MEAN))  # ImageNet-mean fill as in training
    ox, oy = (size - nw) // 2, (size - nh) // 2
    canvas.paste(img.resize((nw, nh), Image.BILINEAR), (ox, oy))
    return canvas, (ox, oy, nw, nh)


def load_model(device):
    m = UNetResNet34(len(CLASS_NAMES))
    m.load_state_dict(load_file(str(ROOT / "weights/yytsi_unet/best.safetensors")), strict=True)
    return m.to(device).eval()


def predict(model, img: Image.Image, size: int, device) -> np.ndarray:
    """Return class-id mask (H, W) at the original image resolution."""
    box_img, (ox, oy, nw, nh) = letterbox(img, size)
    x = ((np.asarray(box_img, dtype=np.float32) / 255 - MEAN) / STD).transpose(2, 0, 1)
    with torch.no_grad():
        logits = model(torch.from_numpy(x).float().unsqueeze(0).to(device))
        if device.type == "mps":
            torch.mps.synchronize()
        cls = logits.argmax(1)[0].cpu().numpy().astype(np.uint8)
    cls = cls[oy:oy + nh, ox:ox + nw]
    return np.asarray(Image.fromarray(cls).resize(img.size, Image.NEAREST))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", default=str(DEFAULT_IMG))
    ap.add_argument("--device", default="auto")
    ap.add_argument("--size", type=int, default=512)
    a = ap.parse_args()
    dev = torch.device(("mps" if torch.backends.mps.is_available() else "cpu") if a.device == "auto" else a.device)
    img = Image.open(a.image).convert("RGB")
    model = load_model(dev)
    predict(model, img, a.size, dev)  # warm-up
    t = time.perf_counter()
    mask = predict(model, img, a.size, dev)
    dt = time.perf_counter() - t

    out = ROOT / "artifacts/vision_smoke"
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(a.image).stem
    Image.fromarray(COLORS[mask]).save(out / f"{stem}_mask.png")
    base = np.asarray(img, dtype=np.float32)
    ov = np.where((mask > 0)[..., None], 0.45 * base + 0.55 * COLORS[mask], base).astype(np.uint8)
    Image.fromarray(ov).save(out / f"{stem}_overlay.png")
    frac = {n: round(float((mask == i).mean()), 4) for i, n in enumerate(CLASS_NAMES)}
    print(f"device={dev} image={img.size} size={a.size} time_per_image={dt:.3f}s pixel_fractions={frac}")
    print(f"wrote {out / (stem + '_overlay.png')}")


if __name__ == "__main__":
    main()
