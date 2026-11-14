"""Per-document folder / discipline / date metadata, derived from the registry record (stdlib only).

derive(rec) -> {project, folder_path, folder, discipline, subdiscipline, date, sheet}
  rec: a registry row ({doc_id, source, title, kind, files, ...}); nothing is read from disk, so the deployed API
  (no dataset, no numpy) can call it too.
  folder_path : ["Sports Complex", "MEP", "Plumbing"]  (Project > Discipline [> Sub-discipline]); folder is "A/B/C"
  discipline  : Architecture | Structural | MEP | Civil | General | Floor plans | Drawings | Reference drawings
  subdiscipline: Plumbing | Ventilation | Heating | Electrical | Fire protection | None (MEP only)
  date        : ISO yyyy-mm-dd taken from the issue folder / file name (opening_design Transfer folders), else None
  sheet       : normalised sheet code ("A504", "S401", "P105") when the file name carries one, else None
Sources and how they are filed (documented in docs/API.md):
  opening_design : project = first folder under opening_design/; discipline = sheet-code letter (A/S/M/P/E/C...), else
                   keywords in file name, then folder names, else Architecture.
  ifc_bench      : project = id minus the -arc/-str/-plumbing/... suffix; discipline = that suffix.
  ifc_models     : project = file name up to the first "_"; discipline = tokens of the name.
  everything else: project = the dataset's name; discipline "Floor plans" or "Reference drawings".
"""
from __future__ import annotations

import re
from datetime import date

SHEET_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{1,2})[-_ ]?(\d{1,2}[-_]\d{2}|\d{3,4})(?:[-_ ]?([A-Z]))?(?![0-9A-Za-z])")
DATE_RE = re.compile(r"(?<!\d)(20[0-2]\d)[-._ ]?(0[1-9]|1[0-2])[-._ ]?(0[1-9]|[12]\d|3[01])(?!\d)")
SHEET_DISC = {"A": ("Architecture", None), "I": ("Architecture", None), "S": ("Structural", None), "C": ("Civil", None),
              "L": ("Civil", None), "G": ("General", None), "P": ("MEP", "Plumbing"), "M": ("MEP", "Ventilation"),
              "E": ("MEP", "Electrical"), "F": ("MEP", "Fire protection"), "H": ("MEP", "Heating")}
KEYWORDS = [  # first match wins; applied to lower-cased text
    (r"structur|struct\b|foundation|framing|footing|truss|\bbeam|rebar|bracing|joist", ("Structural", None)),
    (r"plumb|sanitary|riser|domestic water|waste", ("MEP", "Plumbing")),
    (r"hvac|ventilat|duct|mechanical|furnace|\bahu\b", ("MEP", "Ventilation")),
    (r"heating|boiler|radiant|hydronic", ("MEP", "Heating")),
    (r"electric|lighting|panel schedule|\bmep\b", ("MEP", "Electrical")),
    (r"civil|grading|erosion|stormwater|storm water|survey|topograph|site plan|diagrammatic site", ("Civil", None)),
]
IFC_SUFFIX = {"arc": ("Architecture", None), "ar": ("Architecture", None), "architectural": ("Architecture", None),
              "str": ("Structural", None), "structural": ("Structural", None),
              "plumbing": ("MEP", "Plumbing"), "ventilation": ("MEP", "Ventilation"), "heating": ("MEP", "Heating"),
              "electrical": ("MEP", "Electrical"), "mep": ("MEP", None), "hvac": ("MEP", "Ventilation"),
              "facade": ("Architecture", None), "kitchen": ("Architecture", None)}
SOURCE_LABEL = {"cubicasa5k": "CubiCasa5K", "swiss_dwellings": "Swiss Dwellings", "habs": "HABS",
                "wikimedia": "Wikimedia Commons", "finna": "Finna", "europeana": "Europeana"}
SOURCE_DISC = {"cubicasa5k": "Floor plans", "swiss_dwellings": "Floor plans"}


def parse_date(text: str) -> str | None:
    m = DATE_RE.search(text or "")
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    except ValueError:
        return None


def sheet_code(name: str) -> str | None:
    """Sheet code from a file name; case-sensitive so 'v1-03' and 'cafe 2019' do not match."""
    for m in SHEET_RE.finditer(name or ""):
        letters, num, suffix = m[1], m[2], m[3]
        if letters in ("V", "OX", "XX"):
            continue
        return f"{letters}{re.sub('[-_]', '', num)}{suffix or ''}"
    return None


def _by_keywords(text: str):
    t = (text or "").lower()
    for pat, res in KEYWORDS:
        if re.search(pat, t):
            return res
    return None


def _tidy(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("_", " ")).strip()


def _opening_design(rec: dict) -> dict:
    files = rec.get("files") or {}
    path = next(iter(files.values()), "") or ""
    parts = path.split("/")
    i = parts.index("opening_design") if "opening_design" in parts else 1
    project = _tidy(parts[i + 1]) if len(parts) > i + 2 else _tidy(rec["doc_id"].split("__", 1)[-1].split("-transfer")[0])
    folders = parts[i + 2:-1]
    fname = parts[-1].rsplit(".", 1)[0] if parts else rec.get("title", "")
    dt = None
    for comp in reversed(folders):  # issue folder (deepest first), then file name
        dt = parse_date(comp[:12]) or None
        if dt:
            break
    dt = dt or parse_date(fname[:12])
    code = sheet_code(fname)
    disc = SHEET_DISC.get(code[0]) if code and code[0] in SHEET_DISC and (len(code) > 3) else None
    disc = disc or _by_keywords(fname) or _by_keywords(" ".join(folders)) or ("Architecture", None)
    return {"project": project, "discipline": disc[0], "subdiscipline": disc[1], "date": dt, "sheet": code}


def _ifc_bench(rec: dict) -> dict:
    slug = rec["doc_id"].split("__", 1)[-1]
    head, _, tail = slug.rpartition("-")
    if head and tail in IFC_SUFFIX:
        disc, project = IFC_SUFFIX[tail], head
    else:
        disc, project = (_by_keywords(slug.replace("-", " ")) or ("Architecture", None)), slug
    return {"project": _tidy(project.replace("-", " ")).title(), "discipline": disc[0], "subdiscipline": disc[1],
            "date": None, "sheet": None}


def _ifc_models(rec: dict) -> dict:
    files = rec.get("files") or {}
    path = next(iter(files.values()), "") or ""
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0] or rec["doc_id"].split("__", 1)[-1]
    if "_" in stem:
        project, name = stem.split("_", 1)
    else:
        project, _, name = stem.partition("-")
        project = stem if not name else project
        name = name or stem
    project = re.sub(r"[-_ ]\d+$", "", project) if project.lower().startswith("resbim") else project
    toks = set(re.split(r"[-_ ]", name.lower()))
    disc = next((IFC_SUFFIX[t] for t in toks if t in IFC_SUFFIX), None)
    low = name.lower()
    if disc is None:
        if re.search(r"(^|[-_])plan([-_]|$)", low):
            disc = ("Floor plans", None)
        elif re.search(r"elevation|section", low):
            disc = ("Drawings", None)
        else:
            disc = _by_keywords(low.replace("-", " ")) or ("Architecture", None)
    return {"project": _tidy(project.replace("-", " ")).title() if project.islower() else _tidy(project),
            "discipline": disc[0], "subdiscipline": disc[1], "date": None, "sheet": None}


def derive(rec: dict) -> dict:
    src = rec.get("source") or rec["doc_id"].split("__", 1)[0]
    if src == "opening_design":
        m = _opening_design(rec)
    elif src == "ifc_bench":
        m = _ifc_bench(rec)
    elif src == "ifc_models":
        m = _ifc_models(rec)
    else:
        m = {"project": SOURCE_LABEL.get(src, _tidy(src).title()),
             "discipline": SOURCE_DISC.get(src, "Reference drawings"), "subdiscipline": None, "date": None, "sheet": None}
    fp = [m["project"], m["discipline"]] + ([m["subdiscipline"]] if m["subdiscipline"] else [])
    m["folder_path"] = fp
    m["folder"] = "/".join(fp)
    return m


def folder_tree(metas: list[dict]) -> dict:
    """metas: derive() outputs (one per document). -> {"total", "folders": [{name, path, count, children}]} sorted by name."""
    root: dict = {"children": {}, "count": 0}
    for m in metas:
        node = root
        node["count"] += 1
        for depth, name in enumerate(m["folder_path"]):
            node = node["children"].setdefault(name, {"children": {}, "count": 0})
            node["count"] += 1

    def out(children: dict, prefix: list[str]) -> list[dict]:
        res = []
        for name in sorted(children, key=str.lower):
            c = children[name]
            res.append({"name": name, "path": "/".join(prefix + [name]), "count": c["count"],
                        "children": out(c["children"], prefix + [name])})
        return res

    return {"total": root["count"], "folders": out(root["children"], [])}


# ---- version series lookup (reads artifacts/series/*.json written by `python -m pipeline.series`; stdlib only) ----
_SER: dict = {"key": None, "by_doc": {}}


def _series_index(art=None) -> dict:
    import json
    import os
    from pathlib import Path
    d = Path(art or os.environ.get("ARTIFACTS_DIR") or Path(__file__).resolve().parent.parent / "artifacts") / "series"
    files = sorted(d.glob("*.json")) if d.is_dir() else []
    key = (str(d), tuple((f.name, f.stat().st_mtime_ns) for f in files))
    if _SER["key"] != key:
        by_doc: dict = {}
        for f in files:
            try:
                s = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            for n, v in enumerate(s.get("versions") or [], 1):
                by_doc[v["doc_id"]] = {"series_id": s["series_id"], "title": s.get("title"), "index": n,
                                       "count": len(s["versions"]), "versions": s["versions"]}
        _SER.update(key=key, by_doc=by_doc)
    return _SER["by_doc"]


def series_of(doc_id: str, art=None) -> dict | None:
    """{series_id, title, index (1-based), count, versions:[{doc_id, date, label, ...}]} or None when the doc is in no series."""
    return _series_index(art).get(doc_id)


def latest_version(doc_id: str, art=None) -> str:
    """doc_id of the newest version in the doc's series, or doc_id itself when it has no series."""
    s = series_of(doc_id, art)
    return s["versions"][-1]["doc_id"] if s else doc_id


def older_versions(doc_id: str, art=None) -> list[dict]:
    """Versions of the series other than doc_id's latest (empty when no series): [{doc_id, date, label}]."""
    s = series_of(doc_id, art)
    return [v for v in s["versions"][:-1]] if s else []
