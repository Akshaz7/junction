"""Read-only local replay of the judge simulation and sample200.

Run via scripts/heavy.sh. Downloaded source sidecars live outside tracked results;
only answers/measurements are written to results/final/HONEST.
"""
import argparse
import json
import os
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("before", "after"))
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--artifacts", type=Path, required=True)
    ap.add_argument("--output", type=Path, default=Path("results/final/HONEST"))
    ap.add_argument("--live", action="store_true", help="Replay only judges with real models, maximum $2.50.")
    args = ap.parse_args()
    os.environ.update(MODELS_FAKE="1", EXPLAIN="0", ANSWER_TIMEOUT_S="0",
                      MODELS_CACHE_DIR=str(Path('.honest-replay/model-cache').resolve()),
                      MODELS_COSTS_LOG=str(Path('.honest-replay/model-costs.jsonl').resolve()))
    from engine.answer import answer
    from engine.bench import load_set, run
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    if not args.live:
        sample = run(load_set("sample200"), concurrency=2)
        (out / f"sample200-{args.phase}.json").write_text(json.dumps(sample, indent=1) + "\n")
        print("sample200", sample["totals"], flush=True)
    else:
        os.environ.pop("MODELS_FAKE", None)
        import engine.models
        call, spent = engine.models.call, [0.]
        def capped(*a, **kw):
            if spent[0] >= 2.50:
                raise RuntimeError("F-HONEST live replay budget exhausted")
            result = call(*a, **kw)
            spent[0] += result.cost_usd
            return result
        engine.models.call = capped
    os.environ["ARTIFACTS_DIR"] = str(args.artifacts.resolve())
    report = json.loads(args.report.read_text())
    rows = []
    for case in report["answers"]:
        result = answer(case["question"], [case["doc_id"]])
        rows.append({"file": case["file"], "question": case["question"], "q": case["q"],
                     "original_verdict": case.get("verdict"), "result": result})
        print(case["file"], case["q"], result["answer"]["value"], result["answer"]["unit"], flush=True)
        suffix = "-live" if args.live else ""
        (out / f"judge-{args.phase}{suffix}.json").write_text(json.dumps(rows, indent=1) + "\n")
    if args.live:
        (out / f"judge-{args.phase}-live-spend.json").write_text(json.dumps({"model_call_cost_usd": round(spent[0], 6),
             "returned_answer_cost_usd": round(sum(r['result']['cost']['usd_total'] for r in rows), 6),
             "note": "All model calls counted, including discarded router/reader results; answer cost fields omit some of those calls."}, indent=1) + "\n")
        print("live model cost USD", spent[0], flush=True)


if __name__ == "__main__":
    main()
