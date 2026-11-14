"""Upload validation, original preservation and honest partial-state behaviour."""
import io
import json

import pytest
from PIL import Image

from server import ingest_job
from server.tests.test_files_upload import upload_client  # noqa: F401, F811


def image_bytes():
    b = io.BytesIO()
    Image.new("RGB", (30, 20), "white").save(b, format="PNG")
    return b.getvalue()


@pytest.mark.parametrize("name,detail", [("a.dwg", "Export the drawing as DXF or IFC"),
                                        ("a.zip", "Extract the files"), ("a.xlsx", "Export the schedule as PDF"),
                                        ("a.csv", "Export the schedule as PDF"), ("a.txt", "Export the schedule as PDF")])
def test_unsupported_formats_give_next_step(upload_client, name, detail):
    r = upload_client.post("/api/upload", files={"file": (name, b"anything")})
    assert r.status_code == 415 and detail in r.json()["detail"]


@pytest.mark.parametrize("name,data,detail", [("wrong.jpg", b"\x89PNG\r\n\x1a\n", "contents are PNG"),
                                             ("wrong.ifc", b"not an IFC", "corrupt or have the wrong extension"),
                                             ("wrong.dxf", b"AC1032", "contents are DWG")])
def test_mismatched_extension_fails_before_document_creation(upload_client, tmp_path, name, data, detail):
    r = upload_client.post("/api/upload", files={"file": (name, data)})
    assert r.status_code == 422 and detail in r.json()["detail"]
    assert not list(tmp_path.rglob("*.tmp")) and not list(tmp_path.rglob("doc.json"))


def test_duplicate_uploads_preserve_independent_originals(upload_client, tmp_path):
    ids = [upload_client.post("/api/upload", files={"file": ("duplicate.png", image_bytes())}).json()["doc_id"] for _ in range(2)]
    assert ids[0] != ids[1]
    metas = [json.loads((tmp_path / doc_id / "doc.json").read_text()) for doc_id in ids]
    assert metas[0]["content_sha256"] == metas[1]["content_sha256"]
    assert metas[0]["files"] != metas[1]["files"]


def test_normalisation_preserves_original_and_uses_artifact_directory(tmp_path, monkeypatch):
    from server import artifact_store
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    d = tmp_path / "doc"
    d.mkdir()
    src = tmp_path / "source.png"
    Image.new("RGBA", (30, 10), (0, 0, 0, 0)).save(src)
    original = src.read_bytes()
    (d / "doc.json").write_text(json.dumps({"files": {"png": str(src)}}))
    ingest_job._normalise_raster("doc", tmp_path)
    meta = json.loads((d / "doc.json").read_text())
    assert src.read_bytes() == original and meta["original_files"] == {"png": str(src)}
    assert meta["files"]["png"] == str(d / "normalised.png")
    assert Image.open(d / "normalised.png").getpixel((0, 0)) == (255, 255, 255)
    assert "__original__/source.png" in dict(artifact_store.doc_files("doc"))


def test_partial_scene_failure_keeps_drawing_readable(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setattr(ingest_job, "light_mode", lambda: True)
    d = tmp_path / "doc"
    d.mkdir()
    src = tmp_path / "source.png"
    src.write_bytes(image_bytes())
    (d / "doc.json").write_text(json.dumps({"doc_id": "doc", "kind": "raster", "files": {"png": str(src)}}))

    def fail_reader(doc_id, ddir, status, cost):
        status.stage("planmap_vlm", lambda: (_ for _ in ()).throw(RuntimeError("The drawing reader is unavailable. Try again later.")))
        return []

    monkeypatch.setattr(ingest_job, "_vlm_pages", fail_reader)
    assert ingest_job.run("doc") == "partial"
    status = json.loads((d / "ingest.json").read_text())
    assert status["readable"] and "reader is unavailable" in status["detail"]
    assert (d / "page-1.png").is_file()


def test_managed_ingest_keeps_converter_in_watchdog_group(tmp_path, monkeypatch):
    """Regression: detached converter grandchildren escaped the ingest timeout."""
    from pipeline import ifc_scene
    from types import SimpleNamespace
    captured = {}
    src = tmp_path / "source.ifc"
    src.write_text("unit fixture")
    dst = tmp_path / "raw.glb"
    dst.write_bytes(b"old output")
    monkeypatch.setenv("INGEST_MANAGED_JOB", "1")
    monkeypatch.setenv("HEAVY_SLOT_HELD", "1")
    monkeypatch.setattr(ifc_scene, "IFC_CONVERT", src)
    monkeypatch.setattr(__import__("platform"), "system", lambda: "Darwin")

    def popen(cmd, **kwargs):
        captured.update(kwargs)
        def communicate(timeout):
            dst.write_bytes(b"new output")
            return "", None
        return SimpleNamespace(communicate=communicate)

    monkeypatch.setattr(ifc_scene.subprocess, "Popen", popen)
    ifc_scene.convert(src, dst)
    assert captured["start_new_session"] is False


def test_ifc_conversion_limit_is_failed_with_a_next_step(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("INGEST_IFC_MAX_MB", "0")
    d = tmp_path / "doc"
    d.mkdir()
    src = tmp_path / "source.ifc"
    src.write_bytes(b"ISO-10303-21;")
    (d / "doc.json").write_text(json.dumps({"doc_id": "doc", "kind": "ifc", "files": {"ifc": str(src)}}))
    assert ingest_job.run("doc") == "failed"
    state = json.loads((d / "ingest.json").read_text())
    assert not state["readable"] and "Split the model" in state["reason"]


def test_ifc_parser_error_has_a_next_step(tmp_path):
    status = ingest_job.Status(tmp_path / "ingest.json")
    assert not status.stage("ifc_scene", lambda: (_ for _ in ()).throw(RuntimeError("Unable to parse IFC SPF header")))
    assert "Export it again as IFC" in status.stages[0]["error"]


def test_original_download_restores_metadata_before_choosing_source(tmp_path, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from server import artifact_store, docs_routes
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    doc_id = "uploads__restored"
    d = tmp_path / doc_id
    original = tmp_path / "original.jpeg"
    normalised = tmp_path / "normalised.png"
    normalised.write_bytes(b"reader copy")
    record = {"doc_id": doc_id, "files": {"png": str(normalised)}}
    monkeypatch.setattr(docs_routes, "_document", AsyncMock(return_value=record))

    async def restore(doc_id):
        d.mkdir()
        original.write_bytes(b"original source")
        (d / "doc.json").write_text(json.dumps({"original_files": {"jpeg": str(original)}}))

    monkeypatch.setattr(artifact_store, "ensure_doc", restore)
    response = asyncio.run(docs_routes.doc_source(doc_id))
    assert response.path == original
