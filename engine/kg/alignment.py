"""Optional read-only vector alignment hook. PDF extraction remains owned by Awais.

Expected API: pipeline.pdf_mep.load(path, page_index=0) -> {W_pt,H_pt,...};
align(page_a,page_b) -> {s,R:[[...],[...]],t:[...],residual:points,matches:int}.
All transforms exposed to the graph are converted into metres before matching.
"""
from __future__ import annotations

import importlib
import math
import time

from .build import read_dict


def vector_alignment(b, a, z):
    from .mep import resolve_source
    da, dz = b.nodes[a]['source']['doc_id'], b.nodes[z]['source']['doc_id']
    pa, pz = b.nodes[a]['source']['page'], b.nodes[z]['source']['page']
    ma, mz = read_dict(b.root/da/'doc.json'), read_dict(b.root/dz/'doc.json')
    if not all(m.get('kind') == 'pdf' or 'pdf' in (m.get('formats') or []) for m in (ma,mz)):
        return None
    if not hasattr(b,'_vector_alignments'):
        b._vector_alignments = {}
        b._vector_deadline = time.monotonic()+10
    key = (da,pa,dz,pz)
    if key in b._vector_alignments:
        return b._vector_alignments[key]
    b._vector_alignments[key] = None
    if time.monotonic() > b._vector_deadline:
        return None
    try:
        api=importlib.import_module('pipeline.pdf_mep')
    except ImportError:
        note={'note':'Vector alignment unavailable: optional pipeline.pdf_mep is not installed; matching uses indexed rooms and labels.'}
        if note not in b.warnings:
            b.warnings.append(note)
        return None
    paths=[resolve_source(m,b.root,'pdf') for m in (ma,mz)]
    if not all(paths):
        return None
    try:
        pages=[api.load(p,page_index=pg-1) for p,pg in zip(paths,(pa,pz))]
        pms=[read_dict(b.root/did/f'planmap-{pg}.json') for did,pg in ((da,pa),(dz,pz))]
        scales=[]
        for page,pm in zip(pages,pms):
            scale=pm.get('scale') or {}
            mpp=scale.get('m_per_px')
            width=(pm.get('image') or {}).get('w')
            if not isinstance(mpp,(int,float)) or mpp<=0 or not width or scale.get('method') in ('none','door-prior',None) or (scale.get('confidence') or 0)<.6:
                return None
            scales.append(mpp*width/page['W_pt'])
        raw=api.align(*pages)
        if not isinstance(raw,dict):
            return None
        matches=raw.get('matches',raw.get('n_inliers',0))
        residual=float(raw.get('residual',raw.get('rms_pt',math.inf)))*scales[1]
        s=float(raw['s'])*scales[1]/scales[0]
        if matches<3 or not math.isfinite(residual) or residual<0 or residual>.1 or not .9<=s<=1.1:
            return None
        r,t=raw['R'],raw['t']
        matrix=[[s*r[0][0],s*r[0][1],t[0]*scales[1]],
                [s*r[1][0],s*r[1][1],t[1]*scales[1]],[0.,0.,1.]]
        if not all(math.isfinite(v) for row in matrix for v in row):
            return None
        result={'T':matrix,'residual':residual,'matches':int(matches),'scale':s,'source':'pipeline.pdf_mep.align'}
        b._vector_alignments[key]=result
        return result
    except (AttributeError,KeyError,TypeError,ValueError,RuntimeError,OSError,ImportError):
        return None
