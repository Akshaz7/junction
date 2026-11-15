"""What still makes an IFC look converted? Geometric + semantic "tells" a BIM person spots, measured the same way on
ours and on a native reference (ac20_arc.ifc), so every tell has a native baseline next to it.

  .venv/bin/python scripts/ifc_tells.py ours.ifc [more.ifc ...] [--json out.json]

Per storey-independent checks (footprints from SweptSolid bodies via pipeline.ifc_enrich.footprint):
  walls_free_ends     wall axis ends (long side of the footprint's min rotated rectangle) not touching another wall
                      (within 5 cm): a native model has almost none outside free-standing walls.
  wall_overlap_pairs  wall pairs whose footprints overlap > 0.02 m2 (clash / z-fighting in a viewer).
  wall_heights        distinct wall heights (rounded 5 cm) and the share of walls at the most common height.
  wall_base_off       walls whose base is not at their storey elevation (+- 5 cm).
  door_in_wall        doors/windows whose footprint centre lies inside a wall footprint grown by 5 cm.
  door_heights / window_sills / window_heights   distinct values (rounded 5 cm).
  win_per_ext_m       external wall length (Pset_WallCommon.IsExternal) per window (m): native facades ~3-5 m.
  slab_cover          slab area / area of the union of space footprints (a native floor slab covers the spaces).
  ceilings_roofs      IfcCovering CEILING + IfcRoof + slabs above the top storey's walls.
  space_wall_overlap  share of space area overlapping wall footprints (spaces drawn to wall centrelines or through).
  placeholder_names   elements whose Name looks generated ('Wall-001', 'Door 3', 'Space', 'Element').
  wet_rooms_no_fix    spaces named like a WC/bath/shower/kitchen with no sanitary terminal / sink inside.
  stair_rise          per IfcStair: height of its body (zmax - zmin), vs storey height.
All generic, no per-file rules.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ifcopenshell  # noqa: E402
import ifcopenshell.util.element as ue  # noqa: E402
from shapely.geometry import LineString, Point  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402

from pipeline.ifc_enrich import footprint, _MC  # noqa: E402

PLACEHOLDER = re.compile(r"^(wall|door|window|space|room|slab|element|object|proxy|stair|railing|column|furniture|"
                         r"sanitary|fixture|opening)[\s_-]*\d*$", re.I)
WET = re.compile(r"\b(wc|toilet|bath|bathroom|shower|restroom|lavatory|kitchen|kitchenette|wash|bad|dusche|küche|"
                 r"kylpy|keittiö|pesu|sauna|janitor|jan\.?|mens|womens|men|women)\b", re.I)


def _r(x, q=0.05):
    return round(round(x / q) * q, 2)


def _axis(poly):
    """Long-axis end points + thickness of a wall footprint (its min rotated rectangle)."""
    r = poly.minimum_rotated_rectangle
    c = list(r.exterior.coords)[:4]
    e = [(c[i], c[(i + 1) % 4]) for i in range(4)]
    L = [np.hypot(b[0] - a[0], b[1] - a[1]) for a, b in e]
    i = int(np.argmax(L))
    a, b = e[i]
    a2, b2 = e[(i + 2) % 4]
    t = min(L)
    p0 = ((a[0] + b2[0]) / 2, (a[1] + b2[1]) / 2)
    p1 = ((b[0] + a2[0]) / 2, (b[1] + a2[1]) / 2)
    return p0, p1, t, max(L)


def _storey_elev(el):
    s = ue.get_container(el)
    while s is not None and not s.is_a("IfcBuildingStorey"):
        s = ue.get_aggregate(s)
    return (s.Elevation or 0.0) if s is not None else None, (s.Name if s is not None else None)


def tells(path):
    _MC.clear()  # footprint cache is keyed by entity id: ids repeat across files
    f = ifcopenshell.open(path)
    out = {"file": str(path)}
    walls = f.by_type("IfcWall")
    W = []
    for w in walls:
        fp, z = footprint(w)
        if fp is None or fp.is_empty or fp.area <= 0:
            continue
        W.append((w, fp, z))
    out["walls"] = len(walls)
    out["walls_with_footprint"] = len(W)
    if W:
        polys = [fp for _, fp, _ in W]
        tree = STRtree(polys)
        free, ends = 0, 0
        overl, ov_area = 0, 0.0
        for i, (w, fp, z) in enumerate(W):
            p0, p1, t, L = _axis(fp)
            for p in (p0, p1):
                ends += 1
                pt = Point(p).buffer(max(t / 2, 0.05) + 0.05)
                hit = [j for j in tree.query(pt) if j != i and polys[j].intersects(pt)]
                if not hit:
                    free += 1
            for j in tree.query(fp):
                if j <= i:
                    continue
                a = fp.intersection(polys[j]).area
                if a > 0.02:
                    overl += 1
                    ov_area += a
        out["walls_free_ends"] = f"{free}/{ends}"
        out["walls_free_end_frac"] = round(free / ends, 3) if ends else None
        out["wall_overlap_pairs"] = overl
        out["wall_overlap_m2"] = round(ov_area, 2)
        hs = collections.Counter(_r(z[1] - z[0]) for _, _, z in W)
        out["wall_heights"] = dict(hs.most_common(6))
        out["wall_height_mode_frac"] = round(hs.most_common(1)[0][1] / len(W), 3)
        off = 0
        for w, fp, z in W:
            e, _ = _storey_elev(w)
            if e is not None and abs(z[0] - e) > 0.05:
                off += 1
        out["wall_base_off_storey"] = off
        out["wall_thickness"] = dict(collections.Counter(_r(_axis(fp)[2], 0.01) for _, fp, _ in W).most_common(5))
        grown = unary_union([p.buffer(0.05) for p in polys])
        ext = 0.0
        for w, fp, z in W:
            ps = ue.get_pset(w, "Pset_WallCommon") or {}
            if ps.get("IsExternal"):
                ext += _axis(fp)[3]
    else:
        grown, ext = None, 0.0
    for cls, key in (("IfcDoor", "doors"), ("IfcWindow", "windows")):
        els = f.by_type(cls)
        inw, hs, sills, nofp = 0, collections.Counter(), collections.Counter(), 0
        for d in els:
            fp, z = footprint(d)
            if fp is None:
                # doors/windows in native files are often Brep / mapped: fall back to placement + OverallHeight
                nofp += 1
                if d.OverallHeight:
                    hs[_r(float(d.OverallHeight))] += 1
                continue
            hs[_r(z[1] - z[0])] += 1
            e, _ = _storey_elev(d)
            if e is not None:
                sills[_r(z[0] - e)] += 1
            if grown is not None and grown.contains(fp.centroid):
                inw += 1
        out[key] = len(els)
        out[f"{key}_centre_in_wall"] = f"{inw}/{len(els) - nofp}" if len(els) - nofp else "n/a (no SweptSolid body)"
        out[f"{key}_heights"] = dict(hs.most_common(5))
        out[f"{key}_sills"] = dict(sills.most_common(5))
    nwin = len(f.by_type("IfcWindow"))
    out["ext_wall_m"] = round(ext, 1)
    out["ext_wall_m_per_window"] = round(ext / nwin, 1) if nwin else None
    spaces = []
    for s in f.by_type("IfcSpace"):
        fp, z = footprint(s)
        if fp is not None:
            spaces.append((s, fp, z))
    out["spaces"] = len(f.by_type("IfcSpace"))
    sp_u = unary_union([fp for _, fp, _ in spaces]) if spaces else None
    slabs = [(s, *footprint(s)) for s in f.by_type("IfcSlab")]
    slab_fp = [fp for _, fp, _ in slabs if fp is not None]
    out["slabs"] = len(slabs)
    out["slab_types"] = dict(collections.Counter(str(s.PredefinedType) for s, _, _ in slabs))
    if sp_u is not None and slab_fp:
        out["slab_cover_of_spaces"] = round(unary_union(slab_fp).intersection(sp_u).area / sp_u.area, 3)
    if sp_u is not None and W:
        wu = unary_union([fp for _, fp, _ in W])
        out["space_wall_overlap_frac"] = round(sp_u.intersection(wu).area / sp_u.area, 4)
        out["space_heights"] = dict(collections.Counter(_r(z[1] - z[0]) for _, _, z in spaces).most_common(4))
    top_wall = max((z[1] for _, _, z in W), default=None)
    out["ceilings"] = sum(1 for c in f.by_type("IfcCovering") if str(c.PredefinedType) == "CEILING")
    out["coverings"] = len(f.by_type("IfcCovering"))
    out["roofs"] = len(f.by_type("IfcRoof"))
    out["slabs_at_or_above_wall_top"] = sum(1 for _, _, z in slabs if z and top_wall and z[1] >= top_wall - 0.05)
    out["columns"] = len(f.by_type("IfcColumn"))
    out["beams"] = len(f.by_type("IfcBeam"))
    ph, tot = collections.Counter(), 0
    for el in f.by_type("IfcElement"):
        if el.is_a("IfcOpeningElement"):
            continue
        tot += 1
        if not el.Name or PLACEHOLDER.match(el.Name.strip()):
            ph[el.is_a()] += 1
    out["placeholder_names"] = f"{sum(ph.values())}/{tot}"
    out["placeholder_by_class"] = dict(ph.most_common(6))
    out["name_examples"] = {c: sorted({e.Name for e in f.by_type(c) if e.Name})[:3]
                            for c in ("IfcWall", "IfcDoor", "IfcWindow", "IfcSlab")}
    fix = [footprint(e)[0] for e in f.by_type("IfcSanitaryTerminal") + f.by_type("IfcFlowTerminal")
           + f.by_type("IfcFurniture") + f.by_type("IfcFurnishingElement")]
    fix = [p.centroid for p in fix if p is not None]
    wet, wet_no = 0, []
    for s, fp, z in spaces:
        nm = f"{s.Name or ''} {s.LongName or ''}"
        if WET.search(nm):
            wet += 1
            if not any(fp.buffer(0.1).contains(c) for c in fix):
                wet_no.append(nm.strip())
    out["wet_rooms"] = wet
    out["wet_rooms_without_fixture"] = len(wet_no)
    out["wet_rooms_without_fixture_eg"] = wet_no[:6]
    out["sanitary"] = len(f.by_type("IfcSanitaryTerminal"))
    out["furniture"] = len(f.by_type("IfcFurniture")) + len(f.by_type("IfcFurnishingElement"))
    st = []
    for s in f.by_type("IfcStair"):
        zs = []
        for p in [s] + list(ue.get_decomposition(s)):
            fp, z = footprint(p)
            if z:
                zs += list(z)
        st.append(_r(max(zs) - min(zs)) if zs else None)
    out["stairs"] = len(st)
    out["stair_rise_m"] = dict(collections.Counter(st).most_common(4))
    out["railings"] = len(f.by_type("IfcRailing"))
    out["storeys"] = [(s.Name, s.Elevation) for s in f.by_type("IfcBuildingStorey")]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ifc", nargs="+")
    ap.add_argument("--json")
    a = ap.parse_args()
    rows = [tells(p) for p in a.ifc]
    keys = list(dict.fromkeys(k for r in rows for k in r))
    print("| tell | " + " | ".join(Path(r["file"]).parent.name + "/" + Path(r["file"]).stem for r in rows) + " |")
    print("|---|" + "---|" * len(rows))
    for k in keys:
        if k == "file":
            continue
        print(f"| {k} | " + " | ".join(str(r.get(k, "")).replace("|", "/") for r in rows) + " |")
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
