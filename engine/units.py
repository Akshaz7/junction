"""Unit conversion and cost add-on for numeric metric answers. Pure functions, no model calls.
convert(res, question) appends a bold clause to answer.text_md; answer.value and the metric text stay unchanged."""
import copy
import re

_NUM = r"(\d[\d,]*(?:\.\d+)?|\d*\.\d+)"
_AREA = r"(?:m\s?2|m²|sq\.?\s?(?:m|metres?|meters?)|square\s+(?:metres?|meters?)|sqm)"
_VOL = r"(?:m\s?3|m³|cubic\s+(?:metres?|meters?)|cbm)"
_LEN = r"(?:m|metres?|meters?)"
_UNITS = {"m": 1.0, "m2": 1.0, "m3": 1.0}

# (regex on lowercased question, target label, factor from base metric unit, metric kind)
_TARGETS = [
    (r"\b(?:sq\.?\s?(?:ft|feet)|square\s+(?:feet|foot|ft))\b|\bft\s?2\b|ft²", "ft²", 10.763910416709722, "m2"),
    (r"\bacres?\b", "acres", 1 / 4046.8564224, "m2"),
    (r"\bhectares?\b|\bha\b", "ha", 1 / 10000.0, "m2"),
    (r"\bsq\.?\s?(?:yd|yards?)\b|\bsquare\s+yards?\b", "yd²", 1.1959900463, "m2"),
    (r"\b(?:cubic\s+(?:feet|foot|ft)|ft\s?3)\b|ft³", "ft³", 35.31466672, "m3"),
    (r"\bcubic\s+yards?\b|\byd\s?3\b|yd³", "yd³", 1.30795061586, "m3"),
    (r"\b(?:feet|foot|ft)\b", "ft", 3.280839895013123, "m"),
    (r"\byards?\b|\byd\b", "yd", 1.0936132983377078, "m"),
    (r"\bcentimet(?:re|er)s?\b|\bcm\b", "cm", 100.0, "m"),
    (r"\bmillimet(?:re|er)s?\b|\bmm\b", "mm", 1000.0, "m"),
]
_CUR = r"(eur|euros?|usd|dollars?|gbp|pounds?|sek|chf|€|\$|£)"
_CODE = {"eur": "EUR", "euro": "EUR", "euros": "EUR", "€": "EUR", "usd": "USD", "dollar": "USD", "dollars": "USD", "$": "USD",
         "gbp": "GBP", "pound": "GBP", "pounds": "GBP", "£": "GBP", "sek": "SEK", "chf": "CHF"}
_PER = {"m": rf"(?:{_LEN})", "m2": _AREA, "m3": _VOL}
_SUP = {"m": "m", "m2": "m²", "m3": "m³"}


def _fmt(x, dec=None):
    if dec is None:
        dec = 0 if abs(x) >= 1000 else 1 if abs(x) >= 10 else 2
        if abs(x) < 0.01:
            dec = 4
    return f"{x:,.{dec}f}"


def _operand(value):
    """Show the actual multiplier; rounding the source quantity changes the displayed arithmetic."""
    from decimal import Decimal
    exact = format(Decimal(str(value)), ",f")
    return exact.rstrip("0").rstrip(".") if "." in exact else exact


def _price(question, mkind):
    """Return (rate, currency) when the question gives a unit price for the answer's metric unit."""
    q = question.lower()
    per = _PER[mkind]
    pats = [
        rf"{_NUM}\s*{_CUR}\s*(?:/|per|a|an|each)\s*{per}\b",
        rf"{_CUR}\s*{_NUM}\s*(?:/|per|a|an|each)\s*{per}\b",
    ]
    for n, p in enumerate(pats):
        m = re.search(p, q)
        if m:
            g = m.groups()
            num, cur = (g[0], g[1]) if n == 0 else (g[1], g[0])
            return float(num.replace(",", "")), _CODE.get(cur, cur.upper())
    return None


def _target(question):
    q = question.lower()
    # a price phrase like "35 eur per square metre" must not trigger a metric conversion; only look at non-metric targets
    for pat, label, factor, mkind in _TARGETS:
        if re.search(pat, q):
            return label, factor, mkind
    return None


def convert(res: dict, question: str) -> dict:
    """Return res with a converted-unit and/or cost clause appended to text_md (copy; input untouched)."""
    try:
        ans = res.get("answer") or {}
        val = ans.get("value")
        unit = {"m²": "m2", "m³": "m3", "sqm": "m2"}.get(ans.get("unit"), ans.get("unit"))
        if ans.get("abstained") or isinstance(val, bool) or not isinstance(val, (int, float)) or unit not in _UNITS or not val:
            return res
        text = ans.get("text_md") or ""
        clauses = []
        tgt = _target(question)
        if tgt and tgt[2] == unit:
            label, factor, _ = tgt
            clauses.append(f"**{_fmt(val * factor)} {label}** ({_fmt(val)} {_SUP[unit]})")
        pr = _price(question, unit)
        if pr:
            rate, cur = pr
            cost = val * rate
            clauses.append(f"**{_fmt(cost, 2)} {cur}** at {_operand(rate)} {cur}/{_SUP[unit]} × {_operand(val)} {_SUP[unit]}")
        if not clauses:
            return res
        out = copy.deepcopy(res)
        out["answer"]["text_md"] = text.rstrip() + "\n\n" + "; ".join(clauses) + "."
        from engine.calc import converted_step, input_value, question_source, step
        ref = {"kind": "step", "step_id": "result"}
        extras = out.setdefault("_calc_extras", [])
        if tgt and tgt[2] == unit:
            label, factor, _ = tgt
            s = converted_step("unit-conversion", val, unit, label, factor, ref)
            shown = _fmt(val * factor)
            extras.append({"steps": [s], "result": {"label": "Converted quantity", "value": float(shown.replace(",", "")),
                                                    "unit": label, "rounded_as": f"{len(shown.partition('.')[2])} decimal places", "step_id": s["id"]}})
        if pr:
            rate, cur = pr
            s = step("unit-price", "Cost at supplied price", "quantity × unit price", val * rate, cur,
                     [input_value("quantity", val, unit, ref), input_value("unit price", rate, f"{cur}/{unit}", question_source(question))], operation="multiply")
            extras.append({"steps": [s], "result": {"label": "Cost at supplied price", "value": round(val * rate, 2), "unit": cur,
                                                    "rounded_as": "2 decimal places", "step_id": s["id"]}})
        return out
    except Exception:  # noqa: BLE001 - never break an answer over a convenience clause
        return res


# F-IMPERIAL: feet/inches in questions and answers. Never read a bare feet/inch number as metres.
_FT, _IN = 0.3048, 0.0254
_IMP_ASK = re.compile(r"\b(?:feet|foot|ft|inch(?:es)?)\b|\bin\s+(?:feet|inches|imperial)\b|\bimperial\b|\d\s*(?:'|\")|\bsq\.?\s?ft\b|ft²", re.I)
_FT_IN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:'|ft\b|feet\b|foot\b)\s*-?\s*(?:(\d+(?:\.\d+)?)\s*(?:\"|in\b|inch(?:es)?\b))?", re.I)
_IN_ONLY = re.compile(r"(\d+(?:\.\d+)?)\s*(?:\"|inch(?:es)?\b)", re.I)


def imperial_requested(question: str) -> bool:
    return bool(_IMP_ASK.search(question or ""))


def feet_inches(metres: float) -> str:
    """3.2808 ft written as '3 ft 3.37 in' (inches rounded to 2 places; carries 12 in into feet)."""
    total_in = metres / _IN
    ft = int(total_in // 12)
    inch = round(total_in - ft * 12, 2)
    if inch >= 12:
        ft, inch = ft + 1, 0.0
    return f"{ft} ft {inch:g} in" if ft else f"{inch:g} in"


def with_imperial(metres: float, shown: str) -> str:
    return f"{shown} ({metres / _FT:,.4g} ft = {feet_inches(metres)})"


def normalize_imperial_question(q: str) -> str:
    """Rewrite 12'-6" / 12 ft 6 in / 36" as millimetres so downstream parsers see an explicit metric unit."""
    def ftin(m):
        mm = (float(m[1]) * _FT + (float(m[2]) * _IN if m[2] else 0)) * 1000
        return f"{mm:g} mm"
    q = _FT_IN.sub(ftin, q)
    return _IN_ONLY.sub(lambda m: f"{float(m[1]) * 25.4:g} mm", q)
