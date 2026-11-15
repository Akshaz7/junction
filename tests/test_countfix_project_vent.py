"""Project totals use the same plan-map add-back; a sheet that does not draw doors says so instead of 0 boxes."""
import json

from engine.solvers.solve import solve


def _doc(root, name, title, n_ifc, pm_ids, pm_kind="door"):
    d = root / name
    d.mkdir()
    (d / "doc.json").write_text(json.dumps({"title": title, "kind": "pdf", "formats": ["pdf", "ifc"]}))
    els = [{"item_id": f"d{i}", "kind": "door", "ifc_class": "IfcDoor", "name": f"D{i}",
            "storey": {"name": "3RD FLOOR", "elevation_m": 0.0}, "quantities": {}, "props": {}} for i in range(n_ifc)]
    (d / "elements.json").write_text(json.dumps({"elements": els, "storeys": [{"name": "3RD FLOOR", "elevation_m": 0.0}], "building": {}}))
    (d / "planmap-1.json").write_text(json.dumps({"page": 1, "image": {"w": 1000, "h": 800}, "items": [
        {"item_id": f"d{i}", "kind": pm_kind, "conf": 0.9, "bbox_px": [i * 10, 10, i * 10 + 8, 30], "props": {}} for i in pm_ids]}))


def test_vent_sheet_without_drawn_doors_says_so(tmp_path):
    _doc(tmp_path, "uploads__vent", "L30301 ventilation systems 3rd floor", 51, [], pm_kind="duct")
    a = solve("How many doors are on this floor?", "uploads__vent", root=tmp_path)["answer"]
    assert a["value"] is None
    assert "does not draw doors" in a["text_md"] and "51" in a["text_md"]


def test_project_total_matches_single_sheet_with_note(tmp_path):
    _doc(tmp_path, "uploads__ark", "ARK-103-03 floor plan 3rd floor", 51, range(53))
    _doc(tmp_path, "uploads__vent", "L30301 ventilation systems 3rd floor block U", 51, [], pm_kind="duct")
    assert solve("How many doors are on this floor?", "uploads__ark", root=tmp_path)["answer"]["value"] == 53
    from engine.projects import multidoc
    t = multidoc.answer("How many doors are there in total?", ["uploads__ark", "uploads__vent"], tmp_path)["answer"]["text_md"]
    assert "**53 doors**" in t and "2 have no drawn wall, so the 3D model shows 51" in t
