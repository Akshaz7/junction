"""Render a scene.glb (ours or a native IFC's) as a 3D view and a plan view PNG, same style for both, for side-by-side
"does it look native" checks. Colours by item kind (scene.json next to the GLB, when present; else by node name).

  .venv/bin/python scripts/render_glb_views.py scene.glb out_prefix [--scene scene.json] [--storey-y Y] [--cut 1.2]
      [--max-tris 250000] [--title T]

Writes out_prefix-3d.png and out_prefix-plan.png. The plan view keeps elements whose height range crosses the cut
plane (storey-y + cut; storey-y defaults to the lowest storey in scene.json, else the model's min y), drawn top-down,
lowest first, so it reads like a floor plan cut at 1.2 m. The 3D view keeps everything at or below storey-y + 4 m
when --storey-y is given (one storey), else the whole model. matplotlib Agg only, no GPU.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

COL = {"wall": "#b9b4aa", "door": "#a0522d", "window": "#5aa9e6", "space": "#e8e0c8", "slab": "#8f8f8f",
       "stair": "#d9822b", "railing": "#555555", "column": "#7a6f9b", "sanitary": "#3cb4a0", "furniture": "#c9a26b",
       "covering": "#cfcfcf", "roof": "#8b3a3a", "beam": "#6b6b9b", "duct": "#2e8b57", "terminal": "#2e8b57",
       "other": "#c0c0c0"}
SKIP_3D = {"space", "opening"}


def _kind_of(name, kinds):
    k = kinds.get(name)
    if k:
        return k
    n = name.lower()
    for key in COL:
        if key in n:
            return key
    return "other"


def _norm_kind(k):
    k = (k or "other").lower()
    for key, alias in (("wall", ("wall", "plate", "curtain")), ("door", ("door",)), ("window", ("window",)),
                       ("space", ("space", "room")), ("slab", ("slab", "floor")), ("stair", ("stair",)),
                       ("railing", ("railing",)), ("column", ("column",)), ("sanitary", ("sanitary", "toilet", "sink",
                                                                                         "shower", "bath")),
                       ("furniture", ("furni", "bed", "sofa", "table", "kitchen")), ("covering", ("covering", "ceiling")),
                       ("roof", ("roof",)), ("beam", ("beam", "member")), ("duct", ("duct", "pipe", "flow")),
                       ("terminal", ("terminal",)), ("opening", ("opening",))):
        if any(a in k for a in alias):
            return key
    return "other"


def load(glb, scene_json=None):
    import trimesh
    sc = trimesh.load(glb, force="scene")
    kinds = {}
    sj = scene_json or str(Path(glb).with_name("scene.json"))
    storey_y = None
    if sj and os.path.exists(sj):
        d = json.load(open(sj))
        for nid, it in (d.get("items") or {}).items():
            kinds[it.get("node") or nid] = it.get("kind")
        st = [s.get("elevation_m") for s in d.get("storeys") or [] if s.get("elevation_m") is not None]
        storey_y = min(st) if st else None
    parts = []
    for node in sc.graph.nodes_geometry:
        T, gname = sc.graph[node]
        g = sc.geometry.get(gname)
        if g is None or not hasattr(g, "faces") or len(g.faces) == 0:
            continue
        v = trimesh.transform_points(g.vertices, T)
        key = node if node in kinds else node.rsplit("_", 1)[0]  # multi-material parts: <guid>_<hash>
        kind = _norm_kind(kinds[key]) if kinds.get(key) else _norm_kind(_kind_of(f"{node} {gname}", {}))
        parts.append((kind, v, np.asarray(g.faces)))
    return parts, storey_y


def render(parts, out_prefix, storey_y=None, cut=1.2, max_tris=250000, title=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import PolyCollection
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    allv = np.concatenate([v for _, v, _ in parts]) if parts else np.zeros((1, 3))
    y0 = storey_y if storey_y is not None else float(allv[:, 1].min())
    # ---- plan
    fig, ax = plt.subplots(figsize=(12, 9), dpi=110)
    polys, cols, zs = [], [], []
    cy = y0 + cut
    for kind, v, f in parts:
        if v[:, 1].min() > cy or v[:, 1].max() < y0 - 0.05:
            continue
        if kind in ("slab", "covering", "roof") and v[:, 1].max() > cy:
            continue
        tri = v[f]
        for t in tri[:, :, [0, 2]]:
            polys.append(t)
        alpha_col = COL.get(kind, COL["other"])
        cols += [alpha_col] * len(tri)
        zs += [{"space": 0, "slab": -1, "wall": 2, "door": 3, "window": 3}.get(kind, 1)] * len(tri)
    if polys:
        o = np.argsort(zs, kind="stable")
        pc = PolyCollection([polys[i] for i in o], facecolors=[cols[i] for i in o], edgecolors="none")
        ax.add_collection(pc)
        P = np.concatenate(polys)
        ax.set_xlim(P[:, 0].min() - 1, P[:, 0].max() + 1)
        ax.set_ylim(P[:, 1].max() + 1, P[:, 1].min() - 1)
    ax.set_aspect("equal")
    ax.set_title(f"{title} plan cut at {cy:.1f} m")
    handles = [plt.Rectangle((0, 0), 1, 1, color=COL[k]) for k in sorted({p[0] for p in parts}) if k in COL]
    ax.legend(handles, [k for k in sorted({p[0] for p in parts}) if k in COL], loc="upper right", fontsize=7)
    fig.tight_layout()
    fig.savefig(out_prefix + "-plan.png")
    plt.close(fig)
    # ---- 3D
    fig = plt.figure(figsize=(14, 9), dpi=110)
    ax = fig.add_subplot(111, projection="3d")
    tris, fc = [], []
    light = np.array([0.4, 0.8, 0.45])
    light /= np.linalg.norm(light)
    ytop = (storey_y + 4.0) if storey_y is not None else np.inf
    for kind, v, f in parts:
        if kind in SKIP_3D or v[:, 1].min() > ytop:
            continue
        t = v[f]
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        nn = np.linalg.norm(n, axis=1, keepdims=True)
        nn[nn == 0] = 1
        sh = 0.55 + 0.45 * np.abs((n / nn) @ light)
        base = np.array(matplotlib.colors.to_rgb(COL.get(kind, COL["other"])))
        tris.append(t[:, :, [0, 2, 1]] * np.array([1, -1, 1]))  # x, -z (north up), y up
        fc.append(np.clip(base[None, :] * sh[:, None], 0, 1))
    if tris:
        T = np.concatenate(tris)
        C = np.concatenate(fc)
        if len(T) > max_tris:
            k = np.random.default_rng(0).choice(len(T), max_tris, replace=False)
            T, C = T[k], C[k]
        # painter's order for the fixed view direction
        az, el = np.radians(-60), np.radians(30)
        d = np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)])
        o = np.argsort(T.mean(axis=1) @ d)
        ax.add_collection3d(Poly3DCollection(T[o], facecolors=C[o], edgecolors="none", linewidths=0))
        mn, mx = T.reshape(-1, 3).min(0), T.reshape(-1, 3).max(0)
        ext = np.maximum(mx - mn, 1e-3)
        ax.set_xlim(mn[0], mx[0])
        ax.set_ylim(mn[1], mx[1])
        ax.set_zlim(mn[2], mx[2])
        ax.set_box_aspect(tuple(ext), zoom=1.0)
        ax.view_init(elev=30, azim=-60)
    ax.set_axis_off()
    ax.set_title(f"{title} 3D")
    fig.tight_layout()
    fig.savefig(out_prefix + "-3d.png")
    plt.close(fig)
    return out_prefix + "-3d.png", out_prefix + "-plan.png"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("glb")
    ap.add_argument("out_prefix")
    ap.add_argument("--scene")
    ap.add_argument("--storey-y", type=float)
    ap.add_argument("--cut", type=float, default=1.2)
    ap.add_argument("--max-tris", type=int, default=250000)
    ap.add_argument("--title", default="")
    a = ap.parse_args()
    parts, sy = load(a.glb, a.scene)
    print("parts", len(parts), "kinds", {k: sum(1 for p in parts if p[0] == k) for k in sorted({p[0] for p in parts})})
    print(render(parts, a.out_prefix, a.storey_y if a.storey_y is not None else sy, a.cut, a.max_tris, a.title))


if __name__ == "__main__":
    main()
