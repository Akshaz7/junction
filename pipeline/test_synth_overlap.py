"""V-05b: the synthetic-data overlap guard must reject held-out / question docs and pass clean ones."""
import json
from pathlib import Path

import pytest

from pipeline import synth


def test_guard_rejects_overlap():
    with pytest.raises(AssertionError):
        synth.assert_no_overlap({"a", "b"}, {"b", "c"})


def test_guard_passes_clean():
    assert synth.assert_no_overlap({"a"}, {"b"})["overlap"] == 0


def test_forbidden_includes_question_docs():
    f = synth.question_docs()
    assert len(f) >= 5000
    first = json.loads(open(synth.REPO / "data" / "sets" / "questions_en.full.jsonl").readline())["doc_id"]
    assert first in f


def test_eligible_sources_clean():
    f = synth.question_docs()
    ids = {r["doc_id"] for r, _ in synth.eligible()}
    assert ids and not ids & f
    assert not any(b in i for i in ids for b in synth.BAN)


def test_generated_labels_clean():
    rep = synth.REPO / "results" / "synth_report.json"
    if not rep.exists():
        pytest.skip("no synth report")
    docs = set(json.loads(rep.read_text())["sources_used"])
    assert not docs & synth.question_docs()


def test_procedural_has_fixtures():
    import random
    kinds = set()
    for i in range(30):
        kinds |= set(synth.procedural_plan(random.Random(i))["Procedural"])
    assert {"wall", "door", "window", "toilet", "sink"} <= kinds
