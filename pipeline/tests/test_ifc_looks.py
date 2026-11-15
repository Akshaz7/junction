"""r4 looks post-pass in ifc_enrich: roof over the top storey, slab types, native door/window bodies."""
import shutil
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element as ue
import pytest

from pipeline import ifc_enrich

SRC = Path("/home/ar/junction-pdf3d-r3/artifacts/r3__eval-molio/model.ifc")


@pytest.fixture
def ifc(tmp_path):
    if not SRC.exists():
        pytest.skip("no r3 sample IFC")
    p = tmp_path / "model.ifc"
    shutil.copy(SRC, p)
    return p


def test_roof_and_bodies(ifc, monkeypatch):
    monkeypatch.setenv("PDF_IFC_ROOF", "1")
    monkeypatch.setenv("PDF_IFC_OPENING_BODIES", "1")  # default off now (viewer collapses glass)
    c = ifc_enrich.enrich(ifc)
    f = ifcopenshell.open(str(ifc))
    roofs = f.by_type("IfcRoof")
    assert len(roofs) == 1 and c["roof_slabs"] >= 1
    rs = ue.get_decomposition(roofs[0])
    assert rs and all(ue.get_predefined_type(s) == "ROOF" and not s.ContainedInStructure for s in rs)
    assert not f.by_type("IfcCovering")
    for d in f.by_type("IfcDoor") + f.by_type("IfcWindow"):
        body = [r for r in d.Representation.Representations if r.RepresentationIdentifier == "Body"]
        assert body[0].RepresentationType == "MappedRepresentation"
        assert d.FillsVoids
    floors = [s for s in f.by_type("IfcSlab") if s not in rs]
    assert all(ue.get_predefined_type(s) in ("FLOOR", "BASESLAB") for s in floors)
    # idempotent
    c2 = ifc_enrich.enrich(ifc)
    assert len(ifcopenshell.open(str(ifc)).by_type("IfcRoof")) == 1 and c2.get("door_bodies", 0) == 0


def test_switches_off(ifc, monkeypatch):
    monkeypatch.setenv("PDF_IFC_ROOF", "0")
    monkeypatch.setenv("PDF_IFC_OPENING_BODIES", "0")
    ifc_enrich.enrich(ifc)
    f = ifcopenshell.open(str(ifc))
    assert not f.by_type("IfcRoof")
    assert all(r.RepresentationType != "MappedRepresentation" for d in f.by_type("IfcDoor")
               for r in d.Representation.Representations)


def test_failure_rolls_back(ifc, monkeypatch):
    def boom(f, counts, kinds):
        f.by_type("IfcDoor")[0].Name = "changed"
        raise RuntimeError("x")
    monkeypatch.setattr(ifc_enrich, "_opening_bodies", boom)
    monkeypatch.setenv("PDF_IFC_OPENING_BODIES", "1")
    c = ifc_enrich.enrich(ifc)
    assert "error_looks_opening_bodies" in c
    f = ifcopenshell.open(str(ifc))
    assert all(d.Name != "changed" for d in f.by_type("IfcDoor"))
