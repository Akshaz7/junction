"""Retain the actual order operands across the final evidence pipeline."""
from engine.calc import input_value, question_source, record, row, step, step_source, summed


def quantity(doc, label, typ, used, measured, need, pct, question, root, *, measurements=()):
    from engine.order import _floor_area, _number
    unit = 'count' if typ == 'count' else 'm' if typ == 'length' else 'm2'
    pairs = []
    for item in used:
        value = (1 if typ == 'count' else _floor_area(item, doc, root) if typ == 'floor' else
                 _number(item.q.get('net_wall_area_m2'), item.props.get('net_wall_area_m2')) if item.kind in ('room', 'space') else
                 _number(item.q.get('net_side_area_m2'), item.props.get('net_side_area_m2')))
        if value is not None:
            pairs.append((item, value))
    stub = {'answer': {'value': need, 'unit': unit}}
    calc = summed(stub, [row(doc, i, v, unit) for i, v in pairs], unit)
    if typ == 'length' and measurements:
        from engine.method_lengths import skirting
        calc = skirting(doc, measurements, stub)
    calc['steps'] = [s for s in calc['steps'] if s['id'] != 'result']
    if abs(next(s['value'] for s in calc['steps'] if s['id'] == 'sum') - measured) > 1e-8:
        calc['issues'] = ['Order measurement operands are unavailable; the recorded total cannot yet be replayed.']
    calc['steps'].extend([
        step('waste-fraction', 'Convert waste percentage', 'waste percent / 100', pct / 100, 'fraction',
             [input_value('waste', pct, '%', question_source(question)),
              input_value('percent divisor', 100, '%/fraction', {'kind': 'conversion', 'text': '100 percent = 1'})], operation='divide'),
        step('waste-factor', 'Include base quantity', '1 + waste fraction', 1 + pct / 100, 'factor',
             [input_value('base', 1, 'factor', {'kind': 'policy', 'text': 'The full measured quantity'}),
              input_value('waste fraction', pct / 100, 'fraction', step_source('waste-fraction'))], operation='sum'),
        step('order-raw', 'Apply waste', 'measured quantity × waste factor', measured * (1 + pct / 100), unit,
             [input_value('measured quantity', measured, unit, step_source('sum')),
              input_value('waste factor', 1 + pct / 100, 'factor', step_source('waste-factor'))], operation='multiply'),
        step('result', 'Round upward for ordering', 'ceil(quantity × precision − 1e-9) / precision', need, unit,
             [input_value('unrounded order', measured * (1 + pct / 100), unit, step_source('order-raw')),
              input_value('precision', 1 if typ == 'count' else 100, 'per unit', {'kind': 'policy', 'text': 'Whole items or hundredths of a measurement unit'})],
             note='The 1e-9 tolerance prevents floating-point noise from adding an extra ordering increment.', operation='order_ceil'),
    ])
    calc['formula'] += '; order = measured quantity × (1 + waste/100), rounded upward'
    return label, calc


def attach(res, parts):
    if len(parts) == 1 and not isinstance(res['answer']['value'], dict):
        return record(res, parts[0][1])
    if not parts:
        return res
    import copy
    calc = {'formula': 'Each material is measured and allowed for separately', 'steps': [], 'rows': [], 'checks': [],
            'result': {'value': res['answer']['value'], 'unit': 'quantities', 'rounded_as': 'upward per material'},
            'margin': {}, 'row_note': 'Rows are partitioned by material; materials can use the same source elements.'}
    for index, (label, part) in enumerate(parts):
        prefix = f'order-{index}-'
        for original in part['steps']:
            s = copy.deepcopy(original)
            s['id'] = f'category-{label}' if s['id'] == 'result' else prefix + s['id']
            for inp in s['inputs']:
                if inp['source'].get('kind') == 'step':
                    inp['source']['step_id'] = prefix + inp['source']['step_id']
            calc['steps'].append(s)
        calc['rows'].extend({**r, 'values': {**r['values'], 'material': label}} for r in part['rows'])
        calc.setdefault('issues', []).extend(part.get('issues', []))
    return record(res, calc)
