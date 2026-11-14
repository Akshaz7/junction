import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
IDS = ["swiss_dwellings__site289-bldg536-floor2149", "ifc_bench__ac20-arc", "cubicasa5k__colorful-11397"]


@pytest.mark.parametrize("doc_id", IDS)
def test_usdz_prims_and_arkit(doc_id):
    from pxr import Usd
    art = ROOT / "artifacts" / doc_id
    usdz = art / "scene.usdz"
    assert usdz.exists(), "run python -m pipeline.usdz"
    sj = json.loads((art / "scene.json").read_text())
    stage = Usd.Stage.Open(str(usdz))
    names = {p.GetName() for p in stage.Traverse()}
    missing = [v["usd_name"] for v in sj["items"].values() if v["usd_name"] not in names]
    assert not missing, missing[:5]
    if shutil.which("usdchecker"):
        r = subprocess.run(["usdchecker", "--arkit", str(usdz)], capture_output=True, text=True)
        assert "Success!" in r.stdout + r.stderr, (r.stdout + r.stderr)[-500:]
