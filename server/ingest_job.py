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


STALE_STATUS_S = 300.0  # = server.files_routes.INGEST_TIMEOUT: an older started_at belongs to a previous run


class Status:
    def __init__(self, path: Path):
        self.path, self.stages, self.mode, self.cost = path, [], None, None
        self.started_at, self.step = time.time(), "starting"
        self.detail = ""
        self.readable = False  # page images and text exist: the document can be viewed and questioned
        if path.is_file():
            try:
                self.started_at = json.loads(path.read_text()).get("started_at", self.started_at)
            except ValueError:
                pass
            if time.time() - float(self.started_at or 0) > STALE_STATUS_S:  # an old run's status: this is a re-run
                self.started_at = time.time()
        self.write("running")

    def write(self, status, detail=""):
        state = {"status": status, "stages": self.stages, "detail": detail or self.detail, "mode": self.mode,
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
            if name == "ifc_scene" and not self.readable:
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


def _flag_vlm_fixtures(ddir: Path, pages: list[int]) -> None:
    """A DXF read from its render by the VLM has no CAD block or layer behind a fixture the model names: keep it for
    inspection but below the counting confidence (a toilet nobody drew as a symbol must not become a count)."""
    for n in pages:
        f = ddir / f"planmap-{n}.json"
        if not f.is_file():
            continue
        pm = json.loads(f.read_text())
        changed = False
        for item in pm["items"]:
            if item["kind"] in ("toilet", "sink", "shower", "bathtub") and item.get("source") == "vlm":
                item["conf"] = min(item.get("conf") or 0.4, 0.4)
                item.setdefault("props", {})["note"] = "read from the rendered DXF by a model; no CAD block or sanitary layer confirms it"
                changed = True
        if changed:
            f.write_text(json.dumps(pm))


def _dxf_planmap_usable(ddir: Path) -> bool:
    f = ddir / "planmap-1.json"
    if not f.is_file():
        return False
    pm = json.loads(f.read_text())
    n = sum(1 for i in pm["items"] if i["kind"] in ("room", "wall", "door", "window"))
    return n >= 3  # counts remain usable without units; physical sizes remain unknown


MAX_PDF_PLAN_PAGES = 4

# ---------------------------------------------------------------- whole-ingest budget
# The API (server/files_routes.INGEST_TIMEOUT) kills the job 5 min after the upload was queued, and a kill after
# "ready" still marks the document failed. run() therefore sets a deadline at started_at (queue time) + INGEST_BUDGET_S
# and the heavy steps run in forked children with a timeout (_bounded): a page whose vector read would run past its
# share is dropped (flagged) instead of costing the scene, the IFC route falls back to the plain extrusion, and the
# post-ready text refine stops in time. Without a deadline (_run called directly, as in tests) everything runs inline.
INGEST_BUDGET_S = 270.0
VECTOR_RESERVE_S = 120.0  # kept after the vector plan maps for the IFC route (~70-90 s on a dense sheet) + IFC_RESERVE_S
                          # (extrude fallback + USDZ): with 75 s the IFC route got ~50 s after a long page and always fell
                          # back to the extrusion (ARK s01); the page's optional add-ons give way instead
IFC_RESERVE_S = 25.0      # kept after the IFC route for the extrusion fallback + USDZ
VECTOR_MIN_PAGE_S = 20.0  # a vector page starts only with this much time (beyond VECTOR_RESERVE_S) left
_DEADLINE: list = [None]  # time.time() deadline, or None (no budget: inline)


def _set_deadline(started_at: float | None):
    """Deadline = started_at + INGEST_BUDGET_S (env overrides; 0 = no budget). A stale started_at (an old status file)
    still leaves a quarter of the budget."""
    try:
        b = float(os.environ.get("INGEST_BUDGET_S", INGEST_BUDGET_S))
    except ValueError:
        b = INGEST_BUDGET_S
    if b <= 0:
        _DEADLINE[0] = None
        return
    now = time.time()
    _DEADLINE[0] = max((started_at or now) + b, now + 0.25 * b)


def _budget_left() -> float | None:
    return None if _DEADLINE[0] is None else _DEADLINE[0] - time.time()


def _fork_ok() -> bool:
    import multiprocessing as mp
    return _DEADLINE[0] is not None and os.environ.get("INGEST_FORK", "1") != "0" and "fork" in mp.get_all_start_methods()


def _bounded(fn, timeout_s: float | None):
    """Run fn() in a forked child (its memory is returned to the OS when it exits) with a hard timeout.
    -> ("ok", value) | ("error", repr) | ("timeout", None). Inline (no timeout) when there is no budget/fork."""
    if timeout_s is None or not _fork_ok():
        try:
            return "ok", fn()
        except Exception as e:  # noqa: BLE001
            return "error", repr(e)[:300]
    if timeout_s <= 0:
        return "timeout", None
    import multiprocessing as mp
    ctx = mp.get_context("fork")
    rx, tx = ctx.Pipe(duplex=False)

    def child():
        try:
            r = ("ok", fn())
        except BaseException as e:  # noqa: BLE001
            r = ("error", repr(e)[:300])
        try:
            tx.send(r)
        except Exception as e:  # noqa: BLE001  unpicklable result
            tx.send(("error", f"result not sent: {e!r}"[:300]))
        tx.close()
        os._exit(0)
    p = ctx.Process(target=child, daemon=True)
    p.start()
    tx.close()
    out = ("timeout", None)
    try:
        if rx.poll(timeout_s):
            out = rx.recv()
    except EOFError:
        out = ("error", f"child exited with code {p.exitcode}")
    finally:
        if p.is_alive():
            p.kill()
        p.join(5)
        rx.close()
    if out[0] == "error" and p.exitcode not in (0, None):
        out = ("error", f"{out[1]} (child exit {p.exitcode})")
    return out


class _OverBudget(BaseException):
    """Raised by SIGALRM inside a time-limited stage (BaseException: the stage's own `except Exception` cannot eat it)."""


# Degradation order when time runs short (shares are of the time left to the child's deadline when the stage
# starts; core stages get all of it, optional ones a part, so they are cut first and the core keeps its time):
# core: rooms, openings, plan region crop (rooms and openings leave PLAN_REGION_RESERVE_S / OPENINGS_RESERVE_S
# behind them, so the crop that keeps neighbouring roofs out always runs: it takes ~1-5 s, its outline pass caps
# itself at 2 s) > semantics text (analyse) > optional add-ons: fixtures, levels, quality.
# In the IFC child: pdf_to_ifc core, ifc_enrich extras and MEP optional.
PLAN_REGION_RESERVE_S = 12.0  # left by rooms() for openings collection + plan_region
OPENINGS_RESERVE_S = 6.0      # left by openings() for plan_region
PAGE_LIMITS = [("pdf_rooms", "rooms", 1.0, PLAN_REGION_RESERVE_S, list),
               ("pdf_openings", "openings", 1.0, OPENINGS_RESERVE_S, list),
               ("pdf_semantics", "plan_region", 1.0, 0.0, RuntimeError), ("pdf_semantics", "analyse", 0.5, 0.0, RuntimeError),
               ("pdf_fixtures", "detect", 0.3, 0.0, RuntimeError), ("pdf_levels", "planmap_provenance", 0.3, 0.0, RuntimeError),
               ("pdf_quality", "assess", 0.3, 0.0, RuntimeError)]
# No signal-based limits inside ifcopenshell work: an exception raised in the middle of building entities left a
# half-built model that crashed the scene step (SIGSEGV in the child). The IFC child has its hard timeout only, and
# the MEP step its start check (_mep_enrich: PDF_MEP_MIN_LEFT_S).
IFC_LIMITS: list = []


def _mep_page_limits() -> list:
    """PAGE_LIMITS for an MEP sheet: openings capped at MEP_OPENINGS_CAP_S (absolute), fixtures/levels/quality
    skipped; rooms (and the scale fit from printed areas) and the plan-region crop keep their time."""
    out = []
    for modname, name, share, reserve, empty in PAGE_LIMITS:
        if name in ("detect", "planmap_provenance", "assess"):
            share = 0.0
        out.append((modname, name, share, reserve, empty, MEP_OPENINGS_CAP_S if name == "openings" else None))
    return out


def _soft_limits(page_deadline: float, cut: list, spec: list | None = None) -> list:
    """Forked child only: per-stage time limits (spec: PAGE_LIMITS / IFC_LIMITS), so a dense sheet returns what it has
    instead of being killed. A stage over its limit returns its empty result (rooms, openings) or raises a plain
    error that its caller already absorbs (semantics, fixtures, levels, quality, ifc_enrich, MEP); its name goes to
    `cut`. Returns [(module, name, original)] to restore."""
    import importlib
    import signal

    def handler(signum, frame):
        raise _OverBudget()

    def limited(mod, name, share, reserve, empty, cap=None):
        f = getattr(mod, name)

        def g(*a, **k):
            lim = share * (page_deadline - time.time()) - reserve
            if cap is not None:
                lim = min(lim, cap)
            if lim <= 0.05:
                cut.append(name)
                if empty is RuntimeError:
                    raise RuntimeError(f"skipped: ingest budget ({name})")
                return empty()
            old = signal.signal(signal.SIGALRM, handler)
            signal.setitimer(signal.ITIMER_REAL, lim)
            try:
                return f(*a, **k)
            except _OverBudget:
                cut.append(name)
                if empty is RuntimeError:
                    raise RuntimeError(f"stopped: ingest budget ({name}, {lim:.0f} s)") from None
                return empty()
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, old)
        setattr(mod, name, g)
        return mod, name, f
    plan = []
    for modname, name, share, reserve, empty, *cap in (PAGE_LIMITS if spec is None else spec):
        try:
            m = importlib.import_module(f"pipeline.{modname}")
            if hasattr(m, name):
                plan.append((m, name, share, reserve, empty, *cap))
        except Exception:  # noqa: BLE001  optional role module missing
            pass
    return [limited(*x) for x in plan]


def _parallel_openings(page_deadline: float, cut: list) -> list:
    """Forked vector-page child only: pdf_openings.openings(page, walls) does not need the rooms, so it starts in a
    grandchild (os.fork) when pdf_rooms.rooms(page, walls) starts and the later openings call with the same walls
    takes its result (plus the keys openings leaves on the page, e.g. _arc_polylines for pdf_quality). Same output,
    the two slowest plan-map stages overlap on a multi-core box. Any problem: openings runs inline as before.
    Returns the [(module, name, original)] to restore."""
    import pickle
    import select
    import signal
    from pipeline import pdf_openings, pdf_rooms
    rooms0, open0 = pdf_rooms.rooms, pdf_openings.openings
    state = {}

    def rooms(page, walls, *a, **k):
        if "pid" not in state:
            try:
                r_fd, w_fd = os.pipe()
                pid = os.fork()
                if pid == 0:  # grandchild
                    try:
                        try:  # dies with its parent (a page child killed at the hard timeout leaves no orphan)
                            import ctypes
                            ctypes.CDLL(None).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG
                        except Exception:  # noqa: BLE001  not Linux: the openings soft limit still ends it
                            pass
                        os.close(r_fd)
                        keys = set(page)
                        try:
                            r = ("ok", open0(page, walls), {q: page[q] for q in page if q not in keys})
                        except BaseException as e:  # noqa: BLE001
                            r = ("error", repr(e)[:200], {})
                        data = pickle.dumps(r, protocol=pickle.HIGHEST_PROTOCOL)
                        with os.fdopen(w_fd, "wb") as fh:
                            fh.write(data)
                    finally:
                        os._exit(0)
                os.close(w_fd)
                state.update(pid=pid, fd=r_fd, walls=id(walls), page=id(page))
            except Exception as e:  # noqa: BLE001
                print("parallel openings off:", repr(e)[:120], file=sys.stderr)
                state["pid"] = None
        return rooms0(page, walls, *a, **k)

    def openings(page, walls, *a, **k):
        pid, fd = state.get("pid"), state.get("fd")
        if pid and not a and not k and state.get("walls") == id(walls) and state.get("page") == id(page):
            state["pid"] = None
            buf, ok = [], False
            try:
                while True:
                    left = page_deadline - time.time() - 1.0
                    if left <= 0 or not select.select([fd], [], [], left)[0]:
                        break
                    chunk = os.read(fd, 1 << 20)
                    if not chunk:
                        ok = True
                        break
                    buf.append(chunk)
                if ok and buf:
                    r = pickle.loads(b"".join(buf))
                    if r[0] == "ok":
                        page.update(r[2])
                        return r[1]
                elif not ok:
                    cut.append("openings")
                    return []
            except Exception as e:  # noqa: BLE001
                print("parallel openings result lost:", repr(e)[:120], file=sys.stderr)
            finally:
                try:
                    os.close(fd)
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
                try:
                    os.waitpid(pid, 0)
                except OSError:
                    pass
        return open0(page, walls, *a, **k)
    pdf_rooms.rooms, pdf_openings.openings = rooms, openings
    return [(pdf_rooms, "rooms", rooms0), (pdf_openings, "openings", open0)]


def _fork_call(fn, timeout_s: float):
    """fn() in an os.fork child (works inside a multiprocessing daemon child, unlike _bounded), result pickled back
    through a pipe. -> ("ok", value) | ("error", repr) | ("timeout", None). The child dies with its parent."""
    import pickle
    import select
    import signal
    if timeout_s <= 0:
        return "timeout", None
    r_fd, w_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        try:
            try:
                import ctypes
                ctypes.CDLL(None).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG
            except Exception:  # noqa: BLE001
                pass
            os.close(r_fd)
            try:
                r = ("ok", fn())
            except BaseException as e:  # noqa: BLE001
                r = ("error", repr(e)[:300])
            try:
                data = pickle.dumps(r, protocol=pickle.HIGHEST_PROTOCOL)
            except Exception as e:  # noqa: BLE001
                data = pickle.dumps(("error", f"result not sent: {e!r}"[:300]))
            with os.fdopen(w_fd, "wb") as fh:
                fh.write(data)
        finally:
            os._exit(0)
    os.close(w_fd)
    buf, done, end = [], False, time.time() + timeout_s
    try:
        while True:
            left = end - time.time()
            if left <= 0 or not select.select([r_fd], [], [], left)[0]:
                break
            chunk = os.read(r_fd, 1 << 20)
            if not chunk:
                done = True
                break
            buf.append(chunk)
    finally:
        os.close(r_fd)
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass
    if not done:
        return "timeout", None
    try:
        return pickle.loads(b"".join(buf))
    except Exception as e:  # noqa: BLE001
        return "error", f"child result lost: {e!r}"[:300]


MEP_RESERVE_S = 130.0     # MEP sheet: kept after the vector plan map for IFC + ducts (pdf_mep) + scene + USDZ
MEP_OPENINGS_CAP_S = 15.0  # MEP sheet: the doors are the underlay's; most arcs are duct bends/dampers
MEP_SCENE_S = 45.0        # kept after the MEP step inside the IFC child for ifc_scene


def _mep_hint(pdf: Path, page_index: int) -> bool:
    """Cheap text-only MEP test (pdf_mep's own text gate on the pdfium words, no page load): the vector route plans
    its time for an MEP sheet (small openings cap, more reserve for the ducts). False on any problem."""
    if os.environ.get("PDF_MEP", "1") == "0":
        return False
    try:
        from pipeline import pdf_mep
        if not (hasattr(pdf_mep, "text_cues") and hasattr(pdf_mep, "_cue_score")):
            return False
        import pypdfium2 as pdfium
        from pipeline.pdf_vector import _displayer, _words_pdfium
        doc = pdfium.PdfDocument(str(pdf))
        try:
            pg = doc[page_index]
            rot = pg.get_rotation() % 360
            cl, cb, cr, ct = pg.get_cropbox()
            words = _words_pdfium(pg, _displayer(rot, cr - cl, ct - cb, cl, cb))
            pg.close()
        finally:
            doc.close()
        kinds, n = pdf_mep._cue_score(pdf_mep.text_cues(words))
        return kinds >= 2 and n >= 4
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- multi-page sets: which sheets are floor plans
SHEET_FIRST = ("plan",)                    # read first, in page order
SHEET_THEN = ("mep", "other")              # then these (an MEP plan, a sheet with no readable title)
SHEET_LAST = ("demo", "roof", "rcp")       # plan-like sheets: only when the set has nothing above
# never read as a floor plan: elevation, section, schedule, cover/3D, detail, site, structural


def _sheet_plan(ddir: Path, meta: dict) -> dict:
    """Multi-page PDF: classify every page from the words the pages stage already extracted (text-<n>.json,
    pdf_levels.classify_sheet: title block + view titles + sheet number, ~0.1 s a page, no vector read) and order the
    pages for the vector read: floor plans first, elevations/sections/schedules/covers/details/site/structural never.
    Level datums printed on the elevation/section sheets (pdf_levels.level_table) are kept for the storey stack.
    -> {"order": [page numbers], "kinds": {n: kind}, "levels": [rows], "titles": {n: title}}. A single page, a page
    without text or any error keeps the page order (today's behaviour)."""
    pages_ = [int(p["page"]) for p in meta.get("pages") or []]
    out = {"order": pages_, "kinds": {}, "levels": [], "titles": {}}
    if len(pages_) <= 1 or os.environ.get("PDF_SHEET_SELECT", "1") == "0":
        return out
    try:
        from pipeline import pdf_levels
        kinds, levels = {}, []
        for n in pages_:
            f = ddir / f"text-{n}.json"
            if not f.is_file():
                kinds[n] = "other"
                continue
            t = json.loads(f.read_text())
            ws = [{"text": w.get("text", ""), "bbox": w["bbox_px"]} for w in t.get("words") or [] if w.get("bbox_px")]
            c = pdf_levels.classify_sheet(ws, (t.get("image") or {}).get("w"), (t.get("image") or {}).get("h"))
            kinds[n] = c.get("kind") or "other"
            if c.get("title"):
                out["titles"][n] = str(c["title"])[:40]
            if kinds[n] in ("elevation", "section"):
                for row in pdf_levels.level_table({"words": ws}):
                    if row.get("elevation_m") is not None and all(r["name"] != row["name"] for r in levels):
                        levels.append({**row, "source_page": n})
        order = [n for n in pages_ if kinds[n] in SHEET_FIRST] + [n for n in pages_ if kinds[n] in SHEET_THEN]
        if not order:
            order = [n for n in pages_ if kinds[n] in SHEET_LAST]
        out.update(order=order, kinds=kinds, levels=levels)
    except Exception as e:  # noqa: BLE001  never costs the upload: page order as before
        print("sheet classification skipped:", repr(e)[:200], file=sys.stderr)
    return out


def _add_set_levels(ddir: Path, found: list, levels: list):
    """Level datums from the set's elevation/section sheets -> each plan map's provenance.level_table (rows the plan
    map already has win), so pdf_levels.storeys_from_planmaps (build_many) gives each storey its printed elevation."""
    if not levels:
        return
    for n in found:
        f = ddir / f"planmap-{n}.json"
        try:
            pm = json.loads(f.read_text())
            prov = pm.setdefault("provenance", {})
            have = {r.get("name") for r in prov.get("level_table") or []}
            prov["level_table"] = list(prov.get("level_table") or []) + [r for r in levels if r["name"] not in have]
            f.write_text(json.dumps(pm))
        except Exception as e:  # noqa: BLE001
            print("set levels skipped:", repr(e)[:160], file=sys.stderr)


def _pdf_vector_pages(doc_id: str, ddir: Path, st: "Status", pdf: Path) -> list[int]:
    """Vector CAD PDF: exact plan maps from the page's drawing operators (pipeline.pdf_planmap), gated per page, at most
    MAX_PDF_PLAN_PAGES plan pages. Returns the plan pages; [] (and no plan-map files left behind) means use the VLM path."""
    from pipeline import pdf_planmap
    meta = json.loads((ddir / "pages.json").read_text())
    cap = int(os.environ.get("MAX_PDF_PLAN_PAGES", str(MAX_PDF_PLAN_PAGES)))
    budget = float(os.environ.get("PDF_VECTOR_BUDGET_S", "90"))
    found, notes = [], []

    def one(n):
        """One page's vector plan map. In the forked child (ingest budget), walls() gets PDF_WALLS_SHARE of the
        page's time and the later stages soft limits (_soft_limits), so the page returns a flagged partial plan map
        before the parent's hard timeout. Returns (found, info)."""
        from pipeline import pdf_vector
        left = _budget_left()
        cut, restore = [], []
        mep = n in mep_pages
        if left is not None and _fork_ok():
            page_s = left - (MEP_RESERVE_S if mep else VECTOR_RESERVE_S) - 3.0
            share = max(5.0, float(os.environ.get("PDF_WALLS_SHARE", "0.35")) * page_s)
            pdf_vector.DEADLINE = time.monotonic() + share
            restore = _soft_limits(time.time() + page_s, cut, _mep_page_limits() if mep else None)
            if os.environ.get("PDF_PAR_OPENINGS", "1") != "0" and (os.cpu_count() or 1) >= 2:
                try:
                    restore = _parallel_openings(time.time() + page_s, cut) + restore
                except Exception as e:  # noqa: BLE001
                    print("parallel openings skipped:", repr(e)[:120], file=sys.stderr)
        if mep:
            restore = _mep_shell_walls() + restore
        try:
            pm = pdf_planmap.process(doc_id, ddir, pdf, n - 1)
        finally:
            pdf_vector.DEADLINE = None
            for mod, name, f in restore:
                setattr(mod, name, f)
        lw = dict(pdf_vector.LAST_WALLS)
        info = {"walls_truncated": bool(lw.get("truncated")), "walls_s": lw.get("s"), "cut": cut}
        if pm is not None and (info["walls_truncated"] or cut):  # flag the partial read on the plan map itself
            pm.setdefault("provenance", {})["budget"] = {**info, "walls_budget_s": lw.get("budget_s")}
            (ddir / f"planmap-{n}.json").write_text(json.dumps(pm))
        return pm is not None, info

    mep_pages = set()

    def run_all():
        t0 = time.time()
        slowest = 0.0
        for n in sheets["order"]:
            if len(found) >= cap or time.time() - t0 > budget:
                break
            if _mep_hint(pdf, n - 1):
                mep_pages.add(n)
                notes.append(f"p{n}: MEP sheet (openings capped at {MEP_OPENINGS_CAP_S:.0f} s, add-ons skipped)")
            left = _budget_left()
            if left is not None:
                room = left - (MEP_RESERVE_S if n in mep_pages else VECTOR_RESERVE_S)
                if found and room < max(VECTOR_MIN_PAGE_S, 1.2 * slowest):  # a further plan page would not fit: keep what we have
                    notes.append(f"budget: stopped before p{n} ({left:.0f} s left)")
                    break
                if room < VECTOR_MIN_PAGE_S:
                    notes.append(f"budget: no time for p{n} ({left:.0f} s left)")
                    break
            t = time.time()
            res, val = _bounded(lambda: one(n), None if left is None else
                                left - (MEP_RESERVE_S if n in mep_pages else VECTOR_RESERVE_S))
            slowest = max(slowest, time.time() - t)
            if res == "ok" and val[0]:
                found.append(n)
                inf = val[1] or {}
                if inf.get("walls_truncated") or inf.get("cut"):
                    notes.append(f"p{n}: partial at the ingest budget (walls truncated={inf.get('walls_truncated')}"
                                 f" at {inf.get('walls_s')} s, cut {inf.get('cut') or []})")
            elif res == "timeout":
                notes.append(f"p{n}: vector read stopped at the ingest budget ({time.time() - t:.0f} s)")
                (ddir / f"planmap-{n}.json").unlink(missing_ok=True)
                break
            elif res == "error":  # one odd page never costs the others
                notes.append(f"p{n}: {val}"[:120])
                (ddir / f"planmap-{n}.json").unlink(missing_ok=True)
            else:
                (ddir / f"planmap-{n}.json").unlink(missing_ok=True)
    sheets = _sheet_plan(ddir, meta)
    ok = st.stage("planmap_pdf_vector", run_all)
    if sheets["kinds"]:
        st.stages[-1]["sheets"] = " ".join(f"p{n}:{k}" for n, k in sheets["kinds"].items())[:300]
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
    _add_set_levels(ddir, found, sheets["levels"])
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


def _pdf_words(pdf: Path, page_index: int) -> dict | None:
    """{"words", "W_pt", "H_pt"} of one PDF page from pdfium's text layer (displayed pt, no path walk)."""
    import pypdfium2 as pdfium
    from pipeline.pdf_vector import _displayer, _words_pdfium
    doc = pdfium.PdfDocument(str(pdf))
    try:
        pg = doc[page_index]
        rot = pg.get_rotation() % 360
        cl, cb, cr, ct = pg.get_cropbox()
        w, h = (cr - cl, ct - cb) if rot in (0, 180) else (ct - cb, cr - cl)
        words = _words_pdfium(pg, _displayer(rot, cr - cl, ct - cb, cl, cb))
        pg.close()
    finally:
        doc.close()
    return {"words": words, "W_pt": float(w), "H_pt": float(h)}


MEP_ARK_MIN_MATCHES = 4     # shared-text anchors an architect sheet needs to be the MEP sheet's own floor
MEP_ARK_MAX_DOCS = 40       # architect candidates looked at (newest IFC first)
MEP_ARK_SCAN_S = 20.0       # time for that scan


def _mep_architect(pdf: Path, page_index: int, doc_id: str) -> dict | None:
    """plans2bim-style pairing: the architect plan of the same storey already ingested in the artifacts dir (a PDF
    doc with a model.ifc, not itself an MEP sheet) whose text aligns with this MEP page (pdf_mep.align, shared
    room numbers / tags, >= MEP_ARK_MIN_MATCHES inliers). Best by inliers. {"doc_id", "pdf", "ifc", "matches",
    "rms_pt"} or None (switch PDF_MEP_COMBINE=0; any problem -> None)."""
    if os.environ.get("PDF_MEP_COMBINE", "1") == "0":
        return None
    try:
        from pipeline import pdf_mep
        t0 = time.time()
        me = _pdf_words(pdf, page_index)
        need = int(os.environ.get("PDF_MEP_ARK_MIN", str(MEP_ARK_MIN_MATCHES)))
        cands = []
        for dj in _art().glob("*/doc.json"):
            d = dj.parent
            if d.name == doc_id or not (d / "model.ifc").is_file():
                continue
            cands.append((-(d / "model.ifc").stat().st_mtime, d))
        best = None
        for _, d in sorted(cands)[:MEP_ARK_MAX_DOCS]:
            if time.time() - t0 > MEP_ARK_SCAN_S:
                break
            try:
                meta = json.loads((d / "doc.json").read_text())
                rel = (meta.get("files") or {}).get("pdf")
                if not rel or meta.get("mep_from"):
                    continue
                src = REPO / rel if (REPO / rel).is_file() else Path(rel)
                if not src.is_file() or src.resolve() == Path(pdf).resolve():
                    continue
                other = _pdf_words(src, 0)
                kinds, n = pdf_mep._cue_score(pdf_mep.text_cues(other["words"]))
                if kinds >= 2 and n >= 4:       # another MEP sheet, not an architect plan
                    continue
                T = pdf_mep.align(me, other)
                if T and T["n_inliers"] >= need and (best is None or T["n_inliers"] > best["matches"]):
                    best = {"doc_id": d.name, "pdf": src, "ifc": d / "model.ifc", "matches": T["n_inliers"],
                            "rms_pt": round(T["rms_pt"], 3)}
            except Exception:  # noqa: BLE001  one unreadable candidate
                continue
        return best
    except Exception as e:  # noqa: BLE001
        print("mep architect scan skipped:", repr(e)[:160], file=sys.stderr)
        return None


def _mep_shell_walls() -> list:
    """MEP sheet: pdf_vector.walls swapped for pdf_mep.shell_walls (the detector on the grey architect underlay only,
    capped at PDF_MEP_SHELL_S, filtered to wall thicknesses), so the sheet gets its building shell instead of a
    timed-out scan of every duct pen. Returns [(module, name, original)] to restore; [] when pdf_mep lacks it."""
    if os.environ.get("PDF_MEP_SHELL", "1") == "0":
        return []
    try:
        from pipeline import pdf_mep, pdf_vector
        if not hasattr(pdf_mep, "shell_walls"):
            return []
        orig = pdf_vector.walls
        cap = float(os.environ.get("PDF_MEP_SHELL_S", str(getattr(pdf_mep, "SHELL_CAP_S", 35.0))))

        def walls(page, budget_s=None):
            return pdf_mep.shell_walls(page, orig, budget_s=min(cap, budget_s) if budget_s else cap)
        pdf_vector.walls = walls
        return [(pdf_vector, "walls", orig)]
    except Exception as e:  # noqa: BLE001
        print("mep shell skipped:", repr(e)[:160], file=sys.stderr)
        return []


def _mep_enrich(ifc: Path, doc: dict, page: int, planmap: dict, notes: list | None = None) -> dict | None:
    """MEP sheet (ventilation over an architect underlay): ducts, fittings and air terminals added to the IFC in place
    by pipeline.pdf_mep (lazy import). Only when pdf_mep.is_mep_sheet says so; any exception, a missing module or
    an exhausted ingest budget skips it and leaves the plain IFC (pdf_mep writes atomically). Returns its stats or None."""
    if os.environ.get("PDF_MEP", "1") == "0":
        return None
    try:
        rel = (doc.get("files") or {}).get("pdf")
        if not rel:
            return None
        pdf = REPO / rel
        from pipeline import pdf_mep
        if not (hasattr(pdf_mep, "is_mep_sheet") and hasattr(pdf_mep, "enrich_ifc")):
            return None
        left = _budget_left()
        if left is not None and left < float(os.environ.get("PDF_MEP_MIN_LEFT_S", "30")):
            if notes is not None:
                notes.append(f"mep skipped: ingest budget ({left:.0f} s left)")
            return None
        t = time.time()

        def run():
            if not pdf_mep.is_mep_sheet(pdf, page - 1):
                return None
            if left is not None and "PDF_VTEXT_S" not in os.environ:
                # stroke-text size reader (pdf_ducts): only the time this step can spare after ~60 s of detection
                os.environ["PDF_VTEXT_S"] = str(max(0.0, min(60.0, left - IFC_RESERVE_S - MEP_SCENE_S - 60.0)))
            arch = _mep_architect(pdf, page - 1, str(doc.get("doc_id") or ""))
            if arch is not None and hasattr(pdf_mep, "combine"):
                # the architect model of this storey takes the ducts (its shell, rooms, doors); any failure -> the
                # sheet's own IFC as before
                tmp = Path(str(ifc) + ".combined.tmp.ifc")
                try:
                    rep = pdf_mep.combine(arch["pdf"], pdf, arch["ifc"], tmp, mep_page_index=page - 1,
                                          mep_artifact_dir=Path(ifc).parent)
                    os.replace(tmp, ifc)
                    rep = {k: v for k, v in rep.items() if k not in ("clusters", "overlay")}
                    rep["architect"] = {k: str(v) for k, v in arch.items()}
                    return rep
                except Exception as e:  # noqa: BLE001
                    print("mep combine skipped:", repr(e)[:160], file=sys.stderr)
                    Path(tmp).unlink(missing_ok=True)
            return pdf_mep.enrich_ifc(Path(ifc), pdf, page - 1, planmap)
        if left is None or not _fork_ok():
            r = run()
        else:  # own child, cut before the scene's share: enrich_ifc writes atomically, a kill leaves the plain IFC
            res, r = _fork_call(run, left - IFC_RESERVE_S - MEP_SCENE_S)
            if res != "ok":
                raise RuntimeError("stopped at the ingest budget" if res == "timeout" else str(r))
        if r is None:
            return None
        if notes is not None:
            r = r if isinstance(r, dict) else {}
            notes.append("mep: " + ", ".join(f"{k}={r[k]}" for k in ("ducts", "terminals", "fittings") if k in r)
                         + (f", on architect {r['architect'].get('doc_id')} ({r['architect'].get('matches')} anchors)"
                            if isinstance(r.get("architect"), dict) else "") + f" ({time.time() - t:.0f} s)")
        return r
    except Exception as e:  # noqa: BLE001  optional extra: the plain IFC stays
        print("mep enrich skipped:", repr(e)[:200], file=sys.stderr)
        if notes is not None:
            notes.append(f"mep skipped: {e!r}"[:160])
        return None


STOREY_SPACING_M = 3.0  # fallback storey-to-storey height when the sheets print no levels


def _storeys(pms: list) -> list:
    """[(storey_name, elevation_m)] for plan maps in page order: pipeline.pdf_levels (title block, level marks) when
    present, else each plan map's provenance.storey, else "Floor N" at STOREY_SPACING_M per page. Never raises."""
    out = []
    for i, pm in enumerate(pms):
        sto = (pm.get("provenance") or {}).get("storey") or {}
        out.append([sto.get("name") or f"Floor {i + 1}",
                    float(sto["elevation_m"]) if sto.get("elevation_m") is not None else STOREY_SPACING_M * i])
    try:
        from pipeline import pdf_levels
        lv = pdf_levels.storeys_from_planmaps(pms)
        for e in lv or []:
            k = int(e.get("page_index", -1))
            if 0 <= k < len(out):
                if e.get("name"):
                    out[k][0] = str(e["name"])
                if e.get("elevation_m") is not None:
                    out[k][1] = float(e["elevation_m"])
    except Exception as e:  # noqa: BLE001
        print("pdf_levels skipped:", repr(e)[:200], file=sys.stderr)
    return [(n, round(z, 3)) for n, z in out]


def _stack_pages(pms: list, names: list) -> list[int]:
    """Indexes of the plan maps that become storeys: one per storey (a second sheet of the same level, e.g. a
    demolition plan next to the new plan, or an enlarged plan of it, is not stacked on top). Order kept."""
    keep, seen = [], set()
    for i, (n, z) in enumerate(names):
        key = (str(n).strip().lower(), round(z, 2))
        if i and (key in seen or any(abs(z - names[k][1]) < 0.05 for k in keep)):
            continue
        seen.add(key)
        keep.append(i)
    return keep


def _pdf_via_ifc(doc_id: str, ddir: Path, doc: dict, page, notes: list | None = None):
    """Vector PDF plan map(s) -> IFC4 (pipeline.pdf_to_ifc) -> the IFC scene path (ifc_scene: scene.glb, scene.json,
    elements.json), so a PDF looks like an IFC upload in 3D/AR. The page image and planmap-<n>.json stay the PDF's own
    (ifc_plans is not run: it would replace them); plan-map ids are relinked to the IFC GlobalIds. Any failure leaves
    no IFC files behind and raises, so the caller extrudes the plan map instead. `page` is one plan page or the list
    of plan pages: several pages of different storeys become one storey each (pdf_to_ifc.build_many, names and
    elevations from _storeys); one page keeps build() with its own storey name/elevation. An MEP sheet gets its ducts
    and air terminals added between the IFC build and the scene (_mep_enrich, skipped on any error)."""
    from pipeline import ifc_scene, pdf_to_ifc
    pages_ = list(page) if isinstance(page, (list, tuple)) else [page]
    files = {n: ddir / f"planmap-{n}.json" for n in pages_}
    keep = {n: f.read_text() for n, f in files.items()}
    try:
        pms = [json.loads(keep[n]) for n in pages_]
        names = _storeys(pms)
        idx = _stack_pages(pms, names) if len(pms) > 1 else [0]
        if len(idx) > 1:
            left = _budget_left()
            per = float(os.environ.get("IFC_PAGE_EST_S", "20"))
            fit = len(idx) if left is None else max(1, int((left - IFC_RESERVE_S - 30) // per))
            if fit < len(idx) and notes is not None:
                notes.append(f"budget: {fit} of {len(idx)} storeys")
            idx = idx[:fit]
        used = [pages_[i] for i in idx]
        if len(idx) > 1:
            ifc = pdf_to_ifc.build_many([(pms[i], names[i][0], names[i][1]) for i in idx], ddir / "model.ifc",
                                        doc_id=doc_id)
            if notes is not None:
                notes.append("storeys " + ", ".join(f"p{pages_[i]} {names[i][0]} @{names[i][1]} m" for i in idx))
        else:
            ifc = pdf_to_ifc.build(pms[0], ddir / "model.ifc", storey_name=names[0][0], storey_elevation=names[0][1],
                                   doc_id=doc_id)
        _mep_enrich(Path(ifc), doc, pages_[0], pms[0], notes)
        # A property index left by an earlier pass describes a different model; the indexed path would reject the new
        # GLB's nodes. Drop it so the scene is indexed from the IFC just built.
        (ddir / "elements.json").unlink(missing_ok=True)
        ifc_scene.process(Path(ifc), doc, ddir)
        for n in used:
            pdf_to_ifc.link_planmap(files[n], doc_id)
        _copy_quality(ddir, pages_[0])
        mark_ifc_from_pdf(ddir, True)
    except BaseException:
        _undo_ifc(ddir, files, keep)
        raise
    return notes


def _undo_ifc(ddir: Path, files: dict, keep: dict):
    """Back to the state before _pdf_via_ifc: original plan maps, no IFC/scene files, no IFC marks in doc.json."""
    for n, f in files.items():
        f.write_text(keep[n])
    for name in ("model.ifc", "elements.json", "scene.glb", "scene.json"):
        (ddir / name).unlink(missing_ok=True)
    mark_ifc_from_pdf(ddir, False)


def _pdf_via_ifc_bounded(doc_id: str, ddir: Path, doc: dict, plan_pages: list, notes: list):
    """_pdf_via_ifc in a forked child, cut off IFC_RESERVE_S before the ingest deadline (inline without a budget).
    Raises on failure or timeout (state restored), so the caller extrudes the plan map instead."""
    files = {n: ddir / f"planmap-{n}.json" for n in plan_pages}
    keep = {n: f.read_text() for n, f in files.items()}
    left = _budget_left()
    def child():
        cut = []
        if left is not None and _fork_ok() and IFC_LIMITS:  # optional extras give way to the core IFC + scene
            _soft_limits(time.time() + left - IFC_RESERVE_S - 3.0, cut, IFC_LIMITS)
        out = _pdf_via_ifc(doc_id, ddir, doc, plan_pages, [])
        return (out or []) + ([f"cut at the ingest budget: {cut}"] if cut else [])
    res, val = _bounded(child, None if left is None else left - IFC_RESERVE_S)
    if res == "ok":
        notes.extend(val or [])
        return
    _undo_ifc(ddir, files, keep)
    raise RuntimeError("IFC route stopped at the ingest budget" if res == "timeout" else str(val))


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


def _usdz(doc_id: str, ddir: Path, strict: bool = False):
    import importlib.util as u
    if not u.find_spec("pxr"):
        if strict:  # IFC worker: say why there is no AR file instead of silently hiding the button
            raise RuntimeError("the AR converter (usd-core) is not installed on this server")
        return  # scene.glb still serves the web 3D viewer
    from pipeline import usdz
    usdz.process(doc_id, ddir)


def run(doc_id: str) -> str:
    st = Status(_art() / doc_id / "ingest.json")
    _set_deadline(st.started_at)
    try:
        final = _run(doc_id, st)
    except Exception as e:  # noqa: BLE001
        final = "partial" if st.readable else "failed"
        st.write(final, f"Ingestion could not complete: {str(e)[:300] or type(e).__name__}")
        return final
    if final in ("ready", "partial"):
        try:  # after the status is final: the slow, more exact text layer replaces the quick one
            refine_text(doc_id, _art() / doc_id)
        except Exception as e:  # noqa: BLE001
            print("text refine skipped:", repr(e)[:200], file=sys.stderr)
    return final


def _lean_pdf_words(pdf: Path, page_no: int):
    """pipeline.pages.pdf_words without the drawing: the same pdfminer parse and text layout, but path and image
    painting are dropped before pdfminer builds an LTCurve/LTImage per drawing operator. Text lines are grouped from
    LTChar objects only, so the words are the same; a CAD sheet with ~100k paths no longer holds ~1 GB of curve
    objects. Returns (words, w_pt, h_pt) like pages.pdf_words."""
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.layout import LAParams, LTChar, LTFigure, LTTextContainer, LTTextLine
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage

    class TextOnly(PDFPageAggregator):
        def paint_path(self, gstate, stroke, fill, evenodd, path):
            return None

        def render_image(self, name, stream):
            return None

    words = []

    def flush(chars):
        if not chars:
            return
        txt = "".join(c.get_text() for c in chars).strip()
        if not txt:
            return
        words.append((txt, min(c.x0 for c in chars), min(c.y0 for c in chars),
                      max(c.x1 for c in chars), max(c.y1 for c in chars)))

    def walk(o):
        if isinstance(o, LTTextLine):
            cur = []
            for c in o:
                if isinstance(c, LTChar) and c.get_text().strip():
                    cur.append(c)
                else:
                    flush(cur)
                    cur = []
            flush(cur)
        elif isinstance(o, (LTTextContainer, LTFigure)) or hasattr(o, "__iter__"):
            for c in o:
                walk(c)

    rm = PDFResourceManager(caching=True)
    dev = TextOnly(rm, laparams=LAParams(char_margin=1.5, line_margin=0.3))
    interp = PDFPageInterpreter(rm, dev)
    with open(pdf, "rb") as fp:
        for i, page in enumerate(PDFPage.get_pages(fp, caching=True)):
            if i < page_no:
                continue
            interp.process_page(page)
            pg = dev.get_result()
            for o in pg:
                walk(o)
            return words, pg.width, pg.height
    raise IndexError(f"page {page_no} not in {pdf}")


REFINE_MIN_LEFT_S = 15.0  # text refine pages start only with this much ingest budget left


def _refine_page(pdf: Path, f: Path, t: dict) -> bool:
    """One page's pdfium text -> pdfminer words (atomic replace of text-<n>.json). True when replaced."""
    W, H = t["image"]["w"], t["image"]["h"]
    import pypdfium2 as pdfium
    d = pdfium.PdfDocument(str(pdf))
    w_pt, _ = d[t["page"] - 1].get_size()
    d.close()
    s = W / w_pt
    try:
        raw, pw, ph = _lean_pdf_words(pdf, t["page"] - 1)
    except Exception as e:  # noqa: BLE001  pdfminer internals moved: the stock reader
        print("lean pdfminer words failed, full reader:", repr(e)[:160], file=sys.stderr)
        from pipeline import pages
        raw, pw, ph = pages.pdf_words(pdf, t["page"] - 1, s, W, H)
    words = []
    for tx, x0, y0, x1, y1 in raw:
        bx = [round(max(0, min(v, lim)), 1) for v, lim in zip((x0 * s, (ph - y1) * s, x1 * s, (ph - y0) * s), (W, H, W, H))]
        words.append({"text": tx, "bbox_px": bx})
    if not words:
        return False
    # guard: the refine must not shred the text layer (glyph-by-glyph words break viewer search and labels); keep the
    # pdfium words when pdfminer's result has clearly more single-character words than they do
    old = t.get("words") or []
    if old:
        one = lambda ws: sum(1 for w in ws if len(str(w.get("text", "")).strip()) <= 1)
        if one(words) > max(2 * one(old), 0.25 * len(words)) and len(words) > 1.3 * len(old):
            print(f"text refine kept pdfium words: pdfminer split {len(words)} vs {len(old)}", file=sys.stderr)
            return False
    t.update(words=words, extractor="pdfminer")
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(t, ensure_ascii=False))
    tmp.replace(f)
    return True


def refine_text(doc_id: str, ddir: Path) -> int:
    """Pages whose text came from pdfium (fast, at ingest) are re-read with pdfminer (slow, exact boxes) once the
    document is already usable. Files are replaced atomically; text.json is rebuilt. Returns pages refined.
    With an ingest budget each page runs in a forked child cut off before the deadline (a kill after "ready" would
    mark the document failed); pages not refined in time keep the pdfium words."""
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
        left = _budget_left()
        if left is not None and left < REFINE_MIN_LEFT_S:
            print(f"text refine stopped: ingest budget ({left:.0f} s left)", file=sys.stderr)
            break
        res, val = _bounded(lambda: _refine_page(pdf, f, t), None if left is None else left - 5.0)
        if res == "ok" and val:
            n += 1
        elif res == "timeout":
            f.with_suffix(".tmp").unlink(missing_ok=True)
            print("text refine stopped at the ingest budget", file=sys.stderr)
            break
        elif res == "error":
            print("text refine page skipped:", val, file=sys.stderr)
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
        from server import ifc_ingest
        return ifc_ingest.run(REPO / doc["files"]["ifc"], doc, ddir, st)

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
                _flag_vlm_fixtures(ddir, plan_pages)
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
                    ifc_notes: list = []
                    ok = st.stage("ifc_from_pdf", lambda: _pdf_via_ifc_bounded(doc_id, ddir, doc, plan_pages, ifc_notes))
                    if ifc_notes:
                        st.stages[-1]["note"] = "; ".join(ifc_notes)[:300]
                        st.write("running")
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
