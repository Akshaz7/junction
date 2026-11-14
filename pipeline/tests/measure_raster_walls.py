"""Measure raster reader time and process peak RSS, without changing source artifacts.

Run with PYTHONPATH=. scripts/heavy.sh .venv/bin/python pipeline/tests/measure_raster_walls.py [--image PAGE.png --mpp SCALE].
Without --image, uses a generated-for-demo 6000 px sheet containing wall fills and a ruled title strip.
"""
import argparse
import json
import resource
import sys
from time import perf_counter

import numpy as np
from PIL import Image, ImageDraw
from pipeline import raster_walls

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--image')
ap.add_argument('--mpp', type=float, default=.003)
args = ap.parse_args()
if args.image:
    import cv2
    # Decode directly as grayscale, avoiding a full-resolution RGBA intermediate.
    source = cv2.imread(args.image, cv2.IMREAD_GRAYSCALE)
    factor = 6000 / max(source.shape)
    arr = cv2.resize(source, (round(source.shape[1] * factor), round(source.shape[0] * factor)), interpolation=cv2.INTER_AREA)
    del source
    mpp = args.mpp / factor
else:
    im = Image.new('L', (6000, 4200), 255)
    draw = ImageDraw.Draw(im)
    draw.rectangle((350, 350, 4500, 3600), outline=0, width=70)
    for x in (1700, 3100):
        draw.line((x, 350, x, 3600), fill=0, width=60)
    draw.line((350, 1900, 4500, 1900), fill=0, width=60)
    for y in range(2700, 4100, 180):
        draw.line((5000, y, 5900, y), fill=0, width=8)
    for x in (5000, 5450, 5900):
        draw.line((x, 2700, x, 4100), fill=0, width=8)
    mpp = args.mpp
if not args.image:
    arr = np.asarray(im, dtype=np.uint8)
start = perf_counter()
result = raster_walls.read(arr, mpp)
elapsed = perf_counter() - start
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
rss_mb = rss / (1024 ** 2 if sys.platform == 'darwin' else 1024)
print(json.dumps({'source': args.image or 'generated for demo', 'shape': list(arr.shape), 'seconds': round(elapsed, 3),
                  'peak_rss_mb': round(rss_mb, 1), 'wall_count': len(result['walls']) if result else 0,
                  'working_shape': result['working_shape'] if result else None,
                  'crop_px': result['crop_px'] if result else None}))
if not args.image:
    assert result is not None, 'reader found no generated wall fills'
assert elapsed < 15, elapsed
assert rss_mb < 300, rss_mb
