"""V-08 integration: fine-tuned RT-DETR via ONNX Runtime (CPU), planmap item format.

  from infer_det import DetOnnx, recount
  det = DetOnnx()                                   # weights/onnx/rtdetr.onnx + weights/onnx/det_cuts.json (cuts picked on calibration drawings)
  items = det.detect(pil_image)                     # list of planmap items (kind, bbox_px, conf, source="det"), cuts + duplicate merge applied
  pm2 = recount(pm, pil_image, det)                 # copy of a planmap with its door/window/toilet/sink/shower/bathtub items replaced

CLI:
  .venv/bin/python vision/infer_det.py DOC_ID ...   # prints per-kind counts, planmap-1 (baseline) vs fine-tuned
  .venv/bin/python vision/infer_det.py --parity DOC_ID ...   # torch(HF dir) vs ONNX final detections
Preprocessing = RTDetrImageProcessor (square resize to 1024 bilinear, /255, no normalisation). Post-processing = HF's: sigmoid, top-300 over (query x class).
Batch 1..4 supported (the ONNX graph has a dynamic batch axis only if exported with it; this class loops batch 1 otherwise).
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
KINDS = ["door", "window", "toilet", "sink", "shower", "bathtub"]  # id2label order from training; read from det_classes.json when present
SIZE = 1024


class DetOnnx:
    def __init__(self, onnx_path=None, cuts_path=None, floor=0.2):
        import onnxruntime as ort
        o = ort.SessionOptions(); o.intra_op_num_threads = int(__import__("os").environ.get("OMP_NUM_THREADS", 4))
        self.s = ort.InferenceSession(str(onnx_path or ROOT / "weights/onnx/rtdetr.onnx"), o, providers=["CPUExecutionProvider"])
        cp = Path(cuts_path or ROOT / "weights/onnx/det_cuts.json")
        self.cuts = json.loads(cp.read_text()) if cp.exists() else {}
        kp = ROOT / "weights/onnx/det_classes.json"
        self.kinds = json.loads(kp.read_text()) if kp.exists() else KINDS
        self.floor = floor

    def _x(self, img):
        a = np.asarray(img.convert("RGB").resize((SIZE, SIZE), Image.BILINEAR), np.float32) / 255.0
        return a.transpose(2, 0, 1)[None]

    def raw(self, imgs):
        """Raw detections above `floor`, one list per image: dicts kind, conf, box (normalised cx,cy,w,h -> xyxy in 0..1)."""
        out = []
        for img in imgs:
            logits, boxes = self.s.run(None, {"x": self._x(img)})
            p = 1 / (1 + np.exp(-logits[0]))                      # (Q, C)
            flat = p.reshape(-1); top = np.argsort(-flat)[:300]
            res = []
            for idx in top:
                sc = float(flat[idx])
                if sc < self.floor: break
                q, c = divmod(int(idx), p.shape[1]); cx, cy, w, h = boxes[0][q]
                res.append({"kind": self.kinds[c], "conf": round(sc, 3), "box": [float(cx - w / 2), float(cy - h / 2), float(cx + w / 2), float(cy + h / 2)]})
            out.append(res)
        return out

    def detect(self, img, cuts=None, dedupe=True):
        return self.detect_many([img], cuts, dedupe)[0]

    def detect_many(self, imgs, cuts=None, dedupe=True):
        cuts = cuts or self.cuts
        res = []
        for img, dets in zip(imgs, self.raw(imgs)):
            W, H = img.size
            items = [dict(kind=d["kind"], label=None, bbox_px=[round(max(0, d["box"][0]) * W, 1), round(max(0, d["box"][1]) * H, 1), round(min(1, d["box"][2]) * W, 1), round(min(1, d["box"][3]) * H, 1)],
                          polygon_px=None, props={"model": "rtdetr-ft"}, conf=d["conf"], source="det") for d in dets if d["conf"] >= cuts.get(d["kind"], 0.5)]
            if dedupe:
                import verify as V
                items = V.rule_dup(items, W, H, {**V.DEFAULTS, **V.FREE})
            res.append(items)
        return res


def recount(pm, img, det, cuts=None, only=None):
    """Planmap copy: walls/rooms/text kept, the six detector kinds replaced by the fine-tuned detections (only=("shower","bathtub") swaps just those kinds); item_ids renumbered per kind (same scheme as planmap.assemble)."""
    only = set(only or KINDS)   # kinds taken from the detector; every other kind (incl. the remaining detector kinds) stays as in the plan map
    items = [i for i in pm["items"] if i["kind"] not in only] + [i for i in det.detect(img, cuts) if i["kind"] in only]
    counters, out = {}, []
    for it in sorted(items, key=lambda i: (i["kind"], i["bbox_px"][1], i["bbox_px"][0])):
        counters[it["kind"]] = counters.get(it["kind"], 0) + 1
        out.append({**it, "item_id": f"{it['kind']}-{counters[it['kind']]:03d}"})
    prov = dict(pm.get("provenance", {})); prov["models"] = {**prov.get("models", {}), "det": "rtdetr-r50vd-ft (onnx)"}
    return {**pm, "items": out, "provenance": prov}


def _count(items):
    from collections import Counter
    c = Counter(i["kind"] for i in items)
    return {"door": c["door"], "window": c["window"], "toilet": c["toilet"], "sink": c["sink"], "shower_bathtub": c["shower"] + c["bathtub"]}


if __name__ == "__main__":
    import build_planmaps as B
    args = sys.argv[1:]; parity = "--parity" in args; docs = [a for a in args if not a.startswith("--")]
    det = DetOnnx()
    for d in docs:
        img = Image.open(B.image_path(d)).convert("RGB"); pm = json.loads((ROOT / f"artifacts/{d}/planmap-1.json").read_text())
        new = recount(pm, img, det)
        print(d, "baseline", _count(pm["items"]), "finetuned", _count(new["items"]))
        if parity:
            import torch
            from transformers import RTDetrForObjectDetection, RTDetrImageProcessor
            hf = sys.argv[sys.argv.index("--parity") + 1] if False else str(ROOT / "weights/rtdetr_ft")
            if not Path(hf).exists(): hf = str(ROOT / "weights/rtdetr_ep")
            proc = RTDetrImageProcessor.from_pretrained(hf, size={"height": SIZE, "width": SIZE}, do_resize=True); m = RTDetrForObjectDetection.from_pretrained(hf).eval()
            with torch.no_grad(): o = m(pixel_values=proc(images=img, return_tensors="pt")["pixel_values"])
            r = proc.post_process_object_detection(o, threshold=0.3, target_sizes=torch.tensor([[1.0, 1.0]]))[0]
            a = sorted((m.config.id2label[int(l)], round(float(s), 2)) for s, l in zip(r["scores"], r["labels"]))
            b = sorted((x["kind"], round(x["conf"], 2)) for x in det.raw([img])[0] if x["conf"] >= 0.3)
            print("  parity: torch", len(a), "onnx", len(b), "max conf diff", max([abs(x[1] - y[1]) for x, y in zip(a, b)] or [0]), "same kinds", [x[0] for x in a] == [x[0] for x in b])
