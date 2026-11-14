"""Quantity take-off: ONE answer whose text_md carries one markdown table `| Item | Quantity | Unit | Source |` (agreed with WEB-INTEG), rows in order:
floor area per room (m2), baseboard per room (m), doors (count), windows (count), slab area by type (m2), piping by system (m).
Source = citation markers that exist in answer.citations. A row the file lacks: Quantity "not in this file", Unit and Source empty.
Code only: it reuses the analytics solvers (rooms, baseboard, slab_by_type) and the piping extract; value = number of rooms, unit "rooms"."""
from __future__ import annotations

import re

from engine.solvers.solve import _answer_obj, _evidence, _qty, _step

TAKEOFF_Q = re.compile(r"\bquantity take[- ]?off\b|\btake[- ]?off\b(?!.*\bfor\b)|\bbill of quantities\b|\bBoQ\b|\bquantities?\s+(?:schedule|table|summary|list)\b|\bfull (?:take[- ]?off|quantities)\b"
                       r"|\b(?:list|give|show)\s+(?:me\s+)?(?:all |the )?quantities\b", re.I)
NIF = "not in this file"


def _fmt(v, nd=1):
    return f"{v:,.{nd}f}" if v is not None else NIF


def _section(res, name):
    """text of a sub-answer without its marks, or None when it is a 'no data' answer."""
    if res is None or res["answer"].get("abstained"):
        return None
    t = res["answer"]["text_md"]
    if re.search(r"\bno (?:pipe|slab)|none found|could not find|couldn't find|not in this file", t, re.I) and not res.get("citations"):
        return None
    return t


def quantity_takeoff(question, doc, t0):
    if not TAKEOFF_Q.search(question):
        return None
    from engine import analytics as A
    ifc = doc.mode == "ifc"
    rooms = [r for r in A._of_kind(doc, "room") if (r.bbox_m if ifc else r.bbox_px)]
    trace = [_step("route", "quantity take-off -> existing solvers (rooms, baseboard, doors, windows, slabs, piping), code, no model")]
    # baseboard per room (also fills LAST_BB)
    A.LAST_BB.clear()
    bb = None
    if rooms:
        try:
            bb = A.baseboard("How many linear metres of baseboard per room?", doc, t0)
        except Exception:  # noqa: BLE001
            bb = None
    per = dict(A.LAST_BB)
    no_scale = bb is not None and bb["answer"].get("value") is None
    wins = [w for w in A._of_kind(doc, "window") if A._foot(w, ifc)]
    rows = []
    for r in rooms:
        area = _qty(r, "room", "area")
        approx = False
        if not area and ifc and r.bbox_m:
            b = r.bbox_m
            area, approx = round((b[1][0] - b[0][0]) * (b[1][2] - b[0][2]), 2), True
        b = per.get(r.item_id)
        nw = 0
        f = A._foot(r, ifc)
        if f:
            band = A.DOOR_BAND if ifc else 0
            for w in wins:
                if ifc and w.storey != r.storey:
                    continue
                g = A._foot(w, ifc)
                cx, cy = (g[0] + g[2]) / 2, (g[1] + g[3]) / 2
                if f[0] - band <= cx <= f[2] + band and f[1] - band <= cy <= f[3] + band:
                    nw += 1
        rows.append({"r": r, "area": area, "approx": approx, "bb": (b or {}).get("net"), "doors": (b or {}).get("doors"), "wins": nw})
    cit_all, box_all, ids = [], [], []

    def cite(items, label=None):
        """one citation (+ its boxes) for a group of items; returns its marker like '[3]'"""
        items = [x for x in items if x is not None]
        if not items:
            return ""
        bx, cs, sc = _evidence(doc, items)
        n = len(cit_all) + 1
        c = dict(cs[0], n=n)
        c["item_ids"] = [i.item_id for i in items]
        cit_all.append(c)
        for b in bx:
            box_all.append(dict(b, label=str(n)))
        ids.extend(i for i in sc["highlight_item_ids"] if i not in ids)
        return f"[{n}]"

    T = []

    def row(item, q, unit, src):
        T.append(f"| {item} | {q} | {unit} | {src} |")

    def missing(item):
        T.append(f"| {item} | {NIF} |  |  |")

    lab = lambda r: (A._room_label(r) or "room")[:40] + (f" ({r.storey})" if ifc and r.storey and len(doc.storeys) > 1 else "")  # noqa: E731
    marks = {}
    for x in rows[:60]:
        marks[x["r"].item_id] = cite([x["r"]])
    if not rows:
        missing("Floor area")
        missing("Baseboard")
    for x in rows[:60]:
        r = x["r"]
        if x["area"]:
            row(f"Floor area - {lab(r)}" + (" (bounding rectangle)" if x["approx"] else ""), f"{x['area']:.2f}", "m2", marks[r.item_id])
        else:
            missing(f"Floor area - {lab(r)}")
    for x in rows[:60]:
        r = x["r"]
        if x["bb"] is not None:
            row(f"Baseboard - {lab(r)}", f"{x['bb']:.1f}", "m", marks[r.item_id])
        else:
            missing(f"Baseboard - {lab(r)}")
    doors = [d for d in A._of_kind(doc, "door") if (d.bbox_m if ifc else d.bbox_px)]
    for kind, its in (("Doors", doors), ("Windows", wins)):
        if its:
            row(kind, str(len(its)), "count", cite(its))
        else:
            missing(kind)
    slab = None
    try:
        slab = A.slab_by_type("What is the slab area by type and thickness?", doc, t0)
    except Exception:  # noqa: BLE001
        pass
    srows = []
    if _section(slab, "slab"):
        off = len(cit_all)
        for c in slab.get("citations") or []:
            cit_all.append(dict(c, n=len(cit_all) + 1))
        for b in slab["evidence"].get("boxes") or []:
            box_all.append(dict(b, label=str(int(b["label"]) + off) if str(b.get("label", "")).isdigit() else b.get("label")))
        ids.extend(i for i in slab["evidence"]["scene"].get("highlight_item_ids") or [] if i not in ids)
        for m in re.finditer(r"^\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*\d+\s*\|\s*([\d,.]+)\s*m²\s*\|\s*([^|]*?)\s*\|\s*$", slab["answer"]["text_md"], re.M):
            if m.group(1).lower() == "type":
                continue
            ns_ = []
            for k in re.findall(r"\[(\d+)\]", m.group(4)):  # the sub-answer's marks are box labels: map each to the citation holding that item
                bid = next((b["item_id"] for b in slab["evidence"].get("boxes") or [] if str(b.get("label")) == k), None)
                cn = next((c["n"] for c in cit_all[off:] if bid in (c.get("item_ids") or [])), None) or (off + 1 if cit_all[off:] else None)
                if cn and f"[{cn}]" not in ns_:
                    ns_.append(f"[{cn}]")
            src = "".join(ns_)
            srows.append((f"Slab area - {m.group(1)[:50]}, {m.group(2)}", m.group(3).replace(",", ""), "m2", src))
    for r_ in srows:
        row(*r_)
    if not srows:
        missing("Slab area by type")
    prow = []
    try:
        pd = A._piping_data(doc)
    except Exception:  # noqa: BLE001
        pd = None
    if pd:
        by_id = {i.item_id: i for i in doc.items}
        for name, v in sorted(((pd.get("rollups") or {}).get("by_system") or {}).items(), key=lambda kv: -kv[1]["length_m"])[:25]:
            its = [by_id[i] for i in v.get("item_ids", []) if i in by_id]
            prow.append((f"Piping - {name}", f"{v['length_m']:.1f}", "m", cite(its[:200]) if its else ""))
    for r_ in prow:
        row(*r_)
    if not prow:
        missing("Piping by system")
    notes = []
    if any(x["approx"] for x in rows):
        notes.append("Areas marked (bounding rectangle) have no area quantity in the model.")
    if no_scale:
        notes.append("Baseboard needs a drawing scale and this one has none.")
    text = ("**Quantity take-off**, computed from the file's own data with no model call.\n\n| Item | Quantity | Unit | Source |\n|---|---|---|---|\n" + "\n".join(T)
            + (("\n\n_" + " ".join(notes) + "_") if notes else ""))
    trace += [_step("rooms", f"{len(rows)} rooms"), _step("slab", f"{len(srows)} rows" if srows else NIF), _step("piping", f"{len(prow)} systems" if prow else NIF)]
    scene2 = {"doc_id": doc.doc_id, "highlight_item_ids": ids, "camera_target_item_id": ids[0] if ids else None}
    return _answer_obj(question, [doc.doc_id], text, len(rows), "rooms", 0.8, False, box_all, cit_all, scene2, trace, "index" if ifc else "planmap", t0)
