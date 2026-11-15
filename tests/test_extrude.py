import json
from pathlib import Path

import pytest
import trimesh

ROOT = Path(__file__).resolve().parent.parent
IDS = ["swiss_dwellings__site289-bldg536-floor2149", "swiss_dwellings__site11861-bldg18508-floor50415",
       "swiss_dwellings__site1869-bldg2903-floor13293"]


@pytest.mark.parametrize("doc_id", IDS)
def test_glb_nodes_and_extents(doc_id):
    from pipeline import extrude
    art = ROOT / "artifacts" / doc_id
    extrude.process(doc_id, art)
    pm = json.loads((art / "planmap-1.json").read_text())
    scene = trimesh.load(art / "scene.glb")
    names = set(scene.graph.nodes)
    want = [i["item_id"] for i in pm["items"] if i["kind"] in ("wall", "door", "window", "room")]
    assert want and all(n in names for n in want)
    k = pm["scale"]["m_per_px"]
    ex = scene.extents
    assert abs(ex[0] - pm["image"]["w"] * k) / (pm["image"]["w"] * k) < 0.01
    assert abs(ex[2] - pm["image"]["h"] * k) / (pm["image"]["h"] * k) < 0.01
    assert abs(ex[1] - 2.7) < 0.05  # wall height default
    sj = json.loads((art / "scene.json").read_text())
    assert set(sj["items"]) == set(want)
    # outward-facing prisms: positive volume for a wall
    w = next(i["item_id"] for i in pm["items"] if i["kind"] == "wall")
    node = scene.graph[w]
    mesh = scene.geometry[node[1]]
    assert mesh.volume > 0


def _synthetic(tmp_path, with_stairs=True):
    from PIL import Image
    pm = {"image": {"w": 200, "h": 200}, "scale": {"m_per_px": 0.05},
          "items": [
              {"item_id": "wall-001", "kind": "wall", "bbox_px": [20, 90, 180, 110], "polygon_px": [[20, 90], [180, 90], [180, 110], [20, 110]], "props": {}},
              {"item_id": "window-001", "kind": "window", "bbox_px": [60, 92, 100, 108], "polygon_px": None, "props": {}},
              {"item_id": "door-001", "kind": "door", "bbox_px": [130, 92, 150, 108], "polygon_px": None, "props": {}},
              {"item_id": "toilet-001", "kind": "toilet", "bbox_px": [30, 120, 45, 140], "polygon_px": None, "props": {}},
              {"item_id": "bathtub-001", "kind": "bathtub", "bbox_px": [60, 120, 100, 140], "polygon_px": None, "props": {}},
              {"item_id": "room-001", "kind": "room", "bbox_px": [20, 20, 180, 90], "polygon_px": None, "props": {"room_type": "kitchen"}},
          ] + ([{"item_id": "stairs-001", "kind": "stairs", "bbox_px": [20, 150, 80, 180], "polygon_px": None, "props": {}}] if with_stairs else [])}
    (tmp_path / "planmap-1.json").write_text(json.dumps(pm))
    Image.new("RGB", (200, 200), "white").save(tmp_path / "page-1.png")
    return pm


def test_openings_group_nodes_and_stairs(tmp_path):
    from pipeline import extrude
    _synthetic(tmp_path)
    r = extrude.process("synthetic", tmp_path)
    assert r["glb_kb"] < 500
    sc = trimesh.load(tmp_path / "scene.glb")
    assert {"wall-001", "window-001", "door-001", "toilet-001", "bathtub-001", "stairs-001", "room-001"} <= set(sc.graph.nodes)
    sj = json.loads((tmp_path / "scene.json").read_text())
    assert set(sj["items"]) == {"wall-001", "window-001", "door-001", "toilet-001", "bathtub-001", "stairs-001", "room-001"}
    # window group carries frame + glass children
    assert {"window-001:frame", "window-001:glass"} <= set(sc.graph.nodes)
    # the wall is cut: its mesh has less volume than the solid prism, and the door leaf is within the opening
    wall = sc.geometry[sc.graph["wall-001"][1]]
    solid = 8.0 * 1.0 * 2.7  # 160px*0.05 x 20px*0.05 x 2.7
    assert 0 < wall.volume < solid - 0.5
    # stairs are low geometry, never wall height
    st = sj["items"]["stairs-001"]["bbox_m"]
    assert 0.5 < st[1][1] <= 1.0
    assert "scale_method" in sj


def test_tread_grid_component_is_not_a_wall():
    from shapely.geometry import box
    from pipeline import extrude
    pm = {"items": [{"kind": "stairs", "bbox_px": [100, 100, 200, 200]}, {"kind": "door", "bbox_px": [0, 0, 5, 5]}]}
    boxes = extrude._stair_boxes(pm)
    assert boxes == [[100, 100, 200, 200]]
    assert extrude._is_tread_grid(box(105, 105, 195, 195), boxes)
    assert not extrude._is_tread_grid(box(0, 0, 90, 10), boxes)
    assert not extrude._is_tread_grid(box(0, 0, 90, 10), [])
