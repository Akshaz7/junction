"""Full trace invariants against unchanged real IFC, CAD and raster artifacts."""
from pathlib import Path

import pytest

from engine.answer import answer
from engine.calc import number, validate
from engine.tests.calc_cases import CASES


@pytest.mark.parametrize("route,docs,question", CASES, ids=[str(i) + ":" + case[0] for i, case in enumerate(CASES)])
def test_real_calculation(route, docs, question, monkeypatch):
    for key, value in {"MODELS_FAKE": "1", "READER": "0", "RECOUNT": "0", "EXPLAIN": "0", "ANSWER_TIMEOUT_S": "0"}.items():
        monkeypatch.setenv(key, value)
    root = Path(__file__).resolve().parents[2] / "artifacts"
    docs = docs if isinstance(docs, list) else [docs]
    if not all((root / did).is_dir() for did in docs): pytest.skip("Real artifact not installed")
    res = answer(question, docs)
    c = res.get("reasoning", {}).get("calc")
    v = res["answer"]["value"]
    if v is None and not c:
        # These two questions currently return missing/ambiguous evidence, not a number.
        assert route in ("ifc/filtered-area", "ifc/unit-price")
        return
    assert c, (route, res["answer"])
    assert c["status"] == "complete", c["issues"]
    assert validate(c, root) == []
    assert c["result"]["value"] == v
    if number(v): assert any(s["id"] == "result" for s in c["steps"])
    assert all(i.get("source") for s in c["steps"] for i in s["inputs"])
