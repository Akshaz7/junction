"""Seed the demo projects (idempotent). Applies migrations first.

Usage: .venv/bin/python scripts/seed_projects.py
The same seeding also runs at server start (server.projects_routes.seed_demo_projects); SEED_PROJECTS=0 turns that off.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg  # noqa: E402

from server import config  # noqa: E402
from server.migrate import apply_migrations  # noqa: E402


async def main() -> None:
    from server import db
    from server.projects_routes import seed_demo_projects
    conn = await asyncpg.connect(config.database_url())
    try:
        await apply_migrations(conn)
    finally:
        await conn.close()
    pool = await db.get_pool()
    print("seeded (documents added per demo project):", await seed_demo_projects(pool))
    await db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
