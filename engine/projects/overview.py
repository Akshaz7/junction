"""Project overview: per-level totals across all documents, where sources agree or differ, coverage, mistakes.

  overview(project, root=None) -> dict   (shape: handoff/F-PROJECTS-CONTRACT.md)

project = {id, name, docs:[{doc_id, title?, kind?, formats?, role?, level?, role_source?}]}
Totals never double count: see engine.projects.combine (model wins per level, sheets are cross-checks).
Cached by (project id, document set with roles/levels, file modification times): repeat calls are free.
"""
from __future__ import annotations

import threading
from pathlib import Path

from engine.projects.combine import KINDS, PLURAL, Combined, combine, row_label, totals, value

_CACHE: dict = {}
_LOCK = threading.Lock()
_MAX = 32
AREA_TOL = 0.03          # printed vs measured areas that differ by more than 3% are reported as different


def _root(root) -> Path:
    if root is not None:
        return Path(root)
    import os
    from engine.solvers import ARTIFACTS
    return Path(os.environ.get("ARTIFACTS_DIR") or ARTIFACTS)


def _stamp(doc_id: str, root: Path) -> tuple:
    d = root / doc_id
    out = []
    try:
        for p in list(d.glob("planmap-[0-9]*.json")) + [d / n for n in ("doc.json", "elements.json", "ingest.json", "text-1.json")]:
            try:
                out.append(p.stat().st_mtime_ns)
            except OSError:
                pass
    except OSError:
        pass
    return (len(out), max(out) if out else 0)


def _mistakes_stamp() -> int:
    try:
        import engine.mistakes as m
        return int(Path(m.__file__).stat().st_mtime_ns)
    except Exception:  # noqa: BLE001
        return 0


def cache_key(project: dict, root: Path) -> tuple:
    docs = tuple(sorted((d["doc_id"], d.get("role") or "", d.get("level") or "") for d in project.get("docs") or []))
    return (project.get("id"), docs, tuple(_stamp(d[0], root) for d in docs), _mistakes_stamp())


def _agreements(c: Combined) -> list[dict]:
    out = []
    for r in c.rows:
        label = row_label(c, r)
        for k in KINDS:
            reporting = {}
            for did, stats in r.docs.items():
                info = c.infos[did]
                if info.derived:
                    continue
                if info.role == "model" or stats[k]["n"] or any(i.kind == k for i in (info.doc.items if info.doc else [])):
                    reporting[did] = stats[k]
            if len(reporting) < 2:
                continue
            vals = [{"doc_id": did, "value": s["n"]} for did, s in reporting.items()]
            same = len({v["value"] for v in vals}) == 1
            out.append({"what": f"{PLURAL[k]} on {label}", "values": vals, "status": "matches" if same else "differs",
                        "item_ids_by_doc": {did: s["ids"] for did, s in reporting.items()}})
            if k == "room":
                areas = {did: s["area"] for did, s in reporting.items() if s.get("area") is not None}
                if len(areas) >= 2:
                    hi, lo = max(areas.values()), min(areas.values())
                    out.append({"what": f"room area (m²) on {label}", "values": [{"doc_id": d, "value": round(a, 2)} for d, a in areas.items()],
                                "status": "matches" if hi == 0 or (hi - lo) / hi <= AREA_TOL else "differs",
                                "item_ids_by_doc": {did: reporting[did]["ids"] for did in areas}})
    return out


def _contributes(c: Combined, did: str, root: Path) -> str:
    info = c.infos[did]
    d = info.doc
    if info.derived:
        return "sheet of the model, same data (not counted twice)"
    if d is not None:
        kinds = [PLURAL[k] for k in KINDS if any(i.kind == k for i in d.items)]
        if info.role == "model":
            nst = len(d.storeys or [])
            return ", ".join(kinds + ([f"{nst} levels"] if nst else [])) or "model elements"
        if info.role in ("plan", "scan") and kinds:
            note = f" ({info.note})" if info.note else ""
            return ", ".join(kinds) + note
    ref = {"section": "reference drawing, not counted", "elevation": "reference drawing, not counted",
           "detail": "reference drawing, not counted", "photo": "site photo, not measured",
           "schedule": "schedule text", "spec": "written notes", "revision": "earlier or later issue, not counted"}
    if info.role in ref:
        return ref[info.role]
    try:
        import json
        st = json.loads((root / did / "ingest.json").read_text()).get("status")
        if st == "running":
            return "still being read"
    except Exception:  # noqa: BLE001
        pass
    return "nothing readable yet"


def _ingest_status(root: Path, did: str) -> str | None:
    try:
        import json
        return json.loads((root / did / "ingest.json").read_text()).get("status")
    except Exception:  # noqa: BLE001
        return None


def _labels(c: Combined, agreements: list, root: Path | None = None) -> dict:
    """Per document: Verified (exact model data), Cross-checked (a drawn doc whose numbers agree with another source), Estimate."""
    agree, differ = set(), set()
    for a in agreements:
        for v in a["values"]:
            (agree if a["status"] == "matches" else differ).add(v["doc_id"])
    out = {}
    for did, info in c.infos.items():
        if info.derived:
            out[did] = "Verified"
        elif info.doc is None and info.role in ("model", "plan", "scan") and root is not None:
            # Nothing was read from this file: never claim Verified/Estimate for it.
            out[did] = "Processing" if _ingest_status(root, did) in ("running", "queued", "pending", None) else "Not readable"
        elif info.role == "model" and not (info.doc.items if info.doc is not None else []):
            out[did] = "Partial"
        elif info.role == "model":
            out[did] = "Cross-checked" if did in agree and did not in differ else "Verified"
        elif info.role in ("plan", "scan") and info.doc is not None:
            out[did] = "Cross-checked" if did in agree and did not in differ else "Estimate"
        elif info.role in ("spec", "schedule"):
            out[did] = "Verified"      # printed text, quoted as written
        else:
            out[did] = "Estimate"
    return out


def build(project: dict, root=None) -> dict:
    root = _root(root)
    docs = project.get("docs") or []
    c = combine(docs, root)
    levels = []
    for r in c.rows:
        sources = list(dict.fromkeys([*r.chosen.values(), *r.docs.keys()]))
        levels.append({"level": row_label(c, r),
                       "rooms": value(r, "room"), "doors": value(r, "door"), "windows": value(r, "window"),
                       "floor_area_m2": (round(value(r, "room", "area"), 2) if value(r, "room", "area") is not None else None),
                       "sources": sources})
    agreements = _agreements(c)
    labels = _labels(c, agreements, root)
    coverage = [{"doc_id": did, "role": i.role, "level": i.level, "contributes": _contributes(c, did, root), "confidence_label": labels[did]}
                for did, i in c.infos.items()]
    mistakes = []
    try:
        from engine.mistakes import find as _find
        mistakes = list(_find([d["doc_id"] for d in docs], root) or [])
    except Exception:  # noqa: BLE001  F-MISTAKES may not be merged yet, and a failure there must not hide the rest
        mistakes = []
    return {"project_id": project.get("id"), "totals": totals(c), "levels": levels, "agreements": agreements,
            "mistakes": mistakes, "coverage": coverage}


def overview(project: dict, root=None) -> dict:
    root = _root(root)
    key = cache_key(project, root)
    with _LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit
    res = build(project, root)
    with _LOCK:
        _CACHE[key] = res
        while len(_CACHE) > _MAX:
            _CACHE.pop(next(iter(_CACHE)))
    return res
