"""pdf_mep false-pair rules (label frames, grid lines), symbol terminals drawn as open linework, and reusing the page
pdf_vector already read. Synthetic sheets at 1:100 (m_per_pt 0.0352778)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline import pdf_mep as M  # noqa: E402
from pipeline.tests.test_pdf_mep import _vent_single  # noqa: E402
from pipeline.tests.test_pdf_openings import _pdf  # noqa: E402

MPT = 0.0254 / 72 * 100
DUCT = ["0 G 1.4 w", "100 260 m 300 260 l S", "100 270 m 300 270 l S", "100 260 m 100 270 l S"]   # 7 m run + cap


def _black(page):
    return np.array([p["stroke"] == (0, 0, 0) for p in page["paths"]], bool)


def _circle(cx, cy, r):
    k = 0.5523 * r
    return (f"{cx + r} {cy} m {cx + r} {cy + k} {cx + k} {cy + r} {cx} {cy + r} c "
            f"{cx - k} {cy + r} {cx - r} {cy + k} {cx - r} {cy} c {cx - r} {cy - k} {cx - k} {cy - r} {cx} {cy - r} c "
            f"{cx + k} {cy - r} {cx + r} {cy - k} {cx + r} {cy} c S")


def test_label_frame_around_text_is_not_a_duct(tmp_path):
    # a label frame drawn as four loose lines (2.1 m x 0.42 m) round a tag: closed at both ends like a duct
    frame = ["400 100 m 460 100 l S", "400 112 m 460 112 l S", "400 100 m 400 112 l S", "460 100 m 460 112 l S"]
    pg = M.load(_pdf(tmp_path / "frame.pdf", DUCT + frame, [(405, 103, 8, "SUPPLY"), (432, 103, 8, "AHU1")]))
    D = M.ducts(pg, _black(pg), MPT)
    assert len(D) == 1 and abs(D[0]["length_m"] - 7.06) < 0.1
    assert M.LAST_REJECTS.get("encloses text", 0) >= 1


def test_size_label_inside_a_duct_keeps_it(tmp_path):
    pg = M.load(_pdf(tmp_path / "lab.pdf", DUCT, [(180, 262, 6, "400x200")]))
    D = M.ducts(pg, _black(pg), MPT)
    assert len(D) == 1 and D[0]["label"] == "400x200"


def test_grid_line_pair_with_bubbles_is_rejected(tmp_path):
    ops = list(DUCT)
    for y in (340, 348):            # two dash-dot grid lines 0.28 m apart, exploded into dashes, bubble at one end
        ops += [f"{x} {y} m {x + 30} {y} l S" for x in range(40, 520, 36)]
    ops += [_circle(520 + 11.5, 340, 11.3), _circle(520 + 11.5, 360, 11.3)]
    pg = M.load(_pdf(tmp_path / "grid.pdf", ops, []))
    D = M.ducts(pg, _black(pg), MPT)
    assert len(D) == 1 and abs(np.mean([D[0]["start_pt"][1], D[0]["end_pt"][1]]) - (pg["H_pt"] - 265)) < 2
    assert M.LAST_REJECTS.get("grid bubble", 0) + M.LAST_REJECTS.get("full span", 0) >= 1


def test_open_linework_terminals_repeat(tmp_path):
    ops = list(DUCT)
    for x in (400, 440, 480):        # square diffusers 0.42 m: open outline + two loose diagonals, three alike
        ops += [f"{x} 330 m {x + 12} 330 l {x + 12} 342 l {x} 342 l {x} 330 l S",
                f"{x} 330 m {x + 12} 342 l S", f"{x + 12} 330 m {x} 342 l S"]
    ops += ["400 370 m 412 370 l 412 382 l 400 382 l 400 370 l S"]          # a plain square: no X, not a terminal
    pg = M.load(_pdf(tmp_path / "terms.pdf", ops, []))
    sel = _black(pg)
    D = M.ducts(pg, sel, MPT)
    TT = M.symbol_terminals(pg, sel, MPT, D, M.terminals(pg, sel, MPT))
    assert len(TT) == 3 and all(t["shape"] == "square" and t["repeat"] == 3 for t in TT)
    assert all(abs(t["size_m"] - 0.42) < 0.03 for t in TT)
    r = M.detect(pg, MPT, sel)
    assert len(r["terminals"]) >= 3


def test_vector_page_reuse_matches_load(tmp_path):
    from pipeline.pdf_vector import load_page
    pdf = _vent_single(tmp_path)
    a = M.load(pdf)
    b = M.from_vector_page(load_page(pdf), pdf, 0)
    assert len(a["paths"]) == len(b["paths"]) and [w["text"] for w in a["words"]] == [w["text"] for w in b["words"]]
    ka = sorted((p["stroke"], p["closed"]) for p in a["paths"] if p["stroke"])
    kb = sorted((p["stroke"], p["closed"]) for p in b["paths"] if p["stroke"])
    assert ka == kb
    da, db = M.ducts(a, _black(a), MPT), M.ducts(b, _black(b), MPT)
    assert len(da) == len(db) >= 1
    assert M.prime(pdf, 0, load_page(pdf)) and M._load_cached(pdf, 0)["paths"]
    M._CACHE.clear()


def test_shell_walls_reads_grey_underlay_only(monkeypatch):
    """MEP sheet shell: wall bands from the neutral-grey underlay pairs only (black duct pens ignored); thin pairs,
    short bits and a band read twice are dropped; a page with no underlay falls back to the given detector."""
    from pipeline import pdf_mep as M
    grey, black = [0.5, 0.5, 0.5], [0.0, 0.0, 0.0]
    seg = lambda c, y, x0=0.0, x1=400.0: {"pts": [[x0, y], [x1, y]], "stroke": c, "fill": None, "closed": False,
                                          "width": 0.5, "dashed": False, "n_curves": 0}
    # grey: three 0.2 m wall bands (11.3 pt at 1:50) far apart + filler grey bits
    paths = []
    for y in (100.0, 300.0, 500.0):
        paths += [seg(grey, y), seg(grey, y + 11.3)]
        paths += [dict(seg(grey, 0), pts=[[x, y], [x, y + 11.3]]) for x in (0.0, 400.0)]    # wall end caps
    paths += [seg(grey, 600 + 1.5 * k, 900, 902) for k in range(250)]
    vp = {"paths": paths, "words": [], "W_pt": 1000.0, "H_pt": 1000.0}
    monkeypatch.setattr(M, "SHELL_MIN_WALLS", 1)
    called = {}
    out = M.shell_walls(vp, lambda page, budget_s=None: called.setdefault("n", len(page["paths"])) and [])
    assert not called                                           # the underlay route, not the full-page detector
    assert len(out) == 3 and all(abs(w["thickness_pt"] - 11.3) < 0.5 for w in out)
    mk = lambda t, L, y=0.0: {"polygon": [[0, y], [L, y], [L, y + t], [0, y + t]],
                              "centerline": [[0, y + t / 2], [L, y + t / 2]], "thickness_pt": t}
    f = M.filter_shell([mk(10.0, 200), mk(6.0, 150, 2.0), mk(2.0, 200, 50), mk(10.0, 5, 100), mk(8.0, 200, 300)],
                       0.0254 / 72 * 50)
    assert sorted(w["thickness_pt"] for w in f) == [8.0, 10.0]   # 6 pt inside the 10 pt band, 2 pt thin, 5 pt short
    vp2 = {"paths": [seg(black, 10.0)] * 900, "words": []}
    M.shell_walls(vp2, lambda page, budget_s=None: called.setdefault("n", len(page["paths"])) and [])
    assert called["n"] == 900


def test_terminals_from_tags_follow_leaders():
    """A device tag with a leader gives a terminal at the symbol by the leader's far end (Nx = N symbols), with
    evidence; a tag whose leader ends in empty space is a miss; a tag with no leader (schedule) gives nothing."""
    from pipeline import pdf_mep as M
    mpt = 0.0254 / 72 * 50
    xy, paths = [], []

    def add(pts, closed=False, curves=0):
        i0 = len(xy)
        xy.extend(pts)
        paths.append({"i0": i0, "i1": len(xy), "closed": closed, "stroke": (0, 0, 0), "fill": None, "width": 0.5,
                      "dashed": False, "layer": None, "curves": curves})
    sq = lambda cx, cy, h: [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h), (cx - h, cy - h)]  # noqa: E731
    add([(100, 100), (300, 250)])                    # leader 1: tag at (95,95) -> symbols near (300,250)
    add(sq(305, 255, 5), closed=True)
    add(sq(330, 255, 5), closed=True)
    add([(600, 100), (800, 260)])                    # leader 2: ends in empty space
    import numpy as np
    page = {"xy": np.array(xy, float), "paths": paths, "words": [], "W_pt": 1000.0, "H_pt": 1000.0}
    words = [{"text": "2xAB1-125", "bbox": [60, 88, 98, 96]}, {"text": "-25", "bbox": [60, 98, 75, 106]},
             {"text": "AB2-160", "bbox": [560, 88, 598, 96]}, {"text": "AB3-200", "bbox": [900, 900, 940, 908]}]
    sel = np.ones(len(paths), bool)
    TG, MS = M.terminals_from_tags(page, sel, mpt, words)
    assert len(TG) == 2 and {t["type"] for t in TG} == {"AB1"} and all(t["airflow_ls"] == -25 for t in TG)
    assert all(t["evidence"]["leader_path"] == 0 and t["evidence"]["tag"] == "2xAB1-125" for t in TG)
    assert [m["tag"] for m in MS] == ["AB2-160"]
    assert M.merge_tagged([], TG, mpt) == TG


def test_prime_vtext_reads_artifact_cache(tmp_path, monkeypatch):
    """Stroke-text words come from the artifact's vtext-<page>.json when present (no reading); with the reader off
    and no file, nothing is read or written."""
    import json
    from pipeline import pdf_mep as M
    (tmp_path / "vtext-1.json").write_text(json.dumps({"words": [{"text": "AB1-125", "bbox": [1, 2, 3, 4]},
                                                                  {"text": "bad"}], "partial": False, "s": 9.0}))
    page = {}
    info = M.prime_vtext(page, 0.0176, tmp_path, 0)
    assert info["source"] == "cache" and [w["text"] for w in page["_vtext_words"]] == ["AB1-125"]
    monkeypatch.setenv("PDF_VTEXT", "0")
    page2 = {"paths": [], "xy": __import__("numpy").zeros((0, 2))}
    info2 = M.prime_vtext(page2, 0.0176, tmp_path / "none", 0)
    assert info2["source"] == "none" and page2["_vtext_words"] == [] and not (tmp_path / "none").exists()
