"""Seed `documents` from artifacts/registry.jsonl (idempotent upsert). Applies migrations first.

Usage: uv run python -m server.seed [--registry artifacts/registry.jsonl]
"""
import argparse
import asyncio
import json
from pathlib import Path

import asyncpg

from . import config
from .migrate import apply_migrations

REPO = Path(__file__).resolve().parent.parent

UPSERT = """
insert into documents (doc_id, source, title, kind, formats, pages, licence, credit, heldout, files)
values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)
on conflict (doc_id) do update set source=excluded.source, title=excluded.title, kind=excluded.kind,
  formats=excluded.formats, pages=excluded.pages, licence=excluded.licence, credit=excluded.credit,
  heldout=excluded.heldout, files=excluded.files
"""


def read_registry(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


async def seed_documents(conn: asyncpg.Connection, rows: list[dict]) -> int:
    await conn.executemany(UPSERT, [
        (d["doc_id"], d["source"], d.get("title") or d["doc_id"], d.get("kind") or "raster",
         d.get("formats") or [], int(d.get("pages") or 1), d.get("licence"), d.get("credit"),
         bool(d.get("heldout")), json.dumps(d.get("files") or {}))
        for d in rows])
    return len(rows)


async def _main(registry: Path):
    conn = await asyncpg.connect(config.database_url())
    try:
        await apply_migrations(conn)
        if not registry.exists():
            print(f"no registry at {registry}; schema applied, nothing seeded")
            return
        print("seeded", await seed_documents(conn, read_registry(registry)), "documents")
    finally:
        await conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=str(REPO / "artifacts" / "registry.jsonl"))
    asyncio.run(_main(Path(ap.parse_args().registry)))
