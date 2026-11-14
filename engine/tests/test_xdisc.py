"""Geometry fixtures generated for demo; real-sheet evidence is in the report."""
import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest

from engine import xdisc


def pair():
    rooms = [{"item_id": "r1", "stable_id": "space-left", "number": "101", "label": "Office", "area_m2": 20,
              "bbox_px": [10, 30, 30, 40], "polygon_px": [[0, 0], [48, 0], [48, 100], [0, 100]],
              "ceiling_height_m": 2.45, "ceiling_type": "Type A"},
             {"item_id": "r2", "stable_id": "space-right", "label": "Store", "area_m2": 10,
              "bbox_px": [60, 30, 80, 40], "polygon_px": [[52, 0], [100, 0], [100, 100], [52, 100]]}]
    base = {"doc_id": "architect", "page": 1, "image": {"w": 100, "h": 100}, "rooms": rooms, "words": [],
            "walls": [{"item_id": "wall", "kind": "wall", "polygon_px": [[48, 0], [52, 0], [52, 100], [48, 100]],
                       "fire_rating": "EI60", "fire_rating_source": {"quote": "EI60", "bbox_px": [80, 90, 90, 95]}}]}
    service = {"doc_id": "services", "page": 2, "image": {"w": 100, "h": 100}, "words": [], "complete": {"terminals": True},
               "terminals": [{"item_id": "t1", "bbox_px": [10, 10, 14, 14], "flow_ls": 25, "role": "supply"},
                             {"item_id": "t2", "bbox_px": [20, 10, 24, 14], "flow_ls": 15, "role": "supply"},
                             {"item_id": "t3", "bbox_px": [30, 10, 34, 14], "flow_ls": 10, "role": "extract"}],
               "ducts": [{"item_id": "d1", "bbox_px": [10, 48, 90, 52], "centreline_px": [[10, 50], [90, 50]], "width_px": 4}]}
    reg = {"status": "aligned", "matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]], "residual_px": .1, "anchor_count": 4}
    return base, service, reg


def test_arithmetic_crossings_and_dual_sheet_proof():
    b, s, reg = pair()
    result = xdisc.analyse(b, s, alignment=reg, threshold_ls_m2=2.1, ceiling_below_m=2.5)
    row = result["airflow"][0]
    assert row["supply_ls"] == 40 and row["supply_ls_m2"] == 2
    assert row["extract_ls"] == 10 and row["below_user_threshold"] is True
    assert "25 + 15 = 40 l/s; 40 / 20 = 2 l/s/m²" in row["arithmetic"][0]
    assert {e["doc_id"] for e in row["evidence"]} == {"architect", "services"}
    assert {e["page"] for e in row["evidence"]} == {1, 2}
    crossing = result["crossings"][0]
    assert crossing["fire_rating"] == "EI60" and crossing["room_ids"] == ["r1", "r2"]
    assert len(result["low_ceilings"]) == 1
    assert len(result["missing_air"]) == 2


@pytest.mark.parametrize("change", ["incomplete", "unknown-role", "missing-value", "outside-page", "boundary"])
def test_missing_evidence_never_becomes_zero_or_a_partial_total(change):
    b, s, reg = pair()
    if change == "incomplete": s["complete"]["terminals"] = False
    if change == "unknown-role": s["terminals"][0]["role"] = "unknown"
    if change == "missing-value": s["terminals"][0]["flow_ls"] = None
    if change == "outside-page": s["image"]["w"] = 20
    if change == "boundary": s["terminals"][0]["bbox_px"] = [47, 10, 49, 14]
    r = xdisc.analyse(b, s, alignment=reg)
    assert r["airflow"][0]["supply_ls"] is None
    if change != "missing-value": assert not any(f["room_id"] == "r1" for f in r["missing_air"])


def test_labels_without_polygons_and_unsigned_legend():
    b, s, reg = pair()
    b["rooms"] = []
    b["words"] = [{"text": "16,5 m²", "bbox_px": [10, 10, 40, 15]}]
    s["words"] = [{"text": "-20 l/s", "bbox_px": [10, 10, 30, 15]},
                  {"text": "+13.000", "bbox_px": [10, 20, 30, 25]},
                  {"text": "+25", "bbox_px": [10, 30, 30, 35]}]
    r = xdisc.analyse(b, s, alignment=reg)
    assert r["rooms"][0]["area_m2"] == 16.5
    assert r["rooms"][0]["polygon_px"] is None and not r["airflow"]
    assert len(r["airflow_labels"]) == 1 and r["airflow_labels"][0]["role"] is None
    s["flow_signs"] = {"-": "extract", "+": "supply", "source": {"quote": "- extract"}}
    assert xdisc.airflow_labels(s)[0]["role"] == "extract"


def test_imperial_area_and_flow_units_and_ceiling_units():
    assert xdisc.room_table({"words": [{"text": "100 SF", "bbox_px": [0, 0, 10, 5]}]})[0]["area_m2"] == pytest.approx(9.290304)
    assert xdisc.airflow_labels({"words": [{"text": "36 m³/h", "bbox_px": [0, 0, 10, 5]}]})[0]["flow_ls"] == 10
    b, _, _ = pair()
    b["rooms"][0].pop("ceiling_height_m")
    b["words"] = [{"text": "Type B h=2450", "bbox_px": [10, 20, 30, 24]}]
    b["ceiling_types"] = {"Type B": {"source": {"quote": "Type B: suspended ceiling"}}}
    assert xdisc.room_table(b)[0].get("ceiling_height_m") is None
    b["height_unit"] = "mm"
    assert xdisc.room_table(b)[0]["ceiling_height_m"] == 2.45


def test_room_height_tag_is_not_automatically_a_ceiling():
    b, _, _ = pair()
    b["rooms"][0].pop("ceiling_height_m")
    b["words"] = [{"text": "DOOR h=2100 mm", "bbox_px": [10, 20, 30, 24]}]
    r = xdisc.room_table(b)[0]
    assert r.get("ceiling_height_m") is None
    assert r["unclassified_height_labels"][0]["height_m"] == 2.1


def test_pdf_adapter_scales_points_and_registration_and_preserves_unknown_role():
    raw = {"W_pt": 100, "H_pt": 100, "words": [{"text": "16.5", "bbox": [10, 10, 20, 15]}, {"text": "m²", "bbox": [21, 10, 25, 15]}]}
    s = xdisc.adapt_pdf_page(raw, doc_id="doc", image_size=(200, 200),
                            rooms=[{"number": "101", "label_bbox": [10, 10, 25, 15], "polygon": [[0, 0], [100, 0], [100, 100]], "area_printed_m2": 16.5}],
                            terminals=[{"bbox": [10, 10, 12, 12], "ls": 25}])
    assert s["rooms"][0]["bbox_px"] == [20, 20, 50, 30]
    assert s["rooms"][0]["polygon_px"][-1] == [200, 200]
    assert s["terminals"][0]["role"] == "unknown" and s["terminals"][0]["flow_ls"] == 25
    assert xdisc.room_table({"words": s["words"]})[0]["area_m2"] == 16.5
    target = {"point_to_pixel": [3, 3]}
    reg = xdisc.adapt_alignment({"T": [[1, 0, 10], [0, 1, 20], [0, 0, 1]], "residual": 1, "matches": 4}, target, s)
    assert xdisc.transform([[20, 20]], reg)[0] == pytest.approx([60, 90])
    assert reg["residual_px"] == 3
    assert xdisc.adapt_alignment({"T": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}, target, s)["status"] == "needs_manual"


def test_adapter_missing_or_incompatible_provider_is_explicit():
    class Missing:
        pass
    result = xdisc.prepare_mep_pair({}, {}, provider=Missing())
    assert result["ducts"] == [] and result["limitations"] and result["complete"]["terminals"] is False


def test_corrupt_cache_is_handled_as_missing_evidence(tmp_path):
    d = tmp_path / "bad"; d.mkdir()
    (d / "xdisc-1.json").write_text("{invalid")
    r = xdisc.answer("Airflow per room", ["bad", "missing"], tmp_path)
    assert r["answer"]["value"] is None and "cannot be established" in r["answer"]["text_md"]


def test_no_implicit_rule_and_no_unverified_fire_rating():
    b, s, reg = pair()
    b["walls"][0].pop("fire_rating_source")
    result = xdisc.analyse(b, s, alignment=reg)
    assert "below_user_threshold" not in result["airflow"][0]
    assert result["crossings"][0]["fire_rating"] is None
    assert not result["low_ceilings"]


def test_tangent_and_candidate_geometry_do_not_create_crossings():
    b, s, reg = pair()
    s["ducts"][0]["centreline_px"] = [[48, 0], [48, 100]]
    assert not xdisc.analyse(b, s, alignment=reg)["crossings"]
    s["ducts"][0]["centreline_px"] = [[0, 50], [100, 50]]
    s["ducts"][0]["classification"] = "candidate"
    assert not xdisc.analyse(b, s, alignment=reg)["crossings"]


def test_rotation_scale_translation_and_failed_registration():
    b, s, reg = pair()
    reg["matrix"] = [[0, -.5, 100], [.5, 0, 0], [0, 0, 1]]
    for t in s["terminals"]:
        t["bbox_px"] = xdisc._mapped_box(t["bbox_px"], reg, True)
    for d in s["ducts"]:
        d["centreline_px"] = xdisc.transform(d["centreline_px"], reg, True)
    s["image"] = {"w": 200, "h": 200}
    r = xdisc.analyse(b, s, alignment=reg)
    assert r["airflow"][0]["supply_ls"] == 40 and len(r["crossings"]) == 1
    r = xdisc.analyse(b, s, alignment={"status": "needs_manual", "matrix": None})
    assert not r["airflow"] and not r["crossings"] and r["limitations"]


def test_change_impact_uses_stable_rooms_and_does_not_invent_board_area():
    b, s, reg = pair()
    previous = deepcopy(b); previous["doc_id"] = "old"
    previous["rooms"][0]["area_m2"] = 15
    r = xdisc.change_impact(previous, b, s, alignment=reg)
    imp = r["impacts"][0]
    assert imp["changed"]["area_m2"] == {"before": 15, "after": 20}
    assert imp["terminal_ids"] == ["t1", "t2", "t3"] and imp["service_ids"] == ["d1"]
    assert imp["wall_area_m2"] is None and imp["plasterboard_area_m2"] is None
    assert {e["doc_id"] for e in imp["evidence"]} == {"old", "architect", "services"}


def test_chat_hook_schema_reasoning_and_no_models(tmp_path, monkeypatch):
    b, s, reg = pair()
    for sheet in (b, s):
        folder = tmp_path / sheet["doc_id"]; folder.mkdir()
        (folder / "xdisc-1.json").write_text(json.dumps(sheet))
    monkeypatch.setattr(xdisc, "align", lambda *args: reg)
    from engine import reasoning
    r = xdisc.answer("Airflow per room below 2.1 l/s/m²", [b["doc_id"], s["doc_id"]], tmp_path)
    schema = json.loads((Path(__file__).parents[2] / "server/schemas/answer.schema.json").read_text())
    jsonschema.validate(r, schema)
    assert r["cost"] == {"usd_total": 0, "calls": []}
    assert all(c["doc_id"] in ("architect", "services") for c in r["citations"])
    assert all(box["doc_id"] for box in r["evidence"]["boxes"])
    old_card = deepcopy(r["reasoning"])
    reasoning.attach(r, "Airflow per room", tmp_path)
    assert r["reasoning"] == old_card
    assert xdisc.answer("Count windows", ["architect", "services"], tmp_path) is None


def test_public_answer_routes_before_general_sheet_question_handlers(tmp_path, monkeypatch):
    b, s, reg = pair()
    for sheet in (b, s):
        folder = tmp_path / sheet["doc_id"]; folder.mkdir()
        (folder / "xdisc-1.json").write_text(json.dumps(sheet))
    import importlib
    mod = importlib.import_module("engine.answer")
    monkeypatch.setattr(mod, "_root", lambda: tmp_path)
    monkeypatch.setattr(xdisc, "align", lambda *args: reg)
    monkeypatch.setenv("MODELS_FAKE", "1")
    monkeypatch.setenv("ANSWER_GUARD_OFF", "1")
    r = mod.answer("Airflow per room", ["architect", "services"])
    assert r.get("xdisc") is not None and r["answer"]["value"] == 2
    assert r["cost"]["usd_total"] == 0 and r["reasoning"]["steps"][2]["kind"] == "calculated"


def test_shared_label_alignment_rejects_dimensions_and_collinear_anchors():
    b = {"image": {"w": 1000, "h": 1000}, "words": [{"text": name, "bbox_px": [x, y, x+10, y+5]} for name, x, y in [("R101", 100, 100), ("R102", 800, 100), ("R103", 500, 800), ("R104", 50, 600)]]}
    s = deepcopy(b)
    for w in s["words"]:
        w["bbox_px"] = [w["bbox_px"][0]+20, w["bbox_px"][1]+30, w["bbox_px"][2]+20, w["bbox_px"][3]+30]
    a = xdisc.align(b, s)
    assert a["status"] == "aligned" and a["residual_px"] < 1e-8
    assert xdisc.transform([[120, 130]], a)[0] == pytest.approx([100, 100])
    for w in b["words"] + s["words"]:
        w["text"] = "6000"
    assert xdisc.align(b, s)["matrix"] is None
