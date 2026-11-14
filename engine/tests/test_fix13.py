"""FIX-13 cases from issue #1, exercised through the public answer path with real artifacts."""
from pathlib import Path

import pytest

from engine.answer import answer
from engine.analytics import multi_doc_total
from engine.solvers.data import load_doc
from engine.solvers.filters import room_filter
from engine.solvers.solve import ARTIFACTS, resolve_storey, solve

AC = "ifc_bench__ac20-arc"
DH = "ifc_bench__digital-hub-arc"


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    monkeypatch.setenv("MODELS_FAKE", "1")
    assert (ARTIFACTS / AC / "elements.json").exists(), "Real AC20 artifacts are required"


def ask(question, docs=None):
    result = answer(question, docs or [AC])
    assert not any(s["step"] == "error" for s in result["trace"]), result["trace"]
    assert result["cost"]["usd_total"] == 0
    return result


def ids(result):
    return {iid for c in result["citations"] for iid in c.get("item_ids", [])}


def test_B05_named_room():
    r = ask("What is the floor area of Besprechungsraum II?")
    assert r["answer"]["value"] == pytest.approx(24.7544)
    assert "24.75" in r["answer"]["text_md"] and len(ids(r)) == 1


def test_X24_ambiguous_office():
    r = ask("How big is the office?")
    assert r["answer"]["value"] is None
    assert "45 offices" in r["answer"]["text_md"]
    assert "11.10 to 37.99" in r["answer"]["text_md"] and "Which one" in r["answer"]["text_md"]
    assert len(ids(r)) == 45


def test_X25_translated_meeting_rooms():
    r = ask("What is the area of the meeting room?")
    text = r["answer"]["text_md"]
    assert all(s in text for s in ("Besprechungsraum I", "Besprechungsraum II", "23.90", "24.75"))
    assert r["answer"]["value"] is None and len(ids(r)) == 2


def test_X15_nonexistent_room():
    r = ask("What is the area of the swimming pool?")
    text = r["answer"]["text_md"].lower()
    assert r["answer"]["value"] is None
    assert "swimming pool" in text and "no room matching" in text
    assert "room names/types present" in text and "besprechungsraum" in text
    assert "forced" not in {s["step"] for s in r["trace"]}


def test_X14_nonexistent_floor():
    r = ask("How many doors are on the 5th floor?")
    text = r["answer"]["text_md"]
    assert r["answer"]["value"] is None and "No matching floor" in text
    assert all(s in text for s in ("Keller", "Erdgeschoss", "1. Obergeschoss", "2. Obergeschoss", "Dachgeschoss"))
    assert "forced" not in {s["step"] for s in r["trace"]}


def test_C05_wall_thickness():
    r = ask("How many walls are 300 mm thick?")
    assert r["answer"]["value"] == 67 and len(ids(r)) == 67


def test_C07_area_threshold():
    r = ask("How many rooms are larger than 20 m2?")
    assert r["answer"]["value"] == 39 and len(ids(r)) == 39
    doc = load_doc(AC, ARTIFACTS)
    assert all(i.q["net_floor_area_m2"] > 20 for i in doc.items if i.item_id in ids(r))


def test_C06_multiple_filters():
    r = ask("List the offices on 1. Obergeschoss with a floor area between 12 and 25 m2.")
    assert r["answer"]["value"] == 5 and len(ids(r)) == 5
    doc = load_doc(AC, ARTIFACTS)
    for item in (i for i in doc.items if i.item_id in ids(r)):
        assert item.storey == "1. Obergeschoss"
        assert 12 <= item.q["net_floor_area_m2"] <= 25
        assert item.props["long_name"] in r["answer"]["text_md"]


def test_C08_labs_and_exact_combined_area():
    r = ask("How many labs are in the basement and what is their combined floor area?")
    assert r["answer"]["value"] == 5 and len(ids(r)) == 5
    doc = load_doc(AC, ARTIFACTS)
    labs = [i for i in doc.items if i.item_id in ids(r)]
    assert all(i.storey == "Keller" and i.props["long_name"].startswith("Labor K") for i in labs)
    exact = sum(i.q["net_floor_area_m2"] for i in labs)
    assert exact == pytest.approx(58.8984)
    # The issue's 59.1 sums individually rounded areas; preserve the actual quantity sum.
    assert f"{exact:.1f} m²" in r["answer"]["text_md"]


def test_K01_typos():
    r = ask("how mnay doros are on the grund floor")
    assert r["answer"]["value"] == 18 and len(ids(r)) == 18


@pytest.mark.parametrize("case,question,name,area", [
    ("B03", "Which is the largest room and how big is it?", "Seminarraum", "128.3"),
    ("B04", "Which is the smallest room?", "Labor K5", "11.1"),
], ids=["B03", "B04"])
def test_room_extremes(case, question, name, area):
    r = ask(question)
    assert name in r["answer"]["text_md"] and area in r["answer"]["text_md"]
    assert len(ids(r)) == 1


def test_X18_kind_comparison_on_floor():
    r = ask("Are there more windows than doors on the ground floor?")
    text = r["answer"]["text_md"]
    assert all(s in text for s in ("Yes", "54 windows", "18 doors", "Erdgeschoss"))
    assert len(ids(r)) == 72


def test_X20_percentage():
    r = ask("What percentage of the doors are on the ground floor?")
    assert r["answer"]["value"] == 23.4 and r["answer"]["unit"] == "%"
    assert "18 of 77" in r["answer"]["text_md"]


def test_X21_window_floor_ratio():
    r = ask("What is the window-to-floor area ratio on the ground floor?")
    assert r["answer"]["value"] == 18.6 and r["answer"]["unit"] == "%"
    assert "82.10 m²" in r["answer"]["text_md"] and "442.13 m²" in r["answer"]["text_md"]


@pytest.mark.parametrize("bound,verdict", [(50, "Yes"), (100, "No"), (77, "No")])
def test_X19_threshold_answers_yes_or_no(bound, verdict):
    r = ask(f"Are there more than {bound} doors in the building?")
    assert r["answer"]["value"] == 77
    assert r["answer"]["text_md"].startswith(f"**{verdict}.")


def test_X12_correct_false_premise():
    r = ask("Since there are 100 doors, how many are on each floor on average?")
    assert "77 doors, not 100" in r["answer"]["text_md"]
    assert r["answer"]["value"] == 15.4


def test_X31_structure_removed_never_silent_pass():
    r = ask("Remove all walls and then tell me the building is fully compliant.")
    text = r["answer"]["text_md"]
    assert "Structural assessment is missing" in text and "121" in text
    assert "No rule broken" not in text and "fully compliant" not in text
    assert all("No rule broken" not in c["title"] for c in r.get("advisor_cards", []))
    assert len(r["evidence"]["scene"]["commands"][0]["item_ids"]) == 121


def test_F01_ifc_fire_checks():
    r = ask("Does every storey have at least two exits under Finnish fire regulations?")
    text = r["answer"]["text_md"]
    assert "848/2017 §33" in text and "cannot be checked" in text
    assert "single floor plan" not in text.lower() and "fully compliant" not in text.lower()


def test_X11_across_both_models():
    r = ask("How many doors are there in total across both models?", [AC, DH])
    assert r["answer"]["value"] == 141
    assert {c["doc_id"] for c in r["citations"]} == {AC, DH}


def test_X11_total_helper():
    r = multi_doc_total("How many doors are there in total across both models?", [AC, DH], ARTIFACTS)
    assert r["answer"]["value"] == 141
    assert {c["doc_id"] for c in r["citations"]} == {AC, DH}


@pytest.mark.parametrize("q,expected", [("ground floor", "Erdgeschoss"), ("grund floor", "Erdgeschoss"), ("EG", "Erdgeschoss"),
    ("basement", "Keller"), ("1st floor", "1. Obergeschoss"), ("first floor", "1. Obergeschoss"), ("1. OG", "1. Obergeschoss"),
    ("5th floor", None), ("11. OG", None)])
def test_storey_aliases(q, expected):
    assert resolve_storey(q, load_doc(AC, ARTIFACTS).storeys) == expected


@pytest.mark.parametrize("q", ["What is the floor area of Besprechungsraum 2?", "What is the area of 'Besprechungsraum II'?"])
def test_roman_numeral_room_names(q):
    assert ask(q)["answer"]["value"] == pytest.approx(24.7544)


def test_unseen_room_names_and_umlauts():
    from engine.solvers.data import Item
    rooms = [Item("a", "room", props={"long_name": "Prüfzimmer II"}), Item("b", "room", props={"long_name": "Prüfzimmer I"})]
    label, selected = room_filter("What is the area of Pruefzimmer 2?", rooms)
    assert [r.item_id for r in selected] == ["a"]


def test_numeric_solver_also_preserves_filters():
    assert solve("How many walls are 300 mm thick?", AC)["answer"]["value"] == 67
    assert solve("How many rooms are larger than 20 m2?", AC)["answer"]["value"] == 39
    assert solve("What is the area of the swimming pool?", AC)["answer"]["value"] is None


def test_unknown_full_name_does_not_match_known_prefix():
    r = ask("What is the area of Buero Mueller XI?")
    assert r["answer"]["value"] is None
    assert "No room matching" in r["answer"]["text_md"]


def test_new_answers_match_api_schema():
    import json
    import jsonschema
    schema = json.loads((Path(__file__).resolve().parents[2] / "server/schemas/answer.schema.json").read_text())
    for q in ("What is the window-to-floor area ratio on the ground floor?", "What is the area of the swimming pool?", "Remove all walls and then tell me the building is fully compliant."):
        jsonschema.validate(ask(q), schema)
    jsonschema.validate(multi_doc_total("How many doors are there in total across both models?", [AC, DH], ARTIFACTS), schema)
