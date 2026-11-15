import json

import pytest

from engine.wall_details import details


def put(root, name, value):
    directory = root / "drawing"
    directory.mkdir(exist_ok=True)
    (directory / name).write_text(json.dumps(value))


def plan(root, *, scale=.01, props=None, text=None):
    put(root, "planmap-1.json", {"page": 1, "storey": "Level 1", "scale": {"m_per_px": scale, "method": "door-prior"}, "items": [
        {"item_id": "wall-1", "kind": "wall", "props": props or {}, "polygon_px": [[0, 0], [400, 0], [400, 20], [0, 20]]},
        {"item_id": "door-1", "kind": "door", "bbox_px": [100, 0, 200, 20], "props": {"host_wall_id": "wall-1", "width_m": 1, "height_m": 2}},
    ]})
    if text:
        put(root, "text-1.json", {"text": text})


def test_scan_estimate_dimensions_and_deductions_are_per_face(tmp_path):
    plan(tmp_path)
    wall = details("drawing", "wall-1", tmp_path)
    assert wall["status"] == "Estimate"
    assert (wall["length_m"], wall["thickness_m"], wall["height_m"]) == (4, .2, 2.7)
    assert wall["height_source"] == "ASSUMED (no wall height on this drawing)" and wall["height_assumed"]
    assert wall["storey"] == "Level 1"
    assert wall["opening_count"] == 1
    assert wall["faces"][0]["gross_m2"] == pytest.approx(10.8)
    assert wall["faces"][0]["opening_m2"] == pytest.approx(2)
    assert wall["faces"][0]["net_m2"] == pytest.approx(8.8)
    assert "door-prior" in wall["method"]


def test_printed_height_is_labelled(tmp_path):
    plan(tmp_path, text="Wall height: 3200 mm")
    wall = details("drawing", "wall-1", tmp_path)
    assert wall["height_m"] == 3.2
    assert wall["height_source"] == "printed on this drawing"
    assert wall["status"] == "Estimate"


def test_vector_pdf_planmap_uses_its_polyline_and_recorded_height(tmp_path):
    plan(tmp_path, props={"centerline_px": [[0, 10], [400, 10]], "thickness_m": .2,
                          "height_m": 3.2, "height_source": "printed on this drawing", "is_external": False})
    path = tmp_path / "drawing/planmap-1.json"
    pm = json.loads(path.read_text())
    pm["scale"]["method"] = "printed"
    pm["items"][0]["source"] = "pdf_vector"
    path.write_text(json.dumps(pm))
    wall = details("drawing", "wall-1", tmp_path)
    assert wall["length_m"] == 4
    assert wall["height_source"] == "printed on this drawing"
    assert wall["classification"] == "Internal"
    assert wall["faces"][0]["net_m2"] == pytest.approx(10.8)


def test_new_ifc_sidecar_carries_dimensions_without_needing_source_quantities(tmp_path):
    from engine.wallarea import measure_ifc
    from engine.tests.test_wallarea import model_file
    measured = measure_ifc(model_file(tmp_path, qto=False, rotation=.7))
    wall, = measured["walls"]
    assert wall["length_m"] == pytest.approx(10)
    assert wall["thickness_m"] == pytest.approx(.2)


@pytest.mark.parametrize("inside", [0, 1, None])
def test_ifc_uses_actual_sides_and_only_labels_recorded_orientation(tmp_path, inside):
    put(tmp_path, "wallgeom.json", {"storeys": [], "walls": [{"item_id": "wall-1", "height_m": 3,
        "is_external": True, "inside_side": inside, "axis_source": "IFC axis", "openings": [{"item_id": "o"}],
        "floors": [{"storey": "Ground", "gross_sides_m2": [12, 15], "net_sides_m2": [10, 12]}]}]})
    wall = details("drawing", "wall-1", tmp_path, quantities={"length_m": 4, "width_m": .3})
    assert wall["status"] == "Measured"
    assert wall["height_source"] == "measured from this wall's 3D geometry in the file"
    assert wall["height_basis"] == "ifc_geometry" and "top of the wall minus its bottom" in wall["height_how"]
    assert wall["faces"][0]["opening_m2"] == 2
    assert wall["faces"][1]["opening_m2"] == 3
    assert wall["classification"] == "External (facade)"
    if inside is None:
        assert wall["faces"][0]["label"] == "Face A"
        assert "orientation" in " ".join(wall["notes"])
    else:
        assert wall["faces"][inside]["label"] == "Inner face"


def test_missing_ifc_geometry_never_falls_back_to_assumed_scan_height(tmp_path):
    put(tmp_path, "elements.json", {"elements": []})
    wall = details("drawing", "wall-1", tmp_path)
    assert wall["status"] == "Not available"
    assert wall["height_m"] is None
    assert wall["opening_count"] is None
    assert all(f["gross_m2"] is None for f in wall["faces"])


def test_no_scale_reports_missing_area_instead_of_guessing(tmp_path):
    plan(tmp_path, scale=None)
    wall = details("drawing", "wall-1", tmp_path)
    assert wall["length_m"] is None
    assert wall["faces"][0]["net_m2"] is None
    assert wall["status"] == "Estimate"
    assert "No scaled" in " ".join(wall["notes"])


def test_generated_scene_component_reuses_the_existing_reader_and_estimator(tmp_path, monkeypatch):
    from PIL import Image
    from shapely.geometry import box
    from pipeline import raster_walls
    from engine import linked
    put(tmp_path, "doc.json", {"doc_id": "drawing", "kind": "raster"})
    plan(tmp_path)
    Image.new("L", (500, 500), 255).save(tmp_path / "drawing/page-1.png")
    put(tmp_path, "scene.json", {"source_planmap": "planmap-1.json", "origin_offset_m": [0, 0, 0],
        "defaults": {"wall_m": 2.7}, "items": {"wall-r001": {"kind": "wall", "storey": "Floor 1", "bbox_m": [[0, 0, 0], [4, 2.7, .2]]}}})
    monkeypatch.setattr(raster_walls, "read", lambda gray, mpp: {"walls": [box(0, 0, 400, 20)]})
    result = linked.lookup("drawing", "wall-r001", tmp_path)
    assert result["name"] == "Wall (generated for demo)"
    wall = result["wall_details"]
    assert wall["status"] == "Estimate"
    assert wall["length_m"] == 4
    assert wall["thickness_m"] == .2
    assert wall["height_source"] == "ASSUMED (no wall height on this drawing)" and wall["height_assumed"]
    assert wall["faces"][0]["net_m2"] == pytest.approx(8.8)
    # A stale scene must not inherit dimensions from a different raster component.
    monkeypatch.setattr(raster_walls, "read", lambda gray, mpp: {"walls": [box(100, 100, 400, 200)]})
    assert details("drawing", "wall-r001", tmp_path)["length_m"] is None
    # Saved outlines survive later changes to the raster reader.
    scene = json.loads((tmp_path / "drawing/scene.json").read_text())
    scene["items"]["wall-r001"]["props"] = {"wall_outline_px": [[0, 0], [400, 0], [400, 20], [0, 20]], "height_m": 2.7}
    put(tmp_path, "scene.json", scene)
    assert details("drawing", "wall-r001", tmp_path)["length_m"] == 4


def test_linked_wall_api_and_tag_return_the_same_measurement(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from server import config
    from server.linked_routes import router
    put(tmp_path, "doc.json", {"doc_id": "drawing", "kind": "raster", "formats": ["png"]})
    plan(tmp_path)
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "artifacts_dir", lambda: tmp_path)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/api/docs/drawing/items/wall-1")
        assert response.status_code == 200
        data = response.json()
        assert data["wall_details"]["faces"][0]["net_m2"] == pytest.approx(8.8)
        assert client.get(f"/api/docs/drawing/tags/{data['tag']}").json()["wall_details"] == data["wall_details"]
        assert client.get("/api/docs/drawing/items/no-wall").status_code == 404


def test_connected_raster_network_gets_perimeter_based_estimate(tmp_path):
    from engine import wallarea
    ring = [[0, 0], [400, 0], [400, 400], [0, 400]]
    hole = [[20, 20], [380, 20], [380, 380], [20, 380]]
    pm = {"page": 1, "scale": {"m_per_px": .01, "method": "door-prior"}, "items": [
        {"item_id": "wall-r001", "kind": "wall", "polygon_px": ring,
         "props": {"network_estimate": True, "holes_px": [hole], "height_m": 2.7, "height_source": "assumed for generated 3D"}}]}
    out = wallarea.estimate_planmaps("drawing", tmp_path, "", planmaps=[pm])
    wall = out["walls"][0]
    # perimeter = 16 m + 14.4 m = 30.4 m; area = 16 - 12.96 = 3.04 m2
    assert wall["length_m"] == pytest.approx(15.2)
    assert wall["thickness_m"] == pytest.approx(2 * 3.04 / 30.4)
    assert wall["gross_m2"] == pytest.approx(30.4 * 2.7)
    # without the opt-in flag the old honest refusal stands
    pm["items"][0]["props"].pop("network_estimate")
    assert wallarea.estimate_planmaps("drawing", tmp_path, "", planmaps=[pm])["skipped"]


def test_assumed_height_wording_and_answer_flags_every_area(tmp_path):
    from engine import wallarea
    assert wallarea.ASSUMED_HEIGHT_LABEL == "ASSUMED (no wall height on this drawing)"
    assert wallarea.height_basis(wallarea.ASSUMED_HEIGHT_LABEL) == "assumed"
    assert wallarea.height_basis("stated in your question") == "question"
    assert wallarea.height_basis("printed on this drawing") == "printed"
