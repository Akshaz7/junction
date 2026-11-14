"""Generated-for-demo geometry: gaps, diagonal walls, storey placement and source ids."""
import json
from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image, ImageDraw
from shapely.affinity import rotate
from shapely.geometry import Point, Polygon, box

from pipeline import extrude
from pipeline.tests.measure_opening_gaps import masonry, measure, section


def item(iid, kind, bbox, **props):
    return {'item_id': iid, 'kind': kind, 'bbox_px': bbox, 'polygon_px': None, 'props': props, 'conf': .95}


def drawing(tmp_path, items, size=(400, 300)):
    pm = {'doc_id': 'generated-for-demo', 'image': {'w': size[0], 'h': size[1]},
          'scale': {'m_per_px': .01, 'method': 'dimension', 'confidence': 1}, 'items': items}
    (tmp_path / 'planmap-1.json').write_text(json.dumps(pm))
    Image.new('RGB', size, 'white').save(tmp_path / 'page-1.png')
    return pm


@pytest.mark.parametrize('kind', ['window', 'door'])
@pytest.mark.parametrize('vertical', [False, True])
def test_gap_infill_covers_full_width_and_leaves_opening_empty(tmp_path, kind, vertical):
    boxes = [[20, 90, 140, 110], [220, 90, 370, 110], [140, 96, 220, 104]]
    if vertical:
        boxes = [[y0, x0, y1, x1] for x0, y0, x1, y1 in boxes]
    drawing(tmp_path, [item('wall-001', 'wall', boxes[0]), item('wall-002', 'wall', boxes[1]),
                       item(kind + '-001', kind, boxes[2])], size=(400, 400))
    extrude.process('generated-for-demo', tmp_path)
    manifest = json.loads((tmp_path / 'scene.json').read_text())
    scene = trimesh.load_scene(tmp_path / 'scene.glb')
    result = measure(tmp_path)
    assert result['in_gap'] == result['incomplete_width_support'] == 0
    walls = masonry(scene, manifest)
    center = Point((-1, -.2) if vertical else (-.2, -1))
    assert not section(walls, 1.5).buffer(1e-5).covers(center)
    assert section(walls, .45).buffer(1e-5).covers(center) == (kind == 'window')
    assert set(manifest['items']) == {'wall-001', 'wall-002', kind + '-001'}
    # Infill thickness comes from the 20px neighbour, rather than the 8px icon.
    transform, geometry = scene.graph['wall-infill:' + kind + '-001']
    mesh = scene.geometry[geometry].copy().apply_transform(transform)
    assert mesh.extents[0 if vertical else 2] == pytest.approx(.2)


def test_diagonal_opening_inherits_neighbour_axis_and_thickness():
    wall = rotate(box(-3, -.1, -.5, .1), 35, origin=(0, 0))
    opening = rotate(box(-.5, -.04, .5, .04), 35, origin=(0, 0))
    x0, z0, x1, z1 = opening.bounds
    local, matrix, footprint, host = extrude._fit_opening((x0, x1, z0, z1, 'x'), [('wall-001', wall)])
    assert host == 'wall-001'
    assert local[3] - local[2] == pytest.approx(.2)
    assert abs(matrix[2, 0] / matrix[0, 0]) == pytest.approx(np.tan(np.radians(35)))
    assert footprint.distance(wall) < .001


def test_one_wall_height_per_storey(tmp_path):
    drawing(tmp_path, [item('wall-001', 'wall', [20, 20, 170, 40], height_m=3.0),
                       item('wall-002', 'wall', [20, 60, 170, 80], height_m=3.1),
                       item('wall-003', 'wall', [20, 100, 170, 120], height_m=4.0),
                       item('window-001', 'window', [70, 22, 120, 38])])
    extrude.process('generated-for-demo', tmp_path)
    manifest = json.loads((tmp_path / 'scene.json').read_text())
    assert {it['bbox_m'][1][1] for it in manifest['items'].values() if it['kind'] == 'wall'} == {3.1}
    assert manifest['defaults']['wall_m'] == 3.1


def test_raster_wall_gap_has_infill(tmp_path):
    drawing(tmp_path, [item('window-001', 'window', [140, 91, 220, 109])])
    image = Image.open(tmp_path / 'page-1.png')
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 90, 140, 110), fill='black')
    draw.rectangle((220, 90, 370, 110), fill='black')
    image.save(tmp_path / 'page-1.png')
    extrude.process('generated-for-demo', tmp_path, raster_walls=True)
    result = measure(tmp_path)
    assert result['in_gap'] == result['incomplete_width_support'] == 0


def test_two_layout_blocks_stack_and_keep_item_nodes(tmp_path):
    items = []
    for floor, x in enumerate((20, 270)):
        # Six structural items in each block, with an opening separating two walls.
        for i, bbox in enumerate(([x, 40, x + 60, 60], [x + 100, 40, x + 160, 60],
                                   [x, 60, x + 20, 200], [x + 140, 60, x + 160, 200],
                                   [x, 200, x + 160, 220])):
            items.append(item(f'wall-{floor}-{i}', 'wall', bbox))
        items.append(item(f'window-{floor}', 'window', [x + 60, 45, x + 100, 55]))
    drawing(tmp_path, items, size=(480, 280))
    extrude.process('generated-for-demo', tmp_path)
    manifest = json.loads((tmp_path / 'scene.json').read_text())
    assert [s['elevation_m'] for s in manifest['storeys']] == [0, 3]
    assert {it['item_id'] for it in items} <= set(manifest['items'])
    scene = trimesh.load_scene(tmp_path / 'scene.glb')
    for iid, it in manifest['items'].items():
        assert it['node'] in scene.graph.nodes
        if it['kind'] == 'wall':
            assert it['bbox_m'][0][1] == (0 if it['storey'] == 'Floor 1' else 3)
    assert measure(tmp_path)['incomplete_width_support'] == 0
    assert 'generated for demo' in manifest['note']


def test_label_only_storeys_do_not_split_geometry(tmp_path):
    items = [item('wall-001', 'wall', [20, 30, 350, 50])]
    for i, label in enumerate(('GROUND FLOOR', 'UPPER FLOOR')):
        it = item(f'text-{i}', 'text', [20, 80 + i * 30, 150, 100 + i * 30])
        it['label'] = label
        items.append(it)
    drawing(tmp_path, items)
    extrude.process('generated-for-demo', tmp_path)
    manifest = json.loads((tmp_path / 'scene.json').read_text())
    assert len(manifest['storeys']) == 1


def test_connected_raster_wall_network_uses_local_thickness(tmp_path):
    drawing(tmp_path, [item('window-001', 'window', [140, 35, 220, 43])], size=(600, 400))
    image = Image.open(tmp_path / 'page-1.png')
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 370, 280), outline='black', width=40)
    draw.rectangle((140, 15, 220, 65), fill='white')
    image.save(tmp_path / 'page-1.png')
    extrude.process('generated-for-demo', tmp_path, raster_walls=True)
    scene = trimesh.load_scene(tmp_path / 'scene.glb')
    transform, geometry = scene.graph['wall-infill:window-001']
    infill = scene.geometry[geometry].copy().apply_transform(transform)
    assert infill.extents[2] == pytest.approx(.39, abs=.03)
    assert measure(tmp_path)['incomplete_width_support'] == 0


def test_corner_to_corner_window_keeps_its_own_axis():
    # Raster plans lose the host wall when a window spans it end to end: only the
    # perpendicular end walls are near. The pane must still run along the window.
    ends = [('wall-001', box(-1.7, -2, -1.5, .2)), ('wall-002', box(1.5, -2, 1.7, .2))]
    local, matrix, footprint, host = extrude._fit_opening((-1.5, 1.5, -.2, .2, 'x'), ends)
    assert local[1] - local[0] == pytest.approx(3.0)
    assert abs(matrix[0, 0]) == pytest.approx(1.0)
    assert local[3] - local[2] <= .5
    assert host in {'wall-001', 'wall-002'}


def test_infill_stays_inside_the_gap_and_the_wall_faces():
    """A fat or long opening box must not grow masonry into or past the walls beside it."""
    walls = box(-3, -.1, -.8, .1).union(box(.8, -.1, 3, .1))
    # a perpendicular wall meeting the left end must not widen the band either
    walls = walls.union(box(-1.0, -1.5, -.8, 1.5))
    gap = extrude._infill_gap((-1.2, 1.2, -.3, .3, 'x'), np.eye(4), walls)
    assert gap.intersection(walls).area < 1e-6
    assert gap.bounds == pytest.approx((-.8, -.1, .8, .1), abs=1e-6)


def test_lone_opening_infill_is_wall_thin():
    gap = extrude._infill_gap((-.5, .5, -1., 1., 'x'), np.eye(4), Polygon())
    assert gap.bounds[3] - gap.bounds[1] == pytest.approx(extrude.INFILL_LONE_T)


def test_window_sill_infill_never_closes_a_door(tmp_path):
    drawing(tmp_path, [item('wall-001', 'wall', [20, 90, 140, 110]), item('wall-002', 'wall', [220, 90, 370, 110]),
                       item('window-001', 'window', [140, 96, 220, 104]),
                       item('door-001', 'door', [140, 92, 180, 108])], size=(400, 400))
    extrude.process('generated-for-demo', tmp_path)
    manifest = json.loads((tmp_path / 'scene.json').read_text())
    walls = masonry(trimesh.load_scene(tmp_path / 'scene.glb'), manifest)
    assert not section(walls, .45).buffer(1e-5).covers(Point(-.4, -1))   # door half stays open
    assert section(walls, .45).buffer(1e-5).covers(Point(.0, -1))        # window half keeps its sill wall
