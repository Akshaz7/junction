"""KG-EVAL reproducible read-only benchmark (run via scripts/heavy.sh).

All document choices live in a manifest, never in engine code. Uses existing
text layers only; it does not ingest PDFs or write shared artifact caches.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import pprint
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.kg.evaluation import (
    METHODS,
    Case,
    align,
    centre,
    distribution,
    evaluate,
    fit_table,
    ifc_items,
    metrics,
    norm,
    plan_items,
    read_json,
    svg_items,
)


def source(root, meta, format):
    rel = (meta.get("files") or {}).get(format)
    if not rel:
        return None
    # Same supported source roots as the graph, with no recursive disk scan.
    for base in (root.resolve().parent / "data/full/junction-dataset",
                 root.resolve().parent / "data/junction-dataset-preview", root.resolve().parent):
        path = base / rel
        if path.is_file():
            return path
    return None


def heldout(root, did, heldout_ids):
    meta = read_json(root / did / "doc.json") or {}
    # Unknown membership cannot silently enter the calibration set.
    return meta.get("heldout", True) or did in heldout_ids


def source_tags(root, did, items):
    """Read original IFC Tag for an independent tag matcher; no synthetic tags."""
    from dataclasses import replace
    path = source(root, read_json(root / did / "doc.json") or {}, "ifc")
    if path is None:
        return items
    import ifcopenshell
    model = ifcopenshell.open(path)
    tags = {str(e.GlobalId): str(e.Tag) for e in model.by_type("IfcElement") if getattr(e, "Tag", None)}
    return [replace(i, tag=tags.get(i.identity, i.tag)) for i in items]


def projected_cases(root, did, is_heldout):
    index = read_json(root / did / "elements.json")
    items = ifc_items(index)
    cases = []
    for path in sorted((root / did).glob("planmap-*.json")):
        plan = read_json(path)
        if not plan:
            continue
        right = plan_items(plan)
        levels = {norm(i.level) for i in right if i.level}
        left = [i for i in items if norm(i.level) in levels]
        cases.append(Case(f"projection:{did}:{path.stem}", left, right, is_heldout, True,
                          notes="Generated for demo from IFC geometry; exact source identities, not independent sheet detection. Coordinates inverse-projected from the documented transform."))
    return cases


def sheet_case(root, row):
    model, sheet = row["model"], row["sheet"]
    meta = read_json(root / sheet / "doc.json") or {}
    path = source(root, meta, "svg")
    if not path:
        return None, {"sheet": sheet, "status": "unavailable", "reason": "No accessible source SVG companion; PDF ingestion belongs to Awais."}
    from engine.projects.roles import classify
    level = row.get("level") or classify(meta, root).get("level")
    left = svg_items(path, level)
    right = [i for i in ifc_items(read_json(root / model / "elements.json")) if norm(i.level) == norm(level)]
    fitted = align(left, right)
    if not fitted:
        return None, {"sheet": sheet, "status": "unavailable", "reason": "Fewer than three non-collinear source identity anchors."}
    a, b, evidence = fitted
    # Count recall only for represented source products, not elements absent at
    # the sheet's section plane. Unmatched products remain known-negative candidates.
    return Case(f"sheet:{model}:{sheet}", a, b, True, True, evidence,
                "Generated for demo source SVG companion of PDF. Only explicit straight geometry is bounded; transformed/curved-only groups skipped. Deterministic half of common GUIDs fit the similarity; all fit anchors excluded from scoring."), None


def swiss_check(root, did):
    """Audit independent twin text anchors against DXF polygons, not guessed truth.

    Twins share one registry document, so no same_as edge is expected. Their
    registration is tested by fitting on half the unique numeric room anchors
    and scoring only the remaining anchors, in physical metres.
    """
    import ezdxf
    import numpy as np
    from shapely.geometry import Point, Polygon

    from pipeline.dxf_planmap import UNIT_M, room_texts
    meta = read_json(root / did / "doc.json") or {}
    path = source(root, meta, "dxf")
    text = read_json(root / did / "text-1.json") or {}
    plan = read_json(root / did / "planmap-1.json") or {}
    if not path or not text.get("words"):
        return {"doc_id": did, "status": "unavailable", "reason": "DXF source or existing PDF text layer missing."}
    drawing = ezdxf.readfile(path)
    unit = UNIT_M.get(int(drawing.header.get("$INSUNITS", 0)))
    if unit is None:
        return {"doc_id": did, "status": "unavailable", "reason": "Unknown DXF physical units."}
    aa, bb = defaultdict(list), defaultdict(list)
    for label, x, y in room_texts(drawing.modelspace()):
        if re.fullmatch(r"\d+\.\d+", label):
            aa[label].append((x, y))
    for w in text["words"]:
        if w.get("text") in aa and centre(w.get("bbox_px")):
            bb[w["text"]].append(centre(w["bbox_px"]))
    common = sorted(k for k in aa.keys() & bb.keys() if len(aa[k]) == len(bb[k]) == 1)
    train = common[::2]; test = common[1::2]
    if len(train) < 2 or not test:
        return {"doc_id": did, "status": "unavailable", "reason": "Insufficient unique room-number anchors for a disjoint split."}
    rows, targets = [], []
    for k in train:
        x, y = aa[k][0]; u, v = bb[k][0]
        rows.extend([[x, 1, 0], [-y, 0, 1]]); targets.extend([u, v])
    a, bx, by = np.linalg.lstsq(rows, targets, rcond=None)[0]
    if a <= 0 or np.linalg.matrix_rank(rows) < 3:
        return {"doc_id": did, "status": "unavailable", "reason": "Degenerate/nonpositive physical registration."}
    residuals = [float(np.linalg.norm(np.array([a * aa[k][0][0] + bx, -a * aa[k][0][1] + by]) - bb[k][0])) * unit / a for k in test]
    rooms = {str((i.get("props") or {}).get("number")): i for i in plan.get("items", []) if i.get("kind") == "room" and (i.get("props") or {}).get("number")}
    checks = []
    for k in test:
        room = rooms.get(k)
        if not room or not room.get("polygon_px"):
            continue
        poly = Polygon(room["polygon_px"])
        point = Point(bb[k][0])
        checks.append({"number": k, "item_id": room["item_id"], "inside_source_room": bool(poly.covers(point)),
                       "distance_m": float(poly.distance(point) * unit / a)})
    return {"doc_id": did, "status": "ready", "formats": meta.get("formats"),
            "truth": "Unique numeric room label shared by raw DXF TEXT and existing PDF text layer. Twins are derived drawings and one registry doc, not independent graph documents.",
            "fit_anchors": len(train), "withheld_anchors": len(test), "residual_m": distribution(residuals),
            "containment_checked": len(checks), "containment_correct": sum(c["inside_source_room"] for c in checks), "samples": checks[:10]}


def graph_audit(root, project):
    """No cache writes. Score identities in actual graph, independently of methods."""
    from engine.kg.build import build_uncached
    start = time.perf_counter(); graph = build_uncached(project, root)
    elapsed = time.perf_counter() - start
    nodes = {n["id"]: n for n in graph["nodes"]}
    invalid, same, samples = [], defaultdict(list), defaultdict(list)
    identity_nodes = defaultdict(list)
    for n in graph["nodes"]:
        identity = (n.get("props") or {}).get("guid")
        if identity and n.get("source"):
            identity_nodes[identity].append(n)
    expected = set()
    for members in identity_nodes.values():
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                if a["source"]["doc_id"] != b["source"]["doc_id"]:
                    expected.add(tuple(sorted([a["id"], b["id"]])))
    predicted_by_method = defaultdict(set)
    for e in graph["edges"]:
        a, b = nodes.get(e["from"]), nodes.get(e["to"])
        if not a or not b or not e.get("method") or not e.get("evidence") or not isinstance(e.get("confidence"), (float, int)) or not 0 <= e["confidence"] <= 1:
            invalid.append(e["id"]); continue
        if e["kind"] == "same_as":
            sa, sb = a.get("source") or {}, b.get("source") or {}
            ia, ib = (a.get("props") or {}).get("guid"), (b.get("props") or {}).get("guid")
            # Only IFC-backed identities can be judged this way. Text matches
            # and sequential per-plan IDs are unknown, not automatic successes.
            correct = ia == ib if ia and ib else None
            if correct is not None:
                predicted_by_method[e["method"]].add(tuple(sorted([a["id"], b["id"]])))
            same[e["method"]].append({"edge_id": e["id"], "correct": correct, "confidence": e["confidence"],
                                       "residual_m": e["evidence"].get("residual_m"), "from": sa, "to": sb})
        if e["kind"] in ("in_room", "hosted_by", "serves"):
            samples[e["kind"]].append((e, a, b))
    scored = {}
    for method in METHODS:
        rows = same[method]; known = [r for r in rows if r["correct"] is not None]
        scored[method] = {**metrics(predicted_by_method[method], expected, len(rows) - len(known)),
                          "graph_edges": len(rows), "known": len(known),
                          "residual_m": distribution([r["residual_m"] for r in rows]), "sample": rows[:5]}
    audited = {k: sample_relations(root, samples[k]) for k in ("in_room", "hosted_by", "serves")}
    return {"project": project, "build_seconds": elapsed, "under_30_seconds": elapsed < 30,
            "stats": graph["stats"], "edges_by_kind": dict(Counter(e["kind"] for e in graph["edges"])),
            "warnings": graph.get("warnings", []), "invalid_edge_count": len(invalid), "invalid_edge_sample": invalid[:10],
            "same_as": scored, "same_as_all_methods": metrics(set().union(*predicted_by_method.values()), expected),
            "truth_scope": "Cross-document graph node pairs retaining the same source IFC GlobalId. Unknown source identities excluded. Pairwise recall, not transitive cluster recall.",
            "relation_samples": audited}


def sample_relations(root, rows):
    """IFC relations are audited against raw IFC, geometric links as predicates.

    A checked geometric predicate is not an independent semantic truth label.
    Serves cannot be inferred solely from overlapping geometry.
    """
    from shapely.geometry import Point, Polygon, box
    raw_cache = {}
    samples = []
    # A stable hash samples across the whole list instead of the first room.
    for e, a, b in sorted(rows, key=lambda row: hashlib.sha256(row[0]["id"].encode()).digest())[:10]:
        result = None; basis = "No independent source relationship available."
        sa, sb = a.get("source") or {}, b.get("source") or {}
        did = sa.get("doc_id")
        if did and did == sb.get("doc_id"):
            if did not in raw_cache:
                meta = read_json(root / did / "doc.json") or {}
                path = source(root, meta, "ifc")
                if path:
                    import ifcopenshell
                    raw_cache[did] = ifcopenshell.open(path)
                else:
                    raw_cache[did] = None
            model = raw_cache[did]
            if model and e["kind"] in ("hosted_by", "in_room", "serves"):
                try:
                    item = model.by_guid(sa.get("item_id")); target = sb.get("item_id")
                    possible = set()
                    if e["kind"] == "hosted_by":
                        for rel in getattr(item, "FillsVoids", ()):
                            for host in getattr(rel.RelatingOpeningElement, "VoidsElements", ()):
                                possible.add(host.RelatingBuildingElement.GlobalId)
                    else:
                        for rel in getattr(item, "ContainedInStructure", ()):
                            if rel.RelatingStructure.is_a("IfcSpace"):
                                possible.add(rel.RelatingStructure.GlobalId)
                        for rel in getattr(item, "ProvidesBoundaries", ()):
                            possible.add(rel.RelatingSpace.GlobalId)
                    if possible:
                        result = target in possible
                        basis = ("Raw IFC confirms physical terminal containment only; service function/capacity not independently verified."
                                 if e["kind"] == "serves" else "Raw IFC explicit relationship; no geometry inference.")
                except (RuntimeError, AttributeError):
                    pass
        if result is None and e["kind"] == "in_room" and e.get("method") == "containment_geom":
            poly = (b.get("props") or {}).get("polygon_px")
            bb = sa.get("bbox")
            rb = sb.get("bbox")
            if bb and (poly or rb):
                shape = Polygon(poly).buffer(0) if poly else box(*rb)
                result = bool(shape.covers(Point(centre(bb)))); basis = "Recomputed source geometry predicate only; semantic room membership is unverified."
        samples.append({"edge_id": e["id"], "kind": e["kind"], "method": e["method"],
                        "correct": result, "basis": basis, "from": sa, "to": sb})
    known = [s for s in samples if s["correct"] is not None]
    return {"total_edges": len(rows), "sample_size": len(samples), "checked": len(known),
            "correct": sum(s["correct"] for s in known), "unknown": len(samples) - len(known), "samples": samples}


def calibration_scores(observations, calibrated):
    result = {}
    for split, flag in (("fit_in_sample", False), ("heldout", True)):
        result[split] = {}
        for method in METHODS:
            rows = [o for o in observations if o["heldout"] == flag and o["method"] == method]
            pairs = [(calibrated(method, o["residual_m"]), int(o["correct"])) for o in rows]
            bins = []
            for i in range(10):
                part = [(p, y) for p, y in pairs if min(9, int(p * 10)) == i]
                if part:
                    bins.append({"min_probability": i / 10, "n": len(part),
                                 "mean_probability": sum(p for p, _ in part) / len(part),
                                 "observed_precision": sum(y for _, y in part) / len(part)})
            result[split][method] = {"n": len(pairs),
                                    "brier": sum((p - y) ** 2 for p, y in pairs) / len(pairs) if pairs else None,
                                    "ece": sum(b["n"] * abs(b["mean_probability"] - b["observed_precision"]) for b in bins) / len(pairs) if pairs else None,
                                    "reliability_bins": bins}
    return result


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("artifacts"))
    parser.add_argument("--output", type=Path, default=Path("results/final/KG-EVAL"))
    parser.add_argument("--blind", action="store_true", help="Run only after code and calibration are frozen")
    parser.add_argument("--write-calibration", action="store_true")
    args = parser.parse_args()
    if args.blind and args.write_calibration:
        parser.error("Blind evaluation cannot update calibration")
    config = read_json(args.manifest)
    root = args.root
    ids = root.resolve().parent / "data/sets/heldout_docs.txt"
    heldout_ids = set(ids.read_text().splitlines()) if ids.exists() else set()
    reports, observations, unavailable = [], [], []
    for did in config.get("calibration_docs", []) + config.get("evaluation_docs", []):
        for case in projected_cases(root, did, heldout(root, did, heldout_ids)):
            report, obs = evaluate(case); reports.append(report); observations.extend(obs)
    for row in config.get("sheet_pairs", []):
        case, problem = sheet_case(root, row)
        if problem:
            unavailable.append(problem)
        else:
            report, obs = evaluate(case); reports.append(report); observations.extend(obs)
    for row in config.get("revision_pairs", []):
        a, b = row["doc_a"], row["doc_b"]
        aa, bb = source_tags(root, a, ifc_items(read_json(root / a / "elements.json"))), source_tags(root, b, ifc_items(read_json(root / b / "elements.json")))
        if not aa or not bb:
            unavailable.append({"pair": row, "reason": "Source index unavailable."}); continue
        # Recentered revision coordinates need their world-frame offsets restored.
        def restore(items, did):
            from dataclasses import replace
            scene = read_json(root / did / "scene.json") or {}
            off = scene.get("origin_offset_m")
            if not isinstance(off, list) or len(off) != 3:
                return [replace(i, xy=None) for i in items]
            return [replace(i, xy=(i.xy[0] + off[0], i.xy[1] + off[2]) if i.xy else None) for i in items]
        aa, bb = restore(aa, a), restore(bb, b)
        case = Case(f"revision:{a}:{b}", aa, bb,
                    heldout(root, a, heldout_ids) or heldout(root, b, heldout_ids), False,
                    notes="Truth is shared IFC GlobalId within a known revision pair, not unchanged geometry. Original metre frames restored from scene offsets. Insertions/deletions remain negative candidates.")
        report, obs = evaluate(case); reports.append(report); observations.extend(obs)
    table = fit_table(observations)
    if args.write_calibration:
        path = Path(__file__).resolve().parents[1] / "engine/kg/confidence.py"
        text = path.read_text()
        start = text.index("CALIBRATION = "); end = text.index("# END MEASURED TABLE", start)
        path.write_text(text[:start] + "CALIBRATION = " + pprint.pformat(table, sort_dicts=False, width=100) + "\n" + text[end:])
    calibration = importlib.import_module("engine.kg.confidence")
    calibration = importlib.reload(calibration)
    swiss = [swiss_check(root, did) for did in config.get("swiss_docs", [])]
    graphs = [graph_audit(root, p) for p in config.get("projects", [])]
    blind = None
    if args.blind:
        did = read_json(args.output / "selection.json")["blind_doc_id"]
        blind_reports, blind_observations = [], []
        for case in projected_cases(root, did, True):
            report, obs = evaluate(case)
            blind_reports.append(report); blind_observations.extend(obs)
        blind = {"doc_id": did, "calibration_frozen_before_read": True, "cases": blind_reports,
                 "calibration_evaluation": calibration_scores(blind_observations, calibration.confidence)["heldout"],
                 "graph": graph_audit(root, {"id": "kg-eval-blind", "docs": [did]})}
    out = {"generated_at": datetime.now(UTC).isoformat(),
           "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
           "manifest": config, "cases": reports, "unavailable": unavailable, "swiss_twins": swiss,
           "calibration": calibration.CALIBRATION,
           "calibration_evaluation": calibration_scores(observations, calibration.confidence),
           "calibration_fit_observations": sum(not o["heldout"] for o in observations),
           "heldout_observations_excluded_from_fit": sum(o["heldout"] for o in observations),
           "calibration_source_membership": {did: {"heldout": heldout(root, did, heldout_ids)}
                                             for did in config.get("calibration_docs", []) + [p[k] for p in config.get("revision_pairs", []) for k in ("doc_a", "doc_b")]},
           "code_sha256": {str(p.relative_to(Path(__file__).resolve().parents[1])): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted((Path(__file__).resolve().parents[1] / "engine/kg").glob("*.py"))},
           "projects": graphs, "blind": blind,
           "limitations": ["IFC-derived plans and SVG/PDF/PNG twins share source geometry; these scores do not establish detection accuracy on independent scans.",
                           "GUID is code-known source identity within a known pair, not an independently labelled classifier outcome.",
                           "Reference matcher scores and production graph edge scores are reported separately.",
                           "Missing truth and absent methods have null precision, never 100%.",
                           "No heldout or blind observations are used to fit probabilities."]}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps(out, indent=2, allow_nan=False) + "\n")
    # Keep a compact audit trail; the full deterministic observations can be
    # regenerated from the manifest without committing megabytes of repeated IDs.
    audit = {"n": len(observations), "sha256": hashlib.sha256(json.dumps(observations, sort_keys=True).encode()).hexdigest(),
             "negative_examples": [o for o in observations if not o["correct"]][:20],
             "counts_by_case_method": dict(Counter(o["case"] + "/" + o["method"] for o in observations))}
    (args.output / "observations.json").write_text(json.dumps(audit, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"cases": len(reports), "calibration_observations": out["calibration_fit_observations"],
                      "heldout_observations": out["heldout_observations_excluded_from_fit"],
                      "graphs": [{"id": p["project"]["id"], "seconds": round(p["build_seconds"], 3), "invalid_edges": p["invalid_edge_count"]} for p in graphs],
                      "blind": blind["doc_id"] if blind else None}))


if __name__ == "__main__":
    main()
