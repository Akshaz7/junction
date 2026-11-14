"""Reader tool: tables on a drawing sheet, found from ruling lines (opencv) with the page's words assigned to cells.

detect_tables(img_path, PageText) -> [Table]. Merged cells are honoured (a cell edge without a drawn line is merged).
Fallback for sheets without rulings: none (the planner reads the text lines or looks at the crop instead).
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from pathlib import Path

from engine.reader.text import PageText

_cache: dict[tuple, list["Table"]] = {}


@dataclass
class Cell:
    r: int
    c: int
    rs: int
    cs: int
    text: str
    bbox_px: list[float]


@dataclass
class Table:
    tid: str                       # "tbl<page>.<n>"
    page: int
    bbox_px: list[float]
    nrows: int
    ncols: int
    title: str
    cells: list[Cell] = field(default_factory=list)   # top-left cell of every merged group, row-major

    def grid(self) -> list[list[str]]:
        g = [["" for _ in range(self.ncols)] for _ in range(self.nrows)]
        for c in self.cells:
            g[c.r][c.c] = c.text
        return g

    def row_bbox(self, r: int) -> list[float]:
        cs = [c for c in self.cells if c.r <= r < c.r + c.rs]
        if not cs:
            return self.bbox_px
        return [min(c.bbox_px[0] for c in cs), min(c.bbox_px[1] for c in cs), max(c.bbox_px[2] for c in cs), max(c.bbox_px[3] for c in cs)]

    def cell_at(self, r: int, c: int) -> Cell | None:
        for x in self.cells:
            if x.r <= r < x.r + x.rs and x.c <= c < x.c + x.cs:
                return x
        return None


def _runs(profile, thresh: float) -> list[tuple[int, int]]:
    out, start = [], None
    for i, v in enumerate(profile):
        if v >= thresh and start is None:
            start = i
        elif v < thresh and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(profile) - 1))
    return out


def _centres(runs, gap: int = 4) -> list[float]:
    cs, cur = [], None
    for a, b in runs:
        if cur and a - cur[1] <= gap:
            cur = (cur[0], b)
        else:
            if cur:
                cs.append((cur[0] + cur[1]) / 2)
            cur = (a, b)
    if cur:
        cs.append((cur[0] + cur[1]) / 2)
    return cs


def detect_tables(img_path: Path, pt: PageText, min_cells: int = 6) -> list[Table]:
    import cv2
    import numpy as np
    key = (str(img_path), img_path.stat().st_mtime_ns if img_path.exists() else 0, len(pt.words))
    if key in _cache:
        return _cache[key]
    im = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
    if im is None:
        return []
    H, W = im.shape
    bw = (im < 170).astype("uint8") * 255
    L = max(25, int(W * 0.007))
    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (L, 1)))
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, L)))
    grid = cv2.dilate(cv2.bitwise_or(horiz, vert), np.ones((5, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(grid, connectivity=8)
    comps = sorted((tuple(stats[i][:4]) for i in range(1, n) if stats[i][2] >= 120 and stats[i][3] >= 50), key=lambda s: (s[1], s[0]))
    tables: list[Table] = []
    for (x0, y0, cw, ch) in comps:
        if cw * ch > 0.6 * W * H:
            continue
        x1, y1 = x0 + cw, y0 + ch
        hz = horiz[y0:y1, x0:x1]
        vt = vert[y0:y1, x0:x1]
        ys = _centres(_runs((hz > 0).sum(axis=1), 0.12 * cw))
        xs = _centres(_runs((vt > 0).sum(axis=0), 0.12 * ch))
        if len(ys) < 2 or len(xs) < 2 or (len(ys) - 1) * (len(xs) - 1) < min_cells:
            continue
        nr, nc = len(ys) - 1, len(xs) - 1
        if nr * nc > 4000:
            continue
        # merge cells whose shared edge has no drawn line
        parent = list(range(nr * nc))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        def union(a, b):
            parent[find(a)] = find(b)
        for r in range(nr):
            for c in range(nc):
                if c + 1 < nc:      # vertical edge at xs[c+1] over rows r
                    xi, ya, yb = int(xs[c + 1]), int(ys[r]) + 3, int(ys[r + 1]) - 3
                    seg = vt[max(ya, 0):max(yb, ya + 1), max(xi - 2, 0):xi + 3]
                    if seg.size == 0 or (seg.max(axis=1) > 0).mean() < 0.5:
                        union(r * nc + c, r * nc + c + 1)
                if r + 1 < nr:      # horizontal edge at ys[r+1] over cols c
                    yi, xa, xb = int(ys[r + 1]), int(xs[c]) + 3, int(xs[c + 1]) - 3
                    seg = hz[max(yi - 2, 0):yi + 3, max(xa, 0):max(xb, xa + 1)]
                    if seg.size == 0 or (seg.max(axis=0) > 0).mean() < 0.5:
                        union(r * nc + c, (r + 1) * nc + c)
        groups: dict[int, list[tuple[int, int]]] = {}
        for r in range(nr):
            for c in range(nc):
                groups.setdefault(find(r * nc + c), []).append((r, c))
        ab_x = [x0 + v for v in xs]
        ab_y = [y0 + v for v in ys]
        words_in: dict[int, list[dict]] = {}
        for w in pt.words:
            b = w["bbox_px"]
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            if not (ab_x[0] <= cx <= ab_x[-1] and ab_y[0] <= cy <= ab_y[-1]):
                continue
            c = min(max(bisect.bisect_right(ab_x, cx) - 1, 0), nc - 1)
            r = min(max(bisect.bisect_right(ab_y, cy) - 1, 0), nr - 1)
            words_in.setdefault(find(r * nc + c), []).append(w)
        cells = []
        for g, members in groups.items():
            rs_ = [m[0] for m in members]
            cs_ = [m[1] for m in members]
            r0, r1, c0, c1 = min(rs_), max(rs_), min(cs_), max(cs_)
            ws = sorted(words_in.get(g, []), key=lambda w: (round((w["bbox_px"][1] + w["bbox_px"][3]) / 2 / 12), w["bbox_px"][0]))
            text = " ".join(str(w["text"]) for w in ws).strip()
            cells.append(Cell(r0, c0, r1 - r0 + 1, c1 - c0 + 1, text,
                              [round(ab_x[c0], 1), round(ab_y[r0], 1), round(ab_x[c1 + 1], 1), round(ab_y[r1 + 1], 1)]))
        cells.sort(key=lambda c: (c.r, c.c))
        filled = sum(1 for c in cells if c.text)
        if filled < 4:
            continue
        # title: nearest phrase above the table that overlaps it horizontally, else the first row's text
        title = cells[0].text if cells and cells[0].cs >= max(2, nc // 2) and cells[0].r == 0 else ""
        if not title:
            above = [s for s in pt.segs if s["bbox_px"][3] <= ab_y[0] + 2 and ab_y[0] - s["bbox_px"][3] < 140 and len(s["text"]) > 3 and
                     s["bbox_px"][2] > ab_x[0] and s["bbox_px"][0] < ab_x[-1]]
            if above:
                title = max(above, key=lambda s: s["bbox_px"][3])["text"]
        tables.append(Table("", pt.page, [float(ab_x[0]), float(ab_y[0]), float(ab_x[-1]), float(ab_y[-1])], nr, nc, title[:80], cells))
    for i, t in enumerate(tables, 1):
        t.tid = f"tbl{pt.page}.{i}"
    _cache[key] = tables
    return tables
