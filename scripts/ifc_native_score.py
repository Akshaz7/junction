"""How native does an IFC look? Checklist score 0-100 of traits a native authoring-tool export has.

usage: python scripts/ifc_native_score.py ours.ifc [more.ifc ...] [--ref ac20_arc.ifc] [--no-validate] [--json out.json]
Each item is pass/fail (weight 1; items marked optional have weight 0 and are only reported). Score = 100 * passed / weighted.
Fractions use a 0.95 threshold (0.9 for styles/layers/boundaries) so one odd element does not fail a class.
ifcopenshell.validate on a 10 MB file takes minutes: results are cached by (path, size, mtime) in ~/.cache.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import ifcopenshell
import ifcopenshell.util.element as ue
import ifcopenshell.util.placement as up
from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.ifc_enrich import footprint, _MC  # noqa: E402

REF = "data/junction-dataset-preview/data/ifc_bench/ac20_arc.ifc"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ifc_native_score.json"
TYPED = ("IfcWall", "IfcDoor", "IfcWindow", "IfcSlab", "IfcSpace", "IfcColumn", "IfcBeam", "IfcStair", "IfcRailing",
         "IfcCovering", "IfcFurnishingElement", "IfcRoof", "IfcCurtainWall", "IfcPlate", "IfcMember",
         "IfcFlowTerminal", "IfcStairFlight", "IfcSanitaryTerminal", "IfcTransportElement",
         "IfcBuildingElementProxy")
# classes whose Pset_<X>Common / Qto_<X>BaseQuantities a native export writes
PQ = (("IfcWall", "Wall"), ("IfcDoor", "Door"), ("IfcWindow", "Window"), ("IfcSlab", "Slab"), ("IfcSpace", "Space"))
SPACE_Q = ("NetFloorArea", "GrossPerimeter", "Height")


def _frac(n, d):
    return 1.0 if d == 0 else n / d


def _validate(path: Path, f) -> int | None:
    st = path.stat()
    key = f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    try:
        cache = json.loads(CACHE.read_text())
    except Exception:  # noqa: BLE001
        cache = {}
    if key in cache:
        return cache[key]
    try:
        import ifcopenshell.validate
        lg = ifcopenshell.validate.json_logger()
        ifcopenshell.validate.validate(f, lg, express_rules=False)
        n = len(lg.statements)
    except Exception:  # noqa: BLE001
        return None
    cache[key] = n
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache))
    except Exception:  # noqa: BLE001
        pass
    return n


def _qset_names(el):
    return {k for k in ue.get_psets(el, qtos_only=True)}


def _origin(el):
    try:
        M = up.get_local_placement(el.ObjectPlacement)
        return float(M[0, 3]), float(M[1, 3]), float(M[2, 3])
    except Exception:  # noqa: BLE001
        return None


def score(path, do_validate=True) -> dict:
    path = Path(path)
    t0 = time.time()
    f = ifcopenshell.open(str(path))
    _MC.clear()
    items = []

    def item(key, ok, detail="", optional=False):
        items.append({"key": key, "pass": bool(ok), "detail": detail, "optional": optional})

    # --- spatial hierarchy ------------------------------------------------------------------------------------
    proj = f.by_type("IfcProject")
    sites, blds, stys = f.by_type("IfcSite"), f.by_type("IfcBuilding"), f.by_type("IfcBuildingStorey")

    def parent(e):
        d = getattr(e, "Decomposes", None) or []
        return d[0].RelatingObject if d else None
    chain = bool(proj and sites and blds and stys) and all(parent(s) in proj for s in sites) and \
        all(parent(b) in sites for b in blds) and all(parent(s) in blds for s in stys)
    item("spatial_hierarchy", chain, f"project {len(proj)} site {len(sites)} building {len(blds)} storey {len(stys)}")
    generic = {"", "site", "building", "default", "default site", "default building", "unnamed", "none"}
    named = [e for e in sites + blds + stys if (e.Name or "").strip().lower() not in generic]
    item("spatial_names", len(named) == len(sites + blds + stys) and all((p.Name or "").strip() for p in proj),
         f"{len(named)}/{len(sites + blds + stys)} site/building/storey with a real name: "
         + ", ".join(repr(e.Name) for e in sites + blds + stys)[:160])
    elev = [s for s in stys if s.Elevation is not None]
    item("storey_elevations", stys and len(elev) == len(stys) and all(s.RefElevation is not None for s in sites),
         f"{len(elev)}/{len(stys)} storeys with Elevation; site RefElevation "
         + ",".join(str(s.RefElevation) for s in sites))
    contained = sum(len(r.RelatedElements) for r in f.by_type("IfcRelContainedInSpatialStructure"))
    prods = [p for p in f.by_type("IfcElement") if not p.is_a("IfcFeatureElement")]
    inside = sum(1 for p in prods if getattr(p, "ContainedInStructure", None) or
                 (getattr(p, "Decomposes", None)))
    item("elements_contained", _frac(inside, len(prods)) >= 0.95, f"{inside}/{len(prods)} elements in a storey "
         f"({contained} containment refs)")

    # --- units, owner history, contexts, rep types ---------------------------------------------------------------
    ut = {u.UnitType for ua in f.by_type("IfcUnitAssignment") for u in ua.Units if hasattr(u, "UnitType")}
    need = {"LENGTHUNIT", "AREAUNIT", "VOLUMEUNIT", "PLANEANGLEUNIT"}
    item("units", need <= ut, "missing " + ",".join(sorted(need - ut)) if need - ut else "length/area/volume/angle")
    ohs = f.by_type("IfcOwnerHistory")
    roots = f.by_type("IfcRoot")
    noh = sum(1 for r in roots if r.OwnerHistory is None)
    item("owner_history", len(ohs) == 1 and noh == 0 and all(o.OwningApplication for o in ohs),
         f"{len(ohs)} owner histories, {noh}/{len(roots)} roots without")
    ctx_ids = {c.ContextIdentifier for c in f.by_type("IfcGeometricRepresentationSubContext")}
    ctx_types = {c.ContextType for c in f.by_type("IfcGeometricRepresentationContext")}
    need = {"Body", "Axis", "FootPrint", "Box"}
    item("contexts", need <= ctx_ids and {"Model", "Plan"} <= ctx_types,
         f"subcontexts {sorted(i for i in ctx_ids if i)}; context types {sorted(t for t in ctx_types if t)}")
    rt = collections.Counter(r.RepresentationType for r in f.by_type("IfcShapeRepresentation"))
    need = {"SweptSolid", "Curve2D", "BoundingBox"}
    item("rep_types", need <= set(rt), ", ".join(f"{k} {v}" for k, v in rt.most_common(8)))
    item("rep_clipping", "Clipping" in rt, f"Clipping {rt.get('Clipping', 0)}", optional=True)
    fpr = collections.Counter(r.RepresentationIdentifier for r in f.by_type("IfcShapeRepresentation"))
    item("footprint_reps", fpr.get("FootPrint", 0) > 0, f"FootPrint reps {fpr.get('FootPrint', 0)}")

    # --- walls ---------------------------------------------------------------------------------------------------
    walls = f.by_type("IfcWall")
    nw = len(walls)
    sc = sum(1 for w in walls if w.is_a("IfcWallStandardCase"))
    lsu = sum(1 for w in walls if (m := ue.get_material(w, should_skip_usage=False)) is not None
              and m.is_a("IfcMaterialLayerSetUsage"))
    ax = sum(1 for w in walls if w.Representation and any(r.RepresentationIdentifier == "Axis"
                                                          for r in w.Representation.Representations))
    item("walls_standard_case", nw and _frac(sc, nw) >= 0.95, f"{sc}/{nw} IfcWallStandardCase")
    item("walls_layer_usage", nw and _frac(lsu, nw) >= 0.95, f"{lsu}/{nw} IfcMaterialLayerSetUsage")
    item("walls_axis", nw and _frac(ax, nw) >= 0.95, f"{ax}/{nw} Axis/Curve2D")
    conns = f.by_type("IfcRelConnectsPathElements")
    typed_c = sum(1 for c in conns if c.RelatingConnectionType in ("ATSTART", "ATEND", "ATPATH")
                  and c.RelatedConnectionType in ("ATSTART", "ATEND", "ATPATH"))
    connected = {c.RelatingElement.id() for c in conns} | {c.RelatedElement.id() for c in conns}
    item("wall_connections", nw and _frac(len(connected), nw) >= 0.8 and _frac(typed_c, len(conns)) >= 0.9,
         f"{len(conns)} connections, {len(connected)}/{nw} walls connected, {typed_c} with ATSTART/ATEND/ATPATH")
    ext = sum(1 for w in walls if (ue.get_psets(w).get("Pset_WallCommon") or {}).get("IsExternal") is True)
    item("external_walls_flagged", ext > 0, f"{ext} walls IsExternal=True (Pset_WallCommon)", optional=True)

    # --- openings ------------------------------------------------------------------------------------------------
    fills = f.by_type("IfcDoor") + f.by_type("IfcWindow")
    hosted = 0
    for d in fills:
        for r in getattr(d, "FillsVoids", None) or []:
            op = r.RelatingOpeningElement
            if getattr(op, "VoidsElements", None):
                hosted += 1
                break
    item("openings_hosted", _frac(hosted, len(fills)) >= 0.95,
         f"{hosted}/{len(fills)} doors+windows fill an opening that voids a host "
         f"({len(f.by_type('IfcRelVoidsElement'))} voids, {len(f.by_type('IfcRelFillsElement'))} fills)")

    # --- types, materials ----------------------------------------------------------------------------------------
    typed_els = [e for c in TYPED for e in f.by_type(c, include_subtypes=True)]
    typed_els = list({e.id(): e for e in typed_els}.values())
    nt = [e for e in typed_els if ue.get_type(e) is None]
    by = collections.Counter(e.is_a() for e in nt)
    item("types_for_all", _frac(len(typed_els) - len(nt), len(typed_els)) >= 0.95,
         f"{len(typed_els) - len(nt)}/{len(typed_els)} typed" + (f"; untyped {dict(by)}" if by else ""))
    phys = [e for e in typed_els if not e.is_a("IfcSpace")]
    nm = [e for e in phys if ue.get_material(e) is None and (ue.get_type(e) is None or
                                                             ue.get_material(ue.get_type(e)) is None)]
    by = collections.Counter(e.is_a() for e in nm)
    item("materials_for_all", _frac(len(phys) - len(nm), len(phys)) >= 0.95,
         f"{len(phys) - len(nm)}/{len(phys)} with material" + (f"; without {dict(by)}" if by else ""))

    # --- psets / qtos --------------------------------------------------------------------------------------------
    pd, qd = [], []
    pok = qok = True
    for cls, stem in PQ:
        els = f.by_type(cls)
        if not els:
            continue
        p = sum(1 for e in els if f"Pset_{stem}Common" in ue.get_psets(e, psets_only=True))
        q = sum(1 for e in els if any(n == f"Qto_{stem}BaseQuantities" or n == "BaseQuantities"
                                      for n in _qset_names(e)))
        pok &= _frac(p, len(els)) >= 0.95
        qok &= _frac(q, len(els)) >= 0.95
        pd.append(f"{stem} {p}/{len(els)}")
        qd.append(f"{stem} {q}/{len(els)}")
    item("pset_common", pok and pd, "; ".join(pd))
    item("qto_base", qok and qd, "; ".join(qd))
    sps = f.by_type("IfcSpace")
    sq = 0
    for s in sps:
        qs = ue.get_psets(s, qtos_only=True)
        q = qs.get("Qto_SpaceBaseQuantities") or qs.get("BaseQuantities") or {}
        sq += all(q.get(k) for k in SPACE_Q)
    item("space_qto_keys", sps and _frac(sq, len(sps)) >= 0.95, f"{sq}/{len(sps)} spaces with {'/'.join(SPACE_Q)}")

    # --- styles / layers ----------------------------------------------------------------------------------------
    body_items, styled = 0, 0
    styled_ids = {s.Item.id() for s in f.by_type("IfcStyledItem") if s.Item}
    mat_styled = {m.RepresentedMaterial.id() for m in f.by_type("IfcMaterialDefinitionRepresentation")}
    for p in f.by_type("IfcProduct"):
        if p.is_a("IfcFeatureElement") or not p.Representation:
            continue
        for r in p.Representation.Representations:
            if r.RepresentationIdentifier != "Body":
                continue
            its = list(r.Items)
            if r.RepresentationType == "MappedRepresentation":
                its = [i for m in its for i in m.MappingSource.MappedRepresentation.Items]
            body_items += len(its)
            mat = ue.get_material(p)
            styled += sum(1 for i in its if i.id() in styled_ids or (mat is not None and mat.id() in mat_styled))
    surf = f.by_type("IfcSurfaceStyle")
    item("surface_styles", surf and _frac(styled, body_items) >= 0.9,
         f"{len(surf)} surface styles, {styled}/{body_items} body items styled, "
         f"{len(f.by_type('IfcColourRgb'))} colours; " + ", ".join(sorted({s.Name or '' for s in surf}))[:120])
    item("material_styles", len(mat_styled) > 0, f"{len(mat_styled)} materials carry a style "
         "(IfcMaterialDefinitionRepresentation)", optional=True)
    lay_ids = {i.id() for la in f.by_type("IfcPresentationLayerAssignment") for i in la.AssignedItems}
    reps = [r for p in f.by_type("IfcProduct") if p.Representation and not p.is_a("IfcFeatureElement")
            for r in p.Representation.Representations if r.RepresentationIdentifier == "Body"]
    lr = sum(1 for r in reps if r.id() in lay_ids or any(i.id() in lay_ids for i in r.Items))
    item("presentation_layers", f.by_type("IfcPresentationLayerAssignment") and _frac(lr, len(reps)) >= 0.9,
         f"{len(f.by_type('IfcPresentationLayerAssignment'))} layers, {lr}/{len(reps)} body reps on a layer")

    # --- spaces --------------------------------------------------------------------------------------------------
    nn = sum(1 for s in sps if (s.Name or "").strip() and (s.LongName or "").strip())
    item("spaces_named", sps and _frac(nn, len(sps)) >= 0.95,
         f"{nn}/{len(sps)} with Name+LongName; e.g. " + "; ".join(f"{s.Name!r}/{s.LongName!r}" for s in sps[:3])[:160])
    sb = {b.RelatingSpace.id() for b in f.by_type("IfcRelSpaceBoundary") if b.RelatingSpace}
    item("space_boundaries", sps and _frac(len(sb), len(sps)) >= 0.9,
         f"{len(sb)}/{len(sps)} spaces bounded, {len(f.by_type('IfcRelSpaceBoundary'))} boundaries")
    item("classification", bool(f.by_type("IfcRelAssociatesClassification")),
         f"{len(f.by_type('IfcRelAssociatesClassification'))} classification associations", optional=True)

    # --- buildingSMART normative rules most likely to flag a converted file (paraphrased from
    # github.com/buildingSMART/ifc-gherkin-rules, MIT; same checks as research-web_bsi_lint.py) -----------------
    blt = [d for d in fills if ue.get_type(d) is not None and
           getattr(d, "OperationType" if d.is_a("IfcDoor") else "PartitioningType", None) is not None]
    item("bsi_BLT001_BLT002", not blt, f"{len(blt)} typed doors/windows with OperationType/PartitioningType set")
    ojt = []
    for o in f.by_type("IfcObject"):
        if not hasattr(o, "PredefinedType"):
            continue
        t = ue.get_type(o)
        if t is not None and getattr(t, "PredefinedType", None) not in (None, "NOTDEFINED") and o.PredefinedType:
            ojt.append(o)
        elif t is None and o.PredefinedType == "USERDEFINED" and not getattr(o, "ObjectType", None):
            ojt.append(o)
    ojt += [t for t in f.by_type("IfcTypeObject") if getattr(t, "PredefinedType", None) == "USERDEFINED"
            and not getattr(t, "ElementType", None)]
    by = collections.Counter(o.is_a() for o in ojt)
    item("bsi_OJT001", not ojt, f"{len(ojt)} PredefinedType conflicts" + (f" {dict(by)}" if by else ""))
    sps = [e for e in f.by_type("IfcElement") if (bool(e.Decomposes) and bool(e.ContainedInStructure)) or
           (not e.Decomposes and not e.ContainedInStructure and not e.is_a("IfcFeatureElement"))]
    sps += [p for p in f.by_type("IfcProduct") if not (p.is_a("IfcElement") or p.is_a("IfcGrid") or
                                                       p.is_a("IfcAnnotation")) and getattr(p, "ContainedInStructure", None)]
    item("bsi_SPS007", not sps, f"{len(sps)} containment errors (element not contained / part both / spatial "
         "element contained)")
    g2 = [s for s in f.by_type("IfcSpace") if len([r for r in (s.Representation.Representations if s.Representation
                                                                 else []) if r.RepresentationIdentifier == "Body"
                                                    and r.RepresentationType in ("SweptSolid", "Clipping", "Brep",
                                                                                 "Tessellation")]) != 1]
    item("bsi_GEM002", not g2, f"{len(g2)} spaces without exactly one solid Body")
    try:
        import ifcopenshell.util.pset as upset
        tmpl = upset.get_template("IFC4" if f.schema.startswith("IFC4") else "IFC2X3")
        known = {t.Name for tf in tmpl.templates for t in tf.by_type("IfcPropertySetTemplate")}
    except Exception:  # noqa: BLE001
        known = set()
    pse = sorted({p.Name for p in f.by_type("IfcPropertySet") if p.Name and p.Name.startswith("Pset_")} - known) \
        if known else []
    item("bsi_PSE002", not pse, f"{len(pse)} custom Pset_ names" + (f": {pse[:4]}" if pse else ""))

    # --- validation ----------------------------------------------------------------------------------------------
    if do_validate:
        n = _validate(path, f)
        item("validate_errors_0", n == 0, "validate failed to run" if n is None else f"{n} ifcopenshell.validate issues")

    # --- geometry sanity -----------------------------------------------------------------------------------------
    wf = []
    zero = 0
    for w in walls:
        try:
            fp, z = footprint(w)
        except Exception:  # noqa: BLE001
            fp = None
        if fp is None or fp.is_empty:
            continue
        mrr = fp.minimum_rotated_rectangle
        c = list(mrr.exterior.coords) if mrr.geom_type == "Polygon" else []
        L = max((Point(c[i]).distance(Point(c[i + 1])) for i in range(len(c) - 1)), default=0.0)
        if L < 0.05 or fp.area < 1e-4:
            zero += 1
        else:
            wf.append((w, fp, z))
    item("geom_no_zero_walls", zero == 0, f"{zero} zero-length/zero-area walls; {len(wf)}/{nw} footprints read")
    dup = 0
    if wf:
        tree = STRtree([x[1] for x in wf])
        for i, (w, fp, z) in enumerate(wf):
            for j in tree.query(fp):
                j = int(j)
                if j <= i:
                    continue
                g, zg = wf[j][1], wf[j][2]
                if min(z[1], zg[1]) - max(z[0], zg[0]) <= 0.1:
                    continue
                inter = fp.intersection(g).area
                if inter > 0.5 * min(fp.area, g.area):
                    dup += 1
    item("geom_no_duplicate_walls", dup == 0, f"{dup} wall pairs overlapping > 50% of the smaller")
    floating = 0
    if fills:
        tree = STRtree([x[1] for x in wf]) if wf else None
        for d in fills:
            try:
                dfp, dz = footprint(d)
            except Exception:  # noqa: BLE001
                dfp = None
            o = (dfp.centroid.x, dfp.centroid.y, dz[0]) if dfp is not None and not dfp.is_empty else _origin(d)
            if o is None or tree is None:
                floating += 1
                continue
            pt = Point(o[0], o[1])
            near = [wf[int(j)] for j in tree.query(pt.buffer(0.35))]
            if not any(x[1].distance(pt) <= 0.35 and x[2][0] - 0.5 <= o[2] <= x[2][1] + 0.1 for x in near):
                floating += 1
    item("geom_no_floating_openings", floating == 0, f"{floating}/{len(fills)} doors/windows > 0.35 m from any wall")

    # native exports place each element locally (origin at the element), not everything at the storey origin
    loc, nloc = 0, 0
    for el, fp, _ in wf[:400]:
        o = _origin(el)
        if o is None:
            continue
        nloc += 1
        loc += fp.buffer(max(1.0, 0.1 * fp.length)).contains(Point(o[0], o[1]))
    item("local_placements", nloc and _frac(loc, nloc) >= 0.9, f"{loc}/{nloc} walls with placement origin at the wall")

    w = [x for x in items if not x["optional"]]
    sc = 100.0 * sum(x["pass"] for x in w) / max(len(w), 1)
    return {"path": str(path), "schema": f.schema, "score": round(sc, 1), "passed": sum(x["pass"] for x in w),
            "total": len(w), "items": items, "secs": round(time.time() - t0, 1)}


def table(results: list[dict]) -> str:
    keys = [x["key"] for x in results[0]["items"]]
    for r in results[1:]:
        keys += [x["key"] for x in r["items"] if x["key"] not in keys]
    head = "| item | " + " | ".join(f"{Path(r['path']).parent.name}/{Path(r['path']).stem}" for r in results) + " |"
    lines = [head, "|" + "---|" * (len(results) + 1)]
    lines.append("| **score** | " + " | ".join(f"**{r['score']}** ({r['passed']}/{r['total']})" for r in results) + " |")
    for k in keys:
        cells = []
        opt = False
        for r in results:
            x = next((i for i in r["items"] if i["key"] == k), None)
            if x is None:
                cells.append("-")
                continue
            opt |= x["optional"]
            cells.append(("PASS" if x["pass"] else "FAIL") + " " + x["detail"].replace("|", "/")[:110])
        lines.append(f"| {k}{' (opt)' if opt else ''} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("ifc", nargs="+")
    ap.add_argument("--ref", default=None, help=f"reference native IFC, e.g. {REF}")
    ap.add_argument("--no-validate", action="store_true")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    paths = ([a.ref] if a.ref else []) + a.ifc
    res = [score(p, not a.no_validate) for p in paths]
    print(table(res))
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    main()
