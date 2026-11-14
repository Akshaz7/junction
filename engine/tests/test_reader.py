import json
import struct
import zlib
from types import SimpleNamespace

import pytest

from engine.reader import geom, read_answer
from engine.reader.tools import Session, safe_eval

DOC = "opening_design__fake-sheet"


def _png(path, w=1000, h=800):
    raw = b"".join(b"\x00" + b"\xff" * w for _ in range(h))
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _w(text, x, y, wd=60, ht=14):
    return {"text": text, "bbox_px": [x, y, x + wd, y + ht]}


@pytest.fixture
def root(tmp_path, monkeypatch):
    d = tmp_path / DOC
    d.mkdir()
    _png(d / "page-1.png")
    (d / "doc.json").write_text(json.dumps({"title": "A-801 Door Schedule", "kind": "pdf", "pages": 1}))
    words = [_w("DOOR", 100, 100), _w("121.A", 100, 130), _w("WIDTH", 300, 100), _w("3'-0\"", 300, 130), _w("NOTE", 100, 300), _w("4.", 170, 300, 20),
             _w("PROVIDE", 100, 320, 80), _w("FIRE", 190, 320, 40), _w("CAULK", 240, 320, 60), _w("scale", 600, 700), _w("1:100", 670, 700)]
    (d / "text-1.json").write_text(json.dumps({"doc_id": DOC, "page": 1, "image": {"w": 1000, "h": 800}, "dpi": 150, "source": "test", "words": words}))
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    return tmp_path


def planner(replies, cost=0.003):
    it = iter(replies)
    def call(task, msgs, images=None, schema=None, **k):
        if task != "reader_plan":
            raise RuntimeError("only the planner is faked")
        return SimpleNamespace(json=None, text=next(it), provider="runware", model="m", cost_usd=cost, latency_ms=1)
    return call


def test_safe_eval():
    assert safe_eval("1,200 * 1.1 + sum([1,2])") == pytest.approx(1323)
    for bad in ("__import__('os')", "2**99", "open('x')"):
        with pytest.raises(Exception):
            safe_eval(bad)


def test_geom():
    assert geom.polyline_length([[0, 0], [3, 4]]) == 5
    assert geom.polygon_area([[0, 0], [10, 0], [10, 10], [0, 10]]) == 100


def test_find_text_registers_evidence(root):
    s = Session([DOC], root)
    out = s.run("find_text", {"query": "door 121.A"})
    assert out.startswith("e1 d1 p1") and s.ev["e1"].bbox_px[0] == 100
    assert "no match" in s.run("find_text", {"query": "zebra crossing"})
    assert s.run("nope", {}).startswith("error: unknown tool")
    assert "error" in s.run("compute", {"expr": "__import__('os')"})


def test_scale_tool(root):
    s = Session([DOC], root)
    assert "1:100" in s.run("scale", {"doc": "d1", "page": 1})


def test_agent_answers_with_valid_evidence(root, monkeypatch):
    import engine.models as M
    monkeypatch.setattr(M, "call", planner([
        '{"action":"tool","tool":"find_text","args":{"query":"NOTE 4"}}',
        '{"action":"final","answer":"**Note 4 requires fire caulk.** [x]","value":null,"unit":null,"evidence":["e1","e99"],"confidence":0.8}']))
    a = read_answer("What does note 4 require?", [DOC], root)
    assert not a["answer"]["abstained"] and a["route"] == "hybrid"
    assert len(a["citations"]) == 1 and a["citations"][0]["kind"] == "text" and a["evidence"]["boxes"][0]["label"] == "1"
    assert "[1]" in a["answer"]["text_md"] or "[x]" in a["answer"]["text_md"]
    assert a["cost"]["usd_total"] == pytest.approx(0.006)


def test_agent_abstains_without_evidence(root, monkeypatch):
    import engine.models as M
    monkeypatch.setattr(M, "call", planner(['{"action":"final","answer":"It is 5 hours.","value":5,"unit":"h","evidence":["e7"],"confidence":0.9}'] * 3))
    a = read_answer("What fire rating do the stair doors need?", [DOC], root)
    assert a["answer"]["abstained"] and a["answer"]["value"] is None and a["citations"] == []
    assert "could not verify" in a["answer"]["text_md"]


def test_ungrounded_number_is_dropped(root, monkeypatch):
    import engine.models as M
    monkeypatch.setattr(M, "call", planner([
        '{"action":"tool","tool":"find_text","args":{"query":"door 121.A"}}',
        '{"action":"final","answer":"**7 m**","value":7,"unit":"m","evidence":["e1"],"confidence":0.9}']))
    a = read_answer("door 121.A width", [DOC], root)
    assert a["answer"]["value"] is None and a["answer"]["confidence"] <= 0.3


def test_agent_survives_bad_json_and_multiple_objects(root, monkeypatch):
    import engine.models as M
    monkeypatch.setattr(M, "call", planner([
        "no idea",
        '{"action":"tool","tool":"find_text","args":{"query":"FIRE CAULK"}}\n{"action":"tool","tool":"page_text","args":{}}',
        '```json\n{"action":"final","answer":"**Fire caulk.**","value":null,"unit":null,"evidence":["e1"],"confidence":0.7}\n```']))
    a = read_answer("what is provided?", [DOC], root)
    assert not a["answer"]["abstained"] and a["citations"][0]["page"] == 1


def test_answer_routes_sheet_to_reader(root, monkeypatch):
    import engine.models as M
    from engine.answer import answer
    monkeypatch.setattr(M, "call", planner([
        '{"action":"tool","tool":"find_text","args":{"query":"NOTE 4"}}',
        '{"action":"final","answer":"**Fire caulk.**","value":null,"unit":null,"evidence":["e1"],"confidence":0.8}']))
    events = []
    a = answer("What does note 4 on this sheet require?", [DOC], lambda k, p: events.append((k, p)))
    assert not a["answer"]["abstained"] and a["route"] == "hybrid"
    assert any(k == "status" and "Finding" in p["text"] for k, p in events)
