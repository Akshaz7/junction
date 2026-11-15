"""Room size from printed dimension strings.

A scan's planmap keeps `dimension_evidence` (printed length + the box of its dimension line). When one horizontal and
one vertical dimension span a room's own sides, the room's size is the printed width x depth: exact arithmetic on what
the drawing prints, better than boxes times a global scale. Ambiguous or inconsistent matches are skipped.
"""
from __future__ import annotations

SPAN_LO, SPAN_HI = 0.85, 1.15   # printed span vs room side
MARGIN = 0.15                   # a dimension line may sit slightly outside the room box
SANITY = 0.30                   # printed side vs measured side may differ by at most this fraction


def _pick(cands):
    vals = sorted({round(c["meters"], 3) for c in cands})
    if not cands or (len(vals) > 1 and vals[-1] > vals[0] * 1.01):
        return None
    return cands[0]


def room_sizes(pm: dict) -> dict:
    """item_id -> {width_m, depth_m, area_m2, dimensions: [evidence...]} for rooms bounded by printed dimensions."""
    dims = [d for d in pm.get("dimension_evidence") or [] if isinstance(d.get("meters"), (int, float)) and d["meters"] > 0
            and isinstance(d.get("bbox_px"), list) and len(d["bbox_px"]) == 4]
    mpp = (pm.get("scale") or {}).get("m_per_px")
    out = {}
    for it in pm.get("items") or []:
        b = it.get("bbox_px")
        if it.get("kind") != "room" or not b:
            continue
        rw, rh = b[2] - b[0], b[3] - b[1]
        if rw <= 0 or rh <= 0:
            continue
        hs, vs = [], []
        for d in dims:
            x0, y0, x1, y1 = d["bbox_px"]
            w, h = x1 - x0, y1 - y0
            if w >= 2.5 * h and SPAN_LO <= w / rw <= SPAN_HI and x0 >= b[0] - MARGIN * rw and x1 <= b[2] + MARGIN * rw \
                    and b[1] - MARGIN * rh <= (y0 + y1) / 2 <= b[3] + MARGIN * rh:
                hs.append(d)
            elif h >= 2.5 * w and SPAN_LO <= h / rh <= SPAN_HI and y0 >= b[1] - MARGIN * rh and y1 <= b[3] + MARGIN * rh \
                    and b[0] - MARGIN * rw <= (x0 + x1) / 2 <= b[2] + MARGIN * rw:
                vs.append(d)
        # Several lines with different values could belong to another room: refuse rather than guess.
        hd, vd = _pick(hs), _pick(vs)
        if not hd or not vd:
            continue
        if mpp and (abs(hd["meters"] - rw * mpp) > SANITY * hd["meters"] or abs(vd["meters"] - rh * mpp) > SANITY * vd["meters"]):
            continue
        out[it["item_id"]] = {"width_m": hd["meters"], "depth_m": vd["meters"],
                              "area_m2": round(hd["meters"] * vd["meters"], 4),
                              "dimensions": [{"text": hd.get("text"), "meters": hd["meters"], "bbox_px": hd["bbox_px"]},
                                             {"text": vd.get("text"), "meters": vd["meters"], "bbox_px": vd["bbox_px"]}]}
    return out


def apply(pm: dict) -> dict:
    """Copy of pm where rooms bounded by printed dimensions carry area_m2_label (printed-size area) and their source."""
    sizes = room_sizes(pm)
    if not sizes:
        return pm
    items = []
    for it in pm["items"]:
        s = sizes.get(it.get("item_id"))
        props = it.get("props") or {}
        if s and props.get("area_m2_label") is None:
            props = {**props, "area_m2_label": s["area_m2"], "area_label_source": "printed dimensions",
                     "printed_width_m": s["width_m"], "printed_depth_m": s["depth_m"], "printed_dimensions": s["dimensions"]}
            it = {**it, "props": props}
        items.append(it)
    return {**pm, "items": items}
