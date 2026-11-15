"""Gold on/off check of the detector hook on Modal (esplanades, molio, fzk). LOCAL ONLY; nothing pushed.
    modal run modal_gold.py
Per sheet: plan map via eval_svg_gold.plan_map (r4det snapshot with the hook), PDF_DETECT off vs on -> standard gold metrics
(must be identical: the hook adds props only) + detector value vs gold for door/window:
  confirm: share of TRUE vector items (matched to gold within 0.5 m) with props.det_conf
  flag:    share of FALSE vector items with props.det_check
  suggest: missed gold items recovered by suggestions (within 0.5 m), and false suggestions
  raw:     the detector alone vs gold (recall/precision within 0.5 m)
"""
import os

import modal

H = os.environ.get("DET_HOOK_DIR", os.path.dirname(os.path.abspath(__file__)))
B = os.environ["PIPELINE_SNAPSHOT"]  # repo copy with the hook applied
G = os.environ["GOLD_DIR"]  # *.gold.json from the IFC->SVG twins
app = modal.App("junction-gold-det-test")
vol = modal.Volume.from_name("junction-ds")
image = (modal.Image.debian_slim(python_version="3.12")
         .apt_install("libgl1", "libglib2.0-0")
         .pip_install_from_requirements(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "requirements-modal.txt"))
         .add_local_dir(G, "/root/gold")
         .add_local_dir(B, "/root/r4", ignore=["__pycache__", "*.pyc"]))
SHEETS = ["bsc-esplanades_1807-ep-ar-v18_plan-04-4-korrus", "bsc-molio_molio-with-uris_plan-02-klder",
          "kit-fzk-haus_ac20-fzk-haus_plan-02-dachgeschoss"]


def _c(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _match(a, b, tol):
    """Greedy one-to-one centre matching within tol -> list of (i, j)."""
    import math
    pairs = sorted((math.dist(_c(x), _c(y)), i, j) for i, x in enumerate(a) for j, y in enumerate(b))
    ua, ub, out = set(), set(), []
    for d, i, j in pairs:
        if d > tol:
            break
        if i in ua or j in ub:
            continue
        ua.add(i); ub.add(j); out.append((i, j))
    return out


@app.function(image=image, volumes={"/ds": vol}, cpu=4, memory=16384, timeout=1800)
def run(sheet: str, mode: str) -> dict:
    import json, os, sys, time
    os.chdir("/root/r4"); sys.path.insert(0, "/root/r4"); sys.path.insert(0, "/root/r4/scripts")
    if mode == "on":
        os.environ["PDF_DETECT"] = "1"; os.environ["PDF_DETECT_PY"] = sys.executable
    else:
        os.environ.pop("PDF_DETECT", None)
    from pathlib import Path
    import eval_svg_gold as E
    pdf = Path(f"/ds/full/junction-dataset/data/ifc_models/{sheet}.pdf"); gp = Path(f"/root/gold/{sheet}.gold.json")
    t0 = time.time()
    res = E.evaluate(pdf, gp, 0)  # standard metrics (runs the plan map once)
    pm, s = E.plan_map(pdf, 0)     # second run to read props (same code path)
    out = {"sheet": sheet.split("_")[0], "mode": mode, "metrics": {k: res.get(k) for k in ("wall", "door", "window", "space", "scale")},
           "seconds": round(time.time() - t0, 1)}
    if mode != "on" or pm is None:
        return out
    gold = json.loads(gp.read_text()); mpt = gold["meta"].get("m_per_pt"); tol = 0.5 / mpt
    det = pm.get("detector") or {}
    out["detector_meta"] = {k: det.get(k) for k in ("error", "run", "weights", "thresholds", "tiles", "seconds", "counts_detected", "stats")}
    sug = det.get("suggested") or []
    per = {}
    for kind, gcls in (("door", ("IfcDoor",)), ("window", ("IfcWindow",))):
        g = [el["bbox_pt"] for c in gcls for el in gold["elements"].get(c, [])]
        vec = [it for it in pm["items"] if it["kind"] == kind]
        vb = [[v / s for v in it["bbox_px"]] for it in vec]
        m = _match(vb, g, tol); true_v = {i for i, _ in m}; hit_g = {j for _, j in m}
        conf_true = sum(1 for i in true_v if "det_conf" in (vec[i].get("props") or {}))
        false_v = [i for i in range(len(vec)) if i not in true_v]
        flag_false = sum(1 for i in false_v if (vec[i].get("props") or {}).get("det_check"))
        flag_true = sum(1 for i in true_v if (vec[i].get("props") or {}).get("det_check"))
        missed = [g[j] for j in range(len(g)) if j not in hit_g]
        sk = [[v / s for v in x["bbox_px"]] for x in sug if x["kind"] == kind]
        rec = _match(sk, missed, tol)
        per[kind] = {"gold": len(g), "vector": len(vec), "vector_true": len(true_v), "vector_false": len(false_v),
                     "confirmed_true": conf_true, "confirm_rate_true": round(conf_true / len(true_v), 3) if true_v else None,
                     "flagged_false": flag_false, "flag_rate_false": round(flag_false / len(false_v), 3) if false_v else None,
                     "flagged_true(wrong flags)": flag_true,
                     "missed_by_vector": len(missed), "suggested": len(sk), "suggest_recovers": len(rec),
                     "suggest_false": len(sk) - len(rec)}
    # raw detector vs gold (direct call, same weights/thresholds the hook used)
    try:
        import modal as _m
        r = _m.Cls.from_name("junction-det", "Detector")().detect.remote(pdf.read_bytes(), 0, mpt)
        for kind in ("door", "window"):
            g = [el["bbox_pt"] for el in gold["elements"].get("IfcDoor" if kind == "door" else "IfcWindow", [])]
            d = [x["bbox_pt"] for x in r["items"] if x["kind"] == kind]
            mm = _match(d, g, tol)
            per[kind]["raw_detector"] = {"n": len(d), "tp": len(mm), "recall": round(len(mm) / len(g), 3) if g else None,
                                         "precision": round(len(mm) / len(d), 3) if d else None}
        out["raw_run"] = r.get("run"); out["raw_weights"] = r.get("weights")
    except Exception as e:  # noqa: BLE001
        out["raw_error"] = f"{type(e).__name__}: {e}"[:300]
    out["detector_value"] = per
    return out


@app.local_entrypoint()
def main():
    import json
    jobs = [(s, m) for s in SHEETS for m in ("off", "on")]
    res = list(run.starmap(jobs))
    json.dump(res, open(f"{H}/gold_det_result.json", "w"), indent=1)
    for r in res:
        print("ROW", json.dumps(r))
