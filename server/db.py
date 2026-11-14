"""asyncpg pool helpers. The app must work with no DB."""
import asyncio

import asyncpg

from . import config

_pool: asyncpg.Pool | None = None
_pool_loop = None  # serverless hosts may run each request on a new event loop; a pool is bound to its loop


async def get_pool() -> asyncpg.Pool | None:
    global _pool, _pool_loop
    loop = asyncio.get_running_loop()
    if _pool is not None and _pool_loop is not loop:
        try:
            _pool.terminate()  # stale pool from another loop: close its connections now, or they pile up on the DB
        except Exception:  # noqa: BLE001
            pass
        _pool = None
    if _pool is None:
        try:
            _pool = await asyncio.wait_for(
                asyncpg.create_pool(config.database_url(), min_size=1, max_size=5), timeout=5)
            _pool_loop = loop
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
