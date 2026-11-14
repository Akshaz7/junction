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
        self.write("running")

    def write(self, status, detail=""):
        self.path.write_text(json.dumps({"status": status, "stages": self.stages, "detail": detail, "mode": self.mode,
                                         "cost_usd": round(self.cost["usd"], 5) if self.cost else None,
                                         "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, indent=1))

    def stage(self, name, fn):
        t = time.time()
        try:
            fn()
            self.stages.append({"stage": name, "ok": True, "s": round(time.time() - t, 1)})
            self.write("running")
            return True
        except Exception as e:  # noqa: BLE001
            self.stages.append({"stage": name, "ok": False, "error": repr(e)[:300]})
            self.write("running")
            return False


def _normalise_raster(doc_id: str, art: Path):
    """vision.build_planmaps reads doc.json files['png']: make sure the upload is a PNG."""
    from PIL import Image
    d = json.loads((art / doc_id / "doc.json").read_text())
    key, rel = next(iter(d["files"].items()))
    if key == "png":
        return
    src = REPO / rel
    dst = src.with_suffix(".png")
    Image.open(src).convert("RGB").save(dst)
    d["files"] = {"png": str(Path(rel).with_suffix(".png"))}
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
    return sorted(found)


def _dxf_planmap_usable(ddir: Path) -> bool:
    f = ddir / "planmap-1.json"
    if not f.is_file():
        return False
    pm = json.loads(f.read_text())
    n = sum(1 for i in pm["items"] if i["kind"] in ("room", "wall", "door", "window"))
    return n >= 3 and bool(pm["scale"].get("m_per_px"))


def _extrude(doc_id: str, ddir: Path, page: int):
    from pipeline import extrude
    pm = json.loads((ddir / f"planmap-{page}.json").read_text())
    if not pm["scale"].get("m_per_px"):
        raise RuntimeError("no scale on this page (no door or printed dimension found), so no 3D scene")
    extrude.process(doc_id, ddir, page)


def _usdz(doc_id: str, ddir: Path):
    import importlib.util as u
    if not u.find_spec("pxr"):
        return  # AR needs usd-core, which is not in the deploy image: scene.glb still serves the web 3D viewer
    from pipeline import usdz
    usdz.process(doc_id, ddir)


def run(doc_id: str) -> str:
    art = _art()
    ddir = art / doc_id
    doc = json.loads((ddir / "doc.json").read_text())
    st = Status(ddir / "ingest.json")
    kind = doc["kind"]
    light = light_mode()
    st.mode = "vlm" if light else "full"
    cost = {"usd": 0.0, "model": None}
    st.cost = cost
    ok = True
    plan_pages: list[int] = []
    if kind == "ifc":
        ifc_path = REPO / doc["files"]["ifc"]
        cap = float(os.environ.get("INGEST_IFC_MAX_MB", "15" if light else "400"))
        if ifc_path.stat().st_size > cap * 1e6:
            st.write("partial", f"IFC is {ifc_path.stat().st_size / 1e6:.0f} MB; this server converts IFC files up to {cap:.0f} MB. "
                                "The file is stored, but no 3D scene or element list was built")
            return "partial"
        from pipeline import ifc_plans, ifc_scene
        ifc = REPO / doc["files"]["ifc"]
        ok = st.stage("ifc_scene", lambda: ifc_scene.process(ifc, doc, ddir))
        ok = ok and st.stage("ifc_plans", lambda: ifc_plans.process(doc_id, art))
        ok = ok and st.stage("usdz", lambda: _usdz(doc_id, ddir))
    else:
        from pipeline import pages
        if light:
            pages.MAX_SIDE = int(os.environ.get("PAGES_MAX_SIDE", "4096"))  # keep the render inside the container RAM
        if kind == "raster":
            st.stage("normalise", lambda: _normalise_raster(doc_id, art))
            doc = json.loads((ddir / "doc.json").read_text())

        def do_pages():
            _, res = pages.process((REPO, art, doc))
            if not res.startswith("ok"):
                raise RuntimeError(res)
        ok = st.stage("pages", do_pages)
        if ok:
            st.stage("text", lambda: build_text_json(doc_id, ddir))
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
        elif ok and kind in ("raster", "pdf", "svg"):
            plan_pages = _vlm_pages(doc_id, ddir, st, cost)
        elif ok:
            st.write("partial", f"{kind}: page image only, no plan map for this format")
            return "partial"
        if plan_pages:
            ok = st.stage("extrude", lambda: _extrude(doc_id, ddir, plan_pages[0]))
            ok = ok and st.stage("usdz", lambda: _usdz(doc_id, ddir))
        elif ok and all(s["ok"] for s in st.stages):
            st.cost = cost
            st.write("ready", "no drawing pages found: page images and text are indexed, there is no plan map or 3D scene")
            return "ready"
        elif ok:
            ok = False
    final = "ready" if ok else "failed"
    st.cost = cost
    detail = "" if ok else next((s.get("error", "") for s in st.stages if not s["ok"]), "")
    if ok and plan_pages:
        detail = f"plan map on page(s) {plan_pages}"
    st.write(final, detail)
    return final


if __name__ == "__main__":
    print(run(sys.argv[1]))
