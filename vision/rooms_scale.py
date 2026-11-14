"""V-03: rooms (official room head + OCR labels) and scale (stated area text, else door-width prior)."""
import re

import cv2
import numpy as np

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
}
AREA_RE = re.compile(r"(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:m\s*[²2'\"\^]?|㎡)\s*$", re.I)
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
            tok = re.sub(r"[^A-ZÅÄÖ0-9]", "", t["text"].upper())
            if tok in LABEL_TYPES:
                types.append((tok, LABEL_TYPES[tok]))
        if types:
            r["label"] = " ".join(t for t, _ in types)
            r["props"]["label_room_type"] = types[0][1]
            r["props"]["room_type"] = types[0][1]
    return rooms_items


def estimate_scale(room_list, texts, door_items):
    """Return scale dict (CONTRACT 5.4). Order: stated area text (checked against the door prior), else door prior, else none."""
    door_px = [max(i["bbox_px"][2] - i["bbox_px"][0], i["bbox_px"][3] - i["bbox_px"][1]) for i in door_items]
    prior = None
    if len(door_px) >= 2:
        prior = DOOR_WIDTH_M / float(np.median(door_px))  # door icon bbox (leaf + swing) ~ door width
    indoor = [r for r in room_list if r["props"]["room_type"] not in ("outdoor", "garage", "balcony", "terrace")]
    total_px = sum(r["props"]["area_px"] for r in indoor)
    cands = []
    for t in texts:
        m = AREA_RE.search(t["text"].replace(" ", ""))
        if not m:
            continue
        a = float(m.group(1).replace(",", "."))
        if not 3 <= a <= 400:
            continue
        cx, cy = _centre(t["bbox"])
        own = [r for r in indoor if r["polygon_px"] and cv2.pointPolygonTest(np.array(r["polygon_px"], np.int32), (float(cx), float(cy)), False) >= 0]
        if own:
            cands.append((a, own[0]["props"]["area_px"], "room"))
        if total_px:
            cands.append((a, total_px, "total"))
    if cands and prior:
        good = [(np.sqrt(a / px), kind) for a, px, kind in cands if px and 0.55 < np.sqrt(a / px) / prior < 1.8]
        if good:
            s = min((g for g, _ in good), key=lambda g: abs(np.log(g / prior)))  # interpretation closest to the door prior
            ratio = s / prior
            conf = 0.75 if 0.8 < ratio < 1.25 else 0.55
            return {"m_per_px": s, "method": "dimension", "confidence": conf, "evidence": f"{len(good)} stated area text(s)"}
    if cands and not prior:
        a, px, _ = cands[0]
        return {"m_per_px": float(np.sqrt(a / px)), "method": "dimension", "confidence": 0.4, "evidence": "area text, no door check"}
    if prior:
        return {"m_per_px": prior, "method": "door-prior", "confidence": 0.3, "evidence": f"median door icon {np.median(door_px):.0f}px = {DOOR_WIDTH_M} m"}
    return {"m_per_px": None, "method": "none", "confidence": 0.0}


def apply_scale(room_list, scale):
    s = scale.get("m_per_px")
    for r in room_list:
        r["props"]["area_m2"] = round(r["props"]["area_px"] * s * s, 2) if s else None
