"""ACC-IFC: occurrence hierarchy and measured space footprints, in SI.

Independent of the IFCQTY sidecar: existing quantity consumers keep their format.
No inferred dimensions, bounding-box areas or exporter-specific corrections.
"""
from __future__ import annotations

import math
import re

VERSION = 1
# Product taxonomy, not a fitted symbol heuristic. See results/final/ACC-IFC/constants.json.
FAMILIES = (
    ('IfcStair', 'stairs'), ('IfcStairFlight', 'stairs'),
    ('IfcRamp', 'ramp'), ('IfcRampFlight', 'ramp'), ('IfcWall', 'wall'),
    ('IfcDoor', 'door'), ('IfcWindow', 'window'), ('IfcSpace', 'room'),
    ('IfcSlab', 'slab'), ('IfcColumn', 'column'), ('IfcBeam', 'beam'),
    ('IfcRoof', 'roof'), ('IfcRailing', 'railing'),
)
PROXY_TERMS = {
    'stairs': r'stairs?|staircases?|stairways?|treppen?|portaat|porras|trappor|trappa',
    'door': r'doors?|t[uü]r(?:en)?|ovi|ovet|d[oö]rr(?:ar)?',
    'window': r'windows?|fenster|ikkuna(?:t)?|f[oö]nster',
    'room': r'rooms?|spaces?|raum|r[aä]ume|huone(?:et)?|rum',
    'wall': r'walls?|w[aä]nde?|wand|sein[aä](?:t)?|v[aä]gg(?:ar)?',
}
PART_WORDS = re.compile(r'\b(?:flights?|landings?|treads?|risers?|railings?|handrails?|parts?|components?|'
                        r'podest\w*|stufen?|treppenlauf|kaide\w*|askel\w*|r[aä]cke\w*)\b', re.I)


def proxy_kind(el):
    """Only explicit occurrence names/ObjectType; never a guessed type/family code."""
    text = ' '.join(str(getattr(el, k, None) or '') for k in ('ObjectType', 'Name'))
    if PART_WORDS.search(text):
        return None
    kinds = [k for k, terms in PROXY_TERMS.items() if re.search(rf'(?<!\w)(?:{terms})(?![^\W\d_])', text, re.I)]
    return kinds[0] if len(kinds) == 1 else None


def family(el):
    if el.is_a('IfcBuildingElementProxy'):
        return proxy_kind(el)
    return next((k for cls, k in FAMILIES if el.is_a(cls)), None)


def count_metadata(el):
    """Skip only a related component, never every flight because some stair exists."""
    import ifcopenshell.util.element as E
    cur, seen, component, ancestors = el, {el.id()}, None, []
    status = 'verified'
    while (parent := E.get_aggregate(cur)) is not None:
        if parent.id() in seen:
            status = 'cyclic aggregate hierarchy'
            break
        seen.add(parent.id())
        ancestors.append({'item_id': parent.GlobalId, 'ifc_class': parent.is_a()})
        # Different products remain countable (e.g. a door in a wall or a bar
        # in a slab). A stair/flight or ramp/flight is one semantic family.
        if (el.is_a(parent.is_a()) or parent.is_a(el.is_a())
                or (family(el) is not None and family(el) == family(parent))):
            component = parent.GlobalId
        cur = parent
    return {'aggregate_ancestors': ancestors, 'count_component_of': component,
            'count_status': status,
            'proxy_kind': proxy_kind(el) if el.is_a('IfcBuildingElementProxy') else None}


def stored_net_area(space):
    """Occurrence Qto before typed Pset; explicit property units before project units."""
    import ifcopenshell.util.element as E
    import ifcopenshell.util.unit as U
    ps = E.get_psets(space, verbose=True, should_inherit=False)
    for pn, values in sorted(ps.items(), key=lambda kv: not kv[0].startswith('Qto_')):
        if not isinstance(values, dict):
            continue
        for name, entry in values.items():
            if re.sub(r'\W', '', name).casefold() != 'netfloorarea' or not isinstance(entry, dict):
                continue
            value = entry.get('value')
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
                continue
            prop = space.file.by_id(entry['id'])
            unit = U.get_property_unit(prop, space.file, use_cache=True)
            if unit is not None and unit.UnitType == 'AREAUNIT':
                si = float(value) * U.get_unit_scale(unit)
                if math.isfinite(si):
                    return si, f'{pn}.{name}; declared area unit converted to m²'
    return None, None


def space_area(space):
    """Horizontal union footprint, including holes, not twice the floor/ceiling.

    IfcOpenShell's geometry API returns metres by default, independently of the
    file's length unit. World coordinates preserve tilted product placements.
    """
    import ifcopenshell.util.unit as U
    result = {'measured_m2': None, 'stored_net_m2': None, 'status': 'unavailable',
              'difference_pct': None, 'method': 'IfcSpace geometry horizontal footprint'}
    stored, source = stored_net_area(space)
    result.update(stored_net_m2=stored, stored_source=source)
    if U.get_project_unit(space.file, 'LENGTHUNIT', use_cache=True) is None:
        result['reason'] = 'The model does not declare length units.'
        return result
    try:
        import ifcopenshell.geom as G
        import ifcopenshell.util.shape as S
        st = G.settings()
        st.set('use-world-coords', True)
        shape = G.create_shape(st, space)
        area = float(S.get_footprint_area(shape.geometry, axis='Z'))
        if not math.isfinite(area) or area <= 0:
            raise ValueError('no positive footprint')
        result['measured_m2'] = area
        if stored is None:
            result['status'] = 'no stored net area'
        else:
            delta = abs(stored - area) / area
            result['difference_pct'] = delta * 100
            # 2% is the handoff's cross-check policy, not a fitted constant.
            result['status'] = 'agree' if delta <= .02 + 1e-12 else 'flag'
    except (RuntimeError, ValueError, AttributeError, TypeError, ZeroDivisionError, ImportError) as exc:
        result['reason'] = f'Footprint unavailable ({type(exc).__name__}).'
    return result


def space_row(el, *, geometry=False):
    import ifcopenshell.util.element as E
    st, seen = el, set()
    while st is not None and not st.is_a('IfcBuildingStorey') and st.id() not in seen:
        seen.add(st.id())
        st = E.get_container(st) or E.get_aggregate(st)
    if st is not None and not st.is_a('IfcBuildingStorey'):
        st = None
    row = {'item_id': el.GlobalId, 'ifc_class': el.is_a(), 'name': el.Name,
           'long_name': el.LongName, 'storey': st.Name if st is not None else None,
           **count_metadata(el)}
    if geometry:
        row['space_area'] = space_area(el)
    return row


def build(f, *, geometry=False):
    rows, errors = [], []
    # IfcProduct excludes IfcTypeProduct/IfcTypeObject in every supported schema.
    for el in f.by_type('IfcProduct'):
        if not (el.is_a('IfcElement') or el.is_a('IfcSpace')):
            continue
        try:
            rows.append(space_row(el, geometry=geometry) if el.is_a('IfcSpace') else
                        {'item_id': el.GlobalId, 'ifc_class': el.is_a(), **count_metadata(el)})
        except (RuntimeError, ValueError, AttributeError, TypeError) as exc:
            errors.append({'item_id': el.GlobalId, 'reason': type(exc).__name__})
    return {'version': VERSION, 'schema': f.schema, 'rows': rows, 'errors': errors,
            'space_inventory_complete': not any(e for e in errors if f.by_guid(e['item_id']).is_a('IfcSpace'))}


def enrich_elements(elements, index):
    by = {r['item_id']: r for r in index['rows']}
    for el in elements:
        row = by.get(el['item_id'])
        if row is None:
            continue
        props = el.setdefault('props', {})
        props.update({k: row[k] for k in ('aggregate_ancestors', 'count_component_of', 'count_status', 'proxy_kind')})
        if 'space_area' in row:
            check = props['space_area'] = row['space_area']
            if check['measured_m2'] is not None:
                el.setdefault('quantities', {})['area_m2'] = check['measured_m2']
                el.setdefault('quantity_source', {})['area_m2'] = 'IfcSpace geometry footprint'
