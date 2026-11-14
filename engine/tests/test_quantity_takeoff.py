"""Quantity take-off: one table answer, code only, 'not in this file' where the file has no data."""
import os
from pathlib import Path

import pytest

from engine import sheetqa
from engine.tests.test_sheetqa import _mk

ART = Path(os.environ.get("ARTIFACTS_DIR", "artifacts"))


def test_sheet_takeoff_table_and_not_in_file(tmp_path):
    ln = [("DINING", 100, 100), ("164 SF", 500, 100), ("KITCHEN", 100, 200), ("254 SF", 500, 200), ("STORAGE ROOM", 100, 300), ("901 SF", 500, 300),
          ("OFFICE ROOM", 100, 400), ("222 SF", 500, 400), ("TOTAL", 100, 500), ("1541 SF", 500, 500)]
    d = _mk(tmp_path, "arch2", ln, "A-201 floor plan")
    r = sheetqa.answer("Give me the quantity take-off", [d], tmp_path)
    t = r["answer"]["text_md"]
    assert "| Floor area - DINING | 15.2" in t and "| m2 | [1] |" in t and t.count("not in this file") >= 5 and "| Item | Quantity | Unit | Source |" in t and r["cost"]["usd_total"] == 0 and len(r["citations"]) == 4


def test_non_takeoff_question_is_untouched(tmp_path):
    from engine.quantity_takeoff import TAKEOFF_Q
    assert not TAKEOFF_Q.search("what is the take-off for the kitchen floor with 10% waste")
    assert TAKEOFF_Q.search("Give me the full quantity take-off")


@pytest.mark.skipif(not (ART / "ifc_bench__fzk-house-arc" / "elements.json").exists(), reason="local artifact not present")
def test_ifc_takeoff_rooms_slabs_and_missing_piping(monkeypatch):
    monkeypatch.setenv("MODELS_FAKE", "1")
    from engine.solvers.data import load_doc
    from engine.quantity_takeoff import quantity_takeoff
    import time
    doc = load_doc("ifc_bench__fzk-house-arc", str(ART))
    a = quantity_takeoff("quantity take-off", doc, time.perf_counter())
    t = a["answer"]["text_md"]
    assert a["answer"]["value"] == 7 and "| Item | Quantity | Unit | Source |" in t and "| Doors | 5 | count |" in t and "| Windows | 11 | count |" in t
    assert "Slab area - Solid, 200 mm | 265.0 | m2 |" in t and "| Piping by system | not in this file |  |  |" in t
    import re
    ns = {c["n"] for c in a["citations"]}
    for m in re.finditer(r"\| [\d.]+ \| (?:m2|m|count) \| ((?:\[\d+\])+) \|", t):
        assert all(int(n) in ns for n in re.findall(r"\d+", m.group(1)))
    assert a["cost"]["usd_total"] == 0 and len(a["citations"]) >= 3 and len(a["evidence"]["boxes"]) >= 7


def test_friendly_system_names_and_rollup():
    from engine.analytics import friendly_system, system_rows
    assert friendly_system("S_Schmutzwasser") == "Waste water (S_Schmutzwasser)"
    assert friendly_system("S_PWC") == "Potable cold (S_PWC)"
    assert friendly_system("S_PWH_11") == "Potable hot (S_PWH_11)"
    assert friendly_system("S_Regenwasser") == "Rainwater (S_Regenwasser)"
    assert friendly_system("Unit A Domestic Cold Water") == "Potable cold (Unit A Domestic Cold Water)"
    assert friendly_system("M531 126") == "M531 126"
    assert friendly_system("unknown") == "Unnamed system"
    rows, rest = system_rows([(str(i), 1, 1.0) for i in range(11)])
    assert len(rows) == 8 and rest == 3


def test_piping_systems_answer_is_friendly_and_capped():
    from engine.answer import answer
    a = answer("List the piping systems by length", ["ifc_bench__digital-hub-plumbing"])
    t = a["answer"]["text_md"]
    assert "Waste water (S_Schmutzwasser)" in t and "smaller system" in t
