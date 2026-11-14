"""Watch loop (E-17): Context.dev monitors on the rule source URLs.

API (docs.context.dev): base https://api.context.dev/v1, `Authorization: Bearer <key>`.
  POST /monitors  {name, target:{type:"page",url}, change_detection:{type:"exact"}, schedule:{type:"interval",
                   frequency, unit}, webhook:{url, events, retry}}  -> {id, webhook:{secret}}
  GET /monitors, PATCH /monitors/{id}.
Webhooks carry `X-Context-Signature: t=<unix>,v1=<hex>` = HMAC-SHA256(secret, f"{t}.{rawBody}"), plus X-Context-Id
and X-Context-Event. Payload {event, id, created_at, data:{change:{title, summary, url, monitor_id, ...}}}.
Never log keys or secrets. Secrets live in artifacts/watch/secrets.json (git-ignored); results/watch/monitors.json
holds ids only.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

from engine.rules import load_rules

REPO = Path(__file__).resolve().parent.parent
API = "https://api.context.dev/v1"
MONITOR_PREFIX = "Hologram rule: "
TOLERANCE_S = 300


def api_key() -> str | None:
    return os.environ.get("CONTEXT_DEV_API_KEY") or dotenv_values(REPO / ".env").get("CONTEXT_DEV_API_KEY") or None


def rule_sources() -> dict[str, list[str]]:
    """url -> rule ids that cite it (the `url` field of every rule)."""
    out: dict[str, list[str]] = {}
    for r in load_rules():
        if r.get("url"):
            out.setdefault(r["url"], []).append(r["id"])
    return out


def monitors_file() -> Path:
    return Path(os.environ.get("RESULTS_DIR") or REPO / "results") / "watch" / "monitors.json"


def secrets_file() -> Path:
    return Path(os.environ.get("ARTIFACTS_DIR") or REPO / "artifacts") / "watch" / "secrets.json"


def _load(p: Path, default):
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return default


def webhook_secret(monitor_id: str | None = None) -> str | None:
    """Env override WATCH_WEBHOOK_SECRET, else the per-monitor secret saved at creation."""
    if os.environ.get("WATCH_WEBHOOK_SECRET"):
        return os.environ["WATCH_WEBHOOK_SECRET"]
    s = _load(secrets_file(), {})
    return s.get(monitor_id) if monitor_id else None


def verify_signature(raw: bytes, header: str, secret: str, now: float | None = None) -> bool:
    if not secret or not header:
        return False
    parts = {}
    for p in header.split(","):
        k, _, v = p.strip().partition("=")
        if not k or k in parts:
            return False
        parts[k] = v
    t, v1 = parts.get("t", ""), parts.get("v1", "")
    if not t.isdigit() or len(v1) != 64:
        return False
    if abs((now if now is not None else time.time()) - int(t)) > TOLERANCE_S:
        return False
    want = hmac.new(secret.encode(), t.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, v1.lower())


def sign(raw: bytes, secret: str, t: int | None = None) -> str:
    t = int(time.time()) if t is None else t
    return f"t={t},v1=" + hmac.new(secret.encode(), str(t).encode() + b"." + raw, hashlib.sha256).hexdigest()


def sync_monitors(webhook_url: str | None = None, client: httpx.Client | None = None) -> dict:
    """Create one monitor per rule URL, reusing existing ones by name or target URL. Idempotent.
    Returns {status, monitors:[{url, rule_ids, monitor_id, created}], error?}. Never raises."""
    key = api_key()
    sources = rule_sources()
    if not key:
        return {"status": "no_key", "monitors": [], "error": "CONTEXT_DEV_API_KEY is not set"}
    own = client is None
    c = client or httpx.Client(base_url=API, timeout=30)
    headers = {"Authorization": f"Bearer {key}"}
    rows, secrets = [], _load(secrets_file(), {})
    try:
        existing = c.get("/monitors", headers=headers, params={"limit": 100})
        if existing.status_code >= 400:
            return {"status": "api_error", "monitors": [], "http_status": existing.status_code,
                    "error": existing.text[:300]}
        body = existing.json()
        listed = body if isinstance(body, list) else (body.get("data") or body.get("monitors") or [])
        for url, rule_ids in sources.items():
            name = MONITOR_PREFIX + url.split("//", 1)[-1][:150]
            found = next((m for m in listed if m.get("name") == name or (m.get("target") or {}).get("url") == url), None)
            created = False
            if found is None:
                req = {"mode": "web", "name": name, "tags": ["hologram", "rule-source"],
                       "target": {"type": "page", "url": url}, "change_detection": {"type": "exact"},
                       "schedule": {"type": "interval", "frequency": 6, "unit": "hours"}}
                if webhook_url:
                    req["webhook"] = {"url": webhook_url, "events": ["change.detected"], "retry": {}}
                r = c.post("/monitors", headers=headers, json=req)
                if r.status_code >= 400:
                    rows.append({"url": url, "rule_ids": rule_ids, "monitor_id": None, "created": False,
                                 "error": f"HTTP {r.status_code}: {r.text[:200]}"})
                    continue
                found, created = r.json(), True
            elif webhook_url and (found.get("webhook") or {}).get("url") != webhook_url:
                r = c.patch(f"/monitors/{found['id']}", headers=headers,
                            json={"webhook": {"url": webhook_url, "events": ["change.detected"], "retry": {}}})
                if r.status_code < 400:
                    found = r.json()
            sec = (found.get("webhook") or {}).get("secret")
            if sec:
                secrets[found["id"]] = sec
            rows.append({"url": url, "rule_ids": rule_ids, "monitor_id": found["id"], "created": created,
                         "webhook_url": (found.get("webhook") or {}).get("url")})
    except httpx.HTTPError as e:
        return {"status": "unreachable", "monitors": rows, "error": type(e).__name__}
    finally:
        if own:
            c.close()
    if secrets:
        secrets_file().parent.mkdir(parents=True, exist_ok=True)
        secrets_file().write_text(json.dumps(secrets))
        os.chmod(secrets_file(), 0o600)
    out = {"status": "ok" if rows and all(r.get("monitor_id") for r in rows) else "partial", "monitors": rows}
    monitors_file().parent.mkdir(parents=True, exist_ok=True)
    monitors_file().write_text(json.dumps(out, indent=2) + "\n")
    return out


def rule_ids_for(url: str | None, monitor_id: str | None = None) -> list[str]:
    ids = rule_sources().get(url or "", [])
    if not ids and monitor_id:
        for m in _load(monitors_file(), {}).get("monitors", []):
            if m.get("monitor_id") == monitor_id:
                return m.get("rule_ids", [])
    return ids


def parse_event(payload: dict) -> dict | None:
    """Normalise a change.detected payload to {event_id, monitor_id, url, title, summary, importance, rule_ids}."""
    if not isinstance(payload, dict) or payload.get("event") != "change.detected":
        return None
    ch = (payload.get("data") or {}).get("change")
    if not isinstance(ch, dict):
        return None
    url, mon = ch.get("url"), ch.get("monitor_id")
    return {"event_id": str(payload.get("id") or ""), "monitor_id": mon, "url": url,
            "title": str(ch.get("title") or "A rule source changed")[:200],
            "summary": str(ch.get("summary") or "")[:500], "importance": ch.get("importance"),
            "rule_ids": rule_ids_for(url, mon), "detected_at": ch.get("detected_at") or payload.get("created_at")}


if __name__ == "__main__":
    base = os.environ.get("WATCH_WEBHOOK_URL")
    res = sync_monitors(base)
    print(json.dumps({k: v for k, v in res.items()}, indent=2))
