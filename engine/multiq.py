"""F-MULTIQ: compound questions. One message with several questions ("what is this file how many walls does it have which of these
two files has more windows?") is split deterministically, every part is answered by the normal pipeline, and the results are merged
into one answer (one bullet per part, citations renumbered). Single questions are never touched."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

_START = r"(?:what|how\s+many|how\s+much|which|where|who|when|why)"
# words after which a question word is part of the same clause ("tell me what", "bigger than what", "which of")
_GLUE = {"me", "us", "know", "see", "show", "tell", "ask", "explain", "of", "in", "on", "for", "to", "about", "than", "as", "by",
         "with", "if", "whether", "that", "from", "at", "into", "is", "are", "was", "were", "the", "a", "an", "and", "or", "no",
         "not", "my", "our", "your", "their", "its", "this", "that", "these", "those", "any", "each", "every", "per", "between",
         "than", "list", "name", "count", "find", "give", "get", "check", "determine", "describe", "say", "understand"}
_WH_NEXT = {"which": {"of", "one", "file", "files", "document", "documents", "doc", "docs", "drawing", "drawings", "floor",
                      "floors", "plan", "plans", "room", "rooms", "storey", "story", "level", "model", "models", "sheet"}}
_OPENS = re.compile(r"^\W*(?:what|how|which|where|who|when|why|is|are|does|do|can|could|should|will|was|were|has|have)\b", re.I)
_CMP = re.compile(r"\bwhich\s+(?:one\s+)?(?:of\s+)?(?:these|the|those|my|both)?\s*(?:\w+\s+)?(?:files?|documents?|docs?|drawings?|plans?|"
                  r"floor\s*plans?|models?|sheets?)\s+(?:has|have|got|contains?|shows?)\s+(?:the\s+)?(more|most|fewer|fewest|less|least)\s+"
                  r"(.+?)\s*\??\s*$", re.I)


def split(question: str) -> list[str]:
    """Return the sub-questions of a compound question, or [] when it is a single question."""
    q = re.sub(r"\s+", " ", (question or "").strip())
    if len(q.split()) < 5:
        return []
    segs: list[str] = []
    chunks: list[str] = []
    for c in re.split(r"(?<=\?)\s+(?=\S)", q):               # '?' boundaries, only where a new question starts
        if chunks and _OPENS.match(c) and _OPENS.match(chunks[-1]):
            chunks.append(c)
        elif chunks:
            chunks[-1] += " " + c
        else:
            chunks.append(c)
    for chunk in chunks:
        segs.extend(_runon(chunk) if _OPENS.match(chunk) else [chunk])
    segs = [s.strip(" ,;") for s in segs if len(re.findall(r"\w+", s)) >= 2]
    segs = [re.sub(r"\s+(?:and|then|also|plus)\s*$", "", s, flags=re.I).strip(" ,;") for s in segs]
    if len(segs) < 2 or any(re.search(r"\b(?:of each|each of|them|those|the same|their)\b", x, re.I) for x in segs[1:]):
        return []                                   # a later part leans on the earlier answer: keep it whole
    return [s if s.endswith("?") else s + "?" for s in segs]


def _runon(text: str) -> list[str]:
    words = [(m.group(), m.start()) for m in re.finditer(r"\S+", text)]
    cuts: list[int] = []
    for i, (w, pos) in enumerate(words):
        if i < 2:
            continue
        rest = text[pos:]
        m = re.match(_START + r"\b", rest, re.I)
        if not m:
            continue
        prev = re.sub(r"\W", "", words[i - 1][0]).lower()
        # "and what ..." / "and how many ..." : the 'and' is the separator, look one word further back
        if prev in ("and", "then", "also", "plus") and i >= 3:
            prev = re.sub(r"\W", "", words[i - 2][0]).lower()
            if prev in ("of", "than", "as", "between", "the", "a", "an"):
                continue
        elif prev in _GLUE:
            continue
        kw = m.group().lower().split()[0]
        if kw in _WH_NEXT:
            nxt = re.sub(r"\W", "", words[i + 1][0]).lower() if i + 1 < len(words) else ""
            if nxt not in _WH_NEXT[kw]:
                continue
        if i < 3:                                              # need a real first clause
            continue
        cuts.append(pos)
    if not cuts:
        return [text]
    out, last = [], 0
    for c in cuts:
        out.append(text[last:c])
        last = c
    out.append(text[last:])
    return out


def comparison(question: str):
    m = _CMP.search(question or "")
    if not m:
        return None
    return m.group(1).lower(), m.group(2).strip(" ?.")


def _title(doc_id: str, root: Path) -> str:
    try:
        return json.loads((root / doc_id / "doc.json").read_text()).get("title") or doc_id
    except (OSError, ValueError):
        return doc_id


def _renumber(text: str, off: int) -> str:
    return re.sub(r"\[(\d+)\]", lambda m: f"[{int(m.group(1)) + off}]", text or "")


def _cmp_part(part: str, doc_ids, cmp, answer_fn, root: Path) -> dict | None:
    """'which of these files has more windows': count the thing in each document, compare."""
    if len(doc_ids) < 2:
        return None
    word, thing = cmp
    thing = re.sub(r"\s+(?:than|in|on)\b.*$", "", thing, flags=re.I).strip()
    subs = [(d, answer_fn(f"how many {thing} are there?", [d])) for d in doc_ids]
    vals = []
    for d, r in subs:
        a = r["answer"]
        vals.append(a.get("value") if not a.get("abstained") and isinstance(a.get("value"), (int, float)) else None)
    names = [_title(d, root) for d in doc_ids]
    lines = [f"- {n}: {int(v) if v is not None and float(v).is_integer() else v if v is not None else 'not determined'}" for n, v in zip(names, vals)]
    if any(v is None for v in vals):
        head = f"**I could not compare {thing} across the files, because at least one count is missing.**"
    else:
        best = max(vals) if word in ("more", "most") else min(vals)
        winners = [n for n, v in zip(names, vals) if v == best]
        head = (f"**{winners[0]} has {'more' if word in ('more', 'most') else 'fewer'} {thing}** ({int(best)})." if len(winners) == 1
                else f"**The files have the same number of {thing}** ({int(best)} each).")
    res = copy.deepcopy(next((r for _, r in subs if not r["answer"].get("abstained")), subs[0][1]))
    cits, boxes, off = [], [], 0
    text_lines = []
    for (d, r), line in zip(subs, lines):
        text_lines.append(_renumber(line, off) + ("".join(f" [{c['n'] + off}]" for c in r.get("citations") or [])))
        for c in r.get("citations") or []:
            cits.append({**c, "n": c["n"] + off})
        boxes.extend(((r.get("evidence") or {}).get("boxes")) or [])
        off += len(r.get("citations") or [])
    res["answer"] = {"text_md": head + "\n" + "\n".join(text_lines), "value": None if any(v is None for v in vals) else best,
                     "unit": "count", "confidence": min([r["answer"].get("confidence", 0) or 0 for _, r in subs]),
                     "abstained": any(v is None for v in vals)}
    res["citations"] = cits
    res["question"] = part
    res["doc_ids"] = list(doc_ids)
    res["route"] = "multidoc-compare"
    return res


def _perdoc_part(part: str, doc_ids, answer_fn, root: Path) -> dict:
    """A part that says 'this file' / 'it' with several documents attached: answer it for each document, one labelled block each."""
    subs = [(d, answer_fn(part, [d])) for d in doc_ids]
    live = [r for _, r in subs if not r["answer"].get("abstained")]
    res = copy.deepcopy(next((r for r in live if (r.get("evidence") or {}).get("boxes")), live[0] if live else subs[0][1]))
    cits, blocks, off = [], [], 0
    for d, r in subs:
        t = _renumber((r["answer"].get("text_md") or "").strip(), off)
        ti = _title(d, root)
        blocks.append(t if t.startswith(f"**{ti}**") else f"**{ti}**: {t}")
        for c in r.get("citations") or []:
            cits.append({**c, "n": c["n"] + off})
        off += max([c["n"] for c in r.get("citations") or []] or [0])
    confs = [r["answer"].get("confidence") or 0 for r in live]
    res["answer"] = {"text_md": "\n\n".join(blocks), "value": None, "unit": None, "confidence": min(confs) if confs else 0.0,
                     "abstained": not live}
    res["citations"] = cits
    res["doc_ids"] = list(doc_ids)
    res["question"] = part
    res["trace"] = [s_ for _, r in subs for s_ in r.get("trace") or []]
    return res


def run(question: str, doc_ids: list[str], answer_fn, root: Path):
    """Return a merged answer for a compound question, or None when the question is not compound."""
    parts = split(question)
    cmp_whole = comparison(question)
    if not parts and not (cmp_whole and len(doc_ids) >= 2):
        return None
    if not parts:
        parts = [question]
    results = []
    for p in parts:
        cmp = comparison(p)
        if cmp and len(doc_ids) >= 2:
            r = _cmp_part(p, doc_ids, cmp, answer_fn, root)
            results.append(r if r is not None else answer_fn(p, doc_ids))
        elif len(doc_ids) >= 2 and len(parts) >= 2:
            results.append(_perdoc_part(p, doc_ids, answer_fn, root))
        else:
            results.append(answer_fn(p, doc_ids))
    if len(results) == 1:
        res = results[0]
        res["question"] = question
        return res
    return merge(question, doc_ids, parts, results)


def merge(question, doc_ids, parts, results) -> dict:
    main_i = next((i for i, r in enumerate(results) if not r["answer"].get("abstained") and (r.get("evidence") or {}).get("boxes")),
                  next((i for i, r in enumerate(results) if not r["answer"].get("abstained")), 0))
    res = copy.deepcopy(results[main_i])
    cits, lines, off, trace, calls, usd = [], [], 0, [], [], 0.0
    for p, r in zip(parts, results):
        a = r["answer"]
        t = _renumber((a.get("text_md") or "").strip(), off)
        lines.append(f"**{p.rstrip('?').strip().capitalize()}?**\n{t}")
        for c in r.get("citations") or []:
            cits.append({**c, "n": c["n"] + off})
        off += max([c["n"] for c in r.get("citations") or []] or [0])
        trace.extend(r.get("trace") or [])
        calls.extend((r.get("cost") or {}).get("calls") or [])
        usd += (r.get("cost") or {}).get("usd_total", 0) or 0
    ev = copy.deepcopy(res.get("evidence") or {})   # box labels number the items, not the citations: kept as they are
    res["answer"] = {**res["answer"], "text_md": "\n\n".join(lines),
                     "confidence": min([(r["answer"].get("confidence") or 0) for r in results if not r["answer"].get("abstained")] or [0.0]),
                     "abstained": all(r["answer"].get("abstained") for r in results)}
    res["citations"] = cits
    res["evidence"] = ev
    res["question"] = question
    res["doc_ids"] = list(doc_ids)
    res["route"] = "multi"
    res["trace"] = trace
    res["cost"] = {"usd_total": round(usd, 6), "calls": calls}
    rs = res.get("reasoning") or {}
    rs["parts"] = [{"question": p, "answer": (r["answer"].get("text_md") or "").split("\n")[0], "route": r.get("route"),
                    "confidence": r["answer"].get("confidence"), "abstained": bool(r["answer"].get("abstained"))}
                   for p, r in zip(parts, results)]
    res["reasoning"] = rs
    return res
