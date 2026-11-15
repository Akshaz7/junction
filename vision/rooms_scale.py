"""V-03: rooms (official room head + OCR labels) and scale (stated area text, else door-width prior)."""
import re

import cv2
import numpy as np

try:
    from .planmap import _components, _poly_off
except ImportError:  # direct script execution
    from planmap import _components, _poly_off

ROOM_CLASSES = {1: "outdoor", 3: "kitchen", 4: "living", 5: "bedroom", 6: "bathroom", 7: "entry", 8: "storage", 9: "garage", 10: "undefined"}
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
AREA_RE = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(m\s*(?:²|2|\^2)|㎡|sq\.?\s*m|ft\s*(?:²|2)|sq\.?\s*ft)\s*$", re.I)
DOOR_WIDTH_M = 0.9


def run_ocr(engine, img_np):
    r, _ = engine(img_np)
    items = []
    for box, text, conf in r or []:
        pts = np.array(box, dtype=float)
        x0, y0 = pts.min(0)
        x1, y1 = pts.max(0)
        if float(conf) >= 0.5 and text.strip():
            items.append({"text": text.strip(), "bbox": [int(x0), int(y0), int(x1), int(y1)], "conf": float(conf)})
    return items


def room_items(rooms, room_conf, W, H, size):
    items = []
    min_area = max(30, 0.0012 * W * H)
    for k, rtype in ROOM_CLASSES.items():
        m = cv2.morphologyEx((rooms == k).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        comps, lab = _components(m, min_area)
        for j, st in comps:
            x, y, w, h = map(int, st[:4])
            sub = lab[y:y + h, x:x + w] == j
            items.append(dict(kind="room", label=None, bbox_px=[x, y, x + w, y + h], polygon_px=_poly_off(sub, x, y),
                              props={"room_type": rtype, "model_room_type": rtype, "area_px": int(st[4]), "area_m2": None},
                              conf=round(float(room_conf[y:y + h, x:x + w][sub].mean()), 3), source="det"))
    return items, lab


def _centre(b):
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def label_rooms(rooms_items, texts):
    """Assign each OCR text to the room polygon containing its centre; derive label and label-based type."""
    for r in rooms_items:
        r["_texts"] = []
    for t in texts:
        cx, cy = _centre(t["bbox"])
        best = None
        for r in rooms_items:
            poly = r["polygon_px"]
            if poly and cv2.pointPolygonTest(np.array(poly, np.int32), (float(cx), float(cy)), False) >= 0:
                if best is None or r["props"]["area_px"] < best["props"]["area_px"]:
                    best = r
        if best is not None:
            best["_texts"].append(t)
    for r in rooms_items:
        types = []
        for t in sorted(r.pop("_texts"), key=lambda t: t["bbox"][1]):
            # A printed room number belongs to the label, not to the type token.
            tokens = re.findall(r"[^\W\d_]+", t["text"].upper(), re.U)
            for tok in tokens:
                if tok in LABEL_TYPES:
                    types.append((t["text"], LABEL_TYPES[tok]))
                    break
        if types:
            r["label"] = " ".join(t for t, _ in types)
            r["props"]["label_room_type"] = types[0][1]
            r["props"]["room_type"] = types[0][1]
    return rooms_items


def estimate_scale(room_list, texts, door_items, image_size=None, dpi=None):
    """Printed room areas first; the door guess cannot choose their interpretation.

    Only an explicit square-area unit is accepted. Total-floor text is never
    assigned to a single room. Multiple inconsistent readings are flagged.
    """
    door_px = [max(i["bbox_px"][2] - i["bbox_px"][0], i["bbox_px"][3] - i["bbox_px"][1]) for i in door_items]
    prior = None
    if len(door_px) >= 2:
        prior = DOOR_WIDTH_M / float(np.median(door_px))  # door icon bbox (leaf + swing) ~ door width
    printed = None
    if image_size:
        from engine.scale_text import detect
        words = [{"text": t["text"], "bbox_px": t["bbox"]} for t in texts]
        # A guessed door width must not veto an explicit printed scale.
        printed = detect(words, *image_size, dpi=dpi)
        if printed and printed["method"] not in ("dimension", "scalebar"):
            printed = {**printed, "basis": printed["method"], "method": "dimension"}
    indoor = [r for r in room_list if r["props"]["room_type"] not in ("outdoor", "garage", "balcony", "terrace")]
    cands, room_areas = [], {}
    for t in texts:
        m = AREA_RE.search(t["text"].replace(" ", ""))
        if not m:
            continue
        a = float(m.group(1).replace(",", "."))
        if "ft" in m.group(2).lower():
            a *= 0.09290304
        if not np.isfinite(a) or a <= 0:
            continue
        if re.search(r"\b(?:total|shab|surface habitable|wohnfl.che|gross|net floor)\b", t["text"], re.I):
            continue
        cx, cy = _centre(t["bbox"])
        own = [r for r in indoor if r["polygon_px"] and cv2.pointPolygonTest(np.array(r["polygon_px"], np.int32), (float(cx), float(cy)), False) >= 0]
        if own:
            room = min(own, key=lambda r: r["props"]["area_px"])
            room_areas.setdefault(id(room), (room, [], []))[1].append(a)
            room_areas[id(room)][2].append(t)
    for room, areas, atexts in room_areas.values():
        # Repeated OCR of one label is harmless; conflicting labels are not.
        if max(areas) / min(areas) > 1.05:
            continue
        a = float(np.median(areas))
        room["props"]["area_m2_label"] = round(a, 2)
        px = room["props"].get("area_px")
        if px and px > 0:
            cands.append((float(np.sqrt(a / px)), a, px, room, atexts[0]))
    if printed:
        return printed
    if cands:
        s = float(np.median([c[0] for c in cands]))
        good = [c for c in cands if abs(c[0] / s - 1) <= .15]
        if len(good) > len(cands) / 2:
            v, a, px, room, text = min(good, key=lambda c: abs(c[0] - s))
            return {"m_per_px": float(np.median([c[0] for c in good])), "method": "dimension", "confidence": .8 if len(good) >= 2 else .55,
                    "evidence": f"{len(good)} printed room area label(s) matched to their enclosed outlines",
                    "derivation": _area_derivation(a, px, "room", text, [room]),
                    "selection_rule": "Use the median scale over printed room areas that agree within 15%; each label is associated to the smallest room outline containing it, an inferred association rather than an independent check."}
    if prior:
        return {"m_per_px": prior, "method": "door-prior", "confidence": 0.3, "evidence": f"median door icon {np.median(door_px):.0f}px = {DOOR_WIDTH_M} m"}
    return {"m_per_px": None, "method": "none", "confidence": 0.0}


def _area_derivation(area, pixels, kind, text, rooms):
    return {"formula": "scale = sqrt(printed area in square metres / segmented area in pixels squared)",
            "inputs": [{"name": "printed area", "value": area, "unit": "m2", "source": {"bbox": text["bbox"], "text": text["text"], "reader": "OCR"}},
                       {"name": "segmented area", "value": pixels, "unit": "px2", "source": {
                           "regions": [{"bbox": r["bbox_px"], "polygon_px": r.get("polygon_px"), "area_px": r["props"]["area_px"]} for r in rooms],
                           "reader": "room segmentation", "association": kind}}],
            "note": "The label-to-room/total association was inferred; it is not a measured dimension line or an independent check."}


def apply_scale(room_list, scale):
    s = scale.get("m_per_px")
    for r in room_list:
        label_area = r["props"].get("area_m2_label")
        r["props"]["area_m2"] = label_area if label_area is not None else round(r["props"]["area_px"] * s * s, 2) if s else None
