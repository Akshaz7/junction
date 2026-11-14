"""Attach scale provenance to numeric answers without changing their quantities."""
from __future__ import annotations

import copy
import math
from pathlib import Path

from engine.scale_proof import enrich, operand, positive, read_json, source


def run(ctx, quantitative):
    from engine.reasoning_parts.margin import number
    if ctx.get('unit') not in ('m', 'm2', 'm3') or number(ctx.get('value')) is None:
        return {}
    from engine.reasoning_parts.margin import _rows
    rows, _ = _rows(ctx)
    page_scales, proofs, native, seen = {}, [], [], set()
    for doc, it, _ in rows:
        key = (doc.doc_id, it.page)
        if key in seen:
            continue
        seen.add(key)
        folder = Path(ctx['root']) / doc.doc_id
        pm = read_json(folder / f'planmap-{it.page}.json')
        pm = {**pm, 'doc_id': doc.doc_id, 'page': it.page}
        effective = doc.scale if doc.mode == 'planmap' else pm.get('scale')
        sc = enrich(pm, folder, effective_scale=effective, save_crops=True)
        page_scales[key] = sc
        if doc.mode == 'planmap' or pm.get('projection'):
            proofs.append((doc.doc_id, it.page, sc['proof']))
        units = (doc.meta or {}).get('unit_provenance')
        if doc.mode == 'ifc' and units and positive(units.get('m_per_unit')) and doc.doc_id not in {n[0] for n in native}:
            native.append((doc.doc_id, units))
    steps, checks = [], []
    for did, page, proof in proofs:
        for step in proof['steps']:
            steps.append({**step, 'id': f'{did}-p{page}-{step["id"]}'})
        checks.extend({**c, 'source': source(did, page)} for c in proof['checks'])
        steps.append({'id': f'{did}-p{page}-chosen-scale', 'label': 'Scale used for this page',
                      'expr': 'stored scale used by the source quantities', 'value': proof['result']['value'], 'unit': 'm/px',
                      'inputs': [operand('stored scale', proof['result']['value'], 'm/px', source(did, page, file=f'planmap-{page}.json', pointer='/scale/m_per_px'))],
                      'note': proof['selection_rule']})
    for did, units in native:
        steps.insert(0, {'id': f'{did}-native-units', 'label': 'Model length units', 'expr': units['formula'],
                         'value': units['m_per_unit'], 'unit': 'm/native unit', 'inputs': units['inputs'], 'note': units['note']})
    if not steps:
        steps.append({'id': 'scale-unavailable', 'label': 'Scale provenance unavailable', 'expr': '', 'value': None, 'unit': 'm/px',
                      'inputs': [], 'note': 'The file has no recorded scale derivation or native-unit assignment. No conversion is inferred.'})
    arithmetic = quantitative.get('arithmetic') or []
    calc_rows = []
    terms = arithmetic[0].get('terms', []) if len(arithmetic) == 1 else []
    lookup = {(doc.doc_id, it.item_id): it for doc, it, _ in rows}
    for i, term in enumerate(terms):
        did, iid = term['doc_id'], term['item_id']
        it = lookup[(did, iid)]
        src = source(did, it.page, item_id=iid, bbox=it.bbox_px, file='elements.json' if it.source == 'ifc' else f'planmap-{it.page}.json')
        calc_rows.append({'item_id': iid, 'label': it.label or it.name or it.kind, 'values': {ctx['unit']: term['value']}, 'source': src})
        measure = term.get('measurement')
        if measure:
            steps.append({'id': f'measure-{i + 1}', 'label': 'Element measurement', 'expr': measure['formula'],
                          'value': term['value'], 'unit': ctx['unit'],
                          'inputs': [operand(f'operand {j + 1}', p['value'], p['unit'], src) for j, p in enumerate(measure['operands'])],
                          'note': 'Uses the scale recorded for this page. Outline and box errors are not measured.'})
    if terms:
        total = sum(t['value'] for t in terms)
        steps.append({'id': 'source-quantity-sum', 'label': 'Add source quantities', 'expr': 'sum(all calculation rows)',
                      'value': total, 'unit': ctx['unit'],
                      'inputs': [operand('source quantity', t['value'], ctx['unit'], calc_rows[i]['source']) for i, t in enumerate(terms)],
                      'note': 'All cited terms are retained in the table.'})
        if abs(total - ctx['value']) > 1e-12:
            steps.append({'id': 'display-rounding', 'label': 'Display rounding', 'expr': 'reported result = source sum + display rounding adjustment',
                          'value': ctx['value'], 'unit': ctx['unit'],
                          'inputs': [operand('source sum', total, ctx['unit'], {'calc_step': 'source-quantity-sum'}),
                                     operand('display rounding adjustment', ctx['value'] - total, ctx['unit'],
                                             {'answer_field': 'answer.value', 'calculation': 'reported value minus source sum'})],
                          'note': 'The source sum reproduces the reported result within its displayed precision.'})
    margin = copy.deepcopy(quantitative.get('margin') or {})
    spreads = []
    power = {'m': 1, 'm2': 2, 'm3': 3}[ctx['unit']]
    for did, page, proof in proofs:
        pct = proof.get('method_spread_pct')
        if pct is not None and math.isfinite(pct):
            contribution = sum(abs(t['value']) for t in terms if t['doc_id'] == did and lookup[(did, t['item_id'])].page == page)
            impact = contribution * ((1 + pct / 100) ** power - 1)
            spreads.append({'source': source(did, page), 'scale_pct': pct, 'value': impact if terms else None, 'unit': ctx['unit'],
                            'formula': f'page quantity × ((1 + scale spread/100)^{power} − 1)',
                            'why': 'Observed differences between methods only; not a physical error bound. Door prior excluded because its actual widths are unknown.'})
    if spreads:
        margin['method_spread'] = spreads
        if any((s['value'] or 0) > 0 for s in spreads):
            margin['why'] = margin.get('why', '') + ' Scale-method sensitivity is listed separately; it is not an accuracy guarantee.'
    quantitative['margin'] = margin
    if not terms:
        steps.append({'id': 'unreconciled-source-terms', 'label': 'Source terms unavailable', 'expr': '', 'value': None, 'unit': ctx['unit'],
                      'inputs': [], 'note': 'Rows excluded: cited quantities do not reconcile with the reported value; the complete arithmetic is unavailable.'})
    return {'calc': {'formula': arithmetic[0]['formula'] if terms else 'Reported result; full source arithmetic unavailable',
                     'steps': steps, 'rows': calc_rows,
                     'result': {'value': ctx['value'], 'unit': ctx['unit'], 'rounded_as': 'answer precision'},
                     'checks': checks, 'margin': margin}}


def supplement(res, question, root):
    """Routes with their own evidence card still receive scale/calc provenance."""
    card = res.get('reasoning') or {}
    ans = res.get('answer') or {}
    if card.get('calc') or ans.get('abstained'):
        return res
    ctx = {'root': Path(root), 'res': res, 'question': question, 'ans': ans,
           'cites': res.get('citations') or [], 'doc': None, 'steps': [],
           'unit': str(ans.get('unit') or '').replace('²', '2').replace('³', '3'), 'value': ans.get('value'),
           'models_used': any(s.get('model') for s in res.get('trace') or [])}
    from engine.reasoning_parts import margin
    quantitative = margin.run(ctx)
    if card.get('margin'):
        quantitative['margin'] = copy.deepcopy(card['margin'])
    extra = run(ctx, quantitative)
    if extra:
        card.update(extra)
        card['margin'] = quantitative['margin']
        res['reasoning'] = card
    return res
