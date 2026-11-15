"""Read-only wall detail adapter over the existing wall take-off measurements."""
from __future__ import annotations

from pathlib import Path
import json
import math

from engine import wallarea


def scene_wall(doc_id, item_id, root):
    """Recover generated raster components using the extrusion's existing reader.

    Only an exact saved scene ID is accepted. Bounds must still agree with the
    saved geometry, including any generated opening infill around the outline.
    """
    directory = Path(root) / doc_id
    result = None
    try:
        scene = json.loads((directory / "scene.json").read_text())
        item = scene.get("items", {}).get(item_id)
        if not item or item.get("kind") != "wall" or not scene.get("source_planmap"):
            return None
        name = scene["source_planmap"]
        if Path(name).name != name:
            return None
        pm = json.loads((directory / name).read_text())
        result = {"item_id": item_id, "storey": item.get("storey"), "page": pm.get("page", 1), "planmap": None,
                  "note": "Generated for demo: this 3D wall is a raster component, not a source plan-map wall."}
        # Match the IDs used by pipeline.extrude.process; do not assign source
        # wall measurements to a component merely because their boxes overlap.
        if not item_id.startswith("wall-r"):
            return result
        mpp = wallarea._number((pm.get("scale") or {}).get("m_per_px"))
        if not mpp:
            return result
        if (item.get("props") or {}).get("wall_outline_px"):
            from shapely.geometry import Polygon
            components = [(iid, Polygon(it["props"]["wall_outline_px"], it["props"].get("wall_outline_holes_px") or []))
                          for iid, it in scene["items"].items() if (it.get("props") or {}).get("wall_outline_px")]
        else:
            from PIL import Image
            import numpy as np
            from pipeline.raster_walls import read
            image = directory / f"page-{pm.get('page', 1)}.png"
            with Image.open(image) as im:
                raster = read(np.asarray(im.convert("L"), dtype=np.uint8), mpp)
            if not raster:
                return result
            components = [(f"wall-r{index:03d}", polygon) for index, polygon in enumerate(raster["walls"], 1)]
        origin = scene.get("origin_offset_m") or [0, 0, 0]
        polygons = []
        selected = False
        for iid, polygon in components:
            saved = scene.get("items", {}).get(iid, {})
            bbox = saved.get("bbox_m")
            if not bbox:
                continue
            bounds = polygon.bounds
            expected = [bounds[0] * mpp - origin[0], bounds[1] * mpp - origin[2], bounds[2] * mpp - origin[0], bounds[3] * mpp - origin[2]]
            actual = [bbox[0][0], bbox[0][2], bbox[1][0], bbox[1][2]]
            # Extrusion can attach lintel/sill infill to the wall node, expanding
            # its box. Source-outline estimates exclude that generated infill.
            if not all(math.isfinite(v) for v in expected + actual) or any(
                expected[k] < actual[k] - mpp if k < 2 else expected[k] > actual[k] + mpp for k in range(4)
            ):
                if iid == item_id:
                    result["note"] += " The source outline is outside the saved 3D shape; regenerate the model to measure this component."
                continue
            height = wallarea._number((saved.get("props") or {}).get("height_m") or (scene.get("defaults") or {}).get("wall_m"))
            props = {"height_m": height, "height_source": "assumed for generated 3D"} if height else {}
            if polygon.interiors:
                if iid == item_id:
                    result["note"] += " The component is a wall network with enclosed spaces; separate face areas are unavailable."
                continue
            polygons.append({"item_id": iid, "kind": "wall", "bbox_px": list(bounds),
                             "polygon_px": [list(p) for p in polygon.exterior.coords], "props": props})
            if iid == item_id:
                result["bbox_px"] = list(bounds)
                result["note"] += " Areas cover the source wall outline; generated lintel/sill infill beyond it is excluded."
                selected = True
        if selected:
            others = [{**i, "props": {k: v for k, v in (i.get("props") or {}).items() if k not in ("host_wall_id", "wall_id")}}
                      for i in pm.get("items", []) if i.get("kind") != "wall"]
            result["planmap"] = {**pm, "storey": item.get("storey"), "items": polygons + others}
        return result
    except (OSError, ValueError, TypeError, KeyError, ImportError, AttributeError):
        return result


def details(doc_id, item_id, root, *, quantities=None, props=None, storey=None):
    root = Path(root)
    quantities, props = quantities or {}, props or {}
    measured = wallarea._wallgeom(doc_id, root)
    is_ifc = measured is not None or (root / doc_id / "elements.json").exists()
    # Never run native IFC geometry in a detail request. Ingest creates the sidecar.
    if measured is None and not is_ifc:
        try:
            measured = wallarea.estimate_planmaps(doc_id, root, "")
        except (ValueError, TypeError, KeyError, OSError) as exc:
            measured = {"skipped": [{"item_id": item_id, "reason": f"Plan measurement unavailable: {exc}"}]}
    measured = measured or {}
    wall = next((w for w in measured.get("walls", []) if w["item_id"] == item_id), {})
    generated = None
    if not wall and not is_ifc:
        generated = scene_wall(doc_id, item_id, root)
        if generated and generated.get("planmap"):
            measured = wallarea.estimate_planmaps(doc_id, root, "", planmaps=[generated["planmap"]])
            wall = next((w for w in measured.get("walls", []) if w["item_id"] == item_id), {})
    skipped = next((w["reason"] for w in measured.get("skipped", []) if w["item_id"] == item_id), None)
    height = wallarea._number(wall.get("height_m") or quantities.get("height_m") or props.get("height_m"))
    height_source = "model" if is_ifc and height else wall.get("height_source")
    if not height and not is_ifc:
        height, height_source = 2.7, "assumed default; no wall height found"
    height_source = height_source or "not available"
    length = wallarea._number(wall.get("length_m") or quantities.get("length_m") or props.get("length_m"))
    thickness = wallarea._number(wall.get("thickness_m") or quantities.get("width_m") or props.get("thickness_m") or props.get("width_m"))
    external = wall.get("is_external", props.get("is_external"))
    external = external if isinstance(external, bool) else None
    floors = wall.get("floors", [])
    openings = wall.get("openings", [])
    oriented = external and wall.get("inside_side") in (0, 1)
    faces = []
    for side in (0, 1):
        gross = net = None
        if floors:
            if is_ifc and all(len(f.get("gross_sides_m2", [])) == 2 and len(f.get("net_sides_m2", [])) == 2 for f in floors):
                gross = sum(f["gross_sides_m2"][side] for f in floors)
                net = sum(f["net_sides_m2"][side] for f in floors)
            elif not is_ifc:
                gross, net = wall["gross_m2"] / 2, wall["net_m2"] / 2
        label = ("Inner face" if side == wall.get("inside_side") else "Outer face (facade)") if oriented else f"Face {'AB'[side]}"
        faces.append({"label": label, "gross_m2": gross, "opening_m2": max(0., gross - net) if gross is not None else None, "net_m2": net})
    notes = list(wall.get("notes", []))
    if generated:
        notes.append(generated["note"])
    if external and not oriented:
        notes.append("Inner/outer orientation is not recorded; faces A and B are shown without guessing.")
    if not is_ifc:
        page_prefix = next((f["storey"] + ":" for f in floors), None)
        notes.extend(a for a in measured.get("assumptions", []) if not page_prefix or a.startswith(page_prefix))
    if skipped:
        notes.append(skipped)
    if not wall:
        notes.append("Wall face measurements are not available in this file.")
    status = "Measured" if is_ifc and wall else "Estimate" if wall or not is_ifc else "Not available"
    method = "IFC gross and void-cut longitudinal side faces; openings deducted from the geometry." if is_ifc else f"2D {wall.get('axis_source') or 'wall outline'} × height; openings deducted once; scale: {wall.get('scale_method') or 'not available'}."
    if generated and wall:
        method = f"2D raster wall outline × height − detected openings; excludes generated lintel/sill infill; scale: {wall.get('scale_method') or 'not available'}."
    if not wall:
        method = "Wall face geometry is unavailable; no area or opening deduction has been inferred."
    if wall.get("axis_source") not in (None, "IFC axis") and is_ifc:
        status = "Estimate"
        notes.append("Wall direction inferred from geometry; verify the side-face classification.")
    if wall.get("curved") and len(floors) > 1:
        notes.append("Curved wall storey splits are estimated from mesh fractions.")
    return {"status": status, "length_m": length, "thickness_m": thickness, "height_m": height,
            "height_source": height_source, "storey": storey or ", ".join(dict.fromkeys(f["storey"] for f in floors)),
            "classification": "External (facade)" if external else "Internal" if external is False else "Not recorded",
            "faces": faces, "opening_count": len(openings) if wall else None,
            "method": method, "notes": list(dict.fromkeys(notes))}
