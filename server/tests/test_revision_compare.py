"""Comparison route with generated for demo fixtures and an isolated DB stub."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from server import artifact_store, db
from server.files_routes import router


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setenv("HIDE_EMPTY_DOCS", "0")
    class Pool:
        async def fetch(self, query):
            assert query == "select doc_id from documents"
            return [{"doc_id": d} for d in ("a", "b", "no-data")]
    async def pool():
        return Pool()
    async def restore(doc_id):
        return None
    monkeypatch.setattr(db, "get_pool", pool)
    monkeypatch.setattr(artifact_store, "ensure_doc", restore)
    for doc, items in (("a", []), ("b", [{"item_id": "guid", "kind": "window", "storey": "Våning 1", "bbox_m": [[0, 0, 0], [1, 1, 1]]}])):
        folder = tmp_path / doc; folder.mkdir()
        (folder / "doc.json").write_text(json.dumps({"title": f"Plan Rev {doc.upper()}", "kind": "ifc"}))
        (folder / "elements.json").write_text(json.dumps({"elements": items, "units": "m"}))
    app = FastAPI(); app.include_router(router)
    return TestClient(app)


def test_compare_arbitrary_listed_versions_includes_both_sources(client):
    response = client.post("/api/changes/compare", json={"doc_a": "a", "doc_b": "b"})
    assert response.status_code == 200
    result = response.json()
    assert result["summary"]["added"] == 1 and result["summary"]["by_storey"]["Våning 1"]["total"] == 1
    assert [c["doc_id"] for c in result["changes"][0]["citations"]] == ["a", "b"]
    assert result["versions"][0]["label"] == "Plan Rev A"


@pytest.mark.parametrize("body,status", [({"doc_a": "a", "doc_b": "a"}, 400),
    ({"doc_a": "../a", "doc_b": "b"}, 400), ({"doc_a": "a", "doc_b": "unknown"}, 404),
    ({"doc_a": "a"}, 400), ([], 400), ({"doc_a": 1, "doc_b": {}}, 400)])
def test_invalid_or_unlisted_versions(client, body, status):
    assert client.post("/api/changes/compare", json=body).status_code == status


def test_missing_data_is_unavailable_with_no_invented_zero(client):
    result = client.post("/api/changes/compare", json={"doc_a": "a", "doc_b": "no-data"}).json()
    assert result["status"] == "unavailable" and result["summary"] is None


def test_reverse_order_reverses_added_and_removed(client):
    result = client.post("/api/changes/compare", json={"doc_a": "b", "doc_b": "a"}).json()
    assert result["summary"]["removed"] == 1 and result["summary"]["added"] == 0
