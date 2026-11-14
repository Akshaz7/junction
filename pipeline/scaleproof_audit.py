"""Reproducible, read-only real-file validation for F-SCALEPROOF.

Writes only results/final/SCALEPROOF and new evidence crops. Never runs OCR,
models, geometry conversion, or edits a source/plan map. Run via heavy.sh.
The random final-only IFC was selected in holdout.json before development.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from engine.scale_proof import enrich, read_json

REPO = Path(__file__).resolve().parents[1]
ART = REPO / 'artifacts'
DATA = REPO / 'data/junction-dataset-preview'
OUT = REPO / 'results/final/SCALEPROOF'


def original(record, formats):
    for kind, relative in record.get('files', {}).items():
        path = DATA / relative
        if kind in formats and path.is_file():
            return path
    return None


def source_resolves(src, folder, model=None, dxf=None):
    if src.get('assumption') or src.get('definition') or src.get('metadata'):
        return True
    if src.get('entity') and model is not None:
        try:
            return model.by_id(int(src['entity'].lstrip('#'))) is not None
        except (RuntimeError, ValueError):
            return False
    if src.get('header') and dxf is not None:
        return src['header'] in dxf.header
    if src.get('bbox'):
        from PIL import Image
        with Image.open(folder / f"page-{src['page']}.png") as im:
            x0, y0, x1, y1 = src['bbox']
            return 0 <= x0 < x1 <= im.width and 0 <= y0 < y1 <= im.height
    if src.get('file'):
        raw = read_json(folder / src['file'])
        if not raw:
            return False
        try:
            for key in src.get('pointer', '').lstrip('/').split('/') if src.get('pointer') else []:
                raw = raw[int(key)] if isinstance(raw, list) else raw[key]
            return raw is not None
        except (KeyError, ValueError, IndexError, TypeError):
            return False
    return False


def audit(record, *, final_only=False):
    did, kind = record['doc_id'], record['kind']
    folder = ART / did
    path = original(record, {'ifc', 'dxf', 'png', 'jpg', 'jpeg'})
    pm = read_json(folder / 'planmap-1.json')
    if not pm:
        from PIL import Image
        with Image.open(folder / 'page-1.png') as im:
            pm = {'image': {'w': im.width, 'h': im.height}, 'items': [], 'scale': {'method': 'none', 'm_per_px': None}}
    pm = {**pm, 'doc_id': did, 'page': 1}
    stored = pm.get('scale') or {}
    model = dxf = None
    native = None
    comparisons = []
    if kind == 'dxf':
        import ezdxf

        from pipeline.dxf_planmap import fit_transform, room_texts
        from pipeline.scale_provenance import dxf_scale
        dxf = ezdxf.readfile(str(path))
        registration = pm.get('registration') or {}
        words = read_json(folder / 'text-1.json').get('words', [])
        refit = fit_transform(room_texts(dxf.modelspace()), words)
        if refit:
            comparisons.append({'method': 'recomputed CAD registration', 'value': refit['a'], 'unit': 'px/native unit',
                                'stored_value': registration.get('a'), 'diff_pct': abs(refit['a'] / registration['a'] - 1) * 100 if registration.get('a') else None,
                                'anchors': refit['n'], 'rms_px': refit['rms_px']})
            registration = refit
        reconstructed = dxf_scale(dxf, registration, did)
        reconstructed['method'] = stored.get('method', reconstructed['method'])
        pm['scale'] = reconstructed
        native = reconstructed.get('native_units')
    elif kind == 'ifc':
        import ifcopenshell
        import ifcopenshell.util.unit

        from pipeline.scale_provenance import ifc_units
        model = ifcopenshell.open(str(path))
        native = ifc_units(model, did)
        utility = ifcopenshell.util.unit.calculate_unit_scale(model)
        comparisons.append({'method': 'IFC library unit resolver (same source assignment)', 'value': utility, 'unit': 'm/native unit',
                            'agrees': native['m_per_unit'] is not None and abs(native['m_per_unit'] - utility) < 1e-12})
    scale = enrich(pm, folder, save_crops=True)
    proof = scale['proof']
    # Native assignment conversion is separate from the projection in metres.
    if native and native.get('m_per_unit') is not None:
        proof['steps'].insert(0, {'id': 'native-units', 'label': native['method'], 'expr': native['formula'],
                                 'value': native['m_per_unit'], 'unit': 'm/native unit', 'inputs': native['inputs'], 'note': native['note']})
    resolved, unresolved = 0, []
    crops = set()
    for step in proof['steps']:
        for inp in step['inputs']:
            src = inp['source']
            okay = source_resolves(src, folder, model, dxf)
            resolved += okay
            if not okay:
                unresolved.append({'step': step['id'], 'name': inp['name'], 'source': src})
            if src.get('crop'):
                crops.add(src['crop'])
                assert (ART / src['crop']).is_file()
    selected, old = scale.get('m_per_px'), stored.get('m_per_px')
    row = {'doc_id': did, 'kind': kind, 'origin': record.get('source'), 'original': str(path.relative_to(REPO)) if path else None,
           'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path else None,
           'final_only_unseen': final_only, 'stored_scale': stored, 'current_scale': {k: scale.get(k) for k in ('m_per_px', 'method', 'spread_pct')},
           'stored_vs_current_diff_pct': abs(selected / old - 1) * 100 if selected and old else None,
           'methods': [{'method': s['label'], 'value': s['value'], 'unit': s['unit']} for s in proof['steps']],
           'checks': proof['checks'] + comparisons, 'native_units': native,
           'inputs_resolved': resolved, 'inputs_unresolved': unresolved, 'crops': sorted(crops),
           'proof': proof,
           'status': 'PASS' if not unresolved else 'FAIL',
           'limitation': ('No scale-bearing text, dimension link, native units or door detections are recorded; physical scale remains unknown.'
                          if selected is None else 'Observed method spread and source arithmetic do not establish physical correctness or completeness.')}
    if model is not None:
        row['ifc_schema'] = model.schema
        row['authoring_software'] = model.header.file_name.originating_system
    return row


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    holdout = read_json(OUT / 'holdout.json')
    unseen = (REPO / holdout['path']).resolve()
    records = [json.loads(s) for s in (ART / 'registry.jsonl').read_text().splitlines() if s.strip()]
    selected = []
    for kind, amount in (('raster', 3), ('dxf', 3), ('ifc', 3)):
        pool = [r for r in records if r.get('kind') == kind and original(r, {kind, 'png', 'jpg'})
                and original(r, {'ifc', 'dxf', 'png', 'jpg'}).resolve() != unseen
                and (ART / r['doc_id'] / 'planmap-1.json').exists()]
        selected += pool[:amount]
    # Include archival scans with missing extracted metadata to check honest unknowns.
    origins = set()
    for r in records:
        if r.get('kind') != 'raster' or r.get('source') in ('cubicasa5k', 'swiss_dwellings') or r.get('source') in origins:
            continue
        if original(r, {'jpg', 'png'}) and (ART / r['doc_id'] / 'page-1.png').is_file():
            selected.append(r); origins.add(r.get('source'))
        if len(origins) == 3:
            break
    # Record selections before opening the inputs (the holdout remains last).
    (OUT / 'validation-files.json').write_text(json.dumps({'development_validation': [r['doc_id'] for r in selected], 'final_only': holdout}, indent=2) + '\n')
    rows = []
    for r in selected:
        print('checking', r['doc_id'], flush=True)
        rows.append(audit(r))
    final = next(r for r in records if original(r, {'ifc'}) and original(r, {'ifc'}).resolve() == unseen)
    print('final-only unseen:', final['doc_id'], flush=True)
    rows.append(audit(final, final_only=True))
    report = {'worker': 'F-SCALEPROOF', 'created_utc': datetime.now(UTC).isoformat(),
              'scope': 'Scale derivation, provenance resolution and method comparison; not a physical-scale ground-truth accuracy benchmark.',
              'models_called': 0, 'live_cost_usd': 0, 'source_files_modified': 0, 'heldout_training_or_tuning': False,
              'drawings': len(rows), 'by_kind': dict(Counter(r['kind'] for r in rows)),
              'passed': sum(r['status'] == 'PASS' for r in rows), 'inputs_resolved': sum(r['inputs_resolved'] for r in rows),
              'inputs_unresolved': sum(len(r['inputs_unresolved']) for r in rows), 'crops': sum(len(r['crops']) for r in rows),
              'rows': rows}
    (OUT / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'rows'}), flush=True)
    if len(rows) < 10 or report['inputs_unresolved']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
