"""Audit answer evidence without changing engine policy.

Run through scripts/heavy.sh with the repository Python. Fake models are forced;
this audits code routes, not live reader accuracy. Exit 1 means evidence failures,
2 means the audit could not run. Reports retain all failures and rank the top 30.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
NUMBER = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
UNITS = {"m²": "m2", "m³": "m3", "sqm": "m2", "sq m": "m2", "meters": "m", "metres": "m",
         "items": "count", "each": "count"}
VALUE_KEYS = {"count": ("count", "quantity"), "m": ("length_m", "perimeter_m", "width_m", "height_m"),
              "m2": ("area_m2", "net_area_m2"), "m3": ("volume_m3",), "ft": ("length_ft",),
              "ft2": ("area_ft2",), "ft3": ("volume_ft3",)}
OWNERS = {"scale": "F-SCALEPROOF", "check": "F-XCHECK", "card": "F-EVFIX", "confidence": "F-EVFIX"}


def number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def unit(value):
    return UNITS.get(str(value or "").lower(), str(value or "").lower())


def close(a, b, tolerance=1e-7):
    return number(a) is not None and number(b) is not None and math.isclose(a, b, abs_tol=tolerance, rel_tol=1e-9)


def equal(a, b, tolerance=1e-7):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k], tolerance) for k in a)
    return close(a, b, tolerance)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Sources:
    """Resolve against raw artifacts, not the solver that produced the answer."""
    def __init__(self, root):
        self.root = Path(root)
        self.cache = {}
        self.fingerprints = {}

    def json(self, path):
        if path not in self.cache:
            self.cache[path] = read_json(path)
            if path.is_file():
                self.fingerprints[str(path.relative_to(self.root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return self.cache[path]

    def doc(self, did):
        if not isinstance(did, str) or not did or Path(did).name != did or did in (".", ".."):
            return None
        path = self.root / did
        return path if path.is_dir() and (path / "doc.json").is_file() else None

    def items(self, did, page=None):
        path = self.doc(did)
        if path is None:
            return {}
        found = {}
        elements = self.json(path / "elements.json")
        for item in elements.get("elements", []) if isinstance(elements, dict) else elements:
            if isinstance(item, dict):
                found[item.get("item_id")] = item
        pages = [path / f"planmap-{page}.json"] if page else sorted(path.glob("planmap-[0-9]*.json"))
        for p in pages:
            for item in self.json(p).get("items", []):
                found[item.get("item_id")] = item
        return found

    def dimensions(self, did, page):
        path = self.doc(did)
        if path is None:
            return None
        image = self.json(path / f"planmap-{page}.json").get("image", {})
        if number(image.get("w")) and number(image.get("h")):
            return image["w"], image["h"]
        try:
            from PIL import Image
            with Image.open(path / f"page-{page}.png") as image:
                return image.size
        except (OSError, ValueError):
            return None

    def resolve(self, source, default_doc=None, require_anchor=True):
        if not isinstance(source, dict):
            return ["source is missing or is not a structured reference"]
        did = source.get("doc_id") or default_doc
        path = self.doc(did)
        if path is None:
            return [f"document does not exist: {did}"]
        errors = []
        page = source.get("page")
        meta = self.json(path / "doc.json")
        if page is not None and (type(page) is not int or page < 1 or page > (meta.get("pages") or 1)):
            errors.append(f"invalid page: {page}")
        iid = source.get("item_id")
        if iid and iid not in self.items(did, page if type(page) is int else None):
            errors.append(f"item does not exist: {iid}")
        box = source.get("bbox", source.get("bbox_px"))
        if box is not None:
            if not isinstance(box, (list, tuple)) or len(box) != 4 or any(number(x) is None for x in box):
                errors.append("invalid pixel box")
            elif box[0] < 0 or box[1] < 0 or box[2] <= box[0] or box[3] <= box[1]:
                errors.append("pixel box has negative or inverted bounds")
            else:
                dims = self.dimensions(did, page) if type(page) is int else None
                if dims is None:
                    errors.append("pixel box has no resolvable page dimensions")
                elif box[2] > dims[0] or box[3] > dims[1]:
                    errors.append("pixel box is outside the page")
        ref = source.get("file") or source.get("path") or source.get("crop")
        if ref:
            candidate = self.root / str(ref)
            if not candidate.exists():
                candidate = path / str(ref)
            if not candidate.resolve().is_relative_to(self.root.resolve()) or not candidate.is_file():
                errors.append(f"artifact reference does not resolve: {ref}")
        if require_anchor and not iid and box is None and not ref:
            errors.append("source names a document but no element, region or artifact")
        return errors


def headline_values(text, expected_unit):
    line = re.sub(r"\[\d+\]", "", (text or "").splitlines()[0] if text else "")
    line = line.replace("**", "")
    if expected_unit == "count":
        nouns = r"(?:windows?|doors?|rooms?|walls?|toilets?|sinks?|showers?|bathtubs?|stairs?|staircases?|storeys?|floors?|columns?|slabs?|elements?|items?|apartments?|bedrooms?|bathrooms?|washrooms?|balcon(?:y|ies)|kitchens?|saunas?)"
        return [float(x.replace(",", "")) for x in re.findall(rf"({NUMBER})\s+(?:external\s+|internal\s+|separate\s+)?{nouns}\b", line, re.I)]
    aliases = {"m": r"(?:m|metres?|meters?)", "m2": r"(?:m²|m2|sq\.?\s*m|square\s+met(?:er|re)s?)",
               "m3": r"(?:m³|m3|cubic\s+met(?:er|re)s?)", "ft": r"(?:ft|feet)",
               "ft2": r"(?:ft²|ft2|sq\.?\s*ft)", "ft3": r"(?:ft³|ft3)"}
    suffix = aliases.get(expected_unit, re.escape(expected_unit))
    return [float(x.replace(",", "")) for x in re.findall(rf"({NUMBER})\s*{suffix}(?![\w²³])", line, re.I)] if suffix else []


def audit(res, sources):
    findings = []
    def fail(code, detail, severity="error"):
        prefix = code.split(".")[0]
        findings.append({"code": code, "owner": OWNERS.get(prefix, "F-CALC"), "severity": severity, "detail": detail})

    ans = res.get("answer") or {}
    value, u = ans.get("value"), unit(ans.get("unit"))
    numeric = number(value) is not None or isinstance(value, dict) and bool(value) and all(number(v) is not None for v in value.values())
    reasoning = res.get("reasoning") or {}
    calc = reasoning.get("calc") or {}
    default_doc = (res.get("doc_ids") or [None])[0]
    text = ans.get("text_md") or ""
    steps = reasoning.get("steps") or []
    card_text = " ".join(str(s.get("text") or "") for s in steps)
    confidence = reasoning.get("confidence") or {}
    user_text = " ".join([text, card_text, str(confidence.get("reason") or ""), str(confidence.get("improve") or "")])
    jargon = re.findall(r"\bIfc[A-Z]\w+\b|\bDN0\b|\b[a-z0-9_]+__[a-z0-9-]+\b|\b[0-9A-Za-z_$]{22}\b", user_text)
    if jargon:
        fail("card.jargon", f"technical names or internal identifiers in text: {jargon[:3]}")
    if re.search(r"\bRead\s+1\s+marked region|\b1\s+marked region of", card_text, re.I):
        fail("card.meaningless_read", "card describes one marked region without explaining what was found")

    def source_check(source, label, anchor=True):
        for error in sources.resolve(source, default_doc, anchor):
            fail("source.unresolved", f"{label}: {error}")

    for c in res.get("citations") or []:
        base = {**c, "bbox": c.get("bbox_px")}
        ids = c.get("item_ids") or []
        if ids:
            for iid in ids:
                source_check({**base, "item_id": iid}, "citation")
        else:
            source_check(base, "citation")
    evidence = res.get("evidence") or {}
    for box in evidence.get("boxes") or []:
        source_check({**box, "bbox": box.get("bbox_px")}, "numbered box")
    scene = evidence.get("scene") or {}
    for iid in scene.get("highlight_item_ids") or []:
        source_check({"doc_id": scene.get("doc_id") or default_doc, "item_id": iid}, "3D highlight")

    if not numeric:
        return {"status": "fail" if findings else "not_numeric", "numeric": False, "findings": findings}
    if ans.get("abstained"):
        fail("card.abstained_numeric", "abstention carries a numeric answer")
    if not u:
        fail("calc.unit_missing", "numeric answer has no unit")
    if not calc:
        fail("calc.missing", "numeric answer has no reasoning.calc")
    result = calc.get("result") or {}
    target = result.get("value")
    if calc and not equal(value, target):
        fail("calc.headline_result", f"answer.value {value!r} differs from calc.result {target!r}")
    if calc and unit(result.get("unit")) != u:
        fail("calc.result_unit", f"answer unit {u!r} differs from calc.result unit {result.get('unit')!r}")
    shown = headline_values(text, u)
    expected = list(value.values()) if isinstance(value, dict) else [value]
    if not shown:
        fail("card.headline_uncheckable", "headline numeric quantity could not be parsed", "uncheckable")
    elif not all(any(close(v, n, 0.005 if u != "count" else 1e-7) for n in shown) for v in expected):
        fail("card.headline_value", f"headline quantities {shown} do not reproduce answer.value {value!r}")

    rows = calc.get("rows") or []
    totals = defaultdict(float)
    unknown_rows = False
    seen = set()
    for row in rows:
        source = row.get("source")
        source_check(source, "calculation row")
        identity = ((source or {}).get("doc_id", default_doc), (source or {}).get("page"), row.get("item_id")) if isinstance(source, dict) else None
        if identity and identity[2]:
            if identity in seen:
                fail("calc.duplicate_row", f"element counted twice: {identity}")
            seen.add(identity)
        vals = row.get("values") or {}
        keys = [k for k in VALUE_KEYS.get(u, (u,)) if number(vals.get(k)) is not None]
        if len(keys) == 1:
            totals["scalar"] += vals[keys[0]]
        elif u == "count" and not keys and row.get("item_id"):
            totals["scalar"] += 1
        else:
            unknown_rows = True
        for kind in value if isinstance(value, dict) else []:
            if number(vals.get(kind)) is not None:
                totals[kind] += vals[kind]
            elif row.get("kind") == kind:
                totals[kind] += vals.get("count", 1)
    if calc:
        if not rows and not calc.get("steps"):
            fail("calc.no_workings", "calculation has neither element rows nor steps")
        elif rows:
            actual = {k: totals[k] for k in value} if isinstance(value, dict) else totals["scalar"]
            if unknown_rows:
                fail("calc.rows_uncheckable", "row quantity columns cannot be mapped uniquely to result units", "uncheckable")
            elif not equal(actual, target, 0.005 if u != "count" else 1e-7):
                fail("calc.rows_sum", f"sum of rows {actual!r} differs from result {target!r}; exclusions/conversions need a reconcilable step")
        if not calc.get("formula"):
            fail("calc.formula_missing", "calculation has no formula")
        if not result.get("rounded_as"):
            fail("calc.rounding_missing", "calculation does not state display rounding")
    for step in calc.get("steps") or []:
        if number(step.get("value")) is not None and not step.get("unit"):
            fail("calc.step_unit", f"step {step.get('id')!r} has an implicit unit")
        for operand in step.get("inputs") or []:
            if not operand.get("unit"):
                fail("calc.input_unit", f"input {operand.get('name')!r} has no explicit unit (use '1' for dimensionless)")
            source_check(operand.get("source"), f"input {operand.get('name')!r}")
            if re.search(r"model|recount|vision", str(operand.get("name") or ""), re.I) and not re.search(r"model|recount|vision", str(step.get("label") or ""), re.I):
                fail("calc.model_input", "model output is used without labelling the model step")

    margins = [("reasoning.margin", reasoning.get("margin"))]
    if calc:
        margins.append(("calc.margin", calc.get("margin")))
    for name, margin in margins:
        if not isinstance(margin, dict):
            fail("scale.margin_missing" if u != "count" else "calc.margin_missing", f"{name} is missing")
            continue
        if unit(margin.get("unit")) != u:
            fail("calc.margin_unit", f"{name} unit differs from the measured quantity")
        if not margin.get("why"):
            fail("calc.margin_reason", f"{name} has no explanation")
        err, pct = margin.get("value"), margin.get("pct")
        if err is not None and (number(err) is None or err < 0):
            fail("calc.margin_invalid", f"{name} has an invalid absolute margin")
        if pct is not None and (number(pct) is None or pct < 0):
            fail("calc.margin_pct", f"{name} has an invalid percentage")
        elif pct is not None and number(value) is not None:
            expected_pct = abs(err / value) * 100 if number(err) is not None and value else 0 if err == 0 else None
            if expected_pct is None or not close(pct, expected_pct, 0.05):
                fail("calc.margin_pct", f"{name} percentage {pct!r} does not match absolute margin {err!r} and value {value!r}")
        if err is None and pct is not None:
            fail("calc.margin_unknown", f"{name} claims a percentage with unknown absolute uncertainty")

    checks = calc.get("checks") or []
    for check in checks:
        if not check.get("method"):
            fail("check.method", "comparison does not name its second method")
        second = number(check.get("value"))
        primary = number(value)
        diff = number(check.get("diff_pct"))
        if second is not None and primary is not None:
            measured = abs(second - primary) / abs(primary) * 100 if primary else 0 if second == 0 else None
            if diff is not None and (measured is None or not close(diff, measured, 0.05)):
                fail("check.diff_pct", f"reported difference {diff} is inconsistent with {primary} vs {second}")
            if check.get("agrees") is True and not close(primary, second) and diff is None:
                fail("check.agreement_unbounded", "different quantities called agreeing without a measured difference")
    label = confidence.get("label")
    checked = any(c.get("agrees") is True for c in checks) or any(s.get("kind") == "checked" and s.get("ok") is True for s in steps)
    disagreement = any(c.get("agrees") is False for c in checks) or any(s.get("kind") == "checked" and s.get("ok") is False for s in steps)
    based = reasoning.get("based_on") or {}
    if label not in ("Verified", "Cross-checked", "Estimate"):
        fail("confidence.missing", "numeric answer lacks a valid confidence label")
    if label == "Cross-checked" and not checked:
        fail("confidence.unchecked", "Cross-checked label has no recorded agreeing comparison")
    if label == "Verified":
        if disagreement or based.get("estimated") or based.get("unresolved"):
            fail("confidence.overclaim", "Verified label has disagreeing, estimated or unresolved evidence")
        if not reasoning.get("arithmetic") and not calc:
            fail("confidence.unproven", "Verified label has no reproducible arithmetic")
    pct = confidence.get("pct")
    calibration = confidence.get("calibration") or {}
    if pct is not None:
        n, correct = calibration.get("n"), calibration.get("correct")
        if number(pct) is None or not 0 <= pct <= 100 or type(n) is not int or type(correct) is not int or not 0 <= correct <= n or n <= 0 or not close(pct, round(correct / n * 100)):
            fail("confidence.uncalibrated", "confidence percentage is not backed by valid observed correct/n counts")
    if u == "count" and number(value) is not None:
        boxes = evidence.get("boxes") or []
        unique = {(b.get("doc_id") or default_doc, b.get("page"), b.get("item_id")) for b in boxes}
        caveat = re.search(r"(?:unboxed|not boxed|not all|only\s+\d+|differs?|disagree|missing|unmarked|unresolved|not individually|source.*(?:incomplete|completeness)|not.*(?:completeness|complete)|partial)", text + " " + card_text, re.I)
        if boxes and len(unique) != value and not caveat:
            fail("card.box_count", f"headline count {value:g} has {len(unique)} numbered elements without explaining the difference")
        for s in steps:
            if s.get("kind") == "found":
                found = headline_values(str(s.get("text") or ""), "count")
                if len(found) == 1 and not close(found[0], value) and not caveat:
                    fail("card.found_count", f"Found step reports {found[0]:g}, headline reports {value:g}")
    errors = any(f["severity"] == "error" for f in findings)
    return {"status": "fail" if errors else "uncheckable" if findings else "pass", "numeric": True, "findings": findings}


def question_rows(path):
    if not path.exists():
        return []
    if path.suffix == ".jsonl":
        data = [json.loads(s) for s in path.read_text().splitlines() if s.strip()]
    else:
        data = read_json(path)
        if isinstance(data, dict):
            data = next((data[k] for k in ("questions", "rows", "results") if isinstance(data.get(k), list)), [])
    return [r for r in data if isinstance(r, dict) and isinstance(r.get("question") or r.get("q"), str)]


def select_questions(repo, artifacts, limit=200, seed=20261114, blind=None, extra=()):
    sys.path.insert(0, str(repo))
    from pipeline.langcheck import is_english
    from pipeline.registry import doc_id_for_question_path
    paths = [repo / "data/sets/sample200.jsonl", repo / "data/junction-dataset-preview/questions.jsonl"]
    qa = repo / "results/final/QA"
    if qa.exists():
        paths.extend(sorted(qa.rglob("*.jsonl")) + sorted(qa.rglob("*.json")))
    paths.extend(Path(p) for p in extra)
    buckets = defaultdict(list)
    excluded = Counter()
    seen = set()
    for path in paths:
        for raw in question_rows(path):
            q = raw.get("question") or raw.get("q")
            if not is_english(q):
                excluded["non_english"] += 1
                continue
            ids = raw.get("doc_ids") or ([raw["doc_id"]] if raw.get("doc_id") else [])
            if not ids and raw.get("path"):
                ids = [doc_id_for_question_path(raw["path"])]
            if not ids:
                excluded["no_document_id"] += 1
                continue
            docs = [read_json(artifacts / did / "doc.json") for did in ids]
            if any(d.get("kind") == "pdf" for d in docs):
                excluded["pdf_out_of_scope"] += 1
                continue
            if not all((artifacts / did / "elements.json").exists() or list((artifacts / did).glob("planmap-[0-9]*.json")) for did in ids):
                excluded["no_structured_artifacts"] += 1
                continue
            key = (tuple(ids), q)
            if key in seen:
                continue
            seen.add(key)
            origin = path.relative_to(repo).as_posix() if path.is_relative_to(repo) else str(path)
            fmt = "+".join(sorted({d.get("kind", "unknown") for d in docs}))
            source = "+".join(sorted({d.get("source", "unknown") for d in docs}))
            row = {"question": q, "doc_ids": ids, "origin": origin, "format": fmt, "source": source,
                   "type": raw.get("type", "unknown"), "gold": raw.get("answer", raw.get("gold"))}
            buckets[(origin, fmt, source, row["type"])].append(row)
    rng = random.Random(seed)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    # Reserve the blind document for the end; never inspect its content here.
    blind_rows = [r for b in buckets.values() for r in b if blind in r["doc_ids"]] if blind else []
    chosen = []
    slots = limit - bool(blind_rows)
    while len(chosen) < slots and any(buckets.values()):
        for key in sorted(buckets):
            if len(chosen) >= slots:
                break
            if buckets[key]:
                row = buckets[key].pop()
                if not blind or blind not in row["doc_ids"]:
                    chosen.append(row)
    if blind_rows and limit:
        chosen.append(blind_rows[0])
    return chosen, {"excluded": dict(excluded), "input_files": [str(p.relative_to(repo)) if p.is_relative_to(repo) else str(p) for p in paths if p.exists()], "seed": seed}


def copy_artifacts(source, target, doc_ids):
    """JSON is copied because existing OCR/scale code writes adjacent caches.

    Large binary source assets are linked for reading only. No engine execution
    is permitted against the shared artifacts directory.
    """
    for did in doc_ids:
        dest = target / did
        dest.mkdir(parents=True)
        for path in (source / did).iterdir():
            if path.is_file():
                if path.suffix == ".json":
                    shutil.copy2(path, dest / path.name)
                else:
                    (dest / path.name).symlink_to(path.resolve())


def run(repo, artifacts, rows, output, timeout=20):
    sys.path.insert(0, str(repo))
    os.environ.update(MODELS_FAKE="1", EXPLAIN="0", RECOUNT_CACHE="0")
    runtime = repo / ".evqa-runtime"
    runtime.mkdir(exist_ok=True)
    records = []
    with tempfile.TemporaryDirectory(prefix="audit-", dir=runtime) as temp:
        local = Path(temp)
        shadow = local / "artifacts"
        shadow.mkdir()
        # Copy just before each question, so the blind file is first read last.
        copied = set()
        os.environ.update(ARTIFACTS_DIR=str(shadow), RESULTS_DIR=str(local / "results"),
                          MODELS_CACHE_DIR=str(local / "models"), MODELS_COSTS_LOG=str(local / "costs.jsonl"))
        from engine.answer import answer
        sources = Sources(shadow)
        for i, row in enumerate(rows, 1):
            t0 = time.perf_counter()
            try:
                missing = set(row["doc_ids"]) - copied
                copy_artifacts(artifacts, shadow, missing)
                copied.update(missing)
                def timed_out(signum, frame):
                    raise TimeoutError(f"question exceeded {timeout:g} seconds")
                previous = signal.signal(signal.SIGALRM, timed_out)
                signal.setitimer(signal.ITIMER_REAL, timeout)
                try:
                    res = answer(row["question"], row["doc_ids"])
                finally:
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    signal.signal(signal.SIGALRM, previous)
                check = audit(res, sources)
                record = {**row, **check, "answer": res.get("answer"), "route": res.get("route"),
                          "reasoning": res.get("reasoning"), "cost_usd": (res.get("cost") or {}).get("usd_total", 0),
                          "boxes": len((res.get("evidence") or {}).get("boxes") or []),
                          "fake_model_used": any(s.get("model") for s in res.get("trace") or [])}
            except Exception as exc:
                record = {**row, "status": "error", "numeric": False, "findings": [{"code": "execution.error", "owner": "F-CALC", "severity": "error", "detail": f"{type(exc).__name__}: {exc}"[:500]}]}
            record["ms"] = round((time.perf_counter() - t0) * 1000)
            records.append(record)
            if i % 10 == 0 or i == len(rows):
                print(f"audited {i}/{len(rows)}", flush=True)
        fingerprints = sources.fingerprints
    groups = defaultdict(list)
    for record in records:
        for finding in record["findings"]:
            groups[(finding["owner"], finding["code"], finding["severity"])].append({"doc_ids": record["doc_ids"], "question": record["question"], "detail": finding["detail"]})
    ranked = sorted(groups.items(), key=lambda pair: (pair[0][2] != "error", -len(pair[1]), pair[0]))
    top = [{"owner": key[0], "code": key[1], "severity": key[2], "occurrences": len(examples), "examples": examples[:3]} for key, examples in ranked[:30]]
    summary = {"questions": len(records), "statuses": dict(Counter(r["status"] for r in records)),
               "numeric_answers": sum(r["numeric"] for r in records), "formats": dict(Counter(r["format"] for r in records)),
               "sources": dict(Counter(r["source"] for r in records)), "origins": dict(Counter(r["origin"] for r in records)),
               "cost_usd": round(sum(r.get("cost_usd", 0) for r in records), 6),
               "failure_occurrences_by_owner": dict(Counter(f["owner"] for r in records for f in r["findings"])),
               "fake_model_answers": sum(bool(r.get("fake_model_used")) for r in records)}
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "revision": subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip(),
              "mode": "MODELS_FAKE=1; code-route evidence audit; no live model accuracy claim", "summary": summary,
              "limitations": ["No PDF internals, live model verification, or correctness claim against potentially noisy dataset gold.",
                              "Unrecognized headline/row semantics are uncheckable, never counted as passing.",
                              "A finite unknown margin with an explanation is honest; no arbitrary percentage ceiling is imposed.",
                              "Only existing structured artifacts are eligible; missing-data exclusions are reported."],
              "top_30": top, "artifact_sha256": fingerprints, "records": records}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=1, allow_nan=False) + "\n")
    print(json.dumps(summary, sort_keys=True), flush=True)
    print(f"report: {output}", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20261114)
    parser.add_argument("--questions", type=Path, action="append", default=[])
    parser.add_argument("--blind", type=Path, default=ROOT / "results/final/EVQA/blind.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()
    if args.limit < 1 or args.timeout <= 0:
        parser.error("limit and timeout must be positive")
    repo = args.repo.resolve()
    artifacts = (args.artifacts or repo / "artifacts").absolute()
    output = args.output or ROOT / "results/final/EVQA" / f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    rows, selection = select_questions(repo, artifacts, args.limit, args.seed, read_json(args.blind).get("doc_id"), args.questions)
    if not rows:
        print("No eligible questions with structured artifacts.", file=sys.stderr)
        return 2
    report = run(repo, artifacts, rows, output, args.timeout)
    report["selection"] = selection
    report["blind"] = read_json(args.blind)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=1, allow_nan=False) + "\n")
    return int(any(r["status"] in ("fail", "error", "uncheckable") for r in report["records"]))


if __name__ == "__main__":
    raise SystemExit(main())
