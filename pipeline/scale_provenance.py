"""Capture native unit declarations at ingestion; no geometry conversion/model calls.

The API consumes the resulting JSON and never imports IFC/DXF libraries.
"""
from __future__ import annotations

from engine.scale_proof import candidate, operand, positive, source

PREFIX = {'EXA': 1e18, 'PETA': 1e15, 'TERA': 1e12, 'GIGA': 1e9, 'MEGA': 1e6, 'KILO': 1e3,
          'HECTO': 1e2, 'DECA': 10, None: 1, 'DECI': .1, 'CENTI': .01, 'MILLI': .001,
          'MICRO': 1e-6, 'NANO': 1e-9, 'PICO': 1e-12, 'FEMTO': 1e-15, 'ATTO': 1e-18}


def ifc_units(model, doc_id):
    """Resolve the project's LENGTHUNIT, including chained conversion-based units.

    No default metre: absent/ambiguous assignments are unknown. Entity numbers
    identify exact records in the original IFC regardless of schema/label language.
    """
    projects = model.by_type('IfcProject')
    assignments = {p.UnitsInContext.id(): p.UnitsInContext for p in projects if p.UnitsInContext}
    if not assignments:
        return {'method': 'ifc-units', 'm_per_unit': None, 'inputs': [], 'note': 'The IFC project has no unit assignment.'}
    results = []
    for assignment in assignments.values():
        units = [u for u in assignment.Units if getattr(u, 'UnitType', None) == 'LENGTHUNIT']
        if len(units) != 1:
            return {'method': 'ifc-units', 'm_per_unit': None, 'inputs': [], 'note': 'Missing or ambiguous length unit in the IFC project assignment.'}
        inputs, seen = [], set()

        def resolve(u, seen=seen, inputs=inputs, assignment=assignment):
            if u.id() in seen:
                return None
            seen.add(u.id())
            src = source(doc_id, None, format='ifc', entity=f'#{u.id()}', assignment=f'#{assignment.id()}', attribute='Name')
            if u.is_a('IfcSIUnit') and u.Name == 'METRE' and u.Prefix in PREFIX:
                factor = PREFIX[u.Prefix]
                inputs.append(operand('SI length unit multiplier', factor, 'm/native unit', {**src, 'name': u.Name, 'prefix': u.Prefix,
                                                                                           'definition': 'SI prefix applied to metre'}))
                return factor
            if u.is_a('IfcConversionBasedUnit'):
                if getattr(u, 'ConversionOffset', 0):
                    return None
                cf = u.ConversionFactor
                val = positive(getattr(cf.ValueComponent, 'wrappedValue', None))
                if val is None:
                    return None
                inputs.append(operand('declared conversion factor', val, 'base unit/native unit', {
                    **src, 'name': u.Name, 'entity': f'#{cf.id()}', 'attribute': 'ValueComponent'}))
                base = resolve(cf.UnitComponent)
                return val * base if base else None
            return None

        factor = resolve(units[0])
        results.append({'method': 'ifc-units', 'm_per_unit': factor, 'inputs': inputs,
                        'formula': 'metres per native unit = product of declared conversion factors and SI prefix multipliers',
                        'note': 'From the project unit assignment; quantities and rendered geometry are converted once to metres.',
                        'schema': model.schema})
    factors = {r['m_per_unit'] for r in results}
    if len(factors) != 1 or None in factors:
        return {'method': 'ifc-units', 'm_per_unit': None, 'inputs': [], 'note': 'Project length units disagree or use an unsupported unit definition.'}
    first = results[0]
    first['inputs'] = [i for r in results for i in r['inputs']]
    return first


def dxf_units(doc, doc_id):
    """Use ezdxf's complete INSUNITS table; unitless does not mean metres."""
    from ezdxf import units
    code = doc.header.get('$INSUNITS', 0)
    try:
        factor = units.conversion_factor(int(code), units.M)
    except (ValueError, TypeError, KeyError):
        factor = None
    # ezdxf omits these official INSUNITS entries. Definitions are exact:
    # https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-LT/files/GUID-A58A87BB-482B-4042-A00A-EEF55A2B4FD8.htm
    # https://www.nist.gov/pml/us-surveyfoot
    exact = {1: .0254, 2: .3048, 3: 1609.344, 8: .0254e-6, 9: .0254e-3, 10: .9144,
             21: 1200 / 3937, 22: 100 / 3937, 23: 3600 / 3937, 24: 6336000 / 3937}
    factor = exact.get(code, factor)
    if not positive(factor):
        factor = None
    return {'method': 'dxf-units', 'm_per_unit': factor,
            'inputs': [operand('$INSUNITS', code, 'DXF unit code', source(doc_id, 1, format='dxf', header='$INSUNITS')),
                       operand('metres per drawing unit', factor, 'm/native unit', source(doc_id, 1, format='dxf', header='$INSUNITS',
                                                                                       definition='Autodesk INSUNITS enumeration via ezdxf.units conversion table'))],
            'formula': 'metres per drawing unit = conversion from declared INSUNITS to metres',
            'note': 'Unitless or unsupported declarations have no physical scale.' if factor is None else 'Uses the declared CAD insertion units; no assumed metre default.'}


def dxf_scale(doc, transform, doc_id, page=1):
    native = dxf_units(doc, doc_id)
    factor = native['m_per_unit']
    a = positive(transform.get('a'))
    if not factor or not a:
        return {'m_per_px': None, 'method': 'none', 'confidence': 0, 'native_units': native}
    src = source(doc_id, page, file=f'planmap-{page}.json', pointer='/registration')
    derivation = candidate('dxf-units', factor / a, 'scale = metres per drawing unit / registered pixels per drawing unit',
                          native['inputs'] + [operand('registered pixels per drawing unit', a, 'px/native unit', src)],
                          'Registration residual measures alignment, not physical unit correctness.', independent=False)
    derivation.pop('method'); derivation.pop('m_per_px')
    # Preserve each inlier so the registration can be recomputed from real anchors.
    for anchor in transform.get('anchors', []):
        derivation['inputs'].append(operand('registration anchor', anchor['pixel'], 'px', {
            **src, 'text': anchor['text'], 'bbox': anchor['bbox'], 'native_xy': anchor['native'], 'residual_px': anchor['residual_px']}))
    return {'m_per_px': factor / a, 'method': 'dxf_units_fit', 'confidence': 1.0 if transform.get('rms_px', 0) < 6 else .6,
            'native_units': native, 'derivation': derivation,
            'selection_rule': 'Use declared DXF units divided by the recorded CAD-to-page transform; reject missing units or non-positive transforms.'}
