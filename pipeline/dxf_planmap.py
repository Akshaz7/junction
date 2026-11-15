"""D-08: DXF (swiss_dwellings) -> plan map, real units as scale.

Image: the page-1.png from D-05 (PDF render when a PDF exists, else our DXF render).
For the PDF case the DXF->pixel transform is fitted by least squares on text that appears in both
the DXF (TEXT entities) and the PDF word layer, so scale comes from the DXF units, not a guess.
Item ids: <kind>-<n> in a stable order.  CLI: python -m pipeline.dxf_planmap [--only DOC_ID...]
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
UNIT_M = {0: 1.0, 1: 0.0254, 2: 0.3048, 4: 0.001, 5: 0.01, 6: 1.0, 7: 1000.0}  # $INSUNITS -> metres
NUM = re.compile(r"^\d+\.\d+$")
AREA = re.compile(r"^[\d.]+\s*m²$")
from pipeline.dxf_symbols import fixture_kind  # re-export for existing callers


def room_texts(ms, layer="ROOM_TEXT"):
    """Left/baseline TEXT uses insert even when a default align_point is present."""
    texts = []
    for e in ms.query("TEXT MTEXT"):
        if layer is not None and e.dxf.layer != layer:
            continue
        if e.dxftype() == "MTEXT":
            v = e.dxf.insert
            text = e.plain_text().strip()
        else:
            aligned = e.dxf.halign != 0 or e.dxf.valign != 0
            v = e.dxf.align_point if aligned and e.dxf.hasattr("align_point") else e.dxf.insert
            text = e.dxf.text.strip()
        texts.append((text, float(v.x), float(v.y)))
    return texts


def assign_room_texts(rooms, texts):
    """Boundary labels belong to rooms too; nested outlines prefer the smallest room."""
    from pipeline.dxf_units import assign_texts
    return assign_texts(rooms, texts)


def _pts(e):
    vertices = e.vertices_in_wcs() if e.dxftype() == "LWPOLYLINE" else e.points_in_wcs()
    return [(float(p.x), float(p.y)) for p in vertices]


def _closed(e):
    closed = e.closed if e.dxftype() == "LWPOLYLINE" else e.is_closed
    if closed:
        return True
    p = _pts(e)
    return len(p) >= 4 and p[0] == p[-1]


def _poly_area(p):
    a = 0.0
    for (x0, y0), (x1, y1) in zip(p, p[1:] + p[:1]):
        a += x0 * y1 - x1 * y0
    return abs(a) / 2


def _inside(pt, poly):
    x, y = pt
    c = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            c = not c
    return c


def fit_transform(dxf_texts, words, tol=12.0):
    """px = a*x + bx ; py = -a*y + by.  dxf_texts: [(text, x, y)], words: [{text,bbox_px}]."""
    wc = {}
    for w in words:
        wc.setdefault(w["text"], []).append(w["bbox_px"])
    dc = Counter(t for t, _, _ in dxf_texts)
    pairs, labels = [], []
    for t, x, y in dxf_texts:
        if dc[t] == 1 and len(wc.get(t, [])) == 1 and " " not in t:
            b = wc[t][0]
            pairs.append((x, y, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2))
            labels.append((t, b))
    if len(pairs) < 4:
        return None
    P = np.array(pairs)
    keep = np.ones(len(P), bool)
    for _ in range(4):
        X, Y, U, V = P[keep].T
        A = np.concatenate([np.c_[X, np.ones_like(X), np.zeros_like(X)], np.c_[-Y, np.zeros_like(Y), np.ones_like(Y)]])
        sol = np.linalg.lstsq(A, np.concatenate([U, V]), rcond=None)[0]
        a, bx, by = sol
        res = np.hypot(a * P[:, 0] + bx - P[:, 2], -a * P[:, 1] + by - P[:, 3])
        keep = res < max(tol, 3 * np.median(res[keep]))
        if keep.sum() < 4:
            return None
    return {"a": float(a), "bx": float(bx), "by": float(by), "n": int(keep.sum()),
            "rms_px": float(np.sqrt(np.mean(res[keep] ** 2))),
            "anchors": [{"text": labels[i][0], "bbox": labels[i][1], "native": P[i, :2].tolist(),
                         "pixel": P[i, 2:].tolist(), "residual_px": float(res[i])}
                        for i in range(len(P)) if keep[i]]}


def process(doc_id: str, art: Path, dxf_path: Path) -> dict:
    import ezdxf
    from ezdxf import units
    from pipeline import pages as pg
    doc = ezdxf.readfile(str(dxf_path))
    from pipeline.dxf_input import drawing_layout
    ms = drawing_layout(doc)
    from pipeline.scale_provenance import dxf_units, dxf_scale
    unit_m = dxf_units(doc, doc_id)["m_per_unit"] if ms.name == "Model" else None
    # Preserve unknown units instead of publishing a fabricated physical scale.
    quantity_factor = unit_m
    page = json.loads((art / "pages.json").read_text())
    p1 = page["pages"][0]
    W, H = p1["w"], p1["h"]
    texts = room_texts(ms)
    from pipeline import dxf_generic
    swiss = any(True for _ in ms.query('LWPOLYLINE POLYLINE[layer=="ROOM_OUTLINE"]'))
    generic_rooms = []
    if not swiss:  # any other CAD layering: walls/openings by layer name, rooms from the walls, labels from TEXT
        texts = dxf_generic.room_labels(ms)
        generic_rooms = dxf_generic.derive_rooms(ms, unit_m)
    if page["source"] == "dxf":
        lines = pg.dxf_lines(doc)
        x0, y0, s, _, Hh = pg.dxf_frame(lines)
        tf = {"a": s, "bx": 20 - x0 * s, "by": Hh - 20 + y0 * s, "n": 0, "rms_px": 0.0}
        method = "dxf_render"
    else:
        words = json.loads((art / "text-1.json").read_text())["words"]
        tf = fit_transform(texts, words)
        if tf is None:
            raise RuntimeError("could not register DXF to page image")
        method = "dxf_units_fit"
    a, bx, by = tf["a"], tf["bx"], tf["by"]

    def px(p):
        return [round(a * p[0] + bx, 1), round(-a * p[1] + by, 1)]

    def box(poly):
        xs = [q[0] for q in poly]; ys = [q[1] for q in poly]
        return [min(xs), min(ys), max(xs), max(ys)]

    items, cnt = [], Counter()

    def add(kind, label, poly_m, props, src, conf=1.0):
        cnt[kind] += 1
        poly = [px(q) for q in poly_m]
        items.append({"item_id": f"{kind}-{cnt[kind]}", "kind": kind, "label": label, "bbox_px": box(poly) if poly else None,
                      "polygon_px": poly, "props": props, "conf": conf, "source": src})
        return items[-1]

    # rooms
    rooms = [p for e in ms.query('LWPOLYLINE POLYLINE[layer=="ROOM_OUTLINE"]') if _closed(e) for p in [_pts(e)]] or generic_rooms
    from pipeline.dxf_units import analyse
    # A repeated endpoint closes CAD rings even when the DXF closed bit is unset.
    unit_entities = list(ms.query('LWPOLYLINE POLYLINE[layer=="UNIT_OUTLINE"]'))
    outlines = [_pts(e) for e in unit_entities]
    records, units = analyse(rooms, texts, outlines, room_texts(ms, layer=None), unit_m,
                             unit_closed=[_closed(e) for e in unit_entities])
    room_items = []
    for r, record in zip(rooms, records):
        props = record["props"]
        for key in ("label_point", "centroid"):
            if key in props:
                props[key + "_px"] = px(props.pop(key))
        if "void_outline_indices" in props:
            props["void_polygons_px"] = [[px(p) for p in rooms[j]] for j in props.pop("void_outline_indices")]
        item = add("other" if props.get("role") == "room_void" else "room", record["label"], r, props, "dxf")
        if not props["geometry_valid"] or props.get("classification") == "unlabelled" or props.get("unit_membership_method") == "ambiguous":
            item["conf"] = 0.4  # existing MIN_CONF is 0.5; unknown geometry is retained for inspection
        room_items.append(item)
    unit_items = [add("other", u["label"], p, u["props"], "dxf") for p, u in zip(outlines, units)]
    for item in unit_items:
        if not item["props"]["geometry_valid"] or item["props"]["classification"] == "ambiguous":
            item["conf"] = 0.4
    for item in room_items:
        props = item["props"]
        owner = props.pop("unit_index", None)
        if owner is not None:
            props["unit_item_id"] = unit_items[owner]["item_id"]
        parent = props.pop("parent_room_index", None)
        if parent is not None:
            props["parent_room_item_id"] = room_items[parent]["item_id"]
    for e in ms.query('LWPOLYLINE POLYLINE[layer=="WALL"]'):
        add("wall", "", _pts(e), {}, "dxf")
    if not swiss:
        for poly in dxf_generic.wall_polygons(ms):
            add("wall", "", [(float(x), float(y)) for x, y in poly.exterior.coords[:-1]], {"dxf_source": "wall layer"}, "dxf")
        arcs, wins = dxf_generic.openings(ms, unit_m)
        for d in arcs:
            add("door", "", d["polygon"], {"classification": "swing_arc", "leaf_len_m": d["leaf_len"] * unit_m if unit_m else None}, "dxf", 0.9)
        for w in wins:
            add("window", "", w["polygon"], {"classification": "glazing_lines"}, "dxf", 0.9)
    from pipeline.dxf_symbols import extract_fixtures, extract_openings
    for symbol in [*extract_openings(ms, "window", unit_m), *extract_openings(ms, "door", unit_m),
                   *extract_fixtures(ms)]:
        add(symbol["kind"], symbol["label"], symbol["polygon"], symbol["props"], "dxf", symbol["conf"])
    # text items
    for t, x, y in texts:
        c = px((x, y)); h = 8
        cnt["text"] += 1
        items.append({"item_id": f"text-{cnt['text']}", "kind": "text", "label": t,
                      "bbox_px": [c[0] - 4 * len(t), c[1] - h, c[0] + 4 * len(t), c[1] + h],
                      "polygon_px": None, "props": {"dxf_layer": "ROOM_TEXT" if swiss else "label"}, "conf": 1.0, "source": "dxf"})
    scale = dxf_scale(doc, tf, doc_id)
    if scale["m_per_px"] is not None:
        scale["method"] = method
    pm = {"doc_id": doc_id, "page": 1, "image": {"w": W, "h": H},
          "scale": scale,
          "registration": tf, "items": items,
          "provenance": {"models": {}, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "ms": 0,
                         "note": "from DXF geometry; $INSUNITS=%s" % doc.header.get("$INSUNITS")}}
    from pipeline.scale_regions import dxf_regions
    details = dxf_regions(doc, tf)
    if details:
        pm["regions"] = [{"bbox": [0, 0, W, H], "scale": dict(pm["scale"]), "title": "Main plan"}, *details]
    from engine.scale_proof import enrich
    pm["scale"] = enrich(pm, art, save_crops=True)
    (art / "planmap-1.json").write_text(json.dumps(pm))
    return {"counts": dict(cnt), "reg": tf}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    root = REPO / "data" / "junction-dataset-preview"
    for art in sorted((REPO / "artifacts").glob("swiss_dwellings__*")):
        if a.only and art.name not in a.only:
            continue
        d = json.loads((art / "doc.json").read_text())
        f = d["files"].get("dxf")
        if not f or not (art / "pages.json").exists():
            continue
        try:
            r = process(art.name, art, root / f)
            print(art.name, r["counts"], "rms=%.2f n=%d" % (r["reg"]["rms_px"], r["reg"]["n"]))
        except Exception as ex:
            print(art.name, "FAILED", ex)


if __name__ == "__main__":
    main()
