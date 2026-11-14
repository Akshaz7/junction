from engine.solvers.solve import _pip, _quoted, room_subtype


def test_room_subtype_ignores_brackets_and_exclusions():
    assert room_subtype("How many bedrooms (makuuhuone, usually marked MH) are on this floor plan?")[0] == "bedroom"
    assert room_subtype("How many bathrooms or washrooms (e.g. KH) are on this plan, not counting separate WC rooms?")[0] == "bathroom"
    assert room_subtype("How many separate WC rooms (toilet rooms marked WC) are there?")[0] == "WC room"
    assert room_subtype("How many windows are there?") is None


def test_quoted_keeps_inner_apostrophe():
    assert _quoted("How many rooms labelled 'Cage d'escalier' are there on this floor?") == ["Cage d'escalier"]
    assert _quoted("net area of room 1.51 ('Pièce') in m²?") == ["Pièce"]


def test_point_in_polygon():
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert _pip((5, 5), sq) and not _pip((15, 5), sq)
