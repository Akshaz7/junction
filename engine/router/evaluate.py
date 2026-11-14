"""Score the rules parser. Usage: python -m engine.router.evaluate [--set PATH] [--show N]
Type labels come from the dataset row; kind/scope from labels/router_labels.jsonl.
A question is correct only if type matches AND (when labelled) kind and scope match
AND the parser reported matched=True (an unmatched question would go to the model)."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from .parser import parse

ROOT = Path(__file__).resolve().parents[2]
LABELS = Path(__file__).with_name("labels") / "router_labels.jsonl"


def load_labels() -> dict:
    return {r["question"]: r for r in map(json.loads, LABELS.open())} if LABELS.exists() else {}


def score(rows: list[dict], predict=parse, labels: dict | None = None) -> dict:
    labels = labels if labels is not None else load_labels()
    n = ok = ok_type = unmatched = 0
    kn = kok = sn = sok = 0
    bad = []
    for r in rows:
        p = predict(r["question"])
        lab = labels.get(r["question"], {})
        t_ok = p.type == r["type"]
        k_ok = s_ok = True
        if lab.get("kind"):
            kn += 1; k_ok = p.kind == lab["kind"]; kok += k_ok
        if lab.get("scope"):
            sn += 1; s_ok = p.scope == lab["scope"]; sok += s_ok
        good = t_ok and k_ok and s_ok and p.matched
        n += 1; ok += good; ok_type += t_ok; unmatched += (not p.matched)
        if not good:
            bad.append((r["question"], r["type"], lab.get("kind"), lab.get("scope"), p))
    return {"n": n, "accuracy": ok / n, "type_accuracy": ok_type / n, "kind_accuracy": kok / max(kn, 1),
            "scope_accuracy": sok / max(sn, 1), "unmatched": unmatched, "bad": bad}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=str(ROOT / "data/sets/router_test.jsonl"))
    ap.add_argument("--show", type=int, default=0)
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.set)]
    uniq = list({r["question"]: r for r in rows}.values())
    for name, rs in (("rows", rows), ("unique questions", uniq)):
        s = score(rs)
        print(f"{name}: n={s['n']} accuracy={s['accuracy']:.3f} type={s['type_accuracy']:.3f} "
              f"kind={s['kind_accuracy']:.3f} scope={s['scope_accuracy']:.3f} unmatched={s['unmatched']}")
    for q, t, k, sc, p in score(uniq)["bad"][: a.show]:
        print(f"- [{t}/{k}/{sc}] got {p.type}/{p.kind}/{p.scope} m={p.matched} ({p.reason}) | {q[:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
