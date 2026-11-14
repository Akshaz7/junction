"""The bounded reader preserves page-pixel coordinates and only crops ruled edge strips."""
import numpy as np
import pytest
from PIL import Image, ImageDraw

from pipeline import raster_walls


def sheet(size=(6000, 4200), title=True):
    image = Image.new('L', size, 255)
    d = ImageDraw.Draw(image)
    d.rectangle((350, 350, 4500, 3600), outline=0, width=70)
    d.line((1700, 350, 1700, 3600), fill=0, width=60)
    if title:
        for y in range(2700, 4100, 180):
            d.line((5000, y, 5900, y), fill=0, width=8)
        for x in (5000, 5450, 5900):
            d.line((x, 2700, x, 4100), fill=0, width=8)
    return np.asarray(image)


def test_large_sheet_downsamples_crops_title_and_restores_coordinates():
    image = sheet()
    original = image.copy()
    result = raster_walls.read(image, .003)
    assert result is not None
    assert max(result['working_shape']) <= raster_walls.MAX_SIDE
    assert result['crop_px'][2] < 5000
    bounds = result['floor'].bounds
    assert 300 < bounds[0] < 400 and 3500 < bounds[3] < 3700
    assert np.array_equal(image, original)


def test_does_not_crop_a_second_floor_plan():
    image = Image.new('L', (1600, 1000), 255)
    d = ImageDraw.Draw(image)
    for x in (60, 1180):
        d.rectangle((x, 70, x + 340, 920), outline=0, width=16)
    result = raster_walls.read(np.asarray(image), .01)
    assert result is not None
    assert result['crop_px'] == [0, 0, 1600, 1000]
    assert max(p.bounds[2] for p in result['walls']) > 1500


def test_small_right_hand_plan_with_only_two_border_lines_is_not_a_title_block():
    image = Image.new('L', (1600, 1000), 255)
    d = ImageDraw.Draw(image)
    d.rectangle((60, 70, 1140, 920), outline=0, width=16)
    d.rectangle((1300, 70, 1520, 920), outline=0, width=16)
    result = raster_walls.read(np.asarray(image), .01)
    assert result['crop_px'] == [0, 0, 1600, 1000]


@pytest.mark.parametrize('mpp', [0, -1, float('nan')])
def test_invalid_scale_is_not_processed(mpp):
    assert raster_walls.read(np.full((100, 100), 255, np.uint8), mpp) is None


def test_legacy_float_input_matches_uint8_without_modifying_input():
    image = sheet(size=(6000, 4200))[::4, ::4].copy()
    floating = image.astype(float)
    byte_result = raster_walls.read(image, .012)
    float_result = raster_walls.read(floating, .012)
    assert np.array_equal(floating, image)
    assert byte_result['floor'].symmetric_difference(float_result['floor']).area < 1e-5


def test_blank_page_has_no_walls():
    assert raster_walls.read(np.full((600, 800), 255, np.uint8), .01) is None
