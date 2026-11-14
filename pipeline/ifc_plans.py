"""D-07: IFC storey plans. One page per storey (page-<n>.png, planmap-<n>.json, n by elevation).

Footprints come from the GLB nodes written by D-06 (top-facing faces projected on XZ), so item_ids are the
IFC GlobalIds and boxes are projected from the same 3D geometry the viewer shows.
Usage: uv run python -m pipeline.ifc_plans [--artifacts DIR] [--only DOC_ID ...]
"""
import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from shapely.geometry import Polygon
from shapely.ops import unary_union

from pipeline.pages import save_page

REPO = Path(__file__).resolve().parent.parent
PLAN_KINDS = {"wall", "door", "window", "room", "stairs", "column", "furniture", "railing", "curtain_wall"}
OUT_KIND = {"furniture": "other", "railing": "other", "curtain_wall": "wall"}
ORDER = ["room", "other", "stairs", "wall", "column", "window", "door"]
COLORS = {"room": (232, 238, 246), "other": (185, 185, 185), "stairs": (140, 140, 140), "wall": (55, 55, 55),
          "column": (15, 15, 15), "window": (60, 140, 220), "door": (210, 120, 40)}
MARGIN = 40
LONG_SIDE = 2400


def _cr(a, b):
    return a[0] * b[1] - a[1] * b[0]


def top_faces_xz(tm: trimesh.Trimesh, T, top_only=True):
    v = trimesh.transformations.transform_points(tm.vertices, T)
    f = tm.faces
    n = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    ln = np.linalg.norm(n, axis=1)
    ok = ln > 1e-12
    ny = np.zeros(len(f)); ny[ok] = n[ok, 1] / ln[ok]
    return v, (f[ny > 0.5] if top_only else f[ok])


def process(doc_id: str, art: Path):
    out = art / doc_id
    scene = json.loads((out / "scene.json").read_text())
    element_data = json.loads((out / "elements.json").read_text())
    els = {e["item_id"]: e for e in element_data["elements"]}
    sc = trimesh.load(str(out / "scene.glb"), force="scene")
    parts = defaultdict(list)  # item_id -> [(verts, faces)]; trimesh splits multi-material nodes into <guid>_<hash>
    for node in sc.graph.nodes_geometry:
        gid = node if node in els else node.rsplit("_", 1)[0]
        if gid in els and els[gid]["kind"] in PLAN_KINDS:
            T, gname = sc.graph[node]
            parts[gid].append(top_faces_xz(sc.geometry[gname], T, top_only=els[gid]["kind"] == "room"))
    meshes = {}
    for gid, ps in parts.items():
        off = np.cumsum([0] + [len(v) for v, _ in ps])
        meshes[gid] = (np.concatenate([v for v, _ in ps]),
                       np.concatenate([f + o for (_, f), o in zip(ps, off)]).astype(int))
    by_storey = defaultdict(list)
    for gid in meshes:
        st = els[gid]["storey"]
        if st:
            by_storey[(st["elevation_m"], st["name"])].append(gid)
    pages = []
    for n, key in enumerate(sorted(by_storey), start=1):
        ids = by_storey[key]
        allv = np.concatenate([meshes[i][0][np.unique(meshes[i][1])] for i in ids if len(meshes[i][1])])
        # extent from walls/doors/windows/rooms footprints only (furniture strays would distort)
        x0, x1 = allv[:, 0].min(), allv[:, 0].max()
        z0, z1 = allv[:, 2].min(), allv[:, 2].max()
        ppm = max(5.0, min(80.0, (LONG_SIDE - 2 * MARGIN) / max(x1 - x0, z1 - z0, 1e-6)))
        W = int((x1 - x0) * ppm) + 2 * MARGIN
        H = int((z1 - z0) * ppm) + 2 * MARGIN
        px = lambda v: np.stack([(v[:, 0] - x0) * ppm + MARGIN, (v[:, 2] - z0) * ppm + MARGIN], 1)
        img = Image.new("RGB", (W, H), "white")
        dr = ImageDraw.Draw(img)
        items, counter = [], defaultdict(int)
        for kind in ORDER:
            for gid in sorted(i for i in ids if OUT_KIND.get(els[i]["kind"], els[i]["kind"]) == kind):
                v, f = meshes[gid]
                if not len(f):
                    continue
                p2 = px(v)
                for tri in f:
                    dr.polygon([tuple(p2[k]) for k in tri], fill=COLORS[kind])
                used = p2[np.unique(f)]
                bbox = [round(float(used[:, 0].min()), 1), round(float(used[:, 1].min()), 1),
                        round(float(used[:, 0].max()), 1), round(float(used[:, 1].max()), 1)]
                e = els[gid]
                poly = None
                if kind == "room":
                    geoms = [Polygon(p2[t]).buffer(0) for t in f if abs(_cr(p2[t[1]] - p2[t[0]], p2[t[2]] - p2[t[0]])) > 1e-6]
                    u = unary_union(geoms)
                    if u.geom_type == "MultiPolygon":
                        u = max(u.geoms, key=lambda g: g.area)
                    if not u.is_empty:
                        u = u.simplify(0.5)
                        poly = [[round(x, 1), round(y, 1)] for x, y in u.exterior.coords]
                        dr.line([tuple(c) for c in poly], fill=(90, 120, 170), width=2)
                counter[kind] += 1
                props = {k: v_ for k, v_ in e["quantities"].items()
                         if k in ("width_m", "height_m", "length_m", "area_m2", "volume_m3", "net_floor_area_m2")}
                props.update({"ifc_class": e["ifc_class"], "storey": e["storey"]["name"]})
                if kind == "room":
                    props["room_type"] = e["type_name"]
                items.append({"item_id": gid, "kind": kind, "label": e["name"], "bbox_px": bbox, "polygon_px": poly,
                              "props": props, "conf": 1.0, "source": "ifc"})
        # draw room labels
        for it in items:
            if it["kind"] == "room" and it["label"]:
                cx = (it["bbox_px"][0] + it["bbox_px"][2]) / 2; cy = (it["bbox_px"][1] + it["bbox_px"][3]) / 2
                dr.text((cx - 10, cy - 5), str(it["label"]), fill=(40, 60, 100))
        save_page(img, out, n)
        pm = {"doc_id": doc_id, "page": n, "storey": {"name": key[1], "elevation_m": key[0]},
              "image": {"w": W, "h": H},
              "scale": {"m_per_px": 1 / ppm, "method": "ifc", "confidence": 1.0, "native_units": element_data.get("unit_provenance")},
              "origin_offset_m": scene["origin_offset_m"],
              "projection": {"x_px": "(X - x0)*ppm + 40", "y_px": "(Z - z0)*ppm + 40", "x0": float(x0), "z0": float(z0), "ppm": ppm},
              "items": items,
              "provenance": {"models": {}, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "ms": 0,
                             "note": "plan image generated from IFC geometry (generated for demo)"}}
        (out / f"planmap-{n}.json").write_text(json.dumps(pm))
        pages.append({"page": n, "w": W, "h": H, "dpi": None, "words": 0, "storey": key[1], "elevation_m": key[0]})
    if not pages:  # no walls/rooms (plumbing, HVAC): one overview page instead of none
        return overview_page(doc_id, art)
    (out / "pages.json").write_text(json.dumps({"doc_id": doc_id, "source": "ifc-storeys", "pages": pages}, indent=1))
    return len(pages)


def overview_page(doc_id: str, art: Path) -> int:
    """Models with no walls/rooms (plumbing, HVAC): one top-down overview from element bounding boxes, so the
    document has a page-1 preview. Pipes blue, fittings orange, fixtures green, the rest grey."""
    out = art / doc_id
    els = json.loads((out / "elements.json").read_text())["elements"]
    boxes = [(e["kind"], e["bbox_m"]) for e in els if e.get("bbox_m") and e["kind"] != "site"]
    if not boxes:
        return 0
    x0 = min(b[0][0] for _, b in boxes); x1 = max(b[1][0] for _, b in boxes)
    z0 = min(b[0][2] for _, b in boxes); z1 = max(b[1][2] for _, b in boxes)
    ppm = max(2.0, min(80.0, (LONG_SIDE - 2 * MARGIN) / max(x1 - x0, z1 - z0, 1e-6)))
    W = int((x1 - x0) * ppm) + 2 * MARGIN
    H = int((z1 - z0) * ppm) + 2 * MARGIN
    img = Image.new("RGB", (W, H), "white")
    dr = ImageDraw.Draw(img)
    col = {"pipe": (30, 110, 200), "pipe_fitting": (230, 140, 40), "sanitary": (40, 160, 90)}
    for kind in ("equipment", "pipe_fitting", "sanitary", "pipe"):
        for k, b in boxes:
            if k == kind or (kind == "equipment" and k not in col):
                a = ((b[0][0] - x0) * ppm + MARGIN, (b[0][2] - z0) * ppm + MARGIN)
                c = ((b[1][0] - x0) * ppm + MARGIN, (b[1][2] - z0) * ppm + MARGIN)
                dr.rectangle([a, (max(c[0], a[0] + 2), max(c[1], a[1] + 2))], fill=col.get(k, (150, 150, 150)))
    save_page(img, out, 1)
    (out / "pages.json").write_text(json.dumps({"doc_id": doc_id, "source": "ifc-overview",
        "pages": [{"page": 1, "w": W, "h": H, "dpi": None, "words": 0, "storey": None, "elevation_m": None}]}, indent=1))
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", default=str(REPO / "artifacts"))
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    art = Path(a.artifacts)
    for l in open(art / "registry.jsonl"):
        d = json.loads(l)
        if "ifc" not in d["formats"] or (a.only and d["doc_id"] not in a.only):
            continue
        if not (art / d["doc_id"] / "scene.glb").exists():
            continue
        try:
            print(d["doc_id"], process(d["doc_id"], art), "storey pages", flush=True)
        except Exception as e:  # noqa: BLE001
            print(d["doc_id"], "error", repr(e), flush=True)


if __name__ == "__main__":
    main()
