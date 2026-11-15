"""Local-only browser test server, isolated DB schema and worker-owned artifacts.
Never uses the main application's documents/chats or source drawing directory for writes.
"""
import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from server import config, db
from server.markup_routes import router
from server.migrate import apply_migrations

ROOT = Path(__file__).parent / 'local'
BASE = 'postgresql://hologram:hologram@localhost:5433/hologram'
SCHEMA = 'markup_browser_' + uuid.uuid4().hex[:8]
os.environ['DATABASE_URL'] = BASE + '?options=-csearch_path%3D' + SCHEMA
os.environ['ARTIFACTS_DIR'] = str(ROOT / 'browser-artifacts')

@asynccontextmanager
async def lifespan(_):
    from PIL import Image
    if not (ROOT/'vent.png').is_file():
        import pypdfium2
        ROOT.mkdir(parents=True, exist_ok=True)
        pdf = pypdfium2.PdfDocument('data/judges/L30301_ventilation_3rd_floor_block_U.pdf')
        pdf[0].render(scale=1).to_pil().save(ROOT/'vent.png')
    d = config.artifacts_dir() / 'sheet-under-test'; d.mkdir(parents=True, exist_ok=True)
    with Image.open(ROOT/'vent.png') as im:
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

app = FastAPI(lifespan=lifespan)
app.include_router(router)
@app.post('/test-reset')
async def reset_fixture():
    pool = await db.get_pool()
    await pool.execute('truncate taught_symbols, markup_pins')
    return {'ok': True}
@app.get('/api/docs/{doc_id}')
async def document(doc_id: str):
    return dict(doc_id=doc_id,title='Ventilation sheet — markup verification',source='Private evaluation',formats=['png'],kind='raster',pages=2,licence='Private evaluation only',credit='Judge-supplied sheet',heldout=False)
@app.get('/api/docs/{doc_id}/pages/{page}/image')
async def image(doc_id: str, page: int): return FileResponse(config.artifacts_dir()/doc_id/f'page-{page}.png')
@app.get('/api/docs/{doc_id}/planmap/{page}')
async def plan(doc_id: str, page: int): return {'items':[]}
@app.get('/api/docs/{doc_id}/scene')
async def scene(doc_id: str): return {'items':{},'storeys':[]}
if __name__ == '__main__': uvicorn.run(app, host='127.0.0.1', port=int(os.environ.get('MARKUP_API_PORT','8387')), log_level='warning')
