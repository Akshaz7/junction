"""pipeline.pdf_semantics: plan-region crop + text semantics on a synthetic page (pt, y down)."""
from pipeline import pdf_semantics as ps

MPT = 0.0352778  # 1:100


def _w(text, x, y, h=7.0):
    return {"text": text, "bbox": [x, y, x + 6 * len(text), y + h]}


def _wall(x0, y0, x1, y1, t=7.0):
    if abs(y1 - y0) < 1e-6:
        poly = [[x0, y0 - t / 2], [x1, y0 - t / 2], [x1, y0 + t / 2], [x0, y0 + t / 2]]
    else:
        poly = [[x0 - t / 2, y0], [x0 + t / 2, y0], [x0 + t / 2, y1], [x0 - t / 2, y1]]
    return {"polygon": poly, "centerline": [[x0, y0], [x1, y1]], "thickness_pt": t, "style": "fill"}


def _box(x0, y0, x1, y1, t=7.0):
    return [_wall(x0, y0, x1, y0, t), _wall(x0, y1, x1, y1, t), _wall(x0, y0, x0, y1, t), _wall(x1, y0, x1, y1, t)]


def test_region_drops_unlabelled_roof_and_reads_text():
    plan = _box(100, 100, 500, 250)                 # 14 x 5.3 m office band with room evidence
    plan += [_wall(250, 100, 250, 250), _wall(400, 100, 400, 250)]
    roof = _box(100, 250, 500, 510, t=4.0)          # neighbouring roof below it: no labels
    words = [_w("K101", 150, 160), _w("K102", 300, 160), _w("K103", 430, 160), _w("h=3050", 150, 180),
             _w("h=2700", 300, 180), _w("EI60", 305, 232), _w("ROOF", 300, 420),
             _w("LEGEND:", 700, 100), _w("V-T", 700, 120), _w("OLD", 740, 120), _w("BRICK", 765, 120),
             _w("WALL", 800, 120), _w("LS-U", 700, 135), _w("NEW", 740, 135), _w("GLASS", 765, 135),
             _w("PARTITION", 800, 135), _w("DOOR", 700, 160), _w("HEIGHT", 730, 160), _w("h=2100;", 772, 160),
             _w("FLOOR", 700, 600, 12), _w("PLAN,", 740, 600, 12), _w("2ND", 780, 600, 12), _w("FLOOR", 805, 600, 12),
             _w("+9.000", 160, 215), _w("+9.000", 320, 215), _w("+8.400", 300, 500)]
    doors = [{"kind": "door", "bbox": [b - 10, 293, b + 10, 307]} for b in (170, 320, 450)]
    doors = [{**d, "bbox": [d["bbox"][0], 243, d["bbox"][2], 257]} for d in doors]
    page = {"W_pt": 900, "H_pt": 700, "words": words}
    walls = plan + roof
    region, st = ps.plan_region(page, walls, [], doors, MPT)
    assert region is not None, st
    kept = {id(w) for w in walls if id(w) in set(st["keep_ids"])}
    assert all(id(w) in kept for w in plan)
    assert not any(id(w) in kept for w in roof[1:])  # roof bottom + sides dropped (its top is the band's wall)
    sem = ps.analyse(page, [w for w in walls if id(w) in kept], doors, [], MPT, region)
    assert sem["storey"]["name"] == "2ND FLOOR" and sem["storey"]["number"] == 2
    assert sem["storey"]["elevation_m"] == 9.0
    assert sem["door_height_m"] == 2.1
    codes = {e["code"]: e for e in sem["legend"]}
    assert codes["V-T"]["material"] == "Brick" and codes["LS-U"]["kind"] == "glass_partition"
    assert sem["wall_height_m"] >= 3.05
    assert any(t.get("fire_rating") == "EI60" for t in sem["door_tags"].values())


def test_too_little_evidence_no_crop():
    page = {"W_pt": 900, "H_pt": 700, "words": [_w("K101", 150, 180)]}
    region, st = ps.plan_region(page, _box(100, 100, 500, 300), [], [], MPT)
    assert region is None and "skipped" in st


def test_envelope_wall_drawn_on_through_a_roof_edge_is_clipped_back():
    """An exterior wall drawn as one segment that runs on as a neighbouring roof's edge: the crop alone drops it
    (most of its axis lies outside the plan); the envelope round brings back the part along the plan, not the roof part."""
    plan = [_wall(100, 100, 500, 100), _wall(100, 100, 100, 250), _wall(500, 100, 500, 250),
            _wall(250, 100, 250, 250), _wall(400, 100, 400, 250)]
    ext = _wall(100, 250, 1300, 250)                # bottom exterior wall + the roof edge beyond it, one segment
    roof = [_wall(500, 250, 500, 420, 4.0), _wall(1300, 250, 1300, 420, 4.0), _wall(500, 420, 1300, 420, 4.0)]
    words = [_w("K101", 150, 160), _w("K102", 300, 160), _w("K103", 430, 160), _w("h=3050", 150, 180),
             _w("h=2700", 300, 180), _w("h=2700", 430, 180), _w("EI60", 305, 120)]
    doors = [{"kind": "door", "bbox": [b - 10, 93, b + 10, 107]} for b in (170, 320, 450)]
    page = {"W_pt": 1400, "H_pt": 700, "words": words}
    walls = plan + [ext] + roof
    region, st = ps.plan_region(page, walls, [], doors, MPT)
    assert region is not None, st
    keep = set(st["keep_ids"])
    assert all(id(w) in keep for w in plan)
    assert id(ext) not in keep and not any(id(w) in keep for w in roof[1:])
    back = [w for w in walls if id(w) in keep and w.get("clipped_to_plan")]
    assert len(back) == 1 and st["envelope_readmitted"] == 1
    xs = [p[0] for p in back[0]["centerline"]]
    assert min(xs) <= 105 and 495 <= max(xs) <= 520  # along the plan only, not on along the roof
    assert back[0]["thickness_pt"] == ext["thickness_pt"]


def test_sparsely_labelled_big_room_keeps_its_far_walls():
    """A big room labelled once near the plan's dense corner: its far exterior walls sit metres away from any
    room evidence. The labelled room polygon (wall face to wall face) is plan, so its bounding walls stay."""
    right, top = _wall(900, 100, 900, 600), _wall(500, 100, 900, 100)
    bottom, mid = _wall(500, 600, 900, 600), _wall(500, 100, 500, 600)
    dense = _box(100, 100, 400, 250) + [_wall(250, 100, 250, 250)]
    words = [_w("K101", 150, 160), _w("K102", 300, 160), _w("h=2700", 150, 180), _w("h=2700", 300, 180),
             _w("EI60", 150, 200), _w("EI60", 300, 200), _w("K104", 520, 130), _w("h=3050", 520, 145)]
    big = {"label": "Office", "number": "K104", "label_bbox": [520, 130, 544, 137], "area_printed_m2": None,
           "polygon": [[503.5, 103.5], [896.5, 103.5], [896.5, 596.5], [503.5, 596.5]]}
    page = {"W_pt": 1000, "H_pt": 700, "words": words}
    walls = dense + [right, top, bottom, mid]
    region, st = ps.plan_region(page, walls, [big], [], MPT)
    assert region is not None, st
    keep = set(st["keep_ids"])
    assert all(id(w) in keep for w in (right, top, bottom, mid)), st
    assert region.contains(ps.Polygon(big["polygon"]).buffer(-1))
    assert st["room_area_lost"] == 0.0


def test_outline_pen_closes_the_facade_and_clips_a_parapet():
    """The heavy outline pen draws the whole building outline; the walls miss the east facade and one wall runs on
    3.5 m past the south facade (a terrace parapet). The crop follows the outline: the east facade comes back as a
    wall, the parapet is clipped at the facade."""
    def seg(x0, y0, x1, y1, w=0.6, c=(0.0, 0.0, 0.0)):
        return {"pts": [[x0, y0], [x1, y1]], "closed": False, "stroke": list(c), "width": w, "fill": None,
                "dashed": False, "pattern": False}
    pen = []
    for d in (-3.5, 3.5):  # double outline line (both faces of the exterior wall)
        pen += [seg(100 - d, 100 - d, 500 + d, 100 - d), seg(500 + d, 100 - d, 500 + d, 300 + d),
                seg(500 + d, 300 + d, 100 - d, 300 + d), seg(100 - d, 300 + d, 100 - d, 100 - d)]
    thin = [seg(150 + 10 * i, 120, 150 + 10 * i, 280, 0.24, (0.5, 0.5, 0.5)) for i in range(30)]  # linework pen
    walls = [_wall(100, 100, 500, 100), _wall(100, 300, 500, 300), _wall(100, 100, 100, 300),
             _wall(300, 100, 300, 400)]  # interior wall drawn on through the south facade (parapet)
    words = [_w(f"K1{i:02d}", x, y) for i, (x, y) in enumerate(
        [(110, 106), (250, 106), (430, 106), (110, 285), (250, 285), (430, 285), (200, 200), (400, 200), (460, 150)])]
    page = {"W_pt": 900, "H_pt": 700, "words": words, "paths": pen + thin}
    region, st = ps.plan_region(page, walls, [], [], MPT)
    assert region is not None and st.get("outline") == "ok", st
    kept = [w for w in walls if id(w) in set(st["keep_ids"])]
    east = [w for w in kept if w.get("from_outline_pen") and min(p[0] for p in w["polygon"]) > 480]
    assert east, st
    assert region.bounds[3] < 300 + 0.6 / MPT  # the parapet is not building
    parapet = [w for w in kept if w.get("clipped_to_plan")]
    assert parapet and max(p[1] for w in parapet for p in w["polygon"]) < 300 + 0.6 / MPT


def test_envelope_clip_never_raises_and_passes_through_without_evidence():
    walls = _box(100, 100, 500, 300)
    out, region = ps.envelope_clip({"W_pt": 900, "H_pt": 700, "words": []}, walls, None, MPT)
    assert out is walls and region is None
    out, region = ps.envelope_clip(None, walls, None, MPT)  # bad input: unchanged, no crop
    assert out is walls and region is None
