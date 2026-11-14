"""E-10: compare models on one task, one model at a time (no fallback), same questions.

Task supported: route (accuracy = type and kind; scope reported apart, since "floor plan" wording makes scope ambiguous; vs dataset type and router labels). Other tasks need their
own gold data (read_drawing: VISION; write_answer: text questions) and are added here when it exists.

  python -m engine.compare --task route --models nvidia:nvidia/nemotron-3.5-lightning-30b-a3b,runware:google:gemini@3.1-flash-lite \
      --sets sample200,sample1000.full --max-usd 5 --tag route1
Writes results/compare/<task>-<tag>.json. Every call goes through engine.models.call(only=...).
Pick = cheapest model whose accuracy is within --tolerance (default 1 point) of the best.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from engine.models import BudgetExceeded, ModelError, call
from engine.router.evaluate import load_labels
from engine.router.route import PROMPT, SCHEMA

ROOT = Path(__file__).resolve().parents[1]
SETS = {"sample200": "data/sets/sample200.jsonl", "sample1000.full": "data/sets/sample1000.full.jsonl",
        "router_test": "data/sets/router_test.jsonl"}
DEFAULT_MODELS = [
    "nvidia:nvidia/nemotron-3.5-lightning-30b-a3b", "nvidia:nvidia/nemotron-3-super-120b-a12b",
    "runware:google:gemini@3.1-flash-lite", "runware:google:gemini@3.5-flash",
    "runware:anthropic:claude@haiku-4.5", "runware:anthropic:claude@sonnet-4.6",
]


def unique_questions(sets: list[str]) -> list[dict]:
    seen: dict[str, dict] = {}
    for s in sets:
        p = ROOT / SETS.get(s, s)
        for l in p.open(encoding="utf-8"):
            r = json.loads(l)
            seen.setdefault(r["question"], r)
    return list(seen.values())


def _score(j: dict | None, row: dict, lab: dict) -> dict:
    if not j:
        return {"ok": False, "type_ok": False, "scope_ok": False, "invalid": True}
    t_ok = j.get("type") == row["type"]
    k_ok = (not lab.get("kind")) or (None if j.get("kind") == "none" else j.get("kind")) == lab["kind"]
    s_ok = (not lab.get("scope")) or (None if j.get("scope") == "none" else j.get("scope")) == (None if lab["scope"] == "none" else lab["scope"])
    return {"ok": bool(t_ok and k_ok), "type_ok": bool(t_ok), "scope_ok": bool(s_ok), "invalid": False}
    t_ok = j.get("type") == row["type"]
    k_ok = (not lab.get("kind")) or (None if j.get("kind") == "none" else j.get("kind")) == lab["kind"]
    s_ok = (not lab.get("scope")) or (None if j.get("scope") == "none" else j.get("scope")) == lab["scope"] or lab["scope"] in ("none", None) and j.get("scope") == "none"
    return {"ok": bool(t_ok and k_ok), "type_ok": bool(t_ok), "scope_ok": bool(s_ok), "invalid": False}


def run_model(spec: str, rows: list[dict], labels: dict, concurrency: int, max_usd: float) -> dict:
    prov, model = spec.split(":", 1)
    spent = [0.0]
    stop = [False]

    def one(row):
        if stop[0]:
            return None
        t = time.perf_counter()
        try:
            r = call("route", PROMPT + row["question"], schema=SCHEMA, only=(prov, model))
            sc = _score(r.json, row, labels.get(row["question"], {}))
            cost = r.cost_usd
            spent[0] += cost
            if spent[0] >= max_usd:
                stop[0] = True
            return {**sc, "cost": cost, "ms": int((time.perf_counter() - t) * 1000), "err": None}
        except BudgetExceeded:
            stop[0] = True
            return None
        except (ModelError, Exception) as e:  # a failing model is a result
            return {"ok": False, "type_ok": False, "scope_ok": False, "invalid": False, "cost": 0.0, "ms": int((time.perf_counter() - t) * 1000),
                    "err": f"{type(e).__name__}: {e}"[:120]}

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        res = [x for x in ex.map(one, rows) if x is not None]
    n = len(res)
    ms = sorted(x["ms"] for x in res) or [0]
    errs = [x["err"] for x in res if x["err"]]
    return {
        "model": spec, "n": n, "of": len(rows), "stopped_by_max_usd": stop[0],
        "accuracy": round(sum(x["ok"] for x in res) / n, 4) if n else None,
        "type_accuracy": round(sum(x["type_ok"] for x in res) / n, 4) if n else None,
        "scope_accuracy": round(sum(x["scope_ok"] for x in res) / n, 4) if n else None,
        "invalid_json": sum(x["invalid"] for x in res), "errors": len(errs), "first_error": errs[0] if errs else None,
        "cost_usd_total": round(sum(x["cost"] for x in res), 6),
        "cost_usd_per_call": round(sum(x["cost"] for x in res) / n, 8) if n else None,
        "latency_ms_mean": int(sum(ms) / len(ms)), "latency_ms_p95": ms[int(0.95 * (len(ms) - 1))],
    }


def pick(results: list[dict], tolerance: float = 0.01) -> dict | None:
    ok = [r for r in results if r["accuracy"] is not None and r["errors"] < 0.1 * max(r["n"], 1)]
    if not ok:
        return None
    best = max(r["accuracy"] for r in ok)
    cands = [r for r in ok if r["accuracy"] >= best - tolerance]
    return min(cands, key=lambda r: (r["cost_usd_per_call"], r["latency_ms_mean"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="route", choices=["route"])
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--sets", default="sample200,sample1000.full")
    ap.add_argument("--tag", default="dev")
    ap.add_argument("--max-usd", type=float, default=5.0, help="per model")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--tolerance", type=float, default=0.01)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    rows = unique_questions(a.sets.split(","))
    if a.limit:
        rows = rows[: a.limit]
    labels = load_labels()
    results = []
    for spec in a.models.split(","):
        r = run_model(spec, rows, labels, a.concurrency, a.max_usd)
        results.append(r)
        print(f"{spec:<48} n={r['n']:>4} acc={r['accuracy']} type={r['type_accuracy']} $/call={r['cost_usd_per_call']} "
              f"ms={r['latency_ms_mean']} err={r['errors']}", flush=True)
    best = pick(results, a.tolerance)
    out = {"task": a.task, "sets": a.sets, "unique_questions": len(rows), "tolerance": a.tolerance,
           "pick": best["model"] if best else None, "models": results}
    d = ROOT / "results/compare"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{a.task}-{a.tag}.json").write_text(json.dumps(out, indent=1))
    print("pick:", out["pick"], f"-> results/compare/{a.task}-{a.tag}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
