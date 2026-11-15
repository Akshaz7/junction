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
    return {"m²": "m2", "m³": "m3", "sqm": "m2", "square metres": "m2", "square meters": "m2",
            "cubic metres": "m3", "cubic meters": "m3", "metres": "m", "meters": "m"}.get(unit, unit)


def headline_numbers(text: str) -> list[str]:
    head = re.sub(r"\[[0-9]+\]", "", (text or "").split("\n", 1)[0])
    return re.findall(r"(?<![\w.,])-?[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?(?!\w|[.,][0-9])", head)


def headline_value(text: str, computed: list[dict], unit: str):
    """Recover one displayed number only when a typed computation agrees.

    Citation numbers are not values. Multiple numbers, room numbers, unrelated
    units and body prose cannot supply a value. Rounding follows the precision
    actually displayed; no fitted numerical threshold is involved.
    """
    tokens = headline_numbers(text)
    if len(tokens) != 1:
        return None
    head = (text or "").split("\n", 1)[0].replace("**", "")
    if re.search(r"\b(?:room|apartment|flat|unit|level|storey|floor)\s+[0-9]+\b|\b[A-Za-z]+[-_][0-9]+\b", head, re.I):
        return None  # a single room/floor/tag number is still an identifier, not a quantity
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


def guard_answer_value(res: dict, question: str, doc_ids: list[str], root, hidden=None) -> dict:
    """Last resort: only a matching solver computation may restore a missing field."""
    res = guard_count(res, question, doc_ids, root, hidden)
    a = res.get("answer") or {}
    p = parse(question)
    expected = "count" if count_question(question) else {"area": "m2", "length": "m", "volume": "m3"}.get(p.type)
    tokens = headline_numbers(a.get("text_md"))
    if a.get("abstained") or a.get("value") is not None or not expected or not tokens:
        return res
    from engine.solvers.solve import solve, _step, _abstain
    import time
    if hidden and not isinstance(hidden, dict):
        hidden = {iid: "selected item" for iid in hidden}
    for did in doc_ids:
        try:
            source = solve(question, did, parsed=p, root=root, hidden=hidden)
        except Exception:
            continue
        sa = source["answer"]
        if sa.get("abstained"):
            continue
        computed = [{"value": sa.get("value"), "unit": sa.get("unit")}]
        if headline_value(a.get("text_md"), computed, expected) is not None:
            # Retain the solver's own citations and wording along with its value.
            source["trace"] = list(res.get("trace") or []) + [_step("numeric_guard", "missing numeric field restored from a matching solver computation")] + source.get("trace", [])
            source["cost"] = res.get("cost", source["cost"])
            return source
    trace = list(res.get("trace") or []) + [_step("numeric_guard", "numeric headline withheld: no single matching solver computation")]
    out = _abstain(question, doc_ids[0] if doc_ids else "", "I could not verify a numeric answer for the requested items from the available data.",
                   trace, res.get("route", "index"), time.perf_counter())
    out["doc_ids"] = list(doc_ids)
    out["cost"] = res.get("cost", out["cost"])
    return out


def guard_count(res: dict, question: str, doc_ids: list[str], root, hidden=None) -> dict:
    """Retry a dimensionally wrong count through the count solver, or abstain."""
    ans = res.get("answer") or {}
    if not count_question(question) or ans.get("abstained") or ans.get("value") is None:
        return res
    value = ans["value"]
    valid = (all(whole_count(v) for v in value.values()) if isinstance(value, dict) and value else whole_count(value))
    if ans.get("unit") == "count" and valid:
        ans["value"] = {k: int(v) for k, v in value.items()} if isinstance(value, dict) else int(value)
        return res
    from engine.solvers.solve import _abstain, _step, solve
    import time
    if hidden and not isinstance(hidden, dict):
        hidden = {iid: "selected item" for iid in hidden}
    trace = list(res.get("trace") or [])
    trace.append(_step("numeric_guard", "count question received a non-count quantity; retried the count solver"))
    for did in doc_ids:
        try:
            candidate = solve(question, did, parsed=parse(question), root=root, hidden=hidden)
        except Exception:  # a failed retry must preserve the engine's never-raise contract
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
