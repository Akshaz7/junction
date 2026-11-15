"""Replay scale candidate arithmetic using the common calculation schema."""
from engine.calc import input_value, step, step_source


def reference(raw, did, page, candidate):
    if raw.get('assumption'):
        return {'kind': 'assumption', 'text': raw['assumption']}
    if raw.get('definition'):
        return {'kind': 'conversion', 'text': raw['definition']}
    if raw.get('file'):
        return {**raw, 'kind': 'document', 'doc_id': raw.get('doc_id') or did,
                'page': raw.get('page') or page, 'artifact': raw['file'], 'field': raw.get('pointer', ''),
                # OCR dimension identifiers need not be plan-map item ids.
                'item_id': None}
    return {'kind': 'measurement', 'doc_id': did, 'page': page,
            'record': {'candidate': candidate['method'], **raw},
            'text': 'Recorded scale-candidate measurement; see its original label/line coordinates.'}


def steps(scale, did, page):
    out = []
    for n, c in enumerate(scale.get('candidates') or []):
        prefix = f'method-scale-{did}-{page}-{n}'
        inputs = [input_value(i['name'], i['value'], i['unit'], reference(i.get('source') or {}, did, page, c)) for i in c['inputs']]
        method, value = c['method'], c['m_per_px']
        if not isinstance(method, str): continue

        def add(suffix, label, expr, value, unit, ins, op):
            sid = prefix + '-' + suffix
            out.append(step(sid, label, expr, value, unit, ins, c.get('note', ''), op))
            return input_value(label, value, unit, step_source(sid))

        if c.get('stored_only'):
            add('stored', 'Recorded page scale', c['formula'], value, 'm/px', inputs, 'source')
        elif method in ('dimension', 'dimensions', 'known-size') and len(inputs) == 3:
            metres = inputs[0]['value'] * inputs[1]['value']
            converted = add('metres', 'Convert measured physical length', 'printed length × metres per printed unit', metres, 'm', inputs[:2], 'multiply')
            add('scale', 'Scale from matched length', 'physical length / measured pixel span', value, 'm/px', [converted, inputs[2]], 'divide')
        elif method == 'ratio-dpi' and len(inputs) >= 3:
            dpi = inputs[1]['value']
            resolution = inputs[1]
            if len(inputs) > 3:
                dpi *= inputs[3]['value']
                resolution = add('resolution', 'Apply image resizing to DPI', 'render DPI × uniform resize factor', dpi, 'px/in', [inputs[1], inputs[3]], 'multiply')
            metres = add('metres', 'Convert printed ratio to metres per inch', 'ratio × 0.0254 m/in', inputs[0]['value'] * inputs[2]['value'], 'm/in', [inputs[0], inputs[2]], 'multiply')
            add('scale', 'Printed ratio at recorded DPI', 'metres per inch / pixels per inch', value, 'm/px', [metres, resolution], 'divide')
        elif method == 'ratio-sheet' and len(inputs) == 4:
            metres = add('metres', 'Full sheet physical span', 'ratio × paper long side × metres per millimetre', inputs[0]['value'] * inputs[1]['value'] * inputs[2]['value'], 'm', inputs[:3], 'multiply')
            add('scale', 'Full paper sheet scale', 'physical sheet span / long image side', value, 'm/px', [metres, inputs[3]], 'divide')
        elif method == 'door-prior' and len(inputs) > 2:
            from statistics import median
            px = median(i['value'] for i in inputs[1:])
            width = add('median', 'Median door icon width', 'median(all recorded door icon widths)', px, 'px', inputs[1:], 'median')
            add('scale', 'Door-width assumption', 'assumed physical door width / median icon width', value, 'm/px', [inputs[0], width], 'divide')
        elif method in ('scalebar', 'scale-bar') and len(inputs) >= 4:
            labels, span, factor = inputs[:-2], inputs[-2], inputs[-1]
            delta = labels[-1]['value'] - labels[0]['value']
            length = add('labels', 'Scale bar label difference', 'last label − first label', delta, labels[0]['unit'], [labels[-1], labels[0]], 'subtract')
            metres = add('metres', 'Scale bar distance in metres', 'label difference × metres per printed unit', delta * factor['value'], 'm', [length, factor], 'multiply')
            add('scale', 'Scale bar pixel mapping', 'physical bar span / pixel span', value, 'm/px', [metres, span], 'divide')
        elif method == 'ifc' and len(inputs) == 1:
            one = input_value('one metre', 1, 'm', {'kind': 'conversion', 'text': 'A metre projected at the recorded pixels per metre'})
            add('scale', 'IFC plan projection', '1 / pixels per metre', value, 'm/px', [one, inputs[0]], 'divide')
        elif method.startswith('dxf'):
            native = next((i for i in inputs if i['unit'] == 'm/native unit'), None)
            signed = next((i for i in inputs if i['unit'] == 'px/native unit'), None)
            if native and signed:
                magnitude = add('magnitude', 'CAD registration magnitude', 'abs(signed pixels per drawing unit)', abs(signed['value']), 'px/native unit', [signed], 'abs')
                add('scale', 'Declared CAD units and registration', 'metres per drawing unit / pixels per drawing unit', value, 'm/px', [native, magnitude], 'divide')
    return out
