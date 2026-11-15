"""ACC-IFC real-file measurement, explicit development/final blind phases only.

Run via scripts/heavy.sh. Reads only the preselected permitted files. Never
rewrites shared artifacts; temporary indexes exercise the actual count solver.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine.tests.run_acc_ifc_validation import OUT, forbidden


def oracle_count(products, classes):
    """Direct relation walk, independently of the production metadata helpers."""
    found = []
    for el in products:
        if not any(el.is_a(c) for c in classes):
            continue
        cur, seen, nested = el, set(), False
        while cur.id() not in seen:
            seen.add(cur.id())
            rel = next((r for r in cur.Decomposes if r.is_a('IfcRelAggregates')), None)
            if rel is None:
                break
            cur = rel.RelatingObject
            if any(cur.is_a(c) for c in classes):
                nested = True
                break
        if not nested:
            found.append(el.GlobalId)
    return set(found)


def profile_area(el):
    """Independent shoelace reference for simple vertical extruded room profiles.

    Other representations are explicitly uncheckable here; their quantities
    are cross-checks, not independent geometric ground truth.
    """
    import ifcopenshell.util.placement as P
    import ifcopenshell.util.unit as U
    import numpy as np
    reps = getattr(getattr(el, 'Representation', None), 'Representations', ()) or ()
    bodies = [i for r in reps if r.RepresentationIdentifier == 'Body' for i in r.Items]
    if len(bodies) != 1 or not bodies[0].is_a('IfcExtrudedAreaSolid'):
        return None
    solid = bodies[0]
    if abs(solid.ExtrudedDirection.DirectionRatios[2]) != 1:
        return None
    matrix = P.get_local_placement(el.ObjectPlacement) @ P.get_axis2placement(solid.Position)
    if not np.allclose(np.abs(matrix[:3, 2]), [0, 0, 1]):
        return None
    profile = solid.SweptArea
    if not profile.is_a('IfcArbitraryClosedProfileDef'):
        return None
    rings = [profile.OuterCurve, *(getattr(profile, 'InnerCurves', ()) or ())]
    areas = []
    for ring in rings:
        if not ring.is_a('IfcPolyline'):
            return None
        points = [p.Coordinates for p in ring.Points]
        areas.append(abs(sum(points[i][0] * points[(i+1) % len(points)][1] - points[(i+1) % len(points)][0] * points[i][1] for i in range(len(points)))) / 2)
    return (areas[0] - sum(areas[1:])) * U.calculate_unit_scale(el.file)**2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--blind', action='store_true', help='Final check only, after implementation is frozen')
    args = ap.parse_args()
    selection = json.loads((OUT / 'selection.json').read_text())
    files = [selection['blind']] if args.blind else selection['development']
    blocked = forbidden()
    # Check canonical ids before opening any source contents.
    from pipeline.registry import doc_id_for
    for doc in files:
        parts = Path(doc['path']).relative_to('data/full/junction-dataset/data').parts
        assert doc['doc_id'] == doc_id_for(parts[0], str(Path(*parts[1:])))
        assert doc['doc_id'] not in blocked
        assert args.blind or doc['doc_id'] != selection['blind']['doc_id']
    os.environ.update(MODELS_FAKE='1', EXPLAIN='0')
    import ifcopenshell
    import ifcopenshell.util.unit as U
    from pipeline.ifc_accuracy import build
    from pipeline.ifc_scene import kind_of, quantities_of, storey_of, props_of
    from pipeline.ifc_props import enrich_elements
    from engine.solvers.solve import solve
    reports = []
    for doc in files:
        start = time.perf_counter()
        f = ifcopenshell.open(str(ROOT / doc['path']))
        idx = build(f, geometry=True)
        products = list(f.by_type('IfcElement')) + list(f.by_type('IfcSpace'))
        scale = U.calculate_unit_scale(f)
        with tempfile.TemporaryDirectory(prefix='acc-ifc-real-') as tmp:
            root = Path(tmp)
            d = root / doc['doc_id']
            d.mkdir()
            (d / 'source.ifc').symlink_to((ROOT / doc['path']).resolve())
            elements = []
            for el in products:
                st = storey_of(el)
                elements.append({'item_id': el.GlobalId, 'name': el.Name, 'ifc_class': el.is_a(),
                    'kind': kind_of(el), 'quantities': quantities_of(el, scale), 'props': props_of(el),
                    'storey': {'name': st.Name, 'elevation_m': (st.Elevation or 0) * scale} if st is not None else None})
            enrich_elements(f, elements)
            (d / 'elements.json').write_text(json.dumps({'elements': elements,
                'storeys': [{'name': s.Name, 'elevation_m': (s.Elevation or 0)*scale} for s in f.by_type('IfcBuildingStorey')]}))
            (d / 'doc.json').write_text(json.dumps({'doc_id': doc['doc_id'], 'kind': 'ifc', 'files': {'ifc': str((ROOT / doc['path']).resolve())}}))
            # Verify the optional sidecar path used by future ingestions too.
            (d / 'ifc-accuracy.json').write_text(json.dumps(idx))
            os.environ['ARTIFACTS_DIR'] = str(root)
            checks = []
            for noun, classes in [('stairs', ['IfcStair', 'IfcStairFlight']), ('walls', ['IfcWall']), ('doors', ['IfcDoor']), ('rooms (spaces)', ['IfcSpace'])]:
                expected = oracle_count(products, classes)
                question = f'How many {noun} are in this model?'
                result = solve(question, doc['doc_id'], root=root)
                ids = {g for c in result['citations'] if c.get('item_kind') != 'proxy' for g in c['item_ids']}
                got = result['answer']['value']
                unavailable = result['answer']['abstained']
                checks.append({'question': question, 'expected_native_occurrences': len(expected), 'actual': got,
                    'pass': got == len(expected) and ids == expected, 'honest_unavailable': unavailable,
                    'raw_native_before_hierarchy': sum(any(e.is_a(c) for c in classes) for e in products),
                    'evidence_items': len(ids), 'confidence': result['answer']['confidence']})
            area_result = solve('What is the total area of the rooms (spaces)?', doc['doc_id'], root=root)
            rooms = [r for r in idx['rows'] if r['ifc_class'] == 'IfcSpace']
            profile_checks = []
            for row in rooms:
                reference = profile_area(f.by_guid(row['item_id']))
                got = row['space_area']['measured_m2']
                if reference is not None and got is not None:
                    profile_checks.append({'item_id': row['item_id'], 'profile_shoelace_m2': reference,
                                           'mesh_footprint_m2': got, 'pass': abs(got-reference) <= max(1e-6, abs(reference)*1e-6)})
            reports.append({'doc_id': doc['doc_id'], 'source': doc['path'], 'schema': f.schema,
                'applications': [a.ApplicationFullName for a in f.by_type('IfcApplication')],
                'blind': args.blind, 'checks': checks, 'index_errors': idx['errors'],
                'space_count': len(rooms), 'area_status': dict(Counter(r['space_area']['status'] for r in rooms)),
                'profile_checks': profile_checks,
                'area_answer': {'value': area_result['answer']['value'], 'abstained': area_result['answer']['abstained'],
                                'confidence': area_result['answer']['confidence'],
                                'cross_check_trace_rows': sum('->' in t['detail'] for t in area_result['trace'])},
                'space_measurements': [{'item_id': r['item_id'], **r['space_area']} for r in rooms],
                'seconds': round(time.perf_counter()-start, 3)})
        print(doc['doc_id'], f.schema, len(rooms), 'spaces;', sum(c['pass'] for c in checks), '/', len(checks), 'exact counts;', len(profile_checks), 'independent profile checks', flush=True)
    (OUT / ('real-blind.json' if args.blind else 'real-development.json')).write_text(json.dumps(reports, indent=1)+'\n')
    if not all(c['pass'] or c['honest_unavailable'] for r in reports for c in r['checks']):
        raise SystemExit('Count/evidence mismatch; see report.')
    if not all(c['pass'] for r in reports for c in r['profile_checks']):
        raise SystemExit('Independent geometry reference mismatch; see report.')


if __name__ == '__main__':
    main()
