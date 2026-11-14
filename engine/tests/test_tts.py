"""ElevenLabs TTS through the model layer. No real network: mocked `providers._post`."""
import base64
import json

import httpx
import pytest

from engine.models import call, core
from engine.models import providers as P
from engine.tests.test_models import env, log_lines  # noqa: F401  (autouse fixture comes with the import)

MP3 = b"ID3\x03fake-mp3-bytes"


def audio(status=200, content=MP3):
    return httpx.Response(status, content=content, headers={"content-type": "audio/mpeg"})


@pytest.fixture(autouse=True)
def eleven_only(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk-test")


def test_elevenlabs_first_returns_audio_and_logs_cost(env, monkeypatch):
    seen = {}

    def post(url, headers, payload, timeout=0):
        seen.update(url=url, headers=headers, payload=payload)
        return audio()
    monkeypatch.setattr(P, "_post", post)
    r = call("tts", "Hello there")
    assert r.provider == "elevenlabs" and r.model == "eleven_flash_v2_5"
    assert base64.b64decode(r.extra["audio_b64"]) == MP3
    assert seen["url"].startswith("https://api.elevenlabs.io/v1/text-to-speech/SAz9YHcvj6GT2YYXdXww")
    assert seen["payload"] == {"text": "Hello there", "model_id": "eleven_flash_v2_5"}
    assert seen["headers"]["xi-api-key"] == "sk-test"
    assert r.cost_usd == pytest.approx(len("Hello there") * 0.00017)
    rec = log_lines(env)[-1]
    assert rec["provider"] == "elevenlabs" and rec["task"] == "tts" and rec["cost_usd"] > 0


def test_cache_makes_repeat_free(env, monkeypatch):
    n = []
    monkeypatch.setattr(P, "_post", lambda *a, **k: (n.append(1), audio())[1])
    a = call("tts", "Same text")
    b = call("tts", "Same text")
    assert len(n) == 1 and b.cache_hit and b.cost_usd == 0
    assert b.extra["audio_b64"] == a.extra["audio_b64"]


def test_voice_via_system_message(env, monkeypatch):
    seen = {}
    monkeypatch.setattr(P, "_post", lambda url, h, p, timeout=0: (seen.update(url=url), audio())[1])
    call("tts", [{"role": "system", "content": "voice=JBFqnCBsd6RMkjVDRZzb"}, {"role": "user", "content": "Hi"}])
    assert "/text-to-speech/JBFqnCBsd6RMkjVDRZzb?" in seen["url"]
    with pytest.raises(P.ProviderError):
        call("tts", [{"role": "system", "content": "voice=../../x"}, {"role": "user", "content": "Hi"}])


def test_falls_back_to_runware_on_error(env, monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "rw-test")

    def post(url, headers, payload, timeout=0):
        if "elevenlabs" in url:
            return httpx.Response(401, json={"detail": "bad key"})
        return httpx.Response(200, json={"data": [{"audioURL": "https://x/a.mp3", "cost": 0.0003}]})
    monkeypatch.setattr(P, "_post", post)
    r = call("tts", "Fallback please")
    assert r.provider == "runware" and r.audio_url == "https://x/a.mp3"


def test_budget_cap_from_costs_md(env, monkeypatch):
    (env / "COSTS.md").write_text("| ElevenLabs | 5 USD |\n")
    (env / "costs.jsonl").write_text(json.dumps({"provider": "elevenlabs", "cost_usd": 5.0}) + "\n")
    monkeypatch.setattr(P, "_post", lambda *a, **k: audio())
    with pytest.raises(core.BudgetExceeded):
        call("tts", "Over budget")


def test_audio_in_images_is_rejected_by_non_gemini(monkeypatch):
    img = P.Image(mime="audio/wav", data=b"RIFF", sha="x")
    for fn in (P.openai_compat, P.anthropic, P.runware):
        with pytest.raises(P.ProviderError):
            fn({"name": "x", "base_url": "http://x"}, "m", [{"role": "user", "content": "t"}], [img], None, {}, "k")
