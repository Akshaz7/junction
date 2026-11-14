import json
from pathlib import Path

import pytest

from engine.router import parse
from engine.router import route as R
from engine.router.evaluate import score

ROOT = Path(__file__).resolve().parents[2]
TEST_SET = ROOT / "data/sets/router_test.jsonl"


@pytest.mark.parametrize("q,t,k,s", [
    ("How many doors are shown on this floor plan?", "count", "door", "whole-doc"),
    ("How many rooms labelled 'Küche' are there on this floor?", "count", "room", "storey"),
    ("What is the net floor area of room 12 (Kitchen) in m²?", "area", "room", "room"),
    ("What is the total length of walls on level 2?", "length", "wall", "storey"),
    ("What is the volume of the slabs in the building?", "volume", "slab", "whole-doc"),
    ("What wall types are used in the building, with their quantities?", "text", "wall", "whole-doc"),
    ("Which window is the largest?", "text", "window", None),
    ("How many toilets and sinks are drawn?", "count", "toilet", None),
])
def test_parse_examples(q, t, k, s):
    p = parse(q)
    assert (p.type, p.kind, p.scope) == (t, k, s) and p.matched


def test_unparseable_is_not_matched():
    assert not parse("hello there").matched
    assert not parse("How many are there?").matched  # no kind


def test_quoted_room_name_is_not_a_kind():
    assert parse("How many rooms labelled 'Door' are there on this floor?").kind == "room"


def test_fallback_uses_model_only_when_rules_fail(monkeypatch):
    seen = []

    class Res:
        json = {"type": "count", "kind": "door", "scope": "none"}
        cost_usd = 0.0001
        provider = "nvidia"

    monkeypatch.setattr(R, "call", lambda task, msg, **k: (seen.append(task), Res())[1])
    assert R.route("How many doors are on this floor plan?").source == "rules" and not seen
    r = R.route("hello there")
    assert r.source == "model" and seen == ["route"] and r.parsed.kind == "door" and r.parsed.scope is None


def test_fallback_survives_model_failure(monkeypatch):
    def boom(*a, **k):
        raise R.ModelError("down")
    monkeypatch.setattr(R, "call", boom)
    assert R.route("hello there").source == "rules-guess"


def test_schema_enums():
    assert "door" in R.KINDS and R.SCHEMA["properties"]["type"]["enum"][0] == "count"


@pytest.mark.skipif(not TEST_SET.exists(), reason="data/sets/router_test.jsonl not present")
def test_rules_accuracy_on_router_test():
    rows = [json.loads(l) for l in TEST_SET.open()]
    s = score(rows)
    assert s["accuracy"] >= 0.90, s["accuracy"]
    uniq = list({r["question"]: r for r in rows}.values())
    assert score(uniq)["accuracy"] >= 0.90
