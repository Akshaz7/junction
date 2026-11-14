import asyncio
import json
from pathlib import Path

import asyncpg
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from server import config
from server.app import app
from server.migrate import apply_migrations


@pytest.fixture
def client(schema_url, tmp_path, monkeypatch):
    async def migrate():
        c = await asyncpg.connect(config.database_url())
        await apply_migrations(c)
        await c.close()
    asyncio.run(migrate())
    d = tmp_path / 'unseen-sheet'
    d.mkdir()
    Image.new('RGB', (200, 100), 'white').save(d / 'page-1.png')
    Image.new('RGB', (200, 100), 'white').save(d / 'page-2.png')
    (d / 'planmap-1.json').write_text(json.dumps({'items': [{'kind': 'room', 'label': 'Room from polygon', 'polygon_px': [[0,0],[100,0],[100,100],[0,100]]}]}))
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    async def ensure(_): pass
    monkeypatch.setattr('server.artifact_store.ensure_doc', ensure)
    monkeypatch.setattr('server.markup_routes.find_similar', lambda *a, **kw: {'matches': [{'bbox': [10,10,20,20], 'score': .8}, {'bbox': [120,10,130,20], 'score': .7}]})
    with TestClient(app) as c:
        yield c


def test_teach_review_persist_and_evidence(client):
    base = '/api/docs/unseen-sheet/markup'
    r = client.post(base + '/symbols', json={'name': 'Supply air terminals', 'box': [10,10,20,20]})
    assert r.status_code == 201, r.text
    s = r.json()
    assert s['summary']['pending'] == 2
    assert s['matches'][0]['room'] == 'Room from polygon'
    assert s['matches'][1]['room'] is None
    sid = s['id']
    r = client.patch(base + '/symbols/' + sid, json={'statuses': {'1': 'confirmed', '2': 'rejected'}})
    assert r.status_code == 200
    assert r.json()['summary']['found'] == 1
    assert client.get(base).json()['symbols'][0]['summary']['confirmed'] == 1
    assert client.patch(base + '/symbols/' + sid, json={'statuses': {'made-up': 'confirmed'}}).status_code == 400
    assert client.patch('/api/docs/other-sheet/markup/symbols/' + sid, json={'statuses': {}}).status_code == 404
    assert client.post(base + '/symbols', json={'name': 'SUPPLY AIR TERMINALS', 'box': [10,10,20,20]}).status_code == 409


def test_pins_saved_on_correct_page_listed_deleted(client):
    base = '/api/docs/unseen-sheet/markup'
    p = client.post(base + '/pins', json={'page': 2, 'x': 50, 'y': 60, 'note': 'Check ceiling clash'})
    assert p.status_code == 201
    assert client.get(base + '/pins').json()[0]['page'] == 2
    assert client.get(base + '/pins').json()[0]['n'] == 1
    assert client.delete(base + '/pins/' + p.json()['id']).status_code == 204
    assert client.get(base + '/pins').json() == []
    assert client.post(base + '/pins', json={'x': 999, 'y': 10, 'note': 'Outside'}).status_code == 400


def test_invalid_requests(client):
    base = '/api/docs/unseen-sheet/markup'
    for box in ([10,10,5,20], [-1,0,4,4], [0,0,201,3], [0,0,200,100]):
        assert client.post(base + '/symbols', json={'name': 'dot', 'box': box}).status_code in (400, 422)
    assert client.post(base + '/symbols', json={'name': ' ', 'box': [10,10,20,20]}).status_code == 422
    assert client.get(base + '?page=0').status_code == 400
    assert client.post(base + '/pins', json={'x': 1, 'y': 1, 'note': ' '}).status_code == 422
    assert client.get('/api/docs/missing/markup').status_code == 404
