"""D-12: synthetic revisions for the Changes demo ("generated for demo").

For 3 swiss DXF plans we apply three edits to make version 2: remove one interior wall, add one door
(splitting a wall to open a 0.9 m gap), and rename one room label. Both versions are rendered from the
DXF with the same frame (asserted), plan-mapped by pipeline.dxf_planmap, and the true change list is
stored.  Layout (git-ignored): artifacts/revisions/<doc_id>/{v1,v2}/{plan.dxf,page-1.png,pages.json,
planmap-1.json}, truth_changes.json, doc.json.  Seeded and deterministic.
CLI: python -m pipeline.revisions
"""
from __future__ import annotations

import json
import math
import random
import shutil
from pathlib import Path

import ezdxf
from shapely.geometry import Polygon, box

REPO = Path(__file__).resolve().parent.parent
DOCS = ["swiss_dwellings__site289-bldg536-floor2149", "swiss_dwellings__site11861-bldg18508-floor50415",
        "swiss_dwellings__site1869-bldg2903-floor13293"]
GAP = 0.9
LABELS = ("Pièce", "Camera da letto", "Séjour/repas", "Soggiorno/pranzo", "Cuisine", "Cucina")  # renameable rooms
NEW_BY_OLD = {"Pièce": "Bureau", "Séjour/repas": "Bureau", "Cuisine": "Bureau"}  # else "Studio" (Italian plans)


def _pts(e):
    return [(float(x), float(y)) for x, y in e.get_points("xy")]


def _rect_info(poly: Polygon):
    """(axis, lo, hi, a, b) for an axis-aligned rectangle: axis 'x' means long side along x."""
    x0, y0, x1, y1 = poly.bounds
    if poly.area < 0.98 * (x1 - x0) * (y1 - y0):
        return None
    return ("x", x0, x1, y0, y1) if (x1 - x0) >= (y1 - y0) else ("y", y0, y1, x0, x1)


def make(doc_id: str, root: Path, art: Path, rng: random.Random) -> dict:
    from pipeline import dxf_planmap, pages
    d = json.loads((art / doc_id / "doc.json").read_text())
    src = root / d["files"]["dxf"]
    out = art / "revisions" / doc_id
    if out.exists():
        shutil.rmtree(out)
    (out / "v1").mkdir(parents=True)
    (out / "v2").mkdir()
    shutil.copy(src, out / "v1" / "plan.dxf")
    doc = ezdxf.readfile(str(src))
    ms = doc.modelspace()

    lines = pages.dxf_lines(doc)
    xs = [x for l in lines for x, _ in l]; ys = [y for l in lines for _, y in l]
    ext = box(min(xs), min(ys), max(xs), max(ys))
    interior = ext.buffer(-0.6)
    walls = [(e, Polygon(_pts(e))) for e in ms.query('LWPOLYLINE[layer=="WALL"]')]
    openings = [Polygon(_pts(e)).buffer(0.1) for e in ms.query("LWPOLYLINE")
                if e.dxf.layer in ("DOOR", "WINDOW") and len(_pts(e)) >= 4]

    def free(p):
        return not any(p.intersects(o) for o in openings)

    # 1) remove an interior wall
    c1 = [(e, p) for e, p in walls if interior.contains(p) and 0.4 < p.area < 2.5 and free(p)
          and max(p.bounds[2] - p.bounds[0], p.bounds[3] - p.bounds[1]) >= 1.0]
    rng.shuffle(c1)
    e_rm, p_rm = c1[0]
    # 2) split a straight wall and put a door in the gap
    c2 = []
    for e, p in walls:
        ri = _rect_info(p)
        if ri and p is not p_rm and p != p_rm and interior.contains(p) and free(p) and (ri[2] - ri[1]) >= 2.2 \
                and 0.08 <= (ri[4] - ri[3]) <= 0.35:
            c2.append((e, p, ri))
    rng.shuffle(c2)
    e_sp, p_sp, (axis, lo, hi, a, b) = c2[0]
    mid = (lo + hi) / 2
    g0, g1 = mid - GAP / 2, mid + GAP / 2
    # 3) rename a room: prefer 'Pièce'
    rooms = [(e, Polygon(_pts(e))) for e in ms.query('LWPOLYLINE[layer=="ROOM_OUTLINE"]') if e.closed]
    texts = list(ms.query('TEXT[layer=="ROOM_TEXT"]'))

    def tpos(t):
        v = t.dxf.align_point if t.dxf.hasattr("align_point") else t.dxf.insert
        return (v.x, v.y)
    from shapely.geometry import Point
    cand = []
    for re_, rp in rooms:
        ts = [t for t in texts if rp.contains(Point(tpos(t)))]
        nm = [t for t in ts if t.dxf.text in LABELS]
        if nm:
            cand.append((re_, rp, nm[0]))
    cand.sort(key=lambda c: c[2].dxf.text not in ("Pièce", "Camera da letto"))  # prefer plain bedrooms
    _, rp_ch, t_ch = cand[0]
    old_label = t_ch.dxf.text
    new_label = NEW_BY_OLD.get(old_label, "Studio")

    # --- apply edits
    for h in list(ms.query("HATCH")):  # wall fill belonging to the removed wall
        try:
            from ezdxf import bbox as zb
            bb = zb.extents([h])
            if p_rm.contains(Point((bb.extmin.x + bb.extmax.x) / 2, (bb.extmin.y + bb.extmax.y) / 2)):
                ms.delete_entity(h)
        except Exception:
            pass
    layer_attr = {"layer": "WALL"}
    ms.delete_entity(e_rm)
    ms.delete_entity(e_sp)
    parts = []
    for u0, u1 in ((lo, g0), (g1, hi)):
        rect = [(u0, a), (u1, a), (u1, b), (u0, b)] if axis == "x" else [(a, u0), (a, u1), (b, u1), (b, u0)]
        ms.add_lwpolyline(rect, close=True, dxfattribs=layer_attr)
        parts.append(Polygon(rect))
    if axis == "x":
        leaf = [(g0, a), (g1, a), (g1, b), (g0, b), (g0, a)]
        hinge, u, n = (g0, b), (1, 0), (0, 1)
    else:
        leaf = [(a, g0), (a, g1), (b, g1), (b, g0), (a, g0)]
        hinge, u, n = (b, g0), (0, 1), (1, 0)
    ms.add_lwpolyline(leaf, close=False, dxfattribs={"layer": "DOOR"})
    ms.add_line((hinge[0], hinge[1]), (hinge[0] - n[0] * GAP, hinge[1] - n[1] * GAP), dxfattribs={"layer": "DOOR"})
    au = math.degrees(math.atan2(u[1], u[0])) % 360
    ab = math.degrees(math.atan2(-n[1], -n[0])) % 360
    s_, e_ = (au, ab) if round((ab - au) % 360) == 90 else (ab, au)
    ms.add_arc(center=hinge, radius=GAP, start_angle=s_, end_angle=e_, dxfattribs={"layer": "DOOR"})
    t_ch.dxf.text = new_label
    doc.saveas(str(out / "v2" / "plan.dxf"))

    # --- render + plan-map both versions with the same frame
    frames = []
    for v in ("v1", "v2"):
        dx = out / v / "plan.dxf"
        pg = pages.do_dxf(dx, out / v)
        (out / v / "pages.json").write_text(json.dumps({"doc_id": doc_id, "source": "dxf", "pages": pg}))
        shutil.copy(art / doc_id / "doc.json", out / v / "doc.json")
        dxf_planmap.process(doc_id, out / v, dx)
        pm = json.loads((out / v / "planmap-1.json").read_text())
        pm["version"] = v
        pm["provenance"]["note"] += "; synthetic revision (generated for demo)"
        (out / v / "planmap-1.json").write_text(json.dumps(pm))
        frames.append((pg[0]["w"], pg[0]["h"], round(pg[0]["px_per_unit"], 6)))
    assert frames[0] == frames[1], f"frame changed {frames}"
    pm1 = json.loads((out / "v1" / "planmap-1.json").read_text())
    pm2 = json.loads((out / "v2" / "planmap-1.json").read_text())

    px = lambda pm: (lambda a_, bx, by: (lambda p: [round(a_ * p[0] + bx, 1), round(-a_ * p[1] + by, 1)]))(
        pm["registration"]["a"], pm["registration"]["bx"], pm["registration"]["by"])
    to_px = px(pm1)

    def bbox_of(poly):
        pts = [to_px(p) for p in poly.exterior.coords]
        xs_ = [q[0] for q in pts]; ys_ = [q[1] for q in pts]
        return [min(xs_), min(ys_), max(xs_), max(ys_)]

    def find(pm, kind, bb, label=None):
        best, bd = None, 1e9
        for it in pm["items"]:
            if it["kind"] != kind or (label is not None and it["label"] != label):
                continue
            dd = sum(abs(p - q) for p, q in zip(it["bbox_px"], bb))
            if dd < bd:
                best, bd = it, dd
        return best["item_id"] if best and bd < 6 else None

    door_poly = Polygon(leaf[:4])
    wb_rm, wb_door, wb_room = bbox_of(p_rm), bbox_of(door_poly), bbox_of(rp_ch)
    changes = [
        {"change_id": "c1", "type": "removed", "kind": "wall",
         "description": f"An interior wall about {max(p_rm.bounds[2]-p_rm.bounds[0], p_rm.bounds[3]-p_rm.bounds[1]):.1f} m long was removed.",
         "v1_item": find(pm1, "wall", wb_rm), "v2_item": None, "bbox_px_v1": wb_rm, "bbox_px_v2": None,
         "size_m": [round(p_rm.bounds[2] - p_rm.bounds[0], 2), round(p_rm.bounds[3] - p_rm.bounds[1], 2)]},
        {"change_id": "c2", "type": "added", "kind": "door",
         "description": "A door (0.9 m opening) was added in an interior wall; the wall was split into two parts.",
         "v1_item": None, "v2_item": find(pm2, "door", wb_door), "bbox_px_v1": None, "bbox_px_v2": wb_door,
         "width_m": GAP, "side_effects": [{"kind": "wall", "v1_item": find(pm1, "wall", bbox_of(p_sp)),
                                          "note": "split into two walls to open the gap"}]},
        {"change_id": "c3", "type": "modified", "kind": "room",
         "description": f"Room label changed from '{old_label}' to '{new_label}'.",
         "v1_item": find(pm1, "room", bbox_of(rp_ch), old_label),
         "v2_item": find(pm2, "room", bbox_of(rp_ch), new_label),
         "bbox_px_v1": wb_room, "bbox_px_v2": wb_room, "field": "label", "old": old_label, "new": new_label},
    ]
    assert all(c["v1_item"] or c["v2_item"] for c in changes), changes
    truth = {"doc_id": doc_id, "versions": ["v1", "v2"], "generated_for_demo": True,
             "note": "Synthetic revision made by pipeline.revisions from a CC BY Swiss Dwellings plan "
                     "(generated for demo). Same pixel frame in both versions.",
             "image": pm1["image"], "changes": changes}
    (out / "truth_changes.json").write_text(json.dumps(truth, indent=1))
    return truth


def main():
    root = REPO / "data" / "junction-dataset-preview"
    art = REPO / "artifacts"
    for i, did in enumerate(DOCS):
        t = make(did, root, art, random.Random(42 + i))
        print(did, [(c["change_id"], c["type"], c["kind"], c["v1_item"], c["v2_item"]) for c in t["changes"]])


if __name__ == "__main__":
    main()
