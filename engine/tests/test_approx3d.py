import json

from engine import library


def test_approx_3d_line_only_when_flagged(tmp_path):
    for name, props in (("raster", {"approx": True}), ("ifc", {})):
        d = tmp_path / name
        d.mkdir()
        (d / "scene.json").write_text(json.dumps({"props": props}))
    a = library.app_feature_answer("render this 2D blueprint into 3D", ["raster"], tmp_path)
    assert library.APPROX_3D in a["answer"]["text_md"]
    b = library.app_feature_answer("render this 2D blueprint into 3D", ["ifc"], tmp_path)
    assert library.APPROX_3D not in b["answer"]["text_md"]
