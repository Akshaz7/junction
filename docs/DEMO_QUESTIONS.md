# Demo questions for judges
Generated for demo. Every answer below was produced by `engine.answer` locally on 2026-11-14; raw rows are in `results/demo_questions.json`. All nine answered by code with no model call: cost $0.00 each, 0.0 to 0.12 s. Use the ac20 model (`ifc_bench__ac20-arc`) except Q9.
Order is the suggested running order. Numbers in square brackets are the numbered boxes that glow in 2D, 3D and AR.

## 1. Take-off with waste and price

**Ask:** How much floor tiling should I order for all WC Herren and WC Damen rooms from Keller through 2. Obergeschoss, allowing 10% waste, if each box covers 1.44 m² and costs €32 excluding VAT? Give the room breakdown, whole boxes and total material cost.

**Why:** Show: tile order from the model's room areas, whole boxes, price. Every number is code over the IFC quantities.

**Expected answer** (confidence 0.95, route code, 4 cited items, cost $0.00):

> **Scope I applied:** every WC Herren / WC Damen room on Keller, Erdgeschoss, 1. Obergeschoss, 2. Obergeschoss; floor area = net floor area from the model.
> 
> | Storey | Room | Net floor area (m²) |
> |---|---|---|
> | Keller | WC Damen | 12.38 |
> | Keller | WC Herren | 12.38 |
> | Erdgeschoss | WC Damen | 12.38 |
> | Erdgeschoss | WC Herren | 12.38 |
> | 1. Obergeschoss | WC Damen | 12.38 |
> | 1. Obergeschoss | WC Herren | 12.38 |
> | 2. Obergeschoss | WC Damen | 12.38 |
> | 2. Obergeschoss | WC Herren | 12.38 |
> 
> Net floor area total: **99.02 m²**.
> With 10% waste: **108.92 m²**.
> Whole boxes at 1.44 m² each: **76 boxes** (109.44 m²).
> Cost: 76 x EUR 32 = **EUR 2,432.00 excluding VAT**.
> 
> Conditions applied: rooms: 8 matched; storeys: Keller to 2. Obergeschoss; waste 10%; box coverage 1.44 m²; price EUR 32 per box, excluding VAT. [1] [2] [3] [4]

## 2. Paint take-off

**Ask:** For a budget allowance, assume both faces of every internal wall on 1. Obergeschoss are painted. How many 9-litre tins are needed for two coats at 8 m²/litre per coat, with 10% extra paint, excluding reveals and ceilings?

**Why:** Both faces, two coats, extra paint, whole tins; reveals and ceilings are named as excluded.

**Expected answer** (confidence 0.95, route code, 1 cited items, cost $0.00):

> **Scope I applied:** internal walls (not external) on 1. Obergeschoss, 2 face(s) each, net of openings.
> 
> Painted area: 378.12 m² net per face x 2 = **756.24 m²**.
> Paint: 756.24 x 2 coats / 8 = 189.1 litres, +10% = **208.0 litres**.
> Tins of 9 litres: **24 tins**.
> 
> Conditions applied: internal walls: 21; 2 faces; 2 coats; 8 m²/litre per coat; 10% extra; 9 litre tins; reveals excluded (side-area figure only); ceilings excluded (not measured). [1]

## 3. Masonry budget by storey

**Ask:** What is the budget material quantity and cost for the internal Kalksandstein walls on 1. Obergeschoss and 2. Obergeschoss, using net masonry volume plus 5% waste at an assumed €210/m³ excluding VAT? Separate the two storeys.

**Why:** Net volume (openings removed), waste, assumed unit price labelled as an assumption.

**Expected answer** (confidence 0.95, route code, 2 cited items, cost $0.00):

> **Scope I applied:** internal Kalksandstein walls on 1. Obergeschoss, 2. Obergeschoss, net volume (openings removed), shown per storey.
> 
> | Storey | Walls | Net volume (m³) | +5% (m³) | Cost excl. VAT |
> |---|---|---|---|---|
> | 1. Obergeschoss | 21 | 96.42 | 101.24 | EUR 21,261 |
> | 2. Obergeschoss | 21 | 96.84 | 101.68 | EUR 21,353 |
> 
> Total: 193.26 m³, with waste 202.92 m³, **EUR 42,614 excluding VAT** (assumed unit price).
> 
> Conditions applied: walls: 42; storeys: 1. Obergeschoss, 2. Obergeschoss; net volume; 5% waste; EUR 210/m³ excluding VAT. [1] [2]

## 4. Multi-condition filter (rooms)

**Ask:** On 1. Obergeschoss, list offices with net floor areas from 12 to 25 m² inclusive, excluding the secretary's office and all rooms assigned to Mueller or Obermueller. Sort by area, then room number.

**Why:** Shows the honest partial: names the near misses and says occupants are only read from the room label.

**Expected answer** (confidence 0.6, route code, 1 cited items, cost $0.00):

> **Scope I applied:** offices on 1. Obergeschoss with net floor area 12 to 25 m² inclusive, excluding the secretary's office and rooms whose name contains muller, obermuller.
> 
> | Room no. | Name | Net area (m²) |
> |---|---|---|
> | 204 | Buero Oberschmitt | 24.75 |
> 
> Just under the 12 m² limit on net area: Buero Schmidt (11.95 m²), Buero Schmid (11.95 m²), Buero Schmied I (11.95 m²), Buero Schmitt I (11.95 m²), Buero Schmitt II (11.95 m²).
> 
> Conditions applied: storey 1. Obergeschoss; offices identified by room name; net area 12-25 m² inclusive; secretary's office excluded; names excluded: muller, obermuller (ü and ue spellings treated alike).
> 
> **Partial answer. Not applied or not verifiable from this document:** the model has no occupant assignment; 'assigned to' is read from the name in the room label. [1]

## 5. Multi-condition filter (windows)

**Ask:** Which external windows on Erdgeschoss or 1. Obergeschoss are 0.9 m wide and 2.0 m high? Group them by storey and type, and give their total nominal opening area without including the 1.5 m-high windows.

**Why:** Exact size, external, two storeys, grouped by type, total opening area.

**Expected answer** (confidence 0.95, route code, 1 cited items, cost $0.00):

> **Scope I applied:** external windows on Erdgeschoss, 1. Obergeschoss, exactly 0.9 m wide x 2.0 m high (nominal sizes from the model).
> 
> | Storey | Type | Count | Nominal opening area (m²) | Marks |
> |---|---|---|---|---|
> | Erdgeschoss | IFC Fenster - ein Panel | 3 | 5.40 | Fenster-013, Fenster-015, Fenster-015 |
> 
> **3 windows**, total nominal opening area **5.40 m²** (windows 1.5 m high not included).
> None on 1. Obergeschoss.
> 
> Conditions applied: storeys Erdgeschoss, 1. Obergeschoss; width 0.9 m; height 2.0 m; external. [1]

## 6. Stacking check

**Ask:** Do the WC Herren and WC Damen rooms stack above one another from Keller to 2. Obergeschoss, or does either room shift between floors? Report any horizontal offset and identify the corresponding rooms.

**Why:** Rooms from Keller to 2. Obergeschoss lined up by outline centre.

**Expected answer** (confidence 0.95, route code, 4 cited items, cost $0.00):

> **Scope I applied:** WC Herren and WC Damen on Keller, Erdgeschoss, 1. Obergeschoss, 2. Obergeschoss; positions are the room outline centres in plan.
> 
> | Room | Storey | Room no. | Offset from lowest storey |
> |---|---|---|---|
> | WC Herren | Keller | room 008 | 0.00 m |
> | WC Herren | Erdgeschoss | room 112 | 0.00 m |
> | WC Herren | 1. Obergeschoss | room 213 | 0.00 m |
> | WC Herren | 2. Obergeschoss | room 313 | 0.00 m |
> | WC Damen | Keller | room 009 | 0.00 m |
> | WC Damen | Erdgeschoss | room 113 | 0.00 m |
> | WC Damen | 1. Obergeschoss | room 214 | 0.00 m |
> | WC Damen | 2. Obergeschoss | room 314 | 0.00 m |
> 
> **Each WC sits directly above the one below (every offset under 5 cm): neither room shifts.**
> 
> Conditions applied: storeys Keller to 2. Obergeschoss; WC Herren, WC Damen; horizontal offset from outline centres. [1] [2] [3] [4]

## 7. Door schedule for procurement

**Ask:** Produce a procurement door schedule by storey, original door mark, type and width × height in millimetres. If Tür-005 repeats, how many physical doors does it represent, and can Tuer-016 safely be merged with Tür-016?

**Why:** Original marks kept; quantities per mark; no silent merging of look-alike marks.

**Expected answer** (confidence 0.6, route code, 4 cited items, cost $0.00):

> **Scope I applied:** every door in the model, grouped by storey, original mark, type and width x height in mm.
> 
> | Storey | Mark | Type | W x H (mm) | Qty |
> |---|---|---|---|---|
> | Keller | Tür-002 | IFC Tür - Eine Öffnunsgrichtung | 1000 x 2100 | 1 |
> | Keller | Tür-004 | IFC Tür - Eine Öffnunsgrichtung | 1000 x 2100 | 1 |
> | Keller | Tür-005 | IFC Tür - Eine Öffnunsgrichtung | 1000 x 2100 | 3 |
> | Keller | Tür-012 | IFC Tür - Eine Öffnunsgrichtung | 1000 x 2100 | 1 |
> | Keller | Tür-013 | IFC Tür - Eine Öffnunsgrichtung | 1000 x 2100 | 1 |
> | Keller | Tür-014 | IFC Tür - Eine Öffnunsgrichtung | 1000 x 2100 | 1 |
> | Keller | Tür-015 | IFC Tür - Eine Öffnunsgrichtung | 1000 x 2100 | 1 |
> | Keller | Tür-016 | IFC Tür - Eine Öffnunsgrichtung | 1000 x 2100 | 4 |
> | ... | ... | ... | ... | ... |
> (table continues for every storey; full text in results/demo_questions.json)

## 8. Can-we-remove what-if

**Ask:** Can we remove the front door?

**Why:** Front door, one item, same rule checks as the edit panel. Preview only, nothing hidden or saved. Follow with: remove it.

**Expected answer** (confidence 1.0, route index, 1 cited items, cost $0.00):

> The front door (D34) on Erdgeschoss would be removed in this what-if. 76 of 77 doors would remain. **Not compliant after this edit:** Fewer than two exits left on Erdgeschoss (848/2017 §33).[1]
> 
> Preview only: nothing was changed or saved. Say "remove it" to apply the edit.

## 9. Finnish glossary (second drawing, cubicasa colorful-11397)

**Ask:** For the wet-room scope, what do KPH and KHH+PH mean, and is WC actually written on this drawing or only indicated by toilet symbols? Identify each relevant space without counting a toilet fixture as a separate room.

**Why:** Reads KPH and KHH+PH from printed labels; says WC is not written, only toilet symbols.

**Expected answer** (confidence 0.6, route code, 1 cited items, cost $0.00):

> **Scope I applied:** the meaning of KPH and KHH+PH, whether WC is printed, and which space holds each toilet symbol.
> 
> - **KPH** = kylpyhuone (bathroom).
> - **KHH+PH** = KHH kodinhoitohuone (utility room) + PH pesuhuone (washroom): one combined space.
> - **WC is not written on this drawing**; the 2 toilets are symbols only.
> - Toilet symbol 1 is nearest to **KPH**: a fixture in that space, not a separate room.
> - Toilet symbol 2 is nearest to **KHH+PH**: a fixture in that space, not a separate room.
> 
> Conditions applied: printed labels KPH and KHH+PH; toilet fixtures not counted as rooms.
> 
> **Partial answer. Not applied or not verifiable from this document:** the nearest-label match for each toilet is by distance on the sheet, not by a room boundary. [1]

## Do not demo

- Do not ask Q4 for a clean yes/no: it is a deliberate partial answer (conf 0.6).
- Door counts differ between the cubicasa raster plan (11, estimated) and ac20 (77, from the model); say which drawing is open.
