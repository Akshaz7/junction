"""Read-only, reproducible two-sheet validation; source crops stay local.

Run with PYTHONPATH=. scripts/heavy.sh <python> this.py --architect PDF
--services PDF --output results/final/KG-MEP/round2.json --local-dir /tmp/...
No reader, ingest, shared artifact or source document is modified.
"""
from __future__ import annotations

import argparse
import json
import math
import tempfile
import time
from collections import Counter
from pathlib import Path

import numpy as np

from engine.kg.build import build_uncached
from engine.kg.mep import room_services
from pipeline import pdf_mep as M, pdf_planmap as P, pdf_rooms as R, pdf_vector as V


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def planmap(path, did):
    start = time.monotonic()
    page = V.load_page(path)
    walls = V.walls(page)
    rooms = R.rooms(page, walls)
    scale = R.scale(page, rooms)
    if not scale.get("m_per_pt"):
        raise ValueError("No recorded scale for room extraction")
    pm = P.build(did, 1, round(page["W_pt"]), round(page["H_pt"]), page, walls, rooms, [], scale)
    print(json.dumps({"doc": did, "rooms": sum(i["kind"] == "room" for i in pm["items"]),
                      "seconds": time.monotonic() - start}), flush=True)
    return pm


def anchor_checks(src, dst, T, scale):
    """Leave-one-out errors on the alignment's shared unique text anchors."""
    def unique(page):
        count = Counter(M._norm_text(w["text"]) for w in page["words"])
        return {M._norm_text(w["text"]): [(w["bbox"][i] + w["bbox"][i+2])/2 for i in (0, 1)]
                for w in page["words"] if count[M._norm_text(w["text"])] == 1
                and len(M._norm_text(w["text"])) >= 2}
    a, b = unique(src), unique(dst)
    keys = sorted(a.keys() & b.keys())
    A, B = np.asarray([a[k] for k in keys]), np.asarray([b[k] for k in keys])
    tol = .002 * math.hypot(dst["W_pt"], dst["H_pt"])
    keep = np.linalg.norm(M.apply_T(T, A)-B, axis=1) < tol
    keys = [k for k, yes in zip(keys, keep) if yes]
    A, B = A[keep], B[keep]
    checks = []
    for i, key in enumerate(keys):
        s, rotation, translation = M._fit_similarity(np.delete(A, i, 0), np.delete(B, i, 0))
        error = float(np.linalg.norm(s * rotation @ A[i] + translation - B[i]) * scale)
        checks.append({"text": key, "residual_m": error})
    return {"method": "leave one shared-text inlier out of the similarity refit",
            "scope": "Registration consistency only; not service-detection or room-boundary accuracy. Inlier selection uses the full fit.",
            "count": len(checks), "rms_m": math.sqrt(sum(c["residual_m"]**2 for c in checks)/len(checks)),
            "max_m": max(c["residual_m"] for c in checks), "checks": checks}


def crop(pdf, bbox, output, polygons=(), line=None, point=None):
    import pypdfium2 as pdfium
    from PIL import ImageDraw
    with pdfium.PdfDocument(pdf) as document:
        page = document[0]
        x0, y0, x1, y1 = bbox
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(page.get_width(), x1), min(page.get_height(), y1)
        image = page.render(scale=2, crop=(x0, page.get_height()-y1, page.get_width()-x1, y0)).to_pil()
        draw = ImageDraw.Draw(image)
        xy = lambda p: ((p[0]-x0)*2, (p[1]-y0)*2)
        for poly in polygons:
            draw.line([xy(p) for p in poly] + [xy(poly[0])], fill="red", width=3)
        if line:
            draw.line([xy(p) for p in line], fill="blue", width=3)
        if point:
            x, y = xy(point)
            draw.ellipse((x-8,y-8,x+8,y+8), outline="blue", width=3)
        image.save(output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--architect", type=Path, required=True)
    parser.add_argument("--services", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--local-dir", type=Path, required=True)
    args = parser.parse_args()
    args.local_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    arch, vent = M.load(args.architect), M.load(args.services)
    apm, vpm = planmap(args.architect, "architect"), planmap(args.services, "services")
    scale = apm["scale"]["m_per_px"] * apm["image"]["w"] / arch["W_pt"]
    T = M.align(vent, arch)
    if T is None:
        raise ValueError("No supported sheet alignment")
    split = M.split_mep(vent, arch, m_per_pt=scale)
    ducts = M.ducts(vent, split["mep"], split["m_per_pt"])
    terms = M.terminals(vent, split["mep"], split["m_per_pt"])
    extraction_seconds = time.monotonic() - start
    docs = [{"doc_id": "architect", "title": args.architect.stem, "role": "architectural", "files": {"pdf": str(args.architect.resolve())}},
            {"doc_id": "services", "title": args.services.stem, "role": "ventilation", "files": {"pdf": str(args.services.resolve())}}]
    with tempfile.TemporaryDirectory(prefix="kg-mep-round2-") as tmp:
        root = Path(tmp)
        for doc, pm in zip(docs, (apm, vpm)):
            folder = root / doc["doc_id"]
            folder.mkdir()
            save(folder / "doc.json", {**doc, "kind": "pdf", "formats": ["pdf"], "pages": 1})
            save(folder / "planmap-1.json", pm)
        build_start = time.monotonic()
        graph = build_uncached({"id": "judge-pair-read-only", "docs": docs}, root)
        build_seconds = time.monotonic() - build_start
    save(args.local_dir / "graph.json", graph)
    save(args.local_dir / "planmaps.json", [apm, vpm])
    save(args.local_dir / "extracted.json", {"T": T, "ducts": ducts, "terminals": terms})
    nodes = {n["id"]: n for n in graph["nodes"]}
    service_edges = [e for e in graph["edges"] if e["kind"] == "in_room" and nodes[e["from"]]["kind"] in {"duct", "terminal"}]
    room_rows = []
    for node in graph["nodes"]:
        if node["kind"] == "room" and (node.get("source") or {}).get("doc_id") == "architect":
            row = room_services(graph, node["id"])
            room_rows.append({"id": node["id"], "label": node["label"], "source": node["source"],
                              "count_by_kind": row["count_by_kind"], "length_m_by_kind": row["length_m_by_kind"]})
    # Include unlinked candidates too; never repeat a favourable link to reach ten.
    terminal_links = [e for e in service_edges if nodes[e["from"]]["kind"] == "terminal"]
    duct_links = [e for e in service_edges if nodes[e["from"]]["kind"] == "duct"]
    chosen = [("terminal", i) for i in range(min(3,len(terms)))]
    if ducts:
        chosen += [("duct", int(i)) for i in np.linspace(0,len(ducts)-1,min(len(ducts),10-len(chosen)),dtype=int)]
    checks = []
    pmitems = {i["item_id"]: i for i in apm["items"]}
    for index, (kind, seq) in enumerate(chosen, 1):
        service = next((n for n in nodes.values() if n["kind"] == kind and
                       (n.get("source") or {}).get("item_id") == f"mep-1-{kind}-{seq+1}"), None)
        edges = [e for e in service_edges if service and e["from"] == service["id"]]
        room = nodes[edges[0]["to"]] if edges else None
        raw = (ducts if kind == "duct" else terms)[seq]
        source_points = [raw["start_pt"],raw["end_pt"]] if kind == "duct" else [raw["center_pt"]]
        points = M.apply_T(T, source_points).tolist()
        margin = 2 / scale
        bb = [min(p[0] for p in points)-margin,min(p[1] for p in points)-margin,
              max(p[0] for p in points)+margin,max(p[1] for p in points)+margin]
        item = pmitems.get(room["source"]["item_id"], {}) if room else {}
        poly = item.get("polygon_px") or []
        poly = [[p[0]*arch["W_pt"]/apm["image"]["w"],p[1]*arch["H_pt"]/apm["image"]["h"]] for p in poly]
        arch_file, service_file = args.local_dir/f"sample-{index:02d}-architect.png", args.local_dir/f"sample-{index:02d}-services.png"
        crop(str(args.architect), bb, arch_file, [poly] if poly else [], line=points if kind=="duct" else None, point=points[0] if kind=="terminal" else None)
        inv = M.invert_T(T)
        bbcorners = M.apply_T(inv,[[bb[0],bb[1]],[bb[2],bb[3]]])
        crop(str(args.services),[float(bbcorners[:,0].min()),float(bbcorners[:,1].min()),float(bbcorners[:,0].max()),float(bbcorners[:,1].max())],service_file,
             line=source_points if kind=="duct" else None,point=source_points[0] if kind=="terminal" else None)
        checks.append({"sample": index, "edges": edges, "service_label": service["label"] if service else raw.get("label") or kind,
                       "room_label": room["label"] if room else None,
                       "source_detection": raw, "crops": [str(arch_file),str(service_file)], "manual_verdict": "pending"})
    room_matches = []
    for index, edge in enumerate((e for e in graph["edges"] if e["kind"] == "same_as"), 1):
        evidence = edge["evidence"]
        crops = []
        for origin, word in zip((args.services,args.architect),evidence.get("text_sources", [])):
            x0,y0,x1,y1 = word["bbox_pt"]
            k = scale*T["s"] if word["doc_id"] == "services" else scale
            margin = 2/k
            dest = args.local_dir/f"room-match-{index:02d}-{word['doc_id']}.png"
            crop(str(origin), [x0-margin,y0-margin,x1+margin,y1+margin],dest,point=[(x0+x1)/2,(y0+y1)/2])
            crops.append(str(dest))
        room_matches.append({"from_label":nodes[edge["from"]]["label"],"to_label":nodes[edge["to"]]["label"],
                             "edge":edge,"crops":crops})
    result = {"sources": [args.architect.name,args.services.name], "pdf_reader_commit": "ad2cbd9",
              "extraction_seconds": extraction_seconds, "graph_build_seconds": build_seconds,
              "alignment": {**T,"residual_m":T["residual"]*scale}, "alignment_validation": anchor_checks(vent,arch,T,scale),
              "split": {"method":split["method"],"stats":split["stats"],"source_m_per_pt":split["m_per_pt"]},
              "detected": {"duct_runs":len(ducts),"terminals":len(terms)},
              "linked": {"terminals":len({e["from"] for e in terminal_links}),"duct_runs":len({e["from"] for e in duct_links}),
                         "duct_room_edges":len(duct_links),"room_same_as":sum(e["kind"]=="same_as" for e in graph["edges"])},
              "rooms":room_rows,"sample_selection":"All first three detected terminals; seven distinct evenly spaced duct candidates, including unlinked candidates.",
              "manual_checks":checks,"room_matches":room_matches,"mep":graph.get("mep"),"stats":graph["stats"],
              "limitations":["Detected candidates are incomplete; counts are not total installed quantities.",
                              "Crops contain local source drawings and are deliberately not committed.",
                              "Judges' sheets are evaluation only; no confidence table is fit on these files."]}
    save(args.output,result)
    print(json.dumps({k:result[k] for k in ("graph_build_seconds","detected","linked","mep")}),flush=True)


if __name__ == "__main__":
    main()
