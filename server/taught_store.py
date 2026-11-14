"""Persist manual items as normal plan-map artifacts under a document lock."""
from __future__ import annotations
import json
import os
import uuid
from pathlib import Path

from engine.taught_items import project
from . import config


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def invalidate(doc_id):
    # Most readers use plan-map mtimes. Project search also maintains a disk index.
    from engine.project_index import upsert_doc
    upsert_doc(doc_id, config.artifacts_dir())


def decode(row):
    row = dict(row)
    for key in ('matches', 'template_bbox'):
        if isinstance(row.get(key), str):
            row[key] = json.loads(row[key])
    return row


async def materialize(c, doc_id, page, image):
    """Caller holds the per-document advisory transaction lock.

    doc_artifacts and the label row commit together. Disk is a replaceable cache;
    restore_materialized refreshes it before document reads after a restart.
    """
    directory = config.artifacts_dir() / doc_id
    name = f'planmap-{page}.json'
    stored = await c.fetchval('select data from doc_artifacts where doc_id=$1 and name=$2', doc_id, name)
    if stored:
        plan = json.loads(bytes(stored))
    else:
        path = directory / name
        plan = json.loads(path.read_text()) if path.is_file() else {'doc_id': doc_id, 'items': []}
    symbols = [decode(r) for r in await c.fetch('select * from taught_symbols where doc_id=$1 and manual_selection order by created_at, id', doc_id)]
    output = project(plan, symbols, page, image)
    data = json.dumps(output, ensure_ascii=False).encode()
    await c.execute('insert into doc_artifacts(doc_id,name,content_type,data,size) values($1,$2,$3,$4,$5) '
                    'on conflict(doc_id,name) do update set data=excluded.data,size=excluded.size,created_at=now()',
                    doc_id, name, 'application/json', data, len(data))
    return directory / name, output


async def restore_materialized(pool, doc_id):
    """Refresh only manual plan maps; do not overwrite ordinary source artifacts."""
    from asyncpg import UndefinedColumnError, UndefinedTableError
    try:
        async with pool.acquire() as c:
            async with c.transaction():
                await c.execute('select pg_advisory_xact_lock(hashtext($1))', 'taught:' + doc_id)
                rows = await c.fetch("select name,data from doc_artifacts where doc_id=$1 and name like 'planmap-%'", doc_id)
                for row in rows:
                    plan = json.loads(bytes(row['data']))
                    if plan.get('manual_labels'):
                        path = config.artifacts_dir() / doc_id / row['name']
                        data = bytes(row['data'])
                        if not path.exists() or path.read_bytes() != data:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            atomic_json(path, plan)
    except (UndefinedColumnError, UndefinedTableError):
        pass  # Rolling deployment before migrations: ordinary reads still work.
