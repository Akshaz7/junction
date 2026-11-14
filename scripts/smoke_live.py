#!/usr/bin/env python3
"""Exercise the live API with only Python's standard library and no client keys.

Usage: python3 scripts/smoke_live.py [base_url] [--dry-run]
Every HTTP request is spaced by >=2.5 s (at most 24/min, including writes).
The real run takes several minutes. It creates a labelled demo PDF, a chat,
a skill and a disabled automation; only skills/automations have delete APIs.
Watch sync is idempotent but may provision the server's configured monitors.
Response bodies and exception messages are deliberately excluded from reports.
"""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import ssl
import struct
import time
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import uuid
import wave


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "https://hologram-khaki.vercel.app"
PROMPT = "How many windows are there?"
# The router paths are kept verbatim, so dry-run can check route coverage via AST
# without importing the application, loading .env, or requiring API dependencies.
PLAN = [
    ("GET", "/api/health", "health; database must be ready"),
    ("GET", "/api/docs", "document catalogue; choose a real demo document"),
    ("GET", "/api/folders", "folder tree"),
    ("GET", "/api/docs/{doc_id}", "document detail"),
    ("GET", "/api/docs/{doc_id}/source", "source bytes or documented not_built"),
    ("GET", "/api/docs/{doc_id}/pages/{n}/image", "PNG signature or not_built"),
    ("GET", "/api/docs/{doc_id}/pages/{n}.png", "PNG alias, including older revisions"),
    ("GET", "/api/docs/{doc_id}/planmap/{n}", "plan map or not_built"),
    ("GET", "/api/docs/{doc_id}/scene", "scene manifest or not_built"),
    ("GET", "/api/docs/{doc_id}/files/{name}", "scene.glb, scene.usdz, scene.json, elements.json, page-1.thumb.png"),
    ("GET", "/api/docs/{doc_id}/ingest", "ingestion status"),
    ("POST", "/api/upload", "multipart PDF labelled generated for demo"),
    ("GET", "/api/chats", "chat list"),
    ("POST", "/api/chats", "create smoke- chat"),
    ("GET", "/api/chats/{chat_id}", "chat and messages; also refetch after SSE"),
    ("GET", "/api/chats/{chat_id}/scene-state", "per-chat edit state"),
    ("POST", "/api/chats/{chat_id}/messages", "SSE status, trace and terminal answer; verify saved message"),
    ("GET", "/api/changes", "change feed"),
    ("POST", "/api/changes/refresh", "refresh change feed"),
    ("GET", "/api/changes/{change_id}", "real comparison, including ?page=N; 404 probe if feed empty"),
    ("GET", "/api/skills", "saved prompts"),
    ("POST", "/api/skills", "create smoke- skill"),
    ("POST", "/api/skills/{skill_id}/run", "full answer object"),
    ("DELETE", "/api/skills/{skill_id}", "delete the created skill; verify absence"),
    ("GET", "/api/automations", "automation list"),
    ("POST", "/api/automations", "create smoke- automation, disabled"),
    ("GET", "/api/automations/{automation_id}", "automation detail"),
    ("PATCH", "/api/automations/{automation_id}", "update created automation, keep disabled"),
    ("POST", "/api/automations/{automation_id}/run", "successful report with full answer"),
    ("GET", "/api/automations/{automation_id}/report.md", "Markdown report"),
    ("GET", "/api/automations/{automation_id}/report.pdf", "PDF signature"),
    ("DELETE", "/api/automations/{automation_id}", "delete created automation; verify 404"),
    ("POST", "/api/findings/run", "rule findings for selected doc"),
    ("GET", "/api/findings", "findings filtered by doc"),
    ("POST", "/api/advise", "at most three sourced cards"),
    ("GET", "/api/docs/{doc_id}/items/{item_id:path}", "linked item; 404 probe if no indexed item"),
    ("GET", "/api/docs/{doc_id}/tags/{tag:path}", "linked tag; 404 probe if no tag"),
    ("GET", "/api/bench", "benchmark summaries"),
    ("GET", "/api/bench/latest", "latest summary or documented no_bench"),
    ("GET", "/api/costs", "cost aggregates"),
    ("POST", "/api/tts", "MPEG audio or device fallback"),
    ("POST", "/api/speech-intent", "generated silent WAV: intent or device fallback"),
    ("GET", "/api/watch/monitors", "monitor list and rule URLs"),
    ("POST", "/api/watch/sync", "idempotent sync or explicit no_key fallback"),
    ("POST", "/api/watch/webhook", "unsigned request must be rejected (401 or unconfigured 503)"),
    ("WS", "/ws", "connect, send JSON ping, require JSON pong"),
]


def coverage() -> list[str]:
    """Fail dry-run if a new application route has no smoke operation."""
    discovered = set()
    for path in (ROOT / "server").glob("*.py"):
        tree = ast.parse(path.read_text())
        prefix = ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "APIRouter":
                prefix = next((k.value.value for k in node.keywords if k.arg == "prefix"), "")
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and dec.func.attr in {"get", "post", "patch", "put", "delete", "websocket"}
                        and dec.args and isinstance(dec.args[0], ast.Constant)):
                    verb = "WS" if dec.func.attr == "websocket" else dec.func.attr.upper()
                    discovered.add((verb, prefix + dec.args[0].value))
    planned = {(m, p) for m, p, _ in PLAN}
    return [f"Uncovered route: {m} {p}" for m, p in sorted(discovered - planned)] + [
        f"Route no longer exists: {m} {p}" for m, p in sorted(planned - discovered)]


class ShapeError(Exception):
    """A static local validation message, safe to include in reports."""


def require(ok, message):
    if not ok:
        raise ShapeError(message)


def fields(value, **expected):
    require(isinstance(value, dict), "expected JSON object")
    for key, kind in expected.items():
        require(key in value and isinstance(value[key], kind), f"missing/invalid field: {key}")
    return value


def answer(value):
    fields(value, answer_id=str, question=str, doc_ids=list, answer=dict,
           citations=list, evidence=dict, trace=list, route=str, cost=dict, latency_ms=(int, float))
    fields(value["answer"], text_md=str, confidence=(int, float), abstained=bool)
    require("value" in value["answer"] and "unit" in value["answer"], "missing answer value/unit")
    require(0 <= value["answer"]["confidence"] <= 1, "invalid answer confidence")
    require(value["route"] in {"index", "planmap", "vlm", "hybrid"}, "invalid answer route")
    fields(value["evidence"], boxes=list, scene=dict)
    fields(value["evidence"]["scene"], doc_id=str, highlight_item_ids=list)
    fields(value["cost"], usd_total=(int, float), calls=list)
    require(not any(isinstance(t, dict) and t.get("step") == "error" for t in value["trace"]),
            "answer contains engine error trace")
    return value


def doc(value):
    return fields(value, doc_id=str, source=str, title=str, kind=str, formats=list, pages=int, files=dict)


def feed(value):
    fields(value, changes=list, groups=list)
    require("checked_at" in value, "missing checked_at")
    for entry in value["changes"]:
        fields(entry, id=str, type=str, summary=dict, created_at=str)


def automation(value):
    return fields(value, id=str, name=str, prompt=str, doc_ids=list, enabled=bool,
                  interval_minutes=int, created_at=str)


def multipart(filename, mime, data):
    boundary = "smoke-" + uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n").encode()
    return body + data + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def demo_pdf():
    text = b"BT /F1 12 Tf 20 100 Td (generated for demo - smoke test) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 150] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length " + str(len(text)).encode() + b" >>\nstream\n" + text + b"\nendstream"]
    data, offsets = bytearray(b"%PDF-1.4\n"), [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def silent_wav():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 4000)
    return buffer.getvalue()


class WebSocket:
    """Small RFC 6455 client for one JSON ping/pong, including TLS and control frames."""
    def __init__(self, url, timeout):
        self.sock = None
        self.file = None
        self.url = url
        self.timeout = timeout

    def __enter__(self):
        parsed = urlsplit(self.url)
        sock = socket.create_connection((parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)), self.timeout)
        self.sock = sock
        try:
            if parsed.scheme == "https":
                self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
            self.file = self.sock.makefile("rb")
            key = base64.b64encode(os.urandom(16)).decode()
            path = urlunsplit(("", "", parsed.path, parsed.query, ""))
            self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {parsed.netloc}\r\nUpgrade: websocket\r\n"
                               f"Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n").encode())
            status = self.file.readline(8192).decode().split()
            require(len(status) >= 2 and status[1] == "101", "WebSocket upgrade did not return 101")
            headers = {}
            for _ in range(100):
                line = self.file.readline(8192)
                require(bool(line), "incomplete WebSocket handshake")
                if line == b"\r\n":
                    break
                key_name, _, value = line.decode().partition(":")
                headers[key_name.lower()] = value.strip()
            expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            require(headers.get("sec-websocket-accept") == expected, "invalid WebSocket accept")
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def send(self, payload, opcode=1):
        require(len(payload) < 126, "smoke WebSocket payload too large")
        mask = os.urandom(4)
        self.sock.sendall(bytes([0x80 | opcode, 0x80 | len(payload)]) + mask +
                          bytes(c ^ mask[i % 4] for i, c in enumerate(payload)))

    def exact(self, size):
        data = self.file.read(size)
        require(len(data) == size, "WebSocket closed early")
        return data

    def ping(self):
        self.send(b'{"type":"ping"}')
        deadline = time.monotonic() + self.timeout
        fragments = bytearray()
        while time.monotonic() < deadline:
            self.sock.settimeout(max(0.01, deadline - time.monotonic()))
            first, second = self.exact(2)
            require(not second & 0x80, "server WebSocket frame is masked")
            size = second & 0x7F
            if size == 126:
                size = struct.unpack("!H", self.exact(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self.exact(8))[0]
            require(size <= 1024 * 1024, "WebSocket frame exceeds smoke limit")
            payload, opcode = self.exact(size), first & 0x0F
            if opcode == 8:
                raise ValueError("WebSocket closed before pong")
            if opcode == 9:
                self.send(payload, 10)
            elif opcode in (0, 1):
                fragments.extend(payload)
                if first & 0x80:
                    event = json.loads(fragments)
                    fragments.clear()
                    if event.get("type") == "pong":
                        return
                    if event.get("type") == "ping":
                        self.send(b'{"type":"pong"}')
        raise ValueError("WebSocket pong timed out")

    def __exit__(self, *args):
        if self.file:
            self.file.close()
        if self.sock:
            self.sock.close()


class Smoke:
    def __init__(self, base, timeout, *, expected_build=None, report_path=None, s18=False):
        self.base, self.timeout = base.rstrip("/"), timeout
        self.expected_build, self.report_path, self.s18 = expected_build, report_path, s18
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.started = time.monotonic()
        self.rows, self.created, self.notes = [], [], [
            "Comparison is GET /api/changes/{change_id}; server has no separate /api/compare route.",
            "Documented not_built/no_bench/device/no_key fallbacks are shape-checked and noted, not full feature coverage.",
            "No chat or uploaded-document delete API exists; created IDs are recorded for the lead.",
            "HTTP 429 retries are recorded per check; latency includes Retry-After waits. A check passes only after its response validator passes.",
        ]
        self.next_request = 0.0
        self.context = {"n": "1", "name": "scene.glb"}
        self.seen = set()

    def pace(self):
        time.sleep(max(0.0, self.next_request - time.monotonic()))
        self.next_request = time.monotonic() + 2.5

    def call(self, method, route, check, *, body=None, upload=None, suffix="", allowed=(200,), fallback=None, sse=False):
        self.seen.add((method, route))
        path = route.replace(":path", "")
        try:
            path = path.format(**{k: quote(str(v), safe="") for k, v in self.context.items()}) + suffix
        except KeyError:
            self.rows.append({"method": method, "path": route, "status": None, "latency_ms": 0,
                              "ok": False, "check": "missing prerequisite from an earlier failed request"})
            return None
        self.pace()
        started = time.monotonic()
        row = {"method": method, "path": path, "status": None, "latency_ms": 0, "ok": False}
        value = None
        try:
            if method == "WS":
                with WebSocket(self.base + path, min(self.timeout, 15)) as ws:
                    row["status"] = 101
                    ws.ping()
                row.update(ok=True, check="WebSocket upgrade and JSON pong")
                return None
            headers = {"User-Agent": "hologram-smoke/1", "Accept": "*/*"}
            data = None
            if body is not None:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
            elif upload:
                data, headers["Content-Type"] = multipart(*upload)
            if sse:
                headers["Accept"] = "text/event-stream"
            for attempt in range(3):
                try:
                    response = urlopen(Request(self.base + path, data=data, headers=headers, method=method), timeout=self.timeout)
                except HTTPError as exc:
                    response = exc
                if response.status != 429 or attempt == 2:
                    break
                # The deployed quota is shared with browser/e2e traffic. A 429
                # rejects the operation before it runs, so writes are safe to retry.
                try:
                    delay = max(1.0, min(60.0, float(response.headers.get("Retry-After", "60"))))
                except ValueError:
                    delay = 60.0
                row.setdefault("retries", []).append({"status": 429, "wait_s": delay})
                response.close()
                print(f"WAIT {method} {path}: HTTP 429; retry in {delay:g}s", flush=True)
                time.sleep(delay)
                self.pace()
            with response:
                row["status"] = response.status
                row["content_type"] = response.headers.get("Content-Type", "")
                require(response.status in allowed, "unexpected HTTP status")
                if sse:
                    require("text/event-stream" in row["content_type"], "expected SSE content type")
                    value = self.events(response, time.monotonic())
                else:
                    raw = response.read(32 * 1024 * 1024 + 1)
                    require(len(raw) <= 32 * 1024 * 1024, "response exceeds 32 MiB smoke limit")
                    value = json.loads(raw) if "json" in row["content_type"] else raw
                result = check(value, row)
                row.update(ok=True, check=result if isinstance(result, str) else "shape OK")
                if fallback and isinstance(value, dict) and value.get("status") in fallback:
                    row["check"] = "documented fallback: " + value["status"]
            return value
        except Exception as exc:
            # Do not log raw responses/exception strings: upstream errors may contain secrets.
            row["check"] = str(exc) if isinstance(exc, ShapeError) else type(exc).__name__
            return value
        finally:
            row["latency_ms"] = round((time.monotonic() - started) * 1000, 1)
            row["result"] = "PASS" if row["ok"] else "FAIL"
            self.rows.append(row)
            print(f"{'PASS' if row['ok'] else 'FAIL'} {method} {path} {row['status']} {row['latency_ms']}ms {row['check']}", flush=True)

    def events(self, response, started):
        events, name, lines = [], "message", []
        while True:
            require(time.monotonic() - started < self.timeout, "SSE deadline exceeded")
            line = response.readline(1024 * 1024)
            if not line:
                break
            line = line.decode().rstrip("\r\n")
            if not line:
                if lines:
                    events.append((name, json.loads("\n".join(lines))))
                name, lines = "message", []
            elif line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                lines.append(line[5:].lstrip(" "))
        require(bool(events), "SSE stream has no events")
        require(not any(n == "error" for n, _ in events), "SSE contains error event")
        require(events[-1][0] == "answer", "SSE has no terminal answer")
        require(sum(n == "answer" for n, _ in events) == 1, "SSE has duplicate answers")
        require(any(n == "status" for n, _ in events), "SSE missing status")
        require(any(n == "trace" for n, _ in events), "SSE missing trace")
        for name, payload in events:
            if name == "status":
                fields(payload, text=str)
            elif name == "trace":
                fields(payload, step=str, detail=str, ms=(int, float))
        return answer(events[-1][1])

    def run(self):
        c = self.call
        def health(v, r):
            fields(v, ok=bool, db=bool)
            require(v["ok"] and v["db"], "health/database is not ready")
            r["build_rev"] = v.get("build_rev")
            if self.expected_build:
                require(v.get("build_rev") == self.expected_build, "unexpected deployed build revision")
        c("GET", "/api/health", health)
        if self.expected_build and not self.rows[-1]["ok"]:
            return
        catalogue = c("GET", "/api/docs", lambda v, r: fields(v, total=int, sources=list))
        docs = [d for source in (catalogue or {}).get("sources", []) for d in source.get("docs", [])]
        preferred = ["ifc_bench__ac20-arc", "cubicasa5k__colorful-11397", "ifc_models__ac20-arc"]
        selected = next((d for ident in preferred for d in docs if d.get("doc_id") == ident), None)
        selected = selected or next((d for d in docs if d.get("pages", 0) > 0 and d.get("source") != "uploads"), None)
        if selected:
            self.context["doc_id"] = selected["doc_id"]
        c("GET", "/api/folders", lambda v, r: fields(v, total=int, folders=list))
        c("GET", "/api/docs/{doc_id}", lambda v, r: doc(v))

        def artifact(v, r, kind):
            if r["status"] == 404:
                fields(v, status=str, detail=str)
                require(v["status"] == "not_built", "unexpected artifact error")
                return "documented fallback: not_built"
            if kind == "planmap":
                fields(v, doc_id=str, page=int, image=dict, scale=dict, items=list)
                fields(v["image"], w=int, h=int)
            elif kind == "scene":
                fields(v, doc_id=str, items=dict, units=str, up=str)
                require(v["units"] == "m" and v["up"] == "Y", "invalid scene coordinates")
            elif kind == "elements":
                require(isinstance(v, (list, dict)), "invalid elements index")
            elif kind == "png":
                require(isinstance(v, bytes) and v.startswith(b"\x89PNG\r\n\x1a\n"), "invalid PNG signature")
            elif kind == "glb":
                require(isinstance(v, bytes) and v.startswith(b"glTF"), "invalid GLB signature")
            elif kind == "usdz":
                require(isinstance(v, bytes) and v.startswith(b"PK\x03\x04"), "invalid USDZ signature")
            else:
                require(isinstance(v, bytes) and bool(v), "empty source file")
            return "shape/signature OK"

        c("GET", "/api/docs/{doc_id}/source", lambda v, r: artifact(v, r, "source"), allowed=(200, 404))
        c("GET", "/api/docs/{doc_id}/pages/{n}/image", lambda v, r: artifact(v, r, "png"), allowed=(200, 404))
        c("GET", "/api/docs/{doc_id}/pages/{n}.png", lambda v, r: artifact(v, r, "png"), allowed=(200, 404))
        planmap = c("GET", "/api/docs/{doc_id}/planmap/{n}", lambda v, r: artifact(v, r, "planmap"), allowed=(200, 404))
        scene = c("GET", "/api/docs/{doc_id}/scene", lambda v, r: artifact(v, r, "scene"), allowed=(200, 404))
        for filename, kind in [("scene.glb", "glb"), ("scene.usdz", "usdz"), ("scene.json", "scene"),
                               ("elements.json", "elements"), ("page-1.thumb.png", "png")]:
            self.context["name"] = filename
            c("GET", "/api/docs/{doc_id}/files/{name}", lambda v, r, k=kind: artifact(v, r, k), allowed=(200, 404))
        c("GET", "/api/docs/{doc_id}/ingest", lambda v, r: fields(v, status=str, stages=list, detail=str))
        title = "smoke-" + datetime.now(timezone.utc).strftime("%H%M%S") + "-" + uuid.uuid4().hex[:6]
        uploaded = c("POST", "/api/upload", lambda v, r: fields(v, doc_id=str, status=str, detail=str),
                     upload=(title + "-generated-for-demo.pdf", "application/pdf", demo_pdf()))
        if isinstance(uploaded, dict) and uploaded.get("doc_id"):
            self.created.append({"kind": "upload", "id": uploaded["doc_id"], "deleted": False, "reason": "no delete API"})
            original_doc = self.context.get("doc_id")
            self.context["doc_id"] = uploaded["doc_id"]
            c("GET", "/api/docs/{doc_id}", lambda v, r: doc(v))
            c("GET", "/api/docs/{doc_id}/ingest", lambda v, r: fields(v, status=str, stages=list, detail=str))
            if original_doc:
                self.context["doc_id"] = original_doc
            else:
                self.context.pop("doc_id", None)
        c("GET", "/api/chats", lambda v, r: fields(v, chats=list))
        chat = c("POST", "/api/chats", lambda v, r: fields(v, id=str, title=str, created_at=str),
                 body={"doc_ids": [self.context["doc_id"]] if "doc_id" in self.context else [], "title": title})
        if isinstance(chat, dict) and chat.get("id"):
            self.context["chat_id"] = chat["id"]
            self.created.append({"kind": "chat", "id": chat["id"], "deleted": False, "reason": "no delete API"})
        c("GET", "/api/chats/{chat_id}", lambda v, r: fields(v, id=str, messages=list))
        c("GET", "/api/chats/{chat_id}/scene-state", lambda v, r: fields(v, chat_id=str, states=list))
        streamed = c("POST", "/api/chats/{chat_id}/messages", lambda v, r: answer(v), body={"content": PROMPT}, sse=True)
        def persisted(v, r):
            fields(v, id=str, messages=list)
            require(any(m.get("role") == "user" and m.get("content") == PROMPT for m in v["messages"]), "user message not persisted")
            require(bool(streamed) and any((m.get("answer") or {}).get("answer_id") == streamed.get("answer_id")
                                          for m in v["messages"]), "SSE answer not persisted")
        c("GET", "/api/chats/{chat_id}", persisted)
        changes = c("GET", "/api/changes", lambda v, r: feed(v))
        refreshed = c("POST", "/api/changes/refresh", lambda v, r: feed(v))
        entries = (refreshed or changes or {}).get("changes", [])
        comparison = next((e for e in entries if e.get("type") == "new_version"), None)
        comparison = comparison or next((e for e in entries if e.get("type") == "rule_change"), None)
        self.context["change_id"] = comparison["id"] if comparison else str(uuid.uuid4())
        def compare(v, r):
            if comparison is None:
                fields(v, detail=str)
                return "empty feed: checked unknown comparison 404 only"
            if v.get("status") == "not_built":
                fields(v, changes=list)
                return "documented fallback: comparison not_built"
            if comparison.get("type") == "rule_change":
                fields(v, id=str, summary=dict)
            else:
                fields(v, id=str, changes=list, pages=list, v1=dict, v2=dict, page=int)
        diff = c("GET", "/api/changes/{change_id}", compare, allowed=(200,) if comparison else (404,))
        if isinstance(diff, dict) and isinstance(diff.get("page"), int):
            c("GET", "/api/changes/{change_id}", compare, suffix="?page=" + str(diff["page"]))
        try:
            c("GET", "/api/skills", lambda v, r: fields(v, skills=list))
            skill = c("POST", "/api/skills", lambda v, r: fields(v, id=str, name=str, prompt=str, builtin=bool),
                      body={"name": title, "prompt": PROMPT, "description": "generated for demo"}, allowed=(201,))
            if isinstance(skill, dict) and skill.get("id"):
                self.context["skill_id"] = skill["id"]
                self.created.append({"kind": "skill", "id": skill["id"], "deleted": False})
            def skill_result(v, r):
                fields(v, skill_id=str, prompt=str, answer=dict)
                answer(v["answer"])
            c("POST", "/api/skills/{skill_id}/run", skill_result,
              body={"doc_ids": [self.context["doc_id"]] if "doc_id" in self.context else []})
            c("GET", "/api/automations", lambda v, r: fields(v, automations=list))
            auto = c("POST", "/api/automations", lambda v, r: automation(v), allowed=(201,), body={
                "name": title, "prompt": PROMPT, "doc_ids": [self.context.get("doc_id", "smoke-missing")],
                "interval_minutes": 1440, "enabled": False})
            if isinstance(auto, dict) and auto.get("id"):
                self.context["automation_id"] = auto["id"]
                self.created.append({"kind": "automation", "id": auto["id"], "deleted": False})
            c("GET", "/api/automations/{automation_id}", lambda v, r: automation(v))
            def patched(v, r):
                automation(v)
                require(v["enabled"] is False and v["name"] == title + "-updated", "automation patch did not persist")
            c("PATCH", "/api/automations/{automation_id}", patched, body={"name": title + "-updated", "enabled": False})
            def report(v, r):
                automation(v)
                fields(v.get("last_report"), ok=bool, markdown=str, answer=dict)
                require(v["last_report"]["ok"], "automation report failed")
                answer(v["last_report"]["answer"])
            c("POST", "/api/automations/{automation_id}/run", report)
            def markdown(v, r):
                require("text/markdown" in r["content_type"] and isinstance(v, bytes) and v.startswith(b"# smoke-"), "invalid Markdown report")
            c("GET", "/api/automations/{automation_id}/report.md", markdown)
            def pdf(v, r):
                require("application/pdf" in r["content_type"] and isinstance(v, bytes) and v.startswith(b"%PDF-"), "invalid PDF report")
            c("GET", "/api/automations/{automation_id}/report.pdf", pdf)
        finally:
            self.cleanup()

        c("POST", "/api/findings/run", lambda v, r: fields(v, status=str, findings=list), body={"doc_id": self.context.get("doc_id", "smoke-missing")})
        c("GET", "/api/findings", lambda v, r: fields(v, findings=list), suffix="?doc_id=" + quote(self.context.get("doc_id", "smoke-missing"), safe=""))
        def advice(v, r):
            fields(v, cards=list)
            require(len(v["cards"]) <= 3, "too many advisor cards")
            for card in v["cards"]:
                fields(card, card_id=str, kind=str, title=str, body=str, item_ids=list, source=dict)
                fields(card["source"], type=str, ref=str, title=str, quote=str)
                require(all(card["source"][k] for k in ("type", "ref", "title", "quote")), "unsourced advisor card")
                require(len(card["title"]) <= 60 and len(card["body"]) <= 200 and len(card["source"]["quote"]) <= 200, "advisor card exceeds limits")
        c("POST", "/api/advise", advice, body={"doc_id": self.context.get("doc_id", "smoke-missing"), **({"chat_id": self.context["chat_id"]} if "chat_id" in self.context else {})})
        items = scene.get("items", {}) if isinstance(scene, dict) else {}
        tagged = next(((i, d["tag"]) for i, d in items.items() if isinstance(d, dict) and d.get("tag")), None)
        item_id = tagged[0] if tagged else next(iter(items), None)
        if not item_id and isinstance(planmap, dict):
            item_id = next((i.get("item_id") for i in planmap.get("items", []) if i.get("item_id")), None)
        self.context["item_id"] = item_id or "smoke-missing"
        self.context["tag"] = tagged[1] if tagged else "smoke-missing"
        def linked(v, r, exists):
            if not exists:
                fields(v, detail=str)
                return "no indexed item/tag: checked unknown reference 404 only"
            fields(v, item_id=str, props=dict, places=list)
            require(v["item_id"] == self.context["item_id"], "linked reference resolved to wrong item")
        c("GET", "/api/docs/{doc_id}/items/{item_id:path}", lambda v, r: linked(v, r, item_id), allowed=(200,) if item_id else (404,))
        c("GET", "/api/docs/{doc_id}/tags/{tag:path}", lambda v, r: linked(v, r, tagged), allowed=(200,) if tagged else (404,))
        c("GET", "/api/bench", lambda v, r: fields(v, benches=list))
        def bench(v, r):
            if r["status"] == 404:
                fields(v, status=str, detail=str)
                require(v["status"] == "no_bench", "unexpected bench error")
            else:
                fields(v, file=str, tag=str, data=dict)
        c("GET", "/api/bench/latest", bench, allowed=(200, 404), fallback={"no_bench"})
        c("GET", "/api/costs", lambda v, r: fields(v, total_usd=(int, float), calls=int, by_provider=dict, by_task=dict))
        def speech(v, r, tts=False):
            if isinstance(v, dict):
                if v.get("fallback") == "device":
                    fields(v, reason=str)
                    return "documented fallback: device"
                require(not tts, "expected TTS bytes or device fallback")
                fields(v, text=str, intent=str, provider=str)
                require(v["intent"] in {"ask", "visualise", "show_on_table", "changes", "other"}, "invalid speech intent")
            else:
                require(tts and "audio/mpeg" in r["content_type"] and bool(v), "invalid TTS audio")
        c("POST", "/api/tts", lambda v, r: speech(v, r, True), body={"text": "Smoke test."})
        c("POST", "/api/speech-intent", speech, upload=("smoke-generated-for-demo.wav", "audio/wav", silent_wav()))
        c("GET", "/api/watch/monitors", lambda v, r: fields(v, monitors=list, rule_urls=list))
        def sync(v, r):
            fields(v, status=str, monitors=list)
            require(v["status"] in {"ok", "no_key"}, "watch sync failed")
            return "documented fallback: no_key" if v["status"] == "no_key" else "shape OK"
        c("POST", "/api/watch/sync", sync)
        c("POST", "/api/watch/webhook", lambda v, r: fields(v, detail=str), body={"event": "smoke.unsigned"}, allowed=(401, 503))
        c("WS", "/ws", None)
        if self.s18:
            self.deployed_revisions_and_advisor()
        if self.expected_build:
            c("GET", "/api/health", health)

    def deployed_revisions_and_advisor(self):
        """S-18: exercise every shipped issue of the three real S-16 sheets."""
        original = dict(self.context)
        try:
            for series_id in ("vacation-rental--s400-9872c2", "vacation-rental--s401-9b69ee",
                              "vacation-rental--a100-8f1f68"):
                manifest = ROOT / "deploy" / "demo_artifacts" / "series" / (series_id + ".json")
                series = json.loads(manifest.read_text())
                versions = series["versions"]
                require(len(versions) > 1, "revision fixture has no older issues")
                for index, version in enumerate(versions, 1):
                    self.context["doc_id"] = version["doc_id"]
                    def detail(v, r):
                        doc(v)
                        require(v["doc_id"] == version["doc_id"], "wrong revision detail")
                        require(v.get("series_id") == series_id, "wrong revision series")
                        require(v.get("version_index") == index, "wrong revision index")
                        require(v.get("version_count") == len(versions), "wrong revision count")
                        require(v.get("date") == version["date"], "wrong revision date")
                        require(v.get("size") == version["size_bytes"], "wrong revision source size")
                        require([x.get("doc_id") for x in v.get("versions", [])] ==
                                [x["doc_id"] for x in versions], "incomplete revision history")
                        return f"S-16 {series_id} revision {index}/{len(versions)}"
                    self.call("GET", "/api/docs/{doc_id}", detail)
                    def source(v, r):
                        require(isinstance(v, bytes) and v.startswith(b"%PDF-"), "revision source is not PDF")
                        require(len(v) == version["size_bytes"], "revision source size mismatch")
                        r["bytes"] = len(v)
                        return "revision original PDF signature and size OK"
                    self.call("GET", "/api/docs/{doc_id}/source", source)
                    def png(v, r):
                        require(isinstance(v, bytes) and v.startswith(b"\x89PNG\r\n\x1a\n"), "revision page is not PNG")
                        r["bytes"] = len(v)
                        return "revision page PNG signature OK"
                    self.call("GET", "/api/docs/{doc_id}/pages/{n}.png", png)

            self.context["doc_id"] = "ifc_bench__ac20-arc"
            # Never reuse an existing chat: earlier hidden doors change advisor results.
            self.context.pop("chat_id", None)
            chat = self.call("POST", "/api/chats", lambda v, r: fields(v, id=str), body={
                "doc_ids": [self.context["doc_id"]], "title": "smoke-S18-front-door-generated-for-demo"})
            if isinstance(chat, dict) and chat.get("id"):
                self.context["chat_id"] = chat["id"]
                self.created.append({"kind": "chat", "id": chat["id"], "deleted": False, "reason": "no delete API"})
            def advisor(v, r):
                answer(v)
                fields(v, advisor_cards=list)
                cards = v["advisor_cards"]
                require(0 < len(cards) <= 3, "front-door edit has no advisor cards or too many")
                for card in cards:
                    fields(card, source=dict)
                    fields(card["source"], type=str, ref=str, title=str, quote=str)
                    require(all(card["source"].values()), "unsourced front-door advisor card")
                relevant = [card for card in cards if "848/2017" in json.dumps(card, ensure_ascii=False)
                            and re.search(r"§\s*33|33\s*§", json.dumps(card, ensure_ascii=False))]
                require(bool(relevant), "advisor cards do not cite 848/2017 §33")
                commands = v["evidence"]["scene"].get("commands", [])
                require(any(cmd.get("op") == "hide" and len(cmd.get("item_ids", [])) == 1
                            for cmd in commands), "front-door command did not hide one entrance")
                r["advisor_card_count"] = len(cards)
                r["advisor_sources"] = [card["source"] for card in relevant]
                return "front door hidden; sourced advisor card cites 848/2017 §33"
            self.call("POST", "/api/chats/{chat_id}/messages", advisor,
                      body={"content": "remove the front door"}, sse=True)
        finally:
            self.context = original

    def cleanup(self):
        for kind, key in [("automation", "automation_id"), ("skill", "skill_id")]:
            record = next((r for r in self.created if r["kind"] == kind), None)
            if not record or record["deleted"]:
                continue
            route = f"/api/{'automations' if kind == 'automation' else 'skills'}/{{{key}}}"
            self.call("DELETE", route, lambda v, r: require(v == b"", "delete response not empty"), allowed=(204,))
            record["deleted"] = self.rows[-1]["ok"]
            if kind == "automation":
                self.call("GET", route, lambda v, r: fields(v, detail=str), allowed=(404,))
            else:
                self.call("GET", "/api/skills", lambda v, r: require(
                    isinstance(v, dict) and isinstance(v.get("skills"), list) and
                    not any(s.get("id") == record["id"] for s in v["skills"]), "deleted skill still listed"))

    def save(self, interrupted=False):
        for method, path, _ in PLAN:
            if (method, path) not in self.seen:
                self.rows.append({"method": method, "path": path, "status": None, "latency_ms": 0,
                                  "ok": False, "check": "not reached"})
        failures = sum(not r["ok"] for r in self.rows)
        for row in self.rows:
            row["result"] = "PASS" if row["ok"] else "FAIL"
        report = {"base_url": self.base, "started_at": self.started_at,
                  "finished_at": datetime.now(timezone.utc).isoformat(),
                  "elapsed_s": round(time.monotonic() - self.started, 1), "expected_build_rev": self.expected_build,
                  "passed": failures == 0 and not interrupted, "failures": failures, "interrupted": interrupted,
                  "created": self.created, "notes": self.notes, "checks": self.rows}
        path = self.report_path or ROOT / "results" / "qa" / ("smoke-" + datetime.now().strftime("%H%M") + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n")
        lines = [f"# API smoke: {'PASS' if report['passed'] else 'FAIL'}", "", f"Base: {self.base}", "",
                 f"{len(self.rows)} checks; {failures} failures. Times exclude pacing.", "",
                 "| Method | Endpoint | Status | ms | Result |", "| --- | --- | ---: | ---: | --- |"]
        for r in self.rows:
            lines.append(f"| {r['method']} | {r['path']} | {r['status'] or '-'} | {r['latency_ms']} | {'PASS' if r['ok'] else 'FAIL'}: {r['check']} |")
        lines += ["", *self.notes, "", "Created resources:", ""]
        lines += [f"- {r['kind']} `{r['id']}`: {'deleted' if r['deleted'] else r.get('reason', 'cleanup failed')}" for r in self.created]
        path.with_suffix(".md").write_text("\n".join(lines) + "\n")
        print(f"Reports: {path.relative_to(ROOT)} and {path.with_suffix('.md').relative_to(ROOT)}", flush=True)
        return 0 if report["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", nargs="?", default=DEFAULT_BASE)
    parser.add_argument("--dry-run", action="store_true", help="list all calls and check router coverage; no network/writes")
    parser.add_argument("--timeout", type=float, default=120, help="per-operation timeout in seconds (default 120)")
    parser.add_argument("--expected-build", help="require this health build_rev before and after the smoke")
    parser.add_argument("--s18", action="store_true", help="also check three real revision series and front-door advisor")
    parser.add_argument("--report", type=Path, help="write JSON and Markdown reports at this path")
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error("base_url must be an http(s) URL without credentials, query or fragment")
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    errors = coverage()
    if args.dry_run:
        print(f"Base: {args.base_url}; <=24 requests/min; no keys required; no network in dry-run.")
        for method, path, detail in PLAN:
            print(f"{method:6} {path:58} {detail}")
        print("Extra verification: refetch saved chat, comparison page, uploaded doc + ingest status, deletion checks.")
        print("No /api/compare route: comparisons use /api/changes/{change_id}.")
        print("Watch sync may provision configured monitors; unsigned webhook only tests rejection.")
        if args.s18:
            print("S-18: all issues of S400, S401 and A100 (detail/source/PNG); fresh front-door chat with 848/2017 §33 advisor.")
        print("".join(e + "\n" for e in errors) or f"Coverage OK: {len(PLAN)} router operations.")
        return bool(errors)
    if errors:
        for error in errors:
            print(error)
        return 1
    smoke = Smoke(args.base_url, args.timeout, expected_build=args.expected_build,
                  report_path=args.report.resolve() if args.report else None, s18=args.s18)
    interrupted = False
    try:
        smoke.run()
    except KeyboardInterrupt:
        interrupted = True
        print("Interrupted; attempting cleanup and saving partial results.", flush=True)
    except Exception as exc:
        interrupted = True
        print(f"Runner stopped: {type(exc).__name__}; saving partial results.", flush=True)
    finally:
        smoke.cleanup()
    return smoke.save(interrupted)


if __name__ == "__main__":
    raise SystemExit(main())
