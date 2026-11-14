"""Score the fine-tuned detector on ALL held-out CubiCasa drawings with count questions (4,787), vs the stored plan-map baseline.
  1) modal run train/modal_infer.py ; modal volume get junction-vision-out det_full_dets.json results/vision/det_full_dets.json
  2) .venv/bin/python vision/eval_det_full.py
Cuts come from results/vision/det_finetuned.json (picked on calibration drawings). Exact-count accuracy per kind; 'hybrid' = detector for shower+bathtub only, baseline for the rest."""
import json, re, sys
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import verify as V, verify_eval as VE
ROOT = VE.ROOT
KINDS = {"door", "window", "toilet", "sink", "shower", "bathtub"}
rules = [(r"^How many windows", "window"), (r"^How many doors", "door"), (r"^How many toilet", "toilet"), (r"^How many sinks", "sink"), (r"^How many showers and bathtubs", "shower_bathtub")]
gt = defaultdict(dict)
for l in open(ROOT / "data/sets/questions_en.full.jsonl"):
    q = json.loads(l)
    if q["source"] != "cubicasa5k": continue
    for r, k in rules:
        if re.search(r, q["question"]): gt[q["doc_id"]][k] = int(q["answer"])
dets = json.load(open(ROOT / "results/vision/det_full_dets.json"))
cut = json.load(open(ROOT / "results/vision/det_finetuned.json"))["cut_picked_on_calib"]
n, ok = {m: Counter() for m in ("baseline", "finetuned", "hybrid")}, {m: Counter() for m in ("baseline", "finetuned", "hybrid")}
for d, g in gt.items():
    pm = json.load(open(ROOT / "artifacts" / d / "planmap-1.json")); W, H = pm["image"]["w"], pm["image"]["h"]
    base = V.free_pass(pm["items"], W, H)
    new = [dict(kind=x["kind"], label=None, bbox_px=[x["box"][0] * W, x["box"][1] * H, x["box"][2] * W, x["box"][3] * H], polygon_px=None, props={}, conf=x["conf"], source="det")
           for x in dets.get(d, []) if x["conf"] >= cut.get(x["kind"], 0.5)]
    new = V.rule_dup(new, W, H, {**V.DEFAULTS, **V.FREE})
    keep = [i for i in pm["items"] if i["kind"] not in KINDS]
    P = {"baseline": VE.pred(base), "finetuned": VE.pred(keep + new)}
    pb, pf = P["baseline"], P["finetuned"]; P["hybrid"] = {**pb, "shower_bathtub": pf["shower_bathtub"]}
    for m, p in P.items():
        for k, v in g.items(): n[m][k] += 1; ok[m][k] += p[k] == v
res = {"n_docs": len(gt), "cuts": cut, **{m: {k: round(ok[m][k] / n[m][k], 3) for k in n[m]} for m in n}, "n_questions": dict(n["baseline"])}
(ROOT / "results/vision/det_finetuned_full.json").write_text(json.dumps(res, indent=1)); print(json.dumps(res, indent=1))
