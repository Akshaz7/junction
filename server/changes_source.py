"""Where change lists come from: REAL version series (artifacts/series/*.json) and their PDF diffs.

Feed entries (all computed from files, nothing generated):
  new_version  one per consecutive version pair of a series; summary comes from the cached PDF diff
               (artifacts/series/diffs/<series_id>--<i>-<i+1>.json, built by `python -m pipeline.series --diff`).
  new_version  an uploaded document that matches a series (same sheet code or same normalised title) is a new
               version of that series; diffed against the latest version (computed on refresh, cached).
Rule changes (Context.dev watch events) live in the `changes` table and are merged in by files_routes.
Stdlib only on the read path (the deployed image has no numpy); diffs are computed by engine.pdf_changes
only where numpy exists (local / refresh of uploads).
"""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.docmeta import derive, parse_date, sheet_code

from . import config, docmeta_store

SOURCE = "pdf-diff"
_state = {"checked_at": None}
NOISE = re.compile(r"\b(v\d+|rev\w*|round\s*\d+|markups?|marked\s*up|mark-up|reply|comments?|od|kdf|latest|copy|set|progress|print|plot)\b")


def diffs_dir() -> Path:
    return config.artifacts_dir() / "series" / "diffs"


def _read(p: Path):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def cached_diff(series_id: str, i: int):
    return _read(diffs_dir() / f"{series_id}--{i + 1}-{i + 2}.json")


def mark_checked() -> str:
    _state["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return _state["checked_at"]


def checked_at() -> str:
    return _state["checked_at"] or mark_checked()


def _title_key(text: str) -> str:
    t = re.sub(r"(?<!\d)20\d{2}[-._ ]?\d{2}[-._ ]?\d{2}(?!\d)", " ", (text or "").lower())
    t = NOISE.sub(" ", t)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


def match_series(rec: dict):
    """Series an uploaded doc belongs to, or None. rec: documents row (title, files)."""
    name = rec.get("title") or next((Path(p).stem for p in (rec.get("files") or {}).values()), "")
    code, key = sheet_code(name), _title_key(name)
    best = None
    for s in docmeta_store.series_all():
        if code and s.get("sheet") == code:
            return s
        sk = _title_key(s.get("title") or "")
        if len(key) >= 6 and key == sk:
            best = s
    return best


def _iso(d: str | None) -> str:
    return f"{d}T00:00:00+00:00" if d else datetime.now(timezone.utc).isoformat(timespec="seconds")


def sentence(c: dict) -> str:
    return c.get("description") or f"A {c.get('kind', 'region')} changed."


def _headline(diff: dict | None, n: int | None) -> str:
    if diff is None:
        return "New version (comparison not computed yet)."
    changes = diff.get("changes") or []
    if not changes:
        return "New version: no drawing changes found."
    return f"{n} change{'s' if n != 1 else ''}: {sentence(changes[0])}"


def _entry(sid: str, title: str, a: dict, b: dict, i: int, diff, created_at: str, doc_b=None, eid=None) -> dict:
    n = len(diff["changes"]) if diff is not None else None
    return {"id": eid or f"ser:{sid}:{i + 1}", "type": "new_version", "doc_a": a["doc_id"], "doc_b": doc_b or b["doc_id"],
            "summary": {"doc_id": doc_b or b["doc_id"], "series_id": sid, "title": title, "n_changes": n,
                        "headline": _headline(diff, n), "source": SOURCE, "generated_for_demo": False,
                        "version_a": a.get("label"), "version_b": b.get("label"), "date_a": a.get("date"),
                        "date_b": b.get("date"), "pages_changed": sum(1 for p in (diff or {}).get("pages", []) if p.get("n_changes"))},
            "created_at": created_at}


def series_entries() -> list[dict]:
    out = []
    for s in docmeta_store.series_all():
        v = s["versions"]
        for i in range(len(v) - 1):
            out.append(_entry(s["series_id"], s["title"], v[i], v[i + 1], i, cached_diff(s["series_id"], i), _iso(v[i + 1]["date"])))
    return out


def upload_diff_path(doc_id: str) -> Path:
    return diffs_dir() / f"upload--{doc_id}.json"


def upload_entries(upload_rows: list[dict]) -> list[dict]:
    """upload_rows: documents rows (doc_id, title, files, created_at datetime)."""
    out = []
    for r in upload_rows:
        s = match_series(r)
        if s is None:
            continue
        last = s["versions"][-1]
        diff = _read(upload_diff_path(r["doc_id"]))
        b = {"doc_id": r["doc_id"], "label": f"Version {len(s['versions']) + 1} · upload", "date": r["created_at"].date().isoformat()}
        out.append(_entry(s["series_id"], s["title"], last, b, len(s["versions"]) - 1, diff, r["created_at"].isoformat(),
                          eid=f"upl:{r['doc_id']}"))
    return out


def compute_for_row(r: dict) -> dict | None:
    s = match_series(r)
    if s is None:
        return None
    p = upload_diff_path(r["doc_id"])
    c = _read(p)
    if c is not None:
        return c
    try:
        from engine import pdf_changes
        res = pdf_changes.compare_docs(s["versions"][-1]["doc_id"], r["doc_id"])
    except Exception as e:  # noqa: BLE001
        print("upload diff skipped", r["doc_id"], repr(e)[:120])
        return None
    res["series_id"] = s["series_id"]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(res))
    return res


def group_of(created_at: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    try:
        d = datetime.fromisoformat(created_at)
    except ValueError:
        return "earlier"
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    day = now.astimezone(timezone.utc).date()
    if d.astimezone(timezone.utc).date() >= day:
        return "today"
    if d.astimezone(timezone.utc).date() == day - timedelta(days=1):
        return "yesterday"
    return "earlier"


def grouped(feed: list[dict]) -> list[dict]:
    """Feed (newest first) -> [{"key": today|yesterday|earlier, "label", "ids": [...]}], and sets entry["group"]."""
    labels = {"today": "Today", "yesterday": "Yesterday", "earlier": "Earlier"}
    now = datetime.now(timezone.utc)
    buckets: dict[str, list] = {k: [] for k in labels}
    for e in feed:
        e["group"] = group_of(e["created_at"], now)
        buckets[e["group"]].append(e["id"])
    return [{"key": k, "label": labels[k], "ids": ids} for k, ids in buckets.items() if ids]


def _pair(change_id: str):
    """-> (series, i, diff, doc_b override) for ser:<sid>:<n> / upl:<doc>, else None."""
    if change_id.startswith("ser:"):
        _, sid, n = change_id.rsplit(":", 2) if change_id.count(":") >= 2 else (None, None, None)
        for s in docmeta_store.series_all():
            if s["series_id"] == sid and n.isdigit() and 1 <= int(n) < len(s["versions"]):
                i = int(n) - 1
                return s, i, cached_diff(sid, i), s["versions"][i + 1]["doc_id"]
    return None


def comparison(change_id: str, page: int | None = None, diff=None, series=None, i=None, doc_b=None) -> dict | None:
    if series is None:
        got = _pair(change_id)
        if got is None:
            return None
        series, i, diff, doc_b = got
    vs = series["versions"]
    a = vs[i]
    b = vs[i + 1] if i + 1 < len(vs) and vs[i + 1]["doc_id"] == doc_b else {"doc_id": doc_b, "label": "Uploaded version", "date": None}
    if diff is None:
        return {"id": change_id, "series_id": series["series_id"], "source": SOURCE, "generated_for_demo": False,
                "status": "not_built", "note": "The comparison for this pair has not been computed on this server.",
                "v1": {"label": a["label"], "doc_id": a["doc_id"]}, "v2": {"label": b["label"], "doc_id": b["doc_id"]},
                "image": None, "changes": [], "pages": []}
    pages = diff.get("pages") or []
    def info(p):
        return {"page": p.get("page_b"), "page_v1": p.get("page_a"), "page_v2": p.get("page_b"), "n_changes": p.get("n_changes", 0)}
    plist = [info(p) for p in pages]
    sel = None
    if page is not None:
        sel = next((p for p in pages if p.get("page_b") == page), None)
    if sel is None:
        sel = next((p for p in pages if p.get("n_changes")), pages[0] if pages else None)
    pa, pb = (sel.get("page_a"), sel.get("page_b")) if sel else (1, 1)
    base1, base2 = f"/api/docs/{a['doc_id']}", f"/api/docs/{b['doc_id']}"
    changes = []
    for c in diff.get("changes", []):
        if sel is not None and c.get("page_v2") != pb and c.get("page") != pb:
            continue
        n = len(changes) + 1
        changes.append({"n": n, "change_id": c.get("change_id", f"c{n}"), "type": c["type"], "kind": c["kind"],
                        "sentence": sentence(c), "description": c.get("description"),
                        "v1": {"item_id": None, "bbox_px": c["bbox_px_v1"]} if c.get("bbox_px_v1") else None,
                        "v2": {"item_id": None, "bbox_px": c["bbox_px_v2"]} if c.get("bbox_px_v2") else None,
                        "field": None, "old": c.get("text_old"), "new": c.get("text_new"), "page": pb})
    return {"id": change_id, "series_id": series["series_id"], "source": SOURCE, "generated_for_demo": False,
            "note": diff.get("note"), "image": sel.get("image") if sel else None, "image_v1": sel.get("image_v1") if sel else None,
            "page": pb, "pages": plist,
            "v1": {"label": a["label"], "doc_id": a["doc_id"], "date": a.get("date"), "page_image": f"{base1}/pages/{pa}/image",
                   "thumb": f"{base1}/files/page-{pa}.thumb.png"},
            "v2": {"label": b["label"], "doc_id": b["doc_id"], "date": b.get("date"), "page_image": f"{base2}/pages/{pb}/image",
                   "thumb": f"{base2}/files/page-{pb}.thumb.png"},
            "changes": changes}


async def purge_synthetic(conn) -> int:
    """Delete the old generated 'doc@v1 -> doc@v2' revision rows; the product only shows real series."""
    r = await conn.execute("delete from changes where doc_a like '%@v1' and doc_b like '%@v2'")
    return int(r.split()[-1]) if r else 0
