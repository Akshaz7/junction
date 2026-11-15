"""Count-card facts come from the returned evidence, including transient vision boxes.

A citation is a group of items, never one counted object. Missing boxes do not
change a source total: we report the coverage and keep the source total explicit.
"""
from __future__ import annotations

import math
import re

_NUMBER = r"\d[\d,]*"
_WORDS = {
    "door": ("door", "doors"), "window": ("window", "windows"),
    "room": ("room", "rooms", "space", "spaces"), "wall": ("wall", "walls"),
    "toilet": ("toilet", "toilets", "WC", "WCs"), "sink": ("sink", "sinks"),
    "shower": ("shower", "showers"), "bathtub": ("bathtub", "bathtubs"),
    "stairs": ("staircase", "staircases", "stair", "stairs"),
    "slab": ("slab", "slabs"), "column": ("column", "columns"),
    "beam": ("beam", "beams"), "roof": ("roof", "roofs"),
    "storey": ("storey", "storeys", "story", "stories", "floor", "floors"),
    "pipe": ("pipe", "pipes"), "duct": ("duct", "ducts"),
    "item": ("item", "items", "element", "elements", "object", "objects"),
}


_UNIT_WORD = r"(?:mm|cm|m|km|m2|m²|m3|m³|sqm|sq|ft|in|inch|inches|feet|%|percent|kg|deg|degrees|min|minutes|s|sec|seconds|hours?|ml|l)\b"


def _integer(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0 and int(v) == v


def _kind(question, headline):
    # The answer's noun is narrower than the router's parent kind (e.g. bedrooms).
    clean = headline.replace("*", "")
    # A measurement ("900 mm threshold", "2.1 m high", "5 %") is not a count of anything: never take its unit as the noun.
    for m in re.finditer(rf"(?:{_NUMBER}|no)\s+(?:boxed\s+)?([\w -]+?)(?=\s+(?:on|in|reported|matching|with)\b|[.;\n]|$)", clean, re.I):
        noun = m[1].strip()
        if re.match(_UNIT_WORD, noun, re.I):
            continue
        if len(noun) <= 45:
            return noun
    try:
        from engine.router.parser import parse
        return parse(question).kind or "item"
    except (AttributeError, ValueError):
        return "item"


def _word(kind, n):
    words = _WORDS.get(kind)
    if words:
        return words[0 if n == 1 else 1]
    # Already written in English by the count solver (bedrooms, WC rooms, ...).
    if n == 1:
        return kind
    if kind.endswith("s"):
        return kind
    return kind[:-1] + "ies" if kind.endswith("y") else kind + "s"


def _headline_values(text, counts):
    clean = re.sub(r"\[\d+\]", "", text.split("\n", 1)[0]).replace("*", "")
    out = {}
    for kind in counts:
        names = _WORDS.get(kind, (kind, _word(kind, 2)))
        nouns = "|".join(re.escape(w) for w in sorted(set(names), key=len, reverse=True))
        m = re.search(rf"\b({_NUMBER}|no)\s+(?:boxed\s+)?(?:{nouns})\b", clean, re.I)
        if not m:
            m = re.search(rf"\b(?:{nouns})\s*:\s*({_NUMBER}|no)\b", clean, re.I)
        if m:
            out[kind] = 0 if m[1].lower() == "no" else int(m[1].replace(",", ""))
    if not out and len(counts) == 1:
        m = re.search(rf"\b(?:there are|there is|count is|total is|count:|total:)\s+({_NUMBER})\b", clean, re.I)
        if not m:
            m = re.fullmatch(rf"\s*({_NUMBER})[.!]?\s*", clean)
        if m:
            out[next(iter(counts))] = int(m[1].replace(",", ""))
    return out


def _valid_box(box):
    b = box.get("bbox_px")
    return (isinstance(b, (list, tuple)) and len(b) == 4
            and all(isinstance(x, (int, float)) and math.isfinite(x) for x in b)
            and b[2] > b[0] and b[3] > b[1])


def facts(res, question):
    ans = res.get("answer") or {}
    value = ans.get("value")
    if ans.get("abstained") or ans.get("unit") != "count":
        return None
    text = ans.get("text_md") or ""
    if _integer(value):
        counts = {_kind(question, text.split("\n", 1)[0]): int(value)}
    elif isinstance(value, dict) and value and all(_integer(v) for v in value.values()):
        counts = {k: int(v) for k, v in value.items()}
    else:
        return None
    cites = res.get("citations") or []
    evidence = res.get("evidence") or {}
    scene = evidence.get("scene") or {}
    default_doc = scene.get("doc_id") or next(iter(res.get("doc_ids") or []), "")
    linked, kinds = set(), {}
    for c in cites:
        for iid in c.get("item_ids") or []:
            key = (c.get("doc_id") or default_doc, iid)
            linked.add(key)
            if c.get("item_kind"):
                kinds[key] = c["item_kind"]
    boxes = [b for b in evidence.get("boxes") or [] if _valid_box(b)]
    per_kind = {k: 0 for k in counts}
    box_keys = []
    for b in boxes:
        key = (b.get("doc_id") or default_doc, b.get("item_id"))
        box_keys.append(key)
        k = b.get("kind") or kinds.get(key) or (scene.get("item_kinds") or {}).get(b.get("item_id"))
        if len(counts) == 1:
            k = next(iter(counts))
        if k in per_kind:
            per_kind[k] += 1
    reread = None
    for s in res.get("trace") or []:
        m = re.search(r"plan map (\d+), drawing re-read (\d+)", str(s.get("detail") or ""))
        if m:
            reread = tuple(map(int, m.groups()))
    total = sum(counts.values())
    derived = any(s.get("step") == "route" and re.search(r"\barithmetic\b|\bcomparison\b", str(s.get("detail") or ""))
                  for s in res.get("trace") or [])
    problems = []
    headline = _headline_values(text, counts)
    if any(v != counts[k] for k, v in headline.items()):
        problems.append("headline")
    if len(boxes) != total or per_kind != counts:
        problems.append("boxes")
    if len(linked) != total:
        problems.append("citations")
    if len(box_keys) != len(set(box_keys)):
        problems.append("repeated boxes")
    if boxes and not set(box_keys) <= linked:
        problems.append("unlinked boxes")
    if reread and (reread[0] != reread[1] or reread[1] != total):
        problems.append("recount")
    return dict(counts=counts, total=total, boxes=len(boxes), linked=len(linked),
                per_kind=per_kind, reread=reread, problems=problems,
                derived=derived, model=res.get("route") == "index",
                cite=next((c.get("n") for c in cites if c.get("n") is not None), None))


def _summary(counts):
    return " and ".join(f"{v:,} {_word(k, v)}" for k, v in counts.items())


def _rewrite_headline(ans, f):
    old = ans.get("text_md") or ""
    head, sep, rest = old.partition("\n")
    for kind, value in f["counts"].items():
        names = _WORDS.get(kind, (kind, _word(kind, 2)))
        nouns = "|".join(re.escape(w) for w in sorted(set(names), key=len, reverse=True))
        head = re.sub(rf"\b({_NUMBER}|no)([\s*]+(?:boxed[\s*]+)?(?:{nouns})\b)",
                      lambda m: str(value) + m[2], head, count=1, flags=re.I)
        head = re.sub(rf"(\b(?:{nouns})[\s*]*:[\s*]*)({_NUMBER}|no)\b",
                      lambda m: m[1] + str(value), head, count=1, flags=re.I)
    if "headline" in f["problems"] and _headline_values(head, f["counts"]) != f["counts"]:
        markers = " ".join(dict.fromkeys(re.findall(r"\[\d+\]", head)))
        head = f"**{_summary(f['counts'])} reported.**" + (f" {markers}" if markers else "")
    coverage = f"The headline reports the source count; {f['boxes']:,} have numbered boxes."
    if coverage not in head:
        head += " " + coverage
    ans["text_md"] = head + (sep + rest if sep else "")


def _found(f):
    n, b = f["total"], f["boxes"]
    summary = _summary(f["counts"])
    if n == b and f["per_kind"] == f["counts"]:
        where = "listed in the building model, each with a numbered highlight" if f.get("model") else "marked on the drawing, each with a numbered box"
        text = f"{summary} {where}." if n else (
            f"No matching {_word(next(iter(f['counts'])), 2)} found in the available data; this does not prove none exist in the building.")
    else:
        text = f"The answer reports {summary}; {b:,} numbered boxes are shown."
        if n > b:
            text += f" {n - b:,} are not boxed yet."
        elif b > n:
            text += f" There are {b - n:,} more boxes than the reported count; the box selection needs checking."
        if len(f["counts"]) > 1:
            text += " Boxes by kind: " + _summary(f["per_kind"]) + "."
    if f["linked"] != n:
        text += f" Citations link {f['linked']:,} individual items; the headline keeps the reported source count."
    if "repeated boxes" in f["problems"]:
        text += " Some boxes repeat an item link; they are not independent findings."
    if "unlinked boxes" in f["problems"]:
        text += " Some boxes have no matching item link in the citations."
    return {"kind": "found", "title": "Found", "text": text, "cite": f["cite"], "ok": None}


def recount_step(f):
    a, b = f["reread"]
    total = f["total"]
    source = "The earlier card counted" if f.get("recount_from_card") else "The plan map originally counted"
    text = f"{source} {a}; a second, independent look counted {b}."
    if total == f["boxes"]:
        text += f" The headline reports the {total} boxed items so each reported item can be checked."
    else:
        text += f" The headline reports {total}; only {f['boxes']} have numbered boxes."
    if b > f["boxes"]:
        text += f" The second look suggests {b - f['boxes']} more than are boxed; check the drawing around the numbered boxes."
    elif b < f["boxes"]:
        text += f" The second look counted {f['boxes'] - b} fewer than are boxed; check for extra detections."
    return {"kind": "checked", "title": "Checked", "text": text, "cite": f["cite"],
            "ok": a == b == total == f["boxes"]}


def enforce(res, card, question):
    """Last count invariant, also applied to cards supplied by other routes.

    Keep answer.value as the selected source count. Replace stale Found/Checked
    statements with current evidence coverage; never fabricate missing boxes or
    silently reduce a model/source total to the number of citation groups.
    """
    f = facts(res, question)
    if f is None:
        return card
    card = card or {"steps": [], "confidence": {"label": "Estimate", "pct": 65, "reason": "Reported from the available drawing data.", "improve": None}}
    steps = card.get("steps") or []
    if f["derived"]:
        # Difference/average operands legitimately have different counts. They
        # are inputs, so never rewrite their numbers to match the final result.
        text = (f"The reported result is calculated from the cited source items, rather than counted from the boxes. "
                f"Citations link {f['linked']:,} input items; {f['boxes']:,} numbered boxes are shown.")
        if f["linked"] > f["boxes"]:
            text += f" {f['linked'] - f['boxes']:,} input items are not boxed."
        card["steps"] = [{"kind": "found", "title": "Found", "text": text, "cite": f["cite"], "ok": None},
                         *[s for s in steps if s.get("kind") != "found"]][:4]
        if f["linked"] == f["boxes"]:
            return card
        f["problems"] = ["input coverage"]
    else:
        return _enforce_count(res, card, question, f)
    return _lower_confidence(res, card)


def _lower_confidence(res, card):
    c = card.setdefault("confidence", {})
    c.update(label="Estimate", pct=None,
             reason="The reported count and the visual evidence are not fully reconciled; the coverage and any independent count are stated above.",
             improve="Check the numbered boxes and the surrounding drawing before using this count to order materials.")
    ans = res["answer"]
    raw = ans.get("confidence")
    ans["confidence"] = min(raw, 0.69) if isinstance(raw, (int, float)) else 0.69
    return card


def _enforce_count(res, card, question, f):
    steps = card.get("steps") or []
    if not f["reread"]:
        for s in steps:
            m = re.search(r"counted (\d+); (?:kept the|matches the) (\d+) boxed", s.get("text", ""))
            if s.get("kind") == "checked" and m:
                f["reread"] = (int(m[2]), int(m[1]))
                f["recount_from_card"] = True
                if f["reread"][0] != f["reread"][1] or f["reread"][1] != f["total"]:
                    f["problems"].append("recount")
                break
    for s in steps:
        text = s.get("text", "")
        values = _headline_values(text, f["counts"]) if s.get("kind") == "found" else {}
        boxed = re.search(r"(?:kept|matches the) (\d+) boxed", text)
        if any(v != f["counts"][k] for k, v in values.items()) or (boxed and int(boxed[1]) != f["boxes"]):
            f["problems"].append("stale card")
    # Count findings must use the returned boxes, not a partial first-document lookup.
    keep = [s for s in steps if s.get("kind") not in ("found", "read")]
    if f["reread"]:
        keep = [s for s in keep if s.get("kind") != "checked"]
        keep.append(recount_step(f))
    else:
        # A custom numeric Checked line may refer to a stale selection. Keep
        # qualitative checks and explicit filter arithmetic, not unsupported counts.
        keep = [s for s in keep if s.get("kind") != "checked" or not re.search(r"\b\d+\b", s.get("text", ""))]
    card["steps"] = [_found(f), *keep][:4]
    if f["problems"]:
        _lower_confidence(res, card)
        ans = res["answer"]
        if "headline" in f["problems"] or "boxes" in f["problems"]:
            _rewrite_headline(ans, f)
        elif "recount" in f["problems"]:
            # A disagreement kept on the boxed policy must be visible in the headline.
            old = ans.get("text_md") or ""
            if "boxed" not in old.split("\n", 1)[0].lower():
                ans["text_md"] = re.sub(rf"(\*\*)({_NUMBER})\s+", r"\1\2 boxed ", old, count=1)
    return card
