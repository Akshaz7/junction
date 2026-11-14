#!/usr/bin/env python3
"""Check deployed judging readiness; never read .env or delete chats/documents.

Usage: .venv/bin/python scripts/judge_ready.py [--dry-run]
Live mode creates ONE `judge-ready <timestamp>` chat and one pairing code.
Only that pairing code is deleted, and only if OpenAPI advertises its DELETE.
Run separately from e2e/stress jobs: the 30-request burst consumes shared quota.
Downloads stay in memory. Dry-run uses no network, git, or optional packages.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import subprocess
import time
from typing import NamedTuple
from urllib.parse import quote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "https://hologram-khaki.vercel.app"
DEFAULT_ORIGIN = "https://obviously-present-piglet.eur-1.aiven.app"
AC20 = "ifc_bench__ac20-arc"
CUBI = "cubicasa5k__colorful-11397"
QUESTIONS = (
    ("ground-floor doors", AC20, "How many doors are on the ground floor?", 18),
    ("floors", AC20, "How many floors are there?", 5),
    ("raster windows", CUBI, "How many windows are there?", None),
)
PLAN = (
    ("health", "GET /api/health: ok, db, caps_loaded true; servable_docs >= 370; bench_files >= 1"),
    ("build", "build_rev vs git rev-parse --short HEAD; mismatch warns"),
    ("benchmark", "GET /api/bench/latest: e-s200-*; abstentions = 0"),
    ("documents", f"GET /api/docs: {AC20} listed"),
    ("scene.json", f"GET /api/docs/{AC20}/files/scene.json; validate JSON, print bytes"),
    ("model.glb", f"GET /api/docs/{AC20}/files/scene.glb (contract GLB filename); print bytes"),
    ("scene.usdz", f"GET /api/docs/{AC20}/files/scene.usdz; print bytes"),
    ("page-2.png", f"GET /api/docs/{AC20}/pages/2/image; print bytes"),
    ("new chat", 'POST /api/chats: title "judge-ready <timestamp>"; print id; retain chat'),
    *((name, f'POST messages: {doc}: "{question}"; value={expected if expected is not None else "positive integer"}; '
        "boxes == value, inline [n], server and wall latency") for name, doc, question, expected in QUESTIONS),
    ("WebSocket", "Aiven wss /ws: scene.join for new chat + AC20 -> matching scene.state; no edits"),
    ("rate headroom", "30 quick GET /api/chats/<new id>/scene-state must all return 200 (non-exempt route)"),
    ("pairing", "POST /api/pair -> code; DELETE only created pair if OpenAPI has route, otherwise print code"),
)


class CheckError(Exception):
    """Safe diagnostic text; response bodies and arbitrary exceptions aren't printed."""


class Result(NamedTuple):
    name: str
    status: str
    detail: str


def require(condition, message):
    if not condition:
        raise CheckError(message)


def positive_int(value):
    return type(value) is int and value > 0


def object_json(response):
    value = response.json()
    require(isinstance(value, dict), "expected a JSON object")
    return value


def local_revision():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True,
            stderr=subprocess.DEVNULL, timeout=5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        raise CheckError("cannot read local git HEAD") from None


def validate_answer(value, expected, doc_id):
    answer = value.get("answer", {})
    require(isinstance(answer, dict), "missing answer object")
    count = answer.get("value")
    require(positive_int(count), "answer value must be a positive integer")
    require(expected is None or count == expected, f"value={count}; expected={expected}")
    require(answer.get("abstained") is False, "answer abstained")
    require(doc_id in value.get("doc_ids", []), "answer used the wrong document")
    boxes = value.get("evidence", {}).get("boxes")
    require(isinstance(boxes, list), "missing evidence boxes")
    require(len(boxes) == count, f"value={count}; boxes={len(boxes)}; boxes must equal value")
    for box in boxes:
        require(isinstance(box, dict) and isinstance(box.get("bbox_px"), list)
                and len(box["bbox_px"]) == 4
                and all(type(n) in (int, float) and math.isfinite(n) for n in box["bbox_px"])
                and box["bbox_px"][2] > box["bbox_px"][0]
                and box["bbox_px"][3] > box["bbox_px"][1], "invalid evidence box")
    text = answer.get("text_md")
    require(isinstance(text, str) and re.search(r"\[[1-9]\d*\]", text), "missing inline [n] citation")
    latency = value.get("latency_ms")
    require(type(latency) in (int, float) and math.isfinite(latency) and latency >= 0,
            "missing/invalid server latency_ms")
    return f"value={count}; boxes={len(boxes)}; inline citation; server={latency:.0f} ms"


def streamed_answer(response):
    require(response.headers.get("content-type", "").startswith("text/event-stream"), "expected SSE stream")
    event, data, answers = "", [], []

    def dispatch():
        if event == "error":
            raise CheckError("SSE reported an engine error")
        if event == "answer":
            value = json.loads("\n".join(data))
            require(isinstance(value, dict), "invalid SSE answer")
            answers.append(value)

    for line in response.iter_lines():
        if not line:
            dispatch()
            event, data = "", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
    if event or data:
        dispatch()
    require(len(answers) == 1, "expected exactly one terminal SSE answer")
    return answers[0]


def websocket_join(url, chat_id, timeout):
    from websockets.sync.client import connect

    started = time.monotonic()
    with connect(url, open_timeout=timeout, close_timeout=2, max_size=2**20) as ws:
        ws.send(json.dumps({"type": "scene.join", "chat_id": chat_id, "doc_id": AC20}))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "scene.join response timed out")
            msg = json.loads(ws.recv(timeout=remaining))
            if not isinstance(msg, dict) or msg.get("type") != "scene.state":
                continue
            if msg.get("doc_id") != AC20 or msg.get("chat_id") != chat_id:
                continue
            require(isinstance(msg.get("hidden"), list) and isinstance(msg.get("highlighted"), list)
                    and isinstance(msg.get("labels"), dict), "invalid scene.state payload")
            return f"wss connected; scene.join -> scene.state in {(time.monotonic() - started) * 1000:.0f} ms"


class Readiness:
    def __init__(self, client, base, origin, timeout=30, revision=local_revision, ws_join=websocket_join):
        self.client, self.base, self.origin = client, base.rstrip("/"), origin.rstrip("/")
        self.timeout, self.revision, self.ws_join = timeout, revision, ws_join
        self.results = []
        self.health = None
        self.chat_id = None

    def check(self, name, action):
        try:
            detail = action()
            status = "WARN" if name == "build" and detail.startswith("mismatch:") else "PASS"
            self.results.append(Result(name, status, detail))
        except CheckError as exc:
            self.results.append(Result(name, "FAIL", str(exc)))
        except Exception as exc:
            self.results.append(Result(name, "FAIL", f"request or response error ({type(exc).__name__})"))
        row = self.results[-1]
        print(f"{row.status:<4} | {row.name:<20} | {row.detail}", flush=True)

    def request(self, method, path, **kwargs):
        response = self.client.request(method, self.base + path, **kwargs)
        require(200 <= response.status_code < 300, f"HTTP {response.status_code}: {method} {path}")
        return response

    def check_health(self):
        h = self.health = object_json(self.request("GET", "/api/health"))
        bad = [f"{key} must be true" for key in ("ok", "db", "caps_loaded") if h.get(key) is not True]
        for key, minimum in (("servable_docs", 370), ("bench_files", 1)):
            if type(h.get(key)) is not int or h[key] < minimum:
                bad.append(f"{key} must be >= {minimum}")
        require(not bad, "; ".join(bad))
        return f"ok; db; caps loaded; servable_docs={h['servable_docs']}; bench_files={h['bench_files']}"

    def check_build(self):
        require(self.health is not None, "health unavailable; cannot compare build")
        remote, local = self.health.get("build_rev"), self.revision()
        require(isinstance(remote, str) and re.fullmatch(r"[a-fA-F0-9]{7,40}", remote), "build_rev missing/invalid")
        return f"build_rev={remote}" if remote == local else f"mismatch: deployed={remote}; local={local} (may be behind)"

    def check_bench(self):
        b = object_json(self.request("GET", "/api/bench/latest"))
        require(isinstance(b.get("tag"), str) and b["tag"].startswith("e-s200-"), "expected e-s200-* benchmark")
        require(type(b.get("abstentions")) is int and b["abstentions"] == 0, "benchmark abstentions must be 0")
        return f"{b['tag']}; abstentions=0"

    def check_docs(self):
        catalogue = object_json(self.request("GET", "/api/docs"))
        docs = [d for source in catalogue.get("sources", []) for d in source.get("docs", [])]
        require(any(d.get("doc_id") == AC20 for d in docs), "AC20 missing from catalogue")
        return f"AC20 listed; {len(docs)} docs"

    def download(self, name, path, signature=None):
        response = self.request("GET", path)
        data = response.content
        require(bool(data), f"{name} empty")
        if signature:
            require(data.startswith(signature), f"{name} has invalid file signature ({len(data)} bytes)")
        else:
            scene = object_json(response)
            require(scene.get("doc_id") == AC20 and isinstance(scene.get("items"), dict), "invalid AC20 scene manifest")
        return f"{len(data):,} bytes downloaded"

    def create_chat(self):
        title = "judge-ready " + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        chat = object_json(self.request("POST", "/api/chats", json={"title": title, "doc_ids": [AC20]}))
        cid = chat.get("id")
        require(isinstance(cid, str) and re.fullmatch(r"[a-zA-Z0-9-]{1,80}", cid), "missing/invalid new chat id")
        self.chat_id = cid
        return f"id={cid}; title={title}; retained for demo_reset cleanup"

    def need_chat(self):
        require(self.chat_id is not None, "new chat unavailable")
        return self.chat_id

    def ask(self, doc_id, question, expected):
        cid = self.need_chat()
        started = time.monotonic()
        with self.client.stream("POST", f"{self.base}/api/chats/{cid}/messages",
                                json={"content": question, "doc_ids": [doc_id]}) as response:
            require(response.status_code == 200, f"message HTTP {response.status_code}")
            answer = streamed_answer(response)
        elapsed = (time.monotonic() - started) * 1000
        # Keep measured latency visible even when answer validation fails.
        try:
            detail = validate_answer(answer, expected, doc_id)
        except CheckError as exc:
            raise CheckError(f"{exc}; wall={elapsed:.0f} ms; server={answer.get('latency_ms', 'missing')} ms") from None
        return f"{detail}; wall={elapsed:.0f} ms"

    def check_ws(self):
        cid = self.need_chat()
        url = "wss://" + urlsplit(self.origin).netloc + "/ws"
        return self.ws_join(url, cid, self.timeout)

    def check_rate(self):
        cid = self.need_chat()
        passed, failures = 0, {}
        started = time.monotonic()
        for _ in range(30):
            try:
                status = self.client.get(f"{self.base}/api/chats/{cid}/scene-state").status_code
            except Exception:
                status = "network error"
            if status == 200:
                passed += 1
            else:
                failures[status] = failures.get(status, 0) + 1
        elapsed = time.monotonic() - started
        require(passed == 30, f"{passed}/30 succeeded in {elapsed:.2f} s; failures={failures}")
        require(elapsed < 60, f"30/30 succeeded but took {elapsed:.2f} s; not a quick burst")
        return f"30/30 HTTP 200 in {elapsed:.2f} s (120/min quota)"

    def check_pair(self):
        pair = object_json(self.request("POST", "/api/pair", json={}))
        code = pair.get("code")
        require(isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9-]{4,64}", code), "pair creation returned no valid code")
        # Print immediately so cleanup remains possible if discovery/deletion fails.
        print(f"PAIR CODE: {code}", flush=True)
        response = self.client.get(self.origin + "/openapi.json")
        require(response.status_code == 200, f"OpenAPI discovery HTTP {response.status_code}; pair code retained")
        paths = object_json(response).get("paths", {})
        for template, field in (("/api/pair/{code}", "code"), ("/api/pair/{pair_id}", "id"), ("/api/pair/{id}", "id")):
            if "delete" in paths.get(template, {}):
                identifier = pair.get(field)
                require(isinstance(identifier, str) and identifier, "pair DELETE id unavailable; code retained")
                path = re.sub(r"\{[^}]+\}", quote(identifier, safe=""), template)
                self.request("DELETE", path)
                return "code created; deleted only the created pair"
        return f"code={code}; no advertised DELETE API; retained"

    def run(self):
        print("STATE | CHECK                | DETAIL", flush=True)
        for name, action in (("health", self.check_health), ("build", self.check_build),
                             ("benchmark", self.check_bench), ("documents", self.check_docs)):
            self.check(name, action)
        assets = (
            ("scene.json", f"/api/docs/{AC20}/files/scene.json", None),
            ("model.glb", f"/api/docs/{AC20}/files/scene.glb", b"glTF"),
            ("scene.usdz", f"/api/docs/{AC20}/files/scene.usdz", b"PK\x03\x04"),
            ("page-2.png", f"/api/docs/{AC20}/pages/2/image", b"\x89PNG\r\n\x1a\n"),
        )
        for name, path, signature in assets:
            self.check(name, lambda n=name, p=path, s=signature: self.download(n, p, s))
        self.check("new chat", self.create_chat)
        for name, doc_id, question, expected in QUESTIONS:
            self.check(name, lambda d=doc_id, q=question, e=expected: self.ask(d, q, e))
        self.check("WebSocket", self.check_ws)
        self.check("rate headroom", self.check_rate)
        self.check("pairing", self.check_pair)
        failures = sum(row.status == "FAIL" for row in self.results)
        print(f"NOT READY: {failures} failures" if failures else "JUDGE READY", flush=True)
        return int(failures > 0)


def https_origin(value):
    parts = urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.path not in ("", "/") or parts.query or parts.fragment):
        raise argparse.ArgumentTypeError("expected an HTTPS origin without credentials/path/query")
    return value.rstrip("/")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", type=https_origin, default=DEFAULT_BASE)
    parser.add_argument("--aiven-origin", type=https_origin, default=DEFAULT_ORIGIN)
    parser.add_argument("--timeout", type=float, default=30, help="seconds per HTTP/WS operation (default 30)")
    parser.add_argument("--dry-run", action="store_true", help="list checks without network or writes")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    if args.dry_run:
        print(f"DRY RUN: {args.base_url}/api; WebSocket {args.aiven_origin.replace('https://', 'wss://')}/ws")
        print("STATE | CHECK                | DETAIL")
        for name, detail in PLAN:
            print(f"PLAN | {name:<20} | {detail}")
        print("DRY RUN ONLY: no network or writes; readiness not assessed")
        return 0
    import httpx

    with httpx.Client(timeout=args.timeout, follow_redirects=True,
                      headers={"User-Agent": "hologram-judge-ready/1"}) as client:
        return Readiness(client, args.base_url, args.aiven_origin, args.timeout).run()


if __name__ == "__main__":
    raise SystemExit(main())
