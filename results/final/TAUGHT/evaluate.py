"""Final integration checks on real plan maps. No detection accuracy is claimed.

Source files are read only. All label projections are written into a temporary
artifact tree. The reserved random drawing is opened last, after development.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile

from engine.taught_items import project, query
from engine.solvers.data import load_doc
from engine.solvers.solve import solve
from engine.router.parser import Parsed
from engine import kg, reasoning

OUT = Path(__file__).parent
heldout = set(Path('data/sets/heldout_docs.txt').read_text().splitlines())


def check(doc_id, plan, box, label, root, reserved=False):
    directory = root/doc_id; directory.mkdir()
    page = plan.get('page') or 1
    name = f'planmap-{page}.json'
    (directory/name).write_text(json.dumps(plan))
    before_doc = load_doc(doc_id, root)
    kind = 'terminal' if label == 'TP' else 'door'
    before = sum(i.kind == kind and i.conf >= .5 for i in before_doc.items)
    mark = {'id':'manual-evaluation','name':label,'template_bbox':box,'page':page,'manual_selection':True,
            'matches':[{'id':'1','status':'confirmed'}]}
    after_plan = project(plan,[mark],page)
    (directory/name).write_text(json.dumps(after_plan))
    after_doc = load_doc(doc_id, root)
    after = sum(i.kind == kind and i.conf >= .5 for i in after_doc.items)
    answer = query('Count ' + ('terminals' if kind == 'terminal' else 'doors') + f' on page {page}',[doc_id],root)
    assert answer['answer']['value'] == after
    marked = [it for it in after_doc.items if it.props.get('confirmed_by_user')]
    assert len(marked) == 1
    assert marked[0].props['user_labels'][0]['bbox_px'] == list(box)
    nodes = [node for node in kg.build(doc_id,root)['nodes'] if node['method'] == 'user_label']
    assert len(nodes) == 1 and nodes[0]['confidence'] == 1.0
    card = reasoning.build(answer,'Count '+kind,root)
    assert card['steps'][0]['title'] == 'Marked by you'
    assert len(project(after_plan,[mark],page)['items']) == len(after_plan['items'])
    removed = project(after_plan,[],page)
    assert removed['items'] == plan.get('items',[])
    return {'doc_id':doc_id,'reserved_final_only':reserved,'page':page,'manual_label':label,'selected_box':box,
            'before_count':before,'after_count':after,'marked_items':len(marked),'new_items':after-before,
            'evidence_ids':answer['evidence']['scene']['highlight_item_ids'],
            'checks':['selected box retained','standard kind count','no auto matches','idempotent same mark',
                      'knowledge graph user_label confidence 1','marked-by-you reasoning','removal restores original items']}


def main():
    rows=[]
    with tempfile.TemporaryDirectory(prefix='taught-real-eval-') as temp:
        root=Path(temp)
        # Non-standard air-terminal arrow on the real ventilation plan: manually
        # selected from the earlier F-MARKUP human annotation, not an inferred hit.
        plan={'doc_id':'manual-ventilation-check','page':1,'image':{'w':4762,'h':2526},
              'scale':{'m_per_px':None,'method':'none','confidence':0},'items':[]}
        rows.append(check('manual-ventilation-check',plan,[1568,1745,1591,1755],'TP',root))
        for origin in ('wikimedia','habs'):
            paths = sorted(p for p in Path('data/vision_gen').glob(origin+'__*/planmap-1.json') if p.parent.name not in heldout)
            path=paths[0]; plan=json.loads(path.read_text())
            usable=[i for i in plan.get('items',[]) if i.get('bbox_px') and i['bbox_px'][2]>i['bbox_px'][0] and i['bbox_px'][3]>i['bbox_px'][1]]
            assert usable, f'No selectable item in {path}'
            item=next((i for i in usable if i['kind']=='door'),usable[0])
            rows.append(check(path.parent.name,plan,item['bbox_px'],'ovi',root))
        # This is deliberately the last file opened. It was randomly reserved
        # before development and has not been used to set thresholds or aliases.
        path=Path(json.loads((OUT/'reserved.json').read_text())['held_back_until_final'])
        assert path.parent.name not in heldout
        plan=json.loads(path.read_text())
        usable=[i for i in plan.get('items',[]) if i.get('bbox_px') and i['bbox_px'][2]>i['bbox_px'][0] and i['bbox_px'][3]>i['bbox_px'][1]]
        assert usable, 'Reserved file has no selectable box'
        item=next((i for i in usable if i['kind']=='door'),usable[0])
        rows.append(check(path.parent.name,plan,item['bbox_px'],'Tür',root,True))
    result={'method':'Manual-label integration only. No automatic symbol recognition, precision, recall, or whole-sheet completeness claimed.',
            'source_files_modified':False,'live_model_calls':0,'sheets':rows,'status':'PASS'}
    (OUT/'eval.json').write_text(json.dumps(result,indent=2,ensure_ascii=False))
    print(json.dumps({'status':'PASS','real_sources':len(rows),'reserved_final_only':rows[-1]['doc_id'],
                      'before_after':[[r['before_count'],r['after_count']] for r in rows]}))

if __name__=='__main__':main()
