"""Answer-text streaming: anthropic SSE -> DELTA_SINK (cumulative text), only for write_answer/chat, never cached-as-stream."""
import json

import pytest

from engine.models import call, set_db_logger
from engine.models import core
from engine.models import providers as P


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for k in ["GEMINI_API_KEY", "NVIDIA_API_KEY", "RUNWARE_API_KEY", "MODELS_FAKE"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(core, "ENV_FILE", tmp_path / "nonexistent.env")
    monkeypatch.setenv("MODELS_COSTS_LOG", str(tmp_path / "costs.jsonl"))
    monkeypatch.setenv("MODELS_CACHE_DIR", str(tmp_path / "cache"))
    costs = tmp_path / "COSTS.md"
    costs.write_text("| Provider | Cap |\n|---|---|\n| Anthropic | 15 USD |\n")
    monkeypatch.setenv("MODELS_COSTS_MD", str(costs))
    core._spend_state.clear()
    set_db_logger(None)


class FakeStream:
    status_code = 200

    def __init__(self, events):
        self.lines = [f"data: {json.dumps(e)}" for e in events]

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def iter_lines(self): return iter(self.lines)


EVENTS = [
    {"type": "message_start", "message": {"usage": {"input_tokens": 12}}},
    {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "There are "}},
    {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "**3 doors**."}},
    {"type": "message_delta", "usage": {"output_tokens": 7}},
]


def test_write_answer_streams_cumulative_text_and_returns_full_result(monkeypatch):
    monkeypatch.setattr(P.httpx, "stream", lambda *a, **k: FakeStream(EVENTS))
    seen = []
    tok = P.DELTA_SINK.set(seen.append)
    try:
        r = call("write_answer", [{"role": "user", "content": "q"}], only=("anthropic", "claude-sonnet-5-5"))
    finally:
        P.DELTA_SINK.reset(tok)
    assert seen == ["There are ", "There are **3 doors**."]
    assert r.text == "There are **3 doors**." and r.input_tokens == 12 and r.output_tokens == 7


def test_other_tasks_and_no_sink_do_not_stream(monkeypatch):
    monkeypatch.setattr(P.httpx, "stream", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not stream")))
    import httpx
    monkeypatch.setattr(P, "_post", lambda *a, **k: httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}], "usage": {}}))
    seen = []
    tok = P.DELTA_SINK.set(seen.append)
    try:
        assert call("route", [{"role": "user", "content": "q"}], only=("anthropic", "claude-sonnet-5-5")).text == "ok"
    finally:
        P.DELTA_SINK.reset(tok)
    assert seen == []
    assert call("write_answer", [{"role": "user", "content": "q2"}], only=("anthropic", "claude-sonnet-5-5")).text == "ok"
