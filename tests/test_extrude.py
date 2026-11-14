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
    names = set(scene.graph.nodes_geometry)
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
