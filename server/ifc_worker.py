"""One disposable IFC phase. The supervisor enforces RSS/time; Linux also limits allocations."""
import json
import os
import resource
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _allocation_limit():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if sys.platform != "linux":
        return
    # Account for shared library mappings (OCC/numpy) already loaded: RLIMIT_AS
    # alone at 320 MiB would reject libraries even when resident memory is small.
    pages = [int(x) * os.sysconf("SC_PAGE_SIZE") for x in Path("/proc/self/statm").read_text().split()[:2]]
    virtual, resident = pages
    budget = int(os.environ["IFC_WORKER_MEMORY_BYTES"])
    ceiling = virtual + max(0, budget - resident)
    resource.setrlimit(resource.RLIMIT_AS, (ceiling, ceiling))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def run(stage, source, output):
    out, src = Path(output), Path(source)
    doc = json.loads((out / "doc.json").read_text())
    if stage == "ifc_index":
        from pipeline import ifc_index
        _allocation_limit()
        return ifc_index.process(src, doc, out)
    if stage == "ifc_scene":
        # Load shared libraries before setting the native allocation guard.
        import trimesh  # noqa: F401

        from pipeline import ifc_glb, ifc_scene  # noqa: F401
        _allocation_limit()
        return ifc_scene.process(src, doc, out)
    if stage == "ifc_plans":
        from pipeline import ifc_plans
        _allocation_limit()
        return ifc_plans.process(doc["doc_id"], out.parent)
    if stage == "usdz":
        import importlib.util

        from server.ingest_job import _usdz
        if importlib.util.find_spec("pxr"):
            from pipeline import usdz  # noqa: F401
        _allocation_limit()
        return _usdz(doc["doc_id"], out)
    raise ValueError("Unknown IFC phase")


if __name__ == "__main__":
    try:
        result = run(*sys.argv[1:])
        print(json.dumps({"ok": True, "result": result}), flush=True)
    except Exception as exc:  # noqa: BLE001 - isolated worker reports every failure to its supervisor
        print(json.dumps({"ok": False, "detail": str(exc)[:500] or type(exc).__name__}), flush=True)
        sys.exit(1)
