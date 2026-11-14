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
