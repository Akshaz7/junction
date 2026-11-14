"""Atomic disk cache invalidated by document membership, metadata, source/artifact mtimes and code."""
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
    root = root_path(root)
    rows = []
    docs = project.get('docs') or project.get('doc_ids') or []
    for d in docs:
        if not isinstance(d,(str,dict)):
            continue
        d = {'doc_id': d} if isinstance(d, str) else d
        did = str(d.get('doc_id') or '')
        if not did or Path(did).name != did or did in ('.', '..'):
            continue
        folder = root / did
        files = sorted(p for p in folder.glob('*') if p.suffix in ('.json','.txt','.md','.csv','.tsv','.ifc'))
        rows.append((d, [_stamp(p) for p in files]))
        meta = read_json(folder/'doc.json',{})
        # Original text files and IFC relations can change independently from their extracted index.
        for fmt,rel in (meta.get('files') or {}).items() if isinstance(meta,dict) else []:
            if fmt.lower() not in ('ifc','txt','text','md','csv','tsv') or not isinstance(rel,str):
                continue
            for base in (root.resolve().parent,root.resolve().parent/'data'/'junction-dataset-preview',
                         root.resolve().parent/'data'/'full'/'junction-dataset'):
                p=base/rel
                if p.is_file():
                    rows.append(_stamp(p))
                    break
    for folder in (root / 'series', root / 'series' / 'diffs'):
        rows.extend(_stamp(p) for p in sorted(folder.glob('*.json')))
    code = [_stamp(p) for p in sorted(Path(__file__).parent.glob('*.py'))]
    payload = [project.get('id') or project.get('project_id'), project.get('name'), sorted(rows, key=str), code]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _atomic(path,value):
    tmp=None
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.kg-', suffix='.tmp', delete=False) as f:
            tmp=Path(f.name)
            json.dump(value,f,ensure_ascii=False,allow_nan=False)
        os.replace(tmp,path)
    except OSError:
        # Read-only deployments still serve the computed graph. Never remove another worker's files.
        if tmp:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def _activate(folder,key,project):
    path=folder/'_current.json'
    old=read_json(path,{}) or {}
    if old.get('fingerprint')!=key:
        _atomic(path,{'fingerprint':key,'project':project})


def cached(project, root):
    root = root_path(root)
    pid = project_key(project.get('id') or project.get('project_id') or 'project')
    key = fingerprint(project, root)
    folder=root/'projects'/pid
    hit = read_json(folder / f'kg-{key}.json')
    if isinstance(hit,dict) and hit.get('fingerprint')==key and isinstance(hit.get('graph'),dict):
        _activate(folder,key,project)
        return hit['graph']
    return None


def build(project, root=None):
    from .build import build_uncached
    root = root_path(root)
    pid = project_key(project.get('id') or project.get('project_id') or 'project')
    with _LOCK:
        key = fingerprint(project, root)
        folder = root / 'projects' / pid
        path = folder / f'kg-{key}.json'
        hit = read_json(path)
        if isinstance(hit,dict) and hit.get('fingerprint')==key and isinstance(hit.get('graph'),dict):
            _activate(folder,key,project)
            return hit['graph']
        graph = build_uncached(project, root)
        _atomic(path,{'fingerprint':key,'project':project,'graph':graph})
        _activate(folder,key,project)
        return graph


def load(project_id, root=None):
    root = root_path(root)
    folder = root / 'projects' / project_key(project_id)
    current=read_json(folder/'_current.json')
    if not isinstance(current,dict) or not isinstance(current.get('project'),dict):
        return None
    key=current.get('fingerprint')
    if key!=fingerprint(current['project'],root):
        return None
    hit=read_json(folder/f'kg-{key}.json')
    return hit.get('graph') if isinstance(hit,dict) and hit.get('fingerprint')==key else None
