"""MEP F15: fire-door / fire-rating questions on IFC models are answered in code from the recorded property sets.

Source: the indexed Pset_*Common.FireRating value (and any other recorded property whose name contains "fire").
$0, no reader calls, no truncated list. A door counts as rated only when its recorded text states a rating
(a duration or class number); blank, "none" and "self-closing" alone are listed as not counted, never guessed.
"""
from __future__ import annotations

import re
import time
import uuid

ASK = re.compile(r"\bfire[ -]?(?:rated|rating|ratings|resistan\w*|doors?)\b|\bbrandwerend\b", re.I)
VERB = re.compile(r"\b(?:how many|count|list|which|what|give|show|name|rating|ratings)\b", re.I)
OTHER = re.compile(r"\b(?:complian\w*|regulat\w*|code|escape|egress|travel|distance|exits?|compartment\w*|extinguisher\w*|sprinkler\w*|alarm\w*|detector\w*|stairs?|stairwell|propos\w*|widen|narrow|remove|delete|hide|order|cost|price)\b", re.I)
NONE = re.compile(r"^\s*(?:none|geen|no|nein|kein\w*|not rated|unrated|n/?a|-+|0|false)\s*$", re.I)
SELF = re.compile(r"(?:self[- ]?clos\w*|zelfsluitend|selbstschlie\w*|itsesulkeutuva)", re.I)
RATING = re.compile(r"(?:\b(?:REI|EI|EW|E|F|T|FD|RF|BS)\s*-?\s*\d{2,3}\b|\b\d{2,3}\s*(?:min\w*|mins|m\b|minuut|minuten|minutes)\b|\b(?:30|60|90|120|180|240)\b)", re.I)


def wants(question: str) -> bool:
    return bool(ASK.search(question)) and bool(VERB.search(question)) and not OTHER.search(re.sub(r"\bdo not count[^.?]*", "", question, flags=re.I))


def _values(item):
    out = []
    for k, v in (item.props or {}).items():
        if v in (None, "") or isinstance(v, (dict, list)) and not v:
            continue
        if k == "fire_rating" or re.search(r"fire|brand", str(k), re.I):
            out.append((k, str(v).strip()))
    return out


def classify(text: str) -> str:
    """rated | self-closing only | none | unclear"""
    if not text or NONE.match(text):
        return "none"
    stripped = SELF.sub("", text)
    if RATING.search(stripped):
        return "rated"
    if SELF.search(text):
        return "self-closing only"
    return "unclear"


def answer(question: str, doc, t0=None):
    if doc is None or doc.mode != "ifc" or not wants(question):
        return None
    t0 = t0 or time.perf_counter()
    from engine.solvers.solve import _answer_obj, _evidence, _step
    kind = "wall" if re.search(r"\bwalls?\b", question, re.I) and not re.search(r"\bdoors?\b", question, re.I) else "door"
    items = [i for i in doc.items if i.kind == kind]
    noun = kind
    trace = [_step("route", f"fire rating question -> recorded property sets, code only, no reader ({len(items)} {noun}s checked)")]
    scene0 = {"doc_id": doc.doc_id, "highlight_item_ids": [], "camera_target_item_id": None}
    if not items:
        return _answer_obj(question, [doc.doc_id], f"**No {noun}s are indexed in this model**, so no fire rating can be listed.", None, "count", 0.0, True, [], [], scene0, trace, "index", t0)
    rows, buckets = [], {"rated": [], "self-closing only": [], "none": [], "unclear": []}
    recorded = 0
    for it in items:
        vals = _values(it)
        if not vals:
            continue
        recorded += 1
        text = "; ".join(v for _, v in vals)
        c = classify(text)
        buckets[c].append((it, text))
    if not recorded:
        txt = (f"**None of the {len(items)} {noun}s in this model records a fire rating**, so I cannot say which are fire-rated. "
               "A blank value is not treated as 'no rating'; the property is simply absent from the index.")
        return _answer_obj(question, [doc.doc_id], txt, None, "count", 0.0, True, [], [], scene0, trace, "index", t0)
    rated = sorted(buckets["rated"], key=lambda x: ((x[0].storey or ""), (x[0].name or ""), x[0].item_id))
    by_level: dict[str, int] = {}
    by_rating: dict[str, int] = {}
    for it, text in rated:
        by_level[it.storey or "unassigned"] = by_level.get(it.storey or "unassigned", 0) + 1
        by_rating[text] = by_rating.get(text, 0) + 1
    elev = {s["name"]: s.get("elevation_m", 0) for s in doc.storeys}
    lv = "; ".join(f"{k}: {v}" for k, v in sorted(by_level.items(), key=lambda kv: elev.get(kv[0], 0)))
    rt = "; ".join(f"{k}: {v}" for k, v in sorted(by_rating.items(), key=lambda kv: -kv[1]))
    lines = [f"**{len(rated)} of {len(items)} {noun}s have a recorded fire rating.** Counted only where the recorded value states a rating; "
             f"blank values and self-closing alone are not counted."]
    if rated:
        lines.append(f"By level: {lv}.")
        lines.append(f"By recorded rating: {rt}.")
    lines.append(f"Not counted: {len(buckets['self-closing only'])} self-closing only"
                 f", {len(buckets['none'])} recorded as none"
                 f"{', ' + str(len(buckets['unclear'])) + ' with an unclear value' if buckets['unclear'] else ''}"
                 f", {len(items) - recorded} with no value recorded.")
    boxes, cites, scene = _evidence(doc, [it for it, _ in rated])
    marks = "".join(f"[{c['n']}]" for c in cites)
    table = ["", "| # | Name | Element ID | Level | Recorded fire rating |", "|---|---|---|---|---|"]
    for n, (it, text) in enumerate(rated, 1):
        table.append(f"| {n} | {it.name or ''} | {it.item_id} | {it.storey or ''} | {text} |")
    if buckets["unclear"]:
        table += ["", "Unclear values (not counted): " + "; ".join(f"{it.name or it.item_id} = “{t}”" for it, t in buckets["unclear"])]
    text = " ".join(lines) + marks + ("\n" + "\n".join(table) if rated else "")
    trace.append(_step("count", f"{len(rated)} rated, {len(buckets['self-closing only'])} self-closing only, {len(buckets['none'])} none, {len(items) - recorded} blank"))
    res = _answer_obj(question, [doc.doc_id], text, len(rated), "count", 0.95, False, boxes, cites, scene, trace, "index", t0)
    return res
