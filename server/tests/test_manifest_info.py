"""pipeline.manifest_info: names, room areas and door widths land on scene.json items; ids and tags stay as they were."""
import json
from pathlib import Path

from pipeline import manifest_info

ART = Path(__file__).resolve().parents[2] / "deploy" / "demo_artifacts"


def _items(doc):
    return json.loads((ART / doc / "scene.json").read_text())["items"]


def test_ac20_rooms_have_names_and_areas():
    rooms = [v for v in _items("ifc_bench__ac20-arc").values() if v["kind"] == "room"]
    assert len(rooms) == 82
    assert all(r["name"] and r["props"]["area_m2"] > 0 for r in rooms)
    keller = {r["name"]: r for r in rooms if r["storey"] == "Keller"}
    assert "Besprechungsraum I" in keller
    assert keller["Besprechungsraum I"]["props"]["area_m2"] == 23.9
    assert keller["Besprechungsraum I"]["props"]["area_source"] == "qto"
    assert keller["Besprechungsraum I"]["tag"] == "R1"  # tags survive


def test_enrich_keeps_ids_and_adds_door_width(tmp_path):
    sj = {"items": {"d1": {"node": "d1", "usd_name": "i_x", "bbox_m": [[0, 0, 0], [0.9, 2.1, 0.1]], "storey": "S",
                           "kind": "door", "tag": "D1"},
                    "r1": {"node": "r1", "usd_name": "i_y", "bbox_m": [[0, 0, 0], [4, 2.7, 3]], "storey": "S",
                           "kind": "room", "tag": "R1"}}, "source_planmap": "planmap-1.json"}
    pm = {"items": [{"item_id": "r1", "kind": "room", "label": "KITCHEN", "props": {"room_type": "kitchen", "area_m2": 11.5}}]}
    (tmp_path / "scene.json").write_text(json.dumps(sj))
    (tmp_path / "planmap-1.json").write_text(json.dumps(pm))
    manifest_info.enrich(tmp_path)
    out = json.loads((tmp_path / "scene.json").read_text())["items"]
    assert out["r1"]["name"] == "KITCHEN" and out["r1"]["props"]["area_m2"] == 11.5
    assert out["d1"]["props"]["width_m"] == 0.9 and out["d1"]["props"]["axis"] == "x"
    assert out["d1"]["tag"] == "D1" and out["d1"]["usd_name"] == "i_x" and out["d1"]["bbox_m"] == sj["items"]["d1"]["bbox_m"]
