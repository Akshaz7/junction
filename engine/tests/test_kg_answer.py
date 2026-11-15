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
        nodes = {n["id"]: n for n in graph["nodes"]}
        for step in path:
            assert step["from_label"] == nodes[step["from_id"]]["label"]
            assert step["to_label"] == nodes[step["to_id"]]["label"]
            assert any(e["from"] == step["from_id"] and e["to"] == step["to_id"]
                       and e["kind"] == step["edge_kind"] for e in graph["edges"])
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
    reference = next(s for s in r["reasoning"]["graph_path"] if s["edge_kind"] == "references")
    # Lookup traverses this incoming edge from the door, but IDs keep the source edge direction.
    assert (reference["from_id"], reference["to_id"]) == (sheet["id"], "door:architecture:d1")
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


def test_conflicting_ceiling_notes_are_cited_without_taking_off_a_guess(graph):
    room = next(n for n in graph["nodes"] if n["id"] == "room:architecture:r1")
    room["props"].update(ceiling_height_note="Recorded ceiling heights differ", ceiling_height_notes=[
        {"ceiling_height_m": 2.8, "source": {"doc_id": "notes", "page": 2, "bbox": [10, 10, 20, 20], "quote": "A101 ceiling 2.8 m"}}
    ])
    r = answer("If the ceiling in room A101 drops to 2.4 m, what is affected?", PROJECT, ROOT, graph=graph)
    assert not any(e.get("quantity_delta") for e in r["graph_answer"]["items"])
    assert any(c["doc_id"] == "notes" and c["quote"] == "A101 ceiling 2.8 m" for c in r["citations"])
    assert "heights disagree" in r["answer"]["text_md"]


@pytest.fixture
def count_graph(graph):
    """Generated contract case: independent model/plan, one unlinked extra door."""
    graph["edges"] = [e for e in graph["edges"] if e["kind"] not in ("agrees", "differs")]
    for d, role, label in [("architecture", "model", "Building model"), ("plan", "plan", "Ground floor plan")]:
        graph["nodes"].extend([
            {"id": f"doc:{d}:root", "kind": "doc", "label": label, "doc_ids": [d], "props": {"role": role}},
            {"id": f"level:{d}:2", "kind": "level", "label": "Second floor", "level": "Second floor", "doc_ids": [d], "props": {}},
        ])
    extra = copy.deepcopy(next(n for n in graph["nodes"] if n["id"] == "door:plan:dp2"))
    extra.update(id="door:plan:extra", label="Extra door", source={"doc_id": "plan", "page": 3, "item_id": "extra"})
    graph["nodes"].append(extra)
    return graph


@pytest.mark.parametrize("q", [
    "Do the plan and model agree on doors on level 2?",
    "Does the plan match the model on doors on the second floor?",
    "Compare doors per floor across files.",
    "Which files disagree on doors?",
])
def test_missing_checks_are_computed_from_all_source_items(count_graph, q):
    before = copy.deepcopy(count_graph)
    r = answer(q, PROJECT, ROOT, graph=count_graph)
    assert r["graph_answer"]["computed_checks"] == 1
    assert r["answer"]["value"] == 0
    m = r["graph_answer"]["mismatches"][0]
    assert m["evidence"]["values"] == [2, 3]  # includes unlinked extra, not just matched pairs
    assert set(m["doc_ids"]) == {"architecture", "plan"}
    assert {e["edge_kind"] for e in r["reasoning"]["graph_path"]} == {"same_as", "differs"}
    assert r["answer"]["confidence"] == min(e["confidence"] for e in r["reasoning"]["graph_path"])
    assert count_graph == before


def test_comparison_does_not_invent_zero_for_missing_extraction(count_graph):
    count_graph["nodes"] = [n for n in count_graph["nodes"] if n.get("kind") != "door" or "plan" not in n.get("doc_ids", [])]
    r = answer("Do the plan and model agree on doors?", PROJECT, ROOT, graph=count_graph)
    assert r["graph_answer"]["shape"] == "missing"


def test_derived_count_comparisons_disclose_dependency(count_graph):
    next(n for n in count_graph["nodes"] if n["id"] == "doc:plan:root")["props"]["derived"] = True
    r = answer("Does the plan match the model on doors?", PROJECT, ROOT, graph=count_graph)
    assert "not an independent drawing check" in r["answer"]["text_md"]
    assert r["graph_answer"]["comparisons"][0]["evidence"]["derived"] is True


def test_no_identity_link_does_not_compare_unrelated_files(count_graph):
    count_graph["edges"] = [e for e in count_graph["edges"] if e["kind"] != "same_as"]
    r = answer("Compare doors across files.", PROJECT, ROOT, graph=count_graph)
    assert r["graph_answer"]["shape"] == "missing"


def test_zero_on_known_level_is_valid_but_not_missing_kind_coverage(count_graph):
    for n in count_graph["nodes"]:
        if n["kind"] == "door" and "architecture" in n["doc_ids"]:
            n["level"] = "Third floor"
    # Rooms still establish this floor's cross-file identity; doors are extracted
    # elsewhere in the model, so the known second-floor absence is countable.
    r = answer("Compare doors across files on level 2.", PROJECT, ROOT, graph=count_graph)
    m = r["graph_answer"]["mismatches"][0]
    assert m["evidence"]["values"] == [0, 3]
    assert {c["doc_id"] for c in r["citations"]} == {"architecture", "plan"}


def test_ambiguous_appearances_list_identity_groups_and_pages(graph):
    for did, iid in [("architecture", "upper"), ("plan", "upper-plan")]:
        graph["nodes"].append({"id": f"door:{did}:{iid}", "kind": "door", "label": "Door D12", "doc_ids": [did],
                               "level": "Level 9", "props": {}, "source": {"doc_id": did, "page": 9, "item_id": iid}})
    graph["edges"].append({"id": "upper-same", "kind": "same_as", "from": "door:architecture:upper", "to": "door:plan:upper-plan",
                           "method": "guid", "confidence": .93})
    r = answer("Where else does door D12 appear?", PROJECT, ROOT, graph=graph)
    assert r["graph_answer"]["shape"] == "appearances"
    assert len(r["graph_answer"]["groups"]) == 2
    assert r["answer"]["value"] == 2
    assert {c["page"] for c in r["citations"]} == {1, 9}
    assert "page 9" in r["answer"]["text_md"]
    assert "2 distinct items" in r["answer"]["text_md"]
    scoped = answer("Where else does door D12 appear on level 9?", PROJECT, ROOT, graph=graph)
    assert len(scoped["graph_answer"]["groups"]) == 1


def test_unlinked_ambiguous_appearances_are_listed_without_identity_claim(graph):
    graph["edges"] = [e for e in graph["edges"] if e["kind"] != "same_as"]
    r = answer("Where else does door D12 appear?", PROJECT, ROOT, graph=graph)
    assert len(r["graph_answer"]["groups"]) == 2
    assert len(r["citations"]) == 2
    assert r["answer"]["confidence"] == 0
    assert r["graph_answer"]["items"] == []


@pytest.mark.parametrize("label", ["Flur EG Eingang", "Entré hall", "Sisäänkäynti käytävä"])
def test_general_room_vocabulary_supports_ceiling_dependencies(graph, label):
    for n in graph["nodes"]:
        if n["kind"] == "room" and "A101" in n["label"]:
            n["label"] = label
            n["props"].pop("number", None)
    r = answer("If the ceiling in the entrance hall drops to 2.4 m what is affected?", PROJECT, ROOT, graph=graph)
    assert r["graph_answer"]["shape"] == "impact"
    assert r["reasoning"]["graph_path"]


def test_proposed_dimension_cannot_resolve_a_room_number(graph):
    for n in graph["nodes"]:
        if n["kind"] == "room":
            n["props"]["number"] = "4"
    r = answer("If the ceiling in the unknown hall drops to 2.4 m what is affected?", PROJECT, ROOT, graph=graph)
    assert r["graph_answer"]["shape"] == "missing"


def test_same_ifc_element_on_two_pages_does_not_create_room_ambiguity(graph):
    origin = next(n for n in graph["nodes"] if n["id"] == "room:architecture:r1")
    origin["props"]["ifc_class"] = "IfcSpace"
    extra = copy.deepcopy(origin)
    extra.update(id=origin["id"] + ":p9", level=None)
    extra["source"]["page"] = 9
    extra["props"] = {"ifc_class": "IfcSpace"}
    graph["nodes"].append(extra)
    assert answer("If the ceiling in Office A101 drops to 2.4 m what is affected?", PROJECT, ROOT, graph=graph)["graph_answer"]["shape"] == "impact"
    # Removing the IFC identity proof leaves independent page-local records.
    origin["props"].pop("ifc_class")
    extra["props"].clear()
    assert answer("If the ceiling in Office A101 drops to 2.4 m what is affected?", PROJECT, ROOT, graph=graph)["graph_answer"]["shape"] == "missing"


def test_file_links_names_the_files_of_a_linked_item(graph):
    r = answer("Tell me about Office A101, how does it link to all its files?", PROJECT, ROOT, graph=graph)
    assert r is not None and r["graph_answer"]["shape"] == "file_links"
    assert set(r["graph_answer"]["linked_docs"]) >= {"plan"}
    assert "across 2 files" in r["answer"]["text_md"] and "same as" in r["answer"]["text_md"]


def test_file_links_without_identity_link_lists_files_on_same_level(graph):
    r = answer("Which files link to Room B202?", PROJECT, ROOT, graph=graph)
    assert r is not None and r["graph_answer"]["shape"] == "file_links"
    assert r["graph_answer"]["linked_docs"] == []
    assert "No recorded link" in r["answer"]["text_md"] and "same level" in r["answer"]["text_md"]


def test_file_links_ignores_ordinary_questions(graph):
    assert answer("How many doors are on level 2?", PROJECT, ROOT, graph=graph) is None
