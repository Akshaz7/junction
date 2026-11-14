#!/usr/bin/env python3
"""PHASE A preflight: one table of OK / MISSING / FAILED for paths, tools,
logins, disk, machine, iPhone and keys. Stdlib only."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()
EXTRA_PATH = [str(HOME / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin"]
os.environ["PATH"] = os.pathsep.join(EXTRA_PATH + [os.environ.get("PATH", "")])

rows: list[tuple[str, str, str, str]] = []


def add(group: str, name: str, status: str, note: str = "") -> None:
    rows.append((group, name, status, note.strip().replace("\n", " ")[:90]))


def run(cmd: list[str] | str, timeout: int = 20, **kw) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           shell=isinstance(cmd, str), **kw)
        return p.returncode, (p.stdout + p.stderr).strip()
    except FileNotFoundError:
        return 127, "not found"
    except subprocess.TimeoutExpired:
        return 124, "timed out"


def tool(name: str, cmd: list[str], pattern: str | None = None, check=None) -> None:
    if not shutil.which(cmd[0]):
        add("Tools", name, "MISSING")
        return
    code, out = run(cmd)
    if code != 0:
        add("Tools", name, "FAILED", out[-90:])
        return
    ver = out.splitlines()[0] if out else ""
    if pattern:
        m = re.search(pattern, out)
        ver = m.group(0) if m else ver
    if check and not check(out):
        add("Tools", name, "FAILED", ver)
        return
    add("Tools", name, "OK", ver)


def paths() -> None:
    add("Paths", "repo", "OK" if (ROOT / ".git").exists() else "FAILED", str(ROOT))
    q = sorted((ROOT / "data").glob("**/questions.jsonl"))
    add("Paths", "dataset questions.jsonl", "OK" if q else "MISSING",
        str(q[0].relative_to(ROOT)) if q else "")
    spike = [ROOT / "out", ROOT / "scripts/extract_elements.py", ROOT / "scripts/validate_glb.py"]
    missing = [str(p.relative_to(ROOT)) for p in spike if not p.exists()]
    glbs = len(list((ROOT / "out").glob("*.glb")))
    add("Paths", "spike output", "OK" if not missing else "MISSING",
        f"{glbs} GLB in out/" if not missing else "missing " + ", ".join(missing))
    ifc = ROOT / "tools/IfcConvert"
    if not ifc.exists():
        add("Paths", "tools/IfcConvert runs", "MISSING")
    else:
        code, out = run([str(ifc), "--version"])
        add("Paths", "tools/IfcConvert runs", "OK" if code == 0 else "FAILED", out.splitlines()[0] if out else "")
    add("Paths", "refs/stoa-hero/", "OK" if (ROOT / "refs/stoa-hero/theme-tokens.css").exists() else "MISSING")
    add("Paths", "refs/stoabuild-full-text.md",
        "OK" if (ROOT / "refs/stoabuild-full-text.md").exists() else "MISSING",
        "" if (ROOT / "refs/stoabuild-full-text.md").exists() else "not found anywhere on the Mac")


def tools() -> None:
    tool("git", ["git", "--version"], r"[\d.]+")
    code, out = run(["uv", "python", "find", "3.12"])
    add("Tools", "python 3.12", "OK" if code == 0 else "MISSING", out.splitlines()[0] if code == 0 else "")
    tool("uv", ["uv", "--version"], r"[\d.]+")
    tool("node >= 20", ["node", "--version"], r"v[\d.]+",
         check=lambda o: int(re.search(r"v(\d+)", o).group(1)) >= 20)
    if not shutil.which("docker"):
        add("Tools", "docker running", "MISSING")
    else:
        code, out = run(["docker", "info", "--format", "{{.ServerVersion}}"])
        add("Tools", "docker running", "OK" if code == 0 else "FAILED", out if code == 0 else "daemon not running")
    tool("xcodebuild", ["xcodebuild", "-version"], r"Xcode [\d.]+")
    tool("xcodegen", ["xcodegen", "--version"], r"[\d.]+")
    tool("gh", ["gh", "--version"], r"[\d.]+")
    tool("vercel", ["vercel", "--version"], r"[\d.]+")
    tool("modal", ["modal", "--version"], r"[\d.]+")
    tool("codex", ["codex", "--version"], r"[\d.]+")
    tool("Aiven CLI (avn)", ["avn", "--version"], r"[\d.]+")


def codex_exec() -> None:
    if not shutil.which("codex"):
        add("Logins", "codex exec (unattended)", "MISSING")
        return
    with tempfile.TemporaryDirectory() as d:
        code, out = run(["codex", "exec", "--skip-git-repo-check", "-s", "read-only",
                         "Reply with exactly the word PONG and nothing else."], timeout=120, cwd=d,
                        stdin=subprocess.DEVNULL)
    ok = code == 0 and "PONG" in out
    add("Logins", "codex exec (unattended)", "OK" if ok else "FAILED", "" if ok else out[-90:])


def logins() -> None:
    code, out = run(["gh", "auth", "status"])
    m = re.search(r"account (\S+)", out)
    add("Logins", "gh", "OK" if code == 0 else "FAILED", m.group(1) if m else out[-60:])
    code, out = run(["vercel", "whoami"], timeout=30)
    last = next((l for l in reversed(out.splitlines()) if l.strip() and not l.startswith("<")), "")
    add("Logins", "vercel", "OK" if code == 0 else "MISSING", last if code == 0 else "run: vercel login")
    modal_ok = (HOME / ".modal.toml").exists()
    add("Logins", "modal", "OK" if modal_ok else "MISSING", "" if modal_ok else "run: modal setup")
    code, out = run(["codex", "login", "status"])
    add("Logins", "codex", "OK" if code == 0 else "MISSING", out.splitlines()[-1] if out else "")
    codex_exec()
    code, out = run(["avn", "user", "info", "--json"], timeout=30)
    add("Logins", "aiven", "OK" if code == 0 else "MISSING", "" if code == 0 else "run: avn user login <email> --token")


def disk_machine() -> None:
    free = shutil.disk_usage(str(ROOT)).free / 1e9
    add("Disk", "free >= 60 GB", "OK" if free >= 60 else "FAILED", f"{free:.0f} GB free")
    _, chip = run(["sysctl", "-n", "machdep.cpu.brand_string"])
    _, mem = run(["sysctl", "-n", "hw.memsize"])
    _, osv = run(["sw_vers", "-productVersion"])
    gb = int(mem) / 2**30 if mem.isdigit() else 0
    add("Machine", "chip / memory / macOS", "OK" if "M4" in chip else "FAILED", f"{chip}, {gb:.0f} GB, macOS {osv}")


def iphone() -> None:
    code, out = run(["xcrun", "devicectl", "list", "devices"], timeout=30)
    phones = [l for l in out.splitlines() if "iPhone" in l]
    connected = [l for l in phones if re.search(r"connected|available \(paired\)", l, re.I)]
    if connected:
        add("iPhone", "connected, trusted device", "OK", re.sub(r"\s+", " ", connected[0])[:90])
    elif phones:
        add("iPhone", "connected, trusted device", "FAILED", "paired but not connected: " + re.sub(r"\s+", " ", phones[0])[:60])
    else:
        add("iPhone", "connected, trusted device", "MISSING", "plug in, unlock, Trust, enable Developer Mode")


def keys() -> None:
    code, out = run([sys.executable, str(ROOT / "scripts/check_keys.py")], timeout=180)
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2:
            add("Keys", parts[0], parts[1], parts[2] if len(parts) > 2 else "")


def main() -> None:
    paths(); tools(); logins(); disk_machine(); iphone(); keys()
    w1 = max(len(r[0]) for r in rows); w2 = max(len(r[1]) for r in rows)
    print(f"{'Group':<{w1}}  {'Check':<{w2}}  {'Status':<8} Note")
    print("-" * (w1 + w2 + 30))
    for g, n, s, note in rows:
        print(f"{g:<{w1}}  {n:<{w2}}  {s:<8} {note}")
    bad = [r for r in rows if r[2] in ("MISSING", "FAILED") and r[0] != "Keys"]
    print(f"\n{len(bad)} non-key items need attention.")


if __name__ == "__main__":
    main()
