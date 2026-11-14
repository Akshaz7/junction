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


def answer(question: str, doc_ids: list[str], on_event: Callable | None = None, *, scene_state: dict | None = None) -> dict:
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
                return res
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
            return last
        return _abstained(question, doc_ids, NOT_YET, trace, t0, "index", calls)
    except Exception as e:  # the server must always get an answer object back
        add(_step("error", f"{type(e).__name__}: {e}"[:200]))
        return _abstained(question, doc_ids, "Something went wrong while reading the document, so I cannot answer that right now.",
                          trace, t0, "index", calls)
