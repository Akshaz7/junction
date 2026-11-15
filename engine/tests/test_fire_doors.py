from __future__ import annotations

import os

os.environ.setdefault("MODELS_FAKE", "1")

from engine import fire_doors
from engine.fire_doors import classify, wants


def test_classify():
    assert classify("30 minuten brandwerend") == "rated"
    assert classify("30 minuten brandwerend en zelfsluitend") == "rated"
    assert classify("Zelfsluitend") == "self-closing only"
    assert classify("Geen") == "none"
    assert classify("") == "none"
    assert classify("EI30") == "rated"
    assert classify("REI 60") == "rated"


def test_wants():
    assert wants("How many fire-rated doors are there? Give the rating and count per floor.")
    assert wants("List the fire rating of every door")
    assert not wants("Does the escape route comply with fire code?")
    assert not wants("How many doors are there?")
    assert not wants("What if I widen the fire door to 1100 mm?")


def test_not_ifc_returns_none():
    class D:
        mode = "plan"
    assert fire_doors.answer("How many fire-rated doors?", D()) is None


def test_schependomlaan_full_list_zero_cost():
    from engine.solvers.data import load_doc
    from pathlib import Path
    from engine.answer import _root
    root = _root()
    doc = load_doc("ext_ifcr2__schependomlaan-design", root)
    if doc is None:
        import pytest
        pytest.skip("index not available")
    r = fire_doors.answer("How many fire-rated doors are there? Give the rating and count per floor.", doc)
    assert r is not None
    txt = r["answer"]["text_md"]
    assert "12 of 205" in txt
    assert txt.count("| merk") + txt.count("| ") >= 12
    assert "self-closing only" in txt


def test_levels_guard_for_heaters():
    from engine import textqa
    class S:
        pass
    class D:
        mode = "ifc"
        storeys = [{"name": "L1", "elevation_m": 0}, {"name": "L2", "elevation_m": 3}]
        items = []
        doc_id = "x"
    f = textqa.facts_for("How many radiators are there on each floor?", D())
    assert f.topic != "levels" and f.value != 2
