"""E-79 part: the 'Found' / 'Read' step: which elements or printed text the answer rests on."""
from __future__ import annotations

import re

from engine.reasoning import KIND_WORD, _fmt, _name, _shoelace  # noqa: F401

MAX = 110


def _plural(word: str, n: int) -> str:
    if n == 1:
        return word
    return word + ("es" if word.endswith(("s", "x")) else "s")


def _source_phrase(ctx: dict) -> tuple[str, str]:
    """(preposition phrase for elements, noun for text) in natural words: IFC model, CAD drawing, PDF, scanned image."""
    doc, sc = ctx.get("doc"), ctx.get("sc") or {}
    method = str(sc.get("method") or "")
    srcs = {i.source for i in (doc.items if doc else [])}
    if doc is None:
        return "in the cited source", "the cited source"
    if ctx.get("is_ifc"):
        return "in the building model (IFC)", "the building model"
    if ctx.get("from_cad") or "dxf" in srcs:
        return "in the CAD drawing (DXF)", "the CAD drawing"
    if "pdf" in method or "pdf" in srcs:
        return "in the PDF drawing", "the PDF"
    return "on the scanned drawing", "the scanned drawing"


def _real_name(it) -> str:
    nm = _name(it)
    if (not nm or nm.isdigit() or len(nm) > 28 or re.fullmatch(r"[^\W\d_]{1,6}[-_ ]?\d{1,5}", nm)
            or (re.fullmatch(r"[A-Za-z0-9_$]{16,}", nm) and re.search(r"\d", nm)) or nm == it.item_id
            or re.fullmatch(r"\[[^]]{1,5}\]\w+", nm)):
        return ""   # "Tür-016", "D12": a tag, not a name a reader recognises
    return nm


def _clip(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _docs_suffix(ctx: dict) -> str:
    ids = {c.get("doc_id") for c in ctx["cites"] if c.get("doc_id")} | set(ctx["res"].get("doc_ids") or [])
    return f", across {len(ids)} sources" if len(ids) > 1 else ""


def _storeys(cited) -> str:
    st = sorted({it.storey for it in cited if it.storey})
    if not st:
        return ""
    return f" on {st[0]}" if len(st) == 1 else (f" on {', '.join(st[:3])}" if len(st) <= 3 else f" on {len(st)} storeys")


def _examples(items, limit=3) -> str:
    seen = []
    for it in items:
        nm = _real_name(it)
        if nm and nm not in seen:
            seen.append(nm)
        if len(seen) == limit:
            break
    return ", ".join(seen)


def _found_text(ctx: dict) -> str:
    cited = ctx["cited"]
    where, _ = _source_phrase(ctx)
    suffix = _docs_suffix(ctx)
    st = _storeys(cited)
    if len(cited) == 1:
        it = cited[0]
        nm = _real_name(it)
        k = KIND_WORD.get(it.kind, it.kind).capitalize()
        subject = f"{k} “{nm}”" if nm else f"One {KIND_WORD.get(it.kind, it.kind)}"
        return f"{subject}{st} {where}{suffix}"
    kinds: dict[str, list] = {}
    for it in cited:
        word = KIND_WORD.get(it.kind, it.kind)
        if it.kind == "other" and (it.props or {}).get("role") == "unit":
            word = "apartment"
        elif it.kind == "text" and re.search(r"\brooms?\b", ctx["question"], re.I):
            word = "room label"
        kinds.setdefault(word, []).append(it)
    order = sorted(kinds.items(), key=lambda kv: -len(kv[1]))
    parts = " and ".join(f"{len(v)} {_plural(k, len(v))}" for k, v in order[:2])
    if len(order) > 2:
        parts += f" and {sum(len(v) for _, v in order[2:])} other elements"
    base = f"{parts}{st} {where}{suffix}, each one numbered"
    if len(order) == 1:
        ex = _examples(order[0][1])
        if ex:
            full = f"{base}, including {ex}"
            if len(full) <= MAX:
                return full
            ex2 = _examples(order[0][1], 2)
            full = f"{base}, including {ex2}" if ex2 else base
            return full if len(full) <= MAX else base
    return base


def _read_text(ctx: dict) -> str:
    cites, doc = ctx["cites"], ctx.get("doc")
    _, noun = _source_phrase(ctx)
    c = next((c for c in cites if c.get("quote")), None)
    if c:
        page = c.get("page") or 1
        sheet = (doc.title if doc and doc.title and doc.title != doc.doc_id else "") if (doc and c.get("doc_id") in (None, doc.doc_id)) else ""
        multi = (doc and doc.pages > 1) or page > 1
        loc = f"page {page}" if multi else "the sheet"
        if sheet and len(sheet) <= 30:
            loc = f"{loc} of {sheet}" if multi else f"the sheet “{sheet}”"
        pre = f"Printed on {loc}: “"
        q = _clip(c["quote"], max(20, MAX - len(pre) - 1 - len(_docs_suffix(ctx))))
        return f"{pre}{q}”{_docs_suffix(ctx)}"
    n = len(cites)
    if not any(c.get("item_ids") or c.get("bbox_px") for c in cites):
        return "The available source data was checked; no matching measurement or element was cited."
    pages = sorted({c.get("page") or 1 for c in cites})
    pg = f" on page {pages[0]}" if len(pages) == 1 and pages[0] > 1 else ""
    return f"Used {noun}{pg} as the source; individual items were not identified{_docs_suffix(ctx)}"


def run(ctx: dict) -> None:
    cites, cited, first_cite, steps = ctx["cites"], ctx["cited"], ctx["first_cite"], ctx["steps"]
    if cited:
        cn = first_cite.get(cited[0].item_id) or (cites[0].get("n") if cites else None)
        steps.append({"kind": "found", "title": "Found", "text": _clip(_found_text(ctx), MAX), "cite": cn, "ok": None})
    elif cites:
        steps.append({"kind": "read", "title": "Read", "text": _clip(_read_text(ctx), MAX), "cite": cites[0].get("n"), "ok": None})
    ctx["steps"] = steps
