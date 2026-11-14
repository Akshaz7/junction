"""Registration must reject false certainty and map overlay pixels to base pixels."""
import json
import numpy as np
import pytest
from engine.sheet_align import align_sheets, cached_alignment, manual_alignment, provider_alignment


def sheet(points, labels=None, scale=None):
    result = {"image": {"w": 1200, "h": 900}, "words": [
        {"text": text, "bbox_px": [x-2, y-2, x+2, y+2]}
        for text, (x, y) in zip(labels or [f"R{i}" for i in range(len(points))], points)]}
    if scale is not None: result["m_per_px"] = scale
    return result


POINTS = np.array([[100, 100], [800, 120], [200, 600], [1000, 700], [500, 450]], dtype=float)


def test_similarity_direction_scale_rotation_and_outlier():
    matrix = np.array([[1.2, -.2], [.2, 1.2]])
    base = POINTS @ matrix.T + [20, 40]
    base[-1] += [120, 200]
    result = align_sheets(sheet(base, scale=.01), sheet(POINTS))
    assert result["status"] == "aligned"
    assert result["anchor_count"] == 4
    np.testing.assert_allclose(result["matrix"], np.column_stack([matrix, [20, 40]]), atol=1e-8)
    assert result["residual_mm"] < 1e-7


def test_affine_scan_stretch():
    matrix = np.array([[1.2, .05], [.1, .8]])
    result = align_sheets(sheet(POINTS @ matrix.T + [15, 30]), sheet(POINTS), model="affine")
    np.testing.assert_allclose(result["matrix"], np.column_stack([matrix, [15, 30]]), atol=1e-8)


def test_unicode_shared_names_and_repeated_room_labels():
    points = np.vstack([POINTS, [[300, 300], [700, 600]]])
    names = ['Büro 01', 'TOIMISTO', 'RUM 3', 'B305', 'Étage', 'WC', 'WC']
    result = align_sheets(sheet(points+10, names), sheet(points, [n.lower() for n in names]))
    assert result['anchor_count'] == 7


@pytest.mark.parametrize('points', [[], [[1, 1]], [[1, 1], [10, 10]], [[10, 10], [20, 20], [30, 30], [40, 40]]])
def test_insufficient_or_collinear_support_needs_manual(points):
    assert align_sheets(sheet(points), sheet(points))['status'] == 'needs_manual'


def test_unscaled_result_never_claims_mm():
    result = align_sheets(sheet(POINTS), sheet(POINTS))
    assert result['residual_mm'] is None
    assert 'scale unavailable' in result['detail']


def test_manual_two_points_and_degeneracy():
    result = manual_alignment([[10, 20], [10, 120]], [[0, 0], [50, 0]])
    np.testing.assert_allclose(result['matrix'], [[0, -2, 10], [2, 0, 20]], atol=1e-9)
    assert result['residual_mm'] is None
    with pytest.raises(ValueError): manual_alignment([[1, 1], [1, 1]], [[1, 1], [2, 2]])
    with pytest.raises(ValueError): manual_alignment([[1, 1], [2, 2]], [[1, float('nan')], [2, 2]])


def test_cache_invalidates_changed_text_scale_and_options(tmp_path):
    base, overlay = sheet(POINTS), sheet(POINTS)
    a = cached_alignment(base, overlay, cache_dir=tmp_path)
    assert a == cached_alignment(base, overlay, cache_dir=tmp_path)
    base['m_per_px'] = .01
    b = cached_alignment(base, overlay, cache_dir=tmp_path)
    assert b['residual_mm'] is not None
    cached_alignment(base, overlay, cache_dir=tmp_path, model='affine')
    assert len(list(tmp_path.glob('*.json'))) == 3


def test_grid_lines_supply_distributed_crossings():
    data = {'image': {'w': 1200, 'h': 900}, 'words': [
        {'text': 'A', 'bbox_px': [99, 9, 101, 11]}, {'text': 'B', 'bbox_px': [799, 9, 801, 11]},
        {'text': '1', 'bbox_px': [9, 99, 11, 101]}, {'text': '2', 'bbox_px': [9, 699, 11, 701]}],
        'grid_lines': [[100, 0, 100, 850], [800, 0, 800, 850], [0, 100, 1100, 100], [0, 700, 1100, 700]]}
    result = align_sheets(data, data)
    assert result['status'] == 'aligned'
    assert any(a['label'].startswith('grid:') for a in result['anchors'])


def test_provider_adapter_direction_and_scale():
    result = provider_alignment({}, {}, m_per_px=.01, aligner=lambda src, dst: {
        'T': [[2, 0, 10], [0, 2, 20], [0, 0, 1]], 'residual': .5, 'matches': 23})
    assert result['residual_mm'] == 5
    assert result['matrix'][0] == [2, 0, 10]
    assert provider_alignment({}, {}, aligner=lambda a,b: {'T': None})['status'] == 'needs_manual'


def test_bad_image_size_and_model():
    assert align_sheets({}, {})['status'] == 'needs_manual'
    with pytest.raises(ValueError): align_sheets(sheet(POINTS), sheet(POINTS), model='projective')
