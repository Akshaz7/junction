"""D-13: real version series and per-doc folder metadata (replaces the synthetic pipeline/revisions.py for the product).

A series is the same drawing sheet issued on several dates in a real project (opening_design Transfer folders):
  key = project + sheet code (A-504, S401, ...) when the file name carries one, else project + normalised file title.
  Only PDFs with a date in the issue folder or file name take part; one doc per (key, date) (most pages wins);
  a series needs at least 2 distinct dates.
Outputs (git-ignored, under artifacts/):
  docmeta.json            {doc_id: {project, folder, folder_path, discipline, subdiscipline, date, sheet, size_bytes,
                           updated_at, date_source, series: [{series_id, index, count}]}}   (every registry doc)
  series/<series_id>.json {series_id, title, project, discipline, sheet, versions: [{doc_id, date, size_bytes, label, pages}]}
CLI:
  python -m pipeline.series                 # rebuild docmeta.json and series/*.json
  python -m pipeline.series --diff          # also compute (cached) PDF diffs for every consecutive pair (engine.pdf_changes)
  python -m pipeline.series --diff --only <series_id>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from engine.docmeta import derive

REPO = Path(__file__).resolve().parent.parent
ART = REPO / "artifacts"
DATA_ROOTS = [REPO / "data" / "full" / "junction-dataset", REPO / "data" / "junction-dataset-preview", REPO]
NOISE = re.compile(r"\b(v\d+|rev\w*|round\s*\d+|markups?|marked\s*up|mark-up|reply|comments?|od|kdf|latest|copy|set|progress|print|plot)\b")


def source_path(rec: dict) -> Path | None:
    """The original file of a registry record, searched in the dataset roots, then artifacts/<doc>/source.*."""
    files = rec.get("files") or {}
    for rel in files.values():
        for root in DATA_ROOTS:
            p = root / rel
            if p.is_file():
                return p
    for p in sorted((ART / rec["doc_id"]).glob("source.*")):
        return p
    return None


def _title_key(rec: dict, meta: dict) -> str:
    path = next(iter((rec.get("files") or {}).values()), "")
    stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0] or rec.get("title", "")
    t = re.sub(r"(?<!\d)20\d{2}[-._ ]?\d{2}[-._ ]?\d{2}(?!\d)", " ", stem.lower())
    t = NOISE.sub(" ", t)
    proj = re.sub(r"[^a-z0-9]+", " ", meta["project"].lower()).strip()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    t = re.sub(rf"\b{re.escape(proj)}\b", " ", t) if proj else t
    return re.sub(r"\s+", " ", t).strip()


def _slug(s: str, n: int = 70) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:n].strip("-")


def series_id(project: str, key: str) -> str:
    return f"{_slug(project, 24)}--{_slug(key, 48)}-{hashlib.sha1(f'{project}|{key}'.encode()).hexdigest()[:6]}"


def _updated_at(meta: dict, p: Path | None) -> tuple[str | None, str | None]:
    if meta.get("date"):
        return meta["date"], "path"
    if p is not None:
        return datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"), "mtime"
    return None, None


def build(registry: Path | None = None, art: Path | None = None) -> tuple[dict, list[dict]]:
    art = art or ART
    rows = [json.loads(l) for l in (registry or art / "registry.jsonl").read_text().splitlines() if l.strip()]
    docmeta: dict[str, dict] = {}
    cand: dict[str, dict[str, dict]] = {}   # key -> date -> best candidate
    info: dict[str, dict] = {}
    for rec in rows:
        meta = derive(rec)
        p = source_path(rec)
        meta["size_bytes"] = p.stat().st_size if p else None
        meta["updated_at"], meta["date_source"] = _updated_at(meta, p)
        docmeta[rec["doc_id"]] = meta
        if rec["source"] != "opening_design" or rec.get("kind") != "pdf" or not meta["date"]:
            continue
        title_key = _title_key(rec, meta)
        key = f"{meta['project']}|{meta['sheet']}" if meta["sheet"] else f"{meta['project']}|t:{title_key}"
        if not meta["sheet"] and len(title_key) < 4:
            continue
        slot = cand.setdefault(key, {})
        cur = slot.get(meta["date"])
        item = {"doc_id": rec["doc_id"], "date": meta["date"], "size_bytes": meta["size_bytes"],
                "pages": int(rec.get("pages") or 1), "title": rec.get("title")}
        if cur is None or (item["pages"], item["doc_id"]) > (cur["pages"], cur["doc_id"]):
            slot[meta["date"]] = item
        info[key] = {"project": meta["project"], "discipline": meta["discipline"], "sheet": meta["sheet"]}
    series = []
    for key, by_date in sorted(cand.items()):
        if len(by_date) < 2:
            continue
        versions = sorted(by_date.values(), key=lambda v: v["date"])
        i = info[key]
        sid = series_id(i["project"], key.split("|", 1)[1])
        title = versions[-1]["title"] or key
        series.append({"series_id": sid, "title": title, "project": i["project"], "discipline": i["discipline"],
                       "sheet": i["sheet"],
                       "versions": [{"doc_id": v["doc_id"], "date": v["date"], "size_bytes": v["size_bytes"],
                                     "label": f"Version {n} · {v['date']}", "pages": v["pages"]}
                                    for n, v in enumerate(versions, 1)]})
    for s in series:
        for n, v in enumerate(s["versions"], 1):
            docmeta[v["doc_id"]].setdefault("series", []).append({"series_id": s["series_id"], "index": n, "count": len(s["versions"])})
    return docmeta, series


def write(docmeta: dict, series: list[dict], art: Path | None = None) -> None:
    art = art or ART
    (art / "series").mkdir(parents=True, exist_ok=True)
    for f in (art / "series").glob("*.json"):
        f.unlink()
    for s in series:
        (art / "series" / f"{s['series_id']}.json").write_text(json.dumps(s, indent=1))
    (art / "docmeta.json").write_text(json.dumps(docmeta, separators=(",", ":")))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--only")
    a = ap.parse_args()
    docmeta, series = build()
    if not a.only:
        write(docmeta, series)
    print(f"{len(docmeta)} docs, {len(series)} series ({sum(len(s['versions']) for s in series)} versions)")
    for s in series:
        print(f"  {s['series_id']}  {s['project']} / {s['discipline']}  {[v['date'] for v in s['versions']]}  {s['title'][:50]}")
    if a.diff:
        from engine import pdf_changes
        for s in series:
            if a.only and s["series_id"] != a.only:
                continue
            for i in range(len(s["versions"]) - 1):
                r = pdf_changes.compare_versions(s, i)
                print(s["series_id"], i + 1, "->", i + 2, len(r["changes"]), "changes", r.get("note") or "")


if __name__ == "__main__":
    main()
