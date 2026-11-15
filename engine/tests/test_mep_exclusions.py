"""An exclusion clause must filter the subject (generated for test)."""
import time

import pytest

from engine import mep
from engine.solvers.data import Doc, Item
from engine.tests.test_fix_qa import store


def mixed(tmp_path):
    rows = ([dict(id=f"p{i}", k="pipe", st="G", t="Run", d="fire protection", L=2., ls="quantity") for i in range(49)]
            + [dict(id=f"s{i}", k="sprinkler", st="G" if i < 5 else "U", t="Pendent", d="fire protection", L=None, ls="none") for i in range(10)]
            + [dict(id="d0", k="sensor", st="G", t="Smoke detector", d="fire protection", L=None, ls="none")])
    store(tmp_path, "up", "mep.json", dict(version=mep.MEP_VERSION, services=rows, structure=[]))
    return Doc("up", "ifc", [Item(r["id"], "mep_other", storey=r["st"]) for r in rows],
               storeys=[dict(name="G", elevation_m=0), dict(name="U", elevation_m=3)])


@pytest.mark.parametrize("q", [
    "How many sprinkler heads are in this model, total and on each storey? Count sprinkler heads only, not pipe segments or smoke detectors.",
    "How many sprinkler heads are there, excluding pipes and detectors?",
    "Without counting pipes, how many sprinklers are there?"])
def test_exclusion_clause_removes_excluded_subjects(tmp_path, monkeypatch, q):
    doc = mixed(tmp_path)
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    r = mep.answer(q, doc, time.perf_counter())
    assert r["answer"]["value"] == 10, r["answer"]["text_md"]
    assert not any(i.startswith(("p", "d")) for c in r["citations"] for i in c["item_ids"])


def test_pipes_still_counted_when_asked(tmp_path, monkeypatch):
    doc = mixed(tmp_path)
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    assert mep.answer("How many pipes are there?", doc, time.perf_counter())["answer"]["value"] == 49
