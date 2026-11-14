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
    assert advisor.advise(DOC, {"op": "hide", "item_ids": ["unknown"]}) == []


def test_clean_edit_is_never_silent():
    """FIX-4: an edit that breaks nothing still gets an info card that says which rules were checked."""
    cards = advisor.advise(DOC, {"op": "narrow", "item_ids": [DOOR], "detail": {"width_mm": 1100}})
    assert len(cards) == 1 and cards[0]["severity"] == "info" and cards[0]["kind"] == "info"
    assert "Checked against:" in cards[0]["body"] and cards[0]["checked"]
    _valid(cards[0])


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


# ---- FIX-4 -------------------------------------------------------------------------------------------------

def test_removing_the_erdgeschoss_outer_door_is_a_violation_of_848_33():
    from engine import scene_cmds
    from engine.solvers import ARTIFACTS
    from engine.solvers.data import load_doc
    d = load_doc(DOC, ARTIFACTS)
    q = "remove the Erdgeschoss outer door"
    ids = scene_cmds.scene_answer(q, d, scene_cmds.parse_scene(q))["evidence"]["scene"]["commands"][0]["item_ids"]
    assert 0 < len(ids) < 10                       # the outer door(s) of that storey, not all 77 doors
    cards = advisor.advise(DOC, {"op": "hide", "item_ids": ids})
    v = [c for c in cards if c["severity"] == "violation"]
    assert v and v[0]["source"]["ref"] == "fi-fire-exits-per-storey" and "33 §" in v[0]["source"]["title"]
    assert "848/2017 §33" in v[0]["body"] and "Erdgeschoss" in v[0]["title"] and v[0]["checked"]
    for c in cards:
        _valid(c)


def test_front_door_selects_one_door():
    from engine import scene_cmds
    from engine.solvers import ARTIFACTS
    from engine.solvers.data import load_doc
    d = load_doc(DOC, ARTIFACTS)
    a = scene_cmds.scene_answer("remove the front door", d, scene_cmds.parse_scene("remove the front door"))
    assert len(a["evidence"]["scene"]["commands"][0]["item_ids"]) == 1


RASTER = "cubicasa5k__colorful-11397"


@pytest.mark.skipif(not (ROOT / RASTER).exists(), reason="artifact missing")
def test_raster_entrance_door_removed_is_a_violation_and_says_it_is_detected():
    cards = advisor.advise(RASTER, {"op": "hide", "item_ids": ["door-011"]})
    assert len(cards) == 1 and cards[0]["severity"] == "violation" and cards[0]["source"]["ref"] == "fi-fire-exits-per-storey"
    assert "detected" in cards[0]["body"].lower() and cards[0]["checked"] == ["fi-fire-exits-per-storey"]


@pytest.mark.skipif(not (ROOT / RASTER).exists(), reason="artifact missing")
def test_raster_other_door_gets_info_card_not_silence():
    cards = advisor.advise(RASTER, {"op": "hide", "item_ids": ["door-004"]})
    assert len(cards) == 1 and cards[0]["severity"] == "info" and "IFC" in cards[0]["title"] and cards[0]["checked"] == []


def test_front_door_phrase_on_raster_selects_the_detected_entrance():
    if not (ROOT / RASTER).exists():
        pytest.skip("artifact missing")
    from engine import scene_cmds
    from engine.solvers import ARTIFACTS
    from engine.solvers.data import load_doc
    d = load_doc(RASTER, ARTIFACTS)
    a = scene_cmds.scene_answer("remove the front door", d, scene_cmds.parse_scene("remove the front door"))
    assert a["evidence"]["scene"]["commands"][0]["item_ids"] == ["door-011"]


# 1007/2017 checks on small synthetic models

def _doc(items, storeys=None):
    from engine.solvers.data import Doc
    return Doc("t", "ifc", items, storeys=storeys or [{"name": "EG", "elevation_m": 0.0}])


def _item(iid, kind, **kw):
    from engine.solvers.data import Item
    return Item(iid, kind, storey="EG", **kw)


def _checks(doc):
    from engine import findings
    return {f["rule_id"]: f for f in findings.run_doc(doc)}


def test_1007_stair_width_fails_under_850_mm():
    flight = _item("s1", "stairs", props={"ifc_class": "IfcStairFlight"}, bbox_m=[[0, 0, 0], [0.8, 1, 3]])
    f = _checks(_doc([flight]))["fi-use-stair-width"]
    assert f["severity"] == "fail" and f["source"]["ref"] == "fi-use-stair-width"
    wide = _item("s2", "stairs", props={"ifc_class": "IfcStairFlight"}, bbox_m=[[0, 0, 0], [1.2, 1, 3]])
    assert "fi-use-stair-width" not in _checks(_doc([wide]))


def test_1007_riser_tread_exit_vs_dwelling_values():
    from engine import findings
    rules = {r["check_id"]: r for r in findings.load_rules()}
    st = _item("s1", "stairs", q={"riser_height_m": 0.19, "tread_length_m": 0.26}, bbox_m=[[0, 0, 0], [1.2, 1, 3]])
    doc = _doc([st])
    assert findings.check_stair_riser_tread(doc, rules["stair_riser_tread_dwelling"], {}) == []       # 190/260 passes inside a dwelling
    ex = findings.check_stair_riser_tread(doc, rules["stair_riser_tread_exit"], {})                  # but not 180 mm in an exit
    assert ex and ex[0]["severity"] == "suggestion" and ex[0]["source"]["ref"] == "fi-use-stair-exit-riser-tread"
    st2 = _item("s2", "stairs", q={"riser_height_m": 0.2, "tread_length_m": 0.25}, bbox_m=[[0, 0, 0], [1.2, 1, 3]])
    assert findings.check_stair_riser_tread(_doc([st2]), rules["stair_riser_tread_dwelling"], {})[0]["severity"] == "fail"


def test_1007_barrier_headroom_and_emergency_window():
    low = _item("r1", "railing", props={"predefined_type": "GUARDRAIL"}, bbox_m=[[0, 0, 0], [1, 0.9, 0.05]])
    hand = _item("r2", "railing", props={"predefined_type": "HANDRAIL"}, bbox_m=[[0, 0, 0], [1, 0.9, 0.05]])
    door = _item("d1", "door", q={"width_m": 0.9, "height_m": 1.9})
    win = _item("w1", "window", name="Notausstieg-1", q={"width_m": 0.4, "height_m": 0.5})
    ok = _item("w2", "window", name="Fenster", q={"width_m": 0.2, "height_m": 0.2})
    got = _checks(_doc([low, hand, door, win, ok]))
    assert got["fi-use-barrier-height"]["item_ids"] == ["r1"]          # the handrail is not a barrier
    assert got["fi-use-headroom"]["item_ids"] == ["d1"]
    assert got["fi-use-emergency-window"]["item_ids"] == ["w1"]        # only the marked emergency window is checked


def test_coverage_names_checked_and_unchecked_rules():
    from engine import findings
    c = findings.coverage(_doc([_item("d1", "door", q={"width_m": 0.9, "height_m": 2.1})]))
    assert "fi-acc-door-clear-width" in c["checked"] and "fi-use-headroom" in c["checked"]
    reasons = {x["rule_id"]: x["reason"] for x in c["not_checked"]}
    assert "landing" in reasons["fi-use-door-landing"] and "fi-use-stair-width" in reasons


def test_1007_rules_are_unofficial_translation_and_note_building_act():
    r = {x["id"]: x for x in load_rules()}["fi-use-stair-width"]
    assert r["translation"].startswith("unofficial") and r["finnish_quote"] and r["url"].startswith("https://ym.fi/")
    from engine.rules import RULES_DIR
    assert "752/2023" in (RULES_DIR / "safety_in_use.yaml").read_text(encoding="utf-8")
    assert "752/2023" in (RULES_DIR / "fire_escape.yaml").read_text(encoding="utf-8")


def test_plain_remove_from_chat_runs_the_rule_checks(monkeypatch):
    """FIX-4: 'remove the front door' (no compliance wording) still names the checked rules or the violation; never a silent pass."""
    monkeypatch.setenv("MODELS_FAKE", "1")
    from engine.answer import answer
    from engine.solvers import ARTIFACTS
    for doc, want in [("ifc_bench__ac20-arc", "Fewer than two exits"), ("cubicasa5k__colorful-11397", "No entrance door left")]:
        if not (Path(ARTIFACTS) / doc).exists():
            continue
        a = answer("remove the front door", [doc])
        assert not a["answer"]["abstained"] and a["advisor_cards"], doc
        assert want in a["answer"]["text_md"] and "33" in a["answer"]["text_md"], a["answer"]["text_md"]


@pytest.mark.parametrize("q", [
    "Remove the front door. Is it still compliant?",
    "What if we remove the main entrance?",
    "What happens if I remove the front door?",
    "Delete the entrance door. Does it still meet the fire code?",
    "Take out the front door. Are the exits still OK?",
])
def test_demo_phrasings_hide_the_front_door_and_give_the_exit_violation(q, monkeypatch):
    """E-46: full-stop, what-if and 'main entrance' phrasings are the same edit as the comma form, at $0 and without the model."""
    monkeypatch.setenv("MODELS_FAKE", "1")
    from engine.answer import answer
    from engine.solvers import ARTIFACTS
    doc = "ifc_bench__ac20-arc"
    if not (Path(ARTIFACTS) / doc).exists():
        pytest.skip("real artifacts not present")
    a = answer(q, [doc])
    cmds = a["evidence"]["scene"]["commands"]
    assert any(c.get("op") == "hide" and "D34" in (c.get("labels") or {}).values() for c in cmds), cmds
    assert "Fewer than two exits" in a["answer"]["text_md"] and "33" in a["answer"]["text_md"]
    assert a["cost"]["usd_total"] == 0


def test_hide_compliance_answer_has_numbered_boxes_and_full_rule_ref():
    from engine.answer import answer
    r = answer("Remove the front door. Is it still compliant?", ["ifc_bench__ac20-arc"])
    t = r["answer"]["text_md"]
    assert "848/2017 §33" in t and "(33 §)" not in t
    ids = {b["item_id"] for b in r["evidence"]["boxes"]}
    assert "18PQUIFELEARLM4c0brquf" in ids and len(ids) >= 2          # hidden door + remaining exit
    assert r["citations"] and f"[{r['citations'][0]['n']}]" in t
    assert r["evidence"]["scene"]["commands"][0]["op"] == "hide"
