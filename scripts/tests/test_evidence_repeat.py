"""Generated git responses: scratch failures must remain explicit and isolated."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location("evidence_repeat", Path(__file__).parents[1] / "evidence_repeat.py")
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)


@pytest.mark.parametrize("conflict", [False, True])
def test_scratch_audit_records_conflict_without_resolving_it(tmp_path, monkeypatch, conflict):
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    handoff = tmp_path / "handoff.md"
    calls = []
    scratch_paths = []

    def fake_git(*args, cwd=None, check=True):
        calls.append((args, cwd))
        result = SimpleNamespace(returncode=0, stdout="", stderr="")
        if args[0] == "rev-parse":
            result.stdout = args[1] + "-revision\n"
        elif args[:2] == ("worktree", "add"):
            scratch = Path(args[-2])
            scratch.mkdir(parents=True)
            scratch_paths.append(scratch)
        elif args[0] == "merge" and args[-1] == "final/evfix-revision" and conflict:
            result.returncode = 1
        elif args[0] == "diff":
            result.stdout = "engine/reasoning.py\nengine/reasoning_parts/confidence.py\n"
        return result

    def fake_run(cmd, **kwargs):
        assert cmd[0] == str(tmp_path / "scripts/heavy.sh")
        assert kwargs["cwd"] in scratch_paths
        output = Path(cmd[cmd.index("--output") + 1])
        output.write_text(json.dumps({"summary": {"questions": 199, "statuses": {"fail": 5, "pass": 194}, "cost_usd": 0}}))
        assert "--defer-blind" in cmd
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(driver, "git", fake_git)
    monkeypatch.setattr(driver.subprocess, "run", fake_run)
    assert driver.once(200, handoff) == (2 if conflict else 1)
    metadata = json.loads(next((tmp_path / "results/final/EVQA").glob("merge-*.json")).read_text())
    assert metadata["complete_merge"] is not conflict
    assert metadata["all_four_evidence_branches"] is not conflict
    assert bool([args for args, _ in calls if args == ("merge", "--abort")]) is conflict
    assert all(p.is_relative_to(tmp_path / ".evqa-scratch") for p in scratch_paths)
    assert calls[-1][0][:3] == ("worktree", "remove", "--force")
    assert ("INCOMPLETE" in handoff.read_text()) is conflict


def test_cleanup_own_scratch_when_audit_process_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    calls = []

    def fake_git(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("worktree", "add"):
            Path(args[-2]).mkdir(parents=True)
        return SimpleNamespace(returncode=0, stdout="revision\n", stderr="")

    def failed_audit(*args, **kwargs):
        raise OSError("generated for demo: executable unavailable")

    monkeypatch.setattr(driver, "git", fake_git)
    monkeypatch.setattr(driver.subprocess, "run", failed_audit)
    with pytest.raises(OSError):
        driver.once(200, tmp_path / "handoff.md")
    assert calls[-1][:3] == ("worktree", "remove", "--force")
