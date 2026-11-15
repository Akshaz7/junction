"""F-PROJCOUNT: an IFC plus a drawing of the same building is counted once (the IFC), the drawing is a cross-check,
and a 'same number?' question answers both sides with citations from both documents."""
import json
import shutil
from pathlib import Path

import pytest

F = "ifc_models__kit-fzk-haus-ac20-fzk-haus"
P = "uploads__fzk-haus-ground-floor-plan-test"
SRC = Path(__file__).resolve().parents[2] / "artifacts" / F


@pytest.fixture
def art(tmp_path, monkeypatch):
    if not (SRC / "elements.json").exists():
        pytest.skip("FZK artifacts not available")
    monkeypatch.setenv("MODELS_FAKE", "1")
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    shutil.copytree(SRC, tmp_path / F)
    shutil.copytree(SRC, tmp_path / P)
    d = json.loads((tmp_path / P / "doc.json").read_text())
    d.update(doc_id=P, title="FZK-Haus-ground-floor-plan", kind="pdf", formats=["pdf", "ifc"])
    (tmp_path / P / "doc.json").write_text(json.dumps(d))
    e = json.loads((tmp_path / P / "elements.json").read_text())
    doors = [i for i in e["elements"] if i.get("kind") == "door"]
    drop = {i["item_id"] for i in doors[3:]}
    e["elements"] = [i for i in e["elements"] if i["item_id"] not in drop]
    (tmp_path / P / "elements.json").write_text(json.dumps(e))

    for pm in (tmp_path / P).glob("planmap-*.json"):   # the plan map agrees with the trimmed IFC
        m = json.loads(pm.read_text())
        m["items"] = [i for i in m.get("items", []) if i.get("item_id") not in drop]
        pm.write_text(json.dumps(m))
    return tmp_path


def test_pdf_read_into_ifc_is_a_drawing_not_a_second_building(art):
    from engine.projects.roles import classify
    c = classify({"doc_id": P}, art)
    assert c["role"] == "plan" and c["level"] == "Ground floor"
    assert classify({"doc_id": F}, art)["role"] == "model"


def test_count_is_not_summed_and_shows_cross_check(art):
    from engine.answer import answer
    r = answer("How many doors are there?", [F, P])
    a = r["answer"]
    assert a["value"] == 5 and "8" not in a["text_md"].split("**")[1]
    assert "shows 3" in a["text_md"] and "cross-check" in a["text_md"]


def test_same_number_question_answers_both_sides_with_citations(art):
    from engine.answer import answer
    r = answer("Does the ground floor plan drawing show the same number of doors as the ground floor of the 3D model?", [F, P])
    t = r["answer"]["text_md"]
    assert "counts differ" in t and "has 5 doors" in t and "has 3 doors" in t
    assert {c["doc_id"] for c in r["citations"]} == {F, P}
    assert r["cost"]["usd_total"] == 0


def test_different_buildings_are_still_added(art):
    from engine.answer import answer
    V = "ifc_models__kit-institute-ac20-institute-var-2"
    if not (SRC.parent / V / "elements.json").exists():
        pytest.skip("institute artifacts not available")
    shutil.copytree(SRC.parent / V, art / V)
    r = answer("How many doors in total across both models?", [F, V])
    assert "selected documents" in r["answer"]["text_md"]


def test_app_feature_ignores_comparison_question():
    from engine.library import app_feature
    assert app_feature("Does the plan show the same number of doors as the 3D model?") is None
    assert app_feature("Show it in 3D") == "3d"


def test_compare_wording_for_unrelated_names_and_crosscheck_level(art):
    from engine.answer import answer
    t = answer("Does the ground floor plan drawing show the same number of doors as the ground floor of the 3D model?", [F, P])["answer"]["text_md"]
    assert "Only in the model" not in t and "Only in FZK-Haus (Simple Phantasy Building): Haustuer, Terrassentuer" in t
    t = answer("How many doors are there?", [F, P])["answer"]["text_md"]
    assert "shows 3 doors on Erdgeschoss" in t


def test_row_label_drops_generic_building_suffix():
    from engine.projects.combine import Combined, Group, Row, row_label
    g = Group(key="g1", label="Building")
    c = Combined(infos={}, groups=[g, Group(key="g2", label="Building")], rows=[], multi_group=True)
    assert row_label(c, Row(key="a", name="00 begane grond", group="g1")) == "00 begane grond"
    g.label = "Haus A"
    assert row_label(c, Row(key="a", name="00 EG", group="g1")) == "00 EG (Haus A)"
