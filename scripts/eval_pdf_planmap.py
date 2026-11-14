"""Evaluate the vector-PDF plan map against DXF twins, and the plan/non-plan gate on negatives.

  .venv/bin/python scripts/eval_pdf_planmap.py --pair A.pdf:A.dxf ... --neg X.pdf[:page] ... --out results.json
  .venv/bin/python scripts/eval_pdf_planmap.py --swiss 5 --neg ... --out results.json   # first 5 Swiss pairs, sorted

Each PDF / DXF / gate run is a separate subprocess (one heavy job at a time), timed, with peak RSS from
resource.getrusage(RUSAGE_SELF).ru_maxrss inside the worker. Metrics per pair: room count, total room area
(measured geometry, printed labels), wall length, door/window count, per-room area error (median / max) for
measured vs DXF, printed vs DXF and measured vs printed; and whether printed 1:N agrees with the printed-areas fit
within 2% (scale.check.agree_2pct). Rooms are matched by printed label + area, then by normalised centroid.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWISS = ROOT / "data" / "junction-dataset-preview" / "data" / "swiss_dwellings"
MAX_PDF_PAGES = 4


# ------------------------------------------------------------------ workers (run in a subprocess)
def _rss_mb():
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _worker_pdf(pdf, out, doc_id):
    from pipeline import pages, pdf_planmap
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    pg = pages.do_pdf(Path(pdf), doc_id, out)
    (out / "pages.json").write_text(json.dumps({"doc_id": doc_id, "source": "pdf", "pages": pg}))
    t_render = time.time() - t0
    best, per_page = None, []
    for i in range(min(len(pg), MAX_PDF_PAGES)):
        t1 = time.time()
        try:
            pm = pdf_planmap.process(doc_id, out, Path(pdf), i, write=True)
            err = None
        except Exception as e:  # noqa: BLE001
            pm, err = None, repr(e)[:200]
        nr = sum(1 for it in pm["items"] if it["kind"] == "room") if pm else 0
        per_page.append({"page": i + 1, "planmap": pm is not None, "rooms": nr, "s": round(time.time() - t1, 2),
                         "gate": (pm or {}).get("provenance", {}).get("gate"), "error": err})
        if pm and (best is None or nr > best[1]):
            best = (i + 1, nr)
    return {"render_s": round(t_render, 2), "total_s": round(time.time() - t0, 2), "pages": per_page,
            "planmap": str(out / f"planmap-{best[0]}.json") if best else None, "rss_mb": round(_rss_mb(), 1)}


def _worker_dxf(dxf, out, doc_id):
    from pipeline import dxf_planmap, pages
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    pg = pages.do_dxf(Path(dxf), out)
    (out / "pages.json").write_text(json.dumps({"doc_id": doc_id, "source": "dxf", "pages": pg}))
    pm = dxf_planmap.process(doc_id, out, Path(dxf))
    f = out / "planmap-1.json"
    if pm is not None and not f.is_file():
        f.write_text(json.dumps(pm))
    return {"total_s": round(time.time() - t0, 2), "planmap": str(f) if f.is_file() else None,
            "rss_mb": round(_rss_mb(), 1)}


def _worker_gate(pdf, page_index):
    from pipeline import pdf_openings, pdf_rooms, pdf_vector
    t0 = time.time()
    page = pdf_vector.load_page(Path(pdf), int(page_index))
    walls = pdf_vector.walls(page) if page.get("W_pt") else []
    rooms = pdf_rooms.rooms(page, walls) if page.get("W_pt") else []
    ok, why = pdf_openings.gate(page, walls, rooms)
    if page.get("W_pt") and pdf_vector.is_scanned(page):
        ok, why = False, "scanned (pdf_vector.is_scanned)"
    return {"is_plan": ok, "reason": why, "walls": len(walls), "rooms": len(rooms), "s": round(time.time() - t0, 2),
            "rss_mb": round(_rss_mb(), 1)}


def _worker_planmap_neg(pdf, out, doc_id):
    """Full process() on a negative: must return no plan map on every page."""
    r = _worker_pdf(pdf, out, doc_id)
    return {"planmap_pages": [p["page"] for p in r["pages"] if p["planmap"]], "total_s": r["total_s"],
            "rss_mb": r["rss_mb"]}


def _spawn(*args, timeout=600):
    cmd = [sys.executable, "-W", "ignore", str(Path(__file__).resolve()), "--worker", *map(str, args)]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT,
                       env={**os.environ, "PYTHONPATH": str(ROOT)})
    line = next((ln for ln in reversed(p.stdout.splitlines()) if ln.startswith("{")), None)
    if p.returncode != 0 or not line:
        return {"error": (p.stderr or p.stdout)[-600:], "wall_s": round(time.time() - t0, 2)}
    r = json.loads(line)
    r["wall_s"] = round(time.time() - t0, 2)
    return r


# ------------------------------------------------------------------ metrics
def _area(p):
    return abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(p, p[1:] + p[:1]))) / 2


def _perim(p):
    return sum(math.dist(a, b) for a, b in zip(p, p[1:] + p[:1]))


def _wall_len(p):
    """Long side of the rectangle with this polygon's area and perimeter (centre-line length of a wall slab)."""
    A, P = _area(p), _perim(p)
    d = P * P - 16 * A
    return (P + math.sqrt(d)) / 4 if d > 0 else P / 4


def _summ(pm):
    mpp = (pm.get("scale") or {}).get("m_per_px") or 0
    rooms = [i for i in pm["items"] if i["kind"] == "room"]
    walls = [i for i in pm["items"] if i["kind"] == "wall" and i.get("polygon_px")]
    out = {"rooms": len(rooms), "doors": sum(i["kind"] == "door" for i in pm["items"]),
           "windows": sum(i["kind"] == "window" for i in pm["items"]), "walls": len(walls), "m_per_px": mpp}
    geo = []
    for r in rooms:
        pr = r.get("props") or {}
        g = pr.get("area_m2_geom")
        if g is None and r.get("polygon_px") and mpp:
            g = _area(r["polygon_px"]) * mpp * mpp
        geo.append(g)
    out["area_geom_m2"] = round(sum(g for g in geo if g), 2)
    out["area_printed_m2"] = round(sum((r.get("props") or {}).get("area_m2_label") or 0 for r in rooms), 2)
    out["wall_len_m"] = round(sum(_wall_len(w["polygon_px"]) for w in walls) * mpp, 2)
    q = [(w.get("q") or {}).get("length_m") for w in walls]
    if any(v is not None for v in q):
        out["wall_len_m_own"] = round(sum(v or 0 for v in q), 2)
    out["_rooms"] = []
    allc = [c for r in rooms if r.get("polygon_px") or r.get("bbox_px") for c in [_centre(r)]]
    bx = [min(c[0] for c in allc), min(c[1] for c in allc), max(c[0] for c in allc), max(c[1] for c in allc)] if allc else None
    for r, g in zip(rooms, geo):
        c = _centre(r)
        nc = [(c[0] - bx[0]) / max(bx[2] - bx[0], 1e-6), (c[1] - bx[1]) / max(bx[3] - bx[1], 1e-6)] if bx else [0, 0]
        out["_rooms"].append({"label": (r.get("label") or "").strip().lower(), "printed": (r.get("props") or {}).get("area_m2_label"),
                              "geom": g, "c": nc})
    return out


def _centre(r):
    p = r.get("polygon_px")
    if p:
        return [sum(q[0] for q in p) / len(p), sum(q[1] for q in p) / len(p)]
    b = r["bbox_px"]
    return [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]


def _match(a, b):
    """Greedy room matching: same printed area (+label) first, then nearest normalised centroid (< 0.15)."""
    pairs, used = [], set()
    for i, ra in enumerate(a):
        if ra["printed"] is None:
            continue
        cand = [j for j, rb in enumerate(b) if j not in used and rb["printed"] is not None
                and abs(rb["printed"] - ra["printed"]) < 0.015]
        if cand:
            j = min(cand, key=lambda j: (b[j]["label"] != ra["label"], math.dist(ra["c"], b[j]["c"])))
            used.add(j); pairs.append((i, j))
    done = {i for i, _ in pairs}
    rest = sorted(((math.dist(ra["c"], rb["c"]), i, j) for i, ra in enumerate(a) if i not in done
                   for j, rb in enumerate(b) if j not in used))
    for d, i, j in rest:
        if d > 0.15 or i in done or j in used:
            continue
        done.add(i); used.add(j); pairs.append((i, j))
    return pairs


def _med(v):
    v = sorted(v)
    if not v:
        return None
    n = len(v)
    return round(v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2, 4)


def compare(pdf_pm, dxf_pm):
    a, b = _summ(pdf_pm), _summ(dxf_pm)
    pairs = _match(a["_rooms"], b["_rooms"])
    e_meas, e_print, e_mp = [], [], []
    for i, j in pairs:
        ra, rb = a["_rooms"][i], b["_rooms"][j]
        if ra["geom"] and rb["geom"]:
            e_meas.append(abs(ra["geom"] / rb["geom"] - 1))
        if ra["printed"] and rb["geom"]:
            e_print.append(abs(ra["printed"] / rb["geom"] - 1))
        if ra["geom"] and ra["printed"]:
            e_mp.append(abs(ra["geom"] / ra["printed"] - 1))
    rel = lambda x, y: round(x / y - 1, 4) if y else None
    chk = (pdf_pm.get("scale") or {}).get("check") or {}
    res = {
        "pdf": {k: v for k, v in a.items() if not k.startswith("_")},
        "dxf": {k: v for k, v in b.items() if not k.startswith("_")},
        "room_count_equal": a["rooms"] == b["rooms"],
        "total_area_rel_err_geom": rel(a["area_geom_m2"], b["area_geom_m2"]),
        "total_area_rel_err_printed": rel(a["area_printed_m2"], b["area_geom_m2"]),
        "wall_len_rel_err": rel(a["wall_len_m"], b["wall_len_m"]),
        "wall_len_own_rel_err": rel(a.get("wall_len_m_own") or 0, b["wall_len_m"]) if a.get("wall_len_m_own") else None,
        "doors_diff": a["doors"] - b["doors"],
        "rooms_matched": len(pairs),
        "room_area_err_measured_vs_dxf": {"median": _med(e_meas), "max": round(max(e_meas), 4) if e_meas else None},
        "room_area_err_printed_vs_dxf": {"median": _med(e_print), "max": round(max(e_print), 4) if e_print else None},
        "room_area_err_measured_vs_printed": {"median": _med(e_mp), "max": round(max(e_mp), 4) if e_mp else None},
        "scale": {k: (pdf_pm.get("scale") or {}).get(k) for k in ("method", "ratio", "m_per_pt", "confidence")},
        "ratio_vs_areas_agree_2pct": chk.get("agree_2pct"),
    }
    res["pass"] = {"rooms": res["room_count_equal"],
                   "area_5pct": res["total_area_rel_err_geom"] is not None and abs(res["total_area_rel_err_geom"]) <= 0.05,
                   "walls_10pct": res["wall_len_rel_err"] is not None and abs(res["wall_len_rel_err"]) <= 0.10,
                   "doors_pm1": abs(res["doors_diff"]) <= 1}
    return res


# ------------------------------------------------------------------ driver
def swiss_pairs(n):
    if not SWISS.is_dir():
        return []
    pdfs = {p.stem: p for p in SWISS.rglob("*.pdf")}
    dxfs = {p.stem: p for p in SWISS.rglob("*.dxf")}
    return [(pdfs[k], dxfs[k]) for k in sorted(set(pdfs) & set(dxfs))][:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", action="append", default=[], help="PDF:DXF")
    ap.add_argument("--swiss", type=int, default=0, help="take the first N Swiss Dwellings PDF/DXF pairs")
    ap.add_argument("--neg", action="append", default=[], help="negative PDF[:page1-based]; no page = all pages (<=4)")
    ap.add_argument("--pos", action="append", default=[], help="positive (plan) PDF[:page]: gate should accept")
    ap.add_argument("--full-neg", action="store_true", help="also run the full process() on negatives")
    ap.add_argument("--out", default=str(ROOT / "results" / "eval_pdf_planmap.json"))
    ap.add_argument("--keep", help="keep work dirs here (default: temp)")
    a = ap.parse_args()
    pairs = [tuple(Path(x) for x in p.split(":", 1)) for p in a.pair] + swiss_pairs(a.swiss)
    tmp = Path(a.keep) if a.keep else Path(tempfile.mkdtemp(prefix="evalpdf-"))
    report = {"created": time.strftime("%Y-%m-%dT%H:%M:%S"), "pairs": [], "negatives": [], "positives": []}
    for pdf, dxf in pairs:
        did = pdf.stem.lower()[:60]
        print(f"== {did}", flush=True)
        rp = _spawn("pdf", pdf, tmp / did / "pdf", did)
        rd = _spawn("dxf", dxf, tmp / did / "dxf", did)
        row = {"doc": did, "pdf_file": str(pdf), "dxf_file": str(dxf),
               "pdf_run": {k: v for k, v in rp.items() if k != "planmap"},
               "dxf_run": {k: v for k, v in rd.items() if k != "planmap"}}
        if rp.get("planmap") and rd.get("planmap"):
            row.update(compare(json.loads(Path(rp["planmap"]).read_text()), json.loads(Path(rd["planmap"]).read_text())))
        else:
            row["error"] = "no pdf plan map" if not rp.get("planmap") else "no dxf plan map"
        report["pairs"].append(row)
        print(json.dumps({k: row.get(k) for k in ("room_count_equal", "total_area_rel_err_geom", "wall_len_rel_err",
                                                    "doors_diff", "room_area_err_measured_vs_dxf", "error")}), flush=True)
    for spec, expect in [(x, False) for x in a.neg] + [(x, True) for x in a.pos]:
        path, _, pg = spec.partition(":")
        if pg:
            idx = [int(pg) - 1]
        else:
            import pypdfium2 as pdfium
            d = pdfium.PdfDocument(path); idx = list(range(min(len(d), MAX_PDF_PAGES))); d.close()
        for i in idx:
            r = _spawn("gate", path, i)
            row = {"pdf": Path(path).name, "page": i + 1, "expect_plan": expect, **r}
            report["negatives" if not expect else "positives"].append(row)
            print(f"{'pos' if expect else 'neg'} {Path(path).name[:70]} p{i + 1}: plan={r.get('is_plan')} ({r.get('reason')})", flush=True)
        if a.full_neg and not expect:
            did = Path(path).stem.lower()[:60]
            r = _spawn("negpm", path, tmp / ("neg-" + did), did)
            report["negatives"].append({"pdf": Path(path).name, "full_process": r})
            print(f"neg full process {Path(path).name[:70]}: plan map pages {r.get('planmap_pages')}", flush=True)
    # summary
    P = [r for r in report["pairs"] if "pass" in r]
    summ = {"pairs": len(report["pairs"]), "compared": len(P)}
    for k in ("rooms", "area_5pct", "walls_10pct", "doors_pm1"):
        summ[k] = sum(r["pass"][k] for r in P)
    summ["ratio_vs_areas_agree_2pct"] = sum(1 for r in P if r.get("ratio_vs_areas_agree_2pct"))
    me = [r["room_area_err_measured_vs_dxf"]["median"] for r in P if r["room_area_err_measured_vs_dxf"]["median"] is not None]
    summ["room_area_err_measured_vs_dxf_median_of_medians"] = _med(me)
    summ["pdf_wall_s_max"] = max((r["pdf_run"].get("wall_s") or 0 for r in report["pairs"]), default=None)
    summ["pdf_rss_mb_max"] = max((r["pdf_run"].get("rss_mb") or 0 for r in report["pairs"]), default=None)
    gates = [r for r in report["negatives"] if "is_plan" in r]
    summ["negatives_pages"] = len(gates)
    summ["negatives_rejected"] = sum(1 for r in gates if r.get("is_plan") is False)
    pos = [r for r in report["positives"] if "is_plan" in r]
    summ["positives_pages"] = len(pos)
    summ["positives_accepted"] = sum(1 for r in pos if r.get("is_plan"))
    report["summary"] = summ
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=1))
    print(json.dumps(summ, indent=1))
    print(f"wrote {a.out}  (work dir {tmp})")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--worker":
        sys.path.insert(0, str(ROOT))
        kind, args = sys.argv[2], sys.argv[3:]
        fn = {"pdf": _worker_pdf, "dxf": _worker_dxf, "gate": _worker_gate, "negpm": _worker_planmap_neg}[kind]
        print(json.dumps(fn(*args)))
    else:
        main()
