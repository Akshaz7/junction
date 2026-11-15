"""Isolated manual-label browser fixture; only temporary artifacts and a disposable schema."""
import asyncio
import json
import os
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import uvicorn
from fastapi import FastAPI
from server import config, db
from server.markup_routes import router
from server.files_routes import router as files_router
from server.migrate import apply_migrations

BASE = config.database_url()
SCHEMA = 'taught_browser_' + uuid.uuid4().hex[:8]
os.environ['DATABASE_URL'] = BASE + ('&' if '?' in BASE else '?') + 'options=-csearch_path%3D' + SCHEMA
scratch = tempfile.TemporaryDirectory(prefix='taught-browser-')
os.environ['ARTIFACTS_DIR'] = scratch.name

@asynccontextmanager
async def lifespan(_):
    import pypdfium2
    d = config.artifacts_dir() / 'sheet-under-test'; d.mkdir(parents=True)
    with pypdfium2.PdfDocument('data/judges/L30301_ventilation_3rd_floor_block_U.pdf') as pdf:
        im = pdf[0].render(scale=1).to_pil()
        im.save(d/'page-1.png'); im.save(d/'page-2.png')
    c = await asyncpg.connect(BASE)
    await c.execute(f'create schema {SCHEMA}'); await c.close()
    c = await asyncpg.connect(config.database_url()); await apply_migrations(c); await c.close()
    async def ensure(_): pass
    from server import artifact_store
    artifact_store.ensure_doc = ensure
    try: yield
    finally:
        await db.close_pool()
        c = await asyncpg.connect(BASE); await c.execute(f'drop schema {SCHEMA} cascade'); await c.close()
        scratch.cleanup()

app = FastAPI(lifespan=lifespan)
app.include_router(router); app.include_router(files_router)
@app.post('/test-reset')
async def reset_fixture():
    pool = await db.get_pool()
    await pool.execute('truncate taught_symbols, markup_pins, doc_artifacts')
    for p in config.artifacts_dir().glob('*/planmap-*.json'): p.unlink()
    return {'ok': True}
@app.get('/api/docs/{doc_id}')
async def document(doc_id: str):
    return dict(doc_id=doc_id,title='Ventilation sheet — manual item verification',source='Private evaluation',formats=['png'],kind='raster',pages=2,licence='Private evaluation only',credit='Judge-supplied sheet',heldout=False)
if __name__ == '__main__': uvicorn.run(app, host='127.0.0.1', port=int(os.environ.get('MARKUP_API_PORT','8389')), log_level='warning')
