"""Atomic disk cache invalidated by document membership, metadata, artifact/source mtimes and code version."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path

from .build import read_json

_LOCK = threading.RLock()


def root_path(root=None):
    if root is not None:
        return Path(root)
    from engine.solvers import ARTIFACTS
    return Path(os.environ.get('ARTIFACTS_DIR') or ARTIFACTS)


def project_key(project_id):
    pid = str(project_id)
    if not pid or Path(pid).name != pid or pid in ('.', '..'):
        raise ValueError('Invalid project identifier')
    return pid


def _stamp(path):
    try:
        s = path.stat()
        return (str(path), s.st_size, s.st_mtime_ns)
    except OSError:
        return (str(path), None, None)


def fingerprint(project, root):
    from .ifc import source_path
    rows = []
    docs = project.get('docs') or project.get('doc_ids') or []
    for d in docs:
        d = {'doc_id': d} if isinstance(d, str) else d
        did = str(d.get('doc_id') or '')
        if not did or Path(did).name != did or did in ('.', '..'):
            continue
        folder = root / did
        files = sorted(folder.glob('*.json'))
        # Ingest can add/remove a file while this list is being read; the next request invalidates it.
        rows.append((d, [_stamp(p) for p in files]))
        src = source_path(did, root)
        if src:
            rows.append(_stamp(src))
    # Revision comparisons live outside individual doc folders.
    for folder in (root / 'series', root / 'series' / 'diffs'):
        rows.extend(_stamp(p) for p in sorted(folder.glob('*.json')))
    code = [_stamp(p) for p in sorted(Path(__file__).parent.glob('*.py'))]
    payload = [project.get('id') or project.get('project_id'), project.get('name'), sorted(rows, key=str), code]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]


def cached(project, root):
    root = root_path(root)
    pid = project_key(project.get('id') or project.get('project_id') or 'project')
    key = fingerprint(project, root)
    hit = read_json(root / 'projects' / pid / f'kg-{key}.json')
    return hit.get('graph') if isinstance(hit, dict) and hit.get('fingerprint') == key else None


def build(project, root=None):
    from .build import build_uncached
    root = root_path(root)
    pid = project_key(project.get('id') or project.get('project_id') or 'project')
    with _LOCK:
        key = fingerprint(project, root)
        folder = root / 'projects' / pid
        path = folder / f'kg-{key}.json'
        hit = read_json(path)
        if isinstance(hit, dict) and hit.get('fingerprint') == key:
            return hit['graph']
        graph = build_uncached(project, root)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', dir=folder, prefix='.kg-', suffix='.tmp', delete=False) as f:
                tmp = Path(f.name)
                json.dump({'fingerprint': key, 'project': project, 'graph': graph}, f, ensure_ascii=False, allow_nan=False)
            os.replace(tmp, path)
        except OSError:
            # Read-only deployments can still serve a computed graph.
            if 'tmp' in locals():
                tmp.unlink(missing_ok=True)
        return graph


def load(project_id, root=None):
    root = root_path(root)
    folder = root / 'projects' / project_key(project_id)
    for path in sorted(folder.glob('kg-*.json'), key=lambda p: p.stat().st_mtime_ns, reverse=True):
        hit = read_json(path)
        if not isinstance(hit, dict) or not isinstance(hit.get('project'), dict):
            continue
        if hit.get('fingerprint') == fingerprint(hit['project'], root):
            return hit.get('graph')
        # Latest known membership is authoritative. Do not resurrect an older membership cache.
        return None
    return None
