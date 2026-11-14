"""Project knowledge graph API. Slow builds continue in a bounded background worker."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from . import config
from .projects_routes import _pool, _project, _uuid

router = APIRouter(prefix='/api/projects')
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='project-graph')
_JOBS = {}
BUILD_WAIT_S = 25.0


async def _graph(project_id):
    from engine.kg import build
    from engine.kg.cache import cached, fingerprint
    pool = await _pool()
    project = await _project(pool, _uuid(project_id), refresh=False)
    root = Path(config.artifacts_dir())
    key = (str(root.resolve()), project_id, await asyncio.to_thread(fingerprint, project, root))
    hit = await asyncio.to_thread(cached, project, root)
    if hit is not None:
        return hit, False
    future = _JOBS.get(key)
    if future is None:
        future = _EXECUTOR.submit(build, project, root)
        _JOBS[key] = future
        for old in list(_JOBS):
            if len(_JOBS) <= 32:
                break
            if _JOBS[old].done() and old != key:
                del _JOBS[old]
    try:
        graph = await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)), BUILD_WAIT_S)
        return graph, False
    except asyncio.TimeoutError:
        from engine.kg.schema import Records, finalise
        r = Records()
        pn = r.node('project', project_id, 'root', project.get('name') or 'Project', doc_ids=[])
        for d in project.get('docs') or []:
            dn = r.node('doc', d['doc_id'], 'root', d.get('title') or 'Document', props={'role': d.get('role')})
            r.edge('contains', pn, dn, 'rule', 1, {'rule': 'project_membership'})
        return finalise({'project_id': project_id, 'version': 1, 'built_at': None, 'building': True,
                         'nodes': list(r.nodes.values()), 'edges': list(r.edges.values()),
                         'warnings': [{'note': 'Graph is still building. Request this address again for the complete result.'}]}), True
    except Exception:
        _JOBS.pop(key, None)
        raise HTTPException(503, 'The project graph could not be built. Please try again.') from None


def _response(value, pending):
    return JSONResponse(value, status_code=202, headers={'Retry-After': '3'}) if pending else value


@router.get('/{project_id}/graph')
async def graph_view(project_id: str, level: str | None = None, kinds: str | None = None,
                     doc_id: str | None = None, depth: str = Query('cluster', pattern='^(cluster|full)$')):
    from engine.kg.query import project_graph
    graph, pending = await _graph(project_id)
    return _response(project_graph(graph, level=level, kinds=kinds, doc_id=doc_id, depth=depth), pending)


@router.get('/{project_id}/graph/stats')
async def graph_stats(project_id: str):
    graph, pending = await _graph(project_id)
    return _response({**graph['stats'], **({'building': True} if pending else {})}, pending)


@router.get('/{project_id}/graph/node/{node_id:path}')
async def graph_node(project_id: str, node_id: str):
    from engine.kg import neighbours
    from engine.kg.query import path_to_project
    graph, pending = await _graph(project_id)
    node = next((n for n in graph['nodes'] if n['id'] == node_id), None)
    if node is None:
        if pending:
            return _response({'node': None, 'neighbours': [], 'path_to_project': [], 'building': True}, True)
        raise HTTPException(404, 'Graph item not found in this project.')
    return _response({'node': node, 'neighbours': neighbours(graph, node_id),
                      'path_to_project': path_to_project(graph, node_id)}, pending)
