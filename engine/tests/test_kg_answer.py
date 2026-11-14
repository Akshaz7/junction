"""Contract truth fixtures are generated for demo, not real drawing accuracy."""
import copy
import json
from pathlib import Path

import pytest

from engine.kg_answer import answer
from engine.kg_impact import impact, paths

ROOT = Path(__file__).resolve().parents[2]
PROJECT = {"id": "contract-project", "docs": [{"doc_id": "architecture"}, {"doc_id": "plan"}, {"doc_id": "services"}]}
QUESTIONS = json.loads((ROOT / "results/final/KG-ANSWER/questions.json").read_text())["questions"]


@pytest.fixture
def graph():
    """Explicit fixture quantities: wall length 10 m, ceiling 3 m, door 2.6 m."""
    nodes, edges = [], []

    def node(local, kind, label, doc="architecture", level="Level 2", **props):
        nid = f"{kind}:{doc}:{local}"
        nodes.append({"id": nid, "kind": kind, "label": label, "doc_ids": [doc], "level": level,
                      "props": props, "source": {"doc_id": doc, "page": 1, "item_id": local, "bbox": [1, 2, 10, 20]},
                      "canonical": None, "degree": 0})
        return nid

    def edge(kind, a, b, conf=1, **evidence):
        eid = f"edge-{len(edges)}"
        edges.append({"id": eid, "kind": kind, "from": a, "to": b, "method": "ifc_relation" if conf == 1 else "tag_text",
                      "confidence": conf, "evidence": evidence or {"relation": kind}, "doc_ids": []})
        return eid

    room = node("r1", "room", "Office A101", number="A101", ceiling_height_m=3.0)
    room2 = node("r2", "room", "Room B202", number="B202")
    planroom = node("rp1", "room", "Office A101", "plan", number="A101")
    wall = node("w1", "wall", "Wall W4", tag="W4", length_m=10.0, height_m=3.0, material="gypsum")
    wall2 = node("w2", "wall", "Wall W5", tag="W5")
    door = node("d1", "door", "Door D12", tag="D12", height_m=2.6)
    plandoor = node("dp1", "door", "Door D12", "plan", tag="D12")
    duct = node("v1", "duct", "Duct V1", "services", tag="V1", length_m=5.0)
    duct2 = node("v2", "duct", "Duct V2", "services", tag="V2")
    terminal = node("t1", "terminal", "Supply outlet S1", "services", tag="S1")
    system = node("sys", "system", "Supply air", "services")
    win = node("win", "window", "Window N1")
    planwin = node("winp", "window", "Window N1", "plan")
    door2 = node("d2", "door", "Door D13")
    plandoor2 = node("dp2", "door", "Door D13", "plan")
    edge("bounds", wall, room)
    edge("bounds", wall2, room2)
    edge("hosted_by", door, wall)
    edge("in_room", door, room)
    edge("in_room", duct, room, .9)
    edge("serves", terminal, room, .8)
    edge("connects", duct, duct2)
    edge("part_of_system", duct, system)
    edge("same_as", door, plandoor, .85)
    edge("same_as", room, planroom, .9)
    edge("agrees", door, plandoor, .85, item_kind="door", metric="height_m", values=[2.6, 2.6])
    edge("differs", door2, plandoor2, .85, item_kind="door", metric="width_m", values=[.9, 1.0])
    edge("agrees", win, planwin, .9, item_kind="window", metric="count", values=[1, 1])
    edge("differs", room, planroom, .8, item_kind="room", metric="area_m2", values=[30, 32])
    return {"project_id": PROJECT["id"], "version": 1, "nodes": nodes, "edges": edges, "stats": {}}


@pytest.mark.parametrize("case", QUESTIONS, ids=lambda c: str(c["id"]))
def test_project_question_contract(case, graph):
    result = answer(case["question"], PROJECT, ROOT, graph=graph)
    expect = case["expect"]
    data = result["graph_answer"]
    assert data["shape"] == expect["shape"]
    assert result["cost"] == {"usd_total": 0, "calls": []}
    assert result["answer"]["text_md"].startswith("**")
    assert len([ln for ln in result["answer"]["text_md"].splitlines() if ln.startswith("- ")]) <= 4
    if "value" in expect:
        assert result["answer"]["value"] == expect["value"]
    if "mismatches" in expect:
        assert len(data["mismatches"]) == expect["mismatches"]
        for mismatch in data["mismatches"]:
            assert set(mismatch["doc_ids"]) == {"architecture", "plan"}
            assert len(mismatch["citations"]) >= 2
    if "count" in expect:
        assert len(data["items"]) == expect["count"]
    if "confidence" in expect:
        assert result["answer"]["confidence"] == expect["confidence"]
    if "has_kinds" in expect:
        assert set(expect["has_kinds"]) <= {e["node"]["kind"] for e in data["items"]}
    if "wall_area_delta" in expect:
        assert any(e.get("quantity_delta", {}).get("value") == pytest.approx(expect["wall_area_delta"]) for e in data["items"])
    if "door_exceeds" in expect:
        doors = [e for e in data["items"] if "exceeds_ceiling" in e]
        assert doors and any(e["exceeds_ceiling"] == expect["door_exceeds"] for e in doors)
    if expect.get("quantity_unknown"):
        assert not any(e.get("quantity_delta") for e in data["items"])
    if data["shape"] != "missing":
        path = result["reasoning"]["graph_path"]
        assert path and result["citations"]
        assert result["answer"]["confidence"] == pytest.approx(min(e["confidence"] for e in path))
    else:
        assert result["answer"]["confidence"] == 0
    import jsonschema
    jsonschema.validate(result, json.loads((ROOT / "server/schemas/answer.schema.json").read_text()))


def test_does_not_claim_shared_level_or_system_means_impact(graph):
    before = copy.deepcopy(graph)
    affected = impact(graph, "room:architecture:r1", {"prop": "ceiling_height_m", "value": 2.4})
    ids = {r["node"]["id"] for r in affected}
    assert "room:architecture:r2" not in ids
    assert "duct:services:v2" not in ids  # another duct's connection is not a clearance dependency
    assert "system:services:sys" not in ids
    assert graph == before  # what-if never mutates source data


def test_area_margin_only_when_supported_by_all_input_uncertainties(graph):
    wall = next(n for n in graph["nodes"] if n["label"] == "Wall W4")
    room = next(n for n in graph["nodes"] if n["id"] == "room:architecture:r1")
    room["props"]["ceiling_height_uncertainty_m"] = .01
    wall["props"]["length_uncertainty_m"] = .02
    entries = impact(graph, room["id"], {"prop": "ceiling_height_m", "value": 2.4, "uncertainty_m": .01})
    qty = next(e["quantity_delta"] for e in entries if e["node"]["id"] == wall["id"])
    assert qty["margin"] == pytest.approx(.2124)
    assert qty["prop"] == "plasterboard_area_m2"
    del wall["props"]["material"]
    qty = next(e["quantity_delta"] for e in impact(graph, room["id"], {"prop": "ceiling_height_m", "value": 2.4}) if e["node"]["id"] == wall["id"])
    assert qty["margin"] is None and qty["prop"] == "wall_finish_area_m2"


def test_ambiguous_room_label_requires_scope(graph):
    node = copy.deepcopy(next(n for n in graph["nodes"] if n["id"] == "room:architecture:r1"))
    node.update(id="room:architecture:r9", level="Level 9")
    graph["nodes"].append(node)
    assert answer("What is connected to room A101?", PROJECT, ROOT, graph=graph)["graph_answer"]["shape"] == "missing"
    assert answer("What is connected to room A101 on level 2?", PROJECT, ROOT, graph=graph)["graph_answer"]["shape"] == "connections"


def test_normal_questions_fall_through_without_building_graph(monkeypatch):
    assert answer("How many doors are there?", PROJECT, ROOT) is None
    assert answer("", PROJECT, ROOT) is None


def test_no_links_is_not_a_safety_claim(graph):
    graph["edges"] = []
    graph["nodes"] = [n for n in graph["nodes"] if n["id"] != "door:plan:dp1"]
    result = answer("If door D12 is removed, what is affected?", PROJECT, ROOT, graph=graph)
    assert result["graph_answer"]["shape"] == "missing"
    assert "does not prove" in result["answer"]["text_md"]


def test_widest_path_and_weakest_link(graph):
    graph["edges"].append({"id": "alternative", "kind": "same_as", "from": "door:architecture:d1", "to": "door:plan:dp1", "confidence": .1})
    found = paths(graph, "door:architecture:d1", lambda a, e, b, d: e["kind"] == "same_as", max_depth=None)
    assert found["door:plan:dp1"]["confidence"] == .85
    result = answer("If the ceiling in room A101 drops to 2.4 m, what is affected?", PROJECT, ROOT, graph=graph)
    assert result["answer"]["confidence"] == .8


def test_zero_count_comparison_cites_both_sources_without_inventing_items(graph):
    graph["nodes"].extend([
        {"id": "level:architecture:8", "kind": "level", "label": "Level 8", "level": "Level 8", "doc_ids": ["architecture"], "props": {}},
        {"id": "level:plan:8", "kind": "level", "label": "Level 8", "level": "Level 8", "doc_ids": ["plan"], "props": {}},
    ])
    graph["edges"].append({"id": "zero-doors", "kind": "differs", "from": "level:architecture:8", "to": "level:plan:8",
                           "method": "rule", "confidence": .7, "evidence": {"property": "door_count", "values": [0, 2],
                           "sources": [{"doc_id": "architecture", "item_ids": []}, {"doc_id": "plan", "item_ids": []}]}})
    r = answer("Do the drawings agree on doors on level 8?", PROJECT, ROOT, graph=graph)
    assert r["answer"]["value"] == 0
    assert {c["doc_id"] for c in r["citations"]} == {"architecture", "plan"}
    assert all(c["item_ids"] == [] and c["bbox_px"] is None for c in r["citations"])
    assert "0 versus 2" in r["answer"]["text_md"]


def test_text_reference_counts_as_an_appearance_without_claiming_identity(graph):
    sheet = {"id": "sheet_ref:notes:ref", "kind": "sheet_ref", "label": "Door D12 schedule reference", "doc_ids": ["notes"],
             "props": {}, "source": {"doc_id": "notes", "page": 3, "bbox": [10, 10, 50, 60]}}
    graph["nodes"].append(sheet)
    graph["edges"].append({"id": "reference", "kind": "references", "from": sheet["id"], "to": "door:architecture:d1",
                           "confidence": .7, "method": "label_text", "evidence": {"quote": "D12"}})
    r = answer("Where else does door D12 appear?", PROJECT, ROOT, graph=graph)
    assert r["answer"]["value"] == 2 and r["answer"]["confidence"] == .7
    assert any(s["edge_kind"] == "references" for s in r["reasoning"]["graph_path"])
    assert any(c["doc_id"] == "notes" and c["page"] == 3 for c in r["citations"])
    affected = impact(graph, "door:architecture:d1", {"prop": "removed", "value": True})
    assert any(e["node"]["id"] == sheet["id"] for e in affected)


def test_all_mismatches_are_rendered_with_both_citations(graph):
    mismatch = copy.deepcopy(next(e for e in graph["edges"] if e["kind"] == "differs" and e["evidence"]["item_kind"] == "door"))
    for i in range(5):
        graph["edges"].append({**mismatch, "id": "extra-" + str(i)})
    r = answer("Do the drawings agree on doors?", PROJECT, ROOT, graph=graph)
    rows = [ln for ln in r["answer"]["text_md"].splitlines() if ln.startswith("| Door D13")]
    assert len(rows) == 6
    assert all("[" in ln and ln.count("[") >= 2 for ln in rows)


@pytest.mark.parametrize("level", ["2. Obergeschoss", "3. kerros", "Våning 2"])
def test_multilingual_level_labels_remain_resolvable(graph, level):
    for n in graph["nodes"]:
        n["level"] = level
    r = answer(f"Do the drawings agree on doors on {level}?", PROJECT, ROOT, graph=graph)
    assert r["answer"]["value"] == 50


def test_room_number_and_name_are_used_together(graph):
    graph["nodes"].append({"id": "room:architecture:other", "kind": "room", "label": "Office A101", "level": "Level 2",
                           "doc_ids": ["architecture"], "props": {"number": "A199"}})
    # The tagged room has more specific evidence than another room sharing its label.
    r = answer("What is connected to room A101?", PROJECT, ROOT, graph=graph)
    assert r["graph_answer"]["shape"] == "connections"


def test_path_depth_budget_keeps_a_shorter_lower_confidence_route():
    g = {"nodes": [{"id": s} for s in "ABCDE"], "edges": []}
    for a, b, c in [("A", "B", .9), ("B", "C", .9), ("A", "C", .7), ("C", "D", 1), ("D", "E", 1)]:
        g["edges"].append({"id": a+b, "from": a, "to": b, "confidence": c})
    hits = paths(g, "A", lambda *a: True, max_depth=3)
    assert hits["E"]["confidence"] == .7
    assert hits["E"]["why_path"] == ["AC", "CD", "DE"]


def test_partial_wall_height_does_not_invent_a_larger_lining_reduction(graph):
    wall = next(n for n in graph["nodes"] if n["label"] == "Wall W4")
    wall["props"]["height_m"] = 2.5
    result = answer("If the ceiling in room A101 drops to 2.4 m, what is affected?", PROJECT, ROOT, graph=graph)
    qty = next(e["quantity_delta"] for e in result["graph_answer"]["items"] if e["node"]["id"] == wall["id"])
    assert qty["value"] == -1
    assert qty["conditional"] is True
    assert "if its full face" in result["answer"]["text_md"]


def test_equivalent_appearances_do_not_double_impact_quantities(graph):
    wall = copy.deepcopy(next(n for n in graph["nodes"] if n["label"] == "Wall W4"))
    wall.update(id="wall:plan:wp4", doc_ids=["plan"], source={"doc_id": "plan", "item_id": "wp4", "page": 1})
    graph["nodes"].append(wall)
    graph["edges"].append({"id": "wall-equivalent", "kind": "same_as", "from": "wall:architecture:w1", "to": wall["id"],
                           "confidence": .88, "method": "tag_text", "evidence": {"tag": "W4"}})
    result = answer("If the ceiling in room A101 drops to 2.4 m, what is affected?", PROJECT, ROOT, graph=graph)
    data = result["graph_answer"]
    assert len(data["items"]) > len(data["distinct_items"])
    assert len([nid for nid in data["distinct_items"] if nid.startswith("wall:")]) == 1
    assert "plan" in {c["doc_id"] for c in result["citations"]}


def test_calibrated_confidence_is_never_rounded_to_certainty(graph):
    for edge in graph["edges"]:
        edge["confidence"] = .9997386304234187
    result = answer("Where else does door D12 appear?", PROJECT, ROOT, graph=graph)
    assert result["answer"]["confidence"] == .9997386304234187
    assert result["reasoning"]["confidence"]["pct"] == 99


def test_graph_builder_failure_stays_honest_and_zero_cost(monkeypatch):
    from engine import kg
    def broken(*a):
        raise RuntimeError("Optional reader cannot open this source")
    monkeypatch.setattr(kg, "build", broken)
    result = answer("Where else does door D12 appear?", PROJECT, ROOT)
    assert result["graph_answer"]["shape"] == "missing"
    assert result["cost"] == {"usd_total": 0, "calls": []}
