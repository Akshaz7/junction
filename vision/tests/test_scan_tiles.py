from vision.scan_tiles import dedupe, regions


def test_tiles_cover_every_pixel_once_and_have_context():
    rs = regions(2500, 1800)
    assert len(rs) == 6
    assert sum((c[2] - c[0]) * (c[3] - c[1]) for _, c in rs) == 2500 * 1800
    for crop, core in rs:
        assert 0 <= crop[0] <= core[0] < core[2] <= crop[2] <= 2500
        assert 0 <= crop[1] <= core[1] < core[3] <= crop[3] <= 1800
    assert len(regions(40000, 40000)) <= 16


def test_dedupe_does_not_merge_adjacent_valves_or_grow_boxes():
    def item(box, conf=.8, kind="valve"):
        return dict(kind=kind, bbox_px=box, conf=conf)
    a = item([0, 0, 20, 20])
    b = item([20, 0, 40, 20])
    duplicate = item([1, 1, 19, 19], .7)
    other = item([0, 0, 20, 20], kind="pump")
    assert dedupe([duplicate, a, b, other]) == [a, b, other]
    assert a["bbox_px"] == [0, 0, 20, 20]
