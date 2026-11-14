"""E-10: compare judge_text models (bench text judge) on the same (question, gold, answer) triples.

There is no human label for text verdicts, so accuracy here is AGREEMENT with a reference judge (default runware claude sonnet-4.6).
Triples come from a bench rows file (text rows with an answer). Every call goes through engine.models.call(only=...).

  python -m engine.compare_judge --rows results/bench/full_1.rows.jsonl --limit 60 --max-usd 1 --out results/compare/judge_text-j1.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from engine.bench import JUDGE_PROMPT, JUDGE_SCHEMA
from engine.models import call

ROOT = Path(__file__).resolve().parents[1]
MODELS = ["nvidia:nvidia/nemotron-3.5-lightning-30b-a3b", "runware:google:gemini@3.1-flash-lite",
          "runware:anthropic:claude@haiku-4.5", "runware:google:gemini@3.5-flash"]
REFERENCE = "runware:anthropic:claude@sonnet-4.6"


def verdicts(spec: str, triples: list[dict], max_usd: float) -> dict:
    prov, model = spec.split(":", 1)
    out, cost, lat, errs = [], 0.0, [], 0
    for t in triples:
        if cost >= max_usd:
            break
        t0 = time.perf_counter()
        try:
            r = call("judge_text", [{"role": "user", "content": JUDGE_PROMPT % (t["question"], str(t["gold"])[:1500], t["text"][:1500])}],
                     schema=JUDGE_SCHEMA, only=(prov, model))
            v = (r.json or {}).get("verdict") if getattr(r, "json", None) else None
            cost += r.cost_usd
        except Exception:
            v, errs = None, errs + 1
        lat.append((time.perf_counter() - t0) * 1000)
        out.append(v if v in ("correct", "partial", "wrong") else None)
    return {"verdicts": out, "cost_usd": cost, "errors": errs, "latency_ms_mean": int(sum(lat) / max(1, len(lat)))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True)
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--max-usd", type=float, default=1.0, help="per model")
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = [json.loads(l) for l in (ROOT / a.rows).open(encoding="utf-8")]
    triples = [r for r in rows if r["type"] == "text" and r.get("text") and r.get("gold") is not None][: a.limit]
    ref = verdicts(REFERENCE, triples, a.max_usd)
    res = []
    for spec in a.models.split(","):
        m = verdicts(spec, triples, a.max_usd)
        pairs = [(x, y) for x, y in zip(m["verdicts"], ref["verdicts"]) if y is not None]
        agree = sum(1 for x, y in pairs if x == y)
        res.append({"model": spec, "n": len(pairs), "agreement_with_reference": round(agree / len(pairs), 4) if pairs else None,
                    "unparsed": sum(1 for x, _ in pairs if x is None), "errors": m["errors"], "cost_usd_total": round(m["cost_usd"], 6),
                    "cost_usd_per_call": round(m["cost_usd"] / max(1, len(m["verdicts"])), 8), "latency_ms_mean": m["latency_ms_mean"]})
    best = max((r["agreement_with_reference"] or 0) for r in res)
    ok = [r for r in res if (r["agreement_with_reference"] or 0) >= best - 0.05]
    pick = min(ok, key=lambda r: r["cost_usd_per_call"]) if ok else None
    Path(ROOT / a.out).write_text(json.dumps({"task": "judge_text", "metric": "agreement with reference judge (no human labels)", "reference": REFERENCE,
                                              "n_triples": len(triples), "reference_cost_usd": round(ref["cost_usd"], 6), "models": res,
                                              "pick": pick["model"] if pick else None}, indent=1))
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
