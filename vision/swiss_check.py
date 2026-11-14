"""Does the fine-tuned detector help on Swiss PNG pages? Diagnostic on 20 pages; GT = the DXF plan map's door/window counts (artifacts/<doc>/planmap-1.json, source dxf).
No tuning: cuts come from weights/onnx/det_cuts.json (picked on CubiCasa calibration). NOTE: every Swiss page in artifacts/ is in heldout_docs.txt (the question set references all 1,040), so
there is no non-held-out Swiss page; this is read-only scoring, nothing is trained or tuned on it.
  .venv/bin/python vision/swiss_check.py [--n 20] [--out results/vision/swiss_det_check.json]
"""
import argparse, json, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from PIL import Image
import build_planmaps as B, infer_det as D
ROOT = D.ROOT
ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=20); ap.add_argument("--out", default="results/vision/swiss_det_check.json"); a = ap.parse_args()
docs = sorted(d.name for d in (ROOT / "artifacts").glob("swiss_dwellings__*") if (d / "planmap-1.json").exists())[::max(1, 1040 // a.n)][:a.n]
det = D.DetOnnx(); rows = []
for d in docs:
    pm = json.loads((ROOT / f"artifacts/{d}/planmap-1.json").read_text()); g = Counter(i["kind"] for i in pm["items"] if i["source"] == "dxf")
    items = det.detect(Image.open(B.image_path(d)).convert("RGB")); p = Counter(i["kind"] for i in items)
    rows.append({"doc": d, "dxf": {k: g[k] for k in ("door", "window")}, "det": {k: p[k] for k in ("door", "window", "toilet", "sink")}})
res = {"n": len(rows), "gt": "DXF plan map counts", "weights": "weights/onnx/rtdetr.onnx", "cuts": det.cuts}
for k in ("door", "window"):
    res[k] = {"exact": round(sum(r["det"][k] == r["dxf"][k] for r in rows) / len(rows), 3), "within1": round(sum(abs(r["det"][k] - r["dxf"][k]) <= 1 for r in rows) / len(rows), 3),
              "mean_det": round(sum(r["det"][k] for r in rows) / len(rows), 1), "mean_dxf": round(sum(r["dxf"][k] for r in rows) / len(rows), 1)}
res["rows"] = rows; Path(a.out).write_text(json.dumps(res, indent=1)); print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=1))
