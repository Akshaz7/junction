"""Post-process a generated IFC so it carries the structure a native authoring-tool IFC has.

enrich(ifc_path) -> dict of counts. Edits the file in place, idempotent (skips what is already present).
Compared against data/.../ifc_bench/ac20_arc.ifc (ARCHICAD 20). Adds, computed from the file's own extrusions:
- IfcOwnerHistory + IfcApplication/IfcPerson/IfcOrganization on every IfcRoot; PLANEANGLEUNIT (radian)
- Qto_WallBaseQuantities NetSideArea/NetVolume (openings subtracted), Pset_WallCommon.LoadBearing
- IfcMaterialLayerSetUsage on walls whose type has a layer set (instead of a bare IfcMaterial)
- Axis/Curve2D (Plan/Axis context) on walls without one: long centreline of the footprint's min rectangle
- Box/BoundingBox representation on walls, slabs, doors, windows
- IfcSlabType (FLOOR) + layer set usage + Pset_SlabCommon; Pset_SpaceCommon; Qto_SpaceBaseQuantities GrossVolume
- IfcRelSpaceBoundary (PHYSICAL, INTERNAL/EXTERNAL) between each space and the walls touching it
- IfcRelConnectsPathElements between walls whose footprints touch
No new geometry is invented: everything comes from footprints (shapely, metres) of the existing extrusions.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np
import ifcopenshell
import ifcopenshell.api.material
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.type
import ifcopenshell.api.context
import ifcopenshell.guid
import ifcopenshell.util.element as ue
import ifcopenshell.util.placement as up
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union
from shapely.strtree import STRtree

_MC: dict = {}


def _lp(pl):
    k = ("L", pl.id())
    if k not in _MC:
        _MC[k] = up.get_local_placement(pl)
    return _MC[k]


def _a2p(pl):
    k = ("A", pl.id())
    if k not in _MC:
        _MC[k] = up.get_axis2placement(pl)
    return _MC[k]


APP = ("Hologram", "Hologram PDF-to-IFC", "1.0", "HOLOGRAM-PDF2IFC")


def _ring(curve):
    if curve.is_a("IfcIndexedPolyCurve"):
        return [tuple(p[:2]) for p in curve.Points.CoordList]
    if curve.is_a("IfcPolyline"):
        return [tuple(p.Coordinates[:2]) for p in curve.Points]
    return None


def _profile_poly(prof):
    if prof.is_a("IfcRectangleProfileDef"):
        hx, hy = prof.XDim / 2, prof.YDim / 2
        pts = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
        if prof.Position is not None:
            m = up.get_axis2placement(prof.Position)
            pts = [tuple((m @ np.array([x, y, 0, 1]))[:2]) if m.shape == (4, 4) else
                   tuple((m @ np.array([x, y, 1]))[:2]) for x, y in pts]
        return Polygon(pts)
    if prof.is_a("IfcArbitraryClosedProfileDef"):
        ext = _ring(prof.OuterCurve)
        if not ext or len(ext) < 3:
            return None
        holes = [r for r in (_ring(c) for c in getattr(prof, "InnerCurves", None) or []) if r and len(r) >= 3]
        return Polygon(ext, holes)
    return None


def footprint(el):
    """World-XY footprint (metres) and (zmin, zmax) of an element's SweptSolid body, or (None, None)."""
    if not el.Representation or not el.ObjectPlacement:
        return None, None
    M = _lp(el.ObjectPlacement)
    polys, zs = [], []
    for rep in el.Representation.Representations:
        if rep.RepresentationIdentifier != "Body":
            continue
        for it in rep.Items:
            if not it.is_a("IfcExtrudedAreaSolid"):
                continue
            p = _profile_poly(it.SweptArea)
            if p is None or not p.is_valid and not (p := p.buffer(0)).area:
                continue
            P = M @ _a2p(it.Position) if it.Position else M
            pts = [tuple((P @ np.array([x, y, 0.0, 1.0]))[:2]) for x, y in p.exterior.coords]
            holes = [[tuple((P @ np.array([x, y, 0.0, 1.0]))[:2]) for x, y in r.coords] for r in p.interiors]
            polys.append(Polygon(pts, holes).buffer(0))
            z0 = float(P[2, 3])
            zs += [z0, z0 + float(it.Depth)]
    if not polys:
        return None, None
    return unary_union(polys), (min(zs), max(zs))


def _owner(f, counts):
    ohs = f.by_type("IfcOwnerHistory")
    if ohs:
        oh = ohs[0]
    else:
        person = f.createIfcPerson(None, None, "Hologram", None, None, None, None, None)
        org = f.createIfcOrganization(None, "Hologram", None, None, None)
        po = f.createIfcPersonAndOrganization(person, org, None)
        app = f.createIfcApplication(org, APP[2], APP[1], APP[3])
        now = int(time.time())
        oh = f.createIfcOwnerHistory(po, app, None, "ADDED", now, po, app, now)
        counts["owner_history"] = 1
    n = 0
    for r in f.by_type("IfcRoot"):
        if r.OwnerHistory is None:
            r.OwnerHistory = oh
            n += 1
    counts["owner_history_assigned"] = n
    return oh


def _units(f, counts):
    ua = f.by_type("IfcUnitAssignment")
    if not ua:
        return
    have = {u.UnitType for u in ua[0].Units if hasattr(u, "UnitType")}
    add = []
    for t, name in (("PLANEANGLEUNIT", "RADIAN"), ("TIMEUNIT", "SECOND"), ("SOLIDANGLEUNIT", "STERADIAN")):
        if t not in have:
            add.append(f.createIfcSIUnit(None, t, None, name))
    if add:
        ua[0].Units = tuple(ua[0].Units) + tuple(add)
        counts["units"] = len(add)


def _qto_set(f, el, name, props):
    q = ue.get_psets(el, qtos_only=True).get(name)
    qto = f.by_id(q["id"]) if q else ifcopenshell.api.pset.add_qto(f, product=el, name=name)
    have = set(q or {})
    new = {k: float(v) for k, v in props.items() if k not in have and v is not None}
    if new:
        ifcopenshell.api.pset.edit_qto(f, qto=qto, properties=new)
    return len(new)


def _pset_set(f, el, name, props):
    p = ue.get_psets(el, psets_only=True).get(name)
    pset = f.by_id(p["id"]) if p else ifcopenshell.api.pset.add_pset(f, product=el, name=name)
    have = {k for k, v in (p or {}).items() if v is not None}
    new = {k: v for k, v in props.items() if k not in have and v is not None}
    if new:
        ifcopenshell.api.pset.edit_pset(f, pset=pset, properties=new)
    return len(new)


def _opening_area(el):
    """Sum of filled-opening face areas (w*h) and volumes in a wall."""
    a = v = 0.0
    for rel in getattr(el, "HasOpenings", None) or []:
        op = rel.RelatedOpeningElement
        fp, z = footprint(op)
        fill = [r.RelatedBuildingElement for r in (op.HasFillings or [])]
        q = ue.get_psets(fill[0], qtos_only=True) if fill else {}
        q = next(iter(q.values()), {}) if q else {}
        if q.get("Width") and q.get("Height"):
            a += float(q["Width"]) * float(q["Height"])
        elif fp is not None and z:
            mrr = fp.minimum_rotated_rectangle
            xs = list(mrr.exterior.coords)
            L = max(LineString(xs[i:i + 2]).length for i in range(2))
            a += L * (z[1] - z[0])
        if fp is not None and z:
            v += fp.area * (z[1] - z[0])
    return a, v


def _axis_of(fp):
    mrr = fp.minimum_rotated_rectangle
    c = list(mrr.exterior.coords)[:4]
    if len(c) < 4:
        return None, 0.0
    e = [LineString([c[i], c[(i + 1) % 4]]) for i in range(4)]
    i = 0 if e[0].length >= e[1].length else 1
    a, b = e[i], e[i + 2]
    p0 = ((a.coords[0][0] + b.coords[1][0]) / 2, (a.coords[0][1] + b.coords[1][1]) / 2)
    p1 = ((a.coords[1][0] + b.coords[0][0]) / 2, (a.coords[1][1] + b.coords[0][1]) / 2)
    return LineString([p0, p1]), e[1 - i].length


def _to_local(el, pts):
    Mi = np.linalg.inv(_lp(el.ObjectPlacement))
    return [tuple(float(round(v, 5)) for v in (Mi @ np.array([x, y, 0.0, 1.0]))[:2]) for x, y in pts]


def _ctx(f, ident):
    for c in f.by_type("IfcGeometricRepresentationSubContext"):
        if c.ContextIdentifier == ident:
            return c
    model = next((c for c in f.by_type("IfcGeometricRepresentationContext", include_subtypes=False)
                  if c.ContextType == "Model"), None)
    if ident == "Axis":
        plan = next((c for c in f.by_type("IfcGeometricRepresentationContext", include_subtypes=False)
                     if c.ContextType == "Plan"), None) or ifcopenshell.api.context.add_context(f, context_type="Plan")
        return ifcopenshell.api.context.add_context(f, context_type="Plan", context_identifier="Axis",
                                                    target_view="GRAPH_VIEW", parent=plan)
    return ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier=ident,
                                                target_view="MODEL_VIEW", parent=model)


def _has_rep(el, ident):
    return any(r.RepresentationIdentifier == ident for r in el.Representation.Representations)


def _add_box(f, el, fp, z, counts):
    if _has_rep(el, "Box"):
        return
    Mi = np.linalg.inv(_lp(el.ObjectPlacement))
    x0, y0, x1, y1 = fp.bounds
    corners = [Mi @ np.array([x, y, zz, 1.0]) for x in (x0, x1) for y in (y0, y1) for zz in z]
    lo, hi = np.min(corners, axis=0)[:3], np.max(corners, axis=0)[:3]
    box = f.createIfcBoundingBox(f.createIfcCartesianPoint(tuple(float(v) for v in lo)),
                                 *(float(max(v, 1e-4)) for v in hi - lo))
    rep = f.createIfcShapeRepresentation(_ctx(f, "Box"), "Box", "BoundingBox", [box])
    el.Representation.Representations = tuple(el.Representation.Representations) + (rep,)
    counts["box_reps"] = counts.get("box_reps", 0) + 1


FIRE_RE = re.compile(r"\b(R?EI(?:-?M)?\s?\d{2,3}|E\s?\d{2,3}|F\s?\d{2,3}|\d\s?h(?:ou)?r)\b", re.I)
LAYERS = (("A-WALL", ("IfcWall", "IfcSlab", "IfcColumn", "IfcBeam")), ("A-DOOR", ("IfcDoor",)),
          ("A-GLAZ", ("IfcWindow",)), ("A-AREA", ("IfcSpace",)))


def _sidecar_fire(ifc_path: Path) -> dict:
    """item_id -> fire rating from planmap-*.json next to the IFC (props.fire_rating / fire / EI.. in label)."""
    out = {}
    for pm in sorted(ifc_path.parent.glob("planmap-*.json")):
        try:
            items = json.loads(pm.read_text()).get("items") or []
        except Exception:  # noqa: BLE001
            continue
        for it in items:
            pr = it.get("props") or {}
            v = pr.get("fire_rating") or pr.get("fire")
            if not v:
                m = FIRE_RE.search(" ".join(str(x) for x in (it.get("label"), pr.get("tag"), pr.get("mark")) if x))
                v = m.group(1) if m else None
            if v and it.get("item_id"):
                out[str(it["item_id"])] = str(v).replace(" ", "").upper()
    return out


def _fire_of(el, side: dict):
    ps = ue.get_psets(el)
    iid = (ps.get("Hologram_Provenance") or {}).get("item_id")
    if iid and iid in side:
        return side[iid]
    for name, props in ps.items():
        if name.endswith("Common") and props.get("FireRating"):
            return None  # already set
        for k, v in props.items():
            if k != "id" and isinstance(v, str) and (m := FIRE_RE.search(v)) and "fire" in k.lower():
                return m.group(1).replace(" ", "").upper()
    return None


def _fire_ratings(f, ifc_path, counts):
    side = _sidecar_fire(ifc_path)
    n = 0
    for cls, pset in (("IfcWall", "Pset_WallCommon"), ("IfcDoor", "Pset_DoorCommon"), ("IfcWindow", "Pset_WindowCommon")):
        for el in f.by_type(cls):
            v = _fire_of(el, side)
            if v:
                n += _pset_set(f, el, pset, {"FireRating": v})
    counts["fire_ratings"] = n


def _opening_materials(f, counts):
    mats = {}

    def mat(name, cat):
        if name not in mats:
            mats[name] = next((m for m in f.by_type("IfcMaterial") if m.Name == name), None) or \
                ifcopenshell.api.material.add_material(f, name=name, category=cat)
        return mats[name]
    n = 0
    for el in list(f.by_type("IfcDoor")) + list(f.by_type("IfcWindow")):
        t = ue.get_type(el)
        target = t or el
        if ue.get_material(target) is not None or ue.get_material(el) is not None:
            continue
        name = (t.Name if t else el.Name or "").lower()
        if el.is_a("IfcWindow") or "glass" in name or "glaz" in name:
            ifcopenshell.api.material.assign_material(f, products=[target], material=mat("Glass", "glass"))
        else:
            ifcopenshell.api.material.assign_material(f, products=[target], material=mat("Wood", "wood"))
        n += 1
    counts["opening_materials"] = n


def _space_types(f, counts):
    have = {t.Name: t for t in f.by_type("IfcSpaceType")}
    n = 0
    for sp in f.by_type("IfcSpace"):
        if ue.get_type(sp) is not None:
            continue
        rt = (ue.get_psets(sp).get("Hologram_RoomArea") or {}).get("RoomType")
        name = (rt or sp.LongName or sp.Name or "Space").strip()
        name = re.sub(r"\s*\d+([.,]\d+)?\s*m.*$", "", name).strip() or "Space"
        if name not in have:
            have[name] = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSpaceType", name=name,
                                                             predefined_type="SPACE")
            n += 1
        ifcopenshell.api.type.assign_type(f, related_objects=[sp], relating_type=have[name])
    counts["space_types"] = n


def _layers(f, counts):
    existing = {la.Name: la for la in f.by_type("IfcPresentationLayerAssignment")}
    n = 0
    for lname, classes in LAYERS:
        reps = []
        for cls in classes:
            for el in f.by_type(cls):
                if el.Representation:
                    reps += [r for r in el.Representation.Representations if not r.LayerAssignments]
        if not reps:
            continue
        if lname in existing:
            existing[lname].AssignedItems = tuple(existing[lname].AssignedItems) + tuple(reps)
        else:
            f.createIfcPresentationLayerAssignment(lname, None, reps, None)
            n += 1
    counts["layers"] = n


def enrich(ifc_path) -> dict:
    ifc_path = Path(ifc_path)
    f = ifcopenshell.open(str(ifc_path))
    _MC.clear()
    counts: dict = {}
    _units(f, counts)

    walls = [w for w in f.by_type("IfcWall") if w.Representation]
    fps = {}
    for w in walls:
        fp, z = footprint(w)
        if fp is not None and not fp.is_empty:
            fps[w.id()] = (w, fp, z)

    # walls: qtos, load bearing, axis, layer-set usage, box
    for wid, (w, fp, z) in fps.items():
        h = z[1] - z[0]
        axis, width = _axis_of(fp)
        L = axis.length if axis is not None else 0.0
        oa, ov = _opening_area(w)
        counts["wall_qto_props"] = counts.get("wall_qto_props", 0) + _qto_set(
            f, w, "Qto_WallBaseQuantities", {"Length": L, "Width": width, "Height": h,
                                              "GrossFootprintArea": fp.area, "NetFootprintArea": fp.area,
                                              "GrossSideArea": L * h, "NetSideArea": max(L * h - oa, 0.0),
                                              "GrossVolume": fp.area * h, "NetVolume": max(fp.area * h - ov, 0.0)})
        ext = (ue.get_psets(w).get("Pset_WallCommon") or {}).get("IsExternal")
        counts["wall_pset_props"] = counts.get("wall_pset_props", 0) + _pset_set(
            f, w, "Pset_WallCommon", {"LoadBearing": bool(ext) or width >= 0.2, "IsExternal": bool(ext)})
        if axis is not None and not _has_rep(w, "Axis") and L > 0.05:
            pl = f.createIfcPolyline([f.createIfcCartesianPoint(p) for p in _to_local(w, axis.coords)])
            rep = f.createIfcShapeRepresentation(_ctx(f, "Axis"), "Axis", "Curve2D", [pl])
            w.Representation.Representations = (rep,) + tuple(w.Representation.Representations)
            counts["axis_reps"] = counts.get("axis_reps", 0) + 1
        mat = ue.get_material(w, should_skip_usage=False)
        t = ue.get_type(w)
        tmat = ue.get_material(t) if t else None
        if (mat is None or mat.is_a("IfcMaterial")) and tmat is not None and tmat.is_a("IfcMaterialLayerSet"):
            for rel in list(getattr(w, "HasAssociations", None) or []):
                if rel.is_a("IfcRelAssociatesMaterial") and rel.RelatingMaterial.is_a("IfcMaterial"):
                    objs = [o for o in rel.RelatedObjects if o != w]
                    if objs:
                        rel.RelatedObjects = objs
                    else:
                        f.remove(rel)
            usage = f.createIfcMaterialLayerSetUsage(tmat, "AXIS2", "POSITIVE", -sum(
                l.LayerThickness for l in tmat.MaterialLayers) / 2, None)
            f.createIfcRelAssociatesMaterial(ifcopenshell.guid.new(), f.by_type("IfcOwnerHistory")[0]
                                             if f.by_type("IfcOwnerHistory") else None, None, None, [w], usage)
            counts["layer_set_usage"] = counts.get("layer_set_usage", 0) + 1
        _add_box(f, w, fp, z, counts)

    # wall-wall connections
    if not f.by_type("IfcRelConnectsPathElements") and fps:
        items = list(fps.values())
        tree = STRtree([it[1] for it in items])
        n = 0
        for i, (w, fp, _) in enumerate(items):
            for j in tree.query(fp.buffer(0.02)):
                j = int(j)
                if j <= i or not fp.buffer(0.02).intersects(items[j][1]):
                    continue
                f.createIfcRelConnectsPathElements(ifcopenshell.guid.new(), None, None, None, None, w, items[j][0],
                                                   [], [], "NOTDEFINED", "NOTDEFINED")
                n += 1
        counts["wall_connections"] = n

    # slabs: type, material usage, pset, box
    slabs = [s for s in f.by_type("IfcSlab") if s.Representation]
    st = next((t for t in f.by_type("IfcSlabType")), None)
    for s in slabs:
        fp, z = footprint(s)
        if fp is None:
            continue
        depth = z[1] - z[0]
        if ue.get_type(s) is None:
            if st is None:
                st = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSlabType", name="Floor slab",
                                                         predefined_type="FLOOR")
                mat = ifcopenshell.api.material.add_material(f, name="Concrete", category="concrete")
                ls = ifcopenshell.api.material.add_material_set(f, name="Floor slab", set_type="IfcMaterialLayerSet")
                lay = ifcopenshell.api.material.add_layer(f, layer_set=ls, material=mat)
                lay.LayerThickness = max(depth, 0.01)
                ifcopenshell.api.material.assign_material(f, products=[st], type="IfcMaterialLayerSet", material=ls)
                counts["slab_types"] = 1
            ifcopenshell.api.type.assign_type(f, related_objects=[s], relating_type=st)
            if ue.get_material(s) is None:
                ifcopenshell.api.material.assign_material(f, products=[s], type="IfcMaterialLayerSetUsage",
                                                          material=ue.get_material(st))
        _qto_set(f, s, "Qto_SlabBaseQuantities", {"Depth": depth, "GrossArea": fp.area, "NetArea": fp.area,
                                                  "Perimeter": fp.length, "GrossVolume": fp.area * depth,
                                                  "NetVolume": fp.area * depth})
        counts["slab_pset_props"] = counts.get("slab_pset_props", 0) + _pset_set(
            f, s, "Pset_SlabCommon", {"IsExternal": False, "LoadBearing": True})
        _add_box(f, s, fp, z, counts)

    for el in list(f.by_type("IfcDoor")) + list(f.by_type("IfcWindow")):
        if el.Representation:
            fp, z = footprint(el)
            if fp is not None:
                _add_box(f, el, fp, z, counts)

    # spaces: pset, volume, boundaries
    have_sb = {(r.RelatingSpace.id(), r.RelatedBuildingElement.id()) for r in f.by_type("IfcRelSpaceBoundary")
               if r.RelatingSpace and r.RelatedBuildingElement}
    items = list(fps.values())
    tree = STRtree([it[1] for it in items]) if items else None
    nsb = 0
    for sp in f.by_type("IfcSpace"):
        fp, z = footprint(sp)
        counts["space_pset_props"] = counts.get("space_pset_props", 0) + _pset_set(
            f, sp, "Pset_SpaceCommon", {"IsExternal": False, "Reference": sp.LongName or sp.Name})
        if fp is None or tree is None:
            continue
        _qto_set(f, sp, "Qto_SpaceBaseQuantities", {"GrossVolume": fp.area * (z[1] - z[0]),
                                                    "NetVolume": fp.area * (z[1] - z[0])})
        ring = fp.buffer(0.15)
        for j in tree.query(ring):
            w = items[int(j)][0]
            if (sp.id(), w.id()) in have_sb or not ring.intersects(items[int(j)][1]):
                continue
            ext = bool((ue.get_psets(w).get("Pset_WallCommon") or {}).get("IsExternal"))
            f.createIfcRelSpaceBoundary(ifcopenshell.guid.new(), None, None, None, sp, w, None, "PHYSICAL",
                                        "EXTERNAL" if ext else "INTERNAL")
            nsb += 1
    counts["space_boundaries"] = nsb

    _fire_ratings(f, ifc_path, counts)
    _opening_materials(f, counts)
    _space_types(f, counts)
    _layers(f, counts)
    _owner(f, counts)  # last, so every new rooted entity gets it
    f.write(str(ifc_path))
    return counts
