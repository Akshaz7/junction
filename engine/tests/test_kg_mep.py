"""Generated-for-demo IFC fixtures test relationships, units and honest uncertainty."""
import json
from pathlib import Path

import pytest

from engine.kg.mep import Writer, enrich, enrich_ifc, room_services
from engine.kg.mep_sheets import link_sheet_rooms
from engine.kg.mep_spatial import enrich_spatial


def node(kind, did, item, bbox=None, level="Level A", label=None):
    return {"id": f"{kind}:{did}:{item}", "kind": kind, "label": label or kind,
            "doc_ids": [did], "level": level, "props": {"world_bbox_m": bbox} if bbox else {},
            "source": {"doc_id": did, "page": 1, "item_id": item, "bbox": None}, "canonical": None, "degree": 0}


def ifc_file(tmp_path, schema="IFC4", imperial=False):
    ifc = pytest.importorskip("ifcopenshell")
    f = ifc.file(schema=schema)
    guid = ifc.guid.new
    metre = f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
    if imperial:
        dims = f.create_entity("IfcDimensionalExponents", 1, 0, 0, 0, 0, 0, 0)
        cf = f.create_entity("IfcMeasureWithUnit", f.create_entity("IfcLengthMeasure", 0.3048), metre)
        unit = f.create_entity("IfcConversionBasedUnit", dims, "LENGTHUNIT", "foot", cf)
    else:
        unit = f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE")
    assignment = f.create_entity("IfcUnitAssignment", Units=[unit])
    f.create_entity("IfcProject", GlobalId=guid(), Name="generated for demo", UnitsInContext=assignment)
    room = f.create_entity("IfcSpace", GlobalId=guid(), Name="R-A", LongName="Office")
    cls = "IfcFlowSegment" if schema == "IFC2X3" else "IfcDuctSegment"
    duct = f.create_entity(cls, GlobalId=guid(), Name="Supply duct")
    terminal = f.create_entity("IfcFlowTerminal", GlobalId=guid(), Name="Supply air terminal")
    f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=guid(), RelatedElements=[duct, terminal], RelatingStructure=room)
    system = f.create_entity("IfcSystem", GlobalId=guid(), Name="Ventilation")
    f.create_entity("IfcRelAssignsToGroup", GlobalId=guid(), RelatedObjects=[duct, terminal], RelatingGroup=system)
    p1 = f.create_entity("IfcDistributionPort", GlobalId=guid(), FlowDirection="SOURCE")
    p2 = f.create_entity("IfcDistributionPort", GlobalId=guid(), FlowDirection="SINK")
    for port, owner in [(p1, duct), (p2, terminal)]:
        f.create_entity("IfcRelConnectsPortToElement", GlobalId=guid(), RelatingPort=port, RelatedElement=owner)
    f.create_entity("IfcRelConnectsPorts", GlobalId=guid(), RelatingPort=p1, RelatedPort=p2)
    length = f.create_entity("IfcQuantityLength", Name="Length", LengthValue=10.0 if imperial else 2000.0)
    qto = f.create_entity("IfcElementQuantity", GlobalId=guid(), Name="BaseQuantities", Quantities=[length])
    f.create_entity("IfcRelDefinesByProperties", GlobalId=guid(), RelatedObjects=[duct], RelatingPropertyDefinition=qto)
    height = f.create_entity("IfcPropertySingleValue", Name="FinishCeilingHeight", NominalValue=f.create_entity("IfcLengthMeasure", 9.0 if imperial else 2700.0))
    generic_height = f.create_entity("IfcPropertySingleValue", Name="Height", NominalValue=f.create_entity("IfcLengthMeasure", 15.0 if imperial else 6000.0))
    ps = f.create_entity("IfcPropertySet", GlobalId=guid(), Name="Room values", HasProperties=[height, generic_height])
    f.create_entity("IfcRelDefinesByProperties", GlobalId=guid(), RelatedObjects=[room], RelatingPropertyDefinition=ps)
    path = tmp_path / "services.ifc"
    f.write(str(path))
    return path, room.GlobalId, duct.GlobalId, terminal.GlobalId


@pytest.mark.parametrize("schema", ["IFC2X3", "IFC4", "IFC4X3"])
@pytest.mark.parametrize("imperial", [False, True])
def test_ifc_relationships_units_and_impact_hook(tmp_path, schema, imperial):
    path, rid, did, tid = ifc_file(tmp_path, schema, imperial)
    existing = node("fixture", "m", tid)
    graph = {"nodes": [existing], "edges": []}
    (tmp_path / "m").mkdir()
    writer = Writer(graph)
    import time
    report = enrich_ifc(writer, "m", path, tmp_path, time.monotonic() + 30)
    assert report["services"] == 2
    assert len([n for n in graph["nodes"] if n.get("source", {}).get("item_id") == tid]) == 1
    # Reclassify generic fixtures as actual terminals when IFC says so.
    terminal = writer.items["m", tid]
    assert terminal["kind"] in {"terminal", "fixture"}
    room = writer.items["m", rid]
    assert room["props"]["ceiling_height_m"] == pytest.approx(2.7432 if imperial else 2.7)
    assert writer.items["m", did]["props"]["length_m"] == pytest.approx(3.048 if imperial else 2)
    assert len([e for e in graph["edges"] if e["kind"] == "part_of_system"]) == 2
    connections = [e for e in graph["edges"] if e["kind"] == "connects"]
    assert len(connections) == 1 and connections[0]["evidence"]["port_ids"]
    result = room_services(graph, room["id"])
    assert sum(result["count_by_kind"].values()) == 2
    assert result["length_m_by_kind"] == {}  # Whole element length is not in-room length.
    assert all(s["source"] and s["why_path"] for s in result["services"])
    assert all(e["confidence"] == 1 and e["method"] == "ifc_relation" for e in graph["edges"])


def test_spatial_estimates_do_not_assign_ambiguous_terminal_or_invent_length():
    r1 = node("room", "a", "one", [[0, 0, 0], [5, 3, 5]])
    r2 = node("room", "a", "two", [[4, 0, 0], [9, 3, 5]])
    terminal = node("terminal", "a", "t", [[4.1, 2.5, 1], [4.9, 2.8, 2]])
    duct = node("duct", "a", "d", [[1, 2.5, 1], [8, 2.8, 2]])
    graph = {"nodes": [r1, r2, terminal, duct], "edges": []}
    enrich_spatial(Writer(graph))
    assert len(graph["edges"]) == 2
    assert all(e["from"] == duct["id"] and e["kind"] == "in_room" and e["confidence"] < .6 for e in graph["edges"])
    assert room_services(graph, r1["id"])["length_m_by_kind"] == {}


def test_no_cross_doc_spatial_join_without_registration():
    graph = {"nodes": [node("room", "a", "r", [[0, 0, 0], [5, 3, 5]]),
                       node("terminal", "b", "t", [[1, 2, 1], [2, 3, 2]])], "edges": []}
    enrich_spatial(Writer(graph))
    assert graph["edges"] == []


def test_cross_document_room_link_uses_shared_declared_frame():
    room = node("room", "arch", "r", [[0, 0, 0], [5, 3, 5]], level="Ground floor")
    terminal = node("terminal", "services", "t", [[1, 2, 1], [2, 2.2, 2]], level="00")
    frame = {"building_guid": "shared-building", "project_guid": "shared-project",
             "matrix_z_up_m": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]}
    graph = {"nodes": [room, terminal], "edges": [], "mep": {"frames": {"arch": [frame], "services": [frame]}}}
    enrich_spatial(Writer(graph))
    assert {e["kind"] for e in graph["edges"]} == {"serves", "in_room"}
    assert all(e["evidence"]["alignment"]["anchor_method"] == "declared shared IFC building frame" for e in graph["edges"])
    assert all(e["confidence"] < .6 for e in graph["edges"])


def test_renamed_terminal_keeps_all_core_edges_valid(tmp_path):
    path, _, _, terminal_id = ifc_file(tmp_path)
    t = node("fixture", "m", terminal_id)
    doc = {"id": "doc:m:root", "kind": "doc", "doc_ids": ["m"], "props": {}}
    graph = {"nodes": [doc, t], "edges": [{"id": "core-source", "kind": "contains", "from": doc["id"],
              "to": t["id"], "method": "rule", "confidence": 1, "evidence": {}, "doc_ids": ["m"]}]}
    enrich(graph, {"docs": [{"doc_id": "m", "files": {"ifc": str(path)}}]}, tmp_path)
    assert t["kind"] == "terminal" and t["id"].startswith("terminal:")
    assert graph["edges"][0]["to"] == t["id"]
    node_ids = {n["id"] for n in graph["nodes"]}
    assert all(e["from"] in node_ids and e["to"] in node_ids for e in graph["edges"])


def test_declared_missing_units_do_not_assume_metres(tmp_path):
    path, *_ = ifc_file(tmp_path)
    ifc = pytest.importorskip("ifcopenshell")
    f = ifc.open(str(path))
    f.by_type("IfcProject")[0].UnitsInContext = None
    f.write(str(path))
    graph = {"nodes": [], "edges": []}
    enrich(graph, {"docs": [{"doc_id": "m", "files": {"ifc": str(path)}}]}, tmp_path)
    assert not any(n["props"].get("length_m") or n["props"].get("ceiling_height_m") for n in graph["nodes"])
    assert any(n["props"].get("measurement_note") for n in graph["nodes"])


def test_sheet_match_requires_alignment_and_one_to_one_rooms():
    a = node("room", "a", "ra", label="Office A")
    b = node("room", "b", "rb", label="Office A")
    c = node("room", "b", "rc", label="Office A")
    def pm(items):
        return {"page": 1, "image": {"w": 100, "h": 100}, "items": [
            {"item_id": i, "bbox_px": [10, 10, 30, 30]} for i in items]}
    pdf = {"W_pt": 100, "H_pt": 100}
    T = {"s": 1, "R": [[1, 0], [0, 1]], "t": [0, 0], "matches": 4, "residual": .1}
    graph = {"nodes": [a, b], "edges": []}
    writer = Writer(graph)
    link_sheet_rooms(writer, "a", "b", pm(["ra"]), pm(["rb"]), pdf, pdf, T, .01)
    assert len(graph["edges"]) == 1
    assert graph["edges"][0]["evidence"]["alignment"]["matches"] == 4
    graph = {"nodes": [a, b, c], "edges": []}
    link_sheet_rooms(Writer(graph), "a", "b", pm(["ra"]), pm(["rb", "rc"]), pdf, pdf, T, .01)
    assert not graph["edges"]


def test_missing_ifc_and_optional_pdf_are_explicit_notes(tmp_path):
    (tmp_path / "sheet").mkdir()
    (tmp_path / "sheet" / "input.pdf").write_bytes(b"not parsed when optional module absent")
    graph = {"nodes": [], "edges": []}
    project = {"docs": [{"doc_id": "missing", "kind": "ifc"},
                         {"doc_id": "sheet", "files": {"pdf": "input.pdf"}, "title": "Ventilation"}]}
    import importlib.util
    if importlib.util.find_spec("pipeline.pdf_mep"):
        pytest.skip("optional pipeline installed; adapter exercised separately")
    enrich(graph, project, tmp_path)
    assert graph["mep"]["documents"]["missing"]["status"] == "unavailable"
    assert any("optional pipeline.pdf_mep" in n for n in graph["mep"]["notes"])


def test_same_room_path_deduplicates_services():
    a, b, t = node("room", "a", "a"), node("room", "b", "b"), node("terminal", "b", "t")
    graph = {"nodes": [a, b, t], "edges": []}
    w = Writer(graph)
    w.edge("same_as", a, b, "guid", 1, {"item_id": "shared"})
    w.edge("in_room", t, b, "ifc_relation", 1, {})
    w.edge("serves", t, b, "ifc_relation", 1, {})
    result = room_services(graph, a["id"])
    assert result["count_by_kind"] == {"terminal": 1}
    assert len(result["services"][0]["why_path"]) == 2


def test_enrich_is_idempotent(tmp_path):
    path, *_ = ifc_file(tmp_path)
    project = {"docs": [{"doc_id": "m", "files": {"ifc": str(path)}}]}
    graph = {"nodes": [], "edges": []}
    enrich(graph, project, tmp_path)
    counts = (len(graph["nodes"]), len(graph["edges"]))
    enrich(graph, project, tmp_path)
    assert (len(graph["nodes"]), len(graph["edges"])) == counts


def test_optional_pdf_adapter_clips_lengths_and_cites_original_sheet(tmp_path, monkeypatch):
    """Generated-for-demo vector results stand in for Awais's read-only API."""
    import sys
    import time
    from types import SimpleNamespace
    from engine.kg.mep_sheets import enrich_sheets
    for did in ("arch", "services"):
        folder = tmp_path / did
        folder.mkdir()
        (folder / "source.pdf").write_bytes(b"generated for demo; API stub owns parsing")
        pm = {"page": 1, "image": {"w": 100, "h": 100},
              "scale": {"m_per_px": .01, "method": "dimension", "confidence": 1},
              "items": [{"item_id": "room", "bbox_px": [10, 10, 30, 30],
                         "polygon_px": [[10, 10], [30, 10], [30, 30], [10, 30]]}]}
        (folder / "planmap-1.json").write_text(json.dumps(pm))
    T = {"s": 1, "R": [[1, 0], [0, 1]], "t": [0, 0], "matches": 5, "residual": .1}
    api = SimpleNamespace(load=lambda *args, **kw: {"W_pt": 100, "H_pt": 100},
                          align=lambda *args: T, split_mep=lambda *args, **kw: {"mep": [True]},
                          ducts=lambda *args: [{"start_pt": [0, 20], "end_pt": [40, 20], "width_m": .05}],
                          terminals=lambda *args: [{"center_pt": [20, 20], "size_pt": 2, "airflow_ls": 5}])
    monkeypatch.setitem(sys.modules, "pipeline.pdf_mep", api)
    graph = {"nodes": [node("room", "arch", "room", label="Office"),
                       node("room", "services", "room", label="Office")], "edges": []}
    project = {"docs": [{"doc_id": "arch", "title": "Architectural plan", "files": {"pdf": "source.pdf"}},
                         {"doc_id": "services", "title": "Ventilation", "files": {"pdf": "source.pdf"}}]}
    enrich_sheets(Writer(graph), project, tmp_path, time.monotonic() + 10)
    assert len([e for e in graph["edges"] if e["kind"] == "same_as"]) == 1
    result = room_services(graph, "room:arch:room")
    assert result["count_by_kind"] == {"duct": 1, "terminal": 1}
    assert result["length_m_by_kind"]["duct"] == pytest.approx(.2)
    duct = next(s for s in result["services"] if s["node"]["kind"] == "duct")
    assert duct["element_length_m"] == pytest.approx(.4)
    assert duct["source"]["doc_id"] == "services" and duct["source"]["bbox"][1] < duct["source"]["bbox"][3]
    assert all(s["confidence"] < .6 for s in result["services"])
