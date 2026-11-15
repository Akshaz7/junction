"""Property-filter operands, including original property paths and missing data."""
from dataclasses import asdict

from engine.calc import input_value, number, record, step, summed


def capture(res, records, checked, total, source):
    from engine.props import request
    req = request(res['question'])
    method = {'id': 'recorded-property-filter', 'label': 'Read recorded element properties',
              'why_chosen': 'Uses ' + source + '; missing requested properties remain unknown.', 'alternatives': [],
              'filters': asdict(req) if req else {}, 'checked_elements': checked, 'scope_elements': total}
    rows, steps, results = [], [], []
    value = res['answer'].get('value')
    for n, rec in enumerate(records):
        ref = {'kind': 'measurement', 'doc_id': res['doc_ids'][0], 'page': rec.item.page, 'item_id': rec.item.item_id,
               'bbox': rec.item.bbox_px, 'record': {'values': rec.values, 'property_paths': rec.sources},
               'text': 'Property extraction snapshot from ' + source}
        rows.append({'item_id': rec.item.item_id, 'label': rec.item.name or rec.item.label or rec.item.kind,
                     'values': {**rec.values, **({'count': int(value != 0)} if value is not None else {})}, 'source': ref})
        for key, v in rec.values.items():
            if not number(v): continue
            sid = f'property-{n}-{key}'
            unit = 'm2' if key.endswith('_m2') else 'm' if key.endswith('_m') else 'count' if key.endswith('_count') else 'source unit'
            steps.append(step(sid, key.replace('_', ' '), 'recorded property value', v, unit,
                              [input_value(key, v, unit, {**ref, 'field': rec.sources.get(key, key)})], operation='source'))
            results.append({'label': key, 'value': v, 'unit': unit, 'step_id': sid})
    if value is not None:
        calc = summed(res, rows, 'count', 'matches = Σ(1 per element passing every recorded filter)', steps,
                      note='For a zero-match answer, cited population rows each contribute zero; unknown properties are not converted to zero matches.')
    else:
        calc = {'formula': 'Read each requested property independently', 'steps': steps, 'rows': rows, 'checks': [], 'margin': {},
                'result': {'value': None, 'unit': '', 'mode': 'per-element', 'rounded_as': 'recorded precision'}}
    calc['result']['additional'] = results
    calc['method'] = method
    return record(res, calc)
