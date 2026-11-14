# Hologram live demo — X-16

“We rebuilt Stoa's product in two days. Then we built the part that does not exist yet.”

Ash uses the laptop and native iPhone app with **AC20** (`ifc_bench__ac20-arc`) in the same chat. Times below are editorial budgets, not measured response times. Read the actual answer; do not memorise an unverified door count. This is the intended sequence, not a completed physical-device rehearsal. Keep [judge answers](JUDGE_QA.md) beside the laptop.

## Before judges arrive

- Laptop: open [Hologram → Data](https://hologram-khaki.vercel.app/#/data). Check **Connected workspace** and [API health](https://obviously-present-piglet.eur-1.aiven.app/api/health). Use the same web/API workspace in the native app ([iPhone setup](../ios/README.md)). Grant camera, microphone and speech permissions; use a charged, unlocked phone and a textured, well-lit table.
- Run the reset below before creating the presentation chat. Laptop **Data → Search documents → AC20 → Ask about it**; confirm the AC20 chip. Phone **History → same chat**; enable **Follow other devices** where available. Save the exact `#/chat?chat=<chat_id>` route. Keep laptop chat open during AR.
- Rehearse the exact primary questions below. Confirm ground floor resolves to **Erdgeschoss**, doors are inspectable, **Visualise it → Build step** works both ways, a fresh turn reaches the phone, and **Show on table** preserves the scene/chat. Check plan-to-building reveal, voice spin/sequential highlighting, sourced violation card and laptop return.
- AC20's exact ground-floor door question and numbered-box path still need rehearsal. A related recorded IFC count has [0 response boxes](../results/qa/judge_run-r4.json#/0/n_boxes); the web can resolve scene IDs to drawing regions ([viewer notes](../web/src/viewer3d/README.md)). Do not call an element-only citation numbered-box proof. If boxes are absent, use the explicit raster fallback below.
- Download the recorded demo and physical-iPhone clip locally. **Pending:** local video path/share URL, installed build, rehearsal time and chat route. A recording is usable only after it exists and plays offline. Caption playback **Recorded on iPhone** or **Recorded demo**, naming any different drawing.
- Prepare offline AR with `AR_DEMO=1 bash ios/scripts/install_on_device.sh`; restore the primary build with `AR_DEMO=0 bash ios/scripts/install_on_device.sh`. The installer uses the heavy-job wrapper. The demo build opens bundled AC20; it proves local placement, not shared-chat delivery or online voice/advisor processing.

Network fallback: use the LEAD's stable LAN preview at `http://<Mac-LAN-IP>:4173` and API at `http://<Mac-LAN-IP>:8000` on both devices ([network setup](../ios/README.md)). Phone cannot reach the Mac through `localhost`. Reopen the same LAN chat; a different backend has separate history.

## Minute-by-minute live take

| Time budget | Exact action and spoken line | If this step fails |
| --- | --- | --- |
| 0:00–0:30 | **Laptop:** Data → AC20 → **Ask about it**. Show title/chip and say the opening pitch. “We read the drawing into reusable structured evidence.” | “The live source is unavailable; this is our recorded AC20 take.” Play the downloaded recording. If no recording is ready, show the available source and state the missing step. |
| 0:30–1:10 | Send **“How many doors are on the ground floor?”** Confirm **Erdgeschoss**. Open citation → **Fit drawing** → inspect **numbered boxes in 2D**, then **Sources**. “Here are the items behind that count.” Read the returned value. | Expose a wrong answer/scope. If AC20 provides only element evidence: “This cites model elements; here is the separate raster example of numbered boxes.” Use C01 below, then explicitly return to AC20 and its chat. API/viewer failure: labelled recorded proof. |
| 1:10–1:50 | **Visualise it**: watch the plan build into the model. Under the viewer use **Pause build-up**, drag **Build step** backwards and forwards, then **Play build-up** or **Replay build-up**. Orbit highlighted doors; expose ground floor using storey/cutaway controls. “The evidence keeps its identity as the building rises.” | “The animation is unavailable on this build; these are the current model highlights.” Use loaded static scene or labelled recording. Reduced motion can show the completed model immediately; slider remains available ([controls](../web/src/viewer3d/BuildSlider.tsx)). |
| 1:50–2:15 | **Phone:** show the fresh laptop question and answer arriving in the **same chat live**, with laptop still in frame. “This is the same conversation on the phone.” | Open **History → same chat** manually. “Reload recovered saved history; live delivery failed.” Use recorded dual-screen clip for live-sync behavior if available. |
| 2:15–3:00 | Phone citation → drawing → **Show on table** → scan table → **Place model**. Hold steady as the **AR plan appears and building rises**; inspect matching highlighted doors. “Now the drawing becomes a building on the table.” | Missing button: confirm native app and scene. Placement: textured surface/**Reset placement**. Network/model load: offline **AR_DEMO**, saying “This is bundled AC20, outside the shared chat.” Otherwise physical-iPhone recording. If reveal fails, show actual placement without claiming build-up. |
| 3:00–3:35 | Native AR **Ask by voice** → **“show me the doors”** → **Send voice question**. Show transcript; hold for **spin and sequential highlight**. “I can ask while looking at the building.” | Check microphone/speech permission; retry once. If recognition fails, close AR, type exact command in same phone chat and reopen **Show on table**. If choreography fails, show actual highlights or recorded animation; state the fallback. |
| 3:35–4:25 | Voice **“remove the front door, is it still compliant?”** → **Send voice question**. Show detected entrance disappearing; open **violation card**, affected item and source **`848/2017 §33`**. “This edit triggers the exit check. The card shows the rule it used.” | Type command in same chat if voice fails. If no sourced card: “The advisor did not return a sourced card”; show [recorded edit response](../results/qa/judge_run-r4.json#/13/got) or recorded card, distinguishing response text from card UI. Do not fabricate a violation or claim full compliance certification. |
| 4:25–5:00 | **Back on laptop:** show **both AR voice turns and answers** in original chat, including edit/card; inspect matching scene state. “The questions I asked in AR are now here, with their evidence.” Close: “One question, visible proof, carried from drawing to model to table.” | If AR created **Voice in AR**, open incoming-chat banner/**History**, naming the separate thread. Refresh proves persistence only. If disconnected, use recorded return segment and state live delivery failed. |

Preserve `chat_id` through **Show on table**; independent AR entry can create **Voice in AR**. Answer numbers and scene tags such as `D34` have different purposes. Hiding a door changes the chat edit layer; the source file stays intact.

The [recorded front-door response](../results/qa/judge_run-r4.json#/13/got) supports the intended story; it does not verify the exact spoken phrase, current card rendering or physical AR. The [rule entry](../engine/rules/fire_escape.yaml) has applicability exceptions. Say “a violation under the available model check”. Physical rehearsal and live card delivery remain pending.

## Reset before the next take

Run from repository root against the intended API origin, separately from live e2e/stress traffic:

```sh
python3 scripts/demo_reset.py https://obviously-present-piglet.eur-1.aiven.app --dry-run
python3 scripts/demo_reset.py https://obviously-present-piglet.eur-1.aiven.app
```

The [reset helper](../scripts/demo_reset.py) reads the **Exact question** table below, removes automated chats whose titles start `smoke-`, `e2e-`, `test` or `Voice in AR`, warms questions/assets in a temporary chat, then deletes that temporary chat. Dry run lists actions without writes or asset fetches. Finish before judging; it can exceed the presentation slot. Do not run while demonstrating an AR-created chat you want to keep.

It preserves other chats and does **not** reset their edit layers. In the presentation chat send **“reset the model”**, confirm the front door is visible on both devices, close AR and reset placement. Alternatively create a fresh **AC20** chat and open its exact route on both devices. Restore normal install mode after AR_DEMO. Failure: keep the error, start a fresh chat manually and verify the scene; do not claim reset succeeded.

## Rehearsal and backup questions

Keep these column names: `scripts/demo_reset.py` parses them. Questions warm on their named documents. The primary sequence has no pinned expected door count until rehearsed. Recorded values are historical snapshots, not unseen-input accuracy claims.

| Candidate / document | Exact question | Recorded support / use |
| --- | --- | --- |
| Primary · `ifc_bench__ac20-arc` | How many doors are on the ground floor? | Rehearse exact phrase, Erdgeschoss scope and numbered-box behavior; read the live answer. |
| Primary · `ifc_bench__ac20-arc` | show me the doors | Rehearse exact voice phrase, transcript, spin and sequential highlight on installed phone. |
| Primary · `ifc_bench__ac20-arc` | remove the front door, is it still compliant? | Related phrasing has a [recorded response](../results/qa/judge_run-r4.json#/13/got). Confirm sourced violation card for `848/2017 §33`; reset afterwards. |
| Reset · `ifc_bench__ac20-arc` | reset the model | Restore chat edit layer after removal; verify visible source scene. |
| C13 · `ifc_bench__ac20-arc` | What is the narrowest door width used here? | Recorded [narrowest-door response](../results/demo_candidates.json#/candidates/12/answer_text), element citation. Alternative IFC question. |
| C23 · `ifc_bench__ac20-arc` | show only the doors | Recorded command targets [77 items](../results/demo_candidates.json#/candidates/22/scene_command_item_count). Command/artifact evidence, not physical AR rehearsal. |
| Reset · `ifc_bench__ac20-arc` | reset the model | Restore after isolation backup. |
| C01 · `cubicasa5k__high-quality-108` | How many windows are shown on this floor plan? | Recorded [7 windows](../results/demo_candidates.json#/candidates/0/answer_value) and [7 boxes](../results/demo_candidates.json#/candidates/0/evidence_box_count); explicit separate-document fallback for numbered proof. |
| C28 · `cubicasa5k__colorful-7513` | How many windows are shown on this floor plan? | Recorded [5 windows](../results/demo_candidates.json#/candidates/27/answer_value) and [5 boxes](../results/demo_candidates.json#/candidates/27/evidence_box_count); alternate raster proof. |

## If a judge brings a drawing

**Data → Upload → Choose file** (or drop into upload dialog); prefer PDF, image, DXF or IFC. Wait for **Ready to use**, open document → **Ask about it**, and check source chip. Accepted extension does not prove ingestion or scene availability. Keep incomplete/error status visible. [Upload results](../results/upload_live.json) are test-container evidence, not guaranteed production timings.

Use the judge's question and actual citations; retain scale/confidence qualifications. Show **Visualise it** and AR only if that upload has a usable scene. If processing is still running, explicitly switch to prepared AC20; never imply its answer came from their file. Prepared raster proof retains dataset credits/noncommercial terms. Generated sources must say **“generated for demo”**.

For accuracy/cost use linked snapshots in [JUDGE_QA.md](JUDGE_QA.md) and [REPORT.md](REPORT.md). This script establishes no universal accuracy, free voice, live-sync latency or fine-tuning gain.
