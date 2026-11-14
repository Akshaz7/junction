"""IFC semantic relationships (no geometry evaluation; optional dependency)."""
from pathlib import Path
from .build import read_json


def source_path(doc_id, root):
    meta = read_json(Path(root) / doc_id / 'doc.json', {}) or {}
    rel = (meta.get('files') or {}).get('ifc')
    if rel:
        for base in (Path(root).resolve().parent / 'data' / 'full' / 'junction-dataset',
                     Path(root).resolve().parent / 'data' / 'junction-dataset-preview', Path(root).resolve().parent,
                     Path(root).parent, Path.cwd()):
            p = base / rel
            if p.is_file():
                return p
    p = Path(root) / doc_id / 'source.ifc'
    return p if p.is_file() else None


def enrich_ifc(b):
    pass
