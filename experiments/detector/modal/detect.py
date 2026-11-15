"""Door / window / fixture detector as a Modal GPU function (supplement to the vector PDF->3D pipeline).
LOCAL ONLY: not pushed until Awais verifies it. ultralytics = AGPL-3.0: not served to app users until he decides.

    modal deploy detect.py                      # app "junction-det", function "detect"
    modal run detect.py --pdf-vol /private/private-a.pdf --m-per-pt <m_per_pt>     # smoke test on a volume file

Client (from the pipeline):
    import modal
    dets = modal.Cls.from_name("junction-det", "Detector")().detect.remote(pdf_bytes, page_index, m_per_pt)       # -> {"items": [...], "weights": ..., ...}
    # item: {"kind": "door"|"window"|"fixture", "bbox_pt": [x0, y0, x1, y1], "conf": 0.0-1.0}
    # bbox_pt is in PDF points, top-left origin, y down (the pdf_planmap / eval_svg_gold page frame).

Rendering matches training: 40 px per metre on paper scale, 1280 px tiles with stride 1024, one GPU batch,
class-wise NMS across tile overlaps. Per-class thresholds come from the run's result.json (picked on VAL), else 0.25.
The newest weights on the volume are used, so retrains drop in with no code change.
"""
import os

import modal

app = modal.App("junction-det")
vol = modal.Volume.from_name("junction-ds")
image = (modal.Image.debian_slim(python_version="3.12")
         .apt_install("libgl1", "libglib2.0-0")
         .pip_install("torch==2.5.1", "torchvision==0.20.1", "ultralytics==8.3.40", "opencv-python-headless==4.10.0.84",
                      "numpy==1.26.4", "pypdfium2==4.30.0", "pillow==11.0.0"))
CLS = ["door", "window", "fixture"]
PX_PER_M, TILE, STRIDE = 40.0, 1280, 1024
RUNS = ("y11l_clean", "y11l")  # preferred first


def _weights():
    """Newest FINISHED run (result.json present: thresholds picked on val) in RUNS order; else any best/last.pt."""
    import json, os
    for need_done in (True, False):
        for run in RUNS:
            rj = f"/ds/runs/{run}/result.json"
            if need_done and not os.path.exists(rj):
                continue
            for w in ("best.pt", "last.pt"):
                p = f"/ds/runs/{run}/weights/{w}"
                if os.path.exists(p):
                    conf = json.load(open(rj)).get("conf", {}) if os.path.exists(rj) else {}
                    return p, conf, run
    raise FileNotFoundError("no weights on junction-ds yet")


@app.cls(image=image, gpu="H100", volumes={"/ds": vol}, timeout=900, scaledown_window=300)
class Detector:
    @modal.enter()
    def load(self):
        from ultralytics import YOLO
        vol.reload()
        self.path, self.conf, self.run = _weights()
        self.model = YOLO(self.path)

    @modal.method()
    def detect_vol(self, path: str, m_per_pt: float | None = None) -> dict:
        """Same as detect() for a PDF already on the junction-ds volume (smoke tests)."""
        return self._detect(open("/ds" + path, "rb").read(), 0, m_per_pt, None)

    @modal.method()
    def detect(self, pdf_bytes: bytes, page_index: int = 0, m_per_pt: float | None = None, min_conf: float | None = None) -> dict:
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
def main(pdf_vol: str, m_per_pt: float = 0.0):
    import collections, json
    r = Detector().detect_vol.remote(pdf_vol, m_per_pt or None)
    print(json.dumps({k: v for k, v in r.items() if k != "items"}))
    print(collections.Counter(i["kind"] for i in r["items"]))
