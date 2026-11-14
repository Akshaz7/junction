import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("bda", Path(__file__).resolve().parents[2] / "deploy/build_demo_artifacts.py")
bda = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bda)


def mk(root, name, licence="CC0", publishable=True):
    d = root / name
    (d / "tmp").mkdir(parents=True)
    (d / "doc.json").write_text(json.dumps({"licence": licence}))
    (d / "scene.json").write_text(json.dumps({"publishable": publishable}))
    for f in ("scene.glb", "elements.json", "planmap-1.json", "page-1.png", "page-1.thumb.png", ".done-x", "tmp/big.bin"):
        (d / f).write_bytes(b"x")


def test_copies_only_served_files(tmp_path):
    mk(tmp_path / "a", "ok")
    out = tmp_path / "out"
    assert bda.main.__globals__["refusal"](tmp_path / "a" / "ok") is None
    import sys
    sys.argv = ["x", "--docs", "ok", "--src", str(tmp_path / "a"), "--out", str(out)]
    assert bda.main() == 0
    names = sorted(p.name for p in (out / "ok").iterdir())
    assert names == ["doc.json", "elements.json", "page-1.png", "page-1.thumb.png", "planmap-1.json", "scene.glb", "scene.json"]


def test_refuses_unpublishable(tmp_path):
    mk(tmp_path, "nd", licence="CC-BY-ND-4.0")
    mk(tmp_path, "np", publishable=False)
    assert "licence" in bda.refusal(tmp_path / "nd")
    assert "publishable" in bda.refusal(tmp_path / "np")
    import sys
    sys.argv = ["x", "--docs", "nd", "--src", str(tmp_path), "--out", str(tmp_path / "out")]
    assert bda.main() == 1 and not (tmp_path / "out" / "nd").exists()
