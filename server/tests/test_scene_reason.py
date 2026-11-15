"""A raster upload whose scene.glb is missing and cannot be rebuilt answers with a reason, never a bare 404."""
import json

from fastapi.testclient import TestClient

from server import files_routes
from server.app import app


def _client(tmp_path, monkeypatch, files):
    d = tmp_path / "uploads__old-raster-abc"
    d.mkdir()
    for name, body in files.items():
        (d / name).write_text(body)
    monkeypatch.setattr(files_routes, "_doc_dir", lambda doc_id: d)

    async def noop(doc_id):
        return None
    monkeypatch.setattr(files_routes, "_taught_scene", noop)
    return TestClient(app), d


def test_missing_planmap_explains_instead_of_bare_404(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch, {"scene.json": json.dumps({"items": {}})})
    r = c.get("/api/docs/uploads__old-raster-abc/files/scene.glb")
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail.startswith("3D not available for this file: ") and "plan map" in detail


def test_failed_rebuild_reports_reason(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch, {"scene.json": "{}", "planmap-1.json": "{}"})
    r = c.get("/api/docs/uploads__old-raster-abc/files/scene.glb")
    assert r.status_code == 404
    assert r.json()["detail"].startswith("3D not available for this file: rebuilding the 3D model failed")


def test_non_upload_document_says_no_model(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch, {"scene.json": "{}"})
    r = c.get("/api/docs/ac20_arc/files/scene.glb")
    assert r.status_code == 404 and "3D not available for this file" in r.json()["detail"]
