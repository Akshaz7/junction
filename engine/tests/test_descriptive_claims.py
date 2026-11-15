from pathlib import Path

from engine import descriptive_claims as d

W = {"w1-0": {"doc_id": "x", "page": 1, "item_id": "w1-0", "bbox": [0, 0, 1, 1], "crop": None, "text": "KPH"}}
I = {"door-001": {"doc_id": "x", "page": 1, "item_id": "door-001", "bbox": [0, 0, 1, 1], "crop": None, "text": "door"}}


def test_validate_drops_unknown_ids_and_downgrades():
    raw = {"claims": [
        {"text": "KPH is a bathroom", "evidence_ids": ["w1-0", "ghost"], "status": "verified", "check": "OCR KPH"},
        {"text": "Invented", "evidence_ids": ["ghost"], "status": "verified", "check": "x"},
        {"text": "Read only", "evidence_ids": [], "status": "read_only", "check": ""},
        {"text": "bad status", "evidence_ids": ["door-001"], "status": "great", "check": "c"}]}
    out = d.validate(raw, W, I, {}, {"door-001": 2})
    assert out[0]["ids"] == ["w1-0"] and out[0]["status"] == "verified"
    assert out[1]["status"] == "inferred" and out[1]["ids"] == []
    assert out[2]["status"] == "read_only" and out[2]["check"]
    assert out[3]["status"] == "inferred" and out[3]["cite"] == 2


def test_descriptive_detection():
    ok = {"answer": {"text_md": "A plan.", "value": None}}
    assert d.is_descriptive("What is this file?", ok)
    assert d.is_descriptive("describe the drawing", ok)
    assert not d.is_descriptive("how many doors?", ok)
    assert not d.is_descriptive("what is this file", {"answer": {"text_md": "x", "abstained": True}})
    assert not d.is_descriptive("describe", {"answer": {"text_md": "12", "value": 12, "unit": "m2"}})


def test_attach_fake_schema(monkeypatch):
    monkeypatch.setenv("MODELS_FAKE", "1")
    root = Path(__file__).resolve().parents[2] / "artifacts"
    doc = "cubicasa5k__colorful-12200"
    if not (root / doc).is_dir():
        return
    res = {"doc_ids": [doc], "answer": {"text_md": "A studio flat with doors. [1]"}, "citations": [{"n": 1, "item_ids": ["door-001"]}], "trace": []}
    out = d.attach(res, "what is this file?", root)
    calc = out["reasoning"]["calc"]
    assert calc["kind"] == "claims" and calc["method"]["id"] == "read_and_cite"
    assert calc["result"]["claims_total"] == len([s for s in calc["steps"] if s["section"] == "claim"])
    assert out["reasoning"]["confidence"]["factors"][0]["label"] == "Claims verified by source text"
