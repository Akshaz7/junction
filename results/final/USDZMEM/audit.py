"""Read-only post-export audits; run via scripts/heavy.sh."""
import argparse
import hashlib
import importlib.util
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))


def validate(source, work):
    import numpy as np
    from pxr import Usd, UsdGeom, UsdShade

    from pipeline.usdz import EXACT_KINDS, _item_node, _lean_mesh
    from pipeline.usdz_glb import GLB

    sj = json.loads((source / 'scene.json').read_text())
    mapping = {v['node']: (iid, v) for iid, v in sj['items'].items()}
    expected, bounds, triangles, source_names = {}, {}, {}, set()
    glb = GLB(source / 'scene.glb')
    try:
        for node, transform, mesh in glb.nodes():
            base = _item_node(node, mapping)
            if base not in mapping:
                continue
            iid, info = mapping[base]
            expected[info['usd_name']] = iid
            source_names.add(node)
            if info['kind'] not in EXACT_KINDS:
                continue
            for primitive in mesh['primitives']:
                for points, faces, _ in glb.batches(primitive):
                    points = points @ transform[:3, :3].T + transform[:3, 3]
                    points, faces = _lean_mesh(points, faces, info['kind'])
                    if not len(faces):
                        continue
                    key = info['usd_name']
                    low, high = points.min(axis=0), points.max(axis=0)
                    if key in bounds:
                        low, high = np.minimum(low, bounds[key][0]), np.maximum(high, bounds[key][1])
                    bounds[key] = (low, high)
                    triangles[key] = triangles.get(key, 0) + len(faces)
    finally:
        glb.close()
    stage = Usd.Stage.Open(str(work / 'scene.usdz'))
    prims = {p.GetName(): p for p in stage.GetPrimAtPath('/Root').GetChildren() if p.IsA(UsdGeom.Xform)}
    missing = sorted(set(expected) - set(prims))
    assert not missing, missing[:10]
    count, exact_checked = 0, 0
    for name, prim in prims.items():
        points, face_count = [], 0
        for part in prim.GetChildren():
            if not part.IsA(UsdGeom.Mesh):
                continue
            assert part.GetCustomDataByKey('source_node') in source_names
            mesh = UsdGeom.Mesh(part)
            assert UsdShade.MaterialBindingAPI(part).ComputeBoundMaterial()[0]
            points.append(np.asarray(mesh.GetPointsAttr().Get()))
            counts = np.asarray(mesh.GetFaceVertexCountsAttr().Get())
            assert np.all(counts == 3)
            face_count += len(counts)
            count += 1
        if name in bounds:
            points = np.concatenate(points)
            np.testing.assert_allclose([points.min(axis=0), points.max(axis=0)], bounds[name], atol=.0001, rtol=1e-6)
            assert face_count == triangles[name], (name, face_count, triangles[name])
            exact_checked += 1
    with zipfile.ZipFile(work / 'scene.usdz') as package, (work / 'scene.usdz').open('rb') as stream:
        assert package.testzip() is None
        assert package.namelist()[0] == 'scene.usda'
        for info in package.infolist():
            stream.seek(info.header_offset + 26)
            n, extra = struct.unpack('<HH', stream.read(4))
            assert (info.header_offset + 30 + n + extra) % 64 == 0
            assert info.compress_type == zipfile.ZIP_STORED
    checker = subprocess.run(['usdchecker', '--arkit', str(work / 'scene.usdz')], check=False, text=True, capture_output=True)
    assert checker.returncode == 0 and 'Success!' in checker.stdout + checker.stderr, (checker.stdout + checker.stderr)[-2000:]
    return {'linked_items': len(expected), 'manifest_items': len(sj['items']), 'mesh_batches': count,
            'exact_kind_geometry_checks': exact_checked, 'arkit_validator': 'Success!',
            'source_glb_sha256': hashlib.file_digest((source / 'scene.glb').open('rb'), 'sha256').hexdigest()}


def fixtures():
    from pipeline import usdz
    base = Path(tempfile.mkdtemp(prefix='f-usdzmem-fixtures-'))
    spec = importlib.util.spec_from_file_location('fixture_tests', REPO / 'tests/test_usdz.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = base
    results = []
    for doc_id in module.IDS:
        source = REPO / 'artifacts' / doc_id
        out = base / 'artifacts' / doc_id
        out.mkdir(parents=True)
        shutil.copyfile(source / 'scene.json', out / 'scene.json')
        (out / 'scene.glb').symlink_to((source / 'scene.glb').resolve())
        usdz.process(doc_id, out)
        module.test_usdz_prims_and_arkit(doc_id)
        results.append({'doc_id': doc_id, 'test_usdz_prims_and_arkit': 'pass'})
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('case', nargs='?')
    ap.add_argument('--fixtures', action='store_true')
    args = ap.parse_args()
    if args.fixtures:
        result = {'isolated_original_fixture_tests': fixtures()}
        name = 'fixtures'
    else:
        report = json.loads((Path(__file__).parent / f'after-{args.case}.json').read_text())
        result = validate(Path(report['input']), Path(report['work']))
        name = args.case
    (Path(__file__).parent / f'audit-{name}.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
