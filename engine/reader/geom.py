"""Reader tools: drawing scale (printed scale text + page size) and measuring on the page. No model calls."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from engine.reader.text import PageText

RATIO = re.compile(r"(?<![\d.])1\s?:\s?(\d{1,5})(?!\d)")
IMPERIAL = re.compile(r"(\d+(?:/\d+)?)\s*(?:\"|in\.?|”)\s*=\s*(\d+)\s*'\s*-?\s*(\d+)?\s*(?:\"|”)?")   # 1/8" = 1'-0"
IMPERIAL_FT = re.compile(r"(?<![\d/])(\d+(?:/\d+)?)\s*(?:\"|”)\s*=\s*(\d+)\s*'")


def _frac(s: str) -> float:
    if "/" in s:
        a, b = s.split("/")
        return float(a) / float(b)
    return float(s)


def page_dpi(doc_id: str, page: int, root) -> float | None:
    d = Path(root) / doc_id
    for name in (f"text-{page}.json", "pages.json"):
        try:
            j = json.loads((d / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if name == "pages.json":
            for p in j.get("pages") or []:
                if p.get("page") == page and p.get("dpi"):
                    return float(p["dpi"])
        elif j.get("dpi"):
            return float(j["dpi"])
    return None


def scale_candidates(pt: PageText, dpi: float | None) -> list[dict]:
    """Printed scales on the sheet: [{text, ratio, m_per_px, bbox_px}]. m_per_px needs the render dpi."""
    out = []
    texts = [(s["text"], s["bbox_px"]) for s in pt.segs]
    # words joined with their neighbour phrase so '1/8" = 1'-0"' split over phrases still matches
    for txt, bb in texts:
        t = txt.replace("’", "'").replace("′", "'").replace("″", '"')
        ratio = None
        m = RATIO.search(t)
        if m and int(m.group(1)) >= 2:
            ratio = float(m.group(1))
        else:
            m2 = IMPERIAL.search(t) or IMPERIAL_FT.search(t)
            if m2:
                paper_in = _frac(m2.group(1))
                feet = float(m2.group(2)) + (float(m2.group(3)) / 12 if m2.lastindex and m2.lastindex >= 3 and m2.group(3) else 0.0)
                if paper_in > 0 and feet > 0:
                    ratio = feet * 12 / paper_in
        if ratio:
            out.append({"text": txt[:60], "ratio": round(ratio, 2), "bbox_px": bb,
                        "m_per_px": round(ratio * 0.0254 / dpi, 6) if dpi else None})
    return out


def planmap_scale(doc_id: str, page: int, root) -> dict | None:
    try:
        pm = json.loads((Path(root) / doc_id / f"planmap-{page}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    from engine.scale_policy import choose
    sc = choose(pm, Path(root) / doc_id)
    return sc if sc.get("m_per_px") else None


def polyline_length(pts: list[list[float]], closed: bool = False) -> float:
    n = len(pts)
    segs = range(n) if closed else range(n - 1)
    return sum(math.dist(pts[i], pts[(i + 1) % n]) for i in segs)


def polygon_area(pts: list[list[float]]) -> float:
    n = len(pts)
    return abs(sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))) / 2
