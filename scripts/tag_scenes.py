#!/usr/bin/env python3
"""LEAD glue (CONTRACT 5.11): write the engine's stable tags into every artifacts/<doc_id>/scene.json.

The tag rule lives in engine.scene_cmds.tags (ENGINE owns it); this script only stores the result so the
web 3D viewer, the 2D overlay and the iOS AR screen all show the same W1/D1/... labels the engine uses.
Also reports plan-map items that the engine can cite but that are missing from scene.json.

Usage: .venv/bin/python scripts/tag_scenes.py [--check] [doc_id ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.scene_cmds import tags  # noqa: E402
from engine.solvers.data import load_doc  # noqa: E402

ART = ROOT / "artifacts"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    ids = [a for a in argv if not a.startswith("--")] or sorted(p.parent.name for p in ART.glob("*/scene.json"))
    total_tagged = total_missing = docs = 0
    for doc_id in ids:
        sp = ART / doc_id / "scene.json"
        if not sp.exists():
            continue
        doc = load_doc(doc_id, ART)
        if doc is None:
            continue
        scene = json.loads(sp.read_text(encoding="utf-8"))
        items = scene.get("items")
        if not isinstance(items, dict):
            print(f"{doc_id}: scene.json items is not a dict; skipped")
            continue
        tg = tags(doc)
        missing = [i for i in tg if i not in items]
        changed = 0
        for item_id, tag in tg.items():
            it = items.get(item_id)
            if isinstance(it, dict) and it.get("tag") != tag:
                it["tag"] = tag
                changed += 1
        docs += 1
        total_tagged += sum(1 for v in items.values() if isinstance(v, dict) and v.get("tag"))
        total_missing += len(missing)
        if missing:
            print(f"{doc_id}: {len(missing)} taggable items missing from scene.json (e.g. {missing[:3]})")
        if changed and not check:
            sp.write_text(json.dumps(scene, ensure_ascii=False), encoding="utf-8")
    print(f"docs={docs} tagged_items={total_tagged} missing_from_scene={total_missing}{' (check only)' if check else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
