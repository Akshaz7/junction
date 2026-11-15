# External stress test (DATASETS) - pilot, 14-15 Nov 2026

Held-out: nothing here was used to train or tune. Pilot = 40 docs, 154 questions, live run, USD 2.56 total (routes: 92 planmap, 62 hybrid). Rows: results/external/pilot.live.rows.jsonl, summary: pilot.live.summary.json. Reproduce: scripts/external/{build_questions,ingest,run_pilot}.py.

## Accuracy (exact count; area within 10%)
| dataset | question | n | correct | acc |
|---|---|---|---|---|
| CVC-FP (real scanned, French/Spanish plans) | doors | 20 | 8 | 0.40 |
| | windows | 20 | 3 | 0.15 |
| | rooms | 20 | 1 | 0.05 |
| PID2Graph OPEN100 (real P&IDs) | valves | 12 | 5 | 0.42 |
| | instruments | 12 | 6 (1 abstained) | 0.50 |
| | tanks | 10 | 4 | 0.40 |
| | pumps | 4 | 3 | 0.75 |
| ResPlan (my synthetic raster render) | counts | 32 | 10 | 0.31 |
| | area (m2, scale-derived) | 24 | 4 (2 abstained) | 0.17 |
By type: count 0.37 overall (CVC-FP 12/60, P&ID 18/38, ResPlan 10/32); area 0.17.

## Validity caveats (read before quoting numbers)
- ResPlan rows are weak evidence: I rendered flat coloured polygons with no door arcs or window symbols, so 22/32 count answers are 0 (nothing to detect). That is a rendering artifact, not a fair test. Its area rows are fairer: engine under-estimates in 17/18 wrong cases by about 20-30% (door-prior scale of 8-21 px doors). GT scale: m/px = sqrt(area_m2/inner_px2); median door width over 300 plans 1.00 m (p10 0.88, p90 1.14), so GT scale is plausible but derived, hence the 10% tolerance.
- CVC-FP "rooms" gold counts every annotated enclosed space; definition ambiguity makes this row soft. Doors/windows are one polygon per leaf/opening.
- CVC-FP has no real-world scale, so no m2 or baseboard questions could be built from it.
- n is small (20 / 12 docs per cell); treat as direction, not a benchmark.

## Top failure patterns
1. Scanned plans: windows under-counted in 16/17 wrong cases (typically 20-50% missing, e.g. 14 -> 10, 11 -> 5, 6 -> 3). Detector trained on CubiCasa-style symbols misses hatched/thin French-style windows.
2. Scanned plans: door counts under-counted in 10/12 wrong cases (12 -> 9, 13 -> 6, 8 -> 4); swing arcs on A4/A3 scans of mixed quality.
3. Rooms: no consistent bias (8 over, 11 under, e.g. 5 -> 12, 14 -> 8); room segmentation on scans merges or splits rooms and our definition differs from annotators.
4. P&ID: valve count over-counted in 6/7 wrong cases (one 33 -> 52), instruments mostly +1..+4 but one 41 -> 21; tanks/vessels under-counted (7 -> 4, 2 -> 0). Counts look like symbol-detector noise, with no deduplication across line breaks and no vessel class.
5. Area: scale from door prior (confidence 0.3) biases rooms small; abstains correctly when it cannot find a room, but a rendered plan with only labels gets no scale.

## Not done / unverified
No scanned multi-floor sets, rebar/slab-thickness sets, or MEP IFC with known quantities were fetched. Candidates seen only in search results (not verified): WBDG Duplex/Clinic plumbing IFC, buildingSMART Sample-Test-Files (GitHub API redirected), Dataset-P&ID (500 synthetic, Paliwal 2021), Roboflow P&ID symbol sets (CC BY 4.0). ROBIN, RPLAN, Structured3D, ZInD, SESYD: no licence or download verified. No pipe length ground truth exists in PID2Graph (graph edges only, no metres).
