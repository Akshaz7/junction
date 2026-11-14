#!/usr/bin/env python3
"""Check every key in .env with one small real call. Never prints a key.

Prints OK / MISSING / FAILED (or PRESENT where no cheap probe exists) per key
and writes results/keys.json. Stdlib only.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
OUT = ROOT / "results" / "keys.json"
TIMEOUT = 15

NAMES = [
    "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY", "RUNWARE_API_KEY",
    "FEATHERLESS_API_KEY", "HF_TOKEN", "ELEVENLABS_API_KEY", "MODAL_TOKEN_ID",
    "MODAL_TOKEN_SECRET", "CLOUDINARY_URL", "CONTEXT_DEV_API_KEY", "DATABASE_URL",
    "AIVEN_TOKEN", "AIVEN_PROJECT", "GOOGLE_APPLICATION_CREDENTIALS",
    "DRIVE_FOLDER_ID", "APPLE_TEAM_ID",
]


def read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        return env
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if v:
            env[k.strip()] = v
    return env


def http(url: str, headers: dict | None = None, data: bytes | None = None, method: str | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read(2000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(500).decode("utf-8", "replace")
    except Exception as e:  # network error
        return 0, type(e).__name__


def ok_if(code: int, detail: str = "") -> tuple[str, str]:
    if 200 <= code < 300:
        return "OK", ""
    return "FAILED", f"HTTP {code} {detail[:120]}".strip()


def scrub(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s and len(s) > 4:
            text = text.replace(s, "***")
    return text


def check(name: str, env: dict[str, str]) -> tuple[str, str]:
    v = env.get(name)
    if not v:
        return "MISSING", ""
    if name == "ANTHROPIC_API_KEY":
        c, b = http("https://api.anthropic.com/v1/models?limit=1",
                    {"x-api-key": v, "anthropic-version": "2023-06-01"})
        return ok_if(c, b)
    if name == "GEMINI_API_KEY":
        c, b = http("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
                    {"x-goog-api-key": v})
        return ok_if(c, b)
    if name == "NVIDIA_API_KEY":
        # The model list is public, so prove the key with a tiny authenticated call.
        c, b = http("https://api.nvcf.nvidia.com/v2/nvcf/functions",
                    {"Authorization": f"Bearer {v}", "Accept": "application/json"})
        if c in (401, 403):
            return "FAILED", f"HTTP {c}"
        if 200 <= c < 300:
            return "OK", ""
        return "PRESENT", f"probe inconclusive (HTTP {c})"
    if name == "RUNWARE_API_KEY":
        body = json.dumps([{"taskType": "authentication", "apiKey": v,
                            "taskUUID": str(uuid.uuid4())}]).encode()
        c, b = http("https://api.runware.ai/v1", {"Content-Type": "application/json"}, body, "POST")
        if 200 <= c < 300 and '"errors"' not in b:
            return "OK", ""
        return "FAILED", f"HTTP {c} {b[:120]}"
    if name == "FEATHERLESS_API_KEY":
        c, b = http("https://api.featherless.ai/v1/models?limit=1", {"Authorization": f"Bearer {v}"})
        return ok_if(c, b)
    if name == "HF_TOKEN":
        c, b = http("https://huggingface.co/api/whoami-v2", {"Authorization": f"Bearer {v}"})
        return ok_if(c, b)
    if name == "ELEVENLABS_API_KEY":
        c, b = http("https://api.elevenlabs.io/v1/models", {"xi-api-key": v})
        return ok_if(c, b)
    if name == "MODAL_TOKEN_ID":
        if not env.get("MODAL_TOKEN_SECRET"):
            return "FAILED", "MODAL_TOKEN_SECRET missing"
        modal = shutil.which("modal") or str(Path.home() / ".local/bin/modal")
        if not Path(modal).exists():
            return "PRESENT", "modal CLI not installed"
        e = dict(os.environ, MODAL_TOKEN_ID=v, MODAL_TOKEN_SECRET=env["MODAL_TOKEN_SECRET"])
        try:
            p = subprocess.run([modal, "app", "list", "--json"], env=e, capture_output=True,
                               text=True, timeout=40)
        except subprocess.TimeoutExpired:
            return "FAILED", "modal app list timed out"
        return ("OK", "") if p.returncode == 0 else ("FAILED", p.stderr.strip()[-120:])
    if name == "MODAL_TOKEN_SECRET":
        return "PRESENT", "checked with MODAL_TOKEN_ID"
    if name == "CLOUDINARY_URL":
        u = urllib.parse.urlparse(v)
        if u.scheme != "cloudinary" or not u.hostname:
            return "FAILED", "expected cloudinary://key:secret@cloud"
        auth = base64.b64encode(f"{u.username}:{u.password}".encode()).decode()
        c, b = http(f"https://api.cloudinary.com/v1_1/{u.hostname}/ping",
                    {"Authorization": f"Basic {auth}"})
        return ok_if(c, b)
    if name == "CONTEXT_DEV_API_KEY":
        return "PRESENT", "no probe yet (E-17 reads their API docs)"
    if name == "DATABASE_URL":
        psql = shutil.which("psql")
        if not psql:
            return "PRESENT", "psql not installed; S-05 verifies"
        try:
            p = subprocess.run([psql, v, "-tAc", "select 1"], capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired:
            return "FAILED", "psql timed out"
        return ("OK", "") if p.returncode == 0 else ("FAILED", p.stderr.strip()[-120:])
    if name == "AIVEN_TOKEN":
        c, b = http("https://api.aiven.io/v1/me", {"Authorization": f"aivenv1 {v}"})
        return ok_if(c, b)
    if name == "GOOGLE_APPLICATION_CREDENTIALS":
        p = Path(v).expanduser()
        if not p.exists():
            return "FAILED", "file not found"
        try:
            d = json.loads(p.read_text())
        except Exception:
            return "FAILED", "not valid JSON"
        return ("OK", "") if d.get("client_email") and d.get("private_key") else ("FAILED", "no client_email/private_key")
    return "PRESENT", ""


def main() -> int:
    env = read_env()
    secrets = list(env.values())
    results = {}
    for n in NAMES:
        try:
            status, note = check(n, env)
        except Exception as e:
            status, note = "FAILED", type(e).__name__
        results[n] = {"status": status, "note": scrub(note, secrets)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"checked": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "keys": results}, indent=2))
    w = max(len(n) for n in NAMES)
    for n, r in results.items():
        print(f"{n:<{w}}  {r['status']:<8} {r['note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
