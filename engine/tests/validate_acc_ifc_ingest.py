"""Small synthetic end-to-end IFC ingestion. Run through scripts/heavy.sh."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    os.environ.update(MODELS_FAKE='1', IFC_CONVERT_PY='1', HEAVY_SLOT_HELD='1')
    from engine.tests.test_acc_ifc import model, room
    from pipeline.ifc_scene import process
    f = model()
    space = room(f, net=100)
    f.by_type('IfcProject')[0].RepresentationContexts = f.by_type('IfcGeometricRepresentationContext')
    with tempfile.TemporaryDirectory(prefix='acc-ifc-ingest-') as tmp:
        d = Path(tmp)
        source = d / 'source.ifc'
        f.write(str(source))
        process(source, {'doc_id': 'synthetic__generated-for-test'}, d)
        index = json.loads((d / 'ifc-accuracy.json').read_text())
        elements = json.loads((d / 'elements.json').read_text())
        row = next(e for e in elements['elements'] if e['item_id'] == space.GlobalId)
        check = row['props']['space_area']
        result = {'generated_for_test': True, 'sidecar_version': index['version'],
                  'measured_m2': check['measured_m2'], 'stored_net_m2': check['stored_net_m2'],
                  'status': check['status'], 'scene_glb_bytes': (d / 'scene.glb').stat().st_size,
                  'count_status': row['props']['count_status']}
        assert check['measured_m2'] == 12 and check['stored_net_m2'] == 100 and check['status'] == 'flag'
        assert result['scene_glb_bytes'] > 0 and row['quantities']['area_m2'] == 12
    (ROOT / 'results/final/ACC-IFC/ingest.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
