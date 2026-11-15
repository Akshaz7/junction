"""Local, reproducible real-sheet evaluation; run with scripts/heavy.sh.

PDFs/images and full parser caches remain in tmp/ and are never committed.
The reserved held-out file is read only with --heldout, after development.
--awais-ref loads the supplied PDF adapters from a fetched git ref in memory;
it neither vendors their code nor modifies pipeline/ or any other worktree.
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
import types
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw

from engine import xdisc

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "results/final/XDISC"
LOCAL = OUT / "tmp"


def load_fork(ref):
    modules = {}
    for name in ("pdf_vector", "pdf_rooms", "pdf_mep"):
        module = types.ModuleType("pipeline." + name)
        module.__package__ = "pipeline"
        module.__version__ = ref
        sys.modules[module.__name__] = module
        source = subprocess.check_output(["git", "show", f"{ref}:pipeline/{name}.py"], cwd=ROOT).decode()
        exec(compile(source, module.__name__, "exec"), module.__dict__)  # noqa: S102 — explicitly selected fetched PDF provider
        modules[name] = module
    return modules


def sheet(path, doc_id, page=1):
    s = xdisc.prepare_pdf(path, page=page, cache_dir=LOCAL / "cache")
    s["doc_id"] = doc_id
    return s


def render(path, page=1):
    with pdfium.PdfDocument(path) as pdf:
        pg = pdf[page-1]
        bitmap = pg.render(scale=1)
        image = bitmap.to_pil().copy()
        bitmap.close(); pg.close()
    return image


def proof_board(base_path, service_path, result):
    base, service = render(base_path), render(service_path)
    records = [r for r in result["rooms"] if r.get("number") and len(r.get("label", "")) > 3][:10]
    board = Image.new("RGB", (1200, len(records)*180), "#eeeeee")
    draw = ImageDraw.Draw(board)
    samples = []
    for i, r in enumerate(records):
        b = r["bbox_px"]
        sb = xdisc._mapped_box(b, result["alignment"], True)
        for j, (img, box) in enumerate([(base, b), (service, sb)]):
            margin = 8 if j == 0 else 16
            crop = img.crop(tuple(round(v + (-margin if k < 2 else margin)) for k, v in enumerate(box)))
            if crop.height > crop.width:
                crop = crop.rotate(270, expand=True)
            crop.thumbnail((570, 140))
            if crop.width < 350 and crop.height < 80:
                factor = min(3, 560/crop.width, 135/crop.height)
                crop = crop.resize((round(crop.width*factor), round(crop.height*factor)))
            board.paste(crop, (j*600+10, i*180+35))
        draw.text((10, i*180+10), f"{i+1}: {r['number']} | {r['label']} | {r['area_m2']} m2 | architect / services", fill="black")
        samples.append({"n": i+1, "room_id": r["item_id"], "number_candidate": r["number"], "name_candidate": r["label"],
                        "printed_area_m2": r["area_m2"], "architect_box_px": b, "services_projected_box_px": sb,
                        "verification": "pending visual inspection of tmp/room-proof-board.png"})
    board.save(LOCAL / "room-proof-board.png")
    return samples


def crossing_board(base_path, service_path, result):
    base, service = render(base_path), render(service_path)
    records = result["crossings"][:10]
    board = Image.new("RGB", (1200, max(1, len(records))*240), "#eeeeee")
    draw = ImageDraw.Draw(board)
    samples = []
    for i, r in enumerate(records):
        for j, (img, ev) in enumerate(zip((base, service), r["evidence"][:2])):
            box = ev["bbox_px"]; x, y = xdisc._centre(box)
            radius = 65 if j == 0 else 130
            crop = img.crop((round(x-radius), round(y-radius), round(x+radius), round(y+radius))).convert("RGB")
            ink = ImageDraw.Draw(crop)
            ink.rectangle((box[0]-x+radius, box[1]-y+radius, box[2]-x+radius, box[3]-y+radius), outline="red", width=2)
            crop = crop.resize((200, 200))
            board.paste(crop, (j*600+10, i*240+30))
        draw.text((10, i*240+10), f"{i+1}: {r['service_id']} / {r['barrier_id']} | 2D candidate, not a certified penetration", fill="black")
        samples.append({"n": i+1, "service_id": r["service_id"], "barrier_id": r["barrier_id"],
                        "evidence": r["evidence"], "verification": "pending visual inspection of tmp/crossing-proof-board.png"})
    board.save(LOCAL / "crossing-proof-board.png")
    return samples


def develop(args):
    start = time.perf_counter()
    a = ROOT / "data/judges/ARK-103-03_floor_plan_3rd_floor.pdf"
    v = ROOT / "data/judges/L30301_ventilation_3rd_floor_block_U.pdf"
    b, s = sheet(a, "architecture"), sheet(v, "ventilation")
    result = xdisc.analyse(b, s)
    report = {"status": "PARTIAL", "model_calls": 0, "cost_usd": 0,
              "judges_text_fallback": result, "visual_samples": proof_board(a, v, result),
              "source_files_committed": False, "notes": ["RMS registration residual measures label agreement, not absolute survey accuracy.",
              "Text associations remain candidates; no room shape or missing air was inferred from proximity."]}
    if args.awais_ref:
        load_fork(args.awais_ref)
        prepared = xdisc.prepare_pair(a, v, doc_ids=["architecture", "ventilation"],
                                     image_sizes=[(b["image"]["w"], b["image"]["h"]), (s["image"]["w"], s["image"]["h"])],
                                     cache_dir=LOCAL / "pair-cache")
        nb, ns, analysed = prepared["base"], prepared["services"], prepared["findings"]
        report["awais"] = {"ref": subprocess.check_output(["git", "rev-parse", args.awais_ref], cwd=ROOT).decode().strip(),
                           "raw_counts": {"walls": len(nb.get("walls", [])), "rooms": len(nb["rooms"]), "room_polygons": sum(bool(r.get("polygon_px")) for r in nb["rooms"]),
                                          "ducts": len(ns["ducts"]), "terminal_candidates": len(ns["terminals"])},
                           "limitations": ns.get("limitations", []), "findings": analysed}
        report["crossing_visual_samples"] = crossing_board(a, v, analysed)
        (LOCAL / "enriched-sheets.json").write_text(json.dumps([nb, ns]))
    origin = ROOT / "data/full/junction-dataset/data/opening_design/Vacation_Rental/Transfer"
    other_base = origin / "20170503 ----- ISSUE FOR PERMIT ------/A102 - BASEMENT & ROOF FLOOR PLANS.pdf"
    other_service = origin / "20170502 - HVAC for review/The Downtowner_HVAC - Sheet - M-002 - HVAC Basement & Roof plan.pdf"
    ob, os = sheet(other_base, "other-architecture"), sheet(other_service, "other-hvac")
    report["other_real_pair"] = {"base": str(other_base.relative_to(ROOT)), "services": str(other_service.relative_to(ROOT)),
                                  "findings": xdisc.analyse(ob, os)}
    (LOCAL / "sheets.json").write_text(json.dumps([b, s]))
    if args.alignment_module:
        spec = importlib.util.spec_from_file_location("engine.sheet_align", args.alignment_module)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        sys.modules["engine.sheet_align"] = module
        report["shared_alignment_check"] = {k: v for k, v in xdisc.align(b, s).items() if k != "anchors"}
        # Use the real rendered pair for the shared raster registration route.
        for path, normal, name in [(other_base, ob, "other-base"), (other_service, os, "other-services")]:
            target = LOCAL / f"{name}.png"
            render(path).save(target)
            normal["image_path"] = str(target)
            normal["image_stamp"] = target.stat().st_mtime_ns
        report["other_real_pair"]["shared_findings"] = xdisc.analyse(ob, os)
    report["elapsed_s"] = time.perf_counter()-start
    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"rooms": len(result["rooms"]), "explicit_flow_labels": len(result["airflow_labels"]),
                      "fallback_alignment": {k: v for k, v in result["alignment"].items() if k != "anchors"},
                      "awais_counts": report.get("awais", {}).get("raw_counts"),
                      "other_pair_alignment": report["other_real_pair"]["findings"]["alignment"].get("status"),
                      "elapsed_s": report["elapsed_s"]}, indent=2), flush=True)


def heldout():
    reserved = json.loads((OUT / "heldout.json").read_text())
    path = ROOT / reserved["end_only_file"]
    sheet_data = sheet(path, "heldout-end-only")
    # Deliberately mismatched pair: must fail safely rather than fabricate a
    # coordination result for an unrelated drawing with another origin.
    judges = json.loads((LOCAL / "sheets.json").read_text())
    result = xdisc.analyse(sheet_data, judges[1])
    report = json.loads((OUT / "report.json").read_text())
    report["heldout_end_only"] = {"file": reserved["end_only_file"], "selection": reserved["selection"],
                                  "words": len(sheet_data["words"]), "findings": result,
                                  "passed": result["alignment"].get("matrix") is None and not result["crossings"] and not result["airflow"]}
    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report["heldout_end_only"].items() if k != "findings"}, indent=2))
    assert report["heldout_end_only"]["passed"]


def chat_checks():
    import jsonschema

    from engine.answer import answer
    sheets = json.loads((LOCAL / "enriched-sheets.json").read_text())
    root = LOCAL / "chat-artifacts"
    for s in sheets:
        folder = root / s["doc_id"]; folder.mkdir(parents=True, exist_ok=True)
        (folder / "xdisc-1.json").write_text(json.dumps(s))
    os.environ["ARTIFACTS_DIR"] = str(root)
    os.environ["MODELS_FAKE"] = "1"
    os.environ["EXPLAIN"] = "0"
    schema = json.loads((ROOT / "server/schemas/answer.schema.json").read_text())
    questions = ["Show the room table", "Airflow per room", "Which rooms have no supply air?",
                 "Where do ducts cross walls?", "Ducts in rooms with ceiling height below 2.5 m"]
    results = []
    for q in questions:
        r = answer(q, [s["doc_id"] for s in sheets])
        jsonschema.validate(r, schema)
        assert r.get("xdisc") is not None and r["reasoning"]["steps"]
        assert r["cost"]["usd_total"] == 0
        results.append({"question": q, "answer": r["answer"], "citations": len(r["citations"]),
                        "docs_with_boxes": sorted({b["doc_id"] for b in r["evidence"]["boxes"]}),
                        "reasoning": r["reasoning"], "schema_valid": True})
    report = json.loads((OUT / "report.json").read_text())
    report["real_chat_checks"] = results
    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--awais-ref")
    parser.add_argument("--alignment-module")
    parser.add_argument("--heldout", action="store_true")
    parser.add_argument("--chat", action="store_true")
    args = parser.parse_args()
    LOCAL.mkdir(parents=True, exist_ok=True)
    heldout() if args.heldout else chat_checks() if args.chat else develop(args)
