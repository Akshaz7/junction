import asyncio
import contextlib
import os
import time
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
from .bench_routes import router as bench_router
from .linked_routes import router as linked_router
from .skills_routes import router as skills_router, scheduler, scheduler_enabled, seed_skills
from .ratelimit import RateLimitMiddleware


async def _restore_uploads():
    from . import artifact_store
    try:
        await artifact_store.restore_all()
        from engine.project_index import doc_ids_in, load_index, upsert_doc  # re-index uploads restored from PG
        ix = await asyncio.to_thread(load_index)
        have = set(ix.docs) if ix else set()
        for d in await asyncio.to_thread(doc_ids_in, config.artifacts_dir()):
            if d.startswith("uploads__") and d not in have:
                await asyncio.to_thread(upsert_doc, d)
    except Exception as e:  # noqa: BLE001
        print("upload restore failed:", repr(e)[:200])


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.started_at = time.monotonic()
    pool = await db.get_pool()  # apply migrations on startup when a DB is reachable
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await apply_migrations(conn)
                from .changes_source import mark_checked, purge_synthetic
                await purge_synthetic(conn)
                mark_checked()
                await seed_skills(conn)
        except Exception as e:  # never block startup
            print("migrations failed:", e)
    restore = asyncio.create_task(_restore_uploads())
    try:  # project-wide search index (built at image build time); absent -> chat fallback
        from engine.project_index import load_index
        await asyncio.to_thread(load_index)
    except Exception as e:  # noqa: BLE001
        print("project index load failed:", repr(e)[:200])
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
app.state.started_at = time.monotonic()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
if config.rate_limit_enabled():
    app.add_middleware(RateLimitMiddleware, window=60.0)


app.include_router(docs_router)
app.include_router(linked_router)
app.include_router(files_router)
app.include_router(chats_router)
app.include_router(live_router)
app.include_router(speech_router)
app.include_router(advise_router)
app.include_router(findings_router)
app.include_router(bench_router)
app.include_router(skills_router)
from .watch_routes import router as watch_router  # noqa: E402
app.include_router(watch_router)
from .pair_routes import router as pair_router  # noqa: E402
app.include_router(pair_router)
from .design_versions import router as design_versions_router  # noqa: E402
app.include_router(design_versions_router)


@app.get("/api/health")
async def health():
    from engine.models.core import api_key, caps, config as models_config
    from . import artifact_store
    from .image_info import file_counts, image_info

    models_ok = any((api_key(provider) or "").strip()
                    for provider in models_config()["providers"] if provider != "fake")
    database_ok = await db.db_ok()
    servable_docs = None
    if database_ok:
        try:
            pool = await db.get_pool()
            if pool is not None:
                servable_docs = len(await asyncio.wait_for(artifact_store.servable_ids(pool), timeout=2))
        except Exception:  # Diagnostics remain available if the servable list cannot be read.
            pass
    return {"ok": True, "db": database_ok,
            "build_rev": os.environ.get("BUILD_REV", ""),
            "image": image_info(), **file_counts(), "servable_docs": servable_docs,
            "uptime_s": max(0.0, time.monotonic() - app.state.started_at),
            "models_ok": models_ok, "caps_loaded": bool(caps())}
