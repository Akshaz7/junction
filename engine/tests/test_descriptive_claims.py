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
    assert out[1]["status"] == "read_only" and out[1]["ids"] == []
    assert out[2]["status"] == "read_only" and out[2]["check"]
    assert out[3]["status"] == "inferred" and out[3]["cite"] is None


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


def test_matches_all_labels_independent_of_model_ids():
    evidence = {str(i): {**W['w1-0'], 'text': text} for i, text in enumerate(['ET', 'OH', 'KPH', 'ranskalai nen parveke'])}
    raw = {'claims': [
        {'text': text, 'status': 'read_only', 'evidence_ids': ['ghost']}
        for text in ['Entrance "et".', 'Living room OH.', 'Bathroom KPH.', 'French balcony “RANSKALAINEN PARVEKE”.', 'Labels ET and MISSING.']]}
    out = d.validate(raw, evidence, {}, {}, {})
    assert [c['status'] for c in out] == ['verified'] * 4 + ['read_only']
    assert all(c['ids'] for c in out[:4])


def test_interpretation_and_unrelated_evidence_never_verify():
    raw = {'claims': [
        {'text': 'A studio apartment with KPH.', 'status': 'verified', 'evidence_ids': ['w1-0']},
        {'text': 'There is a ballroom.', 'status': 'verified', 'evidence_ids': ['w1-0']},
        {'text': 'ET is printed.', 'status': 'verified', 'evidence_ids': ['w1-0']}]}
    out = d.validate(raw, W, I, {}, {})
    assert [c['status'] for c in out] == ['inferred', 'read_only', 'read_only']


def test_interpretation_word_can_be_a_literal_printed_title():
    evidence = {'title': {**W['w1-0'], 'text': 'Studio apartment'}}
    raw = {'claims': [{'text': 'The title reads "Studio apartment".', 'status': 'inferred', 'evidence_ids': []}]}
    assert d.validate(raw, evidence, {}, {}, {})[0]['status'] == 'verified'


def test_source_collection_keeps_boxes_and_all_text_fields(tmp_path):
    import json
    directory = tmp_path / 'example'
    directory.mkdir()
    files = {
        'rtext-1.json': {'words': [{'text': 'OCR', 'bbox_px': [1, 2, 3, 4]}]},
        'text.json': {'items': [{'text': 'Layer text', 'bbox_px': [5, 6, 7, 8]}]},
        'text-2.json': {'page': 2, 'words': [{'text': 'PDF layer', 'bbox_px': [2, 3, 4, 5]}]},
        'planmap-1.json': {'items': [{'item_id': 'room-1', 'label': 'ET', 'name': 'Étage', 'text': 'OH', 'bbox_px': [10, 20, 30, 40]}],
                           'title_block': {'title': {'value': 'Ground floor', 'bbox_px': [50, 60, 70, 80]}}},
    }
    for name, data in files.items():
        (directory / name).write_text(json.dumps(data))
    evidence = d.sources.collect('example', tmp_path)
    for query in ('OCR', 'Layer text', 'PDF layer', 'ET', 'ETAGE', 'OH', 'Ground floor'):
        ids = d.sources.match(query, evidence)
        assert ids and evidence[ids[0]]['bbox']


def test_split_ocr_needs_spatial_neighbours():
    evidence = {str(i): {**W['w1-0'], 'text': text, 'bbox': box} for i, (text, box) in enumerate([
        ('ranskalai', [0, 0, 60, 12]), ('nen', [62, 0, 80, 12]), ('parveke', [82, 0, 140, 12])])}
    assert len(d.sources.match('ranskalainen parveke', evidence)) == 3
    evidence['1']['bbox'] = [900, 900, 930, 912]
    assert not d.sources.match('ranskalainen parveke', evidence)
    assert not d.sources.match('ET', {'x': {'text': 'kitchenette'}})


def test_recovered_claims_have_clickable_citations(monkeypatch, tmp_path):
    monkeypatch.setenv('MODELS_FAKE', '1')
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    evidence = {'w': {**W['w1-0'], 'text': 'KPH'}}
    monkeypatch.setattr(d, '_inputs', lambda *args: (None, evidence, {}, {}, {}, {'words': ['w: KPH'], 'items': [], 'fields': []}, 1))
    res = {'doc_ids': ['x'], 'answer': {'text_md': 'Bathroom KPH.'}, 'reasoning': {'steps': [{'text': 'Found 9 walls'}]}, 'trace': []}
    d.attach(res, 'what is this file?', tmp_path)
    step = res['reasoning']['calc']['steps'][0]
    assert step['status'] == 'verified' and step['inputs'][0]['source']['bbox'] == [0, 0, 1, 1]
    assert step['cite'] == res['citations'][0]['n']
    assert res['reasoning']['steps'][0]['text'] == 'Bathroom KPH.'
