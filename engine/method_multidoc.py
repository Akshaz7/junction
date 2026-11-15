"""Retain the project combiner's actual selected sources and group arithmetic."""
from engine.calc import input_value, places, record, row, step, step_source, summed
from engine.calc_routes import append_calculation
from engine.projects.combine import PLURAL
from engine.solvers.solve import _qty


def capture(res, combined, picks, area, detail):
    steps, rows, selections, groups, additional = [], [], [], [], []
    for n, (level, kind) in enumerate(picks):
        did = level.chosen.get(kind)
        if did is None: continue
        doc = combined.infos[did].doc
        stats = level.docs[did][kind]
        unit = 'm2' if area else 'count'
        pairs = [(i, _qty(i, 'room', 'area') if area else 1) for i in doc.items if i.item_id in set(stats['ids']) and i.kind == kind]
        pairs = [(i, value) for i, value in pairs if value is not None]
        value = stats['area' if area else 'n']
        child = summed({'answer': {'value': value, 'unit': unit}}, [row(doc, i, v, unit) for i, v in pairs], unit,
                       'sum selected source items for this building, level and kind')
        prefix = f'level-{n}-'
        dest = {'steps': steps, 'rows': rows, 'result': {}}
        append_calculation(dest, child, prefix, neutralize_count=False)
        additional.extend(dest['result'].get('additional', []))
        groups.append((kind, input_value(level.name, value, unit, step_source(prefix + 'result'))))
        selections.append({'building_group': level.group, 'level': level.name, 'kind': kind, 'doc_id': did,
                           'value': value, 'unit': unit,
                           'why_chosen': 'Model first; otherwise highest item population; document ID breaks exact ties. Derived sheets are not independent checks.',
                           'alternatives': [{'id': other, 'value': stat[kind]['area' if area else 'n'],
                                             'rejected_because': 'Same building/level/kind; source selection keeps one source to avoid adding duplicate representations.'}
                                            for other, stat in level.docs.items() if other != did]})
    result = res['answer']['value']
    method = {'id': 'multi-document-combination', 'label': detail,
              'why_chosen': 'Group by building and level, then choose one source per kind before combining.',
              'alternatives': [{'id': d, 'rejected_because': 'Level could not be placed; omitted from the combined quantity.'} for d in combined.unplaced],
              'selections': selections}
    calc = {'formula': 'Combine only the chosen source for each building, level and kind', 'steps': steps, 'rows': rows,
            'checks': [], 'margin': {}, 'method': method,
            'result': {'value': result, 'unit': 'm2' if area else 'count', 'rounded_as': 'answer precision', 'additional': additional}}
    comparison = 'level comparison' in detail
    if isinstance(result, dict):
        for kind, plural in PLURAL.items():
            if plural not in result: continue
            operands = [i for k, i in groups if k == kind]
            steps.append(step('category-' + plural, f'Compare {plural}', 'first selected level − second selected level', result[plural], 'count', operands, operation='subtract'))
    elif result is not None:
        operands = [i for _, i in groups]
        operation = 'subtract' if comparison else 'source' if 'level ranking' in detail else 'sum'
        if operation == 'source': operands = operands[:1]  # ties each have the same winning quantity
        from engine.calc import evaluate
        raw = evaluate(operation, [i['value'] for i in operands])
        steps.append(step('combined-levels', 'Combine selected level quantities', 'first − second' if comparison else 'winning level quantity' if operation == 'source' else 'sum(chosen level quantities)', raw,
                          'm2' if area else 'count', operands, operation=operation))
        steps.append(step('result', 'Round combined answer', f'round(combined, {places(result)})', result, 'm2' if area else 'count',
                          [input_value('combined quantity', raw, 'm2' if area else 'count', step_source('combined-levels')),
                           input_value('decimal places', places(result), 'decimal places', {'kind': 'policy', 'text': 'Precision used by the project answer'})], operation='round'))
    else:
        calc['result']['mode'] = 'per-element'
    return record(res, calc)
