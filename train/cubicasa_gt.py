"""Ground-truth counts from CubiCasa5K model.svg (validated against the question truths in V-09)."""
import re
from collections import Counter

CLS = re.compile(r'class="([^"]+)"')


def svg_counts(svg_text):
    c = Counter()
    for cl in CLS.findall(svg_text):
        t = cl.split()
        if not t:
            continue
        if t[0] == "Window":
            c["window"] += 1
        elif t[0] == "Door" and len(t) > 1 and t[1] != "None":
            c["door"] += 1
        elif t[0] == "FixedFurniture" and len(t) > 1:
            k = {"Toilet": "toilet", "Sink": "sink", "Shower": "shower_bathtub", "Bathtub": "shower_bathtub", "BathTub": "shower_bathtub"}.get(t[1])
            if k:
                c[k] += 1
        elif t[0] == "Space" and len(t) > 1:
            k = {"Bedroom": "bedroom", "Kitchen": "kitchen", "Bath": "bathroom", "Sauna": "sauna"}.get(t[1])
            if k:
                c["room:" + k] += 1
    return c
