"""Code-only building-services graph enrichment; source files are always read-only.

Public hooks: enrich(graph, project, root), room_services(graph, room_node_id).
IFC relationships are authoritative. Spatial room assignment is an estimate,
and a pipe passing through a room never implies that it supplies that room.
No geometry conversion, model call, or guessed ceiling height is used here.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter
from pathlib import Path

SERVICE_KINDS = {"duct", "pipe", "terminal", "fixture"}
LENGTH_NAMES = {"length", "netlength", "grosslength"}
CEILING_NAMES = {"finishceilingheight", "ceilingheight", "clearheight", "lichtehöhe",
                 "raumhöhe", "huonekorkeus", "rumshöjd"}


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError, TypeError, UnicodeError):
        return default


def positive(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def node_id(kind, doc_id, local_id):
    return f"{kind}:{doc_id}:{local_id}"


class Writer:
    """Use source identities so enrichment never duplicates a core-created item."""

    def __init__(self, graph):
        self.graph = graph
        self.nodes = {n["id"]: n for n in graph.setdefault("nodes", [])}
        self.items = {(s.get("doc_id"), s.get("item_id")): n
                      for n in self.nodes.values() if (s := n.get("source")) and s.get("item_id")}
        self.paged_items = {(s.get("doc_id"), s.get("item_id"), s.get("page", 1)): n
                            for n in self.nodes.values() if (s := n.get("source")) and s.get("item_id")}
        self.edges = {(e["kind"], e["from"], e["to"]) for e in graph.setdefault("edges", [])}
        self.docs = {did: n for n in self.nodes.values() if n["kind"] == "doc" for did in n.get("doc_ids", [])}
        self.renamed = {}

    def node(self, kind, did, local, label, props=None, level=None, page=1, bbox=None):
        nid = node_id(kind, did, local)
        n = self.paged_items.get((did, local, page))
        if n is None:
            n = self.nodes.get(nid)
            if n and n.get("source") and n["source"].get("page", 1) != page:
                nid += f":p{page}"
                n = self.nodes.get(nid)
        if n is None:
            n = {"id": nid, "kind": kind, "label": label, "doc_ids": [did], "level": level,
                 "props": {}, "source": {"doc_id": did, "page": page, "item_id": local, "bbox": bbox},
                 "canonical": None, "degree": 0}
            self.nodes[nid] = n
            self.items[did, local] = n
            self.paged_items[did, local, page] = n
            self.graph["nodes"].append(n)
        if kind in SERVICE_KINDS and n["kind"] != kind:
            # IFC2x3 often exports all terminals as generic objects in elements.json.
            old_id = n["id"]
            self.renamed[old_id] = nid
            self.nodes.pop(old_id, None)
            n["id"] = nid
            n["kind"] = kind
            self.nodes[nid] = n
        if n.get("source") is None:
            n["source"] = {"doc_id": did, "page": page, "item_id": local, "bbox": bbox}
            self.items[did, local] = n
            self.paged_items[did, local, page] = n
        n.setdefault("props", {}).update(props or {})
        if level and not n.get("level"):
            n["level"] = level
        return n

    def edge(self, kind, a, b, method, confidence, evidence):
        if not a or not b or a["id"] == b["id"]:
            return
        key = (kind, a["id"], b["id"])
        if kind in {"connects", "same_as"} and (kind, b["id"], a["id"]) in self.edges:
            return
        if key in self.edges:
            return
        self.edges.add(key)
        eid = hashlib.sha256(json.dumps(key).encode()).hexdigest()[:20]
        if confidence < 1:
            evidence.setdefault("calibration", "Uncalibrated services inference; estimate.")
        self.graph["edges"].append({"id": f"mep:{eid}", "kind": kind, "from": a["id"], "to": b["id"],
                                    "method": method, "confidence": confidence, "evidence": evidence,
                                    "doc_ids": sorted(set(a.get("doc_ids", []) + b.get("doc_ids", [])))})

    def doc_link(self, n, did):
        doc = self.docs.get(did) or self.nodes.get(f"doc:{did}")
        self.edge("contains", doc, n, "rule", 1.0, {"rule": "source document", "doc_id": did})

    def finish(self):
        for edge in self.graph["edges"]:
            edge["from"] = self.renamed.get(edge["from"], edge["from"])
            edge["to"] = self.renamed.get(edge["to"], edge["to"])
        for n in self.graph["nodes"]:
            n["canonical"] = self.renamed.get(n.get("canonical"), n.get("canonical"))


def resolve_source(meta, root, fmt):
    """Registry paths are relative to dataset root; uploads may be absolute."""
    raw = (meta.get("files") or {}).get(fmt)
    if isinstance(raw, dict):
        raw = raw.get("path")
    if not isinstance(raw, str) or not raw:
        return None
    p = Path(raw)
    root = Path(root)
    if p.is_absolute():
        return p if p.is_file() else None
    bases = [root / str(meta.get("doc_id", "")), root, root.parent,
             root.parent / "data" / "junction-dataset-preview",
             root.parent / "data" / "full" / "junction-dataset"]
    return next((base / p for base in bases if (base / p).is_file()), None)


def cache_dependencies(project, root):
    """Include optional-reader installation and original sheet/source modifications."""
    base = Path(__file__).resolve().parents[2]
    paths = [base / "pipeline" / "pdf_mep.py", base / "pipeline" / "pdf_vector.py", base / "engine" / "mep.py"]
    for doc in project.get("docs", []):
        doc = {"doc_id": doc} if isinstance(doc, str) else doc
        did = doc.get("doc_id")
        if not did or Path(did).name != did or did in {".", ".."}:
            continue
        meta = {**read_json(Path(root) / did / "doc.json", {}), **doc}
        for fmt in ("ifc", "pdf"):
            if path := resolve_source(meta, root, fmt):
                paths.append(path)
    return paths


def _by_type(f, cls):
    try:
        return f.by_type(cls)
    except RuntimeError:  # schema may not define the IFC4 class
        return []


def _kind(el, ue):
    from engine.mep import _classify, AMBIGUOUS_FIXTURES
    k = _classify(el, ue.get_type(el), ue.get_psets(el))
    if k in {"pipe", "pipe_fitting"}:
        return "pipe"
    if k in {"duct", "duct_fitting"}:
        return "duct"
    if k in AMBIGUOUS_FIXTURES:
        return "fixture"
    # FlowTerminal covers IFC2x3 and all typed IFC4 terminal subclasses.
    if el.is_a("IfcFlowTerminal"):
        return "terminal"
    return "fixture"  # Other distribution equipment still carries ports/system membership.


def _unit_scale(unit, project_scale):
    if unit is None:
        return project_scale
    import ifcopenshell.util.unit as uu
    if unit.is_a("IfcSIUnit"):
        return uu.get_prefix_multiplier(unit.Prefix)
    if unit.is_a("IfcConversionBasedUnit"):
        factor = unit.ConversionFactor
        return float(factor.ValueComponent.wrappedValue) * _unit_scale(factor.UnitComponent, 1.0)
    return None


def _measures(el, scale):
    """Lengths in declared units only; generic 'Height' is not clear ceiling height."""
    result = {}
    for rel in getattr(el, "IsDefinedBy", ()) or ():
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        ps = rel.RelatingPropertyDefinition
        values = getattr(ps, "Quantities", None) or getattr(ps, "HasProperties", ()) or ()
        for value in values:
            name = re.sub(r"[\s_\-]", "", value.Name or "").casefold()
            key = "length_m" if name in LENGTH_NAMES else "ceiling_height_m" if name in CEILING_NAMES else None
            if key is None:
                continue
            raw = getattr(value, "LengthValue", None)
            nominal = getattr(value, "NominalValue", None)
            if raw is None and nominal is not None and nominal.is_a() in {"IfcLengthMeasure", "IfcPositiveLengthMeasure"}:
                raw = nominal.wrappedValue
            factor = _unit_scale(getattr(value, "Unit", None), scale)
            if positive(raw) is not None and factor is not None:
                result[key] = float(raw) * factor
                result[f"{key}_source"] = {"method": "ifc_relation", "property_set": ps.Name,
                                           "property": value.Name, "value": raw, "unit_scale_m": factor}
    return result


def enrich_ifc(writer, did, path, root, deadline):
    import ifcopenshell
    import ifcopenshell.util.element as ue
    import ifcopenshell.util.unit as uu
    f = ifcopenshell.open(str(path))
    projects = _by_type(f, "IfcProject")
    declared_units = getattr(projects[0], "UnitsInContext", None) if projects else None
    has_length_unit = declared_units and any(getattr(u, "UnitType", None) == "LENGTHUNIT" for u in declared_units.Units)
    scale = uu.calculate_unit_scale(f) if has_length_unit else None
    # Shared spatial entity identity + its complete placement gives a declared
    # common engineering frame. Distinct models with unrelated IDs do not align.
    frames = []
    if scale:
        import ifcopenshell.util.placement as up
        for building in _by_type(f, "IfcBuilding"):
            if building.ObjectPlacement is None:
                continue
            matrix = up.get_local_placement(building.ObjectPlacement).copy()
            matrix[:3, 3] *= scale
            frames.append({"building_guid": building.GlobalId, "project_guid": projects[0].GlobalId,
                           "matrix_z_up_m": matrix.tolist()})
    writer.graph.setdefault("mep", {}).setdefault("frames", {})[did] = frames
    artifact = read_json(Path(root) / did / "elements.json", {})
    rows = artifact if isinstance(artifact, list) else artifact.get("elements", [])
    by_id = {e["item_id"]: e for e in rows}
    scene = read_json(Path(root) / did / "scene.json", {})
    offset = scene.get("origin_offset_m")
    services = {}
    spaces = {}
    index = read_json(Path(root) / did / "mep.json", {})
    indexed = {row["id"]: row for row in index.get("services", []) if row.get("id")}
    for el in _by_type(f, "IfcSpace") + _by_type(f, "IfcDistributionElement"):
        if time.monotonic() > deadline:
            raise TimeoutError("services enrichment reached its time budget")
        room = el.is_a("IfcSpace")
        kind = "room" if room else _kind(el, ue)
        if kind is None:
            continue
        row = by_id.get(el.GlobalId, {})
        st = ue.get_container(el)
        while st is not None and not st.is_a("IfcBuildingStorey"):
            st = ue.get_aggregate(st)
        level = getattr(st, "Name", None)
        props = {"ifc_class": el.is_a(), **_measures(el, scale)}
        if not has_length_unit:
            props["measurement_note"] = "Length unit not recorded; raw dimensions not converted."
        if room:
            label = getattr(el, "LongName", None) or el.Name or "Unnamed room"
            props["room_number"] = el.Name
        else:
            from engine.mep import _classify, _first, NAME_KEYS
            indexed_row = indexed.get(el.GlobalId, {})
            psets = ue.get_psets(el)
            service_kind = indexed_row.get("k") or _classify(el, ue.get_type(el), psets)
            props["service_kind"] = service_kind
            props["is_flow_terminal"] = el.is_a("IfcFlowTerminal")
            props["system"] = indexed_row.get("s") or _first(psets, NAME_KEYS)
            if "length_m" not in props and positive(indexed_row.get("L")):
                props["length_m"] = float(indexed_row["L"])
                props["length_m_source"] = {"artifact": "mep.json", "method": indexed_row.get("ls"),
                                             "note": "Existing unit-resolved services index; not a length inside any room."}
            # Keep author labels in props; never expose a raw GUID as a label.
            from engine.kg.schema import readable
            plain = service_kind.replace("_", " ").capitalize()
            name = readable(el.Name, "")
            label = f"{plain} · {name}" if name else plain
        bb = row.get("bbox_m")
        if bb and offset:
            props["world_bbox_m"] = [[float(c) + float(o) for c, o in zip(p, offset)] for p in bb]
        n = writer.node(kind, did, el.GlobalId, label, props, level)
        writer.doc_link(n, did)
        (spaces if room else services)[el.GlobalId] = n
    writer.finish()
    # Explicit spatial containment and spatial references (IFC4).
    for cls, field in (("IfcRelContainedInSpatialStructure", "RelatedElements"),
                       ("IfcRelReferencedInSpatialStructure", "RelatedElements")):
        for rel in _by_type(f, cls):
            room = spaces.get(getattr(rel.RelatingStructure, "GlobalId", None))
            if not room:
                continue
            for el in getattr(rel, field, ()):
                service = services.get(getattr(el, "GlobalId", None))
                if service:
                    ev = {"relation": cls, "relation_id": rel.GlobalId,
                          "item_id": el.GlobalId, "room_item_id": rel.RelatingStructure.GlobalId}
                    writer.edge("in_room", service, room, "ifc_relation", 1.0, ev)
                    if service.get("props", {}).get("is_flow_terminal") and cls == "IfcRelContainedInSpatialStructure":
                        writer.edge("serves", service, room, "ifc_relation", 1.0,
                                    {**ev, "rule": "terminal physically contained in room; no upstream capacity inference"})
    # Systems may overlap: retain every declared assignment, not just the first.
    for system in _by_type(f, "IfcSystem"):
        members = [services.get(getattr(el, "GlobalId", None))
                   for rel in getattr(system, "IsGroupedBy", ()) for el in rel.RelatedObjects]
        members = [n for n in members if n]
        if not members:
            continue
        sn = writer.node("system", did, system.GlobalId, system.Name or "Unnamed building service system",
                         {"type": getattr(system, "PredefinedType", None)})
        writer.doc_link(sn, did)
        for n in members:
            writer.edge("part_of_system", n, sn, "ifc_relation", 1.0,
                        {"relation": "IfcRelAssignsToGroup", "system_item_id": system.GlobalId,
                         "item_id": n["source"]["item_id"]})
    # Some exporters record system names only in property sets, not IfcSystem.
    # Preserve the recorded string verbatim (commas need not delimit systems).
    assigned = {e["from"] for e in writer.graph["edges"] if e["kind"] == "part_of_system"}
    for n in services.values():
        raw_system = n["props"].get("system")
        if n["id"] not in assigned and isinstance(raw_system, str) and raw_system.strip():
            sn = writer.node("system", did, "property-" + hashlib.sha256(raw_system.encode()).hexdigest()[:16], raw_system,
                             {"recorded_system_label": raw_system})
            # This group is derived from a recorded property, not an IFC object.
            # Its service member is the citation; no fabricated item ID is cited.
            sn["source"] = None
            writer.doc_link(sn, did)
            writer.edge("part_of_system", n, sn, "tag_text", 0.5,
                        {"rule": "recorded system-name property; membership not independently checked",
                         "value": raw_system, "source": n["source"]})
    # Ports: IFC2x3 uses RelConnectsPortToElement, IFC4 also uses RelNests.
    owner = {}
    for rel in _by_type(f, "IfcRelConnectsPortToElement"):
        owner[rel.RelatingPort.id()] = services.get(rel.RelatedElement.GlobalId)
    for rel in _by_type(f, "IfcRelNests"):
        n = services.get(getattr(rel.RelatingObject, "GlobalId", None))
        for obj in rel.RelatedObjects:
            if obj.is_a("IfcDistributionPort"):
                owner[obj.id()] = n
    for rel in _by_type(f, "IfcRelConnectsPorts"):
        a, b = owner.get(rel.RelatingPort.id()), owner.get(rel.RelatedPort.id())
        writer.edge("connects", a, b, "ifc_relation", 1.0,
                    {"relation": "IfcRelConnectsPorts", "relation_id": rel.GlobalId,
                     "port_ids": [rel.RelatingPort.GlobalId, rel.RelatedPort.GlobalId],
                     "flow_direction": [rel.RelatingPort.FlowDirection, rel.RelatedPort.FlowDirection]})
    for rel in _by_type(f, "IfcRelConnectsElements"):
        writer.edge("connects", services.get(rel.RelatingElement.GlobalId), services.get(rel.RelatedElement.GlobalId),
                    "ifc_relation", 1.0, {"relation": "IfcRelConnectsElements", "relation_id": rel.GlobalId})
    return {"schema": f.schema, "services": len(services), "rooms": len(spaces)}


def enrich(graph, project, root, *, time_budget_s=20):
    """Append source-backed nodes/edges in place; dependency failures are visible notes."""
    writer = Writer(graph)
    deadline = time.monotonic() + max(0, time_budget_s)
    notes = graph.setdefault("mep", {"documents": {}, "notes": []})
    notes.setdefault("documents", {})
    notes.setdefault("notes", [])
    for doc in project.get("docs", []):
        if isinstance(doc, str):
            doc = {"doc_id": doc}
        did = doc.get("doc_id")
        if not did:
            continue
        if Path(did).name != did or did in {".", ".."}:
            notes["notes"].append("Invalid document identifier; services skipped.")
            continue
        meta = {**read_json(Path(root) / did / "doc.json", {}), **doc}
        path = resolve_source(meta, root, "ifc")
        if path:
            try:
                notes["documents"][did] = enrich_ifc(writer, did, path, root, deadline)
            except (ImportError, RuntimeError, ValueError, OSError, TimeoutError, AttributeError, TypeError) as exc:
                notes["documents"][did] = {"status": "partial", "note": f"IFC services unavailable: {type(exc).__name__}: {exc}"}
        elif "ifc" in meta.get("formats", []) or meta.get("kind") == "ifc":
            notes["documents"][did] = {"status": "unavailable", "note": "Original IFC not available; explicit service relationships cannot be read."}
    from engine.kg.mep_spatial import enrich_spatial
    enrich_spatial(writer)
    from engine.kg.mep_sheets import enrich_sheets
    enrich_sheets(writer, project, Path(root), deadline)
    for doc in project.get("docs", []):
        did = doc if isinstance(doc, str) else doc.get("doc_id")
        if not did or Path(did).name != did or did in {".", ".."}:
            continue
        for path in (Path(root) / did).glob("planmap-*.json"):
            pm = read_json(path, {})
            if isinstance(pm, dict):
                apply_ceiling_notes(graph, pm.get("room_ceiling_notes", []) or [])
    writer.finish()
    degree = Counter()
    for e in graph["edges"]:
        degree.update((e["from"], e["to"]))
    for n in graph["nodes"]:
        n["degree"] = degree[n["id"]]
    return graph


def apply_ceiling_notes(graph, notes):
    """Optional PDF hook; accepts explicit room-referenced, already unit-resolved notes.

    notes: [{room: {doc_id, page, item_id}, ceiling_height_m: number,
             source: {doc_id, page, item_id?, bbox?, quote}}].
    The PDF owner supplies these notes; this module neither parses PDF text nor
    assigns unqualified heights to nearby rooms. Conflicting values are retained.
    """
    attached = 0
    for note in notes:
        if not isinstance(note, dict):
            continue
        height = positive(note.get("ceiling_height_m"))
        ref, source = note.get("room"), note.get("source")
        if not height or not isinstance(ref, dict) or not isinstance(source, dict):
            continue
        if not source.get("doc_id") or not source.get("page") or not source.get("quote") or not (source.get("bbox") or source.get("item_id")):
            continue
        matches = [n for n in graph.get("nodes", []) if n["kind"] == "room" and
                   all((n.get("source") or {}).get(k) == ref.get(k) for k in ("doc_id", "page", "item_id"))]
        if len(matches) != 1:
            continue
        props = matches[0].setdefault("props", {})
        evidence = {"ceiling_height_m": height, "source": source, "method": "tag_text"}
        values = props.setdefault("ceiling_height_notes", [])
        if evidence not in values:
            values.append(evidence)
            attached += 1
        existing = props.get("ceiling_height_m")
        if existing is None:
            props["ceiling_height_m"] = height
            props["ceiling_height_m_source"] = evidence
        elif abs(existing - height) > 1e-6:
            props["ceiling_height_note"] = "Recorded ceiling heights differ; check the cited sources."
    return attached


def room_services(graph, room_node_id):
    """Impact hook: counts, declared whole-run lengths, paths and source citations.

    No whole-run length is presented as length *inside* a room. Spatially clipped
    lengths, when known, are separately labelled. Unconnected services are unknown.
    """
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    room = nodes.get(room_node_id)
    if not room or room["kind"] != "room":
        return {"room": room, "services": [], "count_by_kind": {}, "length_m_by_kind": {},
                "notes": ["Room not present in the graph."]}
    # Same room on another sheet is also relevant; preserve transitive proof.
    rooms = {room_node_id: []}
    same = {}
    systems = {}
    for e in graph.get("edges", []):
        if e["kind"] == "same_as":
            same.setdefault(e["from"], []).append((e["to"], e))
            same.setdefault(e["to"], []).append((e["from"], e))
        elif e["kind"] == "part_of_system" and e["to"] in nodes:
            systems.setdefault(e["from"], []).append(nodes[e["to"]])
    queue = [room_node_id]
    for rid in queue:
        for peer, edge in same.get(rid, []):
            if peer not in rooms and nodes.get(peer, {}).get("kind") == "room":
                rooms[peer] = [edge, *rooms[rid]]
                queue.append(peer)
    selected = {}
    for e in graph.get("edges", []):
        n = nodes.get(e["from"])
        if e["kind"] not in {"serves", "in_room"} or e["to"] not in rooms or not n or n["kind"] not in SERVICE_KINDS:
            continue
        path = [e, *rooms[e["to"]]]
        confidence = min(x["confidence"] for x in path)
        # Matching depictions of one service count once; keep the strongest path.
        identity = n.get("canonical") or n["id"]
        old = selected.get(identity)
        if old and (old["confidence"] > confidence or (old["confidence"] == confidence and old["relationship"] == "serves")):
            continue
        selected[identity] = {"node": n, "relationship": e["kind"], "why_path": [x["id"] for x in path],
                              "confidence": confidence, "source": n.get("source"),
                              "systems": systems.get(n["id"], []),
                              "element_length_m": n.get("props", {}).get("length_m"),
                              "length_in_room_m": e.get("evidence", {}).get("length_in_room_m"),
                              "length_method": e.get("evidence", {}).get("length_method")}
    counts = Counter(row["node"]["kind"] for row in selected.values())
    lengths = Counter()
    for row in selected.values():
        if row["length_in_room_m"] is not None:
            lengths[row["node"]["kind"]] += row["length_in_room_m"]
    return {"room": room, "services": list(selected.values()), "count_by_kind": dict(counts),
            "length_m_by_kind": dict(lengths), "notes": ["Only recorded links are listed; missing links do not prove a room has no services.",
                "Element length is the whole run; length inside the room is unknown unless separately recorded."]}
