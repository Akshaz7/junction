"""Planner loop for the drawing reader. The planner picks tools, sees compact observations and must finish with an answer whose
claims cite evidence ids (eN, or eN#cK for a table cell) that tool results registered. Unknown ids are stripped; with no valid
evidence the answer abstains and says what was found."""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from engine.models import providers as P
from engine.reader.tools import Session

MAX_STEPS = int(__import__("os").environ.get("READER_STEPS", "6"))
COST_CAP = float(__import__("os").environ.get("READER_COST_CAP", "0.05"))
TIME_CAP = float(__import__("os").environ.get("READER_TIME_CAP", "25"))

SYSTEM = """You answer questions about construction drawings (PDF sheets, scans, plan maps, IFC models) by calling tools, then citing what they returned.
Reply with ONE JSON object per turn, nothing else.
Cite the specific elements you name (each room, door, fixture, label or table cell) so each gets its own box; never cite a whole floor plan or whole sheet when you describe its parts.
Call a tool: {"action":"tool","tool":"<name>","args":{...},"why":"<few words>"}
Finish: {"action":"final","answer":"<markdown, English, first line: the direct answer in **bold**, one short sentence; then up to 4 short bullet points (one fact each, '- ' prefix); no paragraph longer than 2 sentences>","value":<number or null>,"unit":"<unit or null>","evidence":["e3","e5#c1"],"confidence":0.0-1.0}
Use document titles and plain element names in the answer, never tool aliases (d1, e3), IFC class names or internal item ids.
Give up honestly: {"action":"final","answer":"<what you found and what is missing>","value":null,"unit":null,"evidence":[...],"confidence":0.0}
Tools (doc is d1, d2...; page numbers start at 1; pixel boxes are page-image pixels):
- find_text {query, doc?, page?}: fuzzy search of the text layer; hits give an id (eN) and the table row/col if inside a table.
- page_text {doc, page, bbox?}: text lines of a page or region (read notes, titles, legends).
- tables {doc, page}: list ruled tables (schedules, legends, notes) with ids like d1.tbl1.3.
- table {id, find?, rows?}: rows of a table. Each row is an evidence id; columns are numbered, cite one cell as eN#cK.
- view {doc, page, bbox? | ref?, ask}: a vision model reads a crop (max 2 per question). Use when text is not enough (symbols, raster scans).
- scale {doc, page}: printed scale and metres per pixel.
- measure {doc, page, points:[[x,y]..], closed?, ratio?}: real length/area of a polyline in pixels.
- planmap {doc, kind?, name?, page?}: items detected in the drawing (walls, doors, rooms...) with measured quantities and totals.
- ifc {doc, kind?, ifc_class?, storey?, name?, external?}: elements of an IFC model with totals.
- compute {expr}: exact arithmetic. Use it for every sum, area or allowance instead of mental maths.
Rules: every fact and number in the answer must come from an observation; cite the ids that show it. Never invent codes, ratings or sources.
If the drawings do not contain the answer (for example a rule that lives in a building code), say so and stop. Never add typical values, code requirements, or unrelated guidance to a missing-data answer.
Be quick: prefer one precise call over many. Stop as soon as the evidence is enough."""


_FINAL = re.compile(r'"action"\s*:\s*"final"')
_ANSWER = re.compile(r'"answer"\s*:\s*"')
_ESC = {"n": "\n", "t": "\t", "r": "", "b": "", "f": "", '"': '"', "\\": "\\", "/": "/"}


def final_answer_text(buf: str) -> str | None:
    """Answer text typed so far in a streaming reader JSON reply, or None while it is a tool step / not yet at the answer.
    Only a reply that says action=final is exposed, so planner steps never leak into the chat."""
    if not _FINAL.search(buf):
        return None
    m = _ANSWER.search(buf)
    if not m:
        return None
    out, i, n = [], m.end(), len(buf)
    while i < n:
        c = buf[i]
        if c == '"':
            break
        if c == "\\":
            if i + 1 >= n:
                break
            e = buf[i + 1]
            if e == "u":
                if i + 6 > n:
                    break
                try:
                    out.append(chr(int(buf[i + 2:i + 6], 16)))
                except ValueError:
                    pass
                i += 6
                continue
            out.append(_ESC.get(e, e))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _reader_sink():
    """DELTA_SINK wrapper for reader_plan calls: forwards only the final answer's text (cumulative)."""
    from engine.models import providers as P
    sink = P.DELTA_SINK.get()
    if sink is None:
        return None
    last = [""]

    def push(buf: str):
        txt = final_answer_text(buf)
        if txt and txt != last[0]:
            last[0] = txt
            sink(txt)
    return push


def _extract_json(text: str) -> dict | None:
    """First JSON object in the reply (models sometimes emit several, or wrap in a code fence)."""
    text = re.sub(r"```(?:json)?", "", text or "")
    dec = json.JSONDecoder()
    i = text.find("{")
    while i != -1:
        try:
            v, _ = dec.raw_decode(text[i:])
            if isinstance(v, dict):
                return v
        except ValueError:
            pass
        i = text.find("{", i + 1)
    return None


def _ids_in(question: str) -> list[str]:
    """Identifiers worth an exact text search: tokens with digits (121.A, A-801, 104, note 4 -> '4' skipped)."""
    out = []
    for m in re.findall(r"[A-Za-z]{0,3}[-.]?\d+(?:[.\-][A-Za-z0-9]+)*", question):
        if len(m) >= 3 and m not in out:
            out.append(m)
    return out[:3]


def _thumb(doc_id: str, root: Path):
    from engine.reader.text import image_path
    p = image_path(doc_id, 1, root)
    if not p.exists():
        return None
    from PIL import Image
    import tempfile
    im = Image.open(p).convert("RGB")
    s = min(1.0, 900 / max(im.size))
    im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))))
    out = Path(tempfile.mkdtemp(prefix="rthumb-")) / "t.png"
    im.save(out)
    return out


def _numbers(s: str) -> set[float]:
    out = set()
    for m in re.findall(r"-?\d[\d,]*\.?\d*", s or ""):
        try:
            out.add(round(float(m.replace(",", "")), 2))
        except ValueError:
            pass
    return out


def _resolve_refs(sess: Session, refs) -> tuple[list[str], list[str]]:
    ok, bad = [], []
    for r in refs or []:
        r = str(r).strip()
        base, _, cell = r.partition("#c")
        e = sess.ev.get(base)
        if e is None or (cell and (not cell.isdigit() or int(cell) not in e.cells)):
            bad.append(r)
        elif r not in ok:
            ok.append(r)
    return ok, bad


def _build(question, doc_ids, sess: Session, fin: dict, trace, calls, t0, forced_abstain: str | None = None) -> dict:
    text = str(fin.get("answer") or "").strip()
    refs, bad = _resolve_refs(sess, fin.get("evidence"))
    refs = refs[:8]
    value, unit = fin.get("value"), fin.get("unit")
    try:
        conf = max(0.0, min(1.0, float(fin.get("confidence") or 0.0)))
    except (TypeError, ValueError):
        conf = 0.0
    notes = []
    if bad:
        notes.append(f"{len(bad)} cited id(s) did not exist and were dropped")
    from engine.reader.numeric import recover_value
    value, unit, numeric_notes, invalid_count = recover_value(question, text, value, unit, sess, refs)
    notes.extend(numeric_notes)
    if invalid_count:
        forced_abstain = forced_abstain or "no verified whole-number count"
        text = "I could not verify a whole-number count for the requested items from the tool results."
    # numeric grounding: a returned value must appear in some observation (or be a compute result)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seen = set().union(*[_numbers(t) for t in sess.transcript]) if sess.transcript else set()
        if not any(abs(round(float(value), 2) - n) <= max(0.011, abs(n) * 0.005) for n in seen):
            notes.append("value not found in any tool result")
            value, conf = None, min(conf, 0.3)
    from engine.numeric import count_question, headline_numbers
    from engine.router.parser import parse
    if value is None and headline_numbers(text) and (count_question(question) or parse(question).type in ("area", "length", "volume")):
        forced_abstain = forced_abstain or "numeric headline has no verified computation"
        text = "I could not verify a numeric answer for this question from the cited tool results."
    abstained = bool(forced_abstain) or not refs or str(fin.get("action")) == "abstain" or conf <= 0.0
    cites, boxes, ids, n = [], [], [], 0
    seen_ids = set()
    main = sess.ev[refs[0].partition("#c")[0]].doc_id if refs else (doc_ids[0] if doc_ids else "")
    for r in refs:
        base, _, cell = r.partition("#c")
        e = sess.ev[base]
        bb = e.cells.get(int(cell)) if cell else e.bbox_px
        bb = [float(v) for v in bb] if bb else None
        n += 1
        kind = "text" if e.kind in ("text", "row") else ("element" if e.kind == "element" else "region")
        if e.kind == "region" and not e.item_ids:
            kind = "region"
        cites.append({"n": n, "doc_id": e.doc_id, "page": e.page, "kind": kind, "bbox_px": bb, "item_ids": list(e.item_ids),
                      "quote": e.quote})
        if bb:
            boxes.append({"item_id": e.item_ids[0] if e.item_ids else f"{base}", "page": e.page, "bbox_px": bb, "label": str(n)})
        for i in e.item_ids:
            if e.doc_id == main and i not in seen_ids:
                ids.append(i)
                seen_ids.add(i)
    if abstained:
        why = forced_abstain or "no verifiable evidence" if not refs else (forced_abstain or "the drawings do not settle it")
        text = "**I could not verify the requested information from the selected drawings.**"
        trace.append({"step": "abstain", "detail": why, "ms": 0, "model": None, "cost_usd": 0})
        value, conf, cites, boxes, ids = None, 0.0, [], [], []
        if refs:
            pass
    else:
        marks = "".join(f"[{c['n']}]" for c in cites)
        if marks and not re.search(r"\[\d+\]", text):
            text = f"{text} {marks}"
        if notes:
            trace.append({"step": "check", "detail": "; ".join(notes), "ms": 0, "model": None, "cost_usd": 0})
    main = (cites[0]["doc_id"] if cites else (doc_ids[0] if doc_ids else ""))
    res = {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": list(doc_ids),
        "answer": {"text_md": text, "value": value if not abstained else None, "unit": unit if not abstained else None,
                   "confidence": round(conf if not abstained else 0.0, 2), "abstained": abstained},
        "citations": cites,
        "evidence": {"boxes": boxes, "scene": {"doc_id": main, "highlight_item_ids": ids, "camera_target_item_id": ids[0] if ids else None}},
        "trace": trace, "route": "hybrid",
        "_reader_evidence": {"doc_ids": list(doc_ids), "tool_calls": list(sess.audit),
                             "calculations": list(sess.calculations),
                             "evidence": {key: asdict(value) for key, value in sess.ev.items()},
                             "selected_refs": refs, "model_confidence": conf,
                             "note": "Planner confidence is self-reported; it is not measured answer accuracy."},
        "cost": {"usd_total": round(sum(c.get("cost_usd", 0) for c in calls), 6), "calls": calls},
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }
    from engine.reader.calc_trace import seed
    return seed(res, res['_reader_evidence'])


def _plain_step(tool, args, obs) -> str:
    """A thinking-row label a person can read: never the raw tool arguments as JSON."""
    first = obs.splitlines()[0][:100] if obs else ""
    if isinstance(args, dict) and args:
        what = " ".join(str(args[k]) for k in ("kind", "name", "label", "id", "text", "query") if args.get(k))
        if what:
            return f"Looked up {what} on the plan" + (f" ({first})" if first else "")
    return f"{tool}" + (f": {first}" if first else "")


def read_answer(question: str, doc_ids: list[str], root, on_event=None, trace: list | None = None, calls: list | None = None,
                t0: float | None = None, max_steps: int | None = None) -> dict:
    from engine import models as M
    emit = on_event or (lambda k, p: None)
    t0 = t0 or time.perf_counter()
    trace = trace if trace is not None else []
    calls = calls if calls is not None else []
    emit("status", {"text": "Reading the selected drawings…"})
    root = Path(root)
    steps = max_steps or MAX_STEPS

    def add(step):
        trace.append(step)
        emit("trace", step)

    sess = Session(doc_ids, root, emit=emit, on_cost=lambda c: calls.append(c))

    def observe(tool, args):
        obs = sess.run(tool, args)
        from engine.library import reader_partial
        emit("answer.partial", reader_partial(question, doc_ids, sess, trace, calls, t0))
        return obs

    def spent():
        return sum(c.get("cost_usd", 0) for c in calls)

    # prefetch: exact identifiers in the question, and the table list of a single-page sheet
    pre = []
    ts = time.perf_counter()
    for ident in _ids_in(question):
        obs = observe("find_text", {"query": ident})
        if not obs.startswith("no match"):
            pre.append(f"[prefetch find_text {ident}]\n{obs}")
    if len(doc_ids) == 1 and sess.docs["d1"]["pages"] == 1 and not sess.docs["d1"]["ifc"]:
        obs = observe("tables", {"doc": "d1", "page": 1})
        if not obs.startswith("no ruled"):
            pre.append(f"[prefetch tables d1 p1]\n{obs}")
    if pre:
        add({"step": "read", "detail": "prefetched exact matches and tables", "ms": int((time.perf_counter() - ts) * 1000), "model": None, "cost_usd": 0})

    first = f"Documents:\n{sess.overview()}\n\nQuestion: {question}\n" + ("\n" + "\n\n".join(pre) if pre else "")
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": first}]
    thumb = _thumb(doc_ids[0], root) if doc_ids else None
    last_obs = ""
    for step in range(steps):
        if spent() >= COST_CAP or time.perf_counter() - t0 > TIME_CAP:
            add({"step": "read", "detail": "budget reached, finishing with what was found", "ms": 0, "model": None, "cost_usd": 0})
            msgs.append({"role": "user", "content": "Budget reached. Reply now with the final JSON using only what you have."})
        ts = time.perf_counter()
        try:
            _tok = P.DELTA_SINK.set(_reader_sink())
            try:
                r = M.call("reader_plan", msgs, images=[thumb] if (thumb and step == 0) else None)
            finally:
                P.DELTA_SINK.reset(_tok)
        except Exception as e:  # noqa: BLE001
            add({"step": "error", "detail": f"planner unavailable ({type(e).__name__})", "ms": 0, "model": None, "cost_usd": 0})
            return _build(question, doc_ids, sess, {"answer": last_obs[:300], "evidence": []}, trace, calls, t0, "planner unavailable")
        calls.append({"task": "reader_plan", "provider": r.provider, "model": r.model, "cost_usd": r.cost_usd})
        act = r.json if isinstance(r.json, dict) else _extract_json(r.text)
        ms = int((time.perf_counter() - ts) * 1000)
        if not act:
            msgs += [{"role": "assistant", "content": (r.text or "")[:400]}, {"role": "user", "content": "Reply with one JSON object only."}]
            add({"step": "read", "detail": "planner reply was not JSON; retrying", "ms": ms, "model": r.model, "cost_usd": r.cost_usd})
            continue
        if act.get("action") == "final" or act.get("action") == "abstain":
            if act.get("action") == "final" and not _resolve_refs(sess, act.get("evidence"))[0] and step < steps - 1 and spent() < COST_CAP and sess.ev:
                msgs += [{"role": "assistant", "content": json.dumps(act)[:800]},
                         {"role": "user", "content": "Your evidence ids are missing or unknown. Cite ids from the observations (e.g. e5 or e5#c1)."}]
                continue
            add({"step": "answer", "detail": f"{len(sess.ev)} evidence item(s) gathered, {step + 1} planner step(s)", "ms": ms, "model": r.model, "cost_usd": r.cost_usd})
            return _build(question, doc_ids, sess, act, trace, calls, t0)
        tool, args = act.get("tool"), act.get("args") or {}
        obs = observe(str(tool), args if isinstance(args, dict) else {})
        last_obs = obs
        add({"step": "read", "detail": _plain_step(tool, args, obs), "ms": ms, "model": r.model, "cost_usd": r.cost_usd})
        msgs += [{"role": "assistant", "content": json.dumps(act)[:600]}, {"role": "user", "content": f"Observation:\n{obs}"}]
    # steps exhausted: force a final answer
    msgs.append({"role": "user", "content": "Out of steps. Reply now with the final JSON using only what you have."})
    try:
        _tok = P.DELTA_SINK.set(_reader_sink())
        try:
            r = M.call("reader_plan", msgs)
        finally:
            P.DELTA_SINK.reset(_tok)
        calls.append({"task": "reader_plan", "provider": r.provider, "model": r.model, "cost_usd": r.cost_usd})
        act = r.json if isinstance(r.json, dict) else _extract_json(r.text) or {}
    except Exception:  # noqa: BLE001
        act = {}
    if act.get("action") == "final":
        return _build(question, doc_ids, sess, act, trace, calls, t0)
    return _build(question, doc_ids, sess, {"answer": last_obs[:300], "evidence": []}, trace, calls, t0, "step limit")
