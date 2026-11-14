"""F-MISTAKES: "Mistakes found". Real, checkable errors in the customer's own drawings and models, found by plain code.

  find(doc_ids, root)       -> [mistake]   per document, plus checks across documents when 2+ are given; worst first, at most 20 per document
  find_doc(doc_id, root)    -> [mistake]   one document
  compare(values, kind)     -> {"status": "matches"|"differs", ...}   shared by the projects overview
  summary(doc_ids, root)    -> {"checks": [...], "counts": {...}}      what was looked at (used for the "nothing found" answer)
  answer(question, doc_ids, root, t0, trace) -> answer object | None   chat route: "are there any mistakes in this model?"

mistake = {id, severity: high|medium|low, title, text, doc_ids, item_ids, evidence: {kind, values}, check, basis}.

Rules (precision first, a false mistake in front of a customer is worse than none):
  * every check is general: thresholds come from physics and units (a stored area can never exceed the room's own footprint),
    never from a file, a room name or a count; language of the labels never matters;
  * a check runs only when its data exists; with no data it is skipped and says nothing;
  * a rule that depends on "what siblings do" needs a clear majority (90 % of at least 10), otherwise it is a convention, not an error;
  * bounding boxes only prove an overlap; clash text says "check", never "wrong".
Keep this import path light: json + stdlib. ifcopenshell is imported lazily and only for the optional property check.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import statistics
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

CHECKS_VERSION = 1
CAP_PER_DOC = 20
SEV_RANK = {"high": 0, "medium": 1, "low": 2}

# kinds (engine/solvers/data.Item.kind, written by the extractor from the IFC class) that the checks reason about
SERVICE_KINDS = {"pipe", "duct", "cable_tray", "cable"}
STRUCT_KINDS = {"beam", "column"}
HOST_KINDS = {"wall", "curtain_wall", "slab", "roof", "plate", "member", "covering", "proxy", "railing", "footing"}
OPENING_KINDS = {"door", "window"}
# kinds where two identical elements in the same spot are a real double count (layers, members and plates legitimately overlap)
DUP_KINDS = {"door", "window", "wall", "curtain_wall", "slab", "column", "beam", "stairs", "railing", "furniture", "pipe", "duct", "sanitary", "equipment", "light", "terminal"}
SKIP_KINDS = {"site", "building", "storey", "other", "text", "annotation"}
NOUN = {"door": "door", "window": "window", "wall": "wall", "curtain_wall": "curtain wall", "slab": "floor slab", "roof": "roof", "stairs": "stair",
        "ramp": "ramp", "railing": "railing", "column": "column", "beam": "beam", "member": "member", "plate": "plate", "covering": "covering",
        "footing": "footing", "pile": "pile", "furniture": "furniture item", "pipe": "pipe", "duct": "duct", "cable_tray": "cable tray",
        "cable": "cable", "pipe_fitting": "pipe fitting", "duct_fitting": "duct fitting", "terminal": "terminal", "valve": "valve",
        "valve_damper": "valve or damper", "pump_fan": "pump or fan", "pump": "pump", "fan": "fan", "equipment": "piece of equipment",
        "sanitary": "sanitary fixture", "air_terminal": "air terminal", "light": "light", "tank": "tank", "room": "room", "space": "room",
        "proxy": "building element", "mep_other": "service element", "fastener": "fastener", "accessory": "accessory"}


def _root(root) -> Path:
    if root is not None:
        return Path(root)
    from engine.solvers import ARTIFACTS
    return Path(os.environ.get("ARTIFACTS_DIR") or ARTIFACTS)


# ------------------------------------------------------------------------------------------------ small helpers
def _noun(kind: str, n: int = 1) -> str:
    w = NOUN.get(kind) or (kind or "element").replace("_", " ")
    if n == 1:
        return w
    if w.endswith("y") and w[-2:-1] not in "aeiou":
        return w[:-1] + "ies"
    return w + ("es" if w.endswith(("s", "x", "ch")) else "s")


def _fmt(v, nd=1) -> str:
    s = f"{float(v):,.{nd}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _guidish(s: str) -> bool:
    return bool(re.fullmatch(r"[0-9A-Za-z_$]{22}", s or "")) or bool(re.fullmatch(r"[0-9a-fA-F-]{32,36}", s or ""))


def _name(it) -> str:
    """The user's own label for an element (never a GUID); '' when it has none worth showing."""
    for cand in (getattr(it, "label", None), (it.props or {}).get("long_name") if it.props else None, it.name):
        c = " ".join(str(cand or "").split())
        if c and not _guidish(c) and len(c) <= 40 and not c.lower().startswith("ifc") and not re.search(r":\s*\d{4,}\s*$", c) and c.count(":") < 2:
            return c
    return ""


def _desc(it) -> str:
    nm = _name(it)
    kind = "room" if it.kind in ("room", "space") else it.kind
    return f'{_noun(kind)} "{nm}"' if nm else _noun(kind)


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _mid(bb):
    return [(bb[0][i] + bb[1][i]) / 2 for i in range(3)]


def _dims(bb):
    return [abs(bb[1][i] - bb[0][i]) for i in range(3)]


def _norm_level(s: str | None) -> str:
    return re.sub(r"[\s_\-.]+", " ", (s or "").strip().casefold())


def _mid_id(kind: str, doc_ids, item_ids) -> str:
    h = hashlib.sha1(("|".join([kind, *sorted(doc_ids), *sorted(map(str, item_ids))])).encode()).hexdigest()[:10]
    return f"mk-{kind}-{h}"


def _mk(severity, title, text, doc_ids, item_ids, evidence, check, basis="exact", **extra) -> dict:
    ids = list(dict.fromkeys(str(i) for i in item_ids))
    m = {"id": _mid_id(evidence.get("kind", "x"), doc_ids, ids or [text]), "severity": severity, "title": title, "text": text,
         "doc_ids": list(doc_ids), "item_ids": ids[:60], "evidence": evidence, "check": check, "basis": basis}
    m.update({k: v for k, v in extra.items() if v is not None})
    return m


def compare(values, kind: str = "count", tol_pct: float | None = None) -> dict:
    """Do these per-document values agree? values: [{doc_id, value}] or plain numbers. Counts must be equal; areas and lengths
    agree within `tol_pct` (default 2 %). Missing values (None) are ignored, fewer than two real values -> 'matches' with n=1."""
    rows = [v if isinstance(v, dict) else {"doc_id": None, "value": v} for v in values]
    nums = [float(r["value"]) for r in rows if isinstance(r.get("value"), (int, float)) and not isinstance(r.get("value"), bool)]
    if len(nums) < 2:
        return {"status": "matches", "n": len(nums), "spread": 0.0, "spread_pct": 0.0}
    lo, hi = min(nums), max(nums)
    spread = hi - lo
    pct = spread / max(abs(hi), 1e-9) * 100
    if kind == "count":
        ok = spread == 0
    else:
        ok = pct <= (2.0 if tol_pct is None else tol_pct)
    return {"status": "matches" if ok else "differs", "n": len(nums), "spread": round(spread, 4), "spread_pct": round(pct, 2),
            "min": lo, "max": hi}


# ------------------------------------------------------------------------------------------------ loading
def _load(doc_id: str, root: Path):
    from engine.solvers.data import load_doc
    return load_doc(doc_id, root)


def _origin_offset(doc_id: str, root: Path):
    try:
        o = json.loads((root / doc_id / "scene.json").read_text()).get("origin_offset_m")
        return [float(x) for x in o] if o and len(o) == 3 else None
    except (OSError, ValueError, TypeError):
        return None


# ------------------------------------------------------------------------------------------------ IFC: stored numbers vs own geometry
def _ifc_numbers(doc) -> list[dict]:
    out: list[dict] = []
    area_bad, vol_bad, net_bad = defaultdict(list), defaultdict(list), defaultdict(list)
    for it in doc.items:
        if it.kind in SKIP_KINDS or not it.bbox_m or (it.props or {}).get("bbox_source") == "estimated":
            continue
        q = it.q or {}
        dx, dy, dz = _dims(it.bbox_m)
        if it.kind in ("room", "space"):
            a = q.get("net_floor_area_m2") if q.get("net_floor_area_m2") is not None else q.get("area_m2")
            foot = dx * dz
            if a is not None and float(a) > 0.05 and foot > 0.5 and float(a) > foot * 1.05 + 0.1:
                area_bad[it.kind].append((it, float(a), foot))
        else:
            v = next((float(q[k]) for k in ("net_volume_m3", "volume_m3", "gross_volume_m3") if q.get(k) not in (None, 0)), None)
            bv = dx * dy * dz
            if v is not None and bv > 1e-4 and v > bv * 1.05 + 1e-3:
                vol_bad[it.kind].append((it, v, bv))
        for net, gross, unit, label in (("net_floor_area_m2", "gross_floor_area_m2", "m²", "floor area"),):
            n, g = q.get(net), q.get(gross)
            if n is not None and g is not None and float(g) > 0 and float(n) > float(g) * 1.01 + 1e-3:
                net_bad[(it.kind, label)].append((it, float(n), float(g), unit))
    for kind, rows in area_bad.items():
        rows.sort(key=lambda r: -(r[1] / r[2]))
        it, a, foot = rows[0]
        n = len(rows)
        txt = (f'Room "{_name(it) or "unnamed"}" is stored with a floor area of {_fmt(a)} m², but its own outline fits in only {_fmt(foot)} m².' if n == 1 else
               f"{n} rooms are stored with a floor area larger than the rectangle that contains them, for example "
               f'"{_name(it) or "unnamed"}" at {_fmt(a)} m² in a {_fmt(foot)} m² footprint.')
        out.append(_mk("medium", "Stored room area does not fit the room's outline", txt, [doc.doc_id], [r[0].item_id for r in rows],
                       {"kind": "area_mismatch", "values": {"stored_m2": round(a, 2), "footprint_m2": round(foot, 2), "rooms": n}},
                       "Compare the stored area with the room's size in the drawing; a wrong area changes every floor-area total.",
                       storey=it.storey))
    for kind, rows in vol_bad.items():
        rows.sort(key=lambda r: -(r[1] / max(r[2], 1e-9)))
        it, v, bv = rows[0]
        n = len(rows)
        if n < 1:
            continue
        what = _noun(kind, n)
        txt = (f"The stored volume of {_desc(it)} is {_fmt(v, 2)} m³, but the element's own box holds only {_fmt(bv, 2)} m³." if n == 1 else
               f"{n} {what} are stored with a volume larger than the box that contains them, for example {_fmt(v, 2)} m³ in a {_fmt(bv, 2)} m³ box.")
        out.append(_mk("medium", f"Stored volume does not fit the {_noun(kind)}'s size", txt, [doc.doc_id], [r[0].item_id for r in rows],
                       {"kind": "quantity_mismatch", "values": {"stored_m3": round(v, 3), "box_m3": round(bv, 3), "elements": n}},
                       "Check the quantity data of these elements (unit or export problem); material take-offs depend on it.",
                       storey=it.storey))
    for (kind, label), rows in net_bad.items():
        it, nv, gv, unit = rows[0]
        n = len(rows)
        what = _noun(kind, n)
        txt = f"{_cap(_desc(it)) if n == 1 else str(n) + ' ' + what} {'has' if n == 1 else 'have'} a net {label} ({_fmt(nv, 2)} {unit}) larger than the gross {label} ({_fmt(gv, 2)} {unit})."
        out.append(_mk("medium", f"Net {label} is larger than gross {label}", txt, [doc.doc_id], [r[0].item_id for r in rows],
                       {"kind": "quantity_mismatch", "values": {"net": nv, "gross": gv, "elements": n}},
                       "Net can never exceed gross; check how these quantities were exported.", storey=it.storey))
    return out


# ------------------------------------------------------------------------------------------------ IFC: structure of the model
def _ifc_no_storey(doc) -> list[dict]:
    if not doc.storeys:
        return []
    real = [i for i in doc.items if i.kind not in SKIP_KINDS]
    miss = [i for i in real if not i.storey]
    if not miss or len(miss) == len(real):
        return []
    cnt = Counter(i.kind for i in miss)
    parts = ", ".join(f"{n} {_noun(k, n)}" for k, n in cnt.most_common(3))
    return [_mk("medium", "Elements not assigned to a storey",
                f"{len(miss)} of {len(real)} elements belong to no storey ({parts}), so they drop out of every per-floor count and plan.",
                [doc.doc_id], [i.item_id for i in miss], {"kind": "missing_property", "values": {"missing": len(miss), "total": len(real), "property": "storey"}},
                "Assign them to a storey in the authoring tool, or remove them if they are leftovers.")]


def _box_key(bb, q=0.01):
    return tuple(round(bb[i][j] / q) for i in range(2) for j in range(3))


def _ifc_duplicates(doc) -> list[dict]:
    groups: dict[tuple, list] = defaultdict(list)
    for it in doc.items:
        if it.kind not in DUP_KINDS or not it.bbox_m:
            continue
        if max(_dims(it.bbox_m)) < 0.02:
            continue
        groups[(it.kind, it.type_name or "", _name(it), it.storey or "", _box_key(it.bbox_m))].append(it)
    by_kind: dict[str, list[list]] = defaultdict(list)
    for (kind, *_r), g in groups.items():
        if len(g) > 1:
            by_kind[kind].append(g)
    out = []
    for kind, gs in by_kind.items():
        gs.sort(key=lambda g: -len(g))
        extra = sum(len(g) - 1 for g in gs)
        ids = [i.item_id for g in gs for i in g]
        g0 = gs[0]
        it = g0[0]
        where = f" on {it.storey}" if it.storey else ""
        if len(gs) == 1:
            txt = f"{len(g0)} {_noun(kind, len(g0))}{where} sit exactly on top of each other with the same type and size, so one of them is counted twice."
        else:
            txt = f"{extra} {_noun(kind, extra)} duplicate another one placed in exactly the same spot ({len(gs)} places), so they are counted twice."
        out.append(_mk("high" if kind in OPENING_KINDS | {"wall", "column", "beam", "slab"} else "medium", f"Duplicate {_noun(kind, 2)}", txt, [doc.doc_id], ids,
                       {"kind": "duplicate", "values": {"places": len(gs), "extra_copies": extra, "element": kind}},
                       "Open the spot in 3D; delete the extra copy. Quantity take-offs count every copy.", storey=it.storey))
    return out


def _ifc_unhosted(doc) -> list[dict]:
    hosts = [i for i in doc.items if i.kind in HOST_KINDS and i.bbox_m]
    ops = [i for i in doc.items if i.kind in OPENING_KINDS and i.bbox_m]
    if len(hosts) < 3 or len(ops) < 3:
        return []
    cell = 3.0
    grid: dict[tuple, list] = defaultdict(list)
    for h in hosts:
        (x0, y0, z0), (x1, y1, z1) = h.bbox_m
        for cx in range(int(math.floor(x0 / cell)), int(math.floor(x1 / cell)) + 1):
            for cz in range(int(math.floor(z0 / cell)), int(math.floor(z1 / cell)) + 1):
                grid[(cx, cz)].append(h)
    tol = 0.2
    loose: dict[str, list] = defaultdict(list)
    for o in ops:
        (x0, y0, z0), (x1, y1, z1) = o.bbox_m
        near = False
        seen = set()
        for cx in range(int(math.floor((x0 - tol) / cell)), int(math.floor((x1 + tol) / cell)) + 1):
            for cz in range(int(math.floor((z0 - tol) / cell)), int(math.floor((z1 + tol) / cell)) + 1):
                for h in grid.get((cx, cz), ()):
                    if id(h) in seen:
                        continue
                    seen.add(id(h))
                    (a0, b0, c0), (a1, b1, c1) = h.bbox_m
                    if x0 - tol <= a1 and x1 + tol >= a0 and y0 - tol <= b1 and y1 + tol >= b0 and z0 - tol <= c1 and z1 + tol >= c0:
                        near = True
                        break
                if near:
                    break
            if near:
                break
        if not near:
            loose[o.kind].append(o)
    out = []
    for kind, rows in loose.items():
        total = sum(1 for o in ops if o.kind == kind)
        if len(rows) > max(3, 0.25 * total):
            continue   # most of them float: the model keeps hosts elsewhere (or no host geometry), not a placement error
        n = len(rows)
        it = rows[0]
        where = f' on {it.storey}' if it.storey else ""
        txt = (f"{_cap(_desc(it))}{where} is not inside any wall, floor or roof of the model; it floats in space." if n == 1 else
               f"{n} {_noun(kind, n)} are not inside any wall, floor or roof of the model (they float in space), for example {_desc(it)}{where}.")
        out.append(_mk("medium", f"{_cap(_noun(kind, n))} not placed in a wall", txt, [doc.doc_id], [r.item_id for r in rows],
                       {"kind": "not_hosted", "values": {"elements": n, "of": total}},
                       "Open them in 3D; move each one into its wall or delete it. Floating openings are counted but cut no hole.",
                       storey=it.storey))
    return out


def _ifc_spaces(doc) -> list[dict]:
    rooms = [i for i in doc.items if i.kind in ("room", "space")]
    if len(rooms) < 4:
        return []
    def area(i):
        q = i.q or {}
        for k in ("net_floor_area_m2", "area_m2", "gross_floor_area_m2"):
            if q.get(k) is not None:
                return float(q[k])
        return None
    have = [r for r in rooms if area(r) is not None]
    out = []
    if len(have) >= 0.8 * len(rooms):
        zero = [r for r in have if area(r) <= 0.05]
        miss = [r for r in rooms if area(r) is None]
        for rows, why in ((zero, "an area of zero"), (miss, "no area at all")):
            if rows and len(rows) <= 0.2 * len(rooms):
                it = rows[0]
                n = len(rows)
                txt = (f'Room "{_name(it) or "unnamed"}"{" on " + it.storey if it.storey else ""} has {why}, while the other rooms all have one.' if n == 1 else
                       f"{n} rooms have {why}, while the other rooms all have one, for example \"{_name(it) or 'unnamed'}\".")
                out.append(_mk("low", "Rooms without a usable area", txt, [doc.doc_id], [r.item_id for r in rows],
                               {"kind": "missing_property", "values": {"rooms": n, "of": len(rooms), "property": "area"}},
                               "Check the room outline in the model; area totals leave these rooms out.", storey=it.storey))
    return out


def _sibling_gaps(doc, pset_values: dict | None = None) -> list[dict]:
    """A property that 90 % of at least 10 identical elements carry but a few lack. Uses elements.json (material, flags, quantities);
    `pset_values` adds property-set properties read from the IFC file when ifcopenshell is available: {item_id: {name: value}}."""
    groups: dict[tuple, list] = defaultdict(list)
    for it in doc.items:
        if it.kind in SKIP_KINDS or it.kind in ("pipe_fitting", "duct_fitting"):
            continue
        groups[(it.kind, it.type_name or "")].append(it)
    out = []
    cands = []
    for (kind, tname), g in groups.items():
        n = len(g)
        if n < 10:
            continue
        have: dict[str, set] = defaultdict(set)
        for it in g:
            props = {k: v for k, v in (it.props or {}).items() if k not in ("ifc_class", "predefined_type", "is_external_source", "bbox_source") and v not in (None, "")}
            quant = {k: v for k, v in (it.q or {}).items() if v is not None}
            ps = (pset_values or {}).get(it.item_id) or {}
            for k in (*props, *quant, *ps):
                have[k].add(it.item_id)
        for k, ids in have.items():
            miss = n - len(ids)
            if miss >= 1 and len(ids) >= 0.9 * n and miss <= 0.1 * n + 1e-9:
                missing = [it for it in g if it.item_id not in ids]
                cands.append((miss / n, kind, tname, k, n, missing))
    cands.sort(key=lambda c: (c[0], -c[4]))
    seen = set()
    for _frac, kind, tname, k, n, missing in cands:
        key = (kind, k)
        if key in seen:
            continue
        seen.add(key)
        label = k.removeprefix("is_").replace("_m2", "").replace("_m3", "").replace("_m", "").replace("_", " ").strip()
        n_have = n - len(missing)
        where = f" of type \"{tname}\"" if tname and not _guidish(tname) and len(tname) <= 50 else ""
        txt = (f"{n_have} of {n} {_noun(kind, n)}{where} have {label} filled in; {'this one does not' if len(missing) == 1 else f'{len(missing)} do not'}, "
               f"for example {_desc(missing[0])}{' on ' + missing[0].storey if missing[0].storey else ''}.")
        out.append(_mk("low", f"Missing {label} on a few {_noun(kind, 2)}", txt, [doc.doc_id], [m.item_id for m in missing],
                       {"kind": "missing_property", "values": {"property": k, "have": n_have, "of": n, "element": kind}},
                       f"Add the {label} to the {len(missing)} element{'s' if len(missing) != 1 else ''} that lack it; schedules and take-offs skip them.",
                       storey=missing[0].storey))
        if len(out) >= 6:
            break
    return out


# optional: property sets straight from the IFC file (only when ifcopenshell and the source file are present)
PSET_CLASSES = ("IfcDoor", "IfcWindow", "IfcWall", "IfcSlab", "IfcColumn", "IfcBeam", "IfcStair", "IfcSpace", "IfcCovering", "IfcRailing")
IFC_MAX_BYTES = 60 * 1024 * 1024


def _ifc_source(doc_id: str, root: Path) -> Path | None:
    try:
        meta = json.loads((root / doc_id / "doc.json").read_text())
    except (OSError, ValueError):
        return None
    rel = (meta.get("files") or {}).get("ifc")
    if not rel:
        return None
    for base in (root.parent, root.parent.parent, Path.cwd()):
        p = base / rel
        if p.is_file():
            return p
    return None


def _ifc_psets(doc_id: str, root: Path) -> dict | None:
    p = _ifc_source(doc_id, root)
    if p is None or p.stat().st_size > IFC_MAX_BYTES or os.environ.get("MISTAKES_NO_IFC"):
        return None
    try:
        import ifcopenshell
        import ifcopenshell.util.element as uel
        f = ifcopenshell.open(str(p))
    except Exception:  # noqa: BLE001 - optional deep check, never a failure
        return None
    out: dict[str, dict] = {}
    for cls in PSET_CLASSES:
        try:
            els = f.by_type(cls)
        except Exception:  # noqa: BLE001
            continue
        for e in els:
            try:
                d = {}
                for pn, props in (uel.get_psets(e) or {}).items():
                    for k, v in props.items():
                        if k != "id" and v not in (None, ""):
                            d[f"{pn}.{k}"] = v
                out[e.GlobalId] = d
            except Exception:  # noqa: BLE001
                continue
    return out


# ------------------------------------------------------------------------------------------------ clashes
def _segment_axis(bb):
    """Axis (0|1|2) a straight service segment runs along, or None when its box is not a straight, axis-aligned run."""
    d = _dims(bb)
    order = sorted(range(3), key=lambda i: d[i])
    short2, long = d[order[1]], d[order[2]]
    if long < 0.05 or short2 > 0.8 or short2 > 0.5 * long:
        return None
    return order[2]


def _struct_ok(it) -> bool:
    """Beams and columns whose box is a fair stand-in for their shape: near axis-aligned (one horizontal side <= 1.2 m, or vertical)."""
    dx, dy, dz = _dims(it.bbox_m)
    if it.kind == "column":
        return max(dx, dz) <= 2.5
    return min(dx, dz) <= 1.2 and dy <= 2.5


def clashes(services: list, structure: list, offset_a=None, offset_b=None) -> list[dict]:
    """Bounding-box hard clashes between straight services and beams/columns. services/structure: Items with bbox_m.
    offsets (origin_offset_m of each document) move both into one frame when they come from different files."""
    def shift(bb, off):
        return bb if not off else [[bb[0][0] + off[0], bb[0][1], bb[0][2] + off[2]], [bb[1][0] + off[0], bb[1][1], bb[1][2] + off[2]]]
    cell = 2.0
    grid: dict[tuple, list] = defaultdict(list)
    sb = []
    for s in structure:
        if not s.bbox_m or not _struct_ok(s):
            continue
        b = shift(s.bbox_m, offset_b)
        sb.append((s, b))
        for cx in range(int(math.floor(b[0][0] / cell)), int(math.floor(b[1][0] / cell)) + 1):
            for cz in range(int(math.floor(b[0][2] / cell)), int(math.floor(b[1][2] / cell)) + 1):
                grid[(cx, cz)].append((s, b))
    found = []
    for sv in services:
        if not sv.bbox_m:
            continue
        axis = _segment_axis(sv.bbox_m)
        if axis is None:
            continue
        a = shift(sv.bbox_m, offset_a)
        seen = set()
        for cx in range(int(math.floor(a[0][0] / cell)), int(math.floor(a[1][0] / cell)) + 1):
            for cz in range(int(math.floor(a[0][2] / cell)), int(math.floor(a[1][2] / cell)) + 1):
                for s, b in grid.get((cx, cz), ()):
                    if id(s) in seen:
                        continue
                    seen.add(id(s))
                    ov = [min(a[1][i], b[1][i]) - max(a[0][i], b[0][i]) for i in range(3)]
                    if min(ov) < 0.03:
                        continue
                    sd = _dims(a)
                    trans = [i for i in range(3) if i != axis]
                    if any(ov[i] < 0.6 * sd[i] for i in trans):
                        continue          # grazes the corner, does not go through
                    bd = _dims(b)
                    through = ov[axis] >= 0.9 * bd[axis] - 0.02
                    found.append({"service": sv, "struct": s, "overlap_m": [round(x, 3) for x in ov], "through": through,
                                  "depth": ov[axis], "xyz": _mid([[max(a[0][i], b[0][i]) for i in range(3)], [min(a[1][i], b[1][i]) for i in range(3)]])})
    return found


def _room_at(rooms, storey, x, z):
    for r in rooms:
        if not r.bbox_m or (storey and r.storey and r.storey != storey):
            continue
        if r.bbox_m[0][0] <= x <= r.bbox_m[1][0] and r.bbox_m[0][2] <= z <= r.bbox_m[1][2]:
            return _name(r) or None
    return None


def _clash_mistakes(found, doc_ids, rooms=(), cross=False) -> list[dict]:
    if not found:
        return []
    found.sort(key=lambda c: (not c["through"], -c["depth"]))
    out = []
    top = found[:5]
    for c in top:
        sv, st = c["service"], c["struct"]
        stor = sv.storey or st.storey
        room = _room_at(rooms, stor, c["xyz"][0], c["xyz"][2])
        loc = (f" on {stor}" if stor else "") + (f' near room "{room}"' if room else "")
        verb = "passes through" if c["through"] else "runs into"
        txt = f"{_cap(_desc(sv))} {verb} {_desc(st)}{loc}. No opening or sleeve for it is recorded."
        out.append(_mk("high" if c["through"] else "medium", f"{_cap(_noun(sv.kind))} clashes with a {_noun(st.kind)}", txt, doc_ids,
                       [sv.item_id, st.item_id], {"kind": "clash", "values": {"overlap_m": c["overlap_m"], "location_m": [round(v, 2) for v in c["xyz"]],
                                                                               "through": c["through"], "service": sv.kind, "structure": st.kind}},
                       "Open both in 3D and look at the crossing. A planned sleeve or cut-out may exist that the model does not show.",
                       basis="boxes", storey=stor))
    rest = found[5:]
    if rest:
        cnt = Counter((c["service"].kind, c["struct"].kind) for c in rest)
        parts = ", ".join(f"{n} {_noun(a, n)} with {_noun(b, 2)}" for (a, b), n in cnt.most_common(3))
        out.append(_mk("medium", "More services clash with the structure", f"{len(rest)} further clashes of the same kind: {parts}.", doc_ids,
                       [i for c in rest[:30] for i in (c["service"].item_id, c["struct"].item_id)],
                       {"kind": "clash", "values": {"count": len(rest), "total": len(found)}},
                       "Run a full clash check in your coordination tool for the complete list.", basis="boxes"))
    return out


def _ifc_clashes(doc) -> list[dict]:
    services = [i for i in doc.items if i.kind in SERVICE_KINDS]
    structure = [i for i in doc.items if i.kind in STRUCT_KINDS]
    if not services or not structure:
        return []
    found = clashes(services, structure)
    if len(found) > 0.3 * len(services):
        return []   # too many to be real clashes: boxes of a different frame or loose geometry, say nothing
    return _clash_mistakes(found, [doc.doc_id], [i for i in doc.items if i.kind in ("room", "space")])


# ------------------------------------------------------------------------------------------------ plan maps (CAD, scans)
RELIABLE_SCALE = ("dxf", "pdf_vector", "ratio", "scale-bar", "scalebar", "printed")


def _scale_reliable(sc) -> bool:
    m = str((sc or {}).get("method") or "").lower()
    return any(k in m for k in RELIABLE_SCALE)


def _planmap_areas(doc) -> list[dict]:
    from engine.reasoning_parts.checked import _room_pair
    sc = doc.scale or {}
    mpp = float(sc.get("m_per_px") or 0)
    rooms = [i for i in doc.items if i.kind == "room" and (i.conf or 0) >= 0.5]
    pairs = []
    for r in rooms:
        try:
            p = _room_pair(r, doc, mpp)
        except Exception:  # noqa: BLE001
            p = None
        if p and p[0] > 0.5 and p[1] > 0.05:
            pairs.append((r, *p))
    out = []
    cad = [p for p in pairs if p[3] == "cad"]
    for r, lab, meas, _s in cad:
        d = abs(lab - meas) / max(lab, 1e-9) * 100
        if d > 1.0 and abs(lab - meas) >= 0.2:
            more = "more" if meas > lab else "less"
            out.append(_mk("high" if d >= 10 else "medium", "Printed area differs from drawn area",
                           f'{_cap(_name(r) or "A room")} is labelled {_fmt(lab)} m² but its outline measures {_fmt(meas)} m² ({_fmt(d, 0)}% {more}).',
                           [doc.doc_id], [r.item_id], {"kind": "area_mismatch", "values": {"printed_m2": round(lab, 2), "measured_m2": round(meas, 2), "diff_pct": round(d, 1)}},
                           "Check the printed area against the room outline; one of the two is wrong.", page=r.page, bbox_px=r.bbox_px))
    ras = [p for p in pairs if p[3] == "raster"]
    reliable = _scale_reliable(sc)
    if len(ras) >= 4:
        ratios = [lab / meas for _r, lab, meas, _s in ras]
        med = statistics.median(ratios)
        for (r, lab, meas, _s), ratio in zip(ras, ratios):
            dev = ratio / med
            expect = meas * med
            if abs(dev - 1) <= (0.35 if reliable else 0.45) or abs(lab - expect) < 1.5 or not (1.0 <= lab <= 150) or not (0.4 <= dev <= 2.5):
                continue
            if any(abs(math.log10(dev) - k) < 0.08 for k in (-2, -1, 1, 2)):
                continue          # a missing or extra decimal point is a misread, not a drawing error
            more = "more" if expect > lab else "less"
            out.append(_mk("low", "Printed area differs from drawn area",
                           f'{_cap(_name(r) or "A room")} is labelled {_fmt(lab)} m² but its outline measures about {_fmt(expect)} m² '
                           f"({_fmt(abs(expect - lab) / lab * 100, 0)}% {more}) once the scale is matched to the other rooms.",
                           [doc.doc_id], [r.item_id], {"kind": "area_mismatch", "values": {"printed_m2": round(lab, 2), "measured_m2": round(expect, 2),
                                                                                           "diff_pct": round(abs(expect - lab) / lab * 100, 1)}},
                           "This comes from a scanned drawing, so a misread number is possible: look at the printed value and the outline.",
                           basis="scan", page=r.page, bbox_px=r.bbox_px))
    return out


WET_FIXTURES = ("toilet", "shower", "bathtub")
DRY_TYPES = ("bedroom", "living", "dining")


def _inside(pt, poly) -> bool:
    from engine.reasoning_parts.checked import _inside as ins
    return ins(pt, poly)


def _planmap_names(doc) -> list[dict]:
    rooms = [i for i in doc.items if i.kind == "room" and i.polygon_px and (i.props or {}).get("label_room_type") in DRY_TYPES and (i.conf or 0) >= 0.5]
    fix = [i for i in doc.items if i.kind in WET_FIXTURES and i.bbox_px and (i.conf or 0) >= 0.8]
    out = []
    for r in rooms:
        inside = [f for f in fix if f.page == r.page and _inside(((f.bbox_px[0] + f.bbox_px[2]) / 2, (f.bbox_px[1] + f.bbox_px[3]) / 2), r.polygon_px)]
        if not inside:
            continue
        f = inside[0]
        word = (r.props or {}).get("label_room_type")
        nm = _name(r) or word
        out.append(_mk("low", "Room name does not fit what is in the room",
                       f'The room marked "{nm}" ({word}) contains a {_noun(f.kind)}.', [doc.doc_id], [r.item_id, f.item_id],
                       {"kind": "name_mismatch", "values": {"printed_name": nm, "room_type": word, "fixture": f.kind}},
                       "Look at the room: either the name or the fixture is in the wrong place.", basis="scan" if f.source != "dxf" else "exact",
                       page=r.page, bbox_px=r.bbox_px))
    return out


# ------------------------------------------------------------------------------------------------ one document
def find_doc(doc_id: str, root=None) -> list[dict]:
    root = _root(root)
    try:
        doc = _load(doc_id, root)
    except Exception:  # noqa: BLE001
        return []
    if doc is None:
        return []
    cached = _cache_get(doc_id, root)
    if cached is not None:
        return cached
    out: list[dict] = []
    if doc.mode == "ifc":
        psets = None
        try:
            psets = _ifc_psets(doc_id, root)
        except Exception:  # noqa: BLE001
            psets = None
        checks = [lambda: _ifc_numbers(doc), lambda: _ifc_no_storey(doc), lambda: _ifc_duplicates(doc), lambda: _ifc_unhosted(doc),
                  lambda: _ifc_spaces(doc), lambda: _sibling_gaps(doc, psets), lambda: _ifc_clashes(doc)]
    else:
        checks = [lambda: _planmap_areas(doc), lambda: _planmap_names(doc)]
    for c in checks:
        try:
            out.extend(c())
        except Exception:  # noqa: BLE001 - one broken check never hides the others
            continue
    out = _rank(out)[:CAP_PER_DOC]
    _cache_put(doc_id, root, out)
    return out


def _rank(ms: list[dict]) -> list[dict]:
    seen, res = set(), []
    for m in sorted(ms, key=lambda m: (SEV_RANK.get(m["severity"], 3), -len(m.get("item_ids") or []))):
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        res.append(m)
    return res


# ------------------------------------------------------------------------------------------------ across documents
def _level_counts(doc) -> dict:
    out: dict[str, Counter] = defaultdict(Counter)
    for it in doc.items:
        if it.kind in ("room", "door", "window") and it.storey:
            out[_norm_level(it.storey)][it.kind] += 1
    return out


def _cross_doc(docs: list, root: Path) -> list[dict]:
    out = []
    ifcs = [d for d in docs if d.mode == "ifc"]
    # 1. the same storey carries a different number of doors, windows or rooms in two models that both list them
    for i in range(len(ifcs)):
        for j in range(i + 1, len(ifcs)):
            a, b = ifcs[i], ifcs[j]
            la, lb = _level_counts(a), _level_counts(b)
            for lvl in sorted(set(la) & set(lb)):
                for kind in ("room", "door", "window"):
                    na, nb = la[lvl][kind], lb[lvl][kind]
                    if na and nb:
                        cmp_ = compare([{"doc_id": a.doc_id, "value": na}, {"doc_id": b.doc_id, "value": nb}])
                        if cmp_["status"] == "differs":
                            label = next((it.storey for it in a.items if _norm_level(it.storey) == lvl), lvl)
                            ids_a = [it.item_id for it in a.items if it.kind == kind and _norm_level(it.storey) == lvl]
                            ids_b = [it.item_id for it in b.items if it.kind == kind and _norm_level(it.storey) == lvl]
                            out.append(_mk("medium", f"{_cap(_noun(kind, 2))} differ between two models",
                                           f"{_cap(label)} has {na} {_noun(kind, na)} in {_title(a.doc_id, root)} but {nb} in {_title(b.doc_id, root)}.",
                                           [a.doc_id, b.doc_id], ids_a[:30] + ids_b[:30],
                                           {"kind": "count_mismatch", "values": {"level": label, a.doc_id: na, b.doc_id: nb}},
                                           "Open both models on this storey and compare; one of them is out of date or incomplete.", storey=label))
    # 2. services of one model against the structure of another (only when the two models share a frame)
    for a in ifcs:
        for b in ifcs:
            if a is b:
                continue
            services = [i for i in a.items if i.kind in SERVICE_KINDS]
            structure = [i for i in b.items if i.kind in STRUCT_KINDS]
            if not services or not structure or any(i.kind in STRUCT_KINDS for i in a.items) and a.doc_id == b.doc_id:
                continue
            oa, ob = _origin_offset(a.doc_id, root), _origin_offset(b.doc_id, root)
            if oa is None or ob is None:
                continue
            if not _frames_agree(a, b, oa, ob):
                continue
            found = clashes(services, structure, oa, ob)
            if len(found) > 0.3 * len(services):
                continue
            out.extend(_clash_mistakes(found, [a.doc_id, b.doc_id], [i for i in b.items if i.kind in ("room", "space")] + [i for i in a.items if i.kind in ("room", "space")], True))
    return out


def _frames_agree(a, b, oa, ob) -> bool:
    """Do two models sit in one coordinate frame? Their storey elevations match and their footprints overlap substantially."""
    def foot(d, off):
        bbs = [i.bbox_m for i in d.items if i.bbox_m and i.kind not in ("site",)]
        if not bbs:
            return None
        return [min(b[0][0] for b in bbs) + off[0], min(b[0][2] for b in bbs) + off[2], max(b[1][0] for b in bbs) + off[0], max(b[1][2] for b in bbs) + off[2]]
    fa, fb = foot(a, oa), foot(b, ob)
    if not fa or not fb:
        return False
    iw, ih = min(fa[2], fb[2]) - max(fa[0], fb[0]), min(fa[3], fb[3]) - max(fa[1], fb[1])
    if iw <= 0 or ih <= 0:
        return False
    inter = iw * ih
    smaller = min((fa[2] - fa[0]) * (fa[3] - fa[1]), (fb[2] - fb[0]) * (fb[3] - fb[1]))
    ea, eb = sorted(float(s["elevation_m"]) for s in a.storeys if s.get("elevation_m") is not None), sorted(float(s["elevation_m"]) for s in b.storeys if s.get("elevation_m") is not None)
    elev_ok = bool(ea and eb) and sum(1 for x in ea if any(abs(x - y) < 0.05 for y in eb)) >= max(1, min(len(ea), len(eb)) // 2)
    return smaller > 0 and inter / smaller >= 0.6 and elev_ok


def _title(doc_id: str, root: Path) -> str:
    try:
        return json.loads((root / doc_id / "doc.json").read_text()).get("title") or doc_id
    except (OSError, ValueError):
        return doc_id


# ------------------------------------------------------------------------------------------------ public
def find(doc_ids, root=None) -> list[dict]:
    root = _root(root)
    ids = list(dict.fromkeys(doc_ids or []))
    out: list[dict] = []
    docs = []
    for d in ids:
        out.extend(find_doc(d, root))
        try:
            doc = _load(d, root)
        except Exception:  # noqa: BLE001
            doc = None
        if doc is not None:
            docs.append(doc)
    if len(docs) >= 2:
        try:
            out.extend(_cross_doc(docs, root))
        except Exception:  # noqa: BLE001
            pass
    return _rank(out)


def summary(doc_ids, root=None) -> dict:
    """What the checks looked at, for an honest 'nothing found' answer."""
    root = _root(root)
    cnt = Counter()
    modes = set()
    for d in doc_ids or []:
        try:
            doc = _load(d, root)
        except Exception:  # noqa: BLE001
            doc = None
        if doc is None:
            continue
        modes.add(doc.mode)
        for it in doc.items:
            cnt["room" if it.kind == "space" else it.kind] += 1
    return {"counts": dict(cnt), "modes": sorted(modes)}


# small on-disk cache next to the document's other derived files; keyed by input mtimes + CHECKS_VERSION, best effort
def _cache_key(doc_id: str, root: Path) -> str | None:
    d = root / doc_id
    parts = [str(CHECKS_VERSION)]
    for p in [d / "elements.json", d / "doc.json", *sorted(d.glob("planmap-[0-9]*.json"))]:
        try:
            parts.append(f"{p.name}:{int(p.stat().st_mtime)}:{p.stat().st_size}")
        except OSError:
            pass
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16] if len(parts) > 1 else None


_MEM: dict = {}


def _cache_get(doc_id: str, root: Path):
    if os.environ.get("MISTAKES_NO_CACHE"):
        return None
    k = _cache_key(doc_id, root)
    if k is None:
        return None
    hit = _MEM.get((str(root), doc_id))
    if hit and hit[0] == k:
        return hit[1]
    p = root / doc_id / "mistakes.json"
    try:
        j = json.loads(p.read_text())
        if j.get("key") == k:
            _MEM[(str(root), doc_id)] = (k, j["mistakes"])
            return j["mistakes"]
    except (OSError, ValueError, KeyError):
        pass
    return None


def _cache_put(doc_id: str, root: Path, ms: list[dict]) -> None:
    if os.environ.get("MISTAKES_NO_CACHE"):
        return
    k = _cache_key(doc_id, root)
    if k is None:
        return
    _MEM[(str(root), doc_id)] = (k, ms)
    try:
        (root / doc_id / "mistakes.json").write_text(json.dumps({"key": k, "mistakes": ms}))
    except OSError:
        pass


# ------------------------------------------------------------------------------------------------ chat route
_Q = re.compile(
    r"\b(?:mistakes?|errors?|problems?|issues?|inconsisten\w+|discrepanc\w+|clash(?:es)?|conflicts?|wrong|faults?|flaws?|defects?)\b", re.I)
_Q_FRAME = re.compile(
    r"(?:\b(?:are|is)\s+there\s+(?:any|some)\b|\b(?:find|show|list|spot|detect|check\s+(?:for|this|the|it|my)|any|what|which)\b|\bwrong\b|\bsomething\s+wrong\b|\bcheck\b|\bcatch\b|\breview\b)", re.I)
_Q_NOT = re.compile(r"\b(?:how many|what is the (?:area|height|width|length|volume)|total area|per ?sq|error margin|margin of error|trouble ?shoot|error message|how (?:do|can|to))\b", re.I)


def is_mistakes_question(q: str) -> bool:
    q = (q or "").strip()
    if not q or len(q) > 240 or _Q_NOT.search(q) or not _Q.search(q):
        return False
    return bool(_Q_FRAME.search(q))


def _plural(n, w):
    return f"{n} {w}{'' if n == 1 else 's'}"


def answer(question: str, doc_ids: list[str], root=None, t0: float | None = None, trace: list | None = None) -> dict | None:
    """Chat answer built only from find(): numbered items on the drawing, a Checked card. None when this is not that question."""
    if not doc_ids or not is_mistakes_question(question):
        return None
    root = _root(root)
    t0 = t0 or time.perf_counter()
    ms = find(doc_ids, root)
    sm = summary(doc_ids, root)
    if not sm["counts"]:
        return None
    n = len(ms)
    trace = list(trace or [])
    trace.append({"step": "mistakes", "detail": f"{n} possible mistakes from code checks over the file data", "ms": int((time.perf_counter() - t0) * 1000), "model": None, "cost_usd": 0.0})
    cites, boxes, hl = [], [], []
    shown = ms[:4] if n else []
    lines = []
    first_doc = doc_ids[0]
    for k, m in enumerate(shown, 1):
        did = (m.get("doc_ids") or [first_doc])[0]
        ids = m["item_ids"]
        bb = m.get("bbox_px")
        cites.append({"n": k, "doc_id": did, "page": int(m.get("page") or 1), "kind": "element", "bbox_px": [float(v) for v in bb] if bb and len(bb) == 4 else None,
                      "item_ids": ids[:30], "quote": m["title"]})
        if bb and len(bb) == 4:
            boxes.append({"item_id": ids[0], "page": int(m.get("page") or 1), "bbox_px": [int(v) for v in bb], "label": str(k)})
        hl.extend(ids[:30])
        lines.append(f"- **{k}.** {m['text']}")
    exact_all = all(m.get("basis") == "exact" for m in ms) if ms else True
    if n:
        head = f"**{_plural(n, 'possible mistake')} found.** The worst {'is' if len(shown) == 1 else 'are'} listed first."
        more = f"\n\n{n - len(shown)} more are on the Mistakes list of the document." if n > len(shown) else ""
        text = head + "\n\n" + "\n".join(lines) + more
        conf = 0.9 if exact_all else 0.7
        label, pct = ("Verified", 95) if exact_all else (("Cross-checked", 84) if all(m.get("basis") in ("exact", "boxes") for m in ms) else ("Estimate", 68))
        reason = ("Read directly from the file's own data; nothing is estimated." if exact_all else
                  "Overlaps come from element boxes, so each one needs a look in 3D." if label == "Cross-checked" else
                  "Some findings come from a scanned drawing, where a misread number is possible.")
    else:
        c = sm["counts"]
        seen = ", ".join(f"{v} {_noun(k, v)}" for k, v in sorted(c.items(), key=lambda kv: -kv[1])[:4] if k not in SKIP_KINDS)
        text = (f"**No mistakes found** by the checks I can run on this file.\n\nI looked at {seen or 'the drawing data'}: "
                "printed against drawn areas, duplicates, openings outside walls, missing storeys, missing values and clashes, wherever the file has the data. "
                "That does not prove the file is error free.")
        conf, label, pct, reason = 0.85, "Cross-checked", 84, "Only checks the file's data allows were run; a clean result is not a guarantee."
    steps = [{"kind": "checked", "title": "Checked", "ok": n == 0,
              "text": (f"Ran the file's own consistency checks; {_plural(n, 'possible mistake')} found" if n else "Ran the file's own consistency checks; nothing found"), "cite": 1 if cites else None}]
    scene = {"doc_id": first_doc, "highlight_item_ids": list(dict.fromkeys(hl)), "camera_target_item_id": hl[0] if hl else None}
    return {
        "answer_id": uuid.uuid4().hex, "question": question, "doc_ids": list(doc_ids),
        "answer": {"text_md": text, "value": n, "unit": "mistakes", "confidence": conf, "abstained": False},
        "citations": cites, "evidence": {"boxes": boxes, "scene": scene}, "trace": trace, "route": "index",
        "cost": {"usd_total": 0.0, "calls": []}, "latency_ms": int((time.perf_counter() - t0) * 1000),
        "reasoning": {"steps": steps, "confidence": {"label": label, "pct": pct, "reason": reason, "improve": None}},
        "mistakes": ms[:CAP_PER_DOC],
    }
