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
