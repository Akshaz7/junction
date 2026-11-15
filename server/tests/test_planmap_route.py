"""GET /api/docs/{doc_id}/planmap/{n} serves planmap-<n>.json unchanged: the 2D viewer's click-to-inspect needs kind,
bbox_px, polygon_px, props (role, length_m, area_m2, ...) and the page scale block (m_per_px)."""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import config, files_routes as routes


def _client(monkeypatch, art: Path) -> TestClient:
    monkeypatch.setenv("ARTIFACTS_DIR", str(art))
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes._restore] = lambda: None  # no PostgreSQL: files are already on disk
    return TestClient(app)


def _artifact_roots() -> list[Path]:
    """Local artifacts, the baked demo artifacts, and (from a git worktree) the main checkout's artifacts."""
    roots = [config.artifacts_dir(), config.REPO / "artifacts", config.REPO / "deploy" / "demo_artifacts"]
    git = config.REPO / ".git"
    if git.is_file() and git.read_text().startswith("gitdir:"):
        roots.append(Path(git.read_text().split(":", 1)[1].strip()).parents[2] / "artifacts")
    return roots


def _find(doc_id: str) -> Path | None:
    return next((r for r in _artifact_roots() if (r / doc_id / "planmap-1.json").is_file()), None)


def test_planmap_is_served_byte_for_byte(tmp_path, monkeypatch):
    pm = {"doc_id": "uploads__x-1", "page": 1, "image": {"w": 100, "h": 80},
          "scale": {"m_per_px": 0.02, "method": "printed 1:100", "confidence": 0.9},
          "items": [{"item_id": "wall-001", "kind": "wall", "bbox_px": [1, 2, 30, 4],
                     "polygon_px": [[1, 2], [30, 2], [30, 4], [1, 4]],
                     "props": {"length_m": 0.58, "thickness_m": 0.04, "role": "exterior"}}]}
    raw = json.dumps(pm, indent=1).encode()
    (tmp_path / "uploads__x-1").mkdir()
    (tmp_path / "uploads__x-1" / "planmap-1.json").write_bytes(raw)
    with _client(monkeypatch, tmp_path) as c:
        r = c.get("/api/docs/uploads__x-1/planmap/1")
        assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
        assert r.content == raw
        assert c.get("/api/docs/uploads__x-1/planmap/2").json()["status"] == "not_built"


# (doc, item kinds that must carry a polygon, props keys that must appear somewhere)
REAL = [
    ("uploads__swiss-site289-floor2149-bff698", {"wall", "room"}, {"length_m", "thickness_m", "area_m2", "width_m", "role"}),
    ("cubicasa5k__colorful-11397", {"wall", "door", "room"}, {"length_px", "thickness_px", "area_m2"}),
    ("swiss_dwellings__site289-bldg536-floor2149", {"wall", "door", "room"}, {"area_m2_label", "leaf_len_m"}),
]


@pytest.mark.parametrize("doc_id,poly_kinds,prop_keys", REAL)
def test_real_planmap_keeps_inspect_fields(monkeypatch, doc_id, poly_kinds, prop_keys):
    root = _find(doc_id)
    if root is None:
        pytest.skip(f"{doc_id} artifacts not on this machine")
    src = json.loads((root / doc_id / "planmap-1.json").read_text())
    with _client(monkeypatch, root) as c:
        r = c.get(f"/api/docs/{doc_id}/planmap/1")
    assert r.status_code == 200
    body = r.json()
    assert body == src
    assert body["scale"]["m_per_px"] > 0
    items = body["items"]
    assert items and all(i.get("kind") and len(i.get("bbox_px") or []) == 4 for i in items)
    assert poly_kinds <= {i["kind"] for i in items if len(i.get("polygon_px") or []) >= 3}
    assert prop_keys <= {k for i in items for k in (i.get("props") or {})}
