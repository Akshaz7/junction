"""Write artifacts/<doc>/piping.json for every dataset IFC that has pipe/flow segments.
  .venv/bin/python deploy/backfill_piping.py            # all docs with an ifc source
Needs ifcopenshell; one file at a time (run via scripts/heavy.sh)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from server.ingest_job import _has_piping, _piping  # noqa: E402

n = 0
for d in sorted((ROOT / "artifacts").glob("*/doc.json")):
    doc = json.loads(d.read_text())
    ifc = (doc.get("files") or {}).get("ifc")
    if doc.get("kind") != "ifc" or not ifc or not (d.parent / "elements.json").is_file():
        continue
    src = next((c for c in (ROOT / ifc, ROOT / "data/full/junction-dataset" / ifc) if c.is_file()), None)
    if src is None or not _has_piping(src):
        continue
    try:
        _piping(d.parent.name, d.parent, src)
        print("ok", d.parent.name, (d.parent / "piping.json").is_file())
        n += 1
    except Exception as e:  # noqa: BLE001
        print("FAIL", d.parent.name, str(e)[:120])
print(n, "docs")
