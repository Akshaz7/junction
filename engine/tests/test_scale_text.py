import json
from pathlib import Path

from engine import answer, scale_text as st
from engine.solvers.data import Item


def w(t, x, y=100, wd=30, h=20):
    return {"text": t, "bbox_px": [x, y, x + wd, y + h]}


def bar(step_px=100, y=900):
    return [w(str(v), 300 + k * step_px - 15, y) for k, v in enumerate((0, 5, 10, 15))] + [w("m", 300 + 3 * step_px + 40, y)]


def test_scalebar_metres_per_pixel():
    s = st.scalebar(bar(100))
    assert s["method"] == "scalebar" and abs(s["m_per_px"] - 0.05) < 1e-6


def test_scalebar_needs_regular_labels():
    irregular = [w("0", 300), w("5", 400), w("10", 650), w("m", 700)]
    assert st.scalebar(irregular) is None
    assert st.scalebar([w("0", 300), w("5", 400)]) is None      # two labels and no unit: not a scale bar


def test_ratio_and_a2_sheet_when_image_is_the_sheet():
    words = [w("Scale", 10), w("1:200", 80), w("Sheet", 160), w("A2", 220)]
    s = st.detect(words, 2376, 1680)
    assert s["method"] == "ratio-sheet" and abs(s["m_per_px"] - 0.05) < 1e-4


def test_ratio_split_across_words_and_a2_glued():
    ratio, sheet = st.ratio_and_sheet([w("1", 0), w(":", 10), w("200", 20), w("SheetA2", 100)])
    assert (ratio, sheet) == (200, "A2")


def test_ratio_without_sheet_or_dpi_is_not_guessed():
    assert st.detect([w("1:200", 10)], 2376, 1680) is None
    assert st.detect([w("1:200", 10), w("A2", 90)], 1000, 1000) is None     # image is not the sheet's shape


def test_ratio_with_dpi():
    s = st.detect([w("1:100", 10)], 1000, 1000, dpi=150)
    assert s["method"] == "ratio-dpi" and abs(s["m_per_px"] - 25.4 / 150 / 10) < 1e-9


def test_bar_and_ratio_agree_uses_exact_ratio_and_disagree_uses_bar():
    ok = st.detect(bar(100) + [w("1:200", 10), w("A2", 90)], 2376, 1680)
    assert ok["method"] == "ratio-sheet" and "agrees" in ok["evidence"]
    bad = st.detect(bar(200) + [w("1:200", 10), w("A2", 90)], 2376, 1680)
    assert bad["method"] == "scalebar" and "disagrees" in bad["evidence"]


def test_implausible_against_door_prior_is_rejected():
    assert st.detect(bar(100), 2376, 1680, prior=0.0005) is None


def test_rescale_items_and_boxes_only_rooms():
    room = Item(item_id="r", kind="room", bbox_px=[0, 0, 100, 100], props={"room_type": "other"})
    done = Item(item_id="r2", kind="room", bbox_px=[0, 0, 10, 10], q={"area_m2": 4.0}, props={})
    door = Item(item_id="d", kind="door", q={"width_m": 1.0}, props={})
    st.rescale_items([room, done, door], 0.02, 0.04)
    assert room.q["area_m2"] == 16.0 and room.props["area_basis"] == "box"
    assert done.q["area_m2"] == 16.0 and door.q["width_m"] == 2.0


def _school(tmp_path, words, scale):
    d = tmp_path / "uploads__t"
    d.mkdir()
    (d / "page-1.png").write_bytes(b"x")
    (d / "scale-ocr-1.json").write_text(json.dumps(words))
    rooms = [("Classroom 1", 0, 0, 600, 400), ("Classroom 2", 600, 0, 1200, 400), ("Office", 0, 400, 400, 760)]
    items = [{"item_id": f"room-{k}", "kind": "room", "label": n, "bbox_px": [a, b, c, e], "polygon_px": None,
              "props": {"room_type": "other"}, "conf": 0.6, "source": "vlm"} for k, (n, a, b, c, e) in enumerate(rooms, 1)]
    (d / "planmap-1.json").write_text(json.dumps({"doc_id": d.name, "page": 1, "image": {"w": 2376, "h": 1680}, "scale": scale, "items": items}))
    (d / "doc.json").write_text(json.dumps({"title": "t"}))
    return d


def test_end_to_end_uploaded_plan_areas_use_printed_scale(tmp_path, monkeypatch):
    from engine.solvers import data
    words = [w("Scale", 10), w("1:200", 80), w("A2", 220)]
    d = _school(tmp_path, words, {"m_per_px": 0.015, "method": "door-prior", "confidence": 0.3})
    # image size comes from page-1.png; give the loader a real one
    from PIL import Image
    Image.new("RGB", (2376, 1680), "white").save(d / "page-1.png")
    st._memo.clear()
    doc = data.load_doc(d.name, tmp_path)
    assert doc.scale["method"] == "ratio-sheet" and doc.scale["replaced"] == "door-prior"
    from engine import analytics
    import time
    r = analytics.run("total area of the classrooms", doc, time.perf_counter())
    assert r["answer"]["value"] == 1200.0 and "title block scale 1:200" in r["answer"]["text_md"]
    r = analytics.run("area of the office", doc, time.perf_counter())
    assert r["answer"]["value"] == 360.0


def test_no_printed_scale_keeps_guess_and_says_so(tmp_path):
    from PIL import Image
    from engine.solvers import data
    d = _school(tmp_path, [w("Classroom", 10)], {"m_per_px": 0.05, "method": "door-prior", "confidence": 0.3})
    Image.new("RGB", (2376, 1680), "white").save(d / "page-1.png")
    st._memo.clear()
    doc = data.load_doc(d.name, tmp_path)
    assert doc.scale["method"] == "door-prior"
    from engine import analytics
    import time
    assert analytics.scale_note(doc).startswith(" The drawing has no printed scale")
