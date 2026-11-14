"""F-SCANSYM tests: synthetic legend sheets (drawn here, no data files), no network (MODELS_FAKE=1)."""
import os

os.environ.setdefault("MODELS_FAKE", "1")

import cv2
import numpy as np
import pytest

from engine import symbols as S


def _circle_x(img, cx, cy, r=14):
    cv2.circle(img, (cx, cy), r, 0, 2)
    cv2.line(img, (cx - r, cy - r), (cx + r, cy + r), 0, 2)
    cv2.line(img, (cx - r, cy + r), (cx + r, cy - r), 0, 2)


def _square_dot(img, cx, cy, r=14):
    cv2.rectangle(img, (cx - r, cy - r), (cx + r, cy + r), 0, 2)
    cv2.circle(img, (cx, cy), 4, 0, -1)


def _tri(img, cx, cy, r=15):
    pts = np.array([[cx, cy - r], [cx - r, cy + r], [cx + r, cy + r]], np.int32)
    cv2.polylines(img, [pts], True, 0, 2)
    cv2.line(img, (cx, cy - 4), (cx, cy + 8), 0, 2)


def _diamond(img, cx, cy, r=15):
    pts = np.array([[cx, cy - r], [cx + r, cy], [cx, cy + r], [cx - r, cy]], np.int32)
    cv2.polylines(img, [pts], True, 0, 2)
    cv2.circle(img, (cx, cy), 5, 0, 2)


def _plus_box(img, cx, cy, r=14):
    cv2.rectangle(img, (cx - r, cy - r), (cx + r, cy + r), 0, 2)
    cv2.line(img, (cx - r + 4, cy), (cx + r - 4, cy), 0, 2)
    cv2.line(img, (cx, cy - r + 4), (cx, cy + r - 4), 0, 2)


def _words(items):
    """words with pixel boxes for (text, x, y) items, as OCR would give them"""
    out = []
    for t, x, y in items:
        w = 14 * len(t)
        out.append({"text": t, "bbox_px": [x, y, x + w, y + 22], "conf": 0.99})
    return out


@pytest.fixture()
def sheet(tmp_path):
    """A 1400x900 sheet: legend at the left (3 symbols) and a plan to the right with known counts."""
    img = np.full((900, 1400, 3), 255, np.uint8)[:, :, 0].copy()
    legend = [("LIGHT FITTING", _circle_x), ("SOCKET OUTLET", _square_dot), ("SMOKE DETECTOR", _tri), ("EMERGENCY EXIT SIGN", _diamond), ("DISTRIBUTION BOARD", _plus_box)]
    words = [{"text": "LEGEND", "bbox_px": [60, 40, 190, 62], "conf": 0.99}]
    for i, (lab, fn) in enumerate(legend):
        y = 130 + i * 70
        fn(img, 90, y)
        words += _words([(lab, 140, y - 11)])
    truth = {"LIGHT FITTING": [], "SOCKET OUTLET": [], "SMOKE DETECTOR": []}
    rng = np.random.default_rng(3)
    cv2.rectangle(img, (500, 80), (1350, 850), 0, 3)       # walls
    cv2.line(img, (900, 80), (900, 850), 0, 3)
    spots = [(620, 200), (780, 300), (1000, 220), (1200, 400), (700, 600), (1100, 700)]
    kinds = [_circle_x, _circle_x, _square_dot, _square_dot, _tri, _tri]
    names = ["LIGHT FITTING", "LIGHT FITTING", "SOCKET OUTLET", "SOCKET OUTLET", "SMOKE DETECTOR", "SMOKE DETECTOR"]
    for (x, y), fn, nm in zip(spots, kinds, names):
        fn(img, x, y)
        truth[nm].append((x, y))
    p = tmp_path / "sheet.png"
    cv2.imwrite(str(p), img)
    return p, words, truth


def test_target_synonyms_and_languages():
    assert S.target_score("light fittings", "Light fitting, ceiling") == 1.0
    assert S.target_score("sockets", "Pistorasia / socket outlet") == 1.0
    assert S.target_score("smoke detectors", "Savuilmaisin") >= 0.5
    assert S.target_score("valves", "Ball valve") == 1.0
    assert S.target_score("smoke detectors", "Ball valve") == 0.0


def test_question_noun():
    assert S.question_noun("How many smoke detectors are on this sheet?") == "smoke detectors"
    assert S.question_noun("Count the light fittings") == "light fittings"
    assert S.question_noun("how many doors are there?") is None      # a plain building element, not a legend symbol
    assert S.question_noun("what is the total area") is None


def test_find_legend_without_heading(sheet):
    p, words, _ = sheet
    no_head = [w for w in words if w["text"] != "LEGEND"]
    lg = S.find_legend(p, no_head)
    assert [e["label"] for e in lg["entries"]] == ["LIGHT FITTING", "SOCKET OUTLET", "SMOKE DETECTOR", "EMERGENCY EXIT SIGN", "DISTRIBUTION BOARD"]
    assert all(e["kind"] == "symbol" for e in lg["entries"])
    lg2 = S.find_legend(p, words)
    assert lg2["titled"]


def test_no_legend_says_so(tmp_path):
    img = np.full((400, 400), 255, np.uint8)
    cv2.rectangle(img, (50, 50), (350, 350), 0, 3)
    p = tmp_path / "plain.png"
    cv2.imwrite(str(p), img)
    r = S.count_symbols(p, words=[{"text": "ROOM", "bbox_px": [100, 100, 160, 120], "conf": 0.9}])
    assert r["counts"] == {} and r["boxes"] == []
    assert any("no legend" in n for n in r["notes"])


@pytest.mark.parametrize("target,key", [("light fittings", "LIGHT FITTING"), ("sockets", "SOCKET OUTLET"), ("smoke detectors", "SMOKE DETECTOR")])
def test_count_matches_truth(sheet, target, key):
    p, words, truth = sheet
    r = S.count_symbols(p, words=words, target=target, verify=False)
    assert r["counts"].get(key) == len(truth[key])
    assert len(r["boxes"]) == len(truth[key])
    for b in r["boxes"]:
        cx, cy = (b["bbox_px"][0] + b["bbox_px"][2]) / 2, (b["bbox_px"][1] + b["bbox_px"][3]) / 2
        assert any(abs(cx - x) < 20 and abs(cy - y) < 20 for x, y in truth[key])
    assert [b["n"] for b in r["boxes"]] == list(range(1, len(r["boxes"]) + 1))


def test_rotated_symbol_found(sheet, tmp_path):
    p, words, truth = sheet
    img = cv2.imread(str(p), 0)
    # add a triangle detector turned 90 degrees
    t = np.full((60, 60), 255, np.uint8)
    _tri(t, 30, 30)
    t = np.rot90(t)
    img[300:360, 1220:1280] = np.minimum(img[300:360, 1220:1280], t)
    q = tmp_path / "rot.png"
    cv2.imwrite(str(q), img)
    r = S.count_symbols(q, words=words, target="smoke detector", verify=False)
    assert r["counts"]["SMOKE DETECTOR"] == len(truth["SMOKE DETECTOR"]) + 1


def test_legend_excluded_from_count(sheet):
    p, words, truth = sheet
    r = S.count_symbols(p, words=words, target="light fitting", verify=False)
    assert all(b["bbox_px"][0] > 400 for b in r["boxes"])     # nothing counted inside the legend block itself


def test_unknown_target_reported(sheet):
    p, words, _ = sheet
    r = S.count_symbols(p, words=words, target="fire extinguisher", verify=False)
    assert r["counts"] == {} and any("No legend entry" in n for n in r["notes"])


def _oracle(truth_pts):
    """a model check that answers like a careful reader: yes only where a real symbol sits"""
    def f(ref, label, gray, boxes, budget):
        return [any(abs((b[0] + b[2]) / 2 - x) < 20 and abs((b[1] + b[3]) / 2 - y) < 20 for x, y in truth_pts) for b in boxes]
    return f


def test_model_check_never_adds(sheet, monkeypatch):
    """The model only judges candidates the template pass found; with a faithful check the count is the truth, and every counted box was a template candidate."""
    p, words, truth = sheet
    monkeypatch.setattr(S, "_verify_tiles", _oracle(truth["SMOKE DETECTOR"]))
    r = S.count_symbols(p, words=words, target="smoke detectors")
    assert r["counts"]["SMOKE DETECTOR"] == len(truth["SMOKE DETECTOR"])
    assert r["checked"]["agree"] == r["checked"]["sampled"] > 0


def test_model_check_can_drop(sheet, monkeypatch):
    p, words, truth = sheet
    monkeypatch.setattr(S, "_verify_tiles", lambda ref, label, gray, boxes, budget: [False] * len(boxes))
    r = S.count_symbols(p, words=words, target="sockets")
    assert r["counts"]["SOCKET OUTLET"] == 0                  # both passes must agree


def test_weak_symbol_needs_model(tmp_path):
    img = np.full((500, 900), 255, np.uint8)
    cv2.line(img, (60, 100), (160, 100), 0, 2)               # a plain line is not a countable symbol
    for i, lab in enumerate(["ALPHA PIPE", "BETA PIPE", "GAMMA PIPE", "DELTA PIPE", "EPSILON PIPE"]):
        cv2.line(img, (60, 100 + i * 60), (160, 100 + i * 60), 0, 2)
    words = _words([(lab, 200, 89 + i * 60) for i, lab in enumerate(["ALPHA PIPE", "BETA PIPE", "GAMMA PIPE", "DELTA PIPE", "EPSILON PIPE"])])
    p = tmp_path / "pipes.png"
    cv2.imwrite(str(p), img)
    lg = S.find_legend(p, words)
    assert lg["entries"] and all(e["kind"] == "line" for e in lg["entries"])
    r = S.count_symbols(p, words=words, target="alpha pipe", verify=False)
    assert r["boxes"] == []


def test_symbols_route_and_card(sheet, tmp_path, monkeypatch):
    p, words, truth = sheet
    root = tmp_path / "art"
    d = root / "doc1"
    d.mkdir(parents=True)
    import shutil
    shutil.copy(p, d / "page-1.png")
    (d / "doc.json").write_text('{"kind": "png", "pages": 1}')
    from engine.reader import text as T
    pt = T.PageText("doc1", 1, 1400, 900, words, "given")
    monkeypatch.setattr(T, "load_page_text", lambda *a, **k: pt)
    monkeypatch.setattr(S, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(S, "_verify_tiles", _oracle(truth["SMOKE DETECTOR"]))
    monkeypatch.setattr(S, "page_words", lambda img, words=None: (list(pt.words), "given"))
    res = S.answer_symbols("How many smoke detectors are on this sheet?", ["doc1"], root)
    assert res and res["route"] == "symbols"
    assert res["answer"]["value"] == 2 and "**2" in res["answer"]["text_md"]
    assert len(res["evidence"]["boxes"]) == 2 and res["citations"] and res["citations"][0]["item_ids"]
    assert res["reasoning"]["steps"] and res["reasoning"]["confidence"]["label"] in ("Cross-checked", "Estimate")
    assert S.answer_symbols("how many doors are there?", ["doc1"], root) is None
    leg = S.answer_symbols("What symbols are in the legend?", ["doc1"], root)
    assert leg["answer"]["value"] == 5 and "LIGHT FITTING" in leg["answer"]["text_md"]
    assert leg["evidence"]["boxes"] and leg["citations"]


def test_no_legend_route_offers_detector_kinds(tmp_path, monkeypatch):
    root = tmp_path / "art"
    d = root / "doc2"
    d.mkdir(parents=True)
    img = np.full((300, 300), 255, np.uint8)
    cv2.imwrite(str(d / "page-1.png"), img)
    (d / "doc.json").write_text('{"kind": "png"}')
    from engine.reader import text as T
    monkeypatch.setattr(T, "load_page_text", lambda *a, **k: T.PageText("doc2", 1, 300, 300, [], "none"))
    monkeypatch.setattr(S, "CACHE_DIR", tmp_path / "cache")
    res = S.answer_symbols("what symbols are in the legend", ["doc2"], root)
    assert res["answer"]["abstained"] and "doors, windows" in res["answer"]["text_md"]


def test_area_swatch_is_not_countable():
    img = np.full((60, 140), 0, np.uint8)
    img[:] = 255
    cv2.rectangle(img, (5, 10), (125, 50), 0, 2)
    for x in range(10, 125, 8):
        cv2.line(img, (x, 12), (x + 20, 48), 0, 1)
    ink = S.ink_mask(img)
    assert S.symbol_weakness(ink) == S.SWATCH
    star = np.full((60, 60), 255, np.uint8)
    for a in range(4):
        v = np.array([np.cos(a * np.pi / 4), np.sin(a * np.pi / 4)]) * 20
        cv2.line(star, (int(30 - v[0]), int(30 - v[1])), (int(30 + v[0]), int(30 + v[1])), 0, 2)
    assert S.symbol_weakness(S.ink_mask(star)) != S.SWATCH


def test_find_similar_finds_copies_rotated_and_mirrored(tmp_path):
    import cv2
    import numpy as np
    from engine import symbols as S
    img = np.full((600, 900), 255, np.uint8)
    def sym(a, x, y):
        a = a.copy()
        img[y:y + 40, x:x + 40] = np.minimum(img[y:y + 40, x:x + 40], a)
    base = np.full((40, 40), 255, np.uint8)
    cv2.rectangle(base, (2, 2), (37, 37), 0, 2)
    cv2.line(base, (8, 8), (30, 20), 0, 3)
    cv2.circle(base, (12, 30), 4, 0, -1)
    pts = [(100, 100), (400, 300), (700, 450), (200, 480)]
    sym(base, *pts[0]); sym(np.rot90(base), *pts[1]); sym(base[:, ::-1], *pts[2]); sym(base, *pts[3])
    cv2.circle(img, (500, 100), 25, 0, 3)   # a decoy
    p = tmp_path / "s.png"; cv2.imwrite(str(p), img)
    r = S.find_similar(str(p), (95, 95, 145, 145))
    hits = [m for m in r["matches"] if m["score"] >= 0.8]
    assert len(hits) == 4
    cs = sorted((round((m["bbox"][0] + m["bbox"][2]) / 2 / 50), round((m["bbox"][1] + m["bbox"][3]) / 2 / 50)) for m in hits)
    assert cs == sorted((round((x + 20) / 50), round((y + 20) / 50)) for x, y in pts)
    assert r["template_bbox"][2] - r["template_bbox"][0] >= 30
