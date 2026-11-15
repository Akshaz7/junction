"""WHY-CORE: every length and area answer says, in plain words, how we got the number.

One post-pass over a finished answer. For a non-abstained answer whose unit is a
length (m, mm, cm) or an area (m2), ``reasoning.steps`` gets four short steps:

  Source       where the number comes from (model quantity, CAD units, printed text,
               outline detected on the scan, points picked by the reader)
  Scale        drawings only: method, metres per pixel and what it rests on;
               model answers say no drawing scale was needed
  Calculation  the formula with the actual recorded numbers
  How sure     the margin, or "exact from the model"

Everything is read from what the answer already recorded (calc rows/steps,
scale proof, plan map, trace). Missing inputs are named, never filled in. An
existing Measured/Calculated step is replaced by the richer Calculation line
instead of repeated. Pure JSON; no models, no network, no artifact writes.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from statistics import mean, median, stdev

LENGTH = {"m", "mm", "cm"}
AREA = {"m2", "mm2", "cm2"}
SHOW = {"m2": "m²", "mm2": "mm²", "cm2": "cm²"}
IDS = ("why-source", "why-scale", "why-calc", "why-sure")
MAX_TERMS = 6


# ---------------------------------------------------------------- formatting

def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if not isinstance(v, bool) and math.isfinite(f) else None


def _unit(u):
    return str(u or "").replace("²", "2").replace("³", "3").strip()


def _u(u):
    return SHOW.get(_unit(u), _unit(u))


def _q(v, nd=2):
    """Quantities: as recorded, at most nd decimals, thousands separated."""
    f = _num(v)
    if f is None:
        return str(v)
    s = f"{f:,.{nd}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _px(v):
    f = _num(v)
    if f is None:
        return str(v)
    return f"{f:,.0f}" if abs(f - round(f)) < 0.05 else f"{f:,.1f}"


def _sig(v, n=4):
    """Scales: four significant figures, never scientific notation."""
    f = _num(v)
    if f is None:
        return str(v)
    if f == 0:
        return "0"
    nd = max(0, n - 1 - int(math.floor(math.log10(abs(f)))))
    return _q(f, nd)


def _tidy(text):
    """Long recorded decimals in source notes read as 3 significant figures."""
    return re.sub(r"\d+\.\d{4,}", lambda m: _sig(float(m.group()), 3), str(text or "")).strip()


def _conf_word(c):
    c = _num(c)
    if c is None:
        return ""
    return f"confidence {_q(c, 2)} ({'low' if c < 0.5 else 'medium' if c < 0.8 else 'high'})"


def _plural(word, n):
    return word if n == 1 else (word[:-1] + "ies" if word.endswith("y") and word[-2:-1] not in "aeiou" else word + "s")


def _json(path):
    try:
        v = json.loads(Path(path).read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


# ---------------------------------------------------------------- context

class _Ctx:
    def __init__(self, res, root):
        self.res, self.root = res, Path(root)
        self.ans = res.get("answer") or {}
        self.unit = _unit(self.ans.get("unit"))
        self.value = _num(self.ans.get("value"))
        self.card = res.get("reasoning") or {}
        self.calc = self.card.get("calc") or {}
        self.rows = [r for r in self.calc.get("rows") or [] if isinstance(r, dict)]
        self.steps = [s for s in self.calc.get("steps") or [] if isinstance(s, dict)
                      and not str(s.get("id", "")).startswith(("scan-", "method-", "confidence-"))]
        self.trace = res.get("trace") or []
        self.doc_ids = list(dict.fromkeys([*(res.get("doc_ids") or []),
                                           *(c.get("doc_id") for c in res.get("citations") or [] if c.get("doc_id"))]))
        self._files = {}
        self.matched = False   # the IFC quantity was found on the cited element by its value

    def file(self, did, name):
        key = (did, name)
        if key not in self._files:
            self._files[key] = _json(self.root / did / name)
        return self._files[key]

    def doc_kind(self, did):
        return str(self.file(did, "doc.json").get("kind") or "")

    def item(self, did, page, iid):
        pm = self.file(did, f"planmap-{page or 1}.json")
        return next((i for i in pm.get("items") or [] if isinstance(i, dict) and i.get("item_id") == iid), None)

    def element(self, did, iid):
        data = self.file(did, "elements.json")
        return next((e for e in data.get("elements") or [] if isinstance(e, dict) and e.get("item_id") == iid), None)

    def cite_for(self, did, iid):
        for c in self.res.get("citations") or []:
            if c.get("doc_id") == did and iid in (c.get("item_ids") or []):
                return c.get("n")
        return None

    def first_cite(self):
        return next((c.get("n") for c in self.res.get("citations") or [] if c.get("n") is not None), None)

    def shown(self):
        """The value as the headline prints it (calc display rounding when recorded)."""
        for extra in (self.calc.get("result") or {}).get("additional") or []:
            if extra.get("label") == "Displayed answer" and _num(extra.get("value")) is not None:
                return _q(extra["value"], 3)
        return _q(self.value, 3)


def _inputs(s, unit=None, name=None):
    return [i for i in s.get("inputs") or [] if isinstance(i, dict)
            and (unit is None or _unit(i.get("unit")) == unit) and (name is None or name in str(i.get("name", "")))]


def _area_steps(ctx):
    """Outline area × scale × scale, as recorded by calc (outline-*) or any route."""
    return [s for s in ctx.steps if _unit(s.get("unit")) in AREA and _num(s.get("value")) is not None
            and _inputs(s, "px2") and _inputs(s, "m/px")]


def _length_steps(ctx):
    return [s for s in ctx.steps if _unit(s.get("unit")) in LENGTH and _num(s.get("value")) is not None
            and _inputs(s, "px") and _inputs(s, "m/px")]


def _point_steps(ctx):
    return [s for s in ctx.steps if (s.get("operation") == "polyline" or _inputs(s, name="point "))
            and _unit(s.get("unit")) == "px" and len(_points(s)) >= 2]


def _points(s):
    xs, ys = {}, {}
    for i in _inputs(s, name="point "):
        m = re.search(r"point (\d+) ([xy])", str(i.get("name", "")))
        if m and _num(i.get("value")) is not None:
            (xs if m[2] == "x" else ys)[int(m[1])] = _num(i["value"])
    return [(xs[k], ys[k]) for k in sorted(xs) if k in ys]


def _sum_step(ctx):
    return next((s for s in ctx.steps if s.get("operation") == "sum" and _unit(s.get("unit")) in LENGTH | AREA), None)


def _trace_px(ctx):
    """A route that only logged 'L m = P px x S m/px' in its trace."""
    for t in ctx.trace:
        m = re.search(r"(\d+(?:\.\d+)?)\s*m\s*=\s*(\d+(?:\.\d+)?)\s*px\s*[x×]\s*(\d*\.\d+)\s*m/px", str(t.get("detail") or ""))
        if m:
            return tuple(float(g) for g in m.groups())
    return None


def _source_kind(ctx):
    arts = {str((r.get("source") or {}).get("artifact") or "") for r in ctx.rows}
    if "elements.json" in arts or any((r.get("source") or {}).get("origin") == "ifc" for r in ctx.rows):
        return "ifc"
    kinds = {ctx.doc_kind(d) for d in ctx.doc_ids} - {""}
    pixels = _area_steps(ctx) or _length_steps(ctx) or _point_steps(ctx) or _trace_px(ctx)
    if not pixels and kinds and kinds <= {"ifc"}:
        return "ifc"
    if kinds and kinds <= {"dxf", "dwg"}:
        return "dxf"
    return "drawing"


def _pages(ctx):
    """(doc_id, page, m_per_px) the pixel arithmetic used, in first-use order."""
    out = []

    def add(did, page, value=None):
        if did and (did, page or 1) not in [(d, p) for d, p, _ in out]:
            out.append((did, page or 1, value))

    for s in ctx.steps:
        for i in _inputs(s, "m/px"):
            src = i.get("source") or {}
            add(src.get("doc_id"), src.get("page"), _num(i.get("value")))
    for r in ctx.rows:
        src = r.get("source") or {}
        if str(src.get("artifact") or "").startswith("planmap-"):
            add(src.get("doc_id"), src.get("page"))
    for p in (ctx.calc.get("method") or {}).get("pages") or []:
        add(p.get("doc_id"), p.get("page"), _num(p.get("value")))
    if not out and ctx.doc_ids:
        add(ctx.doc_ids[0], next((c.get("page") for c in ctx.res.get("citations") or [] if c.get("doc_id") == ctx.doc_ids[0]), 1))
    return out


def _proof(ctx, did, page):
    for p in ctx.calc.get("scale_proof") or []:
        if isinstance(p, dict) and p.get("doc_id") == did and (p.get("page") or 1) == page:
            return p
    return {}


# ---------------------------------------------------------------- 1. source

def _name(ctx, did, page, iid, fallback):
    it = ctx.item(did, page, iid) or {}
    props = it.get("props") or {}
    label = (it.get("label") or it.get("name") or "").strip()
    rtype = str(props.get("room_type") or "").replace("_", " ")
    if label and rtype and rtype not in label.lower():
        return f"{rtype} {label}"
    return label or rtype or fallback


def _ifc_fields(raw, value):
    """Stored quantity fields on a model element that equal the answer value."""
    out = []
    for group in ("quantities", "props"):
        for k, v in (raw.get(group) or {}).items():
            f = _num(v)
            if f is not None and value is not None and k.endswith(("_m", "_m2", "_mm")) and abs(f - value) <= max(abs(value) * 0.005, 0.005):
                out.append((f"{group}.{k}", f))
    return out


def _source_ifc(ctx):
    rows = ctx.rows
    if len(rows) == 1 or (not rows and len(ctx.res.get("citations") or []) <= 3):
        row = rows[0] if rows else {}
        src = row.get("source") or {}
        did = src.get("doc_id") or (ctx.doc_ids[0] if ctx.doc_ids else None)
        iid = src.get("item_id") or row.get("item_id")
        if not iid:
            ids = [i for c in ctx.res.get("citations") or [] for i in c.get("item_ids") or []]
            iid = ids[0] if len(ids) == 1 else None
        raw = ctx.element(did, iid) if did and iid else None
        kind = (raw or {}).get("kind") or (row.get("values") or {}).get("kind") or "element"
        name = (raw or {}).get("name") or row.get("label") or iid
        who = f"{kind} {name}" + (f" (GUID {iid})" if iid and iid != name else "")
        recorded = [m for m in row.get("methods") or [] if m.get("field")]
        val_key = next((k for k, v in (row.get("values") or {}).items() if k != "kind" and _num(v) is not None), None)
        if recorded:
            m = recorded[0]
            return (f"Building model (IFC): {who}, stored {m['field']} = {_q(m.get('value'), 3)} {_u(ctx.unit)}.",
                    ctx.cite_for(did, iid), True)
        if val_key and src.get("field"):
            return (f"Building model (IFC): {who}, {src['field']} = {_q(row['values'][val_key], 3)} {_u(ctx.unit)}.",
                    ctx.cite_for(did, iid), True)
        fields = _ifc_fields(raw or {}, ctx.value)
        if fields:
            f, v = fields[0]
            ctx.matched = True
            return (f"Building model (IFC): {who}, stored {f} = {_q(v, 3)} {_u(ctx.unit)}.", ctx.cite_for(did, iid), True)
        if raw:
            return (f"Building model (IFC): {who}. No stored quantity on it equals {ctx.shown()} {_u(ctx.unit)}; "
                    "the route did not record which quantity it used.", ctx.cite_for(did, iid), False)
        return ("Building model (IFC). The route did not record which element or quantity gave this number.", ctx.first_cite(), False)
    kinds = sorted({(r.get("values") or {}).get("kind") or (r.get("classification") or {}).get("kind") or "element" for r in rows})
    noun = _plural(kinds[0], len(rows)) if len(kinds) == 1 else "elements"
    fields = sorted({str((r.get("source") or {}).get("field") or "") for r in rows} - {""})
    methods = sorted({str(((r.get("source") or {}).get("record") or {}).get("method") or "") for r in rows} - {""})
    text = f"Building model (IFC): {len(rows)} {noun}"
    if fields:
        text += ", each from " + " / ".join(fields[:2])
    if methods:
        text += f" ({methods[0]})"
    records = [((r.get("source") or {}).get("record") or {}) for r in rows]
    if records and all(_num(x.get("measured_m2")) is not None and _num(x.get("stored_gross_m2")) is not None
                       and abs(x["measured_m2"] - x["stored_gross_m2"]) <= 0.005 * max(1, abs(x["measured_m2"])) for x in records):
        text += "; it matches the stored gross floor area"
    return text + ".", ctx.first_cite(), True


def _source_drawing(ctx, sk):
    where = "the CAD drawing (DXF)" if sk == "dxf" else "the scanned drawing"
    printed = [r for r in ctx.rows if any(m.get("id") == "printed-area" for m in r.get("methods") or [])
               or str((r.get("source") or {}).get("field") or "").endswith("area_m2_label")]
    if printed and len(printed) == len(ctx.rows):
        return (f"Printed on the drawing: {len(printed)} room area {_plural('label', len(printed))} read as written.",
                ctx.first_cite(), True)
    if not ctx.rows and not (_area_steps(ctx) or _length_steps(ctx) or _point_steps(ctx)):
        quotes = [c.get("quote") for c in ctx.res.get("citations") or [] if c.get("kind") == "text" and c.get("quote")]
        if quotes:
            return f'Printed on the drawing: "{_tidy(quotes[0])[:80]}".', ctx.first_cite(), True
    pts = _point_steps(ctx)
    if pts:
        points = _points(pts[0])
        ids = [((i.get("source") or {}).get("item_id")) for i in _inputs(pts[0], name="point ")]
        ids = [i for i in dict.fromkeys(ids) if i]
        did, page = next(((p[0], p[1]) for p in _pages(ctx)), (None, 1))
        whose = (" (end points of " + " and ".join(_name(ctx, did, page, i, i) for i in ids[:3]) + ")") if ids else ""
        by = "picked by the drawing reader (AI)" if not ids else "taken from the detected items"
        shown = " and ".join(f"({_px(x)}, {_px(y)})" for x, y in points[:2]) + (f" and {len(points) - 2} more" if len(points) > 2 else "")
        return f"{len(points)} points on {where} {by}{whose}: {shown} px.", ctx.first_cite(), True
    if ctx.rows:
        kinds = sorted({(r.get("values") or {}).get("kind") or r.get("label") or "item" for r in ctx.rows})
        origin = {(r.get("source") or {}).get("origin") for r in ctx.rows}
        how = "read by the AI" if origin & {"vlm", "vision"} else "detected" if origin & {"det", "seg"} else "recorded"
        r0 = ctx.rows[0]
        src = r0.get("source") or {}
        did, page = src.get("doc_id"), src.get("page") or 1
        if len(ctx.rows) == 1:
            k = kinds[0]
            name = _name(ctx, did, page, src.get("item_id") or r0.get("item_id"), k)
            what = "outline" if k in ("room", "space", "wall") or _area_steps(ctx) else "symbol"
            iid = src.get("item_id") or r0.get("item_id")
            text = f"{k.capitalize()} {what} {how} on {where}: " + (f"{name} ({iid})." if name != k else f"{iid}.")
        else:
            noun = _plural(kinds[0], len(ctx.rows)) if len(kinds) == 1 else "items"
            text = f"Outlines of {len(ctx.rows)} {noun} {how} on {where}, each measured from its pixel shape."
        runs = next((str(t.get("detail")) for t in ctx.trace if t.get("step") == "wall_runs"), None)
        if runs:
            text += f" {_tidy(runs)[0].upper()}{_tidy(runs)[1:]}."
        return text, ctx.cite_for(did, src.get("item_id")) or ctx.first_cite(), True
    if _trace_px(ctx):
        return f"A pixel length measured on {where} by code.", ctx.first_cite(), True
    noun = "distance" if ctx.unit in LENGTH else "area"
    return (f"The {noun} was given by the drawing reader without recorded points; not independently measured.",
            ctx.first_cite(), False)


# ---------------------------------------------------------------- 2. scale

def _door_scale(step):
    widths = [_num(i.get("value")) for i in _inputs(step, "px", "door icon width")]
    widths = [w for w in widths if w]
    prior = next((_num(i.get("value")) for i in _inputs(step, "m", "assumed door width")), None)
    med = _num(step.get("median_width_px")) or (median(widths) if widths else None)
    if not (prior and med):
        return None
    n = len(widths) or step.get("sample_count")
    text = f"assumed {_q(prior, 2)} m door width ÷ median door symbol width {_px(med)} px = {_sig(prior / med)} m/px"
    if widths:
        text += f", from {n} {_plural('door', n)}"
        if len(widths) > 1:
            text += f" ({_px(min(widths))}–{_px(max(widths))} px, spread {_q(stdev(widths) / mean(widths) * 100, 1)}%)"
    return text


def _scale_line(ctx, did, page, used):
    pm = ctx.file(did, f"planmap-{page}.json")
    sc = pm.get("scale") or {}
    mpp = used or _num(sc.get("m_per_px"))
    method = str(sc.get("method") or "")
    proof = _proof(ctx, did, page)
    steps = [s for s in proof.get("steps") or [] if isinstance(s, dict)]
    chosen = next((s for s in steps if mpp and _num(s.get("value")) and abs(s["value"] - mpp) <= 0.002 * mpp), None)
    label = str((chosen or {}).get("label") or method).lower()
    conf = _conf_word(sc.get("confidence"))
    if mpp is None:
        return None, None
    if "door" in label:
        text = _door_scale(chosen or {}) or f"door-width prior ({_tidy(sc.get('evidence') or 'median door symbol taken as 0.9 m')}) = {_sig(mpp)} m/px"
        return "From door widths (no printed scale): " + text + (f"; {conf}." if conf else "."), "door"
    if label == "ifc" or method == "ifc":
        ppm = next((_num(i.get("value")) for i in _inputs(chosen or {}, "px/m")), None)
        how = f"1 ÷ {_q(ppm, 2)} px per metre = {_sig(mpp)} m/px" if ppm else f"{_sig(mpp)} m/px"
        return f"Plan drawn from the model itself: {how}; no scale was guessed.", "exact"
    if "dxf" in label or "dxf" in method:
        unit_m = next((_num(i.get("value")) for i in _inputs(chosen or {}, name="metres per drawing unit")), None)
        how = f"1 drawing unit = {_sig(unit_m)} m, " if unit_m else ""
        return f"CAD file's own units: {how}1 px = {_sig(mpp)} m on the page picture; no scale was guessed.", "exact"
    if "printed" in method or "ratio" in label:
        ratio = sc.get("ratio") or re.sub(r"^printed\s*", "", method)
        mpt, pxpt = _num(sc.get("m_per_pt")), None
        m = re.search(r"at\s+(\d*\.\d+)\s*px per pt", str(sc.get("evidence") or ""))
        pxpt = _num(m.group(1)) if m else None
        how = f"{_sig(mpt)} m per pt ÷ {_sig(pxpt)} px per pt = {_sig(mpp)} m/px" if mpt and pxpt else f"{_sig(mpp)} m/px"
        return f"Printed scale {ratio} on the sheet: {how}" + (f"; {conf}." if conf else "."), "printed"
    if chosen and chosen.get("expr"):
        ins = ", ".join(f"{i.get('name')} {_sig(i.get('value'))} {i.get('unit')}" for i in (chosen.get("inputs") or [])[:3]
                        if _num(i.get("value")) is not None)
        what = {"dimension": "printed dimensions", "scalebar": "the scale bar", "scale bar": "the scale bar"}.get(label, label.replace("_", " "))
        return f"From {what}: {ins + ' → ' if ins else ''}{_sig(mpp)} m/px" + (f"; {conf}." if conf else "."), label
    words = {"dimension": "printed dimension/area text", "scalebar": "the scale bar", "scale-bar": "the scale bar"}.get(method, method.replace("_", " ") or "a recorded page scale")
    ev = f" ({_tidy(sc['evidence'])})" if sc.get("evidence") else ""
    return f"From {words}{ev}: {_sig(mpp)} m/px" + (f"; {conf}." if conf else "."), method


def _scale(ctx, sk, src_ok):
    if sk == "ifc":
        return "Model units (metres), no drawing scale needed.", "exact"
    pixel = _area_steps(ctx) or _length_steps(ctx) or _point_steps(ctx) or _trace_px(ctx)
    if not pixel and ctx.rows and all(any(m.get("id") == "printed-area" for m in r.get("methods") or []) for r in ctx.rows):
        return "Taken as printed, so no drawing scale was needed.", "printed"
    if not pixel and not ctx.rows and not src_ok:
        return None, None
    lines, basis = [], None
    pages = _pages(ctx)
    for did, page, used in pages[:2]:
        line, b = _scale_line(ctx, did, page, used)
        if line:
            lines.append((f"Page {page}: " if len(pages) > 1 else "") + line)
            basis = basis or b
    if not lines:
        t = _trace_px(ctx)
        if t:
            return f"{_sig(t[2])} m/px, as logged by the route; its derivation was not recorded.", None
        return "No drawing scale was recorded for this page, so the metres-per-pixel factor cannot be shown.", None
    return " ".join(lines), basis


# ---------------------------------------------------------------- 3. formula

def _terms(values, unit):
    vals = [_q(v, 2) for v in values]
    shown = vals if len(vals) <= MAX_TERMS else vals[:MAX_TERMS - 1] + [f"… ({len(vals) - MAX_TERMS + 1} more)"]
    return " + ".join(shown)


def _area_formula(s):
    px = next((_num(i.get("value")) for i in _inputs(s, "px2")), None)
    mpp = [_num(i.get("value")) for i in _inputs(s, "m/px")]
    if px is None or not mpp or mpp[0] is None:
        return None
    return f"{_px(px)} px² × {_sig(mpp[0])}² m²/px² = {_q(s['value'], 2)} m²"


def _formula(ctx, sk):
    """(text, from_log): from_log marks arithmetic replayed from the route's trace, not calc steps."""
    u = _u(ctx.unit)
    out, result, from_log = None, None, False
    pick = next((s for s in ctx.steps if s.get("operation") in ("max", "min") and _num(s.get("value")) is not None), None)
    stored = next((s for s in ctx.steps if str(s.get("id") or "").startswith("ifc-quantity") and _num(s.get("value")) is not None), None)
    if pick:
        vals = [_num(i.get("value")) for i in pick.get("inputs") or [] if _num(i.get("value")) is not None]
        ties = sum(1 for v in vals if abs(v - pick["value"]) <= 1e-9)
        word = "largest" if pick["operation"] == "max" else "smallest"
        lead = f"{word} of {len(vals)} values" + (f" ({ties} tied)" if ties > 1 else "") if vals else word + " value"
        return f"{lead[0].upper()}{lead[1:]} = {_q(pick['value'], 3)} {u}.", False
    if stored and not _sum_step(ctx):
        return f"Stored model value: {_q(stored['value'], 3)} {u}, no arithmetic.", False
    total = _sum_step(ctx)
    areas = _area_steps(ctx)
    numeric = [i for i in (total or {}).get("inputs") or [] if _num(i.get("value")) is not None]
    if total and len(numeric) >= 2:
        kinds = {(r.get("values") or {}).get("kind") for r in ctx.rows} - {None}
        noun = _plural(next(iter(kinds)), len(numeric)) if len(kinds) == 1 else "parts"
        out = f"Sum of {len(numeric)} {noun}: {_terms([i['value'] for i in numeric], u)} = {_q(total.get('value'), 2)} {u}"
        result = total.get("value")
        if areas:
            eg = _area_formula(areas[0])
            out += f". Each is its pixel area inside the outline × scale²" + (f", e.g. {eg}" if eg else "")
    elif areas and _area_formula(areas[0]):
        out, result = "Pixel area inside the outline × scale²: " + _area_formula(areas[0]), areas[0]["value"]
    else:
        pts, lens = _point_steps(ctx), _length_steps(ctx)
        if pts or lens:
            parts = []
            if pts:
                points = _points(pts[0])
                if len(points) == 2:
                    dx, dy = abs(points[1][0] - points[0][0]), abs(points[1][1] - points[0][1])
                    parts.append(f"√(Δx² + Δy²) = √({_px(dx)}² + {_px(dy)}²) = {_px(pts[0]['value'])} px")
                elif points:
                    parts.append(f"sum of {len(points) - 1} segment lengths between {len(points)} points = {_px(pts[0]['value'])} px")
            if lens:
                s = lens[0]
                px = next((_num(i.get("value")) for i in _inputs(s, "px")), None)
                mpp = next((_num(i.get("value")) for i in _inputs(s, "m/px")), None)
                parts.append(f"{_px(px)} px × {_sig(mpp)} m/px = {_q(s['value'], 3)} m")
                result = s["value"]
            out = "; ".join(parts)
        elif (t := _trace_px(ctx)):
            out, result, from_log = f"{_px(t[1])} px × {_sig(t[2])} m/px = {_q(t[0], 3)} m", t[0], True
        elif sk == "ifc" and len(ctx.rows) <= 1:
            return f"None needed: the stored value is the answer, {ctx.shown()} {u}.", False
    if out:
        conv = next((s for s in ctx.steps if s.get("operation") == "convert" and _num(s.get("value")) is not None), None)
        if conv:
            out += f"; converted: {_tidy(conv.get('expr'))} = {_q(conv['value'], 3)} {_u(conv.get('unit'))}"
            result = conv["value"]
        if _num(result) is not None and ctx.value is not None and abs(float(result) - float(ctx.shown().replace(",", ""))) > 1e-9:
            out += f", shown as {ctx.shown()} {u}"
        return out + ".", from_log
    if any(s.get("id") == "model-final" for s in ctx.calc.get("steps") or []) or ctx.res.get("route") in ("hybrid", "vlm"):
        return (f"No measurement inputs were recorded: {ctx.shown()} {u} is the drawing reader's own figure, "
                "not rebuilt by code."), False
    return f"The recorded inputs do not rebuild {ctx.shown()} {u}.", False


# ---------------------------------------------------------------- 4. how sure

def _sure(ctx, sk, basis, src_ok, from_log=False, matched=False):
    margin = ctx.calc.get("margin") or ctx.card.get("margin") or {}
    incomplete = ctx.calc.get("status") == "incomplete"
    notes = []
    reader = next((s for s in ctx.calc.get("steps") or [] if s.get("id") == "reader-confidence"), None)
    if sk == "ifc":
        if src_ok:
            text = "Exact from the model: the number is the model's own value, so it is only as right as the model."
        else:
            text = "From the model, but the exact quantity used was not recorded, so it is not checked."
        if any(s.get("ok") is False for s in ctx.card.get("steps") or [] if s.get("kind") == "checked"):
            notes.append("The model's own stored figures disagree; see the cross-check.")
    elif _num(margin.get("value")) is not None:
        pct = f" ({_q(margin.get('pct'), 1)}%)" if _num(margin.get("pct")) is not None else ""
        text = f"About ±{_q(margin['value'], 2)} {_u(margin.get('unit') or ctx.unit)}{pct}: {_tidy(margin.get('why'))}"
    elif basis == "door":
        text = ("Rough estimate: the scale rests on an assumed door width, so the real error is not known"
                + (" and doubles for an area (scale counts twice)." if ctx.unit in AREA else "."))
    elif basis == "printed":
        text = "Good: the scale is the printed one; how well the outline was traced is not measured."
    elif basis == "exact":
        text = "The scale is exact; how well the outline or points match the real element is not measured."
    elif margin.get("why"):
        text = _tidy(margin["why"])
    else:
        text = "No error margin was recorded for this number."
    if reader and _num(reader.get("value")) is not None:
        what = "Points" if _point_steps(ctx) else "Element"
        notes.append(f"{what} chosen by the AI reader (its own confidence {_q(reader['value'], 2)}); not an independent survey.")
    if from_log:
        notes.append("The pixel length comes from the route's log; it is not yet a checkable step in the calculation.")
    elif incomplete and src_ok and not matched:
        notes.append("The recorded steps do not fully rebuild this number.")
    return " ".join([text.rstrip(".") + ".", *notes])


# ---------------------------------------------------------------- merge

def _merge(old, source, scale, calc_text, sure):
    old = [s for s in old if isinstance(s, dict) and s.get("id") not in IDS]
    lead = [s for s in old if s.get("kind") == "found"]
    rest = [s for s in old if s.get("kind") != "found"]
    own = lambda s: str(s.get("id") or "").startswith("ifc-") or s.get("source") == "distance"   # IFC-WHY / DIST steps stay
    target = (next((s for s in rest if s.get("kind") == "calculated" and not own(s)), None)
              or next((s for s in rest if s.get("kind") == "measured" and not own(s)), None))
    out = list(lead) + [s for s in (source, scale) if s]
    for s in rest:
        if s is target and calc_text:
            out.append({**calc_text, "cite": calc_text.get("cite") if calc_text.get("cite") is not None else s.get("cite")})
            continue
        if calc_text and not own(s) and s.get("kind") == "measured" and re.search(r"×|\bpx\b|m/px", str(s.get("text") or "")):
            continue   # the Calculation line carries the same arithmetic with its inputs
        out.append(s)
    if calc_text and target is None:
        out.append(calc_text)
    out.append(sure)
    return out


def _attach(res, root):
    ans = res.get("answer") or {}
    if ans.get("abstained") or res.get("xdisc") is not None:
        return res
    unit = _unit(ans.get("unit"))
    if unit not in LENGTH | AREA or _num(ans.get("value")) is None:
        return res
    ctx = _Ctx(res, root)
    sk = _source_kind(ctx)
    if sk == "ifc":
        src_text, src_cite, src_ok = _source_ifc(ctx)
    else:
        src_text, src_cite, src_ok = _source_drawing(ctx, sk)
    scale_text, basis = _scale(ctx, sk, src_ok)
    formula, from_log = _formula(ctx, sk)
    dist = ctx.calc.get("distance") if isinstance(ctx.calc.get("distance"), dict) else None
    if dist:   # engine/distance.py: its Measured line already carries the √(Δx² + Δy²) working
        items = [i for i in dist.get("items") or [] if isinstance(i, dict)]
        names = " and ".join(str(i.get("name") or i.get("item_id")) for i in items[:2]) or "the two items"
        hows = sorted({str(i.get("how")) for i in items if i.get("how")})
        src_text = (f"Distance between {names}; each point is the centre (centroid) of its outline"
                    + (f" ({', '.join(hows)})" if hows else "") + ".")
        src_ok, formula = True, None

    def mk(id, kind, title, text, cite=None, ok=None):
        return {"id": id, "kind": kind, "title": title, "text": text, "cite": cite, "ok": ok}

    card = res.setdefault("reasoning", {"steps": [], "confidence": {"label": "Estimate", "pct": None,
                                                                  "reason": "No independent verification was recorded."}})
    card["steps"] = _merge(card.get("steps") or [],
                           mk("why-source", "read", "Source", src_text, src_cite),
                           mk("why-scale", "measured", "Scale", scale_text) if scale_text else None,
                           mk("why-calc", "calculated", "Calculation", formula, ctx.first_cite()) if formula else None,
                           mk("why-sure", "checked", "How sure", _sure(ctx, sk, basis, src_ok, from_log, ctx.matched)))
    return res


def attach(res: dict, root) -> dict:
    """Justification is an explanation layer: it must never break an answer."""
    try:
        return _attach(res, root)
    except Exception:  # noqa: BLE001
        return res
