"""E-08: drawing-reading path for questions the plan map cannot answer (text / other on a plan).

read_drawing(question, doc, root) -> answer object. The model sees the page image and returns an answer plus
regions (box_2d = [ymin, xmin, ymax, xmax] on 0-1000). A region becomes a citation ONLY if it is backed by the
plan map: an item whose centre lies inside it, or IoU >= 0.2, or an OCR/text item whose label occurs in
the region's quote. Unbacked regions are dropped and said so in the trace. No page image -> abstain.
Cost goes through engine.models.call("read_drawing"). Page 1 only for now.
"""
from __future__ import annotations

from engine.assistant import with_system
import struct
import time
import uuid
from pathlib import Path

from engine.solvers.data import Doc, Item

SCHEMA = {
    "type": "object", "required": ["can_answer", "answer", "regions"], "additionalProperties": False,
    "properties": {
        "can_answer": {"type": "boolean"},
        "answer": {"type": "string"},
        "regions": {"type": "array", "items": {
            "type": "object", "required": ["box_2d", "what"], "additionalProperties": False,
            "properties": {"box_2d": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                           "what": {"type": "string"}}}},
    },
}
PROMPT = ("You read a building drawing (floor plan page) and answer one question from what is visible on it. "
          "Reply with JSON only. can_answer=false if the drawing does not show the answer (then answer = a short "
          "plain sentence saying so). answer: 1-3 short sentences, key fact first in **bold**, English, keep room labels "
          "exactly as printed. regions: boxes around the parts of the drawing that show the answer, as "
          "box_2d=[ymin,xmin,ymax,xmax] on a 0-1000 scale of the full image, each with a short 'what' (quote any printed "
          "text). Do not guess; no region means no evidence.\n\nQuestion: ")
MAX_REGIONS = 8
CENTRE_IN, IOU_MIN = True, 0.2


def png_size(p: Path) -> tuple[int, int] | None:
    try:
        with p.open("rb") as f:
            b = f.read(32)
        if b[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", b[16:24])
    except (OSError, struct.error):
        pass
    return None


def _iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def to_px(box_2d, w: int, h: int) -> list[float] | None:
    try:
        y0, x0, y1, x1 = (float(v) for v in box_2d)
    except (TypeError, ValueError):
        return None
    if not all(0 <= v <= 1000 for v in (y0, x0, y1, x1)) or y1 <= y0 or x1 <= x0:
        return None
    return [round(x0 / 1000 * w, 1), round(y0 / 1000 * h, 1), round(x1 / 1000 * w, 1), round(y1 / 1000 * h, 1)]


def check_region(px: list[float], what: str, items: list[Item]) -> list[Item]:
    """Plan-map items that back this region (empty list = unverified)."""
    hit = []
    w = (what or "").casefold()
    for it in items:
        if not it.bbox_px:
            continue
        b = it.bbox_px
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        inside = px[0] <= cx <= px[2] and px[1] <= cy <= px[3]
        by_text = bool(it.label) and len(it.label) >= 2 and it.label.casefold() in w
        if inside or _iou(px, b) >= IOU_MIN or by_text:
            hit.append(it)
    return hit


def _abstain(question, doc, text, trace, t0, calls=()):
    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": [doc.doc_id],
        "answer": {"text_md": text, "value": None, "unit": None, "confidence": 0.0, "abstained": True},
        "citations": [], "evidence": {"boxes": [], "scene": {"doc_id": doc.doc_id, "highlight_item_ids": [], "camera_target_item_id": None}},
        "trace": trace, "route": "vlm", "cost": {"usd_total": round(sum(c["cost_usd"] for c in calls), 6), "calls": list(calls)},
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }


def read_drawing(question: str, doc: Doc, root: Path, page: int = 1) -> dict:
    from engine.models import call

    t0 = time.perf_counter()
    trace: list[dict] = []
    img = Path(root) / doc.doc_id / f"page-{page}.png"
    size = png_size(img)
    if size is None:
        trace.append({"step": "abstain", "detail": "no page image", "ms": 0, "model": None, "cost_usd": 0})
        return _abstain(question, doc, "I have no page image for this document, so I cannot read the drawing.", trace, t0)
    ts = time.perf_counter()
    r = call("read_drawing", with_system(PROMPT + question), images=[img], schema=SCHEMA)
    calls = [{"task": "read_drawing", "provider": r.provider, "model": r.model, "cost_usd": r.cost_usd}]
    trace.append({"step": "read", "detail": f"page {page} read by {r.model}", "ms": int((time.perf_counter() - ts) * 1000),
                  "model": r.model, "cost_usd": r.cost_usd})
    j = r.json or {}
    text = (j.get("answer") or "").strip()
    if not j.get("can_answer") or not text:
        trace.append({"step": "abstain", "detail": "the drawing does not show the answer", "ms": 0, "model": None, "cost_usd": 0})
        return _abstain(question, doc, text or "The drawing does not show this, so I cannot answer it.", trace, t0, calls)

    items = [i for i in doc.items if i.page == page]
    w, h = size
    boxes, cites, seen = [], [], set()
    dropped = 0
    for reg in (j.get("regions") or [])[:MAX_REGIONS]:
        px = to_px(reg.get("box_2d"), w, h)
        backed = check_region(px, reg.get("what", ""), items) if px else []
        if not backed:
            dropped += 1
            continue
        n = len(cites) + 1
        cites.append({"n": n, "doc_id": doc.doc_id, "page": page, "kind": "region", "bbox_px": px,
                      "item_ids": [i.item_id for i in backed][:50], "quote": (reg.get("what") or "")[:200] or None})
        boxes.append({"item_id": backed[0].item_id, "page": page, "bbox_px": px, "label": str(n)})
        seen.update(i.item_id for i in backed)
    trace.append({"step": "check", "detail": f"{len(cites)} region(s) backed by the plan map, {dropped} dropped as unverified",
                  "ms": 0, "model": None, "cost_usd": 0})
    marks = "".join(f"[{c['n']}]" for c in cites)
    if cites:
        text = f"{text} {marks}"
        conf = 0.6
    else:
        text += "\n\nI could not tie this to specific places on the drawing, so treat it as unchecked."
        conf = 0.3
    ids = sorted(seen)
    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": [doc.doc_id],
        "answer": {"text_md": text, "value": None, "unit": None, "confidence": conf, "abstained": False},
        "citations": cites, "evidence": {"boxes": boxes, "scene": {"doc_id": doc.doc_id, "highlight_item_ids": ids,
                                                                    "camera_target_item_id": ids[0] if ids else None}},
        "trace": trace, "route": "vlm", "cost": {"usd_total": round(sum(c["cost_usd"] for c in calls), 6), "calls": calls},
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }
