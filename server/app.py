import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config, db
from .migrate import apply_migrations
from .docs_routes import router as docs_router
from .chats_routes import router as chats_router
from .files_routes import router as files_router
from .live import hub, router as live_router
from .speech_routes import router as speech_router
from .advise_routes import router as advise_router
from .findings_routes import router as findings_router
from .linked_routes import router as linked_router
from .skills_routes import router as skills_router, scheduler, scheduler_enabled, seed_skills
from .ratelimit import RateLimitMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await db.get_pool()  # apply migrations on startup when a DB is reachable
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await apply_migrations(conn)
                from .changes_source import seed_changes
                await seed_changes(conn)
                await seed_skills(conn)
        except Exception as e:  # never block startup
            print("migrations failed:", e)
    hub.start()
    sched = asyncio.create_task(scheduler()) if scheduler_enabled() else None
    yield
    if sched:
        sched.cancel()
        with contextlib.suppress(BaseException):
            await sched
    await hub.stop()
    await db.close_pool()


app = FastAPI(title="Hologram API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
if config.rate_limit_enabled():
    app.add_middleware(RateLimitMiddleware, limit=30, window=60.0)


app.include_router(docs_router)
app.include_router(linked_router)
app.include_router(files_router)
app.include_router(chats_router)
app.include_router(live_router)
app.include_router(speech_router)
app.include_router(advise_router)
app.include_router(findings_router)
app.include_router(skills_router)
from .watch_routes import router as watch_router  # noqa: E402
app.include_router(watch_router)


@app.get("/api/health")
async def health():
    return {"ok": True, "db": await db.db_ok()}
