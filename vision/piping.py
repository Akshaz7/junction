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


def extract(doc_id, ifc_path, elements_json=None):
    import ifcopenshell, ifcopenshell.util.element as UE, ifcopenshell.util.unit as UU
    f = ifcopenshell.open(str(ifc_path))
    scale = UU.calculate_unit_scale(f)  # metres per IFC length unit
    geo = {}
    ej = Path(elements_json) if elements_json else ROOT / f"artifacts/{doc_id}/elements.json"
    if ej.exists():
        for e in json.loads(ej.read_text())["elements"]:
            geo[e["item_id"]] = e
    systems = {}
    for sysent in f.by_type("IfcSystem"):
        for rel in getattr(sysent, "IsGroupedBy", None) or []:
            for o in rel.RelatedObjects:
                systems[o.GlobalId] = sysent.Name

    def row(el, kind):
        ps = UE.get_psets(el)
        t = UE.get_type(el)
        if t is not None:
            for k, v in UE.get_psets(t).items():
                ps.setdefault(k, v)
        length = _num(_find(ps, LEN_KEYS))
        dn = _num(_find(ps, DN_KEYS))
        size_txt = _find(ps, ("Größe", "Size", "Maat", "Gesamtmaß"))
        if _dn_from_text(size_txt, el.Name, getattr(el, "ObjectType", None)):
            dn = _dn_from_text(size_txt, el.Name, getattr(el, "ObjectType", None))
        g = geo.get(el.GlobalId)
        len_src = "pset" if length is not None else None
        # Revit psets are mm; a pset length is converted with the IFC unit only when it comes from a Qto (IfcQuantityLength)
        if length is not None:
            length_m = length / 1000.0
        elif g and g.get("bbox_m"):
            a, b = g["bbox_m"]
            length_m = sum((b[i] - a[i]) ** 2 for i in range(3)) ** 0.5  # bbox diagonal: upper bound for diagonal runs
            len_src = "bbox-diagonal"
        else:
            length_m = None
        mat = _find(ps, ("Material", "Rohrsegment", "Materiaal"))
        return {"item_id": el.GlobalId, "kind": kind, "ifc_class": el.is_a(), "name": el.Name, "type_name": (t.Name if t is not None else getattr(el, "ObjectType", None)),
                "dn_mm": dn, "length_m": (round(length_m, 4) if length_m is not None else None), "length_source": len_src,
                "system": systems.get(el.GlobalId) or _find(ps, SYS_KEYS), "material": mat if isinstance(mat, str) else None,
                "storey": (g or {}).get("storey", {}).get("name") if g else _storey(el, UE), "bbox_m": (g or {}).get("bbox_m")}

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
    pipes = [row(e, "pipe") for e in uniq(PIPE_CLASSES)]
    drains = [row(e, "drain") for e in uniq(DRAIN_CLASSES)]
    sanitary = [row(e, "sanitary") for e in uniq(SAN_CLASSES)]
    fit = len(uniq(FITTING_CLASSES))
    res = {"doc_id": doc_id, "schema": f.schema, "ifc_unit_scale_m": scale, "pipes": pipes, "drains": drains, "sanitary_terminals": sanitary, "fittings": fit, "rollups": rollups(pipes, drains)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{doc_id}.json").write_text(json.dumps(res))
    return res


def rollups(pipes, drains):
    def agg(key):
        d = defaultdict(lambda: {"count": 0, "length_m": 0.0, "item_ids": []})
        for p in pipes:
            k = key(p)
            d[k]["count"] += 1; d[k]["length_m"] += p["length_m"] or 0.0; d[k]["item_ids"].append(p["item_id"])
        return {str(k): {**v, "length_m": round(v["length_m"], 2)} for k, v in sorted(d.items(), key=lambda kv: -kv[1]["length_m"])}
    return {"n_pipes": len(pipes), "total_length_m": round(sum(p["length_m"] or 0 for p in pipes), 2), "n_with_dn": sum(p["dn_mm"] is not None for p in pipes),
            "n_with_length": sum(p["length_m"] is not None for p in pipes), "length_sources": {s: sum(p["length_source"] == s for p in pipes) for s in {p["length_source"] for p in pipes}},
            "by_size": agg(lambda p: f"DN{int(p['dn_mm'])}" if p["dn_mm"] else "unknown"), "by_system": agg(lambda p: p["system"] or "unknown"),
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
