import asyncio
from unittest.mock import AsyncMock
import numpy as np
import pytest
from fastapi import HTTPException
from server import sheet_align_routes as routes


@pytest.fixture
def sources(monkeypatch):
    monkeypatch.setattr(routes, '_document', AsyncMock(side_effect=lambda doc: {'doc_id': doc}))
    monkeypatch.setattr(routes.artifact_store, 'ensure_doc', AsyncMock())
    points = [[100,100],[800,120],[200,600],[1000,700]]
    sheet = {'image': {'w': 1200, 'h': 900}, 'words': [{'text': f'R{i}', 'bbox_px': [x,y,x+1,y+1]} for i,(x,y) in enumerate(points)]}
    monkeypatch.setattr(routes, '_load_sheet', lambda record, page: sheet)


def test_alignment_endpoint_returns_image_pixel_coordinates(sources):
    result = asyncio.run(routes.sheet_align(routes.AlignmentRequest(base_doc_id='base', overlay_doc_id='other')))
    assert result['status'] == 'aligned'
    assert result['base_image'] == {'w': 1200, 'h': 900}
    assert result['anchor_count'] == 4


def test_manual_endpoint_rejects_points_outside_page(sources):
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.sheet_align(routes.AlignmentRequest(base_doc_id='base', overlay_doc_id='other', base_points=[(1,1),(2000,20)], overlay_points=[(1,1),(20,20)])))
    assert error.value.status_code == 422


def test_manual_endpoint_has_no_fake_precision(sources):
    result = asyncio.run(routes.sheet_align(routes.AlignmentRequest(base_doc_id='base', overlay_doc_id='other', base_points=[(10,10),(100,100)], overlay_points=[(1,1),(10,10)])))
    assert result['status'] == 'manual'
    assert result['residual_mm'] is None


@pytest.mark.parametrize('doc', ['../other', '..', '/tmp/a'])
def test_invalid_document_rejected_before_loading(doc, sources):
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.sheet_align(routes.AlignmentRequest(base_doc_id=doc, overlay_doc_id='other')))
    assert error.value.status_code == 400


def test_missing_image_is_actionable(sources, monkeypatch):
    def missing(record, page): raise ValueError('This page has no image yet.')
    monkeypatch.setattr(routes, '_load_sheet', missing)
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.sheet_align(routes.AlignmentRequest(base_doc_id='base', overlay_doc_id='other')))
    assert error.value.status_code == 422


def test_page_adapter_handles_database_json_string_files(tmp_path, monkeypatch):
    import json
    from PIL import Image
    monkeypatch.setattr(routes.config, 'artifacts_dir', lambda: tmp_path)
    doc=tmp_path/'source'; doc.mkdir()
    Image.new('RGB',(100,80),'white').save(doc/'page-1.png')
    (doc/'text-1.json').write_text(json.dumps({'words':[{'text':'Room A','bbox':[10,10,30,20]}]}))
    monkeypatch.setattr(routes.docmeta_store, 'source_file', lambda record: None if isinstance(record['files'], dict) else (_ for _ in ()).throw(TypeError()))
    page=routes._load_sheet({'doc_id':'source','files':'{"pdf":"source.pdf"}'},1)
    assert page['words'][0]['bbox_px']==[10,10,30,20]


@pytest.mark.parametrize('case, expected', [('dimension', .01), ('conflict', None), ('prior', None)])
def test_page_adapter_uses_common_scale_policy(tmp_path, monkeypatch, case, expected):
    import json
    from PIL import Image
    from engine.scale_proof import candidate, operand
    monkeypatch.setattr(routes.config, 'artifacts_dir', lambda: tmp_path)
    monkeypatch.setattr(routes.docmeta_store, 'source_file', lambda record: 'generated-for-demo.pdf')
    # A native PDF ratio must not override ambiguous or estimated plan-map scale.
    monkeypatch.setattr('engine.sheet_align.load_pdf_page', lambda *args: {'words': [], 'm_per_px': .2})
    folder = tmp_path / 'generated-for-demo'; folder.mkdir()
    Image.new('RGB', (100, 80), 'white').save(folder / 'page-1.png')
    scale = {'method': 'door-prior', 'm_per_px': .02}
    items = []
    if case == 'dimension':
        items = [{'kind': 'dimension', 'label': '900 mm', 'bbox_px': [0, 0, 90, 20],
                  'props': {'dimension_line_px': [[0, 0], [90, 0]]}}]
    elif case == 'conflict':
        scale = {'method': 'dimension', 'm_per_px': .01, 'candidates': [
            candidate(method, value, 'recorded candidate', [operand('recorded reading', value, 'm/px', {'definition': 'generated for demo'})])
            for method, value in [('dimension', .01), ('ratio-dpi', .02)]]}
    (folder / 'planmap-1.json').write_text(json.dumps({'items': items, 'scale': scale}))
    result = routes._load_sheet({'doc_id': folder.name}, 1)
    if expected is None:
        assert 'm_per_px' not in result
    else:
        assert result['m_per_px'] == pytest.approx(expected)
