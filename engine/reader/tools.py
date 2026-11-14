"""Reader tools over artifacts/<doc>/: one Session per question. Every tool returns a short text observation for the planner
and registers evidence (id eN) with the page box it came from; the final answer may only cite registered ids.

Tools: find_text, page_text, tables, table, view, scale, measure, planmap, ifc, compute.
"""
from __future__ import annotations

import ast
import json
import operator
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from engine.reader import geom
from engine.reader.tables import Table, detect_tables
from engine.reader.text import PageText, find_text, image_path, load_page_text, norm, png_size, tokens
from engine.solvers.data import Doc, load_doc

MAX_VIEWS = 2
MAX_HITS = 10
OBS_CAP = 4200


@dataclass
class Evidence:
    ref: str
    kind: str                       # text | region | element | row
    doc_id: str
    page: int
    bbox_px: list[float] | None
    quote: str | None = None
    item_ids: list[str] = field(default_factory=list)
    label: str | None = None
    cells: dict[int, list[float]] = field(default_factory=dict)    # row evidence: column index -> bbox
    visual: bool = False


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return str(v)


class Session:
    def __init__(self, doc_ids: list[str], root, emit=None, on_cost=None):
        self.root = Path(root)
        self.doc_ids = list(doc_ids)
        self.emit = emit or (lambda kind, payload: None)
        self.on_cost = on_cost or (lambda c: None)
        self.ev: dict[str, Evidence] = {}
        self.docs: dict[str, dict] = {}
        self.tables: dict[str, tuple[str, int, Table]] = {}
        self.views = 0
        self.transcript: list[str] = []            # every observation, for number grounding
        self._planmaps: dict[str, Doc | None] = {}
        for i, d in enumerate(self.doc_ids, 1):
            self.docs[f"d{i}"] = {"id": d, **self._meta(d)}

    # -- documents ---------------------------------------------------------------------------------------------
    def _meta(self, doc_id: str) -> dict:
        d = self.root / doc_id
        try:
            m = json.loads((d / "doc.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            m = {}
        pages = m.get("pages") or len(list(d.glob("page-[0-9]*.png"))) or 1
        if isinstance(pages, list):
            pages = len(pages)
        return {"title": m.get("title") or doc_id, "kind": m.get("kind") or "?", "pages": int(pages),
                "ifc": (d / "elements.json").exists(), "planmaps": len(list(d.glob("planmap-[0-9]*.json")))}

    def resolve(self, ref) -> str | None:
        ref = str(ref or "").strip()
        if ref in self.docs:
            return self.docs[ref]["id"]
        if ref in self.doc_ids:
            return ref
        if not ref and len(self.doc_ids) == 1:
            return self.doc_ids[0]
        low = [d for d in self.doc_ids if ref and ref.casefold() in d.casefold()]
        return low[0] if len(low) == 1 else None

    def label_of(self, doc_id: str) -> str:
        return next((k for k, v in self.docs.items() if v["id"] == doc_id), doc_id)

    def doc(self, doc_id: str, prefer: str | None = None) -> Doc | None:
        k = f"{doc_id}:{prefer}"
        if k not in self._planmaps:
            self._planmaps[k] = load_doc(doc_id, self.root, prefer)
        return self._planmaps[k]

    def overview(self) -> str:
        out = []
        for k, v in self.docs.items():
            mode = "IFC model" if v["ifc"] else ("plan map" if v["planmaps"] else "sheet")
            out.append(f'{k} = "{v["title"]}" (id {v["id"]}; {v["kind"]}; {v["pages"]} page(s); {mode})')
        return "\n".join(out)

    # -- evidence ----------------------------------------------------------------------------------------------
    def reg(self, kind, doc_id, page, bbox, quote=None, item_ids=None, label=None, cells=None, visual=False) -> str:
        ref = f"e{len(self.ev) + 1}"
        self.ev[ref] = Evidence(ref, kind, doc_id, page, [float(round(float(v), 1)) for v in bbox] if bbox else None,
                                (quote or None) and quote[:240], list(item_ids or []), label,
                                {int(k): [float(x) for x in v] for k, v in (cells or {}).items()}, visual)
        return ref

    def page_text(self, doc_id: str, page: int) -> PageText:
        return load_page_text(doc_id, page, self.root)

    def _tables(self, doc_id: str, page: int) -> list[tuple[str, Table]]:
        img = image_path(doc_id, page, self.root)
        if not img.exists():
            return []
        out = []
        for t in detect_tables(img, self.page_text(doc_id, page)):
            key = f"{self.label_of(doc_id)}.{t.tid}"
            self.tables[key] = (doc_id, page, t)
            out.append((key, t))
        return out

    def _pages(self, doc_id: str, page) -> list[int]:
        n = self.docs.get(self.label_of(doc_id), {}).get("pages", 1)
        if page:
            try:
                return [int(page)] if 1 <= int(page) <= n else []
            except (TypeError, ValueError):
                return []
        return list(range(1, min(n, 12) + 1))

    # -- dispatch ----------------------------------------------------------------------------------------------
    def run(self, tool: str, args: dict) -> str:
        fn = getattr(self, f"t_{tool}", None)
        if fn is None:
            return f"error: unknown tool '{tool}'. Tools: find_text, page_text, tables, table, view, scale, measure, planmap, ifc, compute."
        # Publish before parsing a large model, not after the expensive load.
        if tool in ("ifc", "planmap"):
            nouns = {"door": "doors", "window": "windows", "room": "rooms", "wall": "walls", "pipe": "pipes",
                     "duct": "ducts", "column": "columns", "stairs": "stairs", "toilet": "toilets", "sink": "sinks"}
            noun = nouns.get(str(args.get("kind") or ""), "model elements" if tool == "ifc" else "drawing items")
            level = str(args.get("storey") or "").strip()[:60]
            self.status(f"Checking {noun}" + (f" on {level}" if level else "") + "…")
        elif tool == "compute":
            self.status("Calculating from the findings…")
        try:
            obs = fn(**{k: v for k, v in (args or {}).items()})
        except TypeError as e:
            obs = f"error: bad arguments for {tool}: {e}"
        except Exception as e:  # noqa: BLE001 — a tool failure is an observation, not a crash
            obs = f"error: {tool} failed ({type(e).__name__}: {str(e)[:120]})"
        obs = obs if len(obs) <= OBS_CAP else obs[:OBS_CAP] + "\n[truncated]"
        self.transcript.append(obs)
        return obs

    def status(self, text: str):
        self.emit("status", {"text": text})

    # -- tools -------------------------------------------------------------------------------------------------
    def t_find_text(self, query: str, doc: str = "", page=None) -> str:
        ids = [self.resolve(doc)] if doc else self.doc_ids
        if None in ids:
            return f"error: unknown doc '{doc}'"
        self.status(f'Finding "{str(query)[:50]}"')
        lines, n = [], 0
        for did in ids:
            for pg in self._pages(did, page):
                pt = self.page_text(did, pg)
                if not pt.words:
                    continue
                hits = find_text(pt, str(query), limit=MAX_HITS)
                tabs = self._tables(did, pg) if hits else []
                for h in hits:
                    if n >= MAX_HITS:
                        break
                    ref = self.reg("text", did, pg, h["bbox_px"], h["text"])
                    where = ""
                    cx, cy = (h["bbox_px"][0] + h["bbox_px"][2]) / 2, (h["bbox_px"][1] + h["bbox_px"][3]) / 2
                    for key, t in tabs:
                        b = t.bbox_px
                        if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]:
                            cell = next((c for c in t.cells if c.bbox_px[0] <= cx <= c.bbox_px[2] and c.bbox_px[1] <= cy <= c.bbox_px[3]), None)
                            if cell:
                                where = f" in {key} row {cell.r} col {cell.c}"
                            break
                    lines.append(f'{ref} {self.label_of(did)} p{pg}{where}: "{h["text"][:140]}"')
                    n += 1
        if not lines:
            return f'no match for "{query}" in the text of the selected pages (the text layer may be missing or the term spelled differently).'
        return "\n".join(lines)

    def t_page_text(self, doc: str = "", page=1, bbox=None) -> str:
        did = self.resolve(doc)
        if not did:
            return f"error: unknown doc '{doc}'"
        pg = int(page or 1)
        self.status(f"Reading sheet {self.docs[self.label_of(did)]['title']}")
        pt = self.page_text(did, pg)
        if not pt.words:
            return "no text on this page (raster drawing without readable text). Use view to look at it."
        bb = [float(v) for v in bbox] if bbox and len(bbox) == 4 else None
        segs = geom_lines(pt, bb)
        out = []
        for row in segs:
            text = " | ".join(s["text"] for s in row)
            b = [min(s["bbox_px"][0] for s in row), min(s["bbox_px"][1] for s in row), max(s["bbox_px"][2] for s in row), max(s["bbox_px"][3] for s in row)]
            out.append(f'{self.reg("text", did, pg, b, text)}: {text[:200]}')
            if sum(len(x) for x in out) > 3800:
                out.append("[more text on the page: pass a bbox to read a region]")
                break
        return "\n".join(out) or "no text inside that region."

    def t_tables(self, doc: str = "", page=1) -> str:
        did = self.resolve(doc)
        if not did:
            return f"error: unknown doc '{doc}'"
        pg = int(page or 1)
        self.status(f"Finding tables on sheet {self.docs[self.label_of(did)]['title']}")
        ts = self._tables(did, pg)
        if not ts:
            return "no ruled tables detected on this page. Use page_text or view."
        out = []
        for key, t in ts:
            head = " / ".join(c.text for c in t.cells if c.r <= 2 and c.text)[:150]
            out.append(f'{key}: "{t.title}" {t.nrows} rows x {t.ncols} cols at {[int(v) for v in t.bbox_px]}; header: {head}')
        return "\n".join(out)

    def t_table(self, id: str, find: str = "", rows: str = "", max_rows: int = 45) -> str:
        id = str(id)
        if id not in self.tables:
            hit = [k for k in self.tables if k.endswith(id)]
            if len(hit) != 1:
                return f"error: unknown table '{id}'. Call tables first."
            id = hit[0]
        did, pg, t = self.tables[id]
        self.status(f"Reading the {t.title or 'table'} table")
        g = t.grid()
        want: list[int] = []
        if find:
            q = [x for x in tokens(find) if x]
            for r, row in enumerate(g):
                if r < 3:
                    continue
                txt = tokens(" ".join(row))
                if q and all(any(qt == st or (len(qt) >= 3 and qt in st) for st in txt) for qt in q):
                    want.append(r)
        elif rows:
            for part in str(rows).split(","):
                a, _, b = part.strip().partition("-")
                try:
                    want += list(range(int(a), int(b or a) + 1))
                except ValueError:
                    pass
            want = [r for r in want if 0 <= r < t.nrows][:12]
        else:
            want = list(range(3, min(t.nrows, 3 + int(max_rows))))
        head_rows = list(range(min(3, t.nrows)))
        out = [f"{id} \"{t.title}\" ({t.nrows} rows x {t.ncols} cols). Columns are numbered 0..{t.ncols - 1}; cite a cell as eN#cK."]
        for r in (head_rows if not (find or rows) else head_rows[:2]) + [w for w in want if w not in head_rows][:int(max_rows)]:
            cells = {c.c: c.bbox_px for c in t.cells if c.r <= r < c.r + c.rs and c.r == r}
            txt = " | ".join(f"{c}:{g[r][c]}" if g[r][c] else f"{c}:" for c in range(t.ncols))
            ref = self.reg("row", did, pg, t.row_bbox(r), txt, cells={c: b for c, b in cells.items()}, label=f"{id} r{r}")
            out.append(f"{ref} r{r}: {txt}")
        if find and not want:
            out.append(f'no row contains "{find}".')
        elif not find and not rows and t.nrows > 3 + int(max_rows):
            out.append(f"[{t.nrows - 3 - int(max_rows)} more rows: use find or rows=\"a-b\"]")
        return "\n".join(out)

    def t_view(self, doc: str = "", page=1, bbox=None, ref: str = "", pad: int = 250, ask: str = "") -> str:
        if self.views >= MAX_VIEWS:
            return "error: view limit reached for this question."
        did = self.resolve(doc) if doc else None
        pg = int(page or 1)
        if ref and ref in self.ev and self.ev[ref].bbox_px:
            e = self.ev[ref]
            did, pg = e.doc_id, e.page
            b = e.bbox_px
            bbox = [b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad]
        did = did or (self.doc_ids[0] if len(self.doc_ids) == 1 else None)
        if not did:
            return "error: give doc"
        img = image_path(did, pg, self.root)
        size = png_size(img)
        if not size:
            return "error: no page image"
        from PIL import Image
        im = Image.open(img).convert("RGB")
        W, H = im.size
        if bbox and len(bbox) == 4:
            x0, y0, x1, y1 = [float(v) for v in bbox]
        else:
            x0, y0, x1, y1 = 0, 0, W, H
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        if x1 - x0 < 20 or y1 - y0 < 20:
            return "error: empty crop"
        crop = im.crop((int(x0), int(y0), int(x1), int(y1)))
        s = min(1.0, 1600 / max(crop.size))
        if s < 1:
            crop = crop.resize((max(1, int(crop.width * s)), max(1, int(crop.height * s))))
        self.status(f"Looking closely at sheet {self.docs[self.label_of(did)]['title']}")
        tmp = Path(tempfile.mkdtemp(prefix="reader-")) / "crop.png"
        crop.save(tmp)
        from engine import models as M
        prompt = ("You are reading part of a construction drawing. Answer from what is visible in this image only; quote printed text "
                  "exactly (keep units and symbols). If it is not visible, say 'not visible'. Reply in 1-4 short sentences.\n\n" + (ask or "Describe what is shown."))
        r = M.call("read_drawing", prompt, images=[tmp])
        self.views += 1
        self.on_cost({"task": "read_drawing", "provider": r.provider, "model": r.model, "cost_usd": r.cost_usd})
        txt = (r.text or "").strip()[:600]
        e = self.reg("region", did, pg, [x0, y0, x1, y1], txt, visual=True)
        return f"{e} (visual reading of the crop {[int(x0), int(y0), int(x1), int(y1)]} on p{pg}): {txt}"

    def t_scale(self, doc: str = "", page=1) -> str:
        did = self.resolve(doc)
        if not did:
            return f"error: unknown doc '{doc}'"
        pg = int(page or 1)
        self.status("Reading the drawing scale")
        dpi = geom.page_dpi(did, pg, self.root)
        pt = self.page_text(did, pg)
        out = []
        for c in geom.scale_candidates(pt, dpi)[:8]:
            ref = self.reg("text", did, pg, c["bbox_px"], c["text"])
            out.append(f'{ref} printed scale "{c["text"]}" = ratio 1:{_fmt(c["ratio"])}' + (f"; {c['m_per_px']} m per pixel at {dpi:.0f} dpi" if c["m_per_px"] else ""))
        ps = geom.planmap_scale(did, pg, self.root)
        from pipeline.scale_regions import region_map
        from engine.scales import scale_description
        pm = region_map(Path(self.root) / did, pg)
        from engine.scales import scale_anchors
        for label in scale_anchors(pm.get("printed_scale_labels", [])):
            ref = self.reg("text", did, pg, label["bbox"], label["quote"])
            out.append(f"{ref} printed scale 1:{_fmt(label['ratio'])}; physical calibration and view assignment must be checked separately")
        for region in pm.get("regions", []):
            sc = region.get("scale") or {}
            ref = self.reg("region", did, pg, region["bbox"], sc.get("evidence"))
            out.append(f"{ref} {scale_description(sc, region.get('title'))}; {sc.get('evidence', '')}")
        if ps:
            out.append(f'plan map scale: {ps["m_per_px"]} m per pixel (method {ps.get("method")}, confidence {ps.get("confidence")})')
        if dpi:
            out.append(f"page image dpi {dpi:.0f}")
        return "\n".join(out) or "no printed scale found; the page has no scale text and no plan-map scale."

    def t_measure(self, doc: str = "", page=1, points=None, closed: bool = False, m_per_px: float | None = None, ratio: float | None = None) -> str:
        did = self.resolve(doc)
        if not did:
            return f"error: unknown doc '{doc}'"
        pg = int(page or 1)
        pts = [[float(p[0]), float(p[1])] for p in (points or [])]
        if len(pts) < 2:
            return "error: need at least 2 points [[x,y],...] in page pixels"
        self.status("Measuring")
        mpp = float(m_per_px) if m_per_px else None
        if mpp is None and ratio:
            dpi = geom.page_dpi(did, pg, self.root)
            mpp = float(ratio) * 0.0254 / dpi if dpi else None
        src = "given"
        from pipeline.scale_regions import region_map
        from engine.scales import points_scale, positive, scale_description
        pm = region_map(Path(self.root) / did, pg)
        if pm.get("regions"):
            sc, region = points_scale(pm, pts)
            local_mpp = positive(sc.get("m_per_px"))
            if not local_mpp:
                return "error: measurement crosses views or this view has no verified scale; " + str(sc.get("evidence") or "")
            if mpp and abs(mpp / local_mpp - 1) > .01:
                return "error: supplied scale disagrees with the scale for this view"
            mpp, src = local_mpp, scale_description(sc, (region or {}).get("title"))
        if mpp is None:
            ps = geom.planmap_scale(did, pg, self.root)
            if ps and (ps.get("confidence") or 0) >= 0.5:
                mpp, src = float(ps["m_per_px"]), f"plan map scale ({ps.get('method')}, conf {ps.get('confidence')})"
        if mpp is None:
            return "error: no scale known: call scale first, then pass ratio or m_per_px"
        length = geom.polyline_length(pts, closed) * mpp
        res = f"length {length:.3f} m"
        if closed and len(pts) >= 3:
            res += f", area {geom.polygon_area(pts) * mpp * mpp:.2f} m2"
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        ref = self.reg("region", did, pg, [min(xs), min(ys), max(xs), max(ys)], f"measured {res}")
        return f"{ref} {res} (scale {mpp:.6f} m/px from {src})"

    def t_planmap(self, doc: str = "", kind: str = "", name: str = "", page=None, limit: int = 40) -> str:
        did = self.resolve(doc)
        if not did:
            return f"error: unknown doc '{doc}'"
        d = self.doc(did, "planmap")
        if d is None or d.mode != "planmap":
            return "this document has no plan map."
        self.status(f"Checking {kind or 'items'} in {d.title or did}")
        items = [i for i in d.items if (not kind or i.kind == kind) and (not page or i.page == int(page))]
        if name:
            q = norm(name)
            items = [i for i in items if q in norm(" ".join(str(x) for x in (i.label, i.props.get("room_type"), i.props.get("name"), i.item_id) if x))]
        tot = {k: sum(float(i.q[k]) for i in items if i.q.get(k) is not None) for k in ("area_m2", "length_m", "width_m")}
        n_with = {k: sum(1 for i in items if i.q.get(k) is not None) for k in tot}
        out = [f"{len(items)} item(s)" + "".join(f"; sum {k} = {_fmt(v)} over {n_with[k]} item(s)" for k, v in tot.items() if n_with[k])]
        from pipeline.sheet_views import count_views
        for region in count_views(d, items, kind or None, int(page) if page else None):
            ref = self.reg("region", did, region['page'], region['bbox'], region.get('title'))
            out.append(f"{ref} Plan view {region.get('title') or 'unnamed'} (p{region['page']}): {region['count']} matching items")
        if d.meta.get('view_regions'):
            out.append('Only plan views are counted. Elevations, sections and unresolved regions are excluded; empty detections do not prove that no elements exist.')
        sc = d.scale or {}
        if sc:
            out.append(f"scale confidence {sc.get('confidence')} ({sc.get('method')})")
        for i in items[:int(limit)]:
            if not i.bbox_px:
                continue
            bits = [i.kind, f'"{i.label}"' if i.label else None, i.props.get("room_type"), *(f"{k}={_fmt(v)}" for k, v in i.q.items())]
            ref = self.reg("region", did, i.page, i.bbox_px, " ".join(str(b) for b in bits if b), item_ids=[i.item_id])
            out.append(f"{ref} p{i.page} {i.item_id}: " + " ".join(str(b) for b in bits if b))
        if len(items) > int(limit):
            out.append(f"[{len(items) - int(limit)} more not listed; totals above cover all]")
        return "\n".join(out)

    def t_ifc(self, doc: str = "", kind: str = "", ifc_class: str = "", storey: str = "", name: str = "", external: bool | None = None,
              limit: int = 25) -> str:
        did = self.resolve(doc)
        if not did:
            return f"error: unknown doc '{doc}'"
        d = self.doc(did)
        if d is None or d.mode != "ifc":
            return "this document is not an IFC model."
        self.status("Querying the model")
        items = [i for i in d.items if (not kind or i.kind == kind) and (not ifc_class or str(i.props.get("ifc_class") or "").casefold() == ifc_class.casefold())
                 and (not storey or norm(storey) in norm(i.storey or ""))]
        if external is not None:
            items = [i for i in items if bool(i.props.get("is_external")) == bool(external)]
        if name:
            q = norm(name)
            items = [i for i in items if q in norm(" ".join(str(x) for x in (i.name, i.type_name, i.props.get("long_name")) if x))]
        keys = ("length_m", "area_m2", "net_floor_area_m2", "volume_m3", "width_m", "height_m")
        tot = {k: sum(float(i.q[k]) for i in items if i.q.get(k) is not None) for k in keys}
        have = {k: sum(1 for i in items if i.q.get(k) is not None) for k in keys}
        by_storey: dict[str, int] = {}
        for i in items:
            by_storey[i.storey or "?"] = by_storey.get(i.storey or "?", 0) + 1
        out = [f"{len(items)} element(s) matched" + "".join(f"; sum {k} = {_fmt(v)} over {have[k]}" for k, v in tot.items() if have[k])]
        if by_storey and len(by_storey) > 1:
            out.append("per storey: " + ", ".join(f"{k}: {v}" for k, v in sorted(by_storey.items())))
        # Keep the full set behind the count; the observation's sample below
        # limits planner tokens, while citations can still verify every match.
        ids = [i.item_id for i in items]
        nouns = {"door": "doors", "window": "windows", "room": "rooms", "wall": "walls", "pipe": "pipes",
                 "duct": "ducts", "column": "columns", "stairs": "stairs", "toilet": "toilets", "sink": "sinks"}
        noun = nouns.get(kind, "model elements")
        scope = (f" on {storey}" if storey else "") + (f' named "{name}"' if name else "")
        if external is not None:
            scope += " (external)" if external else " (not marked external)"
        quote = f"{len(items)} matching {noun}{scope} in {d.title or 'the selected model'}"
        ref = self.reg("element", did, 1, None, quote, item_ids=ids)
        out.insert(0, f"{ref} (cites all {len(ids)} matching elements)")
        for i in items[:int(limit)]:
            q = " ".join(f"{k}={_fmt(v)}" for k, v in i.q.items() if k in keys)
            pr = " ".join(f"{k}={v}" for k, v in i.props.items() if k in ("is_external", "fire_rating", "material") and v not in (None, ""))
            out.append(f"- {i.item_id} {i.name or i.type_name or ''} [{i.props.get('ifc_class')}] {i.storey or ''} {q} {pr}".strip())
        if len(items) > int(limit):
            out.append(f"[{len(items) - int(limit)} more; totals cover all]")
        return "\n".join(out)

    def t_compute(self, expr: str) -> str:
        v = safe_eval(str(expr))
        return f"{expr} = {_fmt(round(v, 6))}"


# ---------------------------------------------------------------------------------------------- helpers
def geom_lines(pt: PageText, bbox=None) -> list[list[dict]]:
    """Phrases grouped into visual rows (same baseline), reading order, optionally limited to a bbox."""
    from engine.reader.text import lines_in
    segs = lines_in(pt, bbox, max_chars=40000)
    rows: list[list[dict]] = []
    for s in sorted(segs, key=lambda s: ((s["bbox_px"][1] + s["bbox_px"][3]) / 2, s["bbox_px"][0])):
        cy = (s["bbox_px"][1] + s["bbox_px"][3]) / 2
        h = max(s["bbox_px"][3] - s["bbox_px"][1], 1.0)
        if rows:
            lcy = sum((x["bbox_px"][1] + x["bbox_px"][3]) / 2 for x in rows[-1]) / len(rows[-1])
            if abs(cy - lcy) <= 0.5 * h:
                rows[-1].append(s)
                continue
        rows.append([s])
    return [sorted(r, key=lambda s: s["bbox_px"][0]) for r in rows]


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow,
        ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Mod: operator.mod}
_FUNCS = {"sum": lambda *a: sum(a[0]) if len(a) == 1 and isinstance(a[0], (list, tuple)) else sum(a), "round": round, "min": min, "max": max, "abs": abs}


def safe_eval(expr: str) -> float:
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            if isinstance(n.op, ast.Pow) and abs(ev(n.right)) > 8:
                raise ValueError("exponent too large")
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        if isinstance(n, (ast.List, ast.Tuple)):
            return [ev(x) for x in n.elts]
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and not n.keywords:
            return _FUNCS[n.func.id](*[ev(a) for a in n.args])
        raise ValueError("unsupported expression")
    clean = re.sub(r"(?<=\d),(?=\d{3}\b)", "", expr)
    return float(ev(ast.parse(clean, mode="eval")))
