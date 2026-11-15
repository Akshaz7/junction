"""Compare a fake-provider sample with live reads of previously lost answers.

Run through scripts/heavy.sh. Baseline rows identify the regressions; they do
not influence any production code. No gold value enters a model prompt.
"""
import argparse
import json
import os
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--failed", type=Path, required=True)
    ap.add_argument("--output", type=Path, default=Path("results/final/HONEST/round2"))
    ap.add_argument("--reuse-live", action="store_true")
    args = ap.parse_args()
    os.environ.update(MODELS_FAKE="1", EXPLAIN="0", ANSWER_TIMEOUT_S="0",
                      MODELS_CACHE_DIR=str(Path(".honest-replay/model-cache").resolve()),
                      MODELS_COSTS_LOG=str(Path(".honest-replay/round2-costs.jsonl").resolve()),
                      RESULTS_DIR=str(Path(".honest-replay/round2-recount").resolve()))
    from engine.answer import answer
    from engine.bench import load_set, run, score, summarize
    key = lambda r: (r["doc_id"], r["question"])
    baseline = {key(r): r for r in map(json.loads, args.baseline.read_text().splitlines())}
    failed = {key(r): r for r in map(json.loads, args.failed.read_text().splitlines())}
    lost = {k for k in baseline if baseline[k]["outcome"] == "correct" and failed[k]["outcome"] == "abstained"}
    args.output.mkdir(parents=True, exist_ok=True)
    fake_path = args.output / "sample200-after.json"
    if not fake_path.exists():
        fake_path.write_text(json.dumps(run(load_set("sample200"), concurrency=2), indent=1) + "\n")
    after = json.loads(fake_path.read_text())
    live_path = args.output / "three-live.json"
    spent = [0.]
    if not args.reuse_live:
        os.environ.pop("MODELS_FAKE", None)
        import engine.models
        original = engine.models.call
        def capped(*a, **kw):
            if spent[0] >= 2.50:
                raise RuntimeError("Replay cost cap reached")
            result = original(*a, **kw)
            spent[0] += result.cost_usd
            return result
        engine.models.call = capped
        live = []
        for row in load_set("sample200"):
            if key(row) in lost:
                result = answer(row["question"], [row["doc_id"]])
                live.append({"row": row, "result": result, "outcome": score(row, result)})
                live_path.write_text(json.dumps(live, indent=1) + "\n")
                print(row["doc_id"], result["answer"], flush=True)
    live = {key(r["row"]): r for r in json.loads(live_path.read_text())}
    assert set(live) == lost, "Live checks must cover every lost baseline answer"
    before = json.loads((args.output / "sample200-merged-before.json").read_text())
    before_rows, after_rows = [], []
    for r in before["results"]:
        before_rows.append(baseline[key(r)] if key(r) in lost else r)
    for r in after["results"]:
        if key(r) in lost:
            result = live[key(r)]["result"]
            r = {**r, "outcome": live[key(r)]["outcome"], **{k: result["answer"].get(k) for k in ("value", "unit", "confidence")},
                 "text": result["answer"]["text_md"], "cost_usd": result["cost"]["usd_total"], "route": result["route"],
                 "boxes": len(result["evidence"]["boxes"]), "ms": result["latency_ms"]}
        after_rows.append(r)
    current = {key(r): r for r in after_rows}
    regressions = [{"before": r, "after": current[key(r)]} for r in before_rows
                   if r["outcome"] == "correct" and current[key(r)]["outcome"] != "correct"]
    report = {"mode": "197 fake-provider questions and 3 real-provider source reads; matched modes before/after",
              "baseline_live": str(args.baseline), "failed_live": str(args.failed),
              "before": summarize(before_rows)["ALL x ALL"], "after": summarize(after_rows)["ALL x ALL"],
              "live_checks": [{"doc_id": k[0], "question": k[1], "before": baseline[k], "failed": failed[k],
                               "after": live[k]["result"]["answer"], "outcome": live[k]["outcome"]} for k in sorted(lost)],
              "correct_to_wrong_or_abstained": regressions,
              "new_live_spend_usd": round(spent[0], 6),
              "reused_live_results": args.reuse_live,
              "live_answer_cost_usd": round(sum(r["result"]["cost"]["usd_total"] for r in live.values()), 6),
              "note": "This mixed-provider check is not a full-live sample200 accuracy score. Cached real-provider responses remain real reads."}
    (args.output / "sample200-mixed-after.json").write_text(json.dumps(after_rows, indent=1) + "\n")
    (args.output / "sample200-comparison.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: report[k] for k in ("before", "after", "correct_to_wrong_or_abstained")}, indent=1))
    assert not regressions and all(r["outcome"] == "correct" for r in live.values())


if __name__ == "__main__":
    main()
