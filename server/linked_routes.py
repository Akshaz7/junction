"""Linked information (E-12 -> W-13): GET /api/docs/{doc_id}/items/{item_id} and /tags/{tag}.

Both resolve through engine.linked.lookup and return the same shape:
{item_id, kind, tag, name, storey, type_name, props, places: [{doc_id, page, bbox_px | null, storey}]}.
Plain code over artifacts/<doc_id>/; 404 for an unknown document, item or tag.
"""
import asyncio

from fastapi import APIRouter, HTTPException

from . import config

router = APIRouter(prefix="/api")


def _shape(doc_id: str, r: dict) -> dict:
    def storey(p):
        v = p.get("storey", r.get("storey"))
        return v.get("name") if isinstance(v, dict) else v
    places = [{"doc_id": doc_id, "page": p.get("page"), "bbox_px": p.get("bbox_px"), "storey": storey(p)}
              for p in r.get("places") or []]
    return {"doc_id": doc_id, "item_id": r["item_id"], "kind": r.get("kind"), "tag": r.get("tag"), "name": r.get("name"),
            "storey": r.get("storey"), "type_name": r.get("type"), "ifc_class": r.get("ifc_class"),
            "props": r.get("properties") or {}, "quantities": r.get("quantities") or {}, "places": places}


async def _lookup(doc_id: str, ref: str) -> dict | None:
    from engine import linked
    return await asyncio.to_thread(linked.lookup, doc_id, ref, config.artifacts_dir())


@router.get("/docs/{doc_id}/items/{item_id:path}")
async def get_item(doc_id: str, item_id: str):
    r = await _lookup(doc_id, item_id)
    if r is None or r["item_id"] != item_id:  # items are addressed by id only; names and tags go through /tags
        raise HTTPException(404, "item not found")
    return _shape(doc_id, r)


@router.get("/docs/{doc_id}/tags/{tag:path}")
async def get_tag(doc_id: str, tag: str):
    r = await _lookup(doc_id, tag)
    if r is None:
        raise HTTPException(404, "tag not found")
    return _shape(doc_id, r)
