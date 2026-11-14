"""Reproducible, read-only code audit; run via scripts/heavy.sh.

python -m engine.xcheck_audit --sets data/sets/sample200.jsonl results/qa/judge_questions.jsonl
No training, new model calls, artifact writes, or fabricated second readings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from engine import xcheck


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cached_recount(question, doc, root, cache):
    """Exact image hash + exact normalized question; no fuzzy cache borrowing."""
    image = Path(root) / doc.doc_id / "page-1.png"
    if doc.mode != "planmap" or doc.pages != 1 or not image.exists():
        return None
    image_hash = hashlib.sha1(image.read_bytes()).hexdigest()[:16]
    normalized = re.sub(r"\W+", " ", question.lower()).strip()
    hits = []
    for key, value in cache.items():
        parts = key.split("|")
        if len(parts) < 4 or parts[0] != "count" or parts[1] != image_hash or parts[3] != normalized:
            continue
        if not isinstance(value, list) or len(value) < 2 or type(value[0]) is not int or value[0] < 0 or "fake" in str(value[1]).lower():
            continue
        hits.append((value[0], str(value[1]), parts[2]))
    # Different cached models/pins giving different answers are ambiguous.
    return hits[0] if hits and len({h[0] for h in hits}) == 1 else None


def audit(sets, root, output, recount_cache):
    from engine import analytics, reasoning
    from engine.router.parser import parse
    from engine.solvers import SolverUnsupported, solve
    from engine.solvers.data import load_doc
    cache = xcheck.read(recount_cache)
    observations, cases, snapshots = [], [], {}
    seen = set()
    for set_path in sets:
        snapshots[str(set_path)] = digest(set_path)
        rows = [json.loads(line) for line in Path(set_path).read_text().splitlines() if line.strip()]
        for idx, row in enumerate(rows):
            doc_id, question = row.get("doc_id"), row.get("question")
            case = {"set": str(set_path), "id": row.get("id", idx + 1), "doc_id": doc_id, "question": question}
            try:
                doc = load_doc(doc_id, root)
                if doc is None:
                    case["unavailable"] = "No indexed document"
                    cases.append(case)
                    continue
                result = analytics.run(question, doc, time.perf_counter())
                if result is None:
                    result = solve(question, doc_id, parse(question), root=root)
                result = reasoning.attach(result, question, root)
                a = result.get("answer", {})
                card = result.get("reasoning") or {}
                calc = card.get("calc") or {}
                case.update(value=a.get("value"), unit=a.get("unit"), route=result.get("route"),
                            checks=len(calc.get("checks", [])), numeric=xcheck.finite(a.get("value")) is not None,
                            reconciled=calc.get("reconciled", False), abstained=a.get("abstained", False))
                if not calc.get("checks"):
                    case["unavailable"] = (calc.get("unavailable") or ["No independent complete-quantity check recorded"])[0]
                # Per-element observations are deduplicated across questions and sets.
                for check in calc.get("item_checks", []):
                    if not check.get("independent"):
                        continue
                    cohort = "ifc" if doc.mode == "ifc" else "cad" if any(i.source == "dxf" for i in doc.items) else "scan"
                    identity = (doc_id, check["item_id"], check["method"], check["unit"])
                    if identity not in seen:
                        seen.add(identity)
                        observations.append({**check, "cohort": cohort, "set": str(set_path), "question_id": case["id"]})
                for check in calc.get("checks", []):
                    if check["method"] != "room sum / outer outline minus walls":
                        continue
                    identity = (doc_id, tuple(sorted(s["item_id"] for s in check["sources"])), check["method"])
                    if identity not in seen:
                        seen.add(identity)
                        observations.append({**check, "doc_id": doc_id, "set": str(set_path), "question_id": case["id"]})
                # Reuse a previously paid independent recount, where it is exactly
                # the same question and image; fake mode never creates a reading.
                if a.get("unit") == "count" and xcheck.finite(a.get("value")) is not None:
                    rec = cached_recount(question, doc, root, cache)
                    if rec:
                        value, model, kind = rec
                        identity = (doc_id, question, "detector / drawing recount")
                        if identity not in seen:
                            c = xcheck.compare("detector / drawing recount", a["value"], value, "count",
                                               [{"doc_id": doc_id, "page": 1, "model": model, "cache": str(recount_cache), "question": question}])
                            if c:
                                seen.add(identity)
                                observations.append({**c, "doc_id": doc_id, "cohort": "scan", "kind": kind,
                                                     "set": str(set_path), "question_id": case["id"]})
                                case["cached_recount"] = {"value": value, "model": model, "diff_pct": c["diff_pct"]}
            except (SolverUnsupported, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                case["unavailable"] = f"{type(exc).__name__}: {str(exc)[:160]}"
            cases.append(case)
        print(f"Audited {len(rows)} questions from {set_path}", flush=True)
    if Path(recount_cache).exists():
        snapshots[str(recount_cache)] = digest(recount_cache)
    # Record exactly which indexed source state produced these observations.
    for did in sorted({o["doc_id"] for o in observations}):
        for path in sorted((Path(root) / did).glob("planmap-[0-9]*.json")) + [Path(root) / did / "elements.json"]:
            if path.exists():
                snapshots[str(path)] = digest(path)
    groups = defaultdict(list)
    for o in observations:
        groups[o["method"], o["cohort"], o["unit"], o.get("kind")].append(o)
    pairs = []
    for (method, cohort, unit, kind), obs in sorted(groups.items(), key=lambda pair: str(pair[0])):
        n = len(obs)
        one = sum(o["within_1pct"] for o in obs)
        five = sum(o["agrees"] for o in obs)
        pairs.append({"method": method, "cohort": cohort, "unit": unit, "kind": kind, "n": n, "within_1pct": one, "within_5pct": five,
                      "rate_1pct": one / n, "rate_5pct": five / n,
                      "documents": len({o["doc_id"] for o in obs}), "scope": "Deduplicated observed method agreement, not answer accuracy"})
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "difference_formula": "100 × |a − b| / max(|a|, |b|); both zero = 0",
              "scope": "Code-only answers and existing exact-image/question recount cache; no new model calls or training",
              "independence": "Contour/fill agreement and storey regrouping identities excluded from calibration",
              "snapshots_sha256": snapshots, "pairs": pairs,
              "summary": {"questions": len(cases), "numeric_answers": sum(c.get("numeric", False) for c in cases),
                          "complete_checks": sum(c.get("checks", 0) > 0 for c in cases), "independent_observations": len(observations),
                          "unavailable": sum("unavailable" in c for c in cases), "live_cost_usd": 0},
              "cases": cases, "observations": observations}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sets", nargs="+", required=True, type=Path)
    p.add_argument("--root", type=Path, default=Path("artifacts"))
    p.add_argument("--output", type=Path, default=Path("results/final/XCHECK/agreement.json"))
    p.add_argument("--recount-cache", type=Path, default=Path("results/recount_cache/recount_cache.json"))
    args = p.parse_args()
    report = audit(args.sets, args.root, args.output, args.recount_cache)
    print(json.dumps(report["summary"], indent=2))
