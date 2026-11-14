# Demo script: Hologram

Evidence: [candidate results](../results/demo_candidates.json), captured against the running local API on 2026-11-14. Tested 28 English candidates and 10 repeat questions, 38 questions total, sequentially with request pacing. All repeated answers matched their original text and values. This is a curated demo selection, not an accuracy estimate or a training result.

The raster path is gold-correct and has usable evidence. Scene files and API edits work. Browser animation, cross-device delivery and physical AR remain untested here. The fire-exit response is explicitly an inference. The sourced advisor card and web-to-native bridge remain pending.

## Before the recording

Use the LEAD-refreshed stable build at `http://localhost:4173/#/data`, with its API connected to `http://localhost:8000`. Require **Connected workspace**; a generated fallback answer is not evidence of a real API result. Do not record the working-tree dev build while another worker edits it. The iPhone must use reachable web/API addresses on the same workspace; its localhost is not the Mac.

Primary raster: **high_quality-108**, `cubicasa5k__high-quality-108`. Backup raster: **colorful-7513**, `cubicasa5k__colorful-7513`. The toilet/sink alternatives on colorful-11397 are suitable only for 2D; their evidence IDs are missing from the current scene. IFC building: **AC20**, `ifc_bench__ac20-arc`. Retain the drawing credit and licence footer; the raster drawings are CubiCasa5K evaluation data. No generated project documents are used in this selection. If the native fixture appears, retain **generated for demo** and do not present it as AC20.

A saved API rehearsal is available at `http://localhost:4173/#/chat?chat=312243d0-12fc-462a-80ff-4973def7aaa3` if the current build supports saved-chat links. Use fresh questions for the live take; a saved response does not demonstrate a live status stream.

## The eight steps

### 1. Open the workspace and select the drawing

Click **Data** → **Search documents**, type `high_quality-108` → open **high_quality-108** → **Ask about it**. Check that its document chip is selected in the composer. The exact question prepared for this step is C01: “How many windows are shown on this floor plan?” Submit it in the next step.

Backup: select **colorful-7513** through the same path and prepare C28: “How many windows are shown on this floor plan?”

Say: “Hologram brings drawing questions and their sources into a shared workspace.”

### 2. Ask the gold-correct raster count

In **Ask about your drawings**, paste C01: “How many windows are shown on this floor plan?” → **Send question**. Show **Thinking…** and **Exploring document: high_quality-108** if visible; the fast response may make these brief. Expected text: **There are 7 windows on this floor plan.** Citation follows the sentence. Original engine latency: 3 ms; answer cost: $0.0000. These are recorded engine measurements, not promised end-to-end timing.

Backup C28 on `cubicasa5k__colorful-7513`: “How many windows are shown on this floor plan?” → **5 windows**, 5 boxes, $0.0000, recorded engine latency 1 ms. This answer repeated identically. C02 is a further 2D-only alternative: **2 toilets** on colorful-11397. Do not use that drawing's window question: C08 disagrees with gold.

Say: “The count comes with the items that produced it.”

### 3. Check the numbered drawing evidence and cost

Keep the C01 answer; no new question is needed. Click its inline citation chip → **Fit drawing** → click a numbered box → **Next source** to inspect another. Expected: 7 numbered evidence boxes, all inside the page and all mapped to scene items. Show **Where it is set out**, **Sources**, **Show thought process**, and hover/focus the cost chip, displayed as `$0.0000`. The API trace records a plan-map route.

Backup: use C28, “How many windows are shown on this floor plan?”, on `cubicasa5k__colorful-7513`; open its citation to check the 5 window boxes. C02 and C03 remain gold-correct toilet/sink alternatives for 2D only.

Say: “Each numbered box lets you check the answer against the drawing.”

### 4. Raise the same plan into 3D

Keep the C01 question and drawing panel. Click **Visualise it** in the drawing viewer → wait for **3D view ready** → drag to orbit. Check that the same window item IDs carry their numbered labels and highlights. The scene manifest, GLB and USDZ all returned successfully; matching box-to-scene IDs were checked. The visible animation and highlights still need the LEAD's browser rehearsal.

Backup: ask C28, “How many windows are shown on this floor plan?”, on `cubicasa5k__colorful-7513` → citation → **Visualise it**. All 5 evidence items exist in its scene; the manifest, page image, GLB and USDZ were reachable. C02/C03 fixture evidence is absent from the current scenes and cannot demonstrate matching 3D highlights.

Say: “The same items carry through from drawing evidence into the model.”

### 5. Continue on the iPhone and show it on a table — pending bridge/device rehearsal

Chosen question remains C01: “How many windows are shown on this floor plan?” on `cubicasa5k__high-quality-108`. Open the same saved chat in the iPhone web shell; confirm the actual question and answer before filming. Once the answer's native bridge action is wired: citation/drawing → **Show on table** → scan a horizontal surface → place the model → verify the matching highlights. This bridge action is absent from the checked web source, so this sequence is pending, not a tested claim.

Concrete fallback: native toolbar **Show on table** → **Demo scenes** → **AC20 · IFC building**. This selects `ifc_bench__ac20-arc`; the toolbar initially opens a fixture, not the selected web document. Use backup C13, “What is the narrowest door width used here?”, on AC20. Its gold-correct door evidence exists in the scene. Rehearse live highlighting after opening AR. Without it, show only the scene placement and describe it as a separate native view, not synchronized proof. The selected raster plans are not in the native bundled picker and need the bridge/API path. Do not present a simulator capture as physical AR.

Say after a successful bridge rehearsal: “The same drawing evidence is now placed on the table.” If using the picker fallback: “This native view places the selected demo scene on the table.”

### 6. Locate an IFC stair with an explicit inference qualification

Desktop: **Data** → search `AC20` → **AC20** → **Ask about it** → send C16: “Where is the fire exit on level 2?” Expected: **No outer door on 2. Obergeschoss**; 1 stair to other levels (**Treppe-2-OG**). The answer continues: **This is an inference from the model data (outer doors and stairs), not a marked fire exit.** Preserve that sentence in the take. Its scene target is the stair item `0xQhptVzf44Qzhs9jMEILa`, corroborated in the IFC element file.

Citation → **Visualise it** → **Storey** → **2. Obergeschoss**. Verify camera focus on that target during browser rehearsal. On the physical iPhone choose **AC20 · IFC building**, move to the matching storey with **Higher storey**, and turn on **Walk** for life-size navigation. Camera flight, live target delivery and walking are pending device/browser checks; the API alone does not prove them.

Gold-correct backup C13 on the same IFC: “What is the narrowest door width used here?” → **1 m**, the named single-swing door, and 1 scene item. Open the citation → **Visualise it** to identify that element. C17 is an alternate ground-floor exit inference, with the same qualification; no tested candidate proves a marked fire exit.

Say: “The model points to this stair, while explicitly saying it has no marked fire-exit proof.”

### 7. Show measured accuracy and spend

The step's reference question is C01, “How many windows are shown on this floor plan?”; keep its recorded cost chip if returning to chat. Click **Accuracy** → **Run** → `sample200-r2` → **Accuracy by source and question type** → **Before / after fine-tuning** → **Model costs**. This named run is pinned so a newer in-progress result cannot silently change the narration.

From [sample200-r2](../results/bench/sample200-r2.json): 48 correct out of 187 scored questions, headline **25.7%**; 13 text questions are unscored. Abstentions count in the accuracy denominator. The run's total spend is **$0.000455**. The chosen raster answer cost $0.0000; do not generalize that to every answer or confuse the curated questions with this broader run.

There is no matched baseline/fine-tuned pair in the checked run list. Show **No fine-tuned run yet.** Do not narrate an improvement. Backup question C10 on `ifc_bench__ac20-arc`: “Which door types are installed in this building with quantities?” → the gold-matching door-type breakdown; if the dashboard cannot load, show its recorded answer and the linked results file with that limitation. Candidate C13 is another recorded IFC example.

Say: “The dashboard separates measured accuracy, abstentions, unscored text and model spend.”

### 8. Edit by stable tag; sourced advisor card remains pending

**Data** → search `AC20` → **AC20** → **Ask about it**. Keep an AC20 **Visualise it** view open in another desktop window, so the composer remains available. In the same chat send C19: “show me all the windows” → wait for window labels → send C20: “remove W3”. Expected API responses: **Highlighted 206 windows.** then **Window W3 is hidden. 205 of 206 windows remain visible.** The same-chat rehearsal persisted the W3 item as hidden. These commands are already supported by the tested API; they are not pending E-20.

Restore with C21: “restore W3” → **206 of 206 windows are visible.** Then C22: “reset” to clear the edit layer and highlights. Restoration clears hidden state; it does not automatically put W3 back into the highlighted set. Check visible removal, restoration and label delivery in the browser before recording them.

Backup C23 on AC20: “show only the doors” → **Showing only 77 doors.** The command contains the matching door items. Use “reset” to restore the view.

`POST /api/advise` after the W3 hide returned an empty cards list. **A sourced advisor card is pending.** Do not replace it with an invented card, remove a ramp with no tested rule, or claim the source model was changed. Once available, film a real card's source title and verbatim quote before describing it as advice.

Say: “A stable tag hides an item in the viewing layer; the original model stays intact.”

## Two-minute video shot list

Time ranges are an editorial plan, not measured performance. Pending shots may only be used after real rehearsal; use the stated alternative otherwise.

| Time | Shot and narration cue |
|---|---|
| 00:00–00:10 | Workspace → Data → selected high_quality-108, with credit visible. Introduce drawing questions with sources. |
| 00:10–00:30 | Send C01 live; capture the bold count, citation and cost. Do not stretch a fast status line into a false wait. |
| 00:30–00:45 | Citation → Fit drawing → numbered window boxes → source controls. |
| 00:45–01:00 | Visualise it; capture the real rise and matching highlights after browser rehearsal. |
| 01:00–01:15 | Real iPhone table placement only after device rehearsal; otherwise show the native picker separately or continue the desktop scene, with the limitation on screen. |
| 01:15–01:35 | AC20 C16 → stair focus; keep the inference qualification visible. Use C13 if focus is unavailable. Include life-size walking only if physically rehearsed. |
| 01:35–01:50 | Accuracy → pinned sample200-r2 → source/type table → spend; show that fine-tuned comparison is unavailable. |
| 01:50–02:00 | AC20 C19 → C20 and visible W3 hide after browser rehearsal. If no sourced card exists, finish on the real edit; label advisor pending. |

## Candidate selection ledger

Each step has candidate pairs below; repeated IDs deliberately reuse one tested pair to keep the drawing and evidence continuous. Dashboard candidates are reference-answer questions, since opening a dashboard does not itself ask a document question. Full texts, gold answers, events, costs, timings, evidence IDs and replay responses are in [demo_candidates.json](../results/demo_candidates.json).

| Step | Tested candidates | Chosen | Backup | Qualification |
|---|---|---|---|---|
| 1 | C01, C28, C02 | C01 | C28 | API verified; shell/click path read from UI source, not browser rehearsed |
| 2 | C01, C28, C02, C08, C09, C27 | C01 | C28 | API verified against numeric dataset gold |
| 3 | C01, C28, C02, C03, C05, C06 | C01 | C28 | Selected window boxes have scene membership and bounds verified; fixture alternatives are 2D only; browser display not rehearsed |
| 4 | C01, C28, C27, C13 | C01 | C28 | C01/C28 evidence IDs and scene assets verified; C27 rejected for incorrect count; rendered animation/highlights not rehearsed |
| 5 | C01, C28, C13 | C01 | C13 | Bridge/device pending; native bundled AC20 plus C13 is the separate fallback; fixture-count candidates cannot demonstrate scene highlighting |
| 6 | C16, C17, C18, C13 | C16 | C13 | Qualified model inference only; no marked-fire-exit gold; camera/AR navigation not rehearsed |
| 7 | C01, C10, C13 | C01 | C10 | Dashboard APIs verified; no fine-tuned comparison run available |
| 8 | C19, C20, C21, C22, C23 | C19 | C23 | Commands and persisted scene state verified; sourced advisor card pending (cards empty) |

Document aliases below are exact IDs: A = `cubicasa5k__high-quality-108`; B = `cubicasa5k__colorful-11397`; C = `cubicasa5k__colorful-11400`; D = `cubicasa5k__colorful-11960`; I = `ifc_bench__ac20-arc`; S = `swiss_dwellings__site1000-bldg2082-floor9385`; E = `cubicasa5k__colorful-6327`; F = `cubicasa5k__colorful-7513`.

| ID | Doc | Exact question | Correct? | Boxes / evidence items | Engine ms | USD |
|---|---|---|---|---|---|---|
| C01 | A | How many windows are shown on this floor plan? | Yes | 7 / 7 | 3 | 0.000000 |
| C02 | B | How many toilet bowls (WC seats) are drawn on this floor plan? | Yes | 2 / 2 | 0 | 0.000000 |
| C03 | B | How many sinks and wash basins (kitchen and bathroom combined; a double-bowl sink counts as one) are drawn on this floor plan? | Yes | 3 / 3 | 1 | 0.000000 |
| C04 | A | How many bedrooms (makuuhuone, usually marked MH) are on this floor plan? | No | 13 / 13 | 3 | 0.000000 |
| C05 | C | How many toilet bowls (WC seats) are drawn on this floor plan? | Yes | 2 / 2 | 3 | 0.000000 |
| C06 | C | How many sinks and wash basins (kitchen and bathroom combined; a double-bowl sink counts as one) are drawn on this floor plan? | Yes | 3 / 3 | 2 | 0.000000 |
| C07 | D | How many toilet bowls (WC seats) are drawn on this floor plan? | Yes | 1 / 1 | 1 | 0.000000 |
| C08 | B | How many windows are shown on this floor plan? | No | 11 / 11 | 1 | 0.000000 |
| C09 | A | How many sinks and wash basins (kitchen and bathroom combined; a double-bowl sink counts as one) are drawn on this floor plan? | No | 3 / 3 | 2 | 0.000000 |
| C10 | I | Which door types are installed in this building with quantities? | Yes | 0 / 77 | 7 | 0.000000 |
| C11 | I | Which window types are present in the building and how many of each? | Yes | 0 / 206 | 3110 | 0.001020 |
| C12 | I | Which room in the building is the largest? | No | 0 / 1 | 10 | 0.000000 |
| C13 | I | What is the narrowest door width used here? | Yes | 0 / 1 | 8 | 0.000000 |
| C14 | I | What are the heights of each level? | No | 0 / 0 | 2762 | 0.002148 |
| C15 | I | What software and ifc standards were used to create this model? | No | 0 / 0 | 4 | 0.000000 |
| C16 | I | Where is the fire exit on level 2? | Unverified inference | 0 / 1 | 10 | 0.000000 |
| C17 | I | Where is the fire exit on the ground floor? | Unverified inference | 0 / 2 | 10 | 0.000000 |
| C18 | I | Where are the exits on 1. Obergeschoss? | Unverified inference | 0 / 1 | 3 | 0.000000 |
| C19 | I | show me all the windows | Yes | 0 / 206 | 4 | 0.000000 |
| C20 | I | remove W3 | Yes | 0 / 1 | 6 | 0.000000 |
| C21 | I | restore W3 | Yes | 0 / 1 | 3 | 0.000000 |
| C22 | I | reset | Yes | 0 / 0 | 3 | 0.000000 |
| C23 | I | show only the doors | Yes | 0 / 77 | 9 | 0.000000 |
| C24 | S | How many rooms labelled 'Küche' are there on this floor? | Yes | 4 / 4 | 4 | 0.000000 |
| C25 | S | How many toilets (WC) are drawn on this floor plan? | No | 0 / 0 | 2 | 0.000000 |
| C26 | S | What is the net floor area of room 2.10 ('Zimmer') in m²? | No | 0 / 0 | 4 | 0.000000 |
| C27 | E | How many windows are shown on this floor plan? | No | 3 / 3 | 4 | 0.000000 |
| C28 | F | How many windows are shown on this floor plan? | Yes | 5 / 5 | 1 | 0.000000 |

Do not substitute C04 (bedroom scope answered as all rooms), C08/C09/C27 (wrong counts), C12 (room-function disagreement with gold), C14 (incomplete heights), C15 (metadata abstention), or C25/C26 (missing fixture/area data). C24 is a correct alternative labelled-room count on the Swiss PDF, but the raster path above provides clearer continuity into the tested scenes. C02/C03/C05/C06/C07 have correct 2D counts but lack matching fixture items in their current scenes.

## LEAD acceptance

Re-ask the chosen questions against the intended demo server and compare answer facts and evidence IDs with the JSON. Confirm the actual citation, rise, live edit and device views in the stable app. The repeat API questions already matched locally; WEB2 did not run the LEAD's final app/device acceptance. Pending features are explicitly marked above.
