"""D-06: IFC -> scene.glb (recentred) + elements.json + scene.json (CONTRACT 5.5).

Usage: uv run python -m pipeline.ifc_scene [--root DATASET_ROOT] [--artifacts DIR] [--only DOC_ID ...]

Boxes come from the GLB nodes (POSITION accessor min/max x node matrix): no second geometry pass.
"""
import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

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
    ("IfcReinforcingBar", "rebar"), ("IfcReinforcingMesh", "reinforcing_mesh"), ("IfcTendon", "tendon"),
    ("IfcPipeSegment", "pipe"), ("IfcPipeFitting", "pipe_fitting"), ("IfcDuctSegment", "duct"),
    ("IfcDuctFitting", "duct_fitting"), ("IfcFlowTerminal", "terminal"), ("IfcFlowController", "valve_damper"),
    ("IfcFlowMovingDevice", "pump_fan"), ("IfcEnergyConversionDevice", "equipment"),
    ("IfcDistributionElement", "mep_other"), ("IfcBuildingElementProxy", "proxy"),
    ("IfcMechanicalFastener", "fastener"), ("IfcFastener", "fastener"), ("IfcDiscreteAccessory", "accessory"),
    ("IfcSpace", "room"), ("IfcSite", "site"), ("IfcGeographicElement", "site"),
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


def is_site_context(el, kind: str) -> bool:
    """Terrain / landscape around the building, not the building: the IfcSite's own shape (e.g. a terrain block with
    the excavation cut out), IfcGeographicElement (terrain, trees), and proxies placed directly in the site rather
    than in a building or storey. These meshes are left out of scene.glb (the viewer drew them as big translucent
    blocks around the model); their elements.json entries and bboxes stay, with kind "site"."""
    if kind == "site":
        return True
    if kind == "proxy":
        c = uel.get_container(el)
        return c is not None and c.is_a("IfcSite")
    return False


# Never hide more than this share of the mesh nodes as site context: a model that puts its whole building straight
# into the IfcSite (no IfcBuildingStorey) must still show its proxies.
SITE_CONTEXT_MAX_SHARE = 0.5

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
            # IFC area/volume units are independent of length units. A model
            # commonly has millimetres for lengths and square metres for areas;
            # an individual quantity can also override the project unit.
            unit = uunit.get_property_unit(q, el.file, use_cache=True)
            if unit is None or unit.UnitType != {1: "LENGTHUNIT", 2: "AREAUNIT", 3: "VOLUMEUNIT"}[dim]:
                continue  # absent units are unknown, never an implied measurement
            value = float(v) * uunit.get_unit_scale(unit)
            if key not in out and np.isfinite(value):
                out[key] = round(value, 5)
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


def convert_py(ifc: Path, raw_glb: Path):
    """Pure-Python IFC -> GLB (ifcopenshell geometry iterator + trimesh), used where IfcConvert is not available
    (the Linux deploy image). Same contract as IfcConvert --y-up --use-element-guids: node name = GlobalId, metres,
    Y-up, IfcOpeningElement dropped, IfcSpace kept. One mesh per element, coloured by its dominant IFC style.
    Triangles are streamed to disk as float32/uint32 arrays; only the current
    shape and GLB metadata remain in Python memory. One geometry thread by default."""
    from pipeline.ifc_glb import convert as stream_glb
    return stream_glb(ifc, raw_glb)


def convert(ifc: Path, raw_glb: Path):
    import platform
    if not IFC_CONVERT.exists() or platform.system() != "Darwin" or os.environ.get("IFC_CONVERT_PY") == "1":
        return convert_py(ifc, raw_glb)
    raw_glb.parent.mkdir(parents=True, exist_ok=True)
    raw_glb.unlink(missing_ok=True)  # IfcConvert asks before overwriting
    big = ifc.stat().st_size > 50e6
    env = {"HEAVY_SLOTS": "1"} if big else {}
    cmd = [str(IFC_CONVERT), "--exclude", "entities", "IfcOpeningElement", "-j", os.environ.get("IFC_CONVERT_THREADS", "1"),
           "--use-element-guids", "--y-up", str(ifc), str(raw_glb)]
    if os.environ.get("HEAVY_SLOT_HELD") != "1":
        cmd.insert(0, str(HEAVY))
    managed = os.environ.get("INGEST_MANAGED_JOB") == "1"
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            stdin=subprocess.DEVNULL, env={**os.environ, **env}, start_new_session=not managed)
    try:
        out, _ = proc.communicate(timeout=CONVERT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        if managed:
            proc.kill()  # the enclosing ingest watchdog owns the process group
        else:
            os.killpg(proc.pid, signal.SIGKILL)  # heavy.sh + IfcConvert
        proc.communicate()
        raw_glb.unlink(missing_ok=True)
        raise RuntimeError(f"IfcConvert timed out after {CONVERT_TIMEOUT_S} s")
    (raw_glb.parent / "convert.log").write_text(out or "")
    if not raw_glb.exists():
        raise RuntimeError("IfcConvert produced no GLB; see tmp/convert.log")


def node_matrices(g: GLTF2):
    """World transforms, including glTF parent nodes and TRS transforms."""
    def quaternion_matrix(q):
        q = np.asarray(q, dtype=float)
        norm = np.dot(q, q)
        if norm < np.finfo(float).eps:
            return np.eye(4)
        q *= np.sqrt(2. / norm)
        q = np.outer(q, q)
        return np.array([
            [1. - q[2, 2] - q[3, 3], q[1, 2] - q[3, 0], q[1, 3] + q[2, 0], 0.],
            [q[1, 2] + q[3, 0], 1. - q[1, 1] - q[3, 3], q[2, 3] - q[1, 0], 0.],
            [q[1, 3] - q[2, 0], q[2, 3] + q[1, 0], 1. - q[1, 1] - q[2, 2], 0.],
            [0., 0., 0., 1.],
        ])
    parents = {child: i for i, node in enumerate(g.nodes) for child in (node.children or [])}
    world = {}
    visiting = set()

    def matrix(i):
        if i in visiting:
            raise ValueError("The converted scene contains circular node references.")
        if i in world:
            return world[i]
        visiting.add(i)
        node = g.nodes[i]
        if node.matrix:
            local = np.array(node.matrix, dtype=float).reshape(4, 4).T
        else:
            x, y, z, w = node.rotation or [0, 0, 0, 1]
            local = quaternion_matrix([w, x, y, z])
            local[:3, :3] *= np.array(node.scale or [1, 1, 1])
            local[:3, 3] = node.translation or [0, 0, 0]
        world[i] = matrix(parents[i]) @ local if i in parents else local
        visiting.remove(i)
        return world[i]

    for i in range(len(g.nodes)):
        matrix(i)
    return world


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
    transforms = node_matrices(g)
    for ni, n in enumerate(g.nodes):
        if n.mesh is None:
            continue
        lo, hi = mesh_box[n.mesh]
        M = transforms[ni]
        corners = np.array([[x, y, z, 1] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        w = (M @ corners.T).T[:, :3]
        if not np.isfinite(w).all():
            raise ValueError("The converted scene contains invalid geometry coordinates.")
        boxes[ni] = (w.min(0), w.max(0))
    return boxes


def process(ifc: Path, doc: dict, out_dir: Path):
    t0 = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / "tmp" / "raw.glb"
    convert(ifc, raw)
    if (out_dir / "elements.json").is_file():
        from pipeline.ifc_scene_indexed import process as indexed_scene
        return indexed_scene(raw, doc, out_dir, t0)
    g = GLTF2().load(str(raw))
    boxes = node_boxes(g)
    if not boxes:
        raise RuntimeError("GLB has no mesh nodes")
    # recentre X/Z on the bbox centre of the whole scene; Y untouched
    lo = np.min([b[0] for b in boxes.values()], 0)
    hi = np.max([b[1] for b in boxes.values()], 0)
    off = np.array([(lo[0] + hi[0]) / 2, 0.0, (lo[2] + hi[2]) / 2])
    # Translate root nodes once, preserving transforms of child meshes.
    children = {child for node in g.nodes for child in (node.children or [])}
    transforms = node_matrices(g)
    for ni, n in enumerate(g.nodes):
        if ni in children:
            continue
        matrix = transforms[ni].copy()
        matrix[:3, 3] -= off
        n.matrix = matrix.T.flatten().tolist()
        n.translation = n.rotation = n.scale = None
    boxes = {k: (b[0] - off, b[1] - off) for k, b in boxes.items()}
    name_to_box = {}
    for ni, b in boxes.items():
        name_to_box[g.nodes[ni].name] = b

    from pipeline.ifc_index import open_properties, property_quantities_of
    f = open_properties(ifc)
    scale = uunit.calculate_unit_scale(f)
    length_unit_known = uunit.get_project_unit(f, "LENGTHUNIT") is not None
    warnings = [] if length_unit_known else [
        "This IFC does not declare length units. Model sizes use the converter's default and cannot be verified."]
    targets = [e for e in list(f.by_type("IfcElement")) + list(f.by_type("IfcSpace")) + list(f.by_type("IfcSite")) if not e.is_a("IfcOpeningElement")]
    by_guid = {e.GlobalId: e for e in targets}
    kinds = {e.GlobalId: kind_of(e) for e in targets}
    mesh_names = {n.name for n in g.nodes if n.mesh is not None}
    site_ctx = {gid for gid in mesh_names & kinds.keys() if is_site_context(by_guid[gid], kinds[gid])}
    if len(site_ctx) > SITE_CONTEXT_MAX_SHARE * len(mesh_names):
        site_ctx = {gid for gid in site_ctx if kinds[gid] == "site"}  # keep proxies: they are the building here
    if len(site_ctx) == len(mesh_names):
        site_ctx = set()  # a terrain-only model: show it rather than an empty scene
    for gid in site_ctx:
        kinds[gid] = "site"
    if "proxy" in kinds.values():
        warnings.append("Some model shapes have no building object type. Counts by object type may be incomplete; check the 3D shapes or export with object classifications.")
    for n in g.nodes:  # viewers can hide rooms / pick kinds without a lookup
        if n.mesh is not None and n.name in kinds:
            n.extras = {"kind": kinds[n.name]}
            if n.name in site_ctx:  # terrain / site context: keep the node (and the recentring), drop the mesh
                n.mesh = None
                n.extras["site_context"] = True
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
        for k, v in (attr_dims(e, scale) if length_unit_known else {}).items():
            q[k] = v; qsrc[k] = "attribute"
        for k, v in property_quantities_of(e).items():
            q[k] = v; qsrc[k] = "property"
        for k, v in quantities_of(e, scale).items():
            q[k] = v; qsrc[k] = "qto"  # Qto wins over attribute
        k_ = kinds[gid]
        if length_unit_known and b is not None and src.get(gid) == "glb":  # fill gaps from geometry
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
            "storey": ({"name": st.Name or "Unnamed level", "elevation_m": round((st.Elevation or 0) * scale, 4)} if st is not None else None),
            "bbox_m": bbox, "quantities": q, "quantity_source": qsrc, "props": props_of(e),
            "bbox_source": src.get(gid),
        }
        elements.append(entry)
        if gid in name_to_box and gid not in site_ctx:
            items[gid] = {"node": gid, "usd_name": usd_name(gid), "bbox_m": bbox,
                          "storey": entry["storey"]["name"] if entry["storey"] else None, "kind": k_}
    for s in f.by_type("IfcBuildingStorey"):
        storeys[s.GlobalId] = {"name": s.Name or "Unnamed level", "elevation_m": round((s.Elevation or 0) * scale, 4)}
    storey_list = sorted(storeys.values(), key=lambda s: s["elevation_m"])

    from pipeline.scale_provenance import ifc_units
    from pipeline.ifc_props import building_meta, enrich_elements
    enrich_elements(f, elements)
    from pipeline.ifc_quantities import build as build_quantity_index
    try:  # optional sidecar: never fail the scene over it
        (out_dir / "ifc-quantities.json").write_text(json.dumps(build_quantity_index(f, space_geometry=True)))
    except Exception as e:  # noqa: BLE001
        warnings.append(f"quantity index skipped: {e}"[:200])
    elements_tmp = out_dir / "tmp" / "elements-scene.json"
    elements_tmp.parent.mkdir(exist_ok=True)
    elements_tmp.write_text(json.dumps(
        {"doc_id": doc["doc_id"], "version": 2, "schema": f.schema, "units": "m", "unit_provenance": ifc_units(f, doc["doc_id"]), "building": building_meta(f),
         "coords": "recentred in X/Z by origin_offset_m, Y-up (glTF), Y keeps real elevation",
         "storeys": storey_list, "elements": elements}, indent=1))
    elements_tmp.replace(out_dir / "elements.json")
    lic = (doc.get("licence") or "")
    source_offset = np.array((g.extras or {}).get("source_origin_offset_m", [0, 0, 0]), dtype=float)
    scene = {"doc_id": doc["doc_id"], "glb": "scene.glb", "usdz": None, "units": "m", "up": "Y",
             "origin_offset_m": [round(float(x), 5) for x in off + source_offset], "storeys": storey_list,
             "plan_image": None, "items": items, "warnings": warnings, "site_context_hidden": sorted(site_ctx),
             "publishable": not (lic.startswith("CC-BY-ND") or lic.startswith("GPL"))}
    (out_dir / "scene.json").write_text(json.dumps(scene, indent=1))
    try:  # names, room areas, door widths for the info cards (pipeline/manifest_info.py)
        from pipeline import manifest_info
        manifest_info.enrich(out_dir, ifc)
    except Exception as ex:  # noqa: BLE001
        print('manifest_info skipped:', repr(ex)[:200])
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
