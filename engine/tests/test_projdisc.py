"""F-PROJDISC: when same-building drawings disagree, the sheet whose discipline owns the kind is the source."""
import json
import shutil
from pathlib import Path

import pytest

F = "ifc_models__kit-fzk-haus-ac20-fzk-haus"
ARK = "uploads__ark-103-03-floor-plan-ground-floor-test"
VENT = "uploads__l30301-ventilation-systems-ground-floor-test"
SRC = Path(__file__).resolve().parents[2] / "artifacts" / F


def _sheet(root, did, title, keep_doors):
    shutil.copytree(SRC, root / did)
    d = json.loads((root / did / "doc.json").read_text())
    d.update(doc_id=did, title=title, kind="pdf", formats=["pdf", "ifc"])
    (root / did / "doc.json").write_text(json.dumps(d))
    e = json.loads((root / did / "elements.json").read_text())
    doors = [i for i in e["elements"] if i.get("kind") == "door"]
    drop = {i["item_id"] for i in doors[keep_doors:]}
    e["elements"] = [i for i in e["elements"] if i["item_id"] not in drop]
    (root / did / "elements.json").write_text(json.dumps(e))
    for pm in (root / did).glob("planmap-*.json"):   # the plan map agrees with the trimmed IFC
        m = json.loads(pm.read_text())
        m["items"] = [i for i in m.get("items", []) if i.get("item_id") not in drop]
        pm.write_text(json.dumps(m))


@pytest.fixture
def art(tmp_path, monkeypatch):
    if not (SRC / "elements.json").exists():
        pytest.skip("FZK artifacts not available")
    monkeypatch.setenv("MODELS_FAKE", "1")
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    _sheet(tmp_path, ARK, "ARK-103-03_floor_plan_ground_floor", 2)
    _sheet(tmp_path, VENT, "L30301 ventilation systems ground floor block U", 5)   # the MEP sheet draws MORE door symbols
    return tmp_path


def test_discipline_of():
    from engine.projects.combine import discipline_of
    assert discipline_of("ARK-103-03_floor_plan_3rd_floor") == "arch"
    assert discipline_of("L30301 ventilation systems 3rd floor block U") == "mep"
    assert discipline_of("Fire strategy") is None


@pytest.mark.parametrize("order", [0, 1])
def test_doors_come_from_the_architecture_sheet(art, order):
    from engine.answer import answer
    ids = [ARK, VENT] if order == 0 else [VENT, ARK]
    a = answer("How many doors are on this floor?", ids)["answer"]["text_md"]
    assert a.startswith("**2 doors**") and "ventilation" in a.lower() and "shows 5" in a
