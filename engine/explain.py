"""E-77: plain-language explanation of code answers.

Code answers (plan map / IFC index) are exact but terse ("There is **1 bathroom**."). This step hands the exact
result, the cited elements with their own measured values, and how the number was worked out to the answer writer
(task write_answer), which explains it in a few sentences and answers every part of the question the facts cover.
Guard rails: every number in the code answer's bold headline must survive, the [n] markers must survive, and on any
failure, timeout or missing fact the original text is kept. Off with EXPLAIN=0 (and always off with MODELS_FAKE=1).
"""
from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path

PROMPT = """You explain answers about construction drawings and BIM models to a site manager.

QUESTION: {q}

EXACT RESULT (computed by code from the file; its numbers are correct and final):
{a}

ELEMENTS CITED ([n] is the citation marker shown on the drawing):
{items}

DRAWING SUMMARY: {summary}

HOW IT WAS WORKED OUT:
{how}

Write the answer in plain English, easy to scan: the direct answer in bold on the first line, then up to 4 short bullet points ('- ' prefix), one fact each. Content:
1. Start with the direct answer in bold, using exactly the numbers from EXACT RESULT.
2. Add bullets ONLY for parts of the question beyond the headline (e.g. 'and how big', 'which ones'); if the bold line already answers everything, output only that line. At most 3 bullets, each under 15 words. Never mention citations, listings or what you cannot see.
3. Do NOT describe where the answer came from, how it was measured or how sure it is: a separate evidence panel shows that. Only give facts that answer the question.
4. If part of the question cannot be answered from these facts, say so plainly in one sentence. Never invent a value, a rule or a source.
Never show machine ids (long codes like 18PQUIFELEARLM4c0brquf or door-003); describe the element by its name, size or storey instead.
Keep every [n] marker from EXACT RESULT next to the thing it cites. No headings, no long paragraphs, no preamble."""

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _fmt(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{f:,.2f}".rstrip("0").rstrip(".")


def _facts(res: dict, root: Path) -> tuple[str, str]:
    from engine.solvers.data import load_doc
    lines, summary = [], ""
    by_doc: dict[str, list] = {}
    for c in res.get("citations") or []:
        by_doc.setdefault(c.get("doc_id"), []).append(c)
    for did, cites in list(by_doc.items())[:2]:
        doc = load_doc(did, root) if did else None
        if doc is None:
            for c in cites[:20]:
                lines.append(f"[{c.get('n')}] {c.get('label') or ''} {('“' + c['quote'] + '”') if c.get('quote') else ''}".strip())
            continue
        items = {i.item_id: i for i in doc.items}
        from collections import Counter
        cnt = Counter(i.kind for i in doc.items if i.kind not in ("text",))
        summary = (f"{'IFC model' if doc.mode == 'ifc' else 'plan map read from the drawing'} '{doc.title or did}': "
                   + ", ".join(f"{v} {k}s" for k, v in cnt.most_common(8)))
        for c in cites[:25]:
            parts = []
            for iid in (c.get("item_ids") or [])[:6]:
                it = items.get(iid)
                if it is None:
                    continue
                q = {k: _fmt(v) for k, v in (it.q or {}).items() if v not in (None, "") and not isinstance(v, (list, dict))}
                pr = {k: v for k, v in (it.props or {}).items() if k in ("room_type", "is_external", "material", "type", "name", "width_m", "height_m", "thickness_m") and v not in (None, "")}
                parts.append(f"{it.kind} {it.label or iid}" + (f" on {it.storey}" if getattr(it, "storey", None) else "")
                             + (f" {q}" if q else "") + (f" {pr}" if pr else ""))
            lines.append(f"[{c.get('n')}] " + ("; ".join(parts) if parts else (c.get("label") or "")))
    return "\n".join(lines) or "(none)", summary or "(not available)"


def _ok(orig: str, new: str) -> bool:
    if not new or len(new) < 20 or len(new) > 2500:
        return False
    head = re.findall(r"\*\*(.+?)\*\*", orig)
    nums = set(_NUM.findall(re.sub(r"\[\d+\]", "", " ".join(head) if head else orig[:200])))
    new_nums = {n.replace(",", "") for n in _NUM.findall(re.sub(r"\[\d+\]", "", new))}
    if any(n.replace(",", "") not in new_nums for n in nums):
        return False
    # Explanations may preserve/format facts, never introduce new measurements
    # or speculative code ratings alongside an otherwise correct headline.
    allowed = {n.replace(",", "") for n in _NUM.findall(re.sub(r"\[\d+\]", "", orig))}
    if not new_nums <= allowed:
        return False
    marks = set(re.findall(r"\[\d+\]", orig))
    return marks <= set(re.findall(r"\[\d+\]", new))


def explain(res: dict, question: str, root: Path, timeout_s: float = 12.0, on_event=None) -> dict:
    if "quantity_rows" in res: return res  # Keep exact IFC filters, missing-data notes and measurement rules.
    if "wallarea" in res: return res  # preserve exact finish arithmetic and explicit source limitations
    if os.environ.get("EXPLAIN", "1") == "0" or os.environ.get("MODELS_FAKE") == "1":
        return res
    ans = res.get("answer") or {}
    if ans.get("unit") == "count":
        return res   # a code count is already exact and short: no paid rewording, $0 and instant
    if any(s.get("step") == "order" for s in res.get("trace") or []):
        return res  # Preserve the table, measurement notes and stated allowance for CSV export.
    if ans.get("abstained") or res.get("route") not in ("planmap", "index") or not res.get("citations"):
        return res
    text = ans.get("text_md") or ""
    if not text or len(text) > 700 or any(s.get("model") and s.get("step") in ("write", "answer", "read", "reader") for s in res.get("trace") or []):
        return res   # model-written answers already explain themselves
    t0 = time.perf_counter()
    future = None
    try:
        items, summary = _facts(res, root)
        how = "\n".join(f"- {s.get('detail')}" for s in (res.get("trace") or [])[:10] if s.get("detail"))
        from engine.models import call
        from engine.models import providers as P
        from engine.assistant import with_system
        msgs = with_system(PROMPT.format(q=question, a=text, items=items, summary=summary, how=how))
        # Explanations run after the core's streaming context has been reset.
        # Only publish prefixes that already preserve the exact headline/citations.
        sink = (lambda txt: on_event("answer.delta", {"text": txt}) if _ok(text, txt) else None) if on_event else P.DELTA_SINK.get()
        token = P.DELTA_SINK.set(sink)
        try:
            with ThreadPoolExecutor(1) as ex:
                future = ex.submit(copy_context().run, call, "write_answer", msgs)
                r = future.result(timeout=timeout_s)
        finally:
            P.DELTA_SINK.reset(token)
        new = (r.text or "").strip()
    except Exception:  # noqa: BLE001 — the exact code answer always stands on its own
        # The executor has joined by this point. A late paid result must be
        # accounted for even when the explanation deadline rejected its wording.
        if future is None or not future.done() or future.exception() is not None:
            return res
        r, new = future.result(), ""
    # Paid calls still cost money when the wording fails validation.
    usd = getattr(r, "cost_usd", 0) or 0
    cost = res.setdefault("cost", {"usd_total": 0, "calls": []})
    cost.setdefault("calls", []).append({"task": "write_answer", "provider": r.provider, "model": r.model, "cost_usd": usd})
    cost["usd_total"] = round((cost.get("usd_total") or 0) + usd, 6)
    if not _ok(text, new):
        res.setdefault("trace", []).append({"step": "explain", "detail": "explanation did not keep the exact numbers; kept the code answer",
                                            "ms": int((time.perf_counter() - t0) * 1000), "model": getattr(r, "model", None), "cost_usd": getattr(r, "cost_usd", 0) or 0})
        return res
    ans["text_md"] = new
    res.setdefault("trace", []).append({"step": "explain", "detail": "explained in plain words from the cited elements (numbers unchanged)",
                                        "ms": int((time.perf_counter() - t0) * 1000), "model": r.model, "cost_usd": usd})
    return res
