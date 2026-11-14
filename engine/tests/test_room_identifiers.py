"""Generated for demo room labels: number/name intersections and honest misses."""
import time

import pytest

from engine.analytics import filtered_question
from engine.solvers.data import Doc, Item
from engine.solvers.filters import room_filter


def selected(question, rooms):
    result = room_filter(question, rooms)
    assert result is not None
    return [r.item_id for r in result[1]]


@pytest.fixture
def offices():
    return [Item("a", "room", name="214", props={"long_name": "Office"}),
            Item("b", "room", name="215", props={"long_name": "Office"}),
            Item("c", "room", name="2140", props={"long_name": "Office"})]


@pytest.mark.parametrize("target", ["office 214", "214 office", "room 214", "Room 214 Office", "214"])
@pytest.mark.parametrize("template", ["What is the area of {}?", "Where is {}?", "{}"])
def test_number_beats_shared_type(offices, target, template):
    assert selected(template.format(target), offices) == ["a"]


@pytest.mark.parametrize("label,question", [
    ("Room 2.14 Office", "What is the area of office 214?"),
    ("Office", "What is the area of Room 2.14 Office?"),
    ("Büro", "What is the area of office 214?"),
    ("Kontor", "What is the area of Büro 214?"),
    ("Toimisto", "What is the area of kontor 214?"),
    ("Office", "What is the area of Huone 214 Toimisto?"),
    ("Office", "What is the area of Rum 214 Kontor?"),
    ("Office", "What is the area of Raum 214 Büro?"),
])
def test_language_and_field_order(label, question):
    rooms = [Item("a", "room", name="214", props={"long_name": label}),
             Item("b", "room", name="215", props={"long_name": label})]
    assert selected(question, rooms) == ["a"]


def test_number_can_live_in_label_or_props():
    rooms = [Item("a", "room", label="Room 2.14 Office"),
             Item("b", "room", label="Office", props={"number": "215"})]
    assert selected("What is the area of office 214?", rooms) == ["a"]
    assert selected("What is the area of office 215?", rooms) == ["b"]


def test_exact_id_wins_over_compact_spelling():
    rooms = [Item("a", "room", name="2.14", props={"long_name": "Office"}),
             Item("b", "room", name="214", props={"long_name": "Office"}),
             Item("c", "room", name="21.4", props={"long_name": "Office"})]
    assert selected("What is the area of office 214?", rooms) == ["b"]
    assert selected("What is the area of room 2.14?", rooms) == ["a"]
    # No exact 214: never pick one of two equally plausible source ids.
    assert selected("What is the area of office 214?", [rooms[0], rooms[2]]) == ["a", "c"]


@pytest.mark.parametrize("target", ["office 999", "kitchen 214", "office 21", "Office Mueller 214"])
def test_missing_number_or_conflicting_name_never_means_all(offices, target):
    assert selected("What is the area of " + target + "?", offices) == []


def test_scope_number_is_not_a_room_number(offices):
    assert selected("What is the area of offices on floor 214?", offices) == ["a", "b", "c"]
    assert room_filter("What is the area of floor 214?", offices) is None


def test_alphanumeric_ids_and_casefold_offsets():
    room = Item("a", "room", name="A-214", props={"long_name": "Straße Office"})
    assert selected("What is the area of Straße Office a-214?", [room]) == ["a"]


def test_number_only_keeps_ambiguous_rooms_for_caller(offices):
    offices.append(Item("d", "room", name="214", props={"long_name": "Kitchen"}))
    assert selected("What is the area of room 214?", offices) == ["a", "d"]
    assert selected("What is the area of office 214?", offices) == ["a"]


def test_public_analytics_answer_has_only_selected_room_evidence(offices):
    for i, room in enumerate(offices):
        room.q = {"area_m2": 10 + i}
        room.bbox_px = [10 + i * 20, 20, 20 + i * 20, 30]
    doc = Doc("generated-for-demo", "ifc", offices)
    result = filtered_question("What is the area of office 214?", doc, time.perf_counter())
    assert result["answer"]["value"] == 10
    assert result["cost"]["usd_total"] == 0
    assert result["evidence"]["scene"]["highlight_item_ids"] == ["a"]
    assert {iid for c in result["citations"] for iid in c["item_ids"]} == {"a"}
