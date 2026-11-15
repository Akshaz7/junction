"""Client for junction-det (run with an interpreter that has `modal`): pdf page -> JSON on the last stdout line.
usage: pdf_detect_client.py <pdf> <page_index> <m_per_pt json|null>"""
import json
import sys

import modal

pdf, page, mpt = sys.argv[1], int(sys.argv[2]), json.loads(sys.argv[3])
det = modal.Cls.from_name("junction-det", "Detector")()
import os
run = os.environ.get("PDF_DETECT_RUN") or None  # local test: pick the Modal run (y11l, y11l_clean, y11l_mix_a, ...)
min_conf = float(os.environ.get("PDF_DETECT_MIN_CONF", "0.80"))  # Awais's door threshold; <=0 = the run's own thresholds
min_conf = min_conf if min_conf > 0 else None
data = open(pdf, "rb").read()
r = det.detect.remote(data, page, mpt, min_conf, run) if run else det.detect.remote(data, page, mpt, min_conf)
print(json.dumps(r))
