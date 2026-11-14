"""Hand-written labelling frames for `kind` and `scope` (type comes from the dataset).

Independent of engine/router/parser.py on purpose: each frame is anchored on a
whole question shape seen in router_test.jsonl / the preview, and states the
labelled kind and scope for that shape. Output: labels/router_labels.jsonl
(question -> kind, scope). Run:  python engine/router/labels/label_questions.py
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).with_name("router_labels.jsonl")
SOURCES = [ROOT / "data/sets/router_test.jsonl", ROOT / "data/junction-dataset-preview/questions.jsonl"]

# (frame regex on the raw question, kind, scope); first frame that matches wins.
F = [
    # -- sheet / schedule questions
    (r"area of room \d+ \(.*in the finish", "room", "room"),
    (r"door schedule list for room", "door", "room"),
    (r"doors? in the door schedule|doors \(.*\) are listed in the door schedule|door (type|material|number)|(width|height).{0,20}door|hardware group", "door", "whole-doc"),
    (r"\brooms? (are listed|have|in the finish room schedule)|finish room schedule|rooms with floor finish|floor finish of room|floor finishes|ceiling finish|wall finish", "room", "whole-doc"),
    (r"area of room \d+ \(.*in the finish", "room", "room"),
    (r"locker rooms|rooms named|rooms that have an area|combined area", "room", "whole-doc"),
    # -- swiss dwellings / cubicasa / opening design
    (r"net floor area of apartment", "apartment", None),
    (r"net floor area of room \d|net floor area of the room '", "room", "room"),
    (r"total net floor area of all rooms .*on '", "room", "storey"),
    (r"total net (floor )?area .*all (numbered indoor )?rooms|all rooms labelled", "room", "storey"),
    (r"how many rooms labelled", "room", "storey"),
    (r"how many (apartments)", "apartment", "whole-doc"),
    (r"how many (balconies|bedrooms|bathrooms|kitchens|rooms|separate wc rooms|saunas)", "room", "whole-doc"),
    (r"how many floors", "storey", "whole-doc"),
    (r"how many (showers and bathtubs|showers)", "shower", "whole-doc"),
    (r"how many bathtubs", "bathtub", "whole-doc"),
    (r"how many (sinks|washbasins)", "sink", "whole-doc"),
    (r"how many (toilets|toilet bowls)", "toilet", "whole-doc"),
    (r"how many doors", "door", "whole-doc"),
    (r"how many windows", "window", "whole-doc"),
    (r"how many columns", "column", "whole-doc"),
    (r"how many stairs", "stairs", "whole-doc"),
    (r"how many walls", "wall", "whole-doc"),
]
# -- IFC descriptive questions: kind from the subject noun; scope only where the question states one (else None)
G = [
    (r"toilets are there on the ground floor", "toilet", "storey"),
    (r"MEP components", "mep", None),
    (r"MEP systems", "mep", None),
    (r"spaces (in|on) the (underground|ground) level|spaces on level", "room", "storey"),
    (r"spaces? (utilization|breakdown)|space breakdown|all the spaces|furniture can be found in the staff room|sanitary furniture are in room", None, None),
    (r"floor-to-floor|elevation", "storey", None),
    (r"slab", "slab", None),
    (r"window", "window", None),
    (r"door", "door", None),
    (r"beam", "beam", None),
    (r"column", "column", None),
    (r"stair", "stairs", None),
    (r"railing", "railing", None),
    (r"ceiling", "ceiling", None),
    (r"covering", "covering", None),
    (r"pip(e|ing)", "pipe", None),
    (r"wall", "wall", None),
    (r"furniture", "furniture", None),
    (r"(cooling|heating|electrical|sanitary)", "mep", None),
    (r"largest room", "room", None),
    (r"structural elements", None, None),
    (r"software|project information", None, None),
]


def label(q: str):
    for rx, k, s in F + G:
        if re.search(rx, q, re.I):
            return k, s
    return None, None


def main() -> int:
    seen = {}
    for p in SOURCES:
        if not p.exists():
            continue
        for line in p.open():
            r = json.loads(line)
            seen.setdefault(r["question"], r.get("type"))
    n_lab = 0
    with OUT.open("w") as f:
        for q, t in seen.items():
            k, s = label(q)
            n_lab += k is not None
            f.write(json.dumps({"question": q, "type": t, "kind": k, "scope": s}, ensure_ascii=False) + "\n")
    print(f"{len(seen)} unique questions, {n_lab} with a kind label -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
