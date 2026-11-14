"""E-09: IFC text questions. Facts come from elements.json by code; a model only phrases them.

  facts_for(question, doc) -> Facts(lines, item_ids, topic, available)
  text_answer(question, doc, use_model=None) -> answer object (CONTRACT 5.7)

Ladder: code builds the fact lines (exact, from elements.json). If write_answer is reachable it turns the
lines into 1-3 sentences; every number in its text must occur in the fact lines, else the code template is used.
No data -> a plain sentence saying so, abstained=True. Never invents values.
"""
from __future__ import annotations

import os
import re
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from engine.solvers.data import Doc, Item
from engine.solvers.solve import resolve_storey

KIND_KW = [("door", r"\bdoors?\b"), ("window", r"\bwindows?\b|\bglazing\b"), ("wall", r"\bwalls?\b"),
           ("slab", r"\bslabs?\b"), ("stairs", r"\bstairs?\b|\bstaircases?\b"), ("column", r"\bcolumns?\b"),
           ("railing", r"\brailings?\b|\bbalustrades?\b"), ("furniture", r"\bfurniture\b|\bchairs?\b|\bdesks?\b"),
           ("room", r"\brooms?\b|\bspaces?\b|\bfloor area\b")]
ABSENT = [("beam", r"\bbeams?\b"), ("pipe or MEP", r"\b(mep|pipes?|ducts?|heating|ventilation|hvac)\b"),
          ("sanitary fixture", r"\bsanitary\b"), ("covering", r"\bcoverings?\b"), ("ceiling", r"\bceilings?\b")]
PL = {"stairs": "stairs", "furniture": "furniture items", "room": "rooms"}
MAX_IDS = 400


@dataclass
class Facts:
    lines: list[str]
    item_ids: list[str] = field(default_factory=list)
    topic: str = ""
    available: bool = True


def _pl(kind: str, n: int = 2) -> str:
    return PL.get(kind, kind + "s") if n != 1 else {"stairs": "stair", "furniture": "furniture item"}.get(kind, kind)


def _f(v: float) -> str:
    return f"{v:,.1f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:,.0f}"


def _group(items: list[Item], key) -> list[tuple[str, list[Item]]]:
    g: dict[str, list[Item]] = defaultdict(list)
    for i in items:
        g[key(i) or "unnamed"].append(i)
    return sorted(g.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def _ids(items) -> list[str]:
    return [i.item_id for i in items][:MAX_IDS]


def _area(i: Item) -> float | None:
    for k in ("net_floor_area_m2", "area_m2"):
        if i.q.get(k) is not None:
            return float(i.q[k])
    return None


def facts_for(question: str, doc: Doc) -> Facts:
    ql = question.lower()
    st = resolve_storey(question, doc.storeys)
    if st is None and re.search(r"\b(attic|roof (?:floor|level)|top (?:floor|level))\b", ql) and doc.storeys:
        st = max(doc.storeys, key=lambda s: s["elevation_m"])["name"]
    kinds = [k for k, rx in KIND_KW if re.search(rx, ql)]
    # level questions
    if re.search(r"\b(levels?|storeys?|floors?)\b", ql) and re.search(r"height|how many|number of|elevation", ql) and not kinds:
        srt = sorted(doc.storeys, key=lambda s: s["elevation_m"])
        lines = [f"The model has {len(srt)} levels."]
        for a, b in zip(srt, srt[1:] + [None]):
            h = f", height {_f(b['elevation_m'] - a['elevation_m'])} m" if b else ""
            lines.append(f"{a['name']}: elevation {_f(a['elevation_m'])} m{h}")
        return Facts(lines, [], "levels")
    if not kinds:
        for label, rx in ABSENT:
            if re.search(rx, ql):
                return Facts([f"No {label} elements were found in this model."], [], "absent", available=False)
        if re.search(r"software|standard|schema|ifc version|authoring", ql):
            return Facts(["The software and schema are not stored in the element data I have."], [], "meta", available=False)
        return Facts(["I could not tell which elements the question is about."], [], "unknown", available=False)
    kind = kinds[0]
    items = [i for i in doc.items if i.kind == kind and (not st or i.storey == st)]
    where = f" on {st}" if st else ""
    if not items:
        return Facts([f"No {_pl(kind)} were found in this model{where}."], [], "absent", available=False)

    if re.search(r"load[- ]?bearing|fire[- ]?rat|acoustic|thermal transmittance|u-value", ql):
        what = re.search(r"load[- ]?bearing|fire[- ]?rat\w*", ql).group(0)
        return Facts([f"The model does not record {what} data for {_pl(kind)}."], [], "no-prop", available=False)
    if re.search(r"\b(exterior|interior|outer|inner|outside|inside|external|internal)\b", ql) and kind in ("wall", "door", "window"):
        return Facts([f"The model does not say which {_pl(kind)} are exterior or interior."], [], "no-prop", available=False)

    if kind == "room":
        rooms = [(i, _area(i)) for i in items if _area(i) is not None]
        if re.search(r"largest|biggest|smallest|tallest|highest", ql):
            if re.search(r"tall|high|ceiling|height", ql):
                hs = Counter(round(float(i.q["height_m"]), 2) for i in items if i.q.get("height_m") is not None)
                if not hs:
                    return Facts(["The model has no ceiling heights for rooms."], [], "no-prop", available=False)
                top = max(hs)
                hit = [i for i in items if i.q.get("height_m") is not None and round(float(i.q["height_m"]), 2) == top]
                return Facts([f"{len(hit)} of {len(items)} rooms have the greatest ceiling height, {_f(top)} m."]
                             + ([f"All rooms have a ceiling height of {_f(top)} m."] if len(hs) == 1 else []), _ids(hit), "room-height")
            small = "smallest" in ql
            r = (min if small else max)(rooms, key=lambda t: t[1])
            i = r[0]
            return Facts([f"{'Smallest' if small else 'Largest'} room: {i.name} ({i.type_name}), {_f(r[1])} m2, on {i.storey}."], [i.item_id], "room-extreme")
        by = _group(items, lambda i: i.storey)
        if re.search(r"by (level|floor|storey)|each (level|floor|storey)|per (level|floor|storey)|distribution|breakdown|total", ql) and not st:
            lines = [f"{len(items)} rooms in total, {_f(sum(a for _, a in rooms))} m2 net."]
            for name, its in sorted(by, key=lambda kv: next((s['elevation_m'] for s in doc.storeys if s['name'] == kv[0]), 0)):
                lines.append(f"{name}: {len(its)} rooms, {_f(sum(_area(i) or 0 for i in its))} m2")
            return Facts(lines, _ids(items), "room-levels")
        if st or re.search(r"breakdown|grouped|function", ql):
            lines = [f"{st or 'The building'}: {len(items)} rooms, {_f(sum(_area(i) or 0 for i in items))} m2 net."]
            for name, its in _group(items, lambda i: i.type_name):
                lines.append(f"{name}: " + ", ".join(f"{i.name} {_f(_area(i))} m2" for i in sorted(its, key=lambda i: i.name or "") if _area(i) is not None))
            return Facts(lines, _ids(items), "room-function")

    if re.search(r"widest|narrowest|greatest|largest|smallest|biggest", ql) and kind in ("door", "window", "column"):
        key = "width_m" if kind != "column" else "cross_section_area_m2"
        ws = [(i, i.q.get(key)) for i in items if i.q.get(key) is not None]
        if ws:
            rev = not re.search(r"narrowest|smallest", ql)
            n = 2 if re.search(r"\btwo\b|\b2\b", ql) else 1
            srt = sorted(ws, key=lambda t: t[1], reverse=rev)[:n]
            lab = "Widest" if rev else "Narrowest"
            return Facts([f"{lab} {_pl(kind, 1)}{'s' if n > 1 else ''}: " + "; ".join(f"{i.name} ({i.type_name}) {_f(v)} m" for i, v in srt)],
                         _ids([i for i, _ in srt]), "width-extreme")

    if re.search(r"thick", ql):
        ws = [i for i in items if i.q.get("width_m") is not None]
        if ws:
            lines = [f"Thickness by type for {len(ws)} {_pl(kind)}:"]
            for name, its in _group(ws, lambda i: i.type_name):
                lines.append(f"{name}: {_f(float(its[0].q['width_m']) * 1000)} mm ({len(its)})")
            return Facts(lines, _ids(ws), "thickness")

    if re.search(r"material", ql):
        by = _group(items, lambda i: i.props.get("material"))
        lines = [f"{len(items)} {_pl(kind)}{where}; materials:"] + [f"{n}: {len(its)}" for n, its in by]
        return Facts(lines, _ids(items), "materials")

    # default: counts per type
    by = _group(items, lambda i: i.type_name or i.name)
    lines = [f"Total {_pl(kind)}{where}: {len(items)}."] + [f"{n}: {len(its)} ({len(its) / len(items) * 100:.1f}%)" for n, its in by[:25]]
    if len(by) > 25:
        lines.append(f"... and {len(by) - 25} more types")
    return Facts(lines, _ids(items), "types")


def _numbers(s: str) -> set[str]:
    return {m.replace(",", "").rstrip(".") for m in re.findall(r"\d[\d,]*(?:\.\d+)?", s)}


def _template(f: Facts, marks: str) -> str:
    head = f.lines[0]
    body = "\n".join(f"- {l}" for l in f.lines[1:])
    first = re.sub(r"^(Total [^:]+:|[A-Z][^:]*:)\s*", "", head) if False else head
    return f"**{first}** {marks}" + (f"\n\n{body}" if body else "")


PROMPT = ("You answer a question about a building model using ONLY the facts below. Reply in at most three short sentences "
          "of plain English. Put the key fact first in **bold**. Use only numbers that appear in the facts. "
          "Do not add anything that is not in the facts: keep type and room names exactly as written (never translate or explain them). If a list is long, summarise the top items.\n\n"
          "Question: {q}\n\nFacts:\n{facts}\n")


def _phrase(question: str, f: Facts) -> tuple[str | None, dict | None]:
    from engine.models import call
    r = call("write_answer", PROMPT.format(q=question, facts="\n".join(f.lines)))
    t = (r.text or "").strip()
    ok = bool(t) and _numbers(t) <= _numbers("\n".join(f.lines)) and len(t) < 900
    meta = {"task": "write_answer", "provider": r.provider, "model": r.model, "cost_usd": r.cost_usd}
    return (t if ok else None), meta


def text_answer(question: str, doc: Doc, use_model: bool | None = None) -> dict:
    t0 = time.perf_counter()
    f = facts_for(question, doc)
    trace = [{"step": "facts", "detail": f"{f.topic}: {len(f.lines)} lines from elements.json", "ms": 0, "model": None, "cost_usd": 0}]
    calls: list[dict] = []
    cites = [] if not f.item_ids else [{"n": 1, "doc_id": doc.doc_id, "page": 1, "kind": "element", "bbox_px": None,
                                       "item_ids": f.item_ids, "quote": None}]
    marks = "[1]" if cites else ""
    text = None
    if use_model is None:
        use_model = os.environ.get("TEXT_WITH_MODEL", "1") != "0"
    if f.available and use_model and len(f.lines) > 1:
        try:
            ts = time.perf_counter()
            text, meta = _phrase(question, f)
            calls.append(meta)
            trace.append({"step": "write", "detail": "written from the facts" if text else "model text rejected (numbers not in facts); code template used",
                          "ms": int((time.perf_counter() - ts) * 1000), "model": meta["model"], "cost_usd": meta["cost_usd"]})
            if text and marks and "[1]" not in text:
                text = f"{text} {marks}"
        except Exception as e:
            trace.append({"step": "write", "detail": f"model unavailable ({type(e).__name__}); code template used", "ms": 0, "model": None, "cost_usd": 0})
    if not text:
        text = _template(f, marks)
    ids = f.item_ids
    scene = {"doc_id": doc.doc_id, "highlight_item_ids": ids, "camera_target_item_id": ids[0] if ids else None}
    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": [doc.doc_id],
        "answer": {"text_md": text, "value": None, "unit": None, "confidence": 0.9 if f.available else 0.0, "abstained": not f.available},
        "citations": cites, "evidence": {"boxes": [], "scene": scene}, "trace": trace, "route": "index",
        "cost": {"usd_total": round(sum(c["cost_usd"] for c in calls), 6), "calls": calls},
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }
