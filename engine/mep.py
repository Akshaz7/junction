"""F-MEP: building services (pipes, ducts, cables, fixtures, equipment) and structure (columns, beams, footings, ...) answered by code, $0, no model.

  build(doc_id, ifc_path)  ->  artifacts/<doc>/mep.json   one row per distribution / structural element: kind, system, type, storey, size, length, material
  answer(question, doc, t0) -> an answer object, or None when the question is not about services or structure (the existing routes then run unchanged)

General by construction: every IFC schema (2x3 / 4 / 4x3), any authoring tool, labels in English, Finnish, German, Swedish, Dutch, metric and imperial.
Units are never assumed: sizes and lengths are checked against the element's own 3D shape (vision/piping.py: resolve_numeric); a value that agrees with
nothing is reported as "not recorded", never guessed.  Nothing here knows a file name, a storey name or a count.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEP_VERSION = 2

# ------------------------------------------------------------------ vocabulary: IFC class -> plain kind
# kind -> (singular, plural)
KIND_WORDS = {
    "pipe": ("pipe", "pipes"), "pipe_fitting": ("pipe fitting", "pipe fittings"), "duct": ("duct", "ducts"), "duct_fitting": ("duct fitting", "duct fittings"),
    "cable_tray": ("cable tray", "cable trays"), "cable_fitting": ("cable tray fitting", "cable tray fittings"), "cable": ("cable", "cables"),
    "conduit": ("conduit", "conduits"), "valve": ("valve or control", "valves and controls"), "pump": ("pump", "pumps"), "fan": ("fan", "fans"),
    "radiator": ("radiator or heater", "radiators and heaters"), "boiler": ("boiler or heat source", "boilers and heat sources"), "chiller": ("chiller or cooling unit", "chillers and cooling units"),
    "air_handler": ("air handling unit", "air handling units"), "air_terminal": ("air terminal (diffuser or grille)", "air terminals (diffusers and grilles)"),
    "damper": ("damper", "dampers"), "filter": ("filter", "filters"), "tank": ("tank", "tanks"), "heat_exchanger": ("heat exchanger", "heat exchangers"),
    "light": ("light fitting", "light fittings"), "socket": ("socket or outlet", "sockets and outlets"), "switch": ("switch", "switches"),
    "board": ("distribution board", "distribution boards"), "transformer": ("transformer", "transformers"), "sprinkler": ("sprinkler", "sprinklers"),
    "toilet": ("toilet", "toilets"), "basin": ("washbasin or sink", "washbasins and sinks"), "shower": ("shower", "showers"), "bath": ("bathtub", "bathtubs"),
    "fixture": ("plumbing fixture", "plumbing fixtures"), "drain": ("drain", "drains"), "sensor": ("sensor or detector", "sensors and detectors"),
    "alarm": ("alarm device", "alarm devices"), "control": ("control device", "control devices"), "device": ("other service device", "other service devices"),
    "terminal": ("terminal", "terminals"), "segment": ("pipe, duct or cable run", "pipe, duct or cable runs"), "fitting": ("fitting", "fittings"),
    "column": ("column", "columns"), "beam": ("beam", "beams"), "member": ("structural member", "structural members"), "footing": ("footing", "footings"),
    "pile": ("pile", "piles"), "rebar": ("reinforcement bar", "reinforcement bars"), "slab": ("slab", "slabs"), "wall": ("wall", "walls"),
}
LINEAR = {"pipe", "duct", "cable_tray", "cable", "conduit", "segment"}
STRUCT_KINDS = {"column", "beam", "member", "footing", "pile", "rebar"}

CLASS_KIND = {
    "IfcPipeSegment": "pipe", "IfcPipeFitting": "pipe_fitting", "IfcDuctSegment": "duct", "IfcDuctFitting": "duct_fitting", "IfcDuctSilencer": "duct_fitting",
    "IfcCableCarrierSegment": "cable_tray", "IfcCableCarrierFitting": "cable_fitting", "IfcCableSegment": "cable", "IfcCableFitting": "cable_fitting",
    "IfcValve": "valve", "IfcPump": "pump", "IfcFan": "fan", "IfcCompressor": "pump", "IfcSpaceHeater": "radiator", "IfcBoiler": "boiler", "IfcChiller": "chiller",
    "IfcCoolingTower": "chiller", "IfcHeatExchanger": "heat_exchanger", "IfcCoil": "heat_exchanger", "IfcUnitaryEquipment": "air_handler", "IfcAirToAirHeatRecovery": "air_handler",
    "IfcAirTerminal": "air_terminal", "IfcAirTerminalBox": "air_terminal", "IfcDamper": "damper", "IfcFilter": "filter", "IfcTank": "tank", "IfcFlowMeter": "valve",
    "IfcLightFixture": "light", "IfcLamp": "light", "IfcOutlet": "socket", "IfcSwitchingDevice": "switch", "IfcElectricDistributionBoard": "board",
    "IfcElectricDistributionPoint": "board", "IfcTransformer": "transformer", "IfcFireSuppressionTerminal": "sprinkler", "IfcWasteTerminal": "drain",
    "IfcStackTerminal": "drain", "IfcAlarm": "alarm", "IfcSensor": "sensor", "IfcActuator": "control", "IfcController": "control", "IfcProtectiveDevice": "control",
    "IfcJunctionBox": "cable_fitting", "IfcFlowInstrument": "sensor", "IfcUnitaryControlElement": "control", "IfcMotorConnection": "device", "IfcElectricMotor": "device",
    "IfcElectricGenerator": "device", "IfcElectricAppliance": "device", "IfcElectricFlowStorageDevice": "device", "IfcCommunicationsAppliance": "device",
    "IfcAudioVisualAppliance": "device", "IfcInterceptor": "filter", "IfcDistributionChamberElement": "device", "IfcEvaporativeCooler": "chiller", "IfcEvaporator": "chiller",
    "IfcCondenser": "chiller", "IfcHumidifier": "air_handler", "IfcBurner": "boiler", "IfcEngine": "device", "IfcMedicalDevice": "device", "IfcSolarDevice": "device",
    "IfcSanitaryTerminal": "fixture", "IfcFlowTerminal": None, "IfcFlowFitting": None, "IfcFlowSegment": None, "IfcFlowController": None, "IfcFlowMovingDevice": None,
    "IfcFlowStorageDevice": None, "IfcFlowTreatmentDevice": None, "IfcEnergyConversionDevice": None, "IfcDistributionControlElement": None,
    "IfcDistributionFlowElement": None, "IfcDistributionElement": None,
}
GENERIC_BY_CLASS = {"IfcFlowFitting": "fitting", "IfcFlowSegment": "segment", "IfcFlowController": "valve", "IfcFlowMovingDevice": "pump", "IfcFlowStorageDevice": "tank",
                    "IfcFlowTreatmentDevice": "filter", "IfcEnergyConversionDevice": "device", "IfcDistributionControlElement": "control", "IfcFlowTerminal": "terminal",
                    "IfcDistributionFlowElement": "device", "IfcDistributionElement": "device"}
# words in a name / type / family decide a generic class (IFC2x3 exports almost everything as IfcFlowTerminal / IfcFlowController ...)
KEYWORD_KIND = [
    (r"sprinkl", "sprinkler"), (r"\bwc\b|toilet|water closet|urinal|\bwc-|klosett|\bwc_", "toilet"), (r"wash ?basin|\bsink\b|lavatory|basin|waschtisch|waschbecken|pesuallas|handfat|wastafel|tiskiallas|spüle|diskho", "basin"),
    (r"shower|dusche|suihku|dusch|douche", "shower"), (r"bath ?tub|\bbath\b|badewanne|kylpyamme|badkar|\bbad\b", "bath"), (r"floor drain|\bdrain\b|gully|bodenablauf|lattiakaivo|rainwater outlet|afvoer", "drain"),
    (r"luminaire|light fix|lighting|\blight\b|\blamp|leuchte|valaisin|belysning|armatuur|downlight|spotlight|fluorescent|\bled\b", "light"),
    (r"socket|outlet|receptacle|steckdose|pistorasia|stikkontakt|stopcontact|power point", "socket"), (r"\bswitch|schalter|kytkin|strömbrytare|schakelaar|dimmer", "switch"),
    (r"distribution board|switchboard|panelboard|electrical panel|verteiler|keskus|schaltschrank|elcentral|groepenkast|switchgear", "board"),
    (r"\bvalve|ventiil|\bventil\b|absperr|kugelhahn|afsluiter|\bcock\b|\bhahn\b|\bfaucet|\btap\b|\bmixer\b|armatur", "valve"),
    (r"\bpump|pumpe|pumppu|\bpomp\b", "pump"), (r"\bfan\b|ventilator|puhallin|fläkt|\bblower", "fan"), (r"radiator|heizk[oö]rper|patteri|konvektor|convector|panel radiator|\bheater", "radiator"),
    (r"diffuser|grille|\bgrill\b|luftdurchlass|tuloilma|poistoilma|supply air terminal|air terminal|anemostat|\bregister\b|louver|louvre", "air_terminal"),
    (r"\bdamper|klappe|peltti|spjäll", "damper"), (r"filter", "filter"),
    (r"boiler|heat pump|w[äa]rmepumpe|kessel|kattila|lämpöpumppu|furnace", "boiler"), (r"chiller|k[äa]lte(?:maschine|anlage)|cooling unit|fan coil|fancoil|cooling tower", "chiller"),
    (r"air handling|\bahu\b|lüftungsger|ilmanvaihtokone|rooftop unit|\brtu\b", "air_handler"),
    (r"smoke detect|detector|sensor|thermostat|melder|detektor|anturi|\bstat\b", "sensor"), (r"alarm|sounder|horn|strobe|siren", "alarm"),
    (r"\btank\b|cylinder|storage|expansion vessel|accumulator|boiler tank", "tank"), (r"heat exchanger|w[äa]rme[üu]bertrager|lämmönsiirrin|coil", "heat_exchanger"),
    (r"transformer|trafo|muuntaja", "transformer"),
]
STRUCT_CLASS_KIND = {"IfcSlab": "slab", "IfcWall": "wall", "IfcColumn": "column", "IfcBeam": "beam", "IfcMember": "member", "IfcFooting": "footing", "IfcPile": "pile", "IfcReinforcingBar": "rebar",
                     "IfcReinforcingMesh": "rebar", "IfcTendon": "rebar", "IfcTendonAnchor": "rebar"}
AMBIGUOUS_FIXTURES = {"toilet", "basin", "shower", "bath", "drain", "fixture"}
SERVICE_DOMAINS = ("plumbing", "heating", "cooling", "ventilation", "fire protection", "gas", "electrical", "controls and alarms")

# ------------------------------------------------------------------ systems: words in a system / type name -> plain system kind
SYSTEM_KINDS = [
    (r"sprinkl|fire|brand|palo|sammut|l[öo]schen|loesch|suppression|hydrant|riser fire|\bfp\b", "fire protection"),
    (r"storm|rain|regenwasser|hemelwater|sadevesi|dagvatten|niederschlag|\bvwa\b|\bhwa\b|\brw\b|\bsrw\b", "rainwater"),
    (r"sanitary|waste|sewage|sewer|soil|schmutz|abwasser|avlopp|viem[äa]ri|j[äa]tevesi|afvoer|riool|fekal|drain|\bsw\b|^s_sw|spillvann", "waste water"),
    (r"plumbing vent|sanitary vent|^vent$|\bvent pipe", "plumbing vent"),
    (r"hot|warm ?water|warmwasser|varmvatten|l[äa]mminvesi|\bdhw\b|\btww\b|\bpwh\b|domestic hot|hot water", "hot water"),
    (r"cold|kaltwasser|kallvatten|kylm[äa]vesi|\bpwc\b|domestic cold|potable|trinkwasser|drinking|water supply|vattenledning|koud", "cold water"),
    (r"chilled|cooling|k[äa]lte|j[äa][äa]hdytys|kylning|\bchw\b|\bchs\b|\bchr\b", "cooling"),
    (r"heating|hydronic|heizung|radiator|vorlauf|r[üu]cklauf|ruecklauf|v[äa]rme|l[äa]mmitys|^h_|space heat|fernw[äa]rme|district heat|boiler|\bhws\b|\bhwr\b|\bhw\b", "heating"),
    (r"supply air|return air|exhaust|extract air|ventilat|l[üu]ftung|\bluft|tuloilma|poistoilma|ilmanvaihto|fresh air|air handling|\bahu\b|hvac|\bduct|ilma|lufttechnik|ventilation", "ventilation"),
    (r"\bgas\b|erdgas|natural gas|kaasu", "gas"),
    (r"power|electric|elektr|strom|s[äa]hk[öo]|kabel|cable|lighting|licht|valaistus|belysning|\bdata\b|telecom|communication|krachtstroom|sterkstroom|zwakstroom|conduit|socket|\bnlsfb\b|luminaire|\bel\b", "electrical"),
    (r"alarm|sensor|detector|control|automation|bms", "controls and alarms"),
]
KIND_DEFAULT_DOMAIN = {"duct": "ventilation", "duct_fitting": "ventilation", "air_terminal": "ventilation", "fan": "ventilation", "damper": "ventilation", "air_handler": "ventilation",
                       "cable_tray": "electrical", "cable": "electrical", "cable_fitting": "electrical", "conduit": "electrical", "light": "electrical", "socket": "electrical",
                       "switch": "electrical", "board": "electrical", "transformer": "electrical", "sprinkler": "fire protection", "toilet": "plumbing", "basin": "plumbing",
                       "shower": "plumbing", "bath": "plumbing", "drain": "waste water", "radiator": "heating", "boiler": "heating", "chiller": "cooling", "sensor": "controls and alarms",
                       "alarm": "controls and alarms", "control": "controls and alarms", "fixture": "plumbing"}
SYSTEM_KEYS = ("System Classification", "Systemklassifizierung", "Systeemclassificatie", "Järjestelmäluokitus", "System Type", "Systemtyp", "Systeemtype", "System Name", "Systemname",
               "Systeemnaam", "System Abbreviation", "Systemabkürzung", "Järjestelmä", "System")
CLASSIF_KEYS = ("System Classification", "Systemklassifizierung", "Systeemclassificatie", "System Type", "Systemtyp", "Systeemtype")
NAME_KEYS = ("System Name", "Systemname", "Systeemnaam", "System Abbreviation", "Systemabkürzung")
MAT_KEYS = ("Material", "Materiaal", "Materiale", "Werkstoff", "Materiaali", "Structural Material", "Pipe Segment", "Rohrsegment")
BEARING_KEYS = ("LoadBearing", "Load Bearing", "Tragend", "Structural", "Structural Usage", "Dragend", "Kantava")
CONCRETE = re.compile(r"concrete|beton|betong|betoni|stahlbeton|hormig[oó]n|b[ée]ton|\bstb\b|reinforced|cast[- ]in|precast|\bcip\b|ortbeton|c\d{2}/\d{2}|\bb\d{2}\b", re.I)
STEEL = re.compile(r"steel|stahl|st[åa]l|teräs|staal|\bhe[abm]? ?\d+|\bipe ?\d+|\bhup\b|\bshs\b|\brhs\b|metal", re.I)
WOOD = re.compile(r"timber|wood|holz|puu|tr[äa]|hout|glulam|lvl|clt", re.I)


PLAIN_PLURAL = {"proxy": ("generic object", "generic objects"), "furniture": ("furniture item", "furniture items"), "stairs": ("staircase", "staircases"), "covering": ("covering", "coverings"),
                "railing": ("railing", "railings"), "site": ("site", "sites"), "roof": ("roof", "roofs")}


def plural(kind: str, n: int = 2) -> str:
    s, p = KIND_WORDS.get(kind) or PLAIN_PLURAL.get(kind) or (kind.replace("_", " "), kind.replace("_", " ") + "s")
    return s if n == 1 else p


def system_kind(*texts) -> str | None:
    t = " ".join(str(x) for x in texts if x).lower()
    if not t.strip():
        return None
    for rx, label in SYSTEM_KINDS:
        if re.search(rx, t):
            return label
    return None


def clean_type(raw: str | None) -> str:
    """"Pipe Types:Hot Water:699832" -> "Hot Water"; "Rohrtypen:Kupfer - Hartgelötet:7376600" -> "Kupfer - Hartgelötet"; numeric ids dropped."""
    s = str(raw or "").strip()
    if not s:
        return "type not named"
    parts = [p.strip() for p in s.split(":") if p.strip() and not re.fullmatch(r"[\d\s.#_-]+", p.strip())]
    if not parts:
        return "type not named"
    if len(parts) >= 2:
        low = parts[-1].lower()
        if low in ("standard", "default", "generic", "typ", "type", "-", "none") or len(parts[-1]) <= 1:
            return f"{parts[-2]} ({parts[-1]})" if len(parts[-1]) > 1 else parts[-2]
        return parts[-1] if len(parts) == 2 else ": ".join(parts[1:])
    return re.sub(r"\s+\d{5,}$", "", parts[0])


def _kind_from_words(*texts) -> str | None:
    t = " ".join(str(x) for x in texts if x).lower()
    for rx, k in KEYWORD_KIND:
        if re.search(rx, t):
            return k
    return None


def _first(ps: dict, keys):
    for pset in ps.values():
        if isinstance(pset, dict):
            for k in keys:
                v = pset.get(k)
                if v not in (None, "") and not (isinstance(v, str) and v.strip().lower() in ("n/a", "none", "undefined", "unset", "<unspecified>", "-")):
                    return v
    return None


# ------------------------------------------------------------------ profile sizes for structure (units from the IFC, never from a name)
def profile_size(el, scale: float):
    """(text, w_mm, h_mm) from the first swept profile of the element or its mapped type, e.g. ("250 x 400 mm", 250, 400); None when it has none."""
    try:
        reps = el.Representation.Representations if el.Representation else []
        stack = [i for r in reps if r.RepresentationIdentifier in ("Body", None, "") for i in r.Items]
        seen = 0
        while stack and seen < 40:
            seen += 1
            it = stack.pop(0)
            if it.is_a("IfcMappedItem"):
                stack.extend(it.MappingSource.MappedRepresentation.Items)
            elif it.is_a("IfcBooleanResult"):
                stack.append(it.FirstOperand)
            elif it.is_a("IfcExtrudedAreaSolid"):
                p = it.SweptArea
                name = getattr(p, "ProfileName", None)
                k = scale * 1000.0
                if p.is_a("IfcRectangleProfileDef"):
                    w, h = sorted((float(p.XDim) * k, float(p.YDim) * k))
                    return f"{_mm(w)} x {_mm(h)} mm", w, h
                if p.is_a("IfcCircleProfileDef"):
                    d = float(p.Radius) * 2 * k
                    return f"diameter {_mm(d)} mm", d, d
                if p.is_a("IfcIShapeProfileDef") or p.is_a("IfcLShapeProfileDef") or p.is_a("IfcUShapeProfileDef") or p.is_a("IfcTShapeProfileDef"):
                    w = float(getattr(p, "OverallWidth", None) or getattr(p, "FlangeWidth", None) or getattr(p, "Width", None) or 0) * k
                    h = float(getattr(p, "OverallDepth", None) or getattr(p, "Depth", None) or 0) * k
                    return (name or f"{_mm(w)} x {_mm(h)} mm"), w, h
                if name:
                    return str(name), None, None
    except Exception:  # noqa: BLE001
        return None
    return None


def _mm(v: float) -> str:
    return f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}"


def size_from_name(*texts):
    """"STB 250 x 400", "HUP 100x100x6.3", "D200", "d=30", "Ø300" in a type name -> (label, w_mm, h_mm); a name is only a fallback when no profile is stored."""
    for t in texts:
        t = str(t or "")
        m = re.search(r"(?<![A-Za-z0-9.,])(\d{2,4}(?:[.,]\d+)?)\s*[x×*]\s*(\d{2,4}(?:[.,]\d+)?)(?:\s*[x×*]\s*(\d{1,3}(?:[.,]\d+)?))?", t)
        if m:
            a, b = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
            return (f"{_mm(a)} x {_mm(b)} mm", a, b) if min(a, b) >= 10 else None
        m = re.search(r"(?:[ØøΦ⌀]|\bd ?=? ?|\bD)\s?(\d{2,4}(?:[.,]\d+)?)\b", t)
        if m:
            d = float(m.group(1).replace(",", "."))
            if d >= 10:
                return f"diameter {_mm(d)} mm", d, d
    return None


# ------------------------------------------------------------------ extraction
def _unique(f, classes):
    seen = {}
    for c in classes:
        try:
            ents = f.by_type(c)
        except RuntimeError:
            continue
        for e in ents:
            seen.setdefault(e.GlobalId, e)
    return list(seen.values())


FITTING_WORDS = re.compile(r"\b(?:elbow|bend|tee|t-st[üu]cke?|bogen|kn[ie]e|kniest[üu]ck|abzweig\w*|[üu]bergang\w*|transition|reducer|reduktion|coupling|muffe|union|cross|kreuz\w*|stutzen|nipple|endkappe|kulma|haara\w*|supistus|y-?st[üu]ck|wye|offset|takeoff|take-off|saddle|flange|flansch|bushing|verteiler)\b", re.I)


def _classify(el, t, ps) -> str:
    k = _classify0(el, t, ps)
    if k in ("pipe", "duct", "cable_tray", "conduit"):
        hay = " ".join(str(w or "") for w in (el.Name, getattr(el, "ObjectType", None), t.Name if t is not None else None))
        if FITTING_WORDS.search(hay):
            return {"pipe": "pipe_fitting", "duct": "duct_fitting"}.get(k, "cable_fitting")
    return k


def _classify0(el, t, ps) -> str:
    cls = el.is_a()
    k = CLASS_KIND.get(cls)
    words = (el.Name, getattr(el, "ObjectType", None), t.Name if t is not None else None, _first(ps, ("Family", "Family and Type", "Familie", "Reference", "Description")))
    if k == "fixture" or (cls == "IfcSanitaryTerminal"):
        return _kind_from_words(*words) if _kind_from_words(*words) in ("toilet", "basin", "shower", "bath", "drain") else "fixture"
    if k:
        return k
    tc = t.is_a().replace("Type", "") if t is not None else ""
    if CLASS_KIND.get(tc):
        k = CLASS_KIND[tc]
        if k == "fixture":
            return _kind_from_words(*words) if _kind_from_words(*words) in ("toilet", "basin", "shower", "bath", "drain") else "fixture"
        return k
    kw = _kind_from_words(*words)
    if cls in ("IfcFlowSegment", "IfcDistributionFlowElement"):
        hay = " ".join(str(w or "") for w in words).lower()
        keys = {kk.lower() for d in ps.values() if isinstance(d, dict) for kk in d}
        if re.search(r"cable|kabel|tray|conduit|wire|ladder|goot|goten", hay):
            return "conduit" if re.search(r"conduit|buis|tube|rohr", hay) and not re.search(r"tray|ladder|goot", hay) else "cable_tray"
        if re.search(r"\bduct|luftkanal|kanal|ilmanvaihto|ventilation|supply air|return air|exhaust air|kanava", hay) or "hydraulic diameter" in keys or ({"width", "height"} <= keys and "diameter" not in keys):
            return "duct"
        if re.search(r"pipe|rohr|putki|r[öo]r|leiding|piping|tube", hay) or "pipe segment" in keys or "diameter" in keys:
            return "pipe"
        return "segment"
    if cls == "IfcFlowFitting":
        hay = " ".join(str(w or "") for w in words).lower()
        if re.search(r"cable|kabel|tray|conduit|wire", hay):
            return "cable_fitting"
        if re.search(r"\bduct|luftkanal|kanal|ventilation|supply air|return air|exhaust", hay):
            return "duct_fitting"
        if re.search(r"pipe|rohr|putki|r[öo]r|leiding|piping|elbow|tee|coupling|union", hay):
            return "pipe_fitting"
        return "fitting"
    if kw:
        return kw
    return GENERIC_BY_CLASS.get(cls, "device")


PROXY_SAFE = {"socket", "light", "switch", "board", "toilet", "basin", "shower", "bath", "sprinkler", "sensor", "alarm"}


def _proxy_kind(el, UE):
    """Generic objects are only counted as services when their own name says what they are (receptacle, luminaire, toilet, sprinkler ...)."""
    t = UE.get_type(el)
    k = _kind_from_words(el.Name, getattr(el, "ObjectType", None), t.Name if t is not None else None)
    return k if k in PROXY_SAFE else None


def material_layers(el, UE):
    """[(material name, layer thickness or None)] from the element's own material, else its type's."""
    for obj in (el, UE.get_type(el)):
        if obj is None:
            continue
        for rel in getattr(obj, "HasAssociations", None) or []:
            if not rel.is_a("IfcRelAssociatesMaterial"):
                continue
            m = rel.RelatingMaterial
            if m.is_a("IfcMaterialLayerSetUsage"):
                m = m.ForLayerSet
            if m.is_a("IfcMaterialProfileSetUsage"):
                m = m.ForProfileSet
            if m.is_a("IfcMaterialLayerSet"):
                return [(l.Material.Name if l.Material else "", float(l.LayerThickness or 0)) for l in m.MaterialLayers]
            if m.is_a("IfcMaterialProfileSet"):
                return [(p.Material.Name if p.Material else "", None) for p in m.MaterialProfiles]
            if m.is_a("IfcMaterialConstituentSet"):
                return [(c.Material.Name if c.Material else "", None) for c in m.MaterialConstituents]
            if m.is_a("IfcMaterialList"):
                return [(x.Name, None) for x in m.Materials]
            if m.is_a("IfcMaterial"):
                return [(m.Name, None)]
    return []


def concrete_share(el, t, ps):
    """(material text, share of the element that is concrete or None when the model does not say). Layer thickness weights layered walls and slabs."""
    try:
        layers = [(n or "", th) for n, th in material_layers(el, __import__("ifcopenshell.util.element", fromlist=["x"]))]
    except Exception:  # noqa: BLE001
        layers = []
    if not layers:
        txt = _first(ps, MAT_KEYS)
        if isinstance(txt, str) and txt.strip():
            layers = [(txt, None)]
    names = [n for n, _ in layers if n]
    if not names:
        return None, None
    text = "; ".join(dict.fromkeys(names))[:120]
    isc = [bool(CONCRETE.search(n)) for n, _ in layers]
    ths = [th for _, th in layers]
    if all(isc):
        return text, 1.0
    if not any(isc):
        return text, 0.0
    if all(th for th in ths):
        return text, round(sum(th for th, c in zip(ths, isc) if c) / sum(ths), 3)
    return text, None


def volume_m3(el, f, UE, vscale):
    """The model's own volume in m3: quantity take-off first, else a property typed as a volume (so the unit comes from the file, never from the name)."""
    try:
        q = UE.get_psets(el, qtos_only=True)
        for key in ("NetVolume", "GrossVolume"):
            for d in q.values():
                v = d.get(key)
                if isinstance(v, (int, float)) and v > 0:
                    return round(float(v) * vscale, 4)
        for d in q.values():
            for kk, v in d.items():
                if "volume" in kk.lower() and isinstance(v, (int, float)) and v > 0:
                    return round(float(v) * vscale, 4)
    except Exception:  # noqa: BLE001
        pass
    try:
        for ps in (getattr(el, "IsDefinedBy", None) or []):
            if not ps.is_a("IfcRelDefinesByProperties") or not ps.RelatingPropertyDefinition.is_a("IfcPropertySet"):
                continue
            for pr in ps.RelatingPropertyDefinition.HasProperties:
                nv = getattr(pr, "NominalValue", None)
                if nv is not None and nv.is_a("IfcVolumeMeasure") and "volume" in str(pr.Name).lower() and float(nv.wrappedValue) > 0:
                    return round(float(nv.wrappedValue) * vscale, 4)
    except Exception:  # noqa: BLE001
        pass
    return None


def build(doc_id: str, ifc_path, elements_json=None) -> dict:
    """Read the IFC once: one compact row per distribution (services) and structural element."""
    import ifcopenshell
    import ifcopenshell.util.element as UE
    import ifcopenshell.util.unit as UU
    sys.path.insert(0, str(ROOT))
    from vision import piping as P
    f = ifcopenshell.open(str(ifc_path))
    scale = UU.calculate_unit_scale(f)
    geo = {}
    ej = Path(elements_json) if elements_json else ROOT / f"artifacts/{doc_id}/elements.json"
    if ej.exists():
        for e in json.loads(ej.read_text())["elements"]:
            geo[e["item_id"]] = e
    systems = {}
    for sysent in f.by_type("IfcSystem"):
        for rel in getattr(sysent, "IsGroupedBy", None) or []:
            for o in rel.RelatedObjects:
                systems.setdefault(o.GlobalId, sysent.Name)
    dist = _unique(f, ["IfcDistributionElement"])
    dist += [e for e in _unique(f, ["IfcBuildingElementProxy"]) if _proxy_kind(e, UE) is not None]
    meta = {}
    for el in dist:
        ps = UE.get_psets(el)
        t = UE.get_type(el)
        if t is not None:
            for k, v in UE.get_psets(t).items():
                ps.setdefault(k, v)
        meta[el.GlobalId] = (el, t, ps, _proxy_kind(el, UE) if el.is_a("IfcBuildingElementProxy") else _classify(el, t, ps))
    lin = [m[0] for m in meta.values() if m[3] in LINEAR]
    lrows, calib = P.build_rows(f, lin, "seg", geo, scale, UE) if lin else ([], {})
    by_lin = {r["item_id"]: r for r in lrows}
    # rectangular sizes (ducts, cable trays): "300x200" text first, then width/height properties checked against the 3D cross-section
    rect_ids = [i for i, m in meta.items() if m[3] in ("duct", "cable_tray", "conduit", "duct_fitting")]
    w_vals, h_vals, w_cs, h_cs, w_t, h_t, dims_txt = {}, {}, {}, {}, {}, {}, {}
    WK = ("Width", "Breite", "Breedte", "Leveys", "Bredd", "Breedte goot", "Duct Width", "Overall Width")
    HK = ("Height", "Höhe", "Hoogte", "Korkeus", "Höjd", "Duct Height", "Overall Height")
    for i in rect_ids:
        el, t, ps, k = meta[i]
        txt = _first(ps, ("Size", "Größe", "Maat", "Koko", "Storlek", "Overall Size", "Gesamtmaß"))
        mt = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:mm)?\s*[x×*]\s*(\d+(?:[.,]\d+)?)", str(txt or ""))
        if mt:
            dims_txt[i] = (float(mt.group(1).replace(",", ".")), float(mt.group(2).replace(",", ".")))
        bb = (geo.get(i) or {}).get("bbox_m")
        cs = P.cross_section_mm(bb, rect=True)
        tp = P.typed_props(el)
        flat = {kk: vv for d in tp.values() for kk, vv in d.items()}
        for kk in WK:
            if kk in flat and P._num(flat[kk][0]):
                w_vals[i] = P._num(flat[kk][0]); w_t[i] = flat[kk][1] in P.LENGTH_TYPES; w_cs[i] = cs[1] if cs else None; break
        for kk in HK:
            if kk in flat and P._num(flat[kk][0]):
                h_vals[i] = P._num(flat[kk][0]); h_t[i] = flat[kk][1] in P.LENGTH_TYPES; h_cs[i] = cs[0] if cs else None; break
    w_ok, _ = P.resolve_numeric(w_vals, w_cs, w_t, scale)
    h_ok, _ = P.resolve_numeric(h_vals, h_cs, h_t, scale)
    rows = []
    n_checked = n_agree = 0
    for i, (el, t, ps, k) in meta.items():
        g = geo.get(i) or {}
        sysname = systems.get(i) or _first(ps, NAME_KEYS)
        classif = _first(ps, CLASSIF_KEYS)
        tlabel = clean_type(t.Name if t is not None else getattr(el, "ObjectType", None) or el.Name)
        dom = system_kind(classif, sysname, tlabel if k in LINEAR or k in ("pipe_fitting", "duct_fitting") else None)
        if dom is None and k in ("pipe", "pipe_fitting"):
            dom = system_kind(el.Name, getattr(el, "ObjectType", None))
        dom = dom or KIND_DEFAULT_DOMAIN.get(k)
        row = {"id": i, "c": el.is_a(), "k": k, "d": dom, "t": tlabel, "s": (str(sysname) if sysname else None), "st": (g.get("storey") or {}).get("name"),
               "m": (lambda v: v if isinstance(v, str) and len(v) < 60 else None)(_first(ps, MAT_KEYS))}
        r = by_lin.get(i)
        if r:
            row["w"] = r.get("dn_mm")
            row["L"] = r.get("length_m")
            row["ls"] = r.get("length_source")
            if row["w"]:
                row["ws"] = r.get("dn_source")
        if i in dims_txt:
            row["dim"] = list(dims_txt[i])
        elif i in w_ok and i in h_ok:
            row["dim"] = [round(w_ok[i]), round(h_ok[i])]
        elif i in w_ok:
            row["dim"] = [round(w_ok[i]), None]
        rows.append(row)
    # systems with no kind (terminals whose domain is only known from the rest of the model): the dominant domain of their named system
    sys_dom = defaultdict(Counter)
    for r in rows:
        if r["s"] and r["d"]:
            sys_dom[r["s"]][r["d"]] += 1
    for r in rows:
        if r["k"] in ("terminal", "fitting", "device", "segment") and r["d"] is None and r["s"] and sys_dom.get(r["s"]):
            r["d"] = sys_dom[r["s"]].most_common(1)[0][0]
    # generic terminals / fittings: name the kind from the domain once it is known
    for r in rows:
        if r["k"] == "terminal":
            r["k"] = {"plumbing": "fixture", "waste water": "fixture", "hot water": "fixture", "cold water": "fixture", "ventilation": "air_terminal", "electrical": "light" if False else "terminal",
                      "fire protection": "sprinkler"}.get(r["d"], "terminal")
        elif r["k"] == "fitting":
            r["k"] = {"ventilation": "duct_fitting", "electrical": "cable_fitting"}.get(r["d"], "pipe_fitting" if r["d"] else "fitting")
    # independent check: model length vs the extrusion depth of the same element
    for i, (el, t, ps, k) in meta.items():
        r = by_lin.get(i)
        if r and r.get("length_source") == "model length":
            ex = P._extruded_length_m(el, scale)
            if ex and ex > 0.01 and r["length_m"]:
                n_checked += 1
                n_agree += abs(ex - r["length_m"]) <= 0.03 * max(ex, r["length_m"]) + 0.01
    struct = []
    vscale = UU.calculate_unit_scale(f, "VOLUMEUNIT") or scale ** 3
    for cls, k in STRUCT_CLASS_KIND.items():
        try:
            ents = f.by_type(cls)
        except RuntimeError:
            continue
        for el in ents:
            if any(s["id"] == el.GlobalId for s in struct[-1:]):
                continue
            t = UE.get_type(el)
            ps = UE.get_psets(el)
            tname = clean_type(t.Name if t is not None else (getattr(el, "ObjectType", None) or el.Name))
            sz = profile_size(el, scale) or (profile_size(t, scale) if t is not None and getattr(t, "RepresentationMaps", None) is None else None) or size_from_name(tname, el.Name)
            mt, cf = concrete_share(el, t, ps)
            row = {"id": el.GlobalId, "c": cls, "k": k, "t": tname, "v": volume_m3(el, f, UE, vscale), "mt": mt, "cf": cf, "st": (geo.get(el.GlobalId, {}).get("storey") or {}).get("name"),
                   "m": (lambda v: v if isinstance(v, str) and len(v) < 60 else None)(_first(ps, MAT_KEYS))}
            if sz:
                row["sz"] = sz[0]
                if sz[1]:
                    row["dim"] = [round(sz[1], 1), round(sz[2], 1) if sz[2] else None]
            struct.append(row)
    seen_ids = set()
    struct = [s for s in struct if not (s["id"] in seen_ids or seen_ids.add(s["id"]))]
    res = {"version": MEP_VERSION, "doc_id": doc_id, "schema": f.schema, "unit_scale_m": scale, "services": rows, "structure": struct,
           "calibration": {"length_unit": calib.get("length_unit"), "length_agree": calib.get("length_agree"), "size_units": calib.get("dn"), "length_checked": n_checked, "length_agree_n": n_agree}}
    return res


def write(doc_id: str, ifc_path, art_dir: Path, elements_json=None) -> dict:
    res = build(doc_id, ifc_path, elements_json or (Path(art_dir) / "elements.json"))
    tmp = Path(art_dir) / "mep.json.tmp"
    tmp.write_text(json.dumps(res, separators=(",", ":")))
    tmp.replace(Path(art_dir) / "mep.json")
    return res


# ------------------------------------------------------------------ loading at answer time
_CACHE: dict = {}


def _artifacts_dir() -> Path | None:
    if os.environ.get("ARTIFACTS_DIR"):
        return Path(os.environ["ARTIFACTS_DIR"])
    arts = getattr(sys.modules.get("engine.solvers.solve"), "ARTIFACTS", None)
    return Path(arts) if arts else ROOT / "artifacts"


def _find_ifc(doc_id: str) -> Path | None:
    d = _artifacts_dir()
    uploaded = d / doc_id / "source.ifc"
    if uploaded.is_file():
        return uploaded
    try:
        files = json.loads((d / doc_id / "doc.json").read_text()).get("files", {})
    except (OSError, ValueError):
        return None
    p = files.get("ifc")
    if not p:
        return None
    dataset = Path(os.environ["DATASET_ROOT"]) if os.environ.get("DATASET_ROOT") else ROOT / "data/full/junction-dataset"
    for cand in (dataset / p, ROOT / p, Path(p), *ROOT.glob(f"data/*/*/{p}"), *ROOT.glob(f"data/*/{p}")):
        try:
            if cand.exists():
                return cand
        except OSError:
            continue
    return None


def load_index(doc) -> dict | None:
    """artifacts/<doc>/mep.json; built on first use when the IFC is available and small enough to read in a few seconds."""
    d = _artifacts_dir()
    key = (str(d.resolve()), doc.doc_id)
    f = d / doc.doc_id / "mep.json" if d else None
    try:
        if f and f.exists():
            st = f.stat().st_mtime
            c = _CACHE.get(key)
            if c and c[0] == st:
                return c[1]
            res = json.loads(f.read_text())
            if res.get("version") == MEP_VERSION:
                _CACHE[key] = (st, res)
                return res
    except (OSError, ValueError):
        pass
    ifc = _find_ifc(doc.doc_id)
    if ifc is None or ifc.stat().st_size > 60e6:
        return None
    try:
        res = write(doc.doc_id, ifc, d / doc.doc_id)
    except Exception:  # noqa: BLE001  a broken IFC must never take the answer down
        return None
    _CACHE[key] = (f.stat().st_mtime, res)
    return res


# ------------------------------------------------------------------ question parsing
SUBJECTS = [
    ("pipe", r"\bpip(?:e|es|ing|ework)\b|\bplumbing (?:lines?|runs?)\b|\bpipelines?\b"),
    ("duct", r"\bducts?\b|\bductwork\b|\bventilation (?:lines?|runs?)\b|\bair ducts?\b"),
    ("cable_tray", r"\bcable (?:trays?|ladders?|carriers?|trunking|routes?|runs?)\b|\bcabling\b|\bcables?\b|\bwiring\b|\bcable trays?\b"),
    ("conduit", r"\bconduits?\b"),
    ("sprinkler", r"\bsprinklers?\b"),
    ("light", r"\blight (?:fittings?|fixtures?)\b|\blights\b|\blighting\b|\bluminaires?\b|\blamps?\b|\blight\b(?!\s*weight)"),
    ("socket", r"\bsockets?\b|\boutlets?\b|\breceptacles?\b|\bpower points?\b"),
    ("switch", r"\bswitch(?:es)?\b"),
    ("valve", r"\bvalves?\b"),
    ("pump", r"\bpumps?\b"),
    ("fan", r"\bfans?\b"),
    ("radiator", r"\bradiators?\b|\bheaters?\b|\bconvectors?\b"),
    ("air_terminal", r"\bdiffusers?\b|\bgrilles?\b|\bair terminals?\b|\bair outlets?\b"),
    ("sensor", r"\bsensors?\b|\bdetectors?\b|\bthermostats?\b"),
    ("alarm", r"\balarms?\b"),
    ("board", r"\bdistribution boards?\b|\bswitchboards?\b|\bswitchgear\b|\belectrical panels?\b|\bpanelboards?\b"),
    ("boiler", r"\bboilers?\b|\bheat pumps?\b"),
    ("chiller", r"\bchillers?\b"),
    ("air_handler", r"\bair handling units?\b|\bahus?\b"),
    ("tank", r"\btanks?\b"),
    ("fixture", r"\bsanitary (?:fixtures?|terminals?|ware|appliances?)\b|\bplumbing fixtures?\b|\bwater fixtures?\b"),
    ("toilet", r"\btoilets?\b|\bwcs?\b|\burinals?\b"),
    ("basin", r"\bwash ?basins?\b|\bsinks?\b|\blavator(?:y|ies)\b"),
    ("shower", r"\bshowers?\b"),
    ("bath", r"\bbath ?tubs?\b"),
    ("drain", r"\bdrains?\b"),
    ("fitting", r"\bfittings?\b"),
]
GROUP_SUBJECTS = {  # words naming a whole group of kinds (or a whole trade)
    "fixture": {"fixture", "toilet", "basin", "shower", "bath", "drain"},
    "pipe": {"pipe"}, "duct": {"duct"}, "cable_tray": {"cable_tray", "cable", "conduit"},
    "light": {"light"}, "fitting": {"pipe_fitting", "duct_fitting", "cable_fitting", "fitting"}, "valve": {"valve"},
    "air_terminal": {"air_terminal"}, "sensor": {"sensor", "alarm"}, "alarm": {"alarm", "sensor"}, "board": {"board", "transformer"},
}
TRADE_DOMAINS = {"plumbing": {"waste water", "hot water", "cold water", "rainwater", "plumbing vent", "plumbing"}, "water supply": {"hot water", "cold water"}, "hot water": {"hot water"}, "cold water": {"cold water"},
                 "waste water": {"waste water", "plumbing vent"}, "rainwater": {"rainwater"}}
TRADES = [
    ("water supply", r"\bwater supply\b|\bdomestic water\b|\bpotable\b|\bdrinking water\b|\bsupply water\b"), ("hot water", r"\bhot water\b|\bwarm water\b|\bdhw\b"), ("cold water", r"\bcold water\b"),
    ("waste water", r"\bwaste ?water\b|\bsewage\b|\bsewer\b|\bsanitary (?:pipes?|piping|drain\w*|system)\b|\bsoil pipes?\b|\bwaste pipes?\b"), ("rainwater", r"\brain ?water\b|\bstorm ?water\b|\bstorm drain\w*\b"),
    ("electrical", r"\belectric\w*\b|\bpower\b|\bcabling\b|\bwiring\b"), ("plumbing", r"\bplumbing\b|\bwater (?:supply|system)\b|\bsanitary\b|\bdrainage\b|\bsewage\b"),
    ("heating", r"\bheating\b|\bhydronic\b"), ("cooling", r"\bcooling\b|\bchilled\b|\bair[- ]conditioning\b"), ("ventilation", r"\bventilation\b|\bsupply air\b|\bexhaust air\b|\bhvac\b|\bair handling\b"),
    ("fire protection", r"\bfire (?:protection|suppression|fighting|safety|alarm)\b|\bsprinkler"), ("gas", r"\bgas (?:system|supply|pipes?|piping)\b|\bnatural gas\b"),
]
MEP_GENERIC = re.compile(r"\bmep\b|\bbuilding services?\b|\bhvac\b|\bmechanical(?:,| and|/)? (?:and )?electrical\b|\b(?:mechanical|electrical|plumbing|heating|cooling|ventilation|hvac|fire|piping|pipework|distribution) (?:systems?|components?|elements?|equipment)\b|"
                         r"\bservices (?:installed|present|modelled|in)\b|\bmep (?:systems?|components?|elements?|equipment|terminals?)\b|\b(?:mep|building service)\w* ", re.I)
STRUCT_GENERIC = re.compile(r"\bstructural (?:components?|elements?|members?|system|frame|parts|materials?|systems)\b|\bload[- ]?bearing\b|\bstructure\b|\bstructural\b", re.I)
STRUCT_SUBJECTS = [("column", r"\bcolumns?\b|\bpillars?\b|\bst[üu]tzen?\b"), ("beam", r"\bbeams?\b|\bgirders?\b|\bjoists?\b|\blintels?\b"), ("member", r"\bstructural members?\b|\bmembers\b"),
                   ("footing", r"\bfootings?\b|\bfoundations?\b|\bpiles?\b|\bpile caps?\b"), ("rebar", r"\brebars?\b|\breinforcement\b|\breinforcing\b")]
LENGTH_Q = re.compile(r"\blength\b|\bhow long\b|\bmetres?\b|\bmeters?\b|\bmetre?age\b|\brunning\b|\blinear\b|\bhow much\b|\bhow many (?:m|metres|meters)\b|\b(?:total|overall) (?:length|run)\b|\bm\b", re.I)
COUNT_Q = re.compile(r"\bhow many\b|\bnumber of\b|\bcount\b|\btotal number\b|\bquantit(?:y|ies)\b", re.I)
TYPES_Q = re.compile(r"\btypes?\b|\bkinds?\b|\bvarieties\b|\bcategories\b|\bwhich (?:\w+ ){0,3}(?:are|is) (?:used|present|installed|included|available|in)\b|\bwhat (?:\w+ ){0,3}(?:are|is) (?:used|present|installed|there|in)\b|\bby type\b", re.I)
SYSTEMS_Q = re.compile(r"\bsystems?\b|\bby system\b|\bsystem types?\b|\bserv(?:e|es|ing|ed)\b|\bnetworks?\b|\bcircuits?\b", re.I)
SIZES_Q = re.compile(r"\bsizes?\b|\bdiameters?\b|\bdimensions?\b|\bwidths?\b|\bdn ?\d+\b|\bspans?\b|\bhow (?:big|large|wide|thick|tall)\b", re.I)
VOLUME_Q = re.compile(r"\bvolumes?\b|\bconcrete\b|\bm3\b|\bm³\b|\bcubic\b", re.I)
MATERIAL_Q = re.compile(r"\bmaterials?\b|\bmade of\b|\bmade from\b", re.I)
BYLEVEL_Q = re.compile(r"\bby (?:level|floor|storey|story)\b|\bper (?:level|floor|storey|story)\b|\beach (?:level|floor|storey|story)\b|\bdistributed (?:across|over|between)\b|\bacross (?:the )?(?:floors|levels|storeys)\b", re.I)
OVERVIEW_Q = re.compile(r"\bwhat\b.*\b(?:in|are in|is in) (?:this|the) (?:building|model)\b|\boverview\b|\bsummary\b|\bwhich\b.*\bexist\b|\bwhat (?:\w+ ){0,2}(?:is|are) there\b", re.I)


def _subjects(ql: str) -> list[str]:
    out = []
    # A light fitting is a light, not every fitting in the model. Consume
    # compound nouns before their generic "pipe" / "fitting" components.
    for key, rx in (("light", r"\blight fittings?\b"),
                    ("pipe_fitting", r"\bpipe fittings?\b"),
                    ("duct_fitting", r"\bduct fittings?\b"),
                    ("cable_fitting", r"\bcable (?:tray )?fittings?\b")):
        if re.search(rx, ql):
            out.append(key)
            ql = re.sub(rx, "", ql)
    for key, rx in SUBJECTS:
        if re.search(rx, ql) and key not in out:
            out.append(key)
    return out


def _length_requested(question: str) -> bool:
    # "How many metres" counts units of length; "how many segments" counts
    # objects. A storey or type name containing "m" cannot change that operation.
    units = r"(?:m|metres?|meters?|feet|foot|ft|inches?|in)"
    unit_count = re.compile(r"\b(?:how many|number of)\s+(?:(?:linear|running)\s+)?" + units + r"\b", re.I)
    remainder = unit_count.sub("", question)
    return bool((LENGTH_Q.search(question) or unit_count.search(question)) and not COUNT_Q.search(remainder))


def _kinds_of(subj: list[str]) -> set[str]:
    ks: set[str] = set()
    for s in subj:
        ks |= GROUP_SUBJECTS.get(s, {s})
    return ks


# ------------------------------------------------------------------ answers
def _join(words) -> str:
    w = [x for x in words if x]
    return w[0] if len(w) == 1 else (", ".join(w[:-1]) + " and " + w[-1] if w else "")


def _n(v: float) -> str:
    return f"{v:,.1f}" if abs(v) >= 10 else f"{v:,.2f}"


def _int(n: int) -> str:
    return f"{n:,}"


def _share(n: int, tot: int) -> str:
    return f"{100.0 * n / tot:.0f}%" if tot else ""


def _size_label(r: dict) -> str | None:
    if r.get("dim") and r["dim"][0] and r["dim"][1]:
        a, b = r["dim"][0], r["dim"][1]
        return f"{_mm(a)} x {_mm(b)} mm"
    if r.get("w"):
        return f"DN{int(r['w'])}" if r["k"] in ("pipe", "pipe_fitting") else f"diameter {_mm(r['w'])} mm"
    if r.get("sz"):
        return r["sz"]
    if r.get("dim") and r["dim"][0]:
        return f"{_mm(r['dim'][0])} mm wide"
    return None


def _desc(r: dict) -> str:
    """"hot water pipe": the system kind and the plain element word."""
    k = KIND_WORDS.get(r["k"], (r["k"], r["k"]))[0]
    d = r.get("d")
    if r["k"] in LINEAR | {"pipe_fitting", "duct_fitting", "cable_fitting"} and d and d not in ("ventilation", "electrical") or (r["k"] in ("pipe", "pipe_fitting") and d):
        return f"{d} {k}"
    return k


class _Ctx:
    def __init__(self, question, doc, t0, idx):
        self.q, self.ql, self.doc, self.t0, self.idx = question, question.lower(), doc, t0, idx
        self.by_id = {i.item_id: i for i in doc.items}
        self.steps: list[str] = []
        self.hint_checked: str | None = None
        self.cap: tuple | None = None


def _finish(c: _Ctx, text: str, value, unit: str, ids: list[str], steps: list[str], found: str | None = None, measured: str | None = None,
            checked: str | None = None, cap_pct: int | None = None, cap_reason: str | None = None, improve: str | None = None) -> dict:
    from engine.solvers.solve import _answer_obj, _evidence, _step
    uids = [i for i in dict.fromkeys(ids) if i in c.by_id]
    items = [c.by_id[i] for i in uids]
    _b, cites, _s = _evidence(c.doc, items)
    # Citation provenance covers the whole total; rendering can cap highlights.
    scene = {"doc_id": c.doc.doc_id, "highlight_item_ids": uids[:3000], "camera_target_item_id": uids[0] if uids else None}
    trace = [_step("route", "building services / structure -> element index read from the IFC, code, no model")] + [_step("filter", s) for s in steps]
    marks = "".join(f"[{x['n']}]" for x in cites)
    tail = " Shown in 3D: the same items glow in the 3D view." if items and not any(x.get("bbox_px") for x in cites) else ""
    res = _answer_obj(c.q, [c.doc.doc_id], text.replace("{marks}", marks) + tail, value, unit, 1.0 if items or value == 0 else 0.7, False, [], cites, scene, trace, "index", c.t0 or time.perf_counter())
    hint = {"steps": [], "checked": None}
    n_all, n_found = len(ids), len(uids)
    if found:
        hint["steps"].append({"kind": "found", "title": "Found", "text": found, "cite": cites[0]["n"] if cites else None, "ok": None})
    if measured:
        hint["steps"].append({"kind": "measured", "title": "Measured", "text": measured, "cite": cites[0]["n"] if cites else None, "ok": None})
    if checked is None and n_all and unit == "count":
        ok = n_found == n_all
        checked = f"All {_int(n_all)} counted items are found in the 3D model" if ok else f"{_int(n_found)} of the {_int(n_all)} counted items are found in the 3D model"
        hint["checked"] = ok
    elif checked:
        hint["checked"] = True
    if checked:
        hint["steps"].append({"kind": "checked", "title": "Checked", "text": checked, "cite": None, "ok": hint["checked"]})
    if cap_pct:
        hint["pct_cap"], hint["reason"], hint["improve"] = cap_pct, cap_reason, improve
    res["reasoning_hint"] = hint
    return res


def _storey_filter(c: _Ctx, rows: list[dict]):
    from engine.solvers.filters import storey_requested
    from engine.solvers.solve import resolve_storey
    names = {r.get("st") for r in rows if r.get("st")}
    storeys = c.doc.storeys or [{"name": n, "elevation_m": 0} for n in sorted(names)]
    st = resolve_storey(c.q, storeys)
    if st:
        return st, [r for r in rows if r.get("st") == st], None
    if storey_requested(c.q):
        return None, rows, "No matching level was found. Levels in this model: " + ", ".join(s["name"] for s in c.doc.storeys[:12]) + "."
    return None, rows, None


def _top(counter: Counter, n: int = 6, total: int | None = None) -> str:
    return "; ".join(f"{k}: {_int(v)}" + (f" ({_share(v, total)})" if total and total >= 10 else "") for k, v in counter.most_common(n))


def _services_summary(rows: list[dict]) -> Counter:
    return Counter(r["k"] for r in rows)


def _kinds_phrase(rows: list[dict], n: int = 4) -> str:
    cnt = Counter(r["k"] for r in rows)
    return ", ".join(f"{_int(v)} {plural(k, v)}" for k, v in cnt.most_common(n))


def no_services(c: _Ctx, what: str = "building-services (MEP) elements") -> dict:
    cls = Counter(i.kind for i in c.doc.items if i.kind not in ("space", "room", "storey"))
    has = ", ".join(f"{_int(v)} {plural(k, v)}" for k, v in cls.most_common(4))
    text = f"**This model has no {what}**: no pipes, ducts, cables, fixtures or service equipment were found in it."
    if has:
        text += f"\n- It contains: {has}."
    text += "\n- To answer this, upload the plumbing, ventilation or electrical model of the same building."
    return _finish(c, text, 0, "count", [], ["0 distribution elements in the IFC"], found="No pipes, ducts, cables, fixtures or service equipment exist in this model")


# ---- services
def _in_trade(r: dict, trade: str) -> bool:
    if trade in TRADE_DOMAINS:
        return r.get("d") in TRADE_DOMAINS[trade] or (trade == "plumbing" and r["k"] in ("toilet", "basin", "shower", "bath", "fixture", "drain"))
    return r.get("d") == trade or (trade == "electrical" and r["k"] in ("cable_tray", "cable", "light", "socket", "switch", "board", "transformer", "cable_fitting", "conduit"))


def _services_for(c: _Ctx, subj: list[str], trade: str | None):
    rows = c.idx["services"]
    if subj:
        ks = _kinds_of(subj)
        rows = [r for r in rows if r["k"] in ks]
    if trade:
        rows = [r for r in rows if _in_trade(r, trade)]
    return rows


def _systems_answer(c: _Ctx, subj: list[str], trade: str | None) -> dict:
    allrows = c.idx["services"]
    if not allrows:
        return no_services(c)
    st, rows, err = _storey_filter(c, allrows)
    if err:
        return _finish(c, f"**{err}**", None, None, [], ["level not found"])
    if subj or trade:
        rows = _services_for(c, subj, trade) if not st else [r for r in _services_for(c, subj, trade) if r.get("st") == st]
    if not rows:
        what = (trade or ", ".join(plural(s) for s in subj)) + (f" on {st}" if st else "")
        return no_services(c, f"{what} elements") if not st else _finish(c, f"**No {what} elements are modelled**: this model has {_int(len(allrows))} service elements elsewhere.", 0, "count", [], ["0 matches"])
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r.get("d") or "system not named"].append(r)
    order = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    named = {r["s"] for r in rows if r.get("s")}
    head = f"**{_int(len(rows))} service components in {len(groups)} system type{'s' if len(groups) != 1 else ''}**" + (f" on {st}" if st else "")
    bullets = []
    for d, rs in order[:6]:
        extra = ""
        lin = [r for r in rs if r["k"] in LINEAR and r.get("L")]
        if lin:
            extra = f", {_n(sum(r['L'] for r in lin))} m of runs"
        bullets.append(f"- {d.capitalize() if d != 'system not named' else 'System not stated'}: {_int(len(rs))} component{'s' if len(rs) != 1 else ''} ({_kinds_phrase(rs, 3)}{extra})")
    if len(order) > 6:
        bullets.append(f"- +{len(order) - 6} smaller system types ({_int(sum(len(rs) for _, rs in order[6:]))} components)")
    if named and len(named) > 1:
        bullets.append(f"- {_int(len(named))} separately named circuits or loops are defined in the model" if len(named) > len(groups) else f"- Named in the model: {', '.join(sorted(named)[:6])}")
    unass = len(groups.get("system not named", []))
    cap = None
    if unass and unass > 0.3 * len(rows):
        cap, why = 88, f"{_int(unass)} of {_int(len(rows))} components carry no system name, so their system type is not stated in the model"
        bullets.append(f"- {_int(unass)} components have no system recorded in the model")
    text = head + ".\n" + "\n".join(bullets) + " {marks}"
    return _finish(c, text, len(rows), "count", [r["id"] for r in rows], [f"{len(rows)} service elements in {len(groups)} system types"],
                   found=f"{_int(len(rows))} service elements, grouped by the system each one belongs to ({len(groups)} system types)",
                   cap_pct=cap, cap_reason=("Counted exactly, but " + why + ".") if cap else None, improve="Ask the designer to assign every element to a named system." if cap else None)


def _types_answer(c: _Ctx, subj: list[str], trade: str | None) -> dict:
    rows = _services_for(c, subj, trade)
    st, rows2, err = _storey_filter(c, rows)
    if err:
        return _finish(c, f"**{err}**", None, None, [], ["level not found"])
    rows = rows2
    word = _join([plural(s) for s in subj]) if subj else "service elements"
    if not rows:
        return no_services(c, f"{word}") if not c.idx["services"] or not st else _finish(c, f"**No {word} on {st}.**", 0, "count", [], ["0 matches"])
    cnt = Counter(r["t"] for r in rows)
    kinds = Counter(r["k"] for r in rows)
    one_kind = len(kinds) == 1
    head = f"**{_int(len(cnt))} {'type' if len(cnt) == 1 else 'types'} of {word if one_kind or subj else 'service element'}**" + (f" on {st}" if st else "") + f", {_int(len(rows))} elements in total"
    lines = []
    for t, v in cnt.most_common(8):
        sub = [r for r in rows if r["t"] == t]
        ex = ""
        sizes = Counter(_size_label(r) for r in sub if _size_label(r))
        if sizes:
            ex = f", sizes {', '.join(f'{k} ({_int(n)})' for k, n in sizes.most_common(3))}"
        mats = Counter(r["m"] for r in sub if r.get("m"))
        if mats:
            ex += f", {mats.most_common(1)[0][0]}"
        lines.append(f"- {t}: {_int(v)} ({_share(v, len(rows))}){ex}")
    if len(cnt) > 8:
        lines.append(f"- +{len(cnt) - 8} more types ({_int(sum(v for _, v in cnt.most_common()[8:]))} elements)")
    if not one_kind:
        lines.append(f"- Kinds: {_kinds_phrase(rows, 5)}")
    return _finish(c, head + ".\n" + "\n".join(lines) + " {marks}", len(cnt), "count", [r["id"] for r in rows], [f"{len(cnt)} types over {len(rows)} elements"],
                   found=f"{_int(len(rows))} {word}, grouped by the type name stored on each one")


def _count_answer(c: _Ctx, subj: list[str], trade: str | None) -> dict:
    allr = c.idx["services"]
    rows = _services_for(c, subj, trade)
    st, rows, err = _storey_filter(c, rows)
    if err:
        return _finish(c, f"**{err}**", None, None, [], ["level not found"])
    word = _join([plural(s, 2) for s in subj]) if subj else (f"{trade} elements" if trade else "service elements")
    if not rows:
        if not allr:
            return no_services(c, f"{word}" if subj or trade else "building-services (MEP) elements")
        have = Counter(r["k"] for r in allr)
        return _finish(c, f"**No {word}{f' on {st}' if st else ''}** are modelled." + (f"\n- This model's service elements are: {_kinds_phrase(allr, 4)}." if allr else ""), 0, "count", [], [f"0 {word}"],
                       found=f"No {word}{f' on {st}' if st else ''} exist in the model")
    kinds = Counter(r["k"] for r in rows)
    n = len(rows)
    one = len(kinds) == 1
    k0 = next(iter(kinds))
    lines = []
    if not st:
        lv = Counter(r.get("st") or "level not recorded" for r in rows)
        if len(lv) > 1:
            lines.append(f"- By level: {_top(lv, 6)}")
    ty = Counter(r["t"] for r in rows)
    if len(ty) > 1 and (one or len(ty) <= 12):
        lines.append(f"- By type: {_top(ty, 5, n)}")
    if not one:
        lines.append(f"- Kinds: {_kinds_phrase(rows, 6)}")
    sy = Counter(r["d"] or "system not named" for r in rows)
    if len(sy) > 1:
        lines.append(f"- By system: {_top(sy, 5, n)}")
    head = f"**{_int(n)} {plural(k0, n) if one else word}**" + (f" on {st}" if st else " in this model")
    return _finish(c, head + ".\n" + "\n".join(lines[:4]) + " {marks}", n, "count", [r["id"] for r in rows], [f"{n} elements"],
                   found=f"{_int(n)} {plural(k0, n) if one else word}{f' on {st}' if st else ''}, counted element by element in the model")


def _length_answer(c: _Ctx, subj: list[str], trade: str | None) -> dict:
    lin_kinds = [s for s in subj if s in ("pipe", "duct", "cable_tray", "conduit", "cable")] or ["pipe", "duct", "cable_tray", "conduit"]
    ks = _kinds_of(lin_kinds) & LINEAR | _kinds_of(lin_kinds)
    rows = [r for r in c.idx["services"] if r["k"] in ks and r["k"] in LINEAR]
    if trade:
        rows = [r for r in rows if _in_trade(r, trade)]
    st, rows, err = _storey_filter(c, rows)
    if err:
        return _finish(c, f"**{err}**", None, None, [], ["level not found"])
    word = _join([plural(s) for s in lin_kinds if s != "conduit"]) if subj else "pipes, ducts and cable trays"
    if not rows:
        if not c.idx["services"]:
            return no_services(c, word)
        return _finish(c, f"**No {word}{f' on {st}' if st else ''}** are modelled." + (f"\n- This model's service elements are: {_kinds_phrase(c.idx['services'], 4)}." if c.idx["services"] else ""),
                       0, "m", [], ["0 runs"], found=f"No {word} exist in the model")
    have = [r for r in rows if r.get("L")]
    tot = sum(r["L"] for r in have)
    by_kind = defaultdict(float)
    for r in have:
        by_kind[r["k"]] += r["L"]
    bullets = []
    ql = c.ql
    group = "level" if (BYLEVEL_Q.search(ql) or re.search(r"\bdistributed\b|\blevels?\b|\bfloors?\b|\bstoreys?\b", ql)) and not st else ("size" if re.search(r"\bsizes?\b|\bdiameters?\b", ql) else "system")
    if group == "system":
        g = defaultdict(lambda: [0, 0.0])
        for r in have:
            key = f"{r.get('d') or 'system not named'} {KIND_WORDS.get(r['k'], (r['k'],))[0].split(' (')[0]}" if len({x['k'] for x in have}) > 1 else (r.get("d") or "system not named")
            g[key][0] += 1; g[key][1] += r["L"]
        bullets.append("- By system: " + "; ".join(f"{k}: {_n(v[1])} m ({_int(v[0])} runs)" for k, v in sorted(g.items(), key=lambda kv: -kv[1][1])[:8]))
    elif group == "level":
        g = defaultdict(float)
        for r in have:
            g[r.get("st") or "level not recorded"] += r["L"]
        bullets.append("- By level: " + "; ".join(f"{k}: {_n(v)} m" for k, v in sorted(g.items(), key=lambda kv: -kv[1])[:8]))
    else:
        g = defaultdict(float)
        for r in have:
            g[_size_label(r) or "size not recorded"] += r["L"]
        bullets.append("- By size: " + "; ".join(f"{k}: {_n(v)} m" for k, v in sorted(g.items(), key=lambda kv: -kv[1])[:8]))
    if len(by_kind) > 1:
        bullets.append("- By kind: " + "; ".join(f"{plural(k)}: {_n(v)} m" for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1])))
    sized = sum(1 for r in have if _size_label(r))
    if group != "size" and sized < len(have):
        bullets.append(f"- Size recorded for {_int(sized)} of {_int(len(have))} runs; the rest are listed as size not recorded.")
    srcs = Counter(r.get("ls") for r in have)
    approx = srcs.get("bbox-longest-side", 0)
    if len(have) < len(rows):
        bullets.append(f"- {_int(len(rows) - len(have))} runs have no length in the model and are not counted.")
    head = f"**{_n(tot)} m of {word}** in **{_int(len(have))} runs**" + (f" on {st}" if st else "")
    cal = c.idx.get("calibration") or {}
    chk = None
    if cal.get("length_checked") and cal["length_agree_n"] >= 0.9 * cal["length_checked"]:
        chk = f"The stored lengths match the 3D shape on {_int(cal['length_agree_n'])} of {_int(cal['length_checked'])} runs ({_share(cal['length_agree_n'], cal['length_checked'])})"
    cap = None
    if approx > 0.1 * len(have):
        cap = 80
        bullets.append(f"- {_int(approx)} lengths come from the 3D shape's longest side because the model stores no length for them (diagonal runs read a little long).")
    meas = f"Added the stored length of {_int(len(have))} runs: {_n(tot)} m" + (f" ({', '.join(f'{_n(v)} m {plural(k)}' for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1])[:3])})" if len(by_kind) > 1 else "")
    return _finish(c, head + ".\n" + "\n".join(bullets[:4]) + " {marks}", round(tot, 2), "m", [r["id"] for r in have], [f"{len(have)} runs summed"],
                   found=f"{_int(len(rows))} {word} runs{f' on {st}' if st else ''}, each numbered", measured=meas, checked=chk,
                   cap_pct=cap, cap_reason="Most lengths are stored in the model; some are read from the 3D shape." if cap else None, improve="Ask for an export that includes pipe or duct lengths." if cap else None)


def _sizes_answer(c: _Ctx, subj: list[str], trade: str | None) -> dict:
    rows = _services_for(c, subj or ["pipe", "duct", "cable_tray"], trade)
    rows = [r for r in rows if r["k"] in LINEAR | {"pipe_fitting"}] if not subj else rows
    st, rows, err = _storey_filter(c, rows)
    if err:
        return _finish(c, f"**{err}**", None, None, [], ["level not found"])
    word = _join([plural(s) for s in subj]) if subj else "pipes, ducts and cable trays"
    if not rows:
        return no_services(c, word)
    sized = [r for r in rows if _size_label(r)]
    if not sized:
        return _finish(c, f"**The model does not record a size for its {word}** ({_int(len(rows))} elements). Sizes are not guessed.\n- Check the plumbing, duct or cable-tray schedule from the designer.", None, None,
                       [r["id"] for r in rows], ["0 sizes recorded"], found=f"{_int(len(rows))} {word}; none has a usable size")
    cnt = Counter(_size_label(r) for r in sized)
    def key(k):
        m = re.search(r"(\d+(?:\.\d+)?)", k)
        return float(m.group(1)) if m else 0
    lines = []
    for k, v in sorted(cnt.items(), key=lambda kv: key(kv[0]))[:14]:
        ln = sum(r["L"] for r in sized if _size_label(r) == k and r.get("L"))
        lines.append(f"{k}: {_int(v)}" + (f" ({_n(ln)} m)" if ln else ""))
    head = f"**{_int(len(cnt))} sizes of {word}**" + (f" on {st}" if st else "") + f": {', '.join(lines[:6])}" + (f" and {len(lines) - 6} more" if len(lines) > 6 else "")
    bul = []
    if len(sized) < len(rows):
        bul.append(f"- Size recorded for {_int(len(sized))} of {_int(len(rows))} elements; the others are not guessed.")
    if len(lines) > 6:
        bul.append("- " + ", ".join(lines[6:14]))
    return _finish(c, head + ".\n" + "\n".join(bul) + " {marks}", len(cnt), "count", [r["id"] for r in sized], [f"{len(cnt)} sizes over {len(sized)} elements"],
                   found=f"{_int(len(sized))} {word} with a recorded size, grouped by size",
                   checked="Each size was compared with the element's own 3D cross-section; sizes that do not match were dropped" if any(r.get("ws") for r in sized) else None)


# ---- structure
def _struct_items(c: _Ctx, kind: str):
    idx_rows = {r["id"]: r for r in (c.idx or {}).get("structure", [])} if c.idx else {}
    its = [i for i in c.doc.items if i.kind == kind or (kind == "footing" and i.props.get("ifc_class") in ("IfcFooting", "IfcPile")) or (kind == "member" and i.kind == "member")]
    if kind == "footing":
        its = [i for i in c.doc.items if i.kind in ("footing", "pile") or i.props.get("ifc_class") in ("IfcFooting", "IfcPile")
               or (i.kind in ("wall", "slab", "proxy") and re.search(r"foundation|footing|fundament|perustus|grundmauer|\bpfahl|\bpile\b", f"{i.type_name or ''} {i.name or ''}", re.I))]
    return [(i, idx_rows.get(i.item_id)) for i in its]


def _vol(i) -> float | None:
    for k in ("net_volume_m3", "volume_m3", "gross_volume_m3"):
        v = i.q.get(k)
        if v is not None and float(v) > 1e-6:
            return float(v)
    return None


def _mat_of(i, r) -> str | None:
    return (i.props or {}).get("material") or (r or {}).get("m")


def _struct_answer(c: _Ctx, kinds: list[str], want: str) -> dict | None:
    """kinds: structural kinds asked about; want: count | types | sizes | volume | material | overview."""
    pairs = []
    for k in kinds:
        pairs += [(k, i, r) for i, r in _struct_items(c, k)]
    st = None
    from engine.solvers.filters import storey_requested
    from engine.solvers.solve import resolve_storey
    st = resolve_storey(c.q, c.doc.storeys)
    if st:
        pairs = [p for p in pairs if p[1].storey == st]
    elif storey_requested(c.q):
        return None
    word = _join([plural(k) for k in kinds])
    if not pairs:
        have = Counter(i.kind for i in c.doc.items if i.kind in ("column", "beam", "slab", "wall", "member", "footing", "roof", "stairs"))
        what = ", ".join(f"{_int(v)} {plural(k, v)}" for k, v in have.most_common(4))
        return _finish(c, f"**This model has no {word}{f' on {st}' if st else ''}**." + (f"\n- Its structural-type elements are: {what}." if what else ""), 0, "count", [], [f"0 {word}"],
                       found=f"No {word} exist in the model")
    n = len(pairs)
    ids = [p[1].item_id for p in pairs]
    ty = Counter(clean_type(p[1].type_name or p[1].name) for p in pairs)
    lines = []
    if want in ("types", "overview", "count", "sizes", "material"):
        if want == "sizes":
            g = defaultdict(list)
            for k, i, r in pairs:
                lab = (r or {}).get("sz") or (size_from_name(i.type_name, i.name) or (None,))[0]
                g[lab or "size not recorded"].append(i)
            head = f"**{_int(len(g))} {word.rstrip('s')} size{'s' if len(g) != 1 else ''}** across {_int(n)} {word}" + (f" on {st}" if st else "")
            for lab, its in sorted(g.items(), key=lambda kv: -len(kv[1]))[:8]:
                lines.append(f"- {lab}: {_int(len(its))} ({_share(len(its), n)})")
            unknown = len(g.get("size not recorded", []))
            cap = 85 if unknown > 0.3 * n else None
            return _finish(c, head + ".\n" + "\n".join(lines) + " {marks}", len(g), "count", ids, [f"{len(g)} sizes over {n} elements"],
                           found=f"{_int(n)} {word}, grouped by their section size",
                           checked="Sizes read from each element's stored profile; names are only a fallback" if any((r or {}).get("sz") for _, _, r in pairs) else None,
                           cap_pct=cap, cap_reason=(f"{unknown} of {n} have no stored size." if cap else None), improve="Ask for the structural model or a column schedule." if cap else None)
        if want == "material":
            mt = Counter(_mat_of(i, r) or "material not recorded" for _, i, r in pairs)
            head = f"**{_int(len(mt))} material{'s' if len(mt) != 1 else ''} for the {word}**" + (f" on {st}" if st else "")
            for m, v in mt.most_common(8):
                lines.append(f"- {m}: {_int(v)} ({_share(v, n)})")
            return _finish(c, head + ".\n" + "\n".join(lines) + " {marks}", len(mt), "count", ids, [f"{len(mt)} materials"], found=f"{_int(n)} {word}, grouped by the material stored on each one")
        if len(kinds) > 1 or want == "overview":
            kc = Counter(k for k, _, _ in pairs)
            head = f"**{_int(n)} structural elements**" + (f" on {st}" if st else "") + f": {', '.join(f'{_int(v)} {plural(k, v)}' for k, v in kc.most_common())}"
            for k, v in kc.most_common(5):
                tys = Counter(clean_type(i.type_name or i.name) for kk, i, _ in pairs if kk == k)
                lines.append(f"- {plural(k).capitalize()}: {_int(v)} in {_int(len(tys))} type{'s' if len(tys) != 1 else ''} ({_top(tys, 2)})")
            return _finish(c, head + ".\n" + "\n".join(lines[:4]) + " {marks}", n, "count", ids, [f"{n} structural elements"], found=f"{_int(n)} structural elements (columns, beams, footings and similar), counted from the model")
        if want == "count":
            head = f"**{_int(n)} {plural(kinds[0], n)}**" + (f" on {st}" if st else " in this model")
            lv = Counter(i.storey or "level not recorded" for _, i, _ in pairs)
            if len(lv) > 1 and not st:
                lines.append(f"- By level: {_top(lv, 6)}")
            lines.append(f"- By type: {_top(ty, 4, n)}")
            return _finish(c, head + ".\n" + "\n".join(lines) + " {marks}", n, "count", ids, [f"{n} elements"], found=f"{_int(n)} {plural(kinds[0], n)}, counted element by element")
        head = f"**{_int(n)} {plural(kinds[0], n)} in {_int(len(ty))} type{'s' if len(ty) != 1 else ''}**" + (f" on {st}" if st else "")
        for t, v in ty.most_common(8):
            sub = [(i, r) for _, i, r in pairs if clean_type(i.type_name or i.name) == t]
            sz = Counter((r or {}).get("sz") for i, r in sub if (r or {}).get("sz"))
            m = Counter(_mat_of(i, r) for i, r in sub if _mat_of(i, r))
            ex = (f", {sz.most_common(1)[0][0]}" if sz else "") + (f", {m.most_common(1)[0][0]}" if m else "")
            lines.append(f"- {t}: {_int(v)} ({_share(v, n)}){ex}")
        return _finish(c, head + ".\n" + "\n".join(lines) + " {marks}", len(ty), "count", ids, [f"{len(ty)} types over {n} elements"], found=f"{_int(n)} {word}, grouped by type")
    # volume
    conc_only = bool(CONCRETE.search(c.ql))
    vols = []
    for k, i, r in pairs:
        v = (r or {}).get("v") or _vol(i)
        cf = (r or {}).get("cf")
        if cf is None and r is None:
            cf = 1.0 if CONCRETE.search(f"{(i.props or {}).get('material') or ''} {i.type_name or ''} {i.name or ''}") else None
        vols.append((k, i, r, v, cf))
    have = [x for x in vols if x[3]]
    layered = False
    if conc_only:
        sel = [(k, i, r, v * cf) for k, i, r, v, cf in have if cf]
        layered = any(0 < (cf or 0) < 1 for *_, cf in have)
        unk = [x for x in have if x[4] is None]
        if not sel:
            if unk and len(unk) == len(have):
                return _finish(c, f"**The model does not state the material of its {word}**, so the concrete volume cannot be given. Their total volume is {_n(sum(x[3] for x in have))} m³ (material not stated).", None, None,
                               [x[1].item_id for x in have], ["material not stated"], found=f"{_int(n)} {word}; no material is recorded")
            return _finish(c, f"**No concrete {word} found**: none of the {_int(n)} {word} names concrete as a material.", 0, "m3", [], ["0 concrete elements"], found=f"{_int(n)} {word}; none is concrete")
        note = ""
    else:
        sel = [(k, i, r, v) for k, i, r, v, cf in have]
        note = ""
    tot = sum(x[3] for x in sel)
    by = defaultdict(lambda: [0, 0.0])
    for k, i, r, v in sel:
        by[k][0] += 1; by[k][1] += v
    head = f"**{_n(tot)} m³ of {'concrete in the ' if conc_only else ''}{word}**" + (f" on {st}" if st else "") + f" ({_int(len(sel))} elements)"
    lines = ["- By element: " + "; ".join(f"{plural(k)}: {_n(v[1])} m³ ({_int(v[0])})" for k, v in sorted(by.items(), key=lambda kv: -kv[1][1]))] if len(by) > 1 else []
    miss = n - len(have)
    if miss:
        lines.append(f"- {_int(miss)} of {_int(n)} {word} have no volume in the model and are not included.")
    if conc_only:
        unk_n = len([x for x in have if x[4] is None])
        if unk_n:
            lines.append(f"- {_int(unk_n)} elements name no clear material and are not counted as concrete.")
        if layered:
            lines.append("- Layered elements count only their concrete layers (by layer thickness).")
    cap = 88 if (miss > 0.1 * n or layered or (conc_only and any(x[4] is None for x in have))) else None
    return _finish(c, head + ".\n" + "\n".join(lines) + " {marks}", round(tot, 3), "m3", [x[1].item_id for x in sel], [f"{len(sel)} volumes summed"],
                   found=f"{_int(n)} {word}{f' on {st}' if st else ''}", measured=f"Added the model's own volume of {_int(len(sel))} elements: {_n(tot)} m³",
                   cap_pct=cap, cap_reason=("Volumes are the model's own; some elements have no volume, no clear material, or are layered." if cap else None),
                   improve="Ask for a model with quantity take-off (volumes) and named materials." if cap else None)


def _loadbearing_walls(c: _Ctx) -> dict | None:
    walls = [i for i in c.doc.items if i.kind == "wall" and i.props.get("ifc_class") not in ("IfcWallElementedCase",)]
    st = None
    from engine.solvers.solve import resolve_storey
    st = resolve_storey(c.q, c.doc.storeys)
    if st:
        walls = [w for w in walls if w.storey == st]
    if not walls:
        return None
    flag = [w for w in walls if w.props.get("load_bearing") is not None]
    if not flag:
        return _finish(c, f"**The model does not say which walls are load-bearing**: none of its {_int(len(walls))} walls carries a load-bearing property. This is not guessed.\n- Ask the structural engineer for the structural model.", None, None, [w.item_id for w in walls], ["no load-bearing flag"],
                       found=f"{_int(len(walls))} walls; none has a load-bearing flag")
    yes = [w for w in flag if w.props.get("load_bearing") in (True, "TRUE", "true", 1)]
    no = [w for w in flag if w not in yes]
    vol = lambda ws: sum((_vol(w) or 0) for w in ws)
    head = f"**{_int(len(yes))} of {_int(len(flag))} walls are load-bearing**" + (f" on {st}" if st else "")
    lines = [f"- Not load-bearing: {_int(len(no))}", f"- Wall volume: {_n(vol(yes))} m³ load-bearing, {_n(vol(no))} m³ not" if vol(yes) or vol(no) else ""]
    if len(flag) < len(walls):
        lines.append(f"- {_int(len(walls) - len(flag))} walls carry no load-bearing property and are not counted.")
    return _finish(c, head + ".\n" + "\n".join(x for x in lines if x) + " {marks}", len(yes), "count", [w.item_id for w in yes], [f"{len(yes)} load-bearing of {len(flag)}"],
                   found=f"{_int(len(flag))} walls with a load-bearing property; {_int(len(yes))} are marked load-bearing")


def answer(question: str, doc, t0) -> dict | None:
    """Building services and structure by code, or None when the question is something else (the existing routes then run unchanged)."""
    if getattr(doc, "mode", None) != "ifc":
        return None
    ql = " ".join(question.lower().split())
    if re.search(r"\bfloor plan\b|\bon the plan\b|\bsheet\b", ql):
        return None
    subj = _subjects(ql)
    trade = next((t for t, rx in TRADES if re.search(rx, ql)), None)
    generic = bool(MEP_GENERIC.search(ql))
    ssub = [k for k, rx in STRUCT_SUBJECTS if re.search(rx, ql)]
    sgen = bool(STRUCT_GENERIC.search(ql))
    asks = bool(re.search(r"\bhow many\b|\bhow much\b|\bwhat\b|\bwhich\b|\bwhere\b|\blist\b|\bshow\b|\bnumber\b|\btotal\b|\bare there\b|\bis there\b|\bany\b|\bgive\b|\bbreakdown\b|\bsummar|\boverview|\bdescribe|\btell\b|\bcount\b|\bcould you\b|\bcan you\b|\bprovide\b", ql))
    if not asks:
        return None
    if re.search(r"\b(?:remove|delete|hide|isolate|highlight|add|move|resize|change)\b", ql):
        return None
    # locations, areas and finish take-offs belong to the room / take-off routes, which carry their own boxes
    if re.search(r"\bwhere\b|\bm2\b|m\u00b2|\bsq\.? ?(?:m|ft)\b|\btiles?\b|\btiling\b|\bflooring\b|\bpaint\w*\b|\bwaste allowance\b|\b\d+ ?% (?:waste|extra)", ql):
        return None
    if re.search(r"\b(?:capacit\w*|loads?|kw|kwh|watts?|power rating|flow rates?|pressure|voltage|specifications?|maintenance|cost|price|energy|efficien\w*|concept|span|spans|spanning|grid|inferred|estimate|compliant|compliance|code|rooms?|apartment|unit [a-z]?\d+|duplex [ab]|located|location|wattage|ampere\w*|cross[- ]sectional|area|u-?value|thermal)\b", ql):
        return None
    mep_q = bool(subj or generic or trade) and not (ssub and not (subj or generic))
    # ---- structure first when a structural word leads
    if (ssub or sgen or (VOLUME_Q.search(ql) and CONCRETE.search(ql))) and not (subj and not ssub and not sgen):
        idx = load_index(doc)
        c = _Ctx(question, doc, t0, idx)
        if re.search(r"\bload[- ]?bearing\b", ql) and re.search(r"\bwalls?\b", ql):
            return _loadbearing_walls(c)
        if not ssub and re.search(r"\broofs?\b|\bwalls?\b", ql) and not (VOLUME_Q.search(ql) and CONCRETE.search(ql)):
            return None  # roof and wall questions are not about the frame; the other routes answer them
        if re.search(r"\b(?:spans?|load path|structural grid|embodied carbon|efficiency|concept|structural analysis|capacity|capacities|design load)\b", ql):
            return None
        kinds = ssub or (["column", "beam", "member", "footing"] if sgen else [])
        if not kinds and VOLUME_Q.search(ql) and CONCRETE.search(ql):
            named = [k for k, rx in (("slab", r"\bslabs?\b|\bfloors?\b|\bdecks?\b"), ("wall", r"\bwalls?\b")) if re.search(rx, ql)]
            kinds = named or ["column", "beam", "footing", "slab", "wall"]
        if "slab" in kinds or re.search(r"\bslabs?\b", ql) and not ssub:
            if CONCRETE.search(ql) and re.search(r"\bslabs?\b", ql):
                kinds = list(dict.fromkeys(kinds + ["slab"]))
            else:
                return None if not ssub else None
        if "wall" in kinds and not ssub:
            pass
        want = ("volume" if VOLUME_Q.search(ql) else "sizes" if SIZES_Q.search(ql) else "material" if MATERIAL_Q.search(ql) else "types" if TYPES_Q.search(ql) else
                "count" if COUNT_Q.search(ql) and len(kinds) == 1 else "overview" if (len(kinds) != 1 or OVERVIEW_Q.search(ql)) else "types")
        if re.search(r"\bhow many\b", ql) and len(kinds) == 1 and want == "types" and not re.search(r"\btypes?\b|\bby type\b|\bkinds?\b", ql):
            want = "count"
        if want == "count" and re.search(r"\bhow many\b", ql) and not re.search(r"\blevel|floor|storey|story|type|kind", ql) and idx is None:
            return None
        if kinds == ["column", "beam", "footing", "slab", "wall"] and want != "volume":
            want = "overview"
        if not kinds:
            return None
        return _struct_answer(c, kinds, want)
    if not mep_q:
        return None
    idx = load_index(doc)
    if idx is None:
        return None
    if not idx["services"] and subj and _kinds_of(subj) <= AMBIGUOUS_FIXTURES and not trade:
        return None  # an architectural model draws toilets and basins as fixtures or rooms; the existing routes know them
    c = _Ctx(question, doc, t0, idx)
    only_groups = [s for s in subj]
    if SIZES_Q.search(ql) and (subj and set(subj) <= {"pipe", "duct", "cable_tray", "conduit"}):
        return _sizes_answer(c, subj, trade)
    if _length_requested(ql) and (set(subj) & {"pipe", "duct", "cable_tray", "conduit"}):
        return _length_answer(c, subj, trade)
    if LENGTH_Q.search(ql) and not subj and re.search(r"\bpip|\bduct|\bcabl", ql) is None and not generic:
        return None
    if (generic or (trade and not subj)) and (SYSTEMS_Q.search(ql) or COUNT_Q.search(ql) or OVERVIEW_Q.search(ql) or re.search(r"\bbreakdown\b|\bcomponents?\b|\bequipment\b|\bwhich\b|\bwhat\b", ql)):
        if SYSTEMS_Q.search(ql) or not subj:
            return _systems_answer(c, subj, trade)
    if SYSTEMS_Q.search(ql) and not subj and re.search(r"\b(?:what|which|list|show|name|how many|number of)\b.{0,20}\bsystems?\b|\bsystems? (?:are|is|does|do|exist|present|installed|modelled)\b|\bby system\b", ql) and not re.search(r"\b(?:structural|structure|load|door|window|fire|safety|compliance|egress)\b", ql) and c.idx["services"]:
        return _systems_answer(c, subj, trade)
    if only_groups:
        if TYPES_Q.search(ql) and not re.search(r"\bhow many\b", ql):
            return _types_answer(c, subj, trade)
        if COUNT_Q.search(ql) or BYLEVEL_Q.search(ql):
            return _count_answer(c, subj, trade)
        if TYPES_Q.search(ql) or OVERVIEW_Q.search(ql) or re.search(r"\bwhich\b|\bwhat\b|\blist\b|\bwhere\b|\bshow\b", ql):
            return _types_answer(c, subj, trade)
    if trade and COUNT_Q.search(ql):
        return _count_answer(c, subj, trade)
    return None
