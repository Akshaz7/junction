"""Benchmark PDF -> IFC against a native IFC of the same building (the PDF sheet was drawn from that IFC).

  .venv/bin/python scripts/eval_pdf_ifc.py <plan.pdf> <native.ifc> [--storey NAME|auto] [--name N]
        [--artifact DIR] [--shots DIR] [--json OUT]

Steps: run the real ingest on the PDF ($P/ingest.sh, unless --artifact points at an existing ingest output),
extract per-storey plan geometry from both IFCs (walls / doors / windows / spaces / slabs, projected to the XY
plane with ifcopenshell.geom; the native extraction is cached), align our wall footprint to each native storey
(scale + translation, 8 rotations/mirrors, refined by ICP on sampled wall-footprint points), pick the storey
that matches best (or --storey), then report:
  wall centreline length (ours / native), wall count, mean wall run length, door / window counts, space count
  and total area, envelope IoU (closed outer footprint polygons, after alignment), per-space area error for
  matched spaces (IoU >= 0.3 after alignment), storey elevation error, the alignment scale (1.0 = our printed
  scale is right) and scripts/ifc_native_score.py on our IFC if that script exists.
Also a side-by-side 3D render (native storey vs ours) PNG.

Each IFC extraction runs in its own subprocess (the native files reach 70 MB; peak RSS is printed).
No per-file tuning: everything here is generic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = Path(os.environ.get("P3D", "/tmp/claude-1000/-home-ar/68483dcf-9973-4d61-ad2f-715e6e4a2bdb/scratchpad/pdf3d/r3"))
CACHE = P / "eval_tmp" / "cache"
MAX_RSS_MB = int(os.environ.get("EVAL_MAX_RSS_MB", "1500"))
KINDS = {"IfcWall": "wall", "IfcWallStandardCase": "wall", "IfcCurtainWall": "wall", "IfcDoor": "door",
         "IfcWindow": "window", "IfcSpace": "space", "IfcSlab": "slab", "IfcColumn": "column", "IfcStair": "stair",
         "IfcStairFlight": "stair", "IfcRailing": "railing", "IfcRoof": "roof", "IfcCovering": "covering",
         "IfcFurnishingElement": "furniture", "IfcFurniture": "furniture", "IfcSanitaryTerminal": "sanitary",
         "IfcPlate": "wall", "IfcMember": "member", "IfcBeam": "beam"}
RENDER_COL = {"wall": "#8a8a8a", "door": "#c87828", "window": "#3c8cdc", "slab": "#d8d8d0", "space": None,
              "column": "#505050", "stair": "#a0a070", "railing": "#707070", "roof": "#b05040",
              "furniture": "#b09060", "sanitary": "#e0e0ff", "covering": None, "member": "#909090", "beam": "#909090"}


# ------------------------------------------------------------------ IFC extraction (subprocess worker)
def _extract(ifc_path: str, out_json: str, out_npz: str):
    import resource

    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.element as ue
    import numpy as np
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    t0 = time.time()
    f = ifcopenshell.open(ifc_path)
    storeys = {}
    for s in f.by_type("IfcBuildingStorey"):
        el = s.Elevation
        storeys[s.id()] = {"name": s.Name or s.LongName or f"#{s.id()}", "elevation": el, "items": []}
    # length unit for Elevation (geometry comes out in metres)
    try:
        import ifcopenshell.util.unit as uu
        lu = uu.calculate_unit_scale(f)
    except Exception:
        lu = 1.0
    for s in storeys.values():
        if s["elevation"] is not None:
            s["elevation"] = float(s["elevation"]) * lu
    st = ifcopenshell.geom.settings()
    st.set("use-world-coords", True)
    try:
        st.set("disable-opening-subtractions", True)  # footprints / renders: speed over exact holes
    except Exception:
        pass
    elems = []
    for t in KINDS:
        try:
            elems += f.by_type(t, include_subtypes=False)
        except RuntimeError:
            pass  # class not in this schema (IFC2X3 vs IFC4)
    sid_of = {}
    for e in elems:
        c = ue.get_container(e)
        if c is None:
            c = ue.get_aggregate(e)
        if c is None and getattr(e, "FillsVoids", None):  # door / window only linked through its host wall
            try:
                c = ue.get_container(e.FillsVoids[0].RelatingOpeningElement.VoidsElements[0].RelatingBuildingElement)
            except Exception:
                c = None
        while c is not None and not c.is_a("IfcBuildingStorey"):
            c = ue.get_aggregate(c) or ue.get_container(c)
        sid_of[e.id()] = c.id() if c is not None else None
    meshes_v, meshes_f, meshes_k, meshes_s = [], [], [], []
    nv = 0
    it = ifcopenshell.geom.iterator(st, f, max(1, min(4, os.cpu_count() or 1)), include=elems)
    if it.initialize():
        while True:
            sh = it.get()
            e = f.by_id(sh.id)
            kind = KINDS.get(e.is_a())
            v = np.asarray(sh.geometry.verts, float).reshape(-1, 3)
            fa = np.asarray(sh.geometry.faces, int).reshape(-1, 3)
            sid = sid_of.get(sh.id)
            if kind and len(fa) and sid in storeys:
                tri = v[fa][:, :, :2]
                e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
                ar = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) / 2
                polys = [Polygon(t) for t, a in zip(tri, ar) if a > 1e-6]
                fp = unary_union(polys).buffer(0) if polys else None
                rec = {"id": e.GlobalId, "kind": kind, "type": e.is_a(), "name": getattr(e, "Name", None),
                       "long_name": getattr(e, "LongName", None) if e.is_a("IfcSpace") else None,
                       "z": [float(v[:, 2].min()), float(v[:, 2].max())]}
                if fp is not None and not fp.is_empty:
                    fp = fp.simplify(0.005)
                    rec["fp"] = fp.__geo_interface__
                storeys[sid]["items"].append(rec)
                if kind != "space" and kind != "covering":
                    meshes_v.append(v.astype(np.float32)); meshes_f.append(fa + nv); nv += len(v)
                    meshes_k.append(np.full(len(fa), list(RENDER_COL).index(kind), np.int16))
                    meshes_s.append(np.full(len(fa), sid, np.int32))
            if not it.next():
                break
    out = {"ifc": ifc_path, "storeys": {str(k): v for k, v in storeys.items()}, "s": round(time.time() - t0, 1),
           "peak_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)}
    Path(out_json).write_text(json.dumps(out))
    if meshes_v:
        np.savez_compressed(out_npz, v=np.concatenate(meshes_v), f=np.concatenate(meshes_f),
                            k=np.concatenate(meshes_k), s=np.concatenate(meshes_s))
    print(json.dumps({"extract": ifc_path, "s": out["s"], "peak_mb": out["peak_mb"]}))


def extract(ifc: Path, cache=True):
    ifc = Path(ifc).resolve()
    st = ifc.stat()
    key = hashlib.sha1(f"{ifc}|{st.st_size}|{st.st_mtime}|v3".encode()).hexdigest()[:12]
    CACHE.mkdir(parents=True, exist_ok=True)
    js, npz = CACHE / f"{ifc.stem[:40]}-{key}.json", CACHE / f"{ifc.stem[:40]}-{key}.npz"
    if not (cache and js.exists()):
        pr = subprocess.Popen([sys.executable, __file__, "--_extract", str(ifc), str(js), str(npz)])
        while pr.poll() is None:  # RSS watchdog: the laptop is shared, anything past MAX_RSS_MB is killed
            try:
                rss = int(next(ln for ln in open(f"/proc/{pr.pid}/status") if ln.startswith("VmRSS")).split()[1]) // 1024
            except Exception:
                rss = 0
            if rss > MAX_RSS_MB:
                pr.kill()
                raise RuntimeError(f"IFC extraction of {ifc.name} passed {MAX_RSS_MB} MB RSS, killed")
            time.sleep(1)
        if pr.returncode:
            raise RuntimeError(f"IFC extraction of {ifc.name} failed rc={pr.returncode}")
    return json.loads(js.read_text()), (npz if npz.exists() else None)


# ------------------------------------------------------------------ geometry helpers
def _shape(gi):
    from shapely.geometry import shape
    return shape(gi).buffer(0)


def _wall_len(poly):
    """Centreline length of a wall footprint: for each polygon part, the long side of the equivalent rectangle."""
    tot = 0.0
    for g in getattr(poly, "geoms", [poly]):
        a, per = g.area, g.length
        d = max(per * per / 4 - 4 * a, 0.0)
        L = (per / 2 + math.sqrt(d)) / 2
        tot += L
    return tot


def _envelope(polys, close=0.4):
    """Closed outer footprint: union, morphological close, holes filled."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    u = unary_union([p for p in polys if p is not None and not p.is_empty])
    if u.is_empty:
        return u
    u = u.buffer(close, join_style=2).buffer(-close, join_style=2)
    parts = [Polygon(g.exterior) for g in getattr(u, "geoms", [u]) if g.area > 1.0]
    return unary_union(parts) if parts else u


def _sample(geom, step):
    import numpy as np
    pts = []
    for g in getattr(geom, "geoms", [geom]):
        for ring in [g.exterior, *g.interiors]:
            L = ring.length
            n = max(2, int(L / step))
            pts.extend(ring.interpolate(i * L / n).coords[0] for i in range(n))
    return np.asarray(pts, float).reshape(-1, 2)


def _apply(geom, T):
    """T = (R 2x2, s, t 2) -> s*R@p + t."""
    from shapely import affinity
    R, s, t = T
    a, b, c, d = R[0, 0] * s, R[0, 1] * s, R[1, 0] * s, R[1, 1] * s
    return affinity.affine_transform(geom, [a, b, c, d, t[0], t[1]])


def _iou(a, b):
    try:
        u = a.union(b).area
        return a.intersection(b).area / u if u > 0 else 0.0
    except Exception:
        return 0.0


def align(ours, native, ours_env, native_env):
    """Similarity (8 rotations/mirrors x scale x translation) mapping our wall footprint onto the native one.
    Init: envelope bbox centres + sqrt(area) ratio; refine: ICP with a nearest-neighbour KD-tree (scale + shift,
    rotation fixed to the candidate). Score: IoU of the dilated wall footprints. Returns (T, score)."""
    import numpy as np
    from scipy.spatial import cKDTree
    if ours.is_empty or native.is_empty:
        return None, 0.0
    nb = native.buffer(0.15)
    step = max(0.1, math.sqrt(native_env.area if native_env.area > 0 else native.area) / 150)
    qn = _sample(native, step)
    tree = cKDTree(qn)
    best = (None, -1.0)
    s0 = math.sqrt(max(native_env.area, 1e-6) / max(ours_env.area, 1e-6))
    for k in range(4):
        for mir in (1, -1):
            c, s_ = math.cos(k * math.pi / 2), math.sin(k * math.pi / 2)
            R = np.array([[c, -s_], [s_, c]]) @ np.diag([1, mir])
            oc = np.array(ours_env.centroid.coords[0])
            nc = np.array(native_env.centroid.coords[0])
            ob = np.array(ours_env.bounds).reshape(2, 2)
            nb_ = np.array(native_env.bounds).reshape(2, 2)
            inits = [(s0, nc - s0 * (R @ oc), False), (1.0, nc - R @ oc, True)]
            for cx_ in (0, 1):  # our plan may cover part of the storey: try each bbox corner at our scale
                for cy_ in (0, 1):
                    oc_ = R @ np.array([ob[cx_, 0], ob[cy_, 1]])
                    rb = np.array([R @ np.array([ob[i, 0], ob[j, 1]]) for i in (0, 1) for j in (0, 1)])
                    tgt = np.array([nb_[0, 0] if oc_[0] <= rb[:, 0].min() + 1e-9 else nb_[1, 0],
                                    nb_[0, 1] if oc_[1] <= rb[:, 1].min() + 1e-9 else nb_[1, 1]])
                    inits.append((1.0, tgt - oc_, True))
            for s, t, fix in inits:
                po = _sample(ours, step / s)
                for _ in range(25):
                    q = (s * (po @ R.T)) + t
                    d, j = tree.query(q)
                    keep = d < max(np.percentile(d, 80), 2 * step)
                    if keep.sum() < 10:
                        break
                    A, B = po[keep] @ R.T, qn[j[keep]]
                    Am, Bm = A.mean(0), B.mean(0)
                    s_new = s if fix else float(((A - Am) * (B - Bm)).sum() / max(((A - Am) ** 2).sum(), 1e-9))
                    if not (0.2 * s0 < s_new < 5 * s0):
                        break
                    t_new = Bm - s_new * Am
                    if abs(s_new - s) < 1e-5 * s and np.linalg.norm(t_new - t) < 1e-4:
                        s, t = s_new, t_new
                        break
                    s, t = s_new, t_new
                T = (R, s, t)
                # cheap symmetric score: share of boundary samples within 2 steps of the other footprint
                q = (s * (po @ R.T)) + t
                d1, _ = tree.query(q)
                d2, _ = cKDTree(q).query(qn)
                sc = 0.5 * (float((d1 < 2 * step).mean()) + float((d2 < 2 * step).mean()))
                if sc > best[1]:
                    best = (T, sc)
    if best[0] is not None:  # report the real footprint IoU of the winner
        best = (best[0], _iou(_apply(ours, best[0]).buffer(0.15), nb))
    return best


def storey_view(st: dict):
    from shapely.ops import unary_union
    items = st["items"]
    out = {"name": st["name"], "elevation": st["elevation"]}
    for k in ("wall", "door", "window", "space", "slab", "stair", "railing", "furniture", "sanitary", "column"):
        out[k] = [it for it in items if it["kind"] == k]
    walls = [_shape(it["fp"]) for it in out["wall"] if it.get("fp")]
    spaces = [(_shape(it["fp"]), it) for it in out["space"] if it.get("fp")]
    out["wall_geoms"] = walls
    out["wall_fp"] = unary_union(walls) if walls else None
    out["space_geoms"] = spaces
    out["env"] = _envelope(walls + [g for g, _ in spaces]) if walls else None
    return out


def metrics(o: dict, n: dict, T) -> dict:
    """o = our storey view, n = native storey view, T maps ours -> native."""
    def wl(v):
        return sum(_wall_len(g) for g in v["wall_geoms"])
    m = {}
    lo, ln = wl(o), wl(n)
    m["wall_len_m"] = [round(lo, 1), round(ln, 1), round(lo / ln, 3) if ln else None]
    m["walls_n"] = [len(o["wall"]), len(n["wall"])]
    m["wall_run_mean_m"] = [round(lo / len(o["wall"]), 2) if o["wall"] else None,
                            round(ln / len(n["wall"]), 2) if n["wall"] else None]
    m["doors_n"] = [len(o["door"]), len(n["door"])]
    m["windows_n"] = [len(o["window"]), len(n["window"])]
    ao, an = sum(g.area for g, _ in o["space_geoms"]), sum(g.area for g, _ in n["space_geoms"])
    m["spaces_n"] = [len(o["space"]), len(n["space"])]
    m["space_area_m2"] = [round(ao, 1), round(an, 1), round(ao / an, 3) if an else None]
    for k in ("stair", "railing", "furniture", "sanitary", "slab"):
        m[f"{k}_n"] = [len(o[k]), len(n[k])]
    if T is not None:
        R, s, t = T
        m["align_scale"] = round(s, 4)
        if o["env"] is not None and n["env"] is not None:
            m["envelope_iou"] = round(_iou(_apply(o["env"], T), n["env"]), 3)
            m["envelope_area_m2"] = [round(o["env"].area, 1), round(n["env"].area, 1)]
        if o["wall_fp"] is not None and n["wall_fp"] is not None:
            m["wall_fp_iou_30cm"] = round(_iou(_apply(o["wall_fp"], T).buffer(0.15), n["wall_fp"].buffer(0.15)), 3)
        # per-space: greedy by IoU, our space mapped into native frame; areas compared in our own metres
        pairs = []
        mapped = [(_apply(g, T), g, it) for g, it in o["space_geoms"]]
        for gn, itn in n["space_geoms"]:
            for k, (gm, g, it) in enumerate(mapped):
                iu = _iou(gm, gn)
                if iu >= 0.3:
                    pairs.append((iu, k, gn, g, itn, it))
        pairs.sort(key=lambda p: -p[0])
        used_o, used_n, errs, rows = set(), set(), [], []
        for iu, k, gn, g, itn, it in pairs:
            if k in used_o or id(gn) in used_n:
                continue
            used_o.add(k); used_n.add(id(gn))
            e = abs(g.area - gn.area) / gn.area if gn.area > 0 else None
            if e is not None:
                errs.append(e)
            rows.append({"native": itn.get("long_name") or itn.get("name"), "ours": it.get("long_name") or it.get("name"),
                         "a_native": round(gn.area, 2), "a_ours": round(g.area, 2), "iou": round(iu, 3)})
        m["spaces_matched"] = len(rows)
        if errs:
            import numpy as np
            m["space_area_err_median"] = round(float(np.median(errs)), 3)
            m["space_area_err_p90"] = round(float(np.percentile(errs, 90)), 3)
        m["space_pairs"] = rows
    if o["elevation"] is not None and n["elevation"] is not None:
        m["elevation_m"] = [round(o["elevation"], 3), round(n["elevation"], 3),
                            round(o["elevation"] - n["elevation"], 3)]
    return m


# ------------------------------------------------------------------ render (PIL only: no matplotlib in the venv)
def _hex(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def _iso_tris(npz, sid, T=None):
    """Triangles (n,3,3) + kind index of one storey from the extraction npz; T maps x,y (and scales z) into the
    native frame."""
    import numpy as np
    d = np.load(npz)
    sel = d["s"] == int(sid)
    F, K = d["f"][sel], d["k"][sel]
    V = d["v"].astype(float)
    if T is not None:
        R, sc, t = T
        V = V.copy()
        V[:, :2] = sc * (V[:, :2] @ R.T) + t
        V[:, 2] = V[:, 2] * sc
    tri = V[F]
    if len(tri):
        tri[:, :, 2] -= tri[:, :, 2].min()
    return tri, K


def render(npz_n, sid_n, npz_o, sid_o, T, out_png, title=""):
    """Side-by-side axonometric (30 deg) flat-shaded renders, painter's algorithm, shared extent (native frame)."""
    import numpy as np
    from PIL import Image, ImageDraw
    cols = list(RENDER_COL)
    W, H = 900, 760
    panels = []
    for npz, sid, TT in ((npz_n, sid_n, None), (npz_o, sid_o, T)):
        panels.append(_iso_tris(npz, sid, TT) if npz is not None else (np.zeros((0, 3, 3)), np.zeros(0, int)))
    az = math.radians(-35)
    ca, sa = math.cos(az), math.sin(az)

    def proj(p):  # rotate about z, then tilt 35 deg
        x = p[..., 0] * ca - p[..., 1] * sa
        y = p[..., 0] * sa + p[..., 1] * ca
        return np.stack([x, -(y * 0.57 + p[..., 2] * 0.82)], -1), y * 0.82 - p[..., 2] * 0.57
    allp = np.concatenate([proj(t)[0].reshape(-1, 2) for t, _ in panels if len(t)] or [np.zeros((1, 2))])
    lo, hi = allp.min(0), allp.max(0)
    k = min((W - 40) / max(hi[0] - lo[0], 1e-6), (H - 70) / max(hi[1] - lo[1], 1e-6))
    img = Image.new("RGB", (2 * W, H), (250, 250, 250))
    dr = ImageDraw.Draw(img)
    light = np.array([0.3, -0.5, 0.8]) / np.linalg.norm([0.3, -0.5, 0.8])
    for pi, ((tri, K), lab) in enumerate(zip(panels, ("native storey", "ours (aligned to native)"))):
        dr.text((pi * W + 12, 10), lab, fill=(0, 0, 0))
        if not len(tri):
            continue
        if len(tri) > 150000:
            ix = np.random.default_rng(0).choice(len(tri), 150000, replace=False)
            tri, K = tri[ix], K[ix]
        P2, depth = proj(tri)
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
        shade = 0.5 + 0.5 * np.abs(n @ light)
        order = np.argsort(-depth.mean(1))
        for i in order:
            c = RENDER_COL[cols[K[i]]] or "#cccccc"
            rgb = tuple(int(v * shade[i]) for v in _hex(c))
            q = [(pi * W + 20 + (x - lo[0]) * k, 50 + (y - lo[1]) * k) for x, y in P2[i]]
            dr.polygon(q, fill=rgb)
    dr.text((12, H - 18), title[:220], fill=(60, 60, 60))
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png)


def plan_overlay(o, n, T, out_png, title=""):
    """2D: native spaces light blue, native walls grey, native envelope blue; ours (aligned) walls + envelope red."""
    from PIL import Image, ImageDraw
    geoms = [g for g, _ in n["space_geoms"]] + n["wall_geoms"]
    if n["env"] is not None:
        geoms.append(n["env"])
    if T is not None:
        geoms += [_apply(g, T) for g in o["wall_geoms"]]
    from shapely.ops import unary_union
    bx = unary_union(geoms).bounds
    S = 1400
    k = (S - 60) / max(bx[2] - bx[0], bx[3] - bx[1], 1e-6)
    img = Image.new("RGB", (S, S + 30), (255, 255, 255))
    dr = ImageDraw.Draw(img, "RGBA")

    def xy(c):
        return [(30 + (x - bx[0]) * k, 30 + (bx[3] - y) * k) for x, y in c]

    def poly(g, **kw):
        for p in getattr(g, "geoms", [g]):
            if p.geom_type == "Polygon" and not p.is_empty:
                if "fill" in kw:
                    dr.polygon(xy(p.exterior.coords), fill=kw["fill"])
                else:
                    dr.line(xy(p.exterior.coords), fill=kw["line"], width=kw.get("w", 1))
    for g, _ in n["space_geoms"]:
        poly(g, fill=(200, 222, 245, 255))
    for g in n["wall_geoms"]:
        poly(g, fill=(110, 110, 110, 255))
    if n["env"] is not None:
        poly(n["env"], line=(30, 30, 150, 255), w=3)
    if T is not None:
        for g in o["wall_geoms"]:
            poly(_apply(g, T), line=(220, 30, 30, 255), w=2)
        if o["env"] is not None:
            poly(_apply(o["env"], T), line=(220, 30, 30, 200), w=4)
    dr.text((10, S + 8), title[:200], fill=(0, 0, 0))
    img.save(out_png)


# ------------------------------------------------------------------ main
def run_ingest(pdf: Path, name: str) -> Path:
    art = ROOT / "artifacts" / f"r3__{name}"
    cmd = [str(P / "ingest.sh"), str(pdf), name]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout[-1500:], r.stderr[-800:], f"ingest {time.time() - t0:.0f}s")
    return art


def native_score(ifc: Path):
    """scripts/ifc_native_score.py (ifc-native role) on our IFC: {score, passed, total, failed: [keys]} or None."""
    sc = ROOT / "scripts" / "ifc_native_score.py"
    if not sc.exists():
        return None
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "ns.json"
            r = subprocess.run([sys.executable, str(sc), str(ifc), "--json", str(out)], capture_output=True, text=True,
                               timeout=600)
            if not out.exists():
                return {"error": (r.stderr or r.stdout).strip()[-300:]}
            d = json.loads(out.read_text())
            d = d[0] if isinstance(d, list) and d else d
            return {"score": d.get("score"), "passed": d.get("passed"), "total": d.get("total"),
                    "failed": [i["key"] for i in d.get("items", []) if not i.get("pass") and not i.get("optional")]}
    except Exception as e:
        return {"error": repr(e)}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--_extract":
        _extract(*sys.argv[2:5])
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("native")
    ap.add_argument("--storey", default="auto")
    ap.add_argument("--name", default=None)
    ap.add_argument("--artifact", default=None, help="existing ingest output dir (skip the ingest)")
    ap.add_argument("--shots", default=str(P / "shots" / "eval"))
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    pdf, nat = Path(a.pdf).resolve(), Path(a.native).resolve()
    name = a.name or ("eval-" + pdf.stem.split("_")[0])
    art = Path(a.artifact) if a.artifact else run_ingest(pdf, name)
    ours_ifc = art / "model.ifc"
    if not ours_ifc.exists():
        print(json.dumps({"pdf": pdf.name, "error": "no model.ifc", "artifact": str(art)}))
        return
    N, npz_n = extract(nat)
    O, npz_o = extract(ours_ifc, cache=False)
    ov = [(sid, storey_view(s)) for sid, s in O["storeys"].items()]
    ov = [x for x in ov if x[1]["wall"]] or ov
    osid, o = max(ov, key=lambda x: len(x[1]["wall"]))  # the plan's storey: the one with the walls
    cands = []
    for sid, s in N["storeys"].items():
        v = storey_view(s)
        if not v["wall"]:
            continue
        if a.storey != "auto" and a.storey.lower() not in (v["name"] or "").lower():
            continue
        T, sc = align(o["wall_fp"], v["wall_fp"], o["env"], v["env"]) if o["wall_fp"] is not None else (None, 0.0)
        cands.append((sc, sid, v, T))
    if not cands:
        print(json.dumps({"pdf": pdf.name, "error": "no native storey with walls"}))
        return
    cands.sort(key=lambda c: -c[0])
    sc, nsid, n, T = cands[0]
    m = metrics(o, n, T)
    res = {"pdf": pdf.name, "native": nat.name, "artifact": str(art), "storey_native": n["name"],
           "storey_ours": o["name"], "align_wall_iou": round(sc, 3),
           "storey_candidates": [(c[2]["name"], round(c[0], 3)) for c in cands[:5]], **m,
           "native_score": native_score(ours_ifc), "extract_s": [O.get("s"), N.get("s")],
           "extract_peak_mb": [O.get("peak_mb"), N.get("peak_mb")]}
    shots = Path(a.shots)
    shots.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%H%M")
    try:
        render(npz_n, nsid, npz_o, osid, T, shots / f"{name}-3d-{stamp}.png",
               f"{pdf.stem[:60]}  native '{n['name']}' (left) vs ours (right)")
        plan_overlay(o, n, T, shots / f"{name}-plan-{stamp}.png",
                     f"{n['name']}: native walls grey / spaces blue / envelope blue dotted; ours red (aligned)")
        res["shots"] = [str(shots / f"{name}-3d-{stamp}.png"), str(shots / f"{name}-plan-{stamp}.png")]
    except Exception as e:
        res["render_error"] = repr(e)
    txt = json.dumps(res, indent=1, default=str)
    if a.json:
        Path(a.json).write_text(txt)
    print(txt)


if __name__ == "__main__":
    main()
