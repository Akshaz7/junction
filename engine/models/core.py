"""The model layer: one entry point, `call()`. Nothing else may call a provider.

Order of work for each provider in a task's chain:
  skip if its key is missing -> disk cache -> budget cap -> HTTP call with
  backoff on 429/503 -> schema validation -> cost, log, cache.
A failure moves on to the next provider; if the chain is exhausted the last
error is re-raised so the caller can abstain.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import random
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx
import yaml
from dotenv import dotenv_values

from . import providers as P
from .providers import Image, ProviderError, RateLimited

REPO = Path(__file__).resolve().parents[2]
MAX_RETRIES = 5
BASE_DELAY_S = 1.0
MAX_DELAY_S = 30.0

ENV_FILE = REPO / ".env"
_sleep: Callable[[float], None] = time.sleep  # tests patch this


class ModelError(ProviderError):
    """Base for every failure `call()` raises; catch this to abstain."""


class BudgetExceeded(ModelError):
    pass


class NoProviderAvailable(ModelError):
    pass


@dataclass
class Result:
    text: str
    json: Any = None
    provider: str = ""
    model: str = ""
    task: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    images: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    cache_hit: bool = False
    request_id: str | None = None
    audio_url: str | None = None
    extra: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- paths / config (env-overridable for tests)
def _path(env: str, default: Path) -> Path:
    return Path(os.environ[env]) if os.environ.get(env) else default


def _yaml_path() -> Path:
    return _path("MODELS_YAML", Path(__file__).with_name("models.yaml"))


def _costs_log() -> Path:
    return _path("MODELS_COSTS_LOG", REPO / "results" / "costs.jsonl")


def _cache_dir() -> Path:
    return _path("MODELS_CACHE_DIR", REPO / "artifacts" / "cache" / "models")


def _costs_md() -> Path:
    return _path("MODELS_COSTS_MD", REPO / "COSTS.md")


_cfg_cache: dict[str, tuple[float, dict]] = {}


def config() -> dict:
    p = _yaml_path()
    m = p.stat().st_mtime
    hit = _cfg_cache.get(str(p))
    if hit and hit[0] == m:
        return hit[1]
    cfg = yaml.safe_load(p.read_text())
    _cfg_cache[str(p)] = (m, cfg)
    return cfg


def api_key(provider: str) -> str | None:
    """Read fresh at call time: process env first, then .env. Never logged."""
    if provider == "fake":
        return "fake"
    env = (config()["providers"].get(provider) or {}).get("env")
    if not env:
        return None
    v = os.environ.get(env)
    if not v and ENV_FILE.exists():
        v = dotenv_values(ENV_FILE).get(env)
    return v or None


def _forced_fake() -> bool:
    if os.environ.get("MODELS_FAKE", "").strip().lower() in ("1", "true", "yes"):
        return True
    return not any(api_key(p) for p in config()["providers"] if p != "fake")


def chain_for(task: str) -> list[dict]:
    t = config()["tasks"].get(task)
    if t is None:
        raise ModelError(f"unknown task {task!r}")
    steps = [{"provider": t["provider"], "model": t["model"]}] + list(t.get("fallback") or [])
    return [s for s in steps if s.get("provider") and s.get("model")]  # unset model => skipped


# --------------------------------------------------------------------------- budget
_NAME_TO_PROVIDER = {"runware": "runware", "anthropic": "anthropic", "gemini": "gemini", "elevenlabs": "elevenlabs"}


def caps() -> dict[str, float]:
    """USD caps parsed from the COSTS.md table. Non-USD rows (credits, free tier) have no cap."""
    out: dict[str, float] = {}
    p = _costs_md()
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        m = re.match(r"^\|\s*([^|]+?)\s*\|\s*([\d,\.]+)\s*USD\b", line)
        if m:
            prov = _NAME_TO_PROVIDER.get(m.group(1).strip().lower())
            if prov:
                out[prov] = float(m.group(2).replace(",", ""))
    return out


_lock = threading.Lock()
_spend_state: dict[str, tuple[int, dict[str, float]]] = {}  # log path -> (offset, totals)


def spend(provider: str) -> float:
    """Sum of cost_usd for `provider` in results/costs.jsonl (incremental read)."""
    p = _costs_log()
    with _lock:
        off, totals = _spend_state.get(str(p), (0, {}))
        if not p.exists():
            return 0.0
        size = p.stat().st_size
        if size < off:  # file was truncated or replaced
            off, totals = 0, {}
        with p.open("rb") as f:
            f.seek(off)
            chunk = f.read()
        end = chunk.rfind(b"\n") + 1  # only whole lines
        for line in chunk[:end].splitlines():
            try:
                r = json.loads(line)
                totals[r["provider"]] = totals.get(r["provider"], 0.0) + float(r.get("cost_usd") or 0)
            except (ValueError, KeyError, TypeError):
                continue
        _spend_state[str(p)] = (off + end, totals)
        return totals.get(provider, 0.0)


def _check_budget(provider: str) -> None:
    cap = caps().get(provider)
    if cap is not None and spend(provider) >= cap:
        raise BudgetExceeded(f"{provider} spend {spend(provider):.4f} USD reached cap {cap} USD")


# --------------------------------------------------------------------------- logging
_db_logger: Callable[[dict], None] | None = None


def set_db_logger(fn: Callable[[dict], None] | None) -> None:
    """The SERVER registers a function that writes the same record to `model_calls`."""
    global _db_logger
    _db_logger = fn


def _log(res: Result) -> None:
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **{k: v for k, v in asdict(res).items() if k not in ("text", "json", "extra", "audio_url")}}
    p = _costs_log()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        line = (json.dumps(rec, separators=(",", ":")) + "\n").encode()
        with _lock, p.open("ab") as f:
            f.write(line)
    except OSError:  # a read-only costs log must not turn a paid call into an error
        pass
    if _db_logger:
        try:
            _db_logger(rec)
        except Exception:  # logging must never break a call
            pass


# --------------------------------------------------------------------------- normalization
def _sniff_mime(data: bytes, hint: str | None = None) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return hint or "image/png"


def _norm_image(x: Any) -> Image:
    import base64

    if isinstance(x, Image):
        return x
    data: bytes
    hint = None
    if isinstance(x, (bytes, bytearray)):
        data = bytes(x)
    elif isinstance(x, Path) or (isinstance(x, str) and not x.startswith(("data:", "http://", "https://"))):
        data = Path(x).read_bytes()
        hint = mimetypes.guess_type(str(x))[0]
    elif isinstance(x, str) and x.startswith("data:"):
        head, _, b64 = x.partition(",")
        data = base64.b64decode(b64)
        hint = head[5:].split(";")[0] or None
    elif isinstance(x, str):
        r = httpx.get(x, timeout=60, follow_redirects=True)
        r.raise_for_status()
        data, hint = r.content, r.headers.get("content-type", "").split(";")[0] or None
    else:
        raise TypeError(f"unsupported image input: {type(x)}")
    return Image(mime=_sniff_mime(data, hint), data=data, sha=hashlib.sha256(data).hexdigest())


def _norm_messages(messages: Any) -> list[dict]:
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    return [{"role": m["role"], "content": m["content"]} for m in messages]


def cache_key(provider: str, model: str, messages: list[dict], images: list[Image], schema: dict | None, params: dict) -> str:
    blob = json.dumps(
        {"provider": provider, "model": model, "messages": messages, "images": [i.sha for i in images], "schema": schema, "params": params},
        sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


# --------------------------------------------------------------------------- cost
def _cost(cfg: dict, provider: str, model: str, r: P.ProviderResponse) -> float:
    if r.cost_usd is not None:
        return float(r.cost_usd)
    price = (cfg.get("prices", {}).get(provider) or {}).get(model)
    if not price:
        return 0.0
    return (r.input_tokens * price.get("in", 0) + r.output_tokens * price.get("out", 0)) / 1_000_000


# --------------------------------------------------------------------------- call
def _with_backoff(fn: Callable[[], P.ProviderResponse]) -> P.ProviderResponse:
    for attempt in range(MAX_RETRIES + 1):
        try:
            return fn()
        except RateLimited as e:
            if attempt == MAX_RETRIES:
                raise
            delay = e.retry_after if e.retry_after is not None else min(MAX_DELAY_S, BASE_DELAY_S * 2**attempt) * (0.5 + random.random() / 2)
            _sleep(delay)
    raise AssertionError("unreachable")


def _validate(text: str, schema: dict) -> Any:
    import jsonschema

    obj = P.parse_json_text(text)
    try:
        jsonschema.validate(obj, schema)
    except jsonschema.ValidationError as e:
        raise ProviderError(f"output violates schema: {e.message[:200]}") from e
    return obj


def call(
    task: str,
    messages: Any,
    images: list | None = None,
    schema: dict | None = None,
    *,
    request_id: str | None = None,
    only: tuple[str, str] | None = None,
) -> Result:
    """`only=(provider, model)` pins one model and disables the fallback chain (model comparison, E-10)."""
    cfg = config()
    msgs = _norm_messages(messages)
    imgs = [_norm_image(i) for i in (images or [])]
    task_cfg = cfg["tasks"][task] if task in cfg["tasks"] else {}
    params = {k: task_cfg[k] for k in ("max_tokens", "temperature", "extra_body") if task_cfg.get(k) is not None}
    if task == "tts":
        params["kind"] = "audio"

    steps = [{"provider": "fake", "model": "fake-1"}] if _forced_fake() else \
        ([{"provider": only[0], "model": only[1]}] if only else chain_for(task))
    last: Exception | None = None
    tried = 0
    for step in steps:
        prov, model = step["provider"], step["model"]
        key = api_key(prov)
        if not key:
            continue  # missing key: skipped
        tried += 1
        pcfg = {**cfg["providers"].get(prov, {}), "name": prov}
        ck = cache_key(prov, model, msgs, imgs, schema, params)
        cpath = _cache_dir() / f"{ck}.json"
        if cpath.exists():
            try:
                c = json.loads(cpath.read_text())
                res = Result(
                    text=c["text"], json=c.get("json"), provider=prov, model=model, task=task,
                    input_tokens=c.get("input_tokens", 0), output_tokens=c.get("output_tokens", 0), images=len(imgs),
                    cost_usd=0.0, latency_ms=0, cache_hit=True, request_id=request_id,
                    audio_url=c.get("audio_url"), extra=c.get("extra", {}),
                )
                _log(res)
                return res
            except (ValueError, KeyError):
                pass  # corrupt cache entry: ignore
        try:
            _check_budget(prov)
            t0 = time.perf_counter()
            _tok = P.STREAM_NOW.set(P.DELTA_SINK.get() if task in P.STREAM_TASKS else None)
            try:
                pr = _with_backoff(lambda: P.ADAPTERS[prov](pcfg, model, msgs, imgs, schema, params, key))
            finally:
                P.STREAM_NOW.reset(_tok)
            latency = int((time.perf_counter() - t0) * 1000)
            parsed = _validate(pr.text, schema) if schema is not None else None
        except ProviderError as e:  # includes BudgetExceeded, RateLimited, bad JSON
            last = e
            continue
        except httpx.HTTPError as e:  # network failure: next provider
            last = ProviderError(f"{prov} network error: {type(e).__name__}")
            continue
        res = Result(
            text=pr.text, json=parsed, provider=prov, model=model, task=task,
            input_tokens=pr.input_tokens, output_tokens=pr.output_tokens, images=len(imgs),
            cost_usd=_cost(cfg, prov, model, pr), latency_ms=latency, cache_hit=False, request_id=request_id,
            audio_url=pr.extra.get("audio_url"), extra={k: v for k, v in pr.extra.items() if k != "audio_url"},
        )
        _log(res)
        try:
            cpath.parent.mkdir(parents=True, exist_ok=True)
            tmp = cpath.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps({
                "text": res.text, "json": res.json, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
                "audio_url": res.audio_url, "extra": res.extra,
            }))
            tmp.replace(cpath)
        except OSError:
            pass
        return res
    if last is not None:
        raise last
    raise NoProviderAvailable(f"no usable provider for task {task!r} (missing keys or empty chain)")
