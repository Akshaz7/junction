import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from engine import answer as A
from engine.answer import answer

FIX = Path(__file__).parent / "fixtures"
DOC = "cubicasa5k__colorful-11397"


@pytest.fixture(autouse=True)
def root(monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(FIX))
    monkeypatch.setenv("MODELS_FAKE", "1")


def test_signature_matches_stub():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
    import stub_engine
    a, b = inspect.signature(answer).parameters, inspect.signature(stub_engine.answer).parameters
    base = [(n, p.default, p.kind) for n, p in a.items() if p.kind is not inspect.Parameter.KEYWORD_ONLY]
    assert base == [(n, p.default, p.kind) for n, p in b.items()]
    assert all(p.default is None for p in a.values() if p.kind is inspect.Parameter.KEYWORD_ONLY)  # extras are optional


def test_windows_with_events():
    ev = []
    a = answer("How many windows are shown on this floor plan?", [DOC], lambda k, p: ev.append((k, p)))
    assert a["answer"]["value"] == 13 and len(a["evidence"]["boxes"]) == 13 and a["cost"]["usd_total"] == 0
    st = [p["text"] for k, p in ev if k == "status"]
    assert st[0] == "Thinking…" and st[1].startswith("Exploring document: ")
    assert [p for k, p in ev if k == "trace"] == a["trace"]
    assert a["trace"][0]["step"] == "route"


def test_abstentions_are_plain():
    assert answer("How many windows?", [])["answer"]["abstained"]
    t = answer("What materials are used in the walls?", [DOC])
    assert t["answer"]["abstained"] and "cannot read the drawing" in t["answer"]["text_md"]
    m = answer("How many windows are there?", ["missing__doc"])
    assert m["answer"]["abstained"] and m["answer"]["value"] is None


def test_unparsed_goes_to_model_fallback_and_never_raises(monkeypatch):
    a = answer("hello there", [DOC])
    assert a["answer"]["abstained"] and any(s["step"] == "route" for s in a["trace"])
    import engine.solvers as S
    monkeypatch.setattr(A, "solve", lambda *x, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    b = answer("How many windows are shown?", [DOC])
    assert b["answer"]["abstained"] and b["trace"][-1]["step"] == "error"


def test_answer_path_imports_no_heavy_packages():
    code = ("import sys, engine.answer; bad=[m for m in ('torch','ifcopenshell','numpy','PIL','cv2') if m in sys.modules]; "
            "print(bad); sys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
