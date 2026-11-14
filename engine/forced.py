"""Last rung of the ladder: a best-effort answer when code, vision recount and the reader all abstained (Ash: zero abstentions).

forced_answer(question, doc_ids, root, parsed) -> answer object. One cheap call("forced_answer") with the page image
(when there is one) plus whatever text the document has (text layer words, IFC facts). Confidence is low and the text says what it rests on.
Without a usable model result, the numeric value stays unknown. Fake-provider
responses are test fixtures, never source measurements.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

NUM_SCHEMA = {"type": "object", "required": ["value"], "additionalProperties": False, "properties": {"value": {"type": "number"}}}
TXT_SCHEMA = {"type": "object", "required": ["answer"], "additionalProperties": False, "properties": {"answer": {"type": "string"}}}
NO_IMAGE = re.compile(r"(does not|doesn't|did not|no)\s+(contain|include|provide|have|attach|image|see)[^.]{0,40}\b(image|drawing|picture|photo|attachment)\b|"
                      r"\bno (image|drawing) (was |is |has been )?(provided|attached|included)", re.I)
UNITS = {"area": "m²", "length": "m", "volume": "m³", "count": "count"}


def _context(doc_id: str, root: Path, question: str) -> tuple[str, Path | None, str]:
    """-> (text context, page image, basis phrase)"""
    d = Path(root) / doc_id
    img = next((p for p in (d / "page-1.png", d / "page-1.jpg", d / "page-1.thumb.png", *sorted(d.glob("page-*.png"))) if p.exists()), None)
    bits, basis = [], []
    try:
        meta = json.loads((d / "doc.json").read_text())
        bits.append(f"Document title: {meta.get('title') or doc_id}")
    except (OSError, ValueError):
        pass
    try:
        from engine.solvers.data import load_doc, load_sheet_parent
        doc = load_doc(doc_id, root) or load_sheet_parent(doc_id, root, whole=True)
        if doc is not None and doc.mode == "ifc":
            from engine.textqa import facts_for
            f = facts_for(question, doc)
            lines = list(f.lines)[:60]
            if lines:
                bits.append("Facts computed from the model:\n" + "\n".join(lines))
                basis.append("the model's data")
            else:
                from collections import Counter
                c = Counter(i.kind for i in doc.items)
                bits.append("Element counts in the model: " + ", ".join(f"{k} {v}" for k, v in c.most_common(15)))
                basis.append("the model's element counts")
        elif doc is not None:
            from collections import Counter
            c = Counter(i.kind for i in doc.items)
            labels = [i.label for i in doc.items if i.label][:60]
            bits.append("Detected on the plan: " + ", ".join(f"{k} {v}" for k, v in c.items()) + ("; labels: " + ", ".join(labels) if labels else ""))
            basis.append("the objects found on the drawing")
    except Exception:  # noqa: BLE001
        pass
    try:
        t = json.loads((d / "text-1.json").read_text())
        words = " ".join(w["text"] for w in t.get("words", [])[:600])
        if words:
            bits.append("Text printed on the sheet: " + words[:3500])
            basis.append("the printed text")
    except (OSError, ValueError):
        pass
    if img is not None:
        basis.append("the drawing image")
    return "\n\n".join(bits), img, " and ".join(basis)


def forced_answer(question: str, doc_ids: list[str], root: Path, parsed=None, trace: list | None = None, calls: list | None = None) -> dict:
    from engine.models import call
    t0 = time.perf_counter()
    trace = trace if trace is not None else []
    calls = calls if calls is not None else []
    did = doc_ids[0]
    ctx, img, basis = _context(did, root, question)
    typ = getattr(parsed, "type", None)
    numeric = typ in UNITS
    value, text, usd = None, "", 0.0
    prompt = ("Answer the question about a building drawing or model as best you can from the evidence below. "
              + ("The drawing image is attached to this message: look at it and answer from what you see. Never say that no image was provided. "
                 if img is not None else "")
              + "You must give an answer: if unsure, give your best estimate. " + ("Reply JSON {\"value\": <number>}. " + ("Whole number." if typ == "count" else f"Unit {UNITS.get(typ)}.")
              if numeric else "Reply JSON {\"answer\": <1-4 sentences, specific, key fact first>}. ")
              + f"\n\n{ctx}\n\nQuestion: {question}")
    n = None
    if typ == "count" and img is not None:   # the calibrated vision recount beats the generic prompt for counts
        from engine.recount import recount
        c, usd, model = recount(question, img, getattr(parsed, "kind", None))
        if c is not None and model not in ("fake-1", "cache:fake-1"):
            calls.append({"task": "recount", "provider": "vision", "model": model, "cost_usd": usd})
            n = float(c)
    try:
        if n is not None:
            raise StopIteration
        r = call("forced_answer", [{"role": "user", "content": prompt}], images=[img] if img else None, schema=NUM_SCHEMA if numeric else TXT_SCHEMA)
        usd = r.cost_usd
        calls.append({"task": "forced_answer", "provider": r.provider, "model": r.model, "cost_usd": r.cost_usd})
        j = r.json if isinstance(r.json, dict) else {}
        if img is not None and not numeric and NO_IMAGE.search(str(j.get("answer") or "")):   # the model claims it got no image: ask once more, plainly
            r = call("forced_answer", [{"role": "user", "content": prompt + "\n\nThe image IS attached. Describe what is on the drawing that answers the question."}],
                     images=[img], schema=TXT_SCHEMA)
            usd += r.cost_usd
            calls.append({"task": "forced_answer", "provider": r.provider, "model": r.model, "cost_usd": r.cost_usd})
            j = r.json if isinstance(r.json, dict) else {}
            if NO_IMAGE.search(str(j.get("answer") or "")):
                j = {}
        if r.provider == "fake":
            j = {}  # A schema-shaped fixture is not a count from the drawing.
        if numeric and isinstance(j.get("value"), (int, float)):
            n = float(j["value"])
        elif not numeric and (j.get("answer") or "").strip():
            text = j["answer"].strip()
    except StopIteration:
        pass
    except Exception as e:  # noqa: BLE001
        trace.append({"step": "forced", "detail": f"model unavailable ({type(e).__name__})", "ms": 0, "model": None, "cost_usd": 0})
    if numeric:
        defaulted = n is None
        n = 0.0 if n is None else max(0.0, n)
        value = int(round(n)) if typ == "count" else round(n, 2)
        shown = f"{value}" if typ == "count" else f"{value} {UNITS[typ]}"
        if defaulted:
            text = ("I couldn't find this on the drawing, so I won't guess a number. "
                    "Try asking about something drawn or labelled on the plan, or upload a model (IFC) or a clearer drawing that includes it.")
            value = None
        elif value == 0:
            text = (f"**I could not find any** on this drawing. That is what a model could read from {basis or 'the drawing'}, so it is not a verified zero: "
                    "the drawing may be sparse or unclear. Upload a clearer plan or an IFC model to be sure. Or try: how many rooms are there, where is the kitchen, area of the living room.")
        else:
            text = f"About **{shown}**. This is an estimate, not an exact count: it was read from {basis or 'the drawing'} by a model."
    else:
        text = (text or "I couldn't find that in this document. Try asking about a specific room, door or window, or upload a model or drawing that covers it.")
        text += f"\n\n_Based on {basis}._" if (basis and text.strip().startswith("I couldn't") is False) else ""
    trace.append({"step": "forced", "detail": f"best-effort answer from {basis or 'no evidence'}", "ms": int((time.perf_counter() - t0) * 1000), "model": calls[-1]["model"] if calls and calls[-1].get("task") == "forced_answer" else None, "cost_usd": usd})
    citations = []
    if img is not None and (value is not None or text and not text.startswith("I couldn't")):
        try:
            from PIL import Image
            with Image.open(img) as image:
                width, height = image.size
            citations = [{"n": 1, "doc_id": did, "page": int(re.search(r"page-(\d+)", img.name)[1]),
                          "kind": "region", "bbox_px": [0, 0, width, height], "item_ids": [], "quote": None}]
            text += " [1]"
        except (OSError, ValueError, TypeError):
            pass
    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": list(doc_ids),
        "answer": {"text_md": text, "value": value, "unit": UNITS.get(typ) if numeric else None, "confidence": 0.2, "abstained": False},
        "citations": citations, "evidence": {"boxes": [], "scene": {"doc_id": did, "highlight_item_ids": [], "camera_target_item_id": None}},
        "trace": trace, "route": "hybrid",
        "cost": {"usd_total": round(sum(c.get("cost_usd", 0) for c in calls), 6), "calls": calls},
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }
