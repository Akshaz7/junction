# External stress test, round 2 (IFC: slabs, rebar, baseboard, MEP, multi-storey)
Live pilot via engine.answer, 64 questions on 9 IFCs, spend $0.34 of $3. Gold computed from the IFC by ifcopenshell (Qto, property sets, geometry); each row has how_computed and tolerance. Counts exact, area/length/volume +-10% (baseboard total +-15%). Never used for training or tuning.

## Sources and licence
- buildingSMART Community sample files (Simple-Scene, Duplex, Dental Clinic, Schependomlaan): CC BY 4.0, Duplex/Clinic CC BY-ND 3.0 (benchmark only).
- viktor-platform/ifc-sample-models: no licence stated, local test only. It is the ONLY rebar source found (IfcReinforcingBar 346 / 11). No licence-clear IFC with rebar or a slab reinforcement schedule was found; "slab by thickness and rebar" is therefore covered by Qto Depth and bar counts/lengths, not by a real rebar schedule.
- Baseboard is not stored in any IFC: gold = IfcSpace floor-face perimeter (geometry) minus widths of IfcDoor bounding the space. Our own definition; labelled so.
- MEP files carry no IfcSystem: counts and lengths by Revit family name, class and Revit "Length" property.

## Accuracy per question type (n)
| type | correct |
|---|---|
| count (42) | 27 (64%) |
| area (6) | 6 (100%) |
| volume (1) | 1 |
| length (15) | 2 (13%) |

By kind: slab count/area/volume total 12 of 16 right (area by thickness/type 6/6, plain slab counts 4/4; counts filtered by thickness or type 1/5); multi-storey 20/20 (storeys up to 12, per-floor counts); MEP 4/14; rebar 0/6; baseboard 0/8.

## Top failure patterns
1. Filter ignored on counts: "how many slabs 300 mm thick" returns the area (4844.8, gold 3); type-filtered counts return the area or the whole class (WK200: 146 vs 48; screed 971.05 vs 52). Area-by-filter is right, count-by-filter is not.
2. No rebar element kind: every IfcReinforcingBar question returns 0 (count, length, by size) with an answer rather than an abstention. Confident wrong zero.
3. No baseboard / room-perimeter solver: returns total wall length (323.7 for every room) or a generic length. 0/8.
4. MEP family confusion: ducts of different families collapse to one total (all three duct families return 1509 segments / 2462.55 m; gold 658/642/209 and per-family lengths). Fittings 765 vs 358, valves 8 vs 14, terminals 555 vs 440, terminals 0 vs 105 on duplex_mep (IFC2x3 generic IfcFlowSegment/Revit names not mapped to pipe/duct).
5. Pipe length (Revit Length pset) was only correct for duplex_mep total pipe length.

## Caveats
Small n per kind. Gold for baseboard and the MEP length uses our definitions. Slab area uses GrossArea. viktor files unlicensed.
