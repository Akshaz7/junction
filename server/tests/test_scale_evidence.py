from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI

from server import config, files_routes
from server.scale_evidence import crop_path, persist

NAME = 'scale-1-' + 'a' * 20 + '.png'


def crop(tmp_path):
    from PIL import Image
    path = tmp_path / 'test' / 'evidence' / NAME
    path.parent.mkdir(parents=True)
    Image.new('RGB', (20, 10), 'white').save(path)
    return path


async def test_evidence_endpoint_serves_only_generated_crop_names(tmp_path, monkeypatch):
    path = crop(tmp_path)
    monkeypatch.setattr(config, 'artifacts_dir', lambda: tmp_path)
    app = FastAPI()
    app.include_router(files_routes.router)
    app.dependency_overrides[files_routes._restore] = lambda: None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as c:
        r = await c.get(f'/api/docs/test/evidence/{NAME}')
        assert r.status_code == 200 and r.headers['content-type'] == 'image/png'
        assert r.content == path.read_bytes()
        assert (await c.get('/api/docs/test/evidence/source.png')).status_code == 404


def test_crop_path_blocks_other_files_and_symlink_escapes(tmp_path):
    crop(tmp_path)
    assert crop_path(tmp_path, 'test', NAME)
    assert crop_path(tmp_path, '..', NAME) is None
    assert crop_path(tmp_path, 'test', '../source.png') is None
    assert crop_path(tmp_path, 'test', 'scene.glb') is None
    outside = tmp_path / 'outside.png'; outside.write_bytes(b'x')
    alias = tmp_path / 'test' / 'evidence' / ('scale-2-' + 'b' * 20 + '.png')
    alias.symlink_to(outside)
    assert crop_path(tmp_path, 'test', alias.name) is None


async def test_only_referenced_crops_are_persisted_once(tmp_path):
    path = crop(tmp_path)
    inp = {'source': {'doc_id': 'test', 'page': 1, 'crop': 'test/evidence/' + NAME}}
    ans = {'reasoning': {'calc': {'steps': [{'inputs': [inp, inp, {'source': {'doc_id': 'test', 'crop': 'test/evidence/../../secret'}}]}]}}}
    pool = AsyncMock()
    await persist(pool, ans, tmp_path)
    assert pool.execute.await_count == 1
    args = pool.execute.await_args.args
    assert args[1:] == ('test', 'evidence/' + NAME, 'image/png', path.read_bytes(), path.stat().st_size)
