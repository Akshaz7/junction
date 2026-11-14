import shutil
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine import readdraw
from engine.answer import answer

FIX = Path(__file__).parent / "fixtures"
DOC = "cubicasa5k__colorful-11397"
Q = "What is the main entrance used for?"


def _png(path: Path, w=475, h=650):
    raw = b"".join(b"\x00" + b"\xff" * w for _ in range(h))
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@pytest.fixture
def root(tmp_path, monkeypatch):
    shutil.copytree(FIX / DOC, tmp_path / DOC)
    _png(tmp_path / DOC / "page-1.png")
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    return tmp_path


def fake_call(payload):
    import engine.models as M
    return lambda task, msgs, images=None, schema=None, **k: SimpleNamespace(json=payload, provider="runware", model="google:gemini@3.5-flash", cost_usd=0.002, text="")


def test_checked_region_becomes_citation(root, monkeypatch):
    import engine.models as M
    # window-001 sits at [116,155,192,170] px of 475x650 -> box_2d [ymin,xmin,ymax,xmax] on 0-1000
    box = [155 / 650 * 1000 - 5, 116 / 475 * 1000 - 5, 170 / 650 * 1000 + 5, 192 / 475 * 1000 + 5]
    monkeypatch.setattr(M, "call", fake_call({"can_answer": True, "answer": "**It is the window row.**", "regions": [
        {"box_2d": box, "what": "window"}, {"box_2d": [0, 0, 20, 20], "what": "nothing here"}]}))
    a = answer(Q, [DOC])
    assert not a["answer"]["abstained"] and a["route"] == "vlm"
    assert len(a["citations"]) == 1 and a["citations"][0]["item_ids"] == ["window-001"] and a["evidence"]["boxes"]
    assert "[1]" in a["answer"]["text_md"] and a["cost"]["usd_total"] == 0.002
    assert any("1 region(s) backed" in t["detail"] and "1 dropped" in t["detail"] for t in a["trace"])


def test_unbacked_regions_are_flagged(root, monkeypatch):
    import engine.models as M
    monkeypatch.setattr(M, "call", fake_call({"can_answer": True, "answer": "**Something.**", "regions": [{"box_2d": [0, 0, 20, 20], "what": "x"}]}))
    a = answer(Q, [DOC])
    assert a["citations"] == [] and "unchecked" in a["answer"]["text_md"] and a["answer"]["confidence"] < 0.5


def test_cannot_answer_and_no_image(root, monkeypatch):
    import engine.models as M
    monkeypatch.setenv("FORCE_ANSWER", "0")
    monkeypatch.setattr(M, "call", fake_call({"can_answer": False, "answer": "The drawing does not show that.", "regions": []}))
    a = answer(Q, [DOC])
    assert a["answer"]["abstained"] and "does not show" in a["answer"]["text_md"]
    (root / DOC / "page-1.png").unlink()
    assert answer(Q, [DOC])["answer"]["abstained"]


def test_helpers():
    assert readdraw.to_px([0, 0, 500, 1000], 200, 100) == [0.0, 0.0, 200.0, 50.0]
    assert readdraw.to_px([5, 5, 5, 9], 10, 10) is None and readdraw.to_px("x", 10, 10) is None
