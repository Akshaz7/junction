"""Where change lists come from: REAL version series (artifacts/series/*.json) and their PDF diffs.

Feed entries (all computed from files, nothing generated):
  new_version  one per consecutive version pair of a series; summary comes from the cached PDF diff
               (artifacts/series/diffs/<series_id>--<i>-<i+1>.json, built by `python -m pipeline.series --diff`).
  new_version  an uploaded document that matches a series (same sheet code or same normalised title) is a new
               version of that series; diffed against the latest version (computed on refresh, cached).
Rule changes (Context.dev watch events) live in the `changes` table and are merged in by files_routes.
Cached PDF diffs are read without heavy imports. Missing caches fall back to the
real plan-map changes engine (when available), extracted page text, or issue metadata.
"""
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engine.docmeta import SHEET_DISC, derive, parse_date, sheet_code

from . import artifact_store, config, docmeta_store

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
    diff = _read(diffs_dir() / f"{series_id}--{i + 1}-{i + 2}.json")
    return diff if isinstance(diff, dict) and not diff.get("generated_for_demo") else None


def build_series(records: list[dict]) -> list[dict]:
    """Group real dated issues by project and sheet (or normalised file title).

    Manifests are normally built by pipeline.series. This fallback also works on
    a deployed registry without prebuilt series, with dates encoded in doc ids.
    A same-day duplicate is not a new issue; prefer the most complete sheet.
    """
    groups = {}
    for rec in records:
        did = rec.get("doc_id", "")
        if not did.startswith("opening_design__") or rec.get("generated_for_demo") or "@" in did:
            continue
        if rec.get("kind") not in (None, "pdf"):
            continue
        meta = derive(dict(rec, source="opening_design", files=rec.get("files") or {"pdf": did.split("__", 1)[-1]}))
        date = meta.get("date") or parse_date(did)
        if not date:
            continue
        stem = next((Path(f).stem for f in (rec.get("files") or {}).values()), "")
        # Sheet ids are lowercased in doc_id (CONTRACT 5.1).
        sheet = meta.get("sheet") or sheet_code((stem or did.split("__", 1)[-1]).upper())
        title = rec.get("title") or stem
        if not title:
            title = re.split(r"20\d{6}-", did, maxsplit=1)[-1]
        key = sheet or _title_key(title)
        if not key:
            continue
        project = meta["project"]
        group = groups.setdefault((project, key), {"project": project, "sheet": sheet,
                                  "discipline": SHEET_DISC.get(sheet[0], (meta["discipline"], None))[0] if sheet else meta["discipline"], "title": title, "by_date": {}})
        old = group["by_date"].get(date)
        if old is None or (rec.get("pages") or 0, did) > (old.get("pages") or 0, old["doc_id"]):
            group["by_date"][date] = {"doc_id": did, "date": date, "pages": rec.get("pages")}
    out = []
    for (project, key), group in sorted(groups.items()):
        if len(group["by_date"]) < 2:
            continue
        sid = re.sub(r"[^a-z0-9]+", "-", project.lower()).strip("-") + "--" + hashlib.sha1(f"{project}|{key}".encode()).hexdigest()[:12]
        versions = [dict(v, label=f"Version {n} · {v['date']}") for n, v in enumerate(sorted(group.pop("by_date").values(), key=lambda v: v["date"]), 1)]
        out.append(dict(group, series_id=sid, versions=versions))
    return out


def real_series() -> list[dict]:
    series = docmeta_store.series_all()
    if not series:
        registry = docmeta_store._load(config.artifacts_dir() / "registry.jsonl") or {}
        series = build_series(list(registry.values()))
    out = []
    for s in series:
        if s.get("generated_for_demo") or any("@" in v["doc_id"] for v in s["versions"]):
            continue
        by_date = {}
        for v in s["versions"]:
            if v.get("date"):
                by_date.setdefault(v["date"], v)
        versions = sorted(by_date.values(), key=lambda v: v["date"])
        if len(versions) > 1:
            out.append(dict(s, versions=versions))
    return out


async def visible_doc_ids(pool) -> set[str]:
    """Exactly the document ids listed by /api/docs, including DB-only artifacts."""
    rows = await pool.fetch("select doc_id from documents")
    ids = {r["doc_id"] for r in rows}
    if os.environ.get("HIDE_EMPTY_DOCS", "0") == "1":
        ok = await artifact_store.servable_ids(pool)
        ids = {d for d in ids if d in ok or d.startswith("uploads__")}
    return ids


async def visible_feed(pool, feed: list[dict]) -> list[dict]:
    ids = await visible_doc_ids(pool)
    return [e for e in feed if not (e.get("summary") or {}).get("generated_for_demo")
            and (e.get("type") == "rule_change" or
                 (e.get("doc_b") in ids and (not e.get("doc_a") or e["doc_a"] in ids)))]


async def visible_pair(pool, doc_a: str, doc_b: str) -> bool:
    ids = await visible_doc_ids(pool)
    return doc_a in ids and doc_b in ids


def _parties(doc_id: str) -> dict:
    # Only explicit from/to tokens establish a sender or recipient.
    parties = {}
    for role in ("from", "to"):
        match = re.search(rf"(?:^|-){role}-(arch|struct|structural|civil|mep|electrical|owner|regis|maira|spec-consultant|steel-fabricator|lumber-yard)(?=-|$)", doc_id)
        parties["sender" if role == "from" else "recipient"] = match[1].replace("-", " ") if match else None
    return parties


_computed: dict = {}


def pair_diff(series: dict, i: int, j: int | None = None) -> dict | None:
    """Diff of versions i -> j (0-based; j defaults to i + 1, the cached consecutive pair). Any two versions compare."""
    j = i + 1 if j is None else j
    a, b = series["versions"][i], series["versions"][j]
    cached = cached_diff(series["series_id"], i) if j == i + 1 else None
    if cached and cached.get("doc_a") == a["doc_id"] and cached.get("doc_b") == b["doc_id"]:
        return cached
    root = config.artifacts_dir()
    da, db = root / a["doc_id"], root / b["doc_id"]
    files = sorted([*da.glob("planmap-*.json"), *db.glob("planmap-*.json"), *da.glob("text*.json"), *db.glob("text*.json")])
    signature = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files)
    key = (str(root), a["doc_id"], b["doc_id"])
    if key in _computed and _computed[key][0] == signature:
        return _computed[key][1]
    diff = _planmap_diff(a, b, da, db) or _text_diff(a, b, da, db)
    _computed[key] = (signature, diff)
    return diff


def _planmap_diff(a, b, da: Path, db: Path):
    count = a.get("pages")
    if not count or count != b.get("pages"):
        return None
    maps = [(da / f"planmap-{n}.json", db / f"planmap-{n}.json") for n in range(1, count + 1)]
    if not all(x.is_file() and y.is_file() for x, y in maps):
        return None
    from engine.changes import compare
    pages, changes = [], []
    for n, (x, y) in enumerate(maps, 1):
        ma, mb = _read(x), _read(y)
        if not ma or not mb or not ma.get("image") or ma["image"] != mb.get("image"):
            return None  # geometry needs a shared pixel frame
        try:
            with tempfile.TemporaryDirectory(prefix="real-revision-") as tmp:
                d = Path(tmp)
                for label, src in (("v1", x), ("v2", y)):
                    (d / label).mkdir()
                    (d / label / "planmap-1.json").symlink_to(src.resolve())
                result = compare(b["doc_id"], d)
        except ImportError:
            return None  # optional geometry dependency unavailable on this server
        pages.append({"page_a": n, "page_b": n, "image": result["image"], "n_changes": len(result["changes"])})
        for c in result["changes"]:
            changes.append(dict(c, change_id=f"c{len(changes) + 1}", page=n, page_v1=n, page_v2=n))
    return {"doc_a": a["doc_id"], "doc_b": b["doc_id"], "source": "engine", "pages": pages, "changes": changes,
            "note": "Compared the real issues' plan maps; no model call."}


def _page_text(d: Path, n: int):
    data = _read(d / f"text-{n}.json")
    if not data:
        data = next((p for p in (_read(d / "text.json") or {}).get("pages", []) if p.get("page") == n), None)
    if not isinstance(data, dict) or not isinstance(data.get("words"), list):
        return None
    return " ".join(str(w.get("text", "")).strip() for w in data["words"]).strip()


def _text_diff(a, b, da: Path, db: Path):
    if not a.get("pages") or not b.get("pages"):
        return None
    changes = []
    pages = []
    for n in range(1, max(a["pages"], b["pages"]) + 1):
        old = _page_text(da, n) if n <= a["pages"] else ""
        new = _page_text(db, n) if n <= b["pages"] else ""
        if old is None or new is None:
            return None  # incomplete extraction cannot establish unchanged text
        changed = old != new
        pages.append({"page_a": n if n <= a["pages"] else None, "page_b": n if n <= b["pages"] else None,
                      "n_changes": int(changed)})
        if changed:
            changes.append({"change_id": f"c{len(changes) + 1}", "type": "modified", "kind": "text",
                            "description": f'Page {n} text changed from “{old[:180]}” to “{new[:180]}”.',
                            "text_old": old, "text_new": new, "page": n, "page_v1": n, "page_v2": n})
    return {"doc_a": a["doc_id"], "doc_b": b["doc_id"], "source": "text-diff", "pages": pages, "changes": changes,
            "note": "Compared extracted page text only. Drawing geometry has not been compared."}


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
    for s in real_series():
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


def _headline(diff: dict | None, n: int | None, title: str, a: dict, b: dict) -> str:
    if diff is None:
        counts = f" ({a['pages']} → {b['pages']} pages)" if a.get("pages") is not None and b.get("pages") is not None else ""
        return f"New issue of {title}{counts}. Comparison not available."
    changes = diff.get("changes") or []
    if not changes:
        return "New version: no text changes found." if diff.get("source") == "text-diff" else "New version: no drawing changes found."
    return f"{n} change{'s' if n != 1 else ''}: {sentence(changes[0])}"


def _entry(sid: str, title: str, a: dict, b: dict, i: int, diff, created_at: str, doc_b=None, eid=None) -> dict:
    n = len(diff["changes"]) if diff is not None else None
    return {"id": eid or f"ser:{sid}:{i + 1}", "type": "new_version", "doc_a": a["doc_id"], "doc_b": doc_b or b["doc_id"],
            "summary": {"doc_id": doc_b or b["doc_id"], "series_id": sid, "title": title, "n_changes": n,
                        "headline": _headline(diff, n, title, a, b), "source": (diff or {}).get("source", SOURCE),
                        "version_a": a.get("label"), "version_b": b.get("label"), "date_a": a.get("date"),
                        "date_b": b.get("date"), "pages_a": a.get("pages"), "pages_b": b.get("pages"), **_parties(doc_b or b["doc_id"]), "pages_changed": sum(1 for p in (diff or {}).get("pages", []) if p.get("n_changes"))},
            "created_at": created_at}


def series_entries() -> list[dict]:
    out = []
    for s in real_series():
        v = s["versions"]
        for i in range(len(v) - 1):
            entry = _entry(s["series_id"], s["title"], v[i], v[i + 1], i, pair_diff(s, i), _iso(v[i + 1]["date"]))
            entry["summary"].update(discipline=s.get("discipline"), project=s.get("project"), sheet=s.get("sheet"),
                                    index_a=i + 1, index_b=i + 2, pair_prefix=f"ser:{s['series_id']}:")
            out.append(entry)
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
        if diff and (diff.get("generated_for_demo") or diff.get("doc_a") != last["doc_id"] or diff.get("doc_b") != r["doc_id"]):
            diff = None
        b = {"doc_id": r["doc_id"], "label": f"Version {len(s['versions']) + 1} · upload", "date": r["created_at"].date().isoformat()}
        entry = _entry(s["series_id"], s["title"], last, b, len(s["versions"]) - 1, diff, r["created_at"].isoformat(),
                       eid=f"upl:{r['doc_id']}")
        entry["summary"].update(discipline=s.get("discipline"), project=s.get("project"), sheet=s.get("sheet"))
        out.append(entry)
    return out


def compute_for_row(r: dict) -> dict | None:
    s = match_series(r)
    if s is None:
        return None
    p = upload_diff_path(r["doc_id"])
    c = _read(p)
    if c is not None and not c.get("generated_for_demo") and c.get("doc_a") == s["versions"][-1]["doc_id"] and c.get("doc_b") == r["doc_id"]:
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
        span = re.fullmatch(r"(\d{1,4})-(\d{1,4})", n or "")  # ser:<sid>:<a>-<b>: any two versions (1-based)
        for s in real_series():
            if s["series_id"] == sid and n.isdigit() and 1 <= int(n) < len(s["versions"]):
                i = int(n) - 1
                return s, i, pair_diff(s, i), s["versions"][i + 1]["doc_id"]
            if s["series_id"] == sid and span:
                i, j = int(span[1]) - 1, int(span[2]) - 1
                if i != j and 0 <= i < len(s["versions"]) and 0 <= j < len(s["versions"]):
                    return s, i, pair_diff(s, i, j), s["versions"][j]["doc_id"]
    return None


def comparison(change_id: str, page: int | None = None, diff=None, series=None, i=None, doc_b=None) -> dict | None:
    if series is None:
        got = _pair(change_id)
        if got is None:
            return None
        series, i, diff, doc_b = got
    vs = series["versions"]
    a = vs[i]
    b = next((v for v in vs if v["doc_id"] == doc_b), None) or {"doc_id": doc_b, "label": "Uploaded version", "date": None}
    if diff is None:
        return {"id": change_id, "series_id": series["series_id"], "source": (diff or {}).get("source", SOURCE),
                "status": "not_built", "note": _headline(None, None, series["title"], a, b),
                "v1": {"label": a["label"], "doc_id": a["doc_id"], "pages": a.get("pages")}, "v2": {"label": b["label"], "doc_id": b["doc_id"], "pages": b.get("pages")},
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
                        "field": c.get("field"), "old": c.get("text_old", c.get("old")), "new": c.get("text_new", c.get("new")), "page": pb})
    return {"id": change_id, "series_id": series["series_id"], "source": (diff or {}).get("source", SOURCE),
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
