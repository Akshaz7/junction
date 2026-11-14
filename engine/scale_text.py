"""E-57: a real scale for a raster plan, from what is printed on it.

Order of trust (each returns a scale dict like the plan map's `scale`):
  scalebar    "0  5  10 m" tick labels on one line: metres between the first and last label / pixels between them.
  ratio+dpi   "1:200" in the title block and a known image dpi (PDF pages): 25.4/dpi mm per pixel x 200.
  ratio+sheet "1:200" and a sheet size ("A2") when the image is the whole sheet (aspect ratio matches the sheet within 6%).
Nothing found, or a candidate more than ~3x away from the door-size prior: None (the caller keeps what it had and says so).
No model is called; OCR words come from the page text or, for a picture, from rapidocr (cached next to the page)."""
from __future__ import annotations

import json
import re
from pathlib import Path

SHEETS = {"A0": (841, 1189), "A1": (594, 841), "A2": (420, 594), "A3": (297, 420), "A4": (210, 297)}
RATIOS = {20, 25, 50, 75, 100, 125, 150, 200, 250, 300, 400, 500, 1000, 1250, 2000}
RATIO_RE = re.compile(r"(?<!\d)1\s*[:/]\s*(\d{2,4})(?!\d)")
NUM_RE = re.compile(r"^\d{1,3}(?:[.,]\d)?$")
UNIT_RE = re.compile(r"^(?:m|meters?|metres?|mtr)$", re.I)
FT_UNIT_RE = re.compile(r"^(?:f(?:ee|oo|ec|ea)?[tl]\.?|feat|'|’|′)$", re.I)
ANCHOR_RE = re.compile(r"^(?:f(?:ee|ec|ea)[tl]|feet|foot|meters?|metres?|metric|scale|graphic)$", re.I)
FT_M = 0.3048
IMP_RE = re.compile(r"(\d+(?:\s?\d)?(?:\s?/\s?\d+)?)\s*(?:\"|”|″|IN\.?)?\s*=\s*(\d+)\s*(?:'|’|′|FT\.?|FEET)\s*-?\s*(\d+)?", re.I)
SHEET_RE = re.compile(r"^(?:sheet|format|size|iso|paper)?[:=]?(A[0-4])$", re.I)


def _cx(b):
    return (b[0] + b[2]) / 2


def _cy(b):
    return (b[1] + b[3]) / 2


def scalebar(words: list[dict]) -> dict | None:
    """Row of numeric labels (0, 5, 10 ...) with a regular step, at least 3 labels or 2 with an 'm' unit. Linear fit must hold within 6%."""
    nums = []
    for w in words:
        t = str(w.get("text") or "").strip()
        if t in ("O", "o"):
            t = "0"
        elif t in ("S", "s"):   # a handwritten 5 on a scale bar; only kept when the whole row fits a line
            t = "5"
        if re.fullmatch(r"\d{1,3}['’′]", t):
            t = t[:-1]
        if NUM_RE.match(t) and w.get("bbox_px"):
            nums.append((float(t.replace(",", ".")), w["bbox_px"]))
    best = None
    for v0, b0 in nums:
        h = max(b0[3] - b0[1], 1.0)
        cand_row = sorted(((v, b) for v, b in nums if abs(_cy(b) - _cy(b0)) <= 0.6 * h and b[3] - b[1] <= 2.2 * h), key=lambda t: _cx(t[1]))
        row = []
        for v, b in cand_row:   # the same label read twice (tiled pass plus crop) counts once
            if row and row[-1][0] == v and abs(_cx(b) - _cx(row[-1][1])) < 3 * h:
                continue
            row.append((v, b))
        vals = [v for v, _ in row]
        if len(row) < 2 or vals[0] != 0 or vals != sorted(vals) or len(set(vals)) != len(vals):
            continue
        steps = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
        if max(steps) - min(steps) > 1e-6:
            continue
        x0, x1 = _cx(row[0][1]), _cx(row[-1][1])
        if x1 - x0 < 30:
            continue
        mpp = (vals[-1] - vals[0]) / (x1 - x0)
        # every label must sit on the line through the first and last
        if any(abs(_cx(b) - (x0 + (v - vals[0]) / mpp)) > 0.06 * (x1 - x0) for v, b in row):
            continue
        near = [str(w.get("text") or "").strip() for w in words if w.get("bbox_px") and abs(_cy(w["bbox_px"]) - _cy(b0)) <= 1.2 * h
                and -0.2 * (x1 - x0) <= _cx(w["bbox_px"]) - x1 <= 1.0 * (x1 - x0) + 80]
        feet = any(FT_UNIT_RE.match(t) or re.fullmatch(r"\d+['’′]", t) for t in near)
        near_unit = feet or any(UNIT_RE.match(t) for t in near)
        if near_unit:
            if feet:
                mpp *= FT_M
            unit = "ft" if feet else "m"
            cand = {"m_per_px": mpp, "method": "scalebar", "confidence": 0.85 if near_unit else 0.7,
                    "evidence": f"scale bar read from the drawing: labels {', '.join(f'{v:g}' for v in vals)} {unit} span {x1 - x0:.0f} px"}
            cand["derivation"] = {
                "formula": "scale = (last label − first label) × metres per printed unit / (last label centre − first label centre)",
                "inputs": [
                    {"name": f"scale bar label {k + 1}", "value": v, "unit": unit,
                     "source": {"bbox": b, "text": str(v), "anchor_px": [_cx(b), _cy(b)]}}
                    for k, (v, b) in enumerate(row)
                ] + [{"name": "label centre span", "value": x1 - x0, "unit": "px",
                      "source": {"bbox": [min(b[0] for _, b in row), min(b[1] for _, b in row), max(b[2] for _, b in row), max(b[3] for _, b in row)],
                                 "endpoints_px": [[x0, _cy(row[0][1])], [x1, _cy(row[-1][1])]]}},
                     {"name": "metres per printed unit", "value": FT_M if feet else 1.0, "unit": "m/" + unit,
                      "source": {"definition": "1 international foot = 0.3048 m" if feet else "metres printed on the bar"}}],
                "note": "Bar endpoints inferred from the centres of its numeric labels; tick/label alignment and OCR error are not bounded.",
            }
            if best is None or len(row) > best[0]:
                best = (len(row), cand)
    return best[1] if best else None


def imperial_ratio(words: list[dict]) -> float | None:
    """3/16"=1'-0", 1/8"=1'-0", 1"=20' -> N of 1:N (without rounding the scale)."""
    texts = [str(w.get("text") or "") for w in words]
    for i in range(len(texts)):
        for n in (1, 2, 3, 4, 5):
            m = IMP_RE.search(" ".join(texts[i:i + n]))
            if m:
                try:
                    a = m.group(1).strip()
                    fraction = re.fullmatch(r"(?:(\d+)\s+)?(\d+)\s*/\s*(\d+)", a)
                    inch = (float(fraction[1] or 0) + float(fraction[2]) / float(fraction[3])) if fraction else float(a)
                except (ValueError, ZeroDivisionError):
                    continue
                feet = int(m.group(2)) + int(m.group(3) or 0) / 12
                if inch > 0 and 0 < feet <= 500:
                    r = feet * 12 / inch
                    if 4 <= r <= 5000:
                        return r
    return None


def ratio_and_sheet(words: list[dict]) -> tuple[int | None, str | None]:
    texts = [str(w.get("text") or "") for w in words]
    ratio = None
    for i in range(len(texts)):
        for n in (1, 2, 3):
            m = RATIO_RE.search("".join(texts[i:i + n]))
            if m and int(m.group(1)) in RATIOS:
                ratio = int(m.group(1))
                break
        if ratio:
            break
    if ratio is None:
        ratio = imperial_ratio(words)
    sheet = None
    for t in texts:
        m = SHEET_RE.match(t.strip())
        if m:
            sheet = m.group(1).upper()
            break
    return ratio, sheet


def from_ratio(ratio: int | None, sheet: str | None, W: int, H: int, dpi: float | None) -> dict | None:
    if not ratio or W <= 0 or H <= 0:
        return None
    from engine.scale_proof import positive
    if positive(dpi):
        mpp = 25.4 / dpi * ratio / 1000
        return {"m_per_px": mpp, "method": "ratio-dpi", "confidence": 0.8,
                "evidence": f"title block scale 1:{ratio} at {dpi:.0f} dpi"}
    if sheet in SHEETS:
        short, long_ = SHEETS[sheet]
        if abs(max(W, H) / max(1, min(W, H)) - long_ / short) / (long_ / short) <= 0.06:
            mpp = long_ / max(W, H) * ratio / 1000
            return {"m_per_px": mpp, "method": "ratio-sheet", "confidence": 0.7,
                    "evidence": f"title block scale 1:{ratio} on a {sheet} sheet ({short} x {long_} mm) spanning the image"}
    return None


def detect(words: list[dict], W: int, H: int, dpi: float | None = None, prior: float | None = None, dpi_source=None) -> dict | None:
    ratio, sheet = ratio_and_sheet(words)
    bar = scalebar(words)
    readings = evidenced_candidates(words, W, H, dpi, dpi_source)
    printed = [r for r in readings if r['method'].startswith('ratio-')]
    # Detail drawings can carry different scales on the same sheet. Without a
    # region association there is no single safe ratio to apply to the page.
    ratio_values = {round(r['m_per_px'], 12) for r in printed}
    cand = from_ratio(ratio, sheet, W, H, dpi) if len(ratio_values) == 1 else None
    if cand and round(cand["m_per_px"], 12) not in ratio_values:
        cand = None
    if printed and cand is None and len(ratio_values) == 1:
        r = printed[0]
        cand = {'m_per_px': r['m_per_px'], 'method': r['method'], 'confidence': .8,
                'evidence': f"printed scale {r['inputs'][0]['source'].get('text', '')}"}
    pick = bar or cand
    if pick is None:
        return None
    if bar and cand and abs(bar["m_per_px"] / cand["m_per_px"] - 1) > 0.25:
        pick = {**bar, "confidence": 0.6, "evidence": bar["evidence"] + f"; the title block says 1:{ratio}, which disagrees by "
                f"{abs(bar['m_per_px'] / cand['m_per_px'] - 1) * 100:.0f}%, so the printed bar is used"}
    elif bar and cand:   # two independent readings agree: the exact one (printed ratio) carries the number
        pick = {**cand, "confidence": 0.9, "evidence": cand["evidence"] + f"; the printed scale bar agrees ({bar['m_per_px'] / cand['m_per_px'] * 100 - 100:+.1f}%)"}
    if ratio and "1:" not in pick["evidence"] and pick is bar:
        pass
    if prior and not (0.3 < pick["m_per_px"] / prior < 3.5):
        return None     # nowhere near the size of the doors on the drawing: a misread, not a scale
    pick = {**pick, "candidates": evidenced_candidates(words, W, H, dpi, dpi_source),
            "selection_rule": ("Use the printed bar when it differs from the ratio by more than 25%; otherwise use the printed ratio with known DPI or sheet size. "
                               "This is a selection policy, not an accuracy threshold. Reject readings outside 0.3–3.5 times the door-size prior.")}
    return pick


def _page_words(doc_dir: Path, page: int) -> tuple[list[dict], int, int, float | None]:
    from engine.reader.text import load_page_text, ocr_words
    pt = load_page_text(doc_dir.name, page, doc_dir.parent, allow_ocr=False)
    dpi = None
    try:
        dpi = (json.loads((doc_dir / f"text-{page}.json").read_text()) or {}).get("dpi")
    except (OSError, ValueError):
        pass
    words = list(pt.words)
    if pt.source != "pdf-text-layer":
        cache = doc_dir / f"scale-ocr-{page}.json"
        ocr = None
        try:
            ocr = json.loads(cache.read_text())
        except (OSError, ValueError):
            pass
        if ocr is None:
            try:
                ocr = ocr_words(doc_dir / f"page-{page}.png")
            except Exception:  # noqa: BLE001
                ocr = []
            try:
                cache.write_text(json.dumps(ocr))
            except OSError:
                pass
        words += ocr
    # The page may have been uniformly resized after rendering. Keep the
    # original DPI and the explicit factor in the evidence inputs.
    from engine.scale_proof import positive, read_json
    text = read_json(doc_dir / f"text-{page}.json")
    pages = read_json(doc_dir / "pages.json")
    entry = next((p for p in pages.get("pages", []) if p.get("page") == page), {}) if isinstance(pages, dict) else {}
    if not dpi:
        dpi = entry.get("dpi")
    dims = text.get("image") or {} if isinstance(text, dict) and text.get("dpi") else entry
    sx = pt.w / dims["w"] if positive(dims.get("w")) else 1
    sy = pt.h / dims["h"] if positive(dims.get("h")) else 1
    meta = {"file": f"text-{page}.json" if isinstance(text, dict) and text.get("dpi") else "pages.json",
            "raw_dpi": dpi, "resize_factor": sx, "recorded_image": dims, "current_image": {"w": pt.w, "h": pt.h}}
    dpi = float(dpi) * sx if positive(dpi) and abs(sx - sy) <= 1e-6 * max(sx, sy) else None
    return words, pt.w, pt.h, dpi, meta


def _anchor_crops(doc_dir: Path, page: int, words: list[dict]) -> list[dict]:
    """Handwritten or small scale bars are missed by the tiled pass. Re-read a strip left of each 'feet / metres / scale' word at 1x."""
    try:
        import cv2
    except ImportError:
        return []
    from engine.reader.text import ocr_words
    png = doc_dir / f"page-{page}.png"
    im = cv2.imread(str(png))
    if im is None:
        return []
    H, W = im.shape[:2]
    out, seen = [], set()
    for w in words:
        t = str(w.get("text") or "").strip().strip(".:")
        if not (ANCHOR_RE.match(t) and w.get("bbox_px")):
            continue
        b = w["bbox_px"]
        h = max(b[3] - b[1], 10)
        x0, x1 = max(0, int(b[0] - 40 * h)), min(W, int(b[2] + 3 * h))
        y0, y1 = max(0, int(_cy(b) - 4 * h)), min(H, int(_cy(b) + 4 * h))
        key = (x0 // 200, y0 // 200)
        if key in seen or x1 - x0 < 50:
            continue
        seen.add(key)
        tmp = doc_dir / f"_anchor-{page}-{len(seen)}.png"
        try:
            cv2.imwrite(str(tmp), im[y0:y1, x0:x1])
            for o in ocr_words(tmp):
                bb = o["bbox_px"]
                out.append({"text": o["text"], "bbox_px": [bb[0] + x0, bb[1] + y0, bb[2] + x0, bb[3] + y0]})
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
        if len(seen) >= 4:
            break
    return out


def refine_scale(doc_dir: Path, page: int, scale: dict | None) -> dict | None:
    """The better scale for this page, or None when the printed text gives nothing usable (keep `scale`)."""
    if scale and scale.get("method") not in (None, "none", "door-prior"):
        return None   # already a measured scale (dimension, dxf, ifc)
    if not doc_dir.name.startswith("uploads") and not (doc_dir / f"scale-ocr-{page}.json").exists():
        return None   # dataset plans keep their stored scale; OCR only runs for uploads (or where it already ran)
    stamps = tuple(p.stat().st_mtime_ns if p.exists() else 0 for p in
                   (doc_dir / f"page-{page}.png", doc_dir / f"text-{page}.json", doc_dir / f"scale-ocr-{page}.json", doc_dir / "pages.json"))
    key = (str(doc_dir), page, (scale or {}).get("m_per_px"), stamps)
    if key in _memo:
        return _memo[key]
    res = _refine(doc_dir, page, scale)
    _memo[key] = res
    return res


_memo: dict = {}


def _refine(doc_dir: Path, page: int, scale: dict | None) -> dict | None:
    if not (doc_dir / f"page-{page}.png").exists():
        return None
    words, W, H, dpi, dpi_source = _page_words(doc_dir, page)
    if not W:
        return None
    prior = (scale or {}).get("m_per_px")
    res = detect(words, W, H, dpi, prior, dpi_source)
    if res is None or res["method"] not in ("scalebar",) and "agrees" not in res["evidence"]:
        extra = _anchor_crops(doc_dir, page, words)
        if extra:
            have = {(str(w.get("text")), round(_cx(w["bbox_px"]) / 8)) for w in words if w.get("bbox_px")}
            words = words + [e for e in extra if (str(e["text"]), round(_cx(e["bbox_px"]) / 8)) not in have]
            res = detect(words, W, H, dpi, prior, dpi_source) or res
    if res is None:
        res = _rotated_bar(doc_dir, page, W, H, prior)
    return res


def _rotated_bar(doc_dir: Path, page: int, W: int, H: int, prior: float | None) -> dict | None:
    """A bar drawn up a page margin (labels read sideways): OCR the page turned 90 degrees both ways. Only the bar geometry is used, so the rotated frame is fine."""
    try:
        import cv2
        from engine.reader.text import ocr_words
    except ImportError:
        return None
    im = cv2.imread(str(doc_dir / f"page-{page}.png"))
    if im is None:
        return None
    for tag, code in (("90", cv2.ROTATE_90_CLOCKWISE), ("270", cv2.ROTATE_90_COUNTERCLOCKWISE)):
        cache = doc_dir / f"scale-ocr-rot{tag}-{page}.json"
        try:
            ws = json.loads(cache.read_text())
        except (OSError, ValueError):
            tmp = doc_dir / f"_rot{tag}-{page}.png"
            try:
                cv2.imwrite(str(tmp), cv2.rotate(im, code))
                ws = ocr_words(tmp)
            except Exception:  # noqa: BLE001
                ws = []
            finally:
                try:
                    tmp.unlink()
                except OSError:
                    pass
            try:
                cache.write_text(json.dumps(ws))
            except OSError:
                pass
        bar = scalebar(ws)
        if bar and not (prior and not (0.3 < bar["m_per_px"] / prior < 3.5)):
            bar["evidence"] += f" (bar printed sideways, read with the page turned {tag} degrees)"
            # Map every evidence coordinate back to the original page frame.
            def unrotate(x, y, tag=tag):
                return [y, H - x] if tag == "90" else [W - y, x]
            for inp in bar.get("derivation", {}).get("inputs", []):
                src = inp.get("source", {})
                if src.get("bbox"):
                    x0, y0, x1, y1 = src["bbox"]
                    points = [unrotate(x, y) for x in (x0, x1) for y in (y0, y1)]
                    src["bbox"] = [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]
                if src.get("endpoints_px"):
                    src["endpoints_px"] = [unrotate(*p) for p in src["endpoints_px"]]
                if src.get("anchor_px"):
                    src["anchor_px"] = unrotate(*src["anchor_px"])
            return bar
    return None


def _px_area(it) -> tuple[float | None, str]:
    a = it.props.get("area_px")
    if a:
        return float(a), "pixels"
    pg = it.polygon_px
    if pg and len(pg) >= 3:
        return abs(sum(pg[k][0] * pg[(k + 1) % len(pg)][1] - pg[(k + 1) % len(pg)][0] * pg[k][1] for k in range(len(pg)))) / 2, "outline"
    b = it.bbox_px
    return ((b[2] - b[0]) * (b[3] - b[1]), "box") if b else (None, "")


def rescale_items(items, old_mpp: float | None, new_mpp: float) -> None:
    """Items carry m / m2 derived from pixels x the old scale; redo them at the new one (printed label areas stay).
    Rooms with no area yet (a plan read by a vision model gives boxes only) get one from their outline, else their box,
    and say which in props.area_basis."""
    k = new_mpp / old_mpp if old_mpp else None
    for it in items:
        q = it.q
        if k and "area_m2" in q and it.props.get("area_m2_label") is None:
            q["area_m2"] = round(q["area_m2"] * k * k, 2)
        if k:
            for key in ("width_m", "height_m", "length_m"):
                if q.get(key) is not None:
                    q[key] = round(q[key] * k, 3)
        if it.kind == "room" and "area_m2" not in q:
            a, basis = _px_area(it)
            if a:
                q["area_m2"] = round(a * new_mpp * new_mpp, 2)
                it.props["area_basis"] = basis


def evidenced_candidates(words, W, H, dpi=None, dpi_source=None):
    """All usable printed-scale readings with their exact boxes and unit conversions."""
    from engine.scale_proof import candidate, operand, positive, valid_box
    words = [w for w in words if valid_box(w.get("bbox_px"))]
    out = []
    b = scalebar(words)
    if b:
        out.append({"method": b["method"], "m_per_px": b["m_per_px"], **b["derivation"]})
    # Join adjacent words only on the same printed line. Never join separate
    # detail drawings into a fictitious title-block ratio.
    seen = set()
    for i, w in enumerate(words):
        group = [w]
        for other in words[i + 1:i + 5]:
            prev, bb = group[-1]["bbox_px"], other["bbox_px"]
            h = max(prev[3] - prev[1], bb[3] - bb[1])
            if abs(_cy(prev) - _cy(bb)) > h * .6 or bb[0] < prev[0] or bb[0] - prev[2] > 3 * h:
                break
            group.append(other)
        for n in range(1, len(group) + 1):
            ws = group[:n]
            text = " ".join(str(x.get("text") or "") for x in ws)
            m = RATIO_RE.search(text)
            ratio = int(m[1]) if m and positive(m[1]) else imperial_ratio(ws)
            if not ratio:
                continue
            box = [min(x["bbox_px"][0] for x in ws), min(x["bbox_px"][1] for x in ws),
                   max(x["bbox_px"][2] for x in ws), max(x["bbox_px"][3] for x in ws)]
            key = (ratio, tuple(w["bbox_px"]))
            if key in seen:
                break
            seen.add(key)
            src = {**ws[0].get("_source", {}), "bbox": box, "text": text}
            if m is None:
                src["interpretation"] = "ratio = (printed feet × 12 + printed inches) / printed paper inches; fractions and mixed fractions evaluated exactly before division"
            inputs = [operand("printed ratio denominator", ratio, "ratio", src)]
            if positive(dpi):
                resize = (dpi_source or {}).get("resize_factor", 1)
                raw_dpi = (dpi_source or {}).get("raw_dpi") or float(dpi)
                inputs += [operand("page render resolution", float(raw_dpi), "px/in", dpi_source or {"metadata": "page render DPI"}),
                           operand("metres per inch", .0254, "m/in", {"definition": "1 international inch = 0.0254 m"})]
                if resize != 1:
                    inputs.append(operand("uniform image resizing", resize, "current px/render px", dpi_source))
                out.append(candidate("ratio-dpi", ratio * .0254 / float(dpi), "scale = printed ratio × 0.0254 m/in / (page render DPI × uniform image resizing)", inputs,
                                     "Assumes the raster retains the recorded resolution and has not been resized or distorted."))
            else:
                for sw in words:
                    sm = SHEET_RE.match(str(sw.get("text", "")).strip())
                    if not sm:
                        continue
                    sheet = sm[1].upper()
                    c = from_ratio(ratio, sheet, W, H, None) if W and H else None
                    if not c:
                        continue
                    short, long_ = SHEETS[sheet]
                    out.append(candidate("ratio-sheet", c["m_per_px"], "scale = printed ratio × long paper side in mm × 0.001 m/mm / long image side in pixels",
                                         inputs + [operand("paper long side", long_, "mm", {**sw.get("_source", {}), "bbox": sw["bbox_px"], "text": str(sw.get("text")), "definition": f"ISO 216 {sheet}: {short} × {long_} mm"}),
                                                   operand("metres per millimetre", .001, "m/mm", {"definition": "1 mm = 0.001 m"}),
                                                   operand("long image side", max(W, H), "px", {"file": "planmap-page.json", "pointer": "/image"})],
                                         "Assumes an uncropped full sheet; aspect ratio alone does not establish this. No physical error bound is available."))
            break
    return out
