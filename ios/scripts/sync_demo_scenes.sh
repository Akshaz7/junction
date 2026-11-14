#!/usr/bin/env bash
# Refresh the two licensed offline demos. Optional paths support local validation.
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"
python3 - "${1:-$script_dir/../../artifacts}" "${2:-$script_dir/../Hologram/Resources/DemoScenes}" <<'PY'
import json
from pathlib import Path
import shutil
import sys

artifacts, destination = map(Path, sys.argv[1:])
doc_ids = ("ifc_bench__ac20-arc", "cubicasa5k__colorful-11397")
filenames = ("scene.usdz", "scene.json", "doc.json")
total = 0
# Validate both documents before changing any bundled resources.
for doc_id in doc_ids:
    source = artifacts / doc_id
    scene = json.loads((source / "scene.json").read_text())
    doc = json.loads((source / "doc.json").read_text())
    if scene.get("publishable") is not True:
        sys.exit(f"Refusing non-publishable scene: {doc_id}")
    if scene.get("doc_id") != doc_id or doc.get("doc_id") != doc_id:
        sys.exit(f"Document ID mismatch: {doc_id}")
    if not doc.get("credit") or not doc.get("licence"):
        sys.exit(f"Missing licence or credit: {doc_id}")
    total += sum((source / name).stat().st_size for name in filenames)
if total >= 30_000_000:
    sys.exit(f"Demo resources exceed the 30 MB limit: {total} bytes")
for doc_id in doc_ids:
    target = destination / doc_id
    target.mkdir(parents=True, exist_ok=True)
    for name in filenames:
        shutil.copy2(artifacts / doc_id / name, target / name)
print(f"Synced {len(doc_ids)} demo scenes: {total:,} bytes ({total / 1_000_000:.2f} MB)")
PY
