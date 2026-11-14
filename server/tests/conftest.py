import asyncio
import uuid

import asyncpg
import pytest

from server import config, db

async def _connect_or_skip():
    try:
        return await asyncpg.connect(config.database_url(), timeout=2)
    except Exception:
        pytest.skip("no local Postgres")


@pytest.fixture
def schema_url(monkeypatch):
    """Isolated schema so tests never touch real data."""
    name = "t_" + uuid.uuid4().hex[:8]

    async def setup():
        c = await _connect_or_skip()
        await c.execute(f"create schema {name}")
        await c.close()
    asyncio.run(setup())
    base = config.database_url()
    sep = "&" if "?" in base else "?"
    monkeypatch.setenv("DATABASE_URL", f"{base}{sep}options=-csearch_path%3D{name}")
    monkeypatch.setattr(db, "_pool", None)
    yield name

    async def teardown():
        c = await asyncpg.connect(base)
        await c.execute(f"drop schema {name} cascade")
        await c.close()
    asyncio.run(teardown())


