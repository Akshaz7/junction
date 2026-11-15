"""Ingest one uploaded document: pages, plan map / scene, extrusion, USDZ (S-04).

Run as `python -m server.ingest_job <doc_id>` from the repo root (the API starts it as a subprocess so
heavy imports and memory stay out of the server). Writes artifacts/<doc_id>/ingest.json with
{"status": "running|ready|partial|failed", "stages": [...], "detail": "..."}.
Two modes: full (local: torch segmenter/detector) and vlm (deploy image: call("read_drawing") plan map; INGEST_MODE=vlm|full forces one).
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO), str(REPO / "vision")]


def _art() -> Path:
    from server import config
    return config.artifacts_dir()


class Status:
    def __init__(self, path: Path):
        self.path, self.stages, self.mode, self.cost = path, [], None, None
        self.started_at, self.step = time.time(), "starting"
        self.readable = False  # page images and text exist: the document can be viewed and questioned
        if path.is_file():
            try:
                self.started_at = json.loads(path.read_text()).get("started_at", self.started_at)
            except ValueError:
                pass
        self.write("running")

    def write(self, status, detail=""):
        state = {"status": status, "stages": self.stages, "detail": detail, "mode": self.mode,
                 "started_at": self.started_at, "step": self.step, "readable": self.readable or status == "ready",
                 "progress": 1 if status == "ready" else len(self.stages) / (len(self.stages) + 1),
                                         "cost_usd": round(self.cost["usd"], 5) if self.cost else None,
                 "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        if status == "failed":
            state["reason"] = detail or "Ingestion failed. Please upload the file again."
        tmp = self.path.with_suffix(".job.tmp")
        tmp.write_text(json.dumps(state, indent=1))
        tmp.replace(self.path)

    def stage(self, name, fn):
        t = time.time()
        self.step = name
        self.write("running")
        try:
            fn()
            self.stages.append({"stage": name, "ok": True, "s": round(time.time() - t, 1),
                                "peak_process_rss_mib": _peak_rss_mib()})
            self.write("running")
            return True
        except Exception as e:  # noqa: BLE001
            error = str(e)[:300] or type(e).__name__
            if name == "ifc_scene":
                error = ("This IFC could not be read or converted. Export it again as IFC, or split the model into smaller files. "
                         + error)
            self.stages.append({"stage": name, "ok": False, "error": error})
            self.write("running")
            return False


def _peak_rss_mib():
    """Single ingest process high-water RSS, for upload diagnostics."""
    import resource
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 ** 2 if sys.platform == "darwin" else 1024), 1)


def _normalise_raster(doc_id: str, art: Path):
    """vision.build_planmaps reads doc.json files['png']: make sure the upload is a PNG."""
    d = json.loads((art / doc_id / "doc.json").read_text())
    rel = next(iter(d["files"].values()))
    src = REPO / rel
    from pipeline.pages import MAX_SIDE
    from pipeline.raster_input import read_raster
    # Never overwrite an uploaded source (including a PNG). Readers, page images
    # and their evidence boxes all use this single normalised coordinate system.
    dst = art / doc_id / "normalised.png"
    with read_raster(src, MAX_SIDE) as img:
        img.save(dst, **({"dpi": img.info["dpi"]} if img.info.get("dpi") else {}))
    d.setdefault("original_files", dict(d["files"]))
    target = str(dst.relative_to(REPO)) if dst.is_relative_to(REPO) else str(dst)
    d["files"] = {"png": target}
    (art / doc_id / "doc.json").write_text(json.dumps(d, indent=1))


def _has_vision() -> bool:
    """Local full pipeline needs torch + opencv + weights; the deploy image has none of them."""
    import importlib.util as u
    return all(u.find_spec(m) for m in ("torch", "cv2")) and (REPO / "weights").is_dir()


def light_mode() -> bool:
    m = os.environ.get("INGEST_MODE", "")
    return m == "vlm" or (m != "full" and not _has_vision())


def build_text_json(doc_id: str, ddir: Path):
    """artifacts/<doc>/text.json: per page the text layer as words, lines and plain text, boxes in page-image pixels
    (CONTRACT 5.2). Source is the PDF text layer (text-<n>.json from pipeline.pages)."""
    pages = []
    for f in sorted(ddir.glob("text-[0-9]*.json"), key=lambda p: int(p.stem.split("-")[1])):
        t = json.loads(f.read_text())
        words = t.get("words") or []
        rows = []  # reading-order lines: cluster words by vertical centre
        for w in sorted(words, key=lambda w: ((w["bbox_px"][1] + w["bbox_px"][3]) / 2, w["bbox_px"][0])):
            b = w["bbox_px"]
            cy, h = (b[1] + b[3]) / 2, max(1.0, b[3] - b[1])
            if rows and abs(rows[-1]["cy"] - cy) <= 0.6 * h:
                rows[-1]["w"].append(w)
            else:
                rows.append({"cy": cy, "w": [w]})
        lines = []
        for r in rows:
            ws = sorted(r["w"], key=lambda w: w["bbox_px"][0])
            lines.append({"text": " ".join(w["text"] for w in ws),
                          "bbox_px": [min(w["bbox_px"][0] for w in ws), min(w["bbox_px"][1] for w in ws),
                                      max(w["bbox_px"][2] for w in ws), max(w["bbox_px"][3] for w in ws)]})
        pages.append({"page": t["page"], "image": t["image"], "source": t.get("source", "pdf-text-layer"),
                      "text": "\n".join(l["text"] for l in lines), "lines": lines, "words": words})
    if pages:
        (ddir / "text.json").write_text(json.dumps({"doc_id": doc_id, "pages": pages}, ensure_ascii=False))


def _is_text_page(ddir: Path, n: int, n_words: int) -> bool:
    """A specification/text page: many words AND words cover a large share of the page. A drawing sheet can carry
    hundreds of words too, but they are scattered (small covered share)."""
    if n_words < int(os.environ.get("TEXT_PAGE_WORDS", "400")):
        return False
    t = json.loads((ddir / f"text-{n}.json").read_text())
    area = sum(max(0, w["bbox_px"][2] - w["bbox_px"][0]) * max(0, w["bbox_px"][3] - w["bbox_px"][1]) for w in t["words"])
    return area / max(1, t["image"]["w"] * t["image"]["h"]) > float(os.environ.get("TEXT_PAGE_COVER", "0.12"))


def _vlm_pages(doc_id: str, ddir: Path, st: "Status", cost: dict):
    """VLM plan map for every page that looks like a drawing (few words in the text layer), at most MAX_VLM_PAGES.
    Writes planmap-<n>.json. Returns the list of plan pages."""
    from concurrent.futures import ThreadPoolExecutor
    from server import vlm_planmap
    meta = json.loads((ddir / "pages.json").read_text())
    cand = [p["page"] for p in meta["pages"] if not _is_text_page(ddir, p["page"], p.get("words") or 0)]
    cand = cand[:int(os.environ.get("MAX_VLM_PAGES", "4"))]
    found, notes = [], []

    def one(n):
        r = vlm_planmap.read_page(doc_id, n, ddir / f"page-{n}.png", ddir)
        cost["usd"] += r["cost_usd"]
        cost["model"] = r["model"]
        if r["is_plan"]:
            found.append(n)
            if r.get("words") and not (ddir / f"text-{n}.json").exists():
                W, H = r["planmap"]["image"]["w"], r["planmap"]["image"]["h"]
                (ddir / f"text-{n}.json").write_text(json.dumps(
                    {"doc_id": doc_id, "page": n, "image": {"w": W, "h": H}, "dpi": None, "source": "vlm", "words": r["words"]}))
        return n

    def run_all():
        with ThreadPoolExecutor(max_workers=3) as ex:
            list(ex.map(one, cand))
        build_text_json(doc_id, ddir)  # picks up the room labels the model read on pages with no text layer
    st.stage("planmap_vlm", run_all)
    try:
        drop_empty_rooms(ddir)
        drop_photo_rooms(ddir)
    except Exception as e:  # noqa: BLE001
        print('drop_empty_rooms skipped:', repr(e)[:200], file=sys.stderr)
    return sorted(found)


def _pdf_vector_on() -> bool:
    return os.environ.get("PDF_VECTOR", "1") != "0"


def _dxf_planmap_usable(ddir: Path) -> bool:
    f = ddir / "planmap-1.json"
    if not f.is_file():
        return False
    pm = json.loads(f.read_text())
    n = sum(1 for i in pm["items"] if i["kind"] in ("room", "wall", "door", "window"))
    return n >= 3  # counts remain usable without units; physical sizes remain unknown


MAX_PDF_PLAN_PAGES = 4


def _pdf_vector_pages(doc_id: str, ddir: Path, st: "Status", pdf: Path) -> list[int]:
    """Vector CAD PDF: exact plan maps from the page's drawing operators (pipeline.pdf_planmap), gated per page, at most
    MAX_PDF_PLAN_PAGES plan pages. Returns the plan pages; [] (and no plan-map files left behind) means use the VLM path."""
    from pipeline import pdf_planmap
    meta = json.loads((ddir / "pages.json").read_text())
    cap = int(os.environ.get("MAX_PDF_PLAN_PAGES", str(MAX_PDF_PLAN_PAGES)))
    budget = float(os.environ.get("PDF_VECTOR_BUDGET_S", "90"))
    found, notes = [], []

    def run_all():
        t0 = time.time()
        for p in meta["pages"]:
            n = p["page"]
            if len(found) >= cap or time.time() - t0 > budget:
                break
            try:
                if pdf_planmap.process(doc_id, ddir, pdf, n - 1) is not None:
                    found.append(n)
            except Exception as e:  # noqa: BLE001  one odd page never costs the others
                notes.append(f"p{n}: {e!r}"[:120])
                (ddir / f"planmap-{n}.json").unlink(missing_ok=True)
    ok = st.stage("planmap_pdf_vector", run_all)
    if not ok:  # never fail the upload over the vector reader: the VLM path runs next
        notes.append(st.stages[-1].pop("error", ""))
        st.stages[-1]["ok"] = True
    if notes:
        st.stages[-1]["note"] = "; ".join(notes)[:300]
    if not ok or not found:
        for n in found:
            (ddir / f"planmap-{n}.json").unlink(missing_ok=True)
        return []
    st.stages[-1]["note"] = (st.stages[-1].get("note", "") + f" vector plan pages {found}").strip()
    return found


def _extrude(doc_id: str, ddir: Path, page: int, raster_walls: bool = True):
    from pipeline import extrude
    try:
        from pipeline.scale_regions import annotate_document
        annotate_document(ddir, page)
    except Exception as ex:  # scale detection must never prevent an upload
        print("view scale detection skipped:", type(ex).__name__)
    pm = json.loads((ddir / f"planmap-{page}.json").read_text())
    if not pm["scale"].get("m_per_px"):
        # No readable scale: build the 3D anyway on an assumed one, flagged. The engine refuses implausible areas on guessed scales (E-61).
        pm["scale"] = {"m_per_px": ASSUMED_M_PER_PX, "method": "assumed", "source": "assumed", "confidence": 0.1,
                       "evidence": f"no printed scale, dimension or door found: assumed {ASSUMED_M_PER_PX} m per pixel"}
        (ddir / f"planmap-{page}.json").write_text(json.dumps(pm))
    # Explicit CAD walls already have geometry. Reconstructing their thin preview
    # strokes as raster walls adds spurious surfaces and can exhaust memory.
    cad_walls = any(i["kind"] == "wall" and i.get("source") == "dxf" for i in pm["items"])
    use_raster = raster_walls and not cad_walls
    keep = None
    if not raster_walls:  # vector PDF: a room known only by its label (no outline) gets no label-sized floor slab
        f = ddir / f"planmap-{page}.json"
        keep = f.read_text()
        pm = json.loads(keep)
        pm["items"] = [i for i in pm["items"] if not (i["kind"] == "room" and not i.get("polygon_px"))]
        f.write_text(json.dumps(pm))
    try:
        try:  # falls back to plan-map walls when cv2 or wall fills are missing
            extrude.process(doc_id, ddir, page, raster_walls=use_raster)
        except Exception as ex:  # noqa: BLE001 - a raster-wall surprise must never cost the upload its 3D
            print("raster-wall extrude failed, using plan-map walls:", repr(ex)[:160])
            extrude.process(doc_id, ddir, page)
    finally:
        if keep is not None:  # the chat solvers keep every room, label-only ones included
            (ddir / f"planmap-{page}.json").write_text(keep)


def _pdf_via_ifc_on() -> bool:
    return os.environ.get("PDF_VIA_IFC", "1") != "0"


def _copy_quality(ddir: Path, page: int):
    """Copy the plan map's quality block (pipeline.pdf_quality: score, ci95, summary) into scene.json so the 3D/AR
    clients see it. Best effort: never fails the ingest."""
    try:
        q = json.loads((ddir / f"planmap-{page}.json").read_text()).get("quality")
        sj = ddir / "scene.json"
        if q and sj.is_file():
            sj.write_text(json.dumps({**json.loads(sj.read_text()), "quality": q}, indent=1))
    except Exception as e:  # noqa: BLE001
        print("quality copy skipped:", repr(e)[:200], file=sys.stderr)


def _pdf_via_ifc(doc_id: str, ddir: Path, doc: dict, page: int):
    """Vector PDF plan map -> IFC4 (pipeline.pdf_to_ifc) -> the IFC scene path (ifc_scene: scene.glb, scene.json,
    elements.json), so a PDF looks like an IFC upload in 3D/AR. The page image and planmap-<n>.json stay the PDF's own
    (ifc_plans is not run: it would replace them); plan-map ids are relinked to the IFC GlobalIds. Any failure leaves
    no IFC files behind and raises, so the caller extrudes the plan map instead."""
    from pipeline import ifc_scene, pdf_to_ifc
    f = ddir / f"planmap-{page}.json"
    keep = f.read_text()
    try:
        ifc = pdf_to_ifc.build(json.loads(keep), ddir / "model.ifc", storey_name="Floor 1", doc_id=doc_id)
        ifc_scene.process(Path(ifc), doc, ddir)
        pdf_to_ifc.link_planmap(f, doc_id)
        _copy_quality(ddir, page)
        mark_ifc_from_pdf(ddir, True)
    except Exception:
        f.write_text(keep)
        for name in ("model.ifc", "elements.json", "scene.glb", "scene.json"):
            (ddir / name).unlink(missing_ok=True)
        mark_ifc_from_pdf(ddir, False)
        raise


def mark_ifc_from_pdf(ddir: Path, on: bool):
    """doc.json metadata for a PDF converted through pdf_to_ifc, so it is listed and treated like an IFC upload
    (Data page formats, engine.library IFC listing, mistakes/mep IFC property readers via files['ifc'], the 'file type'
    answer) while kind stays "pdf": the web viewer keeps the 2D PDF page and its planmap-<n>.json for citations.
    Engine IFC mode itself comes from elements.json (engine.solvers.data.load_doc). on=False removes the marks."""
    dj = ddir / "doc.json"
    d = json.loads(dj.read_text())
    formats = [f for f in (d.get("formats") or [d.get("kind") or "pdf"]) if f != "ifc"]
    files = {k: v for k, v in (d.get("files") or {}).items() if k != "ifc"}
    d.pop("ifc_from", None)
    if on and (ddir / "model.ifc").is_file():
        formats.append("ifc")   # after "pdf": the type tag (formats[0]) and kind stay PDF
        m = Path(os.path.abspath(ddir / "model.ifc"))
        try:   # same style as files['pdf']: "artifacts/<doc_id>/model.ifc", relative to the repo
            files["ifc"] = str(m.relative_to(os.path.abspath(REPO)))
        except ValueError:      # artifacts outside the repo (ARTIFACTS_DIR): the readers also try absolute paths
            files["ifc"] = str(m)
        d["ifc_from"] = "pdf"   # derived model (pipeline.pdf_to_ifc), not an uploaded IFC
    d["formats"], d["files"] = formats, files
    dj.write_text(json.dumps(d, indent=1))


ASSUMED_M_PER_PX = 0.02


def _photo_like(gray, box, paper) -> bool:
    """A box over a photograph or tone fill, not line art: a large share of mid-grey pixels (line art is paper plus thin black)."""
    import numpy as np
    x0, y0, x1, y1 = (int(v) for v in box)
    c = gray[max(0, y0):y1, max(0, x0):x1]
    if c.size < 400:
        return False
    return float(((c > 0.25 * paper) & (c < 0.75 * paper)).mean()) > PHOTO_MID_SHARE


PHOTO_MID_SHARE = 0.25


def drop_photo_rooms(ddir: Path) -> int:
    """Drop room boxes that sit over photographs (mid-grey share above PHOTO_MID_SHARE). Needs numpy and the page image."""
    import numpy as np
    from PIL import Image
    n = 0
    for f in ddir.glob("planmap-[0-9]*.json"):
        img = ddir / f"page-{f.stem.split('-')[1]}.png"
        if not img.is_file():
            continue
        gray = np.asarray(Image.open(img).convert("L"), dtype=float)
        paper = float(np.percentile(gray, 60))
        pm = json.loads(f.read_text())
        keep = [i for i in pm["items"] if not (i["kind"] == "room" and _photo_like(gray, i["bbox_px"], paper))]
        if len(keep) != len(pm["items"]):
            n += len(pm["items"]) - len(keep)
            pm["items"] = keep
            f.write_text(json.dumps(pm))
    return n


def drop_empty_rooms(ddir: Path) -> int:
    """Remove room boxes with no label, no room type, and no door/window/fixture inside: they are not rooms (photo, margin, title block)."""
    n = 0
    for f in ddir.glob("planmap-[0-9]*.json"):
        pm = json.loads(f.read_text())
        its = pm["items"]
        inside = [i["bbox_px"] for i in its if i["kind"] in ("door", "window", "toilet", "sink", "shower", "bathtub", "stairs")]

        def has(b):
            return any(b[0] <= (c[0] + c[2]) / 2 <= b[2] and b[1] <= (c[1] + c[3]) / 2 <= b[3] for c in inside)
        keep = [i for i in its if not (i["kind"] == "room" and not (i.get("label") or "").strip()
                                       and (i.get("props", {}).get("room_type") or "other") == "other" and not has(i["bbox_px"]))]
        if len(keep) != len(its):
            n += len(its) - len(keep)
            pm["items"] = keep
            f.write_text(json.dumps(pm))
    return n


def _has_piping(ifc_path: Path) -> bool:
    """Cheap byte scan: does the IFC contain pipe or flow segments?"""
    tail = b""
    with open(ifc_path, "rb") as f:
        while chunk := f.read(8 << 20):
            blob = (tail + chunk).upper()
            if b"IFCPIPESEGMENT(" in blob or b"IFCFLOWSEGMENT(" in blob:
                return True
            tail = chunk[-32:]
    return False


def _piping(doc_id: str, ddir: Path, ifc_path: Path):
    """Plumbing IFC: pipe sizes, lengths and drains into artifacts/<doc>/piping.json (read by the engine's piping intent)."""
    import sys as _sys
    _sys.path.insert(0, str(REPO))
    from vision import piping
    res = piping.extract(doc_id, ifc_path, ddir / "elements.json")
    if not (res["pipes"] or res["drains"]):
        return
    tmp = ddir / "piping.json.tmp"
    tmp.write_text(json.dumps(res))
    tmp.replace(ddir / "piping.json")


def _usdz(doc_id: str, ddir: Path):
    import importlib.util as u
    if not u.find_spec("pxr"):
        return  # AR needs usd-core, which is not in the deploy image: scene.glb still serves the web 3D viewer
    from pipeline import usdz
    usdz.process(doc_id, ddir)


def run(doc_id: str) -> str:
    st = Status(_art() / doc_id / "ingest.json")
    try:
        final = _run(doc_id, st)
    except Exception as e:  # noqa: BLE001
        st.write("failed", f"Ingestion could not complete: {str(e)[:300] or type(e).__name__}")
        return "failed"
    if final in ("ready", "partial"):
        try:  # after the status is final: the slow, more exact text layer replaces the quick one
            refine_text(doc_id, _art() / doc_id)
        except Exception as e:  # noqa: BLE001
            print("text refine skipped:", repr(e)[:200], file=sys.stderr)
    return final


def refine_text(doc_id: str, ddir: Path) -> int:
    """Pages whose text came from pdfium (fast, at ingest) are re-read with pdfminer (slow, exact boxes) once the
    document is already usable. Files are replaced atomically; text.json is rebuilt. Returns pages refined."""
    from pipeline import pages
    doc = json.loads((ddir / "doc.json").read_text())
    rel = (doc.get("files") or {}).get("pdf")
    if not rel:
        return 0
    pdf = REPO / rel
    n = 0
    for f in sorted(ddir.glob("text-[0-9]*.json")):
        t = json.loads(f.read_text())
        if t.get("extractor") != "pdfium":
            continue
        W, H = t["image"]["w"], t["image"]["h"]
        import pypdfium2 as pdfium
        d = pdfium.PdfDocument(str(pdf))
        w_pt, _ = d[t["page"] - 1].get_size()
        d.close()
        s = W / w_pt
        raw, pw, ph = pages.pdf_words(pdf, t["page"] - 1, s, W, H)
        words = []
        for tx, x0, y0, x1, y1 in raw:
            bx = [round(max(0, min(v, lim)), 1) for v, lim in zip((x0 * s, (ph - y1) * s, x1 * s, (ph - y0) * s), (W, H, W, H))]
            words.append({"text": tx, "bbox_px": bx})
        if not words:
            continue
        t.update(words=words, extractor="pdfminer")
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(t, ensure_ascii=False))
        tmp.replace(f)
        n += 1
    if n:
        build_text_json(doc_id, ddir)
    return n


def _run(doc_id: str, st: Status) -> str:
    art = _art()
    ddir = art / doc_id
    doc = json.loads((ddir / "doc.json").read_text())
    kind = doc["kind"]
    light = light_mode()
    st.mode = "vlm" if light else "full"
    cost = {"usd": 0.0, "model": None}
    st.cost = cost
    ok = True
    plan_pages: list[int] = []
    vector = False
    if kind == "ifc":
        ifc_path = REPO / doc["files"]["ifc"]
        cap = float(os.environ.get("INGEST_IFC_MAX_MB", "15" if light else "400"))
        if ifc_path.stat().st_size > cap * 1e6:
            st.write("failed", f"IFC is {ifc_path.stat().st_size / 1e6:.0f} MB; this server converts IFC files up to {cap:.0f} MB. "
                               "The original is stored, but it cannot be viewed or questioned yet. Split the model into smaller IFC files and upload them separately.")
            return "failed"
        from pipeline import ifc_plans, ifc_scene
        ifc = REPO / doc["files"]["ifc"]
        ok = st.stage("ifc_scene", lambda: ifc_scene.process(ifc, doc, ddir))
        if ok:
            st.readable = True
            st.write("running", "The model index and 3D scene are ready. Building drawing previews.")
        ok = ok and st.stage("ifc_plans", lambda: ifc_plans.process(doc_id, art))
        if ok and (ddir / "pages.json").is_file():
            doc["pages"] = len(json.loads((ddir / "pages.json").read_text())["pages"])
            (ddir / "doc.json").write_text(json.dumps(doc, indent=1))
        if ok:
            from engine.xcheck_ifc import ingest_lengths
            st.stage("quantity_checks", lambda: ingest_lengths(ifc, doc_id, ddir))
        ok = ok and st.stage("usdz", lambda: _usdz(doc_id, ddir))
        if ok and _has_piping(ifc):
            def pip():
                try:
                    _piping(doc_id, ddir, ifc)
                except Exception as e:  # noqa: BLE001  optional extra: never fail the ingest over it
                    st.stages[-1]["note"] = f"piping skipped: {e}"[:200]
            st.stage("piping", pip)
    else:
        from pipeline import pages
        if light:
            pages.MAX_SIDE = int(os.environ.get("PAGES_MAX_SIDE", "4096"))  # keep the render inside the container RAM
            pages.FAST_TEXT = os.environ.get("INGEST_FAST_TEXT", "1") != "0"  # pdfium text layer: 0.01 s, pdfminer takes 70 s here
        if kind == "raster":
            if not st.stage("normalise", lambda: _normalise_raster(doc_id, art)):
                st.write("failed", st.stages[-1]["error"])
                return "failed"
            doc = json.loads((ddir / "doc.json").read_text())

        def do_pages():
            _, res = pages.process((REPO, art, doc))
            if not res.startswith("ok"):
                raise RuntimeError(res)
        ok = st.stage("pages", do_pages)
        if ok:
            st.stage("text", lambda: build_text_json(doc_id, ddir))
            st.readable = True  # pages and text are on disk: viewers and questions work while the plan map is read
            st.write("running")
        if ok:
            n_pages = len(json.loads((ddir / "pages.json").read_text())["pages"])
            doc_json = json.loads((ddir / "doc.json").read_text())
            doc_json["pages"] = n_pages
            (ddir / "doc.json").write_text(json.dumps(doc_json, indent=1))
        if ok and kind == "dxf":
            from pipeline import dxf_planmap
            have = st.stage("dxf_planmap", lambda: dxf_planmap.process(doc_id, ddir, REPO / doc["files"]["dxf"]))
            if have and _dxf_planmap_usable(ddir):
                plan_pages = [1]
            else:
                # dxf_planmap only knows the layer names of the Swiss Dwellings set (ROOM_OUTLINE, WALL, DOOR, ...).
                # A DXF with other layer names gives an empty plan map: read the rendered drawing with the VLM instead.
                (ddir / "planmap-1.json").unlink(missing_ok=True)
                if have:
                    st.stages[-1]["note"] = "no rooms/walls/doors/windows on the expected layers: read the render with the VLM"
                plan_pages = _vlm_pages(doc_id, ddir, st, cost)
        elif ok and kind == "raster" and not light:
            def vision():
                r = subprocess.run([sys.executable, str(REPO / "vision" / "build_planmaps.py"), doc_id],
                                   cwd=REPO, capture_output=True, text=True, timeout=900)
                if r.returncode != 0 or not (ddir / "planmap-1.json").exists():
                    raise RuntimeError((r.stdout + r.stderr)[-300:])
            ok = st.stage("planmap", vision)
            plan_pages = [1] if ok else []
        elif ok and kind == "pdf" and _pdf_vector_on():
            try:
                plan_pages = _pdf_vector_pages(doc_id, ddir, st, REPO / doc["files"]["pdf"])
            except Exception as e:  # noqa: BLE001  anything odd: today's path
                print("pdf vector plan map skipped:", repr(e)[:200], file=sys.stderr)
                plan_pages = []
            vector = bool(plan_pages)
            if not plan_pages:
                plan_pages = _vlm_pages(doc_id, ddir, st, cost)
        elif ok and kind in ("raster", "pdf", "svg"):
            plan_pages = _vlm_pages(doc_id, ddir, st, cost)
        elif ok:
            st.write("partial", f"{kind}: page image only, no plan map for this format")
            return "partial"
        if plan_pages:
            if vector:  # walls come from the PDF's own geometry: no raster wall read
                ok = False
                if _pdf_via_ifc_on():
                    ok = st.stage("ifc_from_pdf", lambda: _pdf_via_ifc(doc_id, ddir, doc, plan_pages[0]))
                    if not ok:  # IFC route failed: extrude the plan map directly
                        st.stages[-1].update(ok=True, note="fell back to extrude: " + st.stages[-1].pop("error", "")[:200])
                if not ok:
                    ok = st.stage("extrude", lambda: _extrude(doc_id, ddir, plan_pages[0], raster_walls=False))
                    if ok:
                        _copy_quality(ddir, plan_pages[0])
                if not ok:  # vector plan map would not extrude: today's path (VLM plan map, raster walls)
                    st.stages[-1].update(stage="extrude_pdf_vector", ok=True, note=st.stages[-1].pop("error", "")[:200])
                    for f in ddir.glob("planmap-[0-9]*.json"):
                        f.unlink()
                    plan_pages = _vlm_pages(doc_id, ddir, st, cost)
                    ok = True
                    if plan_pages:
                        ok = st.stage("extrude", lambda: _extrude(doc_id, ddir, plan_pages[0]))
            else:
                ok = st.stage("extrude", lambda: _extrude(doc_id, ddir, plan_pages[0]))
            if plan_pages:
                ok = ok and st.stage("usdz", lambda: _usdz(doc_id, ddir))
        if not plan_pages:
            if ok and all(s["ok"] for s in st.stages):
                st.cost = cost
                st.write("ready", "no drawing pages found: page images and text are indexed, there is no plan map or 3D scene")
                return "ready"
            elif ok:
                ok = False
    ok = ok and all(s["ok"] for s in st.stages)
    # Optional geometry/reader failure must not hide a successfully rendered
    # drawing or an IFC index. The detail still explains exactly what failed.
    usable = st.readable or (ddir / "elements.json").is_file()
    final = "ready" if ok else ("partial" if usable else "failed")
    st.cost = cost
    detail = "" if ok else next((s.get("error", "") for s in st.stages if not s["ok"]), "")
    if ok and plan_pages:
        detail = f"plan map on page(s) {plan_pages}"
    warnings = []
    if kind == "ifc" and (ddir / "scene.json").is_file():
        warnings.extend(json.loads((ddir / "scene.json").read_text()).get("warnings") or [])
    if (ddir / "pages.json").is_file():
        for page in json.loads((ddir / "pages.json").read_text()).get("pages", []):
            warnings.extend(page.get("warnings") or [])
    if warnings:
        detail = (detail + ". " if detail else "") + " ".join(dict.fromkeys(warnings))
    st.write(final, detail)
    return final


if __name__ == "__main__":
    # Priority is best-effort. A restricted host may disallow nice(); that must
    # not prevent every upload from starting. Avoid preexec_fn in the threaded API.
    try:
        os.nice(10)
    except OSError:
        pass
    print(run(sys.argv[1]))
