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
        if NUM_RE.match(t) and w.get("bbox_px"):
            nums.append((float(t.replace(",", ".")), w["bbox_px"]))
    best = None
    for v0, b0 in nums:
        h = max(b0[3] - b0[1], 1.0)
        row = sorted({(v, round(_cx(b), 1)): (v, b) for v, b in nums if abs(_cy(b) - _cy(b0)) <= 0.6 * h and b[3] - b[1] <= 2.2 * h}.values(), key=lambda t: _cx(t[1]))
        vals = [v for v, _ in row]
        if len(row) < 3 or vals != sorted(vals) or len(set(vals)) != len(vals) or vals[0] != 0:
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
        near_unit = any(UNIT_RE.match(str(w.get("text") or "").strip()) and abs(_cy(w["bbox_px"]) - _cy(b0)) <= 1.2 * h
                        and 0 <= _cx(w["bbox_px"]) - x1 <= 0.5 * (x1 - x0) + 60 for w in words if w.get("bbox_px"))
        if near_unit or len(row) >= 4:
            cand = {"m_per_px": mpp, "method": "scalebar", "confidence": 0.85 if near_unit else 0.7,
                    "evidence": f"scale bar read from the drawing: labels {', '.join(f'{v:g}' for v in vals)} m span {x1 - x0:.0f} px"}
            if best is None or len(row) > best[0]:
                best = (len(row), cand)
    return best[1] if best else None


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
    sheet = None
    for t in texts:
        m = SHEET_RE.match(t.strip())
        if m:
            sheet = m.group(1).upper()
            break
    return ratio, sheet


def from_ratio(ratio: int | None, sheet: str | None, W: int, H: int, dpi: float | None) -> dict | None:
    if not ratio:
        return None
    if dpi:
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


def detect(words: list[dict], W: int, H: int, dpi: float | None = None, prior: float | None = None) -> dict | None:
    ratio, sheet = ratio_and_sheet(words)
    bar = scalebar(words)
    cand = from_ratio(ratio, sheet, W, H, dpi)
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
    return words, pt.w, pt.h, dpi


def refine_scale(doc_dir: Path, page: int, scale: dict | None) -> dict | None:
    """The better scale for this page, or None when the printed text gives nothing usable (keep `scale`)."""
    if scale and scale.get("method") not in (None, "none", "door-prior"):
        return None   # already a measured scale (dimension, dxf, ifc)
    if not doc_dir.name.startswith("uploads") and not (doc_dir / f"scale-ocr-{page}.json").exists():
        return None   # dataset plans keep their stored scale; OCR only runs for uploads (or where it already ran)
    key = (str(doc_dir), page, (scale or {}).get("m_per_px"))
    if key in _memo:
        return _memo[key]
    res = _refine(doc_dir, page, scale)
    _memo[key] = res
    return res


_memo: dict = {}


def _refine(doc_dir: Path, page: int, scale: dict | None) -> dict | None:
    if not (doc_dir / f"page-{page}.png").exists():
        return None
    words, W, H, dpi = _page_words(doc_dir, page)
    if not W:
        return None
    return detect(words, W, H, dpi, (scale or {}).get("m_per_px"))


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
