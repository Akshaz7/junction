"""E-05 bench: run engine.answer over a question set and score it.

CLI:  python -m engine.bench --set sample200|sample1000.full|full --tag <t> --max-usd <n> [--concurrency 4] [--limit N] [--fake]
Importable:  engine.bench.run(questions, answer_fn=answer, concurrency=4, max_usd=None) -> dict

Scoring (numbers only; the gold answer comes from the dataset row):
  count  exact;  area/length/volume  within 2% or 0.05 absolute.
  text   kept out of the numeric accuracy ("unscored"); judged apart by the `judge_text` task (cached, cheap model):
         verdict correct|partial|wrong, or abstained when the answer abstained. Reported in `text` of the result file.
  abstained answers count as not correct; `answered_accuracy` leaves them out.
Writes results/bench/<tag>.json (summary, per source x type cells) and <tag>.rows.jsonl.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
SETS = {
    "sample200": "data/sets/sample200.jsonl",
    "sample1000.full": "data/sets/sample1000.full.jsonl",
    "full": "data/sets/questions_en.full.jsonl",
}
NUMERIC = ("count", "area", "length", "volume")


def load_set(name: str) -> list[dict]:
    p = ROOT / SETS.get(name, name)
    if name == "full" and not p.exists():
        p = ROOT / "data/sets/questions_en.jsonl"
    return [json.loads(l) for l in p.open(encoding="utf-8")]


def _num(x):
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    if isinstance(x, str):
        m = re.search(r"-?\d+(?:[.,]\d+)?", x.replace(" ", ""))
        if m:
            return float(m.group(0).replace(",", "."))
    return None


def score(row: dict, ans: dict) -> str:
    """-> correct | wrong | abstained | unscored"""
    a = ans["answer"]
    if row["type"] not in NUMERIC:
        return "unscored"
    if a.get("abstained") or a.get("value") is None:
        return "abstained"
    gold, got = _num(row["answer"]), _num(a["value"])
    if gold is None or got is None:
        return "unscored"
    if row["type"] == "count":
        return "correct" if round(got) == round(gold) else "wrong"
    return "correct" if abs(got - gold) <= max(0.05, 0.02 * abs(gold)) else "wrong"


JUDGE_SCHEMA = {"type": "object", "properties": {"verdict": {"type": "string", "enum": ["correct", "partial", "wrong"]},
                "reason": {"type": "string"}}, "required": ["verdict"]}
JUDGE_PROMPT = ("You grade a building-data assistant. Compare ANSWER to the GOLD answer for the QUESTION.\n"
                "correct = same facts and numbers (wording and detail level may differ; a gold 'not available' matches an answer that says "
                "the data is missing); partial = some gold facts right but others missing or wrong; wrong = contradicts the gold or "
                "gives unrelated facts. Reply JSON: {\"verdict\": ..., \"reason\": <one short sentence>}.\n\n"
                "QUESTION: %s\nGOLD: %s\nANSWER: %s")


def judge_text(question: str, gold, text: str) -> tuple[str | None, float]:
    """-> (verdict | None when no judge model is reachable, usd). Goes through call(); cached on disk."""
    try:
        from engine.models import call
        r = call("judge_text", [{"role": "user", "content": JUDGE_PROMPT % (question, str(gold)[:1500], text[:1500])}], schema=JUDGE_SCHEMA)
        v = (r.json or {}).get("verdict") if isinstance(r.json, dict) else None
        return (v if v in ("correct", "partial", "wrong") else None), r.cost_usd
    except Exception:
        return None, 0.0


def _one(row: dict, answer_fn: Callable, judge: bool = True) -> dict:
    t = time.perf_counter()
    try:
        ans = answer_fn(row["question"], [row["doc_id"]], None)
        err = None
    except Exception as e:  # a crash is a result, not a stop
        ans = {"answer": {"abstained": True, "value": None, "text_md": ""}, "cost": {"usd_total": 0}, "route": "error", "trace": []}
        err = f"{type(e).__name__}: {e}"[:200]
    ms = int((time.perf_counter() - t) * 1000)
    verdict, judge_usd = None, 0.0
    if row["type"] not in NUMERIC and not err:
        abst = bool(ans["answer"].get("abstained"))
        if judge and not os.environ.get("MODELS_FAKE") and ans["answer"].get("text_md"):
            # an abstention can still be right ("no heating system in this model" vs gold "none found"): judge it too
            verdict, judge_usd = judge_text(row["question"], row["answer"], ans["answer"].get("text_md", ""))
            if abst and verdict in ("wrong", None):
                verdict = "abstained"
        elif abst:
            verdict = "abstained"
    return {
        "doc_id": row["doc_id"], "source": row["source"], "type": row["type"], "question": row["question"],
        "gold": row["answer"], "value": ans["answer"].get("value"), "unit": ans["answer"].get("unit"),
        "confidence": ans["answer"].get("confidence"), "outcome": score(row, ans) if not err else "error",
        "route": ans.get("route"), "cost_usd": ans["cost"]["usd_total"], "ms": ms,
        "boxes": len(ans.get("evidence", {}).get("boxes", [])), "text": ans["answer"].get("text_md", "")[:300], "error": err,
        "text_verdict": verdict, "judge_usd": judge_usd,
    }


def summarize(results: list[dict]) -> dict:
    cells: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    lat: dict[str, list[int]] = defaultdict(list)
    cost: dict[str, float] = defaultdict(float)
    for r in results:
        for key in (f"{r['source']} x {r['type']}", f"{r['source']} x ALL", f"ALL x {r['type']}", "ALL x ALL"):
            c = cells[key]
            c["n"] += 1
            c[r["outcome"]] += 1
            lat[key].append(r["ms"])
            cost[key] += r["cost_usd"]
    out = {}
    for k, c in sorted(cells.items()):
        scored = c["n"] - c["unscored"]
        answered = c["correct"] + c["wrong"]
        ls = sorted(lat[k])
        out[k] = {
            "n": c["n"], "correct": c["correct"], "wrong": c["wrong"], "abstained": c["abstained"],
            "unscored": c["unscored"], "error": c["error"],
            "accuracy": round(c["correct"] / scored, 4) if scored else None,
            "answered_accuracy": round(answered and c["correct"] / answered, 4) if answered else None,
            "cost_usd_total": round(cost[k], 6), "cost_usd_per_answer": round(cost[k] / c["n"], 8),
            "latency_ms_mean": int(sum(ls) / len(ls)), "latency_ms_p95": ls[int(0.95 * (len(ls) - 1))],
        }
    return out


def summarize_text(results: list[dict]) -> dict:
    """Text answers, scored apart: by source and ALL. accuracy = correct / judged; partial counts half in `score`."""
    out: dict[str, dict] = {}
    for r in results:
        if r["type"] in NUMERIC:
            continue
        for key in (r["source"], "ALL"):
            c = out.setdefault(key, defaultdict(int))
            c["n"] += 1
            c[r.get("text_verdict") or "unjudged"] += 1
            c["judge_usd"] += r.get("judge_usd", 0.0)
    res = {}
    for k, c in out.items():
        judged = c["correct"] + c["partial"] + c["wrong"]
        res[k] = {"n": c["n"], "correct": c["correct"], "partial": c["partial"], "wrong": c["wrong"], "abstained": c["abstained"],
                  "unjudged": c["unjudged"], "accuracy": round(c["correct"] / judged, 4) if judged else None,
                  "score": round((c["correct"] + 0.5 * c["partial"]) / judged, 4) if judged else None,
                  "judge_usd": round(c["judge_usd"], 6)}
    return res


def run(questions: list[dict], answer_fn: Callable | None = None, concurrency: int = 4, max_usd: float | None = None,
        progress: Callable[[int, int, float], None] | None = None) -> dict:
    """questions: dataset rows (question, doc_id, source, type, answer). Returns {results, cells, totals}."""
    if answer_fn is None:
        from engine.answer import answer as answer_fn
    t0 = time.perf_counter()
    results: list[dict] = []
    spent = 0.0
    stopped = False
    it = iter(questions)
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as ex:
        pending = set()
        done_n = 0
        while True:
            while len(pending) < max(1, concurrency) * 2 and not stopped:
                row = next(it, None)
                if row is None:
                    break
                pending.add(ex.submit(_one, row, answer_fn))
            if not pending:
                break
            finished = [f for f in pending if f.done()]
            if not finished:
                time.sleep(0.005)
                continue
            for f in finished:
                pending.discard(f)
                r = f.result()
                results.append(r)
                spent += r["cost_usd"]
                done_n += 1
                if progress:
                    progress(done_n, len(questions), spent)
                if max_usd is not None and spent >= max_usd and not stopped:
                    stopped = True
    cells = summarize(results)
    return {"results": results, "cells": cells, "text": summarize_text(results), "totals": {
        "questions": len(results), "of": len(questions), "stopped_by_max_usd": stopped, "cost_usd": round(spent + sum(r.get("judge_usd", 0.0) for r in results), 6),
        "wall_s": round(time.perf_counter() - t0, 2)}}


def _pct(x):
    return "n/a" if x is None else f"{100 * x:.1f} %"


def report_md(tag: str) -> str:
    """docs/ACCURACY.md text from results/bench/<tag>.json (+ .rows.jsonl for abstain reasons). Numbers are copied, never typed."""
    d = json.loads((ROOT / f"results/bench/{tag}.json").read_text())
    rows = [json.loads(l) for l in (ROOT / f"results/bench/{tag}.rows.jsonl").open(encoding="utf-8")]
    cells, t = d["cells"], d["totals"]
    L = [f"# ACCURACY", "",
         f"Generated by `python -m engine.bench --report {tag}` from `results/bench/{tag}.json` and `{tag}.rows.jsonl`. "
         "Every number below is copied from those files. Set: `%s`%s." % (d["set"], " (fake models)" if d.get("fake") else ""), "",
         "Scoring: count exact; area, length, volume within 2 % or 0.05 absolute. Abstained answers count as not correct "
         "(`accuracy`); `answered acc.` leaves them out. Text answers are judged apart (below).", "",
         f"Overall: {t['questions']} questions, cost ${t['cost_usd']} in total (answers + judge), wall {t['wall_s']} s. Wall includes judge calls; per-answer $ and latency below exclude the judge.", "",
         "## By source and type (numeric, text excluded from accuracy)", "",
         "| source x type | n | correct | wrong | abstained | unscored | accuracy | answered acc. | $/answer | mean ms | p95 ms |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, c in cells.items():
        L.append(f"| {k} | {c['n']} | {c['correct']} | {c['wrong']} | {c['abstained']} | {c['unscored']} | {_pct(c['accuracy'])} | "
                 f"{_pct(c['answered_accuracy'])} | {c['cost_usd_per_answer']:.6f} | {c['latency_ms_mean']} | {c['latency_ms_p95']} |")
    L += ["", "## Text answers (judged by `judge_text`, cached)", "",
          "| source | n | correct | partial | wrong | abstained | unjudged | accuracy (correct / judged) | score (partial = 0.5) | judge $ |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for k, c in d.get("text", {}).items():
        L.append(f"| {k} | {c['n']} | {c['correct']} | {c['partial']} | {c['wrong']} | {c['abstained']} | {c['unjudged']} | "
                 f"{_pct(c['accuracy'])} | {_pct(c['score'])} | {c['judge_usd']} |")
    L += ["", "Text gold answers are free-form; the judge compares facts and numbers, not wording. Small n: read as a direction, not a score.", "",
          "## What abstains and why (numeric questions)", "", "| source | type | reason given to the user | n |", "|---|---|---|---|"]
    from collections import Counter
    ab = Counter()
    for r in rows:
        if r["outcome"] == "abstained":
            why = re.sub(r"[“\"][^”\"]*[”\"]", "“…”", r["text"].split(".")[0]).strip()
            ab[(r["source"], r["type"], why)] += 1
    for (so, ty, why), n in sorted(ab.items(), key=lambda kv: -kv[1]):
        L.append(f"| {so} | {ty} | {why} | {n} |")
    L += ["", "## Routes", "", "| route | outcome | n |", "|---|---|---|"]
    rc = Counter((r["route"], r["outcome"]) for r in rows)
    for (ro, oc), n in sorted(rc.items(), key=lambda kv: (str(kv[0][0]), -kv[1])):
        L.append(f"| {ro} | {oc} | {n} |")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="sample200")
    ap.add_argument("--tag", default="dev")
    ap.add_argument("--max-usd", type=float, default=None)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--fake", action="store_true", help="MODELS_FAKE=1 (no provider calls)")
    ap.add_argument("--report", metavar="TAG", help="write docs/ACCURACY.md from results/bench/<TAG>.json and exit")
    a = ap.parse_args()
    if a.report:
        (ROOT / "docs/ACCURACY.md").write_text(report_md(a.report))
        print("-> docs/ACCURACY.md")
        return 0
    if a.fake:
        os.environ["MODELS_FAKE"] = "1"
    qs = load_set(a.set)
    if a.limit:
        qs = qs[: a.limit]
    res = run(qs, concurrency=a.concurrency, max_usd=a.max_usd)
    out = ROOT / "results/bench"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.tag}.json").write_text(json.dumps({"set": a.set, "tag": a.tag, "fake": a.fake, **{k: res[k] for k in ("totals", "cells", "text")}}, indent=1))
    with (out / f"{a.tag}.rows.jsonl").open("w") as f:
        for r in res["results"]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{'cell':<34}{'n':>5}{'ok':>5}{'bad':>5}{'abst':>5}{'uns':>5}{'acc':>7}{'$/ans':>11}{'ms':>6}")
    for k, c in res["cells"].items():
        if " x ALL" in k or k.startswith("ALL"):
            print(f"{k:<34}{c['n']:>5}{c['correct']:>5}{c['wrong']:>5}{c['abstained']:>5}{c['unscored']:>5}"
                  f"{(c['accuracy'] if c['accuracy'] is not None else float('nan')):>7.3f}{c['cost_usd_per_answer']:>11.6f}{c['latency_ms_mean']:>6}")
    for k, c in res["text"].items():
        print(f"text {k:<20} n={c['n']} correct={c['correct']} partial={c['partial']} wrong={c['wrong']} abst={c['abstained']} unjudged={c['unjudged']} acc={c['accuracy']}")
    print(json.dumps(res["totals"]))
    print(f"-> results/bench/{a.tag}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
