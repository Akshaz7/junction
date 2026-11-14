"""Serve and persist the small source crops referenced by calculation inputs."""
from __future__ import annotations

import re
from pathlib import Path

NAME = re.compile(r'scale-\d+-[a-f0-9]{20}\.png\Z')


def crop_path(root: Path, doc_id: str, name: str) -> Path | None:
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', doc_id) or doc_id in ('.', '..') or not NAME.fullmatch(name):
        return None
    base = (Path(root) / doc_id / 'evidence').resolve()
    path = (base / name).resolve()
    return path if path.is_relative_to(base) and path.is_file() else None


async def persist(pool, answer, root):
    """Mirror only referenced crops; do not re-upload the full document per answer."""
    sources = [i.get('source') or {} for step in ((answer.get('reasoning') or {}).get('calc') or {}).get('steps', [])
               for i in step.get('inputs', [])]
    seen = set()
    for src in sources:
        ref, did = src.get('crop'), src.get('doc_id')
        if not isinstance(ref, str) or not isinstance(did, str) or not ref.startswith(did + '/evidence/'):
            continue
        name = ref.removeprefix(did + '/evidence/')
        path = crop_path(root, did, name)
        if path is None or ref in seen or path.stat().st_size > 1024 * 1024:
            continue
        seen.add(ref)
        data = path.read_bytes()
        await pool.execute(
            'insert into doc_artifacts (doc_id, name, content_type, data, size) values ($1,$2,$3,$4,$5) '
            'on conflict (doc_id, name) do nothing', did, 'evidence/' + name, 'image/png', data, len(data))
