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

from engine.symbol_teach import room_for, summary
from engine.taught_items import canonical_kind, ALIASES
from . import taught_store
from . import artifact_store, config, db

router = APIRouter(prefix='/api')


class Selection(BaseModel):
    page: int = Field(default=1, ge=1, le=100000)
    box: tuple[float, float, float, float]
    name: str = Field(min_length=1, max_length=160)
    note: str = Field(default='', max_length=4000)
    project_id: str | None = Field(default=None, max_length=160)
    canonical_kind: str | None = None

    @field_validator('canonical_kind')
    @classmethod
    def known_kind(cls, value):
        if value == 'stair':
            return 'stairs'
        if value is not None and value not in ALIASES:
            raise ValueError('Unknown standard item kind')
        return value

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
    statuses: dict[str, Literal['confirmed', 'rejected']] = Field(default_factory=dict, max_length=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=4000)
    canonical_kind: str | None = None

    @field_validator('name')
    @classmethod
    def name_nonblank(cls, value):
        return Selection.valid_name(value) if value is not None else None

    @field_validator('canonical_kind')
    @classmethod
    def kind_valid(cls, value):
        return Selection.known_kind(value)


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
        raise HTTPException(503, 'Saved notes and labels are temporarily unavailable. Try again shortly.')
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
    words = text if isinstance(text, list) else text.get('words', text.get('items', [])) if isinstance(text, dict) else []
    words = [w for w in words if isinstance(w, dict) and isinstance(w.get('text'), str) and isinstance(w.get('bbox_px'), (list, tuple)) and len(w['bbox_px']) == 4] if isinstance(words, list) else []
    plan = read(f'planmap-{page}.json', {})
    rooms = [i for i in plan.get('items', []) if isinstance(i, dict) and i.get('kind') == 'room'] if isinstance(plan, dict) else []
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
    symbols = [record(r) for r in await pool.fetch('select * from taught_symbols where doc_id=$1 and manual_selection order by created_at', doc_id)]
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
    if body.box[2] > w or body.box[3] > h:
        raise HTTPException(400, 'Select one item inside the page')
    ctx = await asyncio.to_thread(context, image, body.page)
    matches = [{'id': '1', 'bbox': list(body.box), 'score': 1.0, 'status': 'confirmed',
                'room': room_for(body.box, ctx['rooms'])}]
    async with pool.acquire() as c:
        async with c.transaction():
            await c.execute('select pg_advisory_xact_lock(hashtext($1))', 'taught:' + doc_id)
            r = await c.fetchrow('insert into taught_symbols(doc_id, name, note, template_bbox, page, matches, canonical_kind, manual_selection) '
                                'values($1,$2,$3,$4::jsonb,$5,$6::jsonb,$7,true) returning *',
                                doc_id, body.name, body.note, json.dumps(list(body.box)), body.page, json.dumps(matches),
                                body.canonical_kind or canonical_kind(body.name))
            path, plan = await taught_store.materialize(c, doc_id, body.page, {'w': w, 'h': h})
            taught_store.atomic_json(path, plan)
    await asyncio.to_thread(taught_store.invalidate, doc_id)
    return {**record(r), 'method': 'user_label'}


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
            await c.execute('select pg_advisory_xact_lock(hashtext($1))', 'taught:' + doc_id)
            row = await c.fetchrow('select * from taught_symbols where id=$1 and doc_id=$2 for update', identifier(symbol_id), doc_id)
            if not row:
                raise HTTPException(404, 'Label not found')
            r = record(row)
            if not r.get('manual_selection'):
                raise HTTPException(409, 'Mark this item individually to save a manual label')
            if set(body.statuses) - {m['id'] for m in r['matches']}:
                raise HTTPException(400, 'Unknown match')
            for m in r['matches']:
                if m['id'] in body.statuses:
                    m['status'] = body.statuses[m['id']]
            name = body.name if body.name is not None else r['name']
            kind = (body.canonical_kind or canonical_kind(name)) if {'name', 'canonical_kind'} & body.model_fields_set else r.get('canonical_kind')
            row = await c.fetchrow('update taught_symbols set matches=$1::jsonb,name=$3,note=$4,canonical_kind=$5 where id=$2 returning *',
                                   json.dumps(r['matches']), identifier(symbol_id), name, body.note if body.note is not None else r['note'], kind)
            path, plan = await taught_store.materialize(c, doc_id, r['page'], None)
            taught_store.atomic_json(path, plan)
    await asyncio.to_thread(taught_store.invalidate, doc_id)
    return record(row)


@router.delete('/docs/{doc_id}/markup/symbols/{symbol_id}', status_code=204)
async def delete_symbol(doc_id: str, symbol_id: str):
    doc_dir(doc_id)
    pool = await pool_required()
    async with pool.acquire() as c:
        async with c.transaction():
            await c.execute('select pg_advisory_xact_lock(hashtext($1))', 'taught:' + doc_id)
            row = await c.fetchrow('delete from taught_symbols where id=$1 and doc_id=$2 and manual_selection returning page', identifier(symbol_id), doc_id)
            if row is None:
                raise HTTPException(404, 'Marked item not found')
            path, plan = await taught_store.materialize(c, doc_id, row['page'], None)
            taught_store.atomic_json(path, plan)
    await asyncio.to_thread(taught_store.invalidate, doc_id)


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
    for doc_id in doc_ids:
        await taught_store.restore_materialized(pool, doc_id)
    # All answers use the standard item index, including scene edits and filters.
    return None
