"""Generated for demo geometry: bounded export retains source geometry and AR identity."""
import json
import shutil
import struct
import subprocess
import zipfile

import numpy as np
import pytest
import trimesh
from pxr import Usd, UsdGeom, UsdShade

from pipeline import usdz, usdz_glb


def write_glb(path, header, binary):
    encoded = json.dumps(header).encode()
    encoded += b' ' * (-len(encoded) % 4)
    binary += b'\0' * (-len(binary) % 4)
    path.write_bytes(struct.pack('<III', 0x46546C67, 2, 28 + len(encoded) + len(binary))
                     + struct.pack('<II', len(encoded), 0x4E4F534A) + encoded
                     + struct.pack('<II', len(binary), 0x004E4942) + binary)


def manifest(path, nodes):
    data = {'doc_id': 'generated-for-demo', 'items': {
        node: {'node': node, 'usd_name': f'i_{i}', 'kind': 'wall'} for i, node in enumerate(nodes)
    }, 'usdz': None}
    (path / 'scene.json').write_text(json.dumps(data))
    return data


def archive_payloads_aligned(path):
    with zipfile.ZipFile(path) as archive, path.open('rb') as stream:
        assert archive.testzip() is None
        for info in archive.infolist():
            stream.seek(info.header_offset + 26)
            name_length, extra_length = struct.unpack('<HH', stream.read(4))
            assert (info.header_offset + 30 + name_length + extra_length) % 64 == 0
            assert info.compress_type == zipfile.ZIP_STORED
            assert not info.flag_bits & 1


@pytest.mark.parametrize('zip64', [False, True])
def test_package_alignment_and_streamed_data(tmp_path, monkeypatch, zip64):
    if zip64:
        monkeypatch.setattr(zipfile, 'ZIP64_LIMIT', 256)
    files = []
    for i, size in enumerate([255, 29, 311]):
        p = tmp_path / f'asset-{i}.png'
        p.write_bytes(bytes([i]) * size)
        files.append(p)
    output = tmp_path / 'scene.usdz'
    usdz._write_package(output, files)
    archive_payloads_aligned(output)
    with zipfile.ZipFile(output) as archive:
        for p in files:
            assert archive.read(p.name) == p.read_bytes()


def test_interleaved_accessor_and_normalized_color(tmp_path, monkeypatch):
    # Non-zero offsets, byteStride and deliberately unsorted repeated selection.
    points = np.array([[0, 1, 2, 99], [3, 4, 5, 99], [6, 7, 8, 99]], dtype='<f4')
    binary = b'xxxx' + points.tobytes() + bytes([255, 128, 0, 255])
    header = {'bufferViews': [{'byteOffset': 4, 'byteLength': 48, 'byteStride': 16},
                              {'byteOffset': 52, 'byteLength': 4}],
              'accessors': [{'bufferView': 0, 'componentType': 5126, 'type': 'VEC3', 'count': 3},
                            {'bufferView': 1, 'componentType': 5121, 'type': 'VEC4', 'count': 1, 'normalized': True}]}
    path = tmp_path / 'a.glb'
    write_glb(path, header, binary)
    monkeypatch.setattr(usdz_glb, 'READ_WINDOW', 16)
    reader = usdz_glb.GLB(path)
    try:
        np.testing.assert_array_equal(reader.accessor(0, [2, 0, 2, 1]), points[[2, 0, 2, 1], :3])
        np.testing.assert_allclose(reader.accessor(1, [0]), [[1., 128/255, 0., 1.]])
        with pytest.raises(ValueError, match='out-of-range'):
            reader.accessor(0, [3])
    finally:
        reader.close()


@pytest.mark.parametrize('mode,expected', [(4, [[0, 1, 2], [3, 4, 5]]),
                                          (5, [[0, 1, 2], [2, 1, 3], [2, 3, 4], [4, 3, 5]]),
                                          (6, [[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 5]])])
@pytest.mark.parametrize('indexed', [False, True])
def test_triangle_topology_across_batches(tmp_path, monkeypatch, mode, expected, indexed):
    points = np.column_stack([np.arange(6), np.zeros((6, 2))]).astype('<f4')
    header = {'bufferViews': [{'byteLength': points.nbytes}],
              'accessors': [{'bufferView': 0, 'componentType': 5126, 'type': 'VEC3', 'count': 6}]}
    binary = points.tobytes()
    primitive = {'attributes': {'POSITION': 0}, 'mode': mode}
    if indexed:
        header['bufferViews'].append({'byteOffset': len(binary), 'byteLength': 12})
        header['accessors'].append({'bufferView': 1, 'componentType': 5123, 'type': 'SCALAR', 'count': 6})
        binary += np.arange(6, dtype='<u2').tobytes()
        primitive['indices'] = 1
    path = tmp_path / 'a.glb'
    write_glb(path, header, binary)
    monkeypatch.setattr(usdz_glb, 'TRIANGLES_PER_BATCH', 1)
    reader = usdz_glb.GLB(path)
    try:
        actual = np.concatenate([v[f][:, :, 0] for v, f, _ in reader.batches(primitive)])
        np.testing.assert_array_equal(actual, expected)
    finally:
        reader.close()


def test_batched_instances_parts_materials_and_arkit(tmp_path, monkeypatch):
    scene = trimesh.Scene()
    mesh = trimesh.creation.box()
    mesh.visual.face_colors = [70, 110, 180, 128]
    parent = np.eye(4)
    parent[:3, 3] = [4., 5., 6.]
    scene.graph.update(frame_to='parent', matrix=parent)
    transform = trimesh.transformations.rotation_matrix(.5, [0, 1, 0])
    transform[:3, :3] *= [2, 3, 4]
    scene.add_geometry(mesh, node_name='source_id:leaf', parent_node_name='parent', transform=transform)
    second = np.eye(4)
    second[:3, 3] = [-2, 3, 1]
    scene.add_geometry(mesh, node_name='source_id:frame', transform=second)
    scene.add_geometry(mesh, node_name='exact:leaf', transform=second)
    (tmp_path / 'scene.glb').write_bytes(scene.export(file_type='glb'))
    sj = manifest(tmp_path, ['source_id', 'exact:leaf'])
    monkeypatch.setattr(usdz_glb, 'TRIANGLES_PER_BATCH', 3)
    monkeypatch.setattr(usdz, 'LEAN', False)
    result = usdz.process('generated-for-demo', tmp_path)
    assert result['prims'] == 2
    assert result['parts'] == 12
    stage = Usd.Stage.Open(str(tmp_path / 'scene.usdz'))
    originals = trimesh.load_scene(tmp_path / 'scene.glb', process=False)
    for node in ['source_id:leaf', 'source_id:frame', 'exact:leaf']:
        usd_name = sj['items']['exact:leaf' if node == 'exact:leaf' else 'source_id']['usd_name']
        prim = stage.GetPrimAtPath('/Root/' + usd_name)
        parts = [UsdGeom.Mesh(p) for p in prim.GetChildren() if p.GetCustomDataByKey('source_node') == node]
        assert len(parts) == 4
        actual = np.concatenate([np.asarray(p.GetPointsAttr().Get())[np.asarray(p.GetFaceVertexIndicesAttr().Get()).reshape(-1, 3)] for p in parts])
        transform, geometry = originals.graph[node]
        expected = trimesh.transform_points(originals.geometry[geometry].vertices, transform)[originals.geometry[geometry].faces]
        np.testing.assert_allclose(actual, expected, atol=1e-6)
        for part in parts:
            assert UsdShade.MaterialBindingAPI(part).ComputeBoundMaterial()[0]
            assert len(part.GetNormalsAttr().Get()) == 9
    archive_payloads_aligned(tmp_path / 'scene.usdz')
    if shutil.which('usdchecker'):
        validation = subprocess.run(['usdchecker', '--arkit', str(tmp_path / 'scene.usdz')], check=False, text=True, capture_output=True)
        assert validation.returncode == 0, validation.stdout + validation.stderr
        assert 'Success!' in validation.stdout + validation.stderr


def test_failure_keeps_previous_package_and_manifest(tmp_path):
    (tmp_path / 'scene.usdz').write_bytes(b'previous-package')
    before = manifest(tmp_path, [])
    (tmp_path / 'scene.glb').write_bytes(b'corrupt-glb')
    with pytest.raises((ValueError, struct.error)):
        usdz.process('generated-for-demo', tmp_path)
    assert (tmp_path / 'scene.usdz').read_bytes() == b'previous-package'
    assert json.loads((tmp_path / 'scene.json').read_text()) == before
    assert not list(tmp_path.glob('.usdz-*'))


def test_floor_texture_orientation_and_embedded_asset(tmp_path):
    from PIL import Image
    image = Image.fromarray(np.array([[[255, 0, 0], [0, 255, 0]],
                                     [[0, 0, 255], [255, 255, 255]]], dtype=np.uint8))
    mesh = trimesh.Trimesh(vertices=[[0, 0, 0], [2, 0, 0], [2, 0, 1], [0, 0, 1]],
                           faces=[[0, 1, 2], [0, 2, 3]], process=False)
    mesh.visual = trimesh.visual.TextureVisuals(uv=[[0, 0], [1, 0], [1, 1], [0, 1]], image=image)
    scene = trimesh.Scene()
    scene.add_geometry(mesh, node_name='plan_floor')
    (tmp_path / 'scene.glb').write_bytes(scene.export(file_type='glb'))
    manifest(tmp_path, [])
    usdz.process('generated-for-demo', tmp_path)
    stage = Usd.Stage.Open(str(tmp_path / 'scene.usdz'))
    part = next(p for p in stage.GetPrimAtPath('/Root/plan_floor').GetChildren() if p.IsA(UsdGeom.Mesh))
    uv = np.asarray(UsdGeom.PrimvarsAPI(part).GetPrimvar('st').Get())
    np.testing.assert_allclose(uv, mesh.visual.uv)
    material = UsdShade.MaterialBindingAPI(part).ComputeBoundMaterial()[0]
    shader = stage.GetPrimAtPath(material.GetPath().AppendPath('tex'))
    asset = UsdShade.Shader(shader).GetInput('file').Get().path
    with zipfile.ZipFile(tmp_path / 'scene.usdz') as package:
        from io import BytesIO
        with Image.open(BytesIO(package.read(asset))) as stored:
            np.testing.assert_array_equal(np.asarray(stored), np.asarray(image))
    archive_payloads_aligned(tmp_path / 'scene.usdz')


def test_failure_during_geometry_keeps_previous_package(tmp_path, monkeypatch):
    scene = trimesh.Scene(trimesh.creation.box())
    (tmp_path / 'scene.glb').write_bytes(scene.export(file_type='glb'))
    node = next(iter(scene.graph.nodes_geometry))
    before = manifest(tmp_path, [node])
    (tmp_path / 'scene.usdz').write_bytes(b'previous-package')
    def fail(*args, **kwargs):
        raise RuntimeError('injected write failure')
    monkeypatch.setattr(usdz.Builder, 'mesh', fail)
    with pytest.raises(RuntimeError, match='injected write failure'):
        usdz.process('generated-for-demo', tmp_path)
    assert (tmp_path / 'scene.usdz').read_bytes() == b'previous-package'
    assert json.loads((tmp_path / 'scene.json').read_text()) == before
    assert not list(tmp_path.glob('.usdz-*'))


def test_collapsed_tiny_mesh_retains_manifest_prim(tmp_path):
    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box(extents=[.0001, .0001, .0001]), node_name='tiny_source')
    (tmp_path / 'scene.glb').write_bytes(scene.export(file_type='glb'))
    manifest(tmp_path, ['tiny_source'])
    result = usdz.process('generated-for-demo', tmp_path)
    assert result['prims'] == 1
    assert result['parts'] == 0
    stage = Usd.Stage.Open(str(tmp_path / 'scene.usdz'))
    assert stage.GetPrimAtPath('/Root/i_0')
