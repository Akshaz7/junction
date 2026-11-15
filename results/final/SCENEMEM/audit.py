"""Validate real GLB bytes, GUID links and source quantities after measurement."""
import hashlib
import json
import mmap
from pathlib import Path
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from pipeline.ifc_scene_indexed import read_header
from pipeline.ifc_scene import node_boxes, usd_name
from pygltflib import GLTF2


def digest(path, offset):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        stream.seek(offset)
        while block := stream.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def audit(case):
    result = json.loads((REPO / f'results/final/SCENEMEM/after-{case}.json').read_text())
    assert result['ok'] and result['exit_code'] == 0
    work = Path(result['work'])
    original = json.loads((work / 'input-elements.json').read_text())
    indexed = json.loads((work / 'elements.json').read_text())
    manifest = json.loads((work / 'scene.json').read_text())
    before = {e['item_id']: e for e in original['elements']}
    after = {e['item_id']: e for e in indexed['elements']}
    assert len(before) == len(original['elements']) and set(before) == set(after)
    source_quantities = 0
    for guid, element in before.items():
        assert element['props'] == after[guid]['props']
        for key, value in element.get('quantities', {}).items():
            assert after[guid]['quantities'][key] == value
            assert after[guid]['quantity_source'][key] == element['quantity_source'][key]
            source_quantities += 1
    glb = work / 'scene.glb'
    header, binary_offset, binary_length = read_header(glb)
    raw = work / 'tmp/raw.glb'
    _, raw_offset, raw_length = read_header(raw)
    assert binary_length == raw_length and digest(glb, binary_offset) == digest(raw, raw_offset)
    names = [n['name'] for n in header['nodes']]
    assert len(names) == len(set(names)) and set(names) == set(manifest['items'])
    assert set(names) <= set(after)
    assert manifest['units'] == 'm' and manifest['up'] == 'Y'
    assert indexed['unit_provenance']['m_per_unit'] is not None
    world_boxes = node_boxes(GLTF2.from_json(json.dumps(header)))
    vertices = triangles = 0
    with glb.open('rb') as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
        for ni, node in enumerate(header['nodes']):
            guid = node['name']
            item = manifest['items'][guid]
            assert item['node'] == guid and item['usd_name'] == usd_name(guid)
            assert item['bbox_m'] == after[guid]['bbox_m']
            assert np.max(np.abs(np.asarray(item['bbox_m']) - np.asarray(world_boxes[ni]))) <= .000051
            primitive = header['meshes'][node['mesh']]['primitives'][0]
            position = header['accessors'][primitive['attributes']['POSITION']]
            indices = header['accessors'][primitive['indices']]
            pv, iv = header['bufferViews'][position['bufferView']], header['bufferViews'][indices['bufferView']]
            v = np.ndarray((position['count'],3), '<f4', mapped, binary_offset + pv.get('byteOffset',0))
            i = np.ndarray((indices['count'],), '<u4', mapped, binary_offset + iv.get('byteOffset',0))
            assert np.isfinite(v).all() and i.size % 3 == 0 and i.max() < len(v)
            assert v.min(axis=0).tolist() == position['min'] and v.max(axis=0).tolist() == position['max']
            assert iv.get('byteOffset',0) + i.nbytes <= header['buffers'][0]['byteLength']
            vertices += len(v)
            triangles += len(i) // 3
            del v, i
    return {'case': case, 'schema': indexed['schema'], 'source_mb': result['source_mb'],
            'authoring_applications': indexed.get('building', {}).get('applications', []),
            'indexed_objects_unchanged': len(after), 'source_quantities_unchanged': source_quantities,
            'unique_linked_nodes': len(names), 'vertices': vertices, 'triangles': triangles,
            'peak_scene_rss_mib': result['resource_peak_mib'], 'scene_seconds': result['result']['s'],
            'binary_payload_sha256': digest(glb, binary_offset), 'warnings': manifest.get('warnings', [])}


if __name__ == '__main__':
    report = {'cases': [audit(case) for case in ('munich','schependomlaan','reserved')],
              'reserved_selection': 'SystemRandom choice among non-heldout registry IFCs >15 MB before development; source opened only for final validation.',
              'models_called': 0, 'spend_usd': 0,
              'platform': sys.platform,
              'limitations': ['RSS measured on macOS; Linux container not available in this worker.',
                              'Before runs for Munich and the reserved file were stopped at a 900 MiB guard; their recorded peaks are lower bounds.']}
    output = REPO / 'results/final/SCENEMEM/audit.json'
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)
