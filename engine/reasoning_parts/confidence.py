"""Evidence labels plus observed gold accuracy, never heuristic percentages.

QA2 supplies results/final/QA2/calibration.json. Missing or unmatched cohorts have
no percentage. Detector/scale confidence and recount agreement are not accuracy.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

CALIBRATION_PATH = Path(__file__).resolve().parents[2] / "results/final/QA2/calibration.json"


@lru_cache(maxsize=4)
def _read(path: str, modified: int) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _calibrated(source, unit, label, checked):
    try:
        path = Path(CALIBRATION_PATH)
        data = _read(str(path), path.stat().st_mtime_ns)
    except OSError:
        return None
    matches = []
    for row in data.get("buckets") or []:
        if not isinstance(row, dict) or row.get("source") != source:
            continue
        if any(key in row and row[key] != val for key, val in (("unit", unit), ("label", label), ("checked", checked))):
            continue
        matches.append((sum(k in row for k in ("unit", "label", "checked")), row))
    # Compatibility with the QA2 audit's original published schema. Do not mix
    # unlike operations or extrapolate scan-count results to scan measurements.
    if not matches:
        fmt = {"cad": "dxf", "scan": "png", "ifc": "ifc"}.get(source)
        kind = {"count": "count", "m": "length", "m2": "area", "m3": "volume"}.get(unit)
        if fmt and kind:
            matches = [(0, r) for r in data.get("by_format_and_question_type") or [] if isinstance(r, dict) and r.get("format") == fmt and r.get("type") == kind]
    if not matches:
        return None
    row = max(matches, key=lambda pair: pair[0])[1]
    n, correct = row.get("n"), row.get("correct")
    if type(n) is not int or type(correct) is not int or n <= 0 or not 0 <= correct <= n:
        return None
    return {"pct": round(correct / n * 100), "n": n, "correct": correct,
            "source": "results/final/QA2/calibration.json", "interval_95": row.get("wilson_95"),
            "scope": "Observed audit accuracy; not an individual-answer guarantee"}


def run(ctx: dict) -> dict:
    steps, checked = ctx['steps'], ctx.get('checked')
    exact = ctx.get('quantified_exact') is True
    if 'xchecks' in ctx:
        independent = ctx['xchecks']
        # In the quantity path, reproducing the source sum alone is not an
        # independent verification. Older nonquantity cards retain their flow.
        exact = exact and bool(independent) and all(c['within_1pct'] for c in independent)
        if checked is True and not independent:
            checked = None
    source = "ifc" if ctx.get('is_ifc') else "cad" if ctx.get('from_cad') else "scan"
    source = ctx.get('quantified_source', source)
    if ctx.get('models_used') and ctx.get('route') not in ('planmap', 'index'):
        source = "vision"
    label = "Verified" if exact else "Cross-checked" if checked is True else "Estimate"
    if exact:
        reason = "The cited source quantities reproduce the answer; the source's completeness is not verified."
    elif checked is True:
        reason = "Two recorded readings agree within the recorded tolerance; agreement does not establish an error bound."
    elif checked is False:
        reason = "The recorded readings disagree; check the highlighted evidence."
    else:
        reason = "The source or calculation has not been independently verified."
    calibration = _calibrated(source, ctx.get('unit'), label, checked)
    if calibration:
        reason += f" Audit accuracy: {calibration['correct']} of {calibration['n']} comparable answers."
        if calibration['n'] < 30:
            reason += " This is a small sample."
    else:
        reason += " No measured accuracy is available for this answer type."
    improve = None
    if not exact:
        improve = "Check the numbered evidence and the source quantities."
        if ctx.get('unit') in ('m', 'm2', 'm3') and not ctx.get('is_ifc') and not ctx.get('from_cad'):
            improve = "Supply a known dimension and check the measured outlines."
    if not steps and ctx.get('cites'):
        steps.append({"kind": "read", "title": "Read", "text": "Used the cited drawing as the source; individual items were not identified", "cite": ctx['cites'][0].get('n'), "ok": None})
    agreement = [c['calibration'] for c in ctx.get('xchecks', []) if c.get('calibration')]
    if agreement:
        observed = min(agreement, key=lambda row: row['pct'])
        reason += f" Independent methods agreed within 5% on {observed['within_5pct']} of {observed['n']} measured comparisons; this is agreement, not answer accuracy."
        if observed.get('documents') is not None:
            reason += f" These comparisons cover {observed['documents']} source documents; measurements in one document can share errors."
    result = {"label": label, "pct": calibration['pct'] if calibration else None, "reason": reason,
              "improve": improve, "calibration": calibration, "agreement": agreement, "_steps": steps}
    return factors(result, ctx.get('res') or {'answer': ctx.get('ans', {})}, ctx.get('question', ''), source=source)


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def factors(card, res, question, *, source=None):
    """Decompose an existing score; never invent an accuracy boost or penalty.

    With calibration, pct remains observed cohort accuracy. Otherwise a supplied
    route/model score is explicitly uncalibrated. Missing scores stay unknown.
    Context factors have zero delta: agreement and scale scatter are not measured
    percentage-point changes in answer accuracy.
    """
    ans = res.get('answer') or {}
    raw = ans.get('confidence')
    calibration = card.get('calibration')
    current = card.get('pct')
    if calibration and _finite(calibration.get('pct')):
        base = calibration['pct']
        pct = current if _finite(current) else base
        kind = 'observed_audit_accuracy'
        label = f"Observed audit: {calibration['correct']}/{calibration['n']} comparable answers"
        note = calibration.get('scope', 'Observed cohort accuracy; not an individual-answer guarantee.')
    elif _finite(current):
        base = pct = current
        kind = 'recorded_engine_score'
        label = 'Recorded evidence-card score'
        note = 'Uncalibrated score supplied by this route; not measured answer accuracy.'
    elif _finite(raw) and 0 <= raw <= 1:
        base = pct = round(raw * 100, 6)
        kind = 'recorded_engine_score'
        label = 'Recorded answer-route score'
        note = 'Uncalibrated route/model score, not measured answer accuracy. No accuracy calibration is available.'
    else:
        base, pct, kind = 0, None, 'unavailable'
        label, note = 'No numeric confidence recorded', 'No measured accuracy or route score is available; percentage is unknown.'
    card.update(pct=pct, pct_kind=kind)
    entries = [{'label': label, 'delta': base, 'base': True, 'note': note}]
    if pct is not None and pct != base:
        entries.append({'label': 'Applied evidence confidence cap', 'delta': pct - base,
                        'note': card.get('reason', 'Existing evidence cap; no additional heuristic deduction.')})
    if kind == 'recorded_engine_score':
        score_note = 'The percentage is an uncalibrated route/model score, not measured answer accuracy.'
        reason = card.get('reason') or ''
        if score_note not in reason:
            card['reason'] = (reason + ' ' + score_note).strip()
    if source:
        words = {'scan': 'scanned image read by detector', 'vision': 'vision-model reading',
                 'ifc': 'building-model quantities', 'cad': 'vector CAD geometry', 'unknown': 'cited source data'}
        entries.append({'label': 'Source: ' + words.get(source, source), 'delta': 0,
                        'note': 'Source context; no unmeasured accuracy adjustment.'})
    from engine.reasoning_parts.counts import facts
    counted = facts(res, question)
    if counted and counted.get('reread'):
        original, reread = counted['reread']
        entries.append({'label': f"Recount {'agreed' if original == reread else 'differed'} {original}/{reread}", 'delta': 0,
                        'note': 'Recorded counts; agreement is not an accuracy boost or an error bound.'})
    calc = (res.get('reasoning') or {}).get('calc') or {}
    scale = (calc.get('method') or {}).get('scale') or {}
    if scale:
        entries.append({'label': 'Scale: ' + scale.get('label', scale.get('id', 'recorded method')), 'delta': 0,
                        'note': scale.get('why_chosen', 'Scale quality has no calibrated percentage-point effect.')})
    for s in calc.get('steps') or []:
        if s.get('operation') == 'door_scale_spread':
            entries.append({'label': f"Door-prior proxy spread {s['value']:.3g}%", 'delta': 0,
                            'note': 'Observed icon variation; physical door-width variation remains unknown.'})
    card['factors'] = entries
    return card


def attach(res, question, root):
    """Final hook for every public answer, including cards owned by other routes."""
    card = res.setdefault('reasoning', {'steps': []})
    confidence = card.setdefault('confidence', {'label': 'Estimate', 'pct': None,
                                               'reason': 'No independent verification was recorded.'})
    source = None
    kinds = set()
    for did in res.get('doc_ids') or []:
        try:
            meta = json.loads((Path(root) / did / 'doc.json').read_text())
            kinds.add(meta.get('kind'))
        except (OSError, ValueError, AttributeError):
            pass
    if kinds:
        source = 'ifc' if kinds == {'ifc'} else 'cad' if kinds <= {'dxf', 'dwg'} else 'scan'
    if (card.get('calc') or {}).get('reader'):
        source = 'vision'
    factors(confidence, res, question, source=source)
    if not card.get('graph_path'):
        path, seen = [], set()
        for cite in res.get('citations') or []:
            key = (cite.get('doc_id'), cite.get('page'))
            if key in seen:
                continue
            seen.add(key)
            path.append({'label': 'Cited source page', 'kind': 'document', 'doc_id': key[0], 'page': key[1],
                         'relation': 'source of answer evidence'})
        method = (card.get('calc') or {}).get('method')
        if method:
            path.append({'label': method['label'], 'kind': 'calculation', 'relation': 'method used for this answer'})
        card['graph_path'] = path
    return res
