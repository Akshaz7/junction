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
