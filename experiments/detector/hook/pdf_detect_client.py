"""Client for junction-det (run with an interpreter that has `modal`): pdf page -> JSON on the last stdout line.
usage: pdf_detect_client.py <pdf> <page_index> <m_per_pt json|null>"""
import json
import sys

import modal

pdf, page, mpt = sys.argv[1], int(sys.argv[2]), json.loads(sys.argv[3])
det = modal.Cls.from_name("junction-det", "Detector")()
r = det.detect.remote(open(pdf, "rb").read(), page, mpt)
print(json.dumps(r))
