"""Measure each V-09 geometry rule alone and combined, on calibration drawings and on the 241 held-out."""
import json, re, sys, itertools
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import verify as V
import eval as E

ROOT = E.ROOT
KS = ["window", "door", "toilet", "sink", "shower_bathtub"]
KIND_OF = {"window": ["window"], "door": ["door"], "toilet": ["toilet"], "sink": ["sink"], "shower_bathtub": ["bathtub", "shower"]}


def pred(items):
    c = Counter(i["kind"] for i in items)
    return {k: sum(c[x] for x in v) for k, v in KIND_OF.items()}


def calib_set():
    gt = json.load(open(ROOT / "data/cubicasa5k/calib/gt.json"))
    out = []
    for d, g in gt.items():
        pm = json.load(open(ROOT / "data/cubicasa5k/calib_pm" / f"calib__{d}" / "planmap-1.json"))
        out.append((pm, {k: g.get(k, 0) for k in KS}))
    return out


def heldout_set():
    rules = [(r"^How many windows", "window"), (r"^How many doors", "door"), (r"^How many toilet", "toilet"), (r"^How many sinks", "sink"), (r"^How many showers and bathtubs", "shower_bathtub")]
    by = defaultdict(dict)
    for l in open(ROOT / "data/sets/questions_en.jsonl"):
        q = json.loads(l)
        if q["source"] != "cubicasa5k":
            continue
        for r, k in rules:
            if re.search(r, q["question"]):
                by[q["doc_id"]][k] = int(q["answer"])
    out = []
    for d, g in by.items():
        p = ROOT / "artifacts" / d / "planmap-1.json"
        if p.exists():
            out.append((json.load(open(p)), g))
    return out


def score(data, rules, params=None, items_fn=None):
    n, ok = Counter(), Counter()
    for pm, g in data:
        items = items_fn(pm) if items_fn else V.apply_rules(pm, rules, params)
        p = pred(items)
        for k, v in g.items():
            n[k] += 1
            ok[k] += p[k] == v
    return {k: round(ok[k] / n[k], 3) for k in n}, dict(n)


if __name__ == "__main__":
    cal, held = calib_set(), heldout_set()
    res = {}
    for name, rules in [("none", []), ("tiny", ["tiny"]), ("dup", ["dup"]), ("on_wall", ["on_wall"]), ("split", ["split"]), ("all", V.ORDER)]:
        res[name] = {"calib": score(cal, rules)[0], "heldout": score(held, rules)[0]}
        print(name, "CAL", res[name]["calib"], "HELD", res[name]["heldout"])
    print("n", score(cal, [])[1], score(held, [])[1])
