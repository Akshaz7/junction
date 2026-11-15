"""Run via scripts/heavy.sh. Writes only results/final/EVMETHOD and temp files.

No models, OCR, shared-artifact mutation or threshold tuning. The reserved IFC
is opened only by --unseen, after the normal audit and code tests are complete.
"""
import argparse
import hashlib
import json
import os
import random
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

os.environ.update(MODELS_FAKE='1', READER='0', RECOUNT='0', EXPLAIN='0', ANSWER_TIMEOUT_S='0')

from engine.answer import answer
from engine.calc import number, validate
from engine.method_inventory import inventory
from engine.scale_policy import choose, difference
from engine.scale_proof import read_json
from engine.tests.calc_cases import CASES, IFC, OTHER_IFC

OUT = Path('results/final/EVMETHOD')
ROOT = Path('artifacts')


def rung_availability(entries):
    rungs = {'native IFC projection': {'ifc'}, 'native CAD units/registration': {'dxf-units', 'dxf_units_fit', 'dxf_render'},
             'matched printed dimensions': {'dimension', 'dimensions'}, 'printed ratio + DPI': {'ratio-dpi'},
             'printed ratio + full paper size': {'ratio-sheet'}, 'scale bar': {'scalebar', 'scale-bar'},
             'recorded known-size object': {'known-size'}, 'door-width prior': {'door-prior'}}
    return {rung: {'pages': sum(bool(set(e['available']) & ids) for e in entries),
                   'pct_of_sample': 100 * sum(bool(set(e['available']) & ids) for e in entries) / max(1, len(entries))}
            for rung, ids in rungs.items()}


def write(name, value):
    value['implementation_sha256'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('engine').glob('method_*.py'))}
    value['implementation_sha256']['engine/scale_policy.py'] = hashlib.sha256(Path('engine/scale_policy.py').read_bytes()).hexdigest()
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def native_path(meta, fmt):
    rel = (meta.get('files') or {}).get(fmt)
    if not rel: return None
    paths = [Path(rel), Path('data/full/junction-dataset') / rel, Path('data/junction-dataset-preview') / rel]
    return next((p for p in paths if p.is_file()), None)


def questions():
    # Existing real-file cases cover numeric paths across unrelated origins.
    cases = list(CASES)
    cases.extend([
        ('project/deduplicate', [IFC, 'ifc_models__kit-institute-ac20-institute-var-2'], 'How many doors in total across the set?'),
        ('project/difference', [IFC, 'ifc_bench__digital-hub-arc'], 'Compare level 1 and level 2 doors'),
        ('project/ranking', [IFC, 'ifc_bench__digital-hub-arc'], 'Which level has the most doors?'),
        ('project/area', [IFC, 'ifc_bench__digital-hub-arc'], 'What is the total room area across both models?'),
        ('order/skirting', OTHER_IFC, 'Order skirting for all rooms with 10% waste'),
        ('props/schedule', OTHER_IFC, 'Give me the door schedule'),
        ('props/material', OTHER_IFC, 'What materials are the walls made of?'),
        ('ifc/description', OTHER_IFC, 'What is this building?'),
    ])
    entries = []
    for route, docs, question in cases:
        docs = [docs] if isinstance(docs, str) else docs
        if not all((ROOT / d).is_dir() for d in docs):
            entries.append({'route': route, 'docs': docs, 'skipped': 'real artifact absent'}); continue
        try:
            res = answer(question, docs)
            calc = res.get('reasoning', {}).get('calc')
            value = res['answer'].get('value')
            numeric = number(value) or isinstance(value, dict) and bool(value) and all(number(v) for v in value.values())
            issues = validate(calc, ROOT) if calc else ['No calc emitted']
            entries.append({'route': route, 'docs': docs, 'question': question, 'value': value, 'unit': res['answer'].get('unit'),
                            'numeric': bool(numeric), 'abstained': res['answer'].get('abstained'),
                            'method': calc.get('method') if calc else None, 'calc_status': calc.get('status') if calc else None,
                            'rows': len(calc.get('rows', [])) if calc else 0, 'issues': issues,
                            'complete': bool(calc) and not issues, 'method_recorded': bool(calc and calc.get('method')),
                            'trace': [{'step': s['step'], 'detail': s.get('detail', '')} for s in res.get('trace', []) if not s.get('model')]})
        except Exception as exc:
            entries.append({'route': route, 'docs': docs, 'question': question, 'error': type(exc).__name__ + ': ' + str(exc), 'complete': False})
    rows = inventory()
    summary = {'cases': len(entries), 'run': sum('skipped' not in e for e in entries),
               'numeric': sum(bool(e.get('numeric')) for e in entries), 'complete': sum(bool(e.get('complete')) for e in entries),
               'methods': sum(bool(e.get('method_recorded')) for e in entries),
               'numeric_complete_pct': 100 * sum(bool(e.get('complete')) for e in entries if e.get('numeric')) / max(1, sum(bool(e.get('numeric')) for e in entries))}
    non_scan = [e for e in entries if not e['route'].startswith('raster/')]
    summary['non_scan_cases'] = len(non_scan)
    summary['non_scan_method_pct'] = 100 * sum(bool(e.get('method_recorded')) for e in non_scan) / max(1, len(non_scan))
    by_route = {}
    for route in sorted({e['route'] for e in entries}):
        es = [e for e in entries if e['route'] == route]
        by_route[route] = {'answers': len(es), 'complete_pct': 100 * sum(bool(e.get('complete')) for e in es) / len(es),
                           'method_pct': 100 * sum(bool(e.get('method_recorded')) for e in es) / len(es),
                           'gaps': sorted({issue for e in es for issue in e.get('issues', [])})}
    write('routes.json', {'generated_at': datetime.now(timezone.utc).isoformat(), 'inventory': rows,
                         'scope': 'Inventory lists all named route entrypoints/subhandlers, not every possible query. Percentages below describe observed cases only; no extrapolation to untested entries.',
                         'summary': summary, 'observed_routes': by_route, 'answers': entries})
    print(json.dumps(summary), flush=True)
    for e in entries:
        if not e.get('complete'): print(e['route'], e.get('issues') or e.get('error') or e.get('skipped'), flush=True)


def scales():
    families = {'ifc': [], 'dxf': [], 'raster': [], 'pdf': []}
    twins = []
    for folder in sorted(ROOT.iterdir()):
        if not folder.is_dir() or not (folder / 'planmap-1.json').is_file(): continue
        meta = read_json(folder / 'doc.json')
        if not isinstance(meta, dict): continue
        formats = set(meta.get('formats') or [])
        if 'ifc' in formats and 'dxf' in formats: twins.append(folder.name)
        group = 'ifc' if (folder / 'elements.json').is_file() else 'dxf' if 'dxf' in formats else 'pdf' if meta.get('kind') == 'pdf' else 'raster'
        families[group].append(folder)
    rng = random.Random(20261115)
    selected = [(g, p) for g, paths in families.items() for p in rng.sample(paths, min(12, len(paths)))]
    entries, available, chosen = [], Counter(), Counter()
    for group, folder in selected:
        pm = read_json(folder / 'planmap-1.json')
        sc = choose(pm, folder)
        methods = {c.get('method') for c in sc.get('candidates', [])}
        available.update(methods); chosen[sc['selection']['id']] += 1
        e = {'doc_id': folder.name, 'input': group, 'available': sorted(str(m) for m in methods),
             'chosen': sc['selection'], 'm_per_px': sc.get('m_per_px')}
        meta = read_json(folder / 'doc.json')
        if group == 'dxf':
            path = native_path(meta, 'dxf')
            a = (pm.get('registration') or {}).get('a')
            if path and isinstance(a, (float, int)) and a:
                import ezdxf
                from pipeline.scale_provenance import dxf_units
                native = dxf_units(ezdxf.readfile(path), folder.name)
                if native.get('m_per_unit') and sc.get('m_per_px'):
                    truth = native['m_per_unit'] / abs(a)
                    e['native_comparison'] = {'method': 'original DXF INSUNITS / recorded registration magnitude',
                                               'value': truth, 'diff_pct': difference(truth, sc['m_per_px']),
                                               'limitation': 'Checks unit conversion and recorded registration; not independent physical verification of the drawing.'}
        elif group == 'ifc':
            ppm = (pm.get('projection') or {}).get('ppm')
            if ppm and sc.get('m_per_px'):
                e['native_comparison'] = {'method': 'IFC-generated plan projection, 1 / ppm', 'value': 1 / ppm,
                                          'diff_pct': difference(1 / ppm, sc['m_per_px']),
                                          'limitation': 'Same-source projection arithmetic; not an independent geometric truth.'}
        entries.append(e)
    comparisons = [e['native_comparison'] for e in entries if e.get('native_comparison')]
    summary = {'sample_pages': len(entries), 'sampling': 'Seeded random sample, up to 12 source documents per input family; one page per document; no new OCR/model calls',
               'population_by_family': {k: len(v) for k, v in families.items()}, 'available_by_rung': dict(available), 'chosen_by_rung': dict(chosen),
               'native_comparisons': len(comparisons), 'within_1pct': sum(c['diff_pct'] <= 1 for c in comparisons),
               'max_diff_pct': max((c['diff_pct'] for c in comparisons), default=None), 'ifc_dxf_twins': twins,
               'rung_availability': rung_availability(entries),
               'limitations': ['Candidate availability reflects cached operands, not everything a fresh drawing reader could extract.',
                              'No unrecorded dimensions, OCR, native geometry or physical error bounds were invented.',
                              'Independent scale accuracy requires matching surveyed/native twins; same-source agreement is not that accuracy.']}
    write('scales.json', {'summary': summary, 'pages': entries})
    print(json.dumps(summary), flush=True)


def unseen():
    import ifcopenshell
    from pipeline.ifc_scene import kind_of, storey_of
    from pipeline.scale_provenance import ifc_units
    from engine.solvers.solve import solve
    from engine import calc
    reserved = read_json(OUT / 'reserved.json')
    path = Path(reserved['path'])
    model = ifcopenshell.open(path)
    native = ifc_units(model, 'unseen')
    elements = []
    for e in [*model.by_type('IfcElement'), *model.by_type('IfcSpace')]:
        storey = storey_of(e)
        elements.append({'item_id': e.GlobalId, 'kind': kind_of(e), 'ifc_class': e.is_a(), 'name': e.Name,
                         'storey': {'name': storey.Name} if storey is not None else None, 'quantities': {}})
    with tempfile.TemporaryDirectory(prefix='evmethod-unseen-') as td:
        folder = Path(td) / 'unseen'; folder.mkdir()
        (folder / 'elements.json').write_text(json.dumps({'units': 'm', 'unit_provenance': native, 'elements': elements}))
        results = []
        for kind in ('door', 'window', 'wall'):
            q = 'How many ' + kind + 's are there?'
            res = calc.attach(solve(q, 'unseen', root=td), q, td)
            c = res.get('reasoning', {}).get('calc')
            expected = sum(e['kind'] == kind for e in elements)
            results.append({'question': q, 'value': res['answer']['value'], 'native_kind_count': expected,
                            'matches': expected == res['answer']['value'], 'method': c.get('method') if c else None,
                            'issues': validate(c, Path(td)) if c else ['no calc']})
    write('unseen.json', {'path': str(path), 'schema': model.schema, 'native_units': native,
                          'originating_system': model.header.file_name.originating_system,
                          'elements': len(elements), 'answers': results,
                          'limitations': 'Only metadata/classification/count routes were tested. No geometry was generated or used as a truth for areas/lengths.'})
    print('Reserved IFC:', path, model.schema, 'results:', [(r['matches'], r['issues']) for r in results], flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--unseen', action='store_true'); parser.add_argument('--scales', action='store_true')
    args = parser.parse_args()
    # Existing reasoning can create crop artifacts; suppress that in a read-only audit.
    import engine.scale_proof
    engine.scale_proof._crop = lambda *args, **kwargs: None
    OUT.mkdir(parents=True, exist_ok=True)
    if args.unseen: unseen()
    elif args.scales: scales()
    else: questions()
