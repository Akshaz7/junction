"""Validate an IfcConvert GLB against its elements.json.

Reports file size, mesh/node/primitive/triangle counts, world bbox, whether node
names (GUIDs) map back to IFC elements, what metadata (extras/materials) survived,
and whether the GLB bbox agrees with the IFC-derived bboxes.
Usage: python validate_glb.py model.glb elements.json
"""
import collections
import json
import os
import sys

import numpy as np
import trimesh
from pygltflib import GLTF2


def main(glb, elements_path):
    with open(elements_path) as fh:
        idx = json.load(fh)
    els = {e["guid"]: e for e in idx["elements"]}
    geo_guids = {g for g, e in els.items() if e["has_geometry"] and e["category"] not in ("opening", "space")}

    g = GLTF2().load(glb)
    scene = trimesh.load(glb, force="scene")

    node_names = [n.name for n in g.nodes if n.mesh is not None]
    prims = sum(len(m.primitives) for m in g.meshes)
    tris = sum(len(geom.faces) for geom in scene.geometry.values())
    extras = sum(1 for n in g.nodes if n.extras) + sum(1 for m in g.meshes if m.extras)
    mats = [m.name for m in g.materials]

    matched = [n for n in node_names if n in els]
    unmatched = [n for n in node_names if n not in els]
    missing = sorted(geo_guids - set(node_names))
    dupes = [n for n, c in collections.Counter(node_names).items() if c > 1]

    lo, hi = scene.bounds
    # IFC bbox (Z-up) -> glTF Y-up: (x, y, z) -> (x, z, -y)
    ifc = [e for e in els.values() if e["has_geometry"] and e["category"] not in ("opening", "space")]
    imin = np.min([e["bbox_min"] for e in ifc], 0)
    imax = np.max([e["bbox_max"] for e in ifc], 0)
    ifc_lo = np.array([imin[0], imin[2], -imax[1]])
    ifc_hi = np.array([imax[0], imax[2], -imin[1]])
    bbox_err = float(max(np.abs(lo - ifc_lo).max(), np.abs(hi - ifc_hi).max()))

    report = {
        "glb": glb,
        "file_size_kb": round(os.path.getsize(glb) / 1024, 1),
        "gltf_meshes": len(g.meshes),
        "mesh_nodes": len(node_names),
        "primitives": prims,
        "triangles": int(tris),
        "materials": len(mats),
        "material_names_sample": mats[:8],
        "bbox_min_yup": np.round(lo, 3).tolist(),
        "bbox_max_yup": np.round(hi, 3).tolist(),
        "size_m": np.round(hi - lo, 3).tolist(),
        "bbox_vs_ifc_max_err_m": round(bbox_err, 4),
        "nodes_matching_ifc_guid": f"{len(matched)}/{len(node_names)}",
        "unmatched_node_names": unmatched[:10],
        "duplicate_node_names": dupes[:10],
        "ifc_geom_elements_missing_from_glb": len(missing),
        "missing_sample": [(els[m]["ifc_class"], els[m]["name"]) for m in missing[:10]],
        "nodes_or_meshes_with_extras": extras,
        "glb_class_breakdown": dict(collections.Counter(els[n]["ifc_class"] for n in matched).most_common()),
    }
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
