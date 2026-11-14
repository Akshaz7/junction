from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config, db
from .migrate import apply_migrations
from .docs_routes import router as docs_router
from .ratelimit import RateLimitMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await db.get_pool()  # apply migrations on startup when a DB is reachable
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await apply_migrations(conn)
        except Exception as e:  # never block startup
            print("migrations failed:", e)
    yield
    await db.close_pool()


app = FastAPI(title="Hologram API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
if config.rate_limit_enabled():
    app.add_middleware(RateLimitMiddleware, limit=30, window=60.0)


app.include_router(docs_router)


@app.get("/api/health")
async def health():
    return {"ok": True, "db": await db.db_ok()}
