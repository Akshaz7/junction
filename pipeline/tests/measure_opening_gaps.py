"""Measure masonry support on exported GLBs (read-only; suitable for scratch rebuilds)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import Point, MultiPoint
from shapely.ops import polygonize, unary_union
from shapely.geometry import LineString


def masonry(scene, manifest):
    wall_ids = {iid for iid, it in manifest['items'].items() if it['kind'] == 'wall'}
    meshes = []
    for node in scene.graph.nodes_geometry:
        ancestor = node
        is_wall = node.startswith('wall-infill:')
        while ancestor is not None:
            is_wall |= ancestor in wall_ids
            ancestor = scene.graph.transforms.parents.get(ancestor)
        if is_wall:
            transform, geometry = scene.graph[node]
            mesh = scene.geometry[geometry].copy()
            mesh.apply_transform(transform)
            meshes.append(mesh)
    return trimesh.util.concatenate(meshes) if meshes else None


def section(mesh, height):
    if mesh is None:
        return Point().buffer(0)
    segments = trimesh.intersections.mesh_plane(mesh, [0, 1, 0], [0, height, 0])
    lines = [LineString(np.round(segment[:, [0, 2]], 6)) for segment in segments]
    return unary_union(list(polygonize(unary_union(lines)))) if lines else Point().buffer(0)


def measure(art):
    manifest = json.loads((art / 'scene.json').read_text())
    scene = trimesh.load_scene(art / 'scene.glb')
    mesh = masonry(scene, manifest)
    elevations = {s['name']: s['elevation_m'] for s in manifest['storeys']}
    slices = {}
    missing, width_gaps, total = [], [], 0
    for iid, item in manifest['items'].items():
        if item['kind'] not in ('window', 'door'):
            continue
        total += 1
        node = iid + ':frame'
        transform, geometry = scene.graph[node]
        frame = scene.geometry[geometry].copy()
        frame.apply_transform(transform)
        # Sample the frame's actual long direction, allowing arbitrary wall rotations.
        points = np.unique(np.round(frame.vertices[:, [0, 2]], 5), axis=0)
        center = points.mean(axis=0)
        rectangle = np.array(MultiPoint(points).minimum_rotated_rectangle.exterior.coords)[:4]
        edges = np.roll(rectangle, -1, axis=0) - rectangle
        axis = edges[np.argmax(np.linalg.norm(edges, axis=1))]
        axis /= np.linalg.norm(axis)
        projection = (points - center) @ axis
        samples = [center + axis * u for u in np.linspace(projection.min() * .9, projection.max() * .9, 9)]
        elevation = elevations[item['storey']]
        heights = [elevation + 2.4] + ([elevation + .45] if item['kind'] == 'window' else [])
        support = []
        for height in heights:
            if height not in slices:
                slices[height] = section(mesh, height).buffer(2e-5)
            support.append(slices[height])
        if not all(s.covers(Point(center)) for s in support):
            missing.append(iid)
        if not all(s.covers(Point(p)) for s in support for p in samples):
            width_gaps.append(iid)
    return {'openings': total, 'in_gap': len(missing), 'in_gap_percent': round(100 * len(missing) / total, 2) if total else 0,
            'incomplete_width_support': len(width_gaps), 'missing_ids': missing, 'width_gap_ids': width_gaps}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('scratch', type=Path, nargs='+')
    args = ap.parse_args()
    for path in args.scratch:
        print(json.dumps({'scratch': str(path), **measure(path)}))
