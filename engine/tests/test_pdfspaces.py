"""Generated for demo: PDF room metadata, multilingual names and preserved evidence."""
import time

import pytest

from engine.analytics import filtered_question
from engine.solvers.data import Doc, Item
from engine.solvers.filters import room_filter


def room(label, number=None, room_type="room", item_id="target"):
    return Item(item_id, "room", label=label, source="pdf_vector", conf=.85,
                props={"number": number, "room_type": room_type}, q={"area_m2": 12.5},
                bbox_px=[10, 20, 50, 60], polygon_px=[[10, 20], [50, 20], [50, 60], [10, 60]])


def selected(question, rooms):
    result = room_filter(question, rooms)
    assert result is not None
    return [r.item_id for r in result[1]]


@pytest.mark.parametrize("label,typed,target", [
    ("Cuisine", "kitchen", "kitchen"), ("Bain", "bathroom", "bathroom"),
    ("Couloir", "hall", "corridor"), ("Entrée", "hall", "corridor"),
    ("Séjour", "living", "living room"), ("Chambre", "bedroom", "bedroom"),
    ("Réduit", "storage", "storage"), ("Balcon", "balcony", "balcony"),
    ("Buanderie", "laundry", "laundry room"), ("Repas", "dining", "dining room"),
    ("Escalier", "stairs", "stairs"), ("RESTROOM", "wc", "bathroom"),
    ("Käytävä", "room", "corridor"), ("Förråd", "room", "storage"),
    ("Kylpyhuone", "room", "bathroom"), ("Büro", "office", "office"),
])
def test_pdf_types_match_english_request(label, typed, target):
    rooms = [room(label, "2.04", typed), room("Other", "2.05", item_id="other")]
    assert selected(f"What is the area of {target}?", rooms) == ["target"]
    assert selected(f"What is the area of {target} 2.04?", rooms) == ["target"]


@pytest.mark.parametrize("label,target", [
    ("Cuisine", "Küche"), ("KITCHEN", "keittiö"), ("Kök", "Cuisine"),
    ("Chambre", "Schlafzimmer"), ("Bedroom", "sovrum"), ("Office", "Büro"),
    ("Meeting", "Mötesrum"), ("CORRIDOR", "Couloir"), ("Storage", "Réduit"),
])
def test_translated_type_with_untyped_pdf_label(label, target):
    rooms = [room(label, "4.07"), room("Other", "4.08", item_id="other")]
    assert selected(f"What is the area of {target}?", rooms) == ["target"]
    assert selected(f"Where is {target} 4.07?", rooms) == ["target"]
    assert selected(f"Where is {target}?", rooms) == ["target"]


@pytest.mark.parametrize("label", ["WALK-IN CLOSET", "WALK IN CLOSET", "Room in use"])
def test_scope_words_inside_drawn_name(label):
    assert selected(f"What is the area of {label}?", [room(label), room("WALK", item_id="other")]) == ["target"]


def test_numbered_lookup_uses_type_metadata_as_well_as_source_name():
    assert selected("What is the area of corridor 125?", [room("ENTRY", "125", "hall")]) == ["target"]


def test_declared_room_identifier_excludes_numbers_in_other_annotations():
    rooms = [room("WC 18.5", "B303", "wc"), room("WC", None, "wc", "unnumbered")]
    assert selected("What is the area of room B303?", rooms) == ["target"]
    assert selected("What is the area of room 18.5?", rooms) == []
    assert selected("What is the area of WC 18.5?", rooms) == ["target"]


def test_digits_in_drawn_name_and_separate_identifier():
    rooms = [room("AKA1 WC", "B303", "wc"), room("AKA1 WC", "B304", "wc", "other")]
    assert selected("What is the area of AKA1 WC?", rooms) == ["target", "other"]
    assert selected("What is the area of AKA1 WC B303?", rooms) == ["target"]


def test_excluded_types_are_not_positive_room_targets():
    rooms = [room("Bedroom", "1", "bedroom"), room("Balcon", "2", "balcony", "outside")]
    assert room_filter("What is the total net floor area in m² of all numbered indoor rooms "
                       "(excluding balconies, loggias, terraces and other outdoor spaces)?", rooms) is None


def test_ifc_type_name_does_not_override_a_specific_source_room_name():
    rooms = [Item("meeting", "room", name="214", type_name="Office", props={"long_name": "Meeting"}),
             Item("office", "room", name="215", type_name="Office", props={"long_name": "Office"})]
    assert selected("What is the area of offices?", rooms) == ["office"]


def test_merged_source_room_retains_one_identity_and_unknowns_never_widen():
    rooms = [room("Couloir / Réduit", "2.27 / 2.29", "hall")]
    assert selected("What is the area of storage 2.29?", rooms) == ["target"]
    assert selected("What is the area of kitchen 2.29?", rooms) == []
    assert selected("What is the area of room 2.2?", rooms) == []


def test_no_name_is_inferred_for_number_only_space():
    rooms = [room(None, "2.01")]
    assert selected("What is the area of room 2.01?", rooms) == ["target"]
    assert selected("What is the area of bedroom 2.01?", rooms) == []


def test_pdf_named_area_keeps_the_source_evidence():
    target = room("Couloir", "2.06", "hall")
    doc = Doc("generated-for-demo", "planmap", [target, room("Cuisine", "2.07", "kitchen", "other")],
              scale={"m_per_px": .01, "method": "printed", "confidence": .9})
    result = filtered_question("What is the area of corridor 2.06?", doc, time.perf_counter())
    assert result["answer"]["value"] == 12.5
    assert result["cost"]["usd_total"] == 0
    assert result["evidence"]["scene"]["highlight_item_ids"] == ["target"]
    assert result["evidence"]["boxes"][0]["bbox_px"] == target.bbox_px
    assert {iid for cite in result["citations"] for iid in cite["item_ids"]} == {"target"}
