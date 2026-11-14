"""Document tasks (Stoa starters): Draft claim, Meeting prep, Plan work phase, Review contract.

  detect(question) -> task name | None
  run_task(name, question, doc_ids, history, on_event, trace, t0, root, calls) -> answer object (route "hybrid", never abstains)

Multi-step: (1) gather numbered evidence with code (engine.tasks.evidence: revision changes, page text, plan-map facts, inventory),
(2) write the deliverable with one call("task_write") (Claude Opus 5.5 via runware_claude), citing [n] after every factual sentence,
(3) validate: cites must exist, unsupported figures are flagged, evidence gaps are stated (code adds them when the model forgets),
(4) answer object with citations and boxes in the CONTRACT 5.7 format. Without a document the whole project is the scope; with one,
that document and its revision series are the focus.
"""
from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

from .evidence import Evidence, gather

PATTERNS = {
    "claim": re.compile(r"\b(draft|prepare|write|build|create|compile|put together)\b[^.?!]{0,40}\b(construction\s+|delay\s+|cost\s+)?claim\b|"
                        r"^\s*draft claim\b", re.I),
    "meeting": re.compile(r"\b(prepare|prep|draft|write|create|plan|build)\b[^.?!]{0,50}\b(meeting|agenda)\b|^\s*meeting prep\b", re.I),
    "phase": re.compile(r"\bplan\b[^.?!]{0,40}\b(work\s+phase|construction\s+phase|next\s+phase|work\s+sequence)\b|^\s*plan work phase\b", re.I),
    "contract": re.compile(r"\b(review|check|summari[sz]e|analy[sz]e)\b[^.?!]{0,50}\bcontract\b", re.I),
}
LABEL = {"claim": "Draft claim", "meeting": "Meeting prep", "phase": "Plan work phase", "contract": "Review contract"}

SYSTEM = """You are Hologram's drafting assistant for construction professionals (contractors, site managers, quantity surveyors, \
architects). You write a working document from numbered evidence taken from the project's own files.

Hard rules:
- English. Metric units. Professional, plain, no filler. Use Markdown headings (##) and short bullet lists; no tables.
- Every factual statement (what changed, where, when, what the drawing shows) must end with the evidence number in square brackets, \
like [3] or [2][5]. Use only numbers that appear in the EVIDENCE list. A sentence you cannot support gets no fact.
- Dates, quantities, names and amounts only as they appear in the evidence. Never invent clause numbers, standards, contract terms, \
parties, costs, durations or regulations. Never infer design intent: a revision change is a detected difference between two issues of \
a sheet, so describe it as detected, not as a confirmed scope change.
- Where evidence is missing (cost, delay, entitlement, a contract, a schedule), say so explicitly under a heading "Evidence gaps" and \
say what document would close the gap. Do not fill gaps with plausible text.
- Start with one line: "Draft generated for review: not legal advice." Then the deliverable."""

SPECS = {
    "claim": """Write a construction claim draft. Sections:
## Summary (2-3 sentences: what the documents support and what they do not)
## Documented changes (each: what changed, which sheet and page, the dates of the two issues; cited)
## Affected work (the trades, areas or elements those changes touch, only as far as the evidence shows)
## Chronology (dated events from the evidence, oldest first)
## Cost, delay and entitlement (one short paragraph each; cite what exists; state plainly what is missing)
## Evidence gaps (bullet list; what to collect next)""",
    "meeting": """Write a coordination meeting agenda. Sections:
## Purpose
## Revisions since the last issue (what changed, where, dates; cited)
## Open questions (questions the evidence raises, each tied to the evidence behind it)
## Interfaces between trades (only where the evidence shows two disciplines meeting)
## Decisions needed
## Evidence gaps""",
    "phase": """Write a plan for the next construction work phase. Sections:
## Scope of the phase (from the drawings; cited)
## Work sequence (ordered steps; each step grounded in a cited drawing fact or marked "general practice, not from the documents")
## Dependencies and access (what must be in place first; cited or marked as general practice)
## Checks before starting (inspections, coordination points; cited where the documents show them)
## Missing information (list what the documents do not give: durations, quantities, constraints). Do not invent durations.""",
    "contract": """Review the contract documents. Sections:
## What was reviewed (document names)
## Scope and responsibilities (cited)
## Change procedure and notice requirements (cited, quote the operative words)
## Gaps and risks (what the evidence does not cover)
If no contract document is among the evidence, say so in the first section and list which documents are needed (contract agreement, \
general conditions, change-order forms); then stop.""",
}
CURRENCY = re.compile(r"[$€£]\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|GBP)\b")


def detect(question: str) -> str | None:
    q = (question or "").strip()
    if not q:
        return None
    for name, rx in PATTERNS.items():
        if rx.search(q):
            return name
    return None


def _step(step, detail, ms=0, model=None, cost=0.0):
    return {"step": step, "detail": detail, "ms": ms, "model": model, "cost_usd": cost}


def _evidence_block(ev: Evidence) -> str:
    return "\n".join(f"[{i['n']}] ({i['title']}, page {i['page']}{', ' + i['date'] if i.get('date') else ''}) {i['text'][:640]}" for i in ev.items)


def _prompt(name: str, question: str, ev: Evidence) -> str:
    gaps = "\n".join(f"- {g}" for g in ev.gaps) or "- (none found by the automatic check; still list anything the task needs that the evidence lacks)"
    return (f"TASK: {LABEL[name]}\nUser request: {question}\n\nScope searched: {ev.scope}\n\n{SPECS[name]}\n\n"
            f"Known evidence gaps (state these in the draft):\n{gaps}\n\nEVIDENCE:\n{_evidence_block(ev)}\n")


def _numbers(s: str) -> set[str]:
    s = re.sub(r"\[\d+\]", "", s)
    return {m.replace(",", "").rstrip(".") for m in re.findall(r"\d[\d,]*(?:\.\d+)?", s)}


def _template(name: str, ev: Evidence) -> str:
    """Deterministic draft when no model answers: the evidence, grouped, each line cited."""
    ch = [i for i in ev.items if i.get("change_id")]
    other = [i for i in ev.items if not i.get("change_id")]
    lines = [f"_Draft generated for review: not legal advice. The writing model was unavailable, so this lists the evidence found for **{LABEL[name].lower()}**._", ""]
    if ch:
        lines += ["## Documented changes", *[f"- {i['text']} [{i['n']}]" for i in ch], ""]
    if other:
        lines += ["## Other evidence", *[f"- {i['title']}, page {i['page']}: {i['text'][:240]} [{i['n']}]" for i in other[:12]], ""]
    lines += ["## Evidence gaps", *[f"- {g}" for g in ev.gaps]] if ev.gaps else []
    return "\n".join(lines).strip()


def _gaps_present(text: str) -> bool:
    return bool(re.search(r"evidence gaps?|missing information|not documented|no evidence|not found in the documents", text, re.I))


def run_task(name: str, question: str, doc_ids: list[str], history, on_event, trace: list, t0: float, root: Path, calls: list | None = None) -> dict:
    from engine import models as M
    calls = calls if calls is not None else []
    emit = on_event or (lambda k, p: None)

    def add(step):
        trace.append(step)
        emit("trace", step)

    emit("status", {"text": f"Gathering evidence for: {LABEL[name].lower()}"})
    ts = time.perf_counter()
    ev = gather(name, question, doc_ids, root)
    add(_step("evidence", f"{len(ev.items)} evidence item(s); scope: {ev.scope}" + (f"; gaps: {len(ev.gaps)}" if ev.gaps else ""),
              int((time.perf_counter() - ts) * 1000)))
    if not ev.items:
        add(_step("abstain", "no evidence found for the task"))
        txt = (f"_Draft generated for review._ I found no project evidence for **{LABEL[name].lower()}**: no revision changes, passages or plan-map "
               f"facts in the {ev.docs_searched:,} document(s) searched. Upload the relevant documents in Data"
               + ("" if doc_ids else ", or select a document with @") + ", then ask again.")
        return _finish(question, doc_ids, txt, ev, [], trace, t0, calls, conf=0.3)

    emit("status", {"text": f"Writing the {LABEL[name].lower()}…"})
    text, meta = None, None
    ts = time.perf_counter()
    try:
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _prompt(name, question, ev)}]
        r = M.call("task_write", msgs, images=ev.images[:2] or None)
        meta = {"task": "task_write", "provider": r.provider, "model": r.model, "cost_usd": r.cost_usd}
        calls.append(meta)
        text = (r.text or "").strip()
        if text.startswith("fake:"):
            text = None
        add(_step("write", f"{LABEL[name].lower()} written from {len(ev.items)} evidence item(s)" + (f" and {len(ev.images)} drawing image(s)" if ev.images else ""),
                  int((time.perf_counter() - ts) * 1000), r.model, r.cost_usd))
    except Exception as e:  # noqa: BLE001
        add(_step("write", f"model unavailable ({type(e).__name__}); evidence list used"))
    valid = {i["n"] for i in ev.items}
    if text:
        text = re.sub(r"\[(\d+)\]", lambda m: m.group(0) if int(m.group(1)) in valid else "", text)
        if not re.search(r"\[\d+\]", text):
            add(_step("write", "model text had no valid citation; evidence list used"))
            text = None
    if text:
        unsupported = sorted((_numbers(text) - _numbers(_evidence_block(ev) + " " + question)) - {str(k) for k in range(0, 21)})
        money = [m for m in CURRENCY.findall(text) if m.replace(",", "") not in _evidence_block(ev).replace(",", "")]
        if money:
            add(_step("check", f"amounts not found in the evidence: {', '.join(money[:5])}"))
            text += "\n\n_Check: the amounts " + ", ".join(money[:5]) + " do not appear in the cited documents; verify before use._"
        elif unsupported:
            add(_step("check", f"figures not found verbatim in the evidence: {', '.join(unsupported[:6])}"))
        if ev.gaps and not _gaps_present(text):
            text += "\n\n## Evidence gaps\n" + "\n".join(f"- {g}" for g in ev.gaps)
    else:
        text = _template(name, ev)
    cited = []
    for m in re.finditer(r"\[(\d+)\]", text):
        n = int(m.group(1))
        if n not in cited:
            cited.append(n)
    remap = {old: new for new, old in enumerate(cited, 1)}
    text = re.sub(r"\[(\d+)\]", lambda m: f"[{remap[int(m.group(1))]}]", text)
    return _finish(question, doc_ids, text, ev, cited, trace, t0, calls, conf=0.7 if not ev.gaps else 0.6)


def _finish(question, doc_ids, text, ev: Evidence, cited: list[int], trace, t0, calls, conf) -> dict:
    by_n = {i["n"]: i for i in ev.items}
    cites, boxes = [], []
    for new, old in enumerate(cited, 1):
        it = by_n[old]
        c = {"n": new, "doc_id": it["doc_id"], "page": it["page"], "kind": it["kind"], "bbox_px": it["bbox_px"], "item_ids": [], "quote": it["text"][:400]}
        if it.get("change_id"):
            c["change_id"] = it["change_id"]
        cites.append(c)
        if it["bbox_px"]:
            boxes.append({"item_id": f"cite-{new}", "page": it["page"], "bbox_px": it["bbox_px"], "label": str(new)})
    docs = list(doc_ids) or list(dict.fromkeys(c["doc_id"] for c in cites))
    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": docs,
        "answer": {"text_md": text, "value": None, "unit": None, "confidence": conf, "abstained": False},
        "citations": cites, "evidence": {"boxes": boxes, "scene": {"doc_id": docs[0] if docs else "", "highlight_item_ids": [], "camera_target_item_id": None}},
        "trace": trace, "route": "hybrid",
        "cost": {"usd_total": round(sum(c.get("cost_usd", 0) for c in calls), 6), "calls": calls},
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }
