"""Small bridge from existing document artifacts to the sheet registration engine."""
import asyncio
import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import artifact_store, config, docmeta_store
from .docs_routes import _document

router = APIRouter(prefix="/api")


class AlignmentRequest(BaseModel):
    base_doc_id: str = Field(min_length=1, max_length=250)
    overlay_doc_id: str = Field(min_length=1, max_length=250)
    base_page: int = Field(default=1, ge=1)
    overlay_page: int = Field(default=1, ge=1)
    base_points: list[tuple[float, float]] | None = None
    overlay_points: list[tuple[float, float]] | None = None
    model: str = "similarity"


def _load_sheet(record, page):
    from engine.sheet_align import load_pdf_page
    from PIL import Image
    root = config.artifacts_dir() / record["doc_id"]
    image_path = root / f"page-{page}.png"
    if not image_path.is_file():
        raise ValueError("This page has no image yet. Wait for ingestion or choose another sheet.")
    with Image.open(image_path) as image:
        size = image.size
    sheet = {"image": {"w": size[0], "h": size[1]}, "words": [], "image_path": str(image_path), "image_stamp": image_path.stat().st_mtime_ns}
    text_path = root / f"text-{page}.json"
    if text_path.is_file():
        text = json.loads(text_path.read_text())
        sheet["words"] = text if isinstance(text, list) else text.get("words", text.get("items", []))
        sheet["words"] = [{**w, "bbox_px": w.get("bbox_px", w.get("bbox"))} for w in sheet["words"]]
    pm = root / f"planmap-{page}.json"
    if pm.is_file():
        plan = json.loads(pm.read_text())
        sheet["words"] += [{"text": item.get("label", ""), "bbox_px": item.get("bbox_px")}
                           for item in plan.get("items", []) if item.get("label")]
        scale = plan.get("scale", {})
        # Door priors are estimates and cannot justify an accuracy in millimetres.
        if scale.get("method") in {"dimension", "scalebar", "dxf-units", "ifc"} and scale.get("m_per_px"):
            sheet["m_per_px"] = scale["m_per_px"]
    source = docmeta_store.source_file(record)
    if not sheet["words"] and source and Path(source).suffix.lower() == ".pdf":
        # Cache extraction in the adapter; never parse the 94k vector paths.
        pdf = load_pdf_page(source, page, size)
        if not sheet["words"]:
            sheet["words"] = pdf["words"]
        if "m_per_px" not in sheet and "m_per_px" in pdf:
            sheet["m_per_px"] = pdf["m_per_px"]
    if not sheet["words"]:
        sheet["detail"] = "No positioned text is available. Use two grid crossings."
    return sheet


@router.post("/sheet-align")
async def sheet_align(request: AlignmentRequest):
    from engine.sheet_align import cached_alignment, manual_alignment
    for doc_id in (request.base_doc_id, request.overlay_doc_id):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", doc_id) or doc_id in {".", ".."}:
            raise HTTPException(400, "Invalid document reference.")
    if request.model not in {"similarity", "affine"}:
        raise HTTPException(400, "Choose similarity or affine alignment.")
    records = await asyncio.gather(_document(request.base_doc_id), _document(request.overlay_doc_id))
    for doc_id in (request.base_doc_id, request.overlay_doc_id):
        await artifact_store.ensure_doc(doc_id)
    try:
        base, overlay = await asyncio.gather(
            asyncio.to_thread(_load_sheet, records[0], request.base_page),
            asyncio.to_thread(_load_sheet, records[1], request.overlay_page))
        if request.base_points is not None or request.overlay_points is not None:
            result = manual_alignment(request.base_points or [], request.overlay_points or [])
            for points, image in ((request.base_points, base["image"]), (request.overlay_points, overlay["image"])):
                if any(not (0 <= x <= image["w"] and 0 <= y <= image["h"]) for x, y in points):
                    raise ValueError("Alignment points must be inside their page images.")
        else:
            result = await asyncio.to_thread(cached_alignment, base, overlay, model=request.model)
    except (ValueError, IndexError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {**result, "base_image": base["image"], "overlay_image": overlay["image"]}
