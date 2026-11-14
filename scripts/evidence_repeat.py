"""One scratch-merge audit, or repeated audits every 45 minutes until stopped.

Only detached worktrees below this worker's .evqa-scratch are mutated. Conflicts
are recorded, never resolved by guessing. Each run appends its factual status to
the assigned handoff. Each audit goes through scripts/heavy.sh; the driver never
holds a heavy slot while waiting between runs.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCHES = ("final/calc", "final/scaleproof", "final/xcheck", "final/evfix")
HANDOFF = Path("/Users/akshatthapa/Workspace/junction/handoff/F-EVQA.md")


def git(*args, cwd=ROOT, check=True):
    return subprocess.run(["git", "-C", str(cwd), *args], text=True, capture_output=True, check=check)


def once(limit, handoff=HANDOFF, final_blind=False, branches=BRANCHES):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    print(datetime.now().astimezone().isoformat(), flush=True)
    scratch = ROOT / ".evqa-scratch" / stamp
    output_dir = ROOT / "results/final/EVQA"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"run-{stamp}.json"
    merge_path = output_dir / f"merge-{stamp}.json"
    baseline = git("rev-parse", "HEAD").stdout.strip()
    refs = {branch: git("rev-parse", branch, check=False).stdout.strip() for branch in branches}
    metadata = {"created_at": datetime.now(UTC).isoformat(), "baseline": baseline,
                "branches": refs, "merges": [], "complete_merge": False, "audit_report": report_path.name}
    git("worktree", "add", "--detach", str(scratch), baseline)
    try:
        for branch, revision in refs.items():
            if not revision:
                metadata["merges"].append({"branch": branch, "status": "missing"})
                break
            result = git("merge", "--no-edit", "-m", f"F-EVQA: scratch audit merge of {branch}", revision, cwd=scratch, check=False)
            if result.returncode:
                conflicts = git("diff", "--name-only", "--diff-filter=U", cwd=scratch).stdout.splitlines()
                metadata["merges"].append({"branch": branch, "revision": revision, "status": "conflict", "files": conflicts})
                git("merge", "--abort", cwd=scratch, check=False)
                break
            metadata["merges"].append({"branch": branch, "revision": revision, "status": "merged"})
        metadata["complete_merge"] = len(metadata["merges"]) == len(refs) and all(r["status"] == "merged" for r in metadata["merges"])
        metadata["all_four_evidence_branches"] = metadata["complete_merge"] and set(refs) == set(BRANCHES)
        metadata["scratch_revision"] = git("rev-parse", "HEAD", cwd=scratch).stdout.strip()
        merge_path.write_text(json.dumps(metadata, indent=1) + "\n")
        # All data reads use the worker's existing symlinks. Engine caches and
        # JSON modifications are isolated by evidence_check's artifact overlay.
        for name in ("artifacts", "data", ".venv", "weights", "refs", "tools"):
            source = ROOT / name
            if source.exists() and not (scratch / name).exists():
                (scratch / name).symlink_to(source.resolve(), target_is_directory=True)
        cmd = [str(ROOT / "scripts/heavy.sh"), sys.executable, str(ROOT / "scripts/evidence_check.py"), "--repo", str(scratch),
               "--artifacts", str(ROOT / "artifacts"), "--limit", str(limit), "--output", str(report_path),
               "--blind", str(output_dir / "blind.json")]
        if not final_blind:
            cmd.append("--defer-blind")
        metadata["audit_exit"] = subprocess.run(cmd, cwd=scratch, check=False).returncode
        if report_path.exists():
            report = json.loads(report_path.read_text())
            report["scratch_merge"] = metadata
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1, allow_nan=False) + "\n")
            summary = report["summary"]
            message = f"STATUS F-EVQA {stamp}: scratch merge {'complete' if metadata['complete_merge'] else 'INCOMPLETE'}; {summary['questions']} questions; {summary['statuses']}; ${summary['cost_usd']:.2f}; results/final/EVQA/{report_path.name}."
        else:
            message = f"STATUS F-EVQA {stamp}: audit could not produce a report (exit {metadata['audit_exit']}); merge details {merge_path.name}."
        merge_path.write_text(json.dumps(metadata, indent=1) + "\n")
        with handoff.open("a") as stream:
            stream.write("\n" + message + "\n")
        print(message, flush=True)
        return metadata["audit_exit"] if metadata["complete_merge"] else 2
    finally:
        # This path was created by this invocation. Never remove other workers.
        git("worktree", "remove", "--force", str(scratch), check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", help="keep auditing until interrupted")
    parser.add_argument("--interval", type=float, default=2700, help="seconds between start times (default 45 min)")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--final-blind", action="store_true", help="test the reserved document once, at final validation")
    parser.add_argument("--branch", action="append", choices=BRANCHES, help="isolate a branch for diagnosis; default merges all four")
    args = parser.parse_args()
    if args.interval < 60 or args.limit < 1:
        parser.error("interval must be at least 60 seconds and limit positive")
    if args.final_blind and args.watch:
        parser.error("the blind document is tested once, not in watch mode")
    while True:
        start = time.monotonic()
        code = once(args.limit, final_blind=args.final_blind, branches=tuple(args.branch or BRANCHES))
        if not args.watch:
            return code
        remaining = max(0, args.interval - (time.monotonic() - start))
        while remaining:
            time.sleep(min(30, remaining))
            remaining = max(0, args.interval - (time.monotonic() - start))


if __name__ == "__main__":
    raise SystemExit(main())
