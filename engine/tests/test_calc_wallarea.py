"""The wall-area hook preserves its gross/cut operands, sheets and units."""
import math

from engine.calc import attach, validate


def wall_result(value=12, unit="m2", **report_fields):
    return {"doc_ids": ["wall-source"], "answer": {"value": value, "unit": unit, "abstained": False, "text_md": f"**{value} {unit}**"},
            "wallarea": {"source": "IFC body side faces", "requested_quantity": "net", "value_m2": 12,
                         "gross_m2": 20, "opening_m2": 8, "net_m2": 12,
                         "rows": [{"item_id": "wall-1", "label": "Wall", "gross_m2": 20, "opening_m2": 8, "net_m2": 12}],
                         "margin_m2": .01, "margin_pct": .01 / 12 * 100, **report_fields}}


def test_wall_net_area_uses_actual_cut_operands(tmp_path):
    r = attach(wall_result(), "Net wall surface?", tmp_path)
    c = r["reasoning"]["calc"]
    assert c["status"] == "complete", c["issues"]
    assert c["steps"][0]["operation"] == "subtract"
    assert [i["value"] for i in c["steps"][0]["inputs"]] == [20, 8]
    assert c["margin"] == r["reasoning"]["margin"]


def test_inconsistent_measured_net_area_is_not_complete(tmp_path):
    r = wall_result(13)
    r["wallarea"]["rows"][0]["net_m2"] = 13
    r["wallarea"]["value_m2"] = 13
    c = attach(r, "Net wall surface?", tmp_path)["reasoning"]["calc"]
    assert c["status"] == "incomplete"


def test_sheets_convert_dimensions_and_round_up(tmp_path):
    needed = 12 * 1.1
    sheets = math.ceil(needed / 2.88 - 1e-10)
    r = wall_result(sheets, "count", sheet_count=sheets, sheet_area_m2=2.88, order_area_m2=needed, waste_pct=10)
    c = attach(r, "How many sheets 1200 x 2400 mm with 10% waste?", tmp_path)["reasoning"]["calc"]
    assert c["status"] == "complete", c["issues"]
    conversions = [s for s in c["steps"] if s["operation"] == "convert"]
    assert len(conversions) == 2 and conversions[0]["inputs"][1]["value"] == .001
    assert c["result"]["value"] == 5 and c["margin"]["unit"] == "count" and c["margin"]["value"] is None


def test_area_order_allowance_is_secondary_result(tmp_path):
    c = attach(wall_result(waste_pct=10, order_area_m2=13.2), "Wall area with 10% waste?", tmp_path)["reasoning"]["calc"]
    assert c["status"] == "complete", c["issues"]
    assert c["result"]["value"] == 12
    assert c["result"]["additional"][0]["value"] == 13.2
