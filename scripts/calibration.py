#!/usr/bin/env python3
"""F-QA2: confidence calibration against independent dataset numeric gold.

Consumes evidence_audit.json; no model calls, no engine/constant edits. Buckets
without gold are excluded, missing cards are counted, and small samples carry
Wilson intervals. Candidate constants are descriptive, not validated changes.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def wilson(correct, n):
    if not n:
        return None
    z = 1.959963984540054
    p = correct / n
    den = 1 + z*z/n
    centre = (p + z*z/(2*n)) / den
    half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / den
    return [round(max(0, centre-half), 6), round(min(1, centre+half), 6)]


def stats(records):
    n = len(records)
    correct = sum(r["outcome"] == "correct" for r in records)
    predictions = [r["pct"]/100 for r in records if isinstance(r.get("pct"), (int, float))]
    accuracy = correct/n if n else None
    predicted = sum(predictions)/len(predictions) if predictions else None
    return {"n": n, "documents": len({r["doc_id"] for r in records}), "correct": correct,
            "wrong": sum(r["outcome"] == "wrong" for r in records),
            "abstained": sum(r["outcome"] == "abstained" for r in records),
            "observed_accuracy": round(accuracy, 6) if n else None,
            "predictions": len(predictions),
            "mean_predicted_accuracy": round(predicted, 6) if predicted is not None else None,
            "overconfidence_pp": round((predicted-accuracy)*100, 3) if len(predictions) == n and n else None,
            "wilson_95": wilson(correct, n),
            "small_sample": n < 30 or len({r["doc_id"] for r in records}) < 10}


def calibrate(document):
    records, excluded = [], Counter()
    for row in document["rows"]:
        case = row["case"]
        if not case.get("gold_kind"):
            excluded["no_independent_gold"] += 1; continue
        if case.get("type") not in ("count", "area", "length", "volume"):
            excluded["non_numeric_gold_not_judged"] += 1; continue
        if row["outcome"] not in ("correct", "wrong", "abstained"):
            excluded["unscorable_gold"] += 1; continue
        confidence = (row["response"].get("reasoning") or {}).get("confidence")
        if not confidence:
            excluded["missing_card_on_numeric_gold"] += 1; continue
        response = row["response"]
        fmt = case["format"]
        model_used = any(t.get("model") and t.get("step") not in ("explain", "context", "typos")
                         for t in response.get("trace", []))
        source = ("vision" if response.get("route") in ("vlm", "vision") else
                  "ifc" if fmt == "ifc" and not model_used else
                  "cad" if fmt in ("dxf", "dwg") and not model_used else
                  "text" if response.get("route") == "index" and not model_used else
                  "scan" if response.get("route") == "planmap" else "vision")
        verdicts = [s.get("ok") for s in response.get("reasoning", {}).get("steps", [])
                    if s.get("kind") == "checked" and isinstance(s.get("ok"), bool)]
        output_unit = response["answer"].get("unit")
        unit = {"m²": "m2", "m³": "m3"}.get(output_unit, output_unit)
        if case["type"] == "count":
            unit = "count"  # Some count solvers name the counted object as their unit.
        records.append({"case_id": case["case_id"], "doc_id": case["doc_id"], "source": case["source"],
                        "calibration_source": source, "unit": unit, "output_unit": output_unit,
                        "checked": all(verdicts) if verdicts else None,
                        "format": case["format"], "type": case["type"], "outcome": row["outcome"],
                        "label": confidence["label"], "pct": confidence.get("pct"),
                        "reason": confidence["reason"], "question": case["question"],
                        "value": row["response"]["answer"].get("value"), "gold": case.get("answer")})
    exact, labels, sources, types = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for r in records:
        exact[(r["label"], r["pct"])].append(r)
        labels[r["label"]].append(r)
        sources[r["format"]].append(r)
        types[(r["format"], r["type"])] .append(r)
    buckets = [{"label": label, "pct": pct, **stats(rs)} for (label, pct), rs in sorted(exact.items(), key=lambda kv: (kv[0][0], -1 if kv[0][1] is None else kv[0][1]))]
    loader_groups = defaultdict(list)
    for r in records:
        loader_groups[(r["label"], r["calibration_source"], r["unit"], r["checked"])].append(r)
    loader_buckets = []
    for (label, source, unit, checked), rs in sorted(loader_groups.items(), key=lambda kv: str(kv[0])):
        correct = sum(r["outcome"] == "correct" for r in rs)
        bucket = {"label": label, "source": source, "n": len(rs), "correct": correct,
                  "accuracy": correct / len(rs), "documents": len({r["doc_id"] for r in rs}),
                  "wilson_95": wilson(correct, len(rs)), "candidate_only": True}
        if unit is not None:
            bucket["unit"] = unit
        if checked is not None:
            bucket["checked"] = checked
        loader_buckets.append(bucket)
    proposals = []
    # The source base controls all question types, so estimate it per source;
    # this explicitly does not pretend a detector score is answer accuracy.
    for fmt, source_base, old in (("ifc", "IFC source base", 97), ("dxf", "CAD source base", 95), ("png", "Scanned plan-map source base", 80)):
        source = {"ifc": "ifc", "dxf": "cad", "png": "scan"}[fmt]
        rs = [r for r in records if r["calibration_source"] == source]
        s = stats(rs)
        if not rs:
            proposals.append({"constant": source_base, "current": old, "candidate": None,
                              "decision": "No numeric gold observations for this source; no justified change."})
            continue
        candidate = round(100 * s["correct"] / s["n"])
        proposals.append({"constant": source_base, "current": old, "candidate": candidate,
                          "exact_proposed_edit": f"Change base literal {old} to {candidate} in the {source!r} source branch, only after independent validation; remove heuristic bonuses before treating the result as a probability.",
                          "evidence": s,
                          "status": "candidate_only_not_applied",
                          "qualification": "Descriptive estimate from this audit, not independent validation. Refit on a disjoint, live-model calibration set before shipping.",
                          "required_logic_change": "If candidate < 92, the exact-source max(pct, 92) floor must also be removed for the candidate to have any effect." if fmt in ("ifc", "dxf") and candidate < 92 else None})
    predicted_records = [r for r in records if isinstance(r.get("pct"), (int, float))]
    predicted_groups = [v for (label, pct), v in exact.items() if pct is not None]
    return {"schema_version": 2, "audit_git_commit": document.get("git_commit"), "mode": document.get("mode"),
            "scoring": "Dataset numeric gold only: engine.bench.score exact rounded counts, measurements within max(0.05, 2%). Abstentions are failures; missing cards are reported outside buckets.",
            "summary": stats(records), "excluded": dict(excluded), "buckets_by_label_and_pct": buckets,
            "buckets": loader_buckets,
            "loader_note": "Percent must be correct/n only. These audit-fitted buckets are candidates, not independently validated production probabilities. No match means no percent; do not add heuristic bonuses. Missing checked means no measured check verdict.",
            "by_label": {k: stats(v) for k, v in sorted(labels.items())},
            "by_format": {k: stats(v) for k, v in sorted(sources.items())},
            "by_format_and_question_type": [{"format": k[0], "type": k[1], **stats(v)} for k, v in sorted(types.items())],
            "expected_calibration_error": round(sum(len(v)*abs(sum(r['pct']/100 for r in v)/len(v) - sum(r['outcome']=='correct' for r in v)/len(v)) for v in predicted_groups) / len(predicted_records), 6) if predicted_records else None,
            "brier_score": round(sum((r["pct"]/100-int(r["outcome"] == "correct"))**2 for r in predicted_records)/len(predicted_records), 6) if predicted_records else None,
            "proposed_confidence_constants": proposals,
            "other_constants": {"printed_text_base_93": "Do not change from unjudged text gold; verify source exactness separately.",
                                "vector_pdf_base_88": "Out of scope: no PDF observations.",
                                "vision_reader_base_65": "No live-reader validation; do not infer a production probability from unavailable-provider fallbacks.",
                                "agreement_bonus_8_or_5": "Agreement is not independence. Do not calibrate the bonus without separately labeled agreement/disagreement cohorts.",
                                "detector_bonus_minus6_to_plus3": "Object detector confidence is not exact count probability; per-kind held-back calibration needed.",
                                "exact_source_floor_92": "Remove or gate on a supported operation: exact source data alone does not prove the chosen scope, aggregation, or bbox measurement is correct."},
            "limitations": ["Not a representative production distribution: stratified by source/type with repeated documents.",
                            "Wilson intervals assume independent Bernoulli observations; repeated documents violate that assumption, so intervals may be too narrow.",
                            "Gold may contain annotation errors. No manual gold correction was made to improve accuracy.",
                            "Same audit supplies candidate constants and error estimates; candidates require independent validation.",
                            "Cached model outputs and unavailable-provider fallbacks differ from a fully live run.",
                            "No training or thresholds were changed based on held-back files."],
            "observations": records}


class CalibrationTests(unittest.TestCase):
    def test_wilson_contains_observed(self):
        lo, hi = wilson(5, 10)
        self.assertLess(lo, .5); self.assertGreater(hi, .5)

    def test_zero_and_perfect_have_uncertainty(self):
        self.assertGreater(wilson(0, 5)[1], 0)
        self.assertLess(wilson(5, 5)[0], 1)

    def test_excludes_own_and_missing_card(self):
        doc = {"rows": [{"case": {"gold_kind": None}, "response": {}, "outcome": "unscored"},
                        {"case": {"gold_kind": "dataset", "type": "count"}, "response": {}, "outcome": "wrong"}]}
        out = calibrate(doc)
        self.assertEqual(out["summary"]["n"], 0)
        self.assertEqual(out["excluded"], {"no_independent_gold": 1, "missing_card_on_numeric_gold": 1})

    def test_observed_not_confidence(self):
        rs = [{"outcome": "wrong", "pct": 97, "doc_id": "a"}, {"outcome": "correct", "pct": 97, "doc_id": "b"}]
        self.assertEqual(stats(rs)["observed_accuracy"], .5)
        self.assertEqual(stats(rs)["overconfidence_pp"], 47.)

    def test_loader_buckets_are_measured_and_units_separate(self):
        rows = []
        for i, (outcome, unit, pct) in enumerate((("correct", "count", 97), ("wrong", "count", 97), ("correct", "m2", None))):
            rows.append({"case": {"gold_kind": "dataset", "case_id": str(i), "doc_id": str(i), "source": "dataset", "format": "ifc", "type": "area" if unit == "m2" else "count", "question": "Question?"},
                         "outcome": outcome, "response": {"route": "index", "answer": {"unit": unit}, "reasoning": {"confidence": {"label": "Verified", "pct": pct, "reason": "Read from the model."}}}})
        out = calibrate({"rows": rows})
        self.assertEqual(len(out["buckets"]), 2)
        count = next(b for b in out["buckets"] if b["unit"] == "count")
        self.assertEqual((count["n"], count["correct"], count["accuracy"], count["source"]), (2, 1, .5, "ifc"))
        self.assertNotIn("checked", count)
        self.assertEqual(out["summary"]["predictions"], 2)

    def test_cad_vision_fallback_does_not_calibrate_cad_base(self):
        row = {"case": {"gold_kind": "dataset", "case_id": "test", "doc_id": "drawing", "source": "dataset", "format": "dxf", "type": "area", "question": "Area?"},
               "outcome": "wrong", "response": {"route": "hybrid", "trace": [{"step": "reader", "model": "vision-model"}], "answer": {"unit": "m²"},
               "reasoning": {"confidence": {"label": "Estimate", "pct": 62, "reason": "Read from the image."}}}}
        out = calibrate({"rows": [row]})
        self.assertEqual((out["buckets"][0]["source"], out["buckets"][0]["unit"]), ("vision", "m2"))
        self.assertIsNone(next(p for p in out["proposed_confidence_constants"] if p["current"] == 95)["candidate"])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=ROOT / "results/final/QA2/evidence_audit.json")
    p.add_argument("--output", type=Path, default=ROOT / "results/final/QA2/calibration.json")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        unittest.main(argv=[sys.argv[0]], exit=True)
    out = calibrate(json.loads(args.input.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: out[k] for k in ("summary", "excluded", "buckets_by_label_and_pct")}, indent=2))


if __name__ == "__main__":
    main()
