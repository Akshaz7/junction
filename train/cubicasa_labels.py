"""CubiCasa5K model.svg -> labelled items in F1_original.png pixel coordinates.
kinds: wall, door, window, room (props room_type), toilet, sink, shower, bathtub."""
import re
import xml.etree.ElementTree as ET

NS = "{http://www.w3.org/2000/svg}"
ROOM = {"Bedroom": "bedroom", "Kitchen": "kitchen", "Bath": "bathroom", "Sauna": "sauna", "LivingRoom": "living", "Living": "living",
        "Entrance": "entry", "Hall": "entry", "Storage": "storage", "Garage": "garage", "Balcony": "balcony", "Outdoor": "outdoor",
        "DiningRoom": "dining", "Closet": "storage", "Fireplace": "other", "Undefined": "undefined", "Toilet": "wc", "WC": "wc",
        "Draughtlobby": "entry", "Library": "other"}
FURN = {"Toilet": "toilet", "Sink": "sink", "Shower": "shower", "Bathtub": "bathtub", "BathTub": "bathtub"}


def _mat(s):
    m = re.match(r"matrix\(([^)]*)\)", (s or "").strip())
    if not m:
        return (1, 0, 0, 1, 0, 0)
    v = [float(x) for x in re.split(r"[ ,]+", m.group(1).strip())]
    return tuple(v)


def _mul(p, q):  # p applied after q
    a, b, c, d, e, f = p
    A, B, C, D, E, F = q
    return (a * A + c * B, b * A + d * B, a * C + c * D, b * C + d * D, a * E + c * F + e, b * E + d * F + f)


def _pts(s):
    n = [float(x) for x in re.split(r"[ ,]+", s.strip()) if x]
    return list(zip(n[0::2], n[1::2]))


def _apply(m, pts):
    a, b, c, d, e, f = m
    return [(a * x + c * y + e, b * x + d * y + f) for x, y in pts]


def parse(svg_text, target_w, target_h):
    root = ET.fromstring(svg_text)
    vb = [float(x) for x in re.split(r"[ ,]+", root.get("viewBox").strip())]
    sx, sy = target_w / vb[2], target_h / vb[3]
    items = []

    def polys(el, m):
        out = []
        for p in el.iter(NS + "polygon"):
            out.append(_apply(m, _pts(p.get("points", ""))))
        return out

    def walk(el, m):
        m = _mul(m, _mat(el.get("transform")))
        t = (el.get("class") or "").split()
        kind = None
        if t:
            if t[0] == "Wall":
                kind = "wall"
            elif t[0] == "Window":
                kind = "window"
            elif t[0] == "Door" and len(t) > 1 and t[1] != "None":
                kind = "door"
            elif t[0] == "Space":
                kind = "room"
            elif t[0] == "FixedFurniture" and len(t) > 1 and t[1] in FURN:
                kind = FURN[t[1]]
        if kind:
            if kind in ("toilet", "sink", "shower", "bathtub"):
                bp = [g for g in el.iter(NS + "g") if "BoundaryPolygon" in (g.get("class") or "")]
                ps = polys(bp[0], m) if bp else []
            elif kind in ("wall", "room"):
                first = next(el.iter(NS + "polygon"), None)  # first polygon = outline; later ones are decorations
                ps = [_apply(m, _pts(first.get("points", "")))] if first is not None else []
            else:
                ps = polys(el, m)
            ps = [p for p in ps if len(p) >= 3]
            if ps:
                allp = [(x * sx, y * sy) for p in ps for x, y in p]
                xs, ys = [p[0] for p in allp], [p[1] for p in allp]
                it = {"kind": kind, "bbox_px": [min(xs), min(ys), max(xs), max(ys)],
                      "polygon_px": [[round(x * sx, 1), round(y * sy, 1)] for x, y in ps[0]] if kind in ("wall", "room") else None}
                if kind == "room":
                    it["room_type"] = ROOM.get(t[1] if len(t) > 1 else "Undefined", "other")
                items.append(it)
            if kind in ("wall", "room"):
                pass
            else:
                return  # do not descend into the symbol
        for ch in el:
            walk(ch, m)

    walk(root, (1, 0, 0, 1, 0, 0))
    return items
