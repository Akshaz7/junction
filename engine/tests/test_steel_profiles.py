"""Steel profile questions list stored profile names with counts (generated for test)."""
import time

import pytest

from engine import mep
from engine.solvers.data import Doc, Item
from engine.tests.test_fix_qa import store


def beams(tmp_path):
    rows = [dict(id=f"b{i}", c="IfcBeam", k="beam", t="IPE220" if i < 3 else "1/2IPE300", v=None, mt=None, cf=None, st="L1", m=None,
                 sz="IPE220" if i < 3 else "1/2IPE300") for i in range(5)]
    store(tmp_path, "up", "mep.json", dict(version=mep.MEP_VERSION, services=[], structure=rows))
    return Doc("up", "ifc", [Item(r["id"], "beam", storey="L1", name=r["t"], type_name=r["t"]) for r in rows], storeys=[dict(name="L1", elevation_m=0)])


@pytest.mark.parametrize("q", ["Which steel section profiles are used in this IFC, and how many beams use each profile? Cite the profile names from the IFC.",
                               "What steel profiles are used?", "List the profiles with counts"])
def test_profiles_listed_with_counts(tmp_path, monkeypatch, q):
    doc = beams(tmp_path)
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    r = mep.answer(q, doc, time.perf_counter())
    text = r["answer"]["text_md"]
    assert r["answer"]["value"] == 2 and "IPE220: 3" in text and "1/2IPE300: 2" in text
