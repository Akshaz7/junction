"""An upload whose page image never reached PostgreSQL is re-rendered from its stored original."""
import json
import shutil

import pytest
from PIL import Image

from server import artifact_store, config, files_routes, ingest_job


def test_visual_files_are_stored_before_bulky_extras():
    names = ["scene.usdz", "page-1.png", "scene.glb", "page-1.thumb.png", "planmap-1.json", "normalised.png"]
    order = sorted(names, key=artifact_store._priority)
    assert order.index("planmap-1.json") < order.index("page-1.png") < order.index("page-1.thumb.png")
    assert order.index("scene.glb") < order.index("page-1.thumb.png") < order.index("scene.usdz")
    # still capped like other bulk files
    assert artifact_store._priority("page-1.png") > 1


def test_page_image_rebuilt_from_original(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "artifacts_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "REPO", tmp_path)
    monkeypatch.setattr(ingest_job, "REPO", tmp_path)
    doc_id = "uploads__x-abc123"
    (tmp_path / "uploads").mkdir()
    Image.new("RGB", (309, 600), "white").save(tmp_path / "uploads" / f"{doc_id}.jpg")
    d = tmp_path / doc_id
    d.mkdir()
    (d / "doc.json").write_text(json.dumps({
        "doc_id": doc_id, "kind": "raster", "files": {"png": f"{doc_id}/normalised.png"},
        "original_files": {"jpg": f"uploads/{doc_id}.jpg"}}))
    files_routes._rebuild_pages_sync(doc_id)
    assert Image.open(d / "page-1.png").size == (309, 600)
