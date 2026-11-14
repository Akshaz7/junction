"""Tailor calculation provenance to the sources and operations actually used.

Pure JSON enrichment; source arithmetic stays in the route's calc hooks. Reader
and vision traces belong to EVINT. No guesses about missing native provenance.
"""
from __future__ import annotations

from pathlib import Path

from engine.calc import close, input_value, number, step, unit_name, validate
from engine.scale_proof import read_json


def _records(root, did, page):
    folder = root / did
    native = folder / 'elements.json'
    artifact = 'elements.json' if native.is_file() else f'planmap-{page}.json'
    data = read_json(folder / artifact)
    data = data if isinstance(data, dict) else {}
    return artifact, data, {r['item_id']: r for r in data.get('elements', data.get('items', []))
                            if isinstance(r, dict) and r.get('item_id')}


def _quantity(row, raw, artifact):
    """Report the actual stored operand, including its recorded Qto/geometry origin."""
    values = row.get('values') or {}
    q, props = raw.get('quantities') or {}, raw.get('props') or {}
    methods = []
    priorities = {'area_m2': ('net_floor_area_m2', 'area_m2', 'net_area_m2', 'gross_area_m2') if raw.get('kind') in ('room', 'space') else
                  ('area_m2', 'net_area_m2', 'gross_area_m2', 'net_side_area_m2'),
                  'volume_m3': ('net_volume_m3', 'volume_m3', 'gross_volume_m3'), 'length_m': ('length_m',)}
    for key, fields in priorities.items():
        value = values.get(key)
        if not number(value): continue
        if artifact == 'elements.json':
            used = next((f for f in fields if number(q.get(f)) and close(float(q[f]), value, .005)), None)
            if used:
                origin = (raw.get('quantity_source') or {}).get(used)
                methods.append({'id': 'ifc-' + (origin or 'stored-quantity'), 'label': f"Model {used.replace('_', ' ')}",
                                'field': 'quantities.' + used, 'value': value, 'unit': key,
                                'why_chosen': 'Recorded operand used by the solver. ' +
                                (f"Extraction origin: {origin}." if origin else 'The original Qto/geometry extraction was not recorded.'),
                                'alternatives': [{'id': f, 'value': q[f], 'rejected_because': 'Not the operand used for this row; source-field priority is explicit.'}
                                                 for f in fields if f != used and number(q.get(f))]})
        elif key == 'area_m2':
            # Loader priority is area_m2, then printed label, then polygon area.
            used = next((f for f in ('area_m2', 'area_m2_label', 'area_m2_geom')
                         if number(props.get(f)) and close(props[f], value, .005)), None)
            if used:
                methods.append({'id': 'printed-area' if used == 'area_m2_label' else 'polygon-area' if used == 'area_m2_geom' else 'stored-area',
                                'label': 'Printed room area' if used == 'area_m2_label' else 'Recorded plan area',
                                'field': 'props.' + used, 'value': value, 'unit': 'm2',
                                'why_chosen': 'This is the stored area field used for this row; no scale is applied twice.', 'alternatives': []})
    if values.get('count') in (0, 1):
        methods.append({'id': 'indexed-item', 'label': 'One indexed item',
                        'why_chosen': 'Unique indexed item after the route filters; grouped rows may contribute zero.', 'alternatives': []})
    if methods: row['methods'] = methods
    row['classification'] = {k: v for k, v in {'entity_type': raw.get('ifc_class'), 'kind': raw.get('kind'),
                                             'storey': (raw.get('storey') or {}).get('name') if isinstance(raw.get('storey'), dict) else raw.get('storey'),
                                             'dxf_layer': props.get('dxf_layer'), 'dxf_block': props.get('dxf_block')}.items() if v is not None}


def _text_calc(res):
    """Text answers expose their cited records without fabricating a numeric total."""
    return {'formula': 'Read the cited source records; no numeric aggregation was performed',
            'steps': [], 'rows': [], 'checks': [], 'margin': (res.get('reasoning') or {}).get('margin') or {},
            'result': {'value': (res.get('answer') or {}).get('value'), 'unit': unit_name((res.get('answer') or {}).get('unit')),
                       'mode': 'per-element', 'rounded_as': 'source text'}, 'issues': []}


def attach(res, question, root):
    root = Path(root)
    ans = res.get('answer') or {}
    if ans.get('abstained'): return res
    value = ans.get('value')
    if value is not None and not number(value) and not (isinstance(value, dict) and value and all(number(v) for v in value.values())):
        return res
    trace = res.get('trace') or []
    if value is None and not trace: return res
    if any(str(t.get('step', '')).startswith(('reader', 'readdraw', 'vision', 'symbol')) for t in trace): return res
    cache, scopes = {}, []
    dids = list(dict.fromkeys([*(res.get('doc_ids') or []), *(c.get('doc_id') for c in res.get('citations') or [] if c.get('doc_id'))]))
    for did in dids:
        artifact, data, items = _records(root, did, 1)
        if not data: continue
        # EVINT owns detector/segmenter/vision output methods.
        if artifact != 'elements.json' and any(i.get('source') in ('det', 'seg', 'vlm', 'vision') for i in items.values()): return res
        cache[(did, 1)] = artifact, data, items
    card = res.setdefault('reasoning', {'steps': [], 'confidence': {'label': 'Estimate', 'pct': None,
                                                                  'reason': 'Source trace; no independently measured accuracy.'}})
    calc = card.get('calc')
    if not calc:
        calc = card['calc'] = _text_calc(res)
    filters = [{'step': t.get('step'), 'detail': t.get('detail', '')} for t in trace
               if t.get('step') in ('route', 'load', 'filter', 'scope', 'scene', 'order_measure', 'order_compute', 'revision_compare', 'count', 'compute', 'calculate')]
    conditions = res.get('conditions') or {}
    filters.extend({'step': 'applied condition', 'detail': c} for c in conditions.get('applied', []))
    filters.extend({'step': 'unresolved condition', 'detail': c} for c in conditions.get('left', []))
    for r in calc.get('rows', []):
        ref = r.get('source') or {}
        did, pg = ref.get('doc_id'), ref.get('page', 1)
        if not did: continue
        if (did, pg) not in cache: cache[(did, pg)] = _records(root, did, pg)
        artifact, _, items = cache[(did, pg)]
        raw = items.get(ref.get('item_id'))
        if raw: _quantity(r, raw, artifact)
    population_steps = []
    for (did, pg), (artifact, data, items) in cache.items():
        if not data: continue
        if artifact == 'elements.json' and any(s['doc_id'] == did for s in scopes): continue
        cited_ids = {iid for c in res.get('citations') or [] if c.get('doc_id') == did
                     and (artifact == 'elements.json' or c.get('page', 1) == pg) for iid in c.get('item_ids') or []}
        included = [i for iid, i in items.items() if iid in cited_ids]
        classes = lambda rs: sorted({i.get('ifc_class') or i.get('kind') or 'unclassified' for i in rs})
        scope = {'doc_id': did, 'page': pg, 'artifact': artifact, 'population': len(items),
                 'cited_items': len(included), 'included_entity_types': classes(included),
                 'uncited_entity_types': classes([i for iid, i in items.items() if iid not in cited_ids]),
                 'storey_assignment': ('Uses the indexed element.storey.name; no reassignment by label or elevation during this answer.'
                                       if artifact == 'elements.json' else 'Uses the plan-map page; sheets may have different scales.'),
                 'note': 'Cited inventory is evidence, not necessarily the full selected population for summaries and comparisons.'}
        if artifact != 'elements.json':
            scope['cad_counting_rule'] = ('Count classified plan-map items, not individual symbol strokes. '
                                          'Where retained, layer/block names are listed per row; missing original CAD entity handles/layers cannot be reconstructed from this artifact.')
        else:
            scope['units'] = data.get('units')
            scope['unit_provenance'] = data.get('unit_provenance') or {
                'note': 'Quantities and bounding boxes are stored in metres. Original native-unit conversion operands are absent; no additional conversion was applied.'}
        scopes.append(scope)
        ref = {'kind': 'document', 'doc_id': did, 'page': pg, 'artifact': artifact, 'field': 'elements' if artifact == 'elements.json' else 'items'}
        population_steps.append(step(f'method-scope-{len(scopes)}', 'Indexed source inventory', 'number of indexed source records before this question', len(items), 'count',
                                     [input_value('indexed records', len(items), 'count', ref)], scope['storey_assignment'], 'source'))
    route_details = '; '.join(t.get('detail', '') for t in trace if t.get('step') in ('route', 'revision_compare', 'scene', 'props'))
    formula = calc.get('formula', '')
    kinds = {s['artifact'] for s in scopes}
    method_id = ('complex:' + conditions['handler'] if conditions.get('handler') else 'wall-face-geometry' if res.get('wallarea') else 'revision-comparison' if any(t.get('step') == 'revision_compare' for t in trace)
                 else 'order-allowance' if any(t.get('step', '').startswith('order_') for t in trace)
                 else 'multi-document-combination' if 'multi-document' in route_details or 'selected-document total' in route_details
                 else 'ifc-index' if 'elements.json' in kinds else 'cad-planmap' if scopes else 'cited-text')
    # A producer's explicit choice takes precedence over post-hoc classification.
    calc.setdefault('method', res.pop('_calc_method', None) or {'id': method_id, 'label': formula,
                     'why_chosen': route_details or 'Uses the cited source records available to this route.', 'alternatives': []})
    if any(number(r.get('values', {}).get(k)) for r in calc.get('rows', []) for k in ('area_m2', 'length_m', 'volume_m3')):
        from engine.solvers.data import load_doc
        from engine.scale_calc import steps as scale_steps
        loaded, selections = {}, []
        for scope in scopes:
            if scope['artifact'] == 'elements.json': continue
            did, pg = scope['doc_id'], scope['page']
            if did not in loaded: loaded[did] = load_doc(did, root)
            doc = loaded[did]
            sc = (doc.meta.get('page_scales') or {}).get(pg) if doc else None
            if not sc: continue
            selections.append({'doc_id': did, 'page': pg, **sc['selection']})
            population_steps.extend(scale_steps(sc, did, pg))
        if selections: calc['method']['scales'] = selections
        from engine.method_rescale import capture as capture_rescale
        capture_rescale(calc, loaded)
    calc['scope'] = {'sources': scopes, 'filters': filters}
    calc['steps'] = population_steps + calc.get('steps', [])
    if ans.get('value') is None:
        calc['sources'] = [{k: c.get(k) for k in ('doc_id', 'page', 'item_ids', 'bbox_px', 'quote') if c.get(k) is not None}
                           for c in res.get('citations') or []]
    issues = validate(calc, root)
    calc['issues'] = issues
    calc['status'] = 'incomplete' if issues else 'source-only' if ans.get('value') is None and not calc.get('rows') else 'complete'
    return res
