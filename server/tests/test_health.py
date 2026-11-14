from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import app as app_module
from server.ratelimit import RateLimitMiddleware


def test_health_without_db(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@127.0.0.1:1/none")
    from server import db
    db._pool = None
    with TestClient(app_module.app) as c:
        r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "db": False}


def test_rate_limit_429_on_31st():
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limit=30, window=60.0)

    @app.get("/x")
    def x():
        return {"ok": True}

    c = TestClient(app)
    codes = [c.get("/x").status_code for _ in range(31)]
    assert codes[:30] == [200] * 30
    assert codes[30] == 429


def test_rate_limit_enabled_by_env(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT", "1")
    import importlib
    mod = importlib.reload(app_module)
    try:
        c = TestClient(mod.app)
        codes = [c.get("/api/health").status_code for _ in range(31)]
        assert codes[-1] == 429
    finally:
        monkeypatch.delenv("RATE_LIMIT")
        importlib.reload(mod)
