"""FIX-6: three small $0 helpers that sit in front of the model routes. Code only, no model call.

  fix_typos(question)            -> (question, [(wrong, right)])   domain words only, one edit away, never real English words
  library_answer(question, root) -> answer object | None           "how many designs are in the database", "what is stored", "which documents are processed"
  app_feature_answer(q, doc_ids) -> answer object | None           "render this 2D blueprint into 3D" -> use Visualise it; "show on table" -> AR
The app-feature answer carries `evidence.scene.open` = "3d" | "ar" (CONTRACT 5.14, additive); clients that know it open the view, others show the text.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from collections import Counter
from contextvars import ContextVar
from pathlib import Path

VOCAB = ("windows window doors door floors floor storeys storey rooms room walls wall toilets toilet sinks sink showers shower "
         "bathtubs bathtub stairs staircase designs design database library documents document drawings drawing blueprint blueprints "
         "many count total area height length width volume kitchen bedroom bathroom balcony corridor elevator elevators columns beams "
         "slabs roof apartment apartments furniture visualise visualize processed stored living").split()
# real words one edit from a vocabulary word: never "corrected"
KEEP = set("""store stores stored storing storage floored flooring wind wined window's dooms doom roomy rooms' wall's walls' wale sing sink's
lining shower's showed shows show wide widen wider length's lengths tower towers beam's beans bean design's desing slab's slabs' roofs roofing
colum column's columns' stair's stairs' area's areas arena areas many man mane mean meant money count's counts county county's
total's totals totally toilet's volume's volumes document's documented library's librarian drawing's drawings' height's heights
doors' door's door-to""".split())
_WORD = re.compile(r"[A-Za-z]{5,}")


def _edit1(a: str, b: str) -> bool:
    """Damerau edit distance exactly 1 (substitution, insertion, deletion or adjacent swap)."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        d = [i for i in range(len(a)) if a[i] != b[i]]
        return len(d) == 1 or (len(d) == 2 and d[1] == d[0] + 1 and a[d[0]] == b[d[1]] and a[d[1]] == b[d[0]])
    s, l = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    while i < len(s) and s[i] == l[i]:
        i += 1
    return s[i:] == l[i + 1:]


_SHORT = {"dors": "doors", "dosr": "doors", "doro": "door", "wals": "walls", "romm": "room", "mny": "many", "mnay": "many", "hw": "how", "hoq": "how", "waht": "what", "wat": "what", "whta": "what", "rom": "room", "hwo": "how", "wich": "which", "whihc": "which"}


def fix_typos(question: str) -> tuple[str, list[tuple[str, str]]]:
    vocab = set(VOCAB)
    fixes: list[tuple[str, str]] = []

    def sub(m: re.Match) -> str:
        w = m.group(0)
        lw = w.lower()
        if lw in vocab or lw in KEEP or lw.rstrip("s") in vocab or lw.rstrip("es") in vocab:
            return w
        r = _SHORT.get(lw)
        if r is None and len(lw) >= 5:
            for v in VOCAB:
                if len(v) >= 5 and v[0] == lw[0] and v not in KEEP and (_edit1(lw, v) or (len(v) == len(lw) and sorted(v) == sorted(lw))):
                    r = v
                    break
        if r is None:
            return w
        fixes.append((w, r))
        return r.capitalize() if w[0].isupper() else r
    # a quoted label ('Balcone', "Zimmer") is the drawing's own word, never a typo
    parts = re.split(r"((?<![\w])'[^']+'(?!\w)|\"[^\"]+\")", question)
    return "".join(p if i % 2 else re.sub(r"[A-Za-z]{2,}", sub, p) for i, p in enumerate(parts)), fixes


# ------------------------------------------------------------------ library questions
_THING = r"(?:designs?|documents?|docs?|drawings?|plans?|blueprints?|models?|files?|buildings?|projects?|items?)"
_PLACE = r"(?:database|data ?base|library|workspace|project|app|system|store|storage|collection|corpus|dataset|index|platform|here)"
_LIB = [
    re.compile(rf"\bhow many {_THING}\b[^?]*\b(?:in|inside|are (?:in|stored|loaded|available|processed|indexed|there in)|stored|loaded|available|processed|indexed|do (?:you|we) have|have you)\b", re.I),
    re.compile(rf"\bhow many {_THING}\b[^?]*\b{_PLACE}\b", re.I),
    re.compile(rf"\b(?:what(?:'s| is| are)|show me what(?:'s| is)?|list)\b[^?]*\b(?:stored|saved|loaded|in the {_PLACE}|in your {_PLACE}|you have|available)\b", re.I),
    re.compile(rf"\bwhich {_THING}\b[^?]*\b(?:processed|indexed|read|loaded|available|stored|analy[sz]ed|ready|done|parsed)\b", re.I),
    re.compile(rf"\bwhat {_THING}\b[^?]*\b(?:processed|indexed|read|loaded|available|stored|analy[sz]ed|do you have|have you)\b", re.I),
    re.compile(rf"\b(?:size|contents?) of the {_PLACE}\b", re.I),
]
_PROJECT_SPECIFIC = re.compile(r"\b(?:window|door|room|wall|floor|storey|level|toilet|sink|stair|area|kitchen|bedroom)s?\b", re.I)


# A request's Data catalogue is authoritative; never share it between concurrent chats.
CATALOGUE: ContextVar[list[dict] | None] = ContextVar("library_catalogue", default=None)
JUNK_TITLE = re.compile(r"^(?:smoke[-_]|stress[-_]|qa[-_]|web3[-_]notes[-_]|generated[ _-]+for[ _-]+demo)", re.I)


def excluded_doc(doc: dict) -> bool:
    title = str(doc.get("title") or "").strip()
    tail = str(doc.get("doc_id") or "").split("__", 1)[-1]
    return bool(doc.get("generated_for_demo") or JUNK_TITLE.search(title) or JUNK_TITLE.search(tail)
                or re.search(r"upload-fixture|generated[ _-]+for[ _-]+demo|cross-device", title + " " + tail, re.I))


def catalogue(root=None, records=None) -> list[dict]:
    """Use the same visible database rows as Data, falling back to local metadata outside the API."""
    supplied = records if records is not None else CATALOGUE.get()
    if supplied is not None:
        root = Path(root or __import__("os").environ.get("ARTIFACTS_DIR") or "artifacts")
        docs = [dict(d) for d in supplied if not excluded_doc(d)]
        for d in docs:
            folder = root / d["doc_id"]
            if (folder / "elements.json").is_file():
                d["mode"] = "ifc"
            elif any(folder.glob("planmap-[0-9]*.json")):
                d["mode"] = "planmap"
        return docs
    from engine.project_index import load_index, registry_records, doc_ids_in
    root = Path(root or __import__("os").environ.get("ARTIFACTS_DIR") or "artifacts")
    ix = load_index(root)
    docs = {d: dict(v) for d, v in (ix.docs.items() if ix else [])}
    registered = registry_records(root)
    for did in doc_ids_in(root, registered):
        meta = dict(registered.get(did) or {})
        try:
            meta.update(json.loads((root / did / "doc.json").read_text()))
        except (OSError, ValueError):
            pass
        docs[did] = {**docs.get(did, {}), **meta, "doc_id": did}
    return [d for d in docs.values() if not excluded_doc(d)]


def _result(question, text, *, docs=(), value=None, unit=None, abstained=False, cites=(), step="library"):
    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": list(docs),
        "answer": {"text_md": text, "value": value, "unit": unit, "confidence": 0.0 if abstained else 1.0, "abstained": abstained},
        "citations": list(cites), "evidence": {"boxes": [], "scene": {"doc_id": "", "highlight_item_ids": [], "camera_target_item_id": None}},
        "trace": [{"step": step, "detail": "Answered from the visible document catalogue; no model call", "ms": 0, "model": None, "cost_usd": 0}],
        "route": "index", "cost": {"usd_total": 0.0, "calls": []}, "latency_ms": 0,
    }


_IFC_QUERY = re.compile(r"\b(?:which|what|list|show|find)\b.*\b(?:projects?|documents?|models?|files?|buildings?)\b.*\bifc\b|\b(?:which|what|list|show|find)\b.*\bifc\b.*\b(?:projects?|models?|files?)\b", re.I)
_SHEETS = re.compile(r"\b(?:how many|number of|count (?:the )?)\s*(?:sheets?|pages?)\b|\b(?:sheet|page) count\b", re.I)


def wants_library(q: str) -> bool:
    if _IFC_QUERY.search(q or ""):
        return True
    if not q or _PROJECT_SPECIFIC.search(q):
        return False
    return any(r.search(q) for r in _LIB)


def _is_ifc(doc):
    formats = doc.get("formats") or []
    files = doc.get("files") or {}
    if isinstance(files, str):
        try:
            files = json.loads(files)
        except ValueError:
            files = {}
    return (str(doc.get("kind") or "").lower() == "ifc" or doc.get("mode") == "ifc"
            or "ifc" in {str(f).lower() for f in formats} or "ifc" in files)


def _named(question, docs):
    from engine.project_index import norm_name, tokenize
    q = norm_name(question)
    selected = []
    qt = set(tokenize(question)) - {"pricing", "set", "issue", "sheet", "page"}
    for d in docs:
        title = str(d.get("title") or "")
        names = [title, d["doc_id"], d["doc_id"].split("__", 1)[-1]]
        if any(n and norm_name(n) and re.search(r"(?<!\w)" + re.escape(norm_name(n)) + r"(?!\w)", q) for n in names):
            selected.append(d)
        elif len(qt) >= 2:
            tt = set(tokenize(title))
            # Distinctive project tokens can match a long filename without treating an object kind as a title.
            if len(qt & tt) >= 2 and len(qt & tt) / len(qt) >= 0.75:
                selected.append(d)
    return selected


def sheet_count_answer(question, doc_ids=(), root=None, records=None):
    if not _SHEETS.search(question or ""):
        return None
    docs = catalogue(root, records)
    if doc_ids:
        docs = [d for d in docs if d["doc_id"] in doc_ids]
    else:
        docs = _named(question, docs)
    # A sheet set is the PDF's page metadata, never an IFC selected just because it shares the project name.
    pdfs = [d for d in docs if str(d.get("kind", "")).lower() == "pdf" or "pdf" in (d.get("formats") or [])]
    if pdfs:
        docs = pdfs
    if len(docs) != 1:
        return None
    d = docs[0]
    n = d.get("pages")
    if isinstance(n, list):
        n = len(n)
    if isinstance(n, bool) or not isinstance(n, int) or n < 1 or _is_ifc(d) and not pdfs:
        return _result(question, "The document metadata does not state a sheet count. Select the drawing set PDF to count its pages.", abstained=True)
    c = {"n": 1, "doc_id": d["doc_id"], "page": 1, "kind": "text", "bbox_px": None, "item_ids": [],
         "quote": f"Document metadata: {n} pages"}
    res = _result(question, f"**{d.get('title') or d['doc_id']} has {n} {'page' if n == 1 else 'pages'}** in this file. [1]",
                  docs=[d["doc_id"]], value=n, unit="pages", cites=[c])
    from engine.calc_inventory import metadata
    return metadata(res, [d], pages=True)


def library_answer(question: str, root=None, records=None) -> dict | None:
    if not wants_library(question):
        return None
    docs = catalogue(root, records)
    if _IFC_QUERY.search(question):
        found = sorted((d for d in docs if _is_ifc(d)), key=lambda d: str(d.get("title") or d["doc_id"]).casefold())
        if not found:
            return _result(question, "No IFC models are listed in the visible document library.", value=0, unit="documents")
        text = f"**{len(found)} documents have IFC models:**"
        cites = []
        for n, d in enumerate(found, 1):
            text += f"\n- {d.get('project') or d.get('title') or d['doc_id']} (`{d['doc_id']}`). [{n}]"
            cites.append({"n": n, "doc_id": d["doc_id"], "page": 1, "kind": "text", "bbox_px": None,
                          "item_ids": [], "quote": f"{d.get('title') or d['doc_id']} — IFC file in document metadata"})
        res = _result(question, text, docs=[d["doc_id"] for d in found], value=len(found), unit="documents", cites=cites)
        from engine.calc_inventory import metadata
        return metadata(res, found)
    n = len(docs)
    proc = [d for d in docs if d.get("mode")]
    by_src = Counter(d.get("source") or "other" for d in docs)
    by_kind = Counter(d.get("kind") or "other" for d in docs)
    by_mode = Counter(d.get("mode") for d in proc)
    asks_processed = bool(re.search(r"\b(processed|read|parsed|analy[sz]ed|ready|done)\b", question, re.I))
    src = ", ".join(f"{k} {v:,}" for k, v in by_src.most_common(10)) or "none"
    kinds = ", ".join(f"{k} {v:,}" for k, v in by_kind.most_common(8)) or "none"
    text = f"The library holds **{n:,} documents**, using the same visible catalogue as Data. Test and demo uploads are excluded."
    # An index may only cover the baked documents; missing entries do not mean unprocessed.
    if asks_processed:
        text += (f" Structured data is indexed for **{len(proc):,}** ({by_mode.get('planmap', 0):,} plan maps, "
                 f"{by_mode.get('ifc', 0):,} IFC models). Other documents may still be processing or awaiting indexing.")
    text += f"\n\nBy source: {src}.\n\nBy type: {kinds}."
    res = _result(question, text, value=len(proc) if asks_processed else n, unit="documents")
    from engine.calc_inventory import metadata
    return metadata(res, proc if asks_processed else docs)


def library_search_answer(question, root=None, records=None):
    """Document-list searches operate on a filtered view, without changing the shared search index."""
    from engine.project_answer import DOCUMENT_LIST, document_list_answer
    from engine.project_index import Index, load_index
    search_question = re.sub(r"\bfloor\s+plans\b", "plans", question or "", flags=re.I)
    if not DOCUMENT_LIST.match(search_question):
        return None
    ix = load_index(root)
    if ix is None:
        return _result(question, "There is no searchable document index available yet.", abstained=True, step="search")
    allowed = {d["doc_id"] for d in catalogue(root, records)}
    view = Index()
    with ix.lock:
        view.docs = {k: dict(v) for k, v in ix.docs.items() if k in allowed and not excluded_doc(v)}
        view.chunks = {k: v for k, v in ix.chunks.items() if k[0] in view.docs}
        view.names = {k: [d for d in v if d in view.docs] for k, v in ix.names.items()}
    view.rebuild_postings()
    result = document_list_answer(search_question, view, [], [], time.perf_counter(), root, [])
    if result is not None:
        result["question"] = question
    return result


def drawing_selection_answer(question, root=None, history=None, records=None):
    """An unselected drawing is never inferred from a search score for a count or measurement."""
    from engine.context import last_docs, needs_rewrite, stands_alone
    from engine.project_index import load_index
    from engine.app_help import app_help_answer
    if wants_library(question) or app_feature(question) or app_help_answer(question, []):
        return None
    if last_docs(history) and needs_rewrite(question, [], history) and not stands_alone(question):
        return None
    if re.search(r"\b(?:across|all|every)\s+(?:the\s+)?(?:projects?|drawings?|documents?|models?|buildings?)\b|\b(?:in|across) the (?:project|library)\b", question, re.I):
        return None
    docs = catalogue(root, records)
    if _named(question, docs):
        return None
    ix = load_index(root)
    if ix and ix.named_docs(question):
        return None
    from engine.context import _kinds
    if not (_PROJECT_SPECIFIC.search(question) or _SHEETS.search(question) or _kinds(question)
            or re.search(r"\b(?:this|the) (?:drawing|plan|model|sheet|building)\b", question, re.I)):
        return None
    # Requests to discover drawings are project searches, not a choice of one drawing to measure.
    if re.match(r"\s*(?:find|search|which (?:drawings?|plans?|documents?|projects?)|list (?:drawings?|plans?|documents?))\b", question, re.I):
        return None
    ranked = ix.search(question, len(ix.docs)) if ix else []
    allowed = {d["doc_id"]: d for d in docs}
    likely = [allowed[h["doc_id"]] for h in ranked if h["doc_id"] in allowed][:3]
    if not likely:
        likely = sorted(docs, key=lambda d: str(d.get("title") or d["doc_id"]).casefold())[:3]
    text = "**Which drawing do you mean?** Select one with @ or name it in your question."
    if likely:
        text += "\n\nPossible drawings:\n" + "\n".join(f"- {d.get('title') or d['doc_id']} (`{d['doc_id']}`)" for d in likely)
    return _result(question, text, abstained=True, step="document_selection")


def reader_partial(question, doc_ids, session, trace, calls, t0):
    """A reader can publish this after each tool: verbatim findings, with its registered evidence only."""
    cites, lines, boxes, ids = [], [], [], []
    for evidence in list(session.ev.values())[-6:]:
        if not evidence.quote:
            continue
        n = len(cites) + 1
        cites.append({"n": n, "doc_id": evidence.doc_id, "page": evidence.page,
                      "kind": "text" if evidence.kind in ("text", "row") else "element" if evidence.kind == "element" else "region",
                      "bbox_px": evidence.bbox_px, "item_ids": list(evidence.item_ids), "quote": evidence.quote})
        lines.append(f"- {evidence.quote} [{n}]")
        ids.extend(i for i in evidence.item_ids if i not in ids)
        if evidence.bbox_px:
            boxes.append({"item_id": evidence.item_ids[0] if evidence.item_ids else evidence.ref, "page": evidence.page,
                          "bbox_px": evidence.bbox_px, "label": str(n)})
    text = "Reader findings so far (not yet a complete answer):\n" + "\n".join(lines) if lines else "No verified findings are available yet."
    ans = _result(question, text, docs=doc_ids, abstained=not cites, cites=cites, step="read")
    ans["answer"]["confidence"] = 0.3 if cites else 0.0
    ans["evidence"]["boxes"] = boxes
    ans["evidence"]["scene"] = {"doc_id": cites[0]["doc_id"] if cites else (doc_ids[0] if doc_ids else ""),
                                 "highlight_item_ids": ids, "camera_target_item_id": ids[0] if ids else None}
    ans["trace"] = list(trace)
    ans["route"] = "hybrid"
    ans["cost"] = {"usd_total": round(sum(c.get("cost_usd", 0) for c in calls), 6), "calls": list(calls)}
    ans["latency_ms"] = int((time.perf_counter() - t0) * 1000)
    return ans


# ------------------------------------------------------------------ app-feature requests
_VIEW_VERB = r"(?:render|show|view|see|visuali[sz]e|turn|convert|open|display|make|extrude|build|give|put|take|switch|go)"
_3D = re.compile(rf"\b{_VIEW_VERB}\b[^?]*\b(?:3 ?d|three[- ]?d(?:imensional)?|3d model|in 3|visuali[sz]e it)\b|\bvisuali[sz]e it\b|\b(?:2d|plan|blueprint|drawing|floor ?plan)\b[^?]*\b(?:into|to|in|as)\b[^?]*\b3 ?d\b", re.I)
_AR = re.compile(r"\b(?:show|view|see|put|place|open|display|project|bring)\b[^?]*\b(?:on (?:the |my |a )?(?:table|desk|floor|surface)|in (?:ar|augmented reality)|\bar\b|augmented reality|life[- ]?size|1:1|walk ?through)\b|\bshow on table\b", re.I)
_MEASURE = re.compile(r"\b(how many|how much|count|area|length|height|width|volume|total|which|what)\b", re.I)


def app_feature(question: str) -> str | None:
    q = (question or "").strip()
    if not q or _MEASURE.search(q) and not re.search(r"\bvisuali[sz]e\b|\b3 ?d\b", q, re.I):
        return None
    if _MEASURE.match(q):
        return None
    if _AR.search(q):
        return "ar"
    if _3D.search(q) and not re.search(r"\b(hide|isolate|highlight|remove)\b", q, re.I):
        return "3d"
    return None


APPROX_3D = "The 3D view is approximated from the drawing."


def approx_3d(doc_id: str, root=None) -> bool:
    """True when the doc's scene.json says its 3D was approximated from a raster drawing (props.approx)."""
    try:
        import os
        from pathlib import Path
        r = Path(root or os.environ.get("ARTIFACTS_DIR") or "artifacts")
        sc = json.loads((r / doc_id / "scene.json").read_text())
        return bool((sc.get("props") or {}).get("approx") or sc.get("approx"))
    except (OSError, ValueError, AttributeError):
        return False


def app_feature_answer(question: str, doc_ids: list[str], root=None) -> dict | None:
    which = app_feature(question)
    if not which:
        return None
    t0 = time.perf_counter()
    doc = doc_ids[0] if doc_ids else ""
    if which == "3d":
        text = ("Use **Visualise it** under any answer: it lifts this plan into 3D, and the same numbered items glow. "
                "You can open it from the 3D button on the drawing too." if doc else
                "Select a drawing first, then use **Visualise it** on an answer to lift the plan into 3D with the same numbered items glowing.")
    else:
        text = ("Use **Show on table** in the iOS app: it places this model on your table in AR, with the same items glowing, "
                "and you can scale it up to 1:1 to walk through." if doc else
                "Select a drawing first, then open it in the iOS app and tap **Show on table** to see it in AR with the same items glowing.")
    if doc and approx_3d(doc, root):
        text += " " + APPROX_3D
    scene = {"doc_id": doc, "highlight_item_ids": [], "camera_target_item_id": None, "open": which} if doc else \
            {"doc_id": "", "highlight_item_ids": [], "camera_target_item_id": None}
    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": list(doc_ids),
        "answer": {"text_md": text, "value": which, "unit": "view", "confidence": 1.0, "abstained": False},
        "citations": [], "evidence": {"boxes": [], "scene": scene},
        "trace": [{"step": "app_feature", "detail": f"request to open the {which.upper()} view: answered from the app's own features, no model", "ms": 0,
                   "model": None, "cost_usd": 0}],
        "route": "index", "cost": {"usd_total": 0.0, "calls": []}, "latency_ms": int((time.perf_counter() - t0) * 1000),
    }
