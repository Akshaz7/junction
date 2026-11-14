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


def _pts(e):
    return [(float(x), float(y)) for x, y in e.get_points("xy")]


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
    pairs = []
    for t, x, y in dxf_texts:
        if dc[t] == 1 and len(wc.get(t, [])) == 1 and " " not in t:
            b = wc[t][0]
            pairs.append((x, y, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2))
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
            "rms_px": float(np.sqrt(np.mean(res[keep] ** 2)))}


def process(doc_id: str, art: Path, dxf_path: Path) -> dict:
    import ezdxf
    from pipeline import pages as pg
    doc = ezdxf.readfile(str(dxf_path))
    ms = doc.modelspace()
    unit_m = UNIT_M.get(int(doc.header.get("$INSUNITS", 6)), 1.0)
    page = json.loads((art / "pages.json").read_text())
    p1 = page["pages"][0]
    W, H = p1["w"], p1["h"]
    texts = [(e.dxf.text.strip(), float(v.x), float(v.y))
             for e in ms.query("TEXT") if e.dxf.layer == "ROOM_TEXT"
             for v in [e.dxf.align_point if e.dxf.hasattr("align_point") else e.dxf.insert]]
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

    def add(kind, label, poly_m, props, src):
        cnt[kind] += 1
        poly = [px(q) for q in poly_m]
        items.append({"item_id": f"{kind}-{cnt[kind]}", "kind": kind, "label": label, "bbox_px": box(poly),
                      "polygon_px": poly, "props": props, "conf": 1.0, "source": src})

    # rooms
    rooms = [p for e in ms.query('LWPOLYLINE[layer=="ROOM_OUTLINE"]') if e.closed for p in [_pts(e)]]
    assign = {i: [] for i in range(len(rooms))}
    for t, x, y in texts:
        for i, r in enumerate(rooms):
            if _inside((x, y), r):
                assign[i].append((t, x, y)); break
    for i, r in enumerate(rooms):
        ts = [t for t, _, _ in assign[i]]
        name = next((t for t in ts if not NUM.match(t) and not AREA.match(t) and not t.startswith("App.")), "")
        num = next((t for t in ts if NUM.match(t)), "")
        area_txt = next((t for t in ts if AREA.match(t)), "")
        add("room", name, r,
            {"number": num, "area_m2_label": float(area_txt.split()[0]) if area_txt else None,
             "area_m2_geom": round(_poly_area(r) * unit_m ** 2, 2), "labelled": bool(name)}, "dxf")
    # units
    for e in ms.query('LWPOLYLINE[layer=="UNIT_OUTLINE"]'):
        p = _pts(e)
        lab = next((t for t, x, y in texts if t.startswith("App.") and _inside((x, y), p)), "")
        add("other", lab, p, {"role": "unit", "area_m2_geom": round(_poly_area(p) * unit_m ** 2, 2)}, "dxf")
    for e in ms.query('LWPOLYLINE[layer=="WALL"]'):
        add("wall", "", _pts(e), {}, "dxf")
    for e in ms.query('LWPOLYLINE[layer=="WINDOW"]'):
        if e.closed:
            add("window", "", _pts(e), {}, "dxf")
    arcs = [(e.dxf.center.x, e.dxf.center.y, e.dxf.radius) for e in ms.query('ARC[layer=="DOOR"]')]
    for e in ms.query('LWPOLYLINE[layer=="DOOR"]'):
        p = _pts(e)
        if len(p) == 5:  # door leaf frame; the 2-point lines and arcs are swing symbols
            cx = sum(q[0] for q in p[:4]) / 4; cy = sum(q[1] for q in p[:4]) / 4
            sw = min(arcs, key=lambda c: (c[0] - cx) ** 2 + (c[1] - cy) ** 2, default=None)
            w = max(box(p)[2] - box(p)[0], box(p)[3] - box(p)[1])
            add("door", "", p, {"swing_radius_m": round(sw[2] * unit_m, 2) if sw else None,
                                "leaf_len_m": round(w * unit_m, 2)}, "dxf")
    for e in ms.query('LWPOLYLINE[layer=="FIXTURE"]'):
        if e.closed:
            add("other", "", _pts(e), {"role": "fixture"}, "dxf")
    # text items
    for t, x, y in texts:
        c = px((x, y)); h = 8
        cnt["text"] += 1
        items.append({"item_id": f"text-{cnt['text']}", "kind": "text", "label": t,
                      "bbox_px": [c[0] - 4 * len(t), c[1] - h, c[0] + 4 * len(t), c[1] + h],
                      "polygon_px": None, "props": {}, "conf": 1.0, "source": "dxf"})
    m_per_px = unit_m / a
    pm = {"doc_id": doc_id, "page": 1, "image": {"w": W, "h": H},
          "scale": {"m_per_px": round(m_per_px, 6), "method": method, "confidence": 1.0 if tf["rms_px"] < 6 else 0.6},
          "registration": tf, "items": items,
          "provenance": {"models": {}, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "ms": 0,
                         "note": "from DXF geometry; $INSUNITS=%s" % doc.header.get("$INSUNITS")}}
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
