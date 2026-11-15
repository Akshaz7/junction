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
    correct = sum(r.get('outcome') == 'correct' if 'outcome' in r else r['value'] == r['gold'] for r in rows)
    return {'n': len(rows), 'mae': math.fsum(errors) / len(errors), 'absolute_error_sum': math.fsum(errors),
            'correct': correct, 'pct': round(100 * correct / len(rows)),
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
    counted = facts(res, question)
    unit, value = ans.get('unit'), ans.get('value')
    if value is None:
        # A sanity guard may intentionally withhold an area/length total. Its
        # inventory comparisons remain counts; do not attach a fictitious m² margin.
        unit = None
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
    # Saved alternative artifacts are rejected pipeline candidates, often masks
    # with different class semantics or a failed detector. They are not an
    # independent recount of the selected answer. Keep them in the audit only.
    excluded = []
    inventories = {}
    for row in calc.get('inventory_rows') or []:
        vals, ref = row.get('values') or {}, row.get('source') or {}
        if vals.get('alternative'):
            key = (ref.get('doc_id'), ref.get('page'), vals.get('inventory_artifact'))
            inventories.setdefault(key, set()).add(vals.get('kind'))
    for (did, page, artifact), kinds in sorted(inventories.items()):
        excluded.append({'doc_id': did, 'page': page, 'artifact': artifact,
                         'classes': sorted(k for k in kinds if k),
                         'reason': 'Rejected alternate extraction, not an independent reading of the selected quantity; class support, completeness and equivalent filters are not established.'})
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
    # MAE and a current recount can describe the same missed item; adding or
    # quadrature would imply independence that has not been measured. Compare
    # only like-unit supported components, then round count variation outward.
    # Box coverage alone only shows that the count and the boxes agree. It says
    # nothing about missed or false detections, so it can never stand as a margin.
    if all(c['label'] == 'Reported count versus numbered-box coverage' for c in matching):
        coverage = matching[0]
        budget = {'value': None, 'unit': output_unit, 'pct': None, 'sources': list(dict.fromkeys(sources)),
                  'why': ('The count and the numbered boxes agree' if not coverage['value'] else
                          f"The count and the numbered boxes differ by {coverage['value']:g}") +
                         '. The detection error is unknown: no independent recount or historical error is available.',
                  'scope': 'Observed scan discrepancy and historical reference', 'components': matching,
                  'rule': 'coverage_only_margin_unknown', 'excluded_components': excluded,
                  'complete': False, 'is_error_bound': False}
        if old.get('by_kind'):
            budget['by_kind'] = old['by_kind']
        card['margin'] = calc['margin'] = budget
        return
    raw_error = max(c['value'] for c in matching)
    error = math.ceil(raw_error) if output_unit == 'count' else raw_error
    pct = 100 * error / abs(value) if number(value) and value else None
    labels = []
    for c in matching:
        if c['label'] == 'Reported count versus numbered-box coverage' and c['value'] == 0:
            continue
        labels.append({'Historical mean absolute error': 'historical MAE',
                       'Observed independent recount difference': 'recount difference',
                       'Reported count versus numbered-box coverage': 'box discrepancy',
                       'Door-proxy scale sensitivity': 'scale sensitivity'}.get(c['label'], c['label']))
    basis = ' and '.join(labels) or 'box discrepancy only'
    why = ('Larger of ' if len(labels) > 1 else 'From ') + basis
    if output_unit == 'count' and error != raw_error:
        why += ', rounded up to whole items'
    why += '. Partial variation, not a guaranteed error bound.'
    budget = {'value': error, 'unit': output_unit, 'pct': pct, 'why': why, 'sources': list(dict.fromkeys(sources)),
              'scope': 'Observed scan discrepancy and historical reference', 'components': matching,
              'rule': 'max_supported_components_then_ceil_count', 'raw_value': raw_error,
              'raw_pct': 100 * raw_error / abs(value) if number(value) and value else None,
              'excluded_components': excluded,
              'complete': False, 'is_error_bound': False}
    if old.get('by_kind'):
        budget['by_kind'] = old['by_kind']
    card['margin'] = calc['margin'] = budget


def steps(budget, doc_id):
    """Replay supported components, the overlap rule and outward count rounding."""
    from engine.calc import input_value, step, step_source
    if budget.get('value') is None:
        return []  # unknown margin: nothing to replay
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
        raw = budget.get('raw_value', budget['value'])
        sid = 'scan-margin-raw' if raw != budget['value'] else 'scan-margin-total'
        out.append(step(sid, 'Supported observed/reference variation', 'max(supported comparable variation components)', raw, budget['unit'], totals,
                        'Components may overlap, so they are not added or combined in quadrature. Rejected alternate/failed/different-class inventories are excluded. Shared misses remain unknown.', 'max'))
        if raw != budget['value']:
            out.append(step('scan-margin-total', 'Observed/reference scan variation', 'ceil(max supported variation) to whole items', budget['value'], budget['unit'],
                            [input_value('unrounded variation', raw, budget['unit'], step_source(sid))], budget['why'], 'ceil'))
    return out
