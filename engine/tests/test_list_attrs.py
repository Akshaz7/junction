"""List-with-attributes questions return a cited table, and a trailing 'highlight' does not turn them into a scene command."""
from pathlib import Path

import pytest

DOC = "ifc_bench__ac20-arc"
pytestmark = pytest.mark.skipif(not (Path(__file__).resolve().parents[2] / "artifacts" / DOC / "doc.json").exists(), reason="local artifacts")


@pytest.mark.parametrize("q", [
    "list fire doors with their widths and fire ratings",
    "judge-fire-IFC: Count the doors and list each door name, width in mm, and fire-resistance rating. Show source element IDs and highlight the doors."])
def test_doors_table_with_width_and_rating(q, monkeypatch):
    monkeypatch.setenv("MODELS_FAKE", "1")
    from engine.answer import answer
    r = answer(q, [DOC])
    t = r["answer"]["text_md"]
    assert "| Width |" in t and "| Fire rating |" in t and "1000 mm" in t and "Not recorded" in t
    assert not t.startswith("**Highlighted") and len(r["citations"]) >= 15
    assert all(c["item_ids"] for c in r["citations"][:15])
