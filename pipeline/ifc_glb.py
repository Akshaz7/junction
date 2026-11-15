"""Stream IFC triangles to GLB without retaining every mesh in Python/trimesh."""
import gc
import json
import tempfile
import struct
from pathlib import Path

import ifcopenshell
import numpy as np
from ifcopenshell import geom


def convert(ifc: Path, output: Path):
    settings = geom.settings()
    settings.set("use-world-coords", True)
    settings.set("mesher-linear-deflection", 0.01)  # one centimetre display tolerance, in metres
    settings.set("no-normals", True)
    settings.set("no-parallel-mapping", True)
    data = {"asset": {"version": "2.0", "generator": "Stoa IFC streaming converter"},
            "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [],
            "accessors": [], "bufferViews": [], "materials": []}
    offset, colours, skipped, metadata = None, {}, [], {}
    output.parent.mkdir(parents=True, exist_ok=True)
    binary = output.with_suffix(".bin.tmp")
    try:
        with binary.open("wb") as stream:
            def array(values, component, shape, target):
                start = stream.tell()
                stream.write(values.tobytes())
                view = len(data["bufferViews"])
                data["bufferViews"].append({"buffer": 0, "byteOffset": start,
                                             "byteLength": stream.tell() - start, "target": target})
                accessor = {"bufferView": view, "componentType": component, "count": len(values), "type": shape}
                if shape == "VEC3":
                    accessor.update(min=values.min(axis=0).tolist(), max=values.max(axis=0).tolist())
                data["accessors"].append(accessor)
                return len(data["accessors"]) - 1

            for guid, verts, faces, rgba in shapes(ifc, settings, output.parent, skipped, metadata):
                if len(verts) and len(faces):
                    v = np.column_stack([verts[:, 0], verts[:, 2], -verts[:, 1]])
                    if not np.isfinite(v).all():
                        raise ValueError("The IFC contains invalid geometry coordinates. Export the model again.")
                    if offset is None:
                        offset = np.array([v[0, 0], 0., v[0, 2]])
                    v = np.ascontiguousarray(v - offset, dtype="<f4")
                    if rgba not in colours:
                        colours[rgba] = len(data["materials"])
                        data["materials"].append({"pbrMetallicRoughness": {"baseColorFactor": rgba,
                                                  "metallicFactor": 0., "roughnessFactor": .9},
                                                  "alphaMode": "BLEND" if rgba[3] < .99 else "OPAQUE"})
                    pos = array(v, 5126, "VEC3", 34962)
                    idx = array(np.asarray(faces, dtype="<u4"), 5125, "SCALAR", 34963)
                    ni = len(data["nodes"])
                    data["scenes"][0]["nodes"].append(ni)
                    data["nodes"].append({"name": guid, "mesh": ni})
                    data["meshes"].append({"primitives": [{"attributes": {"POSITION": pos},
                                              "indices": idx, "material": colours[rgba]}]})
            length = stream.tell()
        if not data["nodes"]:
            raise RuntimeError("The IFC has no geometry that could be converted.")
        data["buffers"] = [{"byteLength": length}]
        data["extras"] = {"source_origin_offset_m": offset.tolist(), "unmeshed_item_ids": skipped, **metadata}
        js = json.dumps(data, separators=(",", ":")).encode()
        js += b" " * (-len(js) % 4)
        pad = -length % 4
        with output.open("wb") as dst, binary.open("rb") as src:
            dst.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + length + pad))
            dst.write(struct.pack("<II", len(js), 0x4E4F534A))
            dst.write(js)
            dst.write(struct.pack("<II", length + pad, 0x004E4942))
            while chunk := src.read(1024 * 1024):
                dst.write(chunk)
            dst.write(b"\0" * pad)
    finally:
        binary.unlink(missing_ok=True)


def colour(materials):
    rgba = (.8, .8, .8, 1.)
    if materials:
        m = materials[0]
        d = m.diffuse
        alpha = 1. - float(m.transparency) if m.has_transparency else 1.
        rgba = tuple(min(1., max(0., x)) if np.isfinite(x) else default
                     for x, default in zip((d.r(), d.g(), d.b(), alpha), rgba))
    return rgba


def shapes(source, settings, directory, skipped, metadata):
    from pipeline.ifc_fragments import Fragments
    from pipeline.ifc_facets import mesh as faceted_mesh
    from ifcopenshell.util.element import get_styles
    with tempfile.TemporaryDirectory(prefix="ifc-batches-", dir=directory) as work:
        work = Path(work)
        fragments = Fragments(source, work / "index.sqlite")
        try:
            metadata["aggregate_parts"] = fragments.aggregates()
            for ids, selected in fragments.batches():
                fragment = work / "batch.ifc"
                fragments.write(fragment, selected)
                f = ifcopenshell.open(str(fragment), lazy=True)
                for step_id in ids:
                    element = f.by_id(step_id)
                    if not element.Representation:
                        continue
                    arrays = faceted_mesh(element)
                    if arrays is not None:
                        # IFC styles are preserved in the fragments. The existing
                        # converter uses a single dominant colour per element.
                        rgba = (.8, .8, .8, 1.)
                        for style in get_styles(element):
                            surface = next((s for s in style.Styles if s.is_a("IfcSurfaceStyleShading")), None)
                            if surface is not None:
                                c = surface.SurfaceColour
                                rgba = (c.Red, c.Green, c.Blue, 1. - (getattr(surface, "Transparency", None) or 0.))
                                break
                        yield element.GlobalId, *arrays, rgba
                        del arrays
                    else:
                        try:
                            shape = geom.create_shape(settings, element)
                        except RuntimeError:
                            # Native iterators omit unsupported/2D-only shapes.
                            # Retain their property records and report the omission.
                            skipped.append(element.GlobalId)
                            continue
                        gm = shape.geometry
                        yield element.GlobalId, np.frombuffer(gm.verts_buffer, dtype=np.float64).reshape(-1, 3), np.frombuffer(gm.faces_buffer, dtype=np.int32), colour(gm.materials)
                        del gm, shape
                del element, f
                gc.collect()
        finally:
            fragments.close()
