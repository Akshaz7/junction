"""Full-storey stairs from detected PDF stair runs (geometry only; detection stays in pdf_fixtures).

R4 status: PARTIAL. The planning step is done and tested:
  - risers(h, drawn_treads): the riser count whose riser height lies in 0.15-0.20 m, kept as close as
    possible to the drawn count. The storey height is fixed and only the count changes.
  - group(flights): pairs parallel runs that sit side by side (U / half-turn, landing at the aligned end)
    or perpendicular runs that meet (L / quarter-turn). Everything else is a straight run.
  - plan(flights, h): per stair, the turn, IFC PredefinedType, risers split per flight, and landing height.
enrich_ifc_file(f, planmaps): rebuilds our IfcStair entities in place. Each flight becomes one sawtooth side
profile (risers + treads + sloped underside) extruded across the flight width, and the stair climbs the full
storey height (semantics.wall_height_m, else the storey Hologram_StoreySource.WallHeight, else 3.0 m).
A U stair gets an IfcSlab LANDING at the turn; the second detected stair is merged into the first (its
GlobalId moves to the second flight, the second flight's GlobalId to the landing, so no GlobalId is lost).
Each stair is rebuilt in its own transaction: any error undoes that stair and leaves it as it was.
"""
from __future__ import annotations

import math
import re

RISER_MIN, RISER_MAX = 0.15, 0.20
DEFAULT_RISER = 0.175  # used only when no riser height is printed beside the run (Hologram_Evidence Source=default)
PREDEFINED = {"straight": "STRAIGHT_RUN_STAIR", "U": "HALF_TURN_STAIR", "L": "QUARTER_TURN_STAIR"}


def risers(h: float, drawn_risers: int | None = None) -> tuple[int, float]:
    """(count, riser height) for storey height h: the drawn count if it is buildable, else the nearest count
    that brings the riser height into RISER_MIN..RISER_MAX."""
    h = float(h)
    lo, hi = math.ceil(h / RISER_MAX - 1e-9), max(math.floor(h / RISER_MIN + 1e-9), 1)
    n = int(drawn_risers) if drawn_risers else int(round(h / 0.175))
    n = min(max(n, lo), hi)
    return n, h / n


def _unit(v):
    n = math.hypot(v[0], v[1]) or 1.0
    return (v[0] / n, v[1] / n)


def _ends(fl):
    """Start and end points of the run centre line (model metres)."""
    o, u, s = fl["origin"], _unit(fl["run"]), _unit(fl["side"])
    w2 = fl["width"] / 2
    a = (o[0] + s[0] * w2, o[1] + s[1] * w2)
    return a, (a[0] + u[0] * fl["length"], a[1] + u[1] * fl["length"])


def group(flights: list[dict], gap_max: float = 0.8) -> list[list[int]]:
    """Index groups: two flights per U or L stair, one per straight stair.
    A flight is {"origin": (x, y) corner, "run": (dx, dy), "side": (dx, dy), "length": m, "width": m, "treads": n}."""
    used, out = set(), []
    for i, a in enumerate(flights):
        if i in used:
            continue
        best = None
        for j in range(i + 1, len(flights)):
            if j in used:
                continue
            b = flights[j]
            ua, ub = _unit(a["run"]), _unit(b["run"])
            dot = abs(ua[0] * ub[0] + ua[1] * ub[1])
            (a0, a1), (b0, b1) = _ends(a), _ends(b)
            if dot > 0.98:
                # side by side: centre-line offset across the run is about the two half widths plus a small gap
                n = (-ua[1], ua[0])
                off = abs((b0[0] - a0[0]) * n[0] + (b0[1] - a0[1]) * n[1])
                gap = off - (a["width"] + b["width"]) / 2
                ta = sorted((0.0, a["length"]))
                tb = sorted(((b0[0] - a0[0]) * ua[0] + (b0[1] - a0[1]) * ua[1],
                             (b1[0] - a0[0]) * ua[0] + (b1[1] - a0[1]) * ua[1]))
                ov = min(ta[1], tb[1]) - max(ta[0], tb[0])
                if -0.05 <= gap <= gap_max and ov >= 0.5 * min(a["length"], b["length"]):
                    best = best or (j, "U")
            elif dot < 0.1:
                d = min(math.dist(p, q) for p in (a0, a1) for q in (b0, b1))
                if d <= (a["width"] + b["width"]) / 2 + gap_max:
                    best = best or (j, "L")
        if best:
            used.update((i, best[0]))
            out.append([i, best[0]])
        else:
            used.add(i)
            out.append([i])
    return out


def plan(flights: list[dict], h: float) -> list[dict]:
    """Per stair: turn, PredefinedType, total risers and riser height, risers per flight, landing z."""
    res = []
    for g in group(flights):
        drawn = sum(int(flights[k].get("treads") or 0) + 1 for k in g)
        n, rh = risers(h, drawn or None)
        if len(g) == 1:
            res.append({"flights": g, "turn": "straight", "predefined": PREDEFINED["straight"], "risers": n,
                        "riser_h": rh, "per_flight": [n], "landings_z": []})
            continue
        turn = "U" if abs(sum(x * y for x, y in zip(_unit(flights[g[0]]["run"]), _unit(flights[g[1]]["run"])))) > 0.5 \
            else "L"
        t0 = int(flights[g[0]].get("treads") or 0) + 1
        # a U stair has two equal flights (the drawn counts differ only by where the plan cut falls);
        # an L stair keeps the drawn proportion
        r1 = n // 2 if turn == "U" else min(max(int(round(n * t0 / max(drawn, 1))), 2), n - 2)
        res.append({"flights": g, "turn": turn, "predefined": PREDEFINED[turn], "risers": n, "riser_h": rh,
                    "per_flight": [r1, n - r1], "landings_z": [round(r1 * rh, 4)]})
    return res


WAIST = 0.18          # concrete waist under the pitch line (m)
LANDING_T = 0.20      # landing slab thickness (m)
MATERIAL = "Concrete"


def storey_height(f, storey=None, planmaps=None) -> float:
    for pm in planmaps or []:
        try:
            v = float(((pm or {}).get("semantics") or {}).get("wall_height_m") or 0)
        except (TypeError, ValueError):
            v = 0
        if 1.8 <= v <= 8.0:
            return v
    if storey is not None:
        import ifcopenshell.util.element as ue
        try:
            v = float((ue.get_psets(storey).get("Hologram_StoreySource") or {}).get("WallHeight") or 0)
            if 1.8 <= v <= 8.0:
                return v
        except Exception:  # noqa: BLE001
            pass
    return 3.0


def _curve_pts(c):
    if c.is_a("IfcPolyline"):
        return [tuple(p.Coordinates[:2]) for p in c.Points]
    if c.is_a("IfcIndexedPolyCurve"):
        return [tuple(p[:2]) for p in c.Points.CoordList]
    return []


def _solids_world(fl):
    """[(ring world xy, z bottom, z top)] of the flight's extruded step solids (vertical extrusions only)."""
    import numpy as np
    import ifcopenshell.util.placement as up
    M = up.get_local_placement(fl.ObjectPlacement) if fl.ObjectPlacement else np.eye(4)
    out = []
    for rep in (fl.Representation.Representations if fl.Representation else []):
        for it in rep.Items:
            if not it.is_a("IfcExtrudedAreaSolid") or not it.SweptArea.is_a("IfcArbitraryClosedProfileDef"):
                continue
            P = up.get_axis2placement(it.Position) if it.Position else np.eye(4)
            T = M @ P
            pts = _curve_pts(it.SweptArea.OuterCurve)
            if len(pts) < 3:
                continue
            d = np.array(it.ExtrudedDirection.DirectionRatios, float)
            zdir = (T[:3, :3] @ d)
            if abs(zdir[2]) < 0.99 * np.linalg.norm(zdir):
                continue
            ring = [tuple((T @ np.array([x, y, 0.0, 1.0]))[:2]) for x, y in pts]
            z0 = float(T[2, 3])
            out.append((ring, z0, z0 + float(it.Depth) * float(np.sign(zdir[2]))))
    return out


def _flight_from_solids(fl, tread_hint=None):
    """Planner flight dict (+ "z0") read from the stepped plan slices: the run is the direction the slices
    climb (lowest step -> highest), footprint = their bounding rectangle along that run."""
    import numpy as np
    sol = _solids_world(fl)
    if not sol:
        return None
    sol.sort(key=lambda r: r[2])
    cen = [np.mean(np.array(r[0][:-1] if r[0][0] == r[0][-1] else r[0]), axis=0) for r in sol]
    pts = np.array([p for r in sol for p in r[0]], float)
    if len(sol) >= 2 and np.linalg.norm(cen[-1] - cen[0]) > 0.05:
        u = (cen[-1] - cen[0]) / np.linalg.norm(cen[-1] - cen[0])
    else:
        r = np.array(sol[0][0][:4], float)
        e = r[1] - r[0]
        u = e / (np.linalg.norm(e) or 1)
    s = np.array([-u[1], u[0]])
    tu, ts = pts @ u, pts @ s
    o = u * tu.min() + s * ts.min()
    L, W = float(tu.max() - tu.min()), float(ts.max() - ts.min())
    n = len(sol)
    return {"origin": (float(o[0]), float(o[1])), "run": (float(u[0]), float(u[1])), "side": (float(s[0]), float(s[1])),
            "length": L, "width": W, "treads": n, "z0": min(r[1] for r in sol),
            "tread": float(tread_hint) if tread_hint and 0.2 <= float(tread_hint) <= 0.4 else
            (L / n if n and 0.2 <= L / n <= 0.4 else 0.28)}


def profile(n, rh, t, waist=WAIST):
    """Sawtooth side profile (x along the climb, y up) of a flight of n risers: one riser on each of the n drawn
    nosing lines (x = 0 .. (n-1) t) and the n-1 treads between them, so the flight is exactly as long as its drawn
    run; the last riser is the face of the landing / upper floor slab edge at x = (n-1) t (that slab carries the
    top surface), so the solid itself tops out at (n-1) rh. Sloped underside."""
    pts = [(0.0, 0.0)]
    for k in range(n - 1):
        pts += [(k * t, (k + 1) * rh), ((k + 1) * t, (k + 1) * rh)]
    xe = (n - 1) * t
    slope = rh / t if t > 0 else 1.0
    c = waist * math.sqrt(1 + slope * slope)  # vertical depth of the waist under the pitch line
    yu = min(n * rh - c, (n - 1) * rh - 0.02)
    xb = c / slope
    if yu > 0.02 and xb < xe:
        pts += [(xe, yu), (xb, 0.0)]
    else:
        pts += [(xe, 0.0)]
    out = []
    for p in pts:
        if not out or math.dist(out[-1], p) > 1e-6:
            out.append((round(p[0], 6), round(p[1], 6)))
    return out


class _Ctx:
    def __init__(self, f):
        self.f, self.mat = f, None

    def material(self):
        import ifcopenshell.api.material
        if self.mat is None:
            m = [x for x in self.f.by_type("IfcMaterial") if x.Name == MATERIAL]
            self.mat = m[0] if m else ifcopenshell.api.material.add_material(self.f, name=MATERIAL)
        return self.mat


def _inv_xy(Minv, p, z=0.0):
    import numpy as np
    q = Minv @ np.array([p[0], p[1], z, 1.0])
    return q[:3]


def _flight_solid(f, Minv, start, d, w, n, rh, t, z, pts=None):
    """Profile extruded across the width; start = bottom-riser centre (world xy), d = climb unit (world).
    pts: another side profile in the same (x along d, y up) frame, e.g. a balustrade panel."""
    import numpy as np
    d3 = np.array([d[0], d[1], 0.0])
    a3 = np.array([d[1], -d[0], 0.0])  # across: a x d = up
    R = Minv[:3, :3]
    loc = _inv_xy(Minv, (start[0] - a3[0] * w / 2, start[1] - a3[1] * w / 2), z)
    pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint([float(v) for v in loc]),
                                      f.createIfcDirection([float(v) for v in R @ a3]),
                                      f.createIfcDirection([float(v) for v in R @ d3]))
    pl = f.createIfcCartesianPointList2D(pts or profile(n, rh, t))
    k = len(pl.CoordList)
    curve = f.createIfcIndexedPolyCurve(pl, [f.createIfcLineIndex(list(range(1, k + 1)) + [1])], False)
    prof = f.createIfcArbitraryClosedProfileDef("AREA", "stair flight side profile", curve)
    return f.createIfcExtrudedAreaSolid(prof, pos, f.createIfcDirection((0.0, 0.0, 1.0)), float(w))


RAIL_H, RAIL_T = 0.9, 0.04


def rail_profile(n, rh, t, height=RAIL_H):
    """Balustrade panel along a flight side: from just under the nosing line up to `height` above it."""
    xe = (n - 1) * t if n > 1 else t
    return [(0.0, rh - 0.05), (xe, n * rh - 0.05), (xe, n * rh + height), (0.0, rh + height)]


def _rail_line(f, rl):
    """(mid xy, unit dir, length) of a plan railing from its extruded footprint (world)."""
    import numpy as np
    sol = _solids_world(rl)
    if not sol:
        return None
    pts = np.array(sol[0][0], float)
    c = pts.mean(0)
    w, v = np.linalg.eigh(np.cov((pts - c).T))
    e = v[:, -1]
    L = float(np.ptp((pts - c) @ e))
    return c, e, L


def _rails(f, C, st0, Minv, geo, rails, wells, h):
    """Open-side balustrades: each plan railing that runs along a rebuilt flight side is reshaped to follow the
    pitch; a U stair's well sides get one even when the plan drew none. Returns railings written."""
    import numpy as np
    import ifcopenshell.api.root
    import ifcopenshell.api.spatial
    import ifcopenshell.util.element as ue
    done, used = 0, set()
    for gi, (fl, start, d, w, r, zb, rh, t) in enumerate(geo):
        d = np.array(d); a = np.array([d[1], -d[0]])
        run = max(r - 1, 1) * t
        for sg in (1.0, -1.0):
            p0 = np.array(start) + a * sg * w / 2
            best = None
            for k, (rl, ln) in enumerate(rails):
                if k in used or ln is None:
                    continue
                m, e, L = ln
                if abs(float(np.dot(e, d))) < 0.95:
                    continue
                off = abs(float(np.dot(m - p0, a)))
                along = float(np.dot(m - p0, d))
                if off < 0.3 and -0.5 <= along <= run + 0.5 and (best is None or off < best[0]):
                    best = (off, k)
            well = (gi, sg) in wells
            if best is None and not well:
                continue
            if best is not None:
                rl = rails[best[1]][0]
                rails[best[1]] = (rl, None)  # one railing reshapes one flight side
                ctx, styles = _old_style(f, rl)
            else:
                rl = ifcopenshell.api.root.create_entity(f, ifc_class="IfcRailing", predefined_type="GUARDRAIL",
                                                         name=f"{st0.Name or 'Stair'} well rail")
                cont = ue.get_container(st0)
                if cont is not None:
                    ifcopenshell.api.spatial.assign_container(f, products=[rl], relating_structure=cont)
                ctx, styles = _old_style(f, fl)
                if rails:
                    c2, s2 = _old_style(f, rails[0][0])
                    styles = s2 or styles
                _pset(f, rl, "Hologram_Provenance", {"source": "pdf_stairs", "evidence": "U stair well side"})
            centre = np.array(start) + a * sg * (w / 2 - 0.05)
            sol = _flight_solid(f, Minv, centre, d, RAIL_T, r, rh, t, zb, pts=rail_profile(r, rh, t))
            _set_shape(f, rl, ctx or _old_style(f, fl)[0], [sol], styles)
            rl.ObjectPlacement = f.createIfcLocalPlacement(st0.ObjectPlacement, f.createIfcAxis2Placement3D(
                f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None))
            _pset(f, rl, "Pset_RailingCommon", {"Height": RAIL_H, "IsExternal": False,
                                                "Reference": "Stair balustrade"})
            _pset(f, rl, "Hologram_StairRail", {"Stair": st0.GlobalId, "Flight": fl.GlobalId,
                                                "Side": "well" if well else "open side (plan railing)"})
            _pset(f, rl, "Hologram_Evidence", {
                "Source": "measured" if best is not None else "derived", "HeightSource": "default",
                "Detail": ("drawn railing line beside the run, reshaped to follow the flight pitch" if best is not None
                           else "well side of a U stair (between the two drawn runs), no railing line drawn")
                + f"; {RAIL_H} m default height"})
            done += 1
    return done


def _rect_solid(f, Minv, ring, z, h):
    pts = [tuple(float(v) for v in _inv_xy(Minv, p)[:2]) for p in ring]
    pl = f.createIfcCartesianPointList2D(pts)
    curve = f.createIfcIndexedPolyCurve(pl, [f.createIfcLineIndex(list(range(1, len(pts) + 1)) + [1])], False)
    prof = f.createIfcArbitraryClosedProfileDef("AREA", None, curve)
    zz = float(_inv_xy(Minv, (0, 0), z)[2])
    pos = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, zz)), None, None)
    return f.createIfcExtrudedAreaSolid(prof, pos, f.createIfcDirection((0.0, 0.0, 1.0)), float(h))


def _set_shape(f, product, ctx, items, styles):
    import ifcopenshell.api.geometry
    old = product.Representation
    if old is not None:
        for r in list(old.Representations):
            try:
                ifcopenshell.api.geometry.unassign_representation(f, product=product, representation=r)
                ifcopenshell.api.geometry.remove_representation(f, representation=r)
            except Exception:  # noqa: BLE001
                pass
    rep = f.createIfcShapeRepresentation(ctx, "Body", "SweptSolid", items)
    product.Representation = f.createIfcProductDefinitionShape(None, None, [rep])
    if styles:
        for it in items:
            f.createIfcStyledItem(it, styles, None)


def _old_style(f, product):
    if not product.Representation:
        return None, None
    for r in product.Representation.Representations:
        for it in r.Items:
            for si in f.get_inverse(it):
                if si.is_a("IfcStyledItem"):
                    return r.ContextOfItems, list(si.Styles)
        return r.ContextOfItems, None
    return None, None


def _pset(f, product, name, props):
    import ifcopenshell.api.pset
    import ifcopenshell.util.element as ue
    props = {k: v for k, v in props.items() if v is not None}
    cur = ue.get_psets(product).get(name)
    ps = f.by_id(cur["id"]) if cur else ifcopenshell.api.pset.add_pset(f, product=product, name=name)
    ifcopenshell.api.pset.edit_pset(f, pset=ps, properties=props)


def _material(f, C, products):
    import ifcopenshell.api.material
    import ifcopenshell.util.element as ue
    for p in products:
        try:
            m = ue.get_material(p, should_inherit=False)
        except Exception:  # noqa: BLE001
            m = None
        if m is None:
            ifcopenshell.api.material.assign_material(f, products=[p], material=C.material())


def _ours(st):
    import ifcopenshell.util.element as ue
    ps = ue.get_psets(st)
    return (ps.get("Hologram_Provenance") or {}).get("source") == "pdf_fixtures" or "Hologram_Stair" in ps


def _tread_hints(planmaps):
    out = {}
    for pm in planmaps or []:
        for i, fx in enumerate((pm or {}).get("fixtures") or []):
            if (fx or {}).get("kind") == "stair":
                out[(pm.get("page"), f"fixture-{i + 1}")] = fx.get("props") or {}
    return out


def _rebuild(f, C, stairs, flights, fdat, pl, h, rails=None, mode="drawn", note=None):
    """One planned stair (pl from plan()) over the listed IfcStair / IfcStairFlight / flight dicts."""
    import numpy as np
    import ifcopenshell.api.aggregate
    import ifcopenshell.api.root
    import ifcopenshell.guid
    import ifcopenshell.util.placement as up
    st0 = stairs[0]
    Mst = up.get_local_placement(st0.ObjectPlacement) if st0.ObjectPlacement else np.eye(4)
    Minv = np.linalg.inv(Mst)
    ctx, styles = _old_style(f, flights[0])
    if ctx is None:
        raise ValueError("flight has no body representation")
    z0 = min(d["z0"] for d in fdat)
    # DATA RULE: risers = drawn treads + 1 per flight; riser height and going as printed beside the run, else the
    # measured tread depth and a default riser (Source says which). No stretching to the storey height.
    pr = [d.get("printed") or {} for d in fdat]
    rp = [x["riser_printed_m"] for x in pr if x.get("riser_printed_m")]
    gp = [x["going_printed_m"] for x in pr if x.get("going_printed_m")]
    t = float(np.median(gp)) if gp else float(np.median([d["tread"] for d in fdat]))
    drawn = [int(d["treads"]) for d in fdat]
    rtxt = pr[0].get("riser_text") or next((x.get("riser_text") for x in pr if x.get("riser_text")), "")
    going = (f"printed '{next((x['going_text'] for x in pr if x.get('going_text')), '')}'" if gp
             else "measured drawn tread spacing")
    if mode == "full":
        # a stair in its stair room connects the two floors: the plan cuts it at ~1.2 m, so the treads above the
        # cut are not drawn. Rise = storey height (derived from the printed levels); riser count from the printed
        # riser height when there is one, else the 175 mm class; split over the flights as drawn.
        basis = float(np.median(rp)) if rp else DEFAULT_RISER
        n = max(int(round(h / basis)), 2)
        rh = h / n
        if len(fdat) == 1:
            per = [n]
        else:
            r1 = min(max(int(round(n * drawn[0] / max(sum(drawn), 1))), 2), n - 2)
            per = [r1, n - r1]
        src = "derived"
        evid = {"riser": (f"{n} risers = storey {h:.3f} m / printed '{rtxt}' -> {rh * 1000:.1f} mm" if rp else
                          f"{n} risers = storey {h:.3f} m / {DEFAULT_RISER} m class -> {rh * 1000:.1f} mm"),
                "going": going, "risers": "full storey; drawn treads " + ", ".join(map(str, drawn))}
    else:
        rh = float(np.median(rp)) if rp else DEFAULT_RISER
        per = [k + 1 for k in drawn]
        n = sum(per)
        src = note or ("measured" if rp else "default")
        evid = {"riser": (f"printed '{rtxt}'" if rp else f"default {DEFAULT_RISER} m"), "going": going,
                "risers": "drawn treads + 1 per flight (" + ", ".join(map(str, drawn)) + " treads)"}
    pl = dict(pl, per_flight=per)
    built = []  # (flight, risers, base z, run length)
    geo, wells = [], set()  # per flight (flight, start, dir, width, risers, base z, rh, t); U well sides
    landing = None
    if len(fdat) == 1 or pl["turn"] != "U":
        # straight (and L for now: each flight climbs its share in its own drawn direction)
        zc = z0
        for fl, d, r in zip(flights, fdat, pl["per_flight"] if len(fdat) > 1 else [n]):
            u = np.array(d["run"]); s = np.array(d["side"]); o = np.array(d["origin"])
            start = o + s * d["width"] / 2
            start, wd = _trim_width(C, start, u, d["width"], (r - 1) * t)
            _set_shape(f, fl, ctx, [_flight_solid(f, Minv, start, u, wd, r, rh, t, zc)], styles)
            built.append((fl, r, zc, (r - 1) * t))
            geo.append((fl, tuple(start), tuple(u), wd, r, zc, rh, t))
            zc += r * rh
    else:
        a, b = fdat
        u = np.array(a["run"])
        s = np.array([-u[1], u[0]])
        def ext(d):
            pts = [np.array(d["origin"]), np.array(d["origin"]) + np.array(d["run"]) * d["length"],
                   np.array(d["origin"]) + np.array(d["side"]) * d["width"],
                   np.array(d["origin"]) + np.array(d["run"]) * d["length"] + np.array(d["side"]) * d["width"]]
            tu = [p @ u for p in pts]; ts = [p @ s for p in pts]
            return min(tu), max(tu), min(ts), max(ts)
        ea, eb = ext(a), ext(b)
        hi = abs(ea[1] - eb[1]) <= abs(ea[0] - eb[0])
        sgn = 1.0 if hi else -1.0          # +u points from the flights toward the turn
        turn_t = max(ea[1], eb[1]) if hi else min(ea[0], eb[0])
        # lower flight: the one whose detected climb already heads for the turn, else the first
        heads = [float(np.dot(np.array(d["run"]), u * sgn)) > 0 for d in (a, b)]
        lo = 0 if heads[0] or not heads[1] else 1
        order = [lo, 1 - lo]
        r1, r2 = pl["per_flight"][order[0]], pl["per_flight"][order[1]]
        zl = z0 + r1 * rh
        dirn = u * sgn
        for k, (idx, r) in enumerate(zip(order, (r1, r2))):
            e = (ea, eb)[idx]
            cs = (e[2] + e[3]) / 2
            w = e[3] - e[2]
            run_len = (r - 1) * t
            if k == 0:   # climbs toward the turn, last riser at the landing edge
                start = u * (turn_t - sgn * run_len) + s * cs
                d3 = dirn
                zb = z0
            else:        # leaves the landing, away from the turn
                start = u * turn_t + s * cs
                d3 = -dirn
                zb = zl
            start, w = _trim_width(C, start, d3, w, run_len)
            _set_shape(f, flights[idx], ctx, [_flight_solid(f, Minv, start, d3, w, r, rh, t, zb)], styles)
            built.append((flights[idx], r, zb, run_len))
            geo.append((flights[idx], tuple(start), tuple(d3), w, r, zb, rh, t))
            # the well side faces the other flight
            oc = ((ea, eb)[1 - idx][2] + (ea, eb)[1 - idx][3]) / 2
            acr = np.array([d3[1], -d3[0]])
            wells.add((len(geo) - 1, 1.0 if float(np.dot(acr, s)) * (oc - cs) > 0 else -1.0))
        smin, smax = min(ea[2], eb[2]), max(ea[3], eb[3])
        depth = max(a["width"], b["width"])
        t0, t1 = sorted((turn_t, turn_t + sgn * depth))
        ring = [tuple(u * t0 + s * smin), tuple(u * t1 + s * smin), tuple(u * t1 + s * smax), tuple(u * t0 + s * smax)]
        ring = _clip_to_walls(C, ring)
        landing = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSlab", predefined_type="LANDING",
                                                      name=f"{st0.Name or 'Stair'} landing 1")
        landing.ObjectPlacement = f.createIfcLocalPlacement(st0.ObjectPlacement, f.createIfcAxis2Placement3D(
            f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None))
        _set_shape(f, landing, ctx, [_rect_solid(f, Minv, ring, zl - LANDING_T, LANDING_T)], styles)
        _pset(f, landing, "Pset_SlabCommon", {"IsExternal": False, "LoadBearing": True, "Reference": "Stair landing"})
        _pset(f, landing, "Hologram_Provenance", {"source": "pdf_stairs", "evidence": "U stair turn"})
    _guard(C, geo, landing_ring=ring if landing is not None else None)
    # merge: the second IfcStair goes, its flight moves under the first; GlobalIds are kept
    if len(stairs) > 1:
        st1, fl1 = stairs[1], flights[1]
        old_st, old_fl = st1.GlobalId, fl1.GlobalId
        try:
            ifcopenshell.api.aggregate.unassign_object(f, products=[fl1])
        except Exception:  # noqa: BLE001
            pass
        fl1.ObjectPlacement = f.createIfcLocalPlacement(st0.ObjectPlacement, f.createIfcAxis2Placement3D(
            f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None))
        ifcopenshell.api.aggregate.assign_object(f, products=[fl1], relating_object=st0)
        st1.GlobalId = ifcopenshell.guid.new()
        ifcopenshell.api.root.remove_product(f, product=st1)
        fl1.GlobalId = old_st
        if landing is not None:
            landing.GlobalId = old_fl
        fl1.Name = f"{st0.Name or 'Stair'} flight 2"
    if landing is not None:
        ifcopenshell.api.aggregate.assign_object(f, products=[landing], relating_object=st0)
    # same-frame placement for flight 1 too (its geometry was written in the stair frame)
    for fl, *_ in built:
        if fl.ObjectPlacement is None or fl.ObjectPlacement.PlacementRelTo != st0.ObjectPlacement:
            fl.ObjectPlacement = f.createIfcLocalPlacement(st0.ObjectPlacement, f.createIfcAxis2Placement3D(
                f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None))
        else:
            M = up.get_local_placement(fl.ObjectPlacement)
            if not np.allclose(M, Mst, atol=1e-6):
                fl.ObjectPlacement = f.createIfcLocalPlacement(st0.ObjectPlacement, f.createIfcAxis2Placement3D(
                    f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None))
    # attributes, psets, material
    for k, (fl, r, zb, run_len) in enumerate(built):
        fl.NumberOfRisers, fl.NumberOfTreads = r, max(r - 1, 1)
        fl.RiserHeight, fl.TreadLength = round(rh, 4), round(t, 4)
        _pset(f, fl, "Pset_StairFlightCommon", {"NumberOfRiser": r, "NumberOfTreads": max(r - 1, 1),
                                                "RiserHeight": round(rh, 4), "TreadLength": round(t, 4),
                                                "Reference": f"Stair flight {r} risers"})
        _pset(f, fl, "Hologram_StairFlight", {"BaseElevation": round(zb - z0, 4), "Rise": round(r * rh, 4),
                                              "RunLength": round(run_len, 4), "Source": "pdf_stairs side profile"})
    st0.PredefinedType = pl["predefined"]
    _retype(f, st0, pl["predefined"], {"straight": "Straight run stair", "U": "Half turn stair",
                                       "L": "Quarter turn stair"}[pl["turn"]])
    _pset(f, st0, "Pset_StairCommon", {"NumberOfRiser": n, "NumberOfTreads": n - len(built),
                                       "RiserHeight": round(rh, 4), "TreadLength": round(t, 4), "IsExternal": False,
                                       "Reference": {"straight": "Straight run stair", "U": "Half turn stair",
                                                     "L": "Quarter turn stair"}[pl["turn"]]})
    _pset(f, st0, "Hologram_Stair", {"StoreyHeight": round(h, 4), "TotalRise": round(n * rh, 4),
                                     "FullStorey": bool(abs(n * rh - h) <= 1e-3), "Mode": mode,
                                     "Turn": pl["turn"], "Flights": len(built),
                                     "Landings": 1 if landing is not None else 0, "RebuiltBy": "pdf_stairs"})
    detail = (f"{n} risers x {rh * 1000:.1f} mm = {n * rh:.3f} m rise ({evid['risers']}; riser {evid['riser']}; "
              f"going {evid['going']}); plan position, run direction and width measured from the drawn tread lines")
    for el in [st0] + [fl for fl, *_ in built]:
        _pset(f, el, "Hologram_Evidence", {"Source": src, "Detail": detail})
    if landing is not None:
        _pset(f, landing, "Hologram_Evidence", {"Source": "derived", "Detail": "U-stair turn: between the two drawn "
                                                "runs, one flight width deep beyond their aligned ends; top at "
                                                f"flight 1 rise {r1 * rh:.3f} m"})
    _material(f, C, [fl for fl, *_ in built] + ([landing] if landing is not None else []))
    nr = _rails(f, C, st0, Minv, geo, rails if rails is not None else [], wells, h)
    return {"flights": len(built), "landings": 1 if landing is not None else 0, "rise": n * rh, "rails": nr}


def _walls_xy(C):
    """Union of the wall footprints (world XY), cached on the context; None when there are none."""
    if getattr(C, "walls", 0) == 0:
        from shapely.ops import unary_union
        from pipeline.ifc_enrich import footprint
        polys, C.stair_walls = [], []
        runs = getattr(C, "runs", None) or []
        for w in C.f.by_type("IfcWall"):
            try:
                fp, _ = footprint(w)
            except Exception:  # noqa: BLE001
                fp = None
            if fp is None or fp.is_empty:
                continue
            if any(fp.intersection(r).area > 0.6 * fp.area for r in runs):
                C.stair_walls.append(w.GlobalId)  # lies inside a drawn stair run: the stair's own linework
                continue
            polys.append(fp)
        C.walls = unary_union(polys) if polys else None
    return C.walls


def _spaces_xy(C):
    """[(IfcSpace, world-XY footprint)], cached on the context."""
    if getattr(C, "spaces", None) is None:
        from pipeline.ifc_enrich import footprint
        out = []
        for sp in C.f.by_type("IfcSpace"):
            try:
                fp, _ = footprint(sp)
            except Exception:  # noqa: BLE001
                fp = None
            if fp is not None and not fp.is_empty and fp.area > 0.5:
                out.append((sp, fp))
        C.spaces = out
    return C.spaces


def _clip_to_walls(C, ring, keep=0.5):
    """The landing outline minus the walls it overlaps (largest piece), when that keeps most of it."""
    from shapely.geometry import Polygon
    walls = _walls_xy(C)
    R = Polygon(ring)
    if walls is None or walls.intersection(R).area < 1e-4:
        return ring
    D = R.difference(walls)
    D = max(D.geoms, key=lambda g: g.area) if hasattr(D, "geoms") else D
    if D.is_empty or D.area < keep * R.area or not hasattr(D, "exterior"):
        return ring
    c = list(D.simplify(0.01).exterior.coords)[:-1]
    return [tuple(map(float, q)) for q in c] if len(c) >= 3 else ring


def _trim_width(C, start, u, w, L, min_w=0.6):
    """Narrow a flight (centre line start + u * [0, L], width w) so it stops at the face of any wall it overlaps
    along its side: detected run outlines often include the stringer wall. Returns (start, width)."""
    import numpy as np
    from shapely.geometry import Polygon
    walls = _walls_xy(C)
    if walls is None or L <= 0:
        return start, w
    st, u = np.asarray(start, float), np.asarray(u, float)
    sv = np.array([-u[1], u[0]])
    R = Polygon([tuple(st - sv * w / 2), tuple(st - sv * w / 2 + u * L), tuple(st + sv * w / 2 + u * L),
                 tuple(st + sv * w / 2)])
    inter = walls.intersection(R)
    if inter.is_empty or inter.area < 1e-4:
        return start, w
    lo, hi = -w / 2, w / 2
    for g in (inter.geoms if hasattr(inter, "geoms") else [inter]):
        if g.area < 1e-4 or not hasattr(g, "exterior"):
            continue
        pr = [float((np.array(c) - st) @ sv) for c in g.exterior.coords]
        if (min(pr) + max(pr)) / 2 >= 0:
            hi = min(hi, min(pr))
        else:
            lo = max(lo, max(pr))
    if hi - lo < min_w:
        return start, w  # a wall across the middle: leave it to the guard
    return tuple(st + sv * (lo + hi) / 2), hi - lo


def _guard(C, geo, landing_ring=None, cross_m=0.1, out_m=0.1):
    """Sanity guard: no rebuilt flight (or landing) may cut into a wall deeper than cross_m or leave the building
    region (rooms + filled wall outline) by more than out_m. Raises ValueError, so the caller's transaction undoes
    this stair and it keeps its drawn steps."""
    import numpy as np
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    walls = _walls_xy(C)
    region = getattr(C, "region", None)
    if region is None:  # filled building outline: walls closed by 1.5 m, holes (shafts, rooms) filled, + rooms
        parts = [g for _, g in _spaces_xy(C)]
        if walls is not None:
            uw = walls.buffer(1.5, join_style=2).buffer(-1.5, join_style=2)  # closes envelope gaps up to 3 m
            parts += [Polygon(p.exterior) for p in (uw.geoms if hasattr(uw, "geoms") else [uw]) if hasattr(p, "exterior")]
        C.region = region = unary_union(parts).buffer(out_m) if parts else False
    rings = []
    for _fl, start, d3, w, r, _zb, _rh, t in geo:
        st, u = np.array(start), np.array(d3)
        sv = np.array([-u[1], u[0]])
        L = max((r - 1) * t, 0.05)
        rings.append([tuple(st - sv * w / 2), tuple(st - sv * w / 2 + u * L), tuple(st + sv * w / 2 + u * L),
                      tuple(st + sv * w / 2)])
    if landing_ring is not None:
        rings.append([tuple(map(float, p)) for p in landing_ring])
    for ring in rings:
        R = Polygon(ring).buffer(0)
        if R.is_empty:
            continue
        if walls is not None and walls.intersection(R.buffer(-cross_m)).area > 1e-3:
            raise ValueError("rebuilt flight cuts through a wall")
        if region is not False and R.difference(region).area > 1e-3:
            raise ValueError("rebuilt flight leaves the building region")


STAIR_ROOM = re.compile(r"stair|porra|trepp|trapp|escal|\bpk\b|\bph\b", re.I)


def _in_stair_room(C, d):
    """The drawn run stands in a space named as a stair room (STAIR / PORRASHUONE / TREPPENHAUS / TRAPPHUS ...)."""
    from shapely.geometry import Point
    import numpy as np
    mid = np.array(d["origin"]) + np.array(d["run"]) * d["length"] / 2 + np.array(d["side"]) * d["width"] / 2
    for sp, g in _spaces_xy(C):
        if g.buffer(0.3).contains(Point(float(mid[0]), float(mid[1]))):
            if STAIR_ROOM.search(f"{sp.Name or ''} {sp.LongName or ''}"):
                return True
    return False


def _retype(f, st, predefined, name):
    """The IfcStairType must carry the planned PredefinedType: pdf_fixtures typed every detected run as a straight
    run stair, and a typed occurrence reads its PredefinedType from the type (bSI BLT001 leaves the occurrence empty).
    Reuses or creates the type (stable GlobalId from the old type's), keeps its material, then empties the
    occurrence attribute as ifc_enrich._typed_occurrence_attrs does."""
    import uuid
    import ifcopenshell.api.material
    import ifcopenshell.api.root
    import ifcopenshell.api.type
    import ifcopenshell.guid
    import ifcopenshell.util.element as ue
    old = ue.get_type(st)
    if old is not None and getattr(old, "PredefinedType", None) == predefined:
        st.PredefinedType = None
        return old
    t = next((x for x in f.by_type("IfcStairType") if x.PredefinedType == predefined and x.Name == name), None)
    if t is None:
        t = ifcopenshell.api.root.create_entity(f, ifc_class="IfcStairType", name=name, predefined_type=predefined)
        seed = old.GlobalId if old is not None else st.GlobalId
        t.GlobalId = ifcopenshell.guid.compress(uuid.uuid5(uuid.NAMESPACE_URL, f"hologram-stairtype:{seed}:{predefined}").hex)
        mat = ue.get_material(old) if old is not None else None
        if mat is not None:
            try:
                ifcopenshell.api.material.assign_material(f, products=[t], type=mat.is_a(), material=mat)
            except Exception:  # noqa: BLE001
                pass
    ifcopenshell.api.type.assign_type(f, related_objects=[st], relating_type=t)
    st.PredefinedType = None
    return t


def enrich_ifc_file(f, planmaps=None, report=None) -> int:
    """Rebuild our IfcStair entities in place (see the module docstring). Returns the number of stairs rebuilt;
    never raises. `report` (a list), when given, receives one dict per rebuilt stair."""
    try:
        import ifcopenshell.util.element as ue
    except Exception:  # noqa: BLE001
        return 0
    done = 0
    try:
        C = _Ctx(f)
        hints = _tread_hints(planmaps)
        rails = []
        for rl in f.by_type("IfcRailing"):
            try:
                pv = ue.get_psets(rl).get("Hologram_Provenance") or {}
                if pv.get("source") == "pdf_fixtures":
                    rails.append((rl, _rail_line(f, rl)))
            except Exception:  # noqa: BLE001
                continue
        by_storey = {}
        for st in f.by_type("IfcStair"):
            try:
                if not _ours(st):
                    continue
                if (ue.get_psets(st).get("Hologram_Stair") or {}).get("Spiral"):
                    continue  # spiral stairs are authored from their drawn circle by pdf_fixtures
                fls = [x for x in ue.get_decomposition(st) if x.is_a("IfcStairFlight")]
                if len(fls) != 1:
                    continue
                prov = ue.get_psets(st).get("Hologram_Provenance") or {}
                hp = hints.get((prov.get("page"), prov.get("item_id"))) or {}
                d = _flight_from_solids(fls[0], hp.get("going_printed_m") or hp.get("tread_depth_m"))
                if d is None:
                    continue
                d["printed"] = {k: hp.get(k) for k in ("riser_printed_m", "going_printed_m", "riser_text",
                                                        "going_text") if hp.get(k)}
                if hp.get("treads"):
                    d["treads"] = int(hp["treads"])
                cont = ue.get_container(st)
                by_storey.setdefault(cont.id() if cont else 0, (cont, []))[1].append((st, fls[0], d))
            except Exception:  # noqa: BLE001
                continue
        from shapely.geometry import Polygon as _P
        C.runs = []
        for _cont, _items in by_storey.values():
            for _st, _fl, d in _items:
                o, u, sd = d["origin"], d["run"], d["side"]
                C.runs.append(_P([o, (o[0] + u[0] * d["length"], o[1] + u[1] * d["length"]),
                                  (o[0] + u[0] * d["length"] + sd[0] * d["width"],
                                   o[1] + u[1] * d["length"] + sd[1] * d["width"]),
                                  (o[0] + sd[0] * d["width"], o[1] + sd[1] * d["width"])]).buffer(0.05))
        for cont, items in by_storey.values():
            h = storey_height(f, cont, planmaps)
            plans = plan([d for _, _, d in items], h)
            for pl in plans:
                sts = [items[k][0] for k in pl["flights"]]
                fls = [items[k][1] for k in pl["flights"]]
                fd = [items[k][2] for k in pl["flights"]]
                try:
                    f.begin_transaction()
                except Exception:  # noqa: BLE001
                    pass
                full = pl["turn"] != "straight" or _in_stair_room(C, fd[0])
                tries = [("full", None), ("drawn", "partial: full storey does not fit")] if full else \
                    [("drawn", "partial: run outside a stair room, kept as drawn")]
                for k, (mode, note) in enumerate(tries):
                    if k:
                        try:
                            f.begin_transaction()
                        except Exception:  # noqa: BLE001
                            pass
                    try:
                        r = _rebuild(f, C, sts, fls, fd, pl, h, rails, mode=mode, note=note)
                        try:
                            f.end_transaction()
                        except Exception:  # noqa: BLE001
                            pass
                        done += 1
                        if report is not None:
                            report.append({"stair": sts[0].GlobalId, "name": sts[0].Name, "turn": pl["turn"],
                                           "storey_height": h, "mode": mode, "note": note, **r})
                        break
                    except Exception as e:  # noqa: BLE001
                        try:
                            f.end_transaction()
                            f.undo()
                        except Exception:  # noqa: BLE001
                            pass
                        C.mat = None
                        if report is not None:
                            report.append({"stair": sts[0].GlobalId, "mode": mode, "error": repr(e)[:200]})
    except Exception:  # noqa: BLE001
        return done
    return done
