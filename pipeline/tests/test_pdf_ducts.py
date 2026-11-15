"""pipeline.pdf_ducts: false-duct rules, size labels, damper split, never raises (synthetic pages only)."""
import numpy as np

from pipeline import pdf_ducts as PD

MPT = 0.0254 / 72 * 50       # 1:50


def _page(lines, words=(), fills=()):
    """lines: [((x0,y0),(x1,y1)), ...] black 0.5 pt strokes; fills: closed filled black polygons."""
    xy, paths = [], []
    for a, b in lines:
        i0 = len(xy)
        xy += [a, b]
        paths.append({"i0": i0, "i1": len(xy), "closed": False, "stroke": (0, 0, 0), "fill": None, "width": 0.48,
                      "dashed": False, "layer": None, "curves": 0})
    for poly in fills:
        i0 = len(xy)
        xy += list(poly) + [poly[0]]
        paths.append({"i0": i0, "i1": len(xy), "closed": True, "stroke": None, "fill": (0, 0, 0), "width": 0.0,
                      "dashed": False, "layer": None, "curves": 0})
    return {"W_pt": 2000.0, "H_pt": 2000.0, "xy": np.array(xy, float), "paths": paths, "words": list(words)}


def _duct(x0, x1, y, w_m):
    g = w_m / MPT
    return {"start_pt": [x0, y], "end_pt": [x1, y], "width_pt": g, "width_m": w_m, "length_m": (x1 - x0) * MPT,
            "outline_pt": [[x0, y - g / 2], [x1, y - g / 2], [x1, y + g / 2], [x0, y + g / 2]]}


def _sides(x0, x1, y, w_m):
    g = w_m / MPT
    return [((x0, y - g / 2), (x1, y - g / 2)), ((x0, y + g / 2), (x1, y + g / 2))]


def _word(t, x, y, h=6.0):
    return {"text": t, "bbox": [x, y - h / 2, x + len(t) * h * 0.6, y + h / 2]}


def test_parse_labels_forms():
    W = [_word("400x200", 0, 0), _word("Ø280", 100, 0), _word("ø", 200, 0, 6), _word("180", 204, 0, 6),
         _word("DN140", 300, 0), _word("l/s", 400, 0)]
    got = {(t, s, a, b) for _, _, t, s, a, b in PD.parse_labels(W)}
    assert ("400x200", "rect", 400, 200) in got
    assert ("Ø280", "round", 280, 280) in got
    assert ("ø180", "round", 180, 180) in got
    assert ("DN140", "round", 140, 140) in got
    assert len(got) == 4


def test_leader_band_rejected_and_sized_duct_kept():
    real = _duct(100, 400, 500, 0.4)              # 400x200 duct, label beside it
    band = _duct(100, 400, 900, 0.2)              # band crossed by 6 leaders
    g = 0.2 / MPT
    leaders = [((150 + 40 * k, 900 - g * 2), (170 + 40 * k, 900 + g * 2)) for k in range(6)]
    page = _page(_sides(100, 400, 500, 0.4) + _sides(100, 400, 900, 0.2) + leaders,
                 words=[_word("400x200", 200, 500 - 0.4 / MPT)])
    D, T, rep = PD.refine([real, band], [], page, MPT)
    assert rep["ok"] and len(D) == 1 and rep["rejects"] == {"leaders": 1}
    assert D[0]["props"]["w_m"] == 0.4 and D[0]["props"]["h_m"] == 0.2


def test_text_frame_rejected_and_round_size():
    frame = _duct(100, 200, 300, 0.3)
    pipe = _duct(100, 400, 700, 0.25)
    page = _page(_sides(100, 200, 300, 0.3) + _sides(100, 400, 700, 0.25),
                 words=[_word("NOTETEXT", 110, 300), _word("Ø280", 250, 700 + 0.3 / MPT)])
    D, _, rep = PD.refine([frame, pipe], [], page, MPT)
    assert len(D) == 1 and rep["rejects"] == {"text": 1}
    assert D[0]["props"]["d_m"] == 0.28


def test_no_label_leaves_size_unset():
    d = _duct(100, 400, 500, 0.3)
    D, _, _ = PD.refine([d], [], _page(_sides(100, 400, 500, 0.3)), MPT)
    assert len(D) == 1 and "w_m" not in D[0]["props"] and "d_m" not in D[0]["props"]


def test_damper_vs_terminal():
    s = 0.2 / MPT / 2
    # terminal at a duct END (duct comes in from the left only) vs damper with the duct passing through
    term = {"center_pt": [500, 500], "size_pt": 2 * s, "size_m": 0.2, "shape": "square"}
    damp = {"center_pt": [500, 900], "size_pt": 2 * s, "size_m": 0.2, "shape": "square"}
    box = lambda cx, cy: [((cx - s, cy - s), (cx + s, cy - s)), ((cx + s, cy - s), (cx + s, cy + s)),
                          ((cx + s, cy + s), (cx - s, cy + s)), ((cx - s, cy + s), (cx - s, cy - s)),
                          ((cx - s, cy - s), (cx + s, cy + s)), ((cx + s, cy - s), (cx - s, cy + s))]
    lines = box(500, 500) + box(500, 900)
    lines += [((500 - s, 500 - s * 0.8), (300, 500 - s * 0.8)), ((500 - s, 500 + s * 0.8), (300, 500 + s * 0.8))]
    lines += [((500 - s, 900 - s * 0.8), (300, 900 - s * 0.8)), ((500 + s, 900 - s * 0.8), (700, 900 - s * 0.8))]
    _, T, rep = PD.refine([], [term, damp], _page(lines), MPT)
    assert [t["center_pt"] for t in T] == [[500, 500]] and T[0]["kind"] == "terminal"
    assert [t["center_pt"] for t in rep["dampers"]] == [[500, 900]]


def test_symbol_on_run_with_tag_leader_is_terminal():
    """A symbol a duct passes through is a damper, unless a tag leader (long oblique stroke) ends at it."""
    s = 0.2 / MPT / 2
    box = lambda cx, cy: [((cx - s, cy - s), (cx + s, cy - s)), ((cx + s, cy - s), (cx + s, cy + s)),   # noqa: E731
                          ((cx + s, cy + s), (cx - s, cy + s)), ((cx - s, cy + s), (cx - s, cy - s)),
                          ((cx - s, cy - s), (cx + s, cy + s)), ((cx + s, cy - s), (cx - s, cy + s))]
    run = lambda cy: [((500 - s, cy - s * 0.8), (300, cy - s * 0.8)), ((500 + s, cy - s * 0.8), (700, cy - s * 0.8))]  # noqa: E731
    lines = box(500, 500) + run(500) + box(500, 900) + run(900)
    lines += [((500 + s, 900 - s), (500 + s + 2.0 / MPT, 900 - s - 1.5 / MPT))]     # 2.5 m oblique leader to it
    a = {"center_pt": [500, 500], "size_pt": 2 * s, "size_m": 0.2, "shape": "square"}
    b = {"center_pt": [500, 900], "size_pt": 2 * s, "size_m": 0.2, "shape": "square"}
    _, T, rep = PD.refine([], [a, b], _page(lines), MPT)
    assert [t["center_pt"] for t in T] == [[500, 900]]
    assert [t["center_pt"] for t in rep["dampers"]] == [[500, 500]]


def test_never_raises():
    D = [{"start_pt": None}]
    out = PD.refine(D, [], {"paths": None}, MPT)
    assert out[0] == D and out[2]["ok"] is False


def test_vtext_labels_sizes_only_and_hard_cap(monkeypatch):
    """Stroke-text reader: only words that parse as a duct size come back as labels; a reader that overruns the
    cap is killed and gives no labels; PDF_VTEXT=0 turns it off."""
    import sys
    import time
    import types
    from pipeline import pdf_ducts as PD
    w = lambda t, x: {"text": t, "bbox": [x, 10.0, x + 20.0, 16.0]}   # noqa: E731
    fake = types.SimpleNamespace(words=lambda page, budget_s=0, **k: [w("Ø180", 0), w("+55", 30), w("l/s", 60),
                                                                   w("400x200", 90), w("AB-12", 120)])
    monkeypatch.setitem(sys.modules, "pipeline.pdf_vtext", fake)
    import pipeline
    monkeypatch.setattr(pipeline, "pdf_vtext", fake, raising=False)
    got = PD._vtext_labels({}, budget_s=10)
    assert sorted(g[2] for g in got) == ["400x200", "Ø180"]
    assert {g[3] for g in got} == {"round", "rect"}

    def slow(page, budget_s=0, **k):
        time.sleep(30)
        return [w("Ø180", 0)]
    fake.words = slow
    t = time.time()
    assert PD._vtext_labels({}, budget_s=2) == [] and time.time() - t < 6
    monkeypatch.setenv("PDF_VTEXT", "0")
    fake.words = lambda page, budget_s=0, **k: [w("Ø180", 0)]
    assert PD._vtext_labels({}, budget_s=10) == []


# ---------------------------------------------------------------- r6 rules (synthetic pages, generic numbers)
def _dashes(x0, x1, y, dash_m=0.3, gap_m=0.1):
    out, x = [], x0
    while x < x1:
        out.append(((x, y), (min(x + dash_m / MPT, x1), y)))
        x += (dash_m + gap_m) / MPT
    return out


def _arc(cx, cy, r, a0, a1, n=12):
    th = np.radians(np.linspace(a0, a1, n))
    return [(cx + r * np.cos(t), cy + r * np.sin(t)) for t in th]


def _page_poly(lines, polys=(), closed=(), words=()):
    page = _page(lines, words)
    xy = page["xy"].tolist()
    for P, cl in [(p, False) for p in polys] + [(p, True) for p in closed]:
        i0 = len(xy)
        xy += [list(q) for q in P] + ([list(P[0])] if cl else [])
        page["paths"].append({"i0": i0, "i1": len(xy), "closed": cl, "stroke": (0, 0, 0), "fill": None,
                              "width": 0.48, "dashed": False, "layer": None, "curves": 0})
    page["xy"] = np.array(xy, float)
    return page


def test_dash_dot_sides_flagged_or_dropped(monkeypatch):
    solid = _duct(100, 400, 500, 0.3)
    dashed = _duct(100, 400, 900, 0.3)
    g = 0.3 / MPT
    page = _page(_sides(100, 400, 500, 0.3) + _dashes(100, 400, 900 - g / 2) + _dashes(100, 400, 900 + g / 2))
    D, _, rep = PD.refine([solid, dashed], [], page, MPT)       # default: kept, flagged
    assert len(D) == 2 and [d.get("linetype") for d in D] == [None, "dashed"] and len(rep["dashed_runs"]) == 1
    assert "dash-dot" in D[1]["evidence"] and "dash-dot" not in D[0]["evidence"]
    monkeypatch.setenv("PDF_DUCTS_DASHED", "drop")
    D, _, rep = PD.refine([solid, dashed], [], page, MPT)
    assert len(D) == 1 and D[0]["start_pt"] == [100, 500] and rep["rejects"].get("dashed") == 1


def test_stacked_duplicate_dropped_and_collinear_merged():
    big = _duct(100, 500, 500, 0.5)
    inner = _duct(150, 300, 505, 0.2)             # lies inside big's band
    a, b = _duct(100, 300, 900, 0.3), _duct(280, 520, 900, 0.3)   # one run drawn in two overlapping pieces
    lines = _sides(100, 500, 500, 0.5) + _sides(150, 300, 505, 0.2) + _sides(100, 520, 900, 0.3)
    D, _, rep = PD.refine([big, inner, a, b], [], _page(lines), MPT)
    assert len(D) == 2 and rep["rejects"].get("stacked") == 1 and rep["merged"] == 1
    run = [d for d in D if d["start_pt"][1] == 900][0]
    assert abs(run["start_pt"][0] - 100) < 1e-6 and abs(run["end_pt"][0] - 520) < 1e-6


def test_runs_and_terminals_inside_machine_outline_dropped():
    s = 1.0 / MPT
    rect = [(1000, 1000), (1000 + 3 * s, 1000), (1000 + 3 * s, 1000 + 1.5 * s), (1000, 1000 + 1.5 * s)]
    fans = [_arc(1000 + s, 1000 + 0.75 * s, 0.3 * s, 0, 360, 24), _arc(1000 + 2 * s, 1000 + 0.75 * s, 0.3 * s, 0, 360, 24)]
    inside = _duct(1000 + 0.2 * s, 1000 + 2.8 * s, 1000 + 0.3 * s, 0.2)
    outside = _duct(100, 400, 500, 0.3)
    t_in = {"center_pt": [1000 + s, 1000 + 0.75 * s], "size_pt": 0.6 * s, "size_m": 0.6, "shape": "round"}
    t_tag = dict(t_in, center_pt=[1000 + 2 * s, 1000 + 0.75 * s], source="tag")
    page = _page_poly(_sides(100, 400, 500, 0.3) + _sides(1000 + 0.2 * s, 1000 + 2.8 * s, 1000 + 0.3 * s, 0.2),
                      closed=[rect] + fans)
    D, T, rep = PD.refine([inside, outside], [t_in, t_tag], page, MPT)
    assert len(D) == 1 and rep["rejects"].get("equipment") == 1
    assert [t.get("source") for t in T] == ["tag"] and rep["terminals_in_equipment"] == 1


def test_concentric_arcs_are_a_bend_full_circles_are_not(monkeypatch):
    monkeypatch.setenv("PDF_DUCTS_EXTRA", "1")
    r_in, r_out = 0.4 / MPT, 0.8 / MPT
    arcs = [_arc(800, 800, r_in, 0, 90), _arc(800, 800, r_out, 0, 90),
            _arc(1500, 1500, 0.2 / MPT, 0, 180), _arc(1500, 1500, 0.2 / MPT, 180, 360),       # a ring symbol
            _arc(1500, 1500, 0.4 / MPT, 0, 180), _arc(1500, 1500, 0.4 / MPT, 180, 360)]
    page = _page_poly(_sides(100, 400, 500, 0.3), polys=arcs)
    D, _, rep = PD.refine([_duct(100, 400, 500, 0.3)], [], page, MPT)
    bends = [d for d in D if d.get("fitting") == "bend"]
    assert rep["added"]["bends"] == len(bends) == 2 and rep["bends"] == 1     # one 90 deg bend in 45 deg chords
    assert all(abs(d["width_m"] - 0.4) < 0.01 for d in bends)
    c = np.mean([d["start_pt"] for d in bends], axis=0)
    assert np.hypot(*(c - 800)) < r_out


def test_small_round_duct_two_lines_and_centre_line_across_a_valve(monkeypatch):
    monkeypatch.setenv("PDF_DUCTS_EXTRA", "1")
    g = 0.16 / MPT
    y = 1200
    lines = [((300, y - g / 2), (330, y - g / 2)), ((300, y + g / 2), (330, y + g / 2)),       # 0.53 m piece
             ((345, y - g / 2), (380, y - g / 2)), ((345, y + g / 2), (380, y + g / 2))]       # valve gap, 2nd piece
    lines += [((300 + 8 * k, y), (305 + 8 * k, y)) for k in range(10)]                           # dash-dot centre
    page = _page(_sides(100, 400, 500, 0.3) + lines)
    D, _, rep = PD.refine([_duct(100, 400, 500, 0.3)], [], page, MPT)
    rp = [d for d in D if d.get("source") == "round pair"]
    assert rep["added"]["round_pairs"] == 1 and len(rp) == 1
    assert abs(rp[0]["width_m"] - 0.16) < 0.01 and abs(rp[0]["start_pt"][0] - 300) < 1 and abs(rp[0]["end_pt"][0] - 380) < 1


def test_parse_printed_grammar():
    W = [_word("Ø355L50", 0, 0), _word("1500x700L60PK", 100, 0), _word("Ø280EI30", 200, 0), _word("KL", 300, 0),
         _word("+9.45", 314, 0), _word("AK+8.20", 400, 0), _word("S1-700x100", 500, 0), _word("DN125", 600, 0)]
    got = {(r["text"], r["kind"], r.get("a_mm"), r.get("ins_mm"), r.get("elev_m"), r.get("ref")) for r in PD.parse_printed(W)}
    assert ("Ø355L50", "round", 355, 50, None, None) in got
    assert ("1500x700L60PK", "rect", 1500, 60, None, None) in got
    assert ("Ø280EI30", "round", 280, 0, None, None) in got
    assert ("KL+9.45", "elev", None, None, 9.45, "centre") in got
    assert ("AK+8.20", "elev", None, None, 8.2, "bottom") in got
    assert ("DN125", "round", 125, 0, None, None) in got
    assert len(got) == 6        # the type tag is not a duct size


def test_printed_size_needs_near_and_along():
    a = _duct(100, 400, 500, 0.28)       # label beside it, written along: round, printed
    b = _duct(100, 400, 900, 0.28)       # label 1.6 m away: not its label
    c = _duct(100, 400, 1300, 0.28)      # label close but written across (vertical): not its label
    lines = _sides(100, 400, 500, 0.28) + _sides(100, 400, 900, 0.28) + _sides(100, 400, 1300, 0.28)
    v = {"text": "Ø280", "bbox": [200, 1300 - 0.5 / MPT - 20, 206, 1300 - 0.5 / MPT], "angle": 90}
    words = [_word("Ø280", 200, 500 + 0.4 / MPT), _word("Ø280", 200, 900 + 1.6 / MPT), v]
    D, _, rep = PD.refine([a, b, c], [], _page(lines, words), MPT)
    by = {d["start_pt"][1]: d for d in D}
    assert by[500]["shape"] == "round" and by[500]["diameter_m"] == 0.28 and by[500]["props"]["shape_source"] == "printed"
    for y in (900, 1300):
        assert by[y]["shape"] == "rect" and by[y]["props"]["shape_source"].startswith("default")
        assert "d_m" not in by[y]["props"]


def test_elevation_label_attached():
    d = _duct(100, 400, 500, 0.3)
    D, _, rep = PD.refine([d], [], _page(_sides(100, 400, 500, 0.3), [_word("KL+9.45", 200, 500 + 0.3 / MPT)]), MPT)
    assert rep["elevations"] == 1 and D[0]["elev_m"] == 9.45 and D[0]["elev_ref"] == "centre"


def test_band_cut_into_pieces_judged_as_one():
    """Leaders crossing a band: 2 per piece is under the limit, 6 over the whole band of 3 pieces -> all rejected."""
    g = 0.25 / MPT
    pieces = [_duct(100 + 120 * k, 210 + 120 * k, 900, 0.25) for k in range(3)]
    lines = []
    for k in range(3):
        lines += _sides(100 + 120 * k, 210 + 120 * k, 900, 0.25)
        lines += [((130 + 120 * k + 40 * m, 900 - g * 2), (140 + 120 * k + 40 * m, 900 + g * 2)) for m in range(2)]
    D, _, rep = PD.refine(pieces + [_duct(100, 400, 500, 0.3)], [], _page(lines + _sides(100, 400, 500, 0.3)), MPT)
    assert len(D) == 1 and rep["rejects"].get("leaders") == 3


def test_extra_runs_switch_off(monkeypatch):
    monkeypatch.setenv("PDF_DUCTS_EXTRA", "0")
    r_in, r_out = 0.4 / MPT, 0.8 / MPT
    page = _page_poly(_sides(100, 400, 500, 0.3), polys=[_arc(800, 800, r_in, 0, 90), _arc(800, 800, r_out, 0, 90)])
    D, _, rep = PD.refine([_duct(100, 400, 500, 0.3)], [], page, MPT)
    assert len(D) == 1 and rep["added"] == {"bends": 0, "round_pairs": 0, "single_line": 0}
