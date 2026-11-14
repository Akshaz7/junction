from pathlib import Path

import pytest

from engine import exits
from engine.answer import answer
from engine.solvers import ARTIFACTS
from engine.solvers.data import Doc, Item

REAL = Path(ARTIFACTS) / "ifc_bench__ac20-arc"


def box(x0, z0, x1, z1):
    return [[x0, 0, z0], [x1, 2.1, z1]]


def synthetic():
    # one 10 x 10 room (x 0..10, z 0..10); a door on the south wall facing outside, one to an inner room, one named Notausgang
    room = lambda i, b: Item(i, "room", storey="EG", name=i, bbox_m=b)
    items = [room("r1", box(0, 0, 10, 10)), room("r2", box(10, 0, 20, 10)),
             Item("d_out", "door", storey="EG", name="Tür-1", bbox_m=box(4, -0.1, 5, 0.1)),
             Item("d_in", "door", storey="EG", name="Tür-2", bbox_m=box(9.9, 4, 10.1, 5)),
             Item("d_named", "door", storey="EG", name="Notausgang-1", bbox_m=box(9.9, 8, 10.1, 9)),
             Item("st", "stairs", storey="EG", name="Treppe-EG", bbox_m=box(1, 1, 2, 4)),
             Item("r_up", "room", storey="OG", name="r_up", bbox_m=box(0, 0, 10, 10)),
             Item("d_up", "door", storey="OG", name="Tür-3", bbox_m=box(4, -0.1, 5, 0.1))]
    return Doc("syn", "ifc", items, "syn", [{"name": "EG", "elevation_m": 0.0}, {"name": "OG", "elevation_m": 3.0}])


def test_synthetic_outer_named_and_stairs():
    a = exits.exit_answer("Where is the fire exit on the ground floor?", synthetic())
    ids = a["evidence"]["scene"]["highlight_item_ids"]
    assert ids == ["d_named", "d_out", "st"] and a["evidence"]["scene"]["camera_target_item_id"] == "d_named"
    assert "inference from the model data" in a["answer"]["text_md"] and a["cost"]["usd_total"] == 0
    assert a["evidence"]["scene"]["commands"][0]["op"] == "highlight"


def test_level_numbers_and_unknown_level():
    d = synthetic()
    assert "d_up" in exits.exit_answer("where is the exit on level 1", d)["evidence"]["scene"]["highlight_item_ids"]
    assert exits.exit_answer("where is the exit", d)["answer"]["abstained"]   # no level named, two levels


def test_exit_intent_only():
    assert exits.is_exit_question("Where is the fire exit on level 1?")
    assert not exits.is_exit_question("How many exits are there?") and not exits.is_exit_question("How many doors?")


@pytest.mark.skipif(not (REAL / "elements.json").exists(), reason="ac20_arc artifacts not present")
def test_ac20_ground_floor_has_item_and_camera_target():
    a = answer("Where is the fire exit on the ground floor?", ["ifc_bench__ac20-arc"])
    sc = a["evidence"]["scene"]
    assert sc["highlight_item_ids"] and sc["camera_target_item_id"] and not a["answer"]["abstained"]
    assert "Erdgeschoss" in a["answer"]["text_md"] and a["cost"]["usd_total"] == 0
