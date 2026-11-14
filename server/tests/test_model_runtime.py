"""S-28: deployment caps, best-effort cost logging and runtime artifact roots.

All document contents here are generated for demo test fixtures.
"""
import json
from pathlib import Path

import pytest

from engine import advisor, findings
from engine.models import core
from server import config


def test_image_copies_caps_and_selects_the_same_file(monkeypatch):
    repo = Path(__file__).resolve().parents[2]
    dockerfile = (repo / "deploy" / "Dockerfile").read_text()
    assert "COPY COSTS.md /app/COSTS.md" in dockerfile
    assert "ENV MODELS_COSTS_MD=/app/COSTS.md" in dockerfile
    monkeypatch.setenv("MODELS_COSTS_MD", str(repo / "COSTS.md"))
    assert core.caps(), "the copied COSTS.md must contain recognised USD caps"


@pytest.mark.parametrize("failure", ["mkdir", "open"])
def test_cost_log_oserror_still_logs_to_database(tmp_path, monkeypatch, failure):
    if failure == "mkdir":
        parent = tmp_path / "file"
        parent.write_text("not a directory")
        path = parent / "costs.jsonl"
    else:
        path = tmp_path  # opening a directory for append raises OSError
    monkeypatch.setenv("MODELS_COSTS_LOG", str(path))
    records = []
    monkeypatch.setattr(core, "_db_logger", records.append)
    core._log(core.Result(text="paid answer", provider="gemini", task="advise", cost_usd=0.01))
    assert len(records) == 1 and records[0]["cost_usd"] == 0.01
    assert "text" not in records[0]


def test_findings_and_advisor_use_server_artifacts_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path / "runtime-artifacts"))
    did = "test__runtime-root"
    directory = config.artifacts_dir() / did
    directory.mkdir(parents=True)
    (directory / "elements.json").write_text(json.dumps({
        "elements": [{"item_id": "door-001", "kind": "door", "storey": {"name": "L1"},
                      "quantities": {"width_m": 0.7, "height_m": 2.1},
                      "bbox_m": [[0, 0, 0], [0.7, 2.1, 0.1]]}],
        "storeys": [{"name": "L1", "elevation_m": 0}]}))
    fs = findings.run(did)
    assert any(f["check_id"] == "door_clear_width" and f["severity"] == "fail" for f in fs)
    cards = advisor.advise(did)
    assert cards and cards[0]["item_ids"] == ["door-001"]
    # Explicit callers' roots still take precedence; empty env uses the original default.
    assert findings.run(did, root=tmp_path) == []
    assert advisor.advise(did, root=tmp_path) == []
    monkeypatch.setenv("ARTIFACTS_DIR", "")
    monkeypatch.setattr(findings, "ARTIFACTS", directory.parent)
    monkeypatch.setattr(advisor, "ARTIFACTS", directory.parent)
    assert findings.run(did) == fs
    assert advisor.advise(did) == cards
