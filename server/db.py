"""asyncpg pool helpers. The app must work with no DB."""
import asyncio
import os

import asyncpg

from . import config

MIN_CONN = int(os.environ.get("DB_MIN_CONN", "2"))
MAX_CONN = int(os.environ.get("DB_MAX_CONN", "6"))
KEEPALIVE_S = float(os.environ.get("DB_KEEPALIVE_S", "25"))
_pool: asyncpg.Pool | None = None
_keepalive: asyncio.Task | None = None
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
            # Warm connections matter: a new one costs TCP + TLS + auth (several round trips to a remote DB).
            # min_size connections are opened up front; idle ones are kept (not recycled after 5 min) and pinged.
            _pool = await asyncio.wait_for(
                asyncpg.create_pool(config.database_url(), min_size=MIN_CONN, max_size=MAX_CONN,
                                    max_inactive_connection_lifetime=0, statement_cache_size=100,
                                    max_cached_statement_lifetime=0), timeout=8)
            _pool_loop = loop
            _start_keepalive(loop)
        except Exception:
            return None
    return _pool


def _start_keepalive(loop) -> None:
    global _keepalive
    if _keepalive is not None and not _keepalive.done():
        _keepalive.cancel()
    _keepalive = loop.create_task(_ping_loop(_pool))


async def _ping_loop(pool) -> None:
    """Every KEEPALIVE_S run a trivial query on each warm connection so idle ones are not dropped by the network or
    the server, and a dead one is replaced in the background instead of during a request."""
    while True:
        await asyncio.sleep(KEEPALIVE_S)
        try:
            await asyncio.gather(*[_ping(pool) for _ in range(MIN_CONN)])
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001  keepalive is best effort
            pass


async def _ping(pool) -> None:
    async with pool.acquire() as c:
        await asyncio.wait_for(c.fetchval("select 1"), timeout=5)


async def close_pool() -> None:
    global _pool, _keepalive
    if _keepalive is not None:
        _keepalive.cancel()
        _keepalive = None
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
