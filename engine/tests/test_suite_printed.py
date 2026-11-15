import time
import pytest
from engine.reader.text import PageText
from engine.solvers.printed import printed_total


def page(lines):
    words=[]
    for y,line in enumerate(lines):
        x=0
        for w in line.split():
            words.append({'text':w,'bbox_px':[x,y*30,x+len(w)*7,y*30+14]});x+=len(w)*7+7
    return PageText('generated-for-demo',1,800,800,words,'generated for demo')


def test_ocr_glued_full_floor_label_wins_over_wing_subtotal():
    pt=page(['TOTAL NORTH WING = 510 SF', 'TOTALFOURTHFLOOR= 2340 SF'])
    r=printed_total('What is the total fourth floor area in m2?','generated-for-demo',[pt],'Fourth Floor Plan',time.perf_counter())
    assert r['answer']['value'] == pytest.approx(2340*.09290304,abs=.0001)
    assert 'TOTALFOURTHFLOOR' in r['citations'][0]['quote']


def test_count_selects_whole_building_and_not_selected_floor():
    pt=page(['General note FIRST FLOOR= 12 DORMS', 'SECONDFLOOR= 13 DORMS', 'TOTAL = 25 DORMS'])
    r=printed_total('How many dorm rooms are in the whole building?','generated-for-demo',[pt],'Second Floor Plan',time.perf_counter())
    assert r['answer']['value'] == 25
    s=printed_total('How many dorm rooms are on this floor?','generated-for-demo',[pt],'Second Floor Plan',time.perf_counter())
    assert s['answer']['value'] == 13
    assert printed_total('How many accessible dorm rooms are on this floor?','generated-for-demo',[pt],'Second Floor Plan',time.perf_counter()) is None


def test_ambiguous_or_missing_full_total_defer():
    pt=page(['TOTAL NORTH WING = 510 SF', 'TOTAL SOUTH WING = 730 SF'])
    r=printed_total('What is the total floor area?','generated-for-demo',[pt],'Fourth Floor Plan',time.perf_counter())
    assert r['answer']['value'] is None and 'not substituted' in r['answer']['text_md']
    pt=page(['TOTALFOURTHFLOOR= 2340 SF','TOTALFOURTHFLOOR= 2510 SF'])
    assert printed_total('What is the total fourth floor area?','generated-for-demo',[pt],'Fourth Floor Plan',time.perf_counter()) is None


def test_sheet_ids_are_cited_from_existing_page_title_blocks(tmp_path):
    import json
    from engine.solvers.printed import cite_sheet_numbers
    d=tmp_path/'generated-for-demo';d.mkdir()
    words=[{'text':'B207','bbox_px':[730,710,790,750]}]
    (d/'text-2.json').write_text(json.dumps({'image':{'w':800,'h':800},'words':words}))
    result={'answer':{'text_md':'Sections are on page 2.'},'citations':[{'n':1,'doc_id':d.name,'page':2}],
            'evidence':{'boxes':[]},'trace':[]}
    r=cite_sheet_numbers(result,'Which sheets show the building sections?',tmp_path)
    assert '**B207** (page 2) [2]' in r['answer']['text_md']
    assert r['citations'][1]['quote']=='B207' and r['citations'][1]['bbox_px']==[730,710,790,750]
    assert cite_sheet_numbers(r,'Which sheets show the building sections?',tmp_path) is r
    assert len(r['citations'])==2
