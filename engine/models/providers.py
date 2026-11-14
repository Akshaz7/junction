"""Provider adapters. Each adapter turns a normalized request into one HTTP call.

Only `engine.models.core.call` may use this module. Adapters never read keys
from anywhere but the `key` argument and never log them.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

TIMEOUT_S = 120.0


class ProviderError(Exception):
    """Non-retryable failure of one provider: caller falls through to the next."""


class RateLimited(ProviderError):
    """429/503 style error: caller backs off and retries."""

    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


@dataclass
class Image:
    mime: str
    data: bytes
    sha: str

    @property
    def b64(self) -> str:
        return base64.b64encode(self.data).decode()

    @property
    def data_uri(self) -> str:
        return f"data:{self.mime};base64,{self.b64}"


@dataclass
class ProviderResponse:
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None  # None -> computed from the price table
    extra: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- http
def _post(url: str, headers: dict, payload: Any, timeout: float = TIMEOUT_S) -> httpx.Response:
    """The single network seam. Tests monkeypatch this."""
    return httpx.post(url, headers=headers, json=payload, timeout=timeout)


def _check(resp: httpx.Response, who: str) -> dict:
    if resp.status_code in (429, 503):
        ra = resp.headers.get("retry-after")
        try:
            ra_f = float(ra) if ra is not None else None
        except ValueError:
            ra_f = None
        raise RateLimited(f"{who} HTTP {resp.status_code}", ra_f)
    if resp.status_code >= 400:
        raise ProviderError(f"{who} HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        return resp.json()
    except ValueError as e:
        raise ProviderError(f"{who}: non-JSON response") from e


# --------------------------------------------------------------------------- helpers
def split_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    """Return (system_text, conversation) with string contents."""
    system, conv = [], []
    for m in messages:
        c = m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
        if m["role"] == "system":
            system.append(c)
        else:
            conv.append({"role": m["role"], "content": c})
    return "\n\n".join(system), conv


def schema_instruction(schema: dict) -> str:
    return (
        "Respond with a single JSON object only, no prose and no code fences, "
        "that validates against this JSON Schema:\n" + json.dumps(schema, separators=(",", ":"))
    )


def parse_json_text(text: str) -> Any:
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    if m:
        t = m.group(1)
    try:
        return json.loads(t)
    except ValueError:
        i, j = t.find("{"), t.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(t[i : j + 1])
            except ValueError:
                pass
    raise ProviderError("model did not return valid JSON")


# --------------------------------------------------------------------------- fake
def _fake_value(schema: Any, root: dict, depth: int = 0) -> Any:
    if not isinstance(schema, dict) or depth > 12:
        return None
    if "$ref" in schema:
        node: Any = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            if part:
                node = node[part]
        return _fake_value(node, root, depth + 1)
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return _fake_value(schema[key][0], root, depth + 1)
    if "allOf" in schema:
        merged: dict = {}
        for s in schema["allOf"]:
            merged.update(s)
        return _fake_value(merged, root, depth + 1)
    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), t[0])
    if t is None:
        t = "object" if "properties" in schema else "string"
    if t == "object":
        props = schema.get("properties", {})
        return {k: _fake_value(props.get(k, {}), root, depth + 1) for k in schema.get("required", [])}
    if t == "array":
        n = schema.get("minItems", 0)
        return [_fake_value(schema.get("items", {}), root, depth + 1) for _ in range(n)]
    if t == "string":
        return "x" * schema.get("minLength", 0)
    if t in ("number", "integer"):
        lo = schema.get("minimum")
        if lo is None and "exclusiveMinimum" in schema:
            lo = schema["exclusiveMinimum"] + 1
        v = 0 if lo is None else lo
        if "maximum" in schema and v > schema["maximum"]:
            v = schema["maximum"]
        return int(v) if t == "integer" else float(v)
    if t == "boolean":
        return False
    return None


def fake(cfg, model, messages, images, schema, params, key) -> ProviderResponse:
    h = hashlib.sha256(
        json.dumps([model, messages, [i.sha for i in images], schema], sort_keys=True, default=str).encode()
    ).hexdigest()
    prompt_chars = sum(len(str(m["content"])) for m in messages)
    if params.get("kind") == "audio":
        return ProviderResponse(text="", input_tokens=prompt_chars // 4, extra={"audio_url": f"fake://audio/{h[:16]}.mp3"})
    if schema is not None:
        text = json.dumps(_fake_value(schema, schema))
    else:
        text = f"fake:{h[:16]}"
    return ProviderResponse(text=text, input_tokens=prompt_chars // 4 + len(images) * 85, output_tokens=len(text) // 4 + 1, cost_usd=0.0)


# --------------------------------------------------------------------------- openai-compatible (nvidia, featherless)
def openai_compat(cfg, model, messages, images, schema, params, key) -> ProviderResponse:
    system, conv = split_messages(messages)
    if schema is not None:
        system = (system + "\n\n" if system else "") + schema_instruction(schema)
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    last_user = max((i for i, x in enumerate(conv) if x["role"] == "user"), default=None)
    for idx, m in enumerate(conv):
        if images and idx == last_user:
            parts: list[dict] = [{"type": "text", "text": m["content"]}]
            parts += [{"type": "image_url", "image_url": {"url": im.data_uri}} for im in images]
            out.append({"role": m["role"], "content": parts})
        else:
            out.append(m)
    body: dict[str, Any] = {"model": model, "messages": out, "max_tokens": params.get("max_tokens", 1024), "stream": False}
    if params.get("temperature") is not None:
        body["temperature"] = params["temperature"]
    if params.get("extra_body"):  # e.g. Nemotron chat_template_kwargs
        body.update(params["extra_body"])
    resp = _post(
        cfg["base_url"].rstrip("/") + "/chat/completions",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        body,
    )
    d = _check(resp, cfg["name"])
    try:
        text = d["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError) as e:
        raise ProviderError(f"{cfg['name']}: unexpected response shape") from e
    u = d.get("usage") or {}
    return ProviderResponse(text=text, input_tokens=u.get("prompt_tokens", 0), output_tokens=u.get("completion_tokens", 0))


# --------------------------------------------------------------------------- gemini
def gemini(cfg, model, messages, images, schema, params, key) -> ProviderResponse:
    system, conv = split_messages(messages)
    contents: list[dict] = []
    last_user = max((i for i, m in enumerate(conv) if m["role"] == "user"), default=None)
    for i, m in enumerate(conv):
        parts: list[dict] = [{"text": m["content"]}]
        if images and i == last_user:
            parts += [{"inline_data": {"mime_type": im.mime, "data": im.b64}} for im in images]
        contents.append({"role": "model" if m["role"] == "assistant" else "user", "parts": parts})
    gen: dict[str, Any] = {"maxOutputTokens": params.get("max_tokens", 1024)}
    if params.get("temperature") is not None:
        gen["temperature"] = params["temperature"]
    if schema is not None:
        gen["responseMimeType"] = "application/json"
        gen["responseJsonSchema"] = schema
    body: dict[str, Any] = {"contents": contents, "generationConfig": gen}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    resp = _post(
        f"{cfg['base_url'].rstrip('/')}/models/{model}:generateContent",
        {"x-goog-api-key": key, "Content-Type": "application/json"},
        body,
    )
    d = _check(resp, "gemini")
    try:
        cand = d["candidates"][0]
        text = "".join(p.get("text", "") for p in cand["content"]["parts"] if not p.get("thought"))
    except (KeyError, IndexError, TypeError) as e:
        raise ProviderError(f"gemini: no candidate ({d.get('promptFeedback') or cand_finish(d)})") from e
    u = d.get("usageMetadata") or {}
    return ProviderResponse(
        text=text,
        input_tokens=u.get("promptTokenCount", 0),
        output_tokens=u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0),
    )


def cand_finish(d: dict) -> str:
    try:
        return str(d["candidates"][0].get("finishReason"))
    except (KeyError, IndexError, TypeError):
        return "none"


# --------------------------------------------------------------------------- anthropic
def anthropic(cfg, model, messages, images, schema, params, key) -> ProviderResponse:
    system, conv = split_messages(messages)
    last_user = max((i for i, m in enumerate(conv) if m["role"] == "user"), default=None)
    out: list[dict] = []
    for i, m in enumerate(conv):
        if images and i == last_user:
            blocks: list[dict] = [
                {"type": "image", "source": {"type": "base64", "media_type": im.mime, "data": im.b64}} for im in images
            ]
            blocks.append({"type": "text", "text": m["content"]})
            out.append({"role": m["role"], "content": blocks})
        else:
            out.append(m)
    body: dict[str, Any] = {"model": model, "max_tokens": params.get("max_tokens", 1024), "messages": out}
    if system:
        body["system"] = system
    if schema is not None:
        body["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    # temperature/top_p/top_k are removed from API version 2026-10-21: never send them.
    resp = _post(
        cfg["base_url"].rstrip("/") + "/messages",
        {"x-api-key": key, "anthropic-version": cfg.get("version", "2026-10-21"), "content-type": "application/json"},
        body,
    )
    if resp.status_code == 529:  # Anthropic "overloaded"
        raise RateLimited("anthropic HTTP 529")
    d = _check(resp, "anthropic")
    text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
    u = d.get("usage") or {}
    return ProviderResponse(text=text, input_tokens=u.get("input_tokens", 0), output_tokens=u.get("output_tokens", 0))


# --------------------------------------------------------------------------- runware (native API, NOT OpenAI-compatible)
_RW_RETRY_CODES = {"serviceOverloaded", "timeoutProvider", "providerRateLimitExceeded"}


def _runware_call(cfg, key, task: dict) -> dict:
    task = {"taskUUID": str(uuid.uuid4()), **task}
    resp = _post(cfg["base_url"], {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, [task])
    if resp.status_code in (429, 503, 504):
        ra = resp.headers.get("retry-after")
        raise RateLimited(f"runware HTTP {resp.status_code}", float(ra) if ra and ra.replace(".", "", 1).isdigit() else None)
    try:
        d = resp.json()
    except ValueError as e:
        raise ProviderError("runware: non-JSON response") from e
    if d.get("errors"):
        e0 = d["errors"][0]
        msg = f"runware {e0.get('code')}: {str(e0.get('message'))[:200]}"
        if e0.get("code") in _RW_RETRY_CODES:
            raise RateLimited(msg, e0.get("retryAfter"))
        raise ProviderError(msg)
    if resp.status_code >= 400 or not d.get("data"):
        raise ProviderError(f"runware HTTP {resp.status_code}: {resp.text[:300]}")
    return d["data"][0]


def runware(cfg, model, messages, images, schema, params, key) -> ProviderResponse:
    if params.get("kind") == "audio":
        text = "\n".join(m["content"] for m in messages if m["role"] == "user" and isinstance(m["content"], str))
        r = _runware_call(
            cfg, key,
            {"taskType": "audioInference", "model": model, "speech": {"text": text},
             "outputType": "URL", "outputFormat": "MP3", "includeCost": True},
        )
        return ProviderResponse(
            text="", input_tokens=len(text.encode()), cost_usd=r.get("cost"), extra={"audio_url": r.get("audioURL")}
        )
    system, conv = split_messages(messages)
    if not conv or conv[-1]["role"] != "user":
        raise ProviderError("runware: final message must be a user message")
    task: dict[str, Any] = {
        "taskType": "textInference",
        "model": model,
        "messages": conv,
        "settings": {"maxTokens": params.get("max_tokens", 1024)},
        "includeCost": True,
        "includeUsage": True,
    }
    if system:
        task["settings"]["systemPrompt"] = system
    if params.get("temperature") is not None:
        task["settings"]["temperature"] = params["temperature"]
    if images:
        task["inputs"] = {"images": [im.data_uri for im in images]}
    if schema is not None:
        task["outputFormat"] = "JSON"
        task["jsonSchema"] = schema
    r = _runware_call(cfg, key, task)
    u = r.get("usage") or {}
    return ProviderResponse(
        text=r.get("text") or "",
        input_tokens=u.get("promptTokens", 0),
        output_tokens=u.get("completionTokens", 0),
        cost_usd=r.get("cost"),
    )


ADAPTERS: dict[str, Callable] = {
    "fake": fake,
    "gemini": gemini,
    "nvidia": openai_compat,
    "featherless": openai_compat,
    "anthropic": anthropic,
    "runware": runware,
}
# providers that enforce the schema server-side; the rest get it as an instruction and are validated locally
NATIVE_SCHEMA = {"fake", "gemini", "anthropic", "runware"}
