"""IFC-WHY: which IFC quantity an answer was read from, and why no scale applies.

No models, network access or artifact writes. IFC quantities in elements.json
are already in metres (converted from the model's declared units at import),
so a width, height, length, thickness or area answer is a lookup, not a
measurement through a drawing scale. This module

* builds the calculation for IFC dimension answers from the exact field the
  value came from (quantities.width_m, ...), so the audit reproduces it;
* records the field on IFC area/volume rows that came without one;
* adds a visible "Measured" reasoning step naming element, GlobalId, field and
  the quantity's origin (IFC base quantity, attribute, property or bounding box);
* words the room-area basis (stored net, stored gross or measured footprint)
  and why that one was used.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

# Order matters: "thick" before width (a wall's width_m is its thickness).
DIMENSIONS = [
    ('thickness', re.compile(r'\b(?:thick\w*|thin(?:nest|ner)?|thickness)\b', re.I)),
    ('width', re.compile(r'\b(?:wide|wider|widest|width|widths|narrow\w*|breadth)\b', re.I)),
    ('height', re.compile(r'\b(?:tall\w*|height|heights|high|higher|highest)\b', re.I)),
    ('depth', re.compile(r'\b(?:deep\w*|depth)\b', re.I)),
    ('length', re.compile(r'\b(?:long|longer|longest|length|lengths)\b', re.I)),
]
FIELDS = {'width': ('width_m',), 'height': ('height_m',), 'depth': ('depth_m',), 'length': ('length_m',)}
THICKNESS = {'wall': ('thickness_m', 'width_m'), 'slab': ('thickness_m', 'depth_m', 'width_m'),
             'roof': ('thickness_m', 'depth_m', 'width_m'), 'door': ('thickness_m', 'depth_m'),
             'window': ('thickness_m', 'depth_m')}
MAX = re.compile(r'\b(?:longest|widest|tallest|highest|thickest|deepest|largest|biggest|greatest|max(?:imum)?)\b', re.I)
MIN = re.compile(r'\b(?:shortest|narrowest|thinnest|lowest|shallowest|smallest|min(?:imum)?)\b', re.I)
NAMES = {'width_m': 'Width', 'height_m': 'Height', 'length_m': 'Length', 'depth_m': 'Depth', 'thickness_m': 'Thickness',
         'area_m2': 'Area', 'net_area_m2': 'NetArea', 'gross_area_m2': 'GrossArea', 'net_side_area_m2': 'NetSideArea',
         'gross_side_area_m2': 'GrossSideArea', 'net_floor_area_m2': 'NetFloorArea', 'gross_floor_area_m2': 'GrossFloorArea',
         'net_footprint_area_m2': 'NetFootprintArea', 'gross_footprint_area_m2': 'GrossFootprintArea',
         'volume_m3': 'Volume', 'net_volume_m3': 'NetVolume', 'gross_volume_m3': 'GrossVolume',
         'perimeter_m': 'Perimeter', 'cross_section_area_m2': 'CrossSectionArea'}
ATTRIBUTES = {'width_m': 'OverallWidth', 'height_m': 'OverallHeight'}
UNITS = {'m': 'm', 'm2': 'm²', 'm3': 'm³'}
# Same preference order as engine.solvers.solve._qty, so an unlabelled row is
# attributed to the field the solver actually reads.
AREA_KEYS = {'room': ('selected_floor_area_m2', 'net_floor_area_m2', 'area_m2', 'net_area_m2', 'gross_area_m2'),
             '*': ('area_m2', 'net_area_m2', 'gross_area_m2', 'net_side_area_m2')}
VOLUME_KEYS = ('net_volume_m3', 'volume_m3', 'gross_volume_m3')


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _fmt(v, unit='m'):
    return f'{round(float(v), 4)} {UNITS.get(unit, unit)}'


def dimension(question):
    """The linear dimension a question asks for, or None."""
    for name, pattern in DIMENSIONS:
        if pattern.search(question or ''):
            return name
    return None


def fields_for(dim, kind):
    if dim == 'thickness':
        return THICKNESS.get(kind, ('thickness_m', 'width_m', 'depth_m'))
    return FIELDS.get(dim, ())


def pick(item, dim):
    """(value, field) for an IFC item's stored dimension; None when not stored."""
    q = item.q or {}
    for key in fields_for(dim, 'room' if item.kind == 'space' else item.kind):
        if _number(q.get(key)) and q[key] > 0:
            return float(q[key]), key
    return None


def origin(item, key):
    """Plain description of where an elements.json quantity came from."""
    how = ((item.props or {}).get('quantity_source') or {}).get(key)
    name = NAMES.get(key, key)
    if how == 'qto':
        return f'IFC base quantity {name}'
    if how == 'attribute':
        return f'Ifc{(item.kind or "element").capitalize()} attribute {ATTRIBUTES.get(key, name)}'
    if how == 'property':
        return f'IFC property {name}'
    if how == 'bbox':
        if key == 'height_m':
            return 'model bounding box: vertical extent (max y − min y)'
        return 'model bounding box: largest horizontal extent, max(x-extent, z-extent)'
    if how:
        return str(how)
    return f'stored quantity {name}'


def _bbox_check(item, key):
    """Recompute a bbox-derived value from bbox_m (rounded to 4 dp at import)."""
    b = item.bbox_m
    if not (isinstance(b, list) and len(b) == 2 and all(isinstance(p, list) and len(p) == 3 for p in b)):
        return None
    ext = [b[1][i] - b[0][i] for i in range(3)]
    if key == 'height_m':
        return ext[1], f'bbox y-extent {b[1][1]} − {b[0][1]}'
    axis = 0 if ext[0] >= ext[2] else 2
    return ext[axis], f'bbox {"x" if axis == 0 else "z"}-extent {b[1][axis]} − {b[0][axis]}'


def _gid(item):
    return item.item_id


def _units_text(doc):
    units = (doc.meta or {}).get('unit_provenance') if doc is not None else None
    factor = (units or {}).get('m_per_unit')
    if _number(factor) and abs(factor - 1) > 1e-12:
        return (f'Model lengths were converted to metres at import (× {factor:g} m per model unit); '
                'no drawing scale needed.')
    return 'Model units are metres; no drawing scale needed.'


def dimension_calc(res, question, root):
    """Calculation for an IFC width/height/length/thickness/depth answer.

    Returns None (caller keeps its default) unless every cited item is an IFC
    element with the asked-for stored quantity and the answer reproduces as
    that single value, the maximum/minimum, or the sum of those values.
    """
    from engine.calc import _cited, close, input_value, number, places, step, step_source, row
    ans = res.get('answer') or {}
    value = ans.get('value')
    if ans.get('abstained') or not number(value) or (ans.get('unit') or '') != 'm':
        return None
    dim = dimension(question)
    if not dim:
        return None
    items, missing = _cited(res, Path(root))
    if not items or missing or any(doc is None or doc.mode != 'ifc' or it.source != 'ifc' for doc, it in items):
        return None
    rows, steps = [], []
    for index, (doc, it) in enumerate(items):
        got = pick(it, dim)
        if not got:
            return None
        v, key = got
        r = row(doc, it, v, 'm', kind=it.kind)
        r['values'] = {key: v, 'kind': it.kind}
        if doc.meta.get('sheet_of'):
            r['source']['doc_id'] = doc.meta['sheet_of']
        r['source'].update(field=f'quantities.{key}', text=f'{it.name or it.kind} (GUID {_gid(it)}): {origin(it, key)}')
        r['ifc_quantity'] = {'field': f'quantities.{key}', 'origin': origin(it, key),
                             'quantity_source': ((it.props or {}).get('quantity_source') or {}).get(key)}
        if r['ifc_quantity']['quantity_source'] == 'bbox':
            check = _bbox_check(it, key)
            if check:
                r['ifc_quantity']['formula'] = f'{check[1]} = {check[0]:.4f} m'
        rows.append(r)
    vals = [next(v for k, v in r['values'].items() if k != 'kind') for r in rows]
    keys = {next(k for k in r['values'] if k != 'kind') for r in rows}
    nd = places(value)
    inputs = [input_value(r['label'], v, 'm', r['source']) for r, v in zip(rows, vals)]
    key = keys.pop() if len(keys) == 1 else None
    label = NAMES.get(key, 'dimension').lower() if key else 'dimension'
    if len(rows) == 1:
        steps.append(step('ifc-quantity', f'Read IFC {label}', f'quantities.{key}', vals[0], 'm', inputs,
                          f'{rows[0]["ifc_quantity"]["origin"]}. {_units_text(items[0][0])}', 'source'))
        agg = 'ifc-quantity'
    elif MAX.search(question) and close(round(max(vals), nd), value, 10 ** -nd / 2):
        steps.append(step('ifc-max', f'Largest IFC {label}', f'max(quantities.{key or "<dimension>"})', max(vals), 'm', inputs,
                          f'Ties are all cited. {_units_text(items[0][0])}', 'max'))
        agg = 'ifc-max'
    elif MIN.search(question) and close(round(min(vals), nd), value, 10 ** -nd / 2):
        steps.append(step('ifc-min', f'Smallest IFC {label}', f'min(quantities.{key or "<dimension>"})', min(vals), 'm', inputs,
                          f'Ties are all cited. {_units_text(items[0][0])}', 'min'))
        agg = 'ifc-min'
    elif close(round(math.fsum(vals), nd), value, 10 ** -nd / 2):
        steps.append(step('sum', f'Add IFC {label}s', ' + '.join(str(v) for v in vals), math.fsum(vals), 'm', inputs,
                          _units_text(items[0][0]), 'sum'))
        agg = 'sum'
    else:
        return None
    total = steps[-1]['value']
    if not close(round(total, nd), value, 10 ** -nd / 2):
        return None
    steps.append(step('result', 'Round for the answer', f'round({total}, {nd})', round(total, nd), 'm',
                      [input_value('IFC quantity', total, 'm', step_source(agg)),
                       input_value('decimal places', nd, 'decimal places', {'kind': 'policy', 'text': "Route's recorded answer precision"})],
                      operation='round'))
    if not close(round(total, nd), value):
        return None
    calc = {'formula': {'ifc-quantity': 'answer = stored IFC quantity (metres)', 'ifc-max': 'answer = max(stored IFC quantities)',
                        'ifc-min': 'answer = min(stored IFC quantities)', 'sum': 'total = Σ(stored IFC quantities)'}[agg],
            'steps': steps, 'rows': rows,
            'result': {'value': value, 'unit': 'm', 'rounded_as': f'{nd} decimal places'},
            'checks': [], 'margin': {}, 'issues': [], 'source_units': 'metres (IFC model quantities; no drawing scale)'}
    if agg == 'sum' and key:
        calc.update(row_key=key, row_total_step='sum')
    for r in rows:
        formula = r['ifc_quantity'].get('formula')
        if formula:
            recomputed = float(formula.rsplit('=', 1)[1].split()[0])
            stored = r['values'][r['ifc_quantity']['field'].split('.', 1)[1]]
            calc['checks'].append({'method': 'bounding-box extent versus stored value', 'value': recomputed, 'reported_value': stored,
                                   'agrees': abs(recomputed - stored) <= 5e-4, 'diff_pct': abs(recomputed - stored) / stored * 100 if stored else None,
                                   'source': r['source'], 'note': f'{formula}; bbox_m is rounded to 4 decimals at import.'})
    return calc


def label_rows(calc, root):
    """Name the elements.json field of IFC rows recorded without one (exact value match only)."""
    unit = (calc.get('result') or {}).get('unit')
    if unit not in ('m2', 'm3', 'm'):
        return
    from engine.solvers.data import load_doc, load_sheet_parent
    docs = {}
    for r in calc.get('rows') or []:
        src = r.get('source') or {}
        if src.get('field') or src.get('artifact') != 'elements.json' or not src.get('item_id'):
            continue
        did = src.get('doc_id')
        if did not in docs:
            try:
                docs[did] = load_doc(did, Path(root)) or load_sheet_parent(did, Path(root))
            except (OSError, ValueError, KeyError, TypeError):
                docs[did] = None
        doc = docs[did]
        it = next((i for i in doc.items if i.item_id == src['item_id']), None) if doc else None
        value = next((v for k, v in (r.get('values') or {}).items() if k != 'kind' and _number(v)), None)
        if it is None or value is None:
            continue
        kind = 'room' if it.kind in ('room', 'space') else it.kind
        keys = (AREA_KEYS.get(kind, AREA_KEYS['*']) if unit == 'm2' else VOLUME_KEYS if unit == 'm3'
                else ('length_m', 'width_m', 'height_m', 'thickness_m', 'depth_m', 'perimeter_m'))
        key = next((k for k in keys if _number((it.q or {}).get(k)) and abs(it.q[k] - value) <= 1e-9 * max(1, abs(value))), None)
        if key:
            src['field'] = f'quantities.{key}'
            r['ifc_quantity'] = {'field': src['field'], 'origin': origin(it, key),
                                 'quantity_source': ((it.props or {}).get('quantity_source') or {}).get(key)}


def _name(r):
    return str(r.get('label') or (r.get('values') or {}).get('kind') or 'element')


def measured_text(calc, doc=None):
    """One sentence naming the IFC source quantity of every calc row, or None."""
    rows = [r for r in calc.get('rows') or [] if r.get('ifc_quantity')]
    if not rows or len(rows) != len(calc.get('rows') or []):
        return None
    unit = (calc.get('result') or {}).get('unit') or 'm'
    fields = {r['ifc_quantity']['field'] for r in rows}
    origins = {r['ifc_quantity']['origin'] for r in rows}
    field = fields.pop() if len(fields) == 1 else 'quantities.*'
    vals = [next(v for k, v in r['values'].items() if k != 'kind') for r in rows]
    tail = _units_text(doc)
    if len(rows) == 1:
        r = rows[0]
        how = r['ifc_quantity']['origin']
        extra = f'; {r["ifc_quantity"]["formula"]}' if r['ifc_quantity'].get('formula') else ''
        return (f'Read from the IFC model: {_name(r)} (GUID {r["source"].get("item_id")}) '
                f'{how.split()[-1] if r["ifc_quantity"].get("quantity_source") in ("qto", "attribute", "property") else NAMES.get(field.split(".")[-1], field)} '
                f'{_fmt(vals[0], unit)} ({field}, {how}{extra}). {tail}')
    op = next((s for s in calc.get('steps') or [] if s.get('id') in ('ifc-max', 'ifc-min')), None)
    lead = f'Read from the IFC model: {len(rows)} {field.split(".")[-1].replace("_m2", "").replace("_m3", "").replace("_m", "").replace("_", " ")} values ({field}, {", ".join(sorted(origins))}).'
    if op:
        best = [r for r, v in zip(rows, vals) if abs(v - op['value']) <= 1e-9]
        names = ', '.join(f'{_name(r)} (GUID {r["source"].get("item_id")})' for r in best[:3]) + (' …' if len(best) > 3 else '')
        word = 'largest' if op['id'] == 'ifc-max' else 'smallest'
        return f'{lead} The {word} is {_fmt(op["value"], unit)}: {names}. {tail}'
    return f'{lead} Their sum is {_fmt(math.fsum(vals), unit)}. {tail}'


def add_measured_step(res, calc, root):
    """Visible "Measured" step for IFC-quantity answers; never replaces an existing one."""
    card = res.get('reasoning')
    if not isinstance(card, dict) or (res.get('answer') or {}).get('abstained'):
        return
    steps = card.setdefault('steps', [])
    if any(s.get('kind') == 'measured' for s in steps):
        return
    doc = None
    did = next((r['source'].get('doc_id') for r in calc.get('rows') or [] if r.get('ifc_quantity')), None)
    if did:
        try:
            from engine.solvers.data import load_doc, load_sheet_parent
            doc = load_doc(did, Path(root)) or load_sheet_parent(did, Path(root))
        except (OSError, ValueError, KeyError, TypeError):
            doc = None
    text = measured_text(calc, doc)
    if not text:
        return
    ids = {r['source'].get('item_id') for r in calc.get('rows') or []}
    cite = next((c.get('n') for c in res.get('citations') or [] if ids & set(c.get('item_ids') or [])), None)
    at = max((i + 1 for i, s in enumerate(steps) if s.get('kind') == 'found'), default=0)
    steps.insert(at, {'id': 'ifc-measured', 'kind': 'measured', 'title': 'Measured', 'text': text, 'cite': cite, 'ok': None})
    op = next((s for s in calc.get('steps') or [] if s.get('id') in ('ifc-max', 'ifc-min')), None)
    if op and not any(s.get('kind') == 'calculated' for s in steps):
        unit = UNITS.get((calc.get('result') or {}).get('unit') or 'm', 'm')
        vals = [i.get('value') for i in op.get('inputs') or []]
        shown = ', '.join(str(v) for v in vals[:6]) + (', …' if len(vals) > 6 else '')
        steps.insert(at + 1, {'id': 'ifc-calculated', 'kind': 'calculated', 'title': 'Calculated',
                              'text': f'{"max" if op["id"] == "ifc-max" else "min"}({shown}) = {_fmt(op["value"], unit)}'
                                      f'{" (ties are all cited)" if sum(abs(v - op["value"]) <= 1e-9 for v in vals) > 1 else ""}.',
                              'cite': None, 'ok': None})


BASIS_WHY = {
    'stored gross floor area': 'an unqualified total floor area uses the stored gross floor area (IFC base quantity GrossFloorArea)',
    'stored net floor area': 'a room area uses its stored net floor area (IFC base quantity NetFloorArea) unless a total or gross area is asked for',
    'measured footprint': 'a net area was asked for and the footprint measured from the IfcSpace geometry does not just repeat the gross area',
    'stored area (geometry unavailable)': 'no footprint could be measured, so the stored area quantity is used',
}


def area_basis_text(rooms):
    """'Used: …' sentence for IFC room areas: which basis was used and why (empty when unknown)."""
    from collections import Counter
    bases = Counter(i.props.get('selected_area_basis') for i in rooms if i.props.get('selected_area_basis'))
    if not bases:
        return ''
    parts = []
    for basis, n in bases.most_common():
        total = math.fsum(float(i.q['selected_floor_area_m2']) for i in rooms
                          if i.props.get('selected_area_basis') == basis and _number(i.q.get('selected_floor_area_m2')))
        why = BASIS_WHY.get(basis)
        if basis == 'stored gross floor area' and not any(i.q.get('net_floor_area_m2') is not None for i in rooms
                                                         if i.props.get('selected_area_basis') == basis):
            why = 'no stored net area exists, so the stored gross floor area is used'
        if basis == 'measured footprint' and not any(i.q.get('net_floor_area_m2') is not None or i.q.get('gross_floor_area_m2') is not None
                                                    for i in rooms if i.props.get('selected_area_basis') == basis):
            why = 'no stored area quantity exists, so the footprint measured from the IfcSpace geometry is used'
        parts.append(f'{basis} for {n} room{"s" if n != 1 else ""} ({_fmt(total, "m2")})' + (f', because {why}' if why else ''))
    gross_geo = sum(bool(i.props.get('footprint_basis')) for i in rooms)
    note = (f' The measured footprint matches the stored gross area for {gross_geo} of {len(rooms)} rooms, so it confirms gross, not net.'
            if gross_geo else '')
    return 'Used: ' + '; '.join(parts) + '. Model units are metres; no drawing scale needed.' + note
