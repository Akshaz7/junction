"""ifc_scene: terrain / site context (IfcGeographicElement, proxies placed straight in the IfcSite, the IfcSite's own
shape) stays out of scene.glb and scene.json items, but keeps its elements.json entry as kind "site"."""
import json

import ifcopenshell
import ifcopenshell.api.geometry
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import numpy as np
from pygltflib import GLTF2

from pipeline import ifc_scene, pdf_to_ifc
from pipeline.tests.test_pdf_to_ifc import _planmap


def _block(f, body, cls, name, container, xy):
    el = ifcopenshell.api.root.create_entity(f, ifc_class=cls, name=name)
    rep = ifcopenshell.api.geometry.add_wall_representation(f, context=body, length=30.0, height=0.5, thickness=30.0)
    ifcopenshell.api.geometry.assign_representation(f, product=el, representation=rep)
    m = np.eye(4)
    m[:2, 3] = xy
    ifcopenshell.api.geometry.edit_object_placement(f, product=el, matrix=m)
    ifcopenshell.api.spatial.assign_container(f, products=[el], relating_structure=container)
    return el


def test_site_context_left_out_of_scene(tmp_path):
    src = pdf_to_ifc.build(_planmap(), tmp_path / "model.ifc")
    f = ifcopenshell.open(str(src))
    body = next(c for c in f.by_type("IfcGeometricRepresentationSubContext") if c.ContextIdentifier == "Body")
    site = f.by_type("IfcSite")[0]
    storey = f.by_type("IfcBuildingStorey")[0]
    terrain = _block(f, body, "IfcGeographicElement", "Terrain", site, (-10, -10))
    loose = _block(f, body, "IfcBuildingElementProxy", "Site block", site, (-10, -10))
    kept = _block(f, body, "IfcBuildingElementProxy", "Plinth", storey, (0, 0))
    f.write(str(src))

    out = tmp_path / "art"
    ifc_scene.process(src, {"doc_id": "synthetic"}, out)
    scene = json.loads((out / "scene.json").read_text())
    els = {e["item_id"]: e for e in json.loads((out / "elements.json").read_text())["elements"]}
    g = GLTF2().load(str(out / "scene.glb"))
    meshes = {n.name for n in g.nodes if n.mesh is not None}

    for el in (terrain, loose):
        assert el.GlobalId not in meshes and el.GlobalId not in scene["items"]
        assert els[el.GlobalId]["kind"] == "site" and els[el.GlobalId]["bbox_m"]  # still answerable
    assert sorted(scene["site_context_hidden"]) == sorted([terrain.GlobalId, loose.GlobalId])
    # a proxy inside a storey is building, not site
    assert kept.GlobalId in meshes and scene["items"][kept.GlobalId]["kind"] == "proxy"
    assert any(it["kind"] == "wall" for it in scene["items"].values())
