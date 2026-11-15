from engine.printed_total import find, find_level, level_of, wants, wants_level


def w(t, x, y=10):
    return {"text": t, "bbox_px": [x, y, x + 20, y + 10]}


def test_kyoto_style_total_is_quoted_with_box_and_unit():
    words = [w("1F", 0), w("51.84", 30), w("㎡", 60), w("計", 100, 200), w("27,860.00㎡", 130, 200)]
    (value, unit, quote, bbox), = find(words)
    assert (value, unit) == (27860.0, "m²") and "27,860.00" in quote and bbox[0] == 100


def test_english_and_feet():
    assert find([w("TOTAL", 0), w("1,234", 30), w("SQ", 60), w("FT", 80)])[0][:2] == (1234.0, "ft²")


def test_routing_words():
    assert wants("What total area is printed on the drawing?")
    assert wants("What is the total floor area listed in the area schedule on page 1, in square metres?")
    assert not wants("What is the total area of all rooms?")
    assert not wants("Estimate the total area printed")


def test_per_level_questions_are_not_taken_for_the_grand_total():
    assert not wants("What floor area does the page 1 schedule list for level B2?")


def test_per_level_row_is_read_from_the_printed_schedule():
    q = "What floor area does the page 1 schedule list for level B2?"
    assert level_of(q) == "B2" and wants_level(q)
    words = [w("B1", 0, 10), w("5,855.40㎡", 40, 10), w("B2", 0, 50), w("9,216.68", 40, 50), w("㎡", 70, 50), w("計", 0, 90), w("27,860.00㎡", 40, 90)]
    (value, unit, quote, bbox), = find_level(words, "B2")
    assert (value, unit) == (9216.68, "m²") and bbox[1] == 50


def test_raster_header_prefers_the_printed_metric_figure():
    words = [w("Approx.", 0), w("1295", 30), w("sq.", 60), w("feet", 80), w("(120.31", 110), w("sq.", 140), w("metres)", 160)]
    (value, unit, quote, bbox), = find(words)
    assert (value, unit) == (120.31, "m²") and "1295" in quote and bbox[2] >= 180


def test_printed_room_area_is_quoted_not_replaced_by_geometry(tmp_path):
    import json
    from engine.printed_total import answer, find_room, room_of, wants_room
    q = "What area is printed for the Living room on this plan?"
    assert wants_room(q) and room_of(q).lower().startswith("living")
    assert not wants_room("What is the total area printed on this plan?")
    words = [w("Kitchen", 0, 10), w("4.50", 40, 10), w("x", 60, 10), w("2.08", 70, 10), w("m", 95, 10),
             w("Living", 0, 50), w("Room", 30, 50), w("25.30", 60, 50), w("m²", 90, 50)]
    (value, unit, quote, bbox), = find_room(words, "Living Room")
    assert (value, unit) == (25.3, "m²") and bbox[1] == 50
    assert find_room(words, "Kitchen") == []     # a bare length is not an area label
    d = tmp_path / "doc1"
    d.mkdir()
    (d / "rtext-1.json").write_text(json.dumps({"page": 1, "source": "ocr", "words": words}))
    res = answer(q, ["doc1"], tmp_path)
    assert res["answer"]["value"] == 25.3 and "25.30" in res["citations"][0]["quote"] and res["citations"][0]["bbox_px"][1] == 50
