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
    words = [_w("B301", 150, 160), _w("B302", 300, 160), _w("B303", 430, 160), _w("h=3150", 150, 180),
             _w("h=2700", 300, 180), _w("EI60", 305, 232), _w("ROOF", 300, 420),
             _w("LEGEND:", 700, 100), _w("V-T", 700, 120), _w("OLD", 740, 120), _w("BRICK", 765, 120),
             _w("WALL", 800, 120), _w("LS-U", 700, 135), _w("NEW", 740, 135), _w("GLASS", 765, 135),
             _w("PARTITION", 800, 135), _w("DOOR", 700, 160), _w("HEIGHT", 730, 160), _w("h=2100;", 772, 160),
             _w("FLOOR", 700, 600, 12), _w("PLAN,", 740, 600, 12), _w("3RD", 780, 600, 12), _w("FLOOR", 805, 600, 12),
             _w("+13.000", 160, 215), _w("+13.000", 320, 215), _w("+12.400", 300, 500)]
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
    assert sem["storey"]["name"] == "3RD FLOOR" and sem["storey"]["number"] == 3
    assert sem["storey"]["elevation_m"] == 13.0
    assert sem["door_height_m"] == 2.1
    codes = {e["code"]: e for e in sem["legend"]}
    assert codes["V-T"]["material"] == "Brick" and codes["LS-U"]["kind"] == "glass_partition"
    assert sem["wall_height_m"] >= 3.15
    assert any(t.get("fire_rating") == "EI60" for t in sem["door_tags"].values())


def test_too_little_evidence_no_crop():
    page = {"W_pt": 900, "H_pt": 700, "words": [_w("B301", 150, 180)]}
    region, st = ps.plan_region(page, _box(100, 100, 500, 300), [], [], MPT)
    assert region is None and "skipped" in st
