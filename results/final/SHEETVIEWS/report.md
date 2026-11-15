F-SHEETVIEWS: PARTIAL — 15 Nov 2026

Implemented: spatial printed-scale parsing, fresh OCR even when VLM room labels exist, multilingual view titles, conservative frame/gutter boundaries, model view boxes with tight scale-label evidence, per-view plan counts/citations, evidence-card scope, and a Views overlay. Unresolved, overlapping and non-plan detections are excluded; no-plan sheets withhold quantities. Missing DPI/paper size is stated instead of inferring physical measurements from a printed ratio alone.

Validation: 176 Python tests; 3 web tests; TypeScript passed. sample200 with MODELS_FAKE=1 and isolated artifact copies: 137 correct / 49 wrong / 1 abstention / 13 unscored / 0 errors both before and after. All 200 numeric values, outcomes, routes and box counts match; two answers add view-scope text. No shared artifacts were rewritten.

17 source files inspected, including 11 mixed plan/non-plan sheets (the Finna target plus ten others), and six controls across Finna, HABS, Wikimedia and Europeana. Fresh local OCR ran on every source. The full identifiers, raw responses, boxes, local scales, 51 solver checks and visual observations are in report.json, manual_checks.json and the per-document JSON files.

Counts below are doors/windows/rooms. Stored detections compare the SAME old boxes before and after the spatial mask at confidence >= 0.5; they are not gold counts. New solver counts include a fresh model read and normal overlap filtering, so differences are not solely caused by view masking. Unavailable means no identifiable floor plan, not zero elements.

| Source (identifier suffix) | Stored detections | Same detections scoped | New solver | Printed ratio labels read |
|---|---:|---:|---:|---|
| europeana …45jan3cg5djqhqpodm | unavailable | unavailable | 0/40/23 | no numeric ratio read |
| finna__hka-139877668752900-168422869617700 | 0/0/15 | 0/0/7 | 26/22/22 | 1:100; 1:100.; 1:200. |
| finna__hka-139878174949000-145250688788000 | 0/2/3 | 0/0/1 | 7/5/7 | no numeric ratio read |
| finna__hka-139878174949000-150366720269000 | 0/1/8 | 0/0/5 | 7/1/10 | 1 : 5 0 |
| finna__hka-139879309684900-154961504220600 | 0/1/4 | 0/0/1 | 8/5/11 | no numeric ratio read |
| finna__hka-139879309684900-154962122901100 | 0/1/10 | 0/0/5 | 3/3/3 | no numeric ratio read |
| finna__hka-139879309684900-154962222514200 | 0/0/5 | 0/0/0 | 1/2/1 | SK 1:100; SK 1:66 2/3 |
| finna__hka-139879309684900-155058531210000 | 0/0/5 | 0/0/2 | 5/6/14 | no numeric ratio read |
| finna__hka-139879309684900-155058737003700 | 0/0/9 | 0/0/4 | 9/6/8 | no numeric ratio read |
| finna__hka-139879309684900-161226144595300 | 0/1/5 | 0/0/1 | 5/3/7 | no numeric ratio read |
| finna__hka-139880068219800-169332104793400 | 0/0/6 | 0/0/2 | 4/2/4 | 1:100, 1:20; 1:500 |
| habs__az0258-sheet-00018 | 0/0/5 | 0/0/0 | —/—/— | SCALE 1/2" = 1'-0"; 1/2" = 1' - 0"; 1 : 24 |
| habs__de0117-sheet-00005 | 0/0/13 | 0/0/0 | —/—/— | no numeric ratio read |
| habs__ia0042-sheet-00004 | 0/3/11 | 0/0/0 | —/—/— | SCALE 1/2" = 1'-0"; SCALE 1/2" = 1'-0"; 1/4" = 1'-0"; 1/4" = 1'-0"; 1/2" = 1'-0"; 1/4" = 1'-0" |
| habs__mt0124-sheet-00002 | 6/16/9 | 6/16/8 | 6/32/8 | SCALE: 3/16"=1'-0"; SCALE: 1/16"=1'-0" |
| wikimedia__23288749 | 0/1/6 | 0/1/6 | 0/0/26 | no numeric ratio read |
| wikimedia__24018750 | 0/3/4 | 0/3/0 | 0/6/6 | à 0.05 p. mètre.; à 0.05 p. mètre. |

Visual quantity checks: 6 of 8 checkable kind totals matched across four simpler plans. The two failures are windows: Finna …154962122901100 reads 3 versus 5 visually identified; …154962222514200 reads 2 versus 3. Other historic plans have ambiguous revisions, incomplete door notation, stalls or vaulted circulation bays; exact gold totals were not invented. View isolation does not fix missed or misclassified symbols inside a plan.

Printed-scale limits: the target’s 1:100 and 1:200 labels are retained with boxes; HABS …mt0124 has independently verified 1:64 and 1:192 views. Shared labels and alternative scales without a clear local owner remain unassigned. OCR still misreads the handwritten 66 2/3 denominator as 6693 on one scan; the map does not use that uncalibrated reading for a physical quantity. Several sources have graphic bars rather than numeric ratios; those are distinguished in the visual observations.

Random unseen checks: initial reserve habs__az0258-sheet-00018 was chosen before implementation and tested after the first freeze: section scale 1:24 recovered, all three plan quantity questions withheld rather than using five old room detections. A second Europeana file was randomly reserved before the final general Finnish title correction, inspected only after final code freeze, and correctly identified as one plan without a printed scale. Its automatic counts remain uncertified; no changes were made from that source. Both selections are recorded in selection.json.

Successful model-call records total $0.572554; one schema-rejected response returned no cost record, so this is not claimed as a complete invoice total. No further live calls. The schema now permits an absent scale/title rather than rejecting a valid unlabelled view.

Integration: merge this branch and redeploy the API/web. The production Dockerfile now installs the same rapidocr-onnxruntime dependency already present locally; no Docker build was run. Existing uploaded scan sidecars need re-ingestion to persist new regions for the viewer; shared artifacts were deliberately not changed.

NEEDS-AWAIS: optional PDF hook pipeline.sheet_views.annotate_views(pm, words, image=None, dpi=None, frames=None, views=None) -> independent plan-map dict. Supply rendered-pixel words ({text,bbox_px}), image, current render DPI and optional pixel-space frames/view boxes; persist the returned regions/items. PDF ingest and pipeline/pdf_planmap.py were not edited. The common VLM reader carries view metadata for any image it already processes.

Reproduce (from the worktree): MODELS_FAKE=1 scripts/heavy.sh /Users/akshatthapa/Workspace/junction/.venv/bin/python results/final/SHEETVIEWS/check_sample200.py after; scripts/heavy.sh /Users/akshatthapa/Workspace/junction/.venv/bin/python results/final/SHEETVIEWS/evaluate_ocr.py; /Users/akshatthapa/Workspace/junction/.venv/bin/python results/final/SHEETVIEWS/summarize.py. evaluate_real.py makes paid calls and was used only within this row’s budget.
