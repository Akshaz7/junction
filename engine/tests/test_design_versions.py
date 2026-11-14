"""Design versions (saved 3D edits): exact item-id diff between any two versions, code only."""
from pathlib import Path

import pytest

from engine import design_versions as dv

ROOT = Path(__file__).resolve().parents[2] / "artifacts"
DOC = "ifc_bench__ac20-arc"
RASTER = "cubicasa5k__colorful-11397"
DOOR = "0YIVuBlyXF3PI_fXw2b_vJ"      # Tür-015, tag D30, Erdgeschoss (page 2)
WINDOW = "0$6TgsobP9PPnqNXqQeskc"    # Fenster-005, tag W81, page 2


def test_clean_edits_validates_and_normalises():
    e = dv.clean_edits({"removed": ["b", "a", "a", 7], "moved": {"x": [0.1, 0], "y": [0.0, 0.0]}, "materials": {"w": "Glass"}})
    assert e == {"removed": ["a", "b"], "moved": {"x": [0.1, 0.0]}, "materials": {"w": "Glass"}}
    assert dv.clean_edits({"moved": {"x": [1]}}) is None and dv.clean_edits("nope") is None
    assert dv.clean_edits({"moved": {"x": [1e9, 0]}}) is None
    assert dv.is_empty(dv.clean_edits({}))


def test_diff_between_any_two_snapshots():
    v1 = {"removed": ["d1"], "moved": {"w1": [1.0, 0.0]}, "materials": {}}
    v2 = {"removed": ["d2"], "moved": {"w1": [1.0, 0.0], "w2": [0.0, -0.5]}, "materials": {"wall": "Glass"}}
    got = {(c["action"], c["item_id"]) for c in dv.diff(v1, v2)}
    assert got == {("removed", "d2"), ("added", "d1"), ("moved", "w2"), ("material", "wall")}  # w1 moved in both: same
    back = {(c["action"], c["item_id"]) for c in dv.diff(v2, v1)}
    assert back == {("removed", "d1"), ("added", "d2"), ("moved", "w2"), ("material", "wall")}
    assert dv.diff(v1, v1) == []


@pytest.mark.skipif(not (ROOT / DOC).exists(), reason="artifact missing")
def test_ac20_removed_door_and_moved_window_carry_ids_tags_and_boxes():
    edited = {"removed": [DOOR], "moved": {WINDOW: [1.0, 0.0]}, "materials": {}}
    res = dv.compare(ROOT / DOC, dv.empty(), edited)
    assert res["source"] == "edit-diff" and res["counts"] == {"removed": 1, "added": 0, "moved": 1, "material": 0}
    door, win = res["changes"]
    assert door["type"] == "removed" and door["item_id"] == DOOR and door["tag"] == "D30" and door["kind"] == "door"
    assert door["page"] == 2 and door["bbox_px_v1"] == [802.3, 416.4, 857.5, 422.0] and door["bbox_px_v2"] is None
    assert door["description"] == "Door D30 (Tür-015) was removed."
    assert win["type"] == "modified" and win["field"] == "position" and win["action"] == "moved" and win["tag"] == "W81"
    shift = 1.0 / 0.018103  # metres -> plan pixels on this page
    assert win["bbox_px_v2"][0] == pytest.approx(win["bbox_px_v1"][0] + shift, abs=0.2)
    assert win["description"] == "Window W81 (Fenster-005) moved 1.0 m east."
    assert [p["n_changes"] for p in res["pages"]] == [0, 2, 0, 0, 0]
    # The reverse comparison (edited -> original) puts the door back and moves the window west.
    rev = dv.compare(ROOT / DOC, edited, dv.empty())
    assert [(c["action"], c["item_id"]) for c in rev["changes"]] == [("added", DOOR), ("moved", WINDOW)]
    assert "1.0 m west" in rev["changes"][1]["description"]


@pytest.mark.skipif(not (ROOT / RASTER).exists(), reason="artifact missing")
def test_raster_plan_map_doc():
    res = dv.compare(ROOT / RASTER, dv.empty(), {"removed": ["door-001"], "moved": {}, "materials": {}})
    (c,) = res["changes"]
    assert c["item_id"] == "door-001" and c["tag"] == "D1" and c["page"] == 1 and c["bbox_px_v1"] == [43.0, 156.0, 77.0, 168.0]
