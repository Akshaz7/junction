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
    (d / 'planmap-1.json').write_text(json.dumps({'items': [{'item_id': 'room-1', 'conf': 1, 'kind': 'room', 'label': 'Room from polygon', 'polygon_px': [[0,0],[100,0],[100,100],[0,100]]}]}))
    monkeypatch.setenv('ARTIFACTS_DIR', str(tmp_path))
    async def ensure(_): pass
    monkeypatch.setattr('server.artifact_store.ensure_doc', ensure)
    def no_matching(*a, **kw): raise AssertionError('Manual labels must never run a matcher')
    monkeypatch.setattr('engine.symbols.find_similar', no_matching)
    with TestClient(app) as c:
        yield c


def test_teach_review_persist_and_evidence(client):
    base = '/api/docs/unseen-sheet/markup'
    r = client.post(base + '/symbols', json={'name': 'Supply air terminals', 'box': [10,10,20,20]})
    assert r.status_code == 201, r.text
    s = r.json()
    assert s['summary']['pending'] == 0
    assert s['canonical_kind'] == 'terminal'
    assert s['manual_selection'] is True
    assert len(s['matches']) == 1
    assert s['matches'][0]['bbox'] == [10,10,20,20]
    assert s['matches'][0]['room'] == 'Room from polygon'
    sid = s['id']
    assert client.post(base + '/symbols', json={'name': 'Supply air terminals', 'box': [120,10,130,20]}).status_code == 201
    plan = client.get('/api/docs/unseen-sheet/planmap/1').json()
    assert sum(i['kind'] == 'terminal' for i in plan['items']) == 2
    r = client.patch(base + '/symbols/' + sid, json={'statuses': {'1': 'rejected'}})
    assert r.status_code == 200
    plan = client.get('/api/docs/unseen-sheet/planmap/1').json()
    assert sum(i['kind'] == 'terminal' for i in plan['items']) == 1
    assert client.patch(base + '/symbols/' + sid, json={'statuses': {'1': 'pending'}}).status_code == 422
    assert client.patch(base + '/symbols/' + sid, json={'statuses': {'made-up': 'confirmed'}}).status_code == 400
    assert client.patch('/api/docs/other-sheet/markup/symbols/' + sid, json={'statuses': {}}).status_code == 404
    graph = client.get('/api/docs/unseen-sheet/knowledge-graph').json()
    marked = [n for n in graph['nodes'] if n['method'] == 'user_label']
    assert len(marked) == 1 and marked[0]['confidence'] == 1


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
    for box in ([10,10,5,20], [-1,0,4,4], [0,0,201,3]):
        assert client.post(base + '/symbols', json={'name': 'dot', 'box': box}).status_code in (400, 422)
    assert client.post(base + '/symbols', json={'name': ' ', 'box': [10,10,20,20]}).status_code == 422
    assert client.get(base + '?page=0').status_code == 400
    assert client.post(base + '/pins', json={'x': 1, 'y': 1, 'note': ' '}).status_code == 422
    assert client.get('/api/docs/missing/markup').status_code == 404


def test_actual_chat_stream_uses_saved_reviewed_boxes(client, monkeypatch):
    async def seed():
        c = await asyncpg.connect(config.database_url())
        await c.execute("insert into documents(doc_id,source,title,kind) values('unseen-sheet','test','Real sheet fixture','raster')")
        await c.close()
    asyncio.run(seed())
    from server import chats_routes
    monkeypatch.setattr(chats_routes, 'ENGINE', chats_routes._real_engine)
    base = '/api/docs/unseen-sheet/markup'
    s = client.post(base + '/symbols', json={'name': 'Supply air terminals', 'box': [10,10,20,20]}).json()
    chat = client.post('/api/chats', json={'doc_id': 'unseen-sheet'}).json()
    r = client.post('/api/chats/' + chat['id'] + '/messages', json={'content': 'How many supply air terminals?', 'doc_ids': ['unseen-sheet']})
    assert r.status_code == 200, r.text
    assert 'event: answer' in r.text, r.text
    data = next(json.loads(line[6:]) for line in r.text.splitlines() if line.startswith('data: ') and 'answer_id' in line)
    assert data['answer']['value'] == 1
    assert data['reasoning']['confidence']['label'] == 'Cross-checked'
    assert 'marked by you' in data['answer']['text_md'].lower()
    assert data['citations'][0]['bbox_px'] == [10,10,20,20]
    saved = client.get('/api/chats/' + chat['id']).json()
    assert saved['messages'][-1]['answer']['answer_id'] == data['answer_id']


def test_tell_stoa_rename_delete_and_restart_restore(client):
    base = '/api/docs/unseen-sheet/markup'
    s = client.post(base+'/symbols',json={'name':'dr','box':[10,10,20,20]}).json()
    changed = client.patch(base+'/symbols/'+s['id'],json={'name':'Odd glyph','canonical_kind':'window'}).json()
    assert changed['name'] == 'Odd glyph' and changed['canonical_kind'] == 'window'
    plan = client.get('/api/docs/unseen-sheet/planmap/1').json()
    assert sum(i['kind'] == 'window' for i in plan['items']) == 1
    assert not any(i['kind'] == 'door' for i in plan['items'])
    # Simulate an outdated disk after restart: the database projection wins.
    path = config.artifacts_dir()/'unseen-sheet'/'planmap-1.json'
    path.write_text('{"items":[]}')
    assert client.get('/api/docs/unseen-sheet/planmap/1').json() == plan
    assert client.delete(base+'/symbols/'+s['id']).status_code == 204
    assert client.get(base).json()['symbols'] == []
    assert not any(i.get('source') == 'taught' for i in client.get('/api/docs/unseen-sheet/planmap/1').json()['items'])
    path.write_text(json.dumps(plan))
    assert not any(i.get('source') == 'taught' for i in client.get('/api/docs/unseen-sheet/planmap/1').json()['items'])


def test_concurrent_marks_are_not_lost_and_same_box_counts_once(client):
    from concurrent.futures import ThreadPoolExecutor
    url = '/api/docs/unseen-sheet/markup/symbols'
    with ThreadPoolExecutor(2) as executor:
        responses = list(executor.map(lambda b: client.post(url,json={'name':'Tür','box':b}), [[10,10,20,20],[40,40,50,50]]))
    assert all(r.status_code == 201 for r in responses)
    assert client.post(url,json={'name':'door','box':[10,10,20,20]}).status_code == 201
    plan = client.get('/api/docs/unseen-sheet/planmap/1').json()
    doors = [i for i in plan['items'] if i['kind'] == 'door']
    assert len(doors) == 2
    assert sorted(len(i['props']['user_labels']) for i in doors) == [1,2]
