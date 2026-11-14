"""S-08: /api/tts and /api/speech-intent, with and without keys. No real network."""
import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from engine.models import core
from engine.models import providers as P

MP3 = b"ID3\x03fake"
KEYS = ["GEMINI_API_KEY", "NVIDIA_API_KEY", "ANTHROPIC_API_KEY", "RUNWARE_API_KEY", "FEATHERLESS_API_KEY",
        "ELEVENLABS_API_KEY", "MODELS_FAKE"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    import server.app  # noqa: F401  (may load .env into os.environ; import before we clear keys)
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(core, "ENV_FILE", tmp_path / "none.env")
    monkeypatch.setenv("MODELS_COSTS_LOG", str(tmp_path / "costs.jsonl"))
    monkeypatch.setenv("MODELS_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:x@127.0.0.1:1/none")
    core._spend_state.clear()
    from server import db
    monkeypatch.setattr(db, "_pool", None)
    from server.app import app
    with TestClient(app) as c:
        yield c


def test_tts_without_keys_falls_back(client):
    r = client.post("/api/tts", json={"text": "Hello"})
    assert r.status_code == 200 and r.json()["fallback"] == "device"


def test_tts_validation(client):
    assert client.post("/api/tts", json={"text": "  "}).status_code == 400
    assert client.post("/api/tts", json={"text": "x" * 1501}).status_code == 413
    assert client.post("/api/tts", json={"text": "hi", "voice": "../x"}).status_code == 400


def test_tts_with_key_returns_mp3(client, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")
    monkeypatch.setattr(P, "_post", lambda *a, **k: httpx.Response(200, content=MP3, headers={"content-type": "audio/mpeg"}))
    r = client.post("/api/tts", json={"text": "Hello"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert r.content == MP3 and r.headers["x-tts-provider"] == "elevenlabs" and r.headers["x-tts-cache"] == "miss"
    r2 = client.post("/api/tts", json={"text": "Hello"})
    assert r2.content == MP3 and r2.headers["x-tts-cache"] == "hit"


def test_tts_provider_failure_falls_back(client, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")
    monkeypatch.setattr(P, "_post", lambda *a, **k: httpx.Response(401, json={}))
    r = client.post("/api/tts", json={"text": "Hello"})
    assert r.status_code == 200 and r.json()["fallback"] == "device"


def test_tts_runware_url_is_fetched(client, monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "rw")
    monkeypatch.setattr(P, "_post", lambda *a, **k: httpx.Response(200, json={"data": [{"audioURL": "https://x/a.mp3", "cost": 0.0001}]}))
    import server.speech_routes as sr
    monkeypatch.setattr(sr.httpx, "get", lambda *a, **k: httpx.Response(200, content=MP3, request=httpx.Request("GET", "https://x")))
    r = client.post("/api/tts", json={"text": "Hello"})
    assert r.content == MP3 and r.headers["x-tts-provider"] == "runware"


def test_speech_intent_fallback_and_validation(client):
    wav = ("a.wav", b"RIFFxxxx", "audio/wav")
    assert client.post("/api/speech-intent", files={"file": wav}).json()["fallback"] == "device"
    assert client.post("/api/speech-intent", files={"file": ("a.txt", b"x", "text/plain")}).status_code == 415
    assert client.post("/api/speech-intent", files={"file": ("a.wav", b"", "audio/wav")}).status_code == 400


def test_speech_intent_with_gemini(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    seen = {}

    def post(url, headers, payload, timeout=0):
        seen["payload"] = payload
        out = json.dumps({"text": "how many windows are there", "intent": "ask"})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": out}]}}],
                                         "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 8}})
    monkeypatch.setattr(P, "_post", post)
    r = client.post("/api/speech-intent", files={"file": ("a.wav", b"RIFFxxxx", "audio/wav")})
    assert r.json() == {"text": "how many windows are there", "intent": "ask", "provider": "gemini"}
    parts = seen["payload"]["contents"][-1]["parts"]
    assert parts[-1]["inline_data"]["mime_type"] == "audio/wav"
