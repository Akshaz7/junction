"""Measured scan discrepancy and historical reference errors, never guarantees.

The numerical budget is explicitly partial. Shared detector misses, physical
prior bias and interpretation error remain unbounded by agreement or scores.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from engine.calc import number

REPO = Path(__file__).resolve().parents[1]
HISTORY = REPO / 'results/bench/sample200-r10.rows.jsonl'


@lru_cache(maxsize=4)
def _history(path, modified):
    from engine.router.parser import parse
    records = []
    try:
        for line in Path(path).read_text().splitlines():
            row = json.loads(line)
            if number(row.get('gold')) and number(row.get('value')):
                p = parse(row.get('question', ''))
                records.append({**row, '_kind': p.kind, '_scope': p.scope or 'whole-doc'})
    except (OSError, ValueError, TypeError):
        return []
    return records


def historical(res, question):
    """Same source/operation/kind/route reference cohort, not current calibration."""
    from engine.router.parser import parse
    parsed = parse(question)
    ans = res.get('answer') or {}
    unit = ans.get('unit')
    sources = {did.split('__', 1)[0] for did in res.get('doc_ids') or []}
    if len(sources) != 1 or unit not in ('count', 'm', 'm2', 'm3'):
        return None
    try:
        rows = _history(str(HISTORY), HISTORY.stat().st_mtime_ns)
    except OSError:
        return None
    rows = [r for r in rows if r.get('source') in sources and r.get('unit') == unit and r.get('route') == res.get('route')
            and r.get('type') == parsed.type and r['_kind'] == parsed.kind and r['_scope'] == (parsed.scope or 'whole-doc')]
    if not rows:
        return None
    errors = [abs(r['value'] - r['gold']) for r in rows]
    return {'n': len(rows), 'mae': math.fsum(errors) / len(errors), 'absolute_error_sum': math.fsum(errors),
            'comparisons': [{'doc_id': r['doc_id'], 'predicted': r['value'], 'gold': r['gold']} for r in rows],
            'unit': unit, 'source': str(HISTORY.relative_to(REPO)), 'kind': parsed.kind,
            'scope': 'Historical same-source/operation/kind/route reference; model/version equivalence is not established. Not an individual-answer error bound.'}


def attach(res, question, calc):
    card, ans = res['reasoning'], res.get('answer') or {}
    old = card.get('margin') or calc.get('margin') or {}
    if number(old.get('value')) and old.get('scope') not in ('Observed scan discrepancy and historical reference',):
        # Preserve a matched detector error model or a physical error budget.
        return
    from engine.reasoning_parts.counts import facts
    from engine.router.parser import parse
    parsed = parse(question)
    counted = facts(res, question)
    unit, value = ans.get('unit'), ans.get('value')
    components, sources = [], []
    cohort = historical(res, question)
    if cohort:
        components.append({'label': 'Historical mean absolute error', 'value': cohort['mae'], 'unit': cohort['unit'],
                           'expr': f"{cohort['absolute_error_sum']:g} / {cohort['n']}", 'source': cohort['source'], 'calibration': cohort})
        sources.append(cohort['source'])
    if counted and counted.get('reread'):
        original, reread = counted['reread']
        components.append({'label': 'Observed independent recount difference', 'value': abs(reread - original), 'unit': 'count',
                           'expr': f'abs({reread} − {original})', 'source': 'answer.trace.recount',
                           'operands': [original, reread],
                           'note': 'Observed discrepancy, not proof of completeness.'})
        sources.append('answer.trace.recount')
    if counted and not counted.get('derived'):
        components.append({'label': 'Reported count versus numbered-box coverage', 'value': abs(counted['total'] - counted['boxes']), 'unit': 'count',
                           'expr': f"abs({counted['total']} − {counted['boxes']})", 'source': 'answer.value / evidence.boxes',
                           'operands': [counted['total'], counted['boxes']],
                           'note': 'Coverage discrepancy only. Zero means the returned boxes reconcile, not that no items were missed; this is not an independent detection-error estimate.'})
        sources.append('answer.value / evidence.boxes')
    inventory = calc.get('inventory_rows') or []
    selected, alternate = {}, {}
    for row in inventory:
        vals, ref = row.get('values') or {}, row.get('source') or {}
        kind = vals.get('kind')
        if kind not in ('door', 'window', 'wall', 'room', 'toilet', 'sink', 'shower', 'bathtub', 'stairs', 'column'):
            continue
        if unit == 'count' and parsed.kind and kind != parsed.kind:
            continue
        key = (ref.get('doc_id'), ref.get('page'), kind)
        target = alternate.setdefault(vals.get('inventory_artifact'), {}) if vals.get('alternative') else selected
        target[key] = target.get(key, 0) + 1
    discrepancies = []
    for filename, values in sorted(alternate.items()):
        for key, count in values.items():
            # A class absent from an extraction may be unsupported; only compare
            # classes actually present in both saved extraction runs.
            if key not in selected:
                continue
            delta = abs(selected[key] - count)
            discrepancies.append({'doc_id': key[0], 'page': key[1], 'kind': key[2], 'selected': selected[key], 'alternate': count,
                                  'artifact': filename, 'difference': delta})
    if discrepancies and unit in ('count', None, ''):
        # Compare whole per-class inventories, not a filtered question's count.
        filtered = parsed.scope is not None or parsed.kind in ('bedroom', 'bathroom', 'kitchen', 'wc_room', 'balcony', 'sauna')
        if unit != 'count' or not filtered:
            # Multiple alternate runs are correlated; take the largest total,
            # rather than summing duplicated disagreements across algorithms.
            per_run = {}
            for d in discrepancies:
                per_run[d['artifact']] = per_run.get(d['artifact'], 0) + d['difference']
            components.append({'label': 'Saved extraction count disagreement', 'value': max(per_run.values()), 'unit': 'count',
                               'expr': 'max per saved run of Σ abs(selected class count − alternate class count)',
                               'source': 'calc.inventory_rows', 'comparisons': discrepancies,
                               'note': 'Page inventory disagreement; includes shared segmentation errors and is not a ground-truth error bound.'})
            sources.extend(f"{d['doc_id']}: {d['artifact']}" for d in discrepancies)
    selected_scale = (calc.get('method') or {}).get('scale') or {}
    if unit in ('m', 'm2', 'm3') and number(value) and selected_scale.get('id') == 'door-prior':
        spreads = [s for s in calc.get('steps') or [] if s.get('operation') == 'door_scale_spread' and number(s.get('value'))]
        power = {'m': 1, 'm2': 2, 'm3': 3}[unit]
        if spreads:
            spread = max(s['value'] for s in spreads) / 100
            sensitivity = abs(value) * max((1 + spread) ** power - 1, abs(max(0, 1 - spread) ** power - 1))
            if math.isfinite(sensitivity):
                components.append({'label': 'Door-proxy scale sensitivity', 'value': sensitivity, 'unit': unit,
                                   'expr': f'abs({value:g}) × ((1 + {spread:g})^{power} − 1)', 'source': 'calc.steps:door_scale_spread',
                                   'operands': [value, spread, power],
                                   'note': 'Variation across icon-derived scales only. Actual door-width/prior bias and outline error are not bounded.'})
                sources.append('calc.steps:door_scale_spread')
    if not components:
        # Keep honest unknowns when there is no comparison or matched history.
        return
    output_unit = unit if unit in ('count', 'm', 'm2', 'm3') else 'count'
    matching = [c for c in components if c['unit'] == output_unit]
    if not matching:
        return
    # Do not claim independent additive errors: overlapping references may
    # describe the same failure. The maximum is a conservative comparison proxy.
    error = max(c['value'] for c in matching)
    pct = 100 * error / abs(value) if number(value) and value else None
    why = '; '.join(f"{c['label']}: {c['value']:.4g} {c['unit']} ({c['expr']})" for c in matching)
    why += '. Uses the largest recorded component; components can overlap. This is observed/reference variation, not a guaranteed error bound; shared misses and physical prior bias remain unbounded.'
    if unit in (None, ''):
        why = 'Description inventory only; no scalar answer was requested. ' + why
    budget = {'value': error, 'unit': output_unit, 'pct': pct, 'why': why, 'sources': list(dict.fromkeys(sources)),
              'scope': 'Observed scan discrepancy and historical reference', 'components': matching,
              'complete': False, 'is_error_bound': False}
    card['margin'] = calc['margin'] = budget


def steps(budget, doc_id):
    """Replay each observed component and the max rule with explicit operands."""
    from engine.calc import input_value, step, step_source
    out, totals = [], []
    for index, component in enumerate(budget.get('components') or []):
        prefix = f'scan-margin-{index}'
        ref = {'kind': 'measurement', 'doc_id': doc_id, 'record': component,
               'text': 'Saved observations/reference cohort; variation is not a guaranteed error bound.'}
        operands = component.get('operands')
        history = component.get('calibration')
        if history:
            errors = []
            for j, row in enumerate(history['comparisons']):
                sr = {**ref, 'artifact': history['source'], 'record': row}
                sid = f'{prefix}-history-{j}'
                error = abs(row['predicted'] - row['gold'])
                out.append(step(sid, 'Historical prediction absolute error', f"abs({row['predicted']} − {row['gold']})", error, component['unit'],
                                [input_value('recorded prediction', row['predicted'], component['unit'], sr),
                                 input_value('reference answer', row['gold'], component['unit'], sr)], history['scope'], 'abs_difference'))
                errors.append(input_value('historical absolute error', error, component['unit'], step_source(sid)))
            out.append(step(prefix + '-sum', 'Sum historical absolute errors', 'Σ absolute errors', history['absolute_error_sum'], component['unit'], errors, history['scope'], 'sum'))
            inputs = [input_value('sum absolute errors', history['absolute_error_sum'], component['unit'], step_source(prefix + '-sum')),
                      input_value('comparable historical answers', history['n'], 'count', ref)]
            operation = 'divide'
        elif component.get('comparisons'):
            runs = {}
            for j, row in enumerate(component['comparisons']):
                sid = f'{prefix}-extraction-{j}'
                out.append(step(sid, row['kind'] + ': saved extraction difference', f"abs({row['selected']} − {row['alternate']})", row['difference'], 'count',
                                [input_value('selected retained count', row['selected'], 'count', {**ref, 'record': row}),
                                 input_value('alternate retained count', row['alternate'], 'count', {**ref, 'record': row})], component['note'], 'abs_difference'))
                runs.setdefault(row['artifact'], []).append(input_value('class count difference', row['difference'], 'count', step_source(sid)))
            inputs = []
            for j, (artifact, values) in enumerate(runs.items()):
                sid = f'{prefix}-run-{j}'
                value = math.fsum(v['value'] for v in values)
                out.append(step(sid, 'Saved extraction total discrepancy: ' + artifact, 'Σ class count differences', value, 'count', values, component['note'], 'sum'))
                inputs.append(input_value(artifact + ' total difference', value, 'count', step_source(sid)))
            operation = 'max'
        elif component['label'] == 'Observed independent recount difference':
            # The operands were captured with the component from the real trace.
            operands = component['operands']
            inputs = [input_value(name, value, component['unit'], ref) for name, value in zip(('original count', 'second-look count'), operands)]
            operation = 'abs_difference'
        elif operands:
            operation = 'scale_sensitivity' if component['label'] == 'Door-proxy scale sensitivity' else 'abs_difference'
            inputs = [input_value(name, value, unit, ref) for name, value, unit in zip(
                ('answer quantity', 'relative scale spread', 'dimensional power') if operation == 'scale_sensitivity' else ('reported count', 'numbered boxes'),
                operands, (component['unit'], 'fraction', 'power') if operation == 'scale_sensitivity' else ('count', 'count'))]
        else:
            continue
        out.append(step(prefix, component['label'], component['expr'], component['value'], component['unit'], inputs,
                        component.get('note') or (history or {}).get('scope', ''), operation))
        totals.append(input_value(component['label'], component['value'], component['unit'], step_source(prefix)))
    if totals:
        out.append(step('scan-margin-total', 'Observed/reference scan variation', 'max(recorded variation components)', budget['value'], budget['unit'], totals,
                        budget['why'], 'max'))
    return out
