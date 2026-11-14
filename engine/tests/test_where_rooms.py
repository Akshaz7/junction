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
