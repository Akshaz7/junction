"""pdf_fixtures on synthetic plan pages: stairs, sanitary, lifts, beds found; tile grids, hatches, columns not."""
import math

import pytest

from pipeline import pdf_fixtures as fx

MPT = 0.02  # 1 pt = 20 mm


def P(m):
    return m / MPT


def path(pts, closed=False, curves=0, fill=None):
    return {"pts": [[float(x), float(y)] for x, y in pts], "closed": closed, "fill": fill, "stroke": [0, 0, 0],
            "width": 0.3, "n_curves": curves, "is_arc": False, "obj": 0, "dashed": False, "pattern": None}


def line(x0, y0, x1, y1):
    return path([(P(x0), P(y0)), (P(x1), P(y1))])


def rect(x, y, w, h, **kw):
    return path([(P(x), P(y)), (P(x + w), P(y)), (P(x + w), P(y + h)), (P(x), P(y + h))], closed=True, **kw)


def ellipse(cx, cy, rx, ry, n=32):
    return path([(P(cx + rx * math.cos(2 * math.pi * k / n)), P(cy + ry * math.sin(2 * math.pi * k / n)))
                 for k in range(n)], closed=True, curves=4)


def wall_ring(x0, y0, x1, y1, t=0.2):
    """Four wall polygons (outer face at x0..x1) as pdf_vector.walls gives them."""
    def r(a, b, c, d):
        return {"polygon": [[P(a), P(b)], [P(c), P(b)], [P(c), P(d)], [P(a), P(d)]], "thickness_pt": P(t), "style": "fill"}
    return [r(x0, y0, x1, y0 + t), r(x0, y1 - t, x1, y1), r(x0, y0, x0 + t, y1), r(x1 - t, y0, x1, y1)]


def page_of(paths, words=()):
    return {"W_pt": P(30), "H_pt": P(20), "rotate": 0, "paths": paths, "words": list(words), "image_cover": 0.0}


def word(t, x, y):
    return {"text": t, "bbox": [P(x), P(y), P(x) + 10, P(y) + 4]}


ROOM = [[P(1), P(1)], [P(13), P(1)], [P(13), P(9)], [P(1), P(9)]]


def run(paths, words=(), walls=None, openings=()):
    walls = wall_ring(1, 1, 13, 9) if walls is None else walls
    rooms = [{"polygon": ROOM, "label": "Bath", "number": None}]
    return fx.detect(page_of(paths, words), walls, rooms, list(openings), MPT)


def kinds(out):
    d = {}
    for f in out:
        d[f["kind"]] = d.get(f["kind"], 0) + 1
    return d


def stair(x0=2, y0=2, width=1.0, n=10, g=0.27, walk=True):
    ps = [line(x0, y0 + k * g, x0 + width, y0 + k * g) for k in range(n)]
    ps += [line(x0, y0, x0, y0 + (n - 1) * g), line(x0 + width, y0, x0 + width, y0 + (n - 1) * g)]
    if walk:
        xm, y1 = x0 + width / 2, y0 + (n - 1) * g
        ps += [line(xm, y0, xm, y1), line(xm, y1, xm - 0.1, y1 - 0.15), line(xm, y1, xm + 0.1, y1 - 0.15)]
    return ps


def wc(cx=6.0, cy=1.2):
    # cistern against the top wall (inner face y=1.2), bowl below it
    return [rect(cx - 0.22, cy + 0.01, 0.44, 0.18), ellipse(cx, cy + 0.19 + 0.27, 0.19, 0.27)]


def test_stair_found_with_props():
    out = run(stair())
    st = [f for f in out if f["kind"] == "stair"]
    assert len(st) == 1
    pr = st[0]["props"]
    assert pr["treads"] == 9 and abs(pr["tread_depth_m"] - 0.27) < 0.01 and abs(pr["width_m"] - 1.0) < 0.02
    assert pr["direction"] is not None and pr["direction"][1] > 0.9   # arrow at the high-y end
    assert kinds(out).get("railing") == 2                             # both sides free-standing


def test_stair_needs_closed_ends_and_no_grid():
    # treads without stringers or walls at the ends: not a stair
    loose = [line(2, 2 + k * 0.27, 3, 2 + k * 0.27) for k in range(8)]
    assert kinds(run(loose)).get("stair") is None
    # a 0.3 m tile grid (lines both ways, bounded) is not a stair
    grid = [line(2, 2 + k * 0.3, 5, 2 + k * 0.3) for k in range(10)] + [line(2 + k * 0.3, 2, 2 + k * 0.3, 4.7) for k in range(11)]
    assert kinds(run(grid)).get("stair") is None
    # three lines are not enough
    assert kinds(run(stair(n=3, walk=False))).get("stair") is None


def test_hatch_inside_walls_ignored():
    thick = [{"polygon": [[P(2), P(2)], [P(5), P(2)], [P(5), P(4.5)], [P(2), P(4.5)]], "thickness_pt": P(2.5), "style": "fill"}]
    hatch = stair(2.1, 2.1, 1.0, 8)
    out = run(hatch, walls=wall_ring(1, 1, 13, 9) + thick)
    assert not out


def test_wc_shower_bath_basin():
    ps = wc()
    ps += [rect(9, 2, 0.9, 0.9), line(9, 2, 9.9, 2.9), line(9.9, 2, 9, 2.9)]                      # shower + cross
    ps += [rect(1.2, 6.5, 0.75, 1.7), ellipse(1.575, 7.35, 0.3, 0.75)]                               # bath
    ps += [ellipse(4.0, 1.2 + 0.22, 0.28, 0.21), ellipse(4.0, 1.2 + 0.24, 0.2, 0.14), ellipse(4.0, 1.46, 0.02, 0.02)]  # basin
    out = run(ps, words=[word("WC", 6.5, 2.2)])
    k = kinds(out)
    assert k.get("wc") == 1 and k.get("shower") == 1 and k.get("bath") == 1 and k.get("basin") == 1, k
    w = next(f for f in out if f["kind"] == "wc")
    assert "label WC" in w["props"]["evidence"]


def test_label_alone_is_not_a_fixture():
    out = run([], words=[word("WC", 5, 5), word("DU", 6, 5), word("LIFT", 7, 5), word("Porras", 8, 5)])
    assert out == []


def test_lift_and_shaft_and_column():
    walls = wall_ring(1, 1, 13, 9) + wall_ring(8, 5, 10, 7)
    ps = [line(8.2, 5.2, 9.8, 6.8), line(9.8, 5.2, 8.2, 6.8)]                         # X inside the wall ring
    ps += [rect(3, 6, 0.6, 0.6), line(3, 6, 3.6, 6.6), line(3.6, 6, 3, 6.6)]          # free column with an X
    out = run(ps, words=[word("LIFT", 8.6, 5.8)], walls=walls)
    k = kinds(out)
    assert k.get("lift") == 1 and "shaft" not in k, k
    out = run(ps, walls=walls)
    assert kinds(out) == {"shaft": 1}


def test_bed():
    ps = [rect(2, 1.2, 1.6, 2.0), rect(2.15, 1.3, 0.6, 0.4), rect(2.85, 1.3, 0.6, 0.4)]
    out = run(ps)
    assert kinds(out) == {"furniture": 1} and out[0]["props"]["type"] == "bed"


def test_nothing_without_scale_or_plan():
    assert fx.detect(page_of(stair()), wall_ring(1, 1, 13, 9), [], [], None) == []
    assert fx.detect({}, [], [], [], MPT) == []
    # symbols outside the building footprint (a legend) are ignored
    far = [rect(20, 15, 0.9, 0.9), line(20, 15, 20.9, 15.9), line(20.9, 15, 20, 15.9)]
    assert run(far) == []


def test_door_swing_zone_blocks():
    ps = [rect(9, 2, 0.9, 0.9), line(9, 2, 9.9, 2.9), line(9.9, 2, 9, 2.9)]
    door = {"kind": "door", "bbox": [P(8.8), P(1.8), P(10), P(3)], "props": {"swing_bbox": [P(8.8), P(1.8), P(10), P(3)]}}
    assert kinds(run(ps, openings=[door])).get("shower") is None


def _ifc_with_storey():
    ifcopenshell = pytest.importorskip("ifcopenshell")
    import ifcopenshell.api.aggregate
    import ifcopenshell.api.context
    import ifcopenshell.api.project
    import ifcopenshell.api.root
    import ifcopenshell.api.unit
    f = ifcopenshell.api.project.create_file(version="IFC4")
    proj = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="t")
    ifcopenshell.api.unit.assign_unit(f, length={"is_metric": True, "raw": "METERS"})
    model = ifcopenshell.api.context.add_context(f, context_type="Model")
    body = ifcopenshell.api.context.add_context(f, context_type="Model", context_identifier="Body",
                                                target_view="MODEL_VIEW", parent=model)
    site = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Site")
    bldg = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name="B")
    st = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name="Floor 1")
    ifcopenshell.api.aggregate.assign_object(f, products=[site], relating_object=proj)
    ifcopenshell.api.aggregate.assign_object(f, products=[bldg], relating_object=site)
    ifcopenshell.api.aggregate.assign_object(f, products=[st], relating_object=bldg)
    pl = f.createIfcLocalPlacement(None, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)), None, None))
    site.ObjectPlacement = bldg.ObjectPlacement = st.ObjectPlacement = pl
    return f, st, body


def test_to_ifc_authors_valid_entities(tmp_path):
    f, st, body = _ifc_with_storey()
    ps = stair(n=15) + wc() + [rect(9, 2, 0.9, 0.9), line(9, 2, 9.9, 2.9), line(9.9, 2, 9, 2.9)]
    ps += [ellipse(4.0, 1.42, 0.28, 0.21), ellipse(4.0, 1.44, 0.2, 0.14), ellipse(4.0, 1.46, 0.02, 0.02)]
    ps += [rect(2, 6.8, 1.6, 2.0), rect(2.15, 8.3, 0.6, 0.4), rect(2.85, 8.3, 0.6, 0.4)]
    walls = wall_ring(1, 1, 13, 9) + wall_ring(8, 5, 10, 7)
    ps += [line(8.2, 5.2, 9.8, 6.8), line(9.8, 5.2, 8.2, 6.8)]
    found = run(ps, words=[word("LIFT", 8.6, 5.8)], walls=walls)
    c = fx.to_ifc(f, st, body, found, 0.0, storey_height_m=2.8, m_per_pt=MPT, doc_id="t", page=1)
    assert c.get("IfcStair") == 1 and c.get("IfcStairFlight") == 1 and c.get("IfcRailing") == 2
    assert c.get("IfcSanitaryTerminal") == 3 and c.get("IfcTransportElement") == 1 and c.get("IfcFurniture") == 1, c
    assert "errors" not in c
    fl = f.by_type("IfcStairFlight")[0]
    assert fl.NumberOfRisers == 15 and abs(fl.RiserHeight - 2.8 / 15) < 1e-3 and abs(fl.TreadLength - 0.27) < 0.01
    assert fl.Decomposes and fl.Decomposes[0].RelatingObject.is_a("IfcStair")
    import ifcopenshell.util.element as ue
    pdts = sorted(ue.get_predefined_type(e) for e in f.by_type("IfcSanitaryTerminal"))
    assert pdts == ["SHOWER", "TOILETPAN", "WASHHANDBASIN"]
    for e in f.by_type("IfcSanitaryTerminal") + f.by_type("IfcRailing") + f.by_type("IfcFurniture"):
        assert e.IsTypedBy and e.Representation
        assert e.ContainedInStructure and e.ContainedInStructure[0].RelatingStructure == st
    assert ue.get_predefined_type(f.by_type("IfcRailing")[0]) == "GUARDRAIL"
    # 10 drawn lines under a 2.8 m storey would mean 280 mm risers: the flight is cut, risers come from the height
    assert fx._risers(2.8, 9) == (16, 0.175)
    # geometry in model metres: the WC sits near x = 6 m, y = -1.5 m
    out = tmp_path / "t.ifc"
    f.write(str(out))
    import ifcopenshell.validate
    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(ifcopenshell.open(str(out)), log)
    assert not log.statements, log.statements[:3]
    gids = [e.GlobalId for e in f.by_type("IfcRoot")]
    assert len(gids) == len(set(gids))


def test_to_ifc_empty_and_bad_input():
    f, st, body = _ifc_with_storey()
    assert fx.to_ifc(f, st, body, [], 0.0, m_per_pt=MPT) == {}
    c = fx.to_ifc(f, st, body, [{"kind": "wc", "polygon": [[0, 0], [0, 0], [0, 0]]}, {"kind": "nope", "polygon": [[0, 0]]}],
                  0.0, m_per_pt=MPT)
    assert c.get("IfcSanitaryTerminal") is None


# ---------------------------------------------------------------- recall round 2: CAD-exploded symbols, kitchens


def loose_rect(x, y, w, h):
    """A rectangle exploded into four 2-point lines (how CAD exports draw symbols)."""
    return [line(x, y, x + w, y), line(x + w, y, x + w, y + h), line(x + w, y + h, x, y + h), line(x, y + h, x, y)]


def loose_rounded(x, y, w, h, r, gap=None, n=6):
    """Rounded rectangle as loose segments (arcs flattened); gap=(x0, x1) leaves the bottom edge open there."""
    segs = []
    corners = [(x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)]
    for cx, cy, a0 in corners:
        pts = [(cx + r * math.cos(math.radians(a0 + 90 * k / n)), cy + r * math.sin(math.radians(a0 + 90 * k / n)))
               for k in range(n + 1)]
        segs += [line(*pts[k], *pts[k + 1]) for k in range(n)]
    segs += [line(x + r, y, x + w - r, y), line(x + w, y + r, x + w, y + h - r), line(x, y + h - r, x, y + r)]
    if gap:
        segs += [line(x + w - r, y + h, gap[1], y + h), line(gap[0], y + h, x + r, y + h)]
    else:
        segs += [line(x + w - r, y + h, x + r, y + h)]
    return segs


def run_room(paths, label, words=(), rooms=True):
    walls = wall_ring(1, 1, 13, 9)
    rs = [{"polygon": ROOM, "label": label, "number": None}] if rooms else [{"polygon": None, "label": label}]
    return fx.detect(page_of(paths, words), walls, rs, [], MPT)


def vanity(x=5.0, y=1.2):
    """Vanity top against the top wall with a rounded basin; the tap stem closes the bowl's inner outline."""
    ps = loose_rect(x - 0.6, y, 1.2, 0.6)
    ps += loose_rounded(x - 0.25, y + 0.05, 0.5, 0.44, 0.06)
    ps += loose_rounded(x - 0.21, y + 0.09, 0.42, 0.34, 0.05, gap=(x - 0.012, x + 0.012))
    ps += [line(x - 0.012, y + 0.30, x - 0.012, y + 0.47), line(x + 0.012, y + 0.30, x + 0.012, y + 0.47),
           line(x - 0.012, y + 0.30, x + 0.012, y + 0.30)]
    return ps


def test_exploded_vanity_basin_found_without_room_polygons():
    out = run_room(vanity(), "Bath", rooms=False)
    assert kinds(out).get("basin") == 1, kinds(out)


def test_kitchen_sink_cut_into_counter_and_hob_counter():
    ps = []
    # counter edge line 0.6 m off the top wall (inner face y=1.2), cut at the sink's corners
    ps += [line(2, 1.8, 4.0, 1.8), line(4.8, 1.8, 7.5, 1.8)]
    ps += loose_rect(4.0, 1.3, 0.8, 0.5) + loose_rect(4.05, 1.35, 0.7, 0.36)            # square-cornered sink
    pale = [dict(line(x, 1.8, x, 4.0), stroke=[0.88, 0.88, 0.88]) for x in (4.2, 4.4, 4.6)]  # floor hatch to the edge
    ps += pale
    # hob: four burner rings, counter edge broken around it
    ps += [ellipse(9.2, 1.4, 0.08, 0.08), ellipse(9.6, 1.4, 0.1, 0.1), ellipse(9.2, 1.62, 0.08, 0.08),
           ellipse(9.6, 1.62, 0.08, 0.08)]
    ps += [line(8.0, 1.8, 9.0, 1.8), line(9.8, 1.8, 11.0, 1.8)]
    out = run_room(ps, "Kitchen", words=[word("SINK", 4.2, 1.5)])
    k = kinds(out)
    assert k.get("sink") == 1 and k.get("counter", 0) >= 2, k
    for f in out:
        if f["kind"] == "counter":
            assert 0.5 <= f["props"]["size_m"][1] <= 0.75


def test_square_box_in_box_outside_wet_rooms_is_not_a_sink():
    ps = [line(2, 1.8, 7.5, 1.8)] + loose_rect(4.0, 1.3, 0.8, 0.5) + loose_rect(4.05, 1.35, 0.7, 0.36)
    out = run_room(ps, "Office")
    assert "sink" not in kinds(out) and "basin" not in kinds(out), kinds(out)


def test_callout_bubble_text_still_blocks_basin():
    out = run_room(vanity(), "Bath", words=[word("A480", 4.9, 1.4)])
    assert "basin" not in kinds(out), kinds(out)


def test_locker_banks_near_label():
    # two 0.5 x 2.0 m banks; the LOCKERS word is printed inside one of them; the room is a changing room
    ps = [rect(4, 3, 2.0, 0.5), rect(4, 4.2, 2.0, 0.5)]
    out = fx.detect(page_of(ps, [word("LOCKERS", 4.6, 3.2)]), wall_ring(1, 1, 13, 9),
                    [{"polygon": ROOM, "label": "Changing room", "number": None}], [], MPT)
    lk = [f for f in out if f["kind"] == "furniture" and f["props"].get("type") == "locker"]
    assert len(lk) == 2, out
    # without the word: no lockers
    out = fx.detect(page_of(ps), wall_ring(1, 1, 13, 9), [{"polygon": ROOM, "label": "Changing room", "number": None}],
                    [], MPT)
    assert not [f for f in out if f["props"].get("type") == "locker"]


def test_equipment_box_with_printed_tag_and_height():
    ps = [rect(3, 3, 4.0, 1.2), rect(3, 6, 1.5, 1.0)]
    words = [word("AHU", 3.3, 3.5), word("h=1800", 4.5, 3.5), word("LTO", 3.4, 6.4)]
    out = fx.detect(page_of(ps, words), wall_ring(1, 1, 13, 9), [{"polygon": ROOM, "label": "AHU room", "number": None}],
                    [], MPT)
    eq = sorted((f for f in out if f["kind"] == "equipment"), key=lambda f: f["props"]["size_m"][0])
    assert len(eq) == 2, out
    assert eq[1]["props"]["height_m"] == 1.8 and eq[1]["props"]["tag"] == "AHU"
    assert "height_m" not in eq[0]["props"]  # no printed height: to_ifc uses a marked default
    # the same boxes without a tag are not equipment
    out = fx.detect(page_of(ps), wall_ring(1, 1, 13, 9), [], [], MPT)
    assert not [f for f in out if f["kind"] == "equipment"]


def test_spiral_stair_from_circle_and_radial_lines():
    import math
    cx, cy, r = 6.0, 5.0, 0.8
    ps = [ellipse(cx, cy, r, r, n=48)]
    for k in range(12):  # 12 radial tread lines over 300 degrees, gap at the entry
        a = math.radians(k * 25)
        ps.append(line(cx + 0.1 * math.cos(a), cy + 0.1 * math.sin(a), cx + r * math.cos(a), cy + r * math.sin(a)))
    out = run(ps, words=[word("N", 7.2, 5.0), word("180", 7.5, 5.0)])
    st = [f for f in out if f["kind"] == "stair" and f["props"].get("spiral")]
    assert len(st) == 1, out
    assert st[0]["props"]["treads"] == 12 and st[0]["props"]["diameter_m"] == pytest.approx(1.6, abs=0.05)
    assert st[0]["props"]["riser_printed_m"] == pytest.approx(0.18)
