#!/usr/bin/env python3
"""Judge-style NON-PDF regression runner. No engine edits, model judge, or gold from engine output.

Commands (run build/run/watch through scripts/heavy.sh):
  python scripts/judge_hard.py build
  python scripts/judge_hard.py run --revision main --max-usd 1
  python scripts/judge_hard.py run --revision final/mep --max-usd .5
  python scripts/judge_hard.py run --include-holdout --include-unseen --max-usd .5
  python scripts/judge_hard.py watch --interval 3600 --cycles 1 --max-usd .5
  python scripts/judge_hard.py self-test

Holdout question text/answers live ONLY in a mode-0700 temporary directory, never
in public reports. The committed manifest lists their IDs and file digest.
Unseen-file questions are generated only by `unseen`, after runner development.
Each question runs in its own process group, with a wall timeout. A SQLite ledger
reserves conservative request costs BEFORE provider dispatch, including attempts
which later fail schema validation. Unknown prices and oversized requests fail
closed. Reservations for interrupted/failed requests remain charged. The ledger
is shared by all runs in this session: default total row cap $3, per-run <=$4.
This is an estimated-price cap, not a billing guarantee; the report says so.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/final/QA"
CASES = ROOT / "engine/tests/data/judge_hard.jsonl"
HANDOFF = Path("/Users/akshatthapa/Workspace/junction/handoff/F-QA.md")
SEED = 20261114
KINDS = {"door": "IfcDoor", "window": "IfcWindow", "column": "IfcColumn",
         "beam": "IfcBeam", "pipe": "IfcPipeSegment", "duct": "IfcDuctSegment",
         "light": "IfcLightFixture", "sprinkler": "IfcFireSuppressionTerminal"}
JARGON = re.compile(r"\bIfc[A-Z][A-Za-z0-9_]*\b|\bDN0\b|\b[0-3][A-Za-z0-9_$]{21}\b|"
                    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
MISSING = re.compile(r"cannot|can't|could not|couldn't|not (?:available|provided|recorded|shown|specified|present)|"
                     r"no (?:data|information|recorded|reliable)|missing|unable|need(?:s)? (?:a |the |an )?(?:drawing|model|scale|file|schedule)", re.I)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def digest_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def id_digest(ids):
    return hashlib.sha256("\n".join(sorted(set(ids))).encode()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def state_path():
    return OUT / "private-state.json"


def private_state():
    # Persist no secrets here; only the path to this QA session's private ledger.
    p = state_path()
    if p.exists():
        state = json.loads(p.read_text())
        if Path(state["directory"]).is_dir():
            return state
    directory = Path(tempfile.mkdtemp(prefix="judge-hard-qa-"))
    directory.chmod(0o700)
    state = {"directory": str(directory), "created": now(), "row_cap_usd": 3.0}
    write_json(p, state)
    return state


def safe_by_type(model, cls):
    try:
        return model.by_type(cls)
    except RuntimeError:  # IFC2x3 has generic flow occurrences + specialized types
        return []


def raw_ifc(path):
    """Independent source query: no pipeline/engine code, no triangulation."""
    import ifcopenshell
    import ifcopenshell.util.element as E
    import ifcopenshell.util.unit as U
    f = ifcopenshell.open(str(path))
    buckets = {k: {x.GlobalId: x for x in safe_by_type(f, cls)} for k, cls in KINDS.items()}
    for rel in safe_by_type(f, "IfcRelDefinesByType"):
        typ = rel.RelatingType
        for kind, cls in KINDS.items():
            if typ.is_a() == cls + "Type":
                for x in rel.RelatedObjects:
                    if x.is_a("IfcElement"):
                        buckets[kind][x.GlobalId] = x
    # Do not silently call every fire terminal a sprinkler (hose reels etc. exist).
    buckets["sprinkler"] = {i: x for i, x in buckets["sprinkler"].items()
                            if str(getattr(x, "PredefinedType", None) or getattr(E.get_type(x), "PredefinedType", None)) == "SPRINKLER"}
    units = U.calculate_unit_scale(f)
    counts = {k: len(v) for k, v in buckets.items()}
    group_kind = "door" if counts["door"] else max(counts, key=counts.get)
    storeys = Counter()
    storey_ids = {}
    for iid, x in buckets[group_kind].items():
        container = E.get_container(x)
        while container is not None and not container.is_a("IfcBuildingStorey"):
            container = E.get_aggregate(container)
        if container is not None:
            name = container.Name or container.GlobalId
            storeys[name] += 1
            storey_ids.setdefault(name, []).append(iid)
    chosen = sorted(storeys, key=lambda n: (-storeys[n], n))[0] if storeys else None
    widths = {iid: float(x.OverallWidth) * units for iid, x in buckets["door"].items()
              if getattr(x, "OverallWidth", None) is not None}
    narrow = [iid for iid, w in widths.items() if 0 < w < 0.9]
    missing_fire = []
    for iid, x in buckets["door"].items():
        ps = E.get_psets(x)
        ratings = [v for props in ps.values() if isinstance(props, dict)
                   for k, v in props.items() if k.casefold() == "firerating" and v not in (None, "")]
        if not ratings:
            missing_fire.append(iid)
    apps = [x.ApplicationFullName for x in safe_by_type(f, "IfcApplication")]
    return {"schema": f.schema, "authoring_tools": apps, "unit_scale_m": units,
            "counts": counts, "ids": {k: sorted(v) for k, v in buckets.items()},
            "storey_kind": group_kind, "storey": chosen,
            "storey_ids": storey_ids.get(chosen, []), "storey_count": len(storeys),
            "narrow_door_ids": narrow, "missing_width_count": counts["door"] - len(widths),
            "missing_fire_ids": missing_fire}


def raw_dxf(path):
    import ezdxf
    doc = ezdxf.readfile(path)
    ms = doc.modelspace()
    texts = []
    for x in ms.query("TEXT MTEXT"):
        texts.append({"text": x.plain_text() if x.dxftype() == "MTEXT" else x.dxf.text,
                      "layer": x.dxf.layer, "handle": x.dxf.handle})
    return {"dxf_version": doc.dxfversion, "insunits": doc.header.get("$INSUNITS", 0),
            "entities": len(ms), "entity_types": dict(Counter(x.dxftype() for x in ms)),
            "texts": texts, "layers": dict(Counter(x.dxf.layer for x in ms))}


def expected(value, unit="count", ids=None, method="", **extra):
    return {"value": value, "unit": unit, "abs_tol": 0 if unit == "count" else 0.01,
            "item_count": len(set(ids)) if ids is not None else None,
            "item_ids_sha256": id_digest(ids) if ids is not None else None,
            "method": method, **extra}


def doc_cases(doc_id, meta, reference):
    out = []
    def add(key, question, owner, gold=None, note=None):
        out.append({"id": f"{doc_id}:{key}", "doc_ids": [doc_id], "question": question,
                    "owner": owner, "expected": gold, "oracle_note": note})
    if meta["kind"] == "ifc":
        r = reference
        for k in ("door", "window", "column", "beam", "pipe", "duct", "light"):
            noun = {"pipe": "straight pipe segments", "duct": "straight duct segments", "light": "light fixtures"}.get(k, k + "s")
            method = f"Raw {r['schema']}: {KINDS[k]} occurrences union matching typed generic occurrences; unique GlobalIds."
            add(k, f"How many {noun} are recorded in this model, across all storeys?", "MEP" if k in ("pipe", "duct", "light") else "PROPS",
                expected(r["counts"][k], ids=r["ids"][k], method=method))
        if r["storey"]:
            k = r["storey_kind"]
            add("storey", f'How many {k}s are on storey "{r["storey"]}"?', "PROJECTS",
                expected(len(r["storey_ids"]), ids=r["storey_ids"], method="Raw IFC containment/aggregation relations to a building storey."))
        else:
            add("storey", "Give a per-storey breakdown of the recorded building services.", "PROJECTS", note="No independently resolvable containment for this class.")
        add("width", "How many doors have a recorded overall width strictly below 0.9 metres?", "PROPS",
            expected(len(r["narrow_door_ids"]), ids=r["narrow_door_ids"],
                     method="Raw IfcDoor.OverallWidth * project length-unit conversion; missing widths excluded.",
                     missing_source_values=r["missing_width_count"]))
        add("fire", "How many door objects have no fire rating recorded?", "PROPS",
            expected(len(r["missing_fire_ids"]), ids=r["missing_fire_ids"], method="Raw occurrence and inherited type property sets: missing/nonempty FireRating key."))
        add("volume", "What total net volume of floor slabs is explicitly recorded, and is it complete enough to order concrete?", "ORDER", note="No certified independent net-volume oracle; do not infer volume from bounding boxes.")
        add("order", "How many doors should I order for the recorded door count plus a 10% spare allowance, rounded up?", "ORDER",
            expected(math.ceil(r["counts"]["door"] * 1.1), ids=None, method="ceil(raw unique door count * 1.1); allowance requested by question."))
    else:
        questions = [
            ("doors", "How many doors are on this drawing? Show each one.", "SCANSYM"),
            ("windows", "Count the windows on this drawing, and identify uncertain symbols.", "SCANSYM"),
            ("services", "How many sprinklers and light fittings are shown? Keep the two counts separate.", "MEP"),
            ("area", "What is the total floor area in square metres, and what printed scale supports it?", "SCALES"),
            ("width", "Which doors are narrower than 0.9 metres? Say if widths cannot be verified.", "SCALES"),
            ("schedule", "List the door fire ratings from the schedule and identify missing ratings.", "PROPS"),
            ("order", "What pipe lengths and diameters can I order from this drawing? Separate verified quantities from missing specifications.", "ORDER"),
            ("mistakes", "Are there conflicting dimensions or duplicate room labels? Cite each issue, or say what cannot be checked.", "MISTAKES"),
            ("storeys", "Which storeys does this drawing cover, and are there any omitted floor plans?", "PROJECTS"),
            ("structure", "How many structural columns can be verified on this drawing? Mark their positions.", "ROBUST"),
        ]
        for key, q, owner in questions:
            add(key, q, owner, note="No independently verified visual/semantic oracle. Behaviour checks only; not numeric accuracy.")
    return out


def build(unseen=False):
    selection = json.loads((OUT / "selection.json").read_text())
    state = private_state()
    private = Path(state["directory"])
    docs = selection["documents"] if not unseen else []
    if unseen:
        raw = ROOT / selection["unseen_file"]
        # Resolve metadata only at this final step, never while developing.
        for p in (ROOT / "artifacts").glob("*/doc.json"):
            meta = json.loads(p.read_text())
            rel = meta.get("files", {}).get("ifc")
            if rel and (ROOT / "data/full/junction-dataset" / rel).resolve() == raw.resolve():
                docs = [p.parent.name]
                break
        if not docs:
            raise ValueError("Reserved raw file has no registered document")
    cases, inventory, refs = [], [], {}
    for did in docs:
        meta = json.loads((ROOT / "artifacts" / did / "doc.json").read_text())
        if meta["kind"] == "pdf":
            raise ValueError("PDF ingestion is out of QA scope")
        fmt = {"raster": next((f for f in ("png", "jpg", "jpeg", "tif") if f in meta["files"]), None)}.get(meta["kind"], meta["kind"])
        raw = ROOT / "data/full/junction-dataset" / meta["files"][fmt]
        if not raw.exists():
            raw = ROOT / "data/junction-dataset-preview" / meta["files"][fmt]
        print(f"{now()} source {did}", flush=True)  # no question text
        ref = {}
        if fmt in ("ifc", "dxf"):
            proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "_reference", fmt, str(raw)],
                                  capture_output=True, text=True, timeout=180)
            if proc.returncode:
                raise RuntimeError(f"raw {fmt} extraction failed: {proc.stderr[-300:]}")
            ref = json.loads(proc.stdout)
        inventory.append({"doc_id": did, "raw_file": str(raw.relative_to(ROOT)), "format": fmt,
                          "raw_bytes": raw.stat().st_size, "sha256": digest_file(raw),
                          "schema": ref.get("schema"), "authoring_tools": ref.get("authoring_tools"),
                          "unit_scale_m": ref.get("unit_scale_m"), "storey_count": ref.get("storey_count"),
                          "raw_counts": ref.get("counts"), "raw_entities": ref.get("entities"),
                          "raw_entity_types": ref.get("entity_types"), "raw_dxf_insunits": ref.get("insunits")})
        refs[did] = ref
        cases.extend(doc_cases(did, meta, ref))
    if not unseen:
        # Additional tests are configured in data, never in inference code.
        for spec in selection.get("cross_document", []):
            ds = spec["doc_ids"]
            k = spec["kind"]
            values = [refs[d]["counts"][k] for d in ds]
            value = values[1] - values[0] if spec["operation"] == "difference" else sum(values)
            cases.append({"id": spec["id"], "doc_ids": ds, "question": spec["question"], "owner": spec["owner"],
                          "expected": expected(value, method=f"Independent raw IFC {spec['operation']} of {k} counts: {values}."), "oracle_note": None})
        n = len(cases) // 5
        held_ids = set(random.Random(SEED).sample([q["id"] for q in cases], n))
        public, held = [], []
        for q in cases:
            q["split"] = "holdout" if q["id"] in held_ids else "public"
            (held if q["split"] == "holdout" else public).append(q)
        CASES.parent.mkdir(parents=True, exist_ok=True)
        CASES.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in public))
        heldfile = private / "holdout.jsonl"
        heldfile.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in held))
        heldfile.chmod(0o600)
        write_json(OUT / "corpus.json", {"created": now(), "seed": SEED, "questions": len(cases), "public": len(public),
                   "holdout": len(held), "holdout_ids": sorted(held_ids), "holdout_sha256": digest_file(heldfile),
                   "holdout_storage": "Private temporary session directory; see private-state.json. Do not share question text.",
                   "source_inventory": inventory, "oracle_scope": "IFC raw queries only. DXF/raster/DWG have expected=null; no accuracy claim.",
                   "gold_questions": sum(q["expected"] is not None for q in cases)})
        print(json.dumps({"total": len(cases), "public": len(public), "holdout": len(held)}))
    else:
        for q in cases:
            q["split"] = "unseen"
        unseenfile = private / "unseen.jsonl"
        unseenfile.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in cases))
        unseenfile.chmod(0o600)
        write_json(OUT / "unseen-manifest.json", {"created": now(), "questions": len(cases),
                   "source_inventory": inventory, "ids": [q["id"] for q in cases], "sha256": digest_file(unseenfile)})


class BudgetLedger:
    def __init__(self, path, row_cap=3.0):
        self.path, self.row_cap = str(path), row_cap
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, run TEXT, amount REAL, actual REAL, state TEXT)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def totals(self, run=None):
        with self.connect() as db:
            rows = db.execute("SELECT amount,actual,state FROM calls" + (" WHERE run=?" if run else ""), (run,) if run else ()).fetchall()
        return {"accounted_usd": round(sum(r[0] for r in rows), 8),
                "reported_usd": round(sum(r[1] or 0 for r in rows), 8),
                "unsettled_reserve_usd": round(sum(r[0] for r in rows if r[2] != "settled"), 8), "requests": len(rows)}

    def reserve(self, run, amount, run_cap):
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("Invalid budget reservation")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            all_used = db.execute("SELECT coalesce(sum(amount),0) FROM calls").fetchone()[0]
            used = db.execute("SELECT coalesce(sum(amount),0) FROM calls WHERE run=?", (run,)).fetchone()[0]
            if all_used + amount > self.row_cap + 1e-9 or used + amount > run_cap + 1e-9:
                return None
            return db.execute("INSERT INTO calls(run,amount,state) VALUES(?,?,'reserved')", (run, amount)).lastrowid

    def settle(self, rid, actual):
        if not isinstance(actual, (int, float)) or not math.isfinite(actual) or actual < 0:
            return  # preserve reservation when billing info is invalid
        with self.connect() as db:
            db.execute("UPDATE calls SET amount=?,actual=?,state='settled' WHERE id=?", (actual, actual, rid))


def install_guard(ledger, run_id, run_cap, mode):
    from engine.models import core, providers
    blocked = []
    cfg = core.config()
    def wrap(name, adapter):
        def guarded(pcfg, model, messages, images, schema, params, key):
            if name == "fake":
                # Fake unit runs are clearly labeled and never treated as a live baseline.
                if mode == "fake":
                    return adapter(pcfg, model, messages, images, schema, params, key)
                blocked.append("no_live_provider")
                raise core.BudgetExceeded("QA: missing live provider, do not substitute generated answers")
            price = cfg.get("prices", {}).get(name, {}).get(model)
            if mode == "code" or price is None or params.get("kind") == "audio":
                blocked.append("code_only" if mode == "code" else "unpriced_request")
                raise core.BudgetExceeded("QA: provider request disabled or unpriced")
            # One token per UTF-8 byte is deliberately pessimistic. Include schema,
            # framing, image bytes, and double the requested completion allowance.
            prompt_bound = len(json.dumps(messages, ensure_ascii=False).encode()) + len(json.dumps(schema).encode()) + 8192
            prompt_bound += sum(max(len(i.data), 16384) for i in images)
            output_bound = 2 * int(params.get("max_tokens", 1024))
            reserve = 2 * (prompt_bound * price.get("in", 0) + output_bound * price.get("out", 0)) / 1e6
            rid = ledger.reserve(run_id, reserve, run_cap)
            if rid is None:
                blocked.append("budget_reservation_denied")
                raise core.BudgetExceeded("QA: run/row budget reservation denied")
            # A failed paid call retains its reservation, including HTTP/schema failures.
            response = adapter(pcfg, model, messages, images, schema, params, key)
            actual = core._cost(cfg, name, model, response)
            ledger.settle(rid, actual)
            return response
        return guarded
    providers.ADAPTERS = {name: wrap(name, fn) for name, fn in providers.ADAPTERS.items()}
    core.MAX_RETRIES = 0  # a repeated paid attempt requires a fresh reservation
    return blocked


def number_equal(actual, want, tol=0):
    if isinstance(want, dict):
        return isinstance(actual, dict) and actual.keys() == want.keys() and all(number_equal(actual[k], v, tol) for k, v in want.items())
    return (type(actual) in (int, float) and type(want) in (int, float)
            and math.isfinite(actual) and math.isclose(actual, want, rel_tol=0, abs_tol=tol))


def grade(q, res):
    ans = res.get("answer") or {}
    text = ans.get("text_md") or ""
    lines = [s.strip() for s in text.splitlines() if s.strip()]
    cites = res.get("citations") or []
    proof = [c for c in cites if c.get("doc_id") in q["doc_ids"] and
             (c.get("item_ids") or c.get("bbox_px") or c.get("quote"))]
    reason = res.get("reasoning") or {}
    conf = reason.get("confidence") or {}
    has_label = (conf.get("label") in ("Verified", "Cross-checked", "Estimate")
                 and type(conf.get("pct")) in (int, float) and 0 <= conf["pct"] <= 100)
    honest = bool(MISSING.search(text)) and (ans.get("abstained") is True or ans.get("value") is None)
    first_bold = bool(lines and re.match(r"^\*\*[^*\n]+\*\*", lines[0]))
    bullets = len(re.findall(r"(?m)^\s*(?:[-*+] |\d+[.)] )", text))
    jargon = sorted(set(JARGON.findall(text)))
    gold = q.get("expected")
    numeric = number_equal(ans.get("value"), gold["value"], gold.get("abs_tol", 0)) if gold else None
    if gold and ans.get("abstained"):
        numeric = False
    ids = {iid for c in proof for iid in c.get("item_ids") or []}
    evidence_exact = id_digest(ids) == gold["item_ids_sha256"] if gold and gold.get("item_ids_sha256") else None
    issues = []
    if numeric is False:
        issues.append("wrong_value" if not honest else "answerable_abstention")
    # Abstention need not manufacture citations/reasoning. Report their absence
    # as fields; require them only for claims the engine actually makes.
    if not honest:
        if not proof:
            issues.append("no_source_citations")
        if not reason.get("steps"):
            issues.append("no_reasoning_card")
        if not has_label:
            issues.append("no_confidence_label")
    if not first_bold:
        issues.append("headline_not_bold")
    if bullets > 4:
        issues.append("more_than_four_bullets")
    if jargon:
        issues.append("internal_jargon")
    if ans.get("abstained") and not honest:
        issues.append("unexplained_abstention")
    status = "honest-abstain" if honest else ("incorrect" if issues else "correct")
    return {"status": status, "grading_scope": "numeric_and_behaviour" if gold else "behaviour_only",
            "numeric_correct": numeric, "expected": gold["value"] if gold else None, "actual": ans.get("value"),
            "abstained": bool(ans.get("abstained")), "has_citations": bool(proof), "citation_count": len(cites),
            "cited_item_count": len(ids), "exact_count_evidence": evidence_exact,
            "has_reasoning_card": bool(reason.get("steps")), "has_reasoning_label": has_label,
            "confidence_label": conf.get("label"), "confidence_pct": conf.get("pct"),
            "jargon": jargon, "bold_first_line": first_bold, "bullets": bullets, "issues": issues,
            "answer_text": text[:8000], "answer_cost_usd": (res.get("cost") or {}).get("usd_total"),
            "route": res.get("route"), "engine_latency_ms": res.get("latency_ms")}


def worker(payload):
    sys.path.insert(0, payload["engine_root"])
    # ROOT of this script remains QA even when importing a branch snapshot.
    os.environ["ARTIFACTS_DIR"] = payload["artifacts"]
    os.environ["MODELS_CACHE_DIR"] = payload["cache"]
    os.environ["MODELS_COSTS_LOG"] = payload["cost_log"]
    os.environ["ANSWER_TIMEOUT_S"] = str(payload["timeout"] - 5)
    if payload["mode"] == "fake":
        os.environ["MODELS_FAKE"] = "1"
    else:
        os.environ.pop("MODELS_FAKE", None)
    from engine.models import core
    core.ENV_FILE = ROOT / ".env"  # read fresh, never copied or printed
    blocked = install_guard(BudgetLedger(payload["ledger"]), payload["run_id"], payload["max_usd"], payload["mode"])
    from engine.answer import answer
    started = time.perf_counter()
    res = answer(payload["case"]["question"], payload["case"]["doc_ids"])
    result = grade(payload["case"], res)
    result.update({"latency_ms": round((time.perf_counter() - started) * 1000), "blocked_model_requests": dict(Counter(blocked))})
    return result


def snapshot(revision, dest):
    sha = git("rev-parse", revision + "^{commit}")
    archive = subprocess.check_output(["git", "-C", str(ROOT), "archive", sha])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest, filter="data")
    return sha


def artifact_copy(cases, dest):
    manifest = {}
    for did in sorted({d for q in cases for d in q["doc_ids"]}):
        if Path(did).name != did or did in (".", ".."):
            raise ValueError("Unsafe document id")
        source, target = ROOT / "artifacts" / did, dest / did
        target.mkdir(parents=True)
        hashes = {}
        if source.exists():
            for p in source.iterdir():
                if not p.is_file():
                    continue
                if p.suffix == ".json":
                    shutil.copyfile(p, target / p.name)
                    hashes[p.name] = digest_file(target / p.name)
                else:
                    (target / p.name).symlink_to(p.resolve())  # image/model reads only
        manifest[did] = hashes
    return manifest


def load_cases(path):
    qs = [json.loads(s) for s in path.read_text().splitlines() if s.strip()]
    seen = set()
    for q in qs:
        if not isinstance(q.get("question"), str) or not q["question"].strip() or not q.get("doc_ids"):
            raise ValueError("Every case needs question text and doc_ids")
        if q["id"] in seen:
            raise ValueError("Duplicate case id")
        if q.get("expected") is not None and "method" not in q["expected"]:
            raise ValueError("Expected answers require independent method")
        seen.add(q["id"])
    if not qs:
        raise ValueError("Empty question set")
    return qs


def summarize(rows):
    gold = [r for r in rows if r.get("numeric_correct") is not None]
    return {"questions": len(rows), "statuses": dict(Counter(r["status"] for r in rows)),
            "numeric_questions": len(gold), "numeric_correct": sum(r["numeric_correct"] is True for r in gold),
            "behaviour_only_questions": sum(r.get("grading_scope") == "behaviour_only" for r in rows),
            "issues": dict(Counter(i for r in rows for i in r.get("issues", []))),
            "timeouts": sum(r.get("error") == "question_timeout" for r in rows),
            "latency_ms_median": sorted(r["latency_ms"] for r in rows)[len(rows)//2] if rows else None,
            "latency_ms_max": max((r["latency_ms"] for r in rows), default=None),
            "model_requests_blocked": sum(sum(r.get("blocked_model_requests", {}).values()) for r in rows)}


def report_markdown(report):
    lines = [f"# Judge hard run — {report['revision']} ({report['commit'][:12]})", "",
             f"Time: {report['created']}. Mode: {report['mode']}. "
             f"Wall time: {report['wall_s']:.1f}s. Provider-reported cost: ${report['budget']['reported_usd']:.6f}; "
             f"accounted including uncertain attempts: ${report['budget']['accounted_usd']:.6f}.", "",
             "Price reservations are conservative estimates, not provider-enforced billing guarantees. "
             "Expected=null rows check behaviour only; they cannot prove factual correctness. "
             "Formatting failures do not mean a numeric answer was wrong.", "",
             "| Split | Questions | Numeric right / checked | Honest abstain | Fully passing checks |", "|---|---:|---:|---:|---:|"]
    for split, s in report["summaries"].items():
        lines.append(f"| {split} | {s['questions']} | {s['numeric_correct']} / {s['numeric_questions']} | "
                     f"{s['statuses'].get('honest-abstain', 0)} | {s['statuses'].get('correct', 0)} |")
    lines += ["", "## Top 15 public failures", ""]
    public = [r for r in report["results"] if r.get("issues")]
    def severity(r):
        return (0 if "wrong_value" in r["issues"] else 1 if r.get("error") else 2 if "answerable_abstention" in r["issues"] else 3, -len(r["issues"]))
    for r in sorted(public, key=severity)[:15]:
        lines += [f"- **{r['owner']}** `{r['id']}`: {', '.join(r['issues'])}. "
                  + (f"Expected {r.get('expected')}, returned {r.get('actual')}. " if r.get("numeric_correct") is False else "")
                  + r["question"].replace("\n", " ")]
    if not public:
        lines.append("No public check failures.")
    lines += ["", "Holdout and unseen question text, expected values, answers and individual failures are withheld. "
              "Only aggregate checks above are published. Do not tune on either split.", ""]
    return "\n".join(lines)


def run(args):
    print(f"{now()} starting {args.revision}", flush=True)
    state = private_state()
    private = Path(state["directory"])
    qs = load_cases(args.input)
    if args.include_holdout:
        qs += load_cases(private / "holdout.jsonl")
    if args.include_unseen:
        qs += load_cases(private / "unseen.jsonl")
    if args.limit:
        qs = qs[:args.limit]
    run_id = stamp()
    work = private / run_id
    work.mkdir()
    engine_root, artifacts = work / "engine-snapshot", work / "artifacts"
    engine_root.mkdir()
    sha = snapshot(args.revision, engine_root)
    hashes = artifact_copy(qs, artifacts)
    ledger = BudgetLedger(private / "budget.sqlite")
    started, rows = time.perf_counter(), []
    report = {"created": now(), "revision": args.revision, "commit": sha, "mode": args.mode,
              "runner_sha256": digest_file(Path(__file__)), "case_file_sha256": digest_file(args.input),
              "budget_cap_usd": args.max_usd, "row_cap_usd": 3, "artifact_json_hashes": hashes,
              "corpus_sha256": digest_file(OUT / "corpus.json") if (OUT / "corpus.json").exists() else None}
    private_results = work / "all-results.jsonl"
    for index, q in enumerate(qs, 1):
        payload = {"engine_root": str(engine_root), "artifacts": str(artifacts), "cache": str(private / "model-cache"),
                   "cost_log": str(work / "model-costs.jsonl"), "ledger": ledger.path, "run_id": run_id,
                   "max_usd": args.max_usd, "case": q, "mode": args.mode, "timeout": args.timeout}
        t0 = time.perf_counter()
        proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_worker"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            output, errors = proc.communicate(json.dumps(payload), timeout=args.timeout)
            if proc.returncode:
                # Exception class / final traceback line only. Never print provider responses or headers.
                raise ValueError("worker_exit_" + str(proc.returncode))
            r = json.loads(output.splitlines()[-1])
        except (subprocess.TimeoutExpired, ValueError, IndexError) as exc:
            os.killpg(proc.pid, signal.SIGKILL) if proc.poll() is None else None
            proc.communicate()
            r = {"status": "incorrect", "error": "question_timeout" if isinstance(exc, subprocess.TimeoutExpired) else str(exc),
                 "issues": ["engine_timeout" if isinstance(exc, subprocess.TimeoutExpired) else "engine_error"],
                 "numeric_correct": False if q.get("expected") else None, "expected": q["expected"]["value"] if q.get("expected") else None,
                 "actual": None, "grading_scope": "numeric_and_behaviour" if q.get("expected") else "behaviour_only",
                 "latency_ms": round((time.perf_counter() - t0) * 1000)}
        r.update({"id": q["id"], "question": q["question"], "doc_ids": q["doc_ids"], "split": q.get("split", "public"),
                  "owner": "PERF" if r.get("error") == "question_timeout" else q.get("owner", "ROBUST"),
                  "wall_latency_ms": round((time.perf_counter() - t0) * 1000)})
        rows.append(r)
        with private_results.open("a") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        # No holdout IDs, prompts, or answers in progress output.
        print(f"{now()} {index}/{len(qs)} {r['split']} {r['status']} {r['latency_ms']}ms", flush=True)
    report.update({"wall_s": round(time.perf_counter() - started, 3), "budget": ledger.totals(run_id),
                   "row_budget": ledger.totals(), "summaries": {s: summarize([r for r in rows if r["split"] == s])
                                                            for s in sorted({r["split"] for r in rows})},
                   "results": [r for r in rows if r["split"] == "public"]})
    json_path = OUT / f"run-{run_id}.json"
    write_json(json_path, report)
    json_path.with_suffix(".md").write_text(report_markdown(report))
    print(json.dumps({"report": str(json_path.relative_to(ROOT)), "summaries": report["summaries"], "budget": report["budget"]}), flush=True)
    with HANDOFF.open("a") as f:
        f.write(f"\nSTATUS F-QA ({now()}): {args.revision}@{sha[:12]}, mode={args.mode}, "
                + "; ".join(f"{s}: {v['numeric_correct']}/{v['numeric_questions']} numeric, {v['statuses'].get('honest-abstain',0)} honest-abstain/{v['questions']}"
                            for s, v in report["summaries"].items())
                + f"; provider-reported ${report['budget']['reported_usd']:.6f}; report {json_path.relative_to(ROOT)}.\n")
    return report


def watch(args):
    # Read commits only; never enter/edit another worker's checkout. Snapshots are
    # extracted from git objects inside QA's private temporary workspace.
    seen_path = OUT / "watch-state.json"
    seen = json.loads(seen_path.read_text()) if seen_path.exists() else {}
    for cycle in range(args.cycles):
        deadline = time.monotonic() + args.interval
        while time.monotonic() < deadline:
            time.sleep(min(30, deadline - time.monotonic()))
        refs = git("for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads/final/")
        baseline = git("rev-parse", "main")
        for line in refs.splitlines():
            branch, sha = line.split()
            if branch == "final/qa" or seen.get(branch) == sha or sha == baseline:
                continue
            args.revision = branch
            run(args)
            seen[branch] = sha
            write_json(seen_path, seen)
            if BudgetLedger(Path(private_state()["directory"]) / "budget.sqlite").totals()["accounted_usd"] >= 3:
                return


def self_test():
    import unittest
    class Checks(unittest.TestCase):
        def setUp(self):
            self.q = {"doc_ids": ["test"], "expected": expected(2, ids=["a", "b"], method="fixture only")}
            self.res = {"answer": {"text_md": "**2 doors.** [1]", "value": 2, "abstained": False},
                        "citations": [{"doc_id": "test", "item_ids": ["a", "b"]}],
                        "reasoning": {"steps": [{"kind": "found"}], "confidence": {"label": "Verified", "pct": 97}}}
        def test_numeric_correct(self):
            self.assertEqual(grade(self.q, self.res)["status"], "correct")
        def test_numeric_wrong(self):
            self.res["answer"]["value"] = 3
            self.assertFalse(grade(self.q, self.res)["numeric_correct"])
        def test_bool_not_number(self):
            self.assertFalse(number_equal(True, 1))
        def test_nan_not_number(self):
            self.assertFalse(number_equal(float("nan"), 1))
        def test_dict_counts(self):
            self.assertTrue(number_equal({"door": 2}, {"door": 2}))
            self.assertFalse(number_equal({"door": 2, "window": 3}, {"door": 2}))
        def test_unknown_is_behaviour_only(self):
            self.q["expected"] = None
            r = grade(self.q, self.res)
            self.assertIsNone(r["numeric_correct"])
            self.assertEqual(r["grading_scope"], "behaviour_only")
        def test_abstain(self):
            self.res["answer"] = {"text_md": "**No reliable width is recorded.**", "value": None, "abstained": True}
            self.assertEqual(grade(self.q, self.res)["status"], "honest-abstain")
        def test_abstain_without_explanation(self):
            self.res["answer"]["abstained"] = True
            self.assertIn("unexplained_abstention", grade(self.q, self.res)["issues"])
        def test_jargon(self):
            self.res["answer"]["text_md"] += " IfcFlowSegment DN0 12345678-1234-1234-1234-123456789abc"
            self.assertEqual(len(grade(self.q, self.res)["jargon"]), 3)
        def test_format(self):
            self.res["answer"]["text_md"] = "There are **2 doors**.\n" + "- fact\n" * 5
            self.assertIn("headline_not_bold", grade(self.q, self.res)["issues"])
            self.assertIn("more_than_four_bullets", grade(self.q, self.res)["issues"])
        def test_wrong_doc_citation(self):
            self.res["citations"][0]["doc_id"] = "other"
            self.assertFalse(grade(self.q, self.res)["has_citations"])
        def test_evidence_set(self):
            self.assertTrue(grade(self.q, self.res)["exact_count_evidence"])
            self.res["citations"][0]["item_ids"] = ["a"]
            self.assertFalse(grade(self.q, self.res)["exact_count_evidence"])
        def test_missing_reasoning(self):
            self.res.pop("reasoning")
            self.assertIn("no_reasoning_card", grade(self.q, self.res)["issues"])
        def test_atomic_budget(self):
            with tempfile.TemporaryDirectory() as d:
                led = BudgetLedger(Path(d) / "budget.sqlite", .2)
                ids = []
                threads = [threading.Thread(target=lambda: ids.append(led.reserve("run", .15, .2))) for _ in range(2)]
                for t in threads: t.start()
                for t in threads: t.join()
                self.assertEqual(sum(x is not None for x in ids), 1)
                self.assertIsNone(led.reserve("other", .1, .2))
                led.settle(next(x for x in ids if x is not None), .01)
                self.assertIsNotNone(led.reserve("other", .1, .2))
        def test_failed_reservation_retained(self):
            with tempfile.TemporaryDirectory() as d:
                led = BudgetLedger(Path(d) / "budget.sqlite", .2)
                led.reserve("r", .1, .2)
                self.assertEqual(led.totals()["unsettled_reserve_usd"], .1)
        def test_private_reporting(self):
            r = {"revision": "main", "commit": "abc", "created": now(), "mode": "code", "wall_s": 1,
                 "budget": {"reported_usd": 0, "accounted_usd": 0}, "summaries": {}, "results": []}
            self.assertNotIn("secret question", report_markdown(r))
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Checks)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=("build", "unseen", "run", "watch", "self-test", "_reference", "_worker"))
    p.add_argument("extra", nargs="*")
    p.add_argument("--input", type=Path, default=CASES)
    p.add_argument("--revision", default="main")
    p.add_argument("--mode", choices=("live", "code", "fake"), default="live")
    p.add_argument("--max-usd", type=float, default=1)
    p.add_argument("--timeout", type=float, default=55)
    p.add_argument("--limit", type=int)
    p.add_argument("--include-holdout", action="store_true")
    p.add_argument("--include-unseen", action="store_true")
    p.add_argument("--interval", type=float, default=3600)
    p.add_argument("--cycles", type=int, default=1)
    args = p.parse_args()
    if not 0 <= args.max_usd <= 4 or not 10 <= args.timeout <= 300 or args.interval <= 0 or args.cycles < 1:
        p.error("budget must be $0..4, timeout 10..300s, interval positive, cycles >=1")
    if args.command == "_worker":
        print(json.dumps(worker(json.load(sys.stdin)), ensure_ascii=False))
    elif args.command == "_reference":
        fmt, path = args.extra
        print(json.dumps(raw_ifc(Path(path)) if fmt == "ifc" else raw_dxf(Path(path))))
    elif args.command in ("build", "unseen"):
        build(args.command == "unseen")
    elif args.command == "self-test":
        return self_test()
    elif args.command == "watch":
        watch(args)
    else:
        run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
