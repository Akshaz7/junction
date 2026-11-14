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
    if p.type=='count' and p.kind not in (None,'storey'):
        kinds=p.kinds or [p.kind]
        if any(not any(i.kind==k and i.conf>=.5 for i in doc.items) for k in kinds):
            return 'The automatic reader did not detect that item type; this does not establish a zero count.'
    if re.search(r'\bhow many\s+(?:[\w-]+\s+)?classrooms?\b',q):
        return 'The classroom labels need to be read from the drawing; a floor count would not answer this question.'
    return None
