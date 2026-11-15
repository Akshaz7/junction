"""Rebuild real plan maps in an isolated directory and check AR opening prims.

Run via scripts/heavy.sh python -m pipeline.tests.validate_usdz_openings
    --artifacts artifacts --output results/final/AWAISOPEN --docs <ids...>
Only summary JSON is intended for git; source drawings and rebuilt scenes stay local.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import trimesh
from pxr import Usd, UsdGeom

from pipeline import extrude, usdz


def validate(doc_id: str, artifacts: Path, output: Path) -> dict:
    source = artifacts / doc_id
    target = output / "scenes" / doc_id
    if target.exists():
        raise FileExistsError(f"Use a fresh output directory: {target}")
    target.mkdir(parents=True)
    inputs = sorted({source / "doc.json", *source.glob("planmap-*.json"), *source.glob("page-[0-9]*.png")})
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    for p in inputs:
        shutil.copyfile(p, target / p.name)
    meta = json.loads((target / "doc.json").read_text())
    extrude.process(doc_id, target, raster_walls=meta.get("kind") == "raster")
    manifest = json.loads((target / "scene.json").read_text())
    scene = trimesh.load_scene(target / "scene.glb", process=False)
    by_node = {v["node"]: iid for iid, v in manifest["items"].items()}
    old_mapped = set()
    for node in scene.graph.nodes_geometry:
        base = node
        if base not in by_node and "_" in base and base.rsplit("_", 1)[0] in by_node:
            base = base.rsplit("_", 1)[0]
        if base in by_node:
            old_mapped.add(by_node[base])
    built = usdz.process(doc_id, target)
    stage = Usd.Stage.Open(str(target / "scene.usdz"))
    counts = {}
    for kind in ("door", "window"):
        expected = {iid: it for iid, it in manifest["items"].items() if it["kind"] == kind}
        assert expected, f"{doc_id}: no {kind} geometry to test"
        for iid, info in expected.items():
            prim = stage.GetPrimAtPath("/Root/" + info["usd_name"])
            assert prim and prim.IsA(UsdGeom.Xform), (doc_id, iid)
            meshes = [p for p in prim.GetChildren() if p.IsA(UsdGeom.Mesh)]
            assert meshes, (doc_id, iid, "empty prim")
            points = np.concatenate([np.asarray(UsdGeom.Mesh(p).GetPointsAttr().Get()) for p in meshes])
            np.testing.assert_allclose([points.min(axis=0), points.max(axis=0)], info["bbox_m"], atol=.0011)
        counts[kind] = {"expected": len(expected), "before": len(expected.keys() & old_mapped),
                        "after": len(expected), "item_ids": sorted(expected)}
    assert hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    return {"doc_id": doc_id, "source_kind": meta.get("kind"), "source_unchanged": True,
            "input_sha256": hashes, "counts": counts, "built": built}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--docs", nargs="+", required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.artifacts.resolve()):
        parser.error("Output must be outside the shared artifacts directory")
    results = []
    for doc_id in args.docs:
        result = validate(doc_id, args.artifacts, args.output)
        results.append(result)
        print(json.dumps({"doc_id": doc_id, "counts": {k: {a: b for a, b in v.items() if a != "item_ids"}
                                                       for k, v in result["counts"].items()}}), flush=True)
    (args.output / "usdz_validation.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
