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
    call_meta = {"task": getattr(r, "task", "") or "chat", "provider": r.provider, "model": r.model, "cost_usd": r.cost_usd}
    add(_step("chat", "general conversation, no document selected", r.latency_ms, r.model, r.cost_usd))
    out = _abstained(question, [], (r.text or "").strip() or NO_DOC, trace, t0, calls=[call_meta])
    out["answer"].update({"abstained": False, "confidence": 0.5})
    return out


_PM_KINDS = {"window": ("window",), "door": ("door",), "toilet": ("toilet",), "sink": ("sink",), "shower_bathtub": ("shower", "bathtub")}


def _set_boxes(res, parsed, entries, note):
    """entries: [(item_id, bbox_px)]. Headline, boxes (labelled 1..N), 3D highlight ids and citation item ids all follow N."""
    ans = res["answer"]
    n = len(entries)
    ids = [e[0] for e in entries]
    page = ((res.get("evidence") or {}).get("boxes") or [{"page": 1}])[0].get("page", 1)
    res["evidence"]["boxes"] = [{"item_id": it, "page": page, "bbox_px": [int(v) for v in bb], "label": str(k)} for k, (it, bb) in enumerate(entries, 1)]
    sc = res["evidence"]["scene"]
    sc["highlight_item_ids"] = ids
    sc["camera_target_item_id"] = ids[0] if ids else None
    for c in res.get("citations") or []:
        if "item_ids" in c:
            c["item_ids"] = list(ids)
            if entries:
                c["bbox_px"] = [min(e[1][0] for e in entries), min(e[1][1] for e in entries), max(e[1][2] for e in entries), max(e[1][3] for e in entries)]
    noun = re.sub(r"^.*?\*\*\d+ ([^*]+)\*\*.*$", r"\1", ans["text_md"], flags=re.S) if re.search(r"\*\*\d+ ", ans["text_md"]) else parsed.kind + "s"
    marks = " ".join(dict.fromkeys(re.findall(r"\[\d+\]", ans["text_md"])))
    ans["value"] = n
    ans["text_md"] = f"There {'is' if n == 1 else 'are'} **{n} {noun if n != 1 else noun.rstrip('s')}** on this floor plan." + (f" {marks}" if marks else "")
    ans["confidence"] = round(min(ans.get("confidence", 0.5), 0.5), 3)
    res["trace"].append(_step("recount", note, 0, None, 0))


def _recount_ladder(res, question, did, parsed, root, calls, hidden):
    """Raster plan counts of doors, windows, sinks, WCs, showers/baths are weak. Boxes come from the fine-tuned detector when its
    planmap-det.json exists, else from the plan map plus a vision recount: a lower recount drops the least confident boxes, a higher
    one adds vision-drawn boxes. The headline number always equals the numbered boxes. Vector (DXF) plan maps are exact and skipped."""
    from engine.recount import KIND_OF, detect, merge_boxes, recount, reconcile
    ans = res["answer"]
    if (os.environ.get("RECOUNT", "1") == "0" or os.environ.get("MODELS_FAKE") or hidden or parsed.type != "count" or parsed.kind not in KIND_OF
            or ans.get("abstained") or not isinstance(ans.get("value"), (int, float))):
        return res
    kk = KIND_OF[parsed.kind]
    try:
        from engine.solvers.data import load_doc
        doc = load_doc(did, root)
        if doc is None or doc.mode != "planmap" or not any(i.source == "det" for i in doc.items):
            return res
        det = Path(root) / did / "planmap-det.json"
        if det.exists():   # the fine-tuned RT-DETR detector is the preferred box source
            alld = json.loads(det.read_text()).get("items", [])
            if any(i.get("kind") in ("door", "window", "toilet", "sink", "shower", "bathtub") for i in alld):   # a detector run, not a segmentation-only file
                its = [i for i in alld if i.get("kind") in _PM_KINDS[kk] and (i.get("conf") or 1) >= 0.25]
                _set_boxes(res, parsed, [(i["item_id"], i["bbox_px"]) for i in its], f"fine-tuned detector: {len(its)} {parsed.kind}(s)")
                return res
        img = Path(root) / did / "page-1.png"
        if not img.exists():
            return res
        n, usd, model = recount(question, img, kk)
    except Exception:  # noqa: BLE001
        return res
    if n is None:
        return res
    calls.append({"task": "recount", "provider": "vision", "model": model, "cost_usd": usd})
    plan_n = int(ans["value"])
    final = reconcile(parsed.kind, plan_n, n)
    boxes = (res.get("evidence") or {}).get("boxes") or []
    if len(boxes) != plan_n:
        res["trace"].append(_step("recount", f"plan map {plan_n}, drawing re-read {n}: boxes do not match the count, kept the plan map", 0, model, usd))
        return res
    conf = {i.item_id: (i.conf if i.conf is not None else 1.0) for i in doc.items}
    if final < plan_n:
        ranked = sorted(boxes, key=lambda b: -conf.get(b["item_id"], 1.0))
        keep = sorted(ranked[:final], key=lambda b: boxes.index(b))
        # only override when clearly better: a drop of one needs a clearly weak box to drop (calibration: every right drop-by-one had a
        # box at conf <= 0.56; the wrong ones had all boxes >= 0.8)
        if plan_n - final == 1 and conf.get(ranked[-1]["item_id"], 1.0) >= 0.7:
            res["trace"].append(_step("recount", f"plan map {plan_n}, drawing re-read {n}: every detection is confident, kept the plan map", 0, model, usd))
            return res
        _set_boxes(res, parsed, [(b["item_id"], b["bbox_px"]) for b in keep],
                   f"plan map {plan_n}, drawing re-read {n}: dropped the {plan_n - final} least confident detection(s)")
    elif final > plan_n:
        try:
            new, usd2, m2 = detect(img, kk)
        except Exception:  # noqa: BLE001
            new, usd2, m2 = None, 0.0, ""
        calls.append({"task": "recount_boxes", "provider": "vision", "model": m2, "cost_usd": usd2})
        if new is None:
            res["trace"].append(_step("recount", f"plan map {plan_n}, drawing re-read {n}: no boxes from vision, kept the plan map", 0, model, usd))
            return res
        # calibration: vision's own boxes alone beat plan-map + vision merged (results/box_*.json); the plan-map boxes for this kind are the ones that undercount
        entries = [(f"vision-{kk}-{k:02d}", bb) for k, bb in enumerate(new, 1)]
        if not entries:
            res["trace"].append(_step("recount", f"plan map {plan_n}, drawing re-read {n}: vision drew no boxes, kept the plan map", 0, model, usd))
            return res
        _set_boxes(res, parsed, entries, f"plan map {plan_n}, drawing re-read {n}: replaced by {len(entries)} vision-drawn box(es) ({m2})")
    return res


def ensure_markers(res: dict) -> dict:
    """A cited answer always carries its inline [n] markers: if the text lost them, append them after the last sentence."""
    ans = res.get("answer") or {}
    cites = res.get("citations") or []
    t = ans.get("text_md") or ""
    boxes = (res.get("evidence") or {}).get("boxes") or []
    if not cites and boxes and t and not ans.get("abstained"):   # recount / forced paths can draw boxes without a citation: make one
        xs = [b["bbox_px"] for b in boxes if b.get("bbox_px")]
        cites = [{"n": 1, "doc_id": (res.get("doc_ids") or [""])[0], "page": boxes[0].get("page", 1), "kind": "region",
                  "bbox_px": [min(b[0] for b in xs), min(b[1] for b in xs), max(b[2] for b in xs), max(b[3] for b in xs)] if xs else None,
                  "item_ids": [b["item_id"] for b in boxes if b.get("item_id")], "quote": None}]
        res["citations"] = cites
    if cites and t and not ans.get("abstained") and not re.search(r"\[\d+\]", t):
        ans["text_md"] = t.rstrip() + " " + " ".join(f"[{c['n']}]" for c in cites[:5] if isinstance(c, dict) and "n" in c)
    return res


def _guarded(question, doc_ids, on_event, scene_state, history):
    """No question may end without an answer: past ANSWER_TIMEOUT_S (default 40, 0 = off) a hung model call is abandoned and a
    plain 'took too long' answer is returned, so the stream always ends with an answer event."""
    limit = float(os.environ.get("ANSWER_TIMEOUT_S", "40") or 0)
    if limit <= 0:
        return _answer_forced(question, doc_ids, on_event, scene_state=scene_state, history=history)
    import concurrent.futures as cf
    t0 = time.perf_counter()
    ex = cf.ThreadPoolExecutor(1, thread_name_prefix="answer")
    fut = ex.submit(_answer_forced, question, doc_ids, on_event, scene_state=scene_state, history=history)
    try:
        return fut.result(timeout=limit)
    except cf.TimeoutError:
        txt = (f"This took longer than {limit:.0f} s, so I stopped. Nothing was guessed. Ask again, or name one drawing with @ "
               "and ask a narrower question.")
        step = _step("timeout", f"no answer within {limit:.0f} s; the running model call was abandoned", int(limit * 1000), None, 0)
        if on_event:
            try:
                on_event("trace", step)
            except Exception:  # noqa: BLE001
                pass
        return _abstained(question, doc_ids, txt, [step], t0, route="index")
    finally:
        ex.shutdown(wait=False)


def answer(question: str, doc_ids: list[str], on_event: Callable | None = None, *, scene_state: dict | None = None,
           history: list[dict] | None = None) -> dict:
    # thread memory (engine/context.py): every route below sees the resolved, standalone question and document selection
    original, step = question, None
    try:
        from engine.context import resolve
        rs = resolve(question, doc_ids, history, _root())
        if rs.rewritten:
            question, doc_ids = rs.question, rs.doc_ids
            step = _step("context", f"question resolved with the chat history ({rs.info.get('source')}): {question[:300]}"
                         + (f" [documents: {', '.join(doc_ids)}]" if doc_ids else ""), rs.info.get("latency_ms", 0), rs.info.get("model"), rs.info.get("cost_usd", 0.0))
            if on_event:
                on_event("trace", step)
    except Exception:  # noqa: BLE001 — memory is a convenience, never block the answer
        question, step = original, None
    res = ensure_markers(_guarded(question, doc_ids, on_event, scene_state, history))
    if step is not None:
        res["trace"] = [step, *(res.get("trace") or [])]
        if step.get("cost_usd"):
            res["cost"]["calls"] = [{"task": "context_rewrite", "provider": "", "model": step["model"], "cost_usd": step["cost_usd"]}, *res["cost"].get("calls", [])]
            res["cost"]["usd_total"] = round(res["cost"].get("usd_total", 0) + step["cost_usd"], 6)
    return res


def _answer_forced(question: str, doc_ids: list[str], on_event: Callable | None = None, *, scene_state: dict | None = None,
           history: list[dict] | None = None) -> dict:
    """Code -> vision recount -> reader -> forced best-effort answer. Never abstains on a selected document (FORCE_ANSWER=0 restores abstaining)."""
    from engine.models import providers as _P
    _tok = _P.DELTA_SINK.set((lambda t: on_event("answer.delta", {"text": t})) if on_event else None)  # answer-text streaming
    try:
        res = _answer_core(question, doc_ids, on_event, scene_state=scene_state, history=history)
    finally:
        _P.DELTA_SINK.reset(_tok)
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
        if (question or "").strip() and not os.environ.get("TASKS_OFF"):
            from engine.tasks import detect, run_task   # Stoa starters: Draft claim, Meeting prep, Plan work phase, Review contract
            _task = detect(question)
            if _task:
                add(_step("route", f"document task: {_task}"))
                return run_task(_task, question, doc_ids, history, on_event, trace, t0, root, calls)
        if not doc_ids:
            if (question or "").strip():
                from engine.project_answer import project_answer
                res = project_answer(question, history, on_event, trace, t0, root, calls)
                if res is not None:
                    if res["answer"].get("abstained") and res.get("route") == "index" and os.environ.get("READER", "1") != "0":
                        top = [] if any(s["step"] == "document_list" for s in trace) else _top_docs(question, root)
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

        # 0-. "where is the stairs / lift / entrance (on level N)": code over IFC elements, no model
        from engine.locate import locate_answer, thing as _thing
        _what = _thing(question)
        if _what and parse_scene(question) is None:
            from engine.solvers.data import load_doc as _ld
            ldoc = _ld(doc_ids[0], root)
            if ldoc is not None and ldoc.mode == "ifc":
                emit("status", {"text": f"Exploring document: {_title(doc_ids[0], root)}"})
                res = locate_answer(question, ldoc, _what, t0)
                for s_ in res["trace"]:
                    add(s_)
                res["trace"] = trace
                return res

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
                _hide_ids = next((c.get("item_ids") for c in (res.get("evidence", {}).get("scene", {}).get("commands") or [])
                                  if isinstance(c, dict) and c.get("op") == "hide" and c.get("item_ids")), None)
                if _hide_ids:
                    from engine.analytics import wants_compliance, edit_advice
                    if wants_compliance(question):
                        edit_advice(res, doc, list(dict.fromkeys([*((scene_state or {}).get("hidden") or []), *_hide_ids])))
                for s_ in res["trace"]:
                    add(s_)
                res["trace"] = trace
                if scene_prov:
                    res["cost"] = {"usd_total": round(scene_cost, 6), "calls": list(calls)}
                return res

        # 0a. harder shapes that are still code: floor comparisons, conditional counts, take-offs with waste, named rooms, rule checks
        if parse_scene(question) is None:
            from engine import analytics
            from engine.solvers.data import load_doc as _lda
            from engine.solvers.solve import solve as _solve
            adoc = _lda(doc_ids[0], root)
            if adoc is not None and os.environ.get("ANALYTICS", "1") != "0":
                def _sub(sub_q, _d=doc_ids[0]):
                    return _solve(sub_q, _d, parsed=parse(sub_q), root=root)
                try:
                    res = analytics.run(question, adoc, t0, _sub)
                except Exception as e:  # noqa: BLE001  a handler must never take the answer down
                    res = None
                    add(_step("analytics", f"skipped: {type(e).__name__}"))
                if res is not None:
                    emit("status", {"text": f"Exploring document: {_title(doc_ids[0], root)}"})
                    for s_ in res["trace"]:
                        add(s_)
                    res["trace"] = trace
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
