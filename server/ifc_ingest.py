"""Index first, then attempt 3D in bounded, disposable processes.

The API's existing background ingest task owns the outer heavy slot. Each phase
releases its native memory before the next phase starts. The index survives a
geometry timeout, allocation failure, or process kill.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

INDEX_DETAIL = ("The 3D view is still being prepared. Counts and quantities stored in the model are available; "
                "measurements that require geometry are not available yet.")
PARTIAL_DETAIL = ("Counts and quantities stored in the model are available. "
                  "Measurements that require geometry may be unavailable.")


class PhaseFailure(RuntimeError):
    def __init__(self, detail, metrics):
        super().__init__(detail)
        self.metrics = metrics


def _rss(pid):
    if sys.platform == "linux":
        try:
            return int(Path(f"/proc/{pid}/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
        except (OSError, IndexError):
            return 0
    result = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, check=False)
    return int(result.stdout.strip() or "0") * 1024


def _budget():
    cap = int(float(os.environ.get("IFC_WORKER_MEMORY_MB", "320")) * 1024**2)
    # Leave room for the live API and supervisor in the actual container. Honour
    # a smaller cgroup allocation without relying on its plan's marketing name.
    root = Path("/sys/fs/cgroup")
    try:
        maximum = int((root / "memory.max").read_text())
        current = int((root / "memory.current").read_text())
        cap = min(cap, maximum - current - 64 * 1024**2)
    except (OSError, ValueError):
        pass
    if cap < 96 * 1024**2:
        raise RuntimeError("The server has insufficient free memory for this IFC phase. Try again when other uploads finish.")
    return cap


def phase(stage, source, out, timeout, index_offset=0):
    budget = _budget()
    env = {**os.environ, "IFC_WORKER_MEMORY_BYTES": str(budget), "IFC_CONVERT_THREADS": "1",
           "IFC_CONVERT_PY": "1", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
           "IFC_INDEX_OFFSET": str(index_offset)}
    tmp = out / "tmp"
    tmp.mkdir(exist_ok=True)
    log = tmp / f"{stage}.log"
    peak, reason = 0, None
    with log.open("w") as target:
        proc = subprocess.Popen([sys.executable, str(Path(__file__).with_name("ifc_worker.py")),
                                 stage, str(source), str(out)],
                                env=env, stdout=target, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        start = time.monotonic()
        try:
            while proc.poll() is None:
                peak = max(peak, _rss(proc.pid))
                if peak > budget:
                    reason = f"This phase exceeded its {budget / 1024**2:.0f} MiB memory budget."
                    break
                if time.monotonic() - start > timeout:
                    reason = f"This phase exceeded its {timeout:g} second time limit."
                    break
                time.sleep(.1)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
    # Only a small final JSON record is read; native diagnostics stay on disk.
    with log.open("rb") as handle:
        handle.seek(max(0, log.stat().st_size - 2048))
        lines = handle.read().decode(errors="replace").splitlines()
    record = {}
    for line in reversed(lines):
        try:
            record = json.loads(line)
            if isinstance(record, dict) and "ok" in record:
                break
        except ValueError:
            continue
    metrics = {"peak_worker_rss_mib": round(peak / 1024**2, 1), "memory_budget_mib": round(budget / 1024**2, 1), "worker_exit_code": proc.returncode}
    if reason or proc.returncode:
        detail = reason or record.get("detail") or "The 3D converter stopped before completing; it may have reached the server memory limit."
        raise PhaseFailure(detail, metrics)
    return metrics


def index(source, doc, out, timeout):
    """Discard native property caches after each batch, publish only a complete index.

    Every child reopens the same read-only file lazily, ordered by STEP id. The
    final JSON is streamed to disk; no process retains all parsed property sets.
    """
    work = out / "tmp" / "property-index"
    work.mkdir(parents=True, exist_ok=True)
    (work / "doc.json").write_text(json.dumps(doc))
    assembled = out / "tmp" / "complete-elements.json"
    offset, total, seen, first = 0, None, set(), True
    start = time.monotonic()
    metrics = {"peak_worker_rss_mib": 0, "memory_budget_mib": 0, "worker_exit_code": 0, "batches": 0}
    with assembled.open("w") as target:
        while total is None or offset < total:
            remaining = timeout - (time.monotonic() - start)
            if remaining <= 0:
                raise RuntimeError(f"Property indexing exceeded its {timeout:g} second time limit.")
            result = phase("ifc_index", source, work, remaining, index_offset=offset)
            metrics["peak_worker_rss_mib"] = max(metrics["peak_worker_rss_mib"], result.get("peak_worker_rss_mib", 0))
            metrics["memory_budget_mib"] = result.get("memory_budget_mib", 0)
            metrics["batches"] += 1
            part = json.loads((work / "elements.json").read_text())
            elements = part.pop("elements")
            if total is None:
                total = part.pop("total_elements", len(elements))
                part.pop("indexed_offset", None)
                target.write(json.dumps(part, ensure_ascii=False)[:-1] + ',"elements":[')
            if not elements and offset < total:
                raise RuntimeError("The IFC property reader stopped before indexing every object.")
            for element in elements:
                gid = element["item_id"]
                if not gid or gid in seen:
                    raise RuntimeError("The IFC has missing or duplicate object identifiers. Export the model again as IFC.")
                seen.add(gid)
                if not first:
                    target.write(",")
                json.dump(element, target, ensure_ascii=False)
                first = False
            offset += len(elements)
        target.write("]}")
    assembled.replace(out / "elements.json")
    return metrics


def run(source, doc, out, status):
    cap = float(os.environ.get("INGEST_IFC_MAX_MB", str(100 * 1024**2 / 1e6)))
    size = source.stat().st_size / 1e6
    if size > cap:
        status.write("failed", f"This IFC is {size:.1f} MB; this server indexes IFC files up to {cap:g} MB. "
                              "The original is stored. Split the model into smaller IFC files and upload them separately.")
        return "failed"

    # Leave 30 seconds for persistence and the enclosing five-minute watchdog.
    deadline = time.monotonic() + max(0, 270 - (time.time() - status.started_at))

    def stage(name, timeout):
        metrics = {}
        def execute():
            try:
                remaining = min(timeout, deadline - time.monotonic())
                if remaining <= 0:
                    raise RuntimeError("This phase exceeded the upload processing time budget.")
                metrics.update(index(source, doc, out, remaining) if name == "ifc_index" else phase(name, source, out, remaining))
            except PhaseFailure as exc:
                metrics.update(exc.metrics)
                raise
        ok = status.stage(name, execute)
        status.stages[-1].update(metrics)
        return ok

    if not stage("ifc_index", float(os.environ.get("IFC_INDEX_TIMEOUT_S", "180"))):
        status.write("failed", "The IFC properties could not be indexed. Export the model again as IFC. " + status.stages[-1]["error"])
        return "failed"
    status.readable = True
    status.write("running", INDEX_DETAIL)
    status.detail = INDEX_DETAIL
    if not stage("ifc_scene", float(os.environ.get("IFC_SCENE_TIMEOUT_S", "120"))):
        status.write("partial", "The 3D view could not be prepared. " + PARTIAL_DETAIL + " " + status.stages[-1]["error"])
        return "partial"
    status.detail = "The 3D view and model quantities are ready. Preparing drawing previews and AR."
    status.write("running", status.detail)
    plans = stage("ifc_plans", 45)
    if plans and (out / "pages.json").is_file():
        doc["pages"] = len(json.loads((out / "pages.json").read_text())["pages"])
        (out / "doc.json").write_text(json.dumps(doc, indent=1))
    ar = stage("usdz", 30) if plans else False
    final = "ready" if plans and ar else "partial"
    detail = "" if final == "ready" else ("The 3D view and model quantities are available. Drawing previews or AR could not be prepared. "
                                             + status.stages[-1].get("error", ""))
    status.detail = ""
    status.write(final, detail)
    return final
