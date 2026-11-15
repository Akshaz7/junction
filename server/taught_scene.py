"""Refresh generated scenes after a manual mark, using the normal extrusion code."""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile

from . import config
from .taught_store import atomic_json


def revision(directory):
    plans = [(p, json.loads(p.read_text())) for p in directory.glob('planmap-[0-9]*.json')]
    if not any(plan.get('manual_labels') for _, plan in plans):
        return None
    return hashlib.sha256(b''.join(p.read_bytes() for p, _ in sorted(plans))).hexdigest()


def build(directory):
    """Heavy worker; creates fresh assets before publishing the manifest last."""
    from pipeline.extrude import process
    directory = Path(directory)
    signature = revision(directory)
    old = json.loads((directory / 'scene.json').read_text()) if (directory / 'scene.json').is_file() else {}
    if old.get('taught_revision') == signature:
        return
    if (directory / 'elements.json').exists():
        build_ifc(directory, old, signature)
        return
    source = old.get('source_planmap') or next((p.name for p in sorted(directory.glob('planmap-[0-9]*.json'))), None)
    if not source:
        raise ValueError('No plan map is available for 3D')
    page = int(Path(source).stem.split('-')[1])
    plan = json.loads((directory / source).read_text())
    scale = (plan.get('scale') or {}).get('m_per_px')
    if not isinstance(scale, (int, float)) or scale <= 0:
        raise ValueError('3D placement needs a drawing scale. The marked item is saved in 2D.')
    with tempfile.TemporaryDirectory(prefix='taught-scene-') as temp:
        scratch = Path(temp)
        for name in (source, f'page-{page}.png', 'doc.json'):
            if (directory / name).is_file():
                shutil.copy2(directory / name, scratch / name)
        process(directory.name, scratch, page)
        manifest = json.loads((scratch / 'scene.json').read_text())
        for it in plan['items']:
            if it['item_id'] in manifest['items'] and it.get('props', {}).get('confirmed_by_user'):
                manifest['items'][it['item_id']].update({'method': 'user_label', 'label': it['props']['user_labels'][-1]['name'],
                                                       'linked_item_ids': it['props'].get('linked_item_ids', [])})
        manifest['taught_revision'] = signature
        manifest['unplaced_user_items'] = [it['item_id'] for p in directory.glob('planmap-[0-9]*.json')
                                           for it in json.loads(p.read_text()).get('items', [])
                                           if it.get('props', {}).get('confirmed_by_user') and it['item_id'] not in manifest['items']]
        manifest['usdz'] = None  # Never serve an old AR asset after updating geometry.
        atomic_json(scratch / 'scene.json', manifest)
        try:
            from pipeline.usdz import process as make_usdz
            make_usdz(directory.name, scratch)
            manifest = json.loads((scratch / 'scene.json').read_text())
        except ImportError:
            pass
        for name in ('scene.glb', 'scene.usdz'):
            if (scratch / name).is_file():
                shutil.copy2(scratch / name, directory / (name + '.taught.tmp'))
                os.replace(directory / (name + '.taught.tmp'), directory / name)
        atomic_json(directory / 'scene.json', manifest)


def build_ifc(directory, manifest, signature):
    """Keep the native model; add labelled footprint markers only with an explicit projection."""
    import numpy as np
    import trimesh
    scene = trimesh.load_scene(directory / 'scene.glb')
    items = manifest.get('items', {})
    for iid in list(items):
        if items[iid].get('taught_generated'):
            node = items.pop(iid).get('node', iid)
            if node in scene.graph.nodes_geometry:
                _, geometry = scene.graph[node]
                scene.delete_geometry(geometry)
    for item in items.values():
        if 'taught_previous_method' in item:
            previous = item.pop('taught_previous_method')
            if previous is None:
                item.pop('method', None)
            else:
                item['method'] = previous
    unplaced = []
    for path in sorted(directory.glob('planmap-[0-9]*.json')):
        plan = json.loads(path.read_text())
        projection = plan.get('projection') or {}
        for it in plan.get('items', []):
            if not it.get('props', {}).get('confirmed_by_user'):
                continue
            iid = it['item_id']
            if iid in items:
                items[iid]['taught_previous_method'] = items[iid].get('method')
                items[iid]['method'] = 'user_label'
                continue
            if not all(k in projection for k in ('ppm', 'x0', 'z0')) or projection['ppm'] <= 0:
                unplaced.append(iid)
                continue
            # Projection records its formula and margin. Refuse unknown conventions.
            import re
            mx = re.search(r'\+\s*([\d.]+)\s*$', projection.get('x_px', ''))
            mz = re.search(r'\+\s*([\d.]+)\s*$', projection.get('y_px', ''))
            if not mx or not mz:
                unplaced.append(iid)
                continue
            x0,y0,x1,y1 = it['bbox_px']; ppm = projection['ppm']
            x = ((x0+x1)/2-float(mx[1]))/ppm + projection['x0']
            z = ((y0+y1)/2-float(mz[1]))/ppm + projection['z0']
            elevation = (plan.get('storey') or {}).get('elevation_m')
            if elevation is None:
                unplaced.append(iid)
                continue
            # A thin marker represents a user box, not a measured object height.
            marker = trimesh.creation.box(extents=[(x1-x0)/ppm, .02, (y1-y0)/ppm])
            marker.apply_translation([x, elevation+.02, z])
            marker.visual.vertex_colors = [59,130,246,220]
            scene.add_geometry(marker, node_name=iid, geom_name=iid)
            from hashlib import sha1
            items[iid] = {'node': iid, 'usd_name': 'i_'+sha1(iid.encode()).hexdigest()[:16], 'kind': it['kind'],
                          'bbox_m': np.asarray(marker.bounds).tolist(), 'method': 'user_label', 'taught_generated': True,
                          'label': it.get('label'), 'storey': (plan.get('storey') or {}).get('name'),
                          'note': 'generated for demo: footprint marker for an item marked by you'}
    manifest.update({'taught_revision': signature, 'items': items, 'unplaced_user_items': unplaced, 'usdz': None})
    # The old USDZ is deliberately disabled until rebuilt from the updated GLB.
    temp = directory / 'scene.glb.taught.tmp'
    temp.write_bytes(scene.export(file_type='glb'))
    os.replace(temp, directory / 'scene.glb')
    atomic_json(directory / 'scene.json', manifest)
    try:
        from pipeline.usdz import process as make_usdz
        make_usdz(directory.name, directory)
    except (ImportError, KeyError, ValueError):
        pass  # 3D still works; the manifest explicitly leaves the updated AR asset unavailable.


async def ensure(doc_id):
    directory = config.artifacts_dir() / doc_id
    signature = revision(directory)
    if signature is None:
        return
    manifest = json.loads((directory / 'scene.json').read_text()) if (directory / 'scene.json').is_file() else {}
    if manifest.get('taught_revision') == signature:
        return
    if not (directory / 'elements.json').exists():
        source = manifest.get('source_planmap') or next((p.name for p in sorted(directory.glob('planmap-[0-9]*.json'))), None)
        plan = json.loads((directory / source).read_text()) if source else {}
        scale = (plan.get('scale') or {}).get('m_per_px')
        if not isinstance(scale, (int, float)) or scale <= 0:
            raise ValueError('3D placement needs a drawing scale. The marked item is saved in 2D.')
    from . import db
    pool = await db.get_pool()
    if pool is None:
        raise ValueError('3D refresh is temporarily unavailable; the item is saved in 2D')
    async with pool.acquire() as c:
        # Serialise rebuilds and saves for this document across API processes.
        async with c.transaction():
            await c.execute('select pg_advisory_xact_lock(hashtext($1))', 'taught:' + doc_id)
            process = await asyncio.create_subprocess_exec('bash', str(config.REPO / 'scripts/heavy.sh'),
                          sys.executable, '-m', 'server.taught_scene', str(directory),
                          cwd=str(config.REPO), start_new_session=True, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            try:
                _, error = await asyncio.wait_for(process.communicate(), timeout=55)
            except (TimeoutError, asyncio.CancelledError):
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
                raise ValueError('3D refresh is still unavailable; the item is saved in 2D')
            if process.returncode:
                # Only a short controlled explanation reaches the client.
                raise ValueError('3D needs a usable drawing scale and page image. The marked item is saved in 2D.')


if __name__ == '__main__':
    build(Path(sys.argv[1]))
