"""Document role + storey level for the files of a project (no model call, no per-file rules).

  classify(doc, root=None) -> {role, level, confidence}
    doc  : a registry-style dict {doc_id, title, kind, formats, files?}; only doc_id is required when `root` holds its folder.
    role : model | plan | section | elevation | detail | schedule | scan | photo | spec | revision | other
    level: free-text storey name as printed or modelled ("Erdgeschoss", "Level 2", "Basement"), or None.

Evidence order (first that decides wins, all general):
  1. IFC -> model (its storeys live in the model; level None).
  2. PDF hook `pipeline.pdf_sheet.classify(doc_id, root)` when that module exists.
  3. what the file itself says: CAD layer names (DXF), the text layer (sheet titles, "SECTION", "SCHEDULE"), the plan map
     (walls/rooms/doors found), the image statistics (paper-like drawing vs photograph).
  4. words in the title / id in English, German, Finnish, Swedish, French, Italian, Spanish.
Levels come from the plan map's own storey, else from the sheet text / title using the multilingual patterns below.
`level_ordinal` turns a level phrase into a comparable number (basement -1, ground 0, upper +n, attic 99) so that
"Ground floor" on a sheet and "Erdgeschoss" in a model line up.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROLES = ("model", "plan", "section", "elevation", "detail", "schedule", "scan", "photo", "spec", "revision", "other")

# ---------------------------------------------------------------------------------------------------- words per role
_W = {
    "section": r"sections?|schnitte?|sektio|leikkaus|leikkaukset|coupes?|sezione|sezioni|corte|cortes|snitt|doorsneden?|secci[oó]n",
    "elevation": r"elevations?|ansichten?|julkisivu\w*|fa[cç]ades?|fasad\w*|prospett[oi]|alzados?|gevel\w*|vue en fa[cç]ade",
    "detail": r"details?|detalj\w*|detalles?|dettagli\w*|yksityiskohta|d[eé]tails?",
    "schedule": r"schedules?|tabelle|taulukko|luettelo|luettelot|liste|listen|lista|tabla|tabella|tableau|bill of quantities|boq|"
                r"ovilista|ikkunalista|quantit(?:y|ies)|mengen",
    "spec": r"specifications?|specs?|spezifikation|leistungsbeschreibung|leistungsverzeichnis|beschreibung|selite|kuvaus|"
            r"notes?|report|memo|minutes|handbook|manual|requirements?|standards?|regulations?|contract|guidelines?|"
            r"readme|erkl[aä]rung|rakennusselostus|description",
    "revision": r"revisions?|revised|supersed\w*|rev\.?\s*[a-z0-9]{1,2}|version\s*\d+|v\d+(?:\.\d+)?|"
                r"[aä]nderung\w*|muutos\w*|issue\s*\d+",
    "photo": r"photos?|photograph\w*|fotos?|valokuva\w*|pictures?|img[_ -]?\d+|dsc[_ -]?\d+|snapshot|site visit|"
             r"jobsite|site photo|selfie",
    "scan": r"scans?|scanned|skannaus|gescannt|scansione|escaneado",
    "plan": r"plans?|grundrisse?|grundriss|pohjapiirro\w*|pohja|planta|plantas|pianta|piante|plattegrond|plan de|"
            r"floor ?plans?|layout|asemapiirros|ground floor|first floor|level \d|storey|story|floor|geschoss|kerros|krs",
}
_ROLE_ORDER = ("revision", "section", "elevation", "detail", "schedule", "photo", "scan", "spec", "plan")
_ROLE_RX = {r: re.compile(rf"(?<![A-Za-z0-9])(?:{w})(?![A-Za-z0-9])", re.I) for r, w in _W.items()}

# CAD layer words (A-WALL, A-SECT, 'Elevation-North', 'DETL'...)
_LAYER_HINT = {
    "section": re.compile(r"sect|schnitt|leikkaus|coupe", re.I),
    "elevation": re.compile(r"elev|ansicht|julkisivu|facade|fa[cç]ade", re.I),
    "detail": re.compile(r"detl|detail", re.I),
    "plan": re.compile(r"wall|door|window|room|space|stair|furn|a-(?:wall|door|glaz|flor)|sein[aä]|ovi|ikkuna|wand|t[uü]r|fenster|mur|porte", re.I),
}

# ---------------------------------------------------------------------------------------------------- levels
_NUMWORD = {"ground": 0, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
            "eighth": 8, "ninth": 9, "tenth": 10}
_LEVEL_RES = [  # (regex, normaliser) ; the earliest match in the text wins
    (re.compile(r"(?<![\w.])(\d{1,2})\s*\.\s*(?:og|obergeschoss)\b", re.I), lambda m: f"{m[1]}. Obergeschoss"),
    (re.compile(r"\b(?:og|obergeschoss)\s*(\d{1,2})\b", re.I), lambda m: f"{m[1]}. Obergeschoss"),
    (re.compile(r"\b(erdgeschoss|erdgeschoß)\b|(?<![\w.])eg(?![\w])", re.I), lambda m: "Erdgeschoss"),
    (re.compile(r"\b(untergeschoss|kellergeschoss|keller|souterrain)\b", re.I), lambda m: m[1].capitalize()),
    (re.compile(r"\b(dachgeschoss|dachgeschoß)\b", re.I), lambda m: "Dachgeschoss"),
    (re.compile(r"(?<![\w.])(\d{1,2})\s*\.?\s*(?:kerros|krs|kerr)\b", re.I), lambda m: f"{m[1]}. kerros"),
    (re.compile(r"\b(kellari(?:kerros)?|ullakko|vinttikerros|alakerta|yl[aä]kerta)\b", re.I), lambda m: m[1].capitalize()),
    (re.compile(r"\b(ground|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d{1,2}(?:st|nd|rd|th))"
                r"\s+(?:floor|level|storey|story)\b", re.I), lambda m: f"{m[1].capitalize()} floor"),
    (re.compile(r"\b(floor|level|lvl|storey|story)\s*[-_ ]?\s*(-?\d{1,2})\b", re.I),
     lambda m: f"{'Floor' if m[1].lower() == 'floor' else 'Level'} {m[2]}"),
    (re.compile(r"(?<![\w.])L\s?(-?\d{1,2})(?![\w.])"), lambda m: f"Level {m[1]}"),
    (re.compile(r"\b(sub-?basement|basement|cellar|mezzanine|penthouse|attic|roof(?:\s+(?:level|plan))?)\b", re.I),
     lambda m: m[1].capitalize()),
    (re.compile(r"\b(piano\s+terra|piano\s+\d{1,2}|planta\s+baja|planta\s+\d{1,2}|rez[- ]de[- ]chauss[eé]e|[eé]tage\s+\d{1,2}|"
                r"sous-sol|niveau\s+\d{1,2}|v[aå]ning\s+\d{1,2}|s[oó]tano)\b", re.I), lambda m: m[1].capitalize()),
]


def level_from_text(text: str | None) -> str | None:
    """The storey a title / sheet text names, as printed (normalised spelling), or None."""
    t = text or ""
    best = None
    for rx, norm in _LEVEL_RES:
        m = rx.search(t)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), norm(m))
    return best[1] if best else None


def level_ordinal(text: str | None) -> int | None:
    """Comparable floor number of a level phrase: basement -1, ground 0, upper +n, attic/roof 99; None when unknown.
    Conventions are the written ones of each language: German 1. OG = +1, English 'first floor' = +1, Finnish 1. kerros = ground."""
    t = (text or "").casefold().strip()
    if not t:
        return None
    n = re.search(r"-?\d+", t)
    num = int(n[0]) if n else None
    if re.search(r"\b(?:dachgeschoss|dachgeschoß|attic|roof|ullakko|vinttikerros|penthouse|sottotetto)\b", t):
        return 99
    if re.search(r"\b(?:basement|cellar|keller\w*|untergeschoss|souterrain|kellari\w*|s[oó]tano|sous-sol|interrato|k[aä]llare)\b", t):
        return -(num if num and num > 0 and re.search(r"sub|\bug\b|basement\s*\d|\d\.?\s*(?:ug|basement)", t) else 1)
    if re.search(r"\b(?:erdgeschoss|erdgeschoß|ground|piano terra|planta baja|rez[- ]de[- ]chauss[eé]e|alakerta|terra)\b|^eg$", t) \
            and not re.search(r"\b(?:first|second|\d)\b", t.replace("ground floor", "")):
        return 0
    if re.search(r"obergeschoss|\bog\b", t) and num is not None:
        return num
    if re.search(r"kerros|\bkrs\b|kerr\b", t) and num is not None:
        return max(num - 1, 0) if num >= 1 else num
    m = re.search(r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\b", t)
    if m:
        return _NUMWORD[m[1]]
    if re.search(r"(?:\d)(?:st|nd|rd|th)\b", t) and num is not None:
        return num
    if re.search(r"\b(?:level|lvl|floor|storey|story|piano|planta|[eé]tage|niveau|v[aå]ning|l)\b|^l\s?-?\d", t) and num is not None:
        return num
    if re.fullmatch(r"-?\d{1,2}", t):
        return int(t)
    return None


# ---------------------------------------------------------------------------------------------------- reading files
def _json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _meta(doc: dict, root: Path | None) -> dict:
    d = dict(doc or {})
    if root is not None and d.get("doc_id"):
        stored = _json(Path(root) / d["doc_id"] / "doc.json") or {}
        for k, v in stored.items():
            d.setdefault(k, v)
    return d


def dxf_layers(path: Path, limit_bytes: int = 6_000_000) -> list[str]:
    """Layer names used by a DXF (entity group code 8, and LAYER table entries), read from the first few MB, ASCII only."""
    names: dict[str, int] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            read = 0
            code = None
            for line in f:
                read += len(line)
                if read > limit_bytes:
                    break
                s = line.strip()
                if code is None:
                    code = s
                    continue
                if code == "8" and s:
                    names[s] = names.get(s, 0) + 1
                code = None
    except OSError:
        return []
    return sorted(names, key=lambda k: -names[k])


def _structure_counts(doc_id: str, root: Path) -> dict:
    """Items of the plan map by kind (no heavy load): {wall: n, room: n, ...}."""
    out: dict[str, int] = {}
    for p in sorted(Path(root, doc_id).glob("planmap-[0-9]*.json")):
        m = _json(p) or {}
        for it in m.get("items") or []:
            if isinstance(it, dict):
                out[it.get("kind") or "other"] = out.get(it.get("kind") or "other", 0) + 1
    return out


def _planmap_storey(doc_id: str, root: Path) -> str | None:
    seen: dict[str, int] = {}
    for p in sorted(Path(root, doc_id).glob("planmap-[0-9]*.json")):
        m = _json(p) or {}
        st = m.get("storey")
        name = st.get("name") if isinstance(st, dict) else st if isinstance(st, str) else None
        if name:
            seen[name] = seen.get(name, 0) + 1
    return max(seen, key=seen.get) if len(seen) == 1 else None


def _text_words(doc_id: str, root: Path, pages: int = 2, limit: int = 600) -> str:
    out: list[str] = []
    for n in range(1, pages + 1):
        t = _json(Path(root, doc_id, f"text-{n}.json"))
        if t:
            out += [w.get("text", "") for w in (t.get("words") or [])[:limit] if isinstance(w, dict)]
    return " ".join(out)


def _plain_text(doc_id: str, root: Path, meta: dict) -> str:
    """First ~4 KB of a plain-text style file (txt, md, csv) that belongs to the doc, else ''."""
    for k, v in (meta.get("files") or {}).items():
        if str(k).lower() in ("txt", "md", "csv", "text", "tsv", "json"):
            for base in (Path(root).parent, Path(root)):
                p = base / str(v)
                if p.is_file():
                    try:
                        return p.read_text(encoding="utf-8", errors="ignore")[:4000]
                    except OSError:
                        pass
    for p in Path(root, doc_id).glob("*.txt"):
        try:
            return p.read_text(encoding="utf-8", errors="ignore")[:4000]
        except OSError:
            continue
    return ""


def _looks_tabular(text: str) -> bool:
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) < 4:
        return False
    sep = sum(1 for l in lines if l.count(",") >= 2 or l.count("\t") >= 2 or l.count(";") >= 2 or l.count("|") >= 2)
    return sep / len(lines) > 0.6


def _image_kind(doc_id: str, root: Path) -> str | None:
    """'photo' for a colourful, dark-ish picture; 'drawing' for paper-like line art; None when unreadable.
    Two numbers only: share of light pixels and mean saturation of the page image."""
    p = next((q for q in (Path(root, doc_id, "page-1.thumb.png"), Path(root, doc_id, "page-1.png")) if q.is_file()), None)
    if p is None:
        return None
    try:
        from PIL import Image
        import numpy as np
        im = Image.open(p).convert("RGB")
        im.thumbnail((160, 160))
        a = np.asarray(im, dtype=np.float32) / 255.0
        lum = a.mean(axis=2)
        sat = (a.max(axis=2) - a.min(axis=2))
        light = float((lum > 0.72).mean())
        colour = float(sat.mean())
        mid = float(((lum > 0.2) & (lum < 0.8)).mean())
        if light < 0.45 or (colour > 0.18 and mid > 0.55):
            return "photo"
        return "drawing"
    except Exception:  # noqa: BLE001
        return None


def _title_role(text: str) -> str | None:
    """Role named by a title / id (first word class that matches, in a fixed order that favours the specific over the general)."""
    t = re.sub(r"[_\-.]+", " ", text or "")
    for r in _ROLE_ORDER:
        if _ROLE_RX[r].search(t):
            return r
    return None


def classify(doc: dict, root: Path | str | None = None) -> dict:
    """Role + level of one document. Never raises; unknown -> role 'other', confidence low."""
    try:
        return _classify(doc, Path(root) if root is not None else _default_root())
    except Exception:  # noqa: BLE001
        return {"role": "other", "level": None, "confidence": 0.1}


def _default_root() -> Path:
    import os
    from engine.solvers import ARTIFACTS
    return Path(os.environ.get("ARTIFACTS_DIR") or ARTIFACTS)


def _classify(doc: dict, root: Path) -> dict:
    meta = _meta(doc, root)
    doc_id = meta.get("doc_id") or ""
    title = str(meta.get("title") or "")
    kind = str(meta.get("kind") or "").lower()
    formats = [str(f).lower() for f in (meta.get("formats") or [])]
    folder = Path(root, doc_id) if doc_id else None
    has = (lambda name: bool(folder and (folder / name).exists()))
    if kind == "ifc" or "ifc" in formats or has("elements.json"):
        return {"role": "model", "level": None, "confidence": 0.99}

    # a per-storey sheet generated from / belonging to a model: its level is the storey in its title
    sheet_level = None
    try:
        from engine.solvers.data import load_sheet_parent
        sp = load_sheet_parent(doc_id, root) if doc_id and folder and folder.is_dir() else None
        if sp is not None and sp.storeys:
            sheet_level = sp.storeys[0]["name"] if len(sp.storeys) == 1 else None
    except Exception:  # noqa: BLE001
        sp = None

    hook = None
    try:
        import importlib
        mod = importlib.import_module("pipeline.pdf_sheet")      # Awais owns this module; absent -> heuristics below
        fn = getattr(mod, "classify", None)
        if fn and (kind == "pdf" or "pdf" in formats):
            hook = fn(doc_id, root)
    except Exception:  # noqa: BLE001
        hook = None
    if isinstance(hook, dict) and hook.get("role") in ROLES:
        return {"role": hook["role"], "level": hook.get("level") or level_from_text(title), "confidence": 0.9}

    structure = _structure_counts(doc_id, root) if folder else {}
    walls_rooms = structure.get("wall", 0) + structure.get("room", 0)
    text = _text_words(doc_id, root) if folder else ""
    plain = _plain_text(doc_id, root, meta) if folder else ""
    head = f"{title} {doc_id.split('__', 1)[-1]}"
    by_title = _title_role(head)

    # plain text files: schedules are tables, everything else is a specification / note
    if kind in ("text", "txt", "md", "csv", "spec") or (formats and set(formats) <= {"txt", "md", "csv", "tsv", "text"}):
        role = "schedule" if (by_title == "schedule" or _looks_tabular(plain)) else "spec"
        return {"role": role, "level": level_from_text(title), "confidence": 0.8}

    level = _planmap_storey(doc_id, root) or sheet_level
    level = level or level_from_text(title) or level_from_text(text[:2000])

    # CAD: layer names decide the sheet type when the title does not
    if kind in ("dxf", "dwg") or {"dxf", "dwg"} & set(formats):
        role = by_title if by_title in ("section", "elevation", "detail", "schedule", "spec", "revision") else None
        conf = 0.8
        if role is None:
            dxf = next((Path(str(v)) for k, v in (meta.get("files") or {}).items() if str(k).lower() == "dxf"), None)
            cand = [dxf] if dxf else []
            cand += [Path(root).parent / str(dxf)] if dxf and not dxf.is_absolute() else []
            layers = next((dxf_layers(p) for p in cand if p.is_file()), [])
            votes = {r: sum(1 for l in layers if rx.search(l)) for r, rx in _LAYER_HINT.items()}
            role = max(("section", "elevation", "detail"), key=lambda r: votes[r]) if max(votes["section"], votes["elevation"], votes["detail"]) >= 2 \
                else ("plan" if (votes["plan"] or walls_rooms or by_title == "plan") else (by_title or "plan"))
            conf = 0.7
        return {"role": role, "level": None if role in ("section", "elevation") else level, "confidence": conf}

    # drawn sheets (PDF / raster): title first, then the sheet's own text, then what was found in it
    word_role = _title_role(text[:1500]) if text else None
    if by_title in ("section", "elevation", "detail", "schedule", "spec", "photo", "revision"):
        role, conf = by_title, 0.8
    elif word_role in ("section", "elevation", "detail", "schedule") and walls_rooms < 6:
        role, conf = word_role, 0.65
    elif walls_rooms >= 6 or sp is not None or by_title == "plan":
        role, conf = "plan", 0.85 if walls_rooms >= 6 else 0.7
    elif kind in ("raster",) or {"png", "jpg", "jpeg"} & set(formats):
        img = _image_kind(doc_id, root)
        role, conf = ("photo", 0.6) if img == "photo" else ("scan", 0.5)
    elif kind == "pdf":
        role, conf = ("spec", 0.5) if len(text.split()) > 150 and not structure else ("other", 0.3)
    else:
        role, conf = "other", 0.3
    # a scan / photo is a picture of something: keep 'scan' when it carries a plan map but the title says scan
    if role == "plan" and by_title == "scan":
        role = "scan"
    if role in ("section", "elevation"):
        level = None                                   # these sheets span the whole height; their text names every level
    elif role in ("photo", "spec", "schedule"):
        level = level_from_text(title)
    return {"role": role, "level": level, "confidence": conf}
