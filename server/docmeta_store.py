"""Doc metadata for the API: folder / discipline / size / date / versions (item 2 + 6).

Pure derivation from the registry row (engine.docmeta) overlaid with artifacts/docmeta.json (size, mtime, series)
written by `python -m pipeline.series`. Series files: artifacts/series/<series_id>.json. Stdlib only.
"""
import json
from pathlib import Path

from engine.docmeta import derive, folder_tree

from . import config

_cache: dict = {}


def _load(path: Path):
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size)
    if _cache.get("k:" + str(path)) != key:
        try:
            raw = path.read_text()
            if path.suffix == ".jsonl":
                records = [json.loads(line) for line in raw.splitlines() if line.strip()]
                _cache["v:" + str(path)] = {r["doc_id"]: r for r in records}
            else:
                _cache["v:" + str(path)] = json.loads(raw)
        except (OSError, ValueError):
            return None
        _cache["k:" + str(path)] = key
    return _cache["v:" + str(path)]


def docmeta_file() -> dict:
    return _load(config.artifacts_dir() / "docmeta.json") or {}


def document_record(doc_id: str) -> dict | None:
    """Resolve unseeded revisions from their own manifest, then the dataset registry.

    Callers validate doc_id before using it as an artifact directory name. The
    series title belongs to the latest issue, so never use it for an older one.
    """
    rec = _load(config.artifacts_dir() / doc_id / "doc.json")
    if isinstance(rec, dict) and rec.get("doc_id") == doc_id:
        return rec.copy()
    registry = _load(config.artifacts_dir() / "registry.jsonl") or {}
    rec = registry.get(doc_id)
    return rec.copy() if rec else None


def series_all() -> list[dict]:
    d = config.artifacts_dir() / "series"
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        s = _load(f)
        if isinstance(s, dict) and s.get("series_id") and s.get("versions"):
            out.append(s)
    return out


def series_by_doc() -> dict[str, list[tuple[dict, int]]]:
    m: dict[str, list] = {}
    for s in series_all():
        for i, v in enumerate(s["versions"]):
            m.setdefault(v["doc_id"], []).append((s, i))
    return m


def upload_size(rec: dict):
    for rel in (rec.get("files") or {}).values():
        for p in (config.REPO / rel, config.artifacts_dir() / "uploads" / Path(rel).name):
            if p.is_file():
                return p.stat().st_size
    return None


def enrich(rec: dict, created_at=None, by_doc=None, stored=None) -> dict:
    """rec: documents row dict (doc_id, source, title, kind, files, ...). Adds size, updated_at, folder, discipline, versions."""
    stored = docmeta_file() if stored is None else stored
    by_doc = series_by_doc() if by_doc is None else by_doc
    m = derive(rec)
    s = stored.get(rec["doc_id"]) or {}
    size = s.get("size_bytes")
    if size is None and rec.get("source") == "uploads":
        size = upload_size(rec)
    ser = by_doc.get(rec["doc_id"]) or []
    version = ser[0][0]["versions"][ser[0][1]] if ser else {}
    if size is None:
        size = version.get("size_bytes")
    date = s.get("date") or m["date"] or version.get("date")
    updated = s.get("updated_at") or date or (created_at.isoformat() if created_at else None)
    versions = []
    series_id = vindex = vcount = None
    if ser:
        sr, idx = ser[0]
        series_id, vindex, vcount = sr["series_id"], idx + 1, len(sr["versions"])
        versions = [{"doc_id": v["doc_id"], "index": n, "date": v["date"], "size": v.get("size_bytes"), "label": v["label"],
                     "pages": v.get("pages")} for n, v in enumerate(sr["versions"], 1)]
    return {"size": size, "updated_at": updated, "project": m["project"], "folder": m["folder"], "folder_path": m["folder_path"],
            "discipline": m["discipline"], "subdiscipline": m["subdiscipline"], "sheet": m["sheet"], "date": date,
            "series_id": series_id, "version_index": vindex, "version_count": vcount, "versions": versions}


def tree(recs: list[dict]) -> dict:
    return folder_tree([derive(r) for r in recs])


def source_file(rec: dict):
    """Original file of a doc: dataset roots, repo-relative upload path, uploads dir, or artifacts/<doc>/source.*."""
    roots = [config.REPO / "data" / "full" / "junction-dataset", config.REPO / "data" / "junction-dataset-preview", config.REPO]
    for rel in (rec.get("files") or {}).values():
        for root in roots:
            p = root / rel
            if p.is_file():
                return p
        p = config.artifacts_dir() / "uploads" / Path(rel).name
        if p.is_file():
            return p
    d = config.artifacts_dir() / rec["doc_id"]
    for p in sorted(d.glob("source.*")) if d.is_dir() else []:
        return p
    return None
