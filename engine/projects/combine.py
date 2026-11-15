"""Combine the documents of a project into ONE consistent picture, without double counting.

The same building often arrives in several formats (an IFC model, plan sheets of its levels, scans, a second IFC variant).
Adding all of them would count every door twice. The rule, used by the project overview and by multi-document answers:

  buildings : IFC models of the same building form one group (same building name, or the same storeys at the same
              elevations). Different buildings are separate groups and ARE added together.
  levels    : each group has one row per storey. A plan sheet / scan is placed on the row its level text names
              (exact name, the storey alias rules of the solver, or the same floor number).
  source    : per level and kind (rooms, doors, windows) the model wins, the sheet is a cross-check. Without a model the
              sheet with the most items is used. A source with no item of that kind anywhere is never the source.
  totals    : sum over groups and levels of the chosen values only.
Nothing here calls a model. Counts and areas come from the same item lists the single-document solvers use.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from engine.projects.roles import classify, level_from_text, level_ordinal

KINDS = ("room", "door", "window")
PLURAL = {"room": "rooms", "door": "doors", "window": "windows"}
COUNTED_ROLES = ("model", "plan", "scan")


@dataclass
class DocInfo:
    doc_id: str
    title: str = ""
    kind: str = ""
    formats: list = field(default_factory=list)
    role: str = "other"
    level: str | None = None
    role_source: str = "auto"
    doc: object = None                  # engine.solvers.data.Doc | None
    derived: bool = False               # a sheet generated from a model: same data, never an independent source
    group: str | None = None
    note: str = ""


@dataclass
class Row:
    key: str
    name: str
    group: str
    ordinal: int | None = None
    docs: dict = field(default_factory=dict)       # doc_id -> {kind: {"n", "ids", "area"}}
    chosen: dict = field(default_factory=dict)     # kind -> doc_id


@dataclass
class Group:
    key: str
    label: str
    model_ids: list = field(default_factory=list)
    storeys: list = field(default_factory=list)    # [{name, elevation_m}] sorted by elevation
    rows: list = field(default_factory=list)


@dataclass
class Combined:
    infos: dict                                    # doc_id -> DocInfo
    groups: list
    rows: list                                     # all rows, group order then floor order
    unplaced: list = field(default_factory=list)   # doc_ids of drawn docs that could not be placed on a level
    multi_group: bool = False


def _json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def doc_dict(doc_id: str, root: Path) -> dict:
    meta = _json(Path(root) / doc_id / "doc.json") or {}
    return {"doc_id": doc_id, "title": meta.get("title") or doc_id, "kind": meta.get("kind") or "",
            "formats": meta.get("formats") or [], "files": meta.get("files") or {}}


def short_title(title: str, n: int = 48) -> str:
    t = re.sub(r"\s+", " ", title or "").strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def load_infos(docs: list, root: Path) -> dict:
    """docs: list of doc_id strings or dicts {doc_id, role?, level?, role_source?, title?, kind?, formats?}. Role/level are classified when missing."""
    from engine.solvers.data import load_doc, load_sheet_parent
    infos: dict[str, DocInfo] = {}
    for d in docs:
        d = {"doc_id": d} if isinstance(d, str) else dict(d)
        did = d["doc_id"]
        if did in infos:
            continue
        base = doc_dict(did, root)
        base.update({k: v for k, v in d.items() if v not in (None, "") and k in ("title", "kind", "formats")})
        role, level, src = d.get("role"), d.get("level"), d.get("role_source") or "auto"
        if not role:
            c = classify(base, root)
            role, level = c["role"], level or c["level"]
        doc = None
        derived = False
        try:
            doc = load_doc(did, Path(root))
            if doc is None:
                sp = load_sheet_parent(did, Path(root))
                if sp is not None:
                    doc, derived = sp, True
        except Exception:  # noqa: BLE001  one unreadable file must not hide the others
            doc = None
        infos[did] = DocInfo(did, base["title"], base["kind"], base["formats"], role, level, src, doc, derived)
    return infos


# ------------------------------------------------------------------------------------------------ counting
_ARCH_T = re.compile(r"(?<![a-z0-9])(?:ark|arch\w*|arkkitehti\w*|a[-_ ]?\d{2,3})(?![a-z])|floor[ _-]?plan|grundriss|pohjakuva", re.I)
_MEP_T = re.compile(r"ventilation|hvac|l\d{4,6}\b|plumbing|sanitary|electrical|sprinkler|heating|piping|duct|\b(?:lvi|iv|mep|rak|vvs)\b|\b(?:sähkö|ilmanvaihto)\w*", re.I)
_MEP_KINDS = ("duct", "terminal", "diffuser", "pipe", "valve", "cable")


def discipline_of(title: str | None) -> str | None:
    """'arch' / 'mep' / None from the sheet title alone (ARK, A-xxx, floor plan; ventilation, HVAC, L3xxxx, plumbing, electrical ...)."""
    t = (title or "").replace("_", " ")
    mep, arch = bool(_MEP_T.search(t)), bool(_ARCH_T.search(t))
    if mep and not arch:
        return "mep"
    if arch and not mep:
        return "arch"
    return None


def _discipline_rank(info, kind: str) -> int:
    """0 = the sheet whose discipline owns this kind (doors, windows, rooms: architecture; ducts, pipes ...: MEP), 1 = unknown, 2 = other discipline."""
    d = discipline_of(info.title or info.doc_id)
    if d is None:
        return 1
    owner = "mep" if kind in _MEP_KINDS else "arch"
    return 0 if d == owner else 2


def _items(doc, kind: str) -> list:
    from engine.analytics import _of_kind
    return _of_kind(doc, kind)


def _stat(doc, kind: str, only=None) -> dict:
    from engine.solvers.solve import _qty
    its = _items(doc, kind)
    if only is not None:
        its = [i for i in its if only(i)]
    areas = [_qty(i, "room", "area") for i in its] if kind == "room" else []
    known = [a for a in areas if a is not None]
    return {"n": len(its), "ids": [i.item_id for i in its], "area": round(sum(known), 4) if known else None,
            "areas_known": len(known), "conf": (sum(i.conf for i in its) / len(its)) if its else None}


def _has_kind(doc, kind: str) -> bool:
    return bool(_items(doc, kind))


def _norm(s: str | None) -> str:
    from engine.solvers.filters import fold
    return fold(s or "").strip()


def _ground_index(storeys: list) -> int:
    return next((i for i, s in enumerate(storeys) if (s.get("elevation_m") or 0) >= -0.5), 0)


def _same_building(a, b) -> bool:
    def bname(d):
        m = d.meta or {}
        return _norm(((m.get("building") or {}).get("name")) or "")
    na, nb = bname(a), bname(b)
    if na and na == nb:
        return True
    sa, sb = a.storeys or [], b.storeys or []
    if len(sa) >= 2 and len(sa) == len(sb):
        ea = {_norm(s["name"]): s.get("elevation_m") for s in sa}
        eb = {_norm(s["name"]): s.get("elevation_m") for s in sb}
        return ea.keys() == eb.keys() and all(abs((ea[k] or 0) - (eb[k] or 0)) < 0.05 for k in ea)
    return False


def _group_models(infos: dict) -> list[Group]:
    groups: list[Group] = []
    docs_of: dict[str, list] = {}
    for info in infos.values():
        if info.role != "model" or info.doc is None or getattr(info.doc, "mode", "") != "ifc" or (info.kind == "pdf" and "ifc" in (info.formats or [])):
            continue
        for g in groups:
            if _same_building(infos[g.model_ids[0]].doc, info.doc):
                g.model_ids.append(info.doc_id)
                info.group = g.key
                break
        else:
            g = Group(key=f"g{len(groups) + 1}", label="", model_ids=[info.doc_id])
            info.group = g.key
            groups.append(g)
    for g in groups:
        first = infos[g.model_ids[0]].doc
        bname = ((first.meta or {}).get("building") or {}).get("name") or ""
        g.label = bname or short_title(infos[g.model_ids[0]].title)
        seen: dict[str, dict] = {}
        for mid in g.model_ids:
            for s in infos[mid].doc.storeys or []:
                seen.setdefault(_norm(s["name"]), {"name": s["name"], "elevation_m": s.get("elevation_m") or 0.0})
        g.storeys = sorted(seen.values(), key=lambda s: s["elevation_m"])
    return groups


def _match_row(group: Group, level: str) -> Row | None:
    from engine.solvers.solve import resolve_storey
    if not level:
        return None
    by_name = {_norm(r.name): r for r in group.rows}
    if _norm(level) in by_name:
        return by_name[_norm(level)]
    st = resolve_storey(level, [{"name": r.name, "elevation_m": (group.storeys[i]["elevation_m"] if i < len(group.storeys) else i)}
                                for i, r in enumerate(group.rows) if r.key != ""])
    if st and _norm(st) in by_name:
        return by_name[_norm(st)]
    want = level_ordinal(level)
    if want is not None:
        hits = [r for r in group.rows if r.ordinal == want and r.key != ""]
        if len(hits) == 1:
            return hits[0]
    return None


def combine(docs: list, root: Path | str) -> Combined:
    root = Path(root)
    infos = load_infos(docs, root)
    groups = _group_models(infos)
    multi = len(groups) > 1

    # 1. model rows: one per storey (plus one for elements with no storey)
    for g in groups:
        ground = _ground_index(g.storeys)
        names = {_norm(s["name"]): s for s in g.storeys}
        extra = set()
        for mid in g.model_ids:
            for it in infos[mid].doc.items:
                if it.storey and _norm(it.storey) not in names:
                    extra.add(it.storey)
        for i, s in enumerate(g.storeys):
            o = level_ordinal(s["name"])   # the written name decides (an attic is the top, not "floor 3"); unnamed storeys count from the ground floor
            g.rows.append(Row(key=_norm(s["name"]), name=s["name"], group=g.key, ordinal=o if o is not None else i - ground))
        for nm in sorted(extra):
            g.rows.append(Row(key=_norm(nm), name=nm, group=g.key))
        for mid in g.model_ids:
            doc = infos[mid].doc
            for r in g.rows:
                r.docs[mid] = {k: _stat(doc, k, lambda i, key=r.key: _norm(i.storey) == key) for k in KINDS}
            nolevel = {k: _stat(doc, k, lambda i: not i.storey) for k in KINDS}
            if any(v["n"] for v in nolevel.values()):
                row = next((r for r in g.rows if r.key == ""), None)
                if row is None:
                    row = Row(key="", name="No level in the model", group=g.key)
                    g.rows.append(row)
                row.docs[mid] = nolevel

    # 2. drawn documents (plan / scan with a plan map), placed on levels
    unplaced: list[str] = []
    sheets_group: Group | None = None
    for info in infos.values():
        d = info.doc
        if info.role not in COUNTED_ROLES or info.role == "model" or d is None or info.derived or (getattr(d, "mode", "") != "planmap" and not (info.kind == "pdf" and getattr(d, "mode", "") == "ifc")):
            continue
        row = None
        if info.level:
            for g in sorted(groups, key=lambda g: -len(g.storeys)):
                row = _match_row(g, info.level)
                if row:
                    info.group = g.key
                    break
        if row is None and (info.level or not groups):
            if sheets_group is None:
                sheets_group = Group(key="sheets", label="Drawings")
            g = next((g for g in groups if g.key == "sheets"), None) or sheets_group
            if info.level:
                want = level_ordinal(info.level)
                row = next((r for r in g.rows if (want is not None and r.ordinal == want) or _norm(r.name) == _norm(info.level)), None)
                if row is None:
                    row = Row(key=_norm(info.level), name=info.level, group=g.key, ordinal=want)
                    g.rows.append(row)
            else:
                row = next((r for r in g.rows if r.key == ""), None)
                if row is None:
                    row = Row(key="", name="Level not stated", group=g.key)
                    g.rows.append(row)
            info.group = g.key
            if g not in groups:
                groups.append(g)
            if info.level and any(x.model_ids for x in groups):
                info.note = "level not in the model"
        if row is None:
            unplaced.append(info.doc_id)
            info.note = "level not stated, not added to totals"
            continue
        row.docs[info.doc_id] = {k: _stat(d, k) for k in KINDS}

    for g in groups:
        g.rows.sort(key=lambda r: (r.ordinal is None, r.ordinal if r.ordinal is not None else 0, r.name))
    rows = [r for g in groups for r in g.rows]

    # 3. the source per level and kind: model first (if it has that kind at all), else the sheet with the most items
    for r in rows:
        for k in KINDS:
            cand = []
            for did, stats in r.docs.items():
                info = infos[did]
                doc = info.doc
                if stats[k]["n"] == 0 and not _has_kind(doc, k):
                    continue
                cand.append((0 if info.role == "model" else 1, _discipline_rank(info, k), -stats[k]["n"], did))
            if cand:
                r.chosen[k] = min(cand)[3]
    return Combined(infos, groups, rows, unplaced, multi)


def row_label(c: Combined, r: Row) -> str:
    g = next((g for g in c.groups if g.key == r.group), None)
    return f"{r.name} ({g.label})" if c.multi_group and g and g.label else r.name


def value(r: Row, kind: str, what: str = "n"):
    did = r.chosen.get(kind)
    if did is None:
        return None
    return r.docs[did][kind].get(what)


def totals(c: Combined) -> dict:
    out: dict = {"storeys": None, "rooms": None, "doors": None, "windows": None, "floor_area_m2": None}
    real = [r for r in c.rows if r.key != "" and not (r.name == "Level not stated")]
    if real:
        out["storeys"] = len(real)
    for k, key in (("room", "rooms"), ("door", "doors"), ("window", "windows")):
        vals = [value(r, k) for r in c.rows if r.chosen.get(k)]
        out[key] = sum(vals) if vals else None
    areas = [value(r, "room", "area") for r in c.rows if r.chosen.get("room")]
    areas = [a for a in areas if a is not None]
    out["floor_area_m2"] = round(sum(areas), 2) if areas else None
    return out
