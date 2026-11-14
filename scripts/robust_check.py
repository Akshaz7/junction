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
    result["http_start_peak_rss_mib"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss /
                                               (1024 ** 2 if platform.system() == "Darwin" else 1024), 1)
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
            result["post_ingest_peak_process_rss_mib"] = _rss()
            result["ingest"] = state
            result["user_message"] = state.get("detail")
            art = Path(os.environ["ARTIFACTS_DIR"])
            d = art / doc_id
            result["preview"] = (d / "page-1.png").is_file()
            result["scene"] = (d / "scene.glb").is_file() and (d / "scene.json").is_file()
            if result["scene"]:
                from pygltflib import GLTF2
                scene = json.loads((d / "scene.json").read_text())
                result["scene_items"] = len(scene["items"])
                result["origin_offset_m"] = scene["origin_offset_m"]
                nodes = {node.name for node in GLTF2().load(str(d / "scene.glb")).nodes}
                result["scene_valid"] = bool(scene["items"]) and all(item["node"] in nodes for item in scene["items"].values())
            if (d / "elements.json").is_file():
                result["index_schema"] = json.loads((d / "elements.json").read_text()).get("schema")
            if result["preview"]:
                from PIL import Image
                with Image.open(d / "page-1.png") as im:
                    result["preview_size"] = list(im.size)
            from engine.solvers.data import load_doc
            document = load_doc(doc_id, art)
            result["post_load_peak_process_rss_mib"] = _rss()
            if document is not None:
                kinds = Counter(i.kind for i in document.items)
                result["counts"] = dict(kinds)
                # Ask a useful question about a kind actually represented in the
                # source index; no expected count is encoded in the script.
                kind = next((k for k in ("door", "window", "wall", "room", "stairs", "column", "slab", "pipe", "beam", "roof", "railing", "covering", "furniture") if kinds[k]), None)
                if kind is None and document.mode == "ifc":
                    kind = "door"  # missing classification must give an honest unknown, not a zero
                if kind:
                    from engine.answer import answer
                    noun = "pieces of furniture" if kind == "furniture" else kind if kind == "stairs" else kind + "s"
                    query = f"How many {noun} are there?"
                    a = answer(query, [doc_id])
                    result["first_answer"] = {"question": query, "text": a["answer"]["text_md"],
                                              "value": a["answer"].get("value"), "abstained": a["answer"].get("abstained"),
                                              "unclassified": any(s.get("step") == "unclassified" for s in a.get("trace", [])),
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
                                and result.get("scene_valid") and bool(first.get("citations")) and bool(first.get("reasoning"))
                                and (not first.get("abstained") or (first.get("unclassified") and first.get("value") is None)))
    result["seconds"] = round(time.perf_counter() - t0, 3)
    result["peak_process_rss_mib"] = _rss()
    divisor = 1024 ** 2 if platform.system() == "Darwin" else 1024
    result["peak_http_process_rss_mib"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / divisor, 1)
    result["peak_ingest_process_rss_mib"] = max(
        (s.get("peak_process_rss_mib", 0) for s in result.get("ingest", {}).get("stages", [])), default=None)
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


def _translate_roots(f, dx_m, dy_m):
    """Translate placements without mutating points shared by local geometry."""
    from ifcopenshell.util.element import copy
    from ifcopenshell.util.unit import calculate_unit_scale
    scale = calculate_unit_scale(f)
    for placement in f.by_type("IfcLocalPlacement"):
        if placement.PlacementRelTo is None:
            relative = copy(f, placement.RelativePlacement)
            xyz = list(relative.Location.Coordinates)
            xyz[0] += dx_m / scale
            xyz[1] += dy_m / scale
            relative.Location = f.createIfcCartesianPoint(tuple(xyz))
            placement.RelativePlacement = relative


def _prepare(root: Path, work: Path, reserve: dict, live: bool):
    """Transforms retain source content; generated fixtures are never called real."""
    import ezdxf
    import ifcopenshell
    import numpy as np
    from ezdxf import transform
    from ezdxf.addons.r12export import convert as r12
    from ezdxf.math import Matrix44
    from ifcopenshell.util.unit import convert_file_length_units
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
                           ("huge_10k", im.convert("L").resize((max(1, round(im.width * 10000 / max(im.size))),
                                                                max(1, round(im.height * 10000 / max(im.size))))))]:
        p = work / f"{name}.png"
        changed.save(p)
        changed.close()
        add(name, p, raster, name + " source pixels" + (" in greyscale" if name == "huge_10k" else ""), coverage="preprocessing_only")
    huge = im.resize((max(1, round(im.width * 10000 / max(im.size))), max(1, round(im.height * 10000 / max(im.size)))))
    p = work / "huge_colour.png"
    huge.save(p)
    from pipeline.raster_input import MAX_DECODE_BYTES
    limited = huge.width * huge.height * 3 > MAX_DECODE_BYTES
    add("huge_colour_decode_limit", p, raster, "source RGB pixels enlarged to 10k longest side; decode-memory guard",
        expected_failure=limited, coverage="memory_limit" if limited else "preprocessing_only")
    p = work / "huge.jpeg"
    huge.save(p)
    huge.close()
    add("huge_jpeg_10k", p, raster, "source enlarged to 10k longest side and JPEG compressed", coverage="preprocessing_only")
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
    _translate_roots(f, 5_000_000, 6_000_000)
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
        same_bounds = set(base.get("bounds", {})) == set(other.get("bounds", {}))
        max_error = 0.0
        for item_id, bbox in base.get("bounds", {}).items():
            b = other.get("bounds", {}).get(item_id)
            if b:
                max_error = max(max_error, *(abs((bbox[1][k] - bbox[0][k]) - (b[1][k] - b[0][k])) for k in range(3)))
        quantity_errors = []
        for item_id, quantities in base.get("quantities", {}).items():
            for key, value in quantities.items():
                transformed = other.get("quantities", {}).get(item_id, {}).get(key)
                quantity_errors.append(abs(value - transformed) if transformed is not None else float("inf"))
        quantity_error = max(quantity_errors, default=0.0)
        checks.append({"case": name, "same_counts": same, "max_bbox_extent_error_m": round(max_error, 6),
                       "max_quantity_error_si": round(quantity_error, 6) if quantity_error != float("inf") else None,
                       "same_bbox_items": same_bounds,
                       "ok": same and same_bounds and max_error < 0.001 and quantity_error < 0.001})
    dxf = by_case.get("dxf_original") or {}
    for name in ("dxf_r12", "dxf_r2018", "dxf_feet"):
        other = by_case.get(name)
        if other and dxf.get("counts"):
            same = dxf["counts"] == other.get("counts")
            checks.append({"case": name, "same_counts": same, "ok": same})
    image = by_case.get("png_original") or {}
    exif = by_case.get("exif_rotation") or {}
    if image.get("preview_size") and exif.get("preview_size"):
        rotated = image["preview_size"][::-1] == exif["preview_size"]
        checks.append({"case": "exif_rotation", "display_size_rotated": rotated, "ok": rotated})
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
                                  "memory": "Maximum single-process high-water RSS across the in-process TestClient/API worker and completed ingest/converter children, not simultaneous total RSS. Includes client multipart encoding; oversized-probe RSS is not production API RSS.",
                                  "live_cost_usd": total_cost},
                  "limits": ["PDF internals excluded (Awais)", "DWG converter unavailable; export to DXF or IFC",
                             "Standalone CSV/XLSX/TXT and ZIP unsupported; actionable 415 responses",
                             "Upload maximum 100 MiB; >200 MiB probe tests clear rejection, not conversion",
                             "Raster decode budget defaults to 128 MiB of source pixels (RASTER_MAX_DECODE_MB); larger colour PNGs fail clearly, JPEG draft decoding stays bounded",
                             "IFC4X3 test is a migrated real file, not a native authoring export",
                             "Scene files and referenced nodes validated; browser rendering not exercised",
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
