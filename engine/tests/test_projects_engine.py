"""F-PROJ-ENGINE: roles, no-double-count combine, overview, multi-document answers (real artifacts, MODELS_FAKE=1)."""
import os
from pathlib import Path

import pytest

os.environ.setdefault("MODELS_FAKE", "1")

from engine.answer import answer  # noqa: E402
from engine.projects import classify, level_from_text, level_ordinal, multidoc, overview  # noqa: E402
from engine.projects.combine import combine, doc_dict, totals  # noqa: E402
from engine.solvers import ARTIFACTS  # noqa: E402

ROOT = Path(ARTIFACTS)
AC, DH, FZK = "ifc_bench__ac20-arc", "ifc_bench__digital-hub-arc", "ifc_bench__fzk-house-arc"
VAR = "ifc_models__kit-institute-ac20-institute-var-2"
PLAN1, PLAN2 = VAR + "-plan-03-1-obergeschoss", VAR + "-plan-04-2-obergeschoss"
ELEV = VAR + "-elevation-east"
CUBI = "cubicasa5k__colorful-12627"
SWISS = "swiss_dwellings__site1060-bldg2175-floor9833"
PHOTO = "europeana__1045-ka-photo-klmfalb-c3-b6ke00002hz"

pytestmark = pytest.mark.skipif(not (ROOT / AC).exists(), reason="real artifacts not available")


def role(d):
    return classify(doc_dict(d, ROOT), ROOT)


@pytest.mark.parametrize("doc,want", [(AC, "model"), (FZK, "model"), (ELEV, "elevation"), (CUBI, "plan"), (SWISS, "plan"), (PHOTO, "photo")])
def test_roles_across_origins(doc, want):
    assert role(doc)["role"] == want


def test_levels_from_text_in_several_languages():
    assert level_ordinal(level_from_text("Grundriss 1. Obergeschoss")) == 1
    assert level_ordinal(level_from_text("Floor plan - Level 2")) == 2
    assert level_ordinal(level_from_text("Keller")) == -1
    assert level_ordinal(level_from_text("Pohjapiirros 1. kerros")) == 0   # Finnish "1. kerros" is the ground floor
    assert level_from_text("Site plan") is None
    assert role(PLAN1)["level"] and role(ELEV)["level"] is None


def test_classify_never_raises_on_missing_or_odd_docs():
    assert classify({"doc_id": "no__such-doc", "title": "", "kind": "", "formats": []}, ROOT)["role"] in ("other", "scan", "plan")
    assert classify({}, ROOT)["role"] == "other"


def test_same_building_in_two_formats_is_not_counted_twice():
    c = combine([AC, VAR, PLAN1, PLAN2, ELEV], ROOT)
    t = totals(c)
    assert (t["storeys"], t["doors"], t["rooms"], t["windows"]) == (5, 77, 82, 206)
    assert not c.multi_group
    for r in c.rows:                       # the model is the source of every number; sheets are cross-checks only
        assert all(r.chosen[k] in (AC, VAR) for k in r.chosen)


def test_different_buildings_are_added():
    t = totals(combine([AC, DH], ROOT))
    assert t["doors"] == 77 + 64 and t["storeys"] == 8


def test_overview_shape_and_agreements():
    project = {"id": "p1", "name": "x", "docs": [{"doc_id": d} for d in (AC, VAR, PLAN1, ELEV, CUBI, PHOTO)]}
    o = overview(project, ROOT)
    assert set(o) == {"project_id", "totals", "levels", "agreements", "mistakes", "coverage"}
    assert {c["doc_id"] for c in o["coverage"]} == {AC, VAR, PLAN1, ELEV, CUBI, PHOTO}
    assert o["totals"]["doors"] is not None
    cov = {c["doc_id"]: c for c in o["coverage"]}
    assert "not counted" in cov[ELEV]["contributes"] and cov[PHOTO]["role"] == "photo"
    for a in o["agreements"]:
        assert a["status"] in ("matches", "differs") and len(a["values"]) >= 2
    assert overview(project, ROOT) is o      # cached


def test_overview_with_nothing_readable_does_not_crash():
    o = overview({"id": "p2", "name": "x", "docs": [{"doc_id": "no__such-doc"}]}, ROOT)
    assert o["totals"]["doors"] is None and o["levels"] == []


def test_X11_still_141_with_both_docs_and_card_text():
    r = answer("How many doors are there in total across both models?", [AC, DH])
    assert r["answer"]["value"] == 141
    assert {c["doc_id"] for c in r["citations"]} == {AC, DH}
    assert any("Added 77 + 64 from 2 drawings" in s["text"] for s in r["reasoning"]["steps"])
    # The viewer only carries the primary model's boxes. A complete source
    # total must state that coverage instead of claiming every item is numbered.
    assert r["reasoning"]["confidence"]["label"] == "Estimate"
    unboxed = 141 - len(r["evidence"]["boxes"])
    assert any(f"{unboxed} are not boxed yet" in s["text"] for s in r["reasoning"]["steps"])


def test_same_building_total_uses_model_and_says_so():
    r = answer("How many doors in total across the set?", [AC, VAR, PLAN1])
    assert r["answer"]["value"] == 77
    assert {c["doc_id"] for c in r["citations"]} == {AC}
    assert any("Used the model" in s["text"] and s["ok"] is True for s in r["reasoning"]["steps"])
    assert "cross-check" in r["answer"]["text_md"]


def test_which_floor_has_the_most_rooms_and_fewest_doors():
    r = answer("Which floor has the most rooms?", [AC, VAR])
    assert r["answer"]["value"] == 22 and "Obergeschoss" in r["answer"]["text_md"]
    assert r["citations"] and r["reasoning"]["steps"]
    r = answer("Which level has the fewest doors?", [AC, VAR])
    assert r["answer"]["value"] == 0 and "Dachgeschoss" in r["answer"]["text_md"]


def test_doors_per_level_across_the_set():
    r = answer("doors per level across the set", [AC, VAR, PLAN1])
    assert r["answer"]["value"] == 77
    assert "| 1. Obergeschoss | 22 |" in r["answer"]["text_md"] and "**Total** | 77" in r["answer"]["text_md"]


def test_compare_two_levels():
    r = answer("compare level 1 and level 2", [AC, VAR])
    assert r["answer"]["value"] == {"rooms": 0, "doors": 1, "windows": 0}
    assert "| Doors | 22 | 21 |" in r["answer"]["text_md"]
    r = answer("compare the 1st floor and 2nd floor doors", [AC, VAR])
    assert "difference of **1**" in r["answer"]["text_md"] and r["answer"]["value"] == 1


def test_total_floor_area_and_level_scoped_total():
    r = answer("What is the total floor area across both models?", [AC, DH])
    assert r["answer"]["value"] == pytest.approx(1939.38 + 2842.13, abs=0.1) and r["answer"]["unit"] == "m2"
    r = answer("How many doors on the ground floor across the set?", [AC, VAR])
    assert r["answer"]["value"] == 18


def test_missing_level_is_said_not_guessed():
    r = answer("compare level 1 and level 9", [AC, VAR])
    assert "cannot find level 9" in r["answer"]["text_md"] and not r["answer"]["abstained"] and r["answer"]["value"] is None


def test_questions_with_other_conditions_fall_through_to_the_normal_path():
    assert multidoc.answer("How many doors in the kitchen across both models?", [AC, DH], ROOT) is None
    assert multidoc.answer("How many doors are there?", [AC], ROOT) is None      # one document: not a multi-document question
    assert multidoc.answer("Who designed this?", [AC, DH], ROOT) is None


def test_mixed_formats_do_not_crash_and_answers_cite_every_source():
    docs = [AC, CUBI, SWISS, PHOTO]
    r = answer("How many rooms in total across all of them?", docs)
    assert isinstance(r["answer"]["value"], (int, float))
    cited = {c["doc_id"] for c in r["citations"]}
    assert AC in cited and cited <= set(docs)
    for c in r["citations"]:
        assert c["item_ids"] and isinstance(c["n"], int)
    assert r["evidence"]["scene"]["doc_id"] in docs
