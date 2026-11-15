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


@pytest.mark.parametrize('rotation', [0,90,180,270])
def test_pdf_crop_rotation_matches_actual_render_pixels(tmp_path, rotation):
    from engine.sheet_align import load_pdf_page
    import pypdfium2 as pdfium
    # Tiny original test PDF, generated for demo; no repository drawing is copied.
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /CropBox [100 100 500 700] /Rotate {rotation} /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>'.encode(),
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    content=b'BT /F1 12 Tf 200 600 Td (ROOMA) Tj ET'
    objects.append(b'<< /Length '+str(len(content)).encode()+b' >>\nstream\n'+content+b'\nendstream')
    raw=b'%PDF-1.4\n'; offsets=[0]
    for i,obj in enumerate(objects,1): offsets.append(len(raw)); raw+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    xref=len(raw);raw+=b'xref\n0 6\n0000000000 65535 f \n'+b''.join(f'{o:010} 00000 n \n'.encode() for o in offsets[1:])
    raw+=f'trailer << /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()
    pdf=tmp_path/'generated.pdf'; pdf.write_bytes(raw)
    with pdfium.PdfDocument(pdf) as doc:
        p=doc[0]; bitmap=p.render(scale=1); image=np.asarray(bitmap.to_pil().convert('L')); bitmap.close(); p.close()
    data=load_pdf_page(pdf,image_size=(image.shape[1],image.shape[0]))
    box=next(w['bbox_px'] for w in data['words'] if w['text']=='ROOMA')
    ys,xs=np.where(image<100)
    # Glyph ink must fall inside the positioned text box (allow font raster rounding).
    assert box[0]-2 <= xs.min() <= xs.max() <= box[2]+2
    assert box[1]-2 <= ys.min() <= ys.max() <= box[3]+2
