"""F-QSFIX: a window count read by an image model may include a glazed patio/balcony door.

We do not change the count (one file is not enough to verify a rule). We flag, low confidence, the cited windows that look like
glazed doors: far wider than the other windows on the plan, or touching a room printed as balcony/terrace/porch/patio.
Only for plan maps whose windows came from an image model or detector (vlm/det/seg); vector CAD and IFC types are exact.
"""
from __future__ import annotations

import re
import statistics

WIDE_RATIO = 1.5      # long side vs the median window on the same page
WIDE_MIN_M = 1.5      # and at least this wide when a scale exists
OUTDOOR = re.compile(r"balcon|balkon|parveke|terrace|terrasse|terassi|porch|patio|loggia|deck", re.I)


def _long(b):
    return max(b[2] - b[0], b[3] - b[1])


def suspects(doc, window_items):
    """Window items that look like glazed doors. Needs >= 3 windows on the page so 'unusually wide' means something."""
    out = []
    if not doc or doc.mode != "planmap" or not any(i.source in ("vlm", "det", "seg") for i in window_items):
        return out
    outdoor = [r for r in doc.items if r.kind == "room" and r.bbox_px and OUTDOOR.search(f"{r.label or ''} {r.props.get('room_type') or ''}")]
    mpp = (doc.scale or {}).get("m_per_px")
    for w in window_items:
        if not w.bbox_px:
            continue
        peers = [_long(x.bbox_px) for x in doc.items if x.kind == "window" and x.bbox_px and x.page == w.page]
        wide = len(peers) >= 3 and _long(w.bbox_px) >= WIDE_RATIO * statistics.median(peers) and (not mpp or _long(w.bbox_px) * mpp >= WIDE_MIN_M)
        touch = any(not (w.bbox_px[2] < r.bbox_px[0] or r.bbox_px[2] < w.bbox_px[0] or w.bbox_px[3] < r.bbox_px[1] or r.bbox_px[3] < w.bbox_px[1])
                    for r in outdoor)
        if wide or touch:
            out.append(w)
    return out


def attach(res, question, root):
    """Append the low-confidence note to a window-count answer. Never changes the number."""
    if not re.search(r"\bhow many\b.*\bwindows?\b|\bnumber of windows\b", question, re.I) or re.search(r"\bdoors?\b", question, re.I):
        return res
    ids = res.get("doc_ids") or []
    ans = res.get("answer") or {}
    if len(ids) != 1 or ans.get("abstained") or ans.get("unit") != "count" or not ans.get("text_md"):
        return res
    from engine.solvers.data import load_doc
    doc = load_doc(ids[0], root)
    cited = {i for c in res.get("citations") or [] for i in (c.get("item_ids") or [])}
    wins = [i for i in (doc.items if doc else []) if i.kind == "window" and i.item_id in cited]
    sus = suspects(doc, wins)
    if not sus:
        return res
    n, m = len(sus), len(wins)
    note = (f" Low confidence: {n} of these {m} windows {'is' if n == 1 else 'are'} unusually wide or {'sits' if n == 1 else 'sit'} next to an outdoor space, "
            f"so {'it' if n == 1 else 'they'} may be glazed {'door' if n == 1 else 'doors'} (patio or balcony), not {'a window' if n == 1 else 'windows'}.")
    ans["text_md"] += note
    ans["confidence"] = min(float(ans.get("confidence") or 1), 0.5) if isinstance(ans.get("confidence"), (int, float)) else ans.get("confidence")
    card = res.get("reasoning")
    if isinstance(card, dict):
        card.setdefault("steps", []).append({"kind": "checked", "title": "Possible glazed doors", "ok": False, "cite": None,
                                             "text": note.strip()})
    return res
