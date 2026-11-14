# Hologram judging demo — X-10

“We rebuilt Stoa's product in two days. Then we built the part that does not exist yet.”

Follow the judge's question first. Prepared questions below are backups selected from [recorded candidates](../results/demo_candidates.json), not a representative accuracy sample. This script specifies the intended live take; it does not certify physical-device rehearsal. Check build-up and spinning, sequential highlights on the installed build before promising those effects.

## Prepare the stage

- Laptop: open the [live app](https://hologram-khaki.vercel.app/#/data). Verify **Connected workspace** and [API health](https://obviously-present-piglet.eur-1.aiven.app/api/health). Aiven Runtime is the configured target ([rewrite](../web/vercel.json), latest [decisions](../DECISIONS.md)). The older [deployed check](../results/e2e/deployed-check.md) tested the Vercel API fallback; it does not prove today's WebSocket/AR behavior.
- Install and launch the normal iPhone app with matching deployed web/API URLs using [device instructions](../ios/README.md). Grant camera, microphone and speech permissions beforehand. **Show on table** needs the native app; Safari has no native bridge. Use a charged, unlocked phone and a well-lit, textured table.
- On both devices open **History** and enable **Follow other devices** where available. Create/open the demo chat, then open that exact chat on the phone. Match its `#/chat?chat=<chat_id>` route and document. Keep the laptop chat visible during AR.
- Prepare `cubicasa5k__high-quality-108`, backup `cubicasa5k__colorful-7513`, and `ifc_bench__ac20-arc` (search **AC20**). Check page, scene, matching labels and USDZ load. Reset prior hide/isolate edits. Preserve source credits; CubiCasa5K is CC BY-NC-SA, not an MIT asset.
- Rehearse a fresh laptop turn arriving on the phone, table placement, the 2D-plan build-up, voice door spin/sequential highlights, and that voice turn returning to the same laptop chat. `[PENDING: installed build, rehearsal time, chat_id and physical-device recording]`. Use Plan B for any failed gate.
- Download the two-minute video and physical-iPhone clip onto the laptop: `[PENDING: local video paths and share URLs]`. Caption playback **Recorded on iPhone**. Keep the backup question table open.
- Prepare offline AR_DEMO before judging if needed: `AR_DEMO=1 bash ios/scripts/install_on_device.sh`. It opens bundled AC20 independently of the web chat. Restore the normal build for the primary take with `AR_DEMO=0 bash ios/scripts/install_on_device.sh`. The installer uses the heavy-job wrapper. Offline placement still needs a real iPhone; voice/API calls and chat sync need connectivity.

Network Plan B: use the LEAD's stable LAN preview at `http://<Mac-LAN-IP>:4173` and API at `http://<Mac-LAN-IP>:8000` on both devices ([network setup](../ios/README.md)). The phone cannot use Mac localhost. Reopen the same LAN chat after switching workspaces. Provider-dependent ingestion still needs connectivity.

## Exact click path and Plan B

The [brief](MASTER_PROMPT.md) weights four criteria equally: **A** accuracy, **V** visual verifiability, **C** creativity, **L** low inference cost. Every row maps its proof to those criteria.

| Step | Live action and narration | Plan B | Criteria / evidence |
| --- | --- | --- | --- |
| 1. Select | Laptop **Data → Upload → choose the judge's drawing**; follow the upload route below. Prepared take: **Data → Search documents → high_quality-108 → Ask about it**. Check the document chip. Say the opening pitch, then “Ask your question about this drawing.” | Explicitly switch to prepared high_quality-108, then colorful-7513 if needed. For API failure use the captioned recording. | A/V: actual source visible; C: judge selects input; L: reading happens during ingestion. |
| 2. Ask | Enter the judge's English question → **Send question**. Backup: “How many windows are shown on this floor plan?” Show **Thinking…**, document status, then the bold answer/citation. Say “Let's check the items behind that answer.” | Use a backup on its named document. If wrong or unsupported, expose the evidence and say so. A saved answer demonstrates history, not a live stream. | A: compare to source; V: citation; C: natural question; L: actual answer cost/trace. |
| 3. 2D proof | Inline citation → **Fit drawing** → select a numbered box. Open **Sources** and **Show thought process** if time permits. Say “Each number points to an item you can inspect.” C01 recorded 7 boxes; check today's output. | C28 recorded 5 window boxes. If viewer fails, show recorded proof and identify it as recorded. Never substitute prepared proof for the judge's drawing. | A/V: inspect counted items; C: linked evidence; L: trace identifies code/model work. |
| 4. 3D | In the drawing viewer click **Visualise it** → wait for model → orbit matching numbered highlights. Keep the cutaway open enough to see them. Say “The evidence keeps the same identity in 3D.” | Try C28's scene. If scene unavailable, keep 2D proof and name the separate document in the recorded 3D segment. | A/V: same IDs and labels; C: spatial view; L: reuse map/scene. |
| 5. Phone | Keep laptop chat open. In native phone app **History → same chat** (or exact saved route). Confirm the fresh question and answer arrived without retyping. Say “This is the same conversation on the phone.” | If Follow misses it, open manually. Reload can recover history, but is not live-delivery proof. For disconnection use the recorded dual-screen segment. | A: same document/turn; V: both screens in frame; C: shared workspace; L: reuse stored answer. |
| 6. Table AR | Phone citation → drawing → **Show on table** → scan table → **Place model**. Film 2D plan, then walls, doors and stairs rising where the model contains them. Verify answer items glow. Say “Now the drawing becomes a building on the table.” | Missing button: confirm native app and scene availability, then use physical-iPhone clip. Network failure: prepared offline AR_DEMO AC20, explicitly a separate bundled scene. Placement failure: textured surface or **Reset placement**, then clip. If reveal absent, show placement only and say the reveal is pending. | A: requested title/IDs; V: placement/highlights; C: plan-to-AR reveal; L: reuse USDZ. |
| 7. Voice | Native AR **Ask by voice** → say **“show me the doors”** → **Send voice question**. Hold steady for spin and sequential highlight entrance. Show transcript, answer and door tags. Say “I can ask while looking at the building.” | Retry once after permission check. If voice fails, close AR, type command in same phone chat, reopen **Show on table**. If animation absent, show actual highlights or captioned clip. Offline bundled selection does not prove voice processing. | A: transcript/targets; V: tags/highlights; C: spatial voice; L: show actual cost, never promise free voice. |
| 8. Laptop return | Show that spoken question and answer appearing in the same laptop chat, plus matching model selection. Say “The voice turn is now in the shared chat.” Close: “One question, visible proof, carried from drawing to model to table.” | If a separate chat was created, use incoming-question banner **Open**, or **History → Voice in AR**, and state the difference. Refresh proves persistence only. Failed live delivery: captioned recorded segment. | A/V: same transcript and answer on both screens; C: bidirectional continuation; L: reuse stored answer. |

Answer evidence uses numbers; scene commands can use tags such as D1/W3. Do not call a command tag a citation number. Native AR entered without the originating chat can create **Voice in AR**; retain `chat_id` through **Show on table** for the primary take.

## Upload your own drawing — priority judge-led route

Use the judge's original source and question, including complex questions. Do not promise a prepared answer, cost or response time for an unseen file.

| Stage | Exact action / check | Plan B | Criteria |
| --- | --- | --- | --- |
| Select | **Data → Upload → file picker**, or drop one file in Data. Prefer original PDF, PNG/JPG, DXF or IFC. UI also accepts SVG, TIFF and DWG; accepted extension alone does not prove processing support. Observe displayed size limit. | Use an available PDF/image export for unsupported or stored-only formats; otherwise explicitly switch to a prepared source. Never fabricate a conversion. | A/V: original inspectable input; C: unseen drawing; L: one ingestion. |
| Ingest | **Uploading… → Processing document… → Ready to use**, checking stages under **Uploads**. Open the resulting document. Partial/stored/failed status is not full readiness. | Explain unavailable stages; use a supported export or prepared example. Retain the error; show an ingestion recording if available. Explain the plan map while waiting. | A: explicit readiness; V: preview; C: live ingestion; L: separate extraction cost. |
| Ask | Uploaded document → **Ask about it** → check chip → judge's question. For cross-document questions attach every intended source before sending and inspect each citation. | Narrow question/scope openly if unsupported. Say when evidence does not hold the answer; retain uncertainty in best-effort responses. Backups apply only to their named documents. | A: source scope/limits; V: cited sources; C: judge's question; L: actual trace/cost. |
| Continue | Citation → **Fit drawing → Visualise it**, then steps 5–8 with this upload's chat/scene. Check scene and USDZ availability before promising AR. | Page-only upload supports 2D proof. Name any separate prepared scene or recording used for 3D/AR. | A/V: same IDs, no silent substitution; C: unseen plan into AR when available; L: reuse artifacts. |

[Upload results](../results/upload_live.json) record test-container ingestion and follow-up answers, not guaranteed production timings or unseen-input accuracy. Keep scale uncertainty visible when dimensions come from a door-width prior.

## Two-minute version / video shot list

These are editorial budgets, not measured timings. Start with selected prepared drawing and both devices in the same chat; record fresh turns. Trim optional narration if waiting exceeds its slot; caption edited waits.

| Time | Shot / action | Line and criteria |
| --- | --- | --- |
| 0:00–0:12 | Laptop and phone, source visible. | Exact opening pitch. A/V/C/L: inspectable evidence reused across views. |
| 0:12–0:32 | Judge asks or send C01; status, bold answer, cost. | “Let's check the items behind that answer.” A/V/C/L. |
| 0:32–0:48 | Citation → **Fit drawing**, numbered boxes. | “Each number points to an item you can inspect.” A/V. |
| 0:48–1:03 | **Visualise it**, orbit same highlights. | “The evidence keeps the same identity in 3D.” A/V/C/L. |
| 1:03–1:15 | Phone receives fresh turn; laptop stays in shot. | “This is the same conversation on the phone.” A/V/C/L. |
| 1:15–1:35 | **Show on table → Place model**, plan/build-up. | “Now the drawing becomes a building on the table.” A/V/C/L; only rehearsed effects. |
| 1:35–1:51 | Voice “show me the doors”, send, hold for spin/highlights. | Show transcript and targets. A/V/C; actual voice cost for L. |
| 1:51–2:00 | Laptop returned voice turn; app/source end card. | “One question, visible proof, carried from drawing to model to table.” A/V/C/L. |

If a judge brings a file during this slot, start upload immediately. If it is not ready, state that and use the named prepared example; never imply its answer came from their file.

## Five-minute version

| Time | Action | Criteria / recovery |
| --- | --- | --- |
| 0:00–0:35 | Pitch; **Data → Upload**, judge's file and progress. | A/V/C/L: original unseen source and reading stage; upload Plan B. |
| 0:35–1:20 | Readiness → **Ask about it**, judge's question; source chips and limits. | A/V/C/L: scope, route and cost; name prepared example if processing continues. |
| 1:20–2:00 | Citation → **Fit drawing**, boxes/**Sources** → **Visualise it**. | A/V/C/L: same IDs and reused scene; steps 3–4 Plan B. |
| 2:00–2:25 | Same fresh chat turn on phone. | A/V/C/L: both screens and reused answer; step 5 Plan B. |
| 2:25–3:05 | **Show on table → Place model**, 2D-plan build-up. | A/V/C/L: same scene and highlights; step 6 Plan B. |
| 3:05–3:40 | Voice doors, spin/sequential highlights, laptop return. | A/V/C/L: transcript, targets, persistence; steps 7–8 Plan B. |
| 3:40–4:25 | Optional **Data → AC20 → Ask about it**, C13 narrowest door → citation → **Visualise it**. Spend this slot completing upload proof if needed. | A/V/C/L: IFC property/element, code route; C13 recording if unavailable. |
| 4:25–5:00 | **Accuracy** or recorded report; distinguish numeric/text scores and ingestion/answer cost. Closing line. | A/V/C/L: measured limits and cost; use linked report if dashboard unavailable. |

Optional longer IFC take: C16 “Where is the fire exit on level 2?” → citation → **Visualise it → Storey → 2. Obergeschoss**. Its recorded stair result explicitly says it is an inference, **not a marked fire exit**. Retain that qualification; it is not verified egress advice. **Walk at 1:1** is an optional physical-device-rehearsed extension outside the timed core.

## Backup questions and measured claims

Expected values below come from [demo_candidates.json](../results/demo_candidates.json). Re-ask on the installed build before judging; artifacts/behavior may have changed.

| Candidate / document | Exact question | Recorded result / limits |
| --- | --- | --- |
| C01 · `cubicasa5k__high-quality-108` | How many windows are shown on this floor plan? | 7 windows, 7 boxes, matching scene IDs; answer model cost $0. |
| C28 · `cubicasa5k__colorful-7513` | How many windows are shown on this floor plan? | 5 windows, 5 boxes, matching scene IDs; answer model cost $0. |
| C13 · `ifc_bench__ac20-arc` | What is the narrowest door width used here? | 1 m, Tür-014; IFC element citation, not raster boxes. |
| C23 · `ifc_bench__ac20-arc` | show only the doors | Isolates 77 doors; command/artifact check, not physical AR proof. |
| C19/C20/C21 · `ifc_bench__ac20-arc` | show me all the windows → remove W3 → restore W3 | Highlight/hide/restore persisted per chat. Reset afterwards. |

“show me the doors” is the required voice phrase, without an exact-phrase physical-device result in this candidate capture; do not assign it C23's test status. Avoid colorful-11397's window count and toilet/sink 3D path: the capture reports a window gold mismatch and missing toilet/sink scene IDs.

[ACCURACY.md](ACCURACY.md) uses [sample200-r10](../results/bench/sample200-r10.json): **124/187 numeric correct (66.3%)**, including **16 numeric abstentions** as unsuccessful; **13 text questions** are reported separately. This is a recorded sample, not the final latest-engine score. The run records **$0 total model cost**, excluding prior map extraction and hosting; it does not promise free voice/uploads. A solver can be exact over a map that contains reading errors.

Pending claims: `[PENDING: final benchmark tag/accuracy]`, `[PENDING: matched fine-tuning comparison, if any]`, `[PENDING: current live-sync timing]`, `[PENDING: physical AR build-up/spin rehearsal]`, `[PENDING: judge-upload ingestion and answer spend]`. Quote no gain, universal zero-abstention result or latency without evidence. See [submission checklist](SUBMISSION.md).
