"""Extract a searchable element index from an IFC file.

For every physical element (IfcElement subtype) dumps: GlobalId, name, IFC class,
normalised category, type name, storey, and world-space axis-aligned bbox (metres,
IFC Z-up). Usage: python extract_elements.py model.ifc elements.json
"""
import json
import multiprocessing
import sys
import time

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as uel
import ifcopenshell.util.unit as uunit
import numpy as np

# IFC class -> human category. Checked in order via is_a() so subclasses match.
CATEGORIES = [
    ("IfcWall", "wall"), ("IfcCurtainWall", "curtain_wall"), ("IfcDoor", "door"),
    ("IfcWindow", "window"), ("IfcSlab", "slab"), ("IfcRoof", "roof"),
    ("IfcStair", "stair"), ("IfcStairFlight", "stair"), ("IfcRamp", "ramp"),
    ("IfcRampFlight", "ramp"), ("IfcRailing", "railing"), ("IfcColumn", "column"),
    ("IfcBeam", "beam"), ("IfcMember", "member"), ("IfcPlate", "plate"),
    ("IfcCovering", "covering"), ("IfcFooting", "footing"), ("IfcPile", "pile"),
    ("IfcOpeningElement", "opening"), ("IfcFurnishingElement", "furniture"),
    ("IfcPipeSegment", "pipe"), ("IfcPipeFitting", "pipe_fitting"),
    ("IfcDuctSegment", "duct"), ("IfcDuctFitting", "duct_fitting"),
    ("IfcFlowTerminal", "terminal"), ("IfcFlowController", "valve_damper"),
    ("IfcFlowMovingDevice", "pump_fan"), ("IfcEnergyConversionDevice", "equipment"),
    ("IfcDistributionElement", "mep_other"), ("IfcBuildingElementProxy", "proxy"),
    ("IfcMechanicalFastener", "fastener"), ("IfcFastener", "fastener"),
    ("IfcDiscreteAccessory", "accessory"), ("IfcSpace", "space"),
]


def category(el):
    # IFC2X3 MEP uses generic classes (IfcFlowSegment/IfcFlowFitting) with the real
    # kind on the type object (IfcPipeSegmentType, IfcDuctFittingType, ...).
    typ = uel.get_type(el)
    if typ is not None and typ.is_a("IfcDistributionElementType"):
        for cls, cat in TYPE_CATEGORIES:
            if typ.is_a(cls):
                return cat
    for cls, cat in CATEGORIES:
        if el.is_a(cls):
            return cat
    return "other"


TYPE_CATEGORIES = [
    ("IfcPipeSegmentType", "pipe"), ("IfcPipeFittingType", "pipe_fitting"),
    ("IfcDuctSegmentType", "duct"), ("IfcDuctFittingType", "duct_fitting"),
    ("IfcCableCarrierSegmentType", "cable_tray"), ("IfcCableSegmentType", "cable"),
    ("IfcValveType", "valve"), ("IfcDamperType", "damper"),
    ("IfcSanitaryTerminalType", "sanitary"), ("IfcAirTerminalType", "air_terminal"),
    ("IfcLightFixtureType", "light"), ("IfcPumpType", "pump"), ("IfcFanType", "fan"),
    ("IfcTankType", "tank"),
]


def storey_of(el):
    """Walk containment/aggregation/fills/voids up to the nearest IfcBuildingStorey."""
    seen = set()
    cur = el
    while cur is not None and cur.id() not in seen:
        seen.add(cur.id())
        if cur.is_a("IfcBuildingStorey"):
            return cur
        nxt = uel.get_container(cur) or uel.get_aggregate(cur)
        if nxt is None and cur.is_a("IfcOpeningElement"):
            nxt = next((r.RelatingBuildingElement for r in cur.VoidsElements), None)
        if nxt is None and cur.is_a("IfcElement"):
            fills = getattr(cur, "FillsVoids", None) or []
            nxt = next((r.RelatingOpeningElement for r in fills), None)
        cur = nxt
    return None


def main(src, dst):
    t0 = time.time()
    f = ifcopenshell.open(src)
    scale = uunit.calculate_unit_scale(f)  # file length unit -> metres

    # IfcSpace is spatial, not IfcElement, but is useful in an index; keep both.
    targets = list(f.by_type("IfcElement")) + list(f.by_type("IfcSpace"))
    by_id = {e.id(): e for e in targets}

    # World-space geometry for bboxes. Same kernel IfcConvert uses -> bboxes match the GLB.
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    bboxes = {}
    it = ifcopenshell.geom.iterator(settings, f, multiprocessing.cpu_count(), include=targets)
    if it.initialize():
        while True:
            shape = it.get()
            v = np.asarray(shape.geometry.verts).reshape(-1, 3)
            if len(v):
                # geometry verts are already in metres (kernel converts units)
                bboxes[shape.id] = (v.min(0).round(4).tolist(), v.max(0).round(4).tolist())
            if not it.next():
                break

    # Aggregates (IfcRoof, IfcStair, assemblies) often have no own geometry;
    # roll up the union bbox of their decomposed parts.
    def rolled_bbox(e, depth=0):
        if e.id() in bboxes or depth > 5:
            return bboxes.get(e.id())
        parts = [rolled_bbox(p, depth + 1) for p in uel.get_decomposition(e) if p.id() in by_id]
        parts = [b for b in parts if b]
        if not parts:
            return None
        b = (np.min([p[0] for p in parts], 0).tolist(), np.max([p[1] for p in parts], 0).tolist())
        bboxes[e.id()] = b
        rolled.add(e.id())
        return b

    rolled = set()
    for e in targets:
        rolled_bbox(e)

    out = []
    for e in targets:
        st = storey_of(e)
        typ = uel.get_type(e)
        bb = bboxes.get(e.id())
        out.append({
            "guid": e.GlobalId,
            "step_id": e.id(),
            "name": e.Name,
            "ifc_class": e.is_a(),
            "category": category(e),
            "predefined_type": uel.get_predefined_type(e),
            "object_type": getattr(e, "ObjectType", None),
            "type_name": typ.Name if typ else None,
            "storey": st.Name if st else None,
            "storey_elevation_m": (
                round(st.Elevation * scale, 4) if st is not None and st.Elevation is not None else None
            ),
            "bbox_min": bb[0] if bb else None,
            "bbox_max": bb[1] if bb else None,
            "has_geometry": bb is not None and e.id() not in rolled,
            "bbox_source": None if bb is None else ("parts" if e.id() in rolled else "own"),
        })

    doc = {
        "source": src,
        "schema": f.schema,
        "units": "metres",
        "axes": "IFC world, Z-up (GLB exported with --y-up: glb=(x, z, -y))",
        "storeys": [
            {"name": s.Name, "elevation_m": round((s.Elevation or 0) * scale, 4)}
            for s in sorted(f.by_type("IfcBuildingStorey"), key=lambda s: s.Elevation or 0)
        ],
        "element_count": len(out),
        "elements": out,
    }
    with open(dst, "w") as fh:
        json.dump(doc, fh, indent=1)
    print(f"{src}: {len(out)} elements, {len(bboxes)} with geometry, {time.time() - t0:.2f}s -> {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
