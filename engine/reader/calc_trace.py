"""Reader measurements retain planner coordinates, scale origin and exact maths."""
from engine.calc import input_value, step, step_source


def measurement(did, page, points, closed, mpp, origin, ref, *, ratio=None, dpi=None, supplied=False, root=None):
    from engine.scale_proof import read_json
    from pathlib import Path
    dpi_file = f'text-{page}.json' if root and read_json(Path(root) / did / f'text-{page}.json').get('dpi') else 'pages.json'
    return [{'tool': 'measure', 'doc_id': did, 'page': page, 'points': points, 'closed': closed,
             'm_per_px': mpp, 'scale_origin': origin, 'ratio': ratio, 'supplied_scale': supplied,
             'dpi': dpi, 'dpi_artifact': dpi_file,
             'evidence_ref': ref}]


def steps(record):
    out = []
    for index, entry in enumerate(record.get('calculations', [])):
        sid = f'reader-{index}'
        if entry['tool'] == 'view':
            ref = {'kind': 'measurement', 'doc_id': entry['doc_id'], 'page': entry['page'], 'bbox': entry['bbox'],
                   'record': entry, 'artifact': f'page-{entry["page"]}.png',
                   'text': 'Actual crop and model-input image sizes; the visual reading is a model observation, not a pixel measurement.'}
            for key in ('crop_width_px', 'crop_height_px', 'model_width_px', 'model_height_px'):
                out.append(step(sid + '-' + key, 'Reader view: ' + key, 'recorded image dimension', entry[key], 'px',
                                [input_value(key, entry[key], 'px', ref)], 'Vision model: ' + str(entry['model']), 'source'))
            continue
        if entry['tool'] == 'compute':
            ref = {'kind': 'model', 'doc_id': next(iter(record.get('doc_ids') or []), None),
                   'field': f'reader.calculations[{index}].expr', 'record': entry,
                   'text': 'Planner-supplied arithmetic expression; source operands require checking.'}
            out.append(step(sid, 'Reader arithmetic', entry['expr'], entry['value'], 'as requested',
                            [input_value('planner expression', entry['expr'], 'expression', ref)],
                            entry['note'], 'reader_compute'))
            continue
        if entry['tool'] != 'measure':
            continue
        from engine.reader.geom import polygon_area, polyline_length
        did, page, points = entry['doc_id'], entry['page'], entry['points']
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        ref = {'kind': 'model', 'doc_id': did, 'page': page, 'artifact': f'page-{page}.png',
               'bbox': [min(xs), min(ys), max(xs), max(ys)], 'record': entry,
               'text': 'Model-planned points on the page image, not independently detected survey points.'}
        operands = [input_value(f'point {i // 2 + 1} {"x" if i % 2 == 0 else "y"}', v, 'px', ref)
                    for i, v in enumerate(v for point in points for v in point)]
        scale_ref = {**ref, 'field': 'm_per_px', 'text': 'Planner-supplied scale; no independent source association' if entry['supplied_scale'] or entry.get('ratio') else 'Stored plan-map scale used by measurement'}
        scale = entry['m_per_px']
        if not entry['supplied_scale'] and not entry.get('ratio'):
            scale_ref = {'kind': 'scale', 'doc_id': did, 'page': page, 'artifact': f'planmap-{page}.json', 'field': 'scale.m_per_px'}
        elif not entry['supplied_scale'] and entry.get('ratio') and entry.get('dpi'):
            scale_id = sid + '-scale-conversion'
            out.append(step(scale_id, 'Reader ratio and DPI conversion', 'ratio × 0.0254 m/in / image DPI', scale, 'm/px',
                            [input_value('planner-supplied ratio', float(entry['ratio']), 'ratio', ref),
                             input_value('image resolution', entry['dpi'], 'px/in', {'kind': 'document', 'doc_id': did, 'page': page,
                                                                                   'artifact': entry['dpi_artifact'], 'field': 'dpi'}),
                             input_value('metres per inch', .0254, 'm/in', {'kind': 'conversion', 'text': '1 international inch = 0.0254 m'})],
                            'The ratio was supplied by the planner; this does not prove a printed label or an unchanged page size.', 'ratio_dpi'))
            scale_ref = step_source(scale_id)
        length = polyline_length(points, entry['closed'])
        out.append(step(sid + '-pixels', 'Reader polyline length', 'Σ sqrt((x₂−x₁)² + (y₂−y₁)²)', length, 'px', operands,
                        'Coordinates selected by the planner; closing edge included.' if entry['closed'] else 'Coordinates selected by the planner; open polyline.',
                        'polyline_closed' if entry['closed'] else 'polyline'))
        out.append(step(sid + '-length', 'Convert reader pixel length', 'pixel length × scale', length * scale, 'm',
                        [input_value('pixel length', length, 'px', step_source(sid + '-pixels')),
                         input_value('metres per pixel', scale, 'm/px', scale_ref)],
                        'Scale origin: ' + entry['scale_origin'] + '. Planner coordinates and any supplied scale remain unverified.', 'multiply'))
        if entry['closed'] and len(points) >= 3:
            area = polygon_area(points)
            out.append(step(sid + '-area-pixels', 'Reader enclosed pixel area', '½ |Σ(xᵢ yᵢ₊₁ − xᵢ₊₁ yᵢ)|', area, 'px2', operands,
                            'Shoelace formula on the planner-selected polygon.', 'polygon_area'))
            out.append(step(sid + '-area', 'Convert reader pixel area', 'pixel area × scale × scale', area * scale * scale, 'm2',
                            [input_value('pixel area', area, 'px2', step_source(sid + '-area-pixels')),
                             input_value('metres per pixel', scale, 'm/px', scale_ref), input_value('metres per pixel', scale, 'm/px', scale_ref)],
                            'Scale origin: ' + entry['scale_origin'] + '. Physical uncertainty was not measured.', 'multiply'))
    return out


def seed(res, record):
    """Use a selected reader measurement only when its arithmetic matches.

    This establishes arithmetic reproducibility, not correctness of the model's
    coordinates or a planner-supplied scale. Bare compute expressions retain an
    explicit grounding issue until their operands are linked to source data.
    """
    from engine.calc import number, places, record as keep
    ans = res.get('answer') or {}
    value = ans.get('value')
    if not number(value) or ans.get('abstained'):
        return res
    unit = (ans.get('unit') or '').replace('²', '2').replace('³', '3')
    candidates = steps(record)
    for s in reversed(candidates):
        if s['id'].split('-')[1].isdigit():
            entry = record['calculations'][int(s['id'].split('-')[1])]
        else:
            continue
        if entry.get('evidence_ref') not in record.get('selected_refs', []):
            continue
        if s['unit'] != unit or not number(s['value']) or round(s['value'], places(value)) != value:
            continue
        final = step('result', 'Round reader measurement for the answer', f'round({s["value"]}, {places(value)})', value, unit,
                     [input_value('reader measurement', s['value'], unit, step_source(s['id'])),
                      input_value('decimal places', places(value), 'decimal places', {'kind': 'policy', 'text': 'Precision of the reported answer'})], operation='round')
        # Only this measurement's steps contribute; all other tools remain
        # visible later as background observations.
        selected = [x for x in candidates if x['id'].startswith('-'.join(s['id'].split('-')[:2]) + '-')]
        return keep(res, {'formula': 'Reader geometry: pixel length × scale; area = pixel shoelace area × scale²',
                          'steps': selected + [final], 'rows': [],
                          'result': {'value': value, 'unit': unit, 'rounded_as': f'{places(value)} decimal places'},
                          'row_note': 'A model-planned polygon/polyline is replayed above; no independent element survey was recorded.',
                          'checks': [], 'margin': {}})
    return res
