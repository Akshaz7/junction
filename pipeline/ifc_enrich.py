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
import math
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
from shapely.geometry import Point, Polygon, LineString
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
            m = _a2p(prof.Position)
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
    k = ("F", el.id())
    if k not in _MC:
        _MC[k] = _footprint(el)
    return _MC[k]


def _xy(P, coords):
    a = np.asarray(coords, dtype=float)[:, :2]
    return (a @ P[:2, :2].T + P[:2, 3]).tolist()


def _footprint(el):
    M = _lp(el.ObjectPlacement)
    polys, zs = [], []
    for rep in el.Representation.Representations:
        if rep.RepresentationIdentifier != "Body":
            continue
        for it in rep.Items:
            while it.is_a("IfcBooleanResult") and it.FirstOperand is not None:  # Clipping: the extrusion is operand 1
                it = it.FirstOperand
            if not it.is_a("IfcExtrudedAreaSolid"):
                continue
            p = _profile_poly(it.SweptArea)
            if p is None or not p.is_valid and not (p := p.buffer(0)).area:
                continue
            P = M @ _a2p(it.Position) if it.Position else M
            q = Polygon(_xy(P, p.exterior.coords), [_xy(P, r.coords) for r in p.interiors])
            polys.append(q if q.is_valid else q.buffer(0))
            z0 = float(P[2, 3])
            zs += [z0, z0 + float(it.Depth)]
    if not polys:
        return None, None
    return (polys[0] if len(polys) == 1 else unary_union(polys)), (min(zs), max(zs))


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
        if r.OwnerHistory is None or r.OwnerHistory != oh:  # api calls may mint one per edit; native has one
            r.OwnerHistory = oh
            n += 1
    for o in ohs[1:]:
        if not f.get_inverse(o):
            f.remove(o)
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
    k = ("X", id(fp))
    if k in _MC and _MC[k][0] is fp:
        return _MC[k][1]
    mrr = fp.minimum_rotated_rectangle
    c = np.asarray(mrr.exterior.coords)[:4] if mrr.geom_type == "Polygon" else []
    if len(c) < 4:
        res = (None, 0.0)
    else:
        l0, l1 = float(np.linalg.norm(c[1] - c[0])), float(np.linalg.norm(c[2] - c[1]))
        a0, a1, b0, b1, width = (c[0], c[1], c[2], c[3], l1) if l0 >= l1 else (c[1], c[2], c[3], c[0], l0)
        res = (LineString([tuple((a0 + b1) / 2), tuple((a1 + b0) / 2)]), width)
    _MC[k] = (fp, res)
    return res


def _to_local(el, pts):
    k = ("I", el.ObjectPlacement.id())
    if k not in _MC:
        _MC[k] = np.linalg.inv(_lp(el.ObjectPlacement))
    return [tuple(float(v) for v in r) for r in np.round(_xy(_MC[k], pts), 5)]


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
          ("A-GLAZ", ("IfcWindow",)), ("A-AREA", ("IfcSpace",)),
          ("A-FLOR-STRS", ("IfcStair", "IfcStairFlight", "IfcRailing", "IfcRamp")),
          ("P-SANR-FIXT", ("IfcSanitaryTerminal",)), ("A-FURN", ("IfcFurnishingElement",)),
          ("A-CONV", ("IfcTransportElement",)), ("A-GENM", ("IfcBuildingElementProxy", "IfcCovering", "IfcRoof")),
          ("A-ANNO-TEXT", ("IfcAnnotation",)))


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


# ---- native-structure extras (r3): spatial names/elevations, types+materials for all, material styles,
# FootPrint reps, connection ends, space names/qtos, door/window qtos, one IfcMaterial per name, StandardCase.
TYPED_CLASSES = ("IfcWall", "IfcDoor", "IfcWindow", "IfcSlab", "IfcColumn", "IfcBeam", "IfcStair", "IfcStairFlight",
                 "IfcRailing", "IfcCovering", "IfcFurnishingElement", "IfcRoof", "IfcCurtainWall", "IfcPlate",
                 "IfcMember", "IfcSanitaryTerminal", "IfcFlowTerminal", "IfcTransportElement",
                 "IfcBuildingElementProxy")
DEFAULT_MAT = (("IfcWindow", "Glass", "glass"), ("IfcCurtainWall", "Glass", "glass"), ("IfcPlate", "Glass", "glass"),
               ("IfcDoor", "Wood", "wood"), ("IfcFurnishingElement", "Wood", "wood"),
               ("IfcRailing", "Steel", "steel"), ("IfcTransportElement", "Steel", "steel"), ("IfcMember", "Steel", "steel"), ("IfcBeam", "Concrete", "concrete"),
               ("IfcSanitaryTerminal", "Ceramic", "ceramic"), ("IfcFlowTerminal", "Ceramic", "ceramic"),
               ("IfcCovering", "Plaster", "plaster"))
PALETTE = {  # material category -> (rgb, transparency), roughly what ArchiCAD/Revit export
    "concrete": ((0.75, 0.75, 0.75), 0.0), "masonry": ((0.80, 0.80, 0.78), 0.0), "brick": ((0.72, 0.45, 0.36), 0.0),
    "plaster": ((0.90, 0.90, 0.88), 0.0), "glass": ((0.60, 0.80, 0.90), 0.6), "wood": ((0.62, 0.42, 0.24), 0.0),
    "steel": ((0.55, 0.57, 0.60), 0.0), "ceramic": ((0.95, 0.95, 0.95), 0.0), "": ((0.80, 0.80, 0.80), 0.0)}
GENERIC = {"", "site", "building", "default", "default site", "default building", "my site", "my building"}


def _guarded(fn):
    """A failing r3 extra records counts['error_<name>'] and lets the rest of enrich run (old behaviour kept)."""
    def run(f, *a):
        try:
            return fn(f, *a)
        except Exception as e:  # noqa: BLE001
            a[-1][f"error_{fn.__name__}"] = repr(e)[:200]
    run.__name__ = fn.__name__
    return run


def _clean_title(s):
    s = re.sub(r"^[A-Za-z0-9]+__", "", s or "")  # upload-slug prefix
    s = re.sub(r"[-_][0-9a-f]{6,}$", "", s)        # trailing content hash
    return re.sub(r"[_]+", " ", s).strip()


@_guarded
def _spatial(f, counts):
    n = 0
    proj = (f.by_type("IfcProject") or [None])[0]
    title = _clean_title(proj.Name) if proj is not None else ""
    if proj is not None and title and not proj.LongName:
        proj.LongName = title
        n += 1
    for b in f.by_type("IfcBuilding"):
        if (b.Name or "").strip().lower() in GENERIC and title:
            b.Name, n = title, n + 1
        if b.ElevationOfRefHeight is None:
            b.ElevationOfRefHeight, n = 0.0, n + 1
    for s in f.by_type("IfcSite"):
        if (s.Name or "").strip().lower() in GENERIC and title:
            s.Name, n = f"{title} site", n + 1
        if s.RefElevation is None:
            s.RefElevation, n = 0.0, n + 1
    for st in f.by_type("IfcBuildingStorey"):
        if st.Elevation is None and st.ObjectPlacement is not None:
            st.Elevation, n = float(_lp(st.ObjectPlacement)[2, 3]), n + 1
    counts["spatial"] = n


def _material(f, cache, name, cat):
    if name not in cache:
        cache[name] = next((m for m in f.by_type("IfcMaterial") if m.Name == name), None) or \
            ifcopenshell.api.material.add_material(f, name=name, category=cat)
    return cache[name]


@_guarded
def _wall_types(f, fps, counts):
    """Untyped walls get the existing IfcWallType of the same thickness (+-5 mm) or a new 'Wall <mm> mm' type."""
    types = []
    for t in f.by_type("IfcWallType"):
        m = ue.get_material(t)
        if m is not None and m.is_a("IfcMaterialLayerSet"):
            types.append((sum(l.LayerThickness for l in m.MaterialLayers), t))
    mats, n = {}, 0
    for wid, (w, fp, z) in fps.items():
        if ue.get_type(w) is not None:
            continue
        _, width = _axis_of(fp)
        if width <= 0:
            continue
        t = next((t for th, t in types if abs(th - width) <= 0.005), None)
        if t is None:
            mm = int(round(width * 1000 / 5) * 5)
            t = ifcopenshell.api.root.create_entity(f, ifc_class="IfcWallType", name=f"Wall {mm} mm",
                                                    predefined_type="STANDARD")
            ls = ifcopenshell.api.material.add_material_set(f, name=f"Wall {mm} mm", set_type="IfcMaterialLayerSet")
            lay = ifcopenshell.api.material.add_layer(f, layer_set=ls, material=_material(f, mats, "Masonry", "masonry"))
            lay.LayerThickness = float(width)
            ifcopenshell.api.material.assign_material(f, products=[t], type="IfcMaterialLayerSet", material=ls)
            types.append((width, t))
        ifcopenshell.api.type.assign_type(f, related_objects=[w], relating_type=t)
        n += 1
    counts["wall_types_assigned"] = n


def _types_all(f, counts):
    import ifcopenshell.util.type as utype
    have, n = {}, 0
    for cls in TYPED_CLASSES:
        for el in f.by_type(cls):
            if ue.get_type(el) is not None:
                continue
            tcls = next((t for t in utype.get_applicable_types(el.is_a(), f.schema) or []
                         if t not in ("IfcDistributionElementType", "IfcFlowTerminalType")), None)
            if tcls is None:
                continue
            pt = getattr(el, "PredefinedType", None)
            name = el.ObjectType or (re.sub(r"[-_ ]*\d+$", "", el.Name or "") or el.is_a()[3:])
            key = (tcls, name, pt)
            if key not in have:
                try:
                    have[key] = ifcopenshell.api.root.create_entity(f, ifc_class=tcls, name=name,
                                                                    predefined_type=pt or "NOTDEFINED")
                except Exception:  # noqa: BLE001
                    have[key] = ifcopenshell.api.root.create_entity(f, ifc_class=tcls, name=name)
            ifcopenshell.api.type.assign_type(f, related_objects=[el], relating_type=have[key])
            n += 1
    counts["types_assigned"] = n


def _materials_all(f, counts):
    mats, n = {}, 0
    for cls in TYPED_CLASSES:
        for el in f.by_type(cls):
            t = ue.get_type(el)
            if ue.get_material(el) is not None or (t is not None and ue.get_material(t) is not None):
                continue
            name, cat = next(((nm, c) for k, nm, c in DEFAULT_MAT if el.is_a(k)), ("Concrete", "concrete"))
            ifcopenshell.api.material.assign_material(f, products=[t or el], material=_material(f, mats, name, cat))
            n += 1
    counts["materials_assigned"] = n


def _dedupe_materials(f, counts):
    """Native exports share one IfcMaterial per real material; ours may have one per layer set."""
    by, n = {}, 0
    for m in list(f.by_type("IfcMaterial")):
        k = (m.Name, m.Category)
        if k not in by:
            by[k] = m
            continue
        for inv in f.get_inverse(m):
            ue.replace_attribute(inv, m, by[k])
        if not f.get_inverse(m):
            f.remove(m)
            n += 1
    for u in list(f.by_type("IfcMaterialLayerSetUsage")):  # orphan usages fail schema validation (AssociatedTo [1:?])
        if not f.get_inverse(u):
            f.remove(u)
            n += 1
    counts["materials_merged"] = n


def _mats_of(m):
    if m is None:
        return []
    if m.is_a("IfcMaterial"):
        return [m]
    if m.is_a("IfcMaterialLayerSetUsage"):
        return _mats_of(m.ForLayerSet)
    if m.is_a("IfcMaterialLayerSet"):
        return [l.Material for l in m.MaterialLayers if l.Material]
    if m.is_a("IfcMaterialList"):
        return list(m.Materials)
    if m.is_a("IfcMaterialConstituentSet"):
        return [c.Material for c in m.MaterialConstituents or [] if c.Material]
    return []


def _body_items(el):
    out = []
    for rep in (el.Representation.Representations if getattr(el, "Representation", None) else []):
        if rep.RepresentationIdentifier != "Body":
            continue
        for it in rep.Items:
            out += list(it.MappingSource.MappedRepresentation.Items) if it.is_a("IfcMappedItem") else [it]
    return out


def _new_style(f, name, cat):
    rgb, tr = PALETTE.get(cat or "", PALETTE[""])
    st = f.createIfcSurfaceStyle(name, "BOTH", [f.createIfcSurfaceStyleRendering(
        f.createIfcColourRgb(None, *rgb), float(tr), None, None, None, None, None, None, "NOTDEFINED")])
    return st


def _styles(f, counts):
    """Unstyled body items get a colour from their material; every material carries its style
    (IfcMaterialDefinitionRepresentation), as ArchiCAD/Revit exports do."""
    body = _ctx(f, "Body")
    styled = {si.Item.id(): si.Styles for si in f.by_type("IfcStyledItem") if si.Item is not None}
    by_name = {s.Name: s for s in f.by_type("IfcSurfaceStyle")}
    n_items = n_mats = 0
    mat_style = {}
    for rel in f.by_type("IfcRelAssociatesMaterial"):
        mats = _mats_of(rel.RelatingMaterial)
        if not mats:
            continue
        for o in rel.RelatedObjects:
            occ = [x for r in (getattr(o, "Types", None) or []) for x in r.RelatedObjects] if o.is_a("IfcTypeObject") \
                else [o]
            for e in occ:
                items = _body_items(e)
                st = next((styled[i.id()] for i in items if i.id() in styled), None)
                if st is None and items:
                    m = mats[0]
                    nm = m.Name or "Material"
                    if nm not in by_name:
                        by_name[nm] = _new_style(f, nm, (m.Category or nm).lower())
                    st = (by_name[nm],)
                    for i in items:
                        if i.id() not in styled:
                            f.createIfcStyledItem(i, st, None)
                            styled[i.id()] = st
                            n_items += 1
                if st is not None:
                    for m in mats:
                        mat_style.setdefault(m.id(), (m, st))
    have = {r.RepresentedMaterial.id() for r in f.by_type("IfcMaterialDefinitionRepresentation")}
    for mid, (m, st) in mat_style.items():
        if mid in have:
            continue
        sr = f.createIfcStyledRepresentation(body, "Style", "Material", [f.createIfcStyledItem(None, st, None)])
        f.createIfcMaterialDefinitionRepresentation(None, None, [sr], m)
        n_mats += 1
    counts["styled_items"] = n_items
    counts["material_styles"] = n_mats


@_guarded
def _add_footprint(f, el, fp, counts):
    if fp is None or fp.is_empty or _has_rep(el, "FootPrint"):
        return
    polys = list(fp.geoms) if hasattr(fp, "geoms") else [fp]
    curves = []
    for p in polys:
        if p.geom_type != "Polygon" or p.area < 1e-6:
            continue
        for ring in [p.exterior] + list(p.interiors):
            pts = _to_local(el, list(ring.coords))
            pts = [q for i, q in enumerate(pts) if i == 0 or q != pts[i - 1]]
            if len(pts) >= 3:
                curves.append(f.createIfcPolyline([f.createIfcCartesianPoint(q) for q in pts]))
    if not curves:
        return
    rep = f.createIfcShapeRepresentation(_ctx(f, "FootPrint"), "FootPrint", "GeometricCurveSet",
                                         [f.createIfcGeometricCurveSet(curves)])
    el.Representation.Representations = tuple(el.Representation.Representations) + (rep,)
    counts["footprint_reps"] = counts.get("footprint_reps", 0) + 1


def _axis_world(w):
    for rep in w.Representation.Representations:
        if rep.RepresentationIdentifier == "Axis":
            for it in rep.Items:
                pts = _ring(it)
                if pts and len(pts) >= 2:
                    M = _lp(w.ObjectPlacement)
                    return [tuple((M @ np.array([x, y, 0.0, 1.0]))[:2]) for x, y in (pts[0], pts[-1])]
    return None


@_guarded
def _connection_ends(f, fps, counts):
    """NOTDEFINED path connections -> ATSTART/ATEND (an axis end at the other wall) or ATPATH (mid-wall)."""
    from shapely.geometry import Point
    n = 0
    for rel in f.by_type("IfcRelConnectsPathElements"):
        if rel.RelatingConnectionType not in (None, "NOTDEFINED") and \
                rel.RelatedConnectionType not in (None, "NOTDEFINED"):
            continue
        a, b = rel.RelatingElement, rel.RelatedElement
        if a is None or b is None or a.id() not in fps or b.id() not in fps:
            continue
        ends = []
        for w, other in ((a, b), (b, a)):
            ax = _axis_world(w)
            fo = fps[other.id()][1]
            if ax is None:
                ends.append("ATPATH")
                continue
            tol = _axis_of(fps[other.id()][1])[1] / 2 + _axis_of(fps[w.id()][1])[1] / 2 + 0.1
            ds, de = fo.distance(Point(ax[0])), fo.distance(Point(ax[1]))
            ends.append("ATPATH" if min(ds, de) > tol else ("ATSTART" if ds <= de else "ATEND"))
        rel.RelatingConnectionType, rel.RelatedConnectionType = ends
        n += 1
    counts["connection_ends"] = n


def _opening_qtos(f, counts):
    n = 0
    for el in list(f.by_type("IfcDoor")) + list(f.by_type("IfcWindow")):
        if not el.Tag:
            iid = (ue.get_psets(el).get("Hologram_Provenance") or {}).get("item_id")
            if iid:
                el.Tag = str(iid)
        fp, z = footprint(el) if el.Representation else (None, None)
        if fp is None:
            continue
        mrr = fp.minimum_rotated_rectangle
        c = list(mrr.exterior.coords) if mrr.geom_type == "Polygon" else []
        wdt = max((LineString(c[i:i + 2]).length for i in range(min(2, len(c) - 1))), default=0.0)
        h = z[1] - z[0]
        if el.OverallWidth is None and wdt > 0:
            el.OverallWidth = float(round(wdt, 4))
        if el.OverallHeight is None and h > 0:
            el.OverallHeight = float(round(h, 4))
        name = "Qto_DoorBaseQuantities" if el.is_a("IfcDoor") else "Qto_WindowBaseQuantities"
        n += _qto_set(f, el, name, {"Width": wdt or None, "Height": h or None, "Area": (wdt * h) or None,
                                    "Perimeter": (2 * (wdt + h)) or None})
    counts["opening_qto_props"] = n


def _tags(f, counts):
    """Native exports give every element (and type) a Tag, the authoring tool's element id (ac20: all elements and
    types). Ours: the plan-map item id from Hologram_Provenance (the same link doors/windows already carry), else
    the element's GlobalId; types get their GlobalId."""
    n = 0
    for el in list(f.by_type("IfcElement")) + list(f.by_type("IfcTypeProduct")):
        if el.is_a("IfcFeatureElement") or getattr(el, "Tag", "x") not in (None, ""):
            continue
        iid = None if el.is_a("IfcTypeObject") else (ue.get_psets(el).get("Hologram_Provenance") or {}).get("item_id")
        el.Tag = str(iid or el.GlobalId)
        n += 1
    counts["tags"] = n


def _void_qtos_boxes(f, counts):
    """Native exports quantify every IfcOpeningElement (Qto_OpeningElementBaseQuantities) and give every product with
    a Body a Box representation; walls/slabs/doors/windows get theirs above, here the voids and the other products."""
    n = nb = 0
    for el in f.by_type("IfcElement"):
        if not el.Representation or not _has_rep(el, "Body"):
            continue
        fp, z = footprint(el)
        if fp is None or fp.is_empty:
            continue
        if not _has_rep(el, "Box"):
            _add_box(f, el, fp, z, counts)
            nb += 1
        if not el.is_a("IfcOpeningElement"):
            continue
        # DATA RULE: width = the drawn door/window symbol (the filling's OverallWidth), depth = the host wall's
        # measured thickness, height = the void body (printed or default head/sill: the filling's Hologram_Opening
        # says which); Hologram_Evidence records it
        fill = next((r.RelatedBuildingElement for r in (getattr(el, "HasFillings", None) or [])), None)
        host = next((r.RelatingBuildingElement for r in (getattr(el, "VoidsElements", None) or [])), None)
        wdt = float(fill.OverallWidth) if fill is not None and fill.OverallWidth else None
        dep = (ue.get_psets(host, qtos_only=True).get("Qto_WallBaseQuantities") or {}).get("Width") if host else None
        h = z[1] - z[0]
        if wdt is None or not dep:
            continue
        op = (ue.get_psets(fill).get("Hologram_Opening") or {}) if fill is not None else {}
        srcs = {k: str(v) for k, v in op.items() if k.endswith("Source") and v is not None}
        dflt = any("default" in v.lower() for v in srcs.values())
        n += _qto_set(f, el, "Qto_OpeningElementBaseQuantities",
                      {"Width": wdt, "Height": h or None, "Depth": float(dep), "Area": (wdt * h) or None,
                       "Volume": (wdt * h * float(dep)) or None})
        _pset_set(f, el, "Hologram_Evidence", {
            "Source": "default" if dflt else "derived",
            "Detail": "width = drawn door/window symbol (filling OverallWidth); depth = host wall measured thickness; "
                      "height from the filling: " + (", ".join(f"{k}={v}" for k, v in sorted(srcs.items()))
                                                    or "no source recorded")})
    counts["void_qto_props"], counts["other_box_reps"] = n, nb


def _room_tags(f, counts):
    """A native plan export carries 2D annotation (ac20: 113 IfcAnnotation in the storeys): one room tag per space
    with a printed number/name, only the printed text, as IfcTextLiteralWithExtent at the space's centre, in a Plan/Annotation context with a
    text style, contained in the space's storey. Not rendered in 3D (IfcAnnotation is not an IfcElement)."""
    if any(a.Name == "Room tag" for a in f.by_type("IfcAnnotation")):
        return
    import ifcopenshell.api.spatial
    plan = next((c for c in f.by_type("IfcGeometricRepresentationContext", include_subtypes=False)
                 if c.ContextType == "Plan"), None) or ifcopenshell.api.context.add_context(f, context_type="Plan")
    ctx = next((c for c in f.by_type("IfcGeometricRepresentationSubContext") if c.ContextIdentifier == "Annotation"),
               None) or ifcopenshell.api.context.add_context(f, context_type="Plan", context_identifier="Annotation",
                                                             target_view="PLAN_VIEW", parent=plan)
    tstyle = None
    n = 0
    for sp in f.by_type("IfcSpace"):
        # DATA RULE: only what the sheet prints (Hologram_RoomArea Number/NameSource 'printed...'); a generated
        # number or a room-type fallback name is never shown as a tag
        ra = ue.get_psets(sp).get("Hologram_RoomArea") or {}
        lines = [v for v, src in (((sp.Name or "").strip(), ra.get("NumberSource")),
                                  ((sp.LongName or "").strip(), ra.get("NameSource")))
                 if v and str(src or "").lower().startswith("printed")]
        lines = list(dict.fromkeys(lines))
        st = next((r.RelatingObject for r in (sp.Decomposes or []) if r.RelatingObject.is_a("IfcBuildingStorey")),
                  None)
        fp, z = footprint(sp)
        if not lines or st is None or fp is None or fp.is_empty or st.ObjectPlacement is None:
            continue
        if tstyle is None:
            font = f.createIfcTextStyleFontModel("Arial", ["Arial"], None, None, None, f.createIfcLengthMeasure(0.25))
            tstyle = f.createIfcTextStyle("Room tag", None, None, font, True)
        p = fp.representative_point() if not fp.centroid.within(fp) else fp.centroid
        Mi = np.linalg.inv(_lp(st.ObjectPlacement))
        loc = Mi @ np.array([p.x, p.y, z[0], 1.0])
        items = []
        for i, s in enumerate(lines):
            pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, -0.35 * i, 0.0)), None, None)
            ext = f.createIfcPlanarExtent(max(0.2, 0.18 * len(s)), 0.3)
            t = f.createIfcTextLiteralWithExtent(s, pos, "RIGHT", ext, "center")
            f.createIfcStyledItem(t, [tstyle], None)
            items.append(t)
        an = ifcopenshell.api.root.create_entity(f, ifc_class="IfcAnnotation", name="Room tag")
        an.ObjectType = "Room tag"
        import uuid
        an.GlobalId = ifcopenshell.guid.compress(uuid.uuid5(uuid.NAMESPACE_URL, f"room-tag:{sp.GlobalId}").hex)  # stable
        an.ObjectPlacement = f.createIfcLocalPlacement(st.ObjectPlacement, f.createIfcAxis2Placement3D(
            f.createIfcCartesianPoint(tuple(float(v) for v in loc[:3])), None, None))
        an.Representation = f.createIfcProductDefinitionShape(None, None, [
            f.createIfcShapeRepresentation(ctx, "Annotation", "Annotation2D", items)])
        ifcopenshell.api.spatial.assign_container(f, products=[an], relating_structure=st)
        _pset_set(f, an, "Hologram_Evidence", {"Source": "printed", "Detail": "text as printed on the sheet ("
                                               f"number: {ra.get('NumberSource')}; name: {ra.get('NameSource')}); "
                                               "placed at the space centre (derived), not at the printed label"})
        n += 1
    counts["room_tags"] = n


def _typed_occurrence_attrs(f, counts):
    """bSI rules BLT001/BLT002/OJT001: a typed occurrence leaves OperationType/PartitioningType (doors/windows) and
    PredefinedType empty when its type carries them. Move an occurrence value to the type if the type has none and
    all its occurrences agree; then clear it on the occurrences."""
    n = 0
    for t in f.by_type("IfcTypeObject"):
        occ = [o for r in (getattr(t, "Types", None) or []) for o in r.RelatedObjects]
        if not occ:
            continue
        for attr, tattr in (("PredefinedType", "PredefinedType"), ("OperationType", "OperationType"),
                            ("PartitioningType", "PartitioningType")):
            if not hasattr(t, tattr) or not all(hasattr(o, attr) for o in occ):
                continue
            vals = {getattr(o, attr) for o in occ} - {None}
            if not vals:
                continue
            tv = getattr(t, tattr)
            if tv in (None, "NOTDEFINED") and len(vals) == 1:
                v = vals.pop()
                if v == "USERDEFINED" and attr == "PredefinedType" and not getattr(t, "ElementType", None):
                    t.ElementType = next((o.ObjectType for o in occ if getattr(o, "ObjectType", None)), None)
                try:
                    setattr(t, tattr, v)
                    tv = v
                except Exception:  # noqa: BLE001  (enum differs between occurrence and type)
                    pass
            if tv in (None, "NOTDEFINED") and attr == "PredefinedType":
                continue  # only an informative type value makes the occurrence's redundant
            for o in occ:
                if getattr(o, attr) is not None:
                    setattr(o, attr, None)
                    n += 1
    counts["occurrence_attrs_cleared"] = n


def _opening_slab_boundaries(f, counts):
    """A native export bounds each space by its doors and windows (a door between two rooms bounds both) and by the
    slabs under and over it, not only by walls. A door/window bounds a space whose outline comes within 0.2 m of it;
    a slab whose top (or underside) meets the space's floor (or ceiling) within 0.6 m and covers half its area."""
    have = {(r.RelatingSpace.id(), r.RelatedBuildingElement.id()) for r in f.by_type("IfcRelSpaceBoundary")
            if r.RelatingSpace and r.RelatedBuildingElement}
    els = []
    for el in list(f.by_type("IfcDoor")) + list(f.by_type("IfcWindow")) + list(f.by_type("IfcSlab")):
        if el.is_a("IfcSlab") and ue.get_predefined_type(el) == "LANDING":
            continue
        src = str((ue.get_psets(el).get("Hologram_Evidence") or {}).get("Source") or "").lower()
        if src == "default" or (el.is_a("IfcSlab") and ue.get_predefined_type(el) == "ROOF"
                                and src not in ("measured", "printed")):
            continue   # DATA RULE: no boundary to an element the sheet does not show (a default slab, a roof not drawn)
        fp, z = footprint(el)
        if fp is not None and not fp.is_empty:
            els.append((el, fp, z))
    if not els:
        return
    tree = STRtree([e[1] for e in els])
    no = ns = 0
    for sp in f.by_type("IfcSpace"):
        fp, z = footprint(sp)
        if fp is None or fp.is_empty:
            continue
        ring = fp.buffer(0.2)
        for j in tree.query(ring):
            el, efp, ez = els[int(j)]
            if (sp.id(), el.id()) in have or not ring.intersects(efp):
                continue
            if el.is_a("IfcSlab"):
                if min(abs(ez[1] - z[0]), abs(ez[0] - z[1])) > 0.6 or fp.intersection(efp).area < 0.5 * fp.area:
                    continue
                ext = ue.get_predefined_type(el) == "ROOF"
                ns += 1
            else:
                pn = "Pset_DoorCommon" if el.is_a("IfcDoor") else "Pset_WindowCommon"
                ext = bool((ue.get_psets(el).get(pn) or {}).get("IsExternal"))
                no += 1
            f.createIfcRelSpaceBoundary(ifcopenshell.guid.new(), None, None, None, sp, el, None, "PHYSICAL",
                                        "EXTERNAL" if ext else "INTERNAL")
            have.add((sp.id(), el.id()))
    counts["space_boundaries_openings"], counts["space_boundaries_slabs"] = no, ns


def _space_names(f, counts):
    n = 0
    for sp in f.by_type("IfcSpace"):
        if (sp.LongName or "").strip():
            continue
        rt = (ue.get_psets(sp).get("Hologram_RoomArea") or {}).get("RoomType")
        sp.LongName = (str(rt).replace("_", " ").strip().capitalize() if rt else None) or "Room"
        n += 1
    counts["space_long_names"] = n


def _standard_case(f, counts):
    """IfcWall with Axis + vertical SweptSolid Body + IfcMaterialLayerSetUsage -> IfcWallStandardCase, so the file
    uses one wall class (pdf_to_ifc already writes StandardCase when it has a centreline)."""
    n = 0
    for w in [w for w in f.by_type("IfcWall", include_subtypes=False) if w.Representation]:
        reps = {r.RepresentationIdentifier: r for r in w.Representation.Representations}
        body = reps.get("Body")
        mat = ue.get_material(w, should_skip_usage=False)
        if "Axis" not in reps or body is None or body.RepresentationType != "SweptSolid" or mat is None \
                or not mat.is_a("IfcMaterialLayerSetUsage"):
            continue
        if not all(it.is_a("IfcExtrudedAreaSolid") and tuple(it.ExtrudedDirection.DirectionRatios)[:3] in
                   ((0.0, 0.0, 1.0), (0, 0, 1)) for it in body.Items):
            continue
        info = w.get_info(recursive=False)
        new = f.create_entity("IfcWallStandardCase", **{k: v for k, v in info.items() if k not in ("id", "type")})
        for inv in f.get_inverse(w):
            ue.replace_attribute(inv, w, new)
        f.remove(w)
        n += 1
    counts["standard_case"] = n


def _storey_for(f, pm: dict):
    sts = f.by_type("IfcBuildingStorey")
    if len(sts) == 1:
        return sts[0]
    try:
        from pipeline.pdf_to_ifc import guid_for
        g = guid_for(pm.get("doc_id") or "pdf", "storey", int(pm.get("page", 1)))
        return next((s for s in sts if s.GlobalId == g), None)
    except Exception:  # noqa: BLE001
        return None


def _columns(f, ifc_path: Path, fps: dict, counts):
    """IfcColumn (+ IfcColumnType, concrete, Body/Axis/Box/FootPrint, Qto/Pset) for each column the levels role found
    on the plan (planmap provenance.columns: hatched/filled sections on the column grid), storey high."""
    if f.by_type("IfcColumn"):
        return
    import ifcopenshell.api.spatial
    body = _ctx(f, "Body")
    n = 0
    types: dict = {}
    for pmf in sorted(ifc_path.parent.glob("planmap-*.json")):
        try:
            pm = json.loads(pmf.read_text())
        except Exception:  # noqa: BLE001
            continue
        cols = (pm.get("provenance") or {}).get("columns") or []
        mpp = (pm.get("scale") or {}).get("m_per_px")
        st = _storey_for(f, pm) if cols and mpp else None
        if st is None:
            continue
        Ms = _lp(st.ObjectPlacement) if st.ObjectPlacement else np.eye(4)
        ws = [(w, z) for w, fp, z in fps.values()
              if any(r.RelatingStructure == st for r in getattr(w, "ContainedInStructure", None) or [])]
        if ws:  # the walls of this storey give its floor and the slab underside the columns run to
            z0 = float(np.median([z[0] for _, z in ws]))
            z1 = float(max(z[1] for _, z in ws))
        else:
            h = ((pm.get("provenance") or {}).get("storey") or {}).get("height_m") or 3.0
            z0, z1 = float(Ms[2, 3]), float(Ms[2, 3]) + float(h)
        h = max(z1 - z0, 2.0)
        for c in cols:
            b = c.get("bbox_px")
            if not b or len(b) != 4:
                continue
            w_m, d_m = abs(b[2] - b[0]) * mpp, abs(b[3] - b[1]) * mpp
            if not (0.1 <= w_m <= 1.0 and 0.1 <= d_m <= 1.0):
                continue
            circle = c.get("shape") == "circle"
            key = ("C", round((w_m + d_m) / 2, 2)) if circle else ("R",) + tuple(sorted((round(w_m, 2), round(d_m, 2))))
            t = types.get(key)
            if t is None:
                nm = f"Column D{round(key[1] * 1000)}" if circle else f"Column {round(key[1] * 1000)}x{round(key[2] * 1000)}"
                t = ifcopenshell.api.root.create_entity(f, ifc_class="IfcColumnType", name=nm, predefined_type="COLUMN")
                tp = f.createIfcCircleProfileDef("AREA", nm[7:], None, (w_m + d_m) / 4) if circle else \
                    f.createIfcRectangleProfileDef("AREA", nm[7:], None, key[1], key[2])
                ps = ifcopenshell.api.material.add_material_set(f, name=nm, set_type="IfcMaterialProfileSet")
                ifcopenshell.api.material.add_profile(f, profile_set=ps, profile=tp,
                                                      material=_material(f, {}, "Concrete", "concrete"))
                ifcopenshell.api.material.assign_material(f, products=[t], type="IfcMaterialProfileSet", material=ps)
                types[key] = t
            cx, cy = (b[0] + b[2]) / 2 * mpp, -(b[1] + b[3]) / 2 * mpp
            lz = z0 - float(Ms[2, 3])
            col = ifcopenshell.api.root.create_entity(f, ifc_class="IfcColumn", name=t.Name,
                                                      predefined_type="NOTDEFINED")
            col.PredefinedType = None
            col.Tag = c.get("grid")
            col.ObjectPlacement = f.createIfcLocalPlacement(st.ObjectPlacement, f.createIfcAxis2Placement3D(
                f.createIfcCartesianPoint((round(cx, 4), round(cy, 4), round(lz, 4))), None, None))
            pos2 = f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((0.0, 0.0)), None)
            prof = f.createIfcCircleProfileDef("AREA", None, pos2, (w_m + d_m) / 4) if circle else \
                f.createIfcRectangleProfileDef("AREA", None, pos2, w_m, d_m)
            solid = f.createIfcExtrudedAreaSolid(prof, f.createIfcAxis2Placement3D(
                f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None),
                f.createIfcDirection((0.0, 0.0, 1.0)), h)
            axis = f.createIfcPolyline([f.createIfcCartesianPoint((0.0, 0.0, 0.0)),
                                        f.createIfcCartesianPoint((0.0, 0.0, h))])
            col.Representation = f.createIfcProductDefinitionShape(None, None, [
                f.createIfcShapeRepresentation(_ctx(f, "Axis"), "Axis", "Curve3D", [axis]),
                f.createIfcShapeRepresentation(body, "Body", "SweptSolid", [solid])])
            ifcopenshell.api.type.assign_type(f, related_objects=[col], relating_type=t)
            try:  # the type's profile set gives the occurrence an IfcMaterialProfileSetUsage: centred section
                u = ue.get_material(col, should_skip_usage=False)
                if u is not None and u.is_a("IfcMaterialProfileSetUsage"):
                    u.CardinalPoint = 5
            except Exception:  # noqa: BLE001
                pass
            ifcopenshell.api.spatial.assign_container(f, products=[col], relating_structure=st)
            area = math.pi * ((w_m + d_m) / 4) ** 2 if circle else w_m * d_m
            per = math.pi * (w_m + d_m) / 2 if circle else 2 * (w_m + d_m)
            _qto_set(f, col, "Qto_ColumnBaseQuantities", {"Length": h, "CrossSectionArea": area,
                                                          "OuterSurfaceArea": per * h, "GrossVolume": area * h,
                                                          "NetVolume": area * h})
            _pset_set(f, col, "Pset_ColumnCommon", {"LoadBearing": True, "IsExternal": False, "Reference": t.Name})
            _pset_set(f, col, "Hologram_Provenance", {"source": "pdf_levels.columns",
                                                      "evidence": str(c.get("evidence") or "")})
            _pset_set(f, col, "Hologram_Evidence", {
                "Source": "measured", "HeightSource": "derived",
                "Detail": f"drawn {'circle' if circle else 'square'} {w_m:.3f} x {d_m:.3f} m measured from bbox_px "
                          f"{[round(v, 1) for v in b]} at {mpp:.5f} m/px"
                          + (f", grid {c.get('grid')}" if c.get("grid") else "")
                          + f"; height {h:.3f} m = this storey's wall heights ({c.get('evidence') or 'pdf_levels'})"})
            fp, z = footprint(col)
            if fp is not None:
                _add_box(f, col, fp, z, counts)
                _add_footprint(f, col, fp, counts)
            n += 1
    counts["columns"] = n
    counts["column_types"] = len(types)


# ---- r4 "looks" post-pass: roof over the top storey, slab predefined types, native door/window bodies.
# Each part has its own env switch (default on) and is wrapped so a failure leaves the IFC as it was.
def _on(name):
    import os
    return os.environ.get(name, "1").strip().lower() not in ("0", "false", "no", "off", "")


ROOF_T = 0.3
ROOF_RGB = (0.36, 0.40, 0.46)   # dark slate, like a native roof finish


def _storey_of_el(el):
    for r in getattr(el, "ContainedInStructure", None) or []:
        if r.RelatingStructure.is_a("IfcBuildingStorey"):
            return r.RelatingStructure
    return None


def _contain(f, st, el):
    rel = next((r for r in getattr(st, "ContainsElements", None) or []), None)
    if rel is not None:
        rel.RelatedElements = tuple(rel.RelatedElements) + (el,)
    else:
        f.createIfcRelContainedInSpatialStructure(ifcopenshell.guid.new(), None, None, None, [el], st)


def _slab_types(f, counts):
    """Floor slabs end up FLOOR (BASESLAB for the lowest storey when it sits below ground), through their type
    (a typed occurrence keeps PredefinedType unset: bSI rule OJT001); untyped ones get it on the occurrence."""
    sts = sorted(f.by_type("IfcBuildingStorey"), key=lambda s: s.Elevation or 0.0)
    low = sts[0] if sts and (sts[0].Elevation or 0.0) < -0.5 else None
    base_t = None
    n = 0
    for s in f.by_type("IfcSlab"):
        t = ue.get_type(s)
        eff = ue.get_predefined_type(s)
        if eff in ("ROOF", "LANDING", "BASESLAB") or (eff and eff not in ("FLOOR", "NOTDEFINED", "USERDEFINED")):
            continue
        want = "BASESLAB" if low is not None and _storey_of_el(s) == low else "FLOOR"
        if t is None:
            if s.PredefinedType in (None, "NOTDEFINED"):
                s.PredefinedType = want
                n += 1
            continue
        if want == "FLOOR":
            if t.PredefinedType in (None, "NOTDEFINED"):
                t.PredefinedType = "FLOOR"
                n += 1
            if s.PredefinedType is not None and t.PredefinedType not in (None, "NOTDEFINED"):
                s.PredefinedType = None
            continue
        if base_t is None:
            base_t = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSlabType", name="Base slab",
                                                         predefined_type="BASESLAB")
            tm = ue.get_material(t)
            if tm is not None:
                ifcopenshell.api.material.assign_material(f, products=[base_t], type=tm.is_a(), material=tm)
        ifcopenshell.api.type.assign_type(f, related_objects=[s], relating_type=base_t)
        s.PredefinedType = None
        n += 1
    counts["slab_predefined"] = n


def _roof(f, fps, counts):
    """IfcRoof (FLAT_ROOF) aggregating one IfcSlab ROOF over the top storey: the storey's slab outline (or the
    filled outer envelope of its walls), ROOF_T thick, on top of the storey's walls. Like ac20 (ROOF slabs, no
    IfcCovering) the viewer treats it as roof: hidden by default, shown with "Show roof"."""
    if f.by_type("IfcRoof") or any(ue.get_predefined_type(s) == "ROOF" for s in f.by_type("IfcSlab")):
        return
    sts = [s for s in f.by_type("IfcBuildingStorey") if s.ObjectPlacement]
    if not sts:
        return
    by_st = {}
    for w, fp, z in fps.values():
        st = _storey_of_el(w)
        if st is not None:
            by_st.setdefault(st.id(), []).append((fp, z))
    sts = [s for s in sts if s.id() in by_st] or sts
    top = max(sts, key=lambda s: _lp(s.ObjectPlacement)[2, 3])
    Ms = _lp(top.ObjectPlacement)
    walls = by_st.get(top.id(), [])
    slab_fps = [footprint(s)[0] for s in f.by_type("IfcSlab") if s.Representation and _storey_of_el(s) == top]
    slab_fps = [p for p in slab_fps if p is not None and not p.is_empty and p.area > 1.0]
    if slab_fps:
        outline = unary_union(slab_fps)
        src = "slab"
    elif walls:
        u = unary_union([fp for fp, _ in walls]).buffer(0.3, join_style=2).buffer(-0.3, join_style=2)
        outline = unary_union([Polygon(p.exterior) for p in (u.geoms if hasattr(u, "geoms") else [u])
                               if p.geom_type == "Polygon"])
        src = "walls"
    else:
        return
    polys = [p for p in (outline.geoms if hasattr(outline, "geoms") else [outline])
             if p.geom_type == "Polygon" and p.area > 1.0]
    if not polys:
        return
    if walls:
        ztop = float(max(z[1] for _, z in walls))
    else:
        h = (ue.get_psets(top).get("Hologram_StoreySource") or {}).get("WallHeight") or 3.0
        ztop = float(Ms[2, 3]) + float(h)
    body = _ctx(f, "Body")
    import uuid as _uuid

    def gid(key):  # deterministic: same model in, same roof GlobalIds out (seeded by the top storey's GlobalId)
        return ifcopenshell.guid.compress(_uuid.uuid5(_uuid.NAMESPACE_URL, f"hologram-roof:{top.GlobalId}:{key}").hex)

    roof = ifcopenshell.api.root.create_entity(f, ifc_class="IfcRoof", name="Roof", predefined_type="FLAT_ROOF")
    roof.GlobalId = gid("roof")
    roof.ObjectPlacement = f.createIfcLocalPlacement(top.ObjectPlacement, f.createIfcAxis2Placement3D(
        f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None))
    _contain(f, top, roof)
    rt = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSlabType", name="Roof slab", predefined_type="ROOF")
    rt.GlobalId = gid("type")
    mat = next((m for m in f.by_type("IfcMaterial") if m.Name == "Roof membrane"), None) or \
        ifcopenshell.api.material.add_material(f, name="Roof membrane", category="roof")
    ls = ifcopenshell.api.material.add_material_set(f, name="Roof slab", set_type="IfcMaterialLayerSet")
    lay = ifcopenshell.api.material.add_layer(f, layer_set=ls, material=mat)
    lay.LayerThickness = ROOF_T
    ifcopenshell.api.material.assign_material(f, products=[rt], type="IfcMaterialLayerSet", material=ls)
    style = next((s for s in f.by_type("IfcSurfaceStyle") if s.Name == "pdf_roof"), None) or f.createIfcSurfaceStyle(
        "pdf_roof", "BOTH", [f.createIfcSurfaceStyleRendering(f.createIfcColourRgb(None, *ROOF_RGB), 0.0, None, None,
                                                             None, None, None, None, "NOTDEFINED")])
    n = 0
    for i, p in enumerate(sorted(polys, key=lambda q: -q.area)):
        p = p.simplify(0.01)
        s = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSlab", name=f"Roof slab {i + 1:03d}")
        s.GlobalId = gid(f"slab-{i + 1}")
        s.ObjectPlacement = f.createIfcLocalPlacement(roof.ObjectPlacement, f.createIfcAxis2Placement3D(
            f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None))
        ring = _to_local(s, list(p.exterior.coords))
        ring = [q for k, q in enumerate(ring) if k == 0 or q != ring[k - 1]]
        if ring[0] == ring[-1]:
            ring = ring[:-1]
        if len(ring) < 3:
            f.remove(s)
            continue
        prof = f.createIfcArbitraryClosedProfileDef("AREA", None, f.createIfcPolyline(
            [f.createIfcCartesianPoint(q) for q in ring + [ring[0]]]))
        zl = ztop - float(_lp(s.ObjectPlacement)[2, 3])
        solid = f.createIfcExtrudedAreaSolid(prof, f.createIfcAxis2Placement3D(
            f.createIfcCartesianPoint((0.0, 0.0, round(zl, 5))), None, None),
            f.createIfcDirection((0.0, 0.0, 1.0)), ROOF_T)
        f.createIfcStyledItem(solid, [style], None)
        s.Representation = f.createIfcProductDefinitionShape(None, None, [
            f.createIfcShapeRepresentation(body, "Body", "SweptSolid", [solid])])
        f.createIfcRelAggregates(gid(f"agg-{i + 1}"), None, None, None, roof, [s])
        ifcopenshell.api.type.assign_type(f, related_objects=[s], relating_type=rt)
        ifcopenshell.api.material.assign_material(f, products=[s], type="IfcMaterialLayerSetUsage", material=ls)
        _pset_set(f, s, "Pset_SlabCommon", {"IsExternal": True, "LoadBearing": True})
        sfp, sz = footprint(s)
        if sfp is not None:
            _qto_set(f, s, "Qto_SlabBaseQuantities", {"Depth": ROOF_T, "GrossArea": sfp.area, "NetArea": sfp.area,
                                                      "Perimeter": sfp.length, "GrossVolume": sfp.area * ROOF_T,
                                                      "NetVolume": sfp.area * ROOF_T})
            _add_box(f, s, sfp, sz, counts)
            _add_footprint(f, s, sfp, counts)
        _pset_set(f, roof, "Pset_RoofCommon", {"IsExternal": True})
        _pset_set(f, s, "Hologram_Evidence", {"Source": "derived", "Detail": f"top-storey {src} outline, "
                                              f"{ROOF_T} m default thickness on the wall tops"})
        n += 1
    if not n:
        f.remove(roof)
        return
    counts["roof"] = 1
    counts["roof_slabs"] = n
    counts["roof_source"] = src


def _host_thickness(el):
    for r in getattr(el, "FillsVoids", None) or []:
        for v in getattr(r.RelatingOpeningElement, "VoidsElements", None) or []:
            w = v.RelatingBuildingElement
            q = (ue.get_psets(w, qtos_only=True).get("Qto_WallBaseQuantities") or {}).get("Width")
            if q:
                return float(q)
            fp, _ = footprint(w)
            if fp is not None:
                return float(_axis_of(fp)[1])
    return None


def _type_props(t, cls):
    for p in (getattr(t, "HasPropertySets", None) or []) if t is not None else []:
        if p.is_a(cls):
            return p
    return None


def _items_bbox(items):
    import ifcopenshell.geom as geom
    st = geom.settings()
    los, his, boxes = [], [], []
    for it in items:
        try:
            sh = geom.create_shape(st, it)
            v = np.asarray(sh.verts, dtype=float).reshape(-1, 3)
        except Exception:  # noqa: BLE001
            v = np.zeros((0, 3))
        if len(v):
            boxes.append((v.min(0), v.max(0)))
            los.append(v.min(0))
            his.append(v.max(0))
        else:
            boxes.append(None)
    if not los:
        return None, boxes
    return (np.min(los, 0), np.max(his, 0)), boxes


WIN_PANELS = {"SINGLE_PANEL": 1, "DOUBLE_PANEL_VERTICAL": 2, "DOUBLE_PANEL_HORIZONTAL": 2,
              "TRIPLE_PANEL_VERTICAL": 3, "TRIPLE_PANEL_BOTTOM": 3, "TRIPLE_PANEL_TOP": 3, "TRIPLE_PANEL_LEFT": 3,
              "TRIPLE_PANEL_RIGHT": 3, "TRIPLE_PANEL_HORIZONTAL": 3}


def _style_named(f, names, rgb_tr):
    by = {s.Name: s for s in f.by_type("IfcSurfaceStyle")}
    for n in names:
        if n in by:
            return by[n]
    rgb, tr = rgb_tr
    return f.createIfcSurfaceStyle(names[0], "BOTH", [f.createIfcSurfaceStyleRendering(
        f.createIfcColourRgb(None, *rgb), float(tr), None, None, None, None, None, None, "NOTDEFINED")])


def _opening_bodies(f, counts, kinds=("door", "window")):
    """Body of each IfcDoor/IfcWindow -> ifcopenshell.api.geometry.add_door/window_representation (lining, casings,
    threshold, panel(s), handles / lining, frame, glass), as Bonsai writes them, sized from OverallWidth/Height, the
    type's lining/panel properties and the host wall thickness. It goes in as a MappedRepresentation (like ac20)
    whose transform puts it where the old body was; placement, GlobalId, opening/fill relations are unchanged."""
    import ifcopenshell.api.geometry as geo
    from ifcopenshell.api.geometry.add_door_representation import SUPPORTED_DOOR_TYPES
    from ifcopenshell.api.geometry.add_window_representation import WINDOW_TYPE
    from typing import get_args
    win_types = set(get_args(WINDOW_TYPE))
    styled = {si.Item.id(): si.Styles for si in f.by_type("IfcStyledItem") if si.Item is not None}
    s_door = s_frame = s_glass = s_metal = None
    maps = {}
    nd = nw = 0
    for el in (list(f.by_type("IfcDoor")) if "door" in kinds else []) + \
            (list(f.by_type("IfcWindow")) if "window" in kinds else []):
        reps = [r for r in (el.Representation.Representations if el.Representation else [])
                if r.RepresentationIdentifier == "Body"]
        if len(reps) != 1 or reps[0].RepresentationType == "MappedRepresentation" or not el.ObjectPlacement:
            continue
        old = reps[0]
        fp, z = footprint(el)
        if fp is None:
            continue
        M = _lp(el.ObjectPlacement)
        loc = Polygon(_to_local(el, list(fp.exterior.coords)))
        x0, y0, x1, y1 = loc.bounds
        z0 = z[0] - float(M[2, 3])
        W = float(el.OverallWidth or (x1 - x0))
        H = float(el.OverallHeight or (z[1] - z[0]))
        if W < 0.2 or H < 0.2:
            continue
        thick = _host_thickness(el) or max(y1 - y0, 0.05)
        t = ue.get_type(el)
        body_ctx = old.ContextOfItems
        try:
            if el.is_a("IfcDoor"):
                op = (getattr(t, "OperationType", None) or getattr(el, "OperationType", None) or "SINGLE_SWING_LEFT")
                op = op if op in SUPPORTED_DOOR_TYPES else "SINGLE_SWING_LEFT"
                lp = _type_props(t, "IfcDoorLiningProperties")
                ld = float(getattr(lp, "LiningDepth", None) or min(thick, 0.12))
                lt = float(getattr(lp, "LiningThickness", None) or 0.05)
                key = ("D", op, round(W, 3), round(H, 3), round(ld, 3), round(lt, 3))
                if key not in maps:
                    rep = geo.add_door_representation(
                        f, context=body_ctx, overall_height=H, overall_width=W, operation_type=op,
                        lining_properties={"LiningDepth": ld, "LiningThickness": lt, "LiningOffset": 0.0},
                        unit_scale=1.0)
                    if rep is None:
                        continue
                    maps[key] = rep
            else:
                op = getattr(t, "PartitioningType", None) or getattr(el, "PartitioningType", None) or "SINGLE_PANEL"
                op = op if op in win_types and op in WIN_PANELS else "SINGLE_PANEL"
                lp = _type_props(t, "IfcWindowLiningProperties")
                ld = float(getattr(lp, "LiningDepth", None) or min(thick, 0.1))
                lt = float(getattr(lp, "LiningThickness", None) or 0.05)
                key = ("W", op, round(W, 3), round(H, 3), round(ld, 3), round(lt, 3))
                if key not in maps:
                    maps[key] = geo.add_window_representation(
                        f, context=body_ctx, overall_height=H, overall_width=W, partition_type=op,
                        lining_properties={"LiningDepth": ld, "LiningThickness": lt, "LiningOffset": 0.0},
                        panel_properties=[{}] * WIN_PANELS[op], unit_scale=1.0)
        except Exception as e:  # noqa: BLE001
            counts.setdefault("opening_body_errors", repr(e)[:160])
            continue
        rep = maps[key]
        if not isinstance(rep, tuple):  # first use: bbox, styles, representation map
            bb, boxes = _items_bbox(rep.Items)
            if bb is None:
                maps[key] = None
                continue
            if s_door is None:
                pal = {"wood": ((0.62, 0.42, 0.24), 0.0), "frame": ((0.90, 0.90, 0.88), 0.0),
                       "glass": ((0.60, 0.80, 0.90), 0.6), "metal": ((0.55, 0.57, 0.60), 0.0)}
                s_door = _style_named(f, ["pdf_door", "Wood"], pal["wood"])
                s_frame = _style_named(f, ["pdf_frame"], pal["frame"])
                s_glass = _style_named(f, ["pdf_pane", "pdf_glass", "Glass"], pal["glass"])
                s_metal = _style_named(f, ["pdf_hardware"], pal["metal"])
            lo, hi = bb
            for it, b in zip(rep.Items, boxes):
                if b is None:
                    continue
                ext = b[1] - b[0]
                if key[0] == "D":
                    st = s_metal if max(ext) < 0.25 and ext[2] < 0.05 else s_door  # handles: small, low
                else:
                    inner = b[0][0] > lo[0] + 0.01 and b[0][2] > lo[2] + 0.01 and b[1][0] < hi[0] - 0.01
                    st = s_glass if inner and ext[1] < 0.02 else s_frame
                f.createIfcStyledItem(it, [st], None)
            rmap = f.createIfcRepresentationMap(f.createIfcAxis2Placement3D(
                f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None), rep)
            maps[key] = (rmap, lo, hi)
        if maps[key] is None:
            continue
        rmap, lo, hi = maps[key]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        org = (round(cx - (lo[0] + hi[0]) / 2, 5), round(cy - (lo[1] + hi[1]) / 2, 5), round(z0 - lo[2], 5))
        mi = f.createIfcMappedItem(rmap, f.createIfcCartesianTransformationOperator3D(
            None, None, f.createIfcCartesianPoint(org), None, None))
        new = f.createIfcShapeRepresentation(body_ctx, "Body", "MappedRepresentation", [mi])
        for la in list(getattr(old, "LayerAssignments", None) or []):
            la.AssignedItems = tuple(x for x in la.AssignedItems if x != old) + (new,)
        el.Representation.Representations = tuple(new if r == old else r for r in el.Representation.Representations)
        for it in old.Items:
            for si in list(getattr(it, "StyledByItem", None) or []):
                f.remove(si)
        old_items = list(old.Items)
        f.remove(old)
        for it in old_items:
            try:
                if not f.get_inverse(it):
                    ue.remove_deep2(f, it)
            except Exception:  # noqa: BLE001
                pass
        if el.is_a("IfcDoor"):
            nd += 1
        else:
            nw += 1
    _MC.clear()
    counts["door_bodies"] = nd
    counts["window_bodies"] = nw
    counts["opening_body_maps"] = sum(1 for v in maps.values() if v)


def _undoable(f, counts, name, fn, *a):
    """Run one looks part inside an IFC transaction; any exception undoes everything that part did."""
    try:
        f.begin_transaction()
    except Exception:  # noqa: BLE001
        pass
    try:
        fn(f, *a)
        f.end_transaction()
        return True
    except Exception as e:  # noqa: BLE001
        counts[f"error_{name}"] = repr(e)[:200]
        try:
            f.end_transaction()
            f.undo()
        except Exception:  # noqa: BLE001
            pass
        _MC.clear()
        return False


def _looks_roof(f, fps, counts):
    """PDF_IFC_ROOF (default OFF, =1 turns it on): slab predefined types + roof over the top storey. DATA RULE: a
    floor plan does not show the roof, so it is only built when asked for (a roof plan / printed roof level)."""
    import os
    if os.environ.get("PDF_IFC_ROOF", "0").strip().lower() in ("0", "false", "no", "off", ""):
        return
    t0 = time.time()
    _undoable(f, counts, "looks_slab_types", _slab_types, counts)
    _undoable(f, counts, "looks_roof", _roof, fps, counts)
    if counts.get("roof"):  # a second enrich is a no-op and reports nothing
        counts["looks_roof_s"] = round(time.time() - t0, 2)


def _looks_openings(f, counts):
    """PDF_IFC_OPENING_BODIES (default OFF: the viewer's convert_py makes one primitive per element, so glass
    collapses to the frame colour; '1', 'door' or 'window' turns it on): native door/window bodies."""
    import os
    ob = os.environ.get("PDF_IFC_OPENING_BODIES", "0").strip().lower()
    if ob in ("0", "false", "no", "off", ""):
        return
    kinds = ("door",) if ob == "door" else ("window",) if ob == "window" else ("door", "window")
    t0 = time.time()
    _undoable(f, counts, "looks_opening_bodies", _opening_bodies, counts, kinds)
    counts["looks_openings_s"] = round(time.time() - t0, 2)


MEP_CLASSES = ("IfcDuctSegment", "IfcDuctFitting", "IfcAirTerminal")
MEP_LAYERS = (("M-HVAC-DUCT", ("IfcDuctSegment", "IfcDuctFitting")), ("M-HVAC-DIFF", ("IfcAirTerminal",)))
PORT_TOL_M = 0.35   # two duct ends (or a duct end and a fitting centre) this close in plan are one joint


def _mep_size_key(el):
    m = ue.get_psets(el).get("Hologram_MEP") or {}
    s = ue.get_psets(el).get("Pset_DuctSegmentTypeCommon") or {}
    if el.is_a("IfcDuctSegment"):
        w, h = m.get("width_m"), m.get("height_m")
        shape = s.get("Shape") or "RECTANGULAR"
        if w is None:
            return None
        return (shape, round(float(w), 2), round(float(h or w), 2))
    sz = m.get("size_m")
    return None if sz is None else (str(m.get("kind") or m.get("shape") or ""), round(float(sz), 2))


def _mep_type_name(el, key):
    if el.is_a("IfcDuctSegment"):
        shape, w, h = key
        return f"Duct {'round' if shape == 'ROUND' else 'rectangular'} " + (
            f"ø{w * 1000:.0f}" if shape == "ROUND" else f"{w * 1000:.0f} x {h * 1000:.0f}")
    kind, s = key
    base = "Duct fitting" if el.is_a("IfcDuctFitting") else "Air terminal"
    return f"{base} {kind.lower() + ' ' if kind else ''}{s * 1000:.0f}".strip()


def _mep_ends(el):
    """World (x, y, z) points where an MEP element joins others: a segment's two ends, a fitting's centre."""
    M = _lp(el.ObjectPlacement)
    for rep in el.Representation.Representations:
        if rep.RepresentationIdentifier != "Body":
            continue
        for it in rep.Items:
            if not it.is_a("IfcExtrudedAreaSolid"):
                continue
            P = M @ _a2p(it.Position) if it.Position else M
            d = np.array(list(it.ExtrudedDirection.DirectionRatios) + [0.0])
            d = P @ d
            a = P[:3, 3]
            if el.is_a("IfcDuctSegment"):
                return [a.copy(), a + d[:3] / max(np.linalg.norm(d[:3]), 1e-9) * float(it.Depth)]
            return [a + d[:3] / max(np.linalg.norm(d[:3]), 1e-9) * float(it.Depth) / 2]
    return []


def mep_native(f, counts=None) -> dict:
    """What a native MEP export carries and our duct/terminal writer (pdf_mep) does not: one type per size
    (IfcDuctSegmentType RIGIDSEGMENT / IfcDuctFittingType / IfcAirTerminalType) with a material (galvanised steel),
    an IfcDistributionPort at each joint (IfcRelNests) and IfcRelConnectsPorts where two ends meet within PORT_TOL_M,
    presentation layers M-HVAC-DUCT / M-HVAC-DIFF and a Box. Works on an open file; no MEP elements -> no-op.
    Idempotent (skips elements that are typed / have ports)."""
    import uuid
    import ifcopenshell.api.system
    counts = {} if counts is None else counts
    els = [e for c in MEP_CLASSES for e in f.by_type(c) if e.Representation and e.ObjectPlacement]
    if not els:
        return counts

    def gid(*parts):
        return ifcopenshell.guid.compress(uuid.uuid5(uuid.NAMESPACE_URL, "mep:" + ":".join(parts)).hex)

    types, mats = {}, {}
    nt = 0
    for e in els:
        if ue.get_type(e) is not None:
            continue
        key = _mep_size_key(e)
        if key is None:
            continue
        tk = (e.is_a(), key)
        if tk not in types:
            name = _mep_type_name(e, key)
            t = next((x for x in f.by_type(e.is_a() + "Type") if x.Name == name), None)
            if t is None:
                t = ifcopenshell.api.root.create_entity(f, ifc_class=e.is_a() + "Type", name=name)
                t.GlobalId = gid("type", name)
                pt = getattr(e, "PredefinedType", None)
                if pt and pt not in ("USERDEFINED", "NOTDEFINED"):
                    try:
                        t.PredefinedType = pt
                    except Exception:  # noqa: BLE001
                        pass
                ifcopenshell.api.material.assign_material(f, products=[t], material=_material(
                    f, mats, "Galvanised steel", "steel"))
                hs = (ue.get_psets(e).get("Hologram_MEP") or {}).get("height_source")
                _pset_set(f, t, "Hologram_Evidence", {
                    "Source": "default",
                    "Detail": "size = the occurrences' measured duct width / symbol size (Hologram_MEP"
                              + (f", height_source={hs}" if hs else "") + "); material 'Galvanised steel' is a "
                              "default, not printed on the sheet"})
            types[tk] = t
        ifcopenshell.api.type.assign_type(f, related_objects=[e], relating_type=types[tk])
        if getattr(e, "PredefinedType", None) is not None and getattr(types[tk], "PredefinedType", None) == \
                e.PredefinedType:
            e.PredefinedType = None   # bSI OJT001: the type carries it
        nt += 1
    # ports
    ends = []   # (element, port, point)
    npo = 0
    for e in els:
        if any(r.is_a("IfcRelNests") for r in (getattr(e, "IsNestedBy", None) or [])):
            continue
        Mi = np.linalg.inv(_lp(e.ObjectPlacement))
        for i, p in enumerate(_mep_ends(e)):
            port = ifcopenshell.api.system.add_port(f, element=e)
            port.GlobalId = gid("port", e.GlobalId, str(i))
            port.Name = f"Port {i + 1}"
            port.PredefinedType, port.SystemType = "DUCT", "VENTILATION"
            port.FlowDirection = ("SINK" if i == 0 else "SOURCE") if e.is_a("IfcDuctSegment") else "SOURCEANDSINK"
            q = Mi @ np.array([p[0], p[1], p[2], 1.0])
            port.ObjectPlacement = f.createIfcLocalPlacement(e.ObjectPlacement, f.createIfcAxis2Placement3D(
                f.createIfcCartesianPoint(tuple(float(v) for v in q[:3])), None, None))
            _pset_set(f, port, "Hologram_Evidence", {
                "Source": "derived", "Detail": "at the end/centre of the element's body (measured duct line); "
                                               f"connected when another end is within {PORT_TOL_M} m in plan"})
            ends.append((e, port, p))
            npo += 1
    nc = 0
    if ends:
        tree = STRtree([Point(float(p[0]), float(p[1])) for _, _, p in ends])
        used = set()
        for i, (e, port, p) in enumerate(ends):
            if i in used:
                continue
            best = None
            for j in tree.query(Point(float(p[0]), float(p[1])).buffer(PORT_TOL_M)):
                j = int(j)
                if j == i or j in used or ends[j][0] == e:
                    continue
                dd = float(np.hypot(*(np.asarray(ends[j][2][:2]) - p[:2])))
                if dd <= PORT_TOL_M and (best is None or dd < best[0]):
                    best = (dd, j)
            if best is not None:
                ifcopenshell.api.system.connect_port(f, port, ends[best[1]][1])
                used |= {i, best[1]}
                nc += 1
    for e in els:  # vertical extrusions (fittings, terminals); a duct's footprint is its cross-section, no Box
        if not e.is_a("IfcDuctSegment") and not _has_rep(e, "Box"):
            fp, z = footprint(e)
            if fp is not None and not fp.is_empty:
                _add_box(f, e, fp, z, counts)
    for lname, classes in MEP_LAYERS:
        reps = [r for c in classes for e in f.by_type(c) if e.Representation
                for r in e.Representation.Representations if not r.LayerAssignments]
        if reps:
            la = next((x for x in f.by_type("IfcPresentationLayerAssignment") if x.Name == lname), None)
            if la is None:
                f.createIfcPresentationLayerAssignment(lname, None, reps, None)
            else:
                la.AssignedItems = tuple(la.AssignedItems) + tuple(reps)
    oh = (f.by_type("IfcOwnerHistory") or [None])[0]
    if oh is not None:
        for r in f.by_type("IfcRoot"):
            if r.OwnerHistory is None:
                r.OwnerHistory = oh
    counts.update({"mep_typed": nt, "mep_types": len(types), "mep_ports": npo, "mep_port_connections": nc})
    return counts


def _stairs_hook(f, ifc_path, counts):
    """stairs role: pdf_stairs.enrich_ifc_file(f, planmaps) rebuilds our IfcStair entities (skipped when absent)."""
    try:
        from pipeline import pdf_stairs
    except ImportError:
        return
    try:
        fn = getattr(pdf_stairs, "enrich_ifc_file", None)
        if fn is None:
            return
        pms = []
        for pmf in sorted(Path(ifc_path).parent.glob("planmap-*.json")):
            try:
                pms.append(json.loads(pmf.read_text()))
            except Exception:  # noqa: BLE001
                continue
        counts["stairs_rebuilt"] = fn(f, pms)
    except Exception as e:  # noqa: BLE001
        counts["error_stairs_hook"] = repr(e)[:200]


def _landing_qtos(f, counts):
    """Qto_SlabBaseQuantities (+ Box) on the stair LANDING slabs the stairs hook adds after the slab passes ran."""
    n = 0
    for s in f.by_type("IfcSlab"):
        if ue.get_predefined_type(s) != "LANDING" or not s.Representation:
            continue
        fp, z = footprint(s)
        if fp is None or fp.is_empty:
            continue
        d = float(z[1] - z[0])
        n += _qto_set(f, s, "Qto_SlabBaseQuantities", {"Depth": d, "GrossArea": fp.area, "NetArea": fp.area,
                                                       "Perimeter": fp.length, "GrossVolume": fp.area * d,
                                                       "NetVolume": fp.area * d})
        if not _has_rep(s, "Box"):
            _add_box(f, s, fp, z, counts)
            n += 1
    if n:
        counts["landing_qto_props"] = n


def _boundary_geometry(f, counts):
    """Second-level-style geometry on each IfcRelSpaceBoundary that has none (ac20: 1000/1000 carry an
    IfcConnectionSurfaceGeometry): a wall/door/window boundary is the stretch of the space outline that touches the
    element (its longest straight piece) as a vertical rectangle over the element's height range inside the space; a
    slab boundary is the space outline at the floor or ceiling. Both IfcCurveBoundedPlane (as ac20), in the space's
    local coordinates."""
    n = 0
    for r in f.by_type("IfcRelSpaceBoundary"):
        sp, el = r.RelatingSpace, r.RelatedBuildingElement
        if r.ConnectionGeometry is not None or sp is None or el is None or not sp.ObjectPlacement:
            continue
        sfp, sz = footprint(sp)
        efp, ez = footprint(el)
        if sfp is None or efp is None or sfp.is_empty or efp.is_empty or sfp.geom_type != "Polygon":
            continue
        Mi = np.linalg.inv(_lp(sp.ObjectPlacement))

        def loc(x, y, zz):
            q = Mi @ np.array([x, y, zz, 1.0])
            return float(q[0]), float(q[1]), float(q[2])
        if el.is_a("IfcSlab"):
            zz = sz[0] if abs(ez[1] - sz[0]) <= abs(ez[0] - sz[1]) else sz[1]
            ring = [loc(x, y, zz) for x, y in list(sfp.exterior.coords)]
            z0 = ring[0][2]
            plane = f.createIfcPlane(f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, z0)), None, None))
            bound = f.createIfcPolyline([f.createIfcCartesianPoint((p[0], p[1])) for p in ring])
            surf = f.createIfcCurveBoundedPlane(plane, bound, [])
        else:
            edge = sfp.exterior.intersection(efp.buffer(0.45 if el.is_a("IfcWall") else 0.25))
            parts = [g for g in getattr(edge, "geoms", [edge]) if g.geom_type == "LineString" and g.length > 0.05]
            if not parts:
                continue
            segs = [(g.coords[i], g.coords[i + 1]) for g in parts for i in range(len(g.coords) - 1)]
            (ax, ay), (bx, by) = max(segs, key=lambda q: math.dist(q[0], q[1]))
            z0, z1 = max(sz[0], ez[0]), min(sz[1], ez[1])
            if z1 - z0 < 0.05 or math.dist((ax, ay), (bx, by)) < 0.05:
                continue
            a, b = np.array(loc(ax, ay, z0)), np.array(loc(bx, by, z0))
            L = float(np.linalg.norm(b[:2] - a[:2]))
            ux, uy = (b[:2] - a[:2]) / L
            plane = f.createIfcPlane(f.createIfcAxis2Placement3D(f.createIfcCartesianPoint(tuple(float(v) for v in a)),
                                                                 f.createIfcDirection((float(uy), float(-ux), 0.0)),
                                                                 f.createIfcDirection((float(ux), float(uy), 0.0))))
            h = float(z1 - z0)   # plane coords: x along the shared edge, y up
            bound = f.createIfcPolyline([f.createIfcCartesianPoint(q) for q in
                                         ((0.0, 0.0), (L, 0.0), (L, h), (0.0, h), (0.0, 0.0))])
            surf = f.createIfcCurveBoundedPlane(plane, bound, [])
        r.ConnectionGeometry = f.createIfcConnectionSurfaceGeometry(surf, None)
        n += 1
    for r in f.by_type("IfcRelSpaceBoundary"):  # DATA RULE: say how each boundary was found (rels carry no psets)
        if not r.Description and r.RelatedBuildingElement is not None:
            r.Description = ("derived: the space outline meets the element's measured footprint; geometry = the "
                             "shared outline stretch over the overlapping height range (heights: see the elements)")
    counts["boundary_geometry"] = n



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

    _spatial(f, counts)
    _wall_types(f, fps, counts)

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
        own = next((r.RelatingMaterial for r in getattr(w, "HasAssociations", None) or []
                    if r.is_a("IfcRelAssociatesMaterial")), None)  # get_material falls back to the type's set
        if (own is None or own.is_a("IfcMaterial")) and tmat is not None and tmat.is_a("IfcMaterialLayerSet"):
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
        _add_footprint(f, w, fp, counts)

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
    _connection_ends(f, fps, counts)

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
        _add_footprint(f, s, fp, counts)

    _looks_roof(f, fps, counts)  # r4: slab predefined types + roof over the top storey

    for el in list(f.by_type("IfcDoor")) + list(f.by_type("IfcWindow")):
        if el.Representation:
            fp, z = footprint(el)
            if fp is not None:
                _add_box(f, el, fp, z, counts)
    _looks_openings(f, counts)  # r4: native door/window bodies (after their Box from the old body)

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
        h = z[1] - z[0]
        _qto_set(f, sp, "Qto_SpaceBaseQuantities", {"GrossVolume": fp.area * h, "NetVolume": fp.area * h,
                                                    "NetFloorArea": fp.area, "GrossFloorArea": fp.area,
                                                    "GrossPerimeter": fp.length, "Height": h})
        _add_footprint(f, sp, fp, counts)
        ring = fp.buffer(0.15)
        near = [int(j) for j in tree.query(ring) if ring.intersects(items[int(j)][1])]
        if not near and not any(k[0] == sp.id() for k in have_sb):  # room polygon drawn inside the wall faces
            ring = fp.buffer(0.45)
            near = [int(j) for j in tree.query(ring) if ring.intersects(items[int(j)][1])]
        for j in near:
            w = items[j][0]
            if (sp.id(), w.id()) in have_sb:
                continue
            ext = bool((ue.get_psets(w).get("Pset_WallCommon") or {}).get("IsExternal"))
            f.createIfcRelSpaceBoundary(ifcopenshell.guid.new(), None, None, None, sp, w, None, "PHYSICAL",
                                        "EXTERNAL" if ext else "INTERNAL")
            nsb += 1
    counts["space_boundaries"] = nsb
    try:
        _opening_slab_boundaries(f, counts)
    except Exception as e:  # noqa: BLE001
        counts["error__opening_slab_boundaries"] = repr(e)[:200]

    try:  # columns from the plan map (levels role); one failing extra never costs the rest
        _columns(f, ifc_path, fps, counts)
    except Exception as e:  # noqa: BLE001
        counts["error__columns"] = repr(e)[:200]
    _stairs_hook(f, ifc_path, counts)
    try:
        _landing_qtos(f, counts)
    except Exception as e:  # noqa: BLE001
        counts["error_landing_qtos"] = repr(e)[:200]
    _fire_ratings(f, ifc_path, counts)
    _opening_materials(f, counts)
    _space_types(f, counts)
    for step in (_opening_qtos, _tags, _void_qtos_boxes, _space_names, _room_tags, _types_all, _materials_all, _dedupe_materials, _styles,
                 _typed_occurrence_attrs):
        try:
            step(f, counts)
        except Exception as e:  # noqa: BLE001  - one failing extra never costs the rest
            counts[f"error_{step.__name__}"] = repr(e)[:200]
    _layers(f, counts)
    try:
        _standard_case(f, counts)
    except Exception as e:  # noqa: BLE001
        counts["error__standard_case"] = repr(e)[:200]
    try:
        _boundary_geometry(f, counts)
    except Exception as e:  # noqa: BLE001
        counts["error__boundary_geometry"] = repr(e)[:200]
    _owner(f, counts)  # last, so every new rooted entity gets it
    f.write(str(ifc_path))
    return counts
