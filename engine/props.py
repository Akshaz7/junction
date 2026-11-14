"""Source-backed property queries. No geometry, model calls, inferred ratings or rules.

The existing JSON index works without optional IFC dependencies. When the original
is available, lazily read inherited psets/quantities, tags and material associations.
Only small extracted records are cached; never cache an open IFC model. All lengths
are SI, including quantities with explicit units. Plan-map tables use text alignment
and identifiable headers; proximity to a tag alone is never a schedule link.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import re
import time
import unicodedata
import uuid

from engine.solvers.data import Item, load_doc
from engine.solvers.filters import storey_requested
from engine.solvers.solve import resolve_storey
from engine.wording import clean_type_name


def norm(value):
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKD", str(value)).casefold())


ALIASES = {
    "fire_rating": ("FireRating", "fire_rating", "Feuerwiderstand", "Brandschutzklasse", "Paloluokka", "Brandklass"),
    "is_external": ("IsExternal", "is_external", "Außenbauteil", "Ulkoinen", "Utvändig"),
    "thermal_transmittance": ("ThermalTransmittance", "UValue", "U-value", "U-Wert", "Lämmönläpäisykerroin", "U-värde"),
    "acoustic_rating": ("AcousticRating", "SoundReduction", "Schallschutz", "Ääneneristävyys", "Ljudklass"),
    "load_bearing": ("LoadBearing", "load_bearing", "Tragend", "Kantava", "Bärande"),
    "reference": ("Reference", "Mark", "TypeMark", "Tunnus", "Kennzeichen", "Beteckning"),
    "width_m": ("width_m", "Width", "OverallWidth", "Breite", "Leveys", "Bredd"),
    "height_m": ("height_m", "Height", "OverallHeight", "Höhe", "Korkeus", "Höjd"),
    "area_m2": ("area_m2", "NetFloorArea", "GrossFloorArea"),
    "material": ("Material", "Materials", "Baustoff", "Materiaali"),
    "escape_route": ("EscapeRoute", "IsOnEscapeRoute", "IsEscapeRoute", "Fluchtweg", "Poistumisreitti", "Utrymningsväg"),
    "window_count": ("WindowCount", "NumberOfWindows", "Fensteranzahl", "IkkunoidenMaara"),
    "type_name": ("type_name",), "storey": ("storey",),
    "description": ("Description", "Beschreibung", "Kuvaus", "Beskrivning"),
}
KEYS = {norm(alias): key for key, names in ALIASES.items() for alias in names}
KEYS.update({norm(key): key for key in ALIASES})
LABEL = {"fire_rating": "fire rating", "is_external": "external status", "thermal_transmittance": "U-value",
         "acoustic_rating": "acoustic rating", "load_bearing": "load-bearing status", "reference": "reference",
         "width_m": "width", "height_m": "height", "material": "material", "area_m2": "area",
         "escape_route": "escape-route membership", "window_count": "recorded window count", "fire_rated": "fire rating",
         "type_name": "type", "storey": "level", "description": "description"}
MISSING = {"", "-", "?", "n/a", "na", "unknown", "undefined", "not defined", "not set", "unset", "null", "none specified",
           "tbd", "to be determined", "not specified", "not applicable"}
KINDS = {"door": r"doors?|türen?|tür|ovet|ovi|dörr(?:ar)?", "window": r"windows?|fenster|ikkunat?|fönster",
         "wall": r"walls?|wände|wand|seinät?|vägg(?:ar)?", "room": r"rooms?|spaces?|räume|raum|huone(?:et)?|rum",
         "column": r"columns?", "beam": r"beams?", "slab": r"slabs?"}


def clean(value, key):
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, (tuple, list)):
        value = "; ".join(str(v) for v in value if v is not None)
    if value is None or str(value).strip().casefold() in MISSING:
        return None
    if norm(value) in {norm(LABEL[key]), *(norm(x) for x in ALIASES[key])}:
        return None  # Revit sometimes exports the column heading as its value.
    if key in ("is_external", "load_bearing", "escape_route"):
        if isinstance(value, bool):
            return value
        if str(value).strip().casefold() in {"true", "yes", "1", "ja", "kyllä", "oui"}:
            return True
        if str(value).strip().casefold() in {"false", "no", "0", "nein", "ei", "nej"}:
            return False
        return None
    if key in ("width_m", "height_m", "area_m2", "window_count"):
        if isinstance(value, bool):
            return None
        try:
            n = float(value)
            return n if math.isfinite(n) and (n >= 0 if key == "window_count" else n > 0) else None
        except (TypeError, ValueError):
            return None
    return value.strip() if isinstance(value, str) else value


@dataclass
class Record:
    item: Item
    values: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    aliases: set = field(default_factory=set)

    def put(self, key, value, source):
        value = clean(value, key)
        if value is not None:
            self.values[key], self.sources[key] = value, source


def _json(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _source(doc_id, root, meta):
    repo = Path(__file__).resolve().parents[1]
    bases = [Path(os.environ["DATASET_ROOT"])] if os.environ.get("DATASET_ROOT") else []
    bases += [repo, repo / "data/full/junction-dataset", repo / "data/junction-dataset-preview"]
    rel = (meta.get("files") or {}).get("ifc")
    candidates = [root / doc_id / "source.ifc"]
    if rel:
        candidates += [base / rel for base in bases]
        candidates += [root.parent / rel, root / "uploads" / Path(rel).name]
    return next((p for p in candidates if p.is_file()), None)


def _signature(path):
    s = path.stat()
    return str(path.resolve()), s.st_mtime_ns, s.st_size


@lru_cache(maxsize=2)
def _read_ifc(signature):
    """Return serializable property records only; IFC is optional and imported lazily."""
    import ifcopenshell
    import ifcopenshell.util.element as ue
    import ifcopenshell.util.unit as uu

    model = ifcopenshell.open(signature[0])
    length_unit = uu.get_project_unit(model, "LENGTHUNIT")
    def quantity(value, key, prop=None):
        value = clean(value, key)
        if key == "thermal_transmittance" and value is not None and prop is not None and isinstance(value, (int, float)):
            unit = uu.get_property_unit(prop, model)
            # Preserve an explicitly declared derived unit, including imperial
            # units. Never relabel a custom IFC unit as W/(m²·K).
            symbol = uu.get_unit_symbol(unit) if unit is not None else "unit not recorded"
            return f"{value:g} {symbol}"
        if value is None or key not in ("width_m", "height_m", "area_m2"):
            return value
        dim = 2 if key == "area_m2" else 1
        unit = uu.get_property_unit(prop, model) if prop is not None else length_unit
        # A plain IfcReal width still has the project's length unit.
        unit = unit or (uu.get_project_unit(model, "AREAUNIT") if dim == 2 else length_unit)
        if unit is None:
            return None  # Never assume metres when the IFC has no unit assignment.
        name = "SQUARE_METRE" if dim == 2 else "METRE"
        return uu.convert(value, getattr(unit, "Prefix", None), unit.Name, None, name)

    out = {}
    classes = {"IfcDoor": "door", "IfcWindow": "window", "IfcWall": "wall", "IfcSpace": "room",
               "IfcColumn": "column", "IfcBeam": "beam", "IfcSlab": "slab"}
    for cls, kind in classes.items():
        for el in model.by_type(cls):
            values, sources = {}, {}
            def put(key, val, source, prop=None):
                val = quantity(val, key, prop)
                if val is not None:
                    values[key], sources[key] = val, source
            # Some authoring tools emit complex quantities that the library's
            # verbose get_psets cannot unpack. Read psets and Qtos separately.
            ps = ue.get_psets(el, psets_only=True, verbose=True)
            typ = ue.get_type(el)
            definitions = list(getattr(typ, "HasPropertySets", None) or [])
            definitions += [r.RelatingPropertyDefinition for r in getattr(el, "IsDefinedBy", ())
                            if r.is_a("IfcRelDefinesByProperties")]
            def qvalues(quantities):
                result = {}
                for quantity in quantities or []:
                    if quantity.is_a("IfcPhysicalComplexQuantity"):
                        result.update(qvalues(quantity.HasQuantities))
                    else:
                        attr = {"IfcQuantityLength": "LengthValue", "IfcQuantityArea": "AreaValue"}.get(quantity.is_a())
                        if attr:
                            result[quantity.Name] = {"value": getattr(quantity, attr), "id": quantity.id()}
                return result
            for definition in definitions:
                if definition.is_a("IfcElementQuantity"):
                    ps.setdefault(definition.Name, {}).update(qvalues(definition.Quantities))
            candidates = {}
            for pn, props in ps.items():
                if not isinstance(props, dict):
                    continue
                for name, data in props.items():
                    key = KEYS.get(norm(name))
                    if key is None or name == "id":
                        continue
                    prop = model.by_id(data["id"]) if isinstance(data, dict) and data.get("id") else None
                    val = quantity(data, key, prop)
                    if val is not None:
                        candidates.setdefault(key, []).append((val, f"{pn}.{name}", pn == f"Pset_{cls[3:]}Common"))
            conflicts = []
            for key, choices in candidates.items():
                preferred = [c for c in choices if c[2]] or choices
                if len({str(c[0]) for c in preferred}) == 1:
                    values[key], sources[key] = preferred[0][:2]
                else:
                    conflicts.append(key)
            for attr, key in (("OverallWidth", "width_m"), ("OverallHeight", "height_m")):
                val = getattr(el, attr, None)
                if val is not None:
                    put(key, val, f"{cls}.{attr}")
            mats = ue.get_materials(el)
            names = [m.Name for m in mats if getattr(m, "Name", None)]
            if names:
                put("material", "; ".join(names), "material association (including inherited layers)")
            aliases = {str(v) for v in (getattr(el, "Tag", None), getattr(el, "Name", None),
                                       getattr(typ, "Tag", None), getattr(typ, "Name", None), values.get("reference")) if v}
            storey = ue.get_container(el)
            out[el.GlobalId] = dict(values=values, sources=sources, aliases=aliases, kind=kind,
                                   conflicts=conflicts,
                                   name=el.Name, type_name=getattr(typ, "Name", None),
                                   storey=getattr(storey, "Name", None))
    storeys = []
    for s in model.by_type("IfcBuildingStorey"):
        elevation = getattr(s, "Elevation", None)
        if s.Name and elevation is not None and length_unit is not None:
            storeys.append(dict(name=s.Name, elevation_m=uu.convert(float(elevation), getattr(length_unit, "Prefix", None), length_unit.Name, None, "METRE")))
    return out, storeys


def index(doc_id, root):
    root = Path(root)
    doc = load_doc(doc_id, root)
    if doc is not None and doc.mode != "ifc":
        return None
    meta = _json(root / doc_id / "doc.json")
    source = _source(doc_id, root, meta)
    if doc is None and source is None:
        return None
    records = {it.item_id: Record(it, aliases={v for v in (it.name, it.type_name, it.label) if v})
               for it in (doc.items if doc else [])}
    for rec in records.values():
        def collect(obj, prefix):
            if not isinstance(obj, dict):
                return
            for name, value in obj.items():
                key = KEYS.get(norm(name))
                if key:
                    rec.put(key, value, prefix + name)
                elif isinstance(value, dict):
                    collect(value, prefix + name + ".")
        collect(rec.item.props, "index.")
        collect(rec.item.q, "index.")
        rec.aliases.update(str(v) for k, v in rec.item.props.items() if norm(k) in {"tag", "mark", "reference"} and v)
    status = "the stored model index"
    storeys = doc.storeys if doc else []
    if source:
        try:
            raw, raw_storeys = _read_ifc(_signature(source))
            storeys = storeys or raw_storeys
            for iid, data in raw.items():
                if iid not in records:
                    records[iid] = Record(Item(iid, data["kind"], name=data["name"], type_name=data["type_name"], storey=data["storey"], source="ifc"))
                rec = records[iid]
                for key in data["conflicts"]:
                    rec.values.pop(key, None)
                    rec.sources.pop(key, None)
                rec.values.update(data["values"])
                rec.sources.update(data["sources"])
                rec.aliases.update(data["aliases"])
            status = "the original model's properties, quantities, types and materials"
        except (ImportError, OSError, RuntimeError, ValueError, AttributeError, TypeError, KeyError):
            if doc is None:
                return None  # An unreadable source is not an empty model.
            status = "the stored model index; the original model could not be read"
    for rec in records.values():
        if rec.values.get("reference"):
            rec.aliases.add(str(rec.values["reference"]))
        rec.put("type_name", rec.item.type_name, "model type")
        rec.put("storey", rec.item.storey, "model level")
    return list(records.values()), storeys, status


@dataclass
class Request:
    kind: str | None
    prop: str | None
    schedule: bool = False
    group: bool = False
    predicates: list = field(default_factory=list)
    threshold: tuple | None = None
    tag: str | None = None
    special: str | None = None


def request(question):
    q = question.casefold()
    kinds = [(m.start(), k) for k, rx in KINDS.items() if (m := re.search(r"\b(?:" + rx + r")\b", q))]
    kind = min(kinds)[1] if kinds else None
    prop = next((k for k, rx in (
        ("fire_rating", r"fire[ -]rat\w*|fire resistance|feuerwiderstand|paloluokka|brandklass"),
        ("thermal_transmittance", r"u[ -]value|thermal transmittance|u-wert|u-värde"),
        ("acoustic_rating", r"acoustic|sound (?:rating|reduction)|schallschutz"),
        ("material", r"material|made (?:of|from)|baustoff"),
        ("load_bearing", r"load[ -]bearing|tragend|kantava|bärande"),
        ("is_external", r"external|exterior|internal|interior"),
        ("reference", r"\breference\b"),
        ("width_m", r"\bwidth\b|\bwider\b|\bnarrower\b"),
        ("height_m", r"\bheight\b|\btaller\b|\bshorter\b")) if re.search(rx, q)), None)
    schedule = bool(re.search(r"\bschedule\b|türliste|oviluettelo|dörrförteckning|fensterliste", q))
    if re.search(r"\b(?:group|by)\b", q):
        if re.search(r"\bby type\b", q):
            prop = "type_name"
        elif re.search(r"\bby (?:storey|floor|level)\b", q):
            prop = "storey"
    special = "windowless" if kind == "room" and re.search(r"\b(?:no|without) windows?\b|\bwindowless\b", q) else None
    if len(kinds) > 1 and not special:
        return None  # A single-kind property answer must not drop other kinds.
    tag = None
    quoted = re.search(r"\b(?:tag|mark|reference|door|window|wall|room)\s+[\"']([^\"']+)[\"']", question, re.I)
    m = re.search(r"\b(?:tag|mark|reference)\s+[\"']?((?!(?:of|is|the|for|on|by)\b)[\w.-]+)|\b(?:door|window|wall|room)\s+[\"']?([\w.-]*\d[\w.-]*)", question, re.I)
    if quoted:
        tag = quoted[1]
    elif m:
        tag = (m[1] or m[2]).rstrip(".?")
    if not (prop or schedule or special or (tag and re.search(r"refer|mean|what|describe", q))):
        return None
    if not kind and not tag:
        return None
    # Existing quantity/spatial solvers must retain their full question. A
    # property filter cannot silently replace a length, take-off or comparison.
    if re.search(r"\b(?:total length|total area|(?:net |gross |floor |wall )?area|net|gross|volume|perimeter|waste|cost|price|percentage|proportion|ratio|share|near|nearest|adjacent|distance|between|except|excluding|or|thick\w*|narrowest|widest|tallest|shortest|greatest|smallest|largest|requirement\w*|accessib\w*|complian\w*|regulation\w*|meets?|standards?|compare|energy|savings?|g[ -]values?|connect\w*|beside|through)\b", q):
        return None
    if re.search(r"\b(?:and|from)\b.*\b(?:floor|level|storey|story)\b", q) or re.search(r"\band\s+(?:what|how|which|are|is|do|does)\b", q):
        return None
    if re.search(r"\b(?:material|fire[ -]rating|acoustic[ -]rating)\s+(?:of|is|equals?)\s+(?!the\b|a\b|an\b|door\b|doors\b|wall\b|walls\b|window\b|windows\b|room\b|rooms\b|tag\b|mark\b|reference\b)[\w\"']", q):
        return None  # Value comparisons need an explicit, separate value parser.
    if re.search(r"\b(?:has|have|with)\s+(?:a\s+)?material\s+\S", q):
        return None
    if re.search(r"\b(?:widths?|heights?|materials?|ratings?|u[ -]values?)\s+and\s+(?:widths?|heights?|materials?|(?:fire |acoustic )?ratings?|u[ -]values?)\b", q):
        return None
    predicates = []
    for key, rx, positive in (("is_external", r"\bexternal\b|\bexterior\b", True),
                              ("is_external", r"\binternal\b|\binterior\b", False),
                              ("load_bearing", r"\bload[ -]bearing\b", True),
                              ("escape_route", r"\bescape route\b|\begress route\b", True)):
        if re.search(rx, q) and (key != prop or re.search(r"\bwhich\b|\bhow many\b|\ball\b|\blist\b|\bschedule\b", q)):
            negative = re.search(r"\b(?:not|non)[ -]+(?:" + rx.replace(r"\b", "") + r")", q)
            predicates.append((key, not positive if negative else positive))
    if prop == "fire_rating" and re.search(r"\b(?:which|how many|list)\b", q) and re.search(r"\bfire[ -]rated\b", q):
        predicates.append(("fire_rated", not bool(re.search(r"\b(?:not|non)[ -]?fire[ -]rated\b", q))))
    threshold = None
    measurements = list(re.finditer(r"\b(wider than|narrower than|taller than|shorter than|at least|at most|over|under|more than|less than)\s*(\d+(?:[.,]\d+)?)\s*(mm|cm|metres?|meters?|m|feet|foot|ft|inches|inch|in|\")(?=\W|$)", q))
    if len(measurements) > 1:
        return None  # Existing multi-condition route can keep every inequality.
    m = measurements[0] if measurements else None
    if not m and re.search(r"\b(?:wider|narrower|taller|shorter) than\b", q):
        return None
    if m:
        key = "height_m" if re.search(r"height|tall|short", q) else "width_m"
        unit = m[3]
        scale = .001 if unit == "mm" else .01 if unit == "cm" else .3048 if unit in ("feet", "foot", "ft") else .0254 if unit in ("inch", "inches", "in", '"') else 1
        threshold = key, m[1], float(m[2].replace(",", ".")) * scale
    return Request(kind, prop, schedule, bool(re.search(r"\bgroup|\bby (?:type|material|fire|acoustic|reference|storey|floor|level)", q)), predicates, threshold, tag, special)


def _rated(value):
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return bool(value)
    return str(value).casefold().strip() not in {"0", "false", "no", "none", "not rated", "unrated", "not fire rated"}


def display(value, key):
    if value is None:
        return "Not recorded"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if key in ("width_m", "height_m"):
        return f"{value * 1000:g} mm"
    if key == "area_m2":
        return f"{value:g} m²"
    if key == "thermal_transmittance" and isinstance(value, (int, float)):
        return f"{value:g} W/(m²·K)"
    return str(value)


def _cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _name(rec):
    # Source names/marks are useful; internal GUIDs are only for citations.
    name = rec.values.get("reference") or rec.item.name or rec.item.label
    if not name or name == rec.item.item_id or re.fullmatch(r"[0-9A-Za-z_$]{22}", str(name)):
        return rec.item.kind.capitalize()
    return clean_type_name(str(name), with_mm=False)


def _table(headers, rows):
    return "\n\n| " + " | ".join(headers) + " |\n|" + "---|" * len(headers) + "\n" + "\n".join("| " + " | ".join(_cell(c) for c in row) + " |" for row in rows)


def _result(question, doc_id, records, text, checked, total, root, t0, *, value=None, complete=True, source="model data", extra=None):
    citations, boxes = [], []
    for rec in records:
        it = rec.item
        quote = "; ".join(f"{rec.sources.get(k, LABEL[k])}: {display(v, k)}" for k, v in rec.values.items()) or "No requested property recorded"
        n = len(citations) + 1
        citations.append(dict(n=n, doc_id=doc_id, page=it.page, kind="element", bbox_px=it.bbox_px, item_ids=[it.item_id], quote=quote))
        if it.bbox_px:
            boxes.append(dict(item_id=it.item_id, page=it.page, bbox_px=it.bbox_px, label=str(n), kind=it.kind))
    ids = [r.item.item_id for r in records]
    text += " " + " ".join(f"[{n}]" for n in range(1, min(len(citations), 3) + 1))
    checked_text = f"Requested property present on {checked} of {total} elements; checked {source}."
    reasoning = dict(steps=[dict(kind="found", title="Found", text=f"{len(records)} cited model elements; {total} elements in the checked scope", cite=1 if citations else None, ok=None),
                            dict(kind="checked", title="Checked", text=checked_text, cite=1 if citations else None, ok=complete)],
                     confidence=dict(label="Verified" if complete else "Estimate", pct=100 if complete else 0,
                                     reason="Read directly from the recorded model data." if complete else "Some requested data or scope is missing; no value was inferred.",
                                     improve=None if complete else "Check the missing properties in the source model."))
    return dict(answer_id=uuid.uuid4().hex, question=question, doc_ids=[doc_id],
                answer=dict(text_md=text.rstrip(), value=value, unit="count" if isinstance(value, int) and not isinstance(value, bool) else None,
                            confidence=1.0 if complete else 0.0, abstained=False),
                citations=citations, evidence=dict(boxes=boxes, scene=dict(doc_id=doc_id, highlight_item_ids=ids, camera_target_item_id=ids[0] if ids else None)),
                trace=[dict(step="props", detail=checked_text, ms=0, model=None, cost_usd=0)],
                reasoning=reasoning, route="index", cost=dict(usd_total=0.0, calls=[]), latency_ms=int((time.perf_counter()-t0)*1000))


def _model_answer(question, doc_id, root, req, t0, hidden=()):
    loaded = index(doc_id, root)
    if loaded is None:
        return None
    records, storeys, source = loaded
    hidden = set(hidden or ())
    records = [r for r in records if r.item.item_id not in hidden]
    scope = [r for r in records if not req.kind or r.item.kind == req.kind]
    noun = (req.kind + "s") if req.kind else "elements"
    if req.tag:
        scope = [r for r in scope if any(norm(req.tag) == norm(a) for a in r.aliases)]
        if not scope:
            return _result(question, doc_id, [], f"**No {req.kind or 'element'} matches that tag, name or reference.**", 0, 0, root, t0, complete=False, source=source)
    st = resolve_storey(question, storeys)
    named_levels = [s for s in storeys if re.search(r"(?<!\w)" + re.escape(s["name"]) + r"(?!\w)", question, re.I)]
    if len(named_levels) > 1:
        return None  # Let the multi-scope route keep all requested levels.
    if storey_requested(question) and st is None:
        return _result(question, doc_id, [], "**No matching level is recorded in this model.**", 0, 0, root, t0, complete=False, source=source)
    if st:
        scope = [r for r in scope if r.item.storey == st]
    original = list(scope)
    if not scope:
        return _result(question, doc_id, [], f"**No {noun} are recorded in the requested scope.**", 0, 0, root, t0, source=source)
    missing_filters = Counter()
    filters = list(req.predicates)
    selected = []
    for r in scope:
        unknown, reject = False, False
        for key, expected in filters:
            v = _rated(r.values.get("fire_rating")) if key == "fire_rated" else r.values.get(key)
            if v is None:
                missing_filters[key] += 1
                unknown = True
            elif v != expected:
                reject = True
        if req.threshold:
            key, op, bound = req.threshold
            v = r.values.get(key)
            if v is None:
                missing_filters[key] += 1
                unknown = True
            else:
                # IFC floating conversion noise must not turn equality into 'wider than'.
                equal = math.isclose(v, bound, rel_tol=1e-9, abs_tol=1e-9)
                match = (v >= bound or equal) if op == "at least" else (v <= bound or equal) if op == "at most" else (v < bound and not equal) if op in ("under", "less than", "narrower than", "shorter than") else (v > bound and not equal)
                reject |= not match
        if not reject and not unknown:
            selected.append(r)
    scope = selected
    complete = not missing_filters
    suffix = ""
    if missing_filters:
        suffix = "\n\nCannot classify all elements: " + "; ".join(f"{n} lack {LABEL[k]}" for k, n in missing_filters.items()) + "."
        if not scope:
            return _result(question, doc_id, original, f"**This model does not record enough properties to apply every requested filter.**" + suffix,
                           0, len(original), root, t0, complete=False, source=source)
    elif not scope:
        return _result(question, doc_id, original, f"**No {noun} match the recorded filters.**", len(original), len(original), root, t0,
                       value=0, source=source)
    prop = req.prop
    if req.special == "windowless":
        prop = "window_count"
        known = [r for r in scope if prop in r.values]
        if len(known) != len(scope):
            text = "**This model does not record a complete room-to-window relationship.** I cannot identify rooms with no window from proximity alone."
            return _result(question, doc_id, scope, text, len(known), len(scope), root, t0, complete=False, source=source)
        scope = [r for r in known if r.values[prop] == 0]
        return _result(question, doc_id, scope or original, f"**{len(scope)} rooms have a recorded window count of zero.**", len(known), len(known), root, t0, value=len(scope), source=source)
    if req.schedule:
        keys = ["reference", "width_m", "height_m", "fire_rating", "material"] if req.kind == "door" else ["reference", "width_m", "height_m", "thermal_transmittance", "material"] if req.kind == "window" else ["reference", "area_m2"]
        rows = [[f"{_name(r)} [{n}]", r.item.storey or "Not recorded", *(display(r.values.get(k), k) for k in keys)] for n, r in enumerate(scope[:15], 1)]
        text = f"**{len(scope)} {noun} in the requested schedule.**" + _table(["Element", "Level", *(LABEL[k].capitalize() for k in keys)], rows)
        if len(scope) > 15:
            text += f"\n\nand {len(scope)-15} more."
        text += "\n\nNot recorded means the field is missing; it is not a zero or a failed check."
        checked = sum(all(k in r.values for k in keys) for r in scope)
        complete &= checked == len(scope)
        suffix += "\n\nField coverage: " + "; ".join(f"{LABEL[k]} {sum(k in r.values for r in scope)} of {len(scope)}" for k in keys) + "."
    elif prop:
        known = [r for r in scope if prop in r.values]
        checked = len(known)
        complete &= len(known) == len(scope)
        if not known:
            plural = {"fire_rating": "fire ratings", "thermal_transmittance": "U-values", "acoustic_rating": "acoustic ratings"}.get(prop, LABEL[prop])
            text = f"**This model does not record {plural} for {noun}.**"
        elif req.group:
            groups = Counter(display(r.values.get(prop), prop) for r in scope)
            text = f"**{len(scope)} {noun}, grouped by {LABEL[prop]}.**" + _table([LABEL[prop].capitalize(), "Elements"], list(groups.items())[:15])
            if len(groups) > 15:
                text += f"\n\nand {len(groups)-15} more groups."
        else:
            counts = Counter(display(r.values[prop], prop) for r in known)
            summary = "; ".join(f"{v} ({n} {noun})" for v, n in list(counts.items())[:4])
            text = f"**Recorded {LABEL[prop]}: {summary}.**"
            if len(counts) > 4:
                text += f" {len(counts)-4} additional values are recorded."
            # Listing/filtering is element-specific, with at most 15 visible rows.
            if (len(scope) > 1 and re.search(r"\bwhich\b|\blist\b|\ball\b", question, re.I)) or req.threshold or filters:
                text = f"**{len(scope)} {noun} match the recorded filters.**" + _table(["Element", "Level", LABEL[prop].capitalize()], [[f"{_name(r)} [{n}]", r.item.storey or "Not recorded", display(r.values.get(prop), prop)] for n, r in enumerate(scope[:15], 1)])
                if len(scope) > 15:
                    text += f"\n\nand {len(scope)-15} more."
        if known and len(known) != len(scope):
            text += f"\n\n{len(scope)-len(known)} of {len(scope)} {noun} have no recorded {LABEL[prop]}."
    else:
        checked = len(scope)
        text = f"**{len(scope)} {noun} match that tag, name or reference.**" + _table(["Element", "Type", "Level"], [[_name(r), clean_type_name(r.item.type_name or "Not recorded"), r.item.storey or "Not recorded"] for r in scope[:15]])
    if re.search(r"\ball\b", question, re.I) and prop == "fire_rating" and not req.schedule:
        # A nonempty property is not necessarily a fire classification (e.g. 'Not rated').
        unrated = [r for r in scope if _rated(r.values.get(prop)) is False]
        if complete and not unrated:
            text = "**All selected doors have a recorded fire-rating value.** This checks recorded values only, not compliance with a fire-safety rule." + _table(["Element", "Fire rating"], [[_name(r), display(r.values.get(prop), prop)] for r in scope[:15]])
        else:
            text = "**I cannot confirm that all selected doors are fire-rated.** " + f"{checked} of {len(scope)} have a recorded value; {len(unrated)} explicitly report no rating. Missing values are unknown."
    # A zero match is proven by citing the population that was checked.
    evidence = scope or original
    required = {"fire_rating" if k == "fire_rated" else k for k, _ in filters}
    if prop:
        required.add(prop)
    if req.threshold:
        required.add(req.threshold[0])
    if req.schedule:
        required.update(keys)
    coverage = sum(all(k in r.values for k in required) for r in original) if required else checked
    return _result(question, doc_id, evidence, text + suffix, coverage, len(original), root, t0,
                   value=len(scope) if req.threshold or req.schedule or filters else None, complete=complete, source=source)


def _rows(items):
    """Cluster horizontal text lines with tolerance proportional to glyph height."""
    rows = []
    for it in sorted(items, key=lambda i: ((i.bbox_px[1]+i.bbox_px[3])/2, i.bbox_px[0])):
        bb = it.bbox_px
        cy, height = (bb[1]+bb[3])/2, max(bb[3]-bb[1], 1)
        row = next((r for r in rows if abs(r[0]-cy) <= min(r[1], height)*.5), None)
        if row is None:
            rows.append([cy, height, [it]])
        else:
            row[2].append(it)
    return [sorted(r[2], key=lambda i: i.bbox_px[0]) for r in rows]


def _header_key(text):
    return KEYS.get(norm(text)) or KEYS.get(norm(re.sub(r"\s*\((?:mm|cm|m|in|ft|dB)\)\s*$", "", text, flags=re.I)))


def _aligned(cell, heading):
    a, b = cell.bbox_px, heading.bbox_px
    height = max(a[3]-a[1], b[3]-b[1])
    return min(abs(a[0]-b[0]), abs((a[0]+a[2]-b[0]-b[2])/2)) <= height


def _drawing_answer(question, doc_id, root, req, t0):
    if not req.tag:
        return None  # A schedule-wide aggregate requires a complete table parser.
    doc = load_doc(doc_id, root)
    if doc is None or doc.mode != "planmap":
        return None
    texts = [i for i in doc.items if i.kind == "text" and i.label and i.bbox_px]
    matches = []
    for page in sorted({i.page for i in texts}):
        rows = _rows([i for i in texts if i.page == page])
        for ri, row in enumerate(rows):
            marks = [it for it in row if norm(it.label) == norm(req.tag)]
            if not marks:
                continue
            # Identify a header row with a mark column and at least one property.
            header = None
            for above in reversed(rows[:ri]):
                keys = [_header_key(it.label) for it in above]
                identity = [it for it in above if norm(it.label) in {"tag", "mark", "reference", "tunnus", "kennzeichen", "beteckning", "id", "type"}]
                has_id = len(identity) == 1 and _aligned(marks[0], identity[0])
                if has_id and any(k and k != "reference" for k in keys):
                    if len([k for k in keys if k]) != len({k for k in keys if k}):
                        continue
                    header = above
                    break
            if header is None or len(marks) != 1:
                continue
            values = {}
            for cell in row:
                if cell in marks:
                    continue
                # Column assignment from the header's left edge, verified by the
                # cell centre. Text outside all column ranges is ignored.
                aligned = [h for h in header if _aligned(cell, h)]
                if len(aligned) == 1:
                    key = _header_key(aligned[0].label)
                    if key and key != "reference":
                        values.setdefault(key, []).append(cell)
            if values:
                matches.append((row, header, marks[0], values))
    if not matches:
        return None
    if len(matches) != 1:
        return _result(question, doc_id, [], "**That tag has more than one possible schedule row.** Select one sheet or specify the schedule.", 0, len(matches), root, t0, complete=False, source="drawing text")
    row, header, mark, values = matches[0]
    prop = req.prop
    selected = values.get(prop) if prop else [i for cells in values.values() for i in cells]
    if not selected:
        selected = []
        text = f"**The schedule does not record {LABEL.get(prop, 'that property')} for {req.tag}.**"
    else:
        text = f"**{req.tag}: " + (LABEL[prop] + " = " if prop else "") + "; ".join(i.label for i in selected) + ".**"
    # Plan occurrence(s), header and entire row are all independently checkable.
    occurrences = [i for i in texts if norm(i.label) == norm(req.tag) and i is not mark]
    groups = [([i], i.label) for i in occurrences] + [(header, " | ".join(i.label for i in header)), (row, " | ".join(i.label for i in row))]
    citations, boxes = [], []
    for group, quote in groups:
        bb = [min(i.bbox_px[0] for i in group), min(i.bbox_px[1] for i in group), max(i.bbox_px[2] for i in group), max(i.bbox_px[3] for i in group)]
        n = len(citations)+1
        citations.append(dict(n=n, doc_id=doc_id, page=group[0].page, kind="text", bbox_px=bb, item_ids=[i.item_id for i in group], quote=quote))
        boxes.append(dict(item_id=group[0].item_id, page=group[0].page, bbox_px=bb, label=str(n), kind="text"))
    exact = all(i.source in {"dxf", "ifc"} for i in [*row, *header, *occurrences])
    confidence = min((i.conf for i in [*row, *header, *occurrences]), default=0)
    out = _result(question, doc_id, [], text, int(bool(selected)), 1, root, t0, complete=exact and bool(selected), source="aligned schedule text")
    out["answer"].update(text_md=text+" "+" ".join(f"[{c['n']}]" for c in citations), confidence=(1 if exact else confidence) if selected else 0)
    out["citations"], out["evidence"]["boxes"] = citations, boxes
    out["reasoning"]["steps"] = [dict(kind="found", title="Found", text=f"{len(occurrences)} plan tags and one aligned schedule row", cite=len(citations), ok=None),
                                  dict(kind="checked", title="Checked", text=f"Requested field present on {int(bool(selected))} of 1 schedule rows; exact tag match.", cite=len(citations), ok=bool(selected))]
    if not exact:
        out["reasoning"]["confidence"] = dict(label="Estimate", pct=round(confidence*100) if selected else 0, reason="Read from OCR text; check the tag and schedule boxes." if selected else "The requested schedule field is not recorded.", improve="Check the printed row against the scan.")
    out["trace"] = [dict(step="props", detail="tag -> aligned text schedule; tag, header and row cited", ms=0, model=None, cost_usd=0)]
    return out


def answer(question, doc_ids, root, t0=None, *, hidden=None):
    """None means this route does not handle the question, never a guessed answer."""
    req = request(question)
    if req is None or len(doc_ids) != 1:
        return None
    t0 = t0 or time.perf_counter()
    try:
        result = _model_answer(question, doc_ids[0], Path(root), req, t0, hidden)
        if result is not None and hidden:
            result["answer"]["text_md"] += "\n\nElements hidden in this chat are excluded; source properties are unchanged."
        return result if result is not None else _drawing_answer(question, doc_ids[0], Path(root), req, t0)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None  # malformed/partial ingest still has the ordinary reader fallback


