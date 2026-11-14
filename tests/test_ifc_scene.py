import json
from collections import Counter
from pathlib import Path

from pygltflib import GLTF2

ART = Path(__file__).resolve().parent.parent / "artifacts" / "ifc_bench__ac20-arc"


def test_ac20_scene():
    els = json.loads((ART / "elements.json").read_text())["elements"]
    c = Counter(e["kind"] for e in els)
    assert (c["door"], c["window"], c["wall"], c["room"]) == (77, 206, 121, 82)
    scene = json.loads((ART / "scene.json").read_text())
    assert len(scene["storeys"]) == 5
    names = {n.name for n in GLTF2().load(str(ART / "scene.glb")).nodes if n.mesh is not None}
    assert set(scene["items"]) <= names and len(scene["items"]) == len(names)
    import hashlib
    for k, it in scene["items"].items():
        assert it["node"] == k and it["usd_name"] == "i_" + hashlib.sha1(k.encode()).hexdigest()[:16]
    ids = {e["item_id"] for e in els}
    assert set(scene["items"]) <= ids
