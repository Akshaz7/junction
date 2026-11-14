"""S-12: viewer exemptions, configurable quotas, WebSocket upgrades and health."""
import importlib

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from server import app as app_module
from server.ratelimit import RateLimitMiddleware


def limited_app(limit=None):
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limit=limit)

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        await socket.send_text("connected")
        await socket.close()

    @app.api_route("/{path:path}", methods=["GET", "POST"])
    async def endpoint(path: str):
        return {"ok": True}

    return app


@pytest.mark.parametrize("value, limit", [(None, 30), ("2", 2), ("", 30),
                                         ("invalid", 30), ("0", 30), ("-1", 30)])
def test_configurable_limit(monkeypatch, value, limit):
    monkeypatch.delenv("RATE_LIMIT_PER_MIN", raising=False)
    if value is not None:
        monkeypatch.setenv("RATE_LIMIT_PER_MIN", value)
    with TestClient(limited_app()) as c:
        assert [c.get("/api/chats").status_code for _ in range(limit)] == [200] * limit
        r = c.get("/api/chats")
        assert r.status_code == 429 and r.headers["Retry-After"] == "60"


@pytest.mark.parametrize("path", ["/api/health", "/api/docs/a/files/scene.glb",
                                 "/api/docs/a/files/scene.usdz", "/api/docs/a/pages/1/image",
                                 "/api/docs/a/scene", "/api/docs/a/ingest"])
def test_get_exemptions_do_not_consume_quota(path):
    with TestClient(limited_app(limit=2)) as c:
        assert all(c.get(path).status_code == 200 for _ in range(5))
        assert c.get("/api/chats").status_code == 200
        assert c.get("/api/chats").status_code == 200
        assert c.get("/api/chats").status_code == 429
        assert c.get(path).status_code == 200  # works even after exhaustion


@pytest.mark.parametrize("path", ["/api/chats", "/api/chats/id/messages", "/api/upload",
                                 "/api/advise", "/api/docs/a/scene",
                                 "/api/docs/a/files/scene.glb"])
def test_posts_remain_limited(path):
    with TestClient(limited_app(limit=30)) as c:
        assert all(c.post(path).status_code == 200 for _ in range(30))
        assert c.post(path).status_code == 429


@pytest.mark.parametrize("path", ["/api/docs", "/api/docs/a", "/api/docs/a/planmap/1",
                                 "/api/health-extra", "/api/docs/a/scene/extra"])
def test_other_gets_remain_limited(path):
    with TestClient(limited_app(limit=1)) as c:
        assert c.get(path).status_code == 200
        assert c.get(path).status_code == 429


def test_quota_is_shared_across_routes_but_separate_per_ip():
    with TestClient(limited_app(limit=1)) as c:
        assert c.post("/api/chats").status_code == 200
        assert c.post("/api/advise").status_code == 429
        assert c.post("/api/upload", headers={"x-forwarded-for": "192.0.2.1"}).status_code == 200


def test_websocket_upgrade_bypasses_exhausted_quota():
    with TestClient(limited_app(limit=1)) as c:
        with c.websocket_connect("/ws") as ws:
            assert ws.receive_text() == "connected"
        assert c.get("/api/chats").status_code == 200
        assert c.get("/api/chats").status_code == 429
        with c.websocket_connect("/ws") as ws:
            assert ws.receive_text() == "connected"


def test_app_uses_configurable_limit(monkeypatch):
    try:
        with monkeypatch.context() as m:
            m.setenv("RATE_LIMIT", "1")
            m.setenv("RATE_LIMIT_PER_MIN", "2")
            mod = importlib.reload(app_module)
            # No lifespan: this wiring check needs neither Postgres nor background jobs.
            c = TestClient(mod.app)
            assert c.get("/api/not-a-route").status_code == 404
            assert c.get("/api/not-a-route").status_code == 404
            assert c.get("/api/not-a-route").status_code == 429
    finally:
        importlib.reload(app_module)


@pytest.fixture
def health_client(monkeypatch, tmp_path):
    from engine.models import core
    from server import db

    for provider in core.config()["providers"].values():
        if provider.get("env"):
            monkeypatch.delenv(provider["env"], raising=False)
    monkeypatch.setattr(core, "ENV_FILE", tmp_path / "models.env")

    async def no_db():
        return False

    monkeypatch.setattr(db, "db_ok", no_db)
    monkeypatch.delenv("BUILD_REV", raising=False)
    app = FastAPI()
    app.add_api_route("/api/health", app_module.health)
    with TestClient(app) as c:
        yield c, core.ENV_FILE


def test_health_without_db_or_keys(health_client):
    c, _ = health_client
    r = c.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"ok", "db", "build_rev", "uptime_s", "models_ok",
                         "image", "bench_files", "artifacts_docs", "servable_docs", "caps_loaded"}
    assert body["ok"] is True and body["db"] is False
    assert body["models_ok"] is False and body["build_rev"] == ""
    assert isinstance(body["uptime_s"], (int, float)) and body["uptime_s"] >= 0
    assert c.get("/api/health").json()["uptime_s"] >= body["uptime_s"]


@pytest.mark.parametrize("provider", ["GEMINI_API_KEY", "NVIDIA_API_KEY", "ANTHROPIC_API_KEY",
                                     "RUNWARE_API_KEY", "FEATHERLESS_API_KEY", "ELEVENLABS_API_KEY"])
def test_health_reports_any_provider_without_secrets(health_client, monkeypatch, provider):
    c, _ = health_client
    monkeypatch.setenv(provider, "test-provider-key")
    monkeypatch.setenv("BUILD_REV", "test-revision")
    r = c.get("/api/health")
    assert r.json()["models_ok"] is True and r.json()["build_rev"] == "test-revision"
    assert "test-provider-key" not in r.text and provider not in r.text


def test_health_reads_dotenv_fresh(health_client):
    c, env_file = health_client
    assert c.get("/api/health").json()["models_ok"] is False
    env_file.write_text("GEMINI_API_KEY=test-provider-key\n")
    r = c.get("/api/health")
    assert r.json()["models_ok"] is True and "test-provider-key" not in r.text
    env_file.write_text("GEMINI_API_KEY=\n")
    assert c.get("/api/health").json()["models_ok"] is False


def test_health_reports_database_available(health_client, monkeypatch):
    from server import db

    async def db_ok():
        return True

    monkeypatch.setattr(db, "db_ok", db_ok)
    c, _ = health_client
    assert c.get("/api/health").json()["db"] is True
