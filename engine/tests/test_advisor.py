from pathlib import Path

import pytest

from engine import advisor
from engine.rules import load_rules

ROOT = Path(__file__).resolve().parents[2] / "artifacts"
DOC = "ifc_bench__ac20-arc"
pytestmark = pytest.mark.skipif(not (ROOT / DOC).exists(), reason="artifact missing")
RULES = {r["id"]: r for r in load_rules()}
DOOR = "3qloCPnZDEQBom1ZjBlwJP"          # Keller, 1.0 m interior door
EXIT = "Tür-019"


def _exit_id():
    from engine.solvers.data import load_doc
    from engine.solvers import ARTIFACTS
    return next(i.item_id for i in load_doc(DOC, ARTIFACTS).items if i.name == EXIT)


def _valid(c):
    assert c["kind"] in ("warning", "option", "info") and len(c["title"]) <= 60 and len(c["body"]) <= 200
    s = c["source"]
    assert s["ref"] in RULES and s["quote"] and RULES[s["ref"]]["quote"].startswith(s["quote"]) and len(s["quote"]) <= 200
    assert c["item_ids"]


def test_narrowing_a_door_returns_rule_card():
    cards = advisor.advise(DOC, {"op": "narrow", "item_ids": [DOOR], "detail": {"width_mm": 700}})
    assert cards and cards[0]["kind"] == "warning" and cards[0]["source"]["ref"] == "fi-acc-door-clear-width"
    assert DOOR in cards[0]["item_ids"]
    for c in cards:
        _valid(c)


def test_edit_with_no_rule_returns_no_cards():
    assert advisor.advise(DOC, {"op": "highlight", "item_ids": [DOOR]}) == []
    assert advisor.advise(DOC, {"op": "narrow", "item_ids": [DOOR], "detail": {"width_mm": 1100}}) == []
    assert advisor.advise(DOC, {"op": "hide", "item_ids": ["unknown"]}) == []


def test_hiding_the_only_outer_door_cites_exit_rule():
    cards = advisor.advise(DOC, {"op": "hide", "item_ids": [_exit_id()]})
    assert cards and cards[0]["source"]["ref"] == "fi-fire-exits-per-storey"
    for c in cards:
        _valid(c)


def test_no_edit_returns_at_most_three_sourced_cards():
    cards = advisor.advise(DOC)
    assert 0 < len(cards) <= 3
    for c in cards:
        _valid(c)


def _only_door_of_a_room():
    from engine.solvers.data import load_doc
    from engine.solvers import ARTIFACTS
    d = load_doc(DOC, ARTIFACTS)
    rd = advisor._room_doors(d)
    return next(v[0] for v in rd.values() if len(v) == 1)


def test_hiding_only_door_of_room_cites_route_rule():
    door = _only_door_of_a_room()
    cards = advisor.advise(DOC, {"op": "hide", "item_ids": [door]})
    hit = [c for c in cards if c["source"]["ref"] == "fi-fire-route-length"]
    assert hit and hit[0]["kind"] == "warning" and door in hit[0]["item_ids"]
    for c in cards:
        _valid(c)


def test_material_and_move_edits_without_a_rule_return_no_cards():
    assert advisor.advise(DOC, {"op": "material", "item_ids": [DOOR], "detail": {"material": "oak"}}) == []
    assert advisor.advise(DOC, {"op": "restore", "item_ids": [DOOR]}) == []
