import json

from engine.solvers.solve import solve


def _doc(tmp_path, elements, ingest=None):
    d = tmp_path / "uploads__bad"
    d.mkdir()
    (d / "doc.json").write_text(json.dumps({"doc_id": "uploads__bad", "kind": "ifc", "title": "bad", "formats": ["ifc"], "pages": 1, "files": {}}))
    (d / "elements.json").write_text(json.dumps({"elements": elements, "storeys": [], "building": {}}))
    if ingest:
        (d / "ingest.json").write_text(json.dumps(ingest))
    return tmp_path


def test_empty_ifc_index_is_unknown_not_zero(tmp_path):
    r = solve("How many doors are there?", "uploads__bad", root=_doc(tmp_path, []))
    assert r["answer"]["abstained"] and r["answer"]["value"] is None
    assert "could not be read" in r["answer"]["text_md"] and "no doors" not in r["answer"]["text_md"].lower()


def test_failed_ingest_is_unknown_even_with_some_elements(tmp_path):
    els = [{"item_id": "a", "ifc_class": "IfcWall", "kind": "wall", "name": "w"}]
    r = solve("How many doors are there?", "uploads__bad", root=_doc(tmp_path, els, {"status": "failed", "reason": "missing STEP reference"}))
    assert r["answer"]["abstained"] and "missing STEP reference" in r["answer"]["text_md"]


def test_coverage_names_checks_and_gaps():
    from engine.findings import coverage
    from engine.solvers.data import Doc
    c = coverage(Doc("x", "ifc", [], "t", [], meta={}))
    assert c["not_checked"] and all(n["reason"] for n in c["not_checked"])
