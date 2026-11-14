#!/usr/bin/env python3
"""Remove judging-demo test junk, optionally warming the demo over the API.

Usage: python3 scripts/demo_reset.py [base_url] [--dry-run] [--keep-id ID]
DATABASE_URL enables transactional DB cleanup; no .env is read or printed.
Without a URL, --dry-run exits successfully without contacting any service.
Only marked test uploads (source=uploads AND uploads__ ID) can be deleted;
dataset documents and unmarked uploads are always preserved. --keep-id can
retain an intentional generated document, change or chat (repeat as needed).
Stop e2e/upload jobs before applying. Local artifact/source files and persisted
search indexes are never removed: recreate the deployed ephemeral API container
after DB cleanup to discard its old upload/search cache (a process restart alone
does not clear it).
Optional API dry-run reads metadata and OpenAPI; it never writes
or fetches scenes (which may trigger extrusion). Real requests are spaced by
2.5 seconds, including reads, to stay below 25 writes/min and the 30/min quota.
Run separately from live e2e/stress jobs sharing the same IP. No .env is read.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
PREFIXES = ("smoke-", "e2e-", "test-", "test ", "Voice in AR", "WEB2: ")
CHAT_PATTERNS = re.compile(
    r"^(?:(?:Cross-device|Follow|Live overview|W-20 history) \d+(?: second)?"
    r"|warmup-\d{8}T\d{12}Z|FIX-2 in place|Live sync verification"
    r"|Visibility return verification|Scene commands verification)$", re.I)
TEST_UPLOAD = re.compile(r"^(?:upload-fixture(?:-|$)|smoke-|e2e-)", re.I)
GENERATED = re.compile(r"generated[ -]for[ -]demo", re.I)
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
    return isinstance(title, str) and (
        title.casefold().startswith(tuple(p.casefold() for p in PREFIXES))
        or CHAT_PATTERNS.fullmatch(title) is not None)


def test_document(doc: dict) -> bool:
    """Never infer that a dataset document is disposable from its title."""
    if doc.get("source") != "uploads" or not doc.get("doc_id", "").startswith("uploads__"):
        return False
    title = doc.get("title") or ""
    return bool(TEST_UPLOAD.search(title) or GENERATED.search(title)
                or TEST_UPLOAD.search(doc["doc_id"].removeprefix("uploads__"))
                or GENERATED.search(doc["doc_id"]))


def test_change(change: dict) -> bool:
    summary = change.get("summary") or {}
    if isinstance(summary, str):
        summary = json.loads(summary)
    if not isinstance(summary, dict):
        return False
    return summary.get("generated_for_demo") is True or any(
        GENERATED.search(summary.get(k) or "") for k in ("title", "headline", "summary")
        if isinstance(summary.get(k), str))


async def reset_database(conn, *, dry_run: bool, keep_ids=()) -> list[tuple[str, str, object]]:
    """Plan and apply the same deletes under row locks; cascades remove chat history.

    Documents referenced by retained chats/explicitly kept changes stay intact. Child deletes
    cover non-cascading findings/artifact/answer/scene references in migrations.
    The injectable asyncpg-shaped connection also permits offline sqlite tests.
    """
    keep = set(keep_ids)
    async with conn.transaction(isolation="repeatable_read", readonly=dry_run):
        lock = "" if dry_run else " for update"
        docs = [dict(r) for r in await conn.fetch("select doc_id, source, title from documents" + lock)]
        chats = [dict(r) for r in await conn.fetch("select id, doc_id, title from chats" + lock)]
        changes = [dict(r) for r in await conn.fetch("select id, doc_a, doc_b, summary from changes" + lock)]
        chat_targets = [r for r in chats if str(r["id"]) not in keep and automated(r)]
        chat_ids = {str(r["id"]) for r in chat_targets}
        doc_targets = {r["doc_id"] for r in docs if r["doc_id"] not in keep and test_document(r)}
        # A retained conversation or explicitly retained change protects its docs.
        for chat in chats:
            if str(chat["id"]) not in chat_ids:
                doc_targets.discard(chat["doc_id"])
        for change in changes:
            if str(change["id"]) in keep:
                doc_targets.difference_update((change["doc_a"], change["doc_b"]))
        change_targets = [r for r in changes if str(r["id"]) not in keep and (
            test_change(r) or r["doc_a"] in doc_targets or r["doc_b"] in doc_targets)]
        plan = []
        for row in chat_targets:
            plan.append(("chats", "id", row["id"]))
            print(f"DELETE chats id={display(str(row['id']))} title={display(row['title'])}")
        for row in change_targets:
            plan.append(("changes", "id", row["id"]))
            print(f"DELETE changes id={display(str(row['id']))} (test/generated change or test upload)")
        for doc_id in sorted(doc_targets):
            for table in ("findings", "doc_artifacts", "answers", "scene_edits", "documents"):
                plan.append((table, "doc_id", doc_id))
                print(f"DELETE {table} doc_id={display(doc_id)}")
        print(f"Preserving {len(docs) - len(doc_targets)} documents; "
              f"{len(chats) - len(chat_targets)} chats; {len(changes) - len(change_targets)} changes.")
        if not dry_run:
            for table, column, value in plan:
                # Table/column names are constants above; values are always bound.
                await conn.execute(f"delete from {table} where {column}=$1", value)
        return plan


async def database_cleanup(dry_run: bool, keep_ids) -> bool:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("no DATABASE_URL: database cleanup skipped (no database contacted).")
        return False
    try:
        import asyncpg
        conn = await asyncpg.connect(url, timeout=10, command_timeout=30)
        try:
            await reset_database(conn, dry_run=dry_run, keep_ids=keep_ids)
        finally:
            await conn.close()
    except Exception:
        # Connection/DB exceptions can embed credentials or query values.
        raise DemoError("Database cleanup failed; transaction rolled back. Check schema and connectivity.") from None
    return True


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


def prepare(client: Client, dry_run: bool, keep_ids=()):
    questions = demo_questions(ROOT / "docs" / "DEMO.md")
    docs = list(dict.fromkeys(doc_id for doc_id, _ in questions))
    listed = client.request("GET", "/api/chats", "List chats")
    if not isinstance(listed, dict) or not isinstance(listed.get("chats"), list):
        raise DemoError("Invalid chat list")
    chats = listed["chats"]
    if not all(isinstance(c, dict) and isinstance(c.get("id"), str) for c in chats):
        raise DemoError("Invalid chat entry")
    targets = [c for c in chats if automated(c) and c["id"] not in keep_ids]
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
    parser.add_argument("base_url", nargs="?", help="optional API origin for chat cleanup and demo warm-up")
    parser.add_argument("--dry-run", action="store_true", help="read metadata and list actions; no writes/assets")
    parser.add_argument("--keep-id", action="append", default=[], help="preserve this document/chat/change ID; repeatable")
    args = parser.parse_args()
    started = time.monotonic()
    client = None
    try:
        print("DRY RUN: no writes or asset fetches." if args.dry_run else "Preparing judging demo.", flush=True)
        # Validate an optional API URL before any DB mutation.
        client = Client(args.base_url) if args.base_url else None
        cleaned = asyncio.run(database_cleanup(args.dry_run, args.keep_id))
        if client is not None:
            if not cleaned:
                print("Database cleanup unavailable: API mode cleans chats only, not uploads/changes.")
            prepare(client, args.dry_run, args.keep_id)
        elif not cleaned and not args.dry_run:
            raise DemoError("Set DATABASE_URL for cleanup or supply an API base URL")
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
