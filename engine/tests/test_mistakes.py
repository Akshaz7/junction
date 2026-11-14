"""F-MISTAKES tests on real artifacts (skipped when an artifact is absent)."""
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("MODELS_FAKE", "1")
os.environ["MISTAKES_NO_CACHE"] = "1"
from engine import mistakes  # noqa: E402
from engine.answer import answer as chat  # noqa: E402,F401

ROOT = Path(os.environ.get("ARTIFACTS_DIR") or Path(__file__).resolve().parents[2] / "artifacts")


def need(*ids):
    for i in ids:
        if not (ROOT / i / "doc.json").exists():
            pytest.skip(f"artifact {i} missing")


def test_compare():
    assert mistakes.compare([3, 3, 3])["status"] == "matches"
    assert mistakes.compare([3, 4])["status"] == "differs"
    assert mistakes.compare([100.0, 101.5], "area")["status"] == "matches"
    assert mistakes.compare([100.0, 110.0], "area")["status"] == "differs"
    assert mistakes.compare([5, None])["status"] == "matches"


def test_question_detector():
    yes = ["Are there any mistakes in this drawing?", "find the errors in the model", "is anything wrong with this plan", "check for clashes"]
    no = ["how many doors are there?", "what is the total area?", "what is the error margin"]
    assert all(mistakes.is_mistakes_question(q) for q in yes)
    assert not any(mistakes.is_mistakes_question(q) for q in no)


def _valid(ms):
    for m in ms:
        assert m["severity"] in ("high", "medium", "low")
        assert m["title"] and m["text"] and m["check"] and m["doc_ids"]
        assert m["evidence"]["kind"] and isinstance(m["evidence"]["values"], dict)
        assert "Ifc" not in m["text"]
    assert len(ms) <= mistakes.CAP_PER_DOC
    sev = [mistakes.SEV_RANK[m["severity"]] for m in ms]
    assert sev == sorted(sev)


def test_ifc_duplicates_clinic_structural():
    need("ifc_models__bsc-clinic-clinic-structural")
    ms = mistakes.find_doc("ifc_models__bsc-clinic-clinic-structural", ROOT)
    _valid(ms)
    assert any(m["evidence"]["kind"] == "duplicate" for m in ms)


def test_cross_doc_clashes_clinic():
    ids = ["ifc_models__bsc-clinic-clinic-plumbing", "ifc_models__bsc-clinic-clinic-structural"]
    need(*ids)
    ms = mistakes.find(ids, ROOT)
    _valid(ms)
    cl = [m for m in ms if m["evidence"]["kind"] == "clash"]
    assert cl and all(len(m["doc_ids"]) == 2 for m in cl)


def test_no_clash_across_unaligned_models():
    a, b = "ifc_bench__ac20-arc", "ifc_models__bsc-clinic-clinic-structural"
    need(a, b)
    ms = mistakes.find([a, b], ROOT)
    assert not [m for m in ms if m["evidence"]["kind"] == "clash" and len(m["doc_ids"]) == 2]


def test_ac20_and_swiss_dxf_precise():
    need("ifc_bench__ac20-arc", "swiss_dwellings__site1000-bldg2082-floor9385")
    for d in ("ifc_bench__ac20-arc", "swiss_dwellings__site1000-bldg2082-floor9385"):
        _valid(mistakes.find_doc(d, ROOT))
    # a DXF whose printed areas equal its drawn areas must produce no area mismatch
    assert not [m for m in mistakes.find_doc("swiss_dwellings__site1000-bldg2082-floor9385", ROOT) if m["evidence"]["kind"] == "area_mismatch"]


def test_scans_do_not_crash():
    for d in ("cubicasa5k__colorful-11192", "cubicasa5k__high-quality-architectural-10035"):
        if (ROOT / d / "doc.json").exists():
            _valid(mistakes.find_doc(d, ROOT))


def test_unknown_doc():
    assert mistakes.find_doc("nope__nope", ROOT) == []
    assert mistakes.find([], ROOT) == []


def test_chat_answer_schema():
    need("ifc_models__bsc-clinic-clinic-structural")
    r = mistakes.answer("Are there any mistakes in this model?", ["ifc_models__bsc-clinic-clinic-structural"], ROOT)
    assert r and r["route"] == "index" and r["answer"]["text_md"].startswith("**")
    assert r["reasoning"]["steps"][0]["title"] == "Checked"
    assert r["citations"] and all(c["kind"] == "element" and c["item_ids"] for c in r["citations"])
    schema = Path(__file__).resolve().parents[2] / "server" / "schemas" / "answer.schema.json"
    if schema.exists():
        jsonschema = pytest.importorskip("jsonschema")
        jsonschema.validate(r, json.loads(schema.read_text()))
    assert mistakes.answer("how many doors?", ["ifc_models__bsc-clinic-clinic-structural"], ROOT) is None
