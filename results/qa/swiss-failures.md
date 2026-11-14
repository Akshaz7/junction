# Swiss DXF failures — E-39

Source: `results/bench/e-s200-z2.rows.jsonl`, Swiss rows only. Gold values below are copied from saved results, not used in the reader or solver.

| Question type / kind | Total | Wrong |
|---|---:|---:|
| count / bathtubs | 4 | 4 |
| area / apartments | 5 | 3 |
| count / labelled rooms | 18 | 3 |
| count / toilets | 3 | 3 |
| count / washbasins | 2 | 2 |
| area / labelled rooms | 1 | 1 |
| count / apartments | 4 | 1 |
| count / showers | 1 | 1 |
| area / rooms | 12 | 0 |
| count / doors | 4 | 0 |
| count / windows | 3 | 0 |

18 wrong of 57 rows. Fixture counts share one reader path (10 failures); room-label counts are the next shared path (tied with apartment areas). Individually, bathtubs rank first; toilets tie labelled rooms and apartment areas next.

## Examples (up to two per failing class)

### count / bathtubs

- `swiss_dwellings__site285-bldg527-floor51568` — How many bathtubs are drawn on this floor plan? Gold: **4**; ours: **0**.
- `swiss_dwellings__site604-bldg1319-floor5779` — How many bathtubs are drawn on this floor plan? Gold: **1**; ours: **0**.

### area / apartments

- `swiss_dwellings__site1098-bldg2234-floor10334` — What is the net floor area of apartment C in m², summing all its rooms except balconies, loggias, terraces and other outdoor spaces? Gold: **63.67**; ours: **70.14**.
- `swiss_dwellings__site11692-bldg18240-floor48820` — What is the net floor area of apartment A in m², summing all its rooms except balconies, loggias, terraces and other outdoor spaces? Gold: **113.98**; ours: **108.0**.

### count / labelled rooms

- `swiss_dwellings__site1000-bldg2082-floor9385` — How many rooms labelled 'Zimmer' are there on this floor? Gold: **12**; ours: **9**.
- `swiss_dwellings__site248-bldg456-floor1800` — How many rooms labelled 'Wohnen' are there on this floor? Gold: **3**; ours: **1**.

### count / toilets

- `swiss_dwellings__site1040-bldg2136-floor9659` — How many toilets (WC) are drawn on this floor plan? Gold: **4**; ours: **0**.
- `swiss_dwellings__site303-bldg598-floor2434` — How many toilets (WC) are drawn on this floor plan? Gold: **3**; ours: **0**.

### count / washbasins

- `swiss_dwellings__site1138-bldg2292-floor10584` — How many washbasins are drawn on this floor plan? Gold: **17**; ours: **0**.
- `swiss_dwellings__site289-bldg536-floor2149` — How many washbasins are drawn on this floor plan? Gold: **8**; ours: **0**.

### area / labelled rooms

- `swiss_dwellings__site248-bldg456-floor1800` — What is the total net area in m² of all rooms labelled 'Zimmer' on this floor? Gold: **89.16**; ours: **73.17**.
- Only one wrong example exists in this class.

### count / apartments

- `swiss_dwellings__site1101-bldg2241-floor10275` — How many apartments (residential units) are shown on this floor plan? Gold: **1**; ours: **2**.
- Only one wrong example exists in this class.

### count / showers

- `swiss_dwellings__site3764-bldg5789-floor24598` — How many showers are drawn on this floor plan? Gold: **3**; ours: **0**.
- Only one wrong example exists in this class.

## Every wrong row

| Document | Question | Gold | Ours |
|---|---|---:|---:|
| swiss_dwellings__site1000-bldg2082-floor9385 | How many rooms labelled 'Zimmer' are there on this floor? | 12 | 9 |
| swiss_dwellings__site1040-bldg2136-floor9659 | How many toilets (WC) are drawn on this floor plan? | 4 | 0 |
| swiss_dwellings__site1098-bldg2234-floor10334 | What is the net floor area of apartment C in m², summing all its rooms except balconies, loggias, terraces and other outdoor spaces? | 63.67 | 70.14 |
| swiss_dwellings__site1101-bldg2241-floor10275 | How many apartments (residential units) are shown on this floor plan? | 1 | 2 |
| swiss_dwellings__site1138-bldg2292-floor10584 | How many washbasins are drawn on this floor plan? | 17 | 0 |
| swiss_dwellings__site11692-bldg18240-floor48820 | What is the net floor area of apartment A in m², summing all its rooms except balconies, loggias, terraces and other outdoor spaces? | 113.98 | 108.0 |
| swiss_dwellings__site248-bldg456-floor1800 | What is the total net area in m² of all rooms labelled 'Zimmer' on this floor? | 89.16 | 73.17 |
| swiss_dwellings__site248-bldg456-floor1800 | How many rooms labelled 'Wohnen' are there on this floor? | 3 | 1 |
| swiss_dwellings__site285-bldg527-floor51568 | How many bathtubs are drawn on this floor plan? | 4 | 0 |
| swiss_dwellings__site289-bldg536-floor2149 | How many washbasins are drawn on this floor plan? | 8 | 0 |
| swiss_dwellings__site303-bldg598-floor2434 | How many toilets (WC) are drawn on this floor plan? | 3 | 0 |
| swiss_dwellings__site3764-bldg5789-floor24598 | How many showers are drawn on this floor plan? | 3 | 0 |
| swiss_dwellings__site383-bldg846-floor3730 | How many rooms labelled 'Schlafzimmer' are there on this floor? | 5 | 4 |
| swiss_dwellings__site604-bldg1319-floor5779 | How many bathtubs are drawn on this floor plan? | 1 | 0 |
| swiss_dwellings__site629-bldg1355-floor5906 | How many bathtubs are drawn on this floor plan? | 2 | 0 |
| swiss_dwellings__site644-bldg1390-floor6077 | How many toilets (WC) are drawn on this floor plan? | 5 | 0 |
| swiss_dwellings__site926-bldg1958-floor8576 | How many bathtubs are drawn on this floor plan? | 2 | 0 |
| swiss_dwellings__site4237-bldg7396-floor29509 | What is the net floor area of apartment A in m², summing all its rooms except balconies, loggias, terraces and other outdoor spaces? | 85.75 | 88.0 |

## Code causes and scope

- Fixtures: the old reader only kept closed FIXTURE polylines, discarded curves/blocks, and assigned every retained symbol kind=other. It discarded explicit layer/block types too. The solver then reported zero for unknown fixture types. Named symbols now retain their type; one INSERT counts once. Anonymous geometry stays unknown and the code solver abstains.
- Rooms: the old reader used align_point whenever present, even for left/baseline TEXT; polygon attribution excluded boundary labels and took the first containing outline. TEXT placement, MTEXT, boundary coverage and nested outlines now have generated regressions. Explicit ROOM_TEXT counts also survive labels outside polygons; evidence cites the source labels.
- All Swiss sample documents are held out; no Swiss drawings or plan maps were inspected to choose fixes. Only saved bench rows, source code and generated-for-demo DXFs were used in development. The frozen reader/solver is then evaluated once on the held-out rows. No room areas, fixture sizes, colour mappings, or document-specific overrides were fitted to gold.
- Apartment membership/areas and untyped fixture classification remain data gaps. The general app's reader/forced-answer policies are outside this code-only evaluation.

## Frozen evaluation result

Source: `swiss-before-after.json`; detailed rows: `swiss-before.rows.jsonl` and `swiss-after.rows.jsonl`.

| Code solver | Correct | Wrong | Abstained | Accuracy (all rows) |
|---|---:|---:|---:|---:|
| before | 39/57 | 16 | 2 | 68.42% |
| after | 42/57 | 3 | 12 | 73.68% |

Evaluation cost: $0.00. No conversion errors. Three room-label counts became correct; ten unsupported fixture zeros became abstentions. Abstentions count as incorrect. The archived model-backed run was 39/57 (68.42%); it is not the paired code-only baseline. Production artifacts were not modified.
