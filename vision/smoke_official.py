"""V-00 smoke: official CubiCasa5K multi-task model (hg_furukawa_original). Needs weights/_src/CubiCasa5k-master code (CC BY-NC 4.0).

    uv run python vision/smoke_official.py [image] [--size 512]
Output: 44 ch = 21 heatmaps + 12 room classes + 11 icon classes (0 bg,1 Window,2 Door,3 Closet,4 ElectricalAppl,5 Toilet,6 Sink,7 SaunaBench,8 FireP,9 Bathtub,10 Chimney).
"""
import argparse, sys, time
from pathlib import Path
import numpy as np, torch
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "weights/_src/CubiCasa5k-master"))
from floortrans.models.hg_furukawa_original import hg_furukawa_original  # noqa: E402

ICONS = ["bg", "Window", "Door", "Closet", "ElectricalAppl", "Toilet", "Sink", "SaunaBench", "FireP", "Bathtub", "Chimney"]
ROOMS = ["bg", "Outdoor", "Wall", "Kitchen", "Living", "Bed", "Bath", "Entry", "Storage", "Garage", "Undefined", "Railing"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?", default=str(ROOT / "data/junction-dataset-preview/data/cubicasa5k/colorful-11397.png"))
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--device", default="auto")
    a = ap.parse_args()
    dev = torch.device(("mps" if torch.backends.mps.is_available() else "cpu") if a.device == "auto" else a.device)
    m = hg_furukawa_original(n_classes=51)  # constructor shape, replaced below
    m.conv4_ = torch.nn.Conv2d(256, 44, bias=True, kernel_size=1)
    m.upsample = torch.nn.ConvTranspose2d(44, 44, kernel_size=4, stride=4)
    m.load_state_dict(torch.load(ROOT / "weights/cubicasa_official/model_best_val_loss_var.pkl", map_location="cpu", weights_only=False)["model_state"])
    m = m.to(dev).eval()
    img = Image.open(a.image).convert("RGB")
    W, H = img.size
    x = np.asarray(img.resize((a.size, a.size), Image.BILINEAR), dtype=np.float32) / 255  # official pipeline: [-1,1] scaling
    x = torch.from_numpy(2 * (x - 0.5)).permute(2, 0, 1)[None].to(dev)
    def run():
        with torch.no_grad():
            y = m(x)
            if dev.type == "mps": torch.mps.synchronize()
        return y[0].cpu()
    run(); t = time.perf_counter(); y = run(); dt = time.perf_counter() - t
    rooms = y[21:33].argmax(0).numpy(); icons = y[33:44].argmax(0).numpy()
    import cv2
    comp = {}
    for i, n in enumerate(ICONS[1:], 1):
        k, _, st, _ = cv2.connectedComponentsWithStats((icons == i).astype(np.uint8))[0:4]
        comp[n] = int(sum(1 for r in st[1:] if r[4] >= 20))
    print(f"device={dev} time_per_image={dt:.3f}s icon_components(>=20px)={comp}")
    pal = np.random.RandomState(0).randint(30, 255, (12, 3)).astype(np.uint8); pal[0] = 255
    ov = (0.5 * np.asarray(img.resize((a.size, a.size))) + 0.5 * pal[rooms]).astype(np.uint8)
    out = ROOT / "artifacts/vision_smoke"; out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(ov).save(out / f"{Path(a.image).stem}_official_rooms.png")
    print("wrote", out / f"{Path(a.image).stem}_official_rooms.png")

if __name__ == "__main__":
    main()
