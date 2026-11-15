"""Read dense GLB accessors in bounded windows, without a full triangle scene.

All array copies are limited to the selected triangle batch, including interleaved
accessors and instances. This reader intentionally rejects compressed/sparse
geometry instead of silently exporting incomplete AR geometry.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

DTYPES = {5120: 'i1', 5121: 'u1', 5122: '<i2', 5123: '<u2', 5125: '<u4', 5126: '<f4'}
WIDTHS = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}
READ_WINDOW = 256 * 1024
TRIANGLES_PER_BATCH = 8192


class GLB:
    def __init__(self, path: Path):
        self.path = path
        self.stream = path.open('rb')
        try:
            magic, version, total = struct.unpack('<III', self.stream.read(12))
            length, kind = struct.unpack('<II', self.stream.read(8))
            if magic != 0x46546C67 or version != 2 or kind != 0x4E4F534A or total != path.stat().st_size:
                raise ValueError('Invalid GLB header')
            self.header = json.loads(self.stream.read(length))
            self.binary_length, kind = struct.unpack('<II', self.stream.read(8))
            self.binary_offset = self.stream.tell()
            if kind != 0x004E4942 or self.binary_offset + self.binary_length != total:
                raise ValueError('Invalid GLB binary chunk')
        except Exception:
            self.stream.close()
            raise

    def close(self):
        self.stream.close()

    def buffer(self, view_index, offset=0, length=None):
        view = self.header['bufferViews'][view_index]
        length = view['byteLength'] - offset if length is None else length
        if view.get('buffer', 0) != 0 or offset < 0 or length < 0 or offset + length > view['byteLength']:
            raise ValueError('GLB accessor exceeds its buffer view')
        start = view.get('byteOffset', 0) + offset
        if start + length > self.binary_length:
            raise ValueError('GLB buffer view exceeds the binary chunk')
        self.stream.seek(self.binary_offset + start)
        data = self.stream.read(length)
        if len(data) != length:
            raise ValueError('Truncated GLB accessor')
        return data

    def accessor(self, index, selected):
        a = self.header['accessors'][index]
        if a.get('sparse'):
            raise ValueError('Sparse GLB accessors are not supported for AR export')
        ids = np.asarray(selected, dtype=np.int64).reshape(-1)
        width = WIDTHS[a['type']]
        dtype = np.dtype(DTYPES[a['componentType']])
        result = np.empty((len(ids), width), dtype=dtype)
        if not len(ids):
            return result
        if ids.min() < 0 or ids.max() >= a['count']:
            raise ValueError('GLB mesh has an out-of-range vertex index')
        view = self.header['bufferViews'][a['bufferView']]
        stride = view.get('byteStride', dtype.itemsize * width)
        if stride < dtype.itemsize * width:
            raise ValueError('Invalid GLB accessor stride')
        order = np.argsort(ids)
        ordered = ids[order]
        window_count = max(1, READ_WINDOW // stride)
        at = 0
        while at < len(ids):
            first = int(ordered[at])
            end = int(np.searchsorted(ordered, first + window_count, side='left'))
            last = int(ordered[end - 1])
            raw = self.buffer(a['bufferView'], a.get('byteOffset', 0) + first * stride,
                              (last - first) * stride + dtype.itemsize * width)
            window = np.ndarray((last - first + 1, width), dtype=dtype, buffer=raw,
                                strides=(stride, dtype.itemsize))
            result[order[at:end]] = window[ordered[at:end] - first]
            at = end
        if a.get('normalized') and np.issubdtype(dtype, np.integer):
            limit = np.iinfo(dtype)
            return np.maximum(result.astype(np.float32) / limit.max, -1.)
        return result

    def nodes(self):
        nodes = self.header.get('nodes', [])
        children = {c for n in nodes for c in n.get('children', [])}
        scenes = self.header.get('scenes', [])
        roots = scenes[self.header.get('scene', 0)].get('nodes', []) if scenes else [i for i in range(len(nodes)) if i not in children]
        def visit(index, parent, ancestors):
            if index in ancestors:
                raise ValueError('Cyclic GLB node hierarchy')
            node = nodes[index]
            if 'matrix' in node:
                local = np.asarray(node['matrix'], dtype=float).reshape(4, 4).T
            else:
                x, y, z, w = node.get('rotation', [0, 0, 0, 1])
                local = np.eye(4)
                local[:3, :3] = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                                 [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                                 [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
                local[:3, :3] *= node.get('scale', [1, 1, 1])
                local[:3, 3] = node.get('translation', [0, 0, 0])
            world = parent @ local
            if 'mesh' in node:
                yield node.get('name', str(index)), world, self.header['meshes'][node['mesh']]
            for child in node.get('children', []):
                yield from visit(child, world, ancestors | {index})
        for root in roots:
            yield from visit(root, np.eye(4), set())

    def batches(self, primitive):
        if primitive.get('extensions', {}).get('KHR_draco_mesh_compression'):
            raise ValueError('Draco-compressed GLB geometry is not supported for AR export')
        mode = primitive.get('mode', 4)
        if mode not in (4, 5, 6):
            raise ValueError(f'GLB primitive mode {mode} is not a triangle surface')
        attributes = primitive['attributes']
        count = self.header['accessors'][primitive.get('indices', attributes['POSITION'])]['count']
        def indices(start, end):
            selected = np.arange(start, end)
            if 'indices' in primitive:
                return self.accessor(primitive['indices'], selected).reshape(-1).astype(np.int64)
            return selected
        triangles = count // 3 if mode == 4 else max(0, count - 2)
        if mode == 4 and count % 3:
            raise ValueError('GLB triangle index count is not divisible by three')
        for start in range(0, triangles, TRIANGLES_PER_BATCH):
            end = min(start + TRIANGLES_PER_BATCH, triangles)
            if mode == 4:
                faces = indices(start * 3, end * 3).reshape(-1, 3)
            elif mode == 5:
                strip = indices(start, end + 2)
                faces = np.column_stack([strip[:-2], strip[1:-1], strip[2:]])
                odd = np.arange(start, end) % 2 == 1
                faces[odd] = faces[odd][:, [1, 0, 2]]
            else:
                rim = indices(start + 1, end + 2)
                faces = np.column_stack([np.full(end-start, indices(0, 1)[0]), rim[:-1], rim[1:]])
            selected, inverse = np.unique(faces, return_inverse=True)
            verts = self.accessor(attributes['POSITION'], selected)
            uv = self.accessor(attributes['TEXCOORD_0'], selected) if 'TEXCOORD_0' in attributes else None
            yield verts, inverse.reshape(-1, 3), uv

    def color(self, primitive, kind, defaults):
        material = self.header.get('materials', [])[primitive['material']] if 'material' in primitive else {}
        factor = material.get('pbrMetallicRoughness', {}).get('baseColorFactor')
        if factor is not None:
            # Match trimesh's uint8 material conversion used by the prior exporter.
            c = np.round(np.clip(factor, 0, 1) * 255) / 255
            return tuple(round(float(v), 3) for v in c[:3]), float(c[3])
        color = primitive['attributes'].get('COLOR_0')
        if color is not None:
            c = self.accessor(color, [0])[0].astype(float)
            a = self.header['accessors'][color]
            if not a.get('normalized') and a['componentType'] != 5126:
                c /= np.iinfo(np.dtype(DTYPES[a['componentType']])).max
            return tuple(round(float(v), 3) for v in c[:3]), float(c[3]) if len(c) > 3 else 1.
        return defaults.get(kind, (0.8, 0.8, 0.8)), 1.

    def texture(self, primitive, target):
        materials = self.header.get('materials', [])
        material = materials[primitive['material']] if 'material' in primitive else {}
        texture = material.get('pbrMetallicRoughness', {}).get('baseColorTexture')
        if texture is None:
            return None
        from io import BytesIO

        from PIL import Image
        image_index = self.header['textures'][texture['index']]['source']
        image = self.header['images'][image_index]
        if 'bufferView' not in image:
            raise ValueError('AR plan texture must be embedded in the GLB')
        name = f'plan-{image_index}.png'
        if not (target / name).exists():
            with Image.open(BytesIO(self.buffer(image['bufferView']))) as picture:
                picture.convert('RGB').save(target / name)
        return name
