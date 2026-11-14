"""E-04: engine.answer(question, doc_ids, on_event) -> answer object (CONTRACT 5.7).

Same signature as server/stub_engine.answer. on_event(kind, payload) gets kind in
{"status", "trace"}. Numeric questions (count/area/length/volume) are solved by code
from the plan map or elements.json (engine.solvers): cost 0, no model. When the rules
cannot parse a question the router fallback (Nemotron via call("route")) runs. Text
questions and missing data abstain with a plain sentence. Never raises.

Keep this import path light: no torch, no ifcopenshell (production image has API deps only).
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Callable

from engine.router.parser import Parsed, parse
from engine.scene_cmds import parse_scene, scene_answer
from engine.solvers import ARTIFACTS, SolverUnsupported, solve

MIN_CONF = 0.25
NO_DOC = "Select a document first, then ask again."
NOT_YET = ("I can answer counts, areas, lengths and volumes from the drawing data. "
           "This question needs written reasoning over the documents, which I cannot verify yet.")


ASK = "Ask a question about the selected drawing."
DOC_ID = re.compile(r"\b[a-z0-9]+(?:_[a-z0-9]+)*__[A-Za-z0-9][\w.\-]*[A-Za-z0-9_]", re.I)


def _other_doc(question: str, doc_ids: list[str]) -> str | None:
    """A document id named in the question that is not among the selected docs."""
    sel = {d.lower() for d in doc_ids}
    for m in DOC_ID.findall(question):
        if m.lower() not in sel:
            return m
    return None


def _root() -> Path:
    return Path(os.environ.get("ARTIFACTS_DIR") or ARTIFACTS)


def _title(doc_id: str, root: Path) -> str:
    try:
        return json.loads((root / doc_id / "doc.json").read_text()).get("title") or doc_id
    except (OSError, ValueError):
        return doc_id


def _step(step, detail, ms=0, model=None, cost=0.0):
    return {"step": step, "detail": detail, "ms": ms, "model": model, "cost_usd": cost}


def _abstained(question, doc_ids, text, trace, t0, route="index", calls=None):
    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": list(doc_ids),
        "answer": {"text_md": text, "value": None, "unit": None, "confidence": 0.0, "abstained": True},
        "citations": [], "evidence": {"boxes": [], "scene": {"doc_id": doc_ids[0] if doc_ids else "", "highlight_item_ids": [],
                                                              "camera_target_item_id": None}},
        "trace": trace, "route": route,
        "cost": {"usd_total": round(sum(c.get("cost_usd", 0) for c in (calls or [])), 6), "calls": calls or []},
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }


def _reader(question, doc_ids, root, trace, calls, t0, emit):
    """Tool-using reader (engine/reader). None when disabled or it fails; the caller keeps its own abstain."""
    if os.environ.get("READER", "1") == "0":
        return None
    try:
        from engine.reader import read_answer
        emit("status", {"text": "Reading the drawing closely…"})
        return read_answer(question, doc_ids, root, on_event=emit, trace=trace, calls=calls, t0=t0)
    except Exception as e:  # noqa: BLE001
        trace.append(_step("error", f"reader failed ({type(e).__name__}: {str(e)[:80]})"))
        return None


def _use_reader(res, question, doc_ids, root, trace, calls, t0, emit):
    """Run the reader when `res` is an abstention; return the reader's answer if it found one, else `res`."""
    if res is not None and not res["answer"].get("abstained"):
        return res
    rr = _reader(question, doc_ids, root, trace, calls, t0, emit)
    if rr is not None and not rr["answer"].get("abstained"):
        rr["trace"] = trace
        return rr
    return res if res is not None else rr


def _top_docs(question, root, n=3):
    try:
        from engine.project_index import load_index
        ix = load_index(root)
        hits = ix.search(question, n) if ix else []
        return [h["doc_id"] for h in hits if h.get("coverage", 0) >= 0.4][:n]
    except Exception:  # noqa: BLE001
        return []


def _chat_answer(question, history, trace, t0, add, emit):
    """No document selected: talk normally with Hologram's system prompt (engine/assistant.py)."""
    from engine.assistant import chat
    emit("status", {"text": "Writing an answer…"})
    try:
        r = chat(question, history)
    except Exception as e:  # noqa: BLE001 — every provider failed: fall back to the plain hint
        add(_step("chat", f"no model reachable ({type(e).__name__})"))
        return _abstained(question, [], NO_DOC, trace, t0)
    call_meta = {"task": "chat", "provider": r.provider, "model": r.model, "cost_usd": r.cost_usd}
    add(_step("chat", "general conversation, no document selected", r.latency_ms, r.model, r.cost_usd))
    out = _abstained(question, [], (r.text or "").strip() or NO_DOC, trace, t0, calls=[call_meta])
    out["answer"].update({"abstained": False, "confidence": 0.5})
    return out


def _recount_ladder(res, question, did, parsed, root, calls, hidden):
    """Raster plan counts of doors, windows, sinks, WCs, showers/baths are weak: recount with one cheap vision call and reconcile
    (rules picked on calibration drawings, engine/recount.py). Plan maps from vector sources (DXF) are exact and skipped."""
    from engine.recount import KIND_OF, recount, reconcile
    ans = res["answer"]
    if (os.environ.get("RECOUNT", "1") == "0" or os.environ.get("MODELS_FAKE") or hidden or parsed.type != "count" or parsed.kind not in KIND_OF
            or ans.get("abstained") or not isinstance(ans.get("value"), (int, float))):
        return res
    try:
        from engine.solvers.data import load_doc
        doc = load_doc(did, root)
        if doc is None or doc.mode != "planmap" or not any(i.source == "det" for i in doc.items):
            return res
        img = Path(root) / did / "page-1.png"
        if not img.exists():
            return res
        n, usd, model = recount(question, img, KIND_OF[parsed.kind])
    except Exception:  # noqa: BLE001
        return res
    if n is None:
        return res
    calls.append({"task": "recount", "provider": "vision", "model": model, "cost_usd": usd})
    plan_n = int(ans["value"])
    final = reconcile(parsed.kind, plan_n, n)
    res["trace"].append(_step("recount", f"plan map {plan_n}, drawing re-read {n} -> {final}", 0, model, usd))
    if final != plan_n:
        noun = re.sub(r"^.*?\*\*\d+ ([^*]+)\*\*.*$", r"\1", ans["text_md"], flags=re.S) if re.search(r"\*\*\d+ ", ans["text_md"]) else parsed.kind + "s"
        ans["value"] = final
        ans["text_md"] = f"There {'is' if final == 1 else 'are'} **{final} {noun if final != 1 else noun.rstrip('s')}** on this floor plan (re-counted from the drawing image; low-resolution detection disagreed)."
        ans["confidence"] = round(min(ans.get("confidence", 0.5), 0.5), 3)
    return res


def answer(question: str, doc_ids: list[str], on_event: Callable | None = None, *, scene_state: dict | None = None,
           history: list[dict] | None = None) -> dict:
    """Code -> vision recount -> reader -> forced best-effort answer. Never abstains on a selected document (FORCE_ANSWER=0 restores abstaining)."""
    res = _answer_core(question, doc_ids, on_event, scene_state=scene_state, history=history)
    if (os.environ.get("FORCE_ANSWER", "1") == "0" or not doc_ids or not (question or "").strip() or not res["answer"].get("abstained")
            or parse_scene(question) is not None or _other_doc(question, doc_ids)):
        return res
    _t = res["answer"].get("text_md", "")
    if ("does not record" in _t or _t.lstrip("*").startswith(("No beam", "No pipe or MEP"))) and parse(question).type not in ("count", "area", "length", "volume"):
        res["answer"].update({"abstained": False, "confidence": 0.5})   # a checked statement that the model lacks this data is an answer
        return res
    try:
        from engine.forced import forced_answer
        (on_event or (lambda k, p: None))("status", {"text": "Estimating from the drawing…"})
        trace = list(res.get("trace") or [])
        calls = list((res.get("cost") or {}).get("calls") or [])
        f = forced_answer(question, doc_ids, _root(), parse(question), trace, calls)
        f["latency_ms"] = res.get("latency_ms", 0) + f["latency_ms"]
        return f
    except Exception:  # noqa: BLE001
        return res


def _answer_core(question: str, doc_ids: list[str], on_event: Callable | None = None, *, scene_state: dict | None = None,
                 history: list[dict] | None = None) -> dict:
    emit = on_event or (lambda kind, payload: None)
    t0 = time.perf_counter()
    root = _root()
    trace: list[dict] = []
    calls: list[dict] = []

    def add(step):
        trace.append(step)
        emit("trace", step)

    emit("status", {"text": "Thinking…"})
    try:
        if not doc_ids:
            if (question or "").strip():
                from engine.project_answer import project_answer
                res = project_answer(question, history, on_event, trace, t0, root, calls)
                if res is not None:
                    if res["answer"].get("abstained") and res.get("route") == "index" and os.environ.get("READER", "1") != "0":
                        top = _top_docs(question, root)
                        if top:
                            rr = _reader(question, top, root, trace, calls, t0, emit)
                            if rr is not None and not rr["answer"].get("abstained"):
                                return rr
                    return res
                return _chat_answer(question, history, trace, t0, add, emit)
            add(_step("abstain", "no document selected"))
            return _abstained(question, doc_ids, NO_DOC, trace, t0)

        if not (question or "").strip():
            add(_step("abstain", "empty question"))
            return _abstained(question, doc_ids, ASK, trace, t0)
        other = _other_doc(question, doc_ids)
        if other:
            add(_step("abstain", f"question names {other}, which is not selected"))
            sel = ", ".join(_title(d, root) for d in doc_ids)
            return _abstained(question, doc_ids, f"The question names **{other}**, which is not among the selected documents ({sel}). "
                              "Select that document and ask again, or ask about the selected one.", trace, t0)

        # 0. scene commands (hide / isolate / highlight / reset): code only, edits never touch data
        intent = parse_scene(question)
        scene_cost, scene_prov = 0.0, None
        if intent is None and not os.environ.get("MODELS_FAKE"):
            from engine.scene_cmds import parse_scene_model
            intent, scene_cost, scene_prov = parse_scene_model(question)
            if scene_prov:
                calls.append({"task": "scene_intent", "provider": scene_prov, "cost_usd": scene_cost})
        if intent is not None:
            from engine.solvers.data import load_doc
            doc = load_doc(doc_ids[0], root)
            if doc is not None:
                emit("status", {"text": f"Exploring document: {_title(doc_ids[0], root)}"})
                res = scene_answer(question, doc, intent, scene_state, t0)
                for s_ in res["trace"]:
                    add(s_)
                res["trace"] = trace
                if scene_prov:
                    res["cost"] = {"usd_total": round(scene_cost, 6), "calls": list(calls)}
                return res

        # 0b. exit finder (IFC): code only
        from engine.exits import exit_answer, is_exit_question
        if is_exit_question(question):
            from engine.solvers.data import load_doc as _load
            xdoc = _load(doc_ids[0], root)
            if xdoc is not None and xdoc.mode == "ifc":
                emit("status", {"text": f"Exploring document: {_title(doc_ids[0], root)}"})
                res = exit_answer(question, xdoc, t0)
                for s_ in res["trace"]:
                    add(s_)
                res["trace"] = trace
                return res

        # 1. route: rules, then the model fallback only when the rules are unsure
        ts = time.perf_counter()
        parsed: Parsed = parse(question)
        if parsed.matched:
            add(_step("route", f"{parsed.type} / {parsed.kind} / {parsed.scope or 'unscoped'} (rules)",
                      int((time.perf_counter() - ts) * 1000)))
        else:
            try:
                from engine.router.route import route  # lazy: pulls in the model layer
                r = route(question)
                parsed = r.parsed
                if r.source == "model":
                    calls.append({"task": "route", "provider": r.provider, "cost_usd": r.cost_usd})
                add(_step("route", f"{parsed.type} / {parsed.kind} / {parsed.scope or 'unscoped'} ({r.source})",
                          int((time.perf_counter() - ts) * 1000), model=r.provider or None, cost=r.cost_usd))
            except Exception as e:  # budget, network, anything: carry on with the rules' guess
                add(_step("route", f"model fallback unavailable ({type(e).__name__}); using rules' best guess"))

        if parsed.type not in ("count", "area", "length", "volume"):
            from engine.solvers.data import load_doc
            from engine.textqa import text_answer
            tdoc = load_doc(doc_ids[0], root)
            if tdoc is not None and tdoc.mode == "ifc":
                emit("status", {"text": f"Exploring document: {_title(doc_ids[0], root)}"})
                res = text_answer(question, tdoc)
                for s_ in res["trace"]:
                    add(s_)
                res["trace"] = trace
                res["cost"]["usd_total"] = round(res["cost"]["usd_total"] + sum(c["cost_usd"] for c in calls), 6)
                res["cost"]["calls"] = calls + res["cost"]["calls"]
                res["latency_ms"] = int((time.perf_counter() - t0) * 1000)
                return _use_reader(res, question, doc_ids, root, trace, calls, t0, emit)
            # sheets without a plan map: the reader (text layer, tables, scale, crops)
            if tdoc is None or tdoc.mode != "planmap":
                rr = _reader(question, doc_ids, root, trace, calls, t0, emit)
                if rr is not None and not rr["answer"].get("abstained"):
                    return rr
            if tdoc is not None and tdoc.mode == "planmap" and os.environ.get("READ_DRAWING", "1") != "0":
                from engine.readdraw import read_drawing
                emit("status", {"text": f"Exploring document: {_title(doc_ids[0], root)}"})
                res = read_drawing(question, tdoc, root)
                for s_ in res["trace"]:
                    add(s_)
                res["trace"] = trace
                res["cost"]["usd_total"] = round(res["cost"]["usd_total"] + sum(c["cost_usd"] for c in calls), 6)
                res["cost"]["calls"] = calls + res["cost"]["calls"]
                res["latency_ms"] = int((time.perf_counter() - t0) * 1000)
                if res["answer"].get("abstained") or res["answer"].get("confidence", 1) < 0.5:   # one-shot read unsure: use the tools
                    rr = _reader(question, doc_ids, root, trace, calls, t0, emit)
                    if rr is not None and not rr["answer"].get("abstained"):
                        return rr
                return res
            add(_step("abstain", f"type {parsed.type} is not answered by code"))
            return _abstained(question, doc_ids, NOT_YET, trace, t0, "index", calls)

        # 2. solve over the documents, first one that holds an answer wins
        last = None
        for did in doc_ids:
            emit("status", {"text": f"Exploring document: {_title(did, root)}"})
            try:
                hid = None
                if scene_state and scene_state.get("hidden"):
                    from engine.scene_cmds import tags as _tags
                    from engine.solvers.data import load_doc as _ld
                    d_ = _ld(did, root)
                    if d_ is not None:
                        tg_ = _tags(d_)
                        hid = {i: tg_.get(i, i) for i in scene_state["hidden"]}
                res = solve(question, did, parsed=parsed, root=root, hidden=hid)
            except SolverUnsupported:
                continue
            res = _recount_ladder(res, question, did, parsed, root, calls, hid)
            for s in res["trace"]:
                if s["step"] != "route":
                    add(s)
            last = res
            ans = res["answer"]
            if not ans["abstained"] and ans["confidence"] < MIN_CONF:
                add(_step("abstain", f"confidence {ans['confidence']} below {MIN_CONF}"))
                return _abstained(question, doc_ids, "I am not confident enough in the drawing data for this to give a figure.",
                                  trace, t0, res["route"], calls)
            if not ans["abstained"]:
                res["trace"] = trace
                res["doc_ids"] = list(doc_ids)
                res["question"] = question
                res["cost"] = {"usd_total": round(sum(c["cost_usd"] for c in calls), 6), "calls": calls}
                res["latency_ms"] = int((time.perf_counter() - t0) * 1000)
                return res
        if last is not None:
            last["trace"] = trace
            last["doc_ids"] = list(doc_ids)
            last["question"] = question
            last["cost"] = {"usd_total": round(sum(c["cost_usd"] for c in calls), 6), "calls": calls}
            last["latency_ms"] = int((time.perf_counter() - t0) * 1000)
            return _use_reader(last, question, doc_ids, root, trace, calls, t0, emit)
        return _use_reader(_abstained(question, doc_ids, NOT_YET, trace, t0, "index", calls), question, doc_ids, root, trace, calls, t0, emit)
    except Exception as e:  # the server must always get an answer object back
        add(_step("error", f"{type(e).__name__}: {e}"[:200]))
        return _abstained(question, doc_ids, "Something went wrong while reading the document, so I cannot answer that right now.",
                          trace, t0, "index", calls)
