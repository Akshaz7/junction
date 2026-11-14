#!/usr/bin/env python3
"""Make a tiny fixture USDZ for iOS tests: 5 box prims named by usd_name (CONTRACT 5.1).
Usage: uv run --no-project --with usd-core python scripts/make_ios_fixture.py <out_dir>"""
import hashlib, json, sys, tempfile
from pathlib import Path
from pxr import Usd, UsdGeom, UsdUtils, Gf, Sdf

def usd_name(item_id: str) -> str:
    return "i_" + hashlib.sha1(item_id.encode()).hexdigest()[:16]

ITEMS = {  # item_id: (kind, center xyz m, size xyz m)
    "wall-001": ("wall", (0, 1.35, -2), (6, 2.7, 0.2)),
    "wall-002": ("wall", (-3, 1.35, 0), (0.2, 2.7, 4)),
    "door-001": ("door", (1, 1.05, -2), (0.9, 2.1, 0.25)),
    "window-001": ("window", (-1.5, 1.5, -2), (1.2, 1.2, 0.25)),
    "window-002": ("window", (-3, 1.5, 1), (0.25, 1.2, 1.2)),
}

def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        usdc = Path(d) / "fixture.usdc"
        stage = Usd.Stage.CreateNew(str(usdc))
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        root = UsdGeom.Xform.Define(stage, "/Root")
        stage.SetDefaultPrim(root.GetPrim())
        items = {}
        for item_id, (kind, c, s) in ITEMS.items():
            name = usd_name(item_id)
            x = UsdGeom.Xform.Define(stage, f"/Root/{name}")
            x.AddTranslateOp().Set(Gf.Vec3d(*c))
            x.AddScaleOp().Set(Gf.Vec3f(*s))
            cube = UsdGeom.Cube.Define(stage, f"/Root/{name}/geom")
            cube.GetSizeAttr().Set(1.0)
            cube.GetDisplayColorAttr().Set([Gf.Vec3f(0.8, 0.8, 0.8)])
            items[item_id] = {"node": item_id, "usd_name": name, "kind": kind, "storey": None,
                              "bbox_m": [[c[i] - s[i] / 2 for i in range(3)], [c[i] + s[i] / 2 for i in range(3)]]}
        stage.GetRootLayer().Save()
        ok = UsdUtils.CreateNewARKitUsdzPackage(Sdf.AssetPath(str(usdc)), str(out / "fixture.usdz"))
        assert ok, "usdz packaging failed"
    scene = {"doc_id": "fixture__ios", "usdz": "fixture.usdz", "units": "m", "up": "Y",
             "origin_offset_m": [0, 0, 0], "storeys": [], "items": items,
             "note": "generated for demo: synthetic test fixture"}
    (out / "fixture.scene.json").write_text(json.dumps(scene, indent=2))
    print("wrote", out / "fixture.usdz", "with", len(items), "prims")

if __name__ == "__main__":
    main(Path(sys.argv[1]))
