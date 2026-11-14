"""Dashboard summaries from measured bench results and persisted answer costs."""
import json
import math
import os
from pathlib import Path
from statistics import median

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from . import config, db

router = APIRouter(prefix="/api")
PREFERRED_TAG = "e-s200-z1"  # docs/REPORT.md's completed real-provider sample


def summaries() -> list[dict]:
    # RESULTS_DIR is writable runtime storage; the image keeps measured results under /app/results.
    paths = [config.results_dir() / "bench", config.REPO / "results" / "bench"]
    found = {}
    for directory in paths:
        for path in directory.glob("*.json"):
            if path.name in found or path.name.endswith(".rows.json"):
                continue
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                data = json.loads(path.read_text())
                if not isinstance(data, dict):
                    continue
                found[path.name] = {"path": path, "file": path.name, "stem": path.stem,
                                    "tag": str(data.get("tag") or path.stem), "data": data,
                                    "set": data.get("set"), "fake": data.get("fake"),
                                    "mtime": path.stat().st_mtime}
            except (OSError, ValueError):
                continue
    return sorted(found.values(), key=lambda r: (r["mtime"], r["file"]), reverse=True)


def complete_real_run(data: dict) -> bool:
    totals = data.get("totals", {})
    cells = data.get("cells", {})
    if not isinstance(totals, dict) or not isinstance(cells, dict):
        return False
    n = totals.get("questions")
    return (data.get("fake") is False and isinstance(n, int) and n > 0
            and n == totals.get("of") and not totals.get("stopped_by_max_usd")
            and isinstance(cells.get("ALL x ALL"), dict) and cells["ALL x ALL"].get("n") == n)


def latest_bench(tag: str | None = None):
    found = summaries()
    if tag is not None:
        # Explicit historical selections retain raw data, including fake runs for debugging.
        found = [r for r in found if tag in (r["tag"], r["stem"])]
        if not found:
            return JSONResponse({"status": "no_bench", "detail": f"no bench results for tag {tag!r}"},
                                status_code=404)
    else:
        found = [r for r in found if complete_real_run(r["data"])]
        preferred = next((r for r in found if r["tag"] == PREFERRED_TAG), None)
        if preferred:
            found = [preferred]
    if not found:
        # Keep the dashboard available without presenting missing measurements as zero.
        return {"status": "no_bench", "detail": "No completed real-provider benchmark is available.",
                "tag": None, "n": None, "numeric_correct": None, "numeric_total": None,
                "accuracy": None, "abstentions": None, "by_type": {}, "cost_usd_total": None,
                "cost_per_answer": None, "file": None, "data": None}
    run = found[0]
    data = run["data"]
    cells = data.get("cells") if isinstance(data.get("cells"), dict) else {}
    overall = cells.get("ALL x ALL", {})
    n = overall.get("n")
    unscored = overall.get("unscored")
    return {"file": run["file"], "tag": run["tag"], "data": data, "n": n,
            "numeric_correct": overall.get("correct"),
            "numeric_total": n - unscored if n is not None and unscored is not None else None,
            "accuracy": overall.get("accuracy"), "abstentions": overall.get("abstained"),
            "by_type": {k.removeprefix("ALL x "): v for k, v in cells.items()
                        if k.startswith("ALL x ") and k != "ALL x ALL"},
            "cost_usd_total": overall.get("cost_usd_total"),
            "cost_per_answer": overall.get("cost_usd_per_answer")}


def _usd(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _answer_cost(answer):
    if isinstance(answer, str):  # asyncpg's default JSONB codec
        try:
            answer = json.loads(answer)
        except ValueError:
            return None, None
    if not isinstance(answer, dict):
        return None, None
    cost = answer.get("cost")
    value = _usd(cost.get("usd_total")) if isinstance(cost, dict) else None
    if value is not None:
        return value, "answer.cost.usd_total"
    trace = answer.get("trace")
    if isinstance(trace, list):
        values = [_usd(step.get("cost_usd")) for step in trace if isinstance(step, dict)]
        if any(v is not None for v in values):
            return sum(v for v in values if v is not None), "answer.trace"
    return None, None


def _model_spend():
    path = Path(os.environ.get("MODELS_COSTS_LOG") or config.results_dir() / "costs.jsonl")
    values = []
    try:
        with path.open() as lines:
            for line in lines:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                value = _usd(row.get("cost_usd")) if isinstance(row, dict) else None
                if value is not None:
                    values.append(value)
    except FileNotFoundError:
        pass
    return {"total_usd": round(sum(values), 8), "calls": len(values), "spend_source": "model_cost_log"}


@router.get("/costs/summary")
async def costs_summary():
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    rows = await pool.fetch("select answer from answers where created_at >= now() - interval '24 hours'")
    values = []
    sources = {}
    for row in rows:
        value, source = _answer_cost(row["answer"])
        if value is not None:
            values.append(value)
            sources[source] = sources.get(source, 0) + 1
    return {**_model_spend(), "window_hours": 24, "answers": len(rows),
            "answers_with_cost": len(values), "answers_missing_cost": len(rows) - len(values),
            "answer_cost_usd_total": round(sum(values), 8),
            "median_cost_per_answer": median(values) if values else None,
            "cost_sources": sources}
