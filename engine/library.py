"""FIX-6: three small $0 helpers that sit in front of the model routes. Code only, no model call.

  fix_typos(question)            -> (question, [(wrong, right)])   domain words only, one edit away, never real English words
  library_answer(question, root) -> answer object | None           "how many designs are in the database", "what is stored", "which documents are processed"
  app_feature_answer(q, doc_ids) -> answer object | None           "render this 2D blueprint into 3D" -> use Visualise it; "show on table" -> AR
The app-feature answer carries `evidence.scene.open` = "3d" | "ar" (CONTRACT 5.14, additive); clients that know it open the view, others show the text.
"""
from __future__ import annotations

import re
import time
import uuid
from collections import Counter

VOCAB = ("windows window doors door floors floor storeys storey rooms room walls wall toilets toilet sinks sink showers shower "
         "bathtubs bathtub stairs staircase designs design database library documents document drawings drawing blueprint blueprints "
         "many count total area height length width volume kitchen bedroom bathroom balcony corridor elevator elevators columns beams "
         "slabs roof apartment apartments furniture visualise visualize processed stored").split()
# real words one edit from a vocabulary word: never "corrected"
KEEP = set("""store stores stored storing storage floored flooring wind wined window's dooms doom roomy rooms' wall's walls' wale sing sink's
shower's showed shows show wide widen wider length's lengths tower towers beam's beans bean design's desing slab's slabs' roofs roofing
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


_SHORT = {"dors": "doors", "dosr": "doors", "doro": "door", "wals": "walls", "romm": "room"}


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
    return re.sub(r"[A-Za-z]{4,}", sub, question), fixes


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


def wants_library(q: str) -> bool:
    if not q or _PROJECT_SPECIFIC.search(q):
        return False
    return any(r.search(q) for r in _LIB)


def library_answer(question: str, root=None) -> dict | None:
    if not wants_library(question):
        return None
    t0 = time.perf_counter()
    from engine.project_index import load_index
    ix = load_index(root)
    if ix is None or not ix.docs:
        return None
    docs = [d for d in ix.docs.values() if not d.get("generated_for_demo") or True]
    n = len(docs)
    proc = [d for d in docs if d.get("mode")]
    by_src = Counter(d.get("source") or "other" for d in docs)
    by_kind = Counter(d.get("kind") or "other" for d in docs)
    by_mode = Counter(d.get("mode") for d in proc)
    asks_processed = bool(re.search(r"\b(processed|read|parsed|analy[sz]ed|ready|done)\b", question, re.I))
    src = ", ".join(f"{k} {v:,}" for k, v in by_src.most_common(10))
    kinds = ", ".join(f"{k} {v:,}" for k, v in by_kind.most_common(8))
    text = (f"The library holds **{n:,} documents**. Processed into a structured plan map or IFC model (so counts and measurements are exact): "
            f"**{len(proc):,}** ({by_mode.get('planmap', 0):,} plan maps, {by_mode.get('ifc', 0):,} IFC models). "
            f"The other {n - len(proc):,} are indexed for search by title and text only.\n\n"
            f"By source: {src}.\n\nBy type: {kinds}.")
    if asks_processed:
        text += " Ask about one document by name, or with @, to work on it."
    trace = [{"step": "library", "detail": f"counted {n} documents in the project index; {len(proc)} processed", "ms": int((time.perf_counter() - t0) * 1000),
              "model": None, "cost_usd": 0}]
    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": [],
        "answer": {"text_md": text, "value": len(proc) if asks_processed else n, "unit": "documents", "confidence": 1.0, "abstained": False},
        "citations": [], "evidence": {"boxes": [], "scene": {"doc_id": "", "highlight_item_ids": [], "camera_target_item_id": None}},
        "trace": trace, "route": "index", "cost": {"usd_total": 0.0, "calls": []}, "latency_ms": int((time.perf_counter() - t0) * 1000),
    }


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


def app_feature_answer(question: str, doc_ids: list[str]) -> dict | None:
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
