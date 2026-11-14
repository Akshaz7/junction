"""Evidence for document tasks: numbered, citable items gathered with plain code (no model).

gather(task, doc_ids, root) -> Evidence(items, gaps, images, scope)
  item   {n, doc_id, page, kind: "region"|"text"|"element", text, bbox_px, change_id, title, date}
  gaps   deterministic "missing evidence" lines (cost / delay / entitlement ... searched and not found)
Sources: revision changes of the version series (artifacts/series/diffs, built by pipeline.series), page text (project index passages or
the text layer of the selected documents), plan-map facts of drawings, and the document inventory (title, discipline, date).
Nothing here invents a fact: every item quotes a file under the artifacts root.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

MAX_ITEMS = 40
MAX_CHANGES_PER_PAIR = 4
MAX_PAIRS_PROJECT = 6
MAX_PAIRS_DOC = 6
TEXT_CLIP = 320

QUERIES = {   # lexical retrieval query per task (BM25 over the project index)
    "claim": "change revision addendum delay cost notice claim variation instruction extension schedule",
    "meeting": "revision change coordination clash query RFI decision interface trades open",
    "phase": "sequence foundation framing structure access scaffold services install phase construction notes",
    "contract": "contract agreement scope responsibilities notice change order variation liability payment termination",
}
GAP_RULES = {   # category -> (regex on evidence text, sentence when nothing matches)
    "cost": (re.compile(r"[$€£]\s?\d|\b\d[\d,.]*\s?(usd|eur|dollars?|euros?)\b|\b(cost|price|quote|invoice|estimate|budget|change order)\b", re.I),
             "No cost evidence (prices, quotes, invoices, change orders) was found in the documents searched."),
    "delay": (re.compile(r"\b(delay|delayed|schedule|programme|program|critical path|calendar days?|working days?|extension of time|late)\b", re.I),
              "No delay evidence (schedule, programme, dated notices of delay) was found in the documents searched."),
    "entitlement": (re.compile(r"\b(contract|clause|notice|entitle\w*|extension of time|variation|change order|instruction|agreement)\b", re.I),
                    "No entitlement basis (contract clause, notice, instruction or change order) was found in the documents searched."),
    "contract": (re.compile(r"\b(contract|agreement|conditions of contract|general conditions|subcontract)\b", re.I),
                 "No contract document was found among the project documents."),
}
GAPS_FOR = {"claim": ["cost", "delay", "entitlement"], "contract": ["contract"], "meeting": [], "phase": []}


@dataclass
class Evidence:
    items: list[dict] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    images: list[Path] = field(default_factory=list)
    scope: str = ""          # one line: what was searched
    docs_searched: int = 0

    def add(self, **kw) -> dict | None:
        if len(self.items) >= MAX_ITEMS:
            return None
        text = re.sub(r"\s+", " ", str(kw.get("text") or "")).strip()
        if not text:
            return None
        it = {"doc_id": kw["doc_id"], "page": int(kw.get("page") or 1), "kind": kw.get("kind", "text"), "text": text[:TEXT_CLIP * 2],
              "bbox_px": kw.get("bbox_px"), "change_id": kw.get("change_id"), "title": kw.get("title") or kw["doc_id"], "date": kw.get("date")}
        key = (it["doc_id"], it["page"], it["text"][:80], it["change_id"])
        if any((x["doc_id"], x["page"], x["text"][:80], x["change_id"]) == key for x in self.items):
            return None
        it["n"] = len(self.items) + 1
        self.items.append(it)
        return it


def _json(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def title_of(doc_id: str, root: Path) -> str:
    return (_json(Path(root) / doc_id / "doc.json") or {}).get("title") or doc_id


def all_series(root: Path) -> list[dict]:
    d = Path(root) / "series"
    out = []
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        s = _json(f)
        if isinstance(s, dict) and s.get("series_id") and len(s.get("versions") or []) >= 2:
            out.append(s)
    return out


def series_for(doc_id: str, root: Path) -> dict | None:
    for s in all_series(root):
        if any(v["doc_id"] == doc_id for v in s["versions"]):
            return s
    return None


def _diff(root: Path, sid: str, i: int) -> dict | None:
    return _json(Path(root) / "series" / "diffs" / f"{sid}--{i + 1}-{i + 2}.json")


def _rank(c: dict) -> tuple:
    d = c.get("description") or ""
    return (0 if ("Text" in d and "changed" in d) or "added" in d.lower() else 1 if "removed" in d.lower() and "no text" not in d else 2, -(c.get("ink_px") or 0))


def add_pair(ev: Evidence, s: dict, i: int, limit: int) -> int:
    """Revision changes between versions i and i+1 of a series as evidence items. Returns how many were added."""
    root_diff = s.get("_root")
    diff = _diff(root_diff, s["series_id"], i) if root_diff else None
    if not diff:
        return 0
    a, b = s["versions"][i], s["versions"][i + 1]
    changes = sorted(diff.get("changes") or [], key=_rank)[:limit]
    n = 0
    for c in changes:
        page = c.get("page_v2") or c.get("page") or 1
        bb = c.get("bbox_px_v2") or c.get("bbox_px_v1")
        desc = (c.get("description") or f"A {c.get('kind', 'region')} changed.")
        text = (f"Revision change {c.get('change_id', '')} on page {page} between {a.get('label') or a['doc_id']} "
                f"({a.get('date') or 'undated'}) and {b.get('label') or b['doc_id']} ({b.get('date') or 'undated'}): {desc}")
        if ev.add(doc_id=b["doc_id"], page=page, kind="region", text=text, bbox_px=bb if isinstance(bb, list) and len(bb) == 4 else None,
                  change_id=f"ser:{s['series_id']}:{i + 1}#{c.get('change_id', '')}", title=s.get("title") or title_of(b["doc_id"], Path(root_diff)),
                  date=b.get("date")):
            n += 1
    return n


def _with_root(s: dict, root: Path) -> dict:
    return {**s, "_root": str(root)}


def _plan_facts(doc_id: str, root: Path) -> str | None:
    try:
        from engine.solvers.data import load_doc
        doc = load_doc(doc_id, root)
    except Exception:  # noqa: BLE001
        return None
    if doc is None or not doc.items:
        return None
    c = Counter(i.kind for i in doc.items)
    rooms = [i.label for i in doc.items if i.kind == "room" and i.label][:12]
    storeys = [s.get("name") for s in (doc.storeys or []) if s.get("name")][:8]
    bits = [f"{'IFC model' if doc.mode == 'ifc' else 'Plan map'} of {doc.title or doc_id}: " + ", ".join(f"{v} {k}" for k, v in c.most_common(10))]
    if rooms:
        bits.append("rooms: " + ", ".join(rooms))
    if storeys:
        bits.append("storeys: " + ", ".join(storeys))
    return "; ".join(bits)


def _page_text(doc_id: str, root: Path, pages: int = 2) -> list[dict]:
    """Text layer of the first pages as passages [{page, text, bbox_px}] (fallback when the project index has no passages for the doc)."""
    from engine.project_answer import page_lines
    out = []
    for p in range(1, pages + 1):
        lines = page_lines(doc_id, p, root)
        if not lines:
            continue
        text = " ".join(l["text"] for l in lines)[:TEXT_CLIP * 2]
        bb = [min(l["bbox_px"][0] for l in lines), min(l["bbox_px"][1] for l in lines), max(l["bbox_px"][2] for l in lines), max(l["bbox_px"][3] for l in lines)]
        out.append({"page": p, "text": text, "bbox_px": bb})
    return out


def _image(doc_id: str, root: Path) -> Path | None:
    p = Path(root) / doc_id / "page-1.png"
    return p if p.exists() else None


def gather(task: str, question: str, doc_ids: list[str], root: Path) -> Evidence:
    root = Path(root)
    ev = Evidence()
    from engine.project_index import load_index
    ix = load_index(root)
    if ix and ix.docs:
        ev.docs_searched = len(ix.docs)
    elif root.is_dir():
        ev.docs_searched = sum(1 for p in root.iterdir() if (p / "doc.json").exists())
    query = QUERIES.get(task, question)
    all_s = [_with_root(s, root) for s in all_series(root)]

    if doc_ids:
        # focus: the documents, their revision series, their text and plan-map facts
        names = []
        for d in doc_ids[:3]:
            t = title_of(d, root)
            names.append(t)
            meta = _json(root / d / "doc.json") or {}
            ev.add(doc_id=d, page=1, kind="text", title=t, text=f"Document: {t} ({meta.get('kind') or 'document'}, source {meta.get('source') or 'unknown'}, "
                                                                f"{meta.get('pages') or 1} page(s))")
            s = next((x for x in all_s if any(v["doc_id"] == d for v in x["versions"])), None)
            if s:
                pos = next(i for i, v in enumerate(s["versions"]) if v["doc_id"] == d)
                pairs = list(range(0, len(s["versions"]) - 1))[:MAX_PAIRS_DOC]
                got = sum(add_pair(ev, s, i, MAX_CHANGES_PER_PAIR) for i in pairs)
                ev.scope = (ev.scope + "; " if ev.scope else "") + (f"{len(s['versions'])} versions of '{s.get('title')}' "
                            f"({', '.join(str(v.get('date') or '?') for v in s['versions'][:8])}); {got} documented change(s)")
            else:
                ev.scope = (ev.scope + "; " if ev.scope else "") + f"{t}: not part of a version series, so no documented revisions"
            facts = _plan_facts(d, root)
            if facts:
                ev.add(doc_id=d, page=1, kind="text", title=t, text=facts)
            hit = False
            if ix and d in ix.docs:
                from engine.project_answer import gather_passages
                hs = [h for h in ix.search(query, 20, per_doc=False) if h["doc_id"] == d]
                for p in gather_passages(query, ix, hs, root, [d])[:3]:
                    if p["bbox_px"]:
                        hit = bool(ev.add(doc_id=d, page=p["page"], kind="text", title=t, text=p["text"], bbox_px=p["bbox_px"])) or hit
            if not hit:
                for p in _page_text(d, root):
                    ev.add(doc_id=d, page=p["page"], kind="text", title=t, text=p["text"], bbox_px=p["bbox_px"])
            img = _image(d, root)
            if img is not None and len(ev.images) < 2:
                ev.images.append(img)
                ev.add(doc_id=d, page=1, kind="region", title=t, text=f"The drawing sheet of {t}, page 1 (image attached): what is visible on it, such as rooms, openings and labels")
        ev.scope = f"{', '.join(names)}: {ev.scope}"
    else:
        # whole project: newest revision changes, best-matching passages, the matching documents
        pairs = []
        for s in all_s:
            for i in range(len(s["versions"]) - 1):
                diff = _diff(root, s["series_id"], i)
                if diff and diff.get("changes"):
                    pairs.append((s["versions"][i + 1].get("date") or "", s, i, len(diff["changes"])))
        pairs.sort(key=lambda t: (t[0], t[3]), reverse=True)
        used = 0
        for _, s, i, _n in pairs[:MAX_PAIRS_PROJECT]:
            if add_pair(ev, s, i, MAX_CHANGES_PER_PAIR):
                used += 1
        if ix and ix.docs:
            from engine.project_answer import gather_passages
            hits = ix.search(query, 12, per_doc=False)
            for p in gather_passages(query, ix, hits, root):
                if p["bbox_px"]:
                    ev.add(doc_id=p["doc_id"], page=p["page"], kind="text", title=p["title"], text=p["text"], bbox_px=p["bbox_px"])
            for h in ix.search(query, 6)[:4]:
                sm = ix.docs.get(h["doc_id"]) or {}
                ev.add(doc_id=h["doc_id"], page=1, kind="text", title=sm.get("title") or h["doc_id"],
                       text=f"Document: {sm.get('title')} ({sm.get('kind') or 'document'}, {sm.get('discipline') or 'unclassified'}, source {sm.get('source')})")
        ev.scope = (f"whole project, {ev.docs_searched:,} documents searched; {len(pairs)} revision pair(s) with documented changes, {used} used")
    for cat in GAPS_FOR.get(task, []):
        rx, sentence = GAP_RULES[cat]
        # the document inventory lines name the task's words only by accident: look at passages and changes
        if not any(rx.search(i["text"]) for i in ev.items if i["text"] and not i["text"].startswith("Document:")):
            ev.gaps.append(sentence)
    return ev
