from server.schema import validate_answer


def _ans(route):
    return {"answer_id": "a", "question": "q", "doc_ids": ["d"], "answer": {"text_md": "t", "value": None, "unit": None, "confidence": 0.5, "abstained": False},
            "citations": [], "evidence": {"boxes": [], "scene": {"doc_id": "d", "highlight_item_ids": [], "camera_target_item_id": None}},
            "trace": [], "route": route, "cost": {"usd_total": 0.0, "calls": []}, "latency_ms": 1}


def test_unknown_route_is_mapped_not_a_crash():
    for r in ("multi", "analytics"):
        a = _ans(r)
        validate_answer(a)
        assert a["route"] == "hybrid"


def test_known_routes_untouched():
    for r in ("index", "planmap", "vlm", "hybrid"):
        a = _ans(r)
        validate_answer(a)
        assert a["route"] == r


def test_truly_unknown_route_still_fails_validation():
    import jsonschema
    import pytest
    with pytest.raises(jsonschema.ValidationError):
        validate_answer(_ans("not-a-route"))
