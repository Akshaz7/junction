"""V-10: generalisation. Swiss dwellings PNG (65 docs, GT from questions) scored per kind; wikimedia/habs/finna (no questions) reported as
abstain rate and plan-map stats only. Abstain rule: see abstain()."""
import json, re, sys, glob
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "data/vision_gen"
RULES = [(r"^How many doors", "door", ("door",)), (r"^How many windows", "window", ("window",)), (r"^How many toilets", "toilet", ("toilet",)),
         (r"^How many washbasins", "sink", ("sink",)), (r"^How many bathtubs", "bathtub", ("bathtub", "shower"))]


MC_MIN = 0.84  # median of mean door/window confidence on the 156 clean CubiCasa calibration drawings (hit rate 0.29/0.47/0.65 by tercile)


def abstain(pm):
    """True when the plan map is not trustworthy enough to answer counts: too few structural items or low detector confidence."""
    c = Counter(i["kind"] for i in pm["items"])
    walls = sum((i["bbox_px"][2] - i["bbox_px"][0]) * (i["bbox_px"][3] - i["bbox_px"][1]) for i in pm["items"] if i["kind"] == "wall")
    wall_frac = walls / (pm["image"]["w"] * pm["image"]["h"])
    ds = [i["conf"] for i in pm["items"] if i["kind"] in ("door", "window")]
    return c["wall"] < 4 or c["room"] < 2 or (c["door"] + c["window"]) < 2 or wall_frac < 0.01 or (ds and sum(ds) / len(ds) < MC_MIN)


def load(d):
    return json.load(open(GEN / d / "planmap-1.json"))


def main():
    gt = defaultdict(dict)
    for l in open(ROOT / "data/sets/questions_en.jsonl"):
        q = json.loads(l)
        if q["source"] != "swiss_dwellings":
            continue
        for r, k, _ in RULES:
            if re.search(r, q["question"]):
                gt[q["doc_id"]][k] = int(q["answer"])
    n, ok, n_a, ok_a = Counter(), Counter(), Counter(), Counter()
    err, w1, pr, gr = Counter(), Counter(), Counter(), Counter()
    ab = 0
    for d, g in gt.items():
        pm = load(d); c = Counter(i["kind"] for i in pm["items"]); a = abstain(pm); ab += a
        for r, k, ks in RULES:
            if k in g:
                hit = sum(c[x] for x in ks) == g[k]
                n[k] += 1; ok[k] += hit
                pv = sum(c[x] for x in ks); err[k] += abs(pv - g[k]); w1[k] += abs(pv - g[k]) <= 1; pr[k] += pv; gr[k] += g[k]
                if not a:
                    n_a[k] += 1; ok_a[k] += hit
    res = {"swiss_dwellings": {"docs": len(gt), "abstain_rate": round(ab / len(gt), 3),
                               "accuracy_all": {k: round(ok[k] / n[k], 3) for k in n},
                               "accuracy_answered": {k: (round(ok_a[k] / n_a[k], 3) if n_a[k] else None) for k in n},
                               "answered": dict(n_a),
                               "within1": {k: round(w1[k] / n[k], 3) for k in n}, "mae": {k: round(err[k] / n[k], 2) for k in n}, "pred_over_gt": {k: round(pr[k] / max(1, gr[k]), 2) for k in n}}}
    for s in ("wikimedia", "habs", "finna"):
        docs = [Path(p).parent.name for p in glob.glob(str(GEN / f"{s}__*/planmap-1.json"))]
        pms = [load(d) for d in docs]
        res[s] = {"docs": len(docs), "abstain_rate": round(sum(abstain(p) for p in pms) / max(1, len(pms)), 3), "accuracy": "no ground truth in the dataset (no questions for this source)",
                  "mean_items": {k: round(sum(1 for p in pms for i in p["items"] if i["kind"] == k) / max(1, len(pms)), 1) for k in ("wall", "door", "window", "room", "text")},
                  "scale_methods": dict(Counter(p["scale"]["method"] for p in pms))}
    # same rule on cubicasa calib (rule is defined there, not on swiss)
    json.dump(res, open(ROOT / "results/vision/generalisation.json", "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
