"""ifc_enrich: synthetic PDF-made IFC -> native-style structure (owner history, qtos, psets, layer-set usage,
axis/box reps, slab type, space boundaries, wall connections); idempotent; ifc_scene still converts it."""
import ifcopenshell
import ifcopenshell.util.element as uel

from pipeline import ifc_enrich, pdf_to_ifc
from pipeline.tests.test_pdf_to_ifc import _planmap


def test_enrich_adds_native_structure(tmp_path):
    out = pdf_to_ifc.build(_planmap(), tmp_path / "x.ifc")
    c = ifc_enrich.enrich(out)  # pdf_to_ifc may already add some of these; enrich fills whatever is missing
    assert isinstance(c, dict)
    f = ifcopenshell.open(str(out))
    assert len(f.by_type("IfcRelSpaceBoundary")) >= 4 and len(f.by_type("IfcRelConnectsPathElements")) >= 4
    assert len(f.by_type("IfcOwnerHistory")) == 1
    assert f.by_type("IfcApplication") and all(r.OwnerHistory for r in f.by_type("IfcRoot"))
    assert any(u.UnitType == "PLANEANGLEUNIT" for u in f.by_type("IfcSIUnit"))
    for w in f.by_type("IfcWall"):
        ps = uel.get_psets(w)
        q = ps["Qto_WallBaseQuantities"]
        assert q["NetSideArea"] <= q["GrossSideArea"] + 1e-6 and q["NetVolume"] > 0
        assert 0.15 < q["Width"] < 0.25 and q["Length"] > 3.5
        assert ps["Pset_WallCommon"]["LoadBearing"] in (True, False)
        assert uel.get_type(w).is_a("IfcWallType")
        assert uel.get_material(w, should_skip_usage=False).is_a("IfcMaterialLayerSetUsage")
        ids = {r.RepresentationIdentifier for r in w.Representation.Representations}
        assert {"Axis", "Body", "Box"} <= ids
    host = [w for w in f.by_type("IfcWall") if w.HasOpenings]
    q = uel.get_psets(host[0])["Qto_WallBaseQuantities"]
    assert q["NetSideArea"] < q["GrossSideArea"]
    s = f.by_type("IfcSlab")[0]
    assert uel.get_type(s).is_a("IfcSlabType") and "Pset_SlabCommon" in uel.get_psets(s)
    sp = f.by_type("IfcSpace")[0]
    assert "Pset_SpaceCommon" in uel.get_psets(sp)
    assert {b.RelatingSpace for b in f.by_type("IfcRelSpaceBoundary")} == {sp}
    for d in f.by_type("IfcDoor") + f.by_type("IfcWindow"):
        assert uel.get_type(d) is not None
    # idempotent
    c2 = ifc_enrich.enrich(out)
    assert c2["space_boundaries"] == 0 and c2.get("axis_reps", 0) == 0 and c2.get("layer_set_usage", 0) == 0
    assert len(ifcopenshell.open(str(out)).by_type("IfcRelSpaceBoundary")) == len(f.by_type("IfcRelSpaceBoundary"))


def test_enrich_fills_bare_ifc(tmp_path):
    """Strip what enrich owns from a built IFC, then enrich must restore it."""
    out = pdf_to_ifc.build(_planmap(), tmp_path / "b.ifc")
    f = ifcopenshell.open(str(out))
    for cls in ("IfcRelSpaceBoundary", "IfcRelConnectsPathElements"):
        for r in f.by_type(cls):
            f.remove(r)
    for r in f.by_type("IfcRoot"):
        r.OwnerHistory = None
    for oh in f.by_type("IfcOwnerHistory"):
        f.remove(oh)
    f.write(str(out))
    c = ifc_enrich.enrich(out)
    assert c["space_boundaries"] >= 4 and c["wall_connections"] >= 4 and c["owner_history"] == 1
    g = ifcopenshell.open(str(out))
    assert all(r.OwnerHistory for r in g.by_type("IfcRoot"))


def test_ifc_scene_still_processes(tmp_path):
    from pipeline import ifc_scene
    out = pdf_to_ifc.build(_planmap(), tmp_path / "model.ifc")
    ifc_enrich.enrich(out)
    ifc_scene.process(out, {"doc_id": "synthetic"}, tmp_path)
    assert (tmp_path / "scene.glb").stat().st_size > 1000


def test_fire_materials_space_types_layers(tmp_path):
    import json
    pm = _planmap()
    for it in pm["items"]:
        if it["item_id"] == "wall-001":
            it["props"]["fire_rating"] = "EI60"
        if it["item_id"] == "door-001":
            it["label"] = "D1 EI30"
    (tmp_path / "planmap-1.json").write_text(json.dumps(pm))
    out = pdf_to_ifc.build(pm, tmp_path / "model.ifc")
    ifc_enrich.enrich(out)
    c2 = ifc_enrich.enrich(out)
    assert c2["space_types"] == 0 and c2["layers"] == 0 and c2["opening_materials"] == 0
    f = ifcopenshell.open(str(out))
    fr = {uel.get_psets(w)["Hologram_Provenance"]["item_id"]: uel.get_psets(w)["Pset_WallCommon"].get("FireRating")
          for w in f.by_type("IfcWall")}
    assert fr["wall-001"] == "EI60"
    assert uel.get_psets(f.by_type("IfcDoor")[0])["Pset_DoorCommon"]["FireRating"] == "EI30"
    assert uel.get_material(f.by_type("IfcWindow")[0]) is not None
    assert uel.get_material(f.by_type("IfcDoor")[0]) is not None
    assert uel.get_type(f.by_type("IfcSpace")[0]).is_a("IfcSpaceType")
    names = {la.Name for la in f.by_type("IfcPresentationLayerAssignment")}
    assert {"A-WALL", "A-DOOR", "A-GLAZ", "A-AREA"} <= names


def test_native_extras(tmp_path):
    """r3 extras: spatial names/elevations, FootPrint reps, connection ends, material styles, one material per name,
    typed occurrences without redundant attributes (bSI BLT001/OJT001), untyped walls get a type + layer usage."""
    out = pdf_to_ifc.build(_planmap(), tmp_path / "uploads__demo-plan-0123abcd.ifc")
    f = ifcopenshell.open(str(out))
    w0 = f.by_type("IfcWall")[0]  # strip type + material from one wall: enrich must restore both
    for rel in list(w0.IsTypedBy or []) + [r for r in w0.HasAssociations if r.is_a("IfcRelAssociatesMaterial")]:
        objs = [o for o in rel.RelatedObjects if o != w0]
        if objs:
            rel.RelatedObjects = objs
        else:
            f.remove(rel)
    for s in f.by_type("IfcSite"):
        s.Name, s.RefElevation = "Site", None
    for d in f.by_type("IfcDoor"):
        d.OperationType = "SINGLE_SWING_LEFT"
    f.write(str(out))
    c = ifc_enrich.enrich(out)
    assert not [k for k in c if k.startswith("error")], c
    g = ifcopenshell.open(str(out))
    assert all(s.Name != "Site" and s.RefElevation == 0.0 for s in g.by_type("IfcSite"))
    assert {c.ContextIdentifier for c in g.by_type("IfcGeometricRepresentationSubContext")} >= {"Body", "Axis",
                                                                                                "Box", "FootPrint"}
    for el in g.by_type("IfcWall") + g.by_type("IfcSpace") + g.by_type("IfcSlab"):
        assert "FootPrint" in {r.RepresentationIdentifier for r in el.Representation.Representations}
    for w in g.by_type("IfcWall"):
        assert uel.get_type(w) is not None
        assert uel.get_material(w, should_skip_usage=False).is_a("IfcMaterialLayerSetUsage")
    assert all(r.RelatingConnectionType in ("ATSTART", "ATEND", "ATPATH") for r in g.by_type("IfcRelConnectsPathElements"))
    names = [(m.Name, m.Category) for m in g.by_type("IfcMaterial")]
    assert len(names) == len(set(names))
    assert g.by_type("IfcMaterialDefinitionRepresentation")
    for d in g.by_type("IfcDoor"):
        assert d.OperationType is None and uel.get_type(d).OperationType is not None
    for sp in g.by_type("IfcSpace"):
        assert sp.LongName
        q = uel.get_psets(sp)["Qto_SpaceBaseQuantities"]
        assert q["NetFloorArea"] > 0 and q["GrossPerimeter"] > 0 and q["Height"] > 0
    c2 = ifc_enrich.enrich(out)
    assert not {k: v for k, v in c2.items() if v and not k.startswith("error")}, c2
    import scripts.ifc_native_score as sc
    r = sc.score(out, do_validate=True)
    bad = {i["key"] for i in r["items"] if not i["pass"] and not i["optional"]}
    assert "validate_errors_0" not in bad and "bsi_BLT001_BLT002" not in bad and "bsi_OJT001" not in bad, bad
