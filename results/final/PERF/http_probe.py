"""Time real local HTTP/SSE + PostgreSQL + engine, in a temporary DB schema.

Run via heavy.sh. Uses real artifacts without copying or rewriting them. Only
chat/database plumbing runs here; background restore/ingestion is not started.
`before` imports changed engine modules from HEAD to reproduce the baseline.
"""
import asyncio
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).parent
phase = sys.argv[1]
live = "--live" in sys.argv
baseline_commit = json.loads((OUT / "selection.json").read_text())["baseline_commit"]
if phase == "before":
    modules = {"engine.answer", "engine.explain", "engine.library", "engine.models.providers",
               "engine.reasoning", "engine.solvers.data", "engine.reader", "engine.reader.agent",
               "engine.reader.tools", "engine.reader.text"}
    class Baseline(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, path=None, target=None):
            if fullname not in modules:
                return None
            rel = fullname.replace(".", "/") + ("/__init__.py" if fullname == "engine.reader" else ".py")
            return importlib.util.spec_from_file_location(fullname, ROOT / rel, loader=self,
                submodule_search_locations=[str(ROOT / "engine/reader")] if fullname == "engine.reader" else None)
        def create_module(self, spec):
            return None
        def exec_module(self, module):
            rel = Path(module.__file__).relative_to(ROOT)
            source = subprocess.check_output(["git", "show", f"{baseline_commit}:{rel}"], cwd=ROOT)
            exec(compile(source, str(module.__file__), "exec"), module.__dict__)
    sys.meta_path.insert(0, Baseline())

scratch = tempfile.TemporaryDirectory(prefix="f-perf-http-")
os.environ.update(MODELS_FAKE="0" if live else "1", EXPLAIN="1" if live else "0",
                  MODELS_CACHE_DIR=scratch.name + "/models", MODELS_COSTS_LOG=scratch.name + "/costs.jsonl",
                  ARTIFACTS_DIR=str(ROOT / "artifacts"), HIDE_EMPTY_DOCS="0", RATE_LIMIT="0", ENGINE_IMPL="real")

import asyncpg
import httpx
import uvicorn
from fastapi import FastAPI
from server import config, db, chats_routes, artifact_store
from server.migrate import apply_migrations
from engine.project_index import Index

Index.save = lambda *a, **kw: None  # read-only shared artifacts
base_url = config.DEFAULT_DATABASE_URL  # explicitly local, never .env / deployed DB
schema = "f_perf_" + uuid.uuid4().hex[:10]
os.environ["DATABASE_URL"] = base_url + "?options=-csearch_path%3D" + schema
reserved = json.loads((OUT / "selection.json").read_text())["validation_only_doc_id"]
files = sorted((ROOT / "artifacts").glob("*/elements.json"), key=lambda p: p.stat().st_size, reverse=True)
ids = [p.parent.name for p in files if p.parent.name != reserved][:10]


async def setup():
    c = await asyncpg.connect(base_url)
    await c.execute(f"create schema {schema}")
    await c.close()
    c = await asyncpg.connect(os.environ["DATABASE_URL"])
    await apply_migrations(c)
    for did in ids:
        meta = json.loads((ROOT / "artifacts" / did / "doc.json").read_text())
        await c.execute("insert into documents(doc_id,source,title,kind) values($1,$2,$3,$4)",
                        did, meta.get("source", ""), meta.get("title", did), meta.get("kind", "ifc"))
    await c.close()


async def cleanup():
    c = await asyncpg.connect(base_url)
    await c.execute(f"drop schema {schema} cascade")
    await c.close()


asyncio.run(setup())
# Existing artifact files are already present. Avoid even touching .restored markers.
async def existing_only(did):
    assert (ROOT / "artifacts" / did / "elements.json").is_file()
artifact_store.ensure_doc = existing_only

app = FastAPI()
app.include_router(chats_routes.router)

@app.on_event("shutdown")
async def shutdown():
    await db.close_pool()

listener = socket.socket()
listener.bind(("127.0.0.1", 0))
port = listener.getsockname()[1]
server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
thread.start()
until = time.monotonic() + 10
while not server.started and time.monotonic() < until:
    threading.Event().wait(.01)


def ask(client, dids, question):
    r = client.post("/api/chats", json={"doc_ids": dids, "title": "F-PERF local timing"})
    r.raise_for_status()
    cid = r.json()["id"]
    started = time.perf_counter()
    events, final = [], None
    with client.stream("POST", f"/api/chats/{cid}/messages", json={"content": question, "doc_ids": dids}) as response:
        response.raise_for_status()
        kind = None
        for line in response.iter_lines():
            if line.startswith("event:"):
                kind = line[6:].strip()
            elif line.startswith("data:"):
                payload = json.loads(line[5:])
                events.append({"kind": kind, "ms": round((time.perf_counter() - started) * 1000, 3)})
                if kind == "answer":
                    final = payload
                if kind == "error":
                    raise RuntimeError(payload)
    return {"doc_ids": dids, "question": question, "events": events,
            "first_status_ms": next((e["ms"] for e in events if e["kind"] == "status"), None),
            "first_answer_text_ms": next((e["ms"] for e in events if e["kind"] in ("delta", "answer.partial")), None),
            "final_ms": next((e["ms"] for e in events if e["kind"] == "answer"), None),
            "value": final["answer"]["value"], "cost": final["cost"], "latency_ms": final["latency_ms"],
            "citation_count": len(final["citations"]), "text_md": final["answer"]["text_md"]}


try:
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=305) as client:
        # The largest indexed model gives a long enough evidence workload for profiling.
        rows = [ask(client, [ids[0]], "How many doors are in this model?")]
        if not live:
            rows.append(ask(client, [next(d for d in ids if "plumbing" in d)], "How many pipes are in this model?"))
            rows.append(ask(client, ids, "How many doors are there across all models?"))
        report = {"phase": phase, "models": "live" if live else "fake", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                  "stack": "Loopback Uvicorn, real chats router, isolated local Postgres schema, real artifact indexes",
                  "ingestion": "Already converted; skipped; background restore disabled for read-only shared artifacts", "answers": rows}
        (OUT / f"http-{phase}{'-live' if live else ''}.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report), flush=True)
finally:
    server.should_exit = True
    thread.join(timeout=5)
    listener.close()
    asyncio.run(cleanup())
