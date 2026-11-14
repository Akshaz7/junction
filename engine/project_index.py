"""Project-wide index: one searchable record per document (and per PDF page), pure Python, no models.

  python -m engine.project_index build            # every doc in artifacts/registry.jsonl (minutes, nice it)
  python -m engine.project_index upsert <doc_id>  # add / refresh ONE doc (call after an upload finishes ingesting)
  python -m engine.project_index search "EI 60 stair core"

Pipeline hook: `from engine.project_index import upsert_doc; upsert_doc(doc_id)` (never raises; returns bool).

What is indexed (all lexical, BM25):
  meta chunk (page 0): title, source, discipline, file stem, plan-map room labels / printed text, room types,
                       IFC storeys, element kinds, type names, room long names, item-kind counts.
  page chunks:         PDF / DXF text layer (text-N.json), one chunk per page.
Passages with positions are NOT stored: engine.project_answer re-reads text-N.json for the top pages only.
Index file: <artifacts>/index/project_index.pkl (git-ignored with artifacts/).
"""
from __future__ import annotations

import json
import math
import os
import pickle
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
VERSION = 2

STOP = set("""a an the of in on at to for from by with without and or but not is are was were be been being do does did
this that these those it its as if then than so such into onto over under about across per each any all some which what
who whom where when why how many much more most less least there here have has had can could should would will shall may
might must i we you they he she me my our your their show shown shows list find tell give get please also just only
document documents drawing drawings plan plans sheet sheets file files project model models building buildings
number amount total mention mentions mentioned say says contain contains containing present""".split())
# words that carry the question but little meaning for retrieval
WEAK = {"floor", "level", "storey", "story", "room", "rooms"}

SYN = {  # query-time expansion (weight 0.6); room names in several languages
    "toilet": "wc lavatory restroom washroom toilets bad aborte vessa wc-tila",
    "wc": "toilet lavatory restroom washroom",
    "restroom": "toilet wc washroom lavatory",
    "bathroom": "bath bad bain bagno baño kylpyhuone badezimmer shower",
    "kitchen": "küche cuisine keittiö cucina kitchenette",
    "bedroom": "schlafzimmer chambre makuuhuone camera",
    "stair": "staircase stairs treppenhaus stairwell",
    "staircase": "stair stairs stairwell",
    "balcony": "balkon balcon parveke loggia terrace",
    "door": "doors",
    "ei": "fire-rated fire-resistance rated",
}

DISCIPLINE = [("architectural", r"(^|[-_ ])(arc|arch|architecture|architectural)([-_ .]|$)"),
              ("structural", r"(^|[-_ ])(str|struc|structural|structure)([-_ .]|$)"),
              ("mechanical electrical plumbing", r"(^|[-_ ])(mep|hvac|mech|mechanical|elec|electrical|plumb|plumbing|fire)([-_ .]|$)"),
              ("facade", r"facade|curtain"), ("site landscape", r"(^|[-_ ])(site|landscape)([-_ ]|$)")]

_WORD = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)


def stem(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def tokenize(text: str, keep_stop: bool = False) -> list[str]:
    out = []
    for m in _WORD.findall((text or "").casefold()):
        for w in ([m] if "-" not in m else [m, *m.split("-")]):
            if len(w) > 40:
                continue
            if not keep_stop and (w in STOP or len(w) == 1 and not w.isdigit()):
                continue
            out.append(stem(w))
    return out


def norm_name(s: str) -> str:
    return " ".join(tokenize(s, keep_stop=True))


def _json(p: Path):
    try:
        with p.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _add(c: Counter, text, w: int = 1):
    for t in tokenize(str(text or "")):
        c[t] += w


def _names_for(doc_id: str, meta: dict) -> set[str]:
    keys = set()
    tail = doc_id.split("__", 1)[-1]
    cands = [tail, meta.get("title") or ""]
    for v in (meta.get("files") or {}).values():
        cands.append(Path(str(v)).stem)
    for c in cands:
        n = norm_name(c)
        toks = n.split()
        if not toks or len(toks) > 10:
            continue
        if len(toks) >= 2 or (len(toks[0]) >= 6 and re.search(r"\d", toks[0])):
            keys.add(n)
    return keys


def discipline_of(doc_id: str, meta: dict) -> str:
    s = (doc_id.split("__", 1)[-1] + " " + str(meta.get("title") or "")).casefold()
    return ", ".join(name for name, rx in DISCIPLINE if re.search(rx, s))


def build_chunks(doc_id: str, root: Path) -> tuple[dict, list[tuple[int, int, dict]], set[str]] | None:
    """-> (summary, [(page, n_tokens, term_counts)], names) for one document dir, or None if it is missing."""
    d = Path(root) / doc_id
    if not d.is_dir():
        return None
    meta = _json(d / "doc.json") or {"doc_id": doc_id}
    src = meta.get("source") or doc_id.split("__", 1)[0]
    disc = discipline_of(doc_id, meta)
    summary: dict = {"doc_id": doc_id, "title": meta.get("title") or doc_id, "source": src, "kind": meta.get("kind"),
                     "pages": meta.get("pages") or 1, "discipline": disc,
                     "title_toks": sorted(set(tokenize(meta.get("title") or "")))[:12]}
    m = Counter()
    _add(m, summary["title"], 3)
    _add(m, doc_id.split("__", 1)[-1], 2)
    _add(m, src, 1)
    _add(m, disc, 2)
    _add(m, meta.get("kind"), 1)
    for v in (meta.get("files") or {}).values():
        _add(m, Path(str(v)).stem, 2)

    e = _json(d / "elements.json")
    if e and e.get("elements"):
        storeys = [s.get("name") for s in e.get("storeys") or [] if s.get("name")]
        summary["storeys"] = storeys[:30]
        kinds, rooms, types = Counter(), Counter(), Counter()
        for x in e["elements"]:
            k = x.get("kind") or "other"
            kinds[k] += 1
            pr = x.get("props") or {}
            if k == "room":
                nm = pr.get("long_name") or x.get("type_name") or x.get("name")
                if nm:
                    rooms[str(nm)] += 1
            elif x.get("type_name") and k in ("door", "window", "stairs", "wall", "slab", "column"):
                types[str(x["type_name"])] += 1
        for s in storeys:
            _add(m, s, 2)
        for k, n in kinds.items():
            _add(m, k, 1)
        for nm in rooms:
            _add(m, nm, 2)
        for nm, _ in types.most_common(60):
            _add(m, nm, 1)
        summary.update({"rooms": [n for n, _ in rooms.most_common(25)], "counts": dict(kinds.most_common(12)), "mode": "ifc"})
    else:
        pms = sorted(d.glob("planmap-[0-9]*.json"), key=lambda p: int(p.stem.split("-")[1]))
        if pms:
            kinds, labels, rtypes = Counter(), Counter(), Counter()
            for p in pms:
                pm = _json(p) or {}
                for x in pm.get("items") or []:
                    kinds[x.get("kind") or "other"] += 1
                    if x.get("label") and x.get("kind") in ("room", "text", "other"):
                        labels[str(x["label"])[:60]] += 1
                    rt = (x.get("props") or {}).get("room_type")
                    if x.get("kind") == "room" and rt:
                        rtypes[str(rt)] += 1
            for k in kinds:
                _add(m, k, 1)
            for lab in labels:
                _add(m, lab, 1)
            for rt in rtypes:
                _add(m, rt, 2)
            summary.update({"rooms": [n for n, _ in (rtypes + labels).most_common(25)], "counts": dict(kinds.most_common(12)),
                            "mode": "planmap"})
    chunks = [(0, sum(m.values()), dict(m))]
    for tp in sorted(d.glob("text-[0-9]*.json"), key=lambda p: int(p.stem.split("-")[1])):
        t = _json(tp) or {}
        c = Counter()
        for w in t.get("words") or []:
            _add(c, w.get("text"))
        if c:
            chunks.append((int(t.get("page") or tp.stem.split("-")[1]), sum(c.values()), dict(c)))
    summary["text_pages"] = [p for p, _, _ in chunks if p > 0]
    return summary, chunks, _names_for(doc_id, meta)


class Index:
    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.chunks: dict[tuple[str, int], tuple[int, dict]] = {}
        self.names: dict[str, list[str]] = {}
        self.postings: dict[str, dict[tuple[str, int], int]] = defaultdict(dict)
        self.total_len = 0
        self.lock = threading.RLock()
        self.mtime = 0.0

    # --- mutation -------------------------------------------------------------------------------------
    def remove(self, doc_id: str):
        with self.lock:
            old = self.docs.pop(doc_id, None)
            if old is None:
                return
            for pg in [0, *old.get("text_pages", [])]:
                ent = self.chunks.pop((doc_id, pg), None)
                if ent:
                    self.total_len -= ent[0]
                    for t in ent[1]:
                        self.postings[t].pop((doc_id, pg), None)
                        if not self.postings[t]:
                            del self.postings[t]
            for k, v in list(self.names.items()):
                if doc_id in v:
                    v.remove(doc_id)
                    if not v:
                        del self.names[k]

    def add(self, built):
        summary, chunks, names = built
        did = summary["doc_id"]
        with self.lock:
            self.remove(did)
            self.docs[did] = summary
            for page, n, terms in chunks:
                self.chunks[(did, page)] = (n, terms)
                self.total_len += n
                for t, tf in terms.items():
                    self.postings[t][(did, page)] = tf
            for k in names:
                self.names.setdefault(k, []).append(did)

    def rebuild_postings(self):
        self.postings = defaultdict(dict)
        self.total_len = 0
        for key, (n, terms) in self.chunks.items():
            self.total_len += n
            for t, tf in terms.items():
                self.postings[t][key] = tf

    # --- query ----------------------------------------------------------------------------------------
    def idf(self, term: str) -> float:
        n = len(self.chunks) or 1
        df = len(self.postings.get(term, ()))
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def query_terms(self, question: str) -> dict[str, float]:
        base = tokenize(question)
        terms: dict[str, float] = {}
        for t in base:
            terms[t] = 1.0
        for t in base:
            for s in SYN.get(t, "").split():
                for st in tokenize(s):
                    terms.setdefault(st, 0.6)
        return terms

    def search(self, question: str, k: int = 10, boost_sources: dict[str, float] | None = None, per_doc: bool = True) -> list[dict]:
        """Top documents: [{doc_id, page, score, coverage, matched}], best chunk per doc, best first."""
        terms = self.query_terms(question)
        if not terms:
            return []
        n = len(self.chunks) or 1
        avg = (self.total_len / n) or 1.0
        base = [t for t, w in terms.items() if w == 1.0]
        mass_total = sum(self.idf(t) for t in base) or 1.0
        scores: dict[tuple[str, int], float] = defaultdict(float)
        got: dict[tuple[str, int], set] = defaultdict(set)
        with self.lock:
            for t, w in terms.items():
                post = self.postings.get(t)
                if not post:
                    continue
                idf = self.idf(t) * (0.4 if t in WEAK else 1.0) * w
                for key, tf in post.items():
                    ln = self.chunks[key][0]
                    scores[key] += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * ln / avg))
                    got[key].add(t)
        best: dict[str, dict] = {}
        qset = set(base)
        for key, sc in scores.items():
            did, page = key
            dm = self.docs.get(did, {})
            boost = (boost_sources or {}).get(dm.get("source", ""), 1.0)
            tt = dm.get("title_toks") or ()
            if len(tt) >= 2:                      # the question quotes much of the document's title: it is about that document
                ov = sum(1 for t in tt if t in qset)
                if ov >= 2:
                    boost *= 1 + 1.5 * ov / len(tt)
            sc *= boost
            bk = did if per_doc else key
            cur = best.get(bk)
            if cur is None or sc > cur["score"]:
                matched = got[key]
                cov = sum(self.idf(t) for t in matched if t in base) / mass_total
                best[bk] = {"doc_id": did, "page": page, "score": round(sc, 4), "coverage": round(cov, 3), "matched": sorted(matched)}
        return sorted(best.values(), key=lambda h: -h["score"])[:k]

    def named_docs(self, question: str) -> list[str]:
        """Documents the question names (id, file stem or distinctive title)."""
        toks = tokenize(question, keep_stop=True)
        found: list[str] = []
        for ln in range(min(10, len(toks)), 0, -1):
            for i in range(len(toks) - ln + 1):
                key = " ".join(toks[i:i + ln])
                ids = self.names.get(key)
                if ids and len(ids) <= 3:
                    for d in ids:
                        if d not in found:
                            found.append(d)
        return found

    # --- persistence ----------------------------------------------------------------------------------
    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        with self.lock, tmp.open("wb") as f:
            pickle.dump({"version": VERSION, "docs": self.docs, "chunks": self.chunks, "names": self.names}, f, protocol=5)
        tmp.replace(path)
        self.mtime = path.stat().st_mtime


def index_path(root: Path | str | None = None) -> Path:
    return Path(root or os.environ.get("ARTIFACTS_DIR") or ARTIFACTS) / "index" / "project_index.pkl"


_CACHE: dict[str, Index] = {}


def load_index(root: Path | str | None = None) -> Index | None:
    """Cached per process; reloaded when the file changes on disk. None when no index was built."""
    p = index_path(root)
    try:
        mt = p.stat().st_mtime
    except OSError:
        return None
    ix = _CACHE.get(str(p))
    if ix is not None and ix.mtime >= mt:
        return ix
    try:
        with p.open("rb") as f:
            blob = pickle.load(f)
    except (OSError, pickle.PickleError, EOFError):
        return None
    if blob.get("version") != VERSION:
        return None
    ix = Index()
    ix.docs, ix.chunks, ix.names = blob["docs"], blob["chunks"], blob["names"]
    ix.rebuild_postings()
    ix.mtime = mt
    _CACHE[str(p)] = ix
    return ix


def upsert_doc(doc_id: str, root: Path | str | None = None) -> bool:
    """Add or refresh one document (pipeline calls this after ingestion). Creates the index if absent. Never raises."""
    try:
        r = Path(root or os.environ.get("ARTIFACTS_DIR") or ARTIFACTS)
        built = build_chunks(doc_id, r)
        if built is None:
            return False
        ix = load_index(r) or Index()
        ix.add(built)
        ix.save(index_path(r))
        _CACHE[str(index_path(r))] = ix
        return True
    except Exception as e:  # noqa: BLE001
        print(f"project_index.upsert_doc({doc_id}): {type(e).__name__}: {e}", file=sys.stderr)
        return False


def remove_doc(doc_id: str, root: Path | str | None = None) -> bool:
    try:
        r = Path(root or os.environ.get("ARTIFACTS_DIR") or ARTIFACTS)
        ix = load_index(r)
        if ix is None or doc_id not in ix.docs:
            return False
        ix.remove(doc_id)
        ix.save(index_path(r))
        return True
    except Exception:  # noqa: BLE001
        return False


def doc_ids_in(root: Path) -> list[str]:
    reg = Path(root) / "registry.jsonl"
    ids: list[str] = []
    if reg.exists():
        for line in reg.open(encoding="utf-8"):
            try:
                ids.append(json.loads(line)["doc_id"])
            except (ValueError, KeyError):
                pass
    else:
        ids = sorted(p.name for p in Path(root).iterdir() if (p / "doc.json").exists())
    # uploads are registered by the server, not in registry.jsonl: pick up any doc dir with a doc.json
    seen = set(ids)
    for p in sorted(Path(root).iterdir()):
        if p.is_dir() and not p.name.startswith(("_", ".")) and p.name != "index" and p.name not in seen and (p / "doc.json").exists():
            ids.append(p.name)
    return ids


def build_all(root: Path | str | None = None, progress: bool = False) -> Index:
    r = Path(root or os.environ.get("ARTIFACTS_DIR") or ARTIFACTS)
    ix = Index()
    ids = doc_ids_in(r)
    t0 = time.time()
    for n, did in enumerate(ids, 1):
        try:
            b = build_chunks(did, r)
        except Exception as e:  # noqa: BLE001 — one bad doc must not stop the build
            print(f"skip {did}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        if b:
            ix.add(b)
        if progress and n % 500 == 0:
            print(f"{n}/{len(ids)} docs, {time.time() - t0:.0f}s", flush=True)
    ix.save(index_path(r))
    _CACHE[str(index_path(r))] = ix
    return ix


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    if argv[0] == "build":
        ix = build_all(progress=True)
        p = index_path()
        print(f"indexed {len(ix.docs)} docs, {len(ix.chunks)} chunks, {len(ix.postings)} terms, {p.stat().st_size / 1e6:.1f} MB -> {p}")
    elif argv[0] == "upsert":
        print(all(upsert_doc(d) for d in argv[1:]))
    elif argv[0] == "search":
        ix = load_index()
        if ix is None:
            print("no index: run `python -m engine.project_index build`")
            return 1
        t0 = time.perf_counter()
        hits = ix.search(" ".join(argv[1:]))
        ms = (time.perf_counter() - t0) * 1000
        for h in hits:
            print(h["score"], h["coverage"], h["doc_id"], "p", h["page"], ix.docs[h["doc_id"]]["title"][:60])
        print(f"{ms:.0f} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
