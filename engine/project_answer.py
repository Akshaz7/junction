"""Project-wide answering: the user asks in Chat with NO document selected (Stoa's behaviour).

  project_answer(question, history, on_event, trace, t0, root) -> answer object | None
    None = not a project question (small talk, general know-how) or no index built: the caller keeps the old chat path.

Flow (engine.answer calls this only when doc_ids is empty):
  1. status "Searching: <key terms>", BM25 over the project index (engine.project_index).
  2. take-off question ("how many m2 of tiling for the toilets") -> engine.takeoff over the matching documents.
  3. the question names one document, or one clearly wins -> the existing per-document path (engine.answer.answer with that doc).
  4. otherwise answer from retrieved passages (PDF text with positions, or a document summary) with write_answer;
     every citation quotes an exact substring of a passage; numbers in the text must occur in the passages.
  5. nothing relevant -> say what was searched and that the documents do not cover it. Never invent.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

from engine.project_index import Index, SYN, excluded_doc, load_index, tokenize

SMALL_TALK = re.compile(
    r"^\s*(hi|hello|hey|hei|moi|yo|thanks?|thank you|thx|ok(ay)?|cool|great|good (morning|evening|afternoon)|bye|goodbye|"
    r"who are you|what are you|what can you do|what do you do|help|how (are|do) you|what is hologram|what's your name|"
    r"how does this (app|work)|how do i use (this|the app)).{0,20}$", re.I)
GENERAL = re.compile(r"^\s*(what (is|are|does|do)|how (do|does|to|should|can)|why|explain|define|tell me about)\b", re.I)
PROJECT_CUE = re.compile(r"\b(our|this project|the project|in the|on the|on sheet|on level|floor plan|drawing|model|schedule|section|"
                         r"elevation|ifc|room \d|door \d|level \d)\b", re.I)
STRONG_CUE = re.compile(r"\b(our|this project|the project|this (?:drawing|plan|model|sheet|building)|on sheet|on level|ifc|room \d|door \d|level \d)\b", re.I)
DOCUMENT_LIST = re.compile(
    r"^\s*(?:(?:which|what)\s+(?:drawings|documents|plans|models|sheets|files)\b|"
    r"(?:list|show|find)(?:\s+me)?\s+(?:(?:all|the|project|matching)\s+)*(?:drawings|documents|plans|models|sheets|files)\b)", re.I)
NUMERIC = re.compile(r"\b(how many|how much|count|number of|total|area|length|volume|square|m2|m²)\b", re.I)
MIN_COVERAGE = 0.5
MAX_PASSAGES = 5


def key_terms(question: str, n: int = 5) -> str:
    from engine.project_index import STOP
    out, seen = [], set()
    for w in re.findall(r"[^\W_]+(?:[-'][^\W_]+)*", question or "", re.U):
        lw = w.casefold()
        if lw in STOP or (len(lw) == 1 and not lw.isdigit()) or lw in seen:
            continue
        seen.add(lw)
        out.append(w)
    return " ".join(out[:n]) or (question or "").strip()[:40]


def is_small_talk(question: str) -> bool:
    q = (question or "").strip()
    return not q or bool(SMALL_TALK.match(q)) or not tokenize(q)


def _step(step, detail, ms=0, model=None, cost=0.0):
    return {"step": step, "detail": detail, "ms": ms, "model": model, "cost_usd": cost}


def _out(question, doc_ids, text, trace, t0, *, abstained, conf=0.0, cites=None, boxes=None, scene_doc="", ids=(), route="index", calls=None):
    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": list(doc_ids),
        "answer": {"text_md": text, "value": None, "unit": None, "confidence": conf, "abstained": abstained},
        "citations": cites or [], "evidence": {"boxes": boxes or [], "scene": {
            "doc_id": scene_doc or (doc_ids[0] if doc_ids else ""), "highlight_item_ids": list(ids), "camera_target_item_id": (list(ids)[0] if ids else None)}},
        "trace": trace, "route": route,
        "cost": {"usd_total": round(sum(c.get("cost_usd", 0) for c in (calls or [])), 6), "calls": calls or []},
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }


# --- passages -------------------------------------------------------------------------------------------------------
def page_lines(doc_id: str, page: int, root: Path) -> list[dict]:
    """Text lines of one page with positions: [{text, bbox_px}], reading order. From text-N.json (pdf / dxf text layer)."""
    try:
        t = json.loads((Path(root) / doc_id / f"text-{page}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    words = [w for w in t.get("words") or [] if str(w.get("text") or "").strip() and w.get("bbox_px")]
    words.sort(key=lambda w: ((w["bbox_px"][1] + w["bbox_px"][3]) / 2, w["bbox_px"][0]))
    lines: list[list[dict]] = []
    for w in words:
        b = w["bbox_px"]
        cy, h = (b[1] + b[3]) / 2, max(b[3] - b[1], 1.0)
        if lines:
            lb = lines[-1][-1]["bbox_px"]
            lcy = sum((x["bbox_px"][1] + x["bbox_px"][3]) / 2 for x in lines[-1]) / len(lines[-1])
            if abs(cy - lcy) <= 0.5 * max(h, lb[3] - lb[1]):
                lines[-1].append(w)
                continue
        lines.append([w])
    out = []
    for ln in lines:
        ln.sort(key=lambda w: w["bbox_px"][0])
        bb = [min(w["bbox_px"][0] for w in ln), min(w["bbox_px"][1] for w in ln), max(w["bbox_px"][2] for w in ln), max(w["bbox_px"][3] for w in ln)]
        out.append({"text": " ".join(str(w["text"]).strip() for w in ln), "bbox_px": [round(v, 1) for v in bb]})
    return out


def best_passages(question: str, ix: Index, doc_id: str, page: int, root: Path, per_page: int = 2) -> list[dict]:
    """Best windows (1-3 adjacent lines) of a page for the question: [{text, bbox_px, score, coverage}]."""
    lines = page_lines(doc_id, page, root)
    if not lines:
        return []
    terms = ix.query_terms(question)
    base = [t for t, w in terms.items() if w == 1.0]
    mass_total = sum(ix.idf(t) for t in base) or 1.0
    ltoks = [set(tokenize(l["text"])) for l in lines]
    sc = []
    for toks in ltoks:
        sc.append(sum(ix.idf(t) * w for t, w in terms.items() if t in toks))
    order = sorted(range(len(lines)), key=lambda i: -sc[i])
    out, used = [], set()
    for i in order:
        if sc[i] <= 0 or len(out) >= per_page:
            break
        if i in used:
            continue
        lo, hi = max(0, i - 1), min(len(lines) - 1, i + 1)
        # keep neighbours that are close vertically (same block)
        while lo < i and lines[i]["bbox_px"][1] - lines[lo]["bbox_px"][3] > 2.5 * (lines[i]["bbox_px"][3] - lines[i]["bbox_px"][1]):
            lo += 1
        while hi > i and lines[hi]["bbox_px"][1] - lines[i]["bbox_px"][3] > 2.5 * (lines[i]["bbox_px"][3] - lines[i]["bbox_px"][1]):
            hi -= 1
        idx = list(range(lo, hi + 1))
        if any(j in used for j in idx):
            idx = [i]
        used.update(idx)
        text = " ".join(lines[j]["text"] for j in idx)
        if len(text) > 320:
            text, idx = lines[i]["text"][:320], [i]
        toks = set().union(*(ltoks[j] for j in idx))
        cov = sum(ix.idf(t) for t in base if t in toks) / mass_total
        bb = [min(lines[j]["bbox_px"][0] for j in idx), min(lines[j]["bbox_px"][1] for j in idx),
              max(lines[j]["bbox_px"][2] for j in idx), max(lines[j]["bbox_px"][3] for j in idx)]
        out.append({"text": text, "bbox_px": [round(v, 1) for v in bb], "score": round(sum(sc[j] for j in idx), 3), "coverage": round(cov, 3)})
    return out


def summary_text(s: dict) -> str:
    bits = [f"{s.get('title')} ({s.get('kind') or 'document'}, {s.get('source')})"]
    if s.get("discipline"):
        bits.append(f"discipline: {s['discipline']}")
    if s.get("storeys"):
        bits.append("storeys: " + ", ".join(s["storeys"][:10]))
    if s.get("rooms"):
        bits.append("rooms: " + ", ".join(s["rooms"][:12]))
    if s.get("counts"):
        bits.append("elements: " + ", ".join(f"{v} {k}" for k, v in list(s["counts"].items())[:8]))
    return "; ".join(bits)


def gather_passages(question: str, ix: Index, hits: list[dict], root: Path, only: list[str] | None = None) -> list[dict]:
    terms = ix.query_terms(question)
    base = [t for t, w in terms.items() if w == 1.0]
    cands = []
    for h in hits:
        if only and h["doc_id"] not in only:
            continue
        s = ix.docs.get(h["doc_id"], {})
        if h["page"] > 0:
            for p in best_passages(question, ix, h["doc_id"], h["page"], root):
                if p["coverage"] >= 0.2 or (len(base) <= 1 and p["score"] > 0):
                    cands.append({**p, "doc_id": h["doc_id"], "page": h["page"], "title": s.get("title") or h["doc_id"], "kind": "text",
                                  "rank": p["score"] * (0.5 + p["coverage"])})
        elif h["coverage"] >= MIN_COVERAGE:
            cands.append({"text": summary_text(s), "bbox_px": None, "doc_id": h["doc_id"], "page": 1, "title": s.get("title") or h["doc_id"],
                          "kind": "text", "score": h["score"], "coverage": h["coverage"], "rank": h["score"] * (0.5 + h["coverage"]) * 0.8})
    cands.sort(key=lambda p: -p["rank"])
    out, seen = [], set()
    for p in cands:
        k = (p["doc_id"], p["page"], p["text"][:60])
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
        if len(out) >= MAX_PASSAGES:
            break
    return out


# --- writing --------------------------------------------------------------------------------------------------------
PROMPT = ("Answer the question using ONLY the numbered passages from the project's documents below. Lead with the key fact in bold. "
          "Put the passage number in square brackets, like [1], right after each sentence it supports. Use only numbers and names that "
          "appear in the passages. If the passages do not answer the question, say so plainly in one sentence and do not guess. "
          "At most four short sentences.\n\nQuestion: {q}\n\nPassages:\n{p}\n")


def _numbers(s: str) -> set[str]:
    s = re.sub(r"\[\d+\]", "", s)
    return {m.replace(",", "").rstrip(".") for m in re.findall(r"\d[\d,]*(?:\.\d+)?", s)}


def _write(question: str, passages: list[dict]):
    from engine.assistant import with_system
    from engine.models import call
    block = "\n".join(f"[{i}] ({p['title']}, page {p['page']}) {p['text']}" for i, p in enumerate(passages, 1))
    r = call("write_answer", with_system(PROMPT.format(q=question, p=block)))
    t = (r.text or "").strip()
    ok = bool(t) and re.search(r"\[\d+\]", t) is not None and _numbers(t) <= _numbers(block) and len(t) < 1200
    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", t) if 0 < int(n) <= len(passages)}) if ok else []
    meta = {"task": "write_answer", "provider": r.provider, "model": r.model, "cost_usd": r.cost_usd}
    return (t if ok and cited else None), cited, meta


def _template(passages: list[dict]) -> tuple[str, list[int]]:
    top = passages[:3]
    lines = [f"**Found in {p['title']}, page {p['page']}:** \"{p['text'][:220]}\" [{i}]" for i, p in enumerate(top, 1)]
    return "\n\n".join(lines), list(range(1, len(top) + 1))


def passage_answer(question, passages, trace, t0, root, calls, use_model=True):
    text, cited = None, []
    if use_model and os.environ.get("TEXT_WITH_MODEL", "1") != "0":
        try:
            ts = time.perf_counter()
            text, cited, meta = _write(question, passages)
            calls.append(meta)
            trace.append(_step("write", "written from the passages" if text else "model text rejected (unsupported numbers or no citation); template used",
                               int((time.perf_counter() - ts) * 1000), meta["model"], meta["cost_usd"]))
        except Exception as e:  # noqa: BLE001
            trace.append(_step("write", f"model unavailable ({type(e).__name__}); template used"))
    if not text:
        text, cited = _template(passages)
    remap = {old: new for new, old in enumerate(cited, 1)}
    text = re.sub(r"\[(\d+)\]", lambda m: f"[{remap[int(m.group(1))]}]" if int(m.group(1)) in remap else "", text)
    cites, boxes = [], []
    for old in cited:
        p = passages[old - 1]
        n = remap[old]
        cites.append({"n": n, "doc_id": p["doc_id"], "page": p["page"], "kind": "text", "bbox_px": p["bbox_px"], "item_ids": [],
                      "quote": p["text"]})
        if p["bbox_px"]:
            boxes.append({"item_id": f"text-{n}", "page": p["page"], "bbox_px": p["bbox_px"], "label": str(n)})
    docs = list(dict.fromkeys(c["doc_id"] for c in cites))
    return _out(question, docs, text, trace, t0, abstained=False, conf=0.6, cites=cites, boxes=boxes, route="index", calls=calls)


# --- main -----------------------------------------------------------------------------------------------------------
def _load(did, root):
    from engine.solvers.data import load_doc
    return load_doc(did, root)


def document_list_answer(question, ix, named, trace, t0, root, calls):
    """Enumerate all matching docs before limiting output; never ask a model to invent a document list."""
    cue = DOCUMENT_LIST.match(question)
    if not cue:
        return None
    subject = question[cue.end():]
    base = {t for t in tokenize(subject) if "-" not in t}
    if not base:
        return None
    # Generic schedule titles are useful candidates, but do not prove which kind of schedule is on a sheet.
    schedule = "schedule" in base or "table" in base or bool(re.search(r"\b(?:door|window)\s+lists?\b", subject, re.I))
    required = {"schedule"} if schedule else base
    groups = {t: {t, *tokenize(SYN.get(t, ""))} for t in required}
    hits = ix.search("schedule" if schedule else subject, len(ix.chunks), per_doc=False, include_excluded=set(named))
    by_doc: dict[str, list[dict]] = {}
    for h in hits:
        by_doc.setdefault(h["doc_id"], []).append(h)
    matches = []
    for did, docs_hits in by_doc.items():
        matched = set().union(*(set(h["matched"]) for h in docs_hits))
        if not all(variants & matched for variants in groups.values()):
            continue
        pages = [h for h in docs_hits if h["page"] > 0 and all(variants & set(h["matched"]) for variants in groups.values())]
        best = max(pages or docs_hits, key=lambda h: h["score"])
        matches.append({**best, "page": best["page"] or 1})
    matches.sort(key=lambda h: (-h["score"], h["doc_id"]))
    trace.append(_step("document_list", f"{len(matches)} matching documents; showing at most 15"))
    if not matches:
        return _out(question, [], f"I found no project documents with indexed evidence for **{key_terms(subject)}**.",
                    trace, t0, abstained=True, calls=calls)
    shown = matches[:15]
    text = f"**{len(matches)} drawings match this search.**"
    if schedule:
        text += " Schedule sheets are matched by title or indexed text; check the sheet for the requested schedule."
    cites = []
    for n, h in enumerate(shown, 1):
        s = ix.docs[h["doc_id"]]
        text += f"\n- {s['title']}, page {h['page']}. [{n}]"
        cites.append({"n": n, "doc_id": h["doc_id"], "page": h["page"], "kind": "text", "bbox_px": None,
                      "item_ids": [], "quote": s["title"]})
    if len(matches) > len(shown):
        text += f"\n\nand {len(matches) - len(shown)} more."
    return _out(question, [h["doc_id"] for h in shown], text, trace, t0, abstained=False, conf=0.8, cites=cites, calls=calls)


def project_answer(question: str, history, on_event, trace: list, t0: float, root: Path, calls: list | None = None) -> dict | None:
    ix = load_index(root)
    if ix is None or not ix.docs or is_small_talk(question):
        return None
    calls = calls if calls is not None else []
    emit = on_event or (lambda k, p: None)

    def add(step):
        trace.append(step)
        emit("trace", step)

    terms = key_terms(question)
    emit("status", {"text": f"Searching: {terms}"})
    ts = time.perf_counter()
    named = [d for d in ix.named_docs(question) if d in ix.docs]
    for m in re.findall(r"\b[a-z0-9]+(?:_[a-z0-9]+)*__[A-Za-z0-9][\w.\-]*[A-Za-z0-9_]", question):
        if m in ix.docs and m not in named:
            named.append(m)
    boost = {"uploads": 1.3}
    eligible = {d for d, s in ix.docs.items() if not excluded_doc(s) or d in named}
    hits = ix.search(question, 10, boost, include_excluded=set(named))
    add(_step("search", f"{len(eligible)} documents searched for '{terms}': " + (
        ", ".join(f"{ix.docs[h['doc_id']]['title'][:40]} (p.{h['page']})" if h["page"] else ix.docs[h["doc_id"]]["title"][:40] for h in hits[:3])
        or "no match") + (f"; named: {', '.join(named[:3])}" if named else ""), int((time.perf_counter() - ts) * 1000)))

    listed = document_list_answer(question, ix, named, trace, t0, root, calls)
    if listed is not None:
        emit("trace", trace[-1])
        return listed

    from engine.takeoff import parse_takeoff, takeoff_answer, ROOM_CLASSES
    tk = parse_takeoff(question)

    # 2. take-off over every matching document
    if tk is not None:
        cand = [d for d in named if ix.docs[d].get("mode")]
        if not cand:
            rx = tk.rx
            match = [d for d, s in ix.docs.items() if d in eligible and s.get("mode") and any(rx.search(str(r)) or re.fullmatch(rx.pattern, str(r), re.I) for r in s.get("rooms", []))]
            up = [d for d in match if ix.docs[d].get("source") == "uploads"]
            if 0 < len(up) <= 5:
                cand = up
            elif hits and hits[0]["page"] == 0 and hits[0]["doc_id"] in match and (len(hits) < 2 or hits[0]["score"] >= 1.4 * hits[1]["score"]):
                cand = [hits[0]["doc_id"]]
            else:
                top = [h["doc_id"] for h in hits if h["doc_id"] in match][:5] or match[:5]
                add(_step("abstain", f"take-off: {len(match)} documents have {tk.room_class} rooms, none clearly meant"))
                names = "\n".join(f"- {ix.docs[d]['title']} (`{d}`)" for d in top)
                txt = (f"{len(match)} documents in the project have {tk.room_class} rooms, so I cannot tell which one you mean. "
                       f"Name the drawing (or select it with @) and I will total the rooms and add the allowance."
                       + (f"\n\nClosest matches:\n{names}" if names else ""))
                return _out(question, [], txt, trace, t0, abstained=True, route="index", calls=calls)
        docs = [d for d in (_load(c, root) for c in cand[:5]) if d is not None]
        if docs:
            for d in docs:
                emit("status", {"text": f"Exploring document: {d.title or d.doc_id}"})
            res = takeoff_answer(question, docs, tk, t0, title_of=lambda d: ix.docs.get(d.doc_id, {}).get("title") or d.title or d.doc_id, root=root)
            for s_ in res["trace"]:
                add(s_)
            res["trace"] = trace
            return res

    # 3. a single document is named or clearly wins -> the existing per-document path
    numeric = bool(NUMERIC.search(question))
    clear = None
    if named:
        clear = named[0]
    elif hits and hits[0]["page"] == 0 and hits[0]["coverage"] >= 0.6 and (len(hits) < 2 or hits[0]["score"] >= 1.5 * hits[1]["score"]):
        clear = hits[0]["doc_id"]
    if clear:
        from engine.answer import answer as per_doc
        add(_step("route", f"document identified: {ix.docs[clear]['title']}"))

        def inner(kind, payload):
            if kind == "status" and payload.get("text") == "Thinking…":
                return
            if kind != "trace":
                emit(kind, payload)
        res = per_doc(question, [clear], inner)
        if not res["answer"].get("abstained") or not ix.docs[clear].get("text_pages"):
            res["trace"] = trace + res["trace"]
            return res
        add(_step("route", "per-document path abstained; trying the document's text"))
        hits = [h for h in ix.search(question, len(ix.chunks), per_doc=False, include_excluded=set(named)) if h["doc_id"] == clear][:6] or hits
        only = [clear]
    else:
        only = None
        hits = ix.search(question, 12, boost, per_doc=False)

    # 4. passages
    top = hits[0] if hits else None
    if not top or top["coverage"] < MIN_COVERAGE:
        if GENERAL.match(question) and not STRONG_CUE.search(question) and not named:
            return None            # general know-how: the chat path answers it, labelled as general guidance
        add(_step("abstain", "nothing in the project documents matches"))
        txt = (f"I searched {len(eligible):,} project documents for **{terms}** and none of them covers it, so I cannot answer from the project. "
               "If the document is not uploaded yet, add it in Data; if you know which drawing, select it with @ and ask again.")
        return _out(question, [], txt, trace, t0, abstained=True, route="index", calls=calls)
    passages = gather_passages(question, ix, hits, root, only)
    if numeric and not clear:      # a count/measure from an unidentified drawing would be a guess: only document text may answer
        passages = [p for p in passages if p["bbox_px"]]
    if not passages:
        near = list(dict.fromkeys(h["doc_id"] for h in hits))[:4]
        names = "\n".join(f"- {ix.docs[d]['title']} (`{d}`)" for d in near)
        add(_step("abstain", "documents match the words but no passage answers the question"))
        txt = (f"I searched the project for **{terms}**. Several documents mention related terms, but none contains a passage that "
               "answers this, so I will not guess." + (f"\n\nClosest documents:\n{names}" if names else "")
               + ("\n\nThis needs a count or measurement from one drawing: name it or select it with @." if numeric else ""))
        return _out(question, [], txt, trace, t0, abstained=True, route="index", calls=calls)
    for d in dict.fromkeys(p["doc_id"] for p in passages):
        emit("status", {"text": f"Exploring document: {ix.docs.get(d, {}).get('title') or d}"})
    add(_step("passages", f"{len(passages)} passage(s) from {len({p['doc_id'] for p in passages})} document(s)"))
    res = passage_answer(question, passages, trace, t0, root, calls)
    return res
