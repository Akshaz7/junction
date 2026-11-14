"""D-10: scene.glb + scene.json -> scene.usdz (ARKit-compliant), prims named by usd_name.

Every item gets /Root/<usd_name> (Xform) holding its mesh parts (world-space vertices, metres, Y-up).
Materials are UsdPreviewSurface, shared per colour; the plan_floor quad keeps its plan texture.
CLI: python -m pipeline.usdz [--only DOC_ID...] [--force]
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import numpy as np
import trimesh
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdUtils, Vt

REPO = Path(__file__).resolve().parent.parent
KIND_RGB = {"wall": (0.69, 0.69, 0.71), "door": (0.78, 0.51, 0.24), "window": (0.35, 0.59, 0.84),
            "room": (0.63, 0.75, 0.88), "column": (0.2, 0.2, 0.2), "slab": (0.75, 0.75, 0.75),
            "stairs": (0.6, 0.55, 0.5)}


def _base_rgb(geom, kind):
    try:
        mat = getattr(geom.visual, "material", None)
        c = getattr(mat, "baseColorFactor", None)
        if c is not None:
            return tuple(round(float(v) / 255, 3) for v in c[:3]), float(c[3]) / 255
        vc = getattr(geom.visual, "vertex_colors", None)
        if geom.visual.kind == "vertex" and vc is not None and len(vc):
            return tuple(round(float(v) / 255, 3) for v in vc[0][:3]), float(vc[0][3]) / 255
    except Exception:
        pass
    return KIND_RGB.get(kind, (0.8, 0.8, 0.8)), 1.0


class Builder:
    def __init__(self, stage, tmp: Path):
        self.stage, self.tmp, self.mats = stage, tmp, {}

    def material(self, rgb, alpha, tex=None):
        key = (tuple(rgb), round(alpha, 2), tex)
        if key in self.mats:
            return self.mats[key]
        name = f"m{len(self.mats)}"
        m = UsdShade.Material.Define(self.stage, f"/Root/Materials/{name}")
        sh = UsdShade.Shader.Define(self.stage, f"/Root/Materials/{name}/pbr")
        sh.CreateIdAttr("UsdPreviewSurface")
        sh.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.8)
        sh.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
        if alpha < 0.99:
            sh.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(alpha)
        if tex:
            st = UsdShade.Shader.Define(self.stage, f"/Root/Materials/{name}/st")
            st.CreateIdAttr("UsdPrimvarReader_float2")
            st.CreateInput("varname", Sdf.ValueTypeNames.String).Set("st")
            st.CreateOutput("result", Sdf.ValueTypeNames.Float2)
            t = UsdShade.Shader.Define(self.stage, f"/Root/Materials/{name}/tex")
            t.CreateIdAttr("UsdUVTexture")
            t.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(tex))
            t.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(st.ConnectableAPI(), "result")
            t.CreateInput("wrapS", Sdf.ValueTypeNames.Token).Set("clamp")
            t.CreateInput("wrapT", Sdf.ValueTypeNames.Token).Set("clamp")
            t.CreateOutput("rgb", Sdf.ValueTypeNames.Float3)
            sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(t.ConnectableAPI(), "rgb")
        else:
            sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*rgb))
        sh.CreateOutput("surface", Sdf.ValueTypeNames.Token)
        m.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
        self.mats[key] = m
        return m

    def mesh(self, parent: str, name: str, verts, faces, rgb, alpha, uv=None, tex=None):
        mp = UsdGeom.Mesh.Define(self.stage, f"{parent}/{name}")
        tri = np.asarray(faces)
        v = np.asarray(verts, float)
        mp.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(v.astype(np.float32)))
        mp.CreateFaceVertexCountsAttr(Vt.IntArray.FromNumpy(np.full(len(tri), 3, np.int32)))
        mp.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(tri.reshape(-1).astype(np.int32)))
        a, b, c = v[tri[:, 0]], v[tri[:, 1]], v[tri[:, 2]]
        n = np.cross(b - a, c - a)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        mp.CreateNormalsAttr(Vt.Vec3fArray.FromNumpy(np.repeat(n, 3, axis=0).astype(np.float32)))
        mp.SetNormalsInterpolation(UsdGeom.Tokens.faceVarying)
        mp.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
        mp.CreateDoubleSidedAttr(True)
        ext = UsdGeom.Boundable.ComputeExtentFromPlugins(mp, 0)
        if ext:
            mp.CreateExtentAttr(ext)
        mp.CreateDisplayColorAttr([Gf.Vec3f(*rgb)])
        if uv is not None:
            pv = UsdGeom.PrimvarsAPI(mp).CreatePrimvar("st", Sdf.ValueTypeNames.TexCoord2fArray,
                                                       UsdGeom.Tokens.vertex)
            pv.Set(Vt.Vec2fArray.FromNumpy(np.asarray(uv, np.float32)))
        UsdShade.MaterialBindingAPI.Apply(mp.GetPrim()).Bind(self.material(rgb, alpha, tex))
        return mp


def process(doc_id: str, art: Path) -> dict:
    sj = json.loads((art / "scene.json").read_text())
    scene = trimesh.load(art / "scene.glb", process=False)
    node_to_item = {v["node"]: (k, v) for k, v in sj["items"].items()}
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        usdc = d / "scene.usdc"
        stage = Usd.Stage.CreateNew(str(usdc))
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        root = UsdGeom.Xform.Define(stage, "/Root")
        stage.SetDefaultPrim(root.GetPrim())
        b = Builder(stage, d)
        made, parts_n = set(), 0
        for node in scene.graph.nodes_geometry:
            T, gname = scene.graph[node]
            g = scene.geometry[gname]
            if len(g.faces) == 0:
                continue
            base = node
            if base not in node_to_item and "_" in base and base.rsplit("_", 1)[0] in node_to_item:
                base = base.rsplit("_", 1)[0]  # trimesh splits multi-primitive nodes into <guid>_<hash>
            verts = trimesh.transformations.transform_points(g.vertices, T)
            if base in node_to_item:
                iid, info = node_to_item[base]
                pname = info["usd_name"]
                kind = info["kind"]
            elif base == "plan_floor":
                iid, pname, kind = None, "plan_floor", "floor"
            else:
                continue  # node not described by scene.json (should not happen)
            parent = f"/Root/{pname}"
            if pname not in made:
                UsdGeom.Xform.Define(stage, parent)
                made.add(pname)
            rgb, alpha = _base_rgb(g, kind)
            uv = tex = None
            if kind == "floor":
                img = g.visual.material.baseColorTexture if hasattr(g.visual, "material") else None
                if img is not None:
                    img.convert("RGB").save(d / "plan.png")
                    tex = "plan.png"
                    uv = np.asarray(g.visual.uv)
                    rgb, alpha = (1.0, 1.0, 1.0), 1.0
            b.mesh(parent, f"p{parts_n}", verts, g.faces, rgb, alpha, uv, tex)
            parts_n += 1
        stage.GetRootLayer().Save()
        out = art / "scene.usdz"
        out.unlink(missing_ok=True)
        ok = UsdUtils.CreateNewARKitUsdzPackage(Sdf.AssetPath(str(usdc)), str(out))
        if not ok:
            raise RuntimeError("usdz packaging failed")
    sj["usdz"] = "scene.usdz"
    (art / "scene.json").write_text(json.dumps(sj, indent=1))
    return {"prims": len(made), "parts": parts_n, "mb": round(out.stat().st_size / 1e6, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    for art in sorted((REPO / "artifacts").glob("*__*")):
        if a.only and art.name not in a.only:
            continue
        if not (art / "scene.glb").exists():
            continue
        sj = json.loads((art / "scene.json").read_text())
        if (art / "scene.usdz").exists() and not a.force and sj.get("usdz"):
            continue
        try:
            print(art.name, process(art.name, art))
        except Exception as ex:
            print(art.name, "FAILED", repr(ex))


if __name__ == "__main__":
    main()
