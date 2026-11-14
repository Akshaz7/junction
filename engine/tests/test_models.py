"""Model layer tests. No real network: `fake` provider or mocked `providers._post`."""
import json

import httpx
import jsonschema
import pytest

from engine.models import BudgetExceeded, NoProviderAvailable, call, set_db_logger
from engine.models import core
from engine.models import providers as P

KEYS = ["GEMINI_API_KEY", "NVIDIA_API_KEY", "ANTHROPIC_API_KEY", "RUNWARE_API_KEY", "FEATHERLESS_API_KEY", "MODELS_FAKE"]


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(core, "ENV_FILE", tmp_path / "nonexistent.env")
    monkeypatch.setenv("MODELS_COSTS_LOG", str(tmp_path / "costs.jsonl"))
    monkeypatch.setenv("MODELS_CACHE_DIR", str(tmp_path / "cache"))
    costs_md = tmp_path / "COSTS.md"
    costs_md.write_text(
        "| Provider | Cap |\n|---|---|\n| Runware | 500 USD |\n| Anthropic | 15 USD |\n| Gemini | 20 USD |\n"
        "| Context.dev | 10,000 credits |\n| NVIDIA (build.nvidia.com) | free tier, with backoff |\n"
    )
    monkeypatch.setenv("MODELS_COSTS_MD", str(costs_md))
    monkeypatch.setattr(core, "_sleep", lambda s: None)
    core._spend_state.clear()
    set_db_logger(None)
    yield tmp_path


def log_lines(tmp):
    p = tmp / "costs.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def oai(text="hi"):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


def rw(text="hi", cost=0.001):
    return httpx.Response(200, json={"data": [{"text": text, "usage": {"promptTokens": 7, "completionTokens": 2}, "cost": cost}]})


def gem(text="hi"):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}],
                                     "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 100}})


# ---------------------------------------------------------------- fake
def test_fake_is_default_without_keys_and_deterministic(env):
    a = call("route", [{"role": "user", "content": "hello"}])
    b = call("route", [{"role": "user", "content": "hello"}])
    c = call("route", [{"role": "user", "content": "other"}])
    assert a.provider == "fake" and a.text == b.text and a.text != c.text
    assert a.cost_usd == 0


SCHEMA = {
    "type": "object",
    "required": ["n", "name", "tags", "ok", "kind", "box"],
    "properties": {
        "n": {"type": "integer", "minimum": 3},
        "name": {"type": "string", "minLength": 2},
        "tags": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "ok": {"type": "boolean"},
        "kind": {"enum": ["door", "window"]},
        "box": {"$ref": "#/$defs/box"},
        "extra": {"type": "string"},
    },
    "$defs": {"box": {"type": "object", "required": ["x"], "properties": {"x": {"type": "number"}}}},
    "additionalProperties": False,
}


def test_fake_schema_output_is_valid(env):
    r = call("read_drawing", "go", schema=SCHEMA)
    jsonschema.validate(r.json, SCHEMA)
    assert json.loads(r.text) == r.json


def test_models_fake_env_forces_fake_even_with_keys(env, monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "k")
    monkeypatch.setenv("MODELS_FAKE", "1")
    monkeypatch.setattr(P, "_post", lambda *a, **k: pytest.fail("network used"))
    assert call("route", "x").provider == "fake"


def test_images_change_cache_key_and_are_counted(env):
    a = call("verify_item", "q", images=[b"\x89PNG\r\n\x1a\n1"])
    b = call("verify_item", "q", images=[b"\x89PNG\r\n\x1a\n2"])
    assert a.images == 1 and a.text != b.text and not b.cache_hit


# ---------------------------------------------------------------- cache
def test_repeated_call_hits_cache(env, monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "k")
    n = []
    monkeypatch.setattr(P, "_post", lambda *a, **k: n.append(1) or rw("answer", 0.002))
    a = call("route", "q", request_id="r1")
    b = call("route", "q", request_id="r2")
    assert len(n) == 1
    assert (a.cache_hit, b.cache_hit) == (False, True)
    assert a.cost_usd == 0.002 and b.cost_usd == 0 and b.text == "answer"
    lines = log_lines(env)
    assert [x["cache_hit"] for x in lines] == [False, True]
    assert lines[1]["request_id"] == "r2" and lines[1]["provider"] == "runware"
    for k in ("task", "provider", "model", "input_tokens", "output_tokens", "images", "cost_usd", "latency_ms", "request_id", "cache_hit"):
        assert k in lines[0]


# ---------------------------------------------------------------- budget
def test_over_cap_raises_budget_exceeded(env, monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "k")
    (env / "costs.jsonl").write_text(json.dumps({"provider": "runware", "cost_usd": 500.0}) + "\n")
    monkeypatch.setattr(P, "_post", lambda *a, **k: pytest.fail("must not call provider over cap"))
    with pytest.raises(BudgetExceeded):
        call("route", "q")


def test_over_cap_falls_to_next_provider(env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("RUNWARE_API_KEY", "k")
    (env / "costs.jsonl").write_text(json.dumps({"provider": "gemini", "cost_usd": 20.0}) + "\n")
    hosts = []
    monkeypatch.setattr(P, "_post", lambda url, *a, **k: hosts.append(url) or rw())
    r = call("route", "q")
    assert r.provider == "runware" and hosts == ["https://api.runware.ai/v1"]


def test_spend_accumulates_from_log_and_nvidia_has_no_cap(env, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "n")
    monkeypatch.setattr(P, "_post", lambda *a, **k: oai())
    for i in range(3):
        call("advise", f"q{i}")
    assert core.spend("nvidia") == 0
    assert "nvidia" not in core.caps() and core.caps()["runware"] == 500


def test_cost_from_price_table(env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setattr(P, "_post", lambda *a, **k: gem())
    r = call("read_drawing", "q")  # gemini-3.8-flash: 1000*1.5 + 100*7.5 per 1e6
    assert r.provider == "gemini" and r.cost_usd == pytest.approx(0.00225)
    assert core.spend("gemini") == pytest.approx(0.00225)


# ---------------------------------------------------------------- chain
def test_chain_skips_missing_keys(env, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "n")
    monkeypatch.setenv("RUNWARE_API_KEY", "k")  # gemini (primary for route) has no key
    urls = []
    monkeypatch.setattr(P, "_post", lambda url, *a, **k: urls.append(url) or oai())
    r = call("route", "q")
    assert r.provider == "nvidia" and urls == ["https://integrate.api.nvidia.com/v1/chat/completions"]


def test_chain_skips_to_runware_when_only_runware(env, monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "k")
    monkeypatch.setattr(P, "_post", lambda *a, **k: rw())
    assert call("route", "q").provider == "runware"   # route's chain has only Runware among keyed providers
    monkeypatch.setattr(P, "_post", lambda *a, **k: httpx.Response(200, json={"content": [{"type": "text", "text": "hi"}], "usage": {}}))
    assert call("write_answer", "q").provider == "runware_claude"   # Claude via Runware leads write_answer and chat


def test_no_usable_provider_raises(env, monkeypatch):
    monkeypatch.setenv("FEATHERLESS_API_KEY", "f")  # a key exists, but not in route's chain
    with pytest.raises(NoProviderAvailable):
        call("route", "q")


def test_provider_error_falls_through_and_schema_enforced(env, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "n")
    monkeypatch.setenv("RUNWARE_API_KEY", "k")
    schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}}

    def post(url, *a, **k):
        return oai('{"a": "not-int"}') if "nvidia" in url else rw('{"a": 1}')

    monkeypatch.setattr(P, "_post", post)
    r = call("route", "q", schema=schema)
    assert r.provider == "runware" and r.json == {"a": 1}


# ---------------------------------------------------------------- backoff
def test_backoff_retries_429_then_succeeds(env, monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "k")
    seq = [httpx.Response(429), httpx.Response(429, headers={"retry-after": "2"}), rw("ok")]
    sleeps = []
    monkeypatch.setattr(core, "_sleep", sleeps.append)
    monkeypatch.setattr(P, "_post", lambda *a, **k: seq.pop(0))
    r = call("route", "q")
    assert r.text == "ok" and len(sleeps) == 2 and sleeps[1] == 2.0 and 0 < sleeps[0] <= 1.0


def test_backoff_gives_up_after_5_retries_then_falls_through(env, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "g")
    monkeypatch.setenv("RUNWARE_API_KEY", "k")
    calls = {"nv": 0}
    sleeps = []
    monkeypatch.setattr(core, "_sleep", sleeps.append)

    def post(url, *a, **k):
        if "nvidia" in url:
            calls["nv"] += 1
            return httpx.Response(503)
        return rw()

    monkeypatch.setattr(P, "_post", post)
    r = call("route", "q")
    assert r.provider == "runware" and calls["nv"] == 6 and len(sleeps) == 5


def test_runware_overload_error_code_is_retried(env, monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "k")
    seq = [httpx.Response(200, json={"errors": [{"code": "serviceOverloaded", "message": "busy", "retryAfter": 1}]}), rw("ok")]
    monkeypatch.setattr(P, "_post", lambda *a, **k: seq.pop(0))
    assert call("route", "q").text == "ok"


# ---------------------------------------------------------------- hooks & request shapes
def test_db_logger_receives_record(env):
    got = []
    set_db_logger(got.append)
    call("route", "q", request_id="abc")
    assert got and got[0]["request_id"] == "abc" and got[0]["provider"] == "fake"


def test_anthropic_request_has_no_sampling_params_and_uses_output_config(env, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    seen = {}

    def post(url, headers, payload, timeout=0):
        seen.update(url=url, headers=headers, body=payload)
        return httpx.Response(200, json={"content": [{"type": "text", "text": '{"v": 1}'}], "usage": {"input_tokens": 100, "output_tokens": 10}})

    monkeypatch.setattr(P, "_post", post)
    schema = {"type": "object", "required": ["v"], "properties": {"v": {"type": "integer"}}, "additionalProperties": False}
    r = call("write_answer", [{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}], schema=schema)
    b = seen["body"]
    assert r.provider == "anthropic" and r.json == {"v": 1}
    assert b["model"] == "claude-sonnet-5-5" and b["system"] == "sys"
    assert not ({"temperature", "top_p", "top_k"} & set(b)) and b["output_config"]["format"]["schema"] == schema
    assert seen["headers"]["x-api-key"] == "a" and r.cost_usd == pytest.approx((100 * 2 + 10 * 10) / 1e6)


def test_runware_request_shape_with_image_and_schema(env, monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "k")
    seen = {}

    def post(url, headers, payload, timeout=0):
        seen["task"] = payload[0]
        return rw('{"a": 1}', cost=0.0003)

    monkeypatch.setattr(P, "_post", post)
    schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}}
    r = call("verify_item", [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}], images=[b"\x89PNG\r\n\x1a\nxx"], schema=schema)
    t = seen["task"]
    assert t["taskType"] == "textInference" and t["settings"]["systemPrompt"] == "s" and t["outputFormat"] == "JSON"
    assert t["inputs"]["images"][0].startswith("data:image/png;base64,") and t["messages"] == [{"role": "user", "content": "q"}]
    assert r.cost_usd == 0.0003


def test_tts_fake_returns_audio_url(env):
    r = call("tts", "hello there")
    assert r.audio_url and r.audio_url.startswith("fake://")


def test_extra_body_is_sent_to_openai_compat(env, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "n")
    sent = {}

    def post(url, headers, payload, *a, **k):
        sent.update(payload)
        return oai("ok")

    monkeypatch.setattr(P, "_post", post)
    call("route", "q")
    assert sent.get("chat_template_kwargs") == {"enable_thinking": False}


# ---------------------------------------------------------------- verda (hosted Nemotron VL, OpenAI-compatible)
def test_verda_uses_its_base_url_key_and_max_tokens(env, monkeypatch):
    monkeypatch.setenv("VERDA_INFERENCE_KEY", "vk")
    seen = {}

    def post(url, headers, body, **k):
        seen.update(url=url, auth=headers["Authorization"], body=body)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok", "reasoning_content": "ignored"}}],
                                         "usage": {"prompt_tokens": 3, "completion_tokens": 1}})

    monkeypatch.setattr(P, "_post", post)
    r = call("chat", "hi", only=("verda", "nemotron-3.5-super-vl"))
    assert r.provider == "verda" and r.text == "ok" and r.cost_usd == 0
    assert seen["url"] == "https://containers.datacrunch.io/nemotron-3-5-super-vl-b300/v1/chat/completions"
    assert seen["auth"] == "Bearer vk" and seen["body"]["model"] == "nemotron-3.5-super-vl" and "max_tokens" in seen["body"]
