"""Dependency-free validation of the answer schema and RFC 6455 client frames."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import ssl
import struct
from urllib.parse import urlsplit


def validate(value, schema: dict, path: str = "$") -> list[str]:
    """Apply every assertion used by answer.schema.json; reject unknown keywords.

    Deliberately limited to this repository schema, rather than claiming full JSON
    Schema support. Schema changes cannot silently weaken a run's validation.
    """
    known = {"$schema", "title", "description", "type", "required", "properties",
             "items", "enum", "minLength", "minimum", "maximum", "minItems",
             "maxItems", "additionalProperties"}
    unknown = schema.keys() - known
    if unknown:
        raise ValueError(f"unsupported schema keywords: {sorted(unknown)}")
    # Check all schema branches even when the corresponding property is absent.
    for child in schema.get("properties", {}).values():
        check_schema(child)
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), dict):
            check_schema(schema[key])
    types = {
        "object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "null": value is None,
        "boolean": isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
        "integer": isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value == int(value),
    }
    allowed = schema.get("type", [])
    allowed = [allowed] if isinstance(allowed, str) else allowed
    if any(t not in types for t in allowed):
        raise ValueError("unsupported schema type")
    if allowed and not any(types[t] for t in allowed):
        return [f"{path}: expected {allowed}"]
    errors = []
    if "enum" in schema and not any(type(value) is type(v) and value == v for v in schema["enum"]):
        errors.append(f"{path}: outside enum")
    if isinstance(value, dict):
        errors += [f"{path}.{k}: required" for k in schema.get("required", []) if k not in value]
        for k, v in value.items():
            child = schema.get("properties", {}).get(k, schema.get("additionalProperties", {}))
            if child is False:
                errors.append(f"{path}.{k}: additional property")
            elif isinstance(child, dict):
                errors += validate(v, child, f"{path}.{k}")
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", math.inf):
            errors.append(f"{path}: array length")
        for i, v in enumerate(value):
            errors += validate(v, schema.get("items", {}), f"{path}[{i}]")
    elif isinstance(value, str) and len(value) < schema.get("minLength", 0):
        errors.append(f"{path}: string length")
    elif types["number"] and (value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf)):
        errors.append(f"{path}: numeric bounds")
    return errors


def check_schema(schema):
    # A null dummy traverses all nested schemas through validate's preflight.
    validate(None, schema)


def image_size(data: bytes) -> tuple[int, int]:
    # The contract's page-image endpoint returns PNG, so no imaging dependency.
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR" or len(data) < 24:
        raise ValueError("page-image response is not a PNG")
    return struct.unpack(">II", data[16:24])


class WebSocket:
    """Small masked asyncio client; handles continuation, ping, pong and close."""

    def __init__(self, url: str):
        self.url = url
        self.writer = None

    async def __aenter__(self):
        u = urlsplit(self.url)
        tls = u.scheme in ("https", "wss")
        self.reader, self.writer = await asyncio.wait_for(asyncio.open_connection(
            u.hostname, u.port or (443 if tls else 80), ssl=ssl.create_default_context() if tls else None), 10)
        key = base64.b64encode(os.urandom(16)).decode()
        host = u.netloc
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        request = (f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.writer.write(request.encode())
        await self.writer.drain()
        try:
            headers = (await asyncio.wait_for(self.reader.readuntil(b"\r\n\r\n"), 10)).decode("latin1")
            accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            parsed = {k.strip().lower(): v.strip() for k, v in (s.split(":", 1) for s in headers.split("\r\n")[1:] if ":" in s)}
            if headers.split()[1] != "101" or parsed.get("sec-websocket-accept") != accept:
                raise ValueError("WebSocket upgrade rejected")
        except BaseException:
            self.writer.close()
            await self.writer.wait_closed()
            raise
        return self

    async def __aexit__(self, *_):
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()

    async def send(self, value, opcode=1):
        data = json.dumps(value).encode() if opcode == 1 else value
        mask = os.urandom(4)
        n = len(data)
        header = bytes([0x80 | opcode, 0x80 | (n if n < 126 else 126 if n < 65536 else 127)])
        if n >= 126:
            header += struct.pack(">H" if n < 65536 else ">Q", n)
        self.writer.write(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
        await self.writer.drain()

    async def receive(self):
        data = bytearray()
        while True:
            first, second = await self.reader.readexactly(2)
            n = second & 127
            if n in (126, 127):
                n = struct.unpack(">H" if n == 126 else ">Q", await self.reader.readexactly(2 if n == 126 else 8))[0]
            if n > 2**22:
                raise ValueError("oversize WebSocket frame")
            mask = await self.reader.readexactly(4) if second & 128 else None
            payload = await self.reader.readexactly(n)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            op = first & 15
            if op == 8:
                raise ConnectionError("WebSocket closed")
            if op == 9:
                await self.send(payload, opcode=10)
            elif op in (0, 1):
                data.extend(payload)
                if first & 128:
                    return json.loads(data)

    async def matching(self, predicate, timeout=5):
        async def find():
            while True:
                msg = await self.receive()
                if predicate(msg):
                    return msg
        return await asyncio.wait_for(find(), timeout)
