"""E-59: multi-condition questions apply every condition or name what is left; questions never edit the scene."""
import json
from pathlib import Path

import pytest

import engine.complex_q as C
from engine.scene_cmds import parse_scene
from engine.solvers import ARTIFACTS

AC20 = "ifc_bench__ac20-arc"
pytestmark = pytest.mark.skipif(not (Path(ARTIFACTS) / AC20).exists(), reason="AC20 artifacts not built")


def ask(q, doc=AC20):
    return C.answer(q, [doc], Path(ARTIFACTS))


@pytest.mark.parametrize("q", ["Can we remove the internal wall beside Seminarraum in Keller and widen the opening?", "Prepare a schedule of all doors by storey",
                               "Which doors on 1. Obergeschoss are wider than 1.5 m, can we hide them?", "Produce a door schedule by storey"])
def test_questions_are_not_scene_commands(q):
    assert parse_scene(q) is None


@pytest.mark.parametrize("q", ["remove the front door", "Hide the windows", "can you remove W3"])
def test_commands_still_parse(q):
    assert parse_scene(q) is not None


def test_tiling_applies_every_number():
    r = ask("How much floor tiling should I order for all WC Herren and WC Damen rooms from Keller through 2. Obergeschoss, allowing 10% waste, if each box covers 1.44 m² and costs €32 excluding VAT?")
    t = r["answer"]["text_md"]
    assert "Scope I applied" in t and "76 boxes" in t and "EUR 2,432" in t and r["answer"]["confidence"] > 0.9
    assert {"waste 10%", "box coverage 1.44 m²"} <= set(r["conditions"]["applied"])


def test_office_filter_uses_net_area_and_name_exclusions():
    r = ask("On 1. Obergeschoss, list offices with net floor areas from 12 to 25 m² inclusive, excluding the secretary's office and all rooms assigned to Mueller or Obermueller. Sort by area, then room number.")
    t = r["answer"]["text_md"]
    assert "Oberschmitt" in t and "Mueller" not in t.split("Just outside")[0].split("Name")[-1] and r["answer"]["confidence"] <= 0.6


def test_door_filter_finds_the_two_wide_doors():
    r = ask("On 1. Obergeschoss, which internal doors are at least 1.5 m wide and 2.1 m high and connect a Flur room to an office rather than a WC? List each door.")
    assert "Tür-017" in r["answer"]["text_md"] and "Tür-018" in r["answer"]["text_md"]


def test_unanswerable_says_not_in_document():
    r = ask("What are the installed U-values and g-values of the external windows, and how much annual heating energy would replacing them save?")
    assert "not in the document" in r["answer"]["text_md"] and r["answer"]["confidence"] <= 0.6


def test_wall_removal_is_structure_honest():
    r = ask("Can we remove the internal wall beside Seminarraum in Keller and widen the opening without temporary propping?")
    assert "structural engineer" in r["answer"]["text_md"]
    assert not r["evidence"]["scene"].get("commands")


def test_ordinary_questions_fall_through():
    assert ask("How many doors are there?") is None
    assert ask("What is the area of Seminarraum?") is None


def test_every_complex_q_answer_passes_the_api_schema():
    # the server validates each answer against the contract; route must be one of index/planmap/vlm/hybrid
    import importlib, json
    from pathlib import Path
    from engine.answer import answer
    sch = importlib.import_module("server.schema")
    for q, d in [("How much floor tiling should I order for all WC Herren and WC Damen rooms, allowing 10% waste, if each box covers 1.44 m² and costs €32?", "ifc_bench__ac20-arc"),
                 ("Can we remove the front door?", "ifc_bench__ac20-arc")]:
        a = answer(q, [d])
        sch.validate_answer(a)


def test_where_are_the_toilets_boxes_carry_kind_toilet():
    from engine.answer import answer
    a = answer("Where are the toilets?", ["ifc_bench__ac20-arc"])
    kinds = {b.get("kind") for b in a["evidence"]["boxes"]}
    assert kinds == {"toilet"}


@pytest.mark.parametrize("q,has,hasnt", [
    ("how many people can fit in the seminar room", "Seminarraum", "82 rooms"),
    ("how mny doors are on the first flor", "1. Obergeschoss", "77 doors"),
    ("show me the stairs", "Highlighted 4 stairs on the drawing.", "stairses"),
    ("how thick are the external walls", "300 mm", "total length"),
    ("how tall is the building", "About ", "could not be determined"),
    ("hello", "Hello.", "took longer"),
])
def test_free_form_judge_questions(q, has, hasnt):
    from engine.answer import answer
    t = answer(q, ["ifc_bench__ac20-arc"])["answer"]["text_md"]
    assert has in t and hasnt not in t


@pytest.mark.parametrize("q,must", [
    ("what file is this", "File type"),
    ("what file format is this", "File type"),
    ("what is", "unfinished"),
    ("how many", "unfinished"),
])
def test_file_info_and_incomplete_questions_cost_nothing(monkeypatch, q, must):
    import engine.models
    monkeypatch.setattr(engine.models, "call", lambda *a, **k: pytest.fail("model called"))
    from engine.answer import answer
    a = answer(q, ["ifc_bench__ac20-arc"])
    assert must in a["answer"]["text_md"] and a["cost"]["usd_total"] == 0


def test_file_info_reads_scale_from_plan_map():
    from engine.answer import answer
    assert "m per pixel" in answer("what file is this", ["ifc_bench__ac20-arc"])["answer"]["text_md"]


def test_qa_live_ac20_failures():
    from engine.answer import answer
    D = ["ifc_bench__ac20-arc"]
    t = answer("how many wndows are ther in the basment", D)["answer"]["text_md"]
    assert "44" in t and "Keller" in t
    for q in ("what is the total floor area of each storey?", "total floor area per storey"):
        a = answer(q, D)
        assert a["cost"]["usd_total"] == 0 and "438.1" in a["answer"]["text_md"]
    a = answer("what if we remove the main staircase?", D)
    cmd = a["evidence"]["scene"]["commands"][0]
    assert len(cmd["item_ids"]) == 1 and "stairses" not in a["answer"]["text_md"] and "3 of 4 stairs" in a["answer"]["text_md"]
    t = answer("where is the biggest meeting room?", D)["answer"]["text_md"]
    assert "Besprechungsraum II" in t and "24.8 m²" in t
    assert "No room named" in answer("biggest meeting room on the first floor", D)["answer"]["text_md"]
