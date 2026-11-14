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


def phase(stage, source, out, timeout):
    budget = _budget()
    env = {**os.environ, "IFC_WORKER_MEMORY_BYTES": str(budget), "IFC_CONVERT_THREADS": "1",
           "IFC_CONVERT_PY": "1", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
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


def run(source, doc, out, status):
    cap = float(os.environ.get("INGEST_IFC_MAX_MB", str(100 * 1024**2 / 1e6)))
    size = source.stat().st_size / 1e6
    if size > cap:
        status.write("failed", f"This IFC is {size:.1f} MB; this server indexes IFC files up to {cap:g} MB. "
                              "The original is stored. Split the model into smaller IFC files and upload them separately.")
        return "failed"

    def stage(name, timeout):
        metrics = {}
        def execute():
            try:
                metrics.update(phase(name, source, out, timeout))
            except PhaseFailure as exc:
                metrics.update(exc.metrics)
                raise
        ok = status.stage(name, execute)
        status.stages[-1].update(metrics)
        return ok

    if not stage("ifc_index", 90):
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
