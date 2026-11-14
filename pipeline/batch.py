"""D-11: resumable batch runner (LONG). Stages per doc, each with a marker so a rerun skips finished work:
pages -> (IFC) scene, plans -> (swiss DXF) planmap -> extrude -> usdz.

Phase A: non-IFC docs, pool of <=3 niced workers.  Phase B: IFC docs, one at a time, smallest first
(IfcConvert itself goes through scripts/heavy.sh).  Run the whole thing as:
    scripts/heavy.sh uv run python -m pipeline.batch [--root DIR] [--build-registry] [--only ID...] [-j 3]
Failures: results/batch_failures.jsonl (doc, stage, reason).  Progress: results/batch_progress.md.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RESULTS = REPO / "results"


def _mark(art: Path, stage: str, status: str):
    (art / f".done-{stage}").write_text(status)


def _done(art: Path, stage: str) -> bool:
    return (art / f".done-{stage}").exists()


def run_doc(args):
    """Returns (doc_id, [(stage, status, reason)])."""
    root, artroot, d, force = args
    did = d["doc_id"]
    art = artroot / did
    art.mkdir(exist_ok=True)
    out = []
    fmts = set(d["formats"])
    is_ifc = "ifc" in fmts

    def stage(name, fn, applies=True):
        if not applies:
            return True
        if _done(art, name) and not force:
            out.append((name, "cached", ""))
            return True
        try:
            r = fn()
            if isinstance(r, tuple):  # pages.process style (doc_id, status)
                r = r[1]
            if isinstance(r, str) and (r.startswith("skip") or r.startswith("error")):
                st = "skip" if r.startswith("skip") else "fail"
                _mark(art, name, r) if st == "skip" else None
                out.append((name, st, r))
                return st == "skip"
            _mark(art, name, "ok")
            out.append((name, "ok", ""))
            return True
        except Exception as e:  # noqa: BLE001
            out.append((name, "fail", f"{type(e).__name__}: {e}"[:300]))
            return False

    from pipeline import dxf_planmap, extrude, ifc_plans, ifc_scene, pages, usdz
    if is_ifc:
        ifc = root / d["files"]["ifc"]
        ok = stage("scene", (lambda: "skip: IFC stub (<10 KB), cannot convert") if ifc.stat().st_size < 10_000
                   else (lambda: ifc_scene.process(ifc, d, art)))
        if ok and (art / "elements.json").exists():
            stage("plans", lambda: ifc_plans.process(did, artroot))
    else:
        stage("pages", lambda: pages.process((root, artroot, d)))
    if d["source"] == "swiss_dwellings" and "dxf" in fmts and (art / "pages.json").exists():
        stage("planmap", lambda: dxf_planmap.process(did, art, root / d["files"]["dxf"]))
    if (art / "planmap-1.json").exists() and not (art / "elements.json").exists():
        stage("extrude", lambda: extrude.process(did, art))
    if (art / "scene.glb").exists() and (art / "scene.json").exists():
        sc_stage = "usdz"
        # redo usdz when the glb is newer than the usdz (e.g. VISION planmap arrived, extrude re-ran)
        u = art / "scene.usdz"
        if u.exists() and u.stat().st_mtime < (art / "scene.glb").stat().st_mtime:
            (art / ".done-usdz").unlink(missing_ok=True)
        stage(sc_stage, lambda: usdz.process(did, art))
    return did, out


def _init():
    os.nice(10)


def progress(counter: Counter, total: int, t0: float, phase: str):
    RESULTS.mkdir(exist_ok=True)
    done = sum(v for k, v in counter.items() if k[1] in ("ok", "cached", "skip"))
    lines = [f"# D-11 batch progress", f"updated {time.strftime('%Y-%m-%d %H:%M:%S')}  phase: {phase}",
             f"docs processed: {counter['_docs']}/{total}  elapsed {int(time.time() - t0)} s", "",
             "| stage | ok | cached | skip | fail |", "|---|---|---|---|---|"]
    for s in ("pages", "scene", "plans", "planmap", "extrude", "usdz"):
        lines.append(f"| {s} | " + " | ".join(str(counter[(s, k)]) for k in ("ok", "cached", "skip", "fail")) + " |")
    (RESULTS / "batch_progress.md").write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(REPO / "data" / "junction-dataset-preview"))
    ap.add_argument("--artifacts", default=str(REPO / "artifacts"))
    ap.add_argument("--build-registry", action="store_true")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("-j", type=int, default=3)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    root, artroot = Path(a.root), Path(a.artifacts)
    if a.build_registry:
        from pipeline import registry
        docs, _ = registry.build(root, artroot, count_pages=False)
        print(f"registry: {len(docs)} docs", flush=True)
    docs = [json.loads(l) for l in open(artroot / "registry.jsonl")]
    if a.only:
        docs = [d for d in docs if d["doc_id"] in set(a.only)]
    if a.limit:
        docs = docs[:a.limit]
    plain = [d for d in docs if "ifc" not in d["formats"]]
    ifcs = sorted((d for d in docs if "ifc" in d["formats"]), key=lambda d: (root / d["files"]["ifc"]).stat().st_size)
    t0 = time.time()
    counter: Counter = Counter()
    RESULTS.mkdir(exist_ok=True)
    fails = open(RESULTS / "batch_failures.jsonl", "a")

    def absorb(did, res, phase):
        counter["_docs"] += 1
        for st, status, reason in res:
            counter[(st, status)] += 1
            if status == "fail":
                fails.write(json.dumps({"doc_id": did, "stage": st, "reason": reason, "t": time.strftime("%F %T")}) + "\n")
                fails.flush()
        if counter["_docs"] % 25 == 0:
            progress(counter, len(docs), t0, phase)

    with Pool(max(1, min(a.j, 3)), initializer=_init) as p:
        for did, res in p.imap_unordered(run_doc, [(root, artroot, d, a.force) for d in plain], chunksize=4):
            absorb(did, res, "A: non-IFC")
    progress(counter, len(docs), t0, "B: IFC")
    for d in ifcs:  # one at a time, smallest first
        try:
            did, res = run_doc((root, artroot, d, a.force))
        except Exception:  # noqa: BLE001
            did, res = d["doc_id"], [("scene", "fail", traceback.format_exc()[-300:])]
        absorb(did, res, "B: IFC")
    progress(counter, len(docs), t0, "done")
    print((RESULTS / "batch_progress.md").read_text())


if __name__ == "__main__":
    main()
