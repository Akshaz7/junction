from engine.printed_total import find, wants


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
