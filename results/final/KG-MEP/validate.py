"""Read-only real-source validation. Run through scripts/heavy.sh; writes only this output folder."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import tempfile
import time
from collections import Counter
from pathlib import Path

from engine.kg.build import build_uncached
from engine.kg.mep import read_json, resolve_source, room_services


def save(output, name, value):
    (output / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def summary(docs, root):
    start = time.monotonic()
    graph = build_uncached({"id": "mep-read-only-validation", "docs": [{"doc_id": n} for n in docs]}, root)
    build_s = time.monotonic() - start
    stats = {k: v for k, v in graph["stats"].items() if k != "unlinked"}
    rooms = [n for n in graph["nodes"] if n["kind"] == "room"]
    linked = [room_services(graph, n["id"]) for n in rooms]
    node_ids = {n["id"] for n in graph["nodes"]}
    return {"docs": docs, "build_seconds": round(build_s, 3), "stats": stats,
            "mep": graph.get("mep"), "rooms_with_services": sum(bool(r["services"]) for r in linked),
            "declared_ceiling_heights": sum(bool(n["props"].get("ceiling_height_m")) for n in rooms),
            "services_lengths_known": sum(bool(n["props"].get("length_m")) for n in graph["nodes"] if n["kind"] in {"pipe", "duct"}),
            "dangling_edges": sum(e["from"] not in node_ids or e["to"] not in node_ids for e in graph["edges"]),
            "unknown_length_note": "Whole-element lengths are not lengths inside a room; unrecorded ceilings stay unknown."}


def source_audit(root, docs):
    import ifcopenshell
    import ifcopenshell.util.element as ue
    checks = []
    for index, did in enumerate(docs):
        graph = build_uncached({"id": "mep-source-audit", "docs": [{"doc_id": did}]}, root)
        nodes = {n["id"]: n for n in graph["nodes"]}
        f = ifcopenshell.open(str(resolve_source(read_json(root / did / "doc.json", {}), root, "ifc")))
        owners = {}
        for rel in f.by_type("IfcRelConnectsPortToElement"):
            owners[rel.RelatingPort.GlobalId] = rel.RelatedElement.GlobalId
        for rel in f.by_type("IfcRelNests"):
            for p in rel.RelatedObjects:
                if p.is_a("IfcDistributionPort"):
                    owners[p.GlobalId] = rel.RelatingObject.GlobalId
        ports = [e for e in graph["edges"] if e["kind"] == "connects" and e["evidence"].get("relation") == "IfcRelConnectsPorts"]
        for edge in ports[:3 if index == 0 else 2]:
            rel = f.by_guid(edge["evidence"]["relation_id"])
            a, b = nodes[edge["from"]], nodes[edge["to"]]
            expected = {owners.get(rel.RelatingPort.GlobalId), owners.get(rel.RelatedPort.GlobalId)}
            actual = {a["source"]["item_id"], b["source"]["item_id"]}
            checks.append({"doc_id": did, "kind": "connects", "edge_id": edge["id"], "source_relation": str(rel),
                           "actual_labels": [a["label"], b["label"]],
                           "source_owners": [str(f.by_guid(i)) for i in sorted(expected) if i], "source_agrees": actual == expected})
        if index == 0:
            systems = [e for e in graph["edges"] if e["kind"] == "part_of_system" and e["method"] == "tag_text"]
            for edge in systems[:2]:
                a, b = nodes[edge["from"]], nodes[edge["to"]]
                ps = ue.get_psets(f.by_guid(a["source"]["item_id"]))
                props = [{"pset": pn, "property": k, "value": v} for pn, vals in ps.items() for k, v in vals.items()
                         if v == edge["evidence"]["value"]]
                checks.append({"doc_id": did, "kind": "recorded_system_name", "edge_id": edge["id"],
                               "source_properties": props, "actual_labels": [a["label"], b["label"]], "source_agrees": bool(props)})
        else:
            systems = [e for e in graph["edges"] if e["kind"] == "part_of_system" and e["method"] == "ifc_relation"]
            for edge in systems[:3]:
                a, b = nodes[edge["from"]], nodes[edge["to"]]
                source = b.get("source") or {}
                sid = source.get("item_id") or edge["evidence"].get("system_item_id")
                system = f.by_guid(sid)
                memberships = [r for r in system.IsGroupedBy if any(getattr(o, "GlobalId", None) == a["source"]["item_id"] for o in r.RelatedObjects)]
                checks.append({"doc_id": did, "kind": "part_of_system", "edge_id": edge["id"],
                               "source_system": str(system), "source_member": str(f.by_guid(a["source"]["item_id"])),
                               "source_relation_ids": [r.GlobalId for r in memberships],
                               "actual_labels": [a["label"], b["label"]], "source_agrees": bool(memberships)})
    return {"sample_size": len(checks), "source_agreement": sum(c["source_agrees"] for c in checks),
            "scope": "Topology/system-source agreement only. Ten first source records printed for hand inspection; not a random precision estimate. Spatial room assignments are unmeasured estimates.",
            "checks": checks}


def judges(data, output):
    pdfs = sorted(p for p in (data / "judges").glob("*.pdf"))
    installed = importlib.util.find_spec("pipeline.pdf_mep") is not None
    with tempfile.TemporaryDirectory(prefix=".judge-inputs-", dir=output) as tmp:
        root = Path(tmp)
        docs = []
        for i, path in enumerate(pdfs):
            did = f"judge-local-{i}"
            meta = {"doc_id": did, "title": path.stem, "formats": ["pdf"], "kind": "pdf", "pages": 1,
                    "files": {"pdf": str(path.resolve())}}
            (root / did).mkdir()
            (root / did / "doc.json").write_text(json.dumps(meta))
            docs.append(meta)
        graph = build_uncached({"id": "judge-local-read-only", "docs": docs}, root)
    return {"pdf_reader_installed": installed, "sources": [p.name for p in pdfs],
            "status": "adapter_available" if installed else "skipped_optional_reader_missing",
            "service_count": None, "notes": graph.get("mep", {}).get("notes", []),
            "limitation": "No vector extraction claimed without pipeline.pdf_mep; no PDF or drawing copied or committed."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--clinic", nargs="+", required=True)
    parser.add_argument("--ventilation", nargs="+", required=True)
    parser.add_argument("--audit", nargs=2, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, docs in (("clinic_project.json", args.clinic), ("ventilation_project.json", args.ventilation)):
        result = summary(docs, args.root)
        save(args.output, name, result)
        print(json.dumps({"file": name, "seconds": result["build_seconds"], "nodes": result["stats"]["nodes"], "edges": result["stats"]["edges"], "dangling_edges": result["dangling_edges"]}), flush=True)
    audit = source_audit(args.root, args.audit)
    save(args.output, "source_audit.json", audit)
    print(json.dumps(audit, indent=2), flush=True)
    pdf_result = judges(args.data, args.output)
    save(args.output, "judges_pdfs.json", pdf_result)
    print(json.dumps(pdf_result), flush=True)
    # The preselected file is deliberately inspected only after all other checks.
    reserved = read_json(args.output / "heldout.json", {})
    path = Path(reserved["heldout_path"])
    did = path.parent.name + "__" + re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")
    if (args.root / did / "doc.json").exists():
        held = summary([did], args.root)
    else:
        start = time.monotonic()
        from engine.kg.mep import enrich
        graph = enrich({"nodes": [], "edges": []}, {"docs": [{"doc_id": did, "files": {"ifc": str((args.data / path).resolve())}}]}, args.root)
        held = {"docs": [did], "build_seconds": time.monotonic() - start, "mep": graph.get("mep"),
                "nodes": len(graph["nodes"]), "edges": len(graph["edges"])}
    held["reservation"] = reserved
    save(args.output, "unseen_final.json", held)
    print(json.dumps({"unseen": did, "seconds": held["build_seconds"], "mep": held["mep"]}), flush=True)
    assert audit["sample_size"] == 10 and audit["source_agreement"] == 10


if __name__ == "__main__":
    main()
