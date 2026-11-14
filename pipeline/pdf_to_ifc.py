"""Vector-PDF plan map -> IFC4 file, so PDF floor plans go down the IFC path (pipeline.ifc_scene + IFC questions).

    build(planmap, out_path, *, storey_name, storey_elevation=0.0, wall_height=2.7) -> Path
    build_many([(planmap, storey_name, storey_elevation), ...], out_path) -> Path      (one storey per plan page)
    link_planmap(planmap_path, doc_id=None)  rewrites the plan map's item_ids to the IFC GlobalIds (old id kept in
                                             props.pdf_item_id) so IFC-mode answers can draw 2D boxes on the PDF page.

Input: a plan map from pipeline.pdf_planmap.process (items in page px, scale.m_per_px). Output (ifcopenshell.api, LGPL):
IfcProject (metres) > IfcSite > IfcBuilding > IfcBuildingStorey; one IfcWall per wall item (IfcExtrudedAreaSolid of
the exact wall polygon); per door/window an IfcOpeningElement voiding its host wall (IfcRelVoidsElement) and an
IfcDoor/IfcWindow filling it (IfcRelFillsElement; door 0-2.1 m, window sill 0.9 m head 2.1 m), so walls get real
openings with sills and lintels; door/window gaps the PDF leaves open are filled into the host wall first. One
IfcSpace per room (Name = number, LongName = label, Qto_SpaceBaseQuantities.NetFloorArea = printed area if present
else measured), one IfcSlab under the building footprint, Pset_*Common.IsExternal from the footprint outline, and a
Hologram_Provenance pset (source pdf_vector, item_id, m_per_pt, scale method) on every element.

Plan coordinates: x_m = x_px * m_per_px, y_m = -y_px * m_per_px (page top-left origin, y flipped to a right-handed plan),
so after ifc_scene's Z-up -> Y-up turn glTF X/Z follow the page's px x/y like the extruded scenes do.
GlobalIds are deterministic: uuid5(doc_id, page, item_id), so the same plan map always gives the same ids.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.feature
import ifcopenshell.api.material
import ifcopenshell.api.project
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.style
import ifcopenshell.api.type
import ifcopenshell.api.unit
import ifcopenshell.guid
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import unary_union

DOOR_HEAD_M = 2.1
WINDOW_SILL_M = 0.9
WINDOW_HEAD_M = 2.1
SLAB_THICK_M = 0.2
PANEL_M = {"door": 0.05, "window": 0.03}           # door leaf / glass pane thickness
HOST_SEARCH_M = 0.35                               # an opening's host wall is within this distance
FOOTPRINT_CLOSE_M = 0.6                            # closes door/window gaps when tracing the building outline
COLOURS = {  # (rgb, transparency) roughly what authoring tools export
    "wall": ((0.93, 0.91, 0.87), 0.0), "slab": ((0.62, 0.62, 0.62), 0.0), "door": ((0.62, 0.42, 0.24), 0.0),
    "window": ((0.55, 0.75, 0.95), 0.55), "space": ((0.85, 0.80, 0.65), 0.85),
    "glass": ((0.62, 0.80, 0.90), 0.6),
}
DOOR_OPERATION = {("left", 1): "SINGLE_SWING_LEFT", ("right", 1): "SINGLE_SWING_RIGHT", (None, 1): "SINGLE_SWING_LEFT"}
NS = uuid.UUID("6f1c5f0e-3d0a-4c8e-9a51-7d1b1b0c2a10")


def guid_for(doc_id: str, item_id: str, page: int = 1) -> str:
    """Stable IFC GlobalId (22 chars) for a plan-map item."""
    return ifcopenshell.guid.compress(uuid.uuid5(NS, f"{doc_id}:p{page}:{item_id}").hex)


# ---------------------------------------------------------------- geometry helpers (plan metres, y up)

def _poly_m(pts_px, mpp: float):
    if not pts_px or len(pts_px) < 3:
        return None
    p = Polygon([(x * mpp, -y * mpp) for x, y in pts_px]).buffer(0)
    if p.is_empty or p.area <= 1e-6:
        return None
    if isinstance(p, MultiPolygon):
        p = max(p.geoms, key=lambda g: g.area)
    return p


def _wall_poly(it: dict, mpp: float, m_per_pt: float | None):
    p = _poly_m(it.get("polygon_px"), mpp)
    if p is not None:
        return p
    cl = it.get("centerline")  # [[x,y],...] px (pdf_vector may add it with thickness_pt)
    t_pt = it.get("thickness_pt") or (it.get("props") or {}).get("thickness_pt")
    if cl and len(cl) >= 2 and t_pt and m_per_pt:
        ln = LineString([(x * mpp, -y * mpp) for x, y in cl])
        return ln.buffer(t_pt * m_per_pt / 2, cap_style="flat", join_style="mitre")
    return None


def _axis_m(pr: dict, mpp: float):
    cl = pr.get("centerline_px")
    if not cl or len(cl) < 2:
        return None
    ln = LineString([(x * mpp, -y * mpp) for x, y in cl])
    return ln if ln.length > 0.05 else None


def _storey_title(name: str) -> str:
    s = " ".join(name.split()).title()
    return s.replace("1St", "1st").replace("2Nd", "2nd").replace("3Rd", "3rd").replace("Th ", "th ")


def _parts(g):
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon) and p.area > 1e-6]


def _rect_frame(poly: Polygon, width_hint: float | None):
    """Opening rectangle -> (centre, unit axis along the wall, width, depth)."""
    r = poly.minimum_rotated_rectangle
    c = list(r.exterior.coords)[:4]
    e1 = (c[1][0] - c[0][0], c[1][1] - c[0][1])
    e2 = (c[2][0] - c[1][0], c[2][1] - c[1][1])
    l1, l2 = (e1[0] ** 2 + e1[1] ** 2) ** 0.5, (e2[0] ** 2 + e2[1] ** 2) ** 0.5
    if width_hint and l1 > 1e-6 and l2 > 1e-6:
        along_first = abs(l1 - width_hint) <= abs(l2 - width_hint)
    else:
        along_first = l1 >= l2
    (ax, w), d = ((e1, l1), l2) if along_first else ((e2, l2), l1)
    u = (ax[0] / max(w, 1e-9), ax[1] / max(w, 1e-9))
    ctr = r.centroid
    return (ctr.x, ctr.y), u, w, d


def _rect(c, u, w, d) -> Polygon:
    n = (-u[1], u[0])
    hw, hd = w / 2, d / 2
    return Polygon([(c[0] + s * hw * u[0] + t * hd * n[0], c[1] + s * hw * u[1] + t * hd * n[1])
                    for s, t in ((-1, -1), (1, -1), (1, 1), (-1, 1))])


# ---------------------------------------------------------------- IFC helpers

class _W:
    def __init__(self, f, body, doc_id, page, prov):
        self.f, self.body, self.doc_id, self.page, self.prov = f, body, doc_id, page, prov
        self.styles = {}
        self.axis_ctx = None

    def gid(self, item_id):
        return guid_for(self.doc_id, item_id, self.page)

    def entity(self, cls, item_id, name=None, predefined=None):
        e = ifcopenshell.api.root.create_entity(self.f, ifc_class=cls, name=name, predefined_type=predefined)
        e.GlobalId = self.gid(item_id)
        return e

    def placement(self, rel=None, z=0.0):
        f = self.f
        ax = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, float(z))), None, None)
        return f.createIfcLocalPlacement(rel, ax)

    def profile(self, poly: Polygon):
        f = self.f

        def curve(ring):
            pts = [(round(x, 5), round(y, 5)) for x, y in list(ring.coords)[:-1]]
            pl = f.createIfcCartesianPointList2D(pts)
            return f.createIfcIndexedPolyCurve(pl, [f.createIfcLineIndex(list(range(1, len(pts) + 1)) + [1])], False)
        poly = poly.simplify(0.003)
        if poly.interiors:
            return f.createIfcArbitraryProfileDefWithVoids("AREA", None, curve(poly.exterior), [curve(r) for r in poly.interiors])
        return f.createIfcArbitraryClosedProfileDef("AREA", None, curve(poly.exterior))

    def solid(self, poly: Polygon, z0: float, h: float):
        f = self.f
        pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, float(z0))), None, None)
        return f.createIfcExtrudedAreaSolid(self.profile(poly), pos, f.createIfcDirection((0.0, 0.0, 1.0)), float(h))

    def shape(self, product, polys, z0, h, style=None, axis=None):
        f = self.f
        items = [self.solid(p, z0, h) for p in polys if p.area > 1e-6 and len(p.exterior.coords) >= 4]
        if not items:
            return False
        rep = f.createIfcShapeRepresentation(self.body, "Body", "SweptSolid", items)
        reps = [rep]
        if axis is not None:
            if self.axis_ctx is None:
                self.axis_ctx = ifcopenshell.api.context.add_context(f, context_type="Plan", context_identifier="Axis",
                                                                     target_view="GRAPH_VIEW", parent=self.body.ParentContext)
            pl = f.createIfcPolyline([f.createIfcCartesianPoint((round(x, 5), round(y, 5))) for x, y in axis.coords])
            reps.insert(0, f.createIfcShapeRepresentation(self.axis_ctx, "Axis", "Curve2D", [pl]))
        product.Representation = f.createIfcProductDefinitionShape(None, None, reps)
        if style:
            ifcopenshell.api.style.assign_representation_styles(self.f, shape_representation=rep, styles=[self.style(style)])
        return True

    def style(self, key):
        if key not in self.styles:
            rgb, tr = COLOURS[key]
            s = ifcopenshell.api.style.add_style(self.f, name=f"pdf_{key}")
            ifcopenshell.api.style.add_surface_style(self.f, style=s, ifc_class="IfcSurfaceStyleShading", attributes={
                "SurfaceColour": {"Name": None, "Red": rgb[0], "Green": rgb[1], "Blue": rgb[2]}, "Transparency": tr})
            self.styles[key] = s
        return self.styles[key]

    def pset(self, product, name, props: dict):
        props = {k: v for k, v in props.items() if v is not None}
        if props:
            ps = ifcopenshell.api.pset.add_pset(self.f, product=product, name=name)
            ifcopenshell.api.pset.edit_pset(self.f, pset=ps, properties=props)

    def qto(self, product, name, props: dict):
        props = {k: round(float(v), 4) for k, v in props.items() if v is not None}
        if props:
            q = ifcopenshell.api.pset.add_qto(self.f, product=product, name=name)
            ifcopenshell.api.pset.edit_qto(self.f, qto=q, properties=props)

    def provenance(self, product, it: dict | None):
        self.pset(product, "Hologram_Provenance", {**self.prov, "item_id": (it or {}).get("item_id"),
                                                   "page": self.page, "conf": (it or {}).get("conf")})


# ---------------------------------------------------------------- main builder

def _new_file(doc_id: str, project_name: str | None):
    f = ifcopenshell.api.project.create_file(version="IFC4")
    proj = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name=project_name or doc_id)
    proj.GlobalId = guid_for(doc_id, "project", 0)
    ifcopenshell.api.unit.assign_unit(f, length={"is_metric": True, "raw": "METERS"})
    model = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier="Body",
                                                target_view="MODEL_VIEW", parent=model)
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site")
    site.GlobalId = guid_for(doc_id, "site", 0)
    bldg = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name="Building")
    bldg.GlobalId = guid_for(doc_id, "building", 0)
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=proj)
    ifcopenshell.api.aggregate.assign_object(f, products=[bldg], relating_object=site)
    org = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None)
    site.ObjectPlacement = f.createIfcLocalPlacement(None, org)
    bldg.ObjectPlacement = f.createIfcLocalPlacement(site.ObjectPlacement, f.createIfcAxis2Placement3D(
        f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None))
    return f, proj, bldg, body


def _add_storey(f, bldg, body, planmap: dict, storey_name: str, storey_elevation: float, wall_height: float,
                doc_id: str) -> dict:
    sc = planmap.get("scale") or {}
    mpp = sc.get("m_per_px")
    if not mpp:
        raise ValueError("plan map has no scale.m_per_px")
    m_per_pt = sc.get("m_per_pt")
    page = int(planmap.get("page", 1))
    prov = {"source": "pdf_vector", "doc_id": doc_id, "m_per_px": float(mpp),
            "m_per_pt": float(m_per_pt) if m_per_pt else None, "scale_method": sc.get("method"),
            "scale_ratio": sc.get("ratio"), "scale_confidence": sc.get("confidence"),
            "coords": "plan x = page px x * m_per_px, plan y = -page px y * m_per_px"}
    w = _W(f, body, doc_id, page, {k: v for k, v in prov.items() if v is not None})
    sem = planmap.get("semantics") or {}
    sst = sem.get("storey") or {}
    if storey_name in (None, "Floor 1") and sst.get("name"):
        storey_name = _storey_title(sst["name"])
    storey_name = storey_name or "Floor 1"
    if sem.get("wall_height_m"):
        wall_height = float(sem["wall_height_m"])
    door_head = float(sem.get("door_height_m") or DOOR_HEAD_M)

    st = w.entity("IfcBuildingStorey", "storey", name=storey_name)
    # Elevation carries the printed level (+13.000 in the height system); the geometry stays at z=0 so the
    # viewer, AR and the 2D links see the floor at ground level like a single-storey export
    st.Elevation = float(sst.get("elevation_m", storey_elevation))
    st.ObjectPlacement = f.createIfcLocalPlacement(bldg.ObjectPlacement, f.createIfcAxis2Placement3D(
        f.createIfcCartesianPoint((0.0, 0.0, float(storey_elevation))), None, None))
    ifcopenshell.api.aggregate.assign_object(f, products=[st], relating_object=bldg)
    w.provenance(st, None)
    w.pset(st, "Hologram_StoreySource", {"HeightSystem": sst.get("height_system"),
                                         "ElevationSource": sst.get("elevation_source"),
                                         "StoreyNumber": sst.get("number"), "WallHeight": wall_height,
                                         "DoorHeight": door_head})
    sp = st.ObjectPlacement

    items = planmap.get("items") or []
    def _glass(it):  # interior glazing the openings reader tags as a partition: a glass wall, not a window
        return it.get("kind") in ("door", "window") and (it.get("props") or {}).get("kind") == "glass_partition"
    walls = [(it, _wall_poly(it, mpp, m_per_pt)) for it in items if it.get("kind") == "wall"]
    for it in items:
        if _glass(it):
            gp = _poly_m(it.get("polygon_px"), mpp)
            if gp is None and it.get("bbox_px"):
                x0, y0, x1, y1 = it["bbox_px"]
                gp = _poly_m([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], mpp)
            if gp is not None:
                pr = dict(it.get("props") or {}, glass=True)
                pr.setdefault("thickness_m", round(max(0.02, min(_rect_frame(gp, None)[3], 0.12)), 3))
                walls.append(({**it, "kind": "wall", "props": pr}, gp))
    walls = [(it, p) for it, p in walls if p is not None]
    rooms = [it for it in items if it.get("kind") == "room"]
    opens = []
    for it in items:
        if it.get("kind") not in ("door", "window") or _glass(it):
            continue
        p = _poly_m(it.get("polygon_px"), mpp)
        if p is None and it.get("bbox_px"):
            x0, y0, x1, y1 = it["bbox_px"]
            p = _poly_m([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], mpp)
        if p is not None:
            opens.append((it, p))

    # host wall per opening: the wall with the most overlap with the opening grown by HOST_SEARCH_M
    wall_polys = [p for _, p in walls]
    host = {}
    extra = {i: [] for i in range(len(walls))}
    orphans = []
    for k, (it, p) in enumerate(opens):
        grown = p.buffer(HOST_SEARCH_M)
        best, best_a = None, 0.0
        for i, wp in enumerate(wall_polys):
            if wp.distance(p) > HOST_SEARCH_M:
                continue
            a = wp.intersection(grown).area
            if a > best_a:
                best, best_a = i, a
        if best is None:
            orphans.append(k)
        else:
            host[k] = best
            extra[best].append(p)

    # footprint (slab + IsExternal): walls + openings + rooms, gaps closed, holes filled
    room_polys = {it["item_id"]: _poly_m(it.get("polygon_px"), mpp) for it in rooms}
    every = wall_polys + [p for _, p in opens] + [p for p in room_polys.values() if p is not None]
    footprint = []
    if every:
        u = unary_union(every).buffer(FOOTPRINT_CLOSE_M, join_style="mitre").buffer(-FOOTPRINT_CLOSE_M, join_style="mitre")
        parts = sorted(_parts(u), key=lambda g: -g.area)
        if parts:
            footprint = [Polygon(g.exterior) for g in parts if g.area >= 0.15 * parts[0].area]
    outline = unary_union([g.exterior for g in footprint]) if footprint else None

    def external(poly) -> bool:
        return bool(outline is not None and outline.intersection(poly.buffer(0.1)).length > 0.4)

    out_walls = {}
    products = []
    wtypes, dtypes = {}, {}

    glass_leg = next((e for e in sem.get("legend") or [] if e.get("kind") == "glass_partition"), None)

    def wall_type(pr, ext):
        if pr.get("glass") and not pr.get("wall_type") and glass_leg:
            pr = {**pr, "wall_type": glass_leg["code"], "type_description": glass_leg["description"]}
        t_mm = int(round(float(pr.get("thickness_m") or 0) * 1000 / 10) * 10)
        if pr.get("wall_type"):
            key = (pr["wall_type"], t_mm)
            name = f"{pr['wall_type']} {pr.get('type_description') or ''} {t_mm} mm".replace("  ", " ")
        else:
            key = ("ext" if ext else "int", t_mm)
            name = f"{'Exterior' if ext else 'Interior'} wall {t_mm} mm"
        if key not in wtypes:
            wt = w.entity("IfcWallType", f"type:wall:{key[0]}:{t_mm}", name=name,
                          predefined="PARTITIONING" if pr.get("glass") else "STANDARD")
            mat = ifcopenshell.api.material.add_material(f, name="Glass" if pr.get("glass") else
                                                         (pr.get("material") or ("Exterior wall" if ext else "Wall")))
            ls = ifcopenshell.api.material.add_material_set(f, name=name, set_type="IfcMaterialLayerSet")
            lay = ifcopenshell.api.material.add_layer(f, layer_set=ls, material=mat)
            lay.LayerThickness = max(t_mm, 10) / 1000
            ifcopenshell.api.material.assign_material(f, products=[wt], type="IfcMaterialLayerSet", material=ls)
            wtypes[key] = (wt, ls)
        return wtypes[key]
    # walls (gap openings merged into their host, so the lintel and sill are wall material)
    for i, (it, p) in enumerate(walls):
        geom = unary_union([p] + [e.buffer(0.02, join_style="mitre") for e in extra[i]]) if extra[i] else p
        pr = it.get("props") or {}
        h = float(pr.get("height_m") or wall_height)
        ext = external(p)
        axis = _axis_m(pr, mpp)
        wall = w.entity("IfcWallStandardCase" if axis else "IfcWall", it["item_id"], name=f"Wall-{i + 1:03d}",
                        predefined="STANDARD")
        wall.ObjectPlacement = w.placement(sp)
        w.shape(wall, _parts(geom), 0.0, h, "glass" if pr.get("glass") else "wall", axis=axis)
        wt, ls = wall_type(pr, ext)
        ifcopenshell.api.type.assign_type(f, related_objects=[wall], relating_type=wt)
        if axis:
            ifcopenshell.api.material.assign_material(f, products=[wall], type="IfcMaterialLayerSetUsage", material=ls)
        else:
            ifcopenshell.api.material.assign_material(f, products=[wall], material=ls.MaterialLayers[0].Material)
        w.pset(wall, "Pset_WallCommon", {"IsExternal": ext, "LoadBearing": None, "Reference": wt.Name,
                                         "FireRating": pr.get("fire_rating"),
                                         "AcousticRating": pr.get("acoustic_rating")})
        L = float(pr.get("length_m") or 0) or (axis.length if axis else None)
        t = float(pr.get("thickness_m") or 0) or None
        w.qto(wall, "Qto_WallBaseQuantities", {"Length": L, "Width": t, "Height": h, "NetFootprintArea": p.area,
                                               "GrossFootprintArea": p.area,
                                               "GrossSideArea": L * h if L else None,
                                               "GrossVolume": p.area * h})
        w.provenance(wall, it)
        out_walls[i] = wall
        products.append(wall)
    # openings without a wall nearby get a filler wall of their own (a door drawn in a gap the reader left empty)
    for k in orphans:
        it, p = opens[k]
        wall = w.entity("IfcWall", it["item_id"] + "#wall", name=f"Wall-{len(walls) + k + 1:03d}", predefined="STANDARD")
        wall.ObjectPlacement = w.placement(sp)
        w.shape(wall, [p], 0.0, wall_height, "wall")
        w.pset(wall, "Pset_WallCommon", {"IsExternal": external(p)})
        w.provenance(wall, {"item_id": it["item_id"] + "#wall", "conf": it.get("conf")})
        out_walls[("o", k)] = wall
        products.append(wall)
        host[k] = ("o", k)

    # openings + fillings
    n_void = 0
    for k, (it, p) in enumerate(opens):
        kind = it["kind"]
        pr = it.get("props") or {}
        wall = out_walls[host[k]]
        hw = wall_polys[host[k]] if isinstance(host[k], int) else p
        c, u, wid, dep = _rect_frame(p, pr.get("width_m"))
        thick = max(dep, float((walls[host[k]][0].get("props") or {}).get("thickness_m") or 0) if isinstance(host[k], int) else dep)
        if kind == "door":
            z0, z1 = 0.0, min(door_head, wall_height - 0.05)
        else:
            z0, z1 = WINDOW_SILL_M, min(WINDOW_HEAD_M, wall_height - 0.05)
        cut = _rect(c, u, wid, thick + 0.1)
        op = w.entity("IfcOpeningElement", it["item_id"] + "#opening", name=f"opening {it['item_id']}", predefined="OPENING")
        op.ObjectPlacement = w.placement(wall.ObjectPlacement)
        w.shape(op, [cut], z0, z1 - z0)
        ifcopenshell.api.feature.add_feature(f, feature=op, element=wall)
        n_void += 1
        cls = "IfcDoor" if kind == "door" else "IfcWindow"
        n_kind = sum(1 for q, _ in opens[:k + 1] if q["kind"] == kind)
        el = w.entity(cls, it["item_id"], name=f"{'Door' if kind == 'door' else 'Window'}-{n_kind:03d}",
                      predefined=kind.upper())
        if kind == "door":
            op_type = "DOUBLE_DOOR_SINGLE_SWING" if pr.get("double") or (pr.get("n_leaves") or 1) >= 2 else \
                DOOR_OPERATION.get((pr.get("swing_side"), 1), "SINGLE_SWING_LEFT") if pr.get("leaf") or pr.get("swing") \
                else "NOTDEFINED"
            el.OperationType = op_type
        else:
            op_type = "SINGLE_PANEL"
            el.PartitioningType = op_type
        tkey = (kind, op_type, int(round((pr.get("width_m") or wid) * 10)))
        if tkey not in dtypes:
            tcls = "IfcDoorType" if kind == "door" else "IfcWindowType"
            tname = (f"Door {op_type.replace('_', ' ').lower()} {tkey[2] * 100} mm" if kind == "door"
                     else f"Window single panel {tkey[2] * 100} mm")
            dt = w.entity(tcls, f"type:{kind}:{op_type}:{tkey[2]}", name=tname, predefined=kind.upper())
            if kind == "door":
                dt.OperationType = op_type
            else:
                dt.PartitioningType = op_type
            dtypes[tkey] = dt
        ifcopenshell.api.type.assign_type(f, related_objects=[el], relating_type=dtypes[tkey])
        el.ObjectPlacement = w.placement(sp)
        el.OverallWidth = round(float(pr.get("width_m") or wid), 4)
        el.OverallHeight = round(z1 - z0, 4)
        w.shape(el, [_rect(c, u, wid, PANEL_M[kind])], z0, z1 - z0, kind)
        ifcopenshell.api.feature.add_filling(f, opening=op, element=el)
        ext = external(p) or bool(hw is not None and external(hw) and kind == "window")
        w.pset(el, "Pset_DoorCommon" if kind == "door" else "Pset_WindowCommon",
               {"IsExternal": ext, "FireRating": pr.get("fire_rating"), "AcousticRating": pr.get("acoustic_rating"),
                "Reference": dtypes[tkey].Name})
        w.qto(el, "Qto_DoorBaseQuantities" if kind == "door" else "Qto_WindowBaseQuantities",
              {"Width": el.OverallWidth, "Height": el.OverallHeight, "Area": el.OverallWidth * el.OverallHeight,
               "Perimeter": 2 * (el.OverallWidth + el.OverallHeight)})
        w.provenance(el, it)
        products.append(el)

    # spaces
    n_space = 0
    for it in rooms:
        pr = it.get("props") or {}
        q = it.get("q") or {}
        poly = room_polys.get(it["item_id"])
        num = pr.get("number")
        label = it.get("label") or None
        sp_el = w.entity("IfcSpace", it["item_id"], name=str(num or label or it["item_id"]), predefined="SPACE")
        sp_el.LongName = label
        sp_el.ObjectPlacement = w.placement(sp)
        measured = q.get("area_m2") or pr.get("area_m2_geom") or (round(poly.area, 3) if poly is not None else None)
        printed = q.get("area_m2_printed") or pr.get("area_m2_label")
        sh = float(pr.get("ceiling_height_m") or wall_height)
        if poly is not None:
            w.shape(sp_el, [poly], 0.0, sh, "space")
        w.qto(sp_el, "Qto_SpaceBaseQuantities", {"NetFloorArea": printed or measured, "GrossFloorArea": measured,
                                                 "Height": sh if poly is not None else None,
                                                 "NetVolume": (printed or measured) * sh if (printed or measured) and poly is not None else None,
                                                 "GrossPerimeter": poly.exterior.length if poly is not None else None})
        w.pset(sp_el, "Hologram_RoomArea", {"MeasuredArea": measured, "PrintedArea": printed,
                                            "AreaSource": "printed" if printed else "measured",
                                            "RoomType": pr.get("room_type"),
                                            "CeilingHeight": pr.get("ceiling_height_m"),
                                            "CeilingHeightSource": "h= mark in the room" if pr.get("ceiling_height_m") else None})
        w.provenance(sp_el, it)
        n_space += 1
        products.append(sp_el)

    # floor slab under the building footprint
    if footprint:
        slab = w.entity("IfcSlab", "floor", name=f"Floor slab {storey_name}", predefined="FLOOR")
        slab.ObjectPlacement = w.placement(sp)
        w.shape(slab, footprint, -SLAB_THICK_M, SLAB_THICK_M, "slab")
        w.qto(slab, "Qto_SlabBaseQuantities", {"Depth": SLAB_THICK_M, "GrossArea": sum(g.area for g in footprint)})
        w.provenance(slab, {"item_id": "floor"})
        products.append(slab)

    spatial = [p for p in products if not p.is_a("IfcSpace")]
    if spatial:
        ifcopenshell.api.spatial.assign_container(f, products=spatial, relating_structure=st)
    spaces = [p for p in products if p.is_a("IfcSpace")]
    if spaces:
        ifcopenshell.api.aggregate.assign_object(f, products=spaces, relating_object=st)
    return {"walls": len(out_walls), "filler_walls": len(orphans), "openings": n_void, "spaces": n_space,
            "doors": sum(1 for it, _ in opens if it["kind"] == "door"),
            "windows": sum(1 for it, _ in opens if it["kind"] == "window"), "slab": bool(footprint)}


def build_many(pages: list[tuple[dict, str, float]], out_path, *, wall_height: float = 2.7, doc_id: str | None = None,
               project_name: str | None = None) -> Path:
    """[(planmap, storey_name, storey_elevation_m), ...] -> one IFC with one storey per plan page."""
    if not pages:
        raise ValueError("no plan maps")
    t0 = time.time()
    doc_id = doc_id or pages[0][0].get("doc_id") or "pdf"
    f, proj, bldg, body = _new_file(doc_id, project_name)
    stats = [_add_storey(f, bldg, body, pm, name, elev, wall_height, doc_id) for pm, name, elev in pages]
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    f.write(str(out))
    build.last_stats = {"storeys": stats, "s": round(time.time() - t0, 2)}
    try:  # ifc-native role's enrichment (psets, qtos, material layer sets, types, space boundaries) when present
        from pipeline import ifc_enrich
        ifc_enrich.enrich(out)
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        build.last_stats["enrich_error"] = f"{type(e).__name__}: {e}"[:200]
    return out


def build(planmap: dict, out_path, *, storey_name: str = "Floor 1", storey_elevation: float = 0.0,
          wall_height: float = 2.7, doc_id: str | None = None, project_name: str | None = None) -> Path:
    """One plan map -> IFC4 file with one storey. Raises ValueError when the plan map has no scale."""
    return build_many([(planmap, storey_name, storey_elevation)], out_path, wall_height=wall_height, doc_id=doc_id,
                      project_name=project_name)


build.last_stats = {}


def link_planmap(planmap_path, doc_id: str | None = None) -> int:
    """Rewrite plan-map item_ids to the IFC GlobalIds build() gave them (walls, doors, windows, rooms), keeping the
    PDF id in props.pdf_item_id, so engine IFC mode (engine.solvers.data.load_doc) finds each element's page and
    bbox_px on the real PDF page. Idempotent. Returns the number of items relinked."""
    p = Path(planmap_path)
    pm = json.loads(p.read_text())
    doc_id = doc_id or pm.get("doc_id") or "pdf"
    page = int(pm.get("page", 1))
    n = 0
    for it in pm.get("items") or []:
        if it.get("kind") not in ("wall", "door", "window", "room"):
            continue
        pr = it.setdefault("props", {})
        src = pr.get("pdf_item_id") or it["item_id"]
        pr["pdf_item_id"] = src
        it["item_id"] = guid_for(doc_id, src, page)
        if it["kind"] == "room" and "ifc_class" not in pr:
            pr["ifc_class"] = "IfcSpace"
        n += 1
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(pm))
    tmp.replace(p)
    return n


def validate(ifc_path) -> dict:
    """Counts + structural checks: every opening voids a wall, every door/window fills an opening."""
    f = ifcopenshell.open(str(ifc_path))
    c = {k: len(f.by_type(k)) for k in ("IfcBuildingStorey", "IfcWall", "IfcOpeningElement", "IfcDoor", "IfcWindow",
                                         "IfcSpace", "IfcSlab", "IfcRelVoidsElement", "IfcRelFillsElement")}
    bad_void = [o.GlobalId for o in f.by_type("IfcOpeningElement")
                if not o.VoidsElements or not o.VoidsElements[0].RelatingBuildingElement.is_a("IfcWall")]
    bad_fill = [e.GlobalId for e in f.by_type("IfcDoor") + f.by_type("IfcWindow") if not e.FillsVoids]
    gids = [e.GlobalId for e in f.by_type("IfcRoot")]
    c.update(schema=f.schema, openings_not_voiding_wall=len(bad_void), fillings_without_opening=len(bad_fill),
             duplicate_guids=len(gids) - len(set(gids)))
    return c


if __name__ == "__main__":
    import sys
    pm = json.loads(Path(sys.argv[1]).read_text())
    out = build(pm, sys.argv[2], storey_name=sys.argv[3] if len(sys.argv) > 3 else "Floor 1")
    print(json.dumps({"ifc": str(out), **build.last_stats, "validate": validate(out)}))
