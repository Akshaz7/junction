"""E-79 part: the confidence label, percentage, reason and 'to make it exact' hint.

The percentage is a sum of named factors, so the reason line can say which ones mattered:
  source base (IFC 97, CAD 95, printed text 93, vector PDF plan 88, scanned plan map 80, vision reader 65)
  + scale quality (measurements only: method rank and scale.confidence)
  + cross-check (agree +8, disagree -10)
  + detector confidence (counts: mean conf of the cited items)
  + the answer's own confidence (only when a model wrote it).
Verified needs >= 92 AND exact source data; Cross-checked is 80-91; Estimate is below 80.
"""
from __future__ import annotations

# Bonus per scale method, best first: printed ratio > scale bar > printed areas > dimensions > door prior.
_METHOD_BONUS = (("ratio", 4), ("scale-bar", 3), ("scalebar", 3), ("printed-area", 2), ("rooms-printed", 2), ("room-areas", 2),
                 ("dimension", 0), ("door", -4))


def _method_bonus(method: str) -> int:
    m = (method or "").lower()
    for k, b in _METHOD_BONUS:
        if k in m:
            return b
    return -2


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _plural(n: int, w: str) -> str:
    return f"{n} {w}{'' if n == 1 else 's'}"


def run(ctx: dict) -> dict:
    if ctx.get("wallarea_confidence") is not None:
        from engine.reasoning_parts.wallarea_steps import card
        return {**ctx["wallarea_confidence"], "_steps": card(ctx["res"]["wallarea"])["steps"]}
    ans, cites, route, unit = ctx['ans'], ctx['cites'], ctx['route'], ctx['unit']
    cited, models_used, is_ifc, sc, scale_w, scale_c, from_cad = ctx['cited'], ctx['models_used'], ctx['is_ifc'], ctx['sc'], ctx['scale_w'], ctx['scale_c'], ctx['from_cad']
    steps = ctx['steps']; checked = ctx.get('checked'); area_q = ctx.get('area_q')
    conf_raw = ans.get("confidence")
    conf_raw = float(conf_raw) if isinstance(conf_raw, (int, float)) and not isinstance(conf_raw, bool) else None
    measured = bool(area_q) or unit in ("m", "m2", "m3")
    method = str((sc or {}).get("method") or "")

    factors: list[tuple[float, str]] = []     # (signed effect, phrase for the reason line)
    exact = False
    if is_ifc and not models_used:
        base, src, exact = 97, "Read directly from the building model's own data", True
    elif from_cad and not models_used:
        base, src, exact = 95, "Measured from the CAD file's exact geometry and units", True
    elif route == "index" and not models_used:
        base, src, exact = 93, "Taken from the text printed in the file", True
    elif route == "planmap":
        if "pdf_vector" in method:
            base, src = 88, "Measured from the PDF's vector drawing"
        else:
            base, src = 80, "Detected on a scanned image"
    else:
        base, src = 65, "Read from the drawing image by a vision model"
        if conf_raw is not None:
            factors.append((_clamp((conf_raw - 0.6) * 30, -8, 8), "the model's own confidence"))

    if route == "planmap" and not exact:
        if measured and sc:
            sb = _method_bonus(method) + _clamp((scale_c - 0.7) * 20, -8, 4)
            sb = round(sb)
            factors.append((sb, f"scale from {scale_w}"))
        if not measured:
            confs = [float(it.conf) for it in cited if it.kind not in ("room", "space") and isinstance(it.conf, (int, float))]
            if confs:
                mean = sum(confs) / len(confs)
                factors.append((round(_clamp((mean - 0.8) * 20, -6, 3)), f"detector confidence {mean:.0%}"))
        if conf_raw is not None and models_used:
            factors.append((round(_clamp((conf_raw - 0.7) * 20, -6, 3)), "the model's own confidence"))
    if checked is True and not exact:
        factors.append((8 if route == "planmap" else 5, "an independent second look agrees"))
    elif checked is False:
        factors.append((-10, "the second look disagreed"))

    pct = base + sum(e for e, _ in factors)
    pct = int(round(_clamp(pct, 40, 99 if exact else 91)))
    if exact:
        pct = max(pct, 92) if checked is not False else pct
    if conf_raw is not None and conf_raw < 0.5 and not exact:
        pct = min(pct, 72)
    label = "Verified" if (pct >= 92 and exact) else ("Cross-checked" if pct >= 80 else "Estimate")

    # reason: the source, then the one or two biggest factors
    top = sorted((f for f in factors if f[0]), key=lambda f: -abs(f[0]))[:2]
    if exact:
        reason = src + (". Nothing is estimated." if base == 97 else ".")
    else:
        reason = src
        if top:
            good = [p for e, p in top if e > 0]
            bad = [p for e, p in top if e < 0]
            if bad:
                reason += "; lowered because " + " and ".join(bad)
            if good:
                reason += "; raised because " + " and ".join(good)
        reason += "."
        if "pdf_vector" not in method and route == "planmap" and measured and "door" in method.lower():
            reason = "Detected on a scanned image; scale estimated from door widths."

    improve = None
    if label == "Estimate":
        if route == "planmap" and measured:
            improve = "Add a printed scale (e.g. 1:100) or scale bar to make sizes exact."
        elif route == "planmap":
            nums = sorted({c.get("n") for c in cites if isinstance(c.get("n"), int)})
            rng = f"boxes {nums[0]}–{nums[-1]}" if len(nums) > 1 else (f"box {nums[0]}" if nums else "the numbered boxes")
            improve = f"Check {rng}, or upload a CAD file or vector PDF to make the count exact."
        else:
            improve = "Check the boxed areas, or upload a CAD file to make this exact."
    if not steps and cites and route not in ("planmap", "index") and not exact:
        steps.append({"kind": "read", "title": "Read", "text": f"{_plural(len(cites), 'marked region')} on the drawing", "cite": cites[0].get("n"), "ok": None})
    return {"label": label, "pct": pct, "reason": reason, "improve": improve, "_steps": steps}
