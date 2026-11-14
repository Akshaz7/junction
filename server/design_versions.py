"""Save 3D edits as a new version of a document, and compare any two versions (table design_versions).

  POST /api/docs/{doc_id}/versions                  {removed, moved, materials, parent?, chat_id?} -> new version n
  GET  /api/docs/{doc_id}/versions                  -> [{n: 0, label: "Original"}, {n: 1, ...}, ...]
  GET  /api/docs/{doc_id}/versions/{n}/pages/{p}/image   the page with that version's edits drawn in (PNG)
Feed / comparison ids (served by /api/changes and /api/changes/{id}): "dv:<doc_id>:<a>-<b>" compares version a with b.

The original (version 0) is never stored or changed: a version is a snapshot of edits over it, linked to its parent.
Every version is labelled as edited (generated from 3D edits, not an issued drawing). Diffs are code over item ids
(engine.design_versions), no model call.
"""
from __future__ import annotations

import asyncio
import io
import json
import re
from collections import OrderedDict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from engine import design_versions as dv

from . import artifact_store, config, db

router = APIRouter(prefix="/api")
SAFE_ID = re.compile(r"^[A-Za-z0-9_.\-]+$")
PAIR = re.compile(r"^dv:([A-Za-z0-9_.\-]+):(\d{1,6})-(\d{1,6})$")
SOURCE = "edit-diff"
EDITED = "edited in 3D (generated from edits, not an issued drawing)"
_docs: dict = {}
_images: OrderedDict = OrderedDict()
MAX_IMAGES = 24


def _doc_dir(doc_id: str):
    if not SAFE_ID.match(doc_id) or doc_id in {".", ".."}:
        raise HTTPException(400, "bad doc_id")
    return config.artifacts_dir() / doc_id


def doc_data(doc_id: str):
    """(items, pages) of a document, cached on the plan map / scene file signature."""
    d = _doc_dir(doc_id)
    files = sorted([*d.glob("planmap-*.json"), d / "scene.json"])
    sig = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in files if p.is_file())
    hit = _docs.get(str(d))
    if hit and hit[0] == sig:
        return hit[1]
    data = dv.load_doc(d)
    _docs[str(d)] = (sig, data)
    return data


def label(n: int, created_at=None) -> str:
    if n == 0:
        return "Original"
    day = created_at.date().isoformat() if created_at is not None else None
    return f"Edited version {n}" + (f" · {day}" if day else "")


def _j(v):
    return json.loads(v) if isinstance(v, str) else v


def _record(r) -> dict:
    return {"doc_id": r["doc_id"], "n": r["n"], "parent": r["parent"], "label": r["label"],
            "edits": _j(r["edits"]), "chat_id": r["chat_id"], "created_at": r["created_at"].isoformat(),
            "edited": True, "generated": EDITED}


ORIGINAL = {"n": 0, "parent": None, "label": "Original", "edits": dv.empty(), "edited": False}


async def _pool():
    pool = await db.get_pool()
    if pool is None:
        raise HTTPException(503, "database unavailable")
    return pool


async def versions_of(pool, doc_id: str) -> list[dict]:
    rows = await pool.fetch("select doc_id, n, parent, label, edits, chat_id, created_at from design_versions "
                            "where doc_id=$1 order by n", doc_id)
    return [dict(ORIGINAL, doc_id=doc_id)] + [_record(r) for r in rows]


@router.get("/docs/{doc_id}/versions")
async def list_versions(doc_id: str):
    _doc_dir(doc_id)
    return {"doc_id": doc_id, "versions": await versions_of(await _pool(), doc_id)}


@router.post("/docs/{doc_id}/versions", status_code=201)
async def save_version(doc_id: str, request: Request):
    """Save the current 3D edits as a new version. The original and earlier versions are never changed."""
    d = _doc_dir(doc_id)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "body must be JSON")
    edits = dv.clean_edits(body if isinstance(body, dict) else None)
    if edits is None:
        raise HTTPException(400, "edits must be {removed: [ids], moved: {id: [dx_m, dz_m]}, materials: {id: name}}")
    pool = await _pool()
    await artifact_store.ensure_doc(doc_id)
    if not any(d.glob("planmap-*.json")) and not (d / "scene.json").is_file():
        raise HTTPException(404, "document not found")
    items, _ = await asyncio.to_thread(doc_data, doc_id)
    known = set(items)
    edits = {"removed": [i for i in edits["removed"] if i in known],
             "moved": {k: v for k, v in edits["moved"].items() if k in known},
             "materials": {k: v for k, v in edits["materials"].items() if k in known}}
    if dv.is_empty(edits):
        raise HTTPException(400, "No edits to save: remove or move an item first.")
    existing = await versions_of(pool, doc_id)
    for v in existing[1:]:
        if v["edits"] == edits:
            return _saved(v, existing, created=False)
    parent = body.get("parent")  # the version these edits were made from (the viewer's last save), else the original
    parent = parent if isinstance(parent, int) and any(v["n"] == parent for v in existing) else 0
    chat = body.get("chat_id") if isinstance(body.get("chat_id"), str) and len(body["chat_id"]) <= 64 else None
    import asyncpg
    for _ in range(3):
        try:
            r = await pool.fetchrow(
                "insert into design_versions (doc_id, n, parent, label, edits, chat_id) "
                "select $1, coalesce(max(n), 0) + 1, $2, 'Edited version ' || (coalesce(max(n), 0) + 1) || ' · ' || "
                "to_char(now() at time zone 'utc', 'YYYY-MM-DD'), $3::jsonb, $4 from design_versions where doc_id=$1 "
                "returning doc_id, n, parent, label, edits, chat_id, created_at",
                doc_id, parent, json.dumps(edits), chat)
            break
        except asyncpg.UniqueViolationError:  # two saves raced for the same n: take the next one
            continue
    else:
        raise HTTPException(409, "could not save the version, try again")
    v = _record(r)
    return _saved(v, existing + [v], created=True)


def _saved(v: dict, all_versions: list[dict], created: bool) -> dict:
    parent = next((p for p in all_versions if p["n"] == v["parent"]), all_versions[0])
    data = doc_data(v["doc_id"])
    changes = dv.compare(None, parent["edits"], v["edits"], data)["changes"]
    cid = f"dv:{v['doc_id']}:{v['parent']}-{v['n']}"
    # The post-save link opens this version against the original (cid is the parent -> version step).
    return v | {"created": created, "change_id": cid, "compare_url": f"#/compare?change=dv:{v['doc_id']}:0-{v['n']}",
                "counts": dv.counts(changes), "n_changes": len(changes)}


def _parse(change_id: str):
    m = PAIR.match(change_id)
    return (m[1], int(m[2]), int(m[3])) if m else None


async def feed_entries(pool, visible: set[str] | None = None) -> list[dict]:
    """One new_version entry per saved version (parent -> version), for /api/changes and the Compare screen."""
    try:
        rows = await pool.fetch("select v.doc_id, v.n, v.parent, v.label, v.edits, v.chat_id, v.created_at, d.title "
                                "from design_versions v left join documents d on d.doc_id = v.doc_id order by v.doc_id, v.n")
    except Exception as e:  # noqa: BLE001  (table missing before migration 006)
        print("design versions unavailable:", repr(e)[:120])
        return []
    by_doc: dict[str, list] = {}
    for r in rows:
        by_doc.setdefault(r["doc_id"], []).append(r)
    out = []
    for doc_id, rs in by_doc.items():
        if visible is not None and doc_id not in visible:
            continue
        snaps = {0: dv.empty()} | {r["n"]: _j(r["edits"]) for r in rs}
        labels = {0: "Original"} | {r["n"]: r["label"] for r in rs}
        try:
            data = await asyncio.to_thread(doc_data, doc_id)
        except Exception:  # noqa: BLE001
            data = ({}, {})
        title = next((r["title"] for r in rs if r["title"]), None) or doc_id
        for r in rs:
            p = r["parent"] if r["parent"] in snaps else 0
            res = dv.compare(None, snaps[p], snaps[r["n"]], data)
            out.append({"id": f"dv:{doc_id}:{p}-{r['n']}", "type": "new_version", "doc_a": doc_id, "doc_b": doc_id,
                        "created_at": r["created_at"].isoformat(),
                        "summary": {"doc_id": doc_id, "series_id": f"design:{doc_id}", "title": title,
                                    "n_changes": len(res["changes"]), "counts": res["counts"],
                                    "headline": f"{r['label']}: {dv.headline(res['changes'])}", "source": SOURCE,
                                    "version_a": labels[p], "version_b": r["label"], "index_a": p, "index_b": r["n"],
                                    "pair_prefix": f"dv:{doc_id}:", "edited": True, "generated": EDITED,
                                    "pages_changed": sum(1 for x in res["pages"] if x["n_changes"])}})
    return out


def _page_url(doc_id: str, n: int, page: int, edits: dict) -> str:
    if n == 0 or dv.is_empty(edits):
        return f"/api/docs/{doc_id}/pages/{page}/image"
    return f"/api/docs/{doc_id}/versions/{n}/pages/{page}/image"


async def comparison(pool, change_id: str, page: int | None = None) -> dict | None:
    got = _parse(change_id)
    if got is None:
        return None
    doc_id, a, b = got
    if a == b:
        return None
    vs = {v["n"]: v for v in await versions_of(pool, doc_id)}
    if a not in vs or b not in vs:
        return None
    va, vb = vs[a], vs[b]
    data = await asyncio.to_thread(doc_data, doc_id)
    res = dv.compare(None, va["edits"], vb["edits"], data)
    pages = res["pages"]
    sel = next((p for p in pages if p["page_b"] == page), None) if page is not None else None
    sel = sel or next((p for p in pages if p["n_changes"]), pages[0] if pages else None)
    pn = sel["page_b"] if sel else None
    changes = []
    for c in res["changes"]:
        if pn is not None and c["page"] not in (pn, None):
            continue
        changes.append({"n": len(changes) + 1, "change_id": c["change_id"], "type": c["type"], "kind": c["kind"],
                        "sentence": c["description"], "description": c["description"], "edit": True,
                        "action": c["action"], "item_id": c["item_id"], "tag": c["tag"], "label": c["label"],
                        "storey": c["storey"], "page": c["page"], "delta_m": c.get("delta_m"),
                        "field": c.get("field"), "old": c.get("old"), "new": c.get("new"),
                        "v1": {"item_id": c["item_id"], "bbox_px": c["bbox_px_v1"]} if c["v1_item"] else None,
                        "v2": {"item_id": c["item_id"], "bbox_px": c["bbox_px_v2"]} if c["v2_item"] else None})

    def side(v):
        out = {"label": v["label"], "doc_id": doc_id, "version": v["n"], "date": (v.get("created_at") or "")[:10] or None,
               "edited": v["n"] > 0, "parent": v.get("parent")}
        if pn is not None:
            out |= {"page_image": _page_url(doc_id, v["n"], pn, v["edits"]),
                    "thumb": f"/api/docs/{doc_id}/files/page-{pn}.thumb.png"}
        return out
    return {"id": change_id, "type": "new_version", "doc_id": doc_id, "series_id": f"design:{doc_id}",
            "source": SOURCE, "note": res["note"], "edited": True, "generated": EDITED,
            "image": sel.get("image") if sel else None, "page": pn,
            "pages": [{"page": p["page_b"], "page_v1": p["page_a"], "page_v2": p["page_b"], "n_changes": p["n_changes"]}
                      for p in pages],
            "counts": res["counts"], "n_changes": len(res["changes"]),
            "item_ids": [c["item_id"] for c in res["changes"]],
            "v1": side(va), "v2": side(vb), "changes": changes}


def _paper(arr, r):
    """Median colour of a thin ring just outside rect r (x0, y0, x1, y1) in an HxWx3 array."""
    import numpy as np
    h, w = arr.shape[:2]
    x0, y0, x1, y1 = r
    ring = []
    for y in (y0 - 3, y1 + 2):
        if 0 <= y < h:
            ring.append(arr[y, max(0, x0 - 3):min(w, x1 + 3)])
    for x in (x0 - 3, x1 + 2):
        if 0 <= x < w:
            ring.append(arr[max(0, y0 - 3):min(h, y1 + 3), x])
    px = np.concatenate(ring) if ring else arr.reshape(-1, 3)
    return np.median(px, axis=0).astype(arr.dtype) if len(px) else np.array([255, 255, 255], arr.dtype)


def render_page(doc_id: str, page: int, edits: dict) -> bytes | None:
    """The page image with removed items painted out and moved items redrawn at their new spot."""
    import numpy as np
    from PIL import Image
    f = _doc_dir(doc_id) / f"page-{page}.png"
    if not f.is_file():
        return None
    items, pages = doc_data(doc_id)
    info = pages.get(page) or {}
    img = Image.open(f).convert("RGB")
    src = np.asarray(img)
    out = src.copy()
    h, w = src.shape[:2]
    frame = info.get("image") or {}
    sx, sy = (w / frame["w"], h / frame["h"]) if frame.get("w") and frame.get("h") else (1.0, 1.0)
    mpp = info.get("m_per_px")

    def rect(b, pad=0):
        return (max(0, int(b[0] * sx) - pad), max(0, int(b[1] * sy) - pad),
                min(w, int(np.ceil(b[2] * sx)) + pad), min(h, int(np.ceil(b[3] * sy)) + pad))
    removed = set(edits.get("removed") or [])
    moves = [(i, m) for i, m in (edits.get("moved") or {}).items() if i not in removed and mpp]
    copies = []
    for iid in removed | {i for i, _ in moves}:
        box = (items.get(iid) or {}).get("boxes", {}).get(page)
        if not box:
            continue
        x0, y0, x1, y1 = rect(box, 2)
        if x1 > x0 and y1 > y0:
            out[y0:y1, x0:x1] = _paper(src, (x0, y0, x1, y1))
        move = (edits.get("moved") or {}).get(iid)
        if iid not in removed and move:
            copies.append((rect(box), rect(dv.shift(box, move, mpp))))
    for (a0, b0, a1, b1), (c0, d0, _, _) in copies:
        cw, ch = min(a1 - a0, w - c0), min(b1 - b0, h - d0)
        ox, oy = max(0, -c0), max(0, -d0)
        if cw - ox > 0 and ch - oy > 0:
            out[d0 + oy:d0 + ch, c0 + ox:c0 + cw] = src[b0 + oy:b0 + ch, a0 + ox:a0 + cw]
    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format="PNG", optimize=False)
    return buf.getvalue()


@router.get("/docs/{doc_id}/versions/{n}/pages/{page}/image")
async def version_page_image(doc_id: str, n: int, page: int):
    _doc_dir(doc_id)
    pool = await _pool()
    v = next((x for x in await versions_of(pool, doc_id) if x["n"] == n), None)
    if v is None:
        raise HTTPException(404, "version not found")
    await artifact_store.ensure_doc(doc_id)
    key = (doc_id, n, page, json.dumps(v["edits"], sort_keys=True))
    png = _images.get(key)
    if png is None:
        png = await asyncio.to_thread(render_page, doc_id, page, v["edits"])
        if png is None:
            raise HTTPException(404, f"page {page} image not available")
        _images[key] = png
        while len(_images) > MAX_IMAGES:
            _images.popitem(last=False)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})
