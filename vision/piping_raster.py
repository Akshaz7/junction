"""V-09: read a raster/PDF plumbing sheet with a vision model (Gemini 4 Carbon) through engine.models.call().
  .venv/bin/python vision/piping_raster.py            # renders P1.02 (Vacation_Rental) + P0.00 legend, one call, scores vs the human reading, writes results/vision/piping/v09/
Output is a model answer (label it 'read by a model'): pipe-size labels, fixtures, drains with boxes [y0,x0,y1,x1] on a 0-1000 grid of the plan crop.
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "results/vision/piping/v09"
D = ROOT / "data/full/junction-dataset/data/opening_design/Vacation_Rental/Transfer/20170519 ----- ISSUE FOR BID & PERMIT -------"
PLAN = D / "The_Downtowner_PLMB_ZS - Sheet - P1-02 - SECOND FLOOR AND ROOF PLUMING PLANS.pdf"
LEG = D / "The_Downtowner_PLMB_ZS - Sheet - P0-00 - PLUMBING SYMBOLS & ABBREVIATIONS.pdf"
SCHEMA = {"type": "object", "properties": {
    "pipe_labels": {"type": "array", "items": {"type": "object", "properties": {"size": {"type": "string"}, "text": {"type": "string"}, "system": {"type": "string"}, "box": {"type": "array", "items": {"type": "integer"}}}}},
    "fixtures": {"type": "array", "items": {"type": "object", "properties": {"tag": {"type": "string"}, "type": {"type": "string"}, "box": {"type": "array", "items": {"type": "integer"}}}}},
    "drains": {"type": "array", "items": {"type": "object", "properties": {"kind": {"type": "string"}, "box": {"type": "array", "items": {"type": "integer"}}}}}}}
PROMPT = """Image 1 is the piping legend of a plumbing drawing set (line types and abbreviations). Image 2 is a plan crop from sheet P1.02 of the same set.
Read Image 2 only. List, each with a bounding box [ymin,xmin,ymax,xmax] on a 0-1000 grid of Image 2:
- pipe_labels: every pipe size annotation printed on a pipe run (e.g. 2"o, 3"o, 1 1/2"o) and every vent callout (e.g. 3"VENT UP, 3"V DN); text = exactly what is printed, size = the diameter in inches as printed, system = waste, vent or water (use the legend; dashed cyan lines on this sheet are sanitary waste and vent).
- fixtures: every plumbing fixture TAG box (LAV-1, WC-1, SH-1, KS-1 ...), type = lavatory, water closet, shower, kitchen sink.
- drains: every floor drain or shower drain symbol (small circle where a waste line ends in a shower), kind = shower drain or floor drain.
Do not invent items that are not drawn. Return JSON only."""


def render():
    import pypdfium2 as p
    OUT.mkdir(parents=True, exist_ok=True)
    im = p.PdfDocument(str(PLAN))[0].render(scale=3).to_pil(); s = im.size[0] / 2000
    im.crop((int(200 * s), int(350 * s), int(760 * s), int(820 * s))).save(OUT / "p102_crop.png")
    lg = p.PdfDocument(str(LEG))[0].render(scale=3).to_pil(); s = lg.size[0] / 2000
    lg.crop((int(435 * s), int(40 * s), int(770 * s), int(430 * s))).save(OUT / "p000_legend.png")


def run(model=("runware_oai", "gemini-4-carbon")):
    from engine.models import call
    render()
    r = call("read_drawing", [{"role": "user", "content": PROMPT}], images=[OUT / "p000_legend.png", OUT / "p102_crop.png"], schema=SCHEMA, only=model)
    res = {"model": r.model, "cost_usd": r.cost_usd, "json": r.json, "text": None if r.json else r.text}
    (OUT / "gemini_p102.json").write_text(json.dumps(res, indent=1))
    return res


# Human reading of the P1.02 2nd-floor crop (done by eye on a 3x render, 2026-11-14).
HUMAN = {"pipe_size_labels": {'2"': 5, '3"': 3, '1 1/2"': 3}, "vent_callouts": 5,
         "fixture_tags": {"LAV-1": 2, "WC-1": 3, "SH-1": 3, "KS-1": 1}, "shower_drains": 3}


def score(res):
    from collections import Counter
    import re
    j = res["json"] or {}
    sz = Counter(); vents = 0
    for l in j.get("pipe_labels", []):
        t = (l.get("text") or "") + " " + (l.get("size") or "")
        if re.search(r"vent|V UP|V DN|\bV\b", t, re.I):
            vents += 1; continue
        m = re.search(r'(1\s*1/2|2|3)', l.get("size") or l.get("text") or "")
        if m: sz[m.group(1).replace(" ", "") .replace("11/2", "1 1/2") + '"'] += 1
    tags = Counter((f.get("tag") or "").upper().strip() for f in j.get("fixtures", []))
    return {"pipe_size_labels": dict(sz), "vent_callouts": vents, "fixture_tags": {k: tags.get(k, 0) for k in HUMAN["fixture_tags"]}, "extra_tags": {k: v for k, v in tags.items() if k not in HUMAN["fixture_tags"]},
            "drains": len(j.get("drains", [])), "human": HUMAN}


if __name__ == "__main__":
    res = run(); print(json.dumps(score(res), indent=1)); print("cost", res["cost_usd"], res["model"])
