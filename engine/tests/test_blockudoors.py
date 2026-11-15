"""F-BLOCKUDOORS: a sheet whose elements are the very same ids as the counted source (a ventilation model built on the
architect plan copies its doors) is not an independent cross-check; a sheet with its own ids still is."""
from types import SimpleNamespace as NS

from engine.projects.multidoc import _cross_checks


def _case(vent_ids):
    ark = {"door": {"n": 3, "ids": ["a", "b", "c"]}}
    vent = {"door": {"n": len(vent_ids), "ids": vent_ids}}
    row = NS(chosen={"door": "ark"}, docs={"ark": ark, "vent": vent})
    c = NS(infos={"ark": NS(role="plan"), "vent": NS(role="plan")})
    return c, row


def test_copied_ids_are_not_a_cross_check():
    c, row = _case(["a", "b", "c"])
    assert _cross_checks(c, "door", [row]) == []


def test_own_ids_still_cross_check():
    c, row = _case(["x", "y", "z", "w"])
    notes = _cross_checks(c, "door", [row])
    assert [(n[0], n[3], n[4]) for n in notes] == [("vent", 4, 3)]
