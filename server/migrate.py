"""Tiny migration runner: applies server/migrations/*.sql in order, once each.

Usage: uv run python -m server.migrate
"""
import asyncio
from pathlib import Path

import asyncpg

from . import config

MIGRATIONS = Path(__file__).parent / "migrations"


async def apply_migrations(conn: asyncpg.Connection, directory: Path = MIGRATIONS) -> list[str]:
    await conn.execute(
        "create table if not exists schema_migrations (name text primary key, applied_at timestamptz not null default now())")
    done = {r["name"] for r in await conn.fetch("select name from schema_migrations")}
    applied = []
    for f in sorted(directory.glob("*.sql")):
        if f.name in done:
            continue
        async with conn.transaction():
            await conn.execute(f.read_text())
            await conn.execute("insert into schema_migrations (name) values ($1)", f.name)
        applied.append(f.name)
    return applied


async def _main():
    conn = await asyncpg.connect(config.database_url())
    try:
        print("applied:", await apply_migrations(conn) or "nothing new")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(_main())
