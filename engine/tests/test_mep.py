"""F-MEP: MEP + structure questions answered by code on real artifacts (skipped when an artifact is absent)."""
import os
import re
import time
from pathlib import Path

import pytest

os.environ.setdefault("MODELS_FAKE", "1")
from engine import analytics  # noqa: E402
from engine.solvers.data import load_doc  # noqa: E402

ART = Path(__file__).resolve().parents[2] / "artifacts"


def ask(doc_id, q):
    if not (ART / doc_id).exists():
        pytest.skip(f"artifact {doc_id} missing")
    doc = load_doc(doc_id, ART)
    if doc is None:
        pytest.skip("doc did not load")
    r = analytics.run(q, doc, time.perf_counter())
    return r


def text(r):
    return r["answer"]["text_md"]


CLINIC = "ifc_models__bsc-clinic-clinic-plumbing"


def test_pipe_length_has_real_sizes_no_fake_dn():
    r = ask(CLINIC, "What is the total length of piping?")
    assert r and "pipes" in text(r)
    assert "DN0" not in text(r) and "DN304" not in text(r)
    assert r["citations"] and r["citations"][0]["item_ids"]


def test_sizes_are_standard_dn_series():
    r = ask(CLINIC, "What sizes of pipe are used?")
    sizes = {int(x) for x in re.findall(r"DN(\d+)", text(r))}
    assert sizes and sizes <= {6, 8, 10, 13, 15, 20, 25, 32, 40, 50, 65, 80, 100, 125, 150, 200, 250, 300}


def test_systems_breakdown_by_code():
    r = ask(CLINIC, "How many MEP components are there by system type?")
    assert r and r["route"] != "reader"
    t = text(r).lower()
    assert "hot water" in t and "waste" in t
    assert "no breakdown" not in t


def test_pipe_types_by_code():
    r = ask(CLINIC, "What types of pipes are used?")
    t = text(r)
    assert "6 types" in t and "Hot Water" in t and "Vent" in t


def test_no_ifc_class_jargon():
    for q in ("How many valves are there?", "How many MEP components are there by system type?"):
        r = ask(CLINIC, q)
        assert "Ifc" not in text(r), text(r)


def test_duplex_sizes_recorded_or_stated():
    r = ask("ifc_models__bsc-duplex-duplex-plumbing-20121113", "What sizes of pipe are used?")
    assert r and "DN" in text(r)


def test_electrical_light_fixtures():
    r = ask("ifc_models__bsc-clinic-clinic-electrical", "How many light fixtures are there?")
    assert r and re.search(r"\d", text(r)) and r["citations"][0]["item_ids"]


def test_duct_length_by_system():
    r = ask("ifc_models__bsc-clinic-clinic-hvac", "What is the total duct length by system?")
    assert r and "m of ducts" in text(r)


def test_model_without_services_says_so():
    r = ask("ifc_bench__ac20-arc", "How many sprinklers are there?")
    assert r and "no sprinklers" in text(r).lower()
    assert r["answer"].get("abstained") in (False, None, True)
