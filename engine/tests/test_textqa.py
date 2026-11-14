import json
from collections import Counter
from pathlib import Path

import pytest

from engine import textqa
from engine.answer import answer
from engine.solvers import ARTIFACTS
from engine.solvers.data import load_doc

REAL = Path(ARTIFACTS) / "ifc_bench__ac20-arc"
needs = pytest.mark.skipif(not (REAL / "elements.json").exists(), reason="ac20_arc artifacts not present")


@pytest.fixture(autouse=True)
def _no_model(monkeypatch):
    monkeypatch.setenv("TEXT_WITH_MODEL", "0")
    monkeypatch.setenv("MODELS_FAKE", "1")


def run(q):
    return answer(q, ["ifc_bench__ac20-arc"])


@needs
def test_ten_ifc_bench_questions_match_elements():
    els = json.loads((REAL / "elements.json").read_text())["elements"]
    by = lambda k: [e for e in els if e["kind"] == k]
    cases = {
        "Which door types are installed in this building with quantities?": [str(len(by("door")))] + [f"{n}: {c}" for n, c in Counter(e["type_name"] for e in by("door")).items()],
        "Which window types are present in the building and how many of each?": [str(len(by("window")))],
        "What wall types are present in the building and how many of each?": [str(len(by("wall")))] + [f"{n}: {c}" for n, c in Counter(e["type_name"] for e in by("wall")).items()],
        "Which column types are present here and how many of each?": [str(len(by("column")))],
        "Which stair types are used here with quantities?": [str(len(by("stairs")))],
        "Which railing types are installed in the building?": [str(len(by("railing")))],
        "What are the thicknesses of the various wall types?": ["200 mm", "300 mm"],
        "What are the heights of each level?": ["5 levels", "Keller"],
        "Which room in the building is the largest?": ["128.3 m2", "Keller"],
        "Which two doors have the greatest widths in the building?": ["Tür-019", "Tür-018"],
        "What is the narrowest door width used here?": ["Tür-014"],
        "What is the space breakdown of the attic floor with areas?": ["3 rooms", "202.4 m2"],
    }
    assert len(cases) >= 10
    for q, needles in cases.items():
        a = run(q)
        t = a["answer"]["text_md"]
        assert not a["answer"]["abstained"], q
        for n in needles:
            assert n in t, (q, n, t[:200])
        assert a["evidence"]["scene"]["highlight_item_ids"] or "levels" in q.lower() or "level" in q, q  # levels have no items
        assert a["cost"]["usd_total"] == 0


@needs
def test_missing_data_is_said_plainly():
    for q, frag in [("How many of the walls are load-bearing compared with non-load-bearing?", "does not record"),
                    ("Which beams are used in the building?", "No beam"),
                    ("Which MEP systems are installed in this building?", "No pipe or MEP"),
                    ("Which doors types include fire rating details?", "does not record")]:
        a = run(q)
        assert frag in a["answer"]["text_md"], (q, a["answer"]["text_md"])


def test_model_text_must_use_only_fact_numbers(monkeypatch):
    f = textqa.Facts(["Total doors: 77.", "Type A: 67 (87.0%)", "Type B: 10 (13.0%)"], ["x"], "types")
    class R:  # stand-in for models.call
        def __init__(self, t): self.text, self.provider, self.model, self.cost_usd = t, "p", "m", 0.001
    import engine.models as M
    monkeypatch.setattr(M, "call", lambda *a, **k: R("There are **77 doors**, 67 of type A."))
    ok, _ = textqa._phrase("q", f)
    assert ok
    monkeypatch.setattr(M, "call", lambda *a, **k: R("There are **80 doors**."))
    bad, meta = textqa._phrase("q", f)
    assert bad is None and meta["cost_usd"] == 0.001
