"""IFC answers carry numbered 2D boxes from the per-storey plan pages (QA-LIVE #5)."""
import json
from pathlib import Path

import pytest

from engine.solvers.solve import solve

ROOT = Path(__file__).resolve().parents[2] / "deploy" / "demo_artifacts"
DOC = "ifc_bench__ac20-arc"

pytestmark = pytest.mark.skipif(not (ROOT / DOC / "planmap-2.json").exists(), reason="no ac20 plans")


def test_ground_floor_doors_have_boxes_on_the_right_page():
    ans = solve("How many doors are on the ground floor?", DOC, root=ROOT)
    assert not ans["answer"]["abstained"]
    boxes = ans["evidence"]["boxes"]
    assert boxes and len(boxes) == len(ans["evidence"]["scene"]["highlight_item_ids"])
    pages = json.loads((ROOT / DOC / "pages.json").read_text())["pages"]
    ground = next(p["page"] for p in pages if p["storey"] == "Erdgeschoss")
    assert {b["page"] for b in boxes} == {ground}
    assert [b["label"] for b in boxes] == [str(n) for n in range(1, len(boxes) + 1)]
    assert [c["page"] for c in ans["citations"]] == [ground]
    # a box lies on its door: the centre is inside the door's projected footprint (plan-map box of the same item)
    pm = {i["item_id"]: i for i in json.loads((ROOT / DOC / f"planmap-{ground}.json").read_text())["items"]}
    for b in boxes:
        x0, y0, x1, y1 = b["bbox_px"]
        px0, py0, px1, py1 = pm[b["item_id"]]["bbox_px"]
        assert pm[b["item_id"]]["kind"] == "door"
        assert px0 <= (x0 + x1) / 2 <= px1 and py0 <= (y0 + y1) / 2 <= py1


def test_box_centre_is_inside_the_door_footprint_in_metres():
    """Independent of the plan-map boxes: project the element's bbox_m with the page's recorded transform."""
    ans = solve("How many doors are on the ground floor?", DOC, root=ROOT)
    pages = json.loads((ROOT / DOC / "pages.json").read_text())["pages"]
    ground = next(p["page"] for p in pages if p["storey"] == "Erdgeschoss")
    pr = json.loads((ROOT / DOC / f"planmap-{ground}.json").read_text())["projection"]
    els = {e["item_id"]: e for e in json.loads((ROOT / DOC / "elements.json").read_text())["elements"]}
    tol = 3.0  # px, rasterisation
    for b in ans["evidence"]["boxes"]:
        (x0, _, z0), (x1, _, z1) = els[b["item_id"]]["bbox_m"]
        cx, cy = (b["bbox_px"][0] + b["bbox_px"][2]) / 2, (b["bbox_px"][1] + b["bbox_px"][3]) / 2
        assert (x0 - pr["x0"]) * pr["ppm"] + 40 - tol <= cx <= (x1 - pr["x0"]) * pr["ppm"] + 40 + tol
        assert (z0 - pr["z0"]) * pr["ppm"] + 40 - tol <= cy <= (z1 - pr["z0"]) * pr["ppm"] + 40 + tol
