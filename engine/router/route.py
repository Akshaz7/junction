"""Rules first, Nemotron fallback second (E-07).

route(question) -> RouteResult. Rules answer for free. Only questions the rules
cannot parse (matched=False) go to `call("route", ...)`: chain is NVIDIA Nemotron,
then Runware. The model answer is validated against SCHEMA; if it is invalid or
the call fails, the rules' best guess is returned with source="rules-guess".

CLI: python -m engine.router.route [--set PATH] [--max-usd 0.50] [--sample N] [--force-model]
  --force-model sends EVERY question to the model (measures model-only accuracy
  and per-question cost; the number that matters for the fallback).
Writes results/router_cost.json.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path

from engine.models import BudgetExceeded, ModelError, call
from engine.models.core import spend

from .parser import KIND_TERMS, Parsed, parse

ROOT = Path(__file__).resolve().parents[2]
TYPES = ["count", "area", "length", "volume", "text", "other"]
KINDS = sorted({k for k, _ in KIND_TERMS} | {"text", "other"})
SCOPES = ["room", "storey", "whole-doc", "none"]
SCHEMA = {
    "type": "object",
    "required": ["type", "kind", "scope"],
    "additionalProperties": False,
    "properties": {
        "type": {"type": "string", "enum": TYPES},
        "kind": {"type": "string", "enum": KINDS + ["none"]},
        "scope": {"type": "string", "enum": SCOPES},
    },
}
PROMPT = (
    "Classify a question about a building drawing or BIM model. Reply with JSON only.\n"
    "type: count (how many), area, length, volume, text (descriptive, lists, materials, heights, widths, "
    "breakdowns, superlatives, compound questions), other (not about the drawing).\n"
    f"kind: the thing asked about, one of {', '.join(KINDS)}, or none.\n"
    "scope: room (a named or numbered room), storey (a floor or level), whole-doc (whole building or sheet), "
    "none (not stated).\n\nQuestion: "
)


@dataclass
class RouteResult:
    parsed: Parsed
    source: str  # "rules" | "model" | "rules-guess"
    cost_usd: float = 0.0
    provider: str = ""


def _from_model(question: str, request_id: str | None) -> tuple[Parsed, float, str]:
    r = call("route", PROMPT + question, schema=SCHEMA, request_id=request_id)
    j = r.json or {}
    rules = parse(question)
    return (
        Parsed(j["type"], None if j["kind"] == "none" else j["kind"],
               None if j["scope"] == "none" else j["scope"], True, "model", None),
        r.cost_usd, r.provider,
    )


def route(question: str, *, force_model: bool = False, request_id: str | None = None) -> RouteResult:
    p = parse(question)
    if p.matched and not force_model:
        return RouteResult(p, "rules")
    try:
        mp, cost, prov = _from_model(question, request_id)
        return RouteResult(mp, "model", cost, prov)
    except BudgetExceeded:
        raise
    except (ModelError, KeyError, TypeError, ValueError):
        return RouteResult(p, "rules-guess")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=str(ROOT / "data/sets/router_test.jsonl"))
    ap.add_argument("--max-usd", type=float, default=0.50)
    ap.add_argument("--sample", type=int, default=0, help="random unique questions (0 = all)")
    ap.add_argument("--force-model", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "results/router_cost.json"))
    a = ap.parse_args()

    from .evaluate import load_labels
    labels = load_labels()
    uniq = list({r["question"]: r for r in map(json.loads, open(a.set))}.values())
    if a.sample:
        random.Random(7).shuffle(uniq)
        uniq = uniq[: a.sample]

    total = 0.0
    n = ok = model_calls = 0
    provs: dict[str, int] = {}
    ok_by_src = {"rules": [0, 0], "model": [0, 0], "rules-guess": [0, 0]}
    start_spend = {p: spend(p) for p in ("nvidia", "runware")}
    for r in uniq:
        if total >= a.max_usd:
            print(f"stopped at --max-usd {a.max_usd}", file=sys.stderr)
            break
        res = route(r["question"], force_model=a.force_model)
        total += res.cost_usd
        lab = labels.get(r["question"], {})
        good = res.parsed.type == r["type"] and (not lab.get("kind") or res.parsed.kind == lab["kind"])
        n += 1; ok += good
        ok_by_src[res.source][0] += good; ok_by_src[res.source][1] += 1
        if res.source == "model":
            model_calls += 1
            provs[res.provider] = provs.get(res.provider, 0) + 1
    out = {
        "set": str(Path(a.set).relative_to(ROOT)) if str(a.set).startswith(str(ROOT)) else a.set,
        "unique_questions": n,
        "force_model": a.force_model,
        "accuracy_type_and_kind": round(ok / max(n, 1), 4),
        "by_source": {k: {"correct": v[0], "n": v[1]} for k, v in ok_by_src.items() if v[1]},
        "model_calls": model_calls,
        "providers": provs,
        "total_cost_usd": round(total, 6),
        "mean_cost_per_question_usd": round(total / max(n, 1), 8),
        "mean_cost_per_model_call_usd": round(total / max(model_calls, 1), 8) if model_calls else 0.0,
        "max_usd_guard": a.max_usd,
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
