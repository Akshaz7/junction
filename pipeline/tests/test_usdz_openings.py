"""Generated for demo geometry: preserve opening ids through GLB -> USDZ."""
import json

import numpy as np
import pytest
import trimesh
from PIL import Image
from pxr import Usd, UsdGeom

from pipeline import extrude, usdz


@pytest.mark.parametrize("node,expected", [
    ("door_with_under_scores", "door_with_under_scores"),
    ("door_with_under_scores:leaf", "door_with_under_scores"),
    ("door_with_under_scores:frame_abc", "door_with_under_scores"),
    ("door_with_under_scores_abc", "door_with_under_scores"),
    ("source:window:glass_abc", "source:window"),
    ("source:window", "source:window"),
    ("exact:leaf", "exact:leaf"),
    ("wall-infill:unknown", "wall-infill:unknown"),
    ("plan_floor", "plan_floor"),
])
def test_item_node_preserves_source_names(node, expected):
    mapping = dict.fromkeys(["door_with_under_scores", "source:window", "exact", "exact:leaf"])
    assert usdz._item_node(node, mapping) == expected


def test_extruded_opening_parts_reach_their_manifest_prims(tmp_path):
    items = [
        {"item_id": "door-001", "kind": "door", "bbox_px": [80, 90, 160, 105]},
        {"item_id": "window-001", "kind": "window", "bbox_px": [220, 90, 300, 105]},
    ]
    for it in items:
        it.update(props={}, conf=1, polygon_px=None)
    pm = {"doc_id": "generated-for-demo", "image": {"w": 400, "h": 300},
          "scale": {"m_per_px": .01, "method": "dimension", "confidence": 1}, "items": items}
    (tmp_path / "planmap-1.json").write_text(json.dumps(pm))
    Image.new("RGB", (400, 300), "white").save(tmp_path / "page-1.png")
    extrude.process(pm["doc_id"], tmp_path)
    manifest = json.loads((tmp_path / "scene.json").read_text())
    scene = trimesh.load_scene(tmp_path / "scene.glb", process=False)
    assert any(":" in n for n in scene.graph.nodes_geometry)
    usdz.process(pm["doc_id"], tmp_path)
    stage = Usd.Stage.Open(str(tmp_path / "scene.usdz"))
    for iid, info in manifest["items"].items():
        prim = stage.GetPrimAtPath("/Root/" + info["usd_name"])
        assert prim and prim.IsA(UsdGeom.Xform), iid
        meshes = [p for p in prim.GetChildren() if p.IsA(UsdGeom.Mesh)]
        source_nodes = [n for n in scene.graph.nodes_geometry if n == info["node"] or n.startswith(info["node"] + ":")]
        assert len(meshes) == len(source_nodes) >= 2
        points = np.concatenate([np.asarray(UsdGeom.Mesh(p).GetPointsAttr().Get()) for p in meshes])
        # Different locations and all parts preserved; not just an empty highlight parent.
        np.testing.assert_allclose([points.min(axis=0), points.max(axis=0)], info["bbox_m"], atol=.0011)
    assert stage.GetPrimAtPath("/Root/plan_floor/p0") or stage.GetPrimAtPath("/Root/plan_floor")
