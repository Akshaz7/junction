"""asyncpg pool helpers. The app must work with no DB."""
import asyncio

import asyncpg

from . import config

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool | None:
    global _pool
    if _pool is None:
        try:
            _pool = await asyncio.wait_for(
                asyncpg.create_pool(config.database_url(), min_size=1, max_size=5), timeout=2)
        except Exception:
            return None
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def db_ok() -> bool:
    try:
        pool = await get_pool()
        if pool is None:
            return False
        return await asyncio.wait_for(pool.fetchval("select 1"), timeout=2) == 1
    except Exception:
        return False
