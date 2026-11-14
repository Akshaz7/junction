"""D-02 registry: scan a dataset root, write artifacts/<doc_id>/doc.json + artifacts/registry.jsonl.

Usage: uv run python -m pipeline.registry [--root data/junction-dataset-preview] [--artifacts artifacts]
"""
import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FMT_EXT = {".ifc": "ifc", ".dxf": "dxf", ".dwg": "dwg", ".pdf": "pdf", ".svg": "svg",
           ".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".tif": "tif", ".tiff": "tif"}
KIND_PRIORITY = ["ifc", "dxf", "dwg", "pdf", "svg"]  # anything else is raster
PER_PATH_SOURCES = {"opening_design"}  # original folders kept, stems collide across folders


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower())


def doc_id_for(source: str, rel_in_source: str) -> str:
    """rel_in_source: path below data/<source>/ . Contract 5.1 (+ full relative path for opening_design)."""
    p = Path(rel_in_source)
    stem = str(p.with_suffix("")) if source in PER_PATH_SOURCES else p.stem
    return f"{source.lower()}__{slug(stem)}"


def doc_id_for_question_path(qpath: str) -> str:
    """questions.jsonl path 'data/<source>/<rel>' -> doc_id."""
    parts = Path(qpath).parts
    return doc_id_for(parts[1], str(Path(*parts[2:])))


def parse_license(md_path: Path):
    """Returns (default_licence, default_credit, {relpath: {title, licence, credit}})."""
    text = md_path.read_text(encoding="utf-8")
    default_lic = default_credit = None
    m = re.search(r"^All files:\s*([A-Za-z0-9.\-]+?)\.\s*Credit:\s*(.+)$", text, re.M)
    if m:
        default_lic, default_credit = m.group(1), m.group(2).strip()
    rows = {}
    for line in text.splitlines():
        if not line.startswith("| ") or line.startswith("| file") or line.startswith("|---"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if len(cols) >= 4:
            rows[cols[0]] = {"title": cols[1], "licence": cols[2], "credit": cols[3]}
    return default_lic, default_credit, rows


def load_heldout(sets_dir: Path) -> set:
    f = sets_dir / "heldout_docs.txt"
    return set(f.read_text().split()) if f.exists() else set()


def pdf_pages(path: Path) -> int:
    try:
        import pypdfium2
        doc = pypdfium2.PdfDocument(str(path))
        n = len(doc)
        doc.close()
        return n
    except Exception:
        return 1


def build(root: Path, artifacts: Path, sets_dir: Path = None, results: Path = None, count_pages=True):
    sets_dir = sets_dir or REPO / "data" / "sets"
    results = results or REPO / "results"
    heldout = load_heldout(sets_dir)
    docs = {}
    data = root / "data"
    for src_dir in sorted(p for p in data.iterdir() if p.is_dir()):
        source = src_dir.name
        lic_file = src_dir / "LICENSE.md"
        d_lic, d_credit, rows = parse_license(lic_file) if lic_file.exists() else (None, None, {})
        for f in sorted(src_dir.rglob("*")):
            if not f.is_file() or f.name == "LICENSE.md" or f.suffix.lower() not in FMT_EXT:
                continue
            rel = f.relative_to(src_dir).as_posix()
            did = doc_id_for(source, rel)
            fmt = FMT_EXT[f.suffix.lower()]
            d = docs.get(did)
            meta = rows.get(rel, {})
            if d is None:
                d = docs[did] = {"doc_id": did, "source": source, "formats": [], "kind": None,
                                 "title": meta.get("title") or f.stem, "pages": 1,
                                 "licence": meta.get("licence") or d_lic,
                                 "credit": meta.get("credit") or d_credit,
                                 "heldout": did in heldout, "files": {}}
            d["formats"].append(fmt)
            d["files"][fmt] = f"data/{source}/{rel}"
            if not d["credit"] and meta.get("credit"):
                d["credit"] = meta["credit"]
            if not d["licence"] and meta.get("licence"):
                d["licence"] = meta["licence"]
            if fmt == "pdf" and count_pages:
                d["pages"] = max(d["pages"], pdf_pages(f))
    artifacts.mkdir(parents=True, exist_ok=True)
    missing = []
    with open(artifacts / "registry.jsonl", "w") as reg:
        for did, d in docs.items():
            d["formats"] = sorted(set(d["formats"]))
            d["kind"] = next((k for k in KIND_PRIORITY if k in d["formats"]), "raster")
            if not d["credit"]:
                missing.append(did)
            (artifacts / did).mkdir(exist_ok=True)
            (artifacts / did / "doc.json").write_text(json.dumps(d, indent=1, ensure_ascii=False))
            reg.write(json.dumps(d, ensure_ascii=False) + "\n")
    results.mkdir(exist_ok=True)
    (results / "missing_credits.txt").write_text("\n".join(missing) + ("\n" if missing else ""))
    return docs, missing


def set_heldout(artifacts: Path, heldout: set):
    """Rewrite heldout flag in every doc.json and registry.jsonl."""
    rows = []
    for line in open(artifacts / "registry.jsonl"):
        d = json.loads(line)
        d["heldout"] = d["doc_id"] in heldout
        (artifacts / d["doc_id"] / "doc.json").write_text(json.dumps(d, indent=1, ensure_ascii=False))
        rows.append(d)
    with open(artifacts / "registry.jsonl", "w") as f:
        for d in rows:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(REPO / "data" / "junction-dataset-preview"))
    ap.add_argument("--artifacts", default=str(REPO / "artifacts"))
    a = ap.parse_args()
    docs, missing = build(Path(a.root), Path(a.artifacts))
    print(f"{len(docs)} docs, {len(missing)} without credit")
