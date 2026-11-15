"""Attach a streamed GLB to a completed property index without reopening IFC."""
import json
import shutil
import struct
import time
from pathlib import Path

import numpy as np
from pygltflib import GLTF2


def read_header(source):
    with source.open('rb') as stream:
        magic, version, total = struct.unpack('<III', stream.read(12))
        length, kind = struct.unpack('<II', stream.read(8))
        if magic != 0x46546C67 or version != 2 or kind != 0x4E4F534A or total != source.stat().st_size:
            raise ValueError('The converted GLB header is invalid.')
        header = json.loads(stream.read(length))
        binary_length, binary_kind = struct.unpack('<II', stream.read(8))
        if binary_kind != 0x004E4942 or stream.tell() + binary_length != total:
            raise ValueError('The converted GLB binary chunk is invalid.')
        return header, stream.tell(), binary_length


def write_header(source, output, header, binary_offset, binary_length):
    encoded = json.dumps(header, separators=(',', ':'), allow_nan=False).encode()
    encoded += b' ' * (-len(encoded) % 4)
    tmp = output.with_suffix('.glb.tmp')
    try:
        with tmp.open('wb') as target, source.open('rb') as original:
            target.write(struct.pack('<III', 0x46546C67, 2, 28 + len(encoded) + binary_length))
            target.write(struct.pack('<II', len(encoded), 0x4E4F534A))
            target.write(encoded)
            target.write(struct.pack('<II', binary_length, 0x004E4942))
            original.seek(binary_offset)
            shutil.copyfileobj(original, target, 1024 * 1024)
        tmp.replace(output)
    finally:
        tmp.unlink(missing_ok=True)


def process(raw: Path, doc: dict, out: Path, started=None):
    from pipeline.ifc_scene import node_boxes, node_matrices, usd_name
    index = json.loads((out / 'elements.json').read_text())
    if index.get('doc_id') != doc['doc_id']:
        raise ValueError('The property index belongs to a different document.')
    elements = index['elements']
    by_guid = {e['item_id']: e for e in elements}
    header, binary_offset, binary_length = read_header(raw)
    gltf = GLTF2.from_json(json.dumps(header))  # JSON only: never load the triangle blob
    boxes = node_boxes(gltf)
    if not boxes:
        raise RuntimeError('GLB has no mesh nodes')
    lo = np.min([b[0] for b in boxes.values()], axis=0)
    hi = np.max([b[1] for b in boxes.values()], axis=0)
    offset = np.array([(lo[0] + hi[0]) / 2, 0., (lo[2] + hi[2]) / 2])
    children = {child for node in gltf.nodes for child in (node.children or [])}
    transforms = node_matrices(gltf)
    for ni, node in enumerate(gltf.nodes):
        if ni not in children:
            matrix = transforms[ni].copy()
            matrix[:3, 3] -= offset
            header['nodes'][ni]['matrix'] = matrix.T.flatten().tolist()
            for key in ('translation', 'rotation', 'scale'):
                header['nodes'][ni].pop(key, None)
    items = {}
    warnings = [w for w in index.get('warnings', []) if 'still being prepared' not in w]
    skipped = header.get('extras', {}).get('unmeshed_item_ids', [])
    if skipped:
        warnings.append(f'3D geometry is unavailable for {len(skipped)} indexed objects. Their stored properties remain available; check the source model for those shapes.')
    if any(e['kind'] == 'proxy' for e in elements):
        warnings.append('Some model shapes have no building object type. Counts by object type may be incomplete; check the 3D shapes or export with object classifications.')
    for ni, (low, high) in boxes.items():
        guid = gltf.nodes[ni].name
        element = by_guid.get(guid)
        if element is None:
            raise ValueError('A converted object is missing from the property index.')
        bbox = [np.round(low - offset, 4).tolist(), np.round(high - offset, 4).tolist()]
        element['bbox_m'], element['bbox_source'] = bbox, 'glb'
        header['nodes'][ni].setdefault('extras', {})['kind'] = element['kind']
        items[guid] = {'node': guid, 'usd_name': usd_name(guid), 'bbox_m': bbox,
                       'storey': (element.get('storey') or {}).get('name'), 'kind': element['kind']}
        # Keep exact source quantities. Fill only dimensions the prior scene
        # builder also derived from a box, and explicitly retain that provenance.
        if not any('does not declare length units' in w for w in warnings):
            extent = np.asarray(bbox[1]) - bbox[0]
            dimensions = {'height_m': extent[1]}
            if element['kind'] in ('door', 'window'):
                dimensions['width_m'] = max(extent[0], extent[2])
            elif element['kind'] == 'wall':
                dimensions['length_m'] = max(extent[0], extent[2])
            else:
                dimensions = {}
            q, sources = element.setdefault('quantities', {}), element.setdefault('quantity_source', {})
            for key, value in dimensions.items():
                if key not in q:
                    q[key], sources[key] = round(float(value), 4), 'bbox'
    parts = header.get('extras', {}).get('aggregate_parts', {})
    rolled = {guid: (np.asarray(item['bbox_m'][0]), np.asarray(item['bbox_m'][1])) for guid, item in items.items()}
    def roll(guid, ancestors=frozenset()):
        if guid in rolled:
            return rolled[guid]
        if guid in ancestors or len(ancestors) > 5:
            return None
        children = [b for child in parts.get(guid, []) if (b := roll(child, ancestors | {guid})) is not None]
        if children:
            rolled[guid] = (np.min([b[0] for b in children], axis=0), np.max([b[1] for b in children], axis=0))
            return rolled[guid]
        return None
    for element in elements:
        if element['item_id'] not in items:
            bbox = roll(element['item_id'])
            element['bbox_m'] = [b.tolist() for b in bbox] if bbox is not None else None
            element['bbox_source'] = 'parts' if bbox is not None else None
    write_header(raw, out / 'scene.glb', header, binary_offset, binary_length)
    index.update(geometry='ready', warnings=warnings, coords='recentred in X/Z by origin_offset_m, Y-up (glTF), Y keeps real elevation')
    temp = out / 'tmp' / 'elements-scene.json'
    temp.write_text(json.dumps(index, ensure_ascii=False))
    temp.replace(out / 'elements.json')
    origin = np.asarray(header.get('extras', {}).get('source_origin_offset_m', [0., 0., 0.])) + offset
    licence = doc.get('licence') or ''
    manifest = {'doc_id': doc['doc_id'], 'glb': 'scene.glb', 'usdz': None, 'units': 'm', 'up': 'Y',
                'origin_offset_m': np.round(origin, 5).tolist(), 'storeys': index.get('storeys', []),
                'plan_image': None, 'items': items, 'warnings': warnings,
                'publishable': not (licence.startswith('CC-BY-ND') or licence.startswith('GPL'))}
    (out / 'scene.json').write_text(json.dumps(manifest, ensure_ascii=False))
    from pipeline.manifest_info import enrich
    enrich(out)  # info from the ready index; no second native IFC file
    return {'doc_id': doc['doc_id'], 'elements': len(elements), 'nodes': len(items),
            'storeys': len(manifest['storeys']), 's': round(time.time() - (started or time.time()), 1)}
