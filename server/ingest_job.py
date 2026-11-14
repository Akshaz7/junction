"""Ingest one uploaded document: pages, plan map / scene, extrusion, USDZ (S-04).

Run as `python -m server.ingest_job <doc_id>` from the repo root (the API starts it as a subprocess so
heavy imports and memory stay out of the server). Writes artifacts/<doc_id>/ingest.json with
{"status": "running|ready|partial|failed", "stages": [...], "detail": "..."}.
Local only: the deployed container has no `pipeline/` or models, and keeps uploads as "stored".
"""
import json
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
        self.path, self.stages = path, []
        self.write("running")

    def write(self, status, detail=""):
        self.path.write_text(json.dumps({"status": status, "stages": self.stages, "detail": detail,
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


def run(doc_id: str) -> str:
    art = _art()
    ddir = art / doc_id
    doc = json.loads((ddir / "doc.json").read_text())
    st = Status(ddir / "ingest.json")
    kind = doc["kind"]
    from pipeline import dxf_planmap, extrude, ifc_plans, ifc_scene, pages, usdz
    ok = True
    if kind == "ifc":
        ifc = REPO / doc["files"]["ifc"]
        ok = st.stage("ifc_scene", lambda: ifc_scene.process(ifc, doc, ddir))
        ok = ok and st.stage("ifc_plans", lambda: ifc_plans.process(doc_id, art))
        ok = ok and st.stage("usdz", lambda: usdz.process(doc_id, ddir))
    else:
        if kind == "raster":
            st.stage("normalise", lambda: _normalise_raster(doc_id, art))
            doc = json.loads((ddir / "doc.json").read_text())

        def do_pages():
            _, res = pages.process((REPO, art, doc))
            if not res.startswith("ok"):
                raise RuntimeError(res)
        ok = st.stage("pages", do_pages)
        if ok and kind == "dxf":
            ok = st.stage("dxf_planmap", lambda: dxf_planmap.process(doc_id, ddir, REPO / doc["files"]["dxf"]))
        elif ok and kind == "raster":
            def vision():
                r = subprocess.run([sys.executable, str(REPO / "vision" / "build_planmaps.py"), doc_id],
                                   cwd=REPO, capture_output=True, text=True, timeout=900)
                if r.returncode != 0 or not (ddir / "planmap-1.json").exists():
                    raise RuntimeError((r.stdout + r.stderr)[-300:])
            ok = st.stage("planmap", vision)
        elif ok:
            st.write("partial", f"{kind}: page image only, no plan map for this format")
            return "partial"
        if ok:
            ok = st.stage("extrude", lambda: extrude.process(doc_id, ddir))
            ok = ok and st.stage("usdz", lambda: usdz.process(doc_id, ddir))
    final = "ready" if ok else "failed"
    st.write(final, "" if ok else (next((s.get("error", "") for s in st.stages if not s["ok"]), "")))
    return final


if __name__ == "__main__":
    print(run(sys.argv[1]))
