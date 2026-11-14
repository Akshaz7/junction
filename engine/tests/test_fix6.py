"""FIX-6 (Awais, issue #1): storey counts, zero-count honesty, library questions, app-feature requests, typo tolerance. All $0, no model."""
import pytest

from engine.answer import answer
from engine.library import fix_typos, app_feature, wants_library
from server.schema import validate_answer

@pytest.fixture(autouse=True)
def _fake(monkeypatch):
    monkeypatch.setenv("MODELS_FAKE", "1")


AC = "ifc_bench__ac20-arc"
C1 = "cubicasa5k__colorful-11397"
AC20 = "ifc_bench__ac20-arc"


@pytest.mark.parametrize("q", ["how many floors are there", "How many storeys does the building have?", "number of levels"])
def test_ifc_storey_count(q):
    a = answer(q, [AC])
    validate_answer(a)
    assert a["answer"]["value"] == 5 and a["answer"]["unit"] == "count"
    t = a["answer"]["text_md"]
    for name in ("Keller", "Erdgeschoss", "Dachgeschoss", "-3.0 m", "+9.0 m"):
        assert name in t
    assert a["citations"] and "[1]" in t and a["cost"]["usd_total"] == 0


def test_zero_count_is_not_certain():
    a = answer("how many stairs are there", [C1])
    validate_answer(a)
    if a["answer"]["value"] == 0 and not a["answer"]["abstained"]:
        assert a["answer"]["confidence"] <= 0.5
        assert "searched" in a["answer"]["text_md"]


@pytest.mark.parametrize("q", ["how many designs are in the database", "what is stored", "which documents are processed"])
def test_library_questions(q):
    a = answer(q, [])
    validate_answer(a)
    assert not a["answer"]["abstained"] and a["cost"]["usd_total"] == 0
    assert "documents" in a["answer"]["text_md"] and "By source" in a["answer"]["text_md"]
    assert a["answer"]["value"] > 100


def test_library_does_not_catch_element_questions():
    assert not wants_library("how many windows are in the database room")
    assert not wants_library("how many doors are there")


@pytest.mark.parametrize("q,which", [("render this 2D blueprint into 3D", "3d"), ("show it in 3D", "3d"), ("show on table", "ar"), ("show this in AR", "ar")])
def test_app_feature(q, which):
    a = answer(q, [C1])
    validate_answer(a)
    assert a["evidence"]["scene"]["open"] == which and not a["answer"]["abstained"]
    assert ("Visualise it" in a["answer"]["text_md"]) if which == "3d" else ("Show on table" in a["answer"]["text_md"])


def test_app_feature_leaves_measurements_alone():
    for q in ("how many windows", "show only the doors", "what is the area in 3D"):
        assert app_feature(q) is None


@pytest.mark.parametrize("bad,good", [("windos", "windows"), ("dors", "doors"), ("deisng", "design"), ("databse", "database")])
def test_typos(bad, good):
    assert good in fix_typos(f"how many {bad}")[0]


def test_typos_leave_real_words():
    for q in ("what is stored", "how many storeys", "how many bathrooms", "show the floors"):
        assert fix_typos(q)[0] == q


def test_typo_question_answers():
    a = answer("How many windos are there?", [C1])
    validate_answer(a)
    assert a["answer"]["value"] == 11 and a["question"] == "How many windos are there?"


def test_showers_and_bathtubs_in_total_is_one_sum():
    from engine.router.parser import parse
    p = parse("How many showers and bathtubs are drawn on this floor plan in total?")
    assert p.kinds == ["shower"]
    assert len(parse("How many showers and bathtubs are there?").kinds) == 2   # without a total cue FIX-1's per-kind pair stays


def test_named_room_zero_is_not_certain():
    a = answer("How many separate WC rooms are on this floor plan?", [C1])
    validate_answer(a)
    if a["answer"]["value"] == 0:
        assert a["answer"]["confidence"] <= 0.5 and "not proof" in a["answer"]["text_md"]


def test_where_are_the_toilets_on_a_plan_map_points_not_counts():
    a = answer("where are the toilets", [C1])
    validate_answer(a)
    t = a["answer"]["text_md"]
    assert a["route"] == "planmap" and a["evidence"]["boxes"] and "[1]" in t
    assert "bottom" in t or "top" in t or "middle" in t and "Total area" not in t


# ---- E-50 harder cases
def test_wet_room_area_sums_bathrooms_by_storey():
    a = answer("what is the total wet-room area", [AC20])
    validate_answer(a)
    t = a["answer"]["text_md"]
    assert a["answer"]["unit"] == "m2" and a["answer"]["value"] > 0 and "wet rooms" in t and a["evidence"]["boxes"]


def test_how_many_stairs_and_where_gives_per_storey_split():
    a = answer("how many stairs are there and where are they", [AC20])
    validate_answer(a)
    t = a["answer"]["text_md"]
    assert a["answer"]["value"] == 4 and "on Keller" in t and len(a["evidence"]["boxes"]) == 4


def test_list_every_room_with_area_on_a_plan_map():
    a = answer("list every room with its area", [C1])
    validate_answer(a)
    assert a["route"] == "planmap" and a["answer"]["text_md"].count("m²") >= 3 and a["evidence"]["boxes"]


def test_typo_how_mny_dors():
    a = answer("how mny dors", [C1])
    validate_answer(a)
    assert a["answer"]["value"] == 11


def test_toilet_slang_and_show_all_wcs_locate_the_rooms():
    for q in ["where's the loo", "show me all the WCs", "locate the restrooms in this building", "which rooms are toilets and where"]:
        a = answer(q, [AC20])
        validate_answer(a)
        assert a["answer"]["value"] == 8 and len(a["evidence"]["boxes"]) == 8 and not a["answer"]["abstained"], q


# ---- E-52 baseboard
def test_baseboard_ifc_total_and_per_room_arithmetic():
    a = answer("how many linear metres of baseboard in total", [AC20])
    validate_answer(a)
    assert a["answer"]["unit"] == "m" and a["answer"]["value"] > 500 and a["route"] == "index" and len(a["evidence"]["boxes"]) == 82
    assert "minus 1 door" in a["answer"]["text_md"]
    one = answer("how many linear metres of baseboard in the classrooms", [AC20])
    validate_answer(one)
    t = one["answer"]["text_md"]
    assert "Seminarraum" in t and one["answer"]["value"] == 44.2 and "1 classroom" in t   # outline 46.0 m minus a 1.8 m door


def test_baseboard_scaled_raster_uses_the_drawn_scale():
    a = answer("how many linear metres of baseboard per room", ["cubicasa5k__colorful-10711"])
    validate_answer(a)
    assert a["route"] == "planmap" and not a["answer"]["abstained"] and a["answer"]["value"] > 20 and "dimension" in a["answer"]["text_md"] and a["evidence"]["boxes"]


def test_baseboard_never_invents_a_scale():
    a = answer("how many linear metres of skirting in total", ["cubicasa5k__colorful-10052"])
    validate_answer(a)
    assert a["answer"]["value"] is None and "invented" in a["answer"]["text_md"] and not a["evidence"]["boxes"]


# ---- E-56 piping
DH = "ifc_bench__digital-hub-plumbing"
S65 = "ifc_bench__sixty5-plumbing"


def test_piping_total_is_true_metres_and_glows_in_3d():
    a = answer("how many metres of pipe", [DH])
    validate_answer(a)
    assert a["answer"]["unit"] == "m" and abs(a["answer"]["value"] - 301.11) < 0.01 and "Shown in 3D" in a["answer"]["text_md"]
    assert len(a["evidence"]["scene"]["highlight_item_ids"]) == 504 and not a["evidence"]["boxes"]
    big = answer("why does the benchmark say 301106 m for the pipe length?", [DH])
    assert "really mm" in big["answer"]["text_md"]


def test_piping_sizes_dn_length_systems_drains():
    assert "DN100" in answer("what pipe sizes are used", [DH])["answer"]["text_md"]
    d = answer("DN100 length", [DH])
    assert abs(d["answer"]["value"] - 81.96) < 0.01 and len(d["evidence"]["scene"]["highlight_item_ids"]) == 108
    assert "S_Schmutzwasser" in answer("pipes by system", [DH])["answer"]["text_md"]
    dr = answer("where are the drains", [DH])
    assert dr["answer"]["value"] == 2 and len(dr["evidence"]["scene"]["highlight_item_ids"]) == 2


def test_piping_sixty5_no_waste_terminals_falls_back_honestly_and_missing_size():
    dr = answer("where are the drains", [S65])
    validate_answer(dr)
    assert "No drain fittings are modelled" in dr["answer"]["text_md"] and dr["answer"]["value"] > 1000
    none = answer("DN100 length", [S65])
    assert none["answer"]["value"] == 0 and "Sizes present" in none["answer"]["text_md"]


def test_ground_floor_slightly_below_datum_is_still_ground():
    a = answer("how many metres of pipe on the ground floor", [DH])
    assert "E00_OKRD" in a["answer"]["text_md"]
