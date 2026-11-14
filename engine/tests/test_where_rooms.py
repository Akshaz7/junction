from engine.answer import answer


def test_where_room_from_planmap_labels_is_code_only():
    a = answer("Where are the bathrooms?", ["swiss_dwellings__site1001-bldg2083-floor9389"])
    assert a["route"] == "planmap" and not a["answer"]["abstained"]
    assert a["cost"]["usd_total"] == 0 and a["latency_ms"] < 1500
    assert len(a["evidence"]["boxes"]) == 4


def test_where_room_without_label_falls_through(monkeypatch):
    monkeypatch.setenv("READER", "0")
    monkeypatch.setenv("READ_DRAWING", "0")
    monkeypatch.setenv("MODELS_FAKE", "1")
    a = answer("Where is the sauna?", ["swiss_dwellings__site1001-bldg2083-floor9389"])
    assert a["route"] != "planmap" or "sauna" not in a["answer"]["text_md"].lower()


def test_ifc_where_rooms_in_code_with_storey_boxes():
    a = answer("Where are the toilets?", ["ifc_bench__ac20-arc"])
    assert a["route"] == "index" and a["cost"]["usd_total"] == 0 and a["latency_ms"] < 1500
    assert len(a["evidence"]["boxes"]) == 8 and len(a["evidence"]["scene"]["highlight_item_ids"]) == 8
    b = answer("Where are the toilets on the ground floor?", ["ifc_bench__ac20-arc"])
    assert len(b["evidence"]["boxes"]) == 2


def test_ifc_missing_room_is_a_fast_code_answer():
    a = answer("Where is the kitchen?", ["ifc_bench__ac20-arc"])
    assert "No kitchen is modelled" in a["answer"]["text_md"] and a["latency_ms"] < 1500


def test_ifc_stairs_get_boxes():
    a = answer("Where are the stairs?", ["ifc_bench__ac20-arc"])
    assert len(a["evidence"]["boxes"]) == 4
