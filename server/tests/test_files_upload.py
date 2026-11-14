"""S-13 upload errors and ingestion lifecycle, without a database or heavy conversion."""
import asyncio
import json
import os
import sys
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import files_routes as routes, ingest_job


@pytest.fixture
def upload_client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    pool = SimpleNamespace(execute=AsyncMock())
    monkeypatch.setattr(routes.db, "get_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(routes.artifact_store, "save_doc", AsyncMock())
    monkeypatch.setattr(routes, "publish", AsyncMock())
    monkeypatch.setattr(routes, "ingestion_available", lambda: False)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes._restore] = lambda: None
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("name", ["plan.exe", "plan.svg", "plan.tiff", "plan"])
def test_unsupported_upload_lists_supported_types(upload_client, name):
    response = upload_client.post("/api/upload", files={"file": (name, b"x")})
    assert response.status_code == 415
    assert "pdf, png, jpg (jpeg), dxf, ifc" in response.json()["detail"]
    routes.db.get_pool.assert_not_awaited()


def test_empty_upload_is_rejected(upload_client):
    response = upload_client.post("/api/upload", files={"file": ("empty.pdf", b"")})
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()
    routes.db.get_pool.assert_not_awaited()


def test_upload_size_boundary_and_clear_413(upload_client, tmp_path, monkeypatch):
    assert routes.MAX_UPLOAD == 100 * 1024 * 1024
    monkeypatch.setattr(routes, "MAX_UPLOAD", 16)
    response = upload_client.post("/api/upload", files={"file": ("plan.pdf", b"x" * 17)})
    assert response.status_code == 413
    assert "16 bytes" in response.json()["detail"]
    assert not list(tmp_path.rglob("*.*"))
    routes.db.get_pool.assert_not_awaited()
    assert upload_client.post("/api/upload", files={"file": ("plan.pdf", b"x" * 16)}).status_code == 200


@pytest.mark.parametrize("ext,kind", [("pdf", "pdf"), ("png", "raster"), ("jpg", "raster"),
                                     ("jpeg", "raster"), ("dxf", "dxf"), ("IFC", "ifc")])
def test_supported_uploads(upload_client, tmp_path, ext, kind):
    headers = {"pdf": b"content", "png": b"\x89PNG\r\n\x1a\n", "jpg": b"\xff\xd8\xff",
               "jpeg": b"\xff\xd8\xff", "dxf": b"0\nSECTION\n", "IFC": b"ISO-10303-21;"}
    response = upload_client.post("/api/upload", files={"file": (f"plan.{ext}", headers[ext])})
    assert response.status_code == 200
    doc_id = response.json()["doc_id"]
    assert json.loads((tmp_path / doc_id / "doc.json").read_text())["kind"] == kind


@pytest.fixture
def status_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    d = tmp_path / "uploads__test"
    d.mkdir()
    f = d / "ingest.json"
    f.write_text(json.dumps({"status": "running", "stages": [], "started_at": time.time()}))
    monkeypatch.setattr(routes, "_INGEST_LOCK", asyncio.Lock())
    monkeypatch.setattr(routes, "_persist", AsyncMock())
    monkeypatch.setattr(routes, "publish", AsyncMock())
    return f


@pytest.mark.parametrize("code", [0, 1, -9])
def test_job_exit_without_completion_fails(status_file, monkeypatch, code):
    proc = SimpleNamespace(returncode=code, wait=AsyncMock())
    monkeypatch.setattr(routes.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    asyncio.run(routes._ingest("uploads__test"))
    state = json.loads(status_file.read_text())
    assert state["status"] == "failed" and f"code {code}" in state["reason"]
    routes._persist.assert_awaited_once_with("uploads__test")
    routes.publish.assert_awaited_once()


def test_subprocess_launch_failure_is_recorded(status_file, monkeypatch):
    monkeypatch.setattr(routes.asyncio, "create_subprocess_exec", AsyncMock(side_effect=OSError("converter unavailable")))
    asyncio.run(routes._ingest("uploads__test"))
    state = json.loads(status_file.read_text())
    assert state["status"] == "failed" and "converter unavailable" in state["reason"]


def test_watchdog_kills_stalled_job_and_descendants(status_file, monkeypatch):
    proc = SimpleNamespace(returncode=None, pid=123)

    async def wait():
        if proc.returncode is None:
            await asyncio.Event().wait()

    killed = []

    def killpg(pid, signal):
        killed.append((pid, signal))
        proc.returncode = -9

    proc.wait = wait
    monkeypatch.setattr(routes.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    monkeypatch.setattr(routes.os, "killpg", killpg)
    assert routes.INGEST_TIMEOUT == 300
    monkeypatch.setattr(routes, "INGEST_TIMEOUT", 0.02)
    asyncio.run(routes._ingest("uploads__test"))
    assert killed == [(123, routes.signal.SIGKILL)]
    state = json.loads(status_file.read_text())
    assert state["status"] == "failed" and "timed out" in state["reason"]


def test_queued_job_also_times_out(status_file, monkeypatch):
    launch = AsyncMock()
    monkeypatch.setattr(routes.asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(routes, "INGEST_TIMEOUT", 0.02)

    async def run():
        async with routes._INGEST_LOCK:
            await routes._ingest("uploads__test")

    asyncio.run(run())
    launch.assert_not_awaited()
    assert "timed out" in json.loads(status_file.read_text())["reason"]


@pytest.mark.parametrize("status", ["ready", "partial", "failed"])
def test_terminal_job_status_is_preserved(status_file, monkeypatch, status):
    status_file.write_text(json.dumps({"status": status, "detail": "original reason", "stages": []}))
    proc = SimpleNamespace(returncode=0, wait=AsyncMock())
    monkeypatch.setattr(routes.asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    asyncio.run(routes._ingest("uploads__test"))
    assert json.loads(status_file.read_text())["status"] == status


@pytest.mark.parametrize("state", [None, {"status": "running", "step": "pages", "stages": []},
                                  {"status": "ready", "stages": []},
                                  {"status": "failed", "detail": "Invalid PDF", "stages": []},
                                  {"status": "partial", "detail": "IFC too large", "stages": []}])
def test_ingest_endpoint_progress_shape(upload_client, tmp_path, state):
    d = tmp_path / "uploads__progress"
    d.mkdir()
    if state is not None:
        (d / "ingest.json").write_text(json.dumps(state))
    response = upload_client.get("/api/docs/uploads__progress/ingest")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["step"], str) and 0 <= data["progress"] <= 1
    if state and state["status"] == "ready":
        assert data["progress"] == 1
    if state and state["status"] == "failed":
        assert data["reason"] == "Invalid PDF"


@pytest.mark.parametrize("legacy", [False, True])
def test_poll_recovers_stale_status_after_restart(upload_client, tmp_path, monkeypatch, legacy):
    d = tmp_path / "uploads__stale"
    d.mkdir()
    f = d / "ingest.json"
    state = {"status": "running", "stages": [], "step": "pages"}
    if not legacy:
        state["started_at"] = time.time() - 301
    f.write_text(json.dumps(state))
    if legacy:
        os.utime(f, (time.time() - 301, time.time() - 301))
    monkeypatch.setattr(routes, "_persist", AsyncMock())
    response = upload_client.get("/api/docs/uploads__stale/ingest").json()
    assert response["status"] == "failed" and "timed out" in response["reason"]
    assert json.loads(f.read_text())["status"] == "failed"
    routes._persist.assert_awaited_once_with("uploads__stale")


def test_corrupt_status_returns_clear_failure(upload_client, tmp_path):
    d = tmp_path / "uploads__broken"
    d.mkdir()
    (d / "ingest.json").write_text("{")
    state = upload_client.get("/api/docs/uploads__broken/ingest").json()
    assert state["status"] == "failed" and state["reason"] and state["progress"] == 0


def test_unhandled_ingest_error_sets_failed(status_file, monkeypatch):
    (status_file.parent / "doc.json").write_text("{")
    assert ingest_job.run("uploads__test") == "failed"
    state = json.loads(status_file.read_text())
    assert state["status"] == "failed" and state["reason"]


def test_corrupt_raster_stage_sets_failed(status_file, monkeypatch):
    (status_file.parent / "doc.json").write_text(json.dumps({"kind": "raster", "files": {"jpg": "missing.jpg"}}))
    monkeypatch.setattr(ingest_job, "light_mode", lambda: True)
    monkeypatch.setitem(sys.modules, "pipeline.pages", ModuleType("pipeline.pages"))
    monkeypatch.setattr(ingest_job, "_normalise_raster", lambda *args: (_ for _ in ()).throw(ValueError("Invalid image file")))
    assert ingest_job.run("uploads__test") == "failed"
    state = json.loads(status_file.read_text())
    assert state["status"] == "failed" and "Invalid image file" in state["reason"]
    assert state["step"] == "normalise" and 0 <= state["progress"] < 1
