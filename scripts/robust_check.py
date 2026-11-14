#!/usr/bin/env python3
"""LONG: upload/ingest/scene/answer matrix on real files and documented transforms.

Run with the project Python. Heavy work automatically uses scripts/heavy.sh.
Default: no live inference; raster rows prove preprocessing only. --live-raster
enables real reading on one raster (all other rows still run without models).
--quick omits the reserved, unseen file; the complete run tests it LAST.
No shared data/artifacts are written. PostgreSQL and live events are replaced by
no-op adapters; HTTP upload, subprocess ingestion, geometry and answers are real.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import io
import json
import os
import platform
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def stamp():
    print(datetime.now().astimezone().isoformat(timespec="seconds"), flush=True)


def _rss():
    divisor = 1024 ** 2 if platform.system() == "Darwin" else 1024
    return round(max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                     resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss) / divisor, 1)


def _worker(case, work: Path, timeout: float):
    """One isolated OS process per case: RSS is not inherited from earlier cases."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from server import files_routes as routes

    class NoDatabase:
        async def execute(self, *args):
            return "OK"

    async def pool():
        return NoDatabase()

    async def no_io(*args, **kwargs):
        return 0

    routes.db.get_pool = pool
    routes.artifact_store.save_doc = no_io
    routes.publish = no_io
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes._restore] = lambda: None
    t0 = time.perf_counter()
    result = dict(case)
    result["bytes"] = Path(case["path"]).stat().st_size
    with TestClient(app) as client:
        with open(case["path"], "rb") as source:
            response = client.post("/api/upload", files={"file": (case["filename"], source)})
        result["upload_http"] = response.status_code
        result["upload_seconds"] = round(time.perf_counter() - t0, 3)
        if response.status_code != 200:
            result["user_message"] = response.json().get("detail")
            result["ok"] = response.status_code == case.get("expected_http", 200)
        else:
            doc_id = response.json()["doc_id"]
            while time.perf_counter() - t0 < timeout:
                state = client.get(f"/api/docs/{doc_id}/ingest").json()
                if state["status"] != "running":
                    break
                time.sleep(0.1)
            else:
                raise TimeoutError("The matrix's per-file deadline was reached.")

            async def finish():
                tasks = [t for t in asyncio.all_tasks() if getattr(t.get_coro(), "__name__", "") == "_ingest"]
                if tasks:
                    await asyncio.gather(*tasks)
            client.portal.call(finish)
            result["ingest"] = state
            result["user_message"] = state.get("detail")
            art = Path(os.environ["ARTIFACTS_DIR"])
            d = art / doc_id
            result["preview"] = (d / "page-1.png").is_file()
            result["scene"] = (d / "scene.glb").is_file() and (d / "scene.json").is_file()
            if result["scene"]:
                scene = json.loads((d / "scene.json").read_text())
                result["scene_items"] = len(scene["items"])
                result["origin_offset_m"] = scene["origin_offset_m"]
            if result["preview"]:
                from PIL import Image
                with Image.open(d / "page-1.png") as im:
                    result["preview_size"] = list(im.size)
            from engine.solvers.data import load_doc
            document = load_doc(doc_id, art)
            if document is not None:
                kinds = Counter(i.kind for i in document.items)
                result["counts"] = dict(kinds)
                # Ask a useful question about a kind actually represented in the
                # source index; no expected count is encoded in the script.
                kind = next((k for k in ("door", "window", "wall", "room", "stairs", "column", "slab", "pipe") if kinds[k]), None)
                if kind:
                    from engine.answer import answer
                    query = f"How many {kind if kind == 'stairs' else kind + 's'} are there?"
                    a = answer(query, [doc_id])
                    result["first_answer"] = {"question": query, "text": a["answer"]["text_md"],
                                              "value": a["answer"].get("value"), "abstained": a["answer"].get("abstained"),
                                              "citations": len(a.get("citations") or []),
                                              "boxes": len((a.get("evidence") or {}).get("boxes") or []),
                                              "reasoning": a.get("reasoning"), "cost_usd": a["cost"]["usd_total"]}
                # Only dimensions in the source/index are recorded. These let
                # the parent compare metric/imperial/far-coordinate variants.
                result["quantities"] = {i.item_id: i.q for i in document.items if i.q}
                result["bounds"] = {i.item_id: i.bbox_m for i in document.items if i.bbox_m}
            if case.get("coverage") == "preprocessing_only":
                result["ok"] = result["preview"] and state["status"] in {"ready", "partial"}
            elif case.get("expected_failure"):
                result["ok"] = state["status"] == "failed" and bool(state.get("reason")) and bool(state.get("stages"))
            else:
                first = result.get("first_answer") or {}
                result["ok"] = (state["status"] in {"ready", "partial"} and result["scene"] and result["preview"]
                                and bool(first.get("citations")) and bool(first.get("reasoning"))
                                and not first.get("abstained"))
    result["seconds"] = round(time.perf_counter() - t0, 3)
    result["peak_process_rss_mib"] = _rss()
    (work / "result.json").write_text(json.dumps(result))


def _schema4x3(source: Path, target: Path):
    import ifcopenshell
    from ifcopenshell.util.schema import Migrator
    f = ifcopenshell.open(str(source))
    # IFC4 deprecated this style wrapper; IFC4X3 requires the style itself.
    for a in f.by_type("IfcPresentationStyleAssignment"):
        for inv in f.get_inverse(a):
            if inv.is_a("IfcStyledItem"):
                inv.Styles = tuple(s for x in inv.Styles for s in (x.Styles if x.is_a("IfcPresentationStyleAssignment") else [x]))
        f.remove(a)
    new = ifcopenshell.file(schema="IFC4X3")
    migrator = Migrator()
    with contextlib.redirect_stdout(io.StringIO()):
        for entity in f:
            migrator.migrate(entity, new)
    new.write(str(target))


def _prepare(root: Path, work: Path, reserve: dict, live: bool):
    """Transforms retain source content; generated fixtures are never called real."""
    import ezdxf
    import ifcopenshell
    import numpy as np
    from ezdxf import transform
    from ezdxf.addons.r12export import convert as r12
    from ezdxf.math import Matrix44
    from ifcopenshell.util.unit import calculate_unit_scale, convert_file_length_units
    from PIL import Image

    candidates = sorted(root.rglob("*"))
    raster = next(p for p in candidates if p.suffix.lower() == ".png")
    dxfs = [p for p in candidates if p.suffix.lower() == ".dxf"]
    # A normal-sized DXF with declared units and geometry, selected by metadata.
    dxf = min((p for p in dxfs if p.stat().st_size > 100_000), key=lambda p: p.stat().st_size)
    ifcs = [p for p in candidates if p.suffix.lower() == ".ifc" and p.resolve() != (REPO / reserve["path"]).resolve()]
    ifc = max((p for p in ifcs if p.stat().st_size < 2_000_000), key=lambda p: p.stat().st_size)
    ifc4 = None
    for p in sorted(ifcs, key=lambda p: p.stat().st_size):
        if p.stat().st_size < 100_000:
            continue
        with p.open("rb") as src:
            head = src.read(65536)
        if b"'IFC4'" in head:
            ifc4 = p
            break
    cases = []

    def add(name, path, origin, transform_name="original", **extra):
        cases.append({"case": name, "path": str(path), "filename": path.name,
                      "source": str(origin), "transform": transform_name, **extra})

    # Unit tests cover geometry boundaries. Matrix rows use actual drawing pixels.
    with Image.open(raster) as source:
        im = source.convert("RGB")
    for name, mode, extension in [("png_original", "RGB", "png"), ("jpeg_recompressed", "RGB", "jpeg"),
                                   ("greyscale", "L", "png"), ("alpha", "RGBA", "png")]:
        p = work / f"{name}.{extension}"
        im.convert(mode).save(p)
        coverage = "full" if live and name == "png_original" else "preprocessing_only"
        add(name, p, raster, "re-encoded source pixels as " + mode, coverage=coverage, live=live and name == "png_original")
    for name, changed in [("rotated", im.rotate(90, expand=True)), ("skewed", im.rotate(2, expand=True, fillcolor="white")),
                           ("tiny", im.resize((32, 32))),
                           ("huge_10k", im.resize((10000, max(1, int(im.height * 10000 / im.width)))) )]:
        p = work / f"{name}.png"
        changed.save(p)
        changed.close()
        add(name, p, raster, name + " source pixels", coverage="preprocessing_only")
    exif = Image.Exif()
    exif[274] = 6
    p = work / "exif.jpg"
    im.save(p, exif=exif)
    add("exif_rotation", p, raster, "source JPEG with EXIF orientation 6", coverage="preprocessing_only")
    p = work / "16bit.png"
    Image.fromarray(np.asarray(im.convert("L"), dtype=np.uint16) * 257).save(p)
    add("16bit_png", p, raster, "8-bit source greyscale expanded losslessly to 16-bit", coverage="preprocessing_only")
    p = work / "palette.png"
    im.quantize().save(p, transparency=0)
    add("palette_alpha", p, raster, "source quantised with transparent palette index 0", coverage="preprocessing_only")
    im.close()
    add("duplicate_1", raster, raster, coverage="preprocessing_only")
    add("duplicate_2", raster, raster, coverage="preprocessing_only")
    add("dxf_original", dxf, dxf)
    for version in ("R12", "R2018"):
        f = ezdxf.readfile(dxf)
        f = r12(f) if version == "R12" else f
        if version != "R12":
            f.dxfversion = "AC1032"
        p = work / (version + ".dxf")
        f.saveas(p)
        add("dxf_" + version.lower(), p, dxf, "converted source to " + version)
    f = ezdxf.readfile(dxf)
    ms = f.modelspace()
    paper = f.layout()
    for entity in list(ms):
        ms.move_to_layout(entity, paper)
    p = work / "paper.dxf"
    f.saveas(p)
    add("dxf_paperspace", p, dxf, "source entities moved to paper layout", coverage="preprocessing_only")
    f = ezdxf.readfile(dxf)
    from pipeline.dxf_input import metres_per_unit
    source_scale = metres_per_unit(f)
    if source_scale:
        transform.inplace(f.modelspace(), Matrix44.scale(source_scale / 0.3048))
        f.units = 2
        p = work / "imperial.dxf"
        f.saveas(p)
        add("dxf_feet", p, dxf, "source coordinates and declared units converted to feet")
    f = ezdxf.readfile(dxf)
    f.units = 0
    p = work / "unitless.dxf"
    f.saveas(p)
    add("dxf_unitless", p, dxf, "removed declared units", coverage="preprocessing_only")
    from ezdxf import xref
    f = ezdxf.readfile(dxf)
    xref.attach(f, block_name="MISSING_REFERENCE", filename="missing-reference.dxf", insert=(0, 0))
    p = work / "missing_xref.dxf"
    f.saveas(p)
    add("dxf_missing_xref", p, dxf, "added unresolved external reference; existing content retained")

    add("ifc_original", ifc, ifc)
    f = ifcopenshell.open(str(ifc))
    for e in list(f.by_type("IfcBuildingStorey")) + list(f.by_type("IfcSpace")):
        f.remove(e)
    p = work / "no_levels_or_spaces.ifc"
    f.write(str(p))
    add("ifc_no_storeys_or_spaces", p, ifc, "removed source storeys and spaces; other elements retained")
    f = ifcopenshell.open(str(ifc))
    scale = calculate_unit_scale(f)
    for placement in f.by_type("IfcLocalPlacement"):
        if placement.PlacementRelTo is None:
            loc = placement.RelativePlacement.Location
            xyz = list(loc.Coordinates)
            xyz[0] += 5_000_000 / scale
            xyz[1] += 6_000_000 / scale
            loc.Coordinates = xyz
    p = work / "survey_coordinates.ifc"
    f.write(str(p))
    add("ifc_far_origin", p, ifc, "translated source root placements by 5000 km / 6000 km (geometry unchanged)")
    f = convert_file_length_units(ifcopenshell.open(str(ifc)), "FOOT")
    p = work / "feet.ifc"
    f.write(str(p))
    add("ifc_feet", p, ifc, "source geometry and units converted to feet")
    if ifc4:
        add("ifc4_other_author", ifc4, ifc4)
        p = work / "schema4x3.ifc"
        _schema4x3(ifc4, p)
        add("ifc4x3_migrated", p, ifc4, "IFC4 source migrated to IFC4X3; deprecated style wrappers unwrapped (not a native IFC4X3 sample)")

    # Schedules contain ONLY actual source element data; no invented measurements.
    f = ifcopenshell.open(str(ifc))
    rows = [[e.GlobalId, e.Name or "", e.is_a()] for e in f.by_type("IfcElement")]
    p = work / "schedule.csv"
    with p.open("w", newline="") as dest:
        writer = csv.writer(dest)
        writer.writerow(["Item", "Name", "Class"])
        writer.writerows(rows)
    add("csv_schedule", p, ifc, "source element labels exported as CSV", expected_http=415)
    text = work / "schedule.txt"
    shutil.copyfile(p, text)
    add("text_schedule", text, ifc, "source CSV as plain text", expected_http=415)
    xlsx = work / "schedule.xlsx"
    from xml.sax.saxutils import escape
    with zipfile.ZipFile(xlsx, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Schedule" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        cells = "".join('<row>' + "".join(f'<c t="inlineStr"><is><t>{escape(str(c))}</t></is></c>' for c in row) + '</row>' for row in [["Item", "Name", "Class"], *rows])
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + cells + '</sheetData></worksheet>')
    add("xlsx_schedule", xlsx, ifc, "source labels exported as XLSX", expected_http=415)
    dwg = next(p for p in candidates if p.suffix.lower() == ".dwg")
    add("dwg", dwg, dwg, expected_http=415)
    p = work / "drawings.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.write(raster, raster.name)
        z.write(dxf, dxf.name)
    add("zip", p, raster, "archive of the real raster and DXF", expected_http=415)
    add("wrong_extension", raster, raster, "PNG source named .jpg", filename="wrong.jpg", expected_http=422)
    for name, src in [("corrupt_png", raster), ("corrupt_dxf", dxf), ("corrupt_ifc", ifc)]:
        p = work / (name + src.suffix)
        with src.open("rb") as source:
            p.write_bytes(source.read(128))
        add(name, p, src, "source truncated to first 128 bytes", expected_failure=True)
    p = work / "empty.png"
    p.touch()
    add("empty", p, raster, "source truncated to zero bytes", expected_http=400)
    p = work / "over_200mb.ifc"
    with ifc.open("rb") as source, p.open("wb") as dest:
        shutil.copyfileobj(source, dest)
        dest.seek(210 * 1024 * 1024)
        dest.write(b"\n")
    add("ifc_over_200mb", p, ifc, "sparse byte-size probe padded from real source; parser not exercised", expected_http=413)
    p = work / "over_limit.dxf"
    with dxf.open("rb") as source, p.open("wb") as dest:
        shutil.copyfileobj(source, dest)
        dest.seek(101 * 1024 * 1024)
        dest.write(b"\n")
    add("dxf_over_100mb", p, dxf, "sparse byte-size probe padded from real source; parser not exercised", expected_http=413)
    return cases


def _compare(results):
    """Check transformations against observations, never a hard-coded count."""
    by_case = {r["case"]: r for r in results}
    checks = []
    base = by_case.get("ifc_original") or {}
    for name in ("ifc_feet", "ifc_far_origin"):
        other = by_case.get(name)
        if not other or not base.get("counts"):
            continue
        same = base.get("counts") == other.get("counts")
        max_error = 0.0
        for item_id, bbox in base.get("bounds", {}).items():
            b = other.get("bounds", {}).get(item_id)
            if b:
                max_error = max(max_error, *(abs((bbox[1][k] - bbox[0][k]) - (b[1][k] - b[0][k])) for k in range(3)))
        checks.append({"case": name, "same_counts": same, "max_bbox_extent_error_m": round(max_error, 6),
                       "ok": same and max_error < 0.001})
    # Avoid bloating the committed matrix with every source quantity and bound.
    for r in results:
        r.pop("quantities", None)
        r.pop("bounds", None)
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=REPO / "data/junction-dataset-preview")
    parser.add_argument("--output", type=Path, default=REPO / "results/final/ROBUST/matrix.json")
    parser.add_argument("--reserve", type=Path, default=REPO / "results/final/ROBUST/reserve.json")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--live-raster", action="store_true")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--slot-held", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--case", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--work", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    stamp()
    if args.case:
        case = json.loads(args.case.read_text())
        _worker(case, args.work, args.timeout)
        return 0
    if not args.slot_held:
        return subprocess.call([str(REPO / "scripts/heavy.sh"), sys.executable, __file__, *sys.argv[1:], "--slot-held"],
                               env={**os.environ, "HEAVY_SLOT_HELD": "1", "INGEST_MANAGED_JOB": "1"})
    reserve = json.loads(args.reserve.read_text())
    with tempfile.TemporaryDirectory(prefix="f-robust-") as tmp:
        work = Path(tmp)
        print("Preparing real-source transforms in", work, flush=True)
        cases = _prepare(args.dataset, work, reserve, args.live_raster)
        if not args.quick:
            cases.append({"case": "reserved_unseen_ifc", "path": str(REPO / reserve["path"]),
                          "filename": Path(reserve["path"]).name, "source": reserve["path"],
                          "transform": "original; randomly reserved before implementation; tested last"})
        if args.only:
            cases = [c for c in cases if c["case"] in args.only]
        results = []
        for case in cases:
            stamp()
            print("Checking", case["case"], flush=True)
            d = work / ("run_" + case["case"])
            d.mkdir()
            (d / "artifacts").mkdir()
            (d / "case.json").write_text(json.dumps(case))
            env = {**os.environ, "ARTIFACTS_DIR": str(d / "artifacts"), "RESULTS_DIR": str(d / "results"),
                   "MODELS_CACHE_DIR": str(work / "cache"), "MODELS_COSTS_LOG": str(work / "costs.jsonl"),
                   "MODELS_FAKE": "0" if case.get("live") else "1", "INGEST_MODE": "vlm",
                   "IFC_CONVERT_PY": "1", "INGEST_IFC_MAX_MB": "15", "ENGINE_IMPL": "real", "INGEST": "1",
                   "EXPLAIN": "0", "RECOUNT": "0", "FORCE_ANSWER": "0", "READER": "0",
                   "ANSWER_TIMEOUT_S": "30", "INGEST_MANAGED_JOB": "1", "HEAVY_SLOT_HELD": "1"}
            t0 = time.perf_counter()
            log = d / "worker.log"
            with log.open("w") as stream:
                proc = subprocess.Popen([sys.executable, __file__, "--case", str(d / "case.json"), "--work", str(d),
                                         "--timeout", str(args.timeout)], env=env, cwd=REPO,
                                        stdout=stream, stderr=stream, start_new_session=True)
                try:
                    proc.wait(timeout=args.timeout + 20)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
            if (d / "result.json").is_file():
                result = json.loads((d / "result.json").read_text())
            else:
                result = dict(case, ok=False, error=log.read_text()[-1600:], seconds=round(time.perf_counter() - t0, 3))
            results.append(result)
            print(case["case"], "PASS" if result["ok"] else "FAIL", result.get("user_message", ""), flush=True)
        comparisons = _compare(results)
        costs = [json.loads(line) for line in (work / "costs.jsonl").read_text().splitlines()] if (work / "costs.jsonl").exists() else []
        total_cost = round(sum(c.get("cost_usd", 0) for c in costs if c.get("provider") != "fake"), 6)
        report = {"row": "F-ROBUST", "time": datetime.now(timezone.utc).isoformat(), "long": True,
                  "reserved": reserve, "reserved_tested_last": bool(results and results[-1]["case"] == "reserved_unseen_ifc"),
                  "environment": {"platform": platform.platform(), "python": platform.python_version(),
                                  "ingest": "deploy VLM mode, Python IFC converter", "database": "no-op adapter; persistence NOT tested",
                                  "memory": "Maximum single-process high-water RSS across HTTP worker and its completed ingest/converter children, not simultaneous total RSS",
                                  "live_cost_usd": total_cost},
                  "limits": ["PDF internals excluded (Awais)", "DWG converter unavailable; export to DXF or IFC",
                             "Standalone CSV/XLSX/TXT and ZIP unsupported; actionable 415 responses",
                             "Upload maximum 100 MiB; >200 MiB probe tests clear rejection, not conversion",
                             "IFC4X3 test is a migrated real file, not a native authoring export",
                             "Raster transforms except explicitly live rows test preprocessing only; no model accuracy claim",
                             "DXF simplified line renderer omits text/hatches; arbitrary-layer semantics require the live reader"],
                  "passed": sum(bool(r["ok"]) for r in results), "total": len(results),
                  "transformation_checks": comparisons, "cases": results}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"passed": report["passed"], "total": len(results), "live_cost_usd": total_cost,
                          "output": str(args.output)}), flush=True)
        return 0 if all(r["ok"] for r in results) and all(c["ok"] for c in comparisons) else 1


if __name__ == "__main__":
    raise SystemExit(main())
