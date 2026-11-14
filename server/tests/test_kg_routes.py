"""KG API without a database: exercise the real builder with isolated artifacts."""
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.tests.test_kg_core import item, plan
from server import kg_routes


@pytest.fixture
def kg_client(tmp_path, monkeypatch):
    pid = str(uuid.uuid4())
    plan(tmp_path,'a',[item('r','room',[0,0,100,100]),item('d','door',[10,10,20,20])])
    async def pool():
        return object()
    async def project(pool,p,refresh=False):
        return {'id':str(p),'name':'Building','docs':[{'doc_id':'a','role':'plan','level':'Ground floor'}]}
    monkeypatch.setattr(kg_routes,'_pool',pool)
    monkeypatch.setattr(kg_routes,'_project',project)
    monkeypatch.setattr(kg_routes.config,'artifacts_dir',lambda:tmp_path)
    app=FastAPI()
    app.include_router(kg_routes.router)
    with TestClient(app) as client:
        yield client,pid


def test_api(kg_client):
    c,pid=kg_client
    base=f'/api/projects/{pid}/graph'
    g=c.get(base+'?depth=full').json()
    assert g['stats']['nodes'] == 5
    assert c.get(base+'/stats').json() == g['stats']
    d=next(n for n in g['nodes'] if n['kind']=='door')
    result=c.get(base+'/node/'+d['id']).json()
    assert result['node']==d and result['neighbours'] and result['path_to_project'][-1].startswith('project:')
    assert c.get(base+'/node/absent').status_code==404
    assert c.get(base+'?depth=invalid').status_code==422
    assert c.get('/api/projects/no-uuid/graph').status_code==404
    assert not any(n['kind']=='door' for n in c.get(base).json()['nodes'])
    assert len(c.get(base+'?depth=full&doc_id=unknown').json()['nodes'])==1
