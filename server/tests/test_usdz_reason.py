"""AR export failures are explained, never a silently missing button; AR no longer depends on the plan phase."""
import json

import pytest

from server import ifc_ingest, ingest_job


def test_note_ar_records_reason(tmp_path):
    (tmp_path / "scene.json").write_text(json.dumps({"items": {}, "usdz": "scene.usdz"}))
    ifc_ingest.note_ar(tmp_path, False, "the AR export ran out of memory")
    sj = json.loads((tmp_path / "scene.json").read_text())
    assert sj["usdz"] is None and "memory" in sj["usdz_reason"]
    (tmp_path / "scene.json").write_text(json.dumps({"items": {}, "usdz": "scene.usdz", "usdz_reason": "old"}))
    ifc_ingest.note_ar(tmp_path, True, "")
    assert "usdz_reason" not in json.loads((tmp_path / "scene.json").read_text())


def test_note_ar_without_manifest_is_noop(tmp_path):
    ifc_ingest.note_ar(tmp_path, False, "x")
    assert not (tmp_path / "scene.json").exists()


def test_strict_usdz_names_missing_converter(monkeypatch, tmp_path):
    import importlib.util as u
    monkeypatch.setattr(u, "find_spec", lambda name: None)
    ingest_job._usdz("d", tmp_path)  # lenient: silent for PDFs
    with pytest.raises(RuntimeError, match="usd-core"):
        ingest_job._usdz("d", tmp_path, strict=True)


def test_file_route_explains_missing_ar(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from server import files_routes
    from server.app import app
    d = tmp_path / "ifc__x"
    d.mkdir()
    (d / "scene.json").write_text(json.dumps({"items": {}, "usdz": None, "usdz_reason": "the AR export timed out"}))
    monkeypatch.setattr(files_routes, "_doc_dir", lambda doc_id: d)

    async def noop(doc_id):
        return None
    monkeypatch.setattr(files_routes, "_taught_scene", noop)
    r = TestClient(app).get("/api/docs/ifc__x/files/scene.usdz")
    assert r.status_code == 404
    assert r.json()["detail"] == "AR not available for this file: the AR export timed out"
