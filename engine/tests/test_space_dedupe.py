"""F-MEPSPACES: architectural + MEP spaces over one footprint count once."""
from engine.solvers.data import Item
from engine.space_dedupe import is_mep_space, note, split_spaces


def sp(iid, name, long_name=None, box=((0, 0, 0), (4, 3, 5)), storey="L1", **props):
    return Item(iid, "room", name=name, storey=storey, bbox_m=[list(box[0]), list(box[1])], props={"long_name": long_name, **props})


def test_mep_marked_spaces_excluded_when_arch_exists():
    rooms = [sp("a", "A101", "Foyer"), sp("m", "A101-M", "Foyer MEP Space")]
    kept, gone = split_spaces(rooms)
    assert [r.item_id for r in kept] == ["a"] and [r.item_id for r, _ in gone] == ["m"]
    assert "once" in note(gone) and "A101-M" in note(gone)


def test_pure_mep_model_keeps_its_spaces():
    rooms = [sp("m", "A101-M", "Foyer MEP Space")]
    assert split_spaces(rooms) == (rooms, [])


def test_hvac_zone_words():
    assert is_mep_space(sp("z", "Z1", "HVAC Zone 3")) and not is_mep_space(sp("r", "A1", "Mechanical Room"))


def test_distinct_rooms_sharing_a_footprint_are_all_kept():
    """Location plan: many distinct spaces can share or abut one footprint. None is an MEP duplicate, so none is dropped."""
    rooms = [sp(f"r{i}", f"Room {i}") for i in range(48)]
    kept, gone = split_spaces(rooms)
    assert len(kept) == 48 and not gone


def test_mep_space_without_matching_arch_footprint_is_kept():
    arch = sp("a", "A101", "Foyer")
    mep = sp("m", "A102-M", "Plant MEP Space", box=((20, 0, 20), (24, 3, 25)))
    kept, gone = split_spaces([arch, mep])
    assert len(kept) == 2 and not gone


def test_nested_small_room_kept():
    kept, gone = split_spaces([sp("a", "Hall"), sp("c", "Closet", box=((1, 0, 1), (2, 3, 2)))])
    assert len(kept) == 2 and not gone


def test_different_storeys_not_duplicates():
    kept, gone = split_spaces([sp("a", "R1", storey="L1"), sp("b", "R2", storey="L2")])
    assert len(kept) == 2 and not gone


def test_no_geometry_never_dropped():
    r1, r2 = Item("a", "room", name="A"), Item("b", "room", name="B")
    assert split_spaces([r1, r2]) == ([r1, r2], [])
