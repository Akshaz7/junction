"""Mixed-view regressions. Fixtures are generated for demo, never real gold."""
import json

import pytest
from PIL import Image

from engine import scale_text
from engine.scales import scale_description
from pipeline.scale_regions import annotate_cached


def word(text, x=10, y=10, w=180, h=20):
    return {'text': text, 'bbox_px': [x, y, x+w, y+h]}


@pytest.mark.parametrize('text,ratio', [('1:48', 48), ('1:64', 64), ('1:200', 200), ('1:37.5', 37.5), ('3/16"=1\'-0"', 64)])
def test_printed_ratio_does_not_need_a_standard_scale(text, ratio):
    assert scale_text.ratio_and_sheet([word(text)])[0] == ratio
    assert scale_text.detect([word(text)], 1000, 800, dpi=254)['m_per_px'] == pytest.approx(ratio*.0001)


def test_separate_views_never_pick_first_sheet_scale():
    words = [word('Plan 1:100'), word('Section 1:20', 600, 500)]
    assert scale_text.ratio_and_sheet(words)[0] is None
    assert scale_text.detect(words, 1000, 800, dpi=254) is None


def test_unmeasured_printed_ratio_is_still_visible():
    assert 'printed 1:100' in scale_description({'ratio': 100, 'm_per_px': None})


def test_room_labels_do_not_suppress_scale_ocr(tmp_path, monkeypatch):
    pm = {'image': {'w': 1000, 'h': 800}, 'items': [], 'scale': {'m_per_px': None}}
    Image.new('RGB', (1000, 800), 'white').save(tmp_path/'page-1.png')
    (tmp_path/'text-1.json').write_text(json.dumps({'source': 'vlm', 'words': [word('Kitchen')]}))
    calls = []
    def ocr(path):
        calls.append(path)
        return [word('Plan 1:100', 20, 700)]
    monkeypatch.setattr('engine.reader.text.ocr_words', ocr)
    result = annotate_cached(pm, tmp_path, allow_ocr=True)
    assert result['regions'][0]['scale']['ratio'] == 100
    assert len(calls) == 1
    annotate_cached(pm, tmp_path, allow_ocr=True)
    assert len(calls) == 1
