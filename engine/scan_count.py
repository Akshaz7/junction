"""Count P&ID symbols from individual marked instances, never a bare total.

The drawing's own legend takes precedence. No legend is required. A model may
propose boxes; code validates, deduplicates and counts them. No graph annotations
or benchmark labels are consulted. Failure leaves the existing reader available.
"""
from __future__ import annotations

import math
import os
import re
import time
import uuid
from pathlib import Path

KINDS = {
    "valve": (r"\bvalves?\b", "valves"),
    "instrument": (r"\b(?:instruments?|gauges?|transmitters?|controllers?)\b", "instruments"),
    "tank": (r"\b(?:tanks?|vessels?)\b", "tanks or vessels"),
    "pump": (r"\bpumps?\b", "pumps"),
}
HINTS = {
    "valve": "Count the complete valve assembly once: the paired triangles/body and its actuator are ONE valve. Include manual, control, check, relief and isolation valves. Do not count arrows, pipe crossings, reducers, or each triangle separately.",
    "instrument": "Count each tagged instrument bubble or local instrument symbol once, including gauges, transmitters and controllers. Include control-function/tag bubbles connected to valves: a valve's body and a separately drawn labelled circular bubble are different symbols. A tag's text or leader next to its bubble is not another instrument. Do not count motors, connection dots, or an actuator without a separate tagged bubble.",
    "tank": "Include tanks, vessels, drums, accumulators and reservoirs, vertical OR horizontal: cylindrical outlines with flat, elliptical or dished ends, open-top vessels, rectangular reservoirs. Include vessel-shaped process equipment regardless of its service label, including a steam generator or exchanger shell drawn as a vessel. A large vessel is ONE object even if it has several nozzles, compartments or instrument connections. Do not count pumps, plate-exchanger symbols without a vessel body, or the same vessel twice.",
    "pump": "Count each pump body once, including centrifugal and positive displacement pumps. Its motor and flow arrow are not extra pumps. Do not count instrument bubbles as pumps.",
}
SCHEMA = {"type": "object", "required": ["is_pid", "items", "uncertain"], "additionalProperties": False,
          "properties": {"is_pid": {"type": "boolean"}, "uncertain": {"type": "boolean"},
                         "items": {"type": "array", "items": {"type": "object", "required": ["box"], "additionalProperties": False,
                                   "properties": {"box": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                                                  "label": {"type": "string"}}}}}}
PROMPT = """Read this piping and instrumentation diagram. If it is not a P&ID, is_pid=false and items=[].
Locate every {noun} actually drawn in the process area, scanning from left to right and top to bottom.
{hint}
Use the drawing's own legend/key if present to interpret its symbols. NEVER count legend examples, title-block graphics, schedules or duplicated detail views as installed equipment.
Return one tight box per complete physical symbol, including its body, excluding adjacent labels and connecting pipe runs. box=[ymin,xmin,ymax,xmax], coordinates 0..1000 of this image. label=printed tag only if legible, otherwise omit.
Do not return a total. Code will count the boxes. Do not add invisible symbols to meet an expected count. uncertain=true if resolution, ambiguity or a clipped diagram prevents a reliable count. JSON only."""


def target(question):
    if not re.search(r"\b(?:how many|count|number of)\b", question, re.I):
        return None
    found = [k for k, (rx, _) in KINDS.items() if re.search(rx, question, re.I)]
    return found[0] if len(found) == 1 else None


def pixel_boxes(raw, width, height, kind):
    from vision.scan_tiles import dedupe
    items = []
    for it in raw or []:
        try:
            y0, x0, y1, x1 = map(float, it["box"])
        except (TypeError, KeyError, ValueError):
            continue
        if not all(math.isfinite(v) and 0 <= v <= 1000 for v in (y0, x0, y1, x1)) or x1 <= x0 or y1 <= y0:
            continue
        box = [round(x0 * width / 1000, 1), round(y0 * height / 1000, 1),
               round(x1 * width / 1000, 1), round(y1 * height / 1000, 1)]
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        items.append({"kind": kind, "bbox_px": box, "conf": .6, "label": str(it.get("label") or "")[:80]})
    return sorted(dedupe(items), key=lambda i: (i["bbox_px"][1], i["bbox_px"][0]))


def answer_counts(question, doc_ids, root, t0=None, incurred=None):
    kind = target(question)
    if not kind or len(doc_ids or []) != 1 or os.environ.get("MODELS_FAKE") or os.environ.get("SCAN_COUNTS", "1") == "0":
        return None
    # Explicit diagram context avoids replacing exact model/schedule quantities.
    if not re.search(r"\b(?:piping|instrumentation|diagram|p\s*&\s*id)\b", question, re.I):
        return None
    root, did = Path(root), doc_ids[0]
    d = root / did
    if (d / "elements.json").exists():
        return None
    images = sorted((p for p in d.glob("page-*.png") if re.fullmatch(r"page-\d+", p.stem)),
                    key=lambda p: int(p.stem.split("-")[1]))
    if not images:
        return None
    from PIL import Image
    from engine.models import call
    t0 = t0 or time.perf_counter()
    boxes, cites, calls = [], [], []
    uncertain = False
    try:
        for image in images:
            page = int(image.stem.split("-")[1])
            with Image.open(image) as im:
                width, height = im.size
            r = call("read_drawing", [{"role": "user", "content": PROMPT.format(noun=KINDS[kind][1], hint=HINTS[kind])}], images=[image], schema=SCHEMA)
            calls.append({"task": "read_drawing", "provider": r.provider, "model": r.model, "cost_usd": r.cost_usd})
            j = r.json if isinstance(r.json, dict) else {}
            if not j.get("is_pid"):
                if incurred is not None:
                    incurred.extend(calls)
                return None
            uncertain |= bool(j.get("uncertain"))
            for it in pixel_boxes(j.get("items"), width, height, kind):
                n = len(boxes) + 1
                iid = f"scan-{kind}-{page}-{n:03d}"
                boxes.append({"item_id": iid, "kind": kind, "page": page, "bbox_px": it["bbox_px"], "label": str(n)})
                cites.append({"n": n, "doc_id": did, "page": page, "kind": "region", "bbox_px": it["bbox_px"],
                              "item_ids": [iid], "quote": it["label"] or None})
    except Exception:  # missing provider, corrupt image or budget: keep the existing reader
        if incurred is not None:
            incurred.extend(calls)
        return None
    n = len(boxes)
    noun = KINDS[kind][1]
    text = f"**{n} {noun} found on this diagram.**" + (" [1]" if boxes else "")
    text += "\n\n- Each numbered box marks one symbol; legend examples are excluded."
    if uncertain:
        text += "\n- Some symbols are unclear; check the boxes before using this count."
    else:
        text += "\n- Read from the image by a model; check for missed or misread symbols."
    # No boxes is not proof that the drawing contains zero instances.
    if not boxes:
        text = f"**I could not reliably locate any {noun} on this diagram.** Check the legend and image resolution."
    trace = [{"step": "scan-count", "detail": f"{n} individual symbol boxes after overlap deduplication; legend examples excluded",
              "ms": 0, "model": ", ".join(sorted({c["model"] for c in calls})), "cost_usd": sum(c["cost_usd"] for c in calls)}]
    return {"answer_id": uuid.uuid4().hex, "question": question, "doc_ids": [did],
            "answer": {"text_md": text, "value": n if boxes else None, "unit": "count", "confidence": .45 if uncertain or not boxes else .6, "abstained": False},
            "citations": cites, "evidence": {"boxes": boxes, "scene": {"doc_id": did, "highlight_item_ids": [], "camera_target_item_id": None}},
            "trace": trace, "route": "hybrid", "cost": {"usd_total": sum(c["cost_usd"] for c in calls), "calls": calls},
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "reasoning": {"steps": [{"kind": "found", "title": "Found", "text": f"{n} individually boxed symbols on {len(images)} page(s).", "cite": 1 if boxes else None, "ok": None},
                                     {"kind": "checked", "title": "Checked", "text": "Overlapping duplicate boxes removed; neighboring symbols kept separate. No independent visual check.", "cite": None, "ok": None}],
                          "confidence": {"label": "Estimate", "pct": 45 if uncertain or not boxes else 60, "reason": "Symbols read from the image by a model; completeness is unverified.",
                                         "improve": "Check each numbered box and look for missed symbols before ordering."}}}
