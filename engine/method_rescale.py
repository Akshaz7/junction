"""Explain runtime rescaling against the untouched, original source operands."""
from engine.calc import close, input_value, number, source, step, step_source


def capture(calc, docs):
    extra, replacements = [], []
    for n, r in enumerate(calc.get('rows', [])):
        ref = r.get('source') or {}
        did, iid, pg = ref.get('doc_id'), ref.get('item_id'), ref.get('page', 1)
        doc = docs.get(did)
        if not doc: continue
        it = next((i for i in doc.items if i.item_id == iid and i.page == pg), None)
        adjustment = it.scale_adjustment if it else {}
        old = (adjustment.get('old_scale') or {}).get('m_per_px')
        new = (adjustment.get('new_scale') or {}).get('m_per_px')
        for key, change in adjustment.get('quantities', {}).items():
            value = r.get('values', {}).get(key)
            if not number(value) or not close(value, change['after']): continue
            sid = f'method-rescale-{n}-{key}'
            unit, power, precision = ('m2', 2, 2) if key == 'area_m2' else ('m', 1, 3)
            base = source(doc, it)
            chosen_ref = {'kind': 'measurement', 'doc_id': did, 'page': pg,
                          'record': {'selection': adjustment['new_scale']['selection'], 'm_per_px': new},
                          'text': 'Page scale selected before this answer; derivation is in method.scales and the scale steps.'}
            if number(change['before']) and number(old) and old > 0:
                before_field = next((k for k in ('area_m2', 'area_m2_label', 'area_m2_geom') if close(it.props.get(k), change['before'])), key) if key == 'area_m2' else key
                factor = new / old
                extra.append(step(sid + '-factor', 'Scale correction factor', 'selected metres per pixel / original metres per pixel', factor, 'factor',
                                  [input_value('selected scale', new, 'm/px', chosen_ref),
                                   input_value('original scale', old, 'm/px', {**base, 'kind': 'scale', 'item_id': None, 'field': 'scale.m_per_px'})], operation='divide'))
                raw = change['before'] * factor ** power
                extra.append(step(sid + '-raw', 'Recompute source quantity at selected scale', 'original quantity × correction factor' + ('²' if power == 2 else ''), raw, unit,
                                  [input_value('original quantity', change['before'], unit, {**base, 'field': 'props.' + before_field})] +
                                  [input_value('scale correction factor', factor, 'factor', step_source(sid + '-factor')) for _ in range(power)], operation='multiply'))
            elif key == 'area_m2':
                from engine.scale_text import _px_area
                px, basis = _px_area(it)
                if not number(px): continue
                raw = px * new * new
                extra.append(step(sid + '-raw', 'Measure scaled room area', 'pixel area × selected scale²', raw, unit,
                                  [input_value('pixel area', px, 'px2', {**base, 'field': 'props.area_px / polygon_px / bbox_px'}),
                                   input_value('selected scale', new, 'm/px', chosen_ref), input_value('selected scale', new, 'm/px', chosen_ref)],
                                  'Pixel area basis: ' + basis + '; a bounding box is an approximation.', 'multiply'))
            else: continue
            extra.append(step(sid, 'Round recomputed measurement', f'round(measurement, {precision})', value, unit,
                              [input_value('measurement', raw, unit, step_source(sid + '-raw')),
                               input_value('measurement decimal places', precision, 'decimal places', {'kind': 'policy', 'text': 'Scale-refinement measurement precision'})], operation='round'))
            replacements.append((did, iid, pg, value, unit, step_source(sid)))
            r['methods'] = [{'id': 'scale-updated-quantity', 'label': 'Quantity recomputed at the selected page scale',
                             'why_chosen': adjustment['new_scale']['selection']['why_chosen'], 'alternatives': []}]
            r['source'] = step_source(sid)
    for s in calc.get('steps', []):
        for inp in s.get('inputs', []):
            ref = inp.get('source') or {}
            for did, iid, pg, value, unit, replacement in replacements:
                if (ref.get('doc_id'), ref.get('item_id'), ref.get('page', 1)) == (did, iid, pg) and inp.get('unit') == unit and close(inp.get('value'), value):
                    inp['source'] = replacement
                    break
    calc['steps'] = extra + calc.get('steps', [])
