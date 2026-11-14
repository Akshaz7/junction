"""D-06: IFC -> scene.glb (recentred) + elements.json + scene.json (CONTRACT 5.5).

Usage: uv run python -m pipeline.ifc_scene [--root DATASET_ROOT] [--artifacts DIR] [--only DOC_ID ...]

Boxes come from the GLB nodes (POSITION accessor min/max x node matrix): no second geometry pass.
"""
import argparse
import hashlib
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element as uel
import ifcopenshell.util.unit as uunit
import numpy as np
from pygltflib import GLTF2

REPO = Path(__file__).resolve().parent.parent
IFC_CONVERT = REPO / "tools" / "IfcConvert"
HEAVY = REPO / "scripts" / "heavy.sh"

# (IFC class, kind) checked in order with is_a(). Kinds follow CONTRACT 5.4 where one exists.
KINDS = [
    ("IfcWall", "wall"), ("IfcCurtainWall", "curtain_wall"), ("IfcDoor", "door"), ("IfcWindow", "window"),
    ("IfcSlab", "slab"), ("IfcRoof", "roof"), ("IfcStair", "stairs"), ("IfcStairFlight", "stairs"),
    ("IfcRamp", "ramp"), ("IfcRampFlight", "ramp"), ("IfcRailing", "railing"), ("IfcColumn", "column"),
    ("IfcBeam", "beam"), ("IfcMember", "member"), ("IfcPlate", "plate"), ("IfcCovering", "covering"),
    ("IfcFooting", "footing"), ("IfcPile", "pile"), ("IfcFurnishingElement", "furniture"),
    ("IfcPipeSegment", "pipe"), ("IfcPipeFitting", "pipe_fitting"), ("IfcDuctSegment", "duct"),
    ("IfcDuctFitting", "duct_fitting"), ("IfcFlowTerminal", "terminal"), ("IfcFlowController", "valve_damper"),
    ("IfcFlowMovingDevice", "pump_fan"), ("IfcEnergyConversionDevice", "equipment"),
    ("IfcDistributionElement", "mep_other"), ("IfcBuildingElementProxy", "proxy"),
    ("IfcMechanicalFastener", "fastener"), ("IfcFastener", "fastener"), ("IfcDiscreteAccessory", "accessory"),
    ("IfcSpace", "room"), ("IfcSite", "site"),
]
TYPE_KINDS = [
    ("IfcPipeSegmentType", "pipe"), ("IfcPipeFittingType", "pipe_fitting"), ("IfcDuctSegmentType", "duct"),
    ("IfcDuctFittingType", "duct_fitting"), ("IfcCableCarrierSegmentType", "cable_tray"),
    ("IfcCableSegmentType", "cable"), ("IfcValveType", "valve"), ("IfcDamperType", "damper"),
    ("IfcSanitaryTerminalType", "sanitary"), ("IfcAirTerminalType", "air_terminal"),
    ("IfcLightFixtureType", "light"), ("IfcPumpType", "pump"), ("IfcFanType", "fan"), ("IfcTankType", "tank"),
]
# Quantity name (lowercase) -> (key in `quantities`, dimension). Qto_*BaseQuantities names, IFC2x3 and IFC4.
QMAP = {
    "width": ("width_m", 1), "overallwidth": ("width_m", 1), "height": ("height_m", 1),
    "overallheight": ("height_m", 1), "length": ("length_m", 1), "perimeter": ("perimeter_m", 1),
    "depth": ("depth_m", 1), "thickness": ("thickness_m", 1),
    "netfloorarea": ("net_floor_area_m2", 2), "grossfloorarea": ("gross_floor_area_m2", 2),
    "netarea": ("net_area_m2", 2), "grossarea": ("gross_area_m2", 2),
    "netsidearea": ("net_side_area_m2", 2), "grosssidearea": ("gross_side_area_m2", 2),
    "netsurfacearea": ("net_surface_area_m2", 2), "grosssurfacearea": ("gross_surface_area_m2", 2),
    "grossfootprintarea": ("gross_footprint_area_m2", 2), "netfootprintarea": ("net_footprint_area_m2", 2),
    "area": ("area_m2", 2), "crosssectionarea": ("cross_section_area_m2", 2),
    "netvolume": ("net_volume_m3", 3), "grossvolume": ("gross_volume_m3", 3), "volume": ("volume_m3", 3),
}
VALUE_ATTR = {"IfcQuantityLength": "LengthValue", "IfcQuantityArea": "AreaValue", "IfcQuantityVolume": "VolumeValue"}


def kind_of(el):
    typ = uel.get_type(el)
    if typ is not None and typ.is_a("IfcDistributionElementType"):
        for cls, k in TYPE_KINDS:
            if typ.is_a(cls):
                return k
    for cls, k in KINDS:
        if el.is_a(cls):
            return k
    return "other"


CONVERT_TIMEOUT_S = 1200


def usd_name(item_id: str) -> str:
    return "i_" + hashlib.sha1(item_id.encode()).hexdigest()[:16]


def storey_of(el):
    seen, cur = set(), el
    while cur is not None and cur.id() not in seen:
        seen.add(cur.id())
        if cur.is_a("IfcBuildingStorey"):
            return cur
        nxt = uel.get_container(cur) or uel.get_aggregate(cur)
        if nxt is None and cur.is_a("IfcOpeningElement"):
            nxt = next((r.RelatingBuildingElement for r in cur.VoidsElements), None)
        if nxt is None and cur.is_a("IfcElement"):
            nxt = next((r.RelatingOpeningElement for r in (getattr(cur, "FillsVoids", None) or [])), None)
        cur = nxt
    return None


def quantities_of(el, scale):
    """Qto values from IfcElementQuantity (occurrence first, then type). Metres / m2 / m3."""
    out = {}
    defs = [d for r in (el.IsDefinedBy or []) if r.is_a("IfcRelDefinesByProperties") for d in [r.RelatingPropertyDefinition]]
    typ = uel.get_type(el)
    if typ is not None:
        defs += list(getattr(typ, "HasPropertySets", None) or [])
    defs.sort(key=lambda d: not (d.Name or "").startswith("Qto_"))  # Qto_ sets win
    for d in defs:
        if not d.is_a("IfcElementQuantity"):
            continue
        for q in d.Quantities or []:
            attr = VALUE_ATTR.get(q.is_a())
            m = QMAP.get((q.Name or "").lower().replace(" ", ""))
            if not attr or not m:
                continue
            v = getattr(q, attr, None)
            if v is None:
                continue
            key, dim = m
            if key not in out:
                out[key] = round(float(v) * scale ** dim, 5)
    # Generic aliases the solvers look for
    if "area_m2" not in out:
        a = out.get("net_floor_area_m2", out.get("gross_floor_area_m2", out.get("net_area_m2", out.get("gross_area_m2"))))
        if a is not None:
            out["area_m2"] = a
    if "volume_m3" not in out:
        v = out.get("net_volume_m3", out.get("gross_volume_m3"))
        if v is not None:
            out["volume_m3"] = v
    return out


def attr_dims(el, scale):
    """Door/window OverallWidth/Height attributes (IFC attributes, not Qtos)."""
    out = {}
    if el.is_a("IfcDoor") or el.is_a("IfcWindow"):
        for a, k in (("OverallWidth", "width_m"), ("OverallHeight", "height_m")):
            v = getattr(el, a, None)
            if v:
                out[k] = round(float(v) * scale, 5)
    return out


def props_of(el):
    p = {}
    ps = uel.get_psets(el)
    for name, vals in ps.items():
        for k, v in vals.items():
            if k == "IsExternal" and "is_external" not in p and v is not None:
                p["is_external"] = bool(v)
            if k == "FireRating" and v:
                p.setdefault("fire_rating", v)
    mat = uel.get_material(el)
    if mat is not None:
        try:
            if mat.is_a("IfcMaterial"):
                p["material"] = mat.Name
            elif mat.is_a("IfcMaterialLayerSet"):
                p["material"] = "; ".join(l.Material.Name for l in mat.MaterialLayers if l.Material)
            elif mat.is_a("IfcMaterialLayerSetUsage"):
                p["material"] = "; ".join(l.Material.Name for l in mat.ForLayerSet.MaterialLayers if l.Material)
            elif mat.is_a("IfcMaterialList"):
                p["material"] = "; ".join(m.Name for m in mat.Materials)
            elif hasattr(mat, "Name"):
                p["material"] = mat.Name
        except Exception:
            pass
    return p


def convert(ifc: Path, raw_glb: Path):
    raw_glb.parent.mkdir(parents=True, exist_ok=True)
    raw_glb.unlink(missing_ok=True)  # IfcConvert asks before overwriting
    big = ifc.stat().st_size > 50e6
    env = {"HEAVY_SLOTS": "1"} if big else {}
    import os
    cmd = [str(HEAVY), str(IFC_CONVERT), "--exclude", "entities", "IfcOpeningElement", "-j", "4",
           "--use-element-guids", "--y-up", str(ifc), str(raw_glb)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            stdin=subprocess.DEVNULL, env={**os.environ, **env}, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=CONVERT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)  # heavy.sh + IfcConvert
        proc.communicate()
        raw_glb.unlink(missing_ok=True)
        raise RuntimeError(f"IfcConvert timed out after {CONVERT_TIMEOUT_S} s")
    (raw_glb.parent / "convert.log").write_text(out or "")
    if not raw_glb.exists():
        raise RuntimeError("IfcConvert produced no GLB; see tmp/convert.log")


def node_boxes(g: GLTF2):
    """World bbox per mesh node from accessor min/max and the node matrix."""
    mesh_box = {}
    for mi, m in enumerate(g.meshes):
        los, his = [], []
        for pr in m.primitives:
            a = g.accessors[pr.attributes.POSITION]
            los.append(a.min); his.append(a.max)
        mesh_box[mi] = (np.min(los, 0), np.max(his, 0))
    boxes = {}
    for ni, n in enumerate(g.nodes):
        if n.mesh is None:
            continue
        lo, hi = mesh_box[n.mesh]
        M = np.array(n.matrix or np.eye(4).flatten().tolist()).reshape(4, 4).T  # column-major
        corners = np.array([[x, y, z, 1] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        w = (M @ corners.T).T[:, :3]
        boxes[ni] = (w.min(0), w.max(0))
    return boxes


def process(ifc: Path, doc: dict, out_dir: Path):
    t0 = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / "tmp" / "raw.glb"
    convert(ifc, raw)
    g = GLTF2().load(str(raw))
    boxes = node_boxes(g)
    if not boxes:
        raise RuntimeError("GLB has no mesh nodes")
    # recentre X/Z on the bbox centre of the whole scene; Y untouched
    lo = np.min([b[0] for b in boxes.values()], 0)
    hi = np.max([b[1] for b in boxes.values()], 0)
    off = np.array([(lo[0] + hi[0]) / 2, 0.0, (lo[2] + hi[2]) / 2])
    for n in g.nodes:
        if n.mesh is None:
            continue
        m = n.matrix or np.eye(4).flatten().tolist()
        m = list(m)
        m[12] -= off[0]; m[14] -= off[2]
        n.matrix = m
    boxes = {k: (b[0] - off, b[1] - off) for k, b in boxes.items()}
    name_to_box = {}
    for ni, b in boxes.items():
        name_to_box[g.nodes[ni].name] = b

    f = ifcopenshell.open(str(ifc))
    scale = uunit.calculate_unit_scale(f)
    targets = [e for e in list(f.by_type("IfcElement")) + list(f.by_type("IfcSpace")) + list(f.by_type("IfcSite")) if not e.is_a("IfcOpeningElement")]
    by_guid = {e.GlobalId: e for e in targets}
    kinds = {e.GlobalId: kind_of(e) for e in targets}
    for n in g.nodes:  # viewers can hide rooms / pick kinds without a lookup
        if n.mesh is not None and n.name in kinds:
            n.extras = {"kind": kinds[n.name]}
    g.save(str(out_dir / "scene.glb"))

    # roll up aggregates without own geometry from their parts
    boxes_m = dict(name_to_box)
    src = {k: "glb" for k in boxes_m}

    def rolled(e, depth=0):
        if e.GlobalId in boxes_m or depth > 5:
            return boxes_m.get(e.GlobalId)
        parts = [rolled(p, depth + 1) for p in uel.get_decomposition(e) if getattr(p, "GlobalId", None) in by_guid]
        parts = [p for p in parts if p]
        if not parts:
            return None
        b = (np.min([p[0] for p in parts], 0), np.max([p[1] for p in parts], 0))
        boxes_m[e.GlobalId] = b; src[e.GlobalId] = "parts"
        return b

    for e in targets:
        rolled(e)

    elements, items, storeys = [], {}, {}
    for e in targets:
        gid = e.GlobalId
        st = storey_of(e)
        typ = uel.get_type(e)
        b = boxes_m.get(gid)
        bbox = [np.round(b[0], 4).tolist(), np.round(b[1], 4).tolist()] if b else None
        q = {}
        qsrc = {}
        for k, v in attr_dims(e, scale).items():
            q[k] = v; qsrc[k] = "attribute"
        for k, v in quantities_of(e, scale).items():
            q[k] = v; qsrc[k] = "qto"  # Qto wins over attribute
        k_ = kinds[gid]
        if b is not None and src.get(gid) == "glb":  # fill gaps from geometry
            ext = b[1] - b[0]
            if k_ in ("door", "window"):
                if "width_m" not in q: q["width_m"] = round(float(max(ext[0], ext[2])), 4); qsrc["width_m"] = "bbox"
                if "height_m" not in q: q["height_m"] = round(float(ext[1]), 4); qsrc["height_m"] = "bbox"
            elif k_ == "wall":
                if "length_m" not in q: q["length_m"] = round(float(max(ext[0], ext[2])), 4); qsrc["length_m"] = "bbox"
                if "height_m" not in q: q["height_m"] = round(float(ext[1]), 4); qsrc["height_m"] = "bbox"
        entry = {
            "item_id": gid, "name": e.Name, "ifc_class": e.is_a(), "kind": k_,
            "predefined_type": uel.get_predefined_type(e), "type_name": typ.Name if typ else None,
            "storey": ({"name": st.Name, "elevation_m": round((st.Elevation or 0) * scale, 4)} if st is not None else None),
            "bbox_m": bbox, "quantities": q, "quantity_source": qsrc, "props": props_of(e),
            "bbox_source": src.get(gid),
        }
        elements.append(entry)
        if gid in name_to_box:
            items[gid] = {"node": gid, "usd_name": usd_name(gid), "bbox_m": bbox,
                          "storey": entry["storey"]["name"] if entry["storey"] else None, "kind": k_}
    for s in f.by_type("IfcBuildingStorey"):
        storeys[s.GlobalId] = {"name": s.Name, "elevation_m": round((s.Elevation or 0) * scale, 4)}
    storey_list = sorted(storeys.values(), key=lambda s: s["elevation_m"])

    from pipeline.ifc_props import building_meta, enrich_elements
    enrich_elements(f, elements)
    (out_dir / "elements.json").write_text(json.dumps(
        {"doc_id": doc["doc_id"], "version": 2, "schema": f.schema, "units": "m", "building": building_meta(f),
         "coords": "recentred in X/Z by origin_offset_m, Y-up (glTF), Y keeps real elevation",
         "storeys": storey_list, "elements": elements}, indent=1))
    lic = (doc.get("licence") or "")
    scene = {"doc_id": doc["doc_id"], "glb": "scene.glb", "usdz": None, "units": "m", "up": "Y",
             "origin_offset_m": [round(float(x), 5) for x in off], "storeys": storey_list,
             "plan_image": None, "items": items,
             "publishable": not (lic.startswith("CC-BY-ND") or lic.startswith("GPL"))}
    (out_dir / "scene.json").write_text(json.dumps(scene, indent=1))
    return {"doc_id": doc["doc_id"], "elements": len(elements), "nodes": len(items), "storeys": len(storey_list),
            "s": round(time.time() - t0, 1)}


def main():
    from pipeline.registry import REPO as R
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(R / "data" / "junction-dataset-preview"))
    ap.add_argument("--artifacts", default=str(R / "artifacts"))
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    art = Path(a.artifacts)
    docs = [json.loads(l) for l in open(art / "registry.jsonl")]
    docs = [d for d in docs if "ifc" in d["formats"] and (not a.only or d["doc_id"] in a.only)]
    docs.sort(key=lambda d: (Path(a.root, d["files"]["ifc"]).stat().st_size))  # small first, one at a time
    for d in docs:
        try:
            print(json.dumps(process(Path(a.root) / d["files"]["ifc"], d, art / d["doc_id"])), flush=True)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"doc_id": d["doc_id"], "error": repr(e)}), flush=True)


if __name__ == "__main__":
    main()
