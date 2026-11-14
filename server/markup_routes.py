"""Saved symbol teachings and site notes, in page-image pixels (1-based pages)."""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from engine.symbol_teach import find_similar, room_for, summary, taught_answer
from . import artifact_store, config, db

router = APIRouter(prefix='/api')


class Selection(BaseModel):
    page: int = Field(default=1, ge=1, le=100000)
    box: tuple[float, float, float, float]
    name: str = Field(min_length=1, max_length=160)
    note: str = Field(default='', max_length=4000)
    project_id: str | None = Field(default=None, max_length=160)

    @field_validator('box')
    @classmethod
    def valid_box(cls, b):
        import math
        if not all(math.isfinite(x) and x >= 0 for x in b) or b[2] <= b[0] or b[3] <= b[1]:
            raise ValueError('Select a box with positive width and height')
        return b

    @field_validator('name')
    @classmethod
    def valid_name(cls, v):
        if not v.strip():
            raise ValueError('Name must not be blank')
        return v.strip()


class Review(BaseModel):
    statuses: dict[str, Literal['confirmed', 'rejected', 'pending']] = Field(max_length=500)


class Pin(BaseModel):
    page: int = Field(default=1, ge=1)
    x: float = Field(ge=0, allow_inf_nan=False)
    y: float = Field(ge=0, allow_inf_nan=False)
    note: str = Field(min_length=1, max_length=4000)

    @field_validator('note')
    @classmethod
    def nonempty(cls, v):
        if not v.strip():
            raise ValueError('Write a note')
        return v.strip()


def doc_dir(doc_id):
    if not re.fullmatch(r'[\w.\-]+', doc_id) or doc_id in {'.', '..'}:
        raise HTTPException(400, 'Invalid document')
    return config.artifacts_dir() / doc_id


async def pool_required():
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, 'Notes and labels need a database connection. Try again shortly.')
    return pool


def record(row):
    r = dict(row)
    for k in ('matches', 'template_bbox'):
        if isinstance(r.get(k), str):
            r[k] = json.loads(r[k])
    r['id'] = str(r['id'])
    r['created_at'] = r['created_at'].isoformat()
    if 'matches' in r:
        r['summary'] = summary(r['matches'])
    return r


async def page_image(doc_id, page):
    d = doc_dir(doc_id)
    await artifact_store.ensure_doc(doc_id)
    image = d / f'page-{page}.png'
    if not image.is_file():
        raise HTTPException(404, 'This page image is not available')
    return image


@lru_cache(maxsize=24)
def page_context(path, page, signature):
    """Read only existing words/plan maps. Cached by page and artifact timestamps."""
    from pathlib import Path
    from engine.symbols import find_legend
    d = Path(path)
    def read(name, default):
        try:
            return json.loads((d / name).read_text())
        except (OSError, ValueError):
            return default
    text = read(f'text-{page}.json', {})
    words = text if isinstance(text, list) else text.get('words', text.get('items', []))
    plan = read(f'planmap-{page}.json', {})
    rooms = [i for i in plan.get('items', []) if i.get('kind') == 'room']
    legend = find_legend(d / f'page-{page}.png', words=words) if words else {}
    return {'suggestions': list(dict.fromkeys(e['label'] for e in legend.get('entries', []))), 'rooms': rooms}


def context(image, page):
    d = image.parent
    sig = tuple((p.name, p.stat().st_mtime_ns) for p in (image, d / f'text-{page}.json', d / f'planmap-{page}.json') if p.is_file())
    return page_context(str(d), page, sig)


@router.get('/docs/{doc_id}/markup')
async def get_markup(doc_id: str, page: int = 1):
    if page < 1:
        raise HTTPException(400, 'Invalid page')
    doc_dir(doc_id)
    pool = await pool_required()
    symbols = [record(r) for r in await pool.fetch('select * from taught_symbols where doc_id=$1 order by created_at', doc_id)]
    pins = [record(r) for r in await pool.fetch('select * from markup_pins where doc_id=$1 order by created_at, id', doc_id)]
    for n, p in enumerate(pins, 1):
        p['n'] = n
    image = await page_image(doc_id, page)
    ctx = await asyncio.to_thread(context, image, page)
    return {'symbols': symbols, 'pins': pins, 'suggestions': ctx['suggestions']}


@router.post('/docs/{doc_id}/markup/symbols', status_code=201)
async def teach(doc_id: str, body: Selection):
    pool = await pool_required()
    image = await page_image(doc_id, body.page)
    from PIL import Image
    with Image.open(image) as im:
        w, h = im.size
    if body.box[2] > w or body.box[3] > h or (body.box[2]-body.box[0])*(body.box[3]-body.box[1]) > w*h/4:
        raise HTTPException(400, 'Select one symbol inside the page, not a large sheet area')
    if await pool.fetchval('select exists(select 1 from taught_symbols where doc_id=$1 and lower(name)=lower($2) and page=$3)', doc_id, body.name, body.page):
        raise HTTPException(409, 'This label already exists on this page. Review its saved boxes or choose a different name.')
    result = await asyncio.to_thread(find_similar, image, body.box, page=body.page-1)
    ctx = await asyncio.to_thread(context, image, body.page)
    matches = [{'id': str(i), 'bbox': m['bbox'], 'score': m['score'], 'status': 'pending',
                'room': room_for(m['bbox'], ctx['rooms'])} for i, m in enumerate(result['matches'], 1)]
    r = await pool.fetchrow('insert into taught_symbols(doc_id, project_id, name, note, template_bbox, page, matches) '
                            'values($1,$2,$3,$4,$5::jsonb,$6,$7::jsonb) returning *',
                            doc_id, body.project_id, body.name, body.note, json.dumps(list(body.box)), body.page, json.dumps(matches))
    return {**record(r), 'matcher_note': result.get('note'), 'method': result.get('method')}


def identifier(value):
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(400, 'Invalid markup id')


@router.patch('/docs/{doc_id}/markup/symbols/{symbol_id}')
async def review(doc_id: str, symbol_id: str, body: Review):
    doc_dir(doc_id)
    pool = await pool_required()
    # Lock the row so reviews on two devices cannot lose each other's changes.
    async with pool.acquire() as c:
        async with c.transaction():
            row = await c.fetchrow('select * from taught_symbols where id=$1 and doc_id=$2 for update', identifier(symbol_id), doc_id)
            if not row:
                raise HTTPException(404, 'Label not found')
            r = record(row)
            if set(body.statuses) - {m['id'] for m in r['matches']}:
                raise HTTPException(400, 'Unknown match')
            for m in r['matches']:
                if m['id'] in body.statuses:
                    m['status'] = body.statuses[m['id']]
            row = await c.fetchrow('update taught_symbols set matches=$1::jsonb where id=$2 returning *', json.dumps(r['matches']), identifier(symbol_id))
    return record(row)


@router.get('/docs/{doc_id}/markup/pins')
async def get_pins(doc_id: str):
    doc_dir(doc_id)
    pool = await pool_required()
    pins = [record(r) for r in await pool.fetch('select * from markup_pins where doc_id=$1 order by created_at, id', doc_id)]
    for n, p in enumerate(pins, 1):
        p['n'] = n
    return pins


@router.post('/docs/{doc_id}/markup/pins', status_code=201)
async def add_pin(doc_id: str, body: Pin):
    pool = await pool_required()
    image = await page_image(doc_id, body.page)
    from PIL import Image
    with Image.open(image) as im:
        if body.x > im.width or body.y > im.height:
            raise HTTPException(400, 'Place the pin inside the page')
    return record(await pool.fetchrow('insert into markup_pins(doc_id,page,x,y,note) values($1,$2,$3,$4,$5) returning *', doc_id, body.page, body.x, body.y, body.note))


@router.delete('/docs/{doc_id}/markup/pins/{pin_id}', status_code=204)
async def delete_pin(doc_id: str, pin_id: str):
    doc_dir(doc_id)
    result = await (await pool_required()).execute('delete from markup_pins where id=$1 and doc_id=$2', identifier(pin_id), doc_id)
    if result == 'DELETE 0':
        raise HTTPException(404, 'Pin not found')


async def answer_taught(pool, question, doc_ids):
    if not doc_ids or not re.search(r'\b(how many|count|number of)\b', question, re.I):
        return None
    rows = await pool.fetch('select * from taught_symbols where doc_id=any($1::text[]) order by created_at', doc_ids)
    return taught_answer(question, doc_ids, [record(r) for r in rows])
