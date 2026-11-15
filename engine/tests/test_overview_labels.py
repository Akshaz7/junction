import json
from types import SimpleNamespace as NS

from engine.projects.overview import _labels


def _combined(**infos):
    return NS(infos=infos)


def _info(role, doc=None, derived=False):
    return NS(role=role, doc=doc, derived=derived)


def test_unread_model_is_never_verified(tmp_path):
    (tmp_path / "running").mkdir(); (tmp_path / "running" / "ingest.json").write_text(json.dumps({"status": "running"}))
    (tmp_path / "failed").mkdir(); (tmp_path / "failed" / "ingest.json").write_text(json.dumps({"status": "failed"}))
    c = _combined(running=_info("model"), failed=_info("model"), empty=_info("model", doc=NS(items=[])),
                  read=_info("model", doc=NS(items=[1])))
    out = _labels(c, [], tmp_path)
    assert out == {"running": "Processing", "failed": "Not readable", "empty": "Partial", "read": "Verified"}
