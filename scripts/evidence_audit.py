#!/usr/bin/env python3
"""F-QA2: reproducible, read-only evidence QA (no PDF ingestion, no paid calls).

Run with scripts/heavy.sh <python> scripts/evidence_audit.py --run, then
--generalisation, and scripts/calibration.py. --self-test tests the auditor.
Model calls still go through engine.models.call(); cache misses are refused at
the provider boundary. This tests real code and cached model outputs, never fake
model outputs. Shared artifacts are copied into a private temporary overlay.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/final/QA2"
sys.path.insert(0, str(ROOT))
NUM = r"-?\d[\d,]*(?:\.\d+)?"
PRINTED = re.compile(r"(\d+(?:[.,]\d+)?)\s*m\s*(?:²|2)\b", re.I)


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def close(a, b, relative=.02, absolute=.05):
    return abs(a - b) <= max(absolute, abs(b) * relative)


def parse_num(s):
    return float(s.replace(",", ""))


def polygon_area(poly):
    if not poly or len(poly) < 3:
        return 0.
    return abs(sum(a[0]*b[1] - b[0]*a[1] for a, b in zip(poly, poly[1:] + poly[:1]))) / 2


def point_inside(x, y, poly):
    crosses = 0
    for a, b in zip(poly, poly[1:] + poly[:1]):
        if (a[1] > y) != (b[1] > y):
            if x < a[0] + (y-a[1]) * (b[0]-a[0]) / (b[1]-a[1]):
                crosses += 1
    return crosses % 2 == 1


def area_pair(room, doc):
    p = room.props or {}
    if p.get("area_m2_label") and p.get("area_m2_geom"):
        return float(p["area_m2_label"]), float(p["area_m2_geom"]), 1.
    poly = room.polygon_px
    scale = (doc.scale or {}).get("m_per_px")
    if not poly or not scale:
        return None
    labels = []
    for it in doc.items:
        if it.kind != "text" or it.page != room.page or not it.bbox_px:
            continue
        match = PRINTED.search(it.label or "")
        box = it.bbox_px
        if match and point_inside((box[0]+box[2])/2, (box[1]+box[3])/2, poly):
            labels.append(float(match[1].replace(",", ".")))
    if len(labels) == 1:
        return labels[0], polygon_area(poly) * scale**2, 5.
    return None


def expected_checked(response, cited, docs, metadata=None):
    """Independent arithmetic; never calls the card builder being audited."""
    for trace in response.get("trace", []):
        m = re.search(r"plan map (\d+), drawing re-read (\d+)", trace.get("detail", ""))
        if m:
            a, b = map(int, m.groups())
            return a == b, {"method": "recount", "plan": a, "reread": b}
    rooms = [(did, it) for did, it in cited if it.kind in ("room", "space")]
    checked_text = " ".join(s.get("text", "") for s in (response.get("reasoning") or {}).get("steps", []) if s.get("kind") == "checked")
    if rooms and (response["answer"].get("unit") in ("m2", "m²") or re.search(r"printed (?:label|areas?)|outline|footprint", checked_text, re.I)):
        pairs = [area_pair(it, docs[did]) for did, it in rooms[:12] if docs.get(did) and docs[did].mode != "ifc"]
        pairs = [p for p in pairs if p]
        if pairs:
            diffs = [abs(a-b)/max(abs(a), 1e-9)*100 for a, b, _ in pairs]
            tol = 1. if all(p[2] == 1. for p in pairs) else 5.
            return all(d <= tol for d in diffs), {"method": "printed_vs_geometry", "pairs": pairs, "differences_pct": diffs, "tolerance_pct": tol}
        if len(rooms) == 1:
            did, it = rooms[0]
            q, bb = it.q, it.bbox_m
            area = q.get("area_m2") or q.get("net_floor_area_m2")
            if docs[did] and docs[did].mode == "ifc" and area and bb:
                dx, dz = abs(bb[1][0]-bb[0][0]), abs(bb[1][2]-bb[0][2])
                footprint = dx*dz
                if footprint > .5:
                    return .6*footprint <= area <= 1.02*footprint, {"method": "IFC_bbox_plausibility_only", "area": area, "footprint": footprint, "width": dx, "depth": dz}
    scene_claim = re.search(r"All ([\d,]+) counted items are found in the 3D model", checked_text)
    if scene_claim and metadata is not None:
        claimed = int(scene_claim[1].replace(",", ""))
        if all("_scene_item_ids" in metadata.get(did, {}) for did, _ in cited):
            rendered = sum(it.item_id in metadata[did]["_scene_item_ids"] for did, it in cited)
            return rendered == claimed, {"method": "scene_manifest_membership", "claimed": claimed, "cited": len(cited), "rendered": rendered}
    if len(rooms) == 1:
        p = rooms[0][1].props
        if p.get("label_room_type") and p.get("model_room_type"):
            return p["label_room_type"] == p["model_room_type"], {"method": "room_type", "label": p["label_room_type"], "model": p["model_room_type"]}
    return None, {"method": "not_recomputable"}


def audit(case, response, docs, metadata):
    issues, checks = [], []

    def issue(code, detail, severity="error"):
        issues.append({"code": code, "severity": severity, "detail": detail})

    ans = response.get("answer", {})
    reasoning = response.get("reasoning") or {}
    steps = reasoning.get("steps", [])
    conf = reasoning.get("confidence", {})
    citations = response.get("citations", [])
    cited, seen = [], set()
    for c in citations:
        did = c.get("doc_id") or case["doc_id"]
        doc = docs.get(did)
        items = {i.item_id: i for i in doc.items} if doc else {}
        for iid in c.get("item_ids") or []:
            if iid not in items:
                issue("citation_item_missing", f"Citation [{c.get('n')}] item {iid!r} does not exist in {did}.")
            elif (did, iid) not in seen:
                seen.add((did, iid)); cited.append((did, items[iid]))
    checks.append("all_cited_item_ids_resolved_by_document")
    if not reasoning:
        if not ans.get("abstained"):
            issue("missing_evidence_card", "Non-abstained answer has no reasoning card.")
        return issues, checks, None

    label, pct = conf.get("label"), conf.get("pct")
    if label not in ("Verified", "Cross-checked", "Estimate") or (pct is not None and (type(pct) is not int or not 0 <= pct <= 100)):
        issue("invalid_confidence", f"Malformed confidence {conf!r}.")
    else:
        exact_sources = all(metadata.get(d, {}).get("kind") in ("ifc", "dxf", "dwg") for d in response.get("doc_ids", [case["doc_id"]]))
        if label == "Verified" and not exact_sources:
            issue("verified_without_exact_source", f"{label} {pct}% on source kind {metadata.get(case['doc_id'], {}).get('kind')}; scans cannot be Verified.")
        # Empirical percentages describe observed accuracy, not source exactness.
        # Apply the old thresholds only to cards produced by the heuristic builder.
        if pct is not None and not conf.get("calibration"):
            expected_label = "Verified" if pct >= 92 and exact_sources else "Cross-checked" if pct >= 80 else "Estimate"
            if label != expected_label:
                issue("label_threshold_mismatch", f"{pct}% maps to {expected_label}, shown as {label}.")
        approximate_claims = [str(t.get("detail", "")) for t in response.get("trace", []) if t.get("step") not in ("route", "explain")]
        approximate_claims += [s.get("text", "") for s in steps]
        if label == "Verified" and any(re.search(r"bounding.box|approximat|estimat|fallback", t, re.I) for t in approximate_claims):
            issue("verified_with_estimated_geometry", "Verified card accompanies a trace using approximate/fallback geometry; inspect exactness.")
    checks.append("confidence_source_and_threshold_rules")
    reason = conf.get("reason", "")
    if not re.match(r"[A-Z]", reason) or not reason.endswith((".", "!", "?")):
        issue("reason_not_sentence", f"Reason lacks sentence boundaries: {reason!r}.")
    if re.search(r"because (?:the model's own confidence|detector confidence \d+%|scale from [^;.]+)(?:\.|;| and |$)", reason):
        issue("reason_not_sentence", f"'Because' is followed by a noun phrase without a verb: {reason!r}.")
    checks.append("reason_sentence_boundaries_and_known_fragment_patterns")

    texts = [ans.get("text_md", ""), reason, conf.get("improve") or ""] + [s.get("text", "") for s in steps]
    jargon = re.compile(r"\bIfc[A-Z]\w*|\bGUIDs?\b|\bDN0\b|\b(?:door|window|room|wall|text|vision-[a-z_]+)-\d+\b|\b[A-Za-z0-9_$]{22}\b")
    for text in texts:
        hit = jargon.search(text)
        if hit:
            issue("user_visible_id_or_jargon", f"Visible internal term {hit[0]!r} in {text[:240]!r}.")
        if re.search(r"\b(\w+)(?:\s+\1){1,}\b", text, re.I):
            issue("duplicated_word", f"Repeated adjacent word in {text[:240]!r}.")
    normalized = [re.sub(r"\W+", " ", s.get("text", "")).lower().strip() for s in steps]
    if len(normalized) != len(set(normalized)):
        issue("duplicated_step", "Two evidence steps have the same wording.")
    checks.append("visible_ids_jargon_and_exact_wording_duplicates")

    value = number(ans.get("value"))
    unit = ans.get("unit")
    if value is not None and not ans.get("abstained"):
        head = ans.get("text_md", "").splitlines()[0] if ans.get("text_md") else ""
        head = re.sub(r"\[\d+\]", "", head)
        nums = [parse_num(m[0]) for m in re.finditer(NUM, head)]
        words = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
        nums += [v for w, v in words.items() if re.search(rf"\b{w}\b", head, re.I)]
        if value == 0 and re.search(r"\bno\s+(?:doors|windows|walls|rooms|toilets|sinks|columns)\b", head, re.I):
            nums.append(0)
        if not any(close(n, value, .002, .051) for n in nums):
            issue("headline_value_mismatch", f"answer.value={value}, headline={head!r}.")
    for step in steps:
        text = step.get("text", "")
        if value is not None and step.get("kind") in ("measured", "calculated"):
            result = re.search(rf"(?:=|:)\s*({NUM})\s*m(?:²|2|³|3)?\b", text)
            if result and unit in ("m", "m2", "m²", "m3", "m³") and not close(parse_num(result[1]), value, .002, .051):
                issue("card_answer_number_mismatch", f"Card result {result[1]} differs from answer.value={value}: {text!r}.")
            if unit in ("m2", "m²") and "Added" in text and "stored" in text:
                areas = [it.q.get("area_m2") or it.q.get("net_area_m2") or it.props.get("area_m2") for _, it in cited if it.kind in ("room", "space")]
                areas = [float(a) for a in areas if a is not None]
                if areas and not close(sum(areas), value):
                    issue("claimed_sum_not_supported", f"Card claims stored room areas add to {value}; cited stored areas sum to {sum(areas)}.")
            equation = re.search(rf"Outline ({NUM}) px² × \(({NUM}) m/px\)² = ({NUM})", text)
            if equation:
                px, mpp, shown = map(parse_num, equation.groups())
                if not close(px*mpp*mpp, shown):
                    issue("false_card_equation", f"{px} × {mpp}² = {px*mpp*mpp}, shown {shown}.")
    # Only direct, unqualified single-kind counts promise one box per item.
    if unit == "count" and value is not None and re.search(r"how many (?:windows|doors|toilets|sinks|columns|walls) (?:are|does)", case["question"], re.I):
        if cited and len(cited) != value:
            issue("cited_count_mismatch", f"Answer count={value}; unique existing cited items={len(cited)}.")
        found = next((s for s in steps if s.get("kind") == "found"), None)
        if found:
            m = re.match(r"(\d+) (?:windows|doors|toilets|sinks|columns|walls)\b", found.get("text", ""))
            if m and int(m[1]) != value:
                issue("found_answer_count_mismatch", f"Found step says {m[1]}, answer says {value}.")
    checks.append("headline_card_result_and_supported_arithmetic")

    condition = re.search(r"doors (wider|narrower) than (\d+(?:\.\d+)?)\s*(metres?|meters?|m)\b", case["question"], re.I)
    if condition and unit == "count" and value is not None:
        limit = float(condition[2])
        doc = docs.get(case["doc_id"])
        doors = [it for it in doc.items if it.kind == "door" and it.conf >= .5] if doc else []
        sized = [it for it in doors if number(it.q.get("width_m")) is not None]
        if len(sized) == len(doors):
            expected_count = sum((it.q["width_m"] > limit if condition[1].lower() == "wider" else it.q["width_m"] < limit) for it in sized)
            if expected_count != value:
                issue("qualified_count_false", f"Source widths support {expected_count} doors {condition[1]} than {limit} m, answer says {value}.")
        elif not any(t.get("step") == "filter" for t in response.get("trace", [])):
            if not re.search(r"missing|unavailable|not (?:available|recorded|known)|cannot|couldn.t|unknown|no width", ans.get("text_md", ""), re.I):
                issue("qualified_count_unchecked", f"Width condition was not checked: only {len(sized)} of {len(doors)} source doors have a width, and the response silently returns an unqualified count.")
        checks.append("qualified_door_count_against_available_widths")

    expected, facts = expected_checked(response, cited, docs, metadata)
    for step in [s for s in steps if s.get("kind") == "checked"]:
        if expected is None:
            issue("checked_not_recomputable", f"No independent inputs support Checked: {step.get('text')!r}.")
        elif step.get("ok") is not expected:
            issue("checked_verdict_false", f"Shown ok={step.get('ok')}; recomputed {expected}: {facts}.")
        if facts["method"] == "recount":
            boxed = re.search(r"the (\d+) boxed", step.get("text", ""))
            actual = len((response.get("evidence") or {}).get("boxes", []))
            if boxed and int(boxed[1]) != actual:
                issue("checked_box_count_false", f"Checked says {boxed[1]} boxed, current answer has {actual} boxes.")
        if facts["method"] == "printed_vs_geometry" and len(facts["pairs"]) == 1:
            a, b, _ = facts["pairs"][0]
            m = re.search(rf"label says ({NUM})", step.get("text", ""))
            if m and not close(parse_num(m[1]), a, .002, .02):
                issue("checked_source_number_false", f"Printed label shown {m[1]}, source {a}.")
            m = re.search(rf"matches within ({NUM})%", step.get("text", ""))
            if m and abs(a-b)/max(abs(a), 1e-9)*100 > parse_num(m[1]) + .051:
                issue("checked_tolerance_false", f"Actual difference {abs(a-b)/abs(a)*100}%, shown within {m[1]}%.")
        if facts["method"] == "IFC_bbox_plausibility_only" and step.get("ok") is True:
            checks.append("IFC_checked_is_bbox_plausibility_not_independent_area_measurement")
    if any(s.get("kind") == "checked" for s in steps):
        checks.append("checked_verdict_recomputed")
    return issues, checks, facts


def metadata_for(doc_id, artifacts):
    p = artifacts / doc_id / "doc.json"
    return read_json(p) if p.exists() else {}


def eligible(row, artifacts, excluded):
    if row["doc_id"] in excluded:
        return False
    meta = metadata_for(row["doc_id"], artifacts)
    if not meta or meta.get("kind") == "pdf":
        return False
    # The dataset asks Swiss questions using the PDF filename, but the engine
    # reads the same drawing's DXF plan map. Record the actual CAD path instead.
    fmt = meta.get("kind")
    if fmt in ("dxf", "ifc", "dwg", "svg"):
        row["path"] = meta.get("files", {}).get(fmt, row.get("path"))
    row["format"] = Path(row.get("path", "")).suffix.lower().lstrip(".") or fmt
    return True


def stratified(pool, n, seed):
    rng = random.Random(seed)
    groups = defaultdict(list)
    for row in pool:
        groups[(row.get("source"), row.get("type"))].append(row)
    for group in groups.values():
        rng.shuffle(group)
    result, used = [], set()
    while len(result) < n and any(groups.values()):
        for key in sorted(groups):
            while groups[key]:
                row = groups[key].pop()
                ident = row["doc_id"], row["question"]
                if ident not in used:
                    result.append(row); used.add(ident); break
            if len(result) == n:
                break
    return result


def prepare(artifacts):
    from pipeline.registry import doc_id_for_question_path
    selection = read_json(OUT / "holdout_selection.json")
    excluded = {x["doc_id"] for x in selection["files"]}
    full = rows(ROOT / "data/sets/questions_en.full.jsonl")
    english = {(r["doc_id"], r["question"]) for r in full}
    sample = [dict(r, origin="sample200", gold_kind="dataset") for r in rows(ROOT / "data/sets/sample200.jsonl")]
    sample = [r for r in sample if eligible(r, artifacts, excluded)]
    cases = stratified(sample, 45, 20261114)
    used = {(r["doc_id"], r["question"]) for r in cases}
    preview = []
    for r in rows(ROOT / "data/junction-dataset-preview/questions.jsonl"):
        r["doc_id"] = doc_id_for_question_path(r["path"])
        if (r["doc_id"], r["question"]) in english and (r["doc_id"], r["question"]) not in used:
            r.update(source=r["doc_id"].split("__")[0], origin="preview", gold_kind="dataset")
            if eligible(r, artifacts, excluded):
                preview.append(r)
    cases += stratified(preview, 45, 20261115)
    # Deliberately include unsupported DWG, SVG and JPEG, alongside data-rich
    # IFC/DXF/PNG. Own questions have no invented gold and are not calibrated.
    pools = defaultdict(list)
    for p in sorted(artifacts.glob("*/doc.json")):
        if p.parent.name in excluded:
            continue
        m = read_json(p)
        if m.get("source") == "uploads":
            continue  # stress/upload fixtures are not independent real sources
        kind = m.get("kind")
        if kind not in ("ifc", "dxf", "dwg", "svg", "raster"):
            continue
        key = kind
        if kind == "raster":
            key = "jpg" if any(f in m.get("formats", []) for f in ("jpg", "jpeg")) else "png"
        ready = (p.parent / "elements.json").exists() or any(p.parent.glob("planmap-[0-9]*.json"))
        pools[key].append((not ready, p.parent.name, m))
    questions = [
        ("How many doors are in this drawing?", "count"),
        ("How many windows are shown in this drawing?", "count"),
        ("How many windows and doors are in this drawing?", "count"),
        ("What is the total floor area of all rooms?", "area"),
        ("How many doors are wider than 1 metre?", "count"),
        ("What is the total length of all walls?", "length"),
        ("How many storeys does this building have?", "count"),
        ("Which materials are recorded for the walls?", "text"),
    ]
    for key, n in (("ifc", 8), ("dxf", 8), ("png", 6), ("jpg", 2), ("dwg", 3), ("svg", 3)):
        pool = sorted(pools[key])
        if not pool:
            raise RuntimeError(f"No documents for format {key}")
        for i in range(n):
            _, did, m = pool[i % len(pool)]
            question, typ = questions[i % len(questions)]
            case = dict(doc_id=did, source=m.get("source", did.split("__")[0]), question=question,
                        type=typ, answer=None, path=m.get("files", {}).get(key, next(iter(m.get("files", {}).values()), "")),
                        origin="own", gold_kind=None)
            eligible(case, artifacts, excluded)
            cases.append(case)
    if len(cases) != 120:
        raise RuntimeError(f"Expected 120 cases, got {len(cases)}")
    for i, case in enumerate(cases, 1):
        case["case_id"] = f"audit-{i:03d}"
    write_json(OUT / "audit_cases.json", cases)
    return cases


def snapshot_doc(doc_id, source, overlay):
    dest = overlay / doc_id
    if dest.exists():
        return
    dest.mkdir()
    original = source / doc_id
    for p in sorted(original.iterdir()) if original.exists() else []:
        if p.is_file() and p.suffix == ".json":
            shutil.copy2(p, dest / p.name)
        elif p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg", ".glb"):
            (dest / p.name).symlink_to(p.resolve())
    meta_path = dest / "doc.json"
    if meta_path.exists():
        meta = read_json(meta_path)
        # Keep the DXF/IFC/raster artifact under test, but prohibit PDF fallbacks.
        meta["files"] = {k: v for k, v in meta.get("files", {}).items() if k != "pdf"}
        meta["formats"] = [f for f in meta.get("formats", []) if f != "pdf"]
        write_json(meta_path, meta)


class CacheOnly:
    """Keep engine call/cache behavior, refuse every cache miss before I/O."""
    def __init__(self):
        self.refused = Counter()
        self.patches = []

    def __enter__(self):
        from engine.models import core
        def refuse(pcfg, model, *args, **kwargs):
            self.refused[f"{pcfg.get('name')}:{model}"] += 1
            raise core.P.ProviderError("QA2 cache-only: no paid or network inference")
        self.patches = [patch.object(core, "_forced_fake", return_value=False),
                        patch.object(core, "api_key", return_value="qa2-cache-only"),
                        patch.dict(core.P.ADAPTERS, {k: refuse for k in core.P.ADAPTERS})]
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()


def artifact_hashes(did, artifacts):
    result = {}
    for p in sorted((artifacts / did).glob("*.json")):
        if p.name in ("elements.json", "doc.json", "scene.json") or re.match(r"planmap-\d+\.json|scale-ocr.*\.json|text-\d+\.json|rtext-\d+\.json", p.name):
            result[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def execute(cases, artifacts, output):
    from engine.bench import score
    timestamp = datetime.now(timezone.utc).isoformat()
    output_rows = []
    with tempfile.TemporaryDirectory(prefix="qa2-evidence-") as tmp:
        scratch = Path(tmp); overlay = scratch / "artifacts"; overlay.mkdir()
        env = {"ARTIFACTS_DIR": str(overlay), "RESULTS_DIR": str(scratch / "results"),
               "MODELS_CACHE_DIR": str((artifacts / "cache/models").resolve()),
               "MODELS_COSTS_LOG": str(scratch / "model_costs.jsonl"), "RECOUNT_CACHE": "0",
               "ANSWER_TIMEOUT_S": "45"}
        # MODELS_FAKE must be absent: even "0" disables the production recount.
        with patch.dict(os.environ, env), CacheOnly() as cache:
            os.environ.pop("MODELS_FAKE", None)
            from engine.answer import answer
            from engine.solvers.data import load_doc
            for index, case in enumerate(cases, 1):
                did = case["doc_id"]
                snapshot_doc(did, artifacts, overlay)
                before = artifact_hashes(did, artifacts)
                started = time.perf_counter()
                try:
                    response = answer(case["question"], [did])
                    error = None
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    response = {"answer": {"abstained": True, "text_md": "", "value": None}, "trace": [], "citations": []}
                ids = {did} | {c.get("doc_id") for c in response.get("citations", []) if c.get("doc_id")}
                docs, meta = {}, {}
                for cited_did in ids:
                    snapshot_doc(cited_did, artifacts, overlay)
                    docs[cited_did] = load_doc(cited_did, overlay)
                    meta[cited_did] = metadata_for(cited_did, artifacts)
                    scene_path = overlay / cited_did / "scene.json"
                    if scene_path.exists():
                        meta[cited_did]["_scene_item_ids"] = set(read_json(scene_path).get("items", {}))
                issues, checks, facts = audit(case, response, docs, meta)
                if error:
                    issues.append({"code": "engine_error", "severity": "error", "detail": error})
                if before != artifact_hashes(did, artifacts):
                    issues.append({"code": "external_artifact_drift", "severity": "warning", "detail": "Shared artifact changed during the question; overlay preserves the audited version."})
                outcome = score(case, response) if case.get("gold_kind") else "unscored"
                output_rows.append({"case": case, "outcome": outcome, "duration_ms": round((time.perf_counter()-started)*1000),
                                    "response": response, "issues": issues, "checks": checks,
                                    "checked_recomputation": facts, "artifact_sha256": before})
                print(f"{index}/{len(cases)} {case['case_id']} {outcome} issues={len(issues)}", flush=True)
        cost_path = scratch / "model_costs.jsonl"
        costs = rows(cost_path) if cost_path.exists() else []
    problems = []
    for row in output_rows:
        for problem in row["issues"]:
            problems.append({"case_id": row["case"]["case_id"], "question": row["case"]["question"],
                             "doc_id": row["case"]["doc_id"], **problem})
    priority = {"checked_verdict_false": 0, "card_answer_number_mismatch": 0, "false_card_equation": 0,
                "claimed_sum_not_supported": 0, "verified_without_exact_source": 1,
                "citation_item_missing": 2, "verified_with_estimated_geometry": 2,
                "missing_evidence_card": 3, "reason_not_sentence": 5}
    problems.sort(key=lambda p: (priority.get(p["code"], 4), p["case_id"]))
    summary = {"questions": len(cases), "documents": len({r["doc_id"] for r in cases}),
               "formats": dict(Counter(r.get("format") for r in cases)), "origins": dict(Counter(r.get("origin") for r in cases)),
               "gold_outcomes": dict(Counter(r["outcome"] for r in output_rows)),
               "with_card": sum(bool(r["response"].get("reasoning")) for r in output_rows),
               "with_checked": sum(any(s.get("kind") == "checked" for s in r["response"].get("reasoning", {}).get("steps", [])) for r in output_rows),
               "without_findings": sum(not r["issues"] for r in output_rows),
               "issue_counts": dict(Counter(p["code"] for p in problems)),
               "live_cost_usd": 0, "cached_calls": len(costs), "cache_miss_provider_attempts": sum(cache.refused.values())}
    document = {"schema_version": 1, "created_utc": timestamp,
                "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "auditor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "mode": "real code + read-only model cache; all network inference refused; no fake outputs",
                "limitations": ["Cache misses follow the production unavailable-provider fallback; this is not a fresh live-model benchmark.",
                                "Dataset numeric gold uses engine.bench.score: exact rounded counts; area/length/volume within max(0.05, 2%).",
                                "Own questions have no independent gold and are excluded from accuracy/calibration.",
                                "Sentence and jargon checks are deterministic heuristics; passing does not establish all prose is correct.",
                                "Checked IFC footprint is only a plausibility test, not an independent measurement.",
                                "PDF-only documents and PDF ingest/fallback are excluded. Swiss gold originally referencing PDF is evaluated on the matching DXF artifact.",
                                "This audits processed artifact availability and answers, not fresh raw-file upload/ingestion."],
                "summary": summary, "top_20_problems": problems[:20], "rows": output_rows}
    write_json(output, document)
    print(json.dumps(summary, indent=2))
    return document


def recheck(path, artifacts):
    """Recompute audit checks on saved responses without any model/answer calls.

    Uses the current engine's document loader. Refuse changed source snapshots
    instead of attributing new source data to an earlier engine response.
    """
    from engine.solvers.data import load_doc
    document = read_json(path)
    problems = []
    for row in document["rows"]:
        case, response = row["case"], row["response"]
        current_hashes = artifact_hashes(case["doc_id"], artifacts)
        if any(current_hashes.get(name) != digest for name, digest in row["artifact_sha256"].items()):
            row["issues"] = [i for i in row["issues"] if i["code"] != "source_changed_cannot_recheck"]
            row["issues"].append({"code": "source_changed_cannot_recheck", "severity": "warning", "detail": "Saved response's source hashes differ; original checks preserved."})
        else:
            ids = {case["doc_id"]} | {c["doc_id"] for c in response.get("citations", []) if c.get("doc_id")}
            docs = {did: load_doc(did, artifacts) for did in ids}
            meta = {did: metadata_for(did, artifacts) for did in ids}
            for did in ids:
                scene = artifacts / did / "scene.json"
                if scene.exists():
                    meta[did]["_scene_item_ids"] = set(read_json(scene).get("items", {}))
            old_errors = [i for i in row["issues"] if i["code"] in ("engine_error", "external_artifact_drift")]
            issues, row["checks"], row["checked_recomputation"] = audit(case, response, docs, meta)
            row["issues"] = issues + old_errors
            row["rechecked_artifact_sha256"] = current_hashes
        for issue in row["issues"]:
            problems.append({"case_id": case["case_id"], "question": case["question"], "doc_id": case["doc_id"], **issue})
    priority = {"checked_verdict_false": 0, "card_answer_number_mismatch": 0, "false_card_equation": 0,
                "claimed_sum_not_supported": 0, "verified_without_exact_source": 1,
                "citation_item_missing": 2, "verified_with_estimated_geometry": 2,
                "missing_evidence_card": 3, "reason_not_sentence": 5}
    problems.sort(key=lambda p: (priority.get(p["code"], 4), p["case_id"]))
    document["summary"]["without_findings"] = sum(not r["issues"] for r in document["rows"])
    document["summary"]["issue_counts"] = dict(Counter(p["code"] for p in problems))
    document["top_20_problems"] = problems[:20]
    document["checks_recomputed_utc"] = datetime.now(timezone.utc).isoformat()
    document["auditor_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    write_json(path, document)
    print(json.dumps(document["summary"], indent=2))


def generalisation(artifacts):
    """Only called after the audit, with no tuning or fixes based on these files."""
    selection = read_json(OUT / "holdout_selection.json")
    full = rows(ROOT / "data/sets/questions_en.full.jsonl")
    cases = []
    for file in selection["files"]:
        pool = [dict(r, origin="generalisation", gold_kind="dataset") for r in full
                if r["doc_id"] == file["doc_id"]]
        numeric = [r for r in pool if r["type"] in ("count", "area", "length", "volume")]
        picked = stratified(numeric, 3, selection["seed"])
        used = {r["question"] for r in picked}
        picked += stratified([r for r in pool if r["question"] not in used], 3-len(picked), selection["seed"])
        if len(picked) != 3:
            raise RuntimeError(f"Not enough gold questions for {file['doc_id']}")
        for case in picked:
            eligible(case, artifacts, set())
            case["case_id"] = f"generalisation-{len(cases)+1:03d}"
            cases.append(case)
    result = execute(cases, artifacts, OUT / "generalisation.json")
    result["selection"] = selection
    outcomes = result["summary"]["gold_outcomes"]
    scored = sum(outcomes.get(k, 0) for k in ("correct", "wrong", "abstained"))
    result["accuracy"] = {"correct": outcomes.get("correct", 0), "n": scored,
                          "accuracy": outcomes.get("correct", 0) / scored if scored else None}
    result["selection_note"] = "Original fixed-seed files retained. Prefer numeric gold; files without three numeric questions use text gold for the remaining questions. Text gold is audited for evidence but not numerically scored."
    result["failures"] = [{"case_id": r["case"]["case_id"], "doc_id": r["case"]["doc_id"],
                           "question": r["case"]["question"], "gold": r["case"]["answer"],
                           "value": r["response"]["answer"].get("value"), "outcome": r["outcome"]}
                          for r in result["rows"] if r["outcome"] != "correct"]
    result["unseen_status"] = "No selected doc_id found in tracked development/test/result text at selection time. Cannot certify absence from untracked/external historical runs or training. No files used for tuning in this audit."
    write_json(OUT / "generalisation.json", result)


class AuditorTests(unittest.TestCase):
    def base(self):
        from engine.solvers.data import Doc, Item
        it = Item("door-001", "door", source="det", conf=.9)
        doc = Doc("scan", "planmap", [it])
        case = {"question": "How many doors are in this drawing?", "doc_id": "scan"}
        response = {"answer": {"value": 1, "unit": "count", "text_md": "**1 door**", "abstained": False}, "doc_ids": ["scan"],
                    "citations": [{"n": 1, "doc_id": "scan", "item_ids": [it.item_id]}],
                    "trace": [], "evidence": {"boxes": [{"item_id": it.item_id}]},
                    "reasoning": {"steps": [{"kind": "found", "text": "One door on the scanned drawing"}],
                                  "confidence": {"label": "Cross-checked", "pct": 82, "reason": "Detected on a scanned image."}}}
        return case, response, {"scan": doc}, {"scan": {"kind": "raster"}}

    def codes(self, values):
        return {i["code"] for i in audit(*values)[0]}

    def test_valid_scan(self):
        self.assertFalse(self.codes(self.base()))

    def test_scan_verified(self):
        values = self.base(); values[1]["reasoning"]["confidence"].update(label="Verified", pct=97)
        self.assertIn("verified_without_exact_source", self.codes(values))

    def test_unmatched_calibration_has_no_percent(self):
        values = self.base(); values[1]["reasoning"]["confidence"]["pct"] = None
        self.assertNotIn("invalid_confidence", self.codes(values))

    def test_bool_is_not_a_percent(self):
        values = self.base(); values[1]["reasoning"]["confidence"]["pct"] = True
        self.assertIn("invalid_confidence", self.codes(values))

    def test_missing_item(self):
        values = self.base(); values[1]["citations"][0]["item_ids"] = ["absent"]
        self.assertIn("citation_item_missing", self.codes(values))

    def test_recount_lie(self):
        values = self.base(); values[1]["trace"] = [{"detail": "plan map 1, drawing re-read 2"}]
        values[1]["reasoning"]["steps"].append({"kind": "checked", "ok": True, "text": "Matches."})
        self.assertIn("checked_verdict_false", self.codes(values))

    def test_recount_current_boxes(self):
        values = self.base(); values[1]["trace"] = [{"detail": "plan map 3, drawing re-read 1"}]
        values[1]["reasoning"]["steps"].append({"kind": "checked", "ok": False, "text": "A second look counted 1; kept the 3 boxed"})
        self.assertIn("checked_box_count_false", self.codes(values))

    def test_scene_check_uses_manifest(self):
        values = self.base()
        values[1]["reasoning"]["steps"].append({"kind": "checked", "ok": True, "text": "All 1 counted items are found in the 3D model"})
        values[3]["scan"]["_scene_item_ids"] = set()
        self.assertIn("checked_verdict_false", self.codes(values))
        values[3]["scan"]["_scene_item_ids"] = {"door-001"}
        self.assertNotIn("checked_verdict_false", self.codes(values))

    def test_recheck_preserves_checks_when_source_changed(self):
        values = self.base()
        row = {"case": dict(values[0], case_id="test"), "response": values[1],
               "artifact_sha256": {"doc.json": "old"},
               "issues": [{"code": "original", "severity": "error", "detail": "Original finding."}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.json"
            write_json(path, {"rows": [row], "summary": {}})
            with patch(__name__ + ".artifact_hashes", return_value={"doc.json": "changed"}), patch("builtins.print"):
                recheck(path, Path(tmp))
            saved = read_json(path)
        self.assertEqual(saved["rows"][0]["response"], values[1])
        self.assertEqual({i["code"] for i in saved["rows"][0]["issues"]}, {"original", "source_changed_cannot_recheck"})

    def test_false_equation(self):
        values = self.base(); values[1]["answer"].update(value=50, unit="m2", text_md="**50 m²**")
        values[1]["reasoning"]["steps"].append({"kind": "measured", "text": "Outline 10000 px² × (0.1 m/px)² = 50 m²"})
        self.assertIn("false_card_equation", self.codes(values))

    def test_sentence_fragment(self):
        values = self.base(); values[1]["reasoning"]["confidence"]["reason"] = "Detected on a scan; raised because detector confidence 90%."
        self.assertIn("reason_not_sentence", self.codes(values))

    def test_id_visible(self):
        values = self.base(); values[1]["answer"]["text_md"] += " door-001 IfcFlowSegment"
        self.assertIn("user_visible_id_or_jargon", self.codes(values))

    def test_no_card(self):
        values = self.base(); del values[1]["reasoning"]
        self.assertIn("missing_evidence_card", self.codes(values))

    def test_spelled_number_is_not_a_mismatch(self):
        values = self.base(); values[1]["answer"]["text_md"] = "**One door**"
        self.assertNotIn("headline_value_mismatch", self.codes(values))

    def test_no_items_means_zero(self):
        values = self.base(); values[1]["answer"].update(value=0, text_md="**No doors**")
        self.assertNotIn("headline_value_mismatch", self.codes(values))

    def test_polygon(self):
        poly = [[0, 0], [4, 0], [4, 3], [0, 3]]
        self.assertEqual(polygon_area(poly), 12)
        self.assertTrue(point_inside(2, 1, poly)); self.assertFalse(point_inside(8, 8, poly))


def main():
    global OUT
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--artifacts", type=Path, default=ROOT / "artifacts")
    p.add_argument("--output-dir", type=Path, default=OUT)
    p.add_argument("--prepare", action="store_true")
    p.add_argument("--run", action="store_true")
    p.add_argument("--generalisation", action="store_true")
    p.add_argument("--recheck", type=Path, help="Recompute checks on saved responses; no inference")
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    OUT = args.output_dir.resolve()
    if args.self_test:
        unittest.main(argv=[sys.argv[0]], exit=True)
    if args.prepare:
        prepare(args.artifacts)
    if args.recheck:
        recheck(args.recheck, args.artifacts)
    if args.run:
        cases_path = OUT / "audit_cases.json"
        cases = read_json(cases_path) if cases_path.exists() else prepare(args.artifacts)
        execute(cases, args.artifacts, OUT / "evidence_audit.json")
    if args.generalisation:
        generalisation(args.artifacts)


if __name__ == "__main__":
    main()
