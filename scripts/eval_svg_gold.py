"""Score the vector-PDF plan map against exact SVG gold (IfcConvert plan SVG twin of the same IFC).

usage: .venv/bin/python scripts/eval_svg_gold.py <plan.pdf> <gold.json> [--page N] [--json out.json]

Runs pipeline.pdf_planmap.process on the PDF page in a temp dir (no PNG is rendered: pages.json gives the
pixel size), converts our items from page pixels back to page points, and compares in the page-point frame
(top-left, y down), the frame svg_gold.py writes, so no alignment is needed.

Per class: counts ours/gold; walls: centreline length ratio and footprint IoU; doors/windows: recall and
precision with centres matched one-to-one within 0.5 m; spaces: count and union-area IoU.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shapely.geometry import Polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

DPI_SCALE = 150 / 72  # page px per pt for the temp plan map
MATCH_M = 0.5
GOLD_CLASSES = {
    "wall": ("IfcWall", "IfcWallStandardCase"),
    "door": ("IfcDoor",),
    "window": ("IfcWindow",),
    "space": ("IfcSpace",),
}
OUR_KINDS = {"wall": ("wall",), "door": ("door",), "window": ("window",), "space": ("room", "space")}


def _poly(pts):
    if not pts or len(pts) < 3:
        return None
    p = Polygon(pts)
    if not p.is_valid:
        p = p.buffer(0)
    return p if not p.is_empty and p.area > 0 else None


def _centreline_len(p) -> float:
    """Rectangle with the same perimeter and area: L + t = P/2, L*t = A -> L (the long side)."""
    P, A = p.length, p.area
    h = P / 4
    disc = h * h - A
    return h + math.sqrt(disc) if disc > 0 else h


def _gold(gold: dict, key: str) -> list[dict]:
    out = []
    for cls in GOLD_CLASSES[key]:
        for el in gold["elements"].get(cls, []):
            polys = [q for q in (_poly(pp) for pp in el["polys_pt"]) if q is not None]
            x0, y0, x1, y1 = el["bbox_pt"]
            out.append({"id": el["guid"], "geom": unary_union(polys) if polys else None,
                        "c": ((x0 + x1) / 2, (y0 + y1) / 2)})
    return out


def _ours(pm: dict, key: str, s: float) -> list[dict]:
    out = []
    for it in pm.get("items", []):
        if it.get("kind") not in OUR_KINDS[key]:
            continue
        poly = it.get("polygon_px")
        g = _poly([[x / s, y / s] for x, y in poly]) if poly else None
        x0, y0, x1, y1 = [v / s for v in it["bbox_px"]]
        out.append({"id": it["item_id"], "geom": g, "c": ((x0 + x1) / 2, (y0 + y1) / 2)})
    return out


def _iou(a: list[dict], b: list[dict]):
    ga = unary_union([x["geom"] for x in a if x["geom"] is not None])
    gb = unary_union([x["geom"] for x in b if x["geom"] is not None])
    if ga.is_empty or gb.is_empty:
        return None
    u = ga.union(gb).area
    return round(ga.intersection(gb).area / u, 3) if u else None


def _match(ours: list[dict], gold: list[dict], tol_pt: float):
    """Greedy one-to-one nearest-centre matching within tol."""
    pairs = sorted(((math.dist(o["c"], g["c"]), i, j) for i, o in enumerate(ours) for j, g in enumerate(gold)))
    used_o, used_g, tp = set(), set(), 0
    for d, i, j in pairs:
        if d > tol_pt:
            break
        if i in used_o or j in used_g:
            continue
        used_o.add(i); used_g.add(j); tp += 1
    rec = round(tp / len(gold), 3) if gold else None
    prec = round(tp / len(ours), 3) if ours else None
    return tp, rec, prec


def plan_map(pdf: Path, page_index: int) -> tuple[dict | None, float]:
    from pipeline import pdf_planmap, pdf_vector
    page = pdf_vector.load_page(pdf, page_index)
    W, H = round(page["W_pt"] * DPI_SCALE), round(page["H_pt"] * DPI_SCALE)
    with tempfile.TemporaryDirectory(prefix="svg-gold-") as d:
        (Path(d) / "pages.json").write_text(json.dumps({"pages": [{"page": page_index + 1, "w": W, "h": H}]}))
        pm = pdf_planmap.process(f"eval__{pdf.stem}", Path(d), pdf, page_index, write=False)
    return pm, W / page["W_pt"]


def why_none(pdf: Path, page_index: int) -> str:
    """Replays process()'s early gates (same calls, same order) to name the one that returned None."""
    from pipeline import pdf_openings, pdf_rooms, pdf_vector
    try:
        page = pdf_vector.load_page(pdf, page_index)
        if not page.get("W_pt"):
            return "no vector page"
        if pdf_vector.is_scanned(page):
            return "scanned"
        walls = pdf_vector.walls(page)
        rooms_ = pdf_rooms.rooms(page, walls)
        ok, reason = pdf_openings.gate(page, walls, rooms_)
        if not ok:
            return f"gate: {reason} (walls {len(walls)}, rooms {len(rooms_)})"
        sc = pdf_rooms.scale(page, rooms_)
        if not sc or not sc.get("m_per_pt"):
            return f"no scale (walls {len(walls)}, rooms {len(rooms_)})"
        return f"fewer than 3 rooms+walls after build (walls {len(walls)}, rooms {len(rooms_)})"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"[:200]


def evaluate(pdf: Path, gold_path: Path, page_index: int = 0) -> dict:
    gold = json.loads(gold_path.read_text())
    mpt_gold = gold["meta"].get("m_per_pt")
    pm, s = plan_map(pdf, page_index)
    res = {"pdf": pdf.name, "gold_ratio": gold["meta"].get("ratio"), "plan_map": pm is not None}
    if pm is None:
        res["why_none"] = why_none(pdf, page_index)
        return res
    sc = pm.get("scale") or {}
    mpt_ours = sc.get("m_per_pt") or ((sc.get("m_per_px") or 0) * s) or None
    res["scale"] = {"ours_m_per_pt": mpt_ours, "gold_m_per_pt": mpt_gold, "method": sc.get("method"),
                    "rel_err": round(mpt_ours / mpt_gold - 1, 4) if mpt_ours and mpt_gold else None}
    tol = MATCH_M / mpt_gold if mpt_gold else MATCH_M / (mpt_ours or 1)
    for key in GOLD_CLASSES:
        o, g = _ours(pm, key, s), _gold(gold, key)
        r = {"ours": len(o), "gold": len(g)}
        if key == "wall":
            lo = sum(_centreline_len(x["geom"]) for x in o if x["geom"] is not None)
            lg = sum(_centreline_len(x["geom"]) for x in g if x["geom"] is not None)
            r["len_ratio"] = round(lo / lg, 3) if lg else None
            r["iou"] = _iou(o, g)
        elif key in ("door", "window"):
            r["tp"], r["recall"], r["precision"] = _match(o, g, tol)
        else:
            r["area_iou"] = _iou(o, g)
        res[key] = r
    return res


def table(rows: list[dict]) -> str:
    h = ("| PDF | scale err | walls ours/gold | wall len ratio | wall IoU | doors ours/gold | door R/P "
         "| windows ours/gold | window R/P | spaces ours/gold | space area IoU |")
    lines = [h, "|" + "---|" * 11]
    for r in rows:
        if not r.get("plan_map"):
            lines.append(f"| {r['pdf']} | no plan map |" + " |" * 9)
            continue
        w, d, wi, sp = r["wall"], r["door"], r["window"], r["space"]
        lines.append(
            f"| {r['pdf']} | {r['scale']['rel_err']} | {w['ours']}/{w['gold']} | {w['len_ratio']} | {w['iou']} "
            f"| {d['ours']}/{d['gold']} | {d['recall']}/{d['precision']} | {wi['ours']}/{wi['gold']} "
            f"| {wi['recall']}/{wi['precision']} | {sp['ours']}/{sp['gold']} | {sp['area_iou']} |")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", type=Path)
    ap.add_argument("gold", type=Path)
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    out = evaluate(a.pdf, a.gold, a.page - 1)
    if a.json:
        a.json.write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    print(table([out]))
