"""Identify raster questions whose answer is absent from the structured detections.

A detector's missing class is not a verified zero; labels and dimensions need a
page read. The dispatcher supplies that read and retains a plain unknown on failure.
"""
from __future__ import annotations
import re

from engine.router.parser import parse
from .data import load_doc


def reading_reason(question, doc_ids, root):
    if len(doc_ids) != 1:
        return None
    q=question.lower()
    # Count a drawn designation, rather than certifying accessibility/compliance.
    if re.search(r'\bhow many\b',q) and re.search(r'\b(?:accessible|aba|disabled|wheelchair)\b',q) and re.search(r'\b(?:rooms?|dorms?|units?|spaces?)\b',q):
        doc=load_doc(doc_ids[0],root)
        if doc is None or doc.mode=='planmap':
            return 'The count of rooms carrying that designation has not been verified from the drawing.'
    doc=load_doc(doc_ids[0],root)
    if doc is None or doc.mode!='planmap':
        return None
    demo_map = any(re.search(r'\bdemo\b|\bgenerated\b', i.source, re.I) for i in doc.items)
    if not any(i.source in ('det','seg','vlm') for i in doc.items) and not demo_map:
        return None  # vector CAD counts retain their exact empty-set semantics.
    p=parse(question)
    if demo_map and p.type == 'count':
        return 'The structured map is labelled generated for demo; the count needs checking against the source drawing.'
    if re.search(r'\bhow many\s+(?:[\w-]+\s+)?classrooms?\b',q):
        return 'The classroom labels need to be read from the drawing; a floor count would not answer this question.'
    return None


def missing_detection_reason(question, doc, result):
    """Qualify missing raster detections after the solver and recount have finished.

    An absent detector class must not bypass the calibrated recount. Nor may a
    reader's re-query of those same detections replace an already usable count.
    A count with supporting boxes (including recount boxes) keeps its evidence.
    """
    if doc is None or doc.mode != 'planmap' or result.get('route') != 'planmap':
        return None
    p = parse(question)
    if p.type != 'count' or p.kind in (None, 'storey'):
        return None
    if not any(i.source in ('det', 'seg', 'vlm') for i in doc.items):
        return None
    if (result.get('evidence') or {}).get('boxes'):
        return None
    kinds = set(p.kinds or [p.kind])
    # A combined shower/bath question asks for one total, not two class totals.
    if p.kind in ('shower', 'bathtub') and re.search(r'\bshowers?\b', question, re.I) and re.search(r'\bbath ?tubs?\b', question, re.I):
        kinds = {'shower', 'bathtub'}
    if not any(i.kind in kinds and i.conf >= .5 for i in doc.items):
        return 'The automatic reader did not detect that item type; this does not establish a zero count.'
    return None
