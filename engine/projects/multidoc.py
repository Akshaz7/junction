"""Plain-code answers over SEVERAL documents of one project (no model, no cost).

  answer(question, doc_ids, root, t0) -> answer object | None     (None = not a multi-document question: normal path runs)

Shapes (count or room area, per kind: rooms / doors / windows):
  total      "how many doors in total across both models", "total floor area across all drawings", "... on level 2 across the set"
  per level  "doors per level across the set", "rooms on each floor"
  extreme    "which floor has the most rooms", "which level has the fewest windows"
  compare    "compare level 1 and level 2", "doors on the ground floor versus the first floor"

The numbers come from engine.projects.combine: the same building in two formats is counted once (the model is the source,
the sheet is a cross-check), different buildings are added. Every number cites the items it came from, numbered across
documents, and the answer carries its own "How we know" card.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from engine.projects.combine import KINDS, PLURAL, Combined, combine, row_label, short_title, value
from engine.projects.roles import level_ordinal

MORE = re.compile(r"\b(most|greatest|largest|biggest|highest|maximum|max|more)\b", re.I)
LESS = re.compile(r"\b(fewest|least|smallest|lowest|minimum|min|fewer|less)\b", re.I)
AREAQ = re.compile(r"\b(area|areas|m2|m²|square met(?:er|re)s|sq\.? ?m|floor space)\b", re.I)
AGG = re.compile(r"\b(across|both|combined|altogether|in total|overall|in all|all together|total)\b", re.I)
PER = re.compile(r"\b(?:per|on each|in each|for each|by|every)\s+(?:floor|level|storey|story)\b|\beach\s+(?:floor|level|storey|story)\b", re.I)
WHICH = re.compile(r"\b(?:which|what)\s+(?:floor|level|storey|story)\b", re.I)
AGREE = re.compile(r"\b(?:same (?:number|count|amount|quantity)|as many\b.*\bas\b|equal|match(?:es)?|agree|consistent|tally|mismatch|add up)\b", re.I)
COMPARE = re.compile(r"\b(compare|comparison|versus|vs\.?|difference|differ|against)\b", re.I)
LEVEL_PHRASE = re.compile(
    r"\b(?:(?:ground|basement|cellar|first|second|third|fourth|fifth|sixth|top|upper|attic|roof|\d+(?:st|nd|rd|th)?\.?)\s*(?:floor|level|storey|story|og|obergeschoss|kerros)"
    r"|(?:floor|level|storey|story)\s*-?\d+|erdgeschoss|dachgeschoss|keller\w*)\b", re.I)
KIND_WORDS = r"doors?|windows?|rooms?|spaces?"
KNOWN = set("""how many number of the are is there in on at total all across both combined altogether overall each per every by which what has have had
most least fewest fewer more less greatest largest biggest highest lowest smallest maximum minimum floor floors level levels storey storeys story stories
compare comparison versus vs and with between than against selected these those document documents drawing drawings model models file files sheet sheets plan plans
set project building buildings a an do does show me give count list table area areas m2 square metres meters sq m door doors window windows room rooms space spaces
difference differ different from for to us our please can you tell whole entire set together them it this that everything of these""".split())


def _fold(s: str) -> str:
    from engine.solvers.filters import fold
    return fold(s or "")


def _kind(q: str):
    from engine.router.parser import _kind as k
    kind = k(q.lower())
    return kind if kind in KINDS else None


def _levels_in(q: str, c: Combined, one_building: bool = False) -> tuple[list, list, str]:
    """Rows the question names. Returns (rows, unknown_phrases, question text with the level words removed)."""
    ql = _fold(q)
    rows, unknown = [], []
    rest = q
    for r in sorted(c.rows, key=lambda r: -len(r.name)):
        n = _fold(r.name)
        if n and len(n) > 2 and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", ql):
            if r not in rows:
                rows.append(r)
            rest = re.sub(re.escape(r.name), " ", rest, flags=re.I)
    for m in LEVEL_PHRASE.finditer(rest):
        want = level_ordinal(m.group(0))
        hit = [r for r in c.rows if want is not None and r.ordinal == want]
        if one_building and len(hit) > 1:   # comparing two levels of ONE building: the biggest model decides
            lead = max(c.groups, key=lambda g: len(g.storeys)).key
            hit = [r for r in hit if r.group == lead] or hit[:1]
        if hit:
            for r in hit:
                if r not in rows:
                    rows.append(r)
        else:
            unknown.append(m.group(0).strip())
    rest = LEVEL_PHRASE.sub(" ", rest)
    return rows, unknown, rest


def _plain(rest: str) -> bool:
    """True when nothing but whitelisted words (and numbers) is left: no room names, filters or other conditions."""
    for w in re.findall(r"[^\W\d_]+", rest.lower()):
        if w not in KNOWN:
            return False
    return True


def _items_of(info, kind, ids):
    ids = set(ids)
    return [i for i in info.doc.items if i.item_id in ids and i.kind == kind]


def _gather(c: Combined, picks: list) -> tuple[dict, dict]:
    """picks: [(row, kind)] -> per source doc the Items to cite, and per source doc the summed value."""
    items: dict[str, list] = {}
    per_doc: dict[str, float] = {}
    for r, k in picks:
        did = r.chosen.get(k)
        if did is None:
            continue
        st = r.docs[did][k]
        per_doc[did] = per_doc.get(did, 0) + st["n"]
        items.setdefault(did, []).extend(_items_of(c.infos[did], k, st["ids"]))
    return items, per_doc


def _cite(c: Combined, items: dict) -> tuple[list, list, dict, str | None]:
    """Evidence for every source doc, citations numbered across documents. Scene follows the document with the most items."""
    from engine.solvers.solve import _evidence
    boxes, cites, marks = [], [], {}
    primary = max(items, key=lambda d: len(items[d])) if items else None
    scene = None
    for did, its in items.items():
        if not its:
            continue
        b, ct, sc = _evidence(c.infos[did].doc, its)
        base = len(cites)
        for x in ct:
            cites.append({**x, "n": base + x["n"], "doc_id": did})
        marks[did] = "".join(f"[{x['n']}]" for x in cites[base:])
        if did == primary:
            scene = sc
            boxes = b
    return boxes, cites, marks, scene


def _missing(c: Combined, q: str, unknown: list, doc_ids, t0):
    from engine.solvers.solve import _answer_obj
    names = ", ".join(dict.fromkeys(r.name for r in c.rows))
    text = f"I cannot find {', '.join(unknown)} in the selected documents. Levels present: {names}."
    res = _answer_obj(q, list(doc_ids), text, None, None, 0.9, False, [], [],
                      {"doc_id": doc_ids[0], "highlight_item_ids": [], "camera_target_item_id": None},
                      [{"step": "route", "detail": "multi-document level lookup: level not present", "ms": 0, "model": None, "cost_usd": 0}], "index", t0)
    res["reasoning"] = {"steps": [{"kind": "found", "title": "Checked", "text": f"{len(c.rows)} levels in the selected documents, none matches {', '.join(unknown)}", "cite": None, "ok": False}],
                        "confidence": {"label": "Verified", "pct": 95, "reason": "Checked against the levels each document actually has.", "improve": None}}
    return res


def _unit(area: bool) -> str:
    return "m2" if area else "count"


def _confidence(c: Combined, dids) -> tuple[str, int, str, str | None]:
    kinds = {c.infos[d].role for d in dids}
    if kinds <= {"model"}:
        return "Verified", 97, "Read directly from the building models' own data. Nothing is estimated.", None
    return "Estimate", 78, "Counted on drawings, so some items may be missed or merged.", \
        "Upload the building model (IFC) of the same building to make these numbers exact."


def _build(c: Combined, question: str, text: str, value_, area: bool, picks: list, doc_ids, t0, trace_text: str,
           found: str, extra_steps=None, ok_cross=None, gather=None):
    from engine.solvers.solve import _answer_obj
    items, per_doc = gather if gather is not None else _gather(c, picks)
    boxes, cites, marks, scene = _cite(c, items)
    if scene is None:
        scene = {"doc_id": next(iter(items), doc_ids[0]), "highlight_item_ids": [], "camera_target_item_id": None}
    for i, d in enumerate(per_doc):
        text = text.replace("{m_%d}" % i, marks.get(d, ""))
    text = text.replace("{marks}", "".join(marks.values()))
    label, pct, reason, improve = _confidence(c, list(per_doc))
    first = cites[0]["n"] if cites else None
    steps = [{"kind": "found", "title": "Found", "text": found, "cite": first, "ok": None}]
    steps += extra_steps or []
    res = _answer_obj(question, list(doc_ids), text, value_, _unit(area), 1.0 if label == "Verified" else 0.8, False, boxes, cites, scene,
                      [{"step": "route", "detail": trace_text, "ms": 0, "model": None, "cost_usd": 0}], "index", t0)
    res["reasoning"] = {"steps": steps, "confidence": {"label": label, "pct": pct, "reason": reason, "improve": improve}}
    from engine.method_multidoc import capture
    return capture(res, c, picks, area, trace_text)


def _fmt(v, area):
    return f"{v:,.1f}" if area else f"{int(round(v))}"


def _cross_checks(c: Combined, kind: str, rows: list) -> list:
    """For the chosen rows: a note per kind about sources that were NOT used (same building in another format)."""
    notes = []
    for r in rows:
        used = r.chosen.get(kind)
        if used is None:
            continue
        for did, st in r.docs.items():
            if did == used:
                continue
            info = c.infos[did]
            ids, used_ids = st[kind].get("ids") or [], r.docs[used][kind].get("ids") or []
            if ids and set(map(str, ids)) == set(map(str, used_ids)):
                continue    # identical element ids (an MEP sheet's model built on the architect plan): a copy, not a check
            if st[kind]["n"] or info.role == "model":
                notes.append((did, used, r, st[kind]["n"], r.docs[used][kind]["n"]))
    return notes


def _agree(c: Combined, q: str, kind: str, rows: list, doc_ids, t0):
    """'Does the plan show the same number of doors as the model?' -> every side counted and cited, then match or mismatch."""
    cands = rows or [r for r in c.rows if sum(1 for d, st in r.docs.items() if st[kind]["n"] or c.infos[d].role == "model") >= 2]
    sides = []
    for r in cands:
        docs = [(d, st[kind]) for d, st in r.docs.items() if st[kind]["n"] or c.infos[d].role == "model"]
        if len(docs) >= 2:
            sides.append((r, sorted(docs, key=lambda x: (c.infos[x[0]].role != "model", x[0]))))
    if not sides:
        return None
    what = PLURAL[kind]
    items: dict[str, list] = {}
    per_doc: dict[str, float] = {}
    lines, steps, all_ok = [], [], True
    for r, docs in sides:
        counts = []
        for d, st in docs:
            items.setdefault(d, []).extend(_items_of(c.infos[d], kind, st["ids"]))
            per_doc[d] = per_doc.get(d, 0) + st["n"]
            counts.append(st["n"])
        ok = len(set(counts)) == 1
        all_ok = all_ok and ok
        idx = {d: i for i, d in enumerate(list(per_doc))}
        who = []
        for d, st in docs:
            info = c.infos[d]
            lab = "the 3D model" if info.role == "model" else ("the drawing" if sum(1 for x, _ in docs if c.infos[x].role != "model") == 1 else "the sheet")
            who.append(f"{lab} ({short_title(info.title or d, 50)}) has {st['n']} {what if st['n'] != 1 else what[:-1]} {{m_%d}}" % idx[d])
        head = "They match" if ok else "They do not match"
        diff = ""
        if not ok and len(docs) == 2:
            na = {(i.name or "").strip() for i in _items_of(c.infos[docs[0][0]], kind, docs[0][1]["ids"])}
            nb = {(i.name or "").strip() for i in _items_of(c.infos[docs[1][0]], kind, docs[1][1]["ids"])}
            if "" not in na | nb and (na & nb):   # names only help when the two sources share a naming scheme
                only_a, only_b = sorted(na - nb), sorted(nb - na)
                if only_a or only_b:
                    la, lb = (short_title(c.infos[docs[0][0]].title or docs[0][0], 40), short_title(c.infos[docs[1][0]].title or docs[1][0], 40))
                    diff = (f" Only in {la}: {', '.join(only_a[:12]) or 'none'}; only in {lb}: {', '.join(only_b[:12]) or 'none'}.")
            diff = diff or f" The difference is {abs(counts[0] - counts[1])}."
        lines.append(f"On {row_label(c, r)}: " + " and ".join(who) + f". {head}.{diff}")
        steps.append({"kind": "check", "title": "Compared", "ok": ok, "cite": None,
                      "text": f"{row_label(c, r)}: " + " vs ".join(f"{n}" for n in counts) + (" match" if ok else " differ")})
    text = ("**Yes, the counts match.** " if all_ok else "**No, the counts differ.** ") + " ".join(lines)
    picks = [(r, kind) for r, _ in sides]
    first = sides[0][1][0]
    return _build(c, q, text, int(sides[0][1][0][1]["n"]), False, picks, doc_ids, t0, f"multi-document comparison / {kind} / count -> each source counted and cited, no model",
                  f"{what.capitalize()} counted in {len(per_doc)} documents for {len(sides)} {'level' if len(sides) == 1 else 'levels'}", steps, gather=(items, per_doc))


def answer(question: str, doc_ids, root, t0=None):
    t0 = t0 or time.perf_counter()
    doc_ids = list(dict.fromkeys(doc_ids or []))
    if len(doc_ids) < 2:
        return None
    q = question.strip()
    if not re.search(r"\b(how many|number of|count|total|which|what|compare|comparison|versus|vs\.?|per|each|area|difference)\b", q, re.I):
        return None
    area = bool(AREAQ.search(q))
    kind = _kind(q) or ("room" if area else None)
    if (kind is None and not COMPARE.search(q)) or (area and kind not in (None, "room")):
        return None
    shape = ("agree" if (AGREE.search(q) and kind and not area) else "compare" if COMPARE.search(q) else "which" if WHICH.search(q) else "per" if PER.search(q) else
             "total" if (AGG.search(q) or re.search(r"\bhow many\b|\bnumber of\b", q, re.I)) else None)
    if shape is None:
        return None
    try:
        c = combine(doc_ids, Path(root))
    except Exception:  # noqa: BLE001  never break the answer path
        return None
    if not c.rows or (kind and not any(r.chosen.get(kind) for r in c.rows)):
        return None
    rows, unknown, rest = _levels_in(q, c, one_building=shape in ("compare", "which", "per"))
    if shape == "agree":
        return _agree(c, q, kind, rows, doc_ids, t0)
    if not _plain(rest):
        return None
    if kind is None:
        return _compare_all(c, q, rows, unknown, doc_ids, t0)
    what = PLURAL[kind]
    unit_word = "m²" if area else what
    key = "area" if area else "n"
    have = [r for r in c.rows if r.chosen.get(kind) and value(r, kind, key) is not None]
    if not have:
        return None

    def noun(n):
        if area:
            return "m²"
        return what if n != 1 else what[:-1]

    if unknown and shape in ("total", "compare"):
        return _missing(c, q, unknown, doc_ids, t0)

    if shape == "total":
        use = rows or have
        use = [r for r in use if r in have]
        if not use:
            return None
        vals = [(r, value(r, kind, key)) for r in use]
        total = sum(v for _, v in vals)
        total = round(total, 2) if area else int(total)
        picks = [(r, kind) for r in use]
        _, per_doc = _gather(c, picks)
        parts = list(per_doc.items())
        # per-source sums (areas, not counts, when asked)
        if area:
            per_doc = {}
            for r in use:
                per_doc[r.chosen[kind]] = per_doc.get(r.chosen[kind], 0) + value(r, kind, "area")
            parts = list(per_doc.items())
        lines = "; ".join(f"{short_title(c.infos[d].title or d, 60)}: {_fmt(v, area)} {{m_{i}}}" for i, (d, v) in enumerate(parts))
        scope = (" on " + " and ".join(dict.fromkeys(row_label(c, r) for r in use))) if rows else ""
        head = (f"**{_fmt(total, area)} m² of room area**{scope} in total" if area else f"**{total} {noun(total)}**{scope} in total")
        src = f" across the {len(parts)} selected documents" if len(parts) > 1 else f" from {short_title(c.infos[parts[0][0]].title, 60)}"
        text = f"{head}{src}. {lines}." if len(parts) > 1 else f"{head}{src}. {{m_0}}"
        steps, ok = [], None
        if len(parts) > 1:
            sums = " + ".join(_fmt(v, area) for _, v in parts)
            steps.append({"kind": "added", "title": "Added", "text": f"Added {sums} from {len(parts)} drawings", "cite": None, "ok": None})
        notes = _cross_checks(c, kind, use)
        if notes:
            by_pair: dict = {}
            for did, used, r, n_other, n_used in notes:
                p = by_pair.setdefault((did, used), [0, 0])
                p[0] += n_other
                p[1] += n_used
            for (did, used), (n_other, n_used) in by_pair.items():
                other, src_info = c.infos[did], c.infos[used]
                agree = n_other == n_used
                tail = f"it also shows {n_other}, which matches" if agree else f"it shows {n_other} instead of {n_used}, which differs"
                lead = "Used the model" if src_info.role == "model" else f"Used {short_title(src_info.title, 50)}"
                steps.append({"kind": "check", "title": "Cross-check", "ok": agree, "cite": None,
                              "text": f"{lead}; {short_title(other.title or did, 50)} is a cross-check: {tail}"})
        if c.unplaced:
            names = ", ".join(short_title(c.infos[d].title or d, 40) for d in c.unplaced)
            text += f" Not added, because the level is not stated: {names}."
            steps.append({"kind": "note", "title": "Not added", "cite": None, "ok": None,
                          "text": f"{len(c.unplaced)} drawing{'s' if len(c.unplaced) != 1 else ''} without a stated level: set the level on the project page to include {'them' if len(c.unplaced) != 1 else 'it'}"})
        for d_, _v in parts:
            ex = (getattr(c.infos[d_].doc, "meta", None) or {}).get("planmap_extra", {}).get(kind)
            if ex:
                text += (f" {ex['extra'] + ex['model']} on the plan of {short_title(c.infos[d_].title, 50)}; {ex['extra']} "
                         f"{'has' if ex['extra'] == 1 else 'have'} no drawn wall, so the 3D model shows {ex['model']}.")
        if notes:
            seen_pairs = {}
            for did, used, r, n_other, n_used in notes:
                p_ = seen_pairs.setdefault(did, [0, 0])
                p_[0] += n_other
                p_[1] += n_used
            lvl = (" on " + " and ".join(dict.fromkeys(row_label(c, r) for r in use))) if len(use) <= 2 else ""
            shows = "; ".join(f"{short_title(c.infos[d].title or d, 50)} shows {a} {noun(a)}{lvl}" + (" (matches)" if a == b else f" (differs from {b})") for d, (a, b) in seen_pairs.items())
            text += f" The same building also appears in other selected documents, so they were not added again: as a cross-check, {shows}."
        found = f"{_fmt(total, area)} {unit_word} on {len(use)} {'level' if len(use) == 1 else 'levels'}, from {len(parts)} {'source' if len(parts) == 1 else 'sources'}"
        return _build(c, q, text, total, area, picks, doc_ids, t0, f"multi-document total / {kind} / {'area' if area else 'count'} -> combine, no model",
                      found, steps)

    # level based shapes
    pool = rows if (shape == "compare" and len(rows) >= 2) else have
    if shape == "compare" and len(rows) < 2:
        return None
    vals = {id(r): value(r, kind, key) for r in pool}
    if shape == "which" and not (MORE.search(q) or LESS.search(q)):
        return None
    labelled = [(row_label(c, r), r) for r in pool]
    picks = [(r, kind) for r in pool]
    parts = ", ".join(f"{lb} {_fmt(vals[id(r)], area)}" + (" m²" if area else "") for lb, r in labelled)
    sources = len({r.chosen[kind] for r in pool})
    found = f"{what.capitalize() if not area else 'Room area'} read for {len(pool)} levels from {sources} {'source' if sources == 1 else 'sources'}"

    if shape == "which":
        least = LESS.search(q) and not MORE.search(q)
        best = (min if least else max)(vals.values())
        ties = [(lb, r) for lb, r in labelled if vals[id(r)] == best]
        word = "fewest" if least else "most"
        head = (f"**{ties[0][0]}** has the {word} {unit_word if not area else 'room area'}: **{_fmt(best, area)}{' m²' if area else ''}**."
                if len(ties) == 1 else
                f"**{' and '.join(lb for lb, _ in ties)}** tie for the {word} {unit_word if not area else 'room area'}: **{_fmt(best, area)}{' m²' if area else ''}** each.")
        text = f"{head} Per level: {parts}. {{marks}}"
        win = [(r, kind) for _, r in ties]
        res = _build(c, q, text, best, area, win, doc_ids, t0, f"multi-document level ranking / {kind} -> combine, no model", found)
        return res

    # per level table / compare
    col = "Room area (m²)" if area else what.capitalize()
    body = "\n".join(f"| {lb} | {_fmt(vals[id(r)], area)} | {short_title(c.infos[r.chosen[kind]].title or r.chosen[kind], 36)} |" for lb, r in labelled)
    tot = sum(vals.values())
    if shape == "compare":
        a, b = labelled[0], labelled[1]
        d = vals[id(a[1])] - vals[id(b[1])]
        lead = (f"**{a[0]}** and **{b[0]}** have the same {unit_word if not area else 'room area'}: **{_fmt(vals[id(a[1])], area)}**."
                if d == 0 else
                f"**{(a if d > 0 else b)[0]}** has more {unit_word if not area else 'room area'}: **{_fmt(max(vals[id(a[1])], vals[id(b[1])]), area)}** against **{_fmt(min(vals[id(a[1])], vals[id(b[1])]), area)}**, a difference of **{_fmt(abs(d), area)}**.")
        labelled = labelled[:2]
        picks = [(r, kind) for _, r in labelled]
        body = "\n".join(f"| {lb} | {_fmt(vals[id(r)], area)} | {short_title(c.infos[r.chosen[kind]].title or r.chosen[kind], 36)} |" for lb, r in labelled)
        text = f"{lead}\n\n| Level | {col} | From |\n|---|---|---|\n{body}\n\n{{marks}}"
        return _build(c, q, text, d, area, picks, doc_ids, t0, f"multi-document level comparison / {kind} -> combine, no model", found)
    text = (f"{what.capitalize() if not area else 'Room area'} per level: {parts}.\n\n| Level | {col} | From |\n|---|---|---|\n{body}\n"
            f"| **Total** | {_fmt(tot, area)} | |\n\n{{marks}}")
    return _build(c, q, text, round(tot, 2) if area else int(tot), area, picks, doc_ids, t0,
                  f"multi-document per-level table / {kind} -> combine, no model", found)


def _compare_all(c: Combined, q: str, rows: list, unknown: list, doc_ids, t0):
    """'compare level 1 and level 2' with no thing named: rooms, doors, windows and room area side by side."""
    if unknown or len(rows) < 2:
        if not unknown:
            return None
        return _missing(c, q, unknown, doc_ids, t0)
    a, b = rows[:2]
    la, lb = row_label(c, a), row_label(c, b)

    def cell(r, k, key="n"):
        v = value(r, k, key)
        return "not read" if v is None else (f"{v:,.1f}" if key == "area" else str(int(v)))
    lines = [f"| Rooms | {cell(a, 'room')} | {cell(b, 'room')} |", f"| Doors | {cell(a, 'door')} | {cell(b, 'door')} |",
             f"| Windows | {cell(a, 'window')} | {cell(b, 'window')} |", f"| Room area (m²) | {cell(a, 'room', 'area')} | {cell(b, 'room', 'area')} |"]
    diffs = {}
    for k in KINDS:
        va, vb = value(a, k), value(b, k)
        if va is not None and vb is not None:
            diffs[PLURAL[k]] = va - vb
    bits = [f"{PLURAL[k]} {('+' if diffs[PLURAL[k]] > 0 else '')}{diffs[PLURAL[k]]}" for k in KINDS if PLURAL[k] in diffs and diffs[PLURAL[k]] != 0]
    lead = f"**{la}** against **{lb}**: " + (", ".join(bits) + f" (first minus second)." if bits else "the same rooms, doors and windows.")
    text = f"{lead}\n\n| | {la} | {lb} |\n|---|---|---|\n" + "\n".join(lines) + "\n\n{marks}"
    picks = [(r, k) for r in (a, b) for k in KINDS]
    return _build(c, q, text, diffs or None, False, picks, doc_ids, t0, "multi-document level comparison / rooms, doors, windows -> combine, no model",
                  f"Rooms, doors and windows read for {la} and {lb}")
