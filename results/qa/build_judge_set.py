"""Builds results/qa/judge_questions.jsonl. Gold is computed from artifacts
(elements.json / planmap / page text), independent of engine.answer."""
import sys, json, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from engine.solvers import data

A = Path("artifacts")
AC = "ifc_bench__ac20-arc"
C1, C2 = "cubicasa5k__colorful-11397", "cubicasa5k__colorful-11398"
SW = "swiss_dwellings__site1000-bldg2082-floor9385"
AAL = "opening_design__aalseth-residence-transfer-20190321-to-lumber-yard-latest-plans-with-door-and-window-schedule-sheet-a600-3196-aalseth-lane-schedules"
CTR = "opening_design__ctr-most-current-set-full-size-sheets-a020-life-safety"
D = {k: data.load_doc(k, A) for k in (AC, C1, C2, SW)}
Q = []

def add(doc, q, typ, value=None, must=None, tol=0.0, src="", abstain=False, note=""):
    Q.append(dict(id=f"J{len(Q)+1:02d}", doc_id=doc, question=q, type=typ, value=value,
                  must=must or [], tol=tol, source=src, expect_abstain=abstain, note=note))

def items(d, k): return [i for i in D[d].items if i.kind == k and (D[d].mode == "ifc" or i.conf >= 0.5)]   # plan maps: conf >= 0.5, as the solver
def area(i): return i.q.get("area_m2") or i.q.get("net_floor_area_m2") or 0
def rname(i): return (i.props.get("long_name") or i.label or "")

# ---- AC20 (IFC)
ac_w = collections.Counter(i.storey for i in items(AC, "window"))
ac_d = collections.Counter(i.storey for i in items(AC, "door"))
rooms = items(AC, "room")
wc = [r for r in rooms if rname(r).startswith("WC")]
wc_area = round(sum(area(r) for r in wc), 2)
eg = [r for r in rooms if r.storey == "Erdgeschoss"]
by_storey = collections.defaultdict(float)
for r in rooms: by_storey[r.storey] += area(r)
big = max(rooms, key=area)
bur = [r for r in rooms if rname(r).lower().startswith("buero")]
wide = [i for i in items(AC, "door") if (i.q.get("width_m") or 0) > 1.0]
eg_win_area = round(sum(i.q.get("area_m2", 0) for i in items(AC, "window") if i.storey == "Erdgeschoss"), 2)
src = "artifacts/ifc_bench__ac20-arc/elements.json"
add(AC, "How many windows are on the ground floor?", "count", ac_w["Erdgeschoss"], src=src)
add(AC, "Which floor has the most doors?", "compare", must=[max(ac_d, key=ac_d.get)], src=src, note=str(dict(ac_d)))
add(AC, "How many doors are wider than 1 m?", "count_cond", len(wide), src=src)
add(AC, "How many m2 of floor tiles do I need for all the WCs including 10% waste?", "takeoff", round(wc_area*1.1, 1), tol=0.03, src=src, note=f"wc rooms {len(wc)} area {wc_area}")
add(AC, "What is the total floor area of the WCs?", "area", wc_area, tol=0.02, src=src)
add(AC, "How many offices are there in the building?", "count", len(bur), src=src, note="rooms whose name starts with Buero")
add(AC, "What is the total floor area of the Erdgeschoss rooms?", "area", round(sum(area(r) for r in eg), 1), tol=0.02, src=src)
add(AC, "Which storey has the largest total room area?", "compare", must=[max(by_storey, key=by_storey.get)], src=src, note=str({k: round(v) for k, v in by_storey.items()}))
add(AC, "What is the largest room and how big is it?", "compare", round(area(big), 1), tol=0.02, src=src)
add(AC, "How many windows are there in total on the building and how many on the 2nd floor?", "count_multi", must=[str(len(items(AC, 'window'))), str(ac_w['2. Obergeschoss'])], src=src)
add(AC, "What is the total glazed area of the windows on the ground floor?", "takeoff", eg_win_area, tol=0.03, src=src)
add(AC, "Where is the stair core on the first floor?", "where", must=["1. Obergeschoss"], src=src+" (IfcStair, storey)")
add(AC, "Do the exits on the ground floor meet the Finnish fire-escape rules?", "rule", must=["848/2017"], src="engine/rules/fire_escape.yaml")
add(AC, "Remove the front door. Is the building still compliant?", "edit", must=["848/2017", "33"], src="engine/rules/fire_escape.yaml §33 (two exits per storey)")
add(AC, "Do all doors meet the accessibility clear width requirement?", "rule", must=["241/2017"], src="engine/rules/accessibility.yaml")
add(AC, "How many rooms are on the Keller level?", "count", sum(1 for r in rooms if r.storey == "Keller"), src=src)

add(AC, "Are the stairs wide enough according to the Finnish safety rules?", "rule", must=["1007/2017"], src="engine/rules/safety_in_use.yaml (stair width §3)")
add(AC, "Is the headroom in the doorways sufficient?", "rule", must=["1007/2017", "14"], src="engine/rules/safety_in_use.yaml (§14)")
add(AC, "Do the stairs meet the riser and tread requirements?", "rule", must=["1007/2017"], src="engine/rules/safety_in_use.yaml (§4)")
add(AC, "Does every storey have two exits as required?", "rule", must=["848/2017", "33"], src="engine/rules/fire_escape.yaml (§33)")
add(C1, "Does this plan meet the accessibility requirements?", "rule", must=["IFC"], src="plan maps have no heights/exits; expect 'checks need an IFC model'")

# ---- CubiCasa 11397 / 11398
def croom(d, t): return [r for r in items(d, "room") if r.props.get("room_type") == t]
s1 = "artifacts/cubicasa5k__colorful-11397/planmap-1.json (scale 0.029 m/px, door-prior conf 0.3)"
add(C1, "How many windows and doors are there?", "count_multi", must=["11 windows", "11 doors"], src=s1)
add(C1, "How many bedrooms are there and what is their combined floor area?", "takeoff", must=["3", str(round(sum(area(r) for r in croom(C1,'bedroom')),1))], tol=0.05, src=s1)
add(C1, "How many m2 of flooring for the living room and kitchen with 10% extra?", "takeoff", round((sum(area(r) for r in croom(C1,'living')+croom(C1,'kitchen')))*1.1,1), tol=0.05, src=s1)
add(C1, "What is the biggest room in this plan?", "compare", must=["terrace"], src=s1)
add(C1, "Where is the entrance door?", "where", must=["door"], src=s1+" (entrance = door touching exterior extent)")
add(C1, "If I remove the front door, is there still an exit?", "edit", must=["exit"], src=s1)
s2 = "artifacts/cubicasa5k__colorful-11398/planmap-1.json (scale 0.0143 m/px, door-prior conf 0.3)"
add(C2, "How many toilets and sinks does the plan have?", "count_multi", must=["2 toilets", "3 sinks"], src=s2)
add(C2, "What is the area of the kitchen?", "area", area(croom(C2,'kitchen')[0]), tol=0.05, src=s2)
add(C2, "How many bedrooms are there?", "count", len(croom(C2,'bedroom')), src=s2)
add(C2, "Which is bigger, the living room or the kitchen?", "compare", must=["living"], src=s2)
add(C2, "How many windows are there?", "count", len(items(C2,"window")), src=s2)

# ---- Swiss DXF
sw_r = items(SW, "room")
lab = [r for r in sw_r if r.label]
zim = [r for r in lab if r.label.startswith("Zimmer")]
ssrc = "artifacts/swiss_dwellings__site1000-bldg2082-floor9385/planmap-1.json (dxf units, conf 1.0)"
kue = [r for r in lab if r.label.startswith("Küche")]
add(SW, "How many doors and windows does this floor have?", "count_multi", must=[str(len(items(SW,'door'))), str(len(items(SW,'window')))], src=ssrc)
add(SW, "What is the total area of all the kitchens?", "area", round(sum(area(r) for r in kue), 2), tol=0.03, src=ssrc, note=f"{len(kue)} Küche rooms")
add(SW, "How many Zimmer rooms are there and what is their total area?", "takeoff", must=[str(len(zim)), str(round(sum(area(r) for r in zim),1))], tol=0.03, src=ssrc)
add(SW, "Which room is the largest?", "compare", must=[max(lab, key=area).label, str(round(area(max(lab, key=area)),2))], src=ssrc)
add(SW, "How many doors have a leaf wider than 0.9 m?", "count_cond", sum(1 for d in items(SW,'door') if (d.props.get('leaf_len_m') or 0) > 0.9), src=ssrc)

# ---- PDFs (gold from page text)
a = "artifacts/%s/text-1.json (Room/Window/Door schedules)" % AAL
add(AAL, "How many windows are listed in the window schedule in total?", "text", must=["39"], src=a)
add(AAL, "How many type 07 windows are there and what is their size?", "text", must=["19", "3'-3 1/4"], src=a)
add(AAL, "What is the width of exterior door 04?", "text", must=["5' 3-1/4"], src=a)
add(AAL, "How many exterior door types are outswing?", "text", must=["3"], src=a, note="02, 04, 05")
add(AAL, "What is the area of the basement boat house?", "text", must=["371|34.4"], src=a)
add(AAL, "How many rooms are on the room schedule and what is the total area?", "text", must=["22", "3672|3671"], src=a)
c = "artifacts/%s/text-1.json (life safety plan)" % CTR
add(CTR, "What is the occupant load of the community room?", "text", must=["27.3"], src=c, note="410 SF / 15 SF per occupant")
add(CTR, "What is the area of the fitness room?", "text", must=["210"], src=c)
add(CTR, "Who is the architect on this project?", "text", must=["OpeningDesign"], src=c)
add(CTR, "Who is the general contractor?", "text", must=["Royal"], src=c)
add(CTR, "What occupancy classification is the basement parking garage?", "text", must=["S-2"], src=c)

with open("results/qa/judge_questions.jsonl", "w") as f:
    for q in Q: f.write(json.dumps(q, ensure_ascii=False) + "\n")
print(len(Q), collections.Counter(q["doc_id"][:12] for q in Q))
for q in Q: print(q["id"], q["type"], q["value"], q["must"], "|", q["question"][:60])
