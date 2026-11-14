"""Arithmetic and source-derived uncertainty for wall finishes; no model calls."""
from __future__ import annotations


def card(report):
    steps = []
    def add(kind, title, text, ok=None):
        steps.append({"kind": kind, "title": title, "text": text, "cite": 1 if report.get("rows") else None, "ok": ok})
    if not report.get("rows"):
        add("read", "Missing data", "No verifiable wall-side area was substituted from floor area or nominal quantities.")
        return {"steps": steps, "confidence": {"label": "Estimate", "pct": 0, "reason": "Required source geometry is missing or unsupported.", "improve": "Provide wall bodies, units and room boundaries in the IFC, or a scaled plan with heights."}}
    gross, opening, net = (report.get(k, 0.) for k in ("gross_m2", "opening_m2", "net_m2"))
    add("measured", "Measured", f"{report['wall_count']} walls, {report.get('metric', 'both')} faces: gross {gross:,.4f} m².")
    ops = report.get("openings", [])
    dims = []
    # Dimensions are actual void extents (IFC), or explicitly assumed plan
    # dimensions. The deduction remains the intersected cut, not nominal w×h.
    for op in ops[:3]:
        if op.get("width_m") is not None and op.get("height_m") is not None:
            dims.append(f"{op['width_m']:.3g} × {op['height_m']:.3g} m")
    add("calculated", "Deducted", f"{len(ops)} hosted openings; actual cut {opening:,.4f} m². {gross:,.4f} − {opening:,.4f} = {net:,.4f} m²."
        + (" Void extents include " + ", ".join(dims) + "." if dims else ""))
    checks = [c for c in report.get("checks", []) if c["quantity"] == "NetSideArea"]
    agreement = None
    if checks:
        stored = sum(c["stored_m2"] for c in checks)
        ours = sum(c["measured_one_side_mean_m2"] for c in checks)
        difference = 100 * abs(ours - stored) / stored if stored else None
        max_abs = max(abs(c["difference_m2"]) for c in checks)
        agreement = max_abs <= report.get("numerical_allowance_m2", 0.)
        add("checked", "Checked", f"On {len(checks)} walls, model NetSideArea {stored:,.4f} m²; measured mean of both sides {ours:,.4f} m²"
            + (f" ({difference:.4f}% apart)." if difference is not None else "; stored total is zero.")
            + " Whole-wall check, not a floor-clipped or room finish total.", agreement)
    if report["source"] == "2D plan estimate":
        sensitivity = report.get("height_sensitivity_m2_per_m", 0.) * .1
        add("calculated", "Uncertainty", f"Scale/height accuracy is not supplied: no finite total margin. A 0.10 m wall-height change changes gross area by {sensitivity:.3f} m²; rectangular-end face-offset allowance {report.get('face_offset_allowance_m2', 0.):.3f} m². "
            + " ".join(report.get("assumptions", [])))
        label, pct = "Estimate", 60
        reason = "2D lengths × stated/printed/assumed heights; source accuracy and undetected openings are unquantified. Percentage is an evidence score, not an error bound."
    else:
        margin = report.get("margin_m2")
        text = (f"Numerical/orientation allowance ±{margin:.6f} m² ({report.get('margin_pct') or 0.:.5f}%)." if margin is not None
                else "No finite total margin: some walls/classifications are missing; the result is a measured subtotal.")
        if report.get("orientation_unresolved"):
            text += " Exterior orientation is unresolved: midpoint of the two possible side areas; half their difference bounds that ambiguity."
        text += " Source-model accuracy and construction tolerances are not quantified."
        add("calculated", "Uncertainty", text)
        if report.get("complete") and agreement is not False:
            label, pct = "Verified", 99
            reason = "Measured model side faces with geometry precision accounted for; source-model accuracy is a separate unknown. Percentage is an evidence score, not an error bound."
        else:
            label, pct = "Estimate", 70
            reason = "; ".join(report.get("warnings", [])) or "Outside/inside orientation is not recorded; both possible side areas bound the result."
        if agreement is False:
            label, pct = "Estimate", 70
            reason += " Stored IFC side quantities disagree; check their measurement convention and the model."
    return {"steps": steps, "confidence": {"label": label, "pct": pct, "reason": reason,
            "improve": "Check heights, openings, exterior flags and room boundaries against the source." if label == "Estimate" else None}}


def run(ctx):
    report = ctx["res"].get("wallarea")
    if report is None:
        return False
    result = card(report)
    ctx["steps"] = result["steps"]
    ctx["wallarea_confidence"] = result["confidence"]
    return True
