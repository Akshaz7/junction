"""Printed/stated/written total area: quote it from the text layer with its box. No scale, no pixels, no model.

Falls through (returns None) when the page has no such printed total, or several different ones.
"""
from __future__ import annotations

import re
import time
import uuid

_ASK = re.compile(r"\b(?:printed|stated|written|listed|shown|labell?ed|noted|given|marked|schedule[sd]?)\b", re.I)
_TOTAL_AREA = re.compile(r"\b(?:total|gross|overall|sum)\b[^.?]{0,40}\barea\b|\barea\b[^.?]{0,40}\btotal\b|\bGFA\b", re.I)
_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d{1,3}(?:[   ]\d{3})+|\d+)(?:\.\d+)?"
_UNIT = r"(㎡|m²|m2|sq\.?\s*m\.?|sqm|sq\.?\s*ft\.?|sf|ft²)"
_KEY = r"(?:計|合計|総計|total(?:\s+(?:gross|floor))?(?:\s+area)?|gross\s+floor\s+area|total\s+floor\s+area|GFA|summe|yhteens[aä]|totalt?)"
_LINE = re.compile(rf"(?:{_KEY})\s*[:=]?\s*({_NUM})\s*{_UNIT}", re.I)


def wants(question: str) -> bool:
    return bool(_ASK.search(question) and _TOTAL_AREA.search(question)
                and not re.search(r"\b(?:for|of)\s+(?:the\s+)?(?:level|storey|floor|room|unit|apartment)\b|\blevel\s+\w+\b", question, re.I)
                and not re.search(r"\b(?:estimate|measure|calculate|compute|from the (?:plan|pixels))\b", question, re.I))


def _lines(words):
    rows = sorted((w for w in words if w.get("bbox_px")), key=lambda w: (w["bbox_px"][1] + w["bbox_px"][3]) / 2)
    out = []
    for w in rows:
        b = w["bbox_px"]
        cy, h = (b[1] + b[3]) / 2, max(b[3] - b[1], 1)
        if out and abs(out[-1]["cy"] - cy) <= 0.6 * max(h, out[-1]["h"]):
            out[-1]["words"].append(w)
        else:
            out.append({"cy": cy, "h": h, "words": [w]})
    for ln in out:
        ln["words"].sort(key=lambda w: w["bbox_px"][0])
    return [ln["words"] for ln in out]


def find(words):
    """[(value, unit, quote, bbox)] for every 'total <number><unit>' printed in the words."""
    found = []
    for ws in _lines(words):
        text, spans = "", []
        for w in ws:
            spans.append((len(text), len(text) + len(w["text"]), w))
            text += w["text"] + " "
        for m in _LINE.finditer(text):
            hit = [w for a, b, w in spans if a < m.end() and b > m.start()]
            bb = [min(w["bbox_px"][0] for w in hit), min(w["bbox_px"][1] for w in hit),
                  max(w["bbox_px"][2] for w in hit), max(w["bbox_px"][3] for w in hit)]
            u = m[2].lower().replace(" ", "").replace(".", "")
            unit = "ft²" if u in ("sqft", "sf", "ft²") else "m²"
            found.append((float(re.sub(r"[,\s  ]", "", m[1])), unit, m[0].strip(), bb))
    return found


def answer(question, doc_ids, root, t0=None):
    if not wants(question):
        return None
    from engine.titleblock import _pages
    t0 = t0 or time.perf_counter()
    hits = []
    for did in doc_ids:
        for pt in _pages(did, root, question) or []:
            for value, unit, quote, bbox in find(pt.words):
                hits.append((pt, value, unit, quote, bbox))
    if not hits or len({(v, u) for _, v, u, _, _ in hits}) != 1:
        return None
    pt, value, unit, quote, bbox = hits[0]
    n_pages = len({h[0].page for h in hits})
    text = f"**The total area printed on page {pt.page} is {value:,.2f} {unit}.** Quoted from the drawing's text layer: “{quote}” [1]. No scale or pixel estimate was used."
    if n_pages > 1:
        text += f" The same total is printed on {n_pages} pages."
    ms = int((time.perf_counter() - t0) * 1000)
    return dict(answer_id=uuid.uuid4().hex, question=question, doc_ids=list(doc_ids),
                answer=dict(text_md=text, value=value, unit=unit, confidence=.95, abstained=False),
                citations=[dict(n=1, doc_id=pt.doc_id, page=pt.page, kind="text", bbox_px=bbox, item_ids=[], quote=quote)],
                evidence=dict(boxes=[dict(item_id=f"printed-total-{pt.page}", page=pt.page, bbox_px=bbox, label="1")],
                              scene=dict(doc_id=pt.doc_id, highlight_item_ids=[], camera_target_item_id=None)),
                trace=[dict(step="printed_total", detail=f"quoted printed total from the {pt.source} on page {pt.page}", ms=ms, model=None, cost_usd=0)],
                route="index", cost=dict(usd_total=0.0, calls=[]), latency_ms=ms)
