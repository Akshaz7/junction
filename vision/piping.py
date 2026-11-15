"""V-08 piping: pipe sizes, pipe length and drains from IFC plumbing models, in plain code (no model, no training).

  .venv/bin/python vision/piping.py extract DOC_ID IFC_PATH      # -> results/vision/piping/<doc>.json  (per-element rows + rollups)
  .venv/bin/python vision/piping.py ask DOC_ID "what pipe sizes are used?"   # keyword router over the stored rollups; prints text + item_ids

Why IFC: the dataset has NO piping DXF (the 9 non-Swiss DXFs are mouldings/site/blender exports, layers WALL/DOOR/WINDOW/FIXTURE only on Swiss); the piping data is in 4 plumbing IFCs
(digital_hub_plumbing, sixty5_plumbing, bsc duplex plumbing, bsc clinic plumbing) plus Vacation_Rental/CTR plumbing PDFs (raster/vector sheets, not read here).
item_id = IFC GlobalId, the same id the scene GLB and artifacts/<doc>/elements.json use, so answers glow in 3D/AR like any other item.
UNITS: Revit exports store lengths/diameters in millimetres in property sets; the IFC unit scale is checked and everything is converted to metres / mm here. The benchmark answer for
digital-hub-plumbing says "301106.02 m": that is the same sum in mm mislabelled as m (real total about 301 m).
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results/vision/piping"
PIPE_CLASSES = ("IfcPipeSegment", "IfcFlowSegment")
DRAIN_CLASSES = ("IfcWasteTerminal",)
SAN_CLASSES = ("IfcSanitaryTerminal",)
FITTING_CLASSES = ("IfcPipeFitting", "IfcFlowFitting")
LEN_KEYS = ("Länge", "Length", "Laenge", "Lengte", "NetLength", "GrossLength")
DN_KEYS = ("NominalDiameter", "Nominal Diameter", "Durchmesser", "Diameter", "Nominale diameter", "Außendurchmesser", "Outside Diameter", "OuterDiameter")
SYS_KEYS = ("Systemname", "System Name", "Systemtyp", "System Type", "Systeemnaam", "Systeemtype", "Systemklassifizierung", "System Classification")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _find(ps, keys):
    for pset in ps.values():
        if not isinstance(pset, dict):
            continue
        for k in keys:
            if k in pset and pset[k] not in (None, ""):
                return pset[k]
    return None


def _dn_from_text(*texts):
    for t in texts:
        m = re.search(r"\bDN\s?(\d{1,4})\b", str(t or ""), re.I)
        if m:
            return float(m.group(1))
    return None


def _storey(el, UE):
    c = UE.get_container(el)
    while c is not None and not c.is_a("IfcBuildingStorey"):
        c = UE.get_aggregate(c) if hasattr(UE, "get_aggregate") else None
    return c.Name if c is not None else None


# ------------------------------------------------------------------ sizes and units: general, from the IFC unit, the property type and the element's own geometry
DN_SERIES = (6, 8, 10, 15, 20, 25, 32, 40, 50, 65, 80, 100, 125, 150, 200, 250, 300, 350, 400, 450, 500, 600, 700, 800, 900, 1000, 1200)
LENGTH_TYPES = ("IFCLENGTHMEASURE", "IFCPOSITIVELENGTHMEASURE", "IFCNONNEGATIVELENGTHMEASURE")
FRAC = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:[.,]\d+)?)"


def snap_dn(mm: float | None) -> float | None:
    """Nearest standard nominal size when within 10 percent, else the value rounded to a whole millimetre."""
    if not mm or mm <= 0:
        return None
    best = min(DN_SERIES, key=lambda d: abs(d - mm))
    return float(best) if abs(best - mm) <= 0.10 * best else float(round(mm))


def _frac(txt: str) -> float:
    txt = txt.strip().replace(",", ".")
    tot = 0.0
    for part in txt.split():
        if "/" in part:
            a, b = part.split("/")
            tot += float(a) / float(b)
        else:
            tot += float(part)
    return tot


def parse_size_mm(*texts) -> float | None:
    """A size written as text: "DN 50", "40 mm", "40 mm⌀", "Ø50", "1 1/2\"", "2 in". None when no unit or DN marker is printed (a bare number is not a size)."""
    for t in texts:
        t = str(t or "")
        m = re.search(r"\bDN\s?(\d{1,4})\b", t, re.I)
        if m:
            return float(m.group(1))
        m = re.search(r"[ØøΦ⌀]\s?(\d{1,4}(?:[.,]\d+)?)\b", t) or re.search(r"\b(\d{1,4}(?:[.,]\d+)?)\s?(?:mm|millimet\w*)(?![A-Za-z])", t, re.I)
        if m:
            return float(m.group(1).replace(",", "."))
        m = re.search(rf"\b({FRAC})\s?(?:\"|''|in\b|inch\w*|″|”)", t, re.I)
        if m:
            try:
                return _frac(m.group(1)) * 25.4
            except ValueError:
                pass
    return None


def cross_section_mm(bbox_m, rect: bool = False):
    """Cross-section of a straight, mostly axis-aligned run from its bounding box: mean of the two short sides (round), or (small, large) of them (rect). None for compact or diagonal shapes."""
    if not bbox_m:
        return None
    a, b = bbox_m
    ext = sorted((b[i] - a[i]) * 1000 for i in range(3))
    s0, s1, s2 = ext
    if s2 < 2.0 * max(s1, 1.0) or s1 <= 0:
        return None
    if rect:
        return (s0, s1)
    return (s0 + s1) / 2 if s1 <= 1.35 * s0 + 4 else None


def pick_factor(pairs, cands, tol=(0.55, 1.9), min_pairs=5, min_share=0.5):
    """pairs (value, geometric mm); cands {name: mm per value unit}. The unit under which most values agree with the geometry, and its share, or (None, 0)."""
    pairs = [(v, c) for v, c in pairs if v and v > 0 and c and c > 0]
    if len(pairs) < min_pairs:
        return None, 0.0
    best, share = None, 0.0
    for name, f in cands.items():
        s = sum(tol[0] <= v * f / c <= tol[1] for v, c in pairs) / len(pairs)
        if s > share + 1e-9:
            best, share = name, s
    return (best, share) if share >= min_share else (None, share)


def resolve_numeric(vals: dict, cs: dict, typed_mm: dict, unit_scale: float, tol=(0.55, 1.9)):
    """Millimetres for one numeric property over many elements, never guessing.

    vals {id: raw number}, cs {id: geometric mm or None}, typed_mm {id: True when the property is a typed IFC length (so the file's own unit applies)}.
    A value is kept only when it agrees with its element's own geometry under ONE unit chosen for the whole property (mm, inch, foot, metre, IFC unit);
    a constant placeholder (the same 1.0 everywhere) agrees with nothing and is dropped. With no usable geometry only typed lengths are trusted.
    Returns ({id: mm}, info)."""
    cands = {"mm": 1.0, "in": 25.4, "ft": 304.8, "m": 1000.0}
    if unit_scale and abs(unit_scale * 1000 - 1.0) > 1e-9 and abs(unit_scale * 1000 - 25.4) > 1e-9 and abs(unit_scale * 1000 - 304.8) > 1e-9 and abs(unit_scale * 1000 - 1000.0) > 1e-9:
        cands["ifc"] = unit_scale * 1000.0
    pairs = [(vals[i], cs.get(i)) for i in vals if cs.get(i)]
    name, share = pick_factor(pairs, cands, tol)
    out, how = {}, {"unit": name, "agree": round(share, 2), "pairs": len(pairs)}
    for i, v in vals.items():
        if v is None or v <= 0:
            continue
        c = cs.get(i)
        if name and c:
            if tol[0] <= v * cands[name] / c <= tol[1]:
                out[i] = v * cands[name]
        elif name and not c:
            mm = v * cands[name]
            if 3 <= mm <= 3000:
                out[i] = mm
        elif typed_mm.get(i):
            mm = v * unit_scale * 1000.0
            if (not c and 3 <= mm <= 3000) or (c and tol[0] <= mm / c <= tol[1]):
                out[i] = mm
    return out, how


def typed_props(el):
    """{pset: {prop: (value, IFC value type upper-case)}} for an element and its type; the type only fills what the element lacks."""
    out: dict = {}

    def grab(obj, over):
        for rel in getattr(obj, "IsDefinedBy", None) or []:
            d = getattr(rel, "RelatingPropertyDefinition", None)
            if d is None or not d.is_a("IfcPropertySet"):
                continue
            tgt = out.setdefault(d.Name or "", {})
            for p in d.HasProperties or []:
                if p.is_a("IfcPropertySingleValue") and p.NominalValue is not None and (over or p.Name not in tgt):
                    tgt[p.Name] = (p.NominalValue.wrappedValue, p.NominalValue.is_a().upper())
    grab(el, True)
    for rel in getattr(el, "IsTypedBy", None) or []:
        grab(rel.RelatingType, False)
    t = None
    if not getattr(el, "IsTypedBy", None):  # IFC2x3 type link
        for rel in getattr(el, "IsDefinedBy", None) or []:
            if rel.is_a("IfcRelDefinesByType"):
                t = rel.RelatingType
        if t is not None:
            grab(t, False)
    return out


def _extruded_length_m(el, scale: float):
    """Length of a straight run from its extrusion depth (a swept solid), in metres, or None."""
    try:
        reps = [r for r in (el.Representation.Representations if el.Representation else []) if r.RepresentationIdentifier in ("Body", "Axis", None, "")]
        stack = [i for r in reps for i in r.Items]
        while stack:
            it = stack.pop()
            if it.is_a("IfcMappedItem"):
                stack.extend(it.MappingSource.MappedRepresentation.Items)
            elif it.is_a("IfcExtrudedAreaSolid"):
                d = it.ExtrudedDirection.DirectionRatios
                n = sum(x * x for x in d) ** 0.5 or 1.0
                return float(it.Depth) * scale / (1.0 if abs(n - 1.0) < 1e-6 else 1.0)
    except Exception:  # noqa: BLE001
        return None
    return None


def build_rows(f, el_list, kind, geo, scale, UE):
    """Size, length and system rows for one group of elements, with units resolved once for the whole group (see resolve_numeric)."""
    systems = {}
    for sysent in f.by_type("IfcSystem"):
        for rel in getattr(sysent, "IsGroupedBy", None) or []:
            for o in rel.RelatedObjects:
                systems.setdefault(o.GlobalId, sysent.Name)
    raw = []
    for el in el_list:
        tp = typed_props(el)
        flat = {}
        for pset, d in tp.items():
            for k, (v, ty) in d.items():
                flat.setdefault(k, (v, ty))
        ps = UE.get_psets(el)
        t = UE.get_type(el)
        if t is not None:
            for k, v in UE.get_psets(t).items():
                ps.setdefault(k, v)
        raw.append((el, t, ps, flat, geo.get(el.GlobalId)))
    # numeric diameter candidates (every key that names a diameter), length candidates
    dn_vals: dict[str, dict] = defaultdict(dict)
    dn_typed: dict[str, dict] = defaultdict(dict)
    dn_cs: dict = {}
    len_vals: dict = {}
    len_typed: dict = {}
    len_geo: dict = {}
    for el, t, ps, flat, g in raw:
        i = el.GlobalId
        dn_cs[i] = cross_section_mm((g or {}).get("bbox_m"))
        for k in DN_KEYS:
            if k in flat:
                v = _num(flat[k][0])
                if v is not None:
                    dn_vals[k][i] = v
                    dn_typed[k][i] = flat[k][1] in LENGTH_TYPES
        for k in LEN_KEYS:
            if k in flat and _num(flat[k][0]) is not None and i not in len_vals:
                len_vals[i] = _num(flat[k][0]); len_typed[i] = flat[k][1] in LENGTH_TYPES
        bb = (g or {}).get("bbox_m")
        if bb:
            ext = sorted(bb[1][j] - bb[0][j] for j in range(3))
            len_geo[i] = (ext[2], sum(e * e for e in ext) ** 0.5)
    dn_ok = {k: resolve_numeric(v, dn_cs, dn_typed[k], scale) for k, v in dn_vals.items()}
    # lengths: one unit for the group, judged against the run's bounding box (a straight run is at least its longest side and at most its diagonal)
    cands = {"mm": 0.001, "ft": 0.3048, "m": 1.0, "in": 0.0254}
    if abs(scale - 0.001) > 1e-12 and abs(scale - 1.0) > 1e-12 and abs(scale - 0.3048) > 1e-12 and abs(scale - 0.0254) > 1e-12:
        cands["ifc"] = scale
    lp = [(len_vals[i], len_geo[i]) for i in len_vals if i in len_geo and len_geo[i][1] > 0.02]
    lname, lshare = None, 0.0
    if len(lp) >= 5:
        for nm, fct in cands.items():
            sh = sum(0.85 * g0 <= v * fct <= 1.08 * g1 for v, (g0, g1) in lp) / len(lp)
            if sh > lshare + 1e-9:
                lname, lshare = nm, sh
        if lshare < 0.5:
            lname = None
    rows = []
    for el, t, ps, flat, g in raw:
        i = el.GlobalId
        name_txt = (el.Name, getattr(el, "ObjectType", None), t.Name if t is not None else None)
        size_txt = _find(ps, ("Größe", "Size", "Maat", "Gesamtmaß", "Dimensioner", "Koko", "Mitat", "Storlek"))
        dn, dsrc = None, None
        txt_mm = parse_size_mm(size_txt) or parse_size_mm(*name_txt)
        if txt_mm and (not dn_cs.get(i) or 0.3 <= txt_mm / dn_cs[i] <= 3.0):
            dn, dsrc = txt_mm, "printed size"
        if dn is None:
            for k in DN_KEYS:
                mm = dn_ok.get(k, ({}, None))[0].get(i)
                if mm:
                    dn, dsrc = mm, "model property, checked against the 3D shape"
                    break
        dn = snap_dn(dn) if dn else None
        length_m, lsrc = None, None
        v = len_vals.get(i)
        if v is not None:
            if lname:
                fct = cands[lname]
                g0g1 = len_geo.get(i)
                if not g0g1 or 0.85 * g0g1[0] <= v * fct <= 1.08 * g0g1[1]:
                    length_m, lsrc = v * fct, "model length"
            elif len_typed.get(i):
                length_m, lsrc = v * scale, "model length"
        if length_m is None:
            ex = _extruded_length_m(el, scale)
            if ex:
                length_m, lsrc = ex, "extrusion depth"
        if length_m is None and g and g.get("bbox_m"):
            a, b = g["bbox_m"]
            length_m = max(b[j] - a[j] for j in range(3)); lsrc = "bbox-longest-side"
        mat = _find(ps, ("Material", "Rohrsegment", "Materiaal"))
        rows.append({"item_id": i, "kind": kind, "ifc_class": el.is_a(), "name": el.Name, "type_name": (t.Name if t is not None else getattr(el, "ObjectType", None)),
                     "dn_mm": dn, "dn_source": dsrc, "length_m": (round(length_m, 4) if length_m is not None else None), "length_source": lsrc,
                     "system": systems.get(i) or _find(ps, SYS_KEYS), "material": mat if isinstance(mat, str) else None,
                     "storey": (g or {}).get("storey", {}).get("name") if g else _storey(el, UE), "bbox_m": (g or {}).get("bbox_m")})
    return rows, {"length_unit": lname, "length_agree": round(lshare, 2), "dn": {k: v[1] for k, v in dn_ok.items()}}


def extract(doc_id, ifc_path, elements_json=None):
    import ifcopenshell, ifcopenshell.util.element as UE, ifcopenshell.util.unit as UU
    f = ifcopenshell.open(str(ifc_path))
    scale = UU.calculate_unit_scale(f)  # metres per IFC length unit
    geo = {}
    ej = Path(elements_json) if elements_json else ROOT / f"artifacts/{doc_id}/elements.json"
    if ej.exists():
        for e in json.loads(ej.read_text())["elements"]:
            geo[e["item_id"]] = e

    def uniq(classes):  # by_type() includes subclasses (IfcPipeSegment is an IfcFlowSegment): dedupe by GlobalId
        seen = {}
        for c in classes:
            try:
                ents = f.by_type(c)
            except RuntimeError:  # class not in this schema (IFC2X3 has no IfcPipeSegment)
                continue
            for e in ents:
                seen.setdefault(e.GlobalId, e)
        return list(seen.values())
    pipe_els = [e for e in uniq(PIPE_CLASSES) if _is_pipe(e, UE)]
    pipes, calib = build_rows(f, pipe_els, "pipe", geo, scale, UE)
    drains, _ = build_rows(f, uniq(DRAIN_CLASSES), "drain", geo, scale, UE)
    sanitary, _ = build_rows(f, uniq(SAN_CLASSES), "sanitary", geo, scale, UE)
    fit = len(uniq(FITTING_CLASSES))
    res = {"doc_id": doc_id, "schema": f.schema, "ifc_unit_scale_m": scale, "pipes": pipes, "drains": drains, "sanitary_terminals": sanitary, "fittings": fit,
           "rollups": rollups(pipes, drains), "calibration": calib}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{doc_id}.json").write_text(json.dumps(res))
    return res


NOT_PIPE_TYPES = ("IFCDUCTSEGMENTTYPE", "IFCCABLECARRIERSEGMENTTYPE", "IFCCABLESEGMENTTYPE")
NOT_PIPE_WORDS = re.compile(r"\bduct|luftkanal|kanal\b|kabel|cable|tray|conduit|wire|ilmanvaihto|ventilation|supply air|return air|exhaust air", re.I)


def _is_pipe(el, UE) -> bool:
    """IFC2x3 puts ducts, cable trays and pipes all in IfcFlowSegment: the type entity, then the family name, tells them apart."""
    if el.is_a("IfcPipeSegment"):
        return True
    t = UE.get_type(el)
    if t is not None and t.is_a().upper() in NOT_PIPE_TYPES:
        return False
    if t is not None and t.is_a().upper() == "IFCPIPESEGMENTTYPE":
        return True
    return not NOT_PIPE_WORDS.search(f"{el.Name or ''} {getattr(el, 'ObjectType', '') or ''} {(t.Name if t is not None else '') or ''}")


def rollups(pipes, drains):
    def agg(key):
        d = defaultdict(lambda: {"count": 0, "length_m": 0.0, "item_ids": []})
        for p in pipes:
            k = key(p)
            d[k]["count"] += 1; d[k]["length_m"] += p["length_m"] or 0.0; d[k]["item_ids"].append(p["item_id"])
        return {str(k): {**v, "length_m": round(v["length_m"], 2)} for k, v in sorted(d.items(), key=lambda kv: -kv[1]["length_m"])}
    return {"n_pipes": len(pipes), "total_length_m": round(sum(p["length_m"] or 0 for p in pipes), 2), "n_with_dn": sum(p["dn_mm"] is not None for p in pipes),
            "n_with_length": sum(p["length_m"] is not None for p in pipes), "length_sources": {s: sum(p["length_source"] == s for p in pipes) for s in {p["length_source"] for p in pipes}},
            "by_size": agg(lambda p: f"DN{int(p['dn_mm'])}" if p["dn_mm"] else "size not recorded"), "by_system": agg(lambda p: p["system"] or "unknown"),
            "by_storey": agg(lambda p: p["storey"] or "unknown"), "by_type": agg(lambda p: p["type_name"] or "unknown"),
            "drains": [{"item_id": d["item_id"], "type": d["type_name"], "dn_mm": d["dn_mm"], "storey": d["storey"], "bbox_m": d["bbox_m"]} for d in drains]}


def ask(doc_id, q):
    r = json.loads((OUT / f"{doc_id}.json").read_text())["rollups"]; ql = q.lower()
    if re.search(r"drain|waste", ql):
        d = r["drains"]
        return {"text": f"{len(d)} drain/waste terminals: " + "; ".join(f"{x['type']} (DN{int(x['dn_mm']) if x['dn_mm'] else '?'}) on {x['storey']}" for x in d[:12]), "item_ids": [x["item_id"] for x in d]}
    if re.search(r"size|diameter|dn\b", ql):
        s = r["by_size"]
        return {"text": "Pipe sizes: " + ", ".join(f"{k}: {v['count']} pipes / {v['length_m']} m" for k, v in s.items()), "item_ids": [i for v in s.values() for i in v["item_ids"]]}
    if re.search(r"metre|meter|length|how (much|long)", ql):
        key = "by_system" if "system" in ql else "by_storey" if re.search(r"storey|level|floor", ql) else "by_size" if "size" in ql else None
        t = f"Total pipe length: {r['total_length_m']} m over {r['n_pipes']} segments ({r['n_with_length']} with length data; sources {r['length_sources']})."
        if key:
            t += " By " + key[3:] + ": " + ", ".join(f"{k}: {v['length_m']} m" for k, v in r[key].items())
        return {"text": t, "item_ids": [i for v in r["by_size"].values() for i in v["item_ids"]]}
    return {"text": f"{r['n_pipes']} pipe segments; ask about sizes, length or drains.", "item_ids": []}


if __name__ == "__main__":
    if sys.argv[1] == "extract":
        r = extract(sys.argv[2], sys.argv[3]); print(json.dumps({k: v for k, v in r["rollups"].items() if k != "drains"}, indent=1)[:3000]); print("drains", len(r["rollups"]["drains"]))
    else:
        print(json.dumps(ask(sys.argv[2], sys.argv[3]), indent=1)[:1500])
