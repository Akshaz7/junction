#!/usr/bin/env python3
"""Prepare the judging demo using only the public API and Python's stdlib.

Usage: python3 scripts/demo_reset.py <base_url> [--dry-run]
Dry-run reads chat titles, demo document metadata and OpenAPI; it never writes
or fetches scenes (which may trigger extrusion). Real requests are spaced by
2.5 seconds, including reads, to stay below 25 writes/min and the 30/min quota.
Run separately from live e2e/stress jobs sharing the same IP. No .env is read.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
PREFIXES = ("smoke-", "e2e-", "test", "Voice in AR")
INTERVAL = 2.5
DOC_ID = re.compile(r"[A-Za-z0-9_-]+__[A-Za-z0-9_.-]+")


class DemoError(Exception):
    """Only static, safe messages are emitted; never response bodies/URLs."""


def demo_questions(path: Path) -> list[tuple[str, str]]:
    """Read the document and Exact question columns, including arrow sequences."""
    questions = []
    columns = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("|"):
            columns = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if "Exact question" in cells:
            doc_column = next((i for i, c in enumerate(cells) if "document" in c.lower()), None)
            if doc_column is None:
                raise DemoError("Question table has no document column")
            columns = (doc_column, cells.index("Exact question"))
            continue
        if columns is None or all(re.fullmatch(r"[: -]+", c) for c in cells):
            continue
        if len(cells) <= max(columns):
            raise DemoError("Malformed demo question row")
        ids = DOC_ID.findall(cells[columns[0]])
        if len(ids) != 1:
            raise DemoError("Each demo question row must identify exactly one document")
        for question in cells[columns[1]].split("→"):
            question = question.strip().strip('`“”"').strip()
            if not question:
                raise DemoError("Empty demo question")
            questions.append((ids[0], question))
    if not questions:
        raise DemoError("No Exact question table found in docs/DEMO.md")
    return questions


def automated(chat: dict) -> bool:
    title = chat.get("title")
    return isinstance(title, str) and title.startswith(PREFIXES)


def segment(value: str) -> str:
    return quote(value, safe="")


def display(value: str) -> str:
    # Keep console/table output on one line, including untrusted chat titles.
    return json.dumps(value, ensure_ascii=True)[1:-1].replace("|", r"\u007c")


class Client:
    def __init__(self, base: str):
        parsed = urlsplit(base)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment):
            raise DemoError("Use an HTTP(S) base URL without credentials, query or fragment")
        self.base = base.rstrip("/")
        self.last_request = float("-inf")
        self.rows: list[tuple[str, str, str, int]] = []

    def request(self, method: str, path: str, label: str, body=None, kind="json"):
        remaining = INTERVAL - (time.monotonic() - self.last_request)
        if remaining > 0:
            time.sleep(remaining)
        self.last_request = time.monotonic()
        started = self.last_request
        status, size = "FAILED", 0
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Accept": "text/event-stream" if kind == "sse" else "*/*"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        try:
            req = Request(self.base + path, data=data, headers=headers, method=method)
            with urlopen(req, timeout=180 if kind == "sse" else 15) as response:
                status = str(response.status)
                if kind == "bytes":
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                    if not size:
                        raise DemoError("Empty asset response")
                    return None
                if kind == "sse":
                    if "text/event-stream" not in response.headers.get("Content-Type", ""):
                        raise DemoError("Expected an SSE answer stream")
                    event, lines, answer = "", [], None

                    def finish_event():
                        if event == "error":
                            raise DemoError("Engine reported an SSE error")
                        if event == "answer":
                            return json.loads("\n".join(lines))
                        return None

                    for raw in response:
                        size += len(raw)
                        if time.monotonic() - started > 180:
                            raise DemoError("Answer stream exceeded 180 seconds")
                        line = raw.decode("utf-8").rstrip("\r\n")
                        if not line:
                            found = finish_event()
                            if found is not None:
                                answer = found
                            event, lines = "", []
                        elif line.startswith("event:"):
                            event = line[6:].strip()
                        elif line.startswith("data:"):
                            lines.append(line[5:].removeprefix(" "))
                    answer = finish_event() or answer
                    if not isinstance(answer, dict) or not isinstance(answer.get("answer"), dict):
                        raise DemoError("Stream ended without an answer")
                    if answer["answer"].get("abstained"):
                        status += " (abstained)"
                    return answer
                raw = response.read()
                size = len(raw)
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            status = str(exc.code)
            exc.close()
            raise DemoError(f"HTTP {status}") from None
        except (URLError, TimeoutError, OSError):
            status = "NETWORK ERROR"
            raise DemoError("Network request failed") from None
        except (ValueError, DemoError):
            status += " INVALID" if status != "FAILED" else ""
            raise DemoError("Invalid or unsuccessful API response") from None
        finally:
            self.rows.append((label, status, f"{time.monotonic() - started:.3f}", size))

    def plan(self, label: str):
        self.rows.append((label, "PLANNED", "-", 0))

    def summary(self, started: float):
        print("\n| Action | Status | Seconds | Bytes |")
        print("| --- | --- | ---: | ---: |")
        for label, status, duration, size in self.rows:
            print(f"| {display(label)} | {status} | {duration} | {size} |")
        planned = sum(row[1] == "PLANNED" for row in self.rows)
        print(f"\n{len(self.rows) - planned} requests; {planned} planned actions; "
              f"elapsed {time.monotonic() - started:.3f}s (includes pacing).", flush=True)


def delete_chat(client: Client, chat_id: str, *, warmup_title: str | None = None):
    path = f"/api/chats/{segment(chat_id)}"
    current = client.request("GET", path, "Recheck deletion target " + chat_id)
    if not isinstance(current, dict) or str(current.get("id")) != chat_id:
        raise DemoError("Could not verify chat before deletion")
    if warmup_title is not None:
        allowed = current.get("title") == warmup_title
    else:
        allowed = automated(current)
    if not allowed:
        raise DemoError("Chat title changed; deletion skipped")
    client.request("DELETE", path, "Delete " + str(current["title"]))


def prepare(client: Client, dry_run: bool):
    questions = demo_questions(ROOT / "docs" / "DEMO.md")
    docs = list(dict.fromkeys(doc_id for doc_id, _ in questions))
    listed = client.request("GET", "/api/chats", "List chats")
    if not isinstance(listed, dict) or not isinstance(listed.get("chats"), list):
        raise DemoError("Invalid chat list")
    chats = listed["chats"]
    if not all(isinstance(c, dict) and isinstance(c.get("id"), str) for c in chats):
        raise DemoError("Invalid chat entry")
    targets = [c for c in chats if automated(c)]
    print(f"{len(targets)} matching automated chats; preserving {len(chats) - len(targets)} others.")
    for chat in targets:
        print(f"  DELETE {display(chat['id'])} title={display(chat['title'])}")

    schema = client.request("GET", "/openapi.json", "Check chat deletion support")
    supports_delete = "delete" in schema.get("paths", {}).get("/api/chats/{chat_id}", {})
    if not supports_delete:
        print("NEEDS: API must implement DELETE /api/chats/{chat_id}; real reset stops before writes.")

    pages = {}
    for doc_id in docs:
        doc = client.request("GET", f"/api/docs/{segment(doc_id)}", "Read demo document " + doc_id)
        count = doc.get("pages")
        if doc.get("doc_id") != doc_id or type(count) is not int or count < 1:
            raise DemoError("Demo document has no valid page count")
        pages[doc_id] = count

    warmup_title = "warmup-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if dry_run:
        for chat in targets:
            client.plan("Recheck title, then DELETE chat " + chat["id"] + " " + chat["title"])
        client.plan("POST /api/chats title=" + warmup_title)
        for doc_id, question in questions:
            client.plan(f"POST /api/chats/<warmup>/messages doc={doc_id}: {question}")
        client.plan("Recheck title, then DELETE created warmup chat (also on failure)")
    else:
        if not supports_delete:
            raise DemoError("Missing chat-delete API; no writes made")
        for chat in targets:
            delete_chat(client, chat["id"])
        chat = client.request("POST", "/api/chats", "Create " + warmup_title,
                              {"title": warmup_title, "doc_ids": docs})
        if not isinstance(chat, dict) or not isinstance(chat.get("id"), str):
            raise DemoError("Chat creation returned no id")
        try:
            for doc_id, question in questions:
                client.request("POST", f"/api/chats/{segment(chat['id'])}/messages",
                               f"Warm {doc_id}: {question}",
                               {"content": question, "doc_ids": [doc_id]}, kind="sse")
        finally:
            delete_chat(client, chat["id"], warmup_title=warmup_title)

    failures = 0
    for doc_id in docs:
        prefix = f"/api/docs/{segment(doc_id)}"
        assets = [(prefix + "/scene", "json"),
                  (prefix + "/files/scene.glb", "bytes"),
                  (prefix + "/files/scene.usdz", "bytes")]
        assets.extend((prefix + f"/pages/{page}/image", "bytes")
                      for page in range(1, pages[doc_id] + 1))
        for path, kind in assets:
            if dry_run:
                client.plan("GET " + path)
            else:
                try:
                    client.request("GET", path, "Warm GET " + path, kind=kind)
                except DemoError:
                    failures += 1
    if failures:
        raise DemoError(f"{failures} asset fetches failed; see summary")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="API origin, e.g. http://localhost:8000")
    parser.add_argument("--dry-run", action="store_true", help="read metadata and list actions; no writes/assets")
    args = parser.parse_args()
    started = time.monotonic()
    client = None
    try:
        client = Client(args.base_url)
        print("DRY RUN: no writes or asset fetches." if args.dry_run else "Preparing judging demo.", flush=True)
        prepare(client, args.dry_run)
        return 0
    except DemoError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError, AttributeError, TypeError, KeyError):
        print("ERROR: Could not read demo instructions or validate API response.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    finally:
        if client is not None:
            client.summary(started)


if __name__ == "__main__":
    sys.exit(main())
