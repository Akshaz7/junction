"""Reproduce code/IFC-truth answer checks without writing shared artifacts.

Run from the repository with PYTHONPATH=. and MODELS_FAKE=1 through heavy.sh.
--prepare-development writes truth questions before answering them.
--development evaluates those frozen questions.
--final is the first and only inspection/evaluation of the reserved unseen file.
These checks verify index/graph reasoning, not raster detection accuracy.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from engine.kg.build import build_uncached
from engine.kg.ifc import source_path
from engine.kg_answer import answer

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts"
FZK = "ifc_bench__fzk-house-arc"
VARIANT = "ifc_models__kit-fzk-haus-ac20-fzk-haus"
SWISS = "swiss_dwellings__site1060-bldg2175-floor9833"


def write(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def by_type(f, kind):
    try:
        return f.by_type(kind)
    except RuntimeError:
        return []


def ifc_truth(did, counterpart=None):
    """Read explicit relationships independently of graph-building/query code."""
    import ifcopenshell
    import ifcopenshell.util.element as ue
    f = ifcopenshell.open(str(source_path(did, ARTIFACTS)))
    index = json.loads((ARTIFACTS / did / "elements.json").read_text())["elements"]
    indexed = {e["item_id"] for e in index}
    related, dependents = defaultdict(set), defaultdict(set)
    openings = {r.RelatedOpeningElement.GlobalId: r.RelatingBuildingElement for r in by_type(f, "IfcRelVoidsElement")}
    for r in by_type(f, "IfcRelFillsElement"):
        host = openings.get(r.RelatingOpeningElement.GlobalId)
        obj = r.RelatedBuildingElement
        if host and obj.GlobalId in indexed and host.GlobalId in indexed:
            related[obj.GlobalId].add(host.GlobalId)
            related[host.GlobalId].add(obj.GlobalId)
            dependents[host.GlobalId].add(obj.GlobalId)
    for r in by_type(f, "IfcRelSpaceBoundary"):
        a, b = r.RelatedBuildingElement, r.RelatingSpace
        if a and b and a.GlobalId in indexed and b.GlobalId in indexed:
            related[a.GlobalId].add(b.GlobalId)
            related[b.GlobalId].add(a.GlobalId)
            dependents[a.GlobalId].add(b.GlobalId)
    docs = [did] + ([counterpart] if counterpart else [])
    project = {"id": "kg-answer-" + did, "docs": [{"doc_id": d} for d in docs]}
    choices = []
    for cls, kind in [("IfcDoor", "door"), ("IfcWall", "wall"), ("IfcColumn", "column"), ("IfcSlab", "slab")]:
        elements = [e for e in by_type(f, cls) if e.GlobalId in indexed]
        labels = Counter(str(e.Name) for e in elements if e.Name)
        tags = Counter(str(getattr(e, "Tag", None)) for e in elements if getattr(e, "Tag", None))
        for e in elements:
            # Unique, explicit labels/tags only. No GUIDs or ordinal guessing.
            label = e.Name if e.Name and labels[e.Name] == 1 else getattr(e, "Tag", None)
            if not label or (label != e.Name and tags[str(label)] != 1):
                continue
            if kind not in ("door", "wall"):
                continue
            choices.append((e, kind, str(label)))
            if len(choices) == 3:
                break
        if len(choices) == 3:
            break
    questions = []
    for e, kind, label in choices:
        questions.append({"question": f"What is connected to {kind} {label}?", "doc_id": did,
                          "expect": {"shape": "connections" if related[e.GlobalId] or ue.get_type(e) or ue.get_material(e) else "either",
                                     "required_source_item_ids": sorted(related[e.GlobalId])},
                          "truth": "IFC fills/voids and space-boundary relationships; type/material associations are additional connections"})
        if kind == "wall":
            questions.append({"question": f"If wall {label} moves, what is affected?", "doc_id": did,
                              "expect": {"shape": "impact" if dependents[e.GlobalId] else "either",
                                         "required_source_item_ids": sorted(dependents[e.GlobalId])},
                              "truth": "IFC host openings and bounded spaces"})
        else:
            questions.append({"question": f"If door {label} is removed, what is affected?", "doc_id": did,
                              "expect": {"shape": "impact" if related[e.GlobalId] else "either",
                                         "required_source_item_ids": sorted(related[e.GlobalId])},
                              "truth": "IFC host wall and adjoining spaces"})
        same = False
        if counterpart:
            other = json.loads((ARTIFACTS / counterpart / "elements.json").read_text())["elements"]
            same = e.GlobalId in {x["item_id"] for x in other}
        questions.append({"question": f"Where else does {kind} {label} appear?", "doc_id": did,
                          "expect": {"shape": "appearances" if same else "missing"}, "truth": "IFC GlobalId in the counterpart index"})
    comparison = {"shape": "missing"}
    if counterpart:
        from engine.projects.roles import level_ordinal
        other = json.loads((ARTIFACTS / counterpart / "elements.json").read_text())["elements"]
        def ground_doors(elements):
            return {x["item_id"] for x in elements if x.get("kind") == "door"
                    and level_ordinal((x.get("storey") or {}).get("name")) == 0}
        a, b = ground_doors(index), ground_doors(other)
        comparison = {"shape": "agreement", "value": 100.0 if len(a) == len(b) else 0.0}
    questions.append({"question": "Do the drawings agree on doors on the ground floor?", "doc_id": did,
                      "expect": comparison,
                      "truth": "Ground-floor door counts computed independently from both source indexes" if counterpart else "One source document has no cross-file comparison"})
    return {"project": project, "questions": questions, "source_schema": f.schema, "source_file": str(source_path(did, ARTIFACTS)).split('/data/')[-1]}


def swiss_truth():
    """Exact centres/polygons from the existing DXF extraction; no detection claims."""
    from shapely.geometry import Polygon, Point
    pm = json.loads((ARTIFACTS / SWISS / "planmap-1.json").read_text())
    rooms = [i for i in pm["items"] if i["kind"] == "room" and i.get("polygon_px")]
    polygons = {r["item_id"]: Polygon(r["polygon_px"]).buffer(0) for r in rooms}
    picked = [r for r in rooms if r.get("props", {}).get("number")][:5]
    questions = []
    for room in picked:
        label = room["props"]["number"]
        ids = []
        for item in pm["items"]:
            if item["kind"] in ("room", "wall", "text", "label", "annotation", "dimension") or not item.get("bbox_px"):
                continue
            x0,y0,x1,y1 = item["bbox_px"]
            pt = Point((x0+x1)/2, (y0+y1)/2)
            hits = [rid for rid, poly in polygons.items() if poly.covers(pt)]
            if hits == [room["item_id"]]:
                ids.append(item["item_id"])
        questions.append({"question": f"What is connected to room {label}?", "doc_id": SWISS,
                          "expect": {"shape": "connections" if ids else "missing", "required_source_item_ids": sorted(ids)},
                          "truth": "Unambiguous physical CAD item centres inside the extracted room polygon; annotation text is not a physical connection"})
        questions.append({"question": f"Where else does room {label} appear?", "doc_id": SWISS,
                          "expect": {"shape": "missing"}, "truth": "Single-source project has no cross-file identity/reference evidence"})
    return {"project": {"id": "kg-answer-dxf", "docs": [{"doc_id": SWISS}]}, "questions": questions, "source_format": "dxf"}


def evaluate(sets):
    import jsonschema
    schema = json.loads((ROOT / "server/schemas/answer.schema.json").read_text())
    reports = []
    for case_set in sets:
        project = case_set["project"]
        start = time.perf_counter()
        graph = build_uncached(project, ARTIFACTS)
        elapsed = time.perf_counter() - start
        rows = []
        for case in case_set["questions"]:
            result = answer(case["question"], project, ARTIFACTS, graph=graph)
            data, exp = result["graph_answer"], case["expect"]
            try:
                jsonschema.validate(result, schema)
                assert exp["shape"] == "either" or data["shape"] == exp["shape"], (exp["shape"], data["shape"])
                if "value" in exp:
                    assert result["answer"]["value"] == exp["value"]
                sourced = {e["node"].get("source", {}).get("item_id") for e in data.get("items", [])
                           if (e["node"].get("source") or {}).get("doc_id") == case["doc_id"]}
                assert set(exp.get("required_source_item_ids", [])) <= sourced, sorted(set(exp.get("required_source_item_ids", [])) - sourced)
                assert result["cost"] == {"usd_total": 0, "calls": []}
                path = result["reasoning"]["graph_path"]
                assert result["answer"]["confidence"] <= min((p["confidence"] for p in path), default=0) + .0005
                ok, error = True, None
            except AssertionError as exc:
                ok, error = False, str(exc)
            rows.append({"question": case["question"], "pass": ok, "error": error, "shape": data["shape"],
                         "value": result["answer"]["value"], "confidence": result["answer"]["confidence"],
                         "citations": len(result["citations"]), "graph_path_edges": len(result["reasoning"]["graph_path"])})
        reports.append({"project": project, "source_schema": case_set.get("source_schema"),
                        "nodes": len(graph["nodes"]), "edges": len(graph["edges"]), "build_s": round(elapsed, 3),
                        "passed": sum(r["pass"] for r in rows), "total": len(rows), "questions": rows})
    return reports


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare-development", "development", "final"])
    mode = parser.parse_args().mode
    if mode == "prepare-development":
        write("real-development-questions.json", [ifc_truth(FZK, VARIANT), swiss_truth()])
        print("Prepared independent IFC/CAD truth questions; no answer code executed.")
        return
    if mode == "development":
        reports = evaluate(json.loads((OUT / "real-development-questions.json").read_text()))
        write("real-development-results.json", reports)
    else:
        # This is intentionally delayed until development is complete.
        selection = json.loads((OUT / "selection.json").read_text())
        reserved = ifc_truth(selection["unseen_doc_id"])
        write("unseen-questions.json", reserved)
        reports = evaluate([reserved])
        write("unseen-results.json", reports)
    for report in reports:
        print(f"{report['project']['id']}: {report['passed']}/{report['total']}, {report['build_s']} s")
        for row in report["questions"]:
            if not row["pass"]:
                print(row["question"], row["error"])


if __name__ == "__main__":
    main()
