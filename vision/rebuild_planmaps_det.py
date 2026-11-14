"""Rebuild planmaps with the fine-tuned detector (ONNX, CPU). Keeps walls/rooms/text from the existing planmap-1.json, replaces the six detector kinds.

  scripts/heavy.sh .venv/bin/python vision/rebuild_planmaps_det.py --list ids.txt [--procs 3] [--out-name planmap-det.json] [DOC_ID ...]
Default writes artifacts/<doc>/planmap-det.json (non-destructive; the baseline planmap-1.json is untouched). Use --out-name planmap-1.json only after LEAD/ENGINE
decide to switch (the old file is first copied to planmap-1.base.json once). <=3 worker processes, 1 ORT thread each, niced.
"""
import argparse, json, os, shutil, sys
from multiprocessing import Pool
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
ROOT = Path(__file__).resolve().parent.parent
_det = None


def _work(args):
    d, name, only = args
    global _det
    from PIL import Image
    import build_planmaps as B, infer_det as D
    if _det is None:
        os.nice(5); _det = D.DetOnnx()
    src = ROOT / f"artifacts/{d}/planmap-1.json"
    if not src.exists():
        return d, "no planmap-1"
    pm = json.loads(src.read_text())
    new = D.recount(pm, Image.open(B.image_path(d)).convert("RGB"), _det, only=only)
    out = ROOT / f"artifacts/{d}/{name}"
    if name == "planmap-1.json" and not (out.parent / "planmap-1.base.json").exists():
        shutil.copy(src, out.parent / "planmap-1.base.json")
    out.write_text(json.dumps(new))
    return d, "ok"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("docs", nargs="*"); ap.add_argument("--list"); ap.add_argument("--procs", type=int, default=3); ap.add_argument("--kinds", default="shower,bathtub", help="detector kinds to take from the fine-tuned model (default: the only kinds where it beats the baseline)"); ap.add_argument("--out-name", default="planmap-det.json")
    a = ap.parse_args()
    docs = a.docs + ([l.strip() for l in open(a.list) if l.strip()] if a.list else [])
    os.environ["OMP_NUM_THREADS"] = "1"
    with Pool(min(3, a.procs)) as p:
        for i, (d, s) in enumerate(p.imap_unordered(_work, [(d, a.out_name, a.kinds.split(",")) for d in docs])):
            if s != "ok" or i % 100 == 0: print(i, d, s, flush=True)
    print("done", len(docs))
