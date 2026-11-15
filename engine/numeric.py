"""Numeric answer invariants. Only structured computations can fill a missing value."""
from __future__ import annotations

import math
import re

from engine.router.parser import clean, parse


def count_question(question: str) -> bool:
    """An object count, including area-filtered counts, but not 'how many m²'."""
    q = clean(question)
    if re.search(r"\bhow many\s+(?:square|cubic|sq\b|m[²³23]\b|met(?:er|re)s?\b|feet\b|ft\b)", q):
        return False
    return parse(question).type == "count"


def whole_count(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0 and int(value) == value)


def unit_name(unit):
    return {"m²": "m2", "m³": "m3", "sqm": "m2"}.get(unit, unit)


def headline_value(text: str, computed: list[dict], unit: str):
    """Recover one displayed number only when a typed computation agrees.

    Citation numbers are not values. Multiple numbers, room numbers, unrelated
    units and body prose cannot supply a value. Rounding follows the precision
    actually displayed; no fitted numerical threshold is involved.
    """
    head = re.sub(r"\[[0-9]+\]", "", (text or "").split("\n", 1)[0])
    tokens = re.findall(r"(?<![\w.])-?[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?(?![\w])", head)
    if len(tokens) != 1:
        return None
    token = tokens[0].replace(",", "")
    shown = float(token)
    precision = len(token.partition(".")[2])
    matches = set()
    for result in computed:
        value = result.get("value")
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(value) or unit_name(result.get("unit")) != unit_name(unit)):
            continue
        if unit == "count" and not whole_count(value):
            continue
        if round(value, precision) == shown:
            matches.add(value)
    return next(iter(matches)) if len(matches) == 1 else None


def guard_count(res: dict, question: str, doc_ids: list[str], root, hidden=None) -> dict:
    """Retry a dimensionally wrong count through the count solver, or abstain."""
    ans = res.get("answer") or {}
    if not count_question(question) or ans.get("abstained") or ans.get("value") is None:
        return res
    value = ans["value"]
    valid = (all(whole_count(v) for v in value.values()) if isinstance(value, dict) and value else whole_count(value))
    if ans.get("unit") == "count" and valid:
        if not isinstance(value, dict):
            ans["value"] = int(value)
        return res
    from engine.solvers.solve import _abstain, _step, solve, SolverUnsupported
    import time
    trace = list(res.get("trace") or [])
    trace.append(_step("numeric_guard", "count question received a non-count quantity; retried the count solver"))
    for did in doc_ids:
        try:
            candidate = solve(question, did, parsed=parse(question), root=root, hidden=hidden)
        except (SolverUnsupported, ValueError, TypeError):
            continue
        a = candidate["answer"]
        v = a.get("value")
        valid = all(whole_count(n) for n in v.values()) if isinstance(v, dict) and v else whole_count(v)
        if not a.get("abstained") and a.get("unit") == "count" and valid:
            candidate["trace"] = trace + candidate.get("trace", [])
            candidate["cost"] = res.get("cost", candidate["cost"])
            return candidate
    out = _abstain(question, doc_ids[0] if doc_ids else "", "I could not verify a whole-number count for the requested items. The available measurement is not a count.",
                   trace, res.get("route", "index"), time.perf_counter())
    out["doc_ids"] = list(doc_ids)
    out["cost"] = res.get("cost", out["cost"])
    return out
