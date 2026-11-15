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


def test_timeout_env(monkeypatch):
    monkeypatch.delenv("PDF_DETECT_TIMEOUT_S", raising=False)
    assert pdf_detect._timeout_s() == 30.0
    monkeypatch.setenv("PDF_DETECT_TIMEOUT_S", "12.5")
    assert pdf_detect._timeout_s() == 12.5
    monkeypatch.setenv("PDF_DETECT_TIMEOUT_S", "junk")
    assert pdf_detect._timeout_s() == 30.0


def test_call_passes_timeout_to_subprocess(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["timeout"] = kw["timeout"]

        class R:
            returncode, stdout, stderr = 0, '{"items": []}\n', ""
        return R()
    monkeypatch.setenv("PDF_DETECT_PY", "python3")
    monkeypatch.setenv("PDF_DETECT_TIMEOUT_S", "7")
    monkeypatch.setattr(pdf_detect.subprocess, "run", fake_run)
    pdf_detect._call("x.pdf", 0, None)
    assert seen["timeout"] == 7.0


def test_timeout_and_no_app_deployed_are_recorded_not_raised(monkeypatch):
    """PDF_DETECT=1 with no Modal app (client exits non-zero) or a hung call: apply() records pm['detector']['error']."""
    import subprocess
    monkeypatch.setenv("PDF_DETECT_PY", "python3")

    def no_app(cmd, **kw):
        class R:
            returncode, stdout, stderr = 1, "", "modal.exception.NotFoundError: App 'junction-det' not found"
        return R()
    monkeypatch.setattr(pdf_detect.subprocess, "run", no_app)
    pm = _pm()
    assert "not found" in pdf_detect.apply(pm, "x.pdf", 0, 1.0, 0.01)["error"] and pm["detector"]["error"]

    def hang(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])
    monkeypatch.setattr(pdf_detect.subprocess, "run", hang)
    pm = _pm()
    assert "TimeoutExpired" in pdf_detect.apply(pm, "x.pdf", 0, 1.0, 0.01)["error"]
    assert all("props" not in i for i in pm["items"])
