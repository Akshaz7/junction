#!/usr/bin/env python3
"""One-screen status for the LEAD loop: time, rows by status, worker processes,
log freshness, memory pressure, swap, disk. Stdlib only. Runs in a few seconds.

Exit code 0 always; flags lines that need action with '!!'.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKERS = ["DATA", "VISION", "ENGINE", "SERVER", "WEB", "3D", "IOS"]
STUCK_MIN = 15
SWAP_LIMIT_GB = 8.0
DISK_MIN_GB = 15.0


def sh(cmd: list[str], timeout: int = 10) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def rows() -> tuple[Counter, dict[str, list[str]]]:
    counts: Counter = Counter()
    by_status: dict[str, list[str]] = {}
    tasks = ROOT / "TASKS.md"
    if not tasks.exists():
        return counts, by_status
    for line in tasks.read_text().splitlines():
        m = re.match(r"^\| ([A-Z]-\d+) \|", line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        status = cells[-2] if len(cells) >= 2 else "?"
        counts[status] += 1
        by_status.setdefault(status, []).append(m.group(1))
    return counts, by_status


def processes() -> list[str]:
    out = sh(["ps", "-Ao", "pid,etime,command"])
    keep = []
    for line in out.splitlines()[1:]:
        if re.search(r"codex exec|claude .*-p |claude --print|heavy\.sh|IfcConvert|xcodebuild|engine\.bench|modal run|playwright", line) \
                and "pulse.py" not in line and "grep" not in line:
            keep.append(line.strip()[:160])
    return keep


def log_age() -> list[str]:
    lines = []
    now = time.time()
    for w in WORKERS:
        p = ROOT / "logs" / f"{w}.log"
        if p.exists():
            age = (now - p.stat().st_mtime) / 60
            flag = "!! " if age > STUCK_MIN else ""
            lines.append(f"{flag}{w}: log {age:.0f} min old")
        else:
            lines.append(f"{w}: no log")
    return lines


def memory() -> tuple[str, float]:
    mp = sh(["memory_pressure"], 15)
    m = re.search(r"System-wide memory free percentage:\s*(\d+)%", mp)
    free_pct = f"{m.group(1)}% free" if m else "unknown"
    sw = sh(["sysctl", "vm.swapusage"])
    m2 = re.search(r"used = ([\d.]+)([MG])", sw)
    swap_gb = 0.0
    if m2:
        swap_gb = float(m2.group(1)) / (1024 if m2.group(2) == "M" else 1)
    return free_pct, swap_gb


def keys_summary() -> str:
    p = ROOT / "results" / "keys.json"
    if not p.exists():
        return "keys: not checked yet"
    d = json.loads(p.read_text())
    c = Counter(v["status"] for v in d["keys"].values())
    age = (time.time() - p.stat().st_mtime) / 60
    flag = "!! " if age > 10 else ""
    return f"{flag}keys ({age:.0f} min ago): " + ", ".join(f"{k} {v}" for k, v in sorted(c.items()))


def main() -> None:
    print(f"== pulse {time.strftime('%a %d %b %H:%M:%S %Z')}")
    counts, by_status = rows()
    print("rows: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    for s in ("doing", "blocked", "blocked-human"):
        if by_status.get(s):
            print(f"  {s}: {' '.join(by_status[s])}")
    procs = processes()
    print(f"worker/heavy processes: {len(procs)}")
    for p in procs:
        print("  " + p)
    for line in log_age():
        print("  " + line)
    free_pct, swap_gb = memory()
    flag = "!! " if swap_gb > SWAP_LIMIT_GB else ""
    print(f"{flag}memory: {free_pct}, swap used {swap_gb:.1f} GB" +
          (" -> pause LONG jobs, start no heavy job" if flag else ""))
    disk_gb = shutil.disk_usage(str(ROOT)).free / 1e9
    flag = "!! " if disk_gb < DISK_MIN_GB else ""
    print(f"{flag}disk free: {disk_gb:.0f} GB" +
          (" -> pause D-11, clear artifacts/**/tmp and DerivedData" if flag else ""))
    heavy = list(Path("/tmp/junction-heavy").glob("slot*")) + \
        list(Path(subprocess.os.environ.get("TMPDIR", "/tmp"), "junction-heavy").glob("slot*"))
    print(f"heavy slots in use: {len(set(heavy))}/2")
    print(keys_summary())


if __name__ == "__main__":
    main()
