"""Accuracy note of a PDF-to-3D conversion (quality block written at ingest) copied into the evidence card."""
from __future__ import annotations

import json
from pathlib import Path


def _block(path: Path):
    try:
        q = json.loads(path.read_text()).get("quality")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(q, dict) or q.get("error"):
        return None
    summary = q.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None
    out = {"summary": summary.strip()}
    if isinstance(q.get("score"), (int, float)):
        out["score"] = q["score"]
    return out


def for_doc(doc_id: str, root: Path) -> dict | None:
    """{summary, score?} from scene.json, else the first plan map that has one; None when absent or errored."""
    d = Path(root) / doc_id
    if not d.is_dir():
        return None
    q = _block(d / "scene.json")
    for p in ([] if q else sorted(d.glob("planmap-[0-9]*.json"))):
        q = _block(p)
        if q:
            break
    return q


def attach(res: dict, root: Path) -> None:
    """Add reasoning.quality for the first cited document; never raises."""
    try:
        r = res.get("reasoning")
        ids = res.get("doc_ids") or []
        if not r or not ids or r.get("quality"):
            return
        q = for_doc(ids[0], root)
        if q:
            r["quality"] = q
    except Exception:  # noqa: BLE001
        pass
