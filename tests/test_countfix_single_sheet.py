"""A PDF sheet's IFC has one level; 'on this floor' must count, and plan-map doors the 3D build dropped must be included."""
import json

import pytest

from engine.solvers.solve import solve


def _el(i, kind="door", bbox=True):
    return {"item_id": f"d{i}", "kind": kind, "ifc_class": "IfcDoor", "name": f"D{i}",
            "storey": {"name": "3RD FLOOR", "elevation_m": 0.0}, "quantities": {}, "props": {}}


def _pm(ids):
    return {"page": 1, "image": {"w": 1000, "h": 800}, "items": [
        {"item_id": f"d{i}", "kind": "door", "conf": 0.9, "bbox_px": [i * 10, 10, i * 10 + 8, 30], "props": {}} for i in ids]}


def _make(tmp_path, n_ifc, n_pm, kind="pdf"):
    d = tmp_path / "uploads__sheet"
    d.mkdir()
    (d / "doc.json").write_text(json.dumps({"title": "sheet", "kind": kind}))
    (d / "elements.json").write_text(json.dumps({"elements": [_el(i) for i in range(n_ifc)],
                                                 "storeys": [{"name": "3RD FLOOR", "elevation_m": 0.0}], "building": {}}))
    (d / "planmap-1.json").write_text(json.dumps(_pm(range(n_pm))))
    return tmp_path


@pytest.mark.parametrize("q", ["How many doors are on this floor?", "How many doors are on the floor?", "How many doors are there?"])
def test_this_floor_counts_instead_of_abstaining(tmp_path, q):
    root = _make(tmp_path, 5, 5)
    res = solve(q, "uploads__sheet", root=root)
    assert res["answer"]["value"] == 5, res["answer"]["text_md"]
    assert res["answer"]["value"] == 5


def test_plan_map_doors_without_wall_are_added_with_one_line_note(tmp_path):
    root = _make(tmp_path, 51, 53)
    res = solve("How many doors are on this floor?", "uploads__sheet", root=root)
    a = res["answer"]
    assert a["value"] == 53 and not a["abstained"]
    assert "2 of them have no drawn wall, so the 3D model shows 51" in a["text_md"]
    assert len(res["evidence"]["boxes"]) == 53


def test_non_pdf_models_are_untouched(tmp_path):
    root = _make(tmp_path, 51, 53, kind="ifc")
    assert solve("How many doors are on this floor?", "uploads__sheet", root=root)["answer"]["value"] == 51


def test_disjoint_identities_are_not_summed(tmp_path):
    root = _make(tmp_path, 5, 0)
    (root / "uploads__sheet" / "planmap-1.json").write_text(json.dumps(_pm(range(100, 110))))
    assert solve("How many doors are on this floor?", "uploads__sheet", root=root)["answer"]["value"] == 5


def test_named_missing_storey_still_abstains(tmp_path):
    root = _make(tmp_path, 5, 5)
    res = solve("How many doors are on the second floor?", "uploads__sheet", root=root)
    assert res["answer"]["value"] is None and "No matching floor" in res["answer"]["text_md"]
