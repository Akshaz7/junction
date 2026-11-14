"""Measured comparisons and source-backed text, revision and issue evidence. No inference calls."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from itertools import combinations, pairwise

from .build import read_dict, read_json
from .schema import norm


def _compare(b, a, z, prop, va, vz, sources, *, tolerance=0, confidence=1, **extra):
    if not isinstance(va,(int,float)) or not isinstance(vz,(int,float)):
        return
    diff=abs(vz-va)
    pct=100*diff/max(abs(va),abs(vz)) if va or vz else 0
    b.edge('agrees' if pct <= tolerance else 'differs',a,z,'rule',confidence,
           {'rule':'compare_source_values','property':prop,'values':[va,vz],'diff_pct':round(pct,4),
            'tolerance_pct':tolerance,'sources':sources,**extra})


def comparisons(b):
    """Per-level counts compare coverage of actual indexed kinds; missing extraction is never treated as zero."""
    c=b.combined
    for row in c.rows:
        for da,dz in combinations(row.docs,2):
            ia,iz=c.infos[da],c.infos[dz]
            if ia.derived or iz.derived:
                continue
            for kind in ('room','door','window'):
                sa,sz=row.docs[da][kind],row.docs[dz][kind]
                # A plan map with no windows anywhere cannot disprove the model's windows.
                if not any(i.kind==kind for i in ia.doc.items) or not any(i.kind==kind for i in iz.doc.items):
                    continue
                a=b.level(da,ia.level if ia.doc.mode=='planmap' and ia.level else row.name)
                z=b.level(dz,iz.level if iz.doc.mode=='planmap' and iz.level else row.name)
                sources=[{'doc_id':da,'item_ids':sa['ids']},{'doc_id':dz,'item_ids':sz['ids']}]
                conf=min([b.nodes[n]['props'].get('confidence',1) for did in (da,dz) for item in row.docs[did][kind]['ids']
                          for n in b.item_nodes.get((did,item),[])] or [1])
                _compare(b,a,z,f'{kind}_count',sa['n'],sz['n'],sources,confidence=conf,level=row.name)
                if kind=='room' and sa.get('areas_known')==sa['n'] and sz.get('areas_known')==sz['n']:
                    _compare(b,a,z,'area_m2',sa.get('area'),sz.get('area'),sources,tolerance=3,confidence=conf,level=row.name)
    for e in list(b.edges.values()):
        if e['kind']!='same_as':
            continue
        a,z=b.nodes[e['from']],b.nodes[e['to']]
        derived = any(b.combined.infos[n['source']['doc_id']].derived for n in (a,z))
        if not derived and a['kind']=='room' and z['kind']=='room':
            _compare(b,a['id'],z['id'],'area_m2',a['props'].get('area_m2'),z['props'].get('area_m2'),
                     [a['source'],z['source']],tolerance=3,confidence=e['confidence'],identity_edge=e['id'])


def _words(b,did):
    """Existing text only; no PDF ingestion/rendering or OCR. Returns page, text, bbox records."""
    folder=b.root/did
    for p in sorted(folder.glob('text-[0-9]*.json')):
        d=read_dict(p)
        page=int(p.stem.split('-')[-1])
        for w in d.get('words') or []:
            if isinstance(w,dict) and str(w.get('text') or '').strip():
                yield int(page),str(w['text']),w.get('bbox_px')
        if d.get('text'):
            yield int(page),str(d['text']),None
    d=read_dict(folder/'text.json')
    if isinstance(d,dict):
        for p in d.get('pages') or []:
            for w in p.get('words') or []:
                if isinstance(w,dict) and w.get('text'):
                    yield int(p.get('page') or 1),str(w['text']),w.get('bbox_px')
    for filename in ('text.txt','source.txt','source.csv','source.md'):
        path=folder/filename
        if path.is_file() and path.stat().st_size <= 2*1024*1024:
            yield 1,path.read_text(encoding='utf-8',errors='replace'),None
    # Uploaded text/schedules may only have their original registry path.
    meta=read_dict(folder/'doc.json')
    for fmt,rel in (meta.get('files') or {}).items():
        if fmt.lower() not in ('txt','text','csv','md','tsv'):
            continue
        for base in (b.root.resolve().parent,b.root.resolve().parent/'data'/'junction-dataset-preview',
                     b.root.resolve().parent/'data'/'full'/'junction-dataset'):
            path=base/rel
            if path.is_file() and path.stat().st_size <= 2*1024*1024:
                yield 1,path.read_text(encoding='utf-8',errors='replace'),None
                break


def _ref(b,did,page,text,bb):
    local=hashlib.sha256(str((page,text,bb)).encode()).hexdigest()[:20]
    source={'doc_id':did,'page':page,'item_id':None,'bbox':bb}
    rn=b.node('sheet_ref',did,local,text,props={'quote':text},source=source)
    b.edge('contains',b.doc_nodes[did],rn,'rule',1,{'rule':'document_text','source':source})
    return rn


def references(b):
    from engine.docmeta import derive, sheet_code
    targets=defaultdict(list)
    sheets=defaultdict(list)
    for did, info in b.combined.infos.items():
        meta=read_dict(b.root/did/'doc.json')
        code=meta.get('sheet') or meta.get('sheet_number') or sheet_code(info.title) or derive({**meta,'doc_id':did}).get('sheet')
        if code:
            sheets[norm(code)].append(did)
    # References only use meaningful, unique labels/tags in each source. Generic type words are too ambiguous.
    for nid in b.items:
        n=b.nodes[nid]
        for value in (n['props'].get('tag'),n['props'].get('mark'),n['label'] if n['kind']=='room' else None):
            text=norm(value)
            if text and text!=n['kind'] and len(text)>=2:
                targets[text].append(nid)
    for did,info in b.combined.infos.items():
        # Derived sheets are explicit views of their parent model, not independent confirmation.
        if info.derived:
            parent=(info.doc.meta or {}).get('sheet_of')
            if parent in b.doc_nodes:
                b.edge('references',b.doc_nodes[did],b.doc_nodes[parent],'rule',1,
                       {'rule':'derived_model_sheet','parent_doc_id':parent,'level':info.level})
        for page,text,bb in _words(b,did):
            folded=norm(text)
            code=norm(sheet_code(text))
            if code in sheets:
                destinations=[target for target in sheets[code] if target!=did]
                if len(destinations)==1:
                    rn=_ref(b,did,page,text if len(text)<=300 else code,bb)
                    b.edge('references',rn,b.doc_nodes[destinations[0]],'label_text',.5,
                           {'sheet_code':code,'quote':text[:300],'source':b.nodes[rn]['source']})
            # Exact text runs preserve citations; longer plain-text files may contain an explicit tag as a token.
            matches=[folded] if folded in targets else [k for k in targets if re.search(r'(?<!\w)'+re.escape(k)+r'(?!\w)',folded)]
            for key in matches:
                by_doc=defaultdict(list)
                for nid in targets[key]:
                    if b.nodes[nid]['source']['doc_id']!=did:
                        by_doc[b.nodes[nid]['source']['doc_id']].append(nid)
                unique=[ids[0] for ids in by_doc.values() if len(set(ids))==1]
                if not unique:
                    continue
                quote=key if len(text)>300 else text
                rn=_ref(b,did,page,quote,bb)
                for nid in unique:
                    b.edge('references',rn,nid,'label_text',.5,
                           {'text':key,'quote':quote,'source':b.nodes[rn]['source'],'target_source':b.nodes[nid]['source']})


def _changes(b,diff,local):
    da,dz=diff.get('doc_a'),diff.get('doc_b')
    if da not in b.doc_nodes or dz not in b.doc_nodes or diff.get('generated_for_demo'):
        return
    b.edge('revision_of',b.doc_nodes[dz],b.doc_nodes[da],'revision_compare',1,
           {'source':local,'doc_a':da,'doc_b':dz})
    for index,ch in enumerate(diff.get('changes') or []):
        did=da if ch.get('type')=='removed' else dz
        page=ch.get('page_v1' if did==da else 'page_v2') or ch.get('page') or 1
        bb=ch.get('bbox_px_v1' if did==da else 'bbox_px_v2')
        source={'doc_id':did,'page':page,'item_id':ch.get('v1_item' if did==da else 'v2_item'),'bbox':bb}
        cn=b.node('change',dz,f'{local}:{ch.get("change_id") or index}',ch.get('description') or 'Drawing changed',
                  doc_ids=[da,dz],props={k:v for k,v in ch.items() if k not in ('description',)},source=source)
        b.edge('contains',b.doc_nodes[dz],cn,'revision_compare',1,{'source':local,'change_id':ch.get('change_id')})
        targets=[]
        for d,key,p in ((da,'v1_item',ch.get('page_v1')),(dz,'v2_item',ch.get('page_v2'))):
            target=b.lookup(d,ch.get(key),p)
            if target:
                targets.append(target)
        if not targets:
            # Region diffs have no element IDs. Keep the actual changed region, never guess an element from its box.
            targets=[_ref(b,did,int(page),'Changed drawing region',bb)] if bb else [b.doc_nodes[did]]
        for target in targets:
            b.edge('changed',cn,target,'revision_compare',1,
                   {'source':local,'change_id':ch.get('change_id'),'change_type':ch.get('type'),'source_region':source})


def revisions_and_issues(b):
    for path in sorted((b.root/'series').glob('*.json')):
        s=read_dict(path)
        if s.get('generated_for_demo'):
            continue
        versions=s.get('versions') or []
        for prev,cur in pairwise(versions):
            da,dz=prev.get('doc_id'),cur.get('doc_id')
            if da in b.doc_nodes and dz in b.doc_nodes:
                b.edge('revision_of',b.doc_nodes[dz],b.doc_nodes[da],'revision_compare',1,
                       {'series_id':s.get('series_id'),'versions':[prev,cur]})
    for path in sorted((b.root/'series'/'diffs').glob('*.json')):
        _changes(b,read_dict(path),path.stem)
    seen=set()
    for did in b.doc_nodes:
        for filename in ('changes.json','revision.json','comparison.json'):
            d=read_json(b.root/did/filename,{}) or {}
            if isinstance(d,dict):
                _changes(b,d,f'{did}:{filename}')
        d=read_json(b.root/did/'mistakes.json',{}) or {}
        issues=d.get('mistakes',[]) if isinstance(d,dict) else d if isinstance(d,list) else []
        for issue in issues:
            iid=issue.get('id')
            if not iid or iid in seen:
                continue
            seen.add(iid)
            docs=[d for d in issue.get('doc_ids',[]) if d in b.doc_nodes] or [did]
            nid=b.node('issue',b.pid,str(iid),issue.get('title') or 'Item to check',doc_ids=docs,
                       props={'severity':issue.get('severity'),'text':issue.get('text'),'check':issue.get('check'),
                              'basis':issue.get('basis')})
            for d in docs:
                b.edge('contains',b.doc_nodes[d],nid,'rule',1,{'rule':'existing_mistake','issue_id':iid})
            targets=[n for d in docs for item in issue.get('item_ids',[]) for n in b.item_nodes.get((d,str(item)),[])]
            # A document-level finding need not invent an item citation.
            for target in targets or [b.doc_nodes[d] for d in docs]:
                b.edge('flags',nid,target,'rule',1 if issue.get('basis')=='exact' else .5,
                       {'rule':(issue.get('evidence') or {}).get('kind') or 'existing_mistake','finding':issue,
                        'source':b.nodes[target]['source']})
