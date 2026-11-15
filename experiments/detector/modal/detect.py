"""Door / window / fixture detector as a Modal GPU function (supplement to the vector PDF->3D pipeline).
LOCAL ONLY: not pushed until Awais verifies it. ultralytics = AGPL-3.0: not served to app users until he decides.

    modal deploy detect.py                      # app "junction-det", function "detect"
    modal run detect.py --pdf plan.pdf --m-per-pt <m_per_pt>     # smoke test with a local PDF
Weights: volume "junction-det-weights", /weights/best.pt (see scripts/detector_up.sh).

Client (from the pipeline):
    import modal
    dets = modal.Cls.from_name("junction-det", "Detector")().detect.remote(pdf_bytes, page_index, m_per_pt)       # -> {"items": [...], "weights": ..., ...}
    # item: {"kind": "door"|"window"|"fixture", "bbox_pt": [x0, y0, x1, y1], "conf": 0.0-1.0}
    # bbox_pt is in PDF points, top-left origin, y down (the pdf_planmap / eval_svg_gold page frame).

Rendering matches training: 40 px per metre on paper scale, 1280 px tiles with stride 1024, one GPU batch,
class-wise NMS across tile overlaps. Per-class thresholds come from the run's result.json (picked on VAL), else 0.25.
Re-upload best.pt and the next container start uses it.
"""
import os

import modal

app = modal.App("junction-det")
# Weights live on OUR volume (upload with scripts/detector_up.sh): /weights/best.pt, optional /weights/result.json
# ({"conf": {"door": 0.4, ...}} per-class thresholds picked on VAL), else 0.25.
vol = modal.Volume.from_name("junction-det-weights", create_if_missing=True)
image = (modal.Image.debian_slim(python_version="3.12")
         .apt_install("libgl1", "libglib2.0-0")
         .pip_install("torch==2.5.1", "torchvision==0.20.1", "ultralytics==8.3.40", "opencv-python-headless==4.10.0.84",
                      "numpy==1.26.4", "pypdfium2==4.30.0", "pillow==11.0.0"))
CLS = ["door", "window", "fixture"]
PX_PER_M, TILE, STRIDE = 40.0, 1280, 1024
WEIGHTS = "/weights/best.pt"
THRESHOLDS = "/weights/result.json"


def _weights():
    """(path, per-class conf thresholds, run label) from the weights volume."""
    import json
    if not os.path.exists(WEIGHTS):
        raise FileNotFoundError(f"no weights at {WEIGHTS} on volume junction-det-weights (run scripts/detector_up.sh)")
    conf = json.load(open(THRESHOLDS)).get("conf", {}) if os.path.exists(THRESHOLDS) else {}
    return WEIGHTS, conf, "best"


# Cheap by default: T4/L4-class GPU, scales to zero, short scaledown. DET_GPU / DET_MIN_CONTAINERS override at deploy time.
@app.cls(image=image, gpu=os.environ.get("DET_GPU", "L4"), volumes={"/weights": vol}, timeout=300, scaledown_window=60,
         min_containers=int(os.environ.get("DET_MIN_CONTAINERS", "0")))
class Detector:
    @modal.enter()
    def load(self):
        from ultralytics import YOLO
        vol.reload()  # pick up a freshly uploaded best.pt
        self.path, self.conf, self.run = _weights()
        self.model = YOLO(self.path)

    @modal.method()
    def detect(self, pdf_bytes: bytes, page_index: int = 0, m_per_pt: float | None = None, min_conf: float | None = None,
               run: str | None = None) -> dict:  # `run` accepted for client compatibility; one weights file is served
        return self._detect(pdf_bytes, page_index, m_per_pt, min_conf)

    def _detect(self, pdf_bytes: bytes, page_index: int = 0, m_per_pt: float | None = None, min_conf: float | None = None) -> dict:
        import time
        import pypdfium2 as pdfium
        import torch
        from PIL import Image
        from torchvision.ops import batched_nms
        t0 = time.time()
        assumed = m_per_pt is None
        mpt = m_per_pt or 0.0254 / 72 * 100  # 1:100 when the caller has no scale
        s = PX_PER_M * mpt  # px per pt
        pg = pdfium.PdfDocument(pdf_bytes)[page_index]
        img = pg.render(scale=s).to_pil().convert("RGB")
        W, H = img.size
        xs = list(range(0, max(1, W - TILE) + 1, STRIDE)); ys = list(range(0, max(1, H - TILE) + 1, STRIDE))
        if xs[-1] + TILE < W:
            xs.append(W - TILE)
        if ys[-1] + TILE < H:
            ys.append(H - TILE)
        crops, offs = [], []
        for ty in ys:
            for tx in xs:
                tx, ty = max(0, tx), max(0, ty)
                c = Image.new("RGB", (TILE, TILE), "white")
                c.paste(img.crop((tx, ty, min(W, tx + TILE), min(H, ty + TILE))), (0, 0))
                crops.append(c); offs.append((tx, ty))
        boxes, scores, cls = [], [], []
        for i in range(0, len(crops), 32):
            for (tx, ty), r in zip(offs[i:i + 32], self.model.predict(crops[i:i + 32], imgsz=TILE, conf=0.05, verbose=False, half=True)):
                b = r.boxes.xyxy.cpu().clone(); b[:, [0, 2]] += tx; b[:, [1, 3]] += ty
                boxes.append(b); scores.append(r.boxes.conf.cpu()); cls.append(r.boxes.cls.cpu())
        if boxes:
            B, S, C = torch.cat(boxes), torch.cat(scores), torch.cat(cls)
            keep = batched_nms(B, S, C.long(), 0.5)
            B, S, C = B[keep], S[keep], C[keep]
        else:
            B, S, C = torch.zeros((0, 4)), torch.zeros(0), torch.zeros(0)
        items = []
        for b, sc, c in zip(B.tolist(), S.tolist(), C.tolist()):
            k = CLS[int(c)]
            if sc < (min_conf if min_conf is not None else self.conf.get(k, 0.25)):
                continue
            items.append({"kind": k, "bbox_pt": [round(v / s, 2) for v in b], "conf": round(sc, 3)})
        return {"items": items, "weights": self.path, "run": self.run, "thresholds": self.conf,
                "m_per_pt": mpt, "scale_assumed": assumed, "tiles": len(crops), "seconds": round(time.time() - t0, 2),
                "evidence": "model-detected (Hologram_Evidence Source=derived); never measured"}


@app.local_entrypoint()
def main(pdf: str, page: int = 0, m_per_pt: float = 0.0):
    """Smoke test: modal run detect.py --pdf some.pdf [--page 0] [--m-per-pt 0.0035]"""
    import collections, json
    r = Detector().detect.remote(open(pdf, "rb").read(), page, m_per_pt or None)
    print(json.dumps({k: v for k, v in r.items() if k != "items"}))
    print(collections.Counter(i["kind"] for i in r["items"]))
