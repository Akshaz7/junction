"""Detector hook (experiment): off by default, door confirm only, never adds or moves geometry."""
from pipeline import pdf_detect


def _pm():
    return {"items": [{"id": "door-001", "kind": "door", "bbox_px": [100, 100, 140, 140]},
                      {"id": "door-002", "kind": "door", "bbox_px": [400, 400, 440, 440]},
                      {"id": "wall-001", "kind": "wall", "bbox_px": [0, 0, 500, 10]}]}


def test_off_unless_env(monkeypatch):
    monkeypatch.delenv("PDF_DETECT", raising=False)
    assert not pdf_detect.enabled()
    monkeypatch.setenv("PDF_DETECT", "1")
    assert pdf_detect.enabled()


def test_confirms_matching_door_only(monkeypatch):
    # s = 1 px per pt: a detection on door-001 (and a window, ignored) confirms it; door-002 stays unconfirmed
    monkeypatch.setattr(pdf_detect, "_call", lambda *a, **k: {
        "items": [{"kind": "door", "bbox_pt": [102, 101, 141, 139], "conf": 0.91},
                  {"kind": "window", "bbox_pt": [400, 400, 440, 440], "conf": 0.9}],
        "run": "test", "weights": "w", "thresholds": {}, "tiles": 1, "seconds": 0.1})
    pm = _pm()
    before = [(i["id"], i["bbox_px"]) for i in pm["items"]]
    summ = pdf_detect.apply(pm, "x.pdf", 0, 1.0, 0.01)
    assert [(i["id"], i["bbox_px"]) for i in pm["items"]] == before  # no geometry added or moved
    assert pm["items"][0]["props"]["det_conf"] == 0.91 and "derived" in pm["items"][0]["props"]["det_evidence"]
    assert "props" not in pm["items"][1]
    assert summ["doors_vector"] == 2 and summ["doors_detected"] == 1 and summ["doors_confirmed"] == 1


def test_call_failure_never_breaks(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("modal down")
    monkeypatch.setattr(pdf_detect, "_call", boom)
    pm = _pm()
    summ = pdf_detect.apply(pm, "x.pdf", 0, 1.0, 0.01)
    assert "modal down" in summ["error"] and all("props" not in i for i in pm["items"])


def test_timeout_and_interpreter_defaults(monkeypatch):
    seen = {}

    class Out:
        returncode, stdout, stderr = 0, '{"items": []}', ""

    def fake_run(cmd, **kw):
        seen["cmd"], seen["timeout"] = cmd, kw.get("timeout")
        return Out()
    monkeypatch.delenv("PDF_DETECT_PY", raising=False)
    monkeypatch.delenv("PDF_DETECT_TIMEOUT_S", raising=False)
    monkeypatch.setattr(pdf_detect.importlib_util if hasattr(pdf_detect, "importlib_util") else __import__("importlib.util").util,
                        "find_spec", lambda name: object())
    monkeypatch.setattr(pdf_detect.subprocess, "run", fake_run)
    assert pdf_detect._call("x.pdf", 0, None) == {"items": []}
    import sys
    assert seen["cmd"][0] == sys.executable and seen["timeout"] == 30.0
