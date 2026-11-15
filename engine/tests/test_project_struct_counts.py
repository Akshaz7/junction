"""Project-wide structural counts: beams/columns/members are summed per model, and a readable IFC with none of a kind is a
valid 0, never a missing operand. A missing or failed index stays missing."""
import pytest

from engine.analytics import multi_doc_total
import importlib
from engine.solvers.data import load_doc
from engine.solvers.solve import ARTIFACTS

solve_mod = importlib.import_module('engine.solvers.solve')
STEEL = "ext_ifcr2__viktor-samplestructuralmodel"
ARCH = "ext_ifcr2__schependomlaan-design"
FLOORS = "ext_ifcr2__schep-kanaalplaat"
DOCS = [ARCH, STEEL, FLOORS]


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    monkeypatch.setenv("MODELS_FAKE", "1")
    for d in DOCS:
        if not (ARTIFACTS / d / "elements.json").exists():
            pytest.skip("real IFC artifacts are required")


def test_plain_beam_question_sums_every_model():
    r = multi_doc_total("How many beams are there?", DOCS, ARTIFACTS)
    assert r is not None and not r["answer"]["abstained"]
    per = [solve_mod.solve("How many beams", d, root=ARTIFACTS)["answer"]["value"] for d in DOCS]
    assert r["answer"]["value"] == sum(per) and per[0] > 0 and per[1] > 0


def test_member_counts_work_in_projects():
    r = multi_doc_total("How many structural members are there?", DOCS, ARTIFACTS)
    assert r is not None and isinstance(r["answer"]["value"], int)


def test_zero_in_one_model_is_a_valid_zero(monkeypatch):
    real = solve_mod.solve

    def fake_solve(question, did, **kw):
        res = real(question, did, **kw)
        if did == FLOORS:   # the solver abstains for the model that holds none of the kind
            res["answer"].update(value=None, abstained=True)
        return res
    monkeypatch.setattr(solve_mod, "solve", fake_solve)
    r = multi_doc_total("How many columns across all models", DOCS, ARTIFACTS)
    assert not r["answer"]["abstained"]
    expected = sum(real("How many columns", d, root=ARTIFACTS)["answer"]["value"] or 0 for d in (ARCH, STEEL))
    assert r["answer"]["value"] == expected


def test_failed_index_stays_missing(monkeypatch):
    real = solve_mod.solve

    def fake_solve(question, did, **kw):
        res = real(question, did, **kw)
        if did == FLOORS:
            res["answer"].update(value=None, abstained=True)
        return res
    monkeypatch.setattr(solve_mod, "solve", fake_solve)
    monkeypatch.setattr(solve_mod, "ifc_unreadable", lambda doc, root: "reading the file failed" if doc.doc_id == FLOORS else None)
    r = multi_doc_total("How many columns across all models", DOCS, ARTIFACTS)
    assert r["answer"]["abstained"]
