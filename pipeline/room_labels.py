"""Room-type words printed on plans (Finnish abbreviations plus English/German/French/Swedish), and compound labels.

Light module (no cv2/numpy): used by the vision label pass and by the plan-map loader.
"""
import math
import re

# Finnish plan abbreviations -> room type (exact token match after upper-casing, punctuation stripped)
LABEL_TYPES = {
    "MH": "bedroom", "MH1": "bedroom", "MH2": "bedroom", "MH3": "bedroom", "MAKUUHUONE": "bedroom",
    "OH": "living", "OLOHUONE": "living", "RT": "dining",
    "K": "kitchen", "KK": "kitchen", "KT": "kitchen", "KEITTIO": "kitchen", "KEITTIÖ": "kitchen", "AK": "kitchen",
    "KH": "bathroom", "PH": "bathroom", "KPH": "bathroom", "SH": "bathroom", "PESUH": "bathroom", "PU": "bathroom", "KYLPYHUONE": "bathroom",
    "WC": "wc", "S": "sauna", "SAUNA": "sauna", "PARVEKE": "balcony", "PARV": "balcony", "LASITETTU": "balcony",
    "ET": "entry", "VH": "entry", "ETEINEN": "entry", "TAMBUURI": "entry", "VAR": "storage", "VARASTO": "storage", "KHH": "storage",
    "TEKN": "technical", "TEKNINEN": "technical", "AUTOTALLI": "garage", "AT": "garage", "TERASSI": "terrace", "TERR": "terrace",
    "TYÖH": "study", "TYOH": "study", "PUKUH": "dressing", "KOMERO": "storage", "ULKOVARASTO": "storage", "ULKO": "outdoor",
    "BEDROOM": "bedroom", "CHAMBRE": "bedroom", "SCHLAFZIMMER": "bedroom", "SOVRUM": "bedroom",
    "KITCHEN": "kitchen", "CUISINE": "kitchen", "KÜCHE": "kitchen", "KUCHE": "kitchen", "KÖK": "kitchen",
    "BATH": "bathroom", "BATHROOM": "bathroom", "BAINS": "bathroom", "BAD": "bathroom", "BADRUM": "bathroom",
    "LIVING": "living", "SALON": "living", "SEJOUR": "living", "SÉJOUR": "living", "WOHNZIMMER": "living", "VARDAGSRUM": "living",
    "HALL": "entry", "ENTREE": "entry", "ENTRÉE": "entry", "FLUR": "corridor", "CORRIDOR": "corridor", "DEGT": "corridor",
    "OFFICE": "office", "BUREAU": "office", "BÜRO": "office", "KONTOR": "office", "GARAGE": "garage",
}

WET_TYPES = {"bathroom", "wc"}
_SEGMENT = re.compile(r"[+/,&]+")
_TOKEN = re.compile(r"[^\W\d_]+", re.U)


def label_type(text):
    """Room type of a printed label. A compound label ("KHH+PH", "WC/KPH") is split on + / , &;
    any wet-room word makes the room wet, otherwise the first known word decides."""
    found = []
    for seg in _SEGMENT.split(str(text or "")):
        for tok in _TOKEN.findall(seg.upper()):
            if tok in LABEL_TYPES:
                found.append(LABEL_TYPES[tok])
                break
    wet = next((t for t in found if t in WET_TYPES), None)
    return wet or (found[0] if found else None)


FIXTURES = ("toilet", "sink", "shower", "bathtub")


def _cx(b):
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def _inside(pt, item):
    poly = getattr(item, "polygon_px", None)
    if poly:
        try:
            import cv2
            import numpy as np
            return cv2.pointPolygonTest(np.array(poly, np.int32), (float(pt[0]), float(pt[1])), False) >= 0
        except Exception:  # noqa: BLE001
            pass
    b = item.bbox_px
    return bool(b) and b[0] <= pt[0] <= b[2] and b[1] <= pt[1] <= b[3]


def wet_label_rooms(items):
    """A wet-room label ("KHH+PH") with no room outline around it still marks a bathroom when a toilet, sink,
    shower or bathtub sits right next to the label. Returns synthetic room items citing the label and its fixtures.
    Never fires for a label that already sits inside a room outline, or inside a room already typed wet."""
    from engine.solvers.data import Item
    rooms = [i for i in items if i.kind == "room" and i.bbox_px]
    fixtures = [i for i in items if i.kind in FIXTURES and i.bbox_px]
    out, used = [], set()
    for t in items:
        if t.kind != "text" or not t.label or not t.bbox_px or label_type(t.label) not in WET_TYPES:
            continue
        c = _cx(t.bbox_px)
        if any(_inside(c, r) for r in rooms):
            continue
        w, h = t.bbox_px[2] - t.bbox_px[0], t.bbox_px[3] - t.bbox_px[1]
        reach = 1.5 * max(math.hypot(w, h), 60)
        near = []
        for f in fixtures:
            if f.item_id in used or f.page != t.page:
                continue
            fx, fy = _cx(f.bbox_px)
            dx = max(t.bbox_px[0] - fx, 0, fx - t.bbox_px[2])
            dy = max(t.bbox_px[1] - fy, 0, fy - t.bbox_px[3])
            if math.hypot(dx, dy) <= reach:
                near.append(f)
        if not near:
            continue
        used.update(f.item_id for f in near)
        boxes = [t.bbox_px] + [f.bbox_px for f in near]
        bb = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
        out.append(Item(item_id=f"room-wet-{t.item_id}", kind="room", label=t.label, page=t.page, bbox_px=bb,
                        conf=min(0.8, t.conf or 0.8), source="label+fixtures",
                        props={"room_type": "bathroom", "label_room_type": label_type(t.label), "no_outline": True,
                               "evidence_items": [t.item_id] + [f.item_id for f in near],
                               "note": f"Printed label '{t.label}' with {', '.join(sorted({f.kind for f in near}))} next to it; no room outline was found."}))
    return out
