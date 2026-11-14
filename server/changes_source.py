"""Where change lists come from (S-07). Pluggable so E-11's engine output replaces the synthetic truth.

CHANGE_SOURCE=truth|engine
  truth  : DATA's synthetic revisions, artifacts/revisions/<doc_id>/{v1,v2}/ + truth_changes.json
           (payload says "source": "truth", "generated_for_demo": true).
  engine : engine.changes.compare(doc_id, revision_dir) -> {"changes": [...], "image": {"w","h"}}
           with each change shaped like a truth_changes.json entry (type added|removed|modified, kind,
           description, v1_item, v2_item, bbox_px_v1, bbox_px_v2, optional field/old/new/size_m/width_m).
Default: engine when engine.changes.compare exists, else truth.
"""
import importlib
import json
import os
import re
from pathlib import Path

from . import config


def revisions_dir() -> Path:
    return config.artifacts_dir() / "revisions"


def source_name() -> str:
    want = os.environ.get("CHANGE_SOURCE", "").strip().lower()
    if want in ("truth", "engine"):
        return want
    try:
        return "engine" if hasattr(importlib.import_module("engine.changes"), "compare") else "truth"
    except Exception:  # noqa: BLE001
        return "truth"


def revision_docs() -> list[str]:
    d = revisions_dir()
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if (p / "v1").is_dir() and (p / "v2").is_dir())


def _num(item: str | None) -> str:
    m = re.search(r"(\d+)$", item or "")
    return m.group(1) if m else (item or "?")


def sentence(c: dict) -> str:
    """CONTRACT 5.8 form: 'The area of room 205 reads 47.0 m2 where it read 23.5 m2.'"""
    kind, typ = c.get("kind", "item"), c.get("type")
    if typ == "modified" and c.get("field"):
        n = _num(c.get("v2_item") or c.get("v1_item"))
        unit = " m2" if c["field"] == "area" else ""
        fmt = lambda v: f"{v:.1f}{unit}" if isinstance(v, (int, float)) else f"'{v}'"
        return f"The {c['field']} of {kind} {n} reads {fmt(c.get('new'))} where it read {fmt(c.get('old'))}."
    if typ == "added":
        extra = f" ({c['width_m']} m wide)" if c.get("width_m") else ""
        return f"{kind.capitalize()} {_num(c.get('v2_item'))}{extra} reads present where it read absent."
    if typ == "removed":
        size = c.get("size_m")
        extra = f" ({max(size):.1f} m long)" if size else ""
        return f"{kind.capitalize()} {_num(c.get('v1_item'))}{extra} reads absent where it read present."
    return c.get("description") or f"A {kind} changed."


def _side(c: dict, v: str) -> dict | None:
    item, box = c.get(f"{v}_item"), c.get(f"bbox_px_{v}")
    return {"item_id": item, "bbox_px": box} if (item or box) else None


def _raw(doc_id: str) -> tuple[dict, str]:
    d = revisions_dir() / doc_id
    name = source_name()
    if name == "engine":
        compare = importlib.import_module("engine.changes").compare
        return compare(doc_id, d), "engine"
    return json.loads((d / "truth_changes.json").read_text()), "truth"


def comparison(doc_id: str) -> dict:
    raw, src = _raw(doc_id)
    base = f"/api/docs/{doc_id}/revisions"
    changes = []
    for i, c in enumerate(raw.get("changes", []), 1):
        changes.append({"n": i, "change_id": c.get("change_id", f"c{i}"), "type": c["type"], "kind": c["kind"],
                        "sentence": sentence(c), "description": c.get("description"),
                        "v1": _side(c, "v1"), "v2": _side(c, "v2"),
                        "field": c.get("field"), "old": c.get("old"), "new": c.get("new")})
    return {"doc_id": doc_id, "source": src, "generated_for_demo": bool(raw.get("generated_for_demo")),
            "note": raw.get("note"), "image": raw.get("image"),
            "v1": {"label": "v1", "page_image": f"{base}/v1/page-1.png", "thumb": f"{base}/v1/page-1.thumb.png",
                   "planmap": f"{base}/v1/planmap-1.json"},
            "v2": {"label": "v2", "page_image": f"{base}/v2/page-1.png", "thumb": f"{base}/v2/page-1.thumb.png",
                   "planmap": f"{base}/v2/planmap-1.json"},
            "changes": changes}


def summary(doc_id: str) -> dict:
    c = comparison(doc_id)
    return {"doc_id": doc_id, "source": c["source"], "generated_for_demo": c["generated_for_demo"],
            "n_changes": len(c["changes"]), "headline": c["changes"][0]["sentence"] if c["changes"] else "No changes."}


async def seed_changes(conn) -> int:
    """Insert one `changes` row per revision doc that has none (idempotent). Fires changes.new via the trigger."""
    n = 0
    for doc_id in revision_docs():
        a, b = f"{doc_id}@v1", f"{doc_id}@v2"
        if await conn.fetchval("select 1 from changes where doc_a=$1 and doc_b=$2", a, b):
            continue
        try:
            s = summary(doc_id)
        except Exception as e:  # noqa: BLE001
            print("changes seed skipped", doc_id, repr(e)[:100])
            continue
        await conn.execute("insert into changes (doc_a, doc_b, summary) values ($1,$2,$3::jsonb)", a, b, json.dumps(s))
        n += 1
    return n
